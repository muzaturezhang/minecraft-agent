const mineflayer = require('mineflayer')

const mineflayerViewer = require('prismarine-viewer').mineflayer

const bot = mineflayer.createBot({
  host: '127.0.0.1',
  port: 25565,
  username: 'MLBot',
  auth: 'offline',
  version: '1.20.1'
})

bot.once('spawn', () => {

  mineflayerViewer(bot, {
    port: 3007,
    firstPerson: true,
    viewDistance: 3
  })

  console.log('浏览器画面：http://127.0.0.1:3007')

  console.log('✅ Bot 已进入世界！')

  const { x, y, z } = bot.entity.position
  console.log('当前位置：', { x, y, z })

  const items = bot.inventory.items().map(item => ({
    name: item.name,
    count: item.count
  }))
  console.log('当前背包：', items)

  if (process.env.MC_SEND_GREETING === '1') bot.chat('Hello! I am MLBot.')
})

bot.on('kicked', reason => {
  console.log('被服务器踢出：', reason)
})

bot.on('error', error => {
  console.error('连接错误：', error)
})

bot.on('end', reason => {
  console.log('连接已结束：', reason)
})

const readline = require('node:readline')

const terminal = readline.createInterface({
  input: process.stdin,
  output: process.stdout
})

let walkTimer

terminal.on('line', async line => {
  const command = line.trim()

  if (!bot.entity) {
    console.log('Bot 还没进入世界')
    return
  }

  try {
    if (command === 'state') {
      console.log('位置：', bot.entity.position)
      console.log('背包：', bot.inventory.items().map(item => ({
        name: item.name,
        count: item.count
      })))
    } else if (command === 'turn') {
      await bot.look(bot.entity.yaw + Math.PI / 2, 0)
      console.log('已向左转 90 度')
    } else if (command === 'walk') {
      clearTimeout(walkTimer)
      bot.setControlState('forward', true)
      walkTimer = setTimeout(() => {
        bot.clearControlStates()
        console.log('已停止前进')
      }, 500)
    } else if (command === 'stop') {
      clearTimeout(walkTimer)
      bot.clearControlStates()
      console.log('已停止')
    } else {
      console.log('可输入：state / turn / walk / stop')
    }
  } catch (error) {
    console.error('操作失败：', error.message)
  }
})