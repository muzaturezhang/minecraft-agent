"""Composite Tool schema v1.0.

Model-facing task:
    Chinese natural-language instruction -> 1..N Composite Tool + explicit args

For phase-1 training in this package we use ONE composite tool per instruction.
Composite -> Base Tool execution is deterministic and does not call the model.
"""
try:
    from .base_tool_schema import BASE_TOOLS
except ImportError:
    # Keep direct execution from ``src/tools`` working as well as package imports.
    from base_tool_schema import BASE_TOOLS


def tool(description, required=None, optional=None, defaults=None,
         allowed=None, constraints=None, returns=None, success="",
         base=None, examples=None, confusable=None):
    return {
        "description": description,
        "required_args": required or {},
        "optional_args": optional or {},
        "defaults": defaults or {},
        "allowed_values": allowed or {},
        "constraints": constraints or [],
        "returns": returns or {},
        "success_condition": success,
        "base_tools": base or [],
        "examples": examples or [],
        "confusable_with": confusable or {},
    }


COMPOSITE_TOOLS = {
    # A. perception/search (5)
    "inspect_surroundings": tool("扫描附近环境并返回方块、实体、掉落物摘要。", optional={"radius":"int","categories":"list[str]","max_results":"int"}, defaults={"radius":16,"categories":["blocks","entities","items"],"max_results":20}, returns={"environment":"dict"}, success="完成环境扫描。", base=["get_position","find_blocks","find_entities","find_item_entities"], examples=["看看附近有什么","检查周围生物"]),
    "find_block": tool("寻找指定方块，只返回位置，不破坏、不采集。", required={"block":"str"}, optional={"count":"int","radius":"int","sort":"str"}, defaults={"count":1,"radius":32,"sort":"nearest"}, allowed={"sort":["nearest","farthest"]}, returns={"positions":"list[position]","found_count":"int"}, success="found_count >= count", base=["get_position","find_blocks"], examples=["找三个煤矿","附近有没有钻石矿"], confusable={"break_blocks":"要求破坏方块","collect_resource":"要求最终获得资源"}),
    "find_entity": tool("寻找指定实体，只返回实体信息。", required={"entity":"str"}, optional={"count":"int","radius":"int","sort":"str"}, defaults={"count":1,"radius":32,"sort":"nearest"}, allowed={"sort":["nearest","farthest"]}, returns={"entities":"list[entity]"}, success="找到指定数量实体。", base=["find_entities","get_entity_info"], examples=["找一只牛","Steve在哪"]),
    "find_item_drop": tool("寻找地面指定掉落物，只返回位置。", required={"item":"str"}, optional={"count":"int","radius":"int","sort":"str"}, defaults={"count":1,"radius":32,"sort":"nearest"}, allowed={"sort":["nearest","farthest"]}, returns={"items":"list[entity]"}, success="找到指定数量掉落物。", base=["find_item_entities"], examples=["地上的钻石在哪"], confusable={"collect_drops":"会走过去拾取"}),
    "explore_for": tool("在有限范围内移动探索并寻找目标。", required={"target":"str","target_type":"str"}, optional={"max_distance":"int","search_radius":"int"}, defaults={"max_distance":128,"search_radius":32}, allowed={"target_type":["block","entity","structure"]}, returns={"target_result":"object","success":"bool"}, success="找到目标或达到搜索边界。", base=["get_position","find_blocks","find_entities","goto_position"], examples=["附近没有村庄，出去找一个"]),

    # B. movement (6)
    "navigate_to": tool("前往明确位置、实体或已知地点。", required={"target":"target"}, optional={"target_type":"str","tolerance":"float"}, defaults={"target_type":"auto","tolerance":1.0}, allowed={"target_type":["auto","position","entity","named_location"]}, returns={"success":"bool"}, success="进入目标容差范围。", base=["goto_position","goto_entity"], examples=["去坐标100 64 -20","走到Steve旁边","回基地"]),
    "follow_entity": tool("在有限时间内跟随指定实体。", required={"entity":"str","duration":"float"}, optional={"distance":"float"}, defaults={"distance":3.0}, returns={"success":"bool"}, success="完成指定时间跟随。", base=["find_entities","set_follow_goal","wait_ticks","stop_pathfinding"], examples=["跟着Steve三十秒"]),
    "flee_from": tool("远离指定威胁直到达到安全距离。", required={"threat":"str"}, optional={"safe_distance":"float","max_duration":"float"}, defaults={"safe_distance":16,"max_duration":10}, returns={"success":"bool"}, success="达到安全距离或超时。", base=["get_position","find_entities","get_entity_info","goto_position"], examples=["离苦力怕远一点"]),
    "use_portal": tool("寻找并进入指定传送门。", required={"portal_type":"str"}, optional={"target_dimension":"str","search_radius":"int"}, defaults={"search_radius":32}, returns={"success":"bool"}, success="成功通过传送门。", base=["find_blocks","goto_position","wait_for_dimension_change"], examples=["进入下界传送门"]),
    "ride_vehicle": tool("骑乘或乘坐载具前往明确目标。", required={"vehicle":"str","destination":"target"}, optional={"max_duration":"float"}, defaults={"max_duration":60}, returns={"success":"bool"}, success="乘坐载具到达目标。", base=["find_entities","goto_entity","mount_entity","move_vehicle","dismount"], examples=["坐船去对岸","骑马去基地"]),
    "elytra_travel": tool("使用鞘翅飞往明确目的地。", required={"destination":"target"}, optional={"tolerance":"float","max_duration":"float"}, defaults={"tolerance":3,"max_duration":60}, returns={"success":"bool"}, success="飞到目标附近。", base=["get_inventory","equip","look_at","elytra_fly"], examples=["用鞘翅飞到山顶"]),

    # C. blocks/resources (7)
    "break_blocks": tool("破坏明确方块，不强调获得掉落物。", optional={"block":"str","positions":"list[position]","count":"int","radius":"int"}, defaults={"count":1,"radius":8}, constraints=["block 或 positions 至少提供一个"], returns={"broken_count":"int"}, success="指定方块破坏完成。", base=["find_blocks","goto_position","get_inventory","equip","dig_block"], examples=["把三块石头挖掉"], confusable={"collect_resource":"目标是把资源收入背包"}),
    "collect_resource": tool("寻找并获取指定资源，使其进入背包；tool 指定必须实际使用的手持工具。", required={"resource":"str","count":"int"}, optional={"search_radius":"int","max_distance":"int","tool":"str"}, defaults={"search_radius":32,"max_distance":64}, returns={"collected_count":"int"}, success="获得目标数量资源。", base=["get_inventory","find_blocks","goto_position","equip","dig_block"], examples=["弄八块煤回来","收集十个橡木原木"]),
    "collect_drops": tool("寻找并拾取地面掉落物。", required={"item":"str"}, optional={"count":"int","radius":"int"}, defaults={"count":1,"radius":32}, returns={"collected_count":"int"}, success="掉落物进入背包。", base=["find_item_entities","goto_entity","get_inventory"], examples=["把地上的钻石捡起来"]),
    "hunt_mob": tool("寻找并击杀指定数量的一类生物。", required={"mob":"str","count":"int"}, optional={"radius":"int","weapon":"str","max_duration":"float"}, defaults={"radius":32,"max_duration":60}, returns={"killed_count":"int"}, success="击杀数量达到要求。", base=["find_entities","goto_entity","get_inventory","equip","attack_entity"], examples=["杀三只牛"], confusable={"combat_target":"针对一个明确目标"}),
    "fish_resource": tool("执行有限次数或有限时间的钓鱼。", optional={"count":"int","target_item":"str","max_duration":"float"}, defaults={"count":1,"max_duration":60}, returns={"caught_items":"list[item]"}, success="完成要求的钓鱼目标。", base=["get_inventory","equip","fish_once"], examples=["钓三次鱼"]),
    "maintain_farm": tool("对明确农田执行种植、收获或收获后重种。", required={"crop":"str","action":"str"}, optional={"area":"region","count":"int"}, allowed={"action":["harvest","plant","harvest_and_replant"]}, returns={"processed_count":"int"}, success="农业任务完成。", base=["find_blocks","goto_position","dig_block","get_inventory","equip","place_block","activate_block"], examples=["收小麦然后重新种"]),
    "use_item_on_target": tool("使用指定物品作用于明确方块或实体。", required={"item":"str","target":"target"}, optional={"target_type":"str","count":"int"}, defaults={"target_type":"auto","count":1}, allowed={"target_type":["auto","block","entity"]}, returns={"success":"bool"}, success="物品成功作用于目标。", base=["get_inventory","equip","goto_position","goto_entity","activate_block","use_item_on_entity"], examples=["用骨粉催这棵树","用剪刀剪这只羊"]),

    # D. manufacture (5)
    "craft_item": tool("合成指定数量物品。", required={"item":"str","count":"int"}, optional={"crafting_table":"target"}, defaults={"crafting_table":"nearest_or_inventory"}, returns={"crafted_count":"int"}, success="获得指定数量合成物。", base=["get_inventory","get_recipes","find_blocks","goto_position","craft"], examples=["做四个火把","合成一把铁镐"]),
    "smelt_item": tool("使用熔炉加工指定物品。", required={"input":"str","count":"int"}, optional={"fuel":"str","furnace":"target"}, defaults={"furnace":"nearest"}, returns={"output_items":"list[item]"}, success="完成指定数量熔炼。", base=["get_inventory","find_blocks","goto_position","open_furnace","furnace_put_input","furnace_put_fuel","wait_ticks","furnace_take_output"], examples=["烧十块铁矿","烤五块牛肉"]),
    "brew_potion": tool("酿造明确药水。", required={"potion":"str","count":"int"}, optional={"brewing_stand":"target"}, defaults={"brewing_stand":"nearest"}, returns={"brewed_count":"int"}, success="获得指定数量药水。", base=["get_inventory","find_blocks","goto_position","open_brewing_stand","brew_recipe"], examples=["做两瓶治疗药水"]),
    "enchant_item": tool("为明确物品执行指定附魔。", required={"item":"str","enchantment":"str"}, optional={"level":"int","table":"target"}, defaults={"table":"nearest"}, returns={"success":"bool"}, success="获得指定附魔。", base=["get_inventory","find_blocks","goto_position","open_enchantment_table","select_enchantment"], examples=["给剑附魔锋利"]),
    "repair_item": tool("修复指定物品。", required={"item":"str"}, optional={"repair_material":"str","target_durability":"float"}, returns={"success":"bool"}, success="完成物品修复。", base=["get_inventory","find_blocks","goto_position","open_anvil","repair_with_anvil"], examples=["修一下铁镐"]),

    # E. inventory (4)
    "equip_item": tool("装备指定物品。", required={"item":"str"}, optional={"slot":"str"}, defaults={"slot":"hand"}, allowed={"slot":["hand","off_hand","head","torso","legs","feet"]}, returns={"success":"bool"}, success="物品进入目标装备位。", base=["get_inventory","equip"], examples=["拿上铁镐","穿上铁胸甲"]),
    "organize_inventory": tool("按预定义规则整理背包。", required={"rule":"str"}, allowed={"rule":["compact","resource_grouped","clear_hotbar","combat_ready"]}, returns={"success":"bool"}, success="背包满足规则。", base=["get_inventory","move_inventory_slot"], examples=["整理背包","把同类资源放一起"]),
    "discard_items": tool("丢弃指定物品。", required={"item":"str"}, optional={"count":"int"}, defaults={"count":1}, returns={"discarded_count":"int"}, success="完成指定数量丢弃。", base=["get_inventory","toss_item"], examples=["扔掉三块腐肉"]),
    "consume_item": tool("吃或喝指定消耗品。", required={"item":"str"}, optional={"count":"int"}, defaults={"count":1}, returns={"consumed_count":"int"}, success="完成指定数量消耗。", base=["get_inventory","equip","consume"], examples=["吃一个面包","喝一瓶治疗药水"]),

    # F. containers/trade (6)
    "inspect_container": tool("打开容器并读取内容。", required={"container":"target"}, returns={"items":"list[item]"}, success="读取容器内容。", base=["find_blocks","goto_position","open_container","close_container"], examples=["看看这个箱子里有什么"]),
    "store_items": tool("把背包物品存入容器。", required={"container":"target","item":"str","count":"int"}, returns={"stored_count":"int"}, success="物品进入目标容器。", base=["goto_position","open_container","transfer_to_container","close_container"], examples=["把十块煤放进箱子"]),
    "retrieve_items": tool("从容器取出物品。", required={"container":"target","item":"str","count":"int"}, returns={"retrieved_count":"int"}, success="物品进入背包。", base=["goto_position","open_container","transfer_from_container","close_container"], examples=["从箱子拿十块煤"]),
    "transfer_items": tool("把物品从一个容器转移到另一个。", required={"source":"target","destination":"target","item":"str","count":"int"}, returns={"transferred_count":"int"}, success="物品到达目标容器。", base=["goto_position","open_container","transfer_from_container","close_container","transfer_to_container"], examples=["把A箱子的煤搬到B箱子"]),
    "give_items": tool("把指定物品交给玩家。", required={"player":"str","item":"str","count":"int"}, returns={"given_count":"int"}, success="物品投放到玩家附近。", base=["find_entities","goto_entity","get_inventory","toss_item"], examples=["给Steve十块煤"]),
    "trade_with_villager": tool("与村民执行明确交易。", required={"villager":"target"}, optional={"desired_item":"str","trade_index":"int","count":"int"}, defaults={"count":1}, constraints=["desired_item 或 trade_index 至少提供一个"], returns={"success":"bool"}, success="完成指定交易。", base=["find_entities","goto_entity","open_villager","execute_trade"], examples=["跟这个村民买三个面包"]),

    # G. building (5)
    "place_blocks": tool("按明确位置或简单模式放置方块。", required={"block":"str"}, optional={"positions":"list[position]","pattern":"str","count":"int"}, defaults={"count":1,"pattern":"single"}, allowed={"pattern":["single","line","row","column"]}, returns={"placed_count":"int"}, success="完成方块放置。", base=["get_inventory","equip","goto_position","place_block"], examples=["在这里放三块石头","往前铺五块木板"]),
    "clear_area": tool("清除明确区域中的方块。", required={"region":"region"}, optional={"block_filter":"str"}, defaults={"block_filter":"all"}, returns={"broken_count":"int"}, success="目标区域清理完成。", base=["find_blocks","goto_position","get_inventory","equip","dig_block"], examples=["把这块5乘5区域清空"]),
    "build_path": tool("在明确起点终点之间建造简单道路或桥面。", required={"start":"position","end":"position","material":"str"}, optional={"width":"int"}, defaults={"width":1}, returns={"placed_count":"int"}, success="形成可通行路径。", base=["get_inventory","goto_position","equip","place_block"], examples=["从这里铺石路到那边"]),
    "build_template": tool("按预定义模板建造简单结构。", required={"template":"str","location":"position","material":"str"}, optional={"size":"dict","orientation":"str"}, allowed={"template":["wall","platform","stairs","pillar","small_shelter"]}, returns={"success":"bool"}, success="预定义结构完成。", base=["get_inventory","goto_position","equip","place_block","dig_block"], examples=["搭一堵石墙","建一个小平台"]),
    "light_area": tool("按固定间隔为明确区域放置光源。", required={"region":"region"}, optional={"light_source":"str","spacing":"int"}, defaults={"light_source":"torch","spacing":6}, returns={"placed_count":"int"}, success="区域照明完成。", base=["get_inventory","goto_position","equip","place_block"], examples=["把矿洞插上火把"]),

    # H. world/entity interaction (5)
    "activate_mechanism": tool("操作门、按钮、拉杆等机关。", required={"target":"target"}, optional={"desired_state":"str"}, returns={"success":"bool"}, success="机关完成指定交互。", base=["find_blocks","goto_position","activate_block"], examples=["打开门","拉一下拉杆"]),
    "animal_interaction": tool("对动物执行喂食、繁殖、驯服、剪毛或挤奶。", required={"animal":"str","action":"str"}, optional={"item":"str","count":"int"}, defaults={"count":1}, allowed={"action":["feed","breed","tame","shear","milk"]}, returns={"success":"bool"}, success="动物交互完成。", base=["find_entities","goto_entity","get_inventory","equip","activate_entity","use_item_on_entity"], examples=["给牛喂小麦","剪羊毛"]),
    "sleep": tool("找到指定床或最近床并睡觉。", optional={"bed":"target"}, defaults={"bed":"nearest_bed"}, returns={"success":"bool"}, success="进入睡眠状态。", base=["find_blocks","goto_position","sleep_in_bed"], examples=["去睡觉"]),
    "write_text": tool("把文字写入书或告示牌。", required={"target_type":"str","text":"str"}, optional={"target":"target"}, allowed={"target_type":["sign","book"]}, returns={"success":"bool"}, success="文字写入完成。", base=["update_sign","write_book"], examples=["在牌子写基地"]),
    "send_message": tool("发送公共聊天或私聊。", required={"message":"str"}, optional={"channel":"str","recipient":"str"}, defaults={"channel":"chat"}, allowed={"channel":["chat","whisper"]}, constraints=["channel=whisper 时必须有 recipient"], returns={"success":"bool"}, success="消息发送完成。", base=["send_chat","send_whisper"], examples=["在聊天说我找到钻石了","私聊Steve说我马上回来"]),

    # I. combat (1)
    "combat_target": tool("对一个明确目标执行有限近战或远程战斗。", required={"target":"target"}, optional={"mode":"str","weapon":"str","max_duration":"float","stop_distance":"float"}, defaults={"mode":"melee","max_duration":30,"stop_distance":2}, allowed={"mode":["melee","ranged"]}, returns={"success":"bool"}, success="目标死亡、失效或超时。", base=["find_entities","goto_entity","get_inventory","equip","look_at","attack_entity"], examples=["杀掉眼前僵尸","用弓攻击那个骷髅"], confusable={"hunt_mob":"寻找并击杀多个同类生物"}),

    # J. control (2)
    "wait": tool("等待明确有限时间。", required={"duration":"float"}, returns={"success":"bool"}, success="等待结束。", base=["wait_ticks"], examples=["等十秒"]),
    "stop_action": tool("停止指定持续动作。", optional={"action":"str"}, defaults={"action":"all"}, allowed={"action":["navigation","following","item_use","all"]}, returns={"success":"bool"}, success="指定动作停止。", base=["stop_pathfinding","deactivate_item","clear_control_states"], examples=["停下来","别跟着我了"]),
}


def get_composite_tool_names():
    return list(COMPOSITE_TOOLS.keys())


def get_composite_tool(name):
    return COMPOSITE_TOOLS.get(name)


def validate_schema():
    errors = []
    if len(COMPOSITE_TOOLS) != 46:
        errors.append(f"Composite Tool 数量应为46，当前为{len(COMPOSITE_TOOLS)}")
    for name, schema in COMPOSITE_TOOLS.items():
        for base in schema["base_tools"]:
            if base not in BASE_TOOLS:
                errors.append(f"{name} 引用了不存在的 Base Tool: {base}")
        declared = set(schema["required_args"]) | set(schema["optional_args"])
        for key in schema["defaults"]:
            if key not in declared:
                errors.append(f"{name} 默认参数未声明: {key}")
    return errors


if __name__ == "__main__":
    print("Composite Tool 数量：", len(COMPOSITE_TOOLS))
    for i, name in enumerate(COMPOSITE_TOOLS, 1):
        print(f"{i:02d}. {name}")
    print("\nSchema 检查")
    errors = validate_schema()
    if errors:
        for e in errors:
            print("-", e)
    else:
        print("检查通过：Schema 没有发现引用错误。")
