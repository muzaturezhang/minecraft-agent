# Minecraft Agent: State-Conditioned Tool-Call Data

This repository contains data construction, offline rule replay and game tool execution for a Chinese-instruction Minecraft agent. Given a final goal, inventory, a bounded world state and execution history, each training example predicts the next high-level tool call.

## Contents

- `data/datasets/multistep_v1/`: 1,400 scenarios, 4,200 language trajectories and 12,582 step examples.
- `src/dataset/`: scenario generation, state transitions, validation and step expansion.
- `src/tools/`: declarative high-level tool schemas and capability metadata.
- `configs/`: task quotas, reusable region definitions and Minecraft 1.20.1 recipes.
- `scripts/`: data-building and recipe-export entry points.
- `tests/`: offline software tests.
- `mineflayer/`: original executor and connection/smoke-test scripts, with dependency manifests. Installed third-party packages are excluded.

The executor supports seven high-level calls: `navigate_to`, `collect_resource`, `retrieve_items`, `craft_item`, `smelt_item`, `equip_item` and `give_items`. The model observation adapter and full model-driven control loop are the next implementation stage. Minecraft servers, model checkpoints and installed third-party packages are not included.

## Dataset

| Split | Scenarios | Step examples |
| --- | ---: | ---: |
| Train | 1,000 | 9,018 |
| Validation | 150 | 1,356 |
| Test | 250 | 2,208 |

Five task families cover resource collection, ordinary crafting, tool progression, smelting/cooking, and crafting followed by tool use. L0/L1/L2 require 1, 2–3 and 4–6 reference calls. The test contains 100 new-state cases, 100 held-out action combinations and 50 new-target cases with supplied recipes. Each scenario has three Chinese template phrasings, all kept in the same split.

`tasks.json` stores reference scenarios. `trajectories.jsonl` stores language trajectories. `train.jsonl`, `valid.jsonl` and `test.jsonl` contain input/target pairs. Use instruction, state, history and shared recipe knowledge as model input. Keep the structured `input.goal` as evaluator metadata rather than exposing it in a natural-language planning experiment. The target is one tool-call JSON.

## Run

Python 3.10 or newer is sufficient for the offline builders and tests. They use the standard library.

```bash
python3 -m unittest discover -s tests -v
python3 scripts/generate_multistep_tasks.py --output-dir data/datasets/rebuilt
```

The generator refuses a nonempty destination. Use a fresh output path. The frozen manifest records the original build configuration and data hashes. A rebuild records its own Git context.

Recipes are already included. To export them again with Node.js and the declared `minecraft-data` version:

```bash
npm install
npm run export-recipes
```

Install dependencies locally. Dependency packages and game binaries are not distributed in this repository.

## Game execution

Install the runtime dependencies from their lockfile:

```bash
cd mineflayer
npm ci
npm test
MC_HOST=127.0.0.1 MC_PORT=25565 npm run smoke
```

The smoke command reads the connected server by default. Set `MC_TOOL_CALL` to execute an explicit high-level JSON call. See `mineflayer/README.md` for examples. Connection settings use environment variables.

For a separate Minecraft 1.20.1 test server, `scripts/prepare_dataset_world.js` generates region setup commands and accepts `--apply` to write the fixtures. `scripts/smoke_dataset_cases.js --port 25566` replays selected reference cases against the executor. Fixture setup clears and replaces blocks and inventories. Use a disposable test world with operator permissions. These scripts are executor checks rather than model-success evaluations.

## Scope and evaluation

Scenarios use exposed resource patches, known containers and available facilities within a 32-block horizontal boundary. Offline replay checks recipes, resource/material changes, tool prerequisites and completion events. It does not reproduce arbitrary terrain, pathfinding, survival or combat. Different valid call sequences can complete the same goal, so task completion should accompany exact tool/argument matching.

## References and third-party material

Task families draw on [MineDojo](https://github.com/MineDojo/MineDojo), tool progression on [MineRL](https://minerl.readthedocs.io/en/v0.4.4/environments/), and inventory planning on [Plancraft](https://github.com/gautierdag/plancraft). The trajectories here are constructed for this project's interfaces.

The MineDojo task-template snapshot, provenance and MIT notice are retained in `data/raw/minedojo/`. Recipe data comes from the declared `minecraft-data` package. Minecraft is a trademark of Mojang/Microsoft. No Minecraft binaries, worlds, textures or model weights are included.

No project-wide redistribution license has been selected for the original project code and generated data. Retained third-party notices apply to their respective material.
