'use strict'

const assert = require('node:assert/strict')
const { createExecutor, RESOURCE_BLOCKS } = require('./executor')

const bot = {
  entity: { position: { x: 1, y: 64, z: -2 } },
  inventory: { items: () => [{ name: 'torch', count: 4 }, { name: 'torch', count: 2 }, { name: 'stick', count: 1 }, { name: 'beef', count: 3 }] },
  health: 20,
  food: 18,
  game: { dimension: 'overworld' }
}

const executor = createExecutor(bot)
assert.deepEqual(executor.stateSnapshot().inventory, { torch: 6, stick: 1, raw_beef: 3 })
assert.deepEqual(executor.stateSnapshot().position, { x: 1, y: 64, z: -2 })
assert.equal(typeof executor.worldSnapshot, 'function')
assert.deepEqual(executor.supportedTools, ['navigate_to', 'collect_resource', 'retrieve_items', 'craft_item', 'smelt_item', 'give_items', 'equip_item'])
assert.deepEqual(RESOURCE_BLOCKS.cobblestone, ['stone'])

async function checkEquipment() {
  const stack = { name: 'wooden_pickaxe', type: 101, count: 1 }
  const mock = { ...bot, registry: { itemsByName: { wooden_pickaxe: { id: 101, name: 'wooden_pickaxe' } }, blocksByName: { coal_ore: { id: 15 } } },
    inventory: { items: () => [stack] },
    pathfinder: { bestHarvestTool: () => { throw new Error('Wrong hand must fail before mining') } },
    equip: async (item, slot) => { assert.ok(['hand', 'off-hand'].includes(slot)); mock.lastEquipmentSlot = slot; mock.heldItem = item } }
  const runtime = createExecutor(mock)
  const wrongHand = await runtime.execute({ name: 'collect_resource', arguments: { resource: 'coal', count: 1, tool: 'wooden_pickaxe' } })
  assert.equal(wrongHand.status, 'error')
  assert.match(wrongHand.error.message, /Equip specified tool/)
  const equipped = await runtime.execute({ name: 'equip_item', arguments: { item: 'wooden_pickaxe', slot: 'hand' } })
  assert.equal(equipped.status, 'success')
  assert.equal(mock.heldItem, stack)
  const offhand = await runtime.execute({ name: 'equip_item', arguments: { item: 'wooden_pickaxe', slot: 'off_hand' } })
  assert.equal(offhand.status, 'success')
  assert.equal(mock.lastEquipmentSlot, 'off-hand')
}
checkEquipment().catch(error => { console.error(error); process.exitCode = 1 })

executor.execute({ name: 'unsupported', arguments: {} }).then(() => {
  throw new Error('unsupported tool should reject')
}, error => {
  assert.match(error.message, /Unsupported Composite Tool/)
  console.log('executor unit checks passed')
})
