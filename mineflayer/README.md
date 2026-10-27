# Game runtime

`executor.js` accepts one high-level `{ "name": "...", "arguments": {} }` call and maps it to Mineflayer and Pathfinder operations. It returns success/error, results, state snapshots and relevant use events.

Supported calls: `navigate_to`, `collect_resource`, `retrieve_items`, `craft_item`, `smelt_item`, `equip_item`, `give_items`.

```bash
npm ci
npm test
MC_HOST=127.0.0.1 MC_PORT=25565 npm run smoke
```

Environment settings include `MC_HOST`, `MC_PORT`, `MC_USERNAME`, `MC_AUTH` and `MC_VERSION`. The smoke runner reads state by default. To perform a real action:

```bash
MC_PORT=25566 MC_TOOL_CALL='{"name":"craft_item","arguments":{"item":"torch","count":4}}' npm run smoke
```

Named locations can be supplied through `MC_TOOL_CONTEXT` with a `known_targets` mapping. Resource fixtures use exposed patches in a fixed 32-block horizontal boundary. The runtime does not implement unrestricted underground mining.

`npm run setup-smoke-world` prepares a disposable world area. It replaces blocks and inventories and requires operator commands. `npm run test-give-items` starts a second bot as a recipient. Use these only on a dedicated test server.

`bot.js` provides an interactive connection and optional viewer. The model-driven observation/decision loop is not wired into these reference runners yet.

Dependencies are declared in `package.json` and locked in `package-lock.json`. Their installed source code is not bundled here.
