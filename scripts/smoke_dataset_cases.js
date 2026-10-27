#!/usr/bin/env node
'use strict'

// Replays reference cases to check fixtures/executor integration. This is not a
// learned-policy evaluation and must never be reported as model success rate.
const fs = require('node:fs')
const path = require('node:path')
const { once } = require('node:events')
const ROOT = path.resolve(__dirname, '..')
const mineflayer = require(path.join(ROOT, 'mineflayer/node_modules/mineflayer'))
const { pathfinder, Movements, goals } = require(path.join(ROOT, 'mineflayer/node_modules/mineflayer-pathfinder'))
const { fixtureCommands } = require('./prepare_dataset_world')
const { createExecutor } = require(path.join(ROOT, 'mineflayer/executor'))

function normalized(inv) { return JSON.stringify(Object.entries(inv).filter(([, n]) => n).sort()) }

async function main() {
  const args = process.argv.slice(2)
  if (!args.includes('--port')) throw new Error('Pass --port for the isolated loopback server')
  const port = Number(args[args.indexOf('--port') + 1])
  const tasks = JSON.parse(fs.readFileSync(path.join(ROOT, 'data/datasets/multistep_v1/tasks.json')))
  let selected
  if (args.includes('--task-id')) {
    selected = tasks.filter(t => t.task_id === args[args.indexOf('--task-id') + 1])
  } else {
    const cases = [['A', 'coal'], ['A', 'cobblestone'], ['A', 'raw_iron'], ['B', 'torch'],
      ['C', 'stone_pickaxe'], ['D', 'cooked_beef'], ['E', 'wooden_axe'], ['E', 'wooden_pickaxe']]
    selected = cases.map(([cat, item]) => tasks.filter(t => t.split === 'train' && t.metadata.category === cat &&
      t.goal.item === item && t.goal.count <= (cat === 'A' ? 16 : cat === 'B' ? 4 : 2) &&
      t.metadata.difficulty === (cat === 'E' ? 'L1' : cat === 'B' || cat === 'C' ? 'L1' : 'L0') &&
      (cat !== 'A' || t.steps[0].tool === 'collect_resource') && (cat !== 'E' || t.goal.use_count === 1))
      .sort((a, b) => a.goal.count - b.goal.count)[0])
  }
  if (!selected.length || selected.some(t => !t)) throw new Error('Could not select smoke cases')
  const bot = mineflayer.createBot({ host: '127.0.0.1', port, username: 'MCExecutor', auth: 'offline', version: '1.20.1' })
  bot.loadPlugin(pathfinder)
  bot.on('error', error => console.error(error.message))
  const timer = setTimeout(() => { bot.end(); process.exitCode = 1 }, selected.length * 120000)
  try {
    await once(bot, 'spawn')
    const movements = new Movements(bot)
    movements.canDig = false
    movements.allow1by1towers = false
    movements.allowFreeMotion = false
    bot.pathfinder.setMovements(movements)
    const executor = createExecutor(bot, { goals, collectTimeoutMs: 45000 })
    for (const task of selected) {
      console.log(JSON.stringify({ event: 'case_start', task_id: task.task_id }))
      for (const command of fixtureCommands(task.initial_state)) {
        bot.chat(`/${command}`)
        await bot.waitForTicks(2)
      }
      await bot.waitForChunksToLoad()
      await bot.waitForTicks(10)
      if (normalized(executor.stateSnapshot().inventory) !== normalized(task.initial_state.inventory)) throw new Error('Initial inventory mismatch')
      let expected = { ...task.initial_state.inventory }
      for (const [index, step] of task.steps.entries()) {
        const result = await executor.execute({ name: step.tool, arguments: step.args }, task.initial_state)
        for (const [item, delta] of Object.entries(step.state_delta.inventory)) {
          expected[item] = (expected[item] || 0) + delta
          if (!expected[item]) delete expected[item]
        }
        const inventoryMatches = normalized(result.state_after.inventory) === normalized(expected)
        const useMatches = !step.args.tool || result.result?.events?.some(e => e.tool === step.args.tool)
        console.log(JSON.stringify({ event: 'step_result', task_id: task.task_id, step_index: index,
          inventory_matches: inventoryMatches, specified_tool_matches: useMatches, result }))
        if (result.status !== 'success' || !inventoryMatches || !useMatches) throw new Error(`Case failed at step ${index}: ${result.error?.message || 'state mismatch'}`)
      }
      console.log(JSON.stringify({ event: 'case_passed', task_id: task.task_id, steps: task.steps.length }))
    }
  } finally {
    clearTimeout(timer)
    bot.pathfinder.stop()
    bot.quit()
  }
}

if (require.main === module) main().catch(error => { console.error(error.stack); process.exitCode = 1 })
