'use strict'

const mineflayer = require('mineflayer')
const { createExecutor } = require('./executor')

const bot = mineflayer.createBot({
  host: process.env.MC_HOST || '127.0.0.1',
  port: Number(process.env.MC_PORT || 25566),
  username: 'MCExecutor',
  auth: 'offline',
  version: '1.20.1'
})

function command(text) {
  bot.chat(`/${text}`)
}

bot.once('spawn', async () => {
  const executor = createExecutor(bot)
  const commands = [
    'tp @s 0 64 0',
    'fill -5 63 -5 10 63 5 minecraft:stone',
    'setblock 2 64 0 minecraft:crafting_table',
    'setblock 3 64 0 minecraft:furnace',
    'setblock 4 64 0 minecraft:chest',
    'setblock 6 64 0 minecraft:coal_ore',
    'item replace block 4 64 0 container.0 with minecraft:coal 5',
    'give @s minecraft:stick 16',
    'give @s minecraft:coal 16',
    'give @s minecraft:iron_pickaxe 1',
    'give @s minecraft:beef 3',
    'give @s minecraft:iron_ingot 3',
    'give @s minecraft:crafting_table 1'
  ]
  for (const text of commands) {
    command(text)
    await bot.waitForTicks(5)
  }
  await bot.waitForTicks(20)
  console.log(JSON.stringify({ event: 'test_world_ready', state: executor.stateSnapshot(), world: executor.worldSnapshot(12) }, null, 2))
  bot.quit()
})

bot.on('kicked', reason => console.error(JSON.stringify({ event: 'kicked', reason })))
bot.on('error', error => console.error(JSON.stringify({ event: 'error', message: error.message })))
