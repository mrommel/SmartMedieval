# Siege of Greywatch — implementation plan

## First playable milestone

- [x] Add a browser-playable isometric map served by the Django project, with original canvas-drawn placeholder art.
- [x] Spawn six attackers, support single-unit and shift-click group selection, and issue movement orders with click-to-move.
- [x] Route units around castle walls through the open gate and make the courtyard objective capturable.
- [x] Add a start/restart flow, concise controls, responsive layout, and status feedback.
- [x] Add a scenario/single-game launch catalog with seeded entries and read-only APIs.

## Game authoring and server-owned play

- [x] Add an authenticated admin editor to create single games and link them to scenarios.
- [x] Persist session-owned game instances and load the battlefield, units, and current instance state from the server.
- [x] Store editable game definitions on the server instead of using one fixed map and starting roster for all catalog entries.
- [x] Send player movement and end-turn actions to the server for validation and state updates, with revision checks against stale actions.
- [x] Make movement and courtyard capture turn-based rather than advancing them in a continuous client-side animation loop.
- [x] Add exactly one opposing enemy side with its own units and server-side AI. Connect the server to `http://127.0.0.1:11435/v1` using `unsloth/Qwen3.8-27B-GGUF:UD-Q4_K_XL`; read the API key from `.env` and never expose it to the browser or commit it. Defenders move on end turn but cannot fight or occupy the objective until combat is implemented.

## Game engine and siege systems

- [ ] Separate simulation state, input, pathfinding, rendering, and UI so each can evolve without coupling.
  - [x] Move prototype state, movement, capture, and pathfinding out of the browser UI into a testable server engine.
  - [ ] Move battlefield rendering behind a renderer module.
  - [ ] Isolate pointer/camera input and launch/catalog UI.
- [ ] Add robust terrain collision, unit spacing, and map configuration for multiple strongpoints and elevation levels; allow units to climb between levels using ladders and ramps.
- [x] Add camera pan and zoom with pointer dragging, wheel input, and accessible zoom buttons.
- [x] Give units turn-based move points that are spent on movement and restored at turn end.
- [ ] Give units fight points, health, and morale, with turn-based rules for spending and changing them.
- [ ] Allow units to promote to higher ranks with increased point allowances.
- [ ] Add melee, bow, and crossbow combat with distinct attack ranges, reload times, health, projectile motion, and line-of-sight checks.
- [ ] Add defender behavior, cover and wall advantages, capture/defeat states, and a tuned playable encounter.
- [ ] Persist settings and add accessible controls, pause and animation-speed controls, and clear combat feedback.

## Asset creation

- [ ] Set an original visual direction, palette, tile scale, and asset naming/manifest conventions.
- [ ] Create terrain, road, wall, gate, tower, courtyard, and objective art as modular isometric tiles.
- [ ] Create original directional attacker/defender sprites with idle, walk, attack, hit, and defeat animations.
- [ ] Create weapons, arrows/bolts, selection indicators, health bars, UI icons, and lightweight combat audio.
- [ ] Keep editable source assets, optimized browser exports, and a record of licenses/attributions for any external material.
- [ ] Replace the milestone's procedural placeholder drawings incrementally and confirm visual clarity at desktop and mobile sizes.

## Release and validation

- [x] Add server-engine and API tests for pathfinding, movement, turn transitions, objective capture, session access, and stale actions, plus Django catalog/page smoke tests.
- [ ] Add automated tests for line of sight and combat as those systems are implemented.
- [ ] Test game editing and scenario links, server-loaded instances and action updates, turn rules, elevation traversal, unit stats and promotion, and enemy AI.
- [ ] Test the complete scenario in current desktop and mobile browsers and tune performance and balance.
- [ ] Document local setup, controls, asset workflow, and production build/deployment steps.
