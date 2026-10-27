'use strict'

// Extract a deliberately bounded recipe subset from versioned game data.
const fs = require('node:fs')
const path = require('node:path')
const mc = require('minecraft-data')('1.20.1')
const targets = ['oak_planks', 'stick', 'torch', 'crafting_table', 'furnace',
  'wooden_pickaxe', 'stone_pickaxe', 'iron_pickaxe', 'wooden_axe', 'stone_axe',
  'wooden_shovel', 'stone_shovel', 'iron_shovel', 'iron_axe', 'iron_hoe']
const allowed = new Set([...targets, 'oak_log', 'coal', 'cobblestone', 'iron_ingot'])
const recipes = {}
for (const item of targets) {
  const alternatives = mc.recipes[mc.itemsByName[item].id]
  const candidates = alternatives.map(recipe => {
    const cells = recipe.ingredients || recipe.inShape.flat()
    const inputs = {}
    for (const id of cells) {
      if (id === null || id === -1) continue
      const name = mc.items[id].name
      inputs[name] = (inputs[name] || 0) + 1
    }
    return { inputs, output_count: recipe.result.count,
      requires_crafting_table: recipe.inShape ? recipe.inShape.length > 2 || recipe.inShape.some(row => row.length > 2) : false }
  }).filter(recipe => Object.keys(recipe.inputs).every(name => allowed.has(name)))
  if (!candidates.length) throw new Error(`No bounded recipe for ${item}`)
  recipes[item] = candidates[0]
}
const payload = {
  minecraft_version: '1.20.1',
  minecraft_data_version: require('minecraft-data/package.json').version,
  craft_recipes: recipes,
  smelt_recipes: { raw_iron: { output: 'iron_ingot', input_game_name: 'raw_iron', fuel: 'coal', items_per_fuel: 8 },
    raw_beef: { output: 'cooked_beef', input_game_name: 'beef', fuel: 'coal', items_per_fuel: 8 } },
  notes: ['Craft recipes extracted from minecraft-data; one oak/coal/cobblestone recipe per target.',
    'Smelting subset is declared explicitly and checked against server data when preparing a test world.',
    'raw_beef is the existing executor observation alias for Minecraft beef.',
    'No enchantments, alternate fuels or charcoal recipes in this bounded release.'],
  server_jar_sha256: null
}
const output = path.resolve(process.argv[2] || path.join(__dirname, '../configs/recipe_catalog.json'))
fs.writeFileSync(output, JSON.stringify(payload, null, 2) + '\n')
console.log(output)
