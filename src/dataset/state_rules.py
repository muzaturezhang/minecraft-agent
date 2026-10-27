"""Small deterministic state rules for the first multi-step dataset slice.

The rules intentionally cover only the tools used by the seed tasks.  New
recipes and executor-backed state fields can be added without changing the
trajectory format.
"""

from __future__ import annotations

import math
from typing import Any


class StateRuleError(ValueError):
    """Raised when a tool call cannot be executed in the declared state."""


CRAFT_RECIPES = {
    "torch": {
        "output_count": 4,
        "inputs": {"stick": 1, "coal": 1},
        "requires_crafting_table": False,
    },
    "iron_pickaxe": {
        "output_count": 1,
        "inputs": {"iron_ingot": 3, "stick": 2},
        "requires_crafting_table": True,
    },
}

SMELT_RECIPES = {
    "raw_beef": {"output": "cooked_beef", "fuel_per_items": 8},
}

RESOURCE_ALIASES = {
    "coal": ("coal", "coal_ore"),
    "raw_beef": ("raw_beef", "cow"),
    "iron_ore": ("iron_ore", "iron"),
    "oak_log": ("oak_log", "oak_tree"),
}


def _inventory(state: dict[str, Any]) -> dict[str, int]:
    inventory = state.get("inventory", {})
    if not isinstance(inventory, dict):
        raise StateRuleError("state.inventory 必须是对象")
    return inventory


def _inventory_change(before: dict[str, Any], after: dict[str, Any], item: str) -> int:
    return int(after.get(item, 0)) - int(before.get(item, 0))


def _delta_inventory(delta: dict[str, Any]) -> dict[str, int]:
    value = delta.get("inventory", {})
    if not isinstance(value, dict):
        raise StateRuleError("state_delta.inventory 必须是对象")
    return value


def _expect_inventory_delta(delta: dict[str, Any], expected: dict[str, int], action: str) -> None:
    actual = {item: amount for item, amount in _delta_inventory(delta).items() if amount}
    normalized = {item: amount for item, amount in expected.items() if amount}
    _require(actual == normalized, f"state_delta 中 {action} 库存变化不匹配: 期望 {normalized}, 实际 {actual}")


def _get_path(state: dict[str, Any], path: str) -> Any:
    value: Any = state
    for piece in path.split("."):
        if not isinstance(value, dict) or piece not in value:
            return None
        value = value[piece]
    return value


def _get_set_value(delta: dict[str, Any], path: str) -> Any:
    values = delta.get("set", {})
    if not isinstance(values, dict):
        raise StateRuleError("state_delta.set 必须是对象")
    return values.get(path)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise StateRuleError(message)


def _resource_source(state: dict[str, Any], resource: str) -> tuple[str, int] | None:
    nodes = state.get("nearby_resources", {})
    if not isinstance(nodes, dict):
        raise StateRuleError("state.nearby_resources 必须是对象")
    for key in RESOURCE_ALIASES.get(resource, (resource,)):
        if key in nodes:
            return key, int(nodes[key])
    return None


def _check_collect(before: dict[str, Any], after: dict[str, Any], args: dict[str, Any], delta: dict[str, Any]) -> None:
    resource = args["resource"]
    count = args["count"]
    source = _resource_source(before, resource)
    _require(source is not None, f"附近没有可用于收集的资源: {resource}")
    source_key, available = source
    _require(available >= count, f"附近 {resource} 数量不足: 需要 {count}, 只有 {available}")
    if resource in {"coal", "iron_ore"}:
        capabilities = before.get("capabilities", {})
        _require(capabilities.get("has_pickaxe") is True, f"收集 {resource} 前需要镐")
    _require(_inventory_change(_inventory(before), _inventory(after), resource) == count,
             f"收集 {resource} 后库存增量必须为 {count}")
    _expect_inventory_delta(delta, {resource: count}, f"收集 {resource}")
    _require(_get_set_value(delta, f"nearby_resources.{source_key}") == available - count,
             f"收集 {resource} 必须同步更新附近资源 {source_key}")


def _check_retrieve(before: dict[str, Any], after: dict[str, Any], args: dict[str, Any], delta: dict[str, Any]) -> None:
    container = args["container"]
    item = args["item"]
    count = args["count"]
    available = _get_path(before, f"containers.{container}.{item}")
    _require(isinstance(available, int), f"找不到容器 {container} 中的 {item}")
    _require(available >= count, f"容器 {container} 中的 {item} 数量不足")
    _require(_inventory_change(_inventory(before), _inventory(after), item) == count,
             f"从容器取出 {item} 后库存增量必须为 {count}")
    _expect_inventory_delta(delta, {item: count}, f"取出 {item}")
    _require(_get_set_value(delta, f"containers.{container}.{item}") == available - count,
             f"取出 {item} 必须同步更新容器库存")


def _check_craft(before: dict[str, Any], after: dict[str, Any], args: dict[str, Any], delta: dict[str, Any]) -> None:
    item = args["item"]
    count = args["count"]
    recipe = CRAFT_RECIPES.get(item)
    _require(recipe is not None, f"数据集规则中尚未登记配方: {item}")
    if recipe["requires_crafting_table"]:
        capabilities = before.get("capabilities", {})
        _require(capabilities.get("crafting_table_available") is True, f"合成 {item} 前需要工作台")
    batches = math.ceil(count / recipe["output_count"])
    inv_before = _inventory(before)
    inv_after = _inventory(after)
    for ingredient, amount in recipe["inputs"].items():
        _require(inv_before.get(ingredient, 0) >= amount * batches,
                 f"合成 {item} 缺少材料: {ingredient}")
        _require(_inventory_change(inv_before, inv_after, ingredient) == -amount * batches,
                 f"合成 {item} 后 {ingredient} 消耗不正确")
    _require(_inventory_change(inv_before, inv_after, item) == recipe["output_count"] * batches,
             f"合成 {item} 后产出数量不正确")
    expected_delta = {ingredient: -amount * batches for ingredient, amount in recipe["inputs"].items()}
    expected_delta[item] = expected_delta.get(item, 0) + recipe["output_count"] * batches
    _expect_inventory_delta(delta, expected_delta, f"合成 {item}")
    changes = _delta_inventory(delta)
    for ingredient, amount in recipe["inputs"].items():
        _require(changes.get(ingredient) == -amount * batches,
                 f"state_delta 中 {ingredient} 消耗不正确")
    _require(changes.get(item) == recipe["output_count"] * batches,
             f"state_delta 中 {item} 产出不正确")


def _check_smelt(before: dict[str, Any], after: dict[str, Any], args: dict[str, Any], delta: dict[str, Any]) -> None:
    input_item = args["input"]
    count = args["count"]
    recipe = SMELT_RECIPES.get(input_item)
    _require(recipe is not None, f"数据集规则中尚未登记熔炼配方: {input_item}")
    furnace = args.get("furnace", "nearest")
    if furnace != "nearest":
        target = _get_path(before, f"known_targets.{furnace}")
        _require(isinstance(target, dict) and target.get("type") == "furnace",
                 f"找不到熔炉目标: {furnace}")
    else:
        capabilities = before.get("capabilities", {})
        _require(capabilities.get("furnace_available") is True, "附近没有可用熔炉")
    fuel = args.get("fuel", "coal")
    fuel_count = math.ceil(count / recipe["fuel_per_items"])
    inv_before = _inventory(before)
    inv_after = _inventory(after)
    _require(inv_before.get(input_item, 0) >= count, f"熔炼前缺少原料: {input_item}")
    _require(inv_before.get(fuel, 0) >= fuel_count, f"熔炼前缺少燃料: {fuel}")
    _require(_inventory_change(inv_before, inv_after, input_item) == -count,
             f"熔炼后原料消耗不正确")
    _require(_inventory_change(inv_before, inv_after, fuel) == -fuel_count,
             f"熔炼后燃料消耗不正确")
    _require(_inventory_change(inv_before, inv_after, recipe["output"]) == count,
             f"熔炼后产出数量不正确")
    _expect_inventory_delta(delta, {
        input_item: -count,
        fuel: -fuel_count,
        recipe["output"]: count,
    }, f"熔炼 {input_item}")
    changes = _delta_inventory(delta)
    _require(changes.get(input_item) == -count and changes.get(fuel) == -fuel_count,
             "state_delta 中熔炼消耗不正确")
    _require(changes.get(recipe["output"]) == count, "state_delta 中熔炼产出不正确")


def _check_give(before: dict[str, Any], after: dict[str, Any], args: dict[str, Any], delta: dict[str, Any]) -> None:
    player = args["player"]
    item = args["item"]
    count = args["count"]
    _require(player in before.get("visible_players", []), f"当前看不到玩家: {player}")
    _require(_inventory(before).get(item, 0) >= count, f"交付前缺少物品: {item}")
    _require(_inventory_change(_inventory(before), _inventory(after), item) == -count,
             f"交付后 {item} 消耗不正确")
    _expect_inventory_delta(delta, {item: -count}, f"交付 {item}")


def validate_transition(before: dict[str, Any], call: dict[str, Any], delta: dict[str, Any], after: dict[str, Any]) -> None:
    """Validate preconditions and the observable effect of one tool call."""
    name = call["name"]
    args = call["arguments"]
    if name == "collect_resource":
        _check_collect(before, after, args, delta)
    elif name == "retrieve_items":
        _check_retrieve(before, after, args, delta)
    elif name == "craft_item":
        _check_craft(before, after, args, delta)
    elif name == "smelt_item":
        _check_smelt(before, after, args, delta)
    elif name == "give_items":
        _check_give(before, after, args, delta)
