#!/usr/bin/env node
'use strict'

// Business fixture entrypoint. Writes commands by default; --apply requires an
// explicit loopback port and operator permission in an isolated test server.
const fs = require('node:fs')
const path = require('node:path')
const ROOT = path.resolve(__dirname, '..')
const { Vec3 } = require(path.join(ROOT, 'mineflayer/node_modules/vec3'))
const BLOCKS = { oak_log: 'oak_log', cobblestone: 'stone', coal: 'coal_ore', raw_iron: 'iron_ore' }
const ALIASES = { raw_beef: 'beef' }
const OFFSETS = [[-12, -12], [12, -12], [-12, 12], [12, 12]]

function fixtureCommands(state, clearRegion = true) {
  const [x, y, z] = state.boundary.origin
  const r = state.boundary.radius
  const commands = ['gamerule doDaylightCycle false', 'gamerule doMobSpawning false',
    'gamerule keepInventory true', 'time set day', 'weather clear', 'gamemode creative @s',
    `tp @s ${x} ${y + 2} ${z}`, `forceload add ${x - r} ${z - r} ${x + r} ${z + r}`]
  if (clearRegion) {
    commands.push(`fill ${x - r} ${y - 1} ${z - r} ${x + r} ${y - 1} ${z + r} bedrock`)
    for (let dy = 0; dy < 32; dy += 4) {
      commands.push(`fill ${x - r} ${y + dy} ${z - r} ${x + r} ${y + dy + 3} ${z + r} air`)
    }
  }
  commands.push(`kill @e[type=item,x=${x - r},y=${y},z=${z - r},dx=${2 * r},dy=32,dz=${2 * r}]`)
  for (const [item, node] of Object.entries(state.resources)) {
    if (!BLOCKS[item] || !node.reachable || node.count > 64) throw new Error('Unsupported resource fixture')
    const [cx, cy, cz] = node.position
    const rows = Math.floor(node.count / 8)
    if (rows) commands.push(`fill ${cx - 4} ${cy} ${cz - 4} ${cx + 3} ${cy} ${cz - 5 + rows} ${BLOCKS[item]}`)
    if (node.count % 8) commands.push(`fill ${cx - 4} ${cy} ${cz - 4 + rows} ${cx - 5 + node.count % 8} ${cy} ${cz - 4 + rows} ${BLOCKS[item]}`)
  }
  const target = state.known_targets
  commands.push(`setblock ${target.workbench.position.join(' ')} crafting_table`,
    `setblock ${target.furnace.position.join(' ')} furnace`,
    `setblock ${target.supply_chest.position.join(' ')} chest`)
  let slot = 0
  for (const [item, count] of Object.entries(state.containers.supply_chest)) {
    const unstackable = /_(pickaxe|axe|shovel|hoe)$/.test(item)
    for (let remaining = count; remaining > 0; remaining -= unstackable ? 1 : 64) {
      if (slot >= 27) throw new Error('Chest inventory does not fit')
      commands.push(`item replace block ${target.supply_chest.position.join(' ')} container.${slot++} with ${ALIASES[item] || item} ${Math.min(remaining, unstackable ? 1 : 64)}`)
    }
  }
  commands.push('clear @s')
  for (const [item, count] of Object.entries(state.inventory)) commands.push(`give @s ${ALIASES[item] || item} ${count}`)
  commands.push(`tp @s ${state.position.join(' ')}`, 'gamemode survival @s')
  return commands
}

function templateStates(config) {
  return Object.entries(config.map_templates).map(([name, template]) => {
    const [x, y, z] = template.origin
    return { name, state: { position: template.origin, inventory: {},
      boundary: { origin: template.origin, radius: config.boundary_radius },
      resources: Object.fromEntries(template.resources.map((item, i) => [item, {
        count: 64, reachable: true, position: [x + OFFSETS[i][0], y, z + OFFSETS[i][1]] }])),
      known_targets: { supply_chest: { position: [x + 3, y, z + 1] },
        workbench: { position: [x + 1, y, z + 3] }, furnace: { position: [x + 3, y, z + 3] } },
      containers: { supply_chest: {} } } }
  })
}

async function apply(states, port) {
  const mineflayer = require(path.join(ROOT, 'mineflayer/node_modules/mineflayer'))
  const bot = mineflayer.createBot({ host: '127.0.0.1', port, username: 'MCExecutor', auth: 'offline', version: '1.20.1' })
  const { once } = require('node:events')
  bot.on('error', error => console.error(error.message))
  const timer = setTimeout(() => { bot.end(); process.exitCode = 1 }, 120000)
  const errors = []
  bot.on('messagestr', message => {
    if (/permission|Unknown|Incorrect|Cannot|failed|too many|not found|not allowed|outside of the world/i.test(message)) errors.push(message)
  })
  try {
    await once(bot, 'spawn')
    await bot.waitForChunksToLoad()
    for (const entry of states) {
      for (const command of fixtureCommands(entry.state)) {
        bot.chat(`/${command}`)
        await bot.waitForTicks(2)
      }
      await bot.waitForChunksToLoad()
      await bot.waitForTicks(10)
      // Check the entire patch, not just the first matching ore.
      for (const [item, node] of Object.entries(entry.state.resources)) {
        const [cx, cy, cz] = node.position
        let observed = 0
        for (let index = 0; index < node.count; index++) {
          const block = bot.blockAt(new Vec3(cx - 4 + index % 8, cy, cz - 4 + Math.floor(index / 8)))
          if (block?.name === BLOCKS[item]) observed++
        }
        if (observed !== node.count) throw new Error(`${entry.name}: ${item} expected ${node.count}, observed ${observed}`)
      }
      for (const [key, name] of [['workbench', 'crafting_table'], ['furnace', 'furnace'], ['supply_chest', 'chest']]) {
        if (bot.blockAt(new Vec3(...entry.state.known_targets[key].position))?.name !== name) throw new Error(`${entry.name}: missing ${name}`)
      }
      const { stateSnapshot } = require(path.join(ROOT, 'mineflayer/executor'))
      const actualInventory = stateSnapshot(bot).inventory
      if (JSON.stringify(Object.entries(actualInventory).sort()) !== JSON.stringify(Object.entries(entry.state.inventory).sort())) throw new Error('Initial player inventory mismatch')
      const chest = await bot.openContainer(bot.blockAt(new Vec3(...entry.state.known_targets.supply_chest.position)))
      const contents = {}
      for (const stack of chest.containerItems()) {
        const key = stack.name === 'beef' ? 'raw_beef' : stack.name
        contents[key] = (contents[key] || 0) + stack.count
      }
      await chest.close()
      if (JSON.stringify(Object.entries(contents).sort()) !== JSON.stringify(Object.entries(entry.state.containers.supply_chest).sort())) throw new Error('Initial chest inventory mismatch')
      console.log(JSON.stringify({ event: 'region_verified', name: entry.name, origin: entry.state.boundary.origin,
        resources: Object.fromEntries(Object.entries(entry.state.resources).map(([k, v]) => [k, v.count])) }))
    }
    if (errors.length) throw new Error(errors.join('; '))
  } finally {
    clearTimeout(timer)
    bot.quit()
  }
}

async function main() {
  const args = process.argv.slice(2)
  const value = flag => args[args.indexOf(flag) + 1]
  const config = JSON.parse(fs.readFileSync(path.join(ROOT, 'configs/multistep_v1.json')))
  let states = templateStates(config)
  if (args.includes('--task-id')) {
    const tasks = JSON.parse(fs.readFileSync(args.includes('--tasks') ? value('--tasks') : path.join(ROOT, 'data/datasets/multistep_v1/tasks.json')))
    const task = tasks.find(t => t.task_id === value('--task-id'))
    if (!task) throw new Error('Unknown task id')
    states = [{ name: task.task_id, state: task.initial_state }]
  }
  if (args.includes('--apply')) {
    if (!args.includes('--port') || !Number.isInteger(Number(value('--port')))) throw new Error('--apply requires explicit --port of isolated loopback test server')
    await apply(states, Number(value('--port')))
  } else {
    console.log(JSON.stringify(states.map(e => ({ name: e.name, commands: fixtureCommands(e.state) })), null, 2))
  }
}

if (require.main === module) main().catch(error => { console.error(error.stack); process.exitCode = 1 })
module.exports = { fixtureCommands, templateStates, apply }
