"""Deterministic bounded scenarios with held-out complete action compositions.

Benchmark task families inspire these cases; all states and tool labels are ours.
The constructive reference policy is not a shortest-path oracle.
"""
from __future__ import annotations

import copy
import hashlib
import json
import random
from collections import Counter

from .world_model import MINING, Planner, SimulationError, execute, state_delta


NAMES = {'oak_log': '橡木原木', 'coal': '煤', 'cobblestone': '圆石', 'raw_iron': '粗铁',
         'oak_planks': '橡木木板', 'stick': '木棍', 'torch': '火把', 'crafting_table': '工作台',
         'furnace': '熔炉', 'wooden_pickaxe': '木镐', 'stone_pickaxe': '石镐', 'iron_pickaxe': '铁镐',
         'wooden_axe': '木斧', 'stone_axe': '石斧', 'iron_ingot': '铁锭', 'cooked_beef': '熟牛肉',
         'wooden_shovel': '木锹', 'stone_shovel': '石锹', 'iron_shovel': '铁锹',
         'iron_axe': '铁斧', 'iron_hoe': '铁锄'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def signature(calls):
    """Ignore counts, coordinates and container names, retain meaningful operations."""
    return json.dumps([[c['call']['name'], {k: v for k, v in c['call']['arguments'].items()
                       if k in {'item', 'input', 'resource', 'tool', 'fuel', 'slot'}}]
                      for c in calls], sort_keys=True, separators=(',', ':'))


def fingerprint(goal, state):
    # Coordinates, map IDs, language and irrelevant items cannot make a new scene.
    return digest({'goal': goal, 'inventory': state['inventory'],
                   'resources': {k: {'count': v['count'], 'reachable': v['reachable']}
                                 for k, v in state['resources'].items()},
                   'containers': state['containers'], 'capabilities': state['capabilities']})


def segments(sig):
    actions = json.loads(sig)
    return {json.dumps(actions[start:end], sort_keys=True, separators=(',', ':'))
            for start in range(len(actions)) for end in range(start + 1, len(actions) + 1)}


def instructions(goal):
    name, n = NAMES[goal['item']], goal['count']
    if goal['kind'] == 'craft_and_use':
        resource, uses = NAMES[goal['use_resource']], goal['use_count']
        return [f'制作{n}个{name}，再用新制作的{name}采集{uses}个{resource}。',
                f'请先做出{n}个{name}，并实际用它获取{uses}个{resource}。',
                f'我要{n}个新制作的{name}，随后用这件工具收集{uses}个{resource}。']
    verb = {'obtain': '新获取', 'craft': '新制作', 'smelt': '烧制'}[goal['kind']]
    return [f'请{verb}至少{n}个{name}。', f'帮我{verb}{n}个{name}，允许按配方批量多产出。',
            f'这次的目标是{verb}不少于{n}个{name}。']


def ancestors(item, catalog):
    seen = set()
    def visit(value):
        if value in seen:
            return
        seen.add(value)
        recipe = catalog['craft_recipes'].get(value)
        if recipe:
            for ingredient in recipe['inputs']:
                visit(ingredient)
        for input_item, r in catalog['smelt_recipes'].items():
            if r['output'] == value:
                visit(input_item)
                visit(r['fuel'])
        if value in MINING and MINING[value][1]:
            visit('stone_pickaxe' if MINING[value][1] == 2 else 'wooden_pickaxe')
    visit(item)
    return sorted(seen - {item})


def candidate(row, rng, config, catalog):
    item, category = row['target'], row['category']
    n = 1 if category in {'C', 'E'} else rng.randint(1, 16)
    goal = {'kind': {'A': 'obtain', 'B': 'craft', 'C': 'craft', 'D': 'smelt', 'E': 'craft_and_use'}[category],
            'item': item, 'count': n}
    if category == 'E':
        goal.update(use_resource=('oak_log' if item.endswith('_axe') else
                                 'raw_iron' if item == 'stone_pickaxe' else
                                 'coal' if item == 'iron_pickaxe' else 'cobblestone'), use_count=rng.randint(1, 3))
    map_id = rng.choice(config['map_template_order'])
    template = config['map_templates'][map_id]
    origin = template['origin']
    def pos(dx, dz):
        return [origin[0] + dx, origin[1], origin[2] + dz]
    patches = [(-12, -12), (12, -12), (-12, 12), (12, 12)]
    resources = {value: {'count': rng.randint(20, 64), 'reachable': True,
                         'position': pos(*patches[i])}
                 for i, value in enumerate(template['resources'])}
    if category == 'E' and goal['use_resource'] not in resources:
        return None
    pool = ancestors(item, catalog)
    # Intermediate inventory/source conditions, rather than language rewrites,
    # make scenes. All quantities fit small Minecraft inventories and patches.
    p = {'L0': 0.9, 'L1': 0.6, 'L2': 0.3}[row['difficulty']]
    inventory = {value: (1 if value.endswith(('_pickaxe', '_axe')) else rng.randint(1, 32))
                 for value in pool if rng.random() < p}
    for tool in ('wooden_pickaxe', 'stone_pickaxe'):
        if tool != item and rng.random() < p * .65:
            inventory[tool] = 1
    if category == 'A' and row['difficulty'] == 'L0' and MINING[item][1]:
        inventory['stone_pickaxe' if item == 'raw_iron' else 'wooden_pickaxe'] = 1
    if row['difficulty'] == 'L0':
        if item in catalog['craft_recipes']:
            r = catalog['craft_recipes'][item]
            batches = -(-n // r['output_count'])
            inventory.update({v: amount * batches + rng.randint(0, 4) for v, amount in r['inputs'].items()})
        if category == 'D':
            source = 'raw_beef' if item == 'cooked_beef' else 'raw_iron'
            inventory.update({source: n + rng.randint(0, 4), 'coal': -(-n // 8) + rng.randint(0, 2)})
    inventory.pop(item, None)
    # Known inspected chest; no unseen container contents are given to the model.
    box_pool = sorted(set(pool) | ({item} if category == 'A' else set()))
    if any(value in MINING and MINING[value][1] for value in [item, *pool]):
        box_pool = sorted(set(box_pool) | {'wooden_pickaxe', 'stone_pickaxe'})
    chest = {value: (1 if value.endswith(('_pickaxe', '_axe')) else rng.randint(16, 48))
             for value in box_pool if rng.random() < .5}
    inventory = {k: v for k, v in inventory.items() if k not in config['heldout_targets']}
    chest = {k: v for k, v in chest.items() if k not in config['heldout_targets']}
    state = {'inventory': inventory, 'position': list(origin), 'equipment': {},
             'boundary': {'origin': list(origin), 'radius': config['boundary_radius']},
             'resources': resources, 'containers': {'supply_chest': chest},
             'known_targets': {'supply_chest': {'type': 'container', 'position': pos(3, 1)},
                               'workbench': {'type': 'crafting_table', 'position': pos(1, 3)},
                               'furnace': {'type': 'furnace', 'position': pos(3, 3)}},
             'capabilities': {'crafting_table_available': True, 'furnace_available': True},
             'progress': {'crafted': {}, 'smelted': {}, 'used': {}}}
    preferences = {value: rng.random() < .5 for value in sorted(set(pool) | set(box_pool) | {item})}
    preferences['mining_tool'] = rng.choice(['wooden_pickaxe', 'stone_pickaxe'])
    try:
        calls = Planner(catalog).plan(state, goal, preferences)
    except SimulationError:
        return None
    low, high = config['difficulty_reference_steps'][row['difficulty']]
    if not low <= len(calls) <= high:
        return None
    return goal, state, calls, map_id


def generate(config, catalog):
    """Reserve composition tests first, then sample disjoint training and states."""
    rng = random.Random(config['seed'])
    tasks, seen, reserved, trained = [], set(), set(), set()
    # Reserve one normalized macro-plan per target/difficulty; retain alternative
    # plans for training. E L1 is always craft/equip/collect, so its combination
    # holdout is L2. Quotas in config already reflect this constraint.
    reserved_by_key = {}
    order = [r for r in config['quotas'] if r['test_partition'] == 'composition']
    order += [r for r in config['quotas'] if r['split'] == 'train']
    order += [r for r in config['quotas'] if r['split'] == 'valid']
    order += [r for r in config['quotas'] if r['test_partition'] == 'state']
    order += [r for r in config['quotas'] if r['test_partition'] == 'novel_target']
    attempts_by_row = []
    for row in order:
        produced, attempts = 0, 0
        key = (row['category'], row['target'], row['difficulty'])
        while produced < row['count']:
            attempts += 1
            if attempts > 150000:
                raise ValueError(f'Could not fill quota {row}; filled {produced}, reserved {len(reserved)}')
            result = candidate(row, rng, config, catalog)
            if result is None:
                continue
            goal, state, calls, map_id = result
            sig, fp = signature(calls), fingerprint(goal, state)
            if fp in seen:
                continue
            if row['test_partition'] == 'composition':
                # Hold out a material-source alternative, not a mandatory
                # suffix such as craft-pickaxe -> mine-coal: banning that
                # suffix would remove all longer mining lessons as well.
                if row['difficulty'] == 'L1' and row['category'] in {'A', 'B', 'C', 'D'}:
                    if len(calls) != 2 or calls[0]['call']['name'] != 'retrieve_items':
                        continue
                    if row['category'] == 'A':
                        expected = 'wooden_pickaxe' if row['target'] == 'coal' else 'stone_pickaxe'
                        if calls[0]['call']['arguments']['item'] != expected:
                            continue
                    if row['category'] == 'D':
                        expected = 'raw_beef' if row['target'] == 'cooked_beef' else 'raw_iron'
                        if calls[0]['call']['arguments']['item'] != expected:
                            continue
                    if row['category'] == 'C' and row['target'] == 'iron_pickaxe':
                        if calls[0]['call']['arguments']['item'] != 'stick':
                            continue
                if key in reserved_by_key and sig != reserved_by_key[key]:
                    continue
                reserved_by_key[key] = sig
                reserved.add(sig)
            elif row['split'] in {'train', 'valid'} and segments(sig) & reserved:
                continue
            elif row['test_partition'] == 'state' and sig not in trained:
                continue
            if row['split'] == 'train':
                trained.add(sig)
            seen.add(fp)
            phrases = instructions(goal)
            steps, current = [], copy.deepcopy(state)
            for entry in calls:
                after, events = execute(current, entry['call'], catalog)
                steps.append({'tool': entry['call']['name'], 'args': entry['call']['arguments'],
                              'state_delta': state_delta(current, after), 'events': events})
                current = after
            task_id = f"{row['split']}_{row['test_partition'] or 'main'}_{row['category']}_{row['target']}_{row['difficulty']}_{produced:03d}"
            tasks.append({'task_id': task_id, 'scenario_group': fp, 'split': row['split'],
                          'instruction': phrases[0], 'language_variants': phrases[1:],
                          'goal': goal, 'initial_state': state, 'steps': steps,
                          'simulation_version': config['simulation_version'],
                          'metadata': {'category': row['category'], 'difficulty': row['difficulty'],
                                       'test_partition': row['test_partition'], 'map_template': map_id,
                                       'semantic_fingerprint': fp, 'composition_signature': sig,
                                       'source': 'benchmark-inspired constructive case; not copied demonstration',
                                       'benchmark_case_templates': config['benchmark_case_templates'][row['category']],
                                       'validation': 'symbolic-replay-only'}})
            produced += 1
        attempts_by_row.append({**row, 'attempts': attempts})
    tasks.sort(key=lambda t: t['task_id'])
    audit(tasks, config)
    return tasks, attempts_by_row


def audit(tasks, config):
    def require(condition, message):
        if not condition:
            raise ValueError(message)
    expected = Counter((r['split'], r['test_partition'], r['category'], r['target'], r['difficulty'])
                       for r in config['quotas'] for _ in range(r['count']))
    actual = Counter((t['split'], t['metadata']['test_partition'], t['metadata']['category'],
                      t['goal']['item'], t['metadata']['difficulty']) for t in tasks)
    require(actual == expected, 'Quota mismatch')
    require(len({fingerprint(t['goal'], t['initial_state']) for t in tasks}) == len(tasks), 'Duplicate scenes')
    train = {t['metadata']['composition_signature'] for t in tasks if t['split'] == 'train'}
    valid = {t['metadata']['composition_signature'] for t in tasks if t['split'] == 'valid'}
    comp = {t['metadata']['composition_signature'] for t in tasks if t['metadata']['test_partition'] == 'composition'}
    exposed = set().union(*(segments(sig) for sig in train | valid))
    require(not comp & exposed, 'Composition holdout leakage (including contiguous subplans)')
    primitives = set().union(*(segments(sig) for sig in train))
    for sig in comp:
        for action in json.loads(sig):
            require(json.dumps([action], sort_keys=True, separators=(',', ':')) in primitives,
                    f'Combination test contains an unseen primitive action: {action}')
    for t in tasks:
        if t['metadata']['test_partition'] == 'state':
            require(t['metadata']['composition_signature'] in train, 'State test has unseen macro-plan')
        if t['split'] != 'test':
            # Uniform recipe knowledge is intentionally separate from task states.
            text = json.dumps([t['goal'], t['initial_state'], t['steps']])
            require(not any(f'"{value}"' in text for value in config['heldout_targets']), 'Novel target leakage')
    return {'quotas_match': True, 'semantic_duplicates': 0, 'composition_overlap': 0,
            'novel_target_leakage': 0, 'train_macro_plans': len(train), 'composition_macro_plans': len(comp)}
