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
  - [x] Support optional elevated tiles, ladder/ramp traversal, height-aware melee, and raised-tile rendering and picking.
  - [x] Keep units on distinct tiles during movement and prevent paths through occupied tiles.
  - [ ] Add multiple strongpoints and terrain collision beyond keep walls.
  - [ ] Add editable map objects such as trees and rocks, with rendering and appropriate movement and line-of-sight collision.
- [x] Add camera pan and zoom with pointer dragging, wheel input, and accessible zoom buttons.
- [x] Give units turn-based move points that are spent on movement and restored at turn end.
- [ ] Complete unit stats and turn-based combat rules.
  - [x] Add health, one fight point per turn, adjacent melee attacks, defender counterattacks, casualties, and defeat state.
  - [x] Add casualty-driven morale and veteran promotion effects to unit stats.
- [x] Allow recruits with full morale to promote to veteran with increased move and fight allowances.
- [ ] Extend combat with bow and crossbow ranges, reload times, projectile motion, and line-of-sight checks.
  - [x] Add server-validated bow/crossbow attacks with wall-blocked line of sight, weapon ranges, reloads, and defender ranged attacks.
  - [x] Animate arrows and bolts as projectiles.
- [ ] Add defender behavior, cover and wall advantages, capture/defeat states, and a tuned playable encounter.
- [ ] Persist settings and add accessible controls, pause and animation-speed controls, and clear combat feedback.
  - [x] Add pause/resume, locally saved animation-speed controls, reduced-motion support, and damage/casualty feedback.
  - [x] Add keyboard-accessible battlefield orders.
  - [x] Add richer combat history: persist the latest 100 attacks and promotions, including casualties and morale changes, and show them in the battlefield sidebar.

## Asset creation

- [ ] Set an original visual direction, palette, tile scale, and asset naming/manifest conventions.
- [ ] Create terrain, road, wall, gate, tower, castle moat, drawbridge, battlements, courtyard, objective, tree, and rock art as modular isometric tiles and objects.
- [ ] Create original directional attacker/defender sprites with idle, walk, attack, hit, and defeat animations.
- [ ] Create weapons, arrows/bolts, selection indicators, health bars, UI icons, and lightweight combat audio.
- [ ] Keep editable source assets, optimized browser exports, and a record of licenses/attributions for any external material.
- [ ] Replace the milestone's procedural placeholder drawings incrementally and confirm visual clarity at desktop and mobile sizes.

## Release and validation

- [x] Add server-engine and API tests for pathfinding, movement, turn transitions, objective capture, session access, and stale actions, plus Django catalog/page smoke tests.
- [x] Add automated tests for morale and promotion as those systems are implemented.
  - [x] Add automated tests for line of sight, ranged combat, and reload timing.
- [ ] Test game editing and scenario links, server-loaded instances and action updates, turn rules, elevation traversal, unit stats and promotion, and enemy AI.
  - [x] Add engine tests for elevation validation, climbing, descending, capture, and defender movement.
- [ ] Test the complete scenario in current desktop and mobile browsers and tune performance and balance.
- [ ] Document local setup, controls, asset workflow, and production build/deployment steps.
