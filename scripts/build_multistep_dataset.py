#!/usr/bin/env python3
"""Build the first multi-step Composite Tool dataset."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dataset.multistep import build_dataset, load_task_specs, write_jsonl  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=Path, default=ROOT / "data" / "multistep_tasks.json")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data" / "datasets" / "multistep_demo")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    result = build_dataset(load_task_specs(args.tasks), seed=args.seed)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.output_dir / "trajectories.jsonl", result["trajectories"])
    for split, rows in result["samples"].items():
        write_jsonl(args.output_dir / f"{split}.jsonl", rows)
    manifest = {
        "format_version": "multistep-composite-tool-v1",
        "seed": args.seed,
        "task_count": len(result["trajectories"]),
        "trajectory_count": len(result["trajectories"]),
        "sample_count": sum(len(rows) for rows in result["samples"].values()),
        "samples_by_split": {split: len(rows) for split, rows in result["samples"].items()},
        "tasks_by_split": {
            split: sum(value == split for value in result["split_by_task"].values())
            for split in ("train", "valid", "test")
        },
        "source": str(args.tasks.relative_to(ROOT)),
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
