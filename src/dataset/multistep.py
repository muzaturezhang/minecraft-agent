"""Build validated multi-step Composite Tool supervision data.

Task specifications are deliberately declarative.  A task owns its complete
trajectory, while the exported step samples expose only the state and history
available immediately before the next tool call.
"""

from __future__ import annotations

import copy
import json
import random
from pathlib import Path
from typing import Any, Iterable

try:
    from tools.composite_tool_schema import COMPOSITE_TOOLS
except ImportError:
    from composite_tool_schema import COMPOSITE_TOOLS

from .state_rules import StateRuleError, validate_transition
from .world_model import SimulationError, execute, is_complete


class DatasetValidationError(ValueError):
    """Raised when a task specification cannot produce valid supervision."""


def load_task_specs(path: str | Path) -> list[dict[str, Any]]:
    """Load a JSON list of task specifications."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise DatasetValidationError("任务文件必须是 JSON 数组")
    return payload


def _type_matches(value: Any, type_name: str) -> bool:
    if type_name == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "float":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_name == "str":
        return isinstance(value, str)
    if type_name == "bool":
        return isinstance(value, bool)
    if type_name.startswith("list["):
        return isinstance(value, list)
    # target, position, region and domain-specific references are JSON objects
    # or strings in different executor adapters, so validate their presence
    # without imposing a representation here.
    return True


def _validate_call(call: dict[str, Any], path: str) -> dict[str, Any]:
    if not isinstance(call, dict):
        raise DatasetValidationError(f"{path} 必须是对象")
    tool_name = call.get("tool")
    args = call.get("args", {})
    if not isinstance(tool_name, str) or tool_name not in COMPOSITE_TOOLS:
        raise DatasetValidationError(f"{path}.tool 未知: {tool_name!r}")
    if not isinstance(args, dict):
        raise DatasetValidationError(f"{path}.args 必须是对象")

    schema = COMPOSITE_TOOLS[tool_name]
    required = schema["required_args"]
    declared = set(required) | set(schema["optional_args"])
    missing = sorted(set(required) - set(args))
    unknown = sorted(set(args) - declared)
    if missing:
        raise DatasetValidationError(f"{path} 缺少参数: {', '.join(missing)}")
    if unknown:
        raise DatasetValidationError(f"{path} 包含未声明参数: {', '.join(unknown)}")
    for key, value in args.items():
        type_name = required.get(key, schema["optional_args"].get(key))
        if not _type_matches(value, type_name):
            raise DatasetValidationError(
                f"{path}.args.{key} 类型错误: 期望 {type_name}, 实际 {type(value).__name__}"
            )
    for key, allowed in schema["allowed_values"].items():
        if key in args and args[key] not in allowed:
            raise DatasetValidationError(
                f"{path}.args.{key} 值非法: {args[key]!r}; 允许 {allowed}"
            )
    for constraint in schema["constraints"]:
        if "或" in constraint and "至少提供一个" in constraint:
            alternatives = constraint.split("至少提供一个", 1)[0].strip()
            names = [name.strip() for name in alternatives.split("或")]
            if not any(name in args and args[name] is not None for name in names):
                raise DatasetValidationError(
                    f"{path} 未满足约束，至少需要一个参数: {', '.join(names)}"
                )
        if "channel=whisper" in constraint and args.get("channel") == "whisper" and not args.get("recipient"):
            raise DatasetValidationError(f"{path}.args.recipient 在 whisper 模式下必填")
    return {"name": tool_name, "arguments": copy.deepcopy(args)}


def _add_inventory(state: dict[str, Any], delta: dict[str, Any], path: str) -> None:
    inventory = state.setdefault("inventory", {})
    if not isinstance(inventory, dict) or not isinstance(delta, dict):
        raise DatasetValidationError(f"{path}.inventory 必须是对象")
    for item, amount in delta.items():
        if not isinstance(amount, int) or isinstance(amount, bool):
            raise DatasetValidationError(f"{path}.inventory.{item} 必须是整数增量")
        updated = inventory.get(item, 0) + amount
        if updated < 0:
            raise DatasetValidationError(
                f"{path}.inventory.{item} 使库存变为负数: {updated}"
            )
        if updated:
            inventory[item] = updated
        else:
            inventory.pop(item, None)


def apply_state_delta(state: dict[str, Any], delta: dict[str, Any], path: str) -> dict[str, Any]:
    """Apply the small, explicit state transition language used by task specs."""
    if delta is None:
        return copy.deepcopy(state)
    if not isinstance(delta, dict):
        raise DatasetValidationError(f"{path}.state_delta 必须是对象")
    result = copy.deepcopy(state)
    if "inventory" in delta:
        _add_inventory(result, delta["inventory"], path)
    for key, value in delta.get("set", {}).items():
        if not isinstance(key, str) or not key:
            raise DatasetValidationError(f"{path}.state_delta.set 的键必须非空")
        cursor = result
        pieces = key.split(".")
        for piece in pieces[:-1]:
            cursor = cursor.setdefault(piece, {})
        cursor[pieces[-1]] = copy.deepcopy(value)
    unknown = set(delta) - {"inventory", "set"}
    if unknown:
        raise DatasetValidationError(
            f"{path}.state_delta 包含未知字段: {', '.join(sorted(unknown))}"
        )
    return result


def _validate_task(task: dict[str, Any], index: int) -> None:
    path = f"tasks[{index}]"
    if not isinstance(task, dict):
        raise DatasetValidationError(f"{path} 必须是对象")
    for key in ("task_id", "instruction", "initial_state", "steps"):
        if key not in task:
            raise DatasetValidationError(f"{path} 缺少字段: {key}")
    if not isinstance(task["task_id"], str) or not task["task_id"]:
        raise DatasetValidationError(f"{path}.task_id 必须是非空字符串")
    if not isinstance(task["instruction"], str) or not task["instruction"]:
        raise DatasetValidationError(f"{path}.instruction 必须是非空字符串")
    if not isinstance(task["initial_state"], dict):
        raise DatasetValidationError(f"{path}.initial_state 必须是对象")
    if not isinstance(task["steps"], list) or not task["steps"]:
        raise DatasetValidationError(f"{path}.steps 必须是非空数组")
    for step_index, step in enumerate(task["steps"]):
        _validate_call(step, f"{path}.steps[{step_index}]")
        if "state_delta" in step and not isinstance(step["state_delta"], dict):
            raise DatasetValidationError(f"{path}.steps[{step_index}].state_delta 必须是对象")
    variants = task.get("language_variants", [])
    if not isinstance(variants, list) or not all(isinstance(x, str) and x for x in variants):
        raise DatasetValidationError(f"{path}.language_variants 必须是字符串数组")


def _split_tasks(tasks: list[dict[str, Any]], seed: int) -> dict[str, str]:
    ids = [task["task_id"] for task in tasks]
    if len(set(ids)) != len(ids):
        raise DatasetValidationError("task_id 必须唯一")
    if any('split' in task for task in tasks):
        if not all(task.get('split') in {'train', 'valid', 'test'} for task in tasks):
            raise DatasetValidationError('显式划分必须为每个任务填写 train/valid/test')
        assigned = {}
        for task in tasks:
            group = task.get('scenario_group', task['task_id'])
            if group in assigned and assigned[group] != task['split']:
                raise DatasetValidationError('同一 scenario_group 不得跨集合')
            assigned[group] = task['split']
        return {task['task_id']: task['split'] for task in tasks}
    groups: dict[str, list[str]] = {}
    for task in tasks:
        group = task.get("scenario_group", task["task_id"])
        if not isinstance(group, str) or not group:
            raise DatasetValidationError(f"{task['task_id']}.scenario_group 必须是非空字符串")
        groups.setdefault(group, []).append(task["task_id"])
    shuffled = list(groups)
    random.Random(seed).shuffle(shuffled)
    n = len(shuffled)
    # Keep tiny datasets useful: validation and test each receive a task when
    # there are at least three groups; otherwise everything remains trainable.
    counts = {"train": n, "valid": 0, "test": 0}
    if n >= 3:
        counts = {"train": n - 2, "valid": 1, "test": 1}
    elif n == 2:
        counts = {"train": 1, "valid": 0, "test": 1}
    split_by_group: dict[str, str] = {}
    offset = 0
    for split, count in counts.items():
        for group in shuffled[offset:offset + count]:
            split_by_group[group] = split
        offset += count
    return {
        task["task_id"]: split_by_group[task.get("scenario_group", task["task_id"])]
        for task in tasks
    }


def build_dataset(tasks: Iterable[dict[str, Any]], seed: int = 42, recipe_catalog=None) -> dict[str, Any]:
    """Validate tasks and return trajectories plus split step samples."""
    task_list = list(tasks)
    for index, task in enumerate(task_list):
        _validate_task(task, index)
    split_by_task = _split_tasks(task_list, seed)
    trajectories: list[dict[str, Any]] = []
    samples: dict[str, list[dict[str, Any]]] = {"train": [], "valid": [], "test": []}

    for task_index, task in enumerate(task_list):
        task_id = task["task_id"]
        split = split_by_task[task_id]
        state = copy.deepcopy(task["initial_state"])
        history: list[dict[str, Any]] = []
        trajectory_steps = []
        variants = [task["instruction"], *task.get("language_variants", [])]
        bounded = task.get('simulation_version') == 'bounded-v1'
        if bounded and recipe_catalog is None:
            raise DatasetValidationError('bounded-v1 需要 recipe_catalog')
        for step_index, raw_step in enumerate(task["steps"]):
            step_path = f"tasks[{task_index}].steps[{step_index}]"
            call = _validate_call(raw_step, step_path)
            state_before = copy.deepcopy(state)
            state = apply_state_delta(state, raw_step.get("state_delta", {}), step_path)
            try:
                if bounded:
                    expected, events = execute(state_before, call, recipe_catalog)
                    if expected != state or events != raw_step.get('events'):
                        raise SimulationError('声明的状态变化/事件与规则执行不一致')
                else:
                    validate_transition(state_before, call, raw_step.get("state_delta", {}), state)
            except (StateRuleError, SimulationError) as exc:
                raise DatasetValidationError(f"{step_path} 状态规则失败: {exc}") from exc
            state_after = copy.deepcopy(state)
            step_record = {
                "step_index": step_index,
                "tool_call": call,
                "state_delta": copy.deepcopy(raw_step.get("state_delta", {})),
                "state_before": state_before,
                "state_after": state_after,
            }
            trajectory_steps.append(step_record)
            for variant_index, instruction in enumerate(variants):
                sample = {
                    "sample_id": f"{task_id}__v{variant_index}__s{step_index}",
                    "task_id": task_id,
                    "scenario_group": task.get("scenario_group", task_id),
                    "step_index": step_index,
                    "instruction": instruction,
                    "state": state_before,
                    "history": copy.deepcopy(history),
                    "target": copy.deepcopy(call),
                    "split": split,
                }
                if bounded:
                    # Only this object is serialized for model conditioning.
                    # Split, IDs, category, difficulty and future plan stay out.
                    sample['input'] = {key: sample.pop(key) for key in ('instruction', 'state', 'history')}
                    sample['input']['goal'] = copy.deepcopy(task['goal'])
                    sample['input']['recipe_knowledge'] = {
                        'craft_recipes': recipe_catalog['craft_recipes'],
                        'smelt_recipes': recipe_catalog['smelt_recipes']}
                samples[split].append(sample)
            history.append({
                "tool_call": copy.deepcopy(call),
                "state_delta": copy.deepcopy(raw_step.get("state_delta", {})),
                **({'status': 'success', 'events': copy.deepcopy(raw_step['events'])} if bounded else {}),
            })
        if bounded and not is_complete(task['goal'], task['initial_state'], state):
            raise DatasetValidationError(f'{task_id}: 最终目标未满足')
        trajectories.append({
            "task_id": task_id,
            "scenario_group": task.get("scenario_group", task_id),
            "instruction": task["instruction"],
            "language_variants": copy.deepcopy(task.get("language_variants", [])),
            "initial_state": copy.deepcopy(task["initial_state"]),
            "steps": trajectory_steps,
            "final_state": state,
            "metadata": copy.deepcopy(task.get("metadata", {})),
            "split": split,
            **({'goal': copy.deepcopy(task['goal']), 'simulation_version': 'bounded-v1'} if bounded else {}),
        })
    return {"trajectories": trajectories, "samples": samples, "split_by_task": split_by_task}


def write_jsonl(path: str | Path, rows: Iterable[dict[str, Any]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
