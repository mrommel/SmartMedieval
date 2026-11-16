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

- [x] Separate simulation state, input, pathfinding, rendering, and UI so each can evolve without coupling.
  - [x] Move prototype state, movement, capture, and pathfinding out of the browser UI into a testable server engine.
  - [x] Move battlefield rendering behind a renderer module.
  - [x] Isolate pointer/camera input and launch/catalog UI.
- [x] Add robust terrain collision, unit spacing, and map configuration for multiple strongpoints and elevation levels; allow units to climb between levels using ladders and ramps.
  - [x] Support optional elevated tiles, ladder/ramp traversal, height-aware melee, and raised-tile rendering and picking.
  - [x] Keep units on distinct tiles during movement and prevent paths through occupied tiles.
  - [x] Add multiple gated strongpoints and terrain collision beyond keep walls.
  - [x] Add editable map objects such as trees and rocks, with rendering and appropriate movement and line-of-sight collision.
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
  - [x] Keep a nearby garrison at the objective during AI movement and target capturing attackers first.
  - [x] Add wall, tree, and rock cover against ranged attacks with combat feedback.
  - [x] Add a gate-covering crossbow to the seeded assault and test that the gate must be cleared before capture.
  - [ ] Playtest and tune the encounter on desktop and mobile.
- [ ] Persist settings and add accessible controls, pause and animation-speed controls, and clear combat feedback.
  - [x] Add pause/resume, locally saved animation-speed controls, reduced-motion support, and damage/casualty feedback.
  - [x] Add keyboard-accessible battlefield orders.
  - [x] Add richer combat history: persist the latest 100 attacks and promotions, including casualties and morale changes, and show them in the battlefield sidebar.

## Medieval tactical expansion (inspired by UFO: Enemy Unknown)

- [x] Add a throne-room mission where attackers must reach the throne and capture the living king; make the king a unit, define capture range/action and guards, and distinguish capture from killing him in victory/defeat rules.
- [x] Add catapults as crewed siege equipment with limited ammunition, aiming, firing and reload costs, projectile impacts, and damage to units or fortifications.
- [x] Add an editable medieval village with houses, lanes, fences, wells, and other cover; define movement, visibility, and combat interactions for its structures (solid houses; entering buildings is the next milestone).
- [ ] Let units enter and navigate houses and castles across multiple floors, including basements and dungeons; connect levels with doors, stairs, ladders, and passages, and account for walls and floors in movement and line of sight.
  - [x] Add optional perimeter doors and walkable ground-floor house interiors with doorway-only movement, wall-aware combat and cutaway rendering; retain solid legacy houses.
- [ ] Make multi-level interiors readable and selectable in the isometric view with roof/floor cutaways and floor controls; allow routes from outside to rooms, upper floors, and underground spaces.
- [ ] Add discoverable hidden doors and passages, plus traps that can be spotted, disarmed, avoided, or triggered; include their effects in server-validated movement and enemy behavior.
- [ ] Let units pick up, drop, carry, and equip items from ground tiles, with inventory limits and turn-based action costs; make dropped gear recoverable after a casualty.
  - [x] Add server-owned ground potions, two-item carrying limits, fight-point-costed pickup/drop and casualty drops; general equipment remains to do.
- [x] Add consumable healing potions that units can carry, use on themselves or nearby allies, and find on the ground; cap healing at maximum health and consume the potion on use.
- [x] Replace unit classes with a weapon, a carried-tools list, and a separate king mission marker. Migrate saved rosters, active matches, and history, while still accepting imported legacy labels.
- [x] Show the selected soldier's current HP, morale, remaining movement/fight points, weapon, tools, potions, and reload/catapult status in a dedicated sidebar readout; refresh on selection and after each action.
- [x] Refine the selected-soldier UI with labeled stat rows and graphical remaining/max indicators, mobile styling and text equivalents for screen readers. Keep current-turn capacities separate from projected next-turn allowances after morale changes or promotion; test empty/group selections, zero points, reload, death, and resume.
- [ ] Manually review the selected-soldier panel on desktop/mobile screens and with a screen reader in a real browser.
- [ ] Add equippable armor with distinct protection and weight; apply protection consistently to melee and ranged damage.
- [ ] Make carried weight (including armor, weapons, and potions) affect movement-point costs or allowances, with clear limits and feedback before issuing orders.
- [ ] Add horseback riding: mount/dismount actions, mounted movement and melee, horse health and casualties, and terrain or doorway restrictions for horses.
- [ ] Give ground types such as roads, grass, mud, and swamp different movement costs and traversal rules for foot units and horses; have pathfinding choose routes by move-point cost, not just tile count.
- [ ] Preview the exact path, terrain costs, and turns required while hovering or selecting a destination; update the preview for occupancy, equipment weight, and mounted status, and distinguish unreachable tiles.
- [ ] Let units reserve move/fight points for reactions during the enemy turn, such as a bow shot or melee strike when a visible enemy enters range; show the reserved cost and eligible trigger area.
- [ ] Add fog of war and night battles: reveal only what allied units can see, and let torches, watchfires, and daylight affect detection and ambushes without revealing hidden enemies to the player.
- [ ] Add defensive stances such as crouching behind cover or raising a shield, with explicit action costs and trade-offs between protection, visibility, and movement.
- [ ] Add smoke and fire hazards that affect visibility, movement, and health; let fires spread through appropriate village or castle structures and provide ways to avoid or extinguish them.
- [ ] Expand injuries beyond lost health with temporary penalties and treatment, while retaining the existing casualty-driven morale and promotion rules.
- [ ] Support withdrawing surviving units through a designated exit and show a mission debrief with casualties, rescued villagers, prisoners, and recovered equipment.
- [ ] Add nonlethal capture of enemy commanders; use prisoners and recovered gear to reveal enemy plans or unlock new tactics and equipment through medieval interrogation and smithing.
- [ ] Carry surviving units, their experience, wounds, and equipment between linked battles so retreat and recovery have lasting consequences.
- [ ] Add a manageable camp or fortress with a smithy, infirmary, stores, and training ground for preparing units and crafting equipment between missions.
- [ ] Add a regional campaign in which protecting villages earns supplies and noble support while ignored raids escalate and threaten later missions.

Mechanics references: [UFO: Enemy Unknown gameplay](https://en.wikipedia.org/wiki/X-COM:_UFO_Defense#Gameplay), [terror missions](https://www.ufopaedia.org/Terror_Mission), [research](https://www.ufopaedia.org/Research), and [persistent soldiers](https://www.ufopaedia.org/Soldiers).

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
