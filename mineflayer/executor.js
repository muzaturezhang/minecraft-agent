'use strict'

const { Vec3 } = require('vec3')

const TOOL_ARGS = {
  navigate_to: ['target'],
  collect_resource: ['resource', 'count'],
  retrieve_items: ['container', 'item', 'count'],
  craft_item: ['item', 'count'],
  smelt_item: ['input', 'count'],
  give_items: ['player', 'item', 'count'],
  equip_item: ['item']
}

const RESOURCE_BLOCKS = {
  coal: ['coal_ore', 'deepslate_coal_ore'],
  raw_iron: ['iron_ore', 'deepslate_iron_ore'],
  oak_log: ['oak_log'],
  cobblestone: ['stone']
}

const ITEM_ALIASES = {
  raw_beef: 'beef'
}

function inventorySnapshot(bot) {
  const inventory = {}
  for (const item of bot.inventory.items()) {
    const name = item.name === 'beef' ? 'raw_beef' : item.name
    inventory[name] = (inventory[name] || 0) + item.count
  }
  return inventory
}

function positionSnapshot(bot) {
  const p = bot.entity.position
  return { x: p.x, y: p.y, z: p.z }
}

function stateSnapshot(bot) {
  return {
    position: positionSnapshot(bot),
    inventory: inventorySnapshot(bot),
    health: bot.health,
    food: bot.food,
    dimension: bot.game.dimension
  }
}

function worldSnapshot(bot, radius = 8) {
  const position = bot.entity.position.floored()
  const center = bot.blockAt(position)
  const names = ['stone', 'dirt', 'grass_block', 'oak_log', 'coal_ore', 'iron_ore', 'crafting_table', 'furnace', 'chest']
  const nearby = {}
  for (const name of names) {
    const id = bot.registry.blocksByName[name]?.id
    if (id == null) continue
    nearby[name] = bot.findBlocks({ matching: id, maxDistance: radius, count: 8 }).map(pos => ({ x: pos.x, y: pos.y, z: pos.z }))
  }
  return {
    center: center ? { name: center.name, position: { x: center.position.x, y: center.position.y, z: center.position.z } } : null,
    nearby
  }
}

function assertPositiveCount(value, name) {
  if (!Number.isInteger(value) || value < 1) {
    throw new TypeError(`${name} must be a positive integer`)
  }
}

function withTimeout(promise, timeoutMs, label) {
  let timer
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${label} timed out after ${timeoutMs}ms`)), timeoutMs)
  })
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer))
}

function debug(message, details) {
  if (process.env.MC_EXECUTOR_DEBUG === '1') {
    console.log(JSON.stringify({ executor_debug: message, ...details }))
  }
}

function normalizeTarget(target) {
  if (Array.isArray(target) && target.length === 3) {
    return new Vec3(Number(target[0]), Number(target[1]), Number(target[2]))
  }
  if (target && typeof target === 'object' && ['x', 'y', 'z'].every(k => Number.isFinite(target[k]))) {
    return new Vec3(target.x, target.y, target.z)
  }
  throw new TypeError('target must be [x, y, z] or {x, y, z}')
}

function requirePathfinder(bot) {
  if (!bot.pathfinder) {
    throw new Error('mineflayer-pathfinder is not loaded')
  }
}

function getItem(bot, name) {
  const item = bot.registry.itemsByName[ITEM_ALIASES[name] || name]
  if (!item) throw new Error(`Unknown Minecraft item: ${name}`)
  return item
}

function getBlock(bot, position) {
  const block = bot.blockAt(position)
  if (!block) throw new Error(`No loaded block at ${position}`)
  return block
}

function resolveWorldTarget(target, context = {}) {
  if (typeof target === 'string' && context.known_targets?.[target]) {
    const known = context.known_targets[target]
    if (known.position) return known.position
  }
  return target
}

function getContainerBlock(bot, target, context) {
  target = resolveWorldTarget(target, context)
  let position
  if (typeof target === 'string') {
    const match = target.match(/^(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)$/)
    if (!match) throw new Error('container must be a coordinate string "x,y,z"')
    position = new Vec3(Number(match[1]), Number(match[2]), Number(match[3]))
  } else {
    position = normalizeTarget(target)
  }
  return getBlock(bot, position)
}

function createExecutor(bot, options = {}) {
  const { goals, maxSearchDistance = 48, collectTimeoutMs = 30000 } = options

  async function navigateTo(args, context) {
    requirePathfinder(bot)
    if (!goals?.GoalNear) throw new Error('Pathfinder goals are not configured')
    const target = normalizeTarget(resolveWorldTarget(args.target, context))
    const tolerance = args.tolerance ?? 1
    await bot.pathfinder.goto(new goals.GoalNear(target.x, target.y, target.z, tolerance))
    return { arrived: positionSnapshot(bot), tolerance }
  }

  async function collectResource(args, context) {
    assertPositiveCount(args.count, 'count')
    requirePathfinder(bot)
    const blockNames = RESOURCE_BLOCKS[args.resource] || [args.resource]
    const blockIds = blockNames.map(name => bot.registry.blocksByName[name]?.id).filter(Number.isInteger)
    if (!blockIds.length) throw new Error(`No block mapping for resource: ${args.resource}`)
    if (!bot.pathfinder.bestHarvestTool) throw new Error('Pathfinder harvest-tool helper is unavailable')

    const initialCount = inventorySnapshot(bot)[args.resource] || 0
    const deadline = Date.now() + collectTimeoutMs
    let brokenBlocks = 0
    const events = []
    const boundary = context.boundary
    const origin = boundary ? normalizeTarget(boundary.origin) : null
    // Bounded fixtures expose a small known surface patch. Do not mistake
    // unrelated underground stone below the platform for permitted resources.
    const node = context.resources?.[args.resource]
    const patch = node && normalizeTarget(node.position)
    const radius = boundary?.radius ?? args.max_distance ?? maxSearchDistance
    const requestedTool = args.tool && getItem(bot, args.tool)
    if (requestedTool && bot.heldItem?.name !== requestedTool.name) throw new Error('Equip specified tool before collecting')
    while ((inventorySnapshot(bot)[args.resource] || 0) - initialCount < args.count) {
      if (Date.now() >= deadline) throw new Error(`Timed out collecting ${args.resource}`)
      const positions = bot.findBlocks({ matching: blockIds, ...((patch || origin) ? { point: patch || origin } : {}),
        maxDistance: Math.min(args.search_radius ?? maxSearchDistance, radius, patch ? 6 : Infinity), count: 512 })
        .filter(p => !origin || Math.hypot(p.x - origin.x, p.z - origin.z) <= radius)
        .filter(p => !patch || (p.y === patch.y && Math.hypot(p.x - patch.x, p.z - patch.z) <= 6))
        .sort((a, b) => a.distanceTo(bot.entity.position) - b.distanceTo(bot.entity.position))
      const position = positions[0]
      if (!position) throw new Error(`No diggable ${blockNames.join('/')} found nearby`)
      debug('resource_target_found', { resource: args.resource, position: { x: position.x, y: position.y, z: position.z } })
      try {
        await withTimeout(bot.pathfinder.goto(new goals.GoalNear(position.x, position.y, position.z, 2)),
          Math.max(1, deadline - Date.now()), 'collect navigation')
      } catch (error) {
        bot.pathfinder.stop()
        throw error
      }
      const block = getBlock(bot, position)
      debug('resource_target_reached', { position: positionSnapshot(bot), diggable: bot.canDigBlock(block) })
      if (!bot.canDigBlock(block)) throw new Error(`Block is not currently diggable: ${block.name}`)
      const tool = requestedTool ? bot.inventory.items().find(i => i.type === requestedTool.id) : bot.pathfinder.bestHarvestTool(block)
      if (requestedTool && !tool) throw new Error(`Missing specified tool ${args.tool}`)
      if (typeof block.canHarvest === 'function' && !block.canHarvest(tool?.type ?? null)) throw new Error(`No suitable harvest tool for ${block.name}`)
      if (tool) await bot.equip(tool, 'hand')
      if (requestedTool && bot.heldItem?.name !== requestedTool.name) throw new Error('Specified tool is not in hand')
      await bot.dig(block)
      events.push({ type: 'harvest', block: block.name, tool: bot.heldItem?.name || null,
        position: [position.x, position.y, position.z] })
      debug('resource_block_dug', { block: block.name, inventory: inventorySnapshot(bot) })
      brokenBlocks += 1
      await bot.waitForTicks(10)
      // Move close enough to pick up drops; digging from reach alone is insufficient.
      await withTimeout(bot.pathfinder.goto(new goals.GoalNear(position.x, position.y, position.z, 1)),
        Math.max(1, deadline - Date.now()), 'collect drops').catch(error => { bot.pathfinder.stop(); throw error })
      await bot.waitForTicks(5)
      if (brokenBlocks > args.count + 4) throw new Error('Too many digs without expected inventory gain')
    }
    return {
      collected: (inventorySnapshot(bot)[args.resource] || 0) - initialCount,
      brokenBlocks,
      events
    }
  }

  async function equipItem(args) {
    const item = getItem(bot, args.item)
    const stack = bot.inventory.items().find(value => value.type === item.id)
    if (!stack) throw new Error(`Missing equipment: ${args.item}`)
    const destination = args.slot === 'off_hand' ? 'off-hand' : args.slot || 'hand'
    await bot.equip(stack, destination)
    return { equipped: args.item, slot: args.slot || 'hand' }
  }

  async function retrieveItems(args, context) {
    assertPositiveCount(args.count, 'count')
    requirePathfinder(bot)
    const block = getContainerBlock(bot, args.container, context)
    const item = getItem(bot, args.item)
    await bot.pathfinder.goto(new goals.GoalNear(block.position.x, block.position.y, block.position.z, 3))
    const container = await bot.openContainer(block)
    try {
      const available = container.containerItems()
        .filter(stack => stack.type === item.id)
        .reduce((sum, stack) => sum + stack.count, 0)
      if (available < args.count) throw new Error(`Container has ${available} ${args.item}; requested ${args.count}`)
      await container.withdraw(item.id, null, args.count, null)
    } finally {
      await container.close()
    }
    return { retrieved: args.count }
  }

  async function craftItem(args) {
    assertPositiveCount(args.count, 'count')
    const item = getItem(bot, args.item)
    const initialCount = inventorySnapshot(bot)[args.item] || 0
    let table = null
    const tableTarget = args.crafting_table ?? 'nearest_or_inventory'
    const inventoryRecipe = bot.recipesFor(item.id, null, 1, null)[0]
    if (inventoryRecipe) {
      const craftTimes = Math.ceil(args.count / inventoryRecipe.result.count)
      await bot.craft(inventoryRecipe, craftTimes, null)
      return { crafted: (inventorySnapshot(bot)[args.item] || 0) - initialCount, workstation: null }
    }
    if (tableTarget && tableTarget !== 'nearest_or_inventory') {
      table = getBlock(bot, normalizeTarget(tableTarget))
      if (table.name !== 'crafting_table') throw new Error('crafting_table target is not a crafting table')
    } else if (tableTarget === 'nearest_or_inventory') {
      const tableId = bot.registry.blocksByName.crafting_table?.id
      table = tableId == null ? null : bot.findBlock({ matching: tableId, maxDistance: maxSearchDistance })
    }
    if (!table) throw new Error(`No crafting table available for ${args.item}`)
    if (bot.pathfinder && goals?.GoalNear) {
      await bot.pathfinder.goto(new goals.GoalNear(table.position.x, table.position.y, table.position.z, 3))
    }
    const recipe = bot.recipesFor(item.id, null, 1, table)[0]
    if (!recipe) throw new Error(`No available recipe for ${args.item} x${args.count}`)
    const craftTimes = Math.ceil(args.count / recipe.result.count)
    await bot.craft(recipe, craftTimes, table)
    return { crafted: (inventorySnapshot(bot)[args.item] || 0) - initialCount }
  }

  async function smeltItem(args, context) {
    assertPositiveCount(args.count, 'count')
    requirePathfinder(bot)
    const input = getItem(bot, args.input)
    const fuel = getItem(bot, args.fuel || 'coal')
    let furnaceBlock
    if (args.furnace && args.furnace !== 'nearest') {
      furnaceBlock = getBlock(bot, normalizeTarget(resolveWorldTarget(args.furnace, context)))
    } else {
      const furnaceIds = ['furnace', 'blast_furnace', 'smoker']
        .map(name => bot.registry.blocksByName[name]?.id).filter(Number.isInteger)
      furnaceBlock = bot.findBlock({ matching: furnaceIds, maxDistance: maxSearchDistance })
      if (!furnaceBlock) throw new Error('No furnace found nearby')
    }
    if (!['furnace', 'blast_furnace', 'smoker'].includes(furnaceBlock.name)) {
      throw new Error(`Target is not a furnace: ${furnaceBlock.name}`)
    }
    await bot.pathfinder.goto(new goals.GoalNear(furnaceBlock.position.x, furnaceBlock.position.y, furnaceBlock.position.z, 3))
    const furnace = await withTimeout(bot.openFurnace(furnaceBlock), 15000, 'openFurnace')
    const initial = inventorySnapshot(bot)
    try {
      await withTimeout(furnace.putInput(input.id, null, args.count), 15000, 'furnace.putInput')
      const fuelCount = Math.max(1, Math.ceil(args.count / 8))
      await withTimeout(furnace.putFuel(fuel.id, null, fuelCount), 15000, 'furnace.putFuel')
      const expectedSeconds = args.count * 10
      const maxDuration = args.max_duration ?? Math.max(120, expectedSeconds + 30)
      if (maxDuration < expectedSeconds) throw new Error(`max_duration is too short; need at least ${expectedSeconds}s`)
      const deadline = Date.now() + maxDuration * 1000
      while ((furnace.outputItem()?.count || 0) < args.count && Date.now() < deadline) {
        await new Promise(resolve => setTimeout(resolve, 500))
      }
      if ((furnace.outputItem()?.count || 0) < args.count) throw new Error('Timed out waiting for furnace output')
      await withTimeout(furnace.takeOutput(), 15000, 'furnace.takeOutput')
    } finally {
      await furnace.close()
    }
    const finalInventory = inventorySnapshot(bot)
    return { inventoryBefore: initial, inventoryAfter: finalInventory, cooked: (finalInventory.cooked_beef || 0) - (initial.cooked_beef || 0) }
  }

  async function giveItems(args) {
    assertPositiveCount(args.count, 'count')
    requirePathfinder(bot)
    const player = bot.players[args.player]?.entity
    if (!player) throw new Error(`Player not visible: ${args.player}`)
    const item = getItem(bot, args.item)
    const available = inventorySnapshot(bot)[args.item] || 0
    if (available < args.count) throw new Error(`Have ${available} ${args.item}; requested ${args.count}`)
    await bot.pathfinder.goto(new goals.GoalNear(player.position.x, player.position.y, player.position.z, 3))
    await bot.toss(item.id, null, args.count)
    return { tossedNearPlayer: args.player, item: args.item, count: args.count }
  }

  const handlers = { navigate_to: navigateTo, collect_resource: collectResource, retrieve_items: retrieveItems,
    craft_item: craftItem, smelt_item: smeltItem, give_items: giveItems, equip_item: equipItem }

  async function execute(call, context = {}) {
    if (!call || typeof call !== 'object' || typeof call.name !== 'string') {
      throw new TypeError('call must be {name, arguments}')
    }
    const handler = handlers[call.name]
    if (!handler) throw new Error(`Unsupported Composite Tool: ${call.name}`)
    const args = call.arguments || {}
    const missing = TOOL_ARGS[call.name].filter(key => args[key] === undefined || args[key] === null)
    if (missing.length) throw new TypeError(`${call.name} missing arguments: ${missing.join(', ')}`)
    const before = stateSnapshot(bot)
    try {
      const result = await handler(args, context)
      const after = stateSnapshot(bot)
      return { tool_call: call, status: 'success', result, state_before: before, state_after: after }
    } catch (error) {
      return {
        tool_call: call,
        status: 'error',
        error: { name: error.name, message: error.message },
        state_before: before,
        state_after: stateSnapshot(bot)
      }
    }
  }

  return { execute, stateSnapshot: () => stateSnapshot(bot), worldSnapshot: radius => worldSnapshot(bot, radius), supportedTools: Object.keys(handlers) }
}

module.exports = { createExecutor, stateSnapshot, worldSnapshot, RESOURCE_BLOCKS }
