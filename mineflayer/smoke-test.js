'use strict'

const mineflayer = require('mineflayer')
const { pathfinder, Movements, goals } = require('mineflayer-pathfinder')
const { createExecutor } = require('./executor')

const bot = mineflayer.createBot({
  host: process.env.MC_HOST || '127.0.0.1',
  port: Number(process.env.MC_PORT || 25565),
  username: process.env.MC_USERNAME || 'MCExecutor',
  auth: process.env.MC_AUTH || 'offline',
  version: process.env.MC_VERSION || '1.20.1'
})

bot.loadPlugin(pathfinder)

bot.once('spawn', async () => {
  const movements = new Movements(bot)
  movements.canDig = false
  bot.pathfinder.setMovements(movements)
  const executor = createExecutor(bot, { goals })
  console.log(JSON.stringify({ event: 'spawn', state: executor.stateSnapshot(), world: executor.worldSnapshot(8), supported_tools: executor.supportedTools }, null, 2))

  if (process.env.MC_TOOL_CALL) {
    const call = JSON.parse(process.env.MC_TOOL_CALL)
    const context = process.env.MC_TOOL_CONTEXT ? JSON.parse(process.env.MC_TOOL_CONTEXT) : {}
    console.log(JSON.stringify(await executor.execute(call, context), null, 2))
    if (process.env.MC_KEEP_ALIVE !== '1') bot.quit()
  } else if (process.env.MC_SMOKE_READONLY !== '0') {
    console.log(JSON.stringify({ event: 'readonly_smoke_pass', state: executor.stateSnapshot() }, null, 2))
    bot.quit()
  }
})

bot.on('kicked', reason => console.error(JSON.stringify({ event: 'kicked', reason })))
bot.on('error', error => console.error(JSON.stringify({ event: 'error', message: error.message })))
bot.on('end', reason => console.log(JSON.stringify({ event: 'end', reason })))
