#!/usr/bin/env python3
"""Construct the approved bounded Minecraft dataset and audit the split contract."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from dataset.multistep import build_dataset, write_jsonl
from dataset.scenario_generator import audit, generate
from tools.composite_tool_schema import COMPOSITE_TOOLS


def write_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'configs/multistep_v1.json')
    parser.add_argument('--recipes', type=Path, default=ROOT / 'configs/recipe_catalog.json')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'data/datasets/multistep_v1')
    args = parser.parse_args()
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        parser.error('输出目录非空；请使用新的独立位置，避免覆盖数据')
    config, recipes = (json.loads(p.read_text()) for p in (args.config, args.recipes))
    tasks, attempts = generate(config, recipes)
    result = build_dataset(tasks, config['seed'], recipes)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.output_dir / 'tasks.json', tasks)
    write_json(args.output_dir / 'config.json', config)
    write_json(args.output_dir / 'recipe_catalog.json', recipes)
    used_tools = sorted({s['tool'] for t in tasks for s in t['steps']})
    write_json(args.output_dir / 'tool_schema.json', {name: COMPOSITE_TOOLS[name] for name in used_tools})
    write_jsonl(args.output_dir / 'trajectories.jsonl', result['trajectories'])
    for split, rows in result['samples'].items():
        write_jsonl(args.output_dir / f'{split}.jsonl', rows)
    summary = {
        'format_version': 'bounded-composite-tool-v1', 'dataset_version': config['version'],
        'seed': config['seed'], 'minecraft_version': config['minecraft_version'],
        'scenario_count': len(tasks), 'language_trajectory_count': len(tasks) * 3,
        'step_sample_count': sum(map(len, result['samples'].values())),
        'scenarios_by_split': dict(Counter(t['split'] for t in tasks)),
        'samples_by_split': {k: len(v) for k, v in result['samples'].items()},
        'category_by_split': {s: dict(Counter(t['metadata']['category'] for t in tasks if t['split'] == s))
                              for s in ('train', 'valid', 'test')},
        'difficulty_by_split': {s: dict(Counter(t['metadata']['difficulty'] for t in tasks if t['split'] == s))
                                for s in ('train', 'valid', 'test')},
        'test_partitions': dict(Counter(t['metadata']['test_partition'] for t in tasks if t['split'] == 'test')),
        'map_templates': dict(Counter(t['metadata']['map_template'] for t in tasks)),
        'tools': used_tools, 'audit': audit(tasks, config), 'benchmarks': config['benchmarks'],
        'validation': 'Symbolic preconditions/recipes/events replayed; not real-server task completion.',
        'difficulty_definition': 'Reference policy action count, not proven minimum or universal task difficulty.',
        'training_input': 'Serialize only input. Prepend the same tool_schema.json for every split. Predict target.',
        'goal_semantics': 'Newly obtain/craft/smelt specified count; E also records actual use of specified new tool type.',
        'limitations': ['All scenes constructively solvable; no failure labels.',
                       'Exposed patches, inspected chest, common public stations; no survival/combat/exploration.',
                       'No durability/enchantments/alternate recipes; every case uses fewer than 59 digs.',
                       'Three manually templated Chinese phrasings, not three independent world states.',
                       'Recipe knowledge for held-out targets is supplied identically to all splits.'],
        'git_commit': subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True).stdout.strip() or None,
        'git_dirty': bool(subprocess.run(['git', 'status', '--porcelain'], cwd=ROOT, capture_output=True, text=True).stdout.strip()),
        'generation_attempts': sum(r['attempts'] for r in attempts),
        'source_sha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                          for name in ('scripts/generate_multistep_tasks.py', 'scripts/export_recipe_catalog.js',
                                       'src/dataset/scenario_generator.py', 'src/dataset/world_model.py',
                                       'src/dataset/multistep.py', 'src/tools/composite_tool_schema.py')},
    }
    files = sorted(args.output_dir.iterdir())
    summary['sha256'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    write_json(args.output_dir / 'manifest.json', summary)
    print(json.dumps({k: summary[k] for k in ('scenario_count', 'step_sample_count', 'scenarios_by_split', 'samples_by_split', 'audit')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
