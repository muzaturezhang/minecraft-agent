"""Bounded symbolic execution used for data construction, not a learned world model.

Every transition is calculated from preconditions and recipes. Unknown actions
fail closed. This module does not certify Mineflayer reachability or server execution.
"""
from __future__ import annotations

import copy
import math


class SimulationError(ValueError):
    pass


MINING = {'oak_log': ('oak_log', 0), 'coal': ('coal_ore', 1),
          'cobblestone': ('stone', 1), 'raw_iron': ('iron_ore', 2)}
PICKS = {'wooden_pickaxe': 1, 'stone_pickaxe': 2, 'iron_pickaxe': 3}
AXES = {'wooden_axe', 'stone_axe', 'iron_axe'}


def require(condition, message):
    if not condition:
        raise SimulationError(message)


def harvest_tool(inventory, resource, forced=None):
    require(resource in MINING, f'Unsupported resource {resource}')
    level = MINING[resource][1]
    if forced:
        require(inventory.get(forced, 0) > 0, f'Missing tool {forced}')
        valid = forced in AXES if resource == 'oak_log' else PICKS.get(forced, 0) >= level
        require(valid, f'{forced} cannot harvest {resource}')
        return forced
    if level:
        for item in reversed(PICKS):
            if inventory.get(item, 0) and PICKS[item] >= level:
                return item
        raise SimulationError(f'Need pickaxe level {level} for {resource}')
    return next((item for item in sorted(AXES) if inventory.get(item)), None)


def _inside(state, position):
    origin = state['boundary']['origin']
    return sum((position[i] - origin[i]) ** 2 for i in (0, 2)) <= state['boundary']['radius'] ** 2


def execute(state, call, catalog):
    """Return a new state and actual symbolic events, without mutating input."""
    s = copy.deepcopy(state)
    inv = s['inventory']
    name, args = call['name'], call['arguments']
    count = args.get('count', 1)
    require(isinstance(count, int) and not isinstance(count, bool) and count > 0, 'count must be positive integer')
    events = []

    def add(item, amount):
        value = inv.get(item, 0) + amount
        require(value >= 0, f'Insufficient {item}')
        if value:
            inv[item] = value
        else:
            inv.pop(item, None)

    def progress(group, key, amount):
        table = s.setdefault('progress', {}).setdefault(group, {})
        table[key] = table.get(key, 0) + amount

    if name == 'collect_resource':
        item = args['resource']
        node = s['resources'].get(item)
        require(node and node['count'] >= count and node['reachable'], f'Resource unavailable: {item}')
        require(_inside(s, node['position']), 'Target outside boundary')
        tool = harvest_tool(inv, item, args.get('tool'))
        if args.get('tool'):
            require(s.get('equipment', {}).get('hand') == tool, 'Equip specified tool first')
        node['count'] -= count
        add(item, count)
        s['position'] = list(node['position'])
        if tool:
            progress('used', f'{tool}:{item}', count)
        events.append({'type': 'harvest', 'item': item, 'count': count, 'tool': tool})
    elif name == 'retrieve_items':
        container, item = args['container'], args['item']
        target = s['known_targets'].get(container)
        require(target and target['type'] == 'container' and _inside(s, target['position']), 'Unknown or out-of-bounds container')
        contents = s['containers'].get(container, {})
        require(contents.get(item, 0) >= count, f'Insufficient {item} in container')
        contents[item] -= count
        add(item, count)
        s['position'] = list(target['position'])
        events.append({'type': 'retrieve', 'item': item, 'count': count})
    elif name == 'craft_item':
        item = args['item']
        recipe = catalog['craft_recipes'].get(item)
        require(recipe is not None, f'Unknown recipe {item}')
        require(not recipe['requires_crafting_table'] or s['capabilities']['crafting_table_available'], 'No crafting table')
        batches = math.ceil(count / recipe['output_count'])
        for ingredient, amount in recipe['inputs'].items():
            add(ingredient, -amount * batches)
        produced = batches * recipe['output_count']
        add(item, produced)
        progress('crafted', item, produced)
        events.append({'type': 'craft', 'item': item, 'count': produced})
    elif name == 'smelt_item':
        item = args['input']
        recipe = catalog['smelt_recipes'].get(item)
        require(recipe is not None and s['capabilities']['furnace_available'], 'Unknown recipe or no furnace')
        require(args.get('fuel', 'coal') == recipe['fuel'], 'Unsupported fuel')
        add(item, -count)
        add(recipe['fuel'], -math.ceil(count / recipe['items_per_fuel']))
        add(recipe['output'], count)
        progress('smelted', recipe['output'], count)
        events.append({'type': 'smelt', 'item': recipe['output'], 'count': count})
    elif name == 'equip_item':
        item = args['item']
        require(inv.get(item, 0) > 0, f'Missing equipment {item}')
        require(args.get('slot', 'hand') == 'hand', 'Only hand equipment in bounded data')
        s.setdefault('equipment', {})['hand'] = item
        events.append({'type': 'equip', 'item': item})
    elif name == 'navigate_to':
        target = args['target']
        if isinstance(target, str):
            target = s['known_targets'].get(target, {}).get('position')
        require(isinstance(target, list) and len(target) == 3 and _inside(s, target), 'Invalid navigation target')
        s['position'] = list(target)
    else:
        raise SimulationError(f'Unsupported symbolic action {name}')
    return s, events


def is_complete(goal, initial, current):
    item, count = goal['item'], goal['count']
    kind = goal['kind']
    if kind == 'obtain':
        return current['inventory'].get(item, 0) - initial['inventory'].get(item, 0) >= count
    group = 'smelted' if kind == 'smelt' else 'crafted'
    made = current.get('progress', {}).get(group, {}).get(item, 0) >= count
    if kind == 'craft_and_use':
        used = current.get('progress', {}).get('used', {}).get(f"{item}:{goal['use_resource']}", 0)
        return made and used >= goal['use_count']
    require(kind in {'craft', 'smelt'}, f'Unknown goal kind {kind}')
    return made


def state_delta(before, after):
    changes = {k: after['inventory'].get(k, 0) - before['inventory'].get(k, 0)
               for k in sorted(before['inventory'].keys() | after['inventory'].keys())}
    return {'inventory': {k: v for k, v in changes.items() if v},
            'set': {k: copy.deepcopy(v) for k, v in after.items() if k != 'inventory' and v != before.get(k)}}


class Planner:
    """Constructive dependency planner for the bounded catalog, not a general solver."""
    def __init__(self, catalog):
        self.catalog = catalog

    def plan(self, initial, goal, preferences=None):
        self.state, self.calls = copy.deepcopy(initial), []
        self.preferences = preferences or {}
        self.stack = set()
        self.goal = goal
        target = goal['count'] + (initial['inventory'].get(goal['item'], 0) if goal['kind'] == 'obtain' else 0)
        self.acquire(goal['item'], target, force=goal['kind'] != 'obtain')
        if goal['kind'] == 'craft_and_use':
            self.emit('equip_item', item=goal['item'], slot='hand')
            self.emit('collect_resource', resource=goal['use_resource'], count=goal['use_count'], tool=goal['item'])
        require(is_complete(goal, initial, self.state), 'Constructed plan did not satisfy goal')
        return self.calls

    def emit(self, name, **args):
        require(len(self.calls) < 16, 'Planning depth budget exceeded')
        call = {'name': name, 'arguments': args}
        self.state, events = execute(self.state, call, self.catalog)
        self.calls.append({'call': call, 'events': events})

    def acquire(self, item, count, force=False):
        needed = count if force else max(0, count - self.state['inventory'].get(item, 0))
        if not needed:
            return
        require(item not in self.stack, f'Cyclic dependency {item}')
        self.stack.add(item)
        try:
            boxes = [(key, box) for key, box in self.state['containers'].items() if box.get(item, 0) >= needed]
            recipe = self.catalog['craft_recipes'].get(item)
            smelt = next(((key, r) for key, r in self.catalog['smelt_recipes'].items() if r['output'] == item), None)
            prefer_box = self.preferences.get(item, False)
            if not force and boxes and (prefer_box or (item not in MINING and not recipe and not smelt)):
                self.emit('retrieve_items', container=boxes[0][0], item=item, count=needed)
            elif recipe:
                batches = math.ceil(needed / recipe['output_count'])
                # Obtain derived ingredients first: sticks may consume planks
                # that must still be present when making a wooden tool.
                def depth(value):
                    r = self.catalog['craft_recipes'].get(value)
                    return 1 + max(map(depth, r['inputs']), default=0) if r else 0
                for ingredient, amount in sorted(recipe['inputs'].items(), key=lambda pair: -depth(pair[0])):
                    self.acquire(ingredient, amount * batches)
                self.emit('craft_item', item=item, count=needed)
            elif smelt:
                input_item, r = smelt
                self.acquire(input_item, needed)
                self.acquire(r['fuel'], math.ceil(needed / r['items_per_fuel']))
                self.emit('smelt_item', input=input_item, count=needed, fuel=r['fuel'])
            elif item in MINING:
                node = self.state['resources'].get(item)
                if not node or node['count'] < needed:
                    if boxes:
                        self.emit('retrieve_items', container=boxes[0][0], item=item, count=needed)
                        return
                    raise SimulationError(f'No permitted source for {item}')
                try:
                    harvest_tool(self.state['inventory'], item)
                except SimulationError:
                    needed_tool = 'stone_pickaxe' if MINING[item][1] == 2 else self.preferences.get('mining_tool', 'wooden_pickaxe')
                    # A stone pickaxe cannot bootstrap the stone needed to
                    # make itself; use a wooden pickaxe for that dependency.
                    if needed_tool in self.stack:
                        needed_tool = 'wooden_pickaxe'
                    self.acquire(needed_tool, 1)
                if node and node['count'] >= needed:
                    self.emit('collect_resource', resource=item, count=needed)
                elif boxes:
                    self.emit('retrieve_items', container=boxes[0][0], item=item, count=needed)
                else:
                    raise SimulationError(f'No permitted source for {item}')
            elif boxes:
                self.emit('retrieve_items', container=boxes[0][0], item=item, count=needed)
            else:
                raise SimulationError(f'Cannot acquire {item}')
        finally:
            self.stack.remove(item)
