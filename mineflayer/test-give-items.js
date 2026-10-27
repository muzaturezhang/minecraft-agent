'use strict'

const mineflayer = require('mineflayer')
const { pathfinder, Movements, goals } = require('mineflayer-pathfinder')
const { createExecutor } = require('./executor')

const config = {
  host: process.env.MC_HOST || '127.0.0.1',
  port: Number(process.env.MC_PORT || 25566),
  auth: 'offline',
  version: process.env.MC_VERSION || '1.20.1'
}

const recipient = mineflayer.createBot({ ...config, username: 'TestRecipient' })
const bot = mineflayer.createBot({ ...config, username: 'MCExecutor' })

recipient.once('spawn', () => console.log(JSON.stringify({ event: 'recipient_spawn', position: recipient.entity.position })))
bot.loadPlugin(pathfinder)
bot.once('spawn', async () => {
  const movements = new Movements(bot)
  movements.canDig = false
  bot.pathfinder.setMovements(movements)
  const executor = createExecutor(bot, { goals })
  await bot.waitForTicks(20)
  bot.chat('/give @s minecraft:apple 2')
  await bot.waitForTicks(10)
  const result = await executor.execute({ name: 'give_items', arguments: { player: 'TestRecipient', item: 'apple', count: 1 } })
  console.log(JSON.stringify(result, null, 2))
  bot.quit()
  recipient.quit()
})

for (const [name, client] of [['executor', bot], ['recipient', recipient]]) {
  client.on('kicked', reason => console.error(JSON.stringify({ event: 'kicked', bot: name, reason })))
  client.on('error', error => console.error(JSON.stringify({ event: 'error', bot: name, message: error.message })))
}
