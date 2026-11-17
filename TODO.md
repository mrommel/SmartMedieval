# Siege of Greywatch — implementation plan

Check off only shipped, tested behavior. The **Completed baseline** records existing features; the open lists below are remaining work, not claims that their parent systems are absent. See [AGENTS.md](AGENTS.md) for detailed current mechanics and [readme.md](readme.md) for setup and controls.

## Next milestone: playable-quality validation

- [ ] Play the seeded assault, throne-room, hamlet, reconnaissance, night-watch and shieldwall games in current desktop and mobile browsers. Check routes, turn progression, balance, AI wait time, combat feedback, selection and performance; record and fix reproducible problems before declaring the encounter tuned.
- [ ] Manually review the selected-soldier panel and battlefield with keyboard-only input, a real screen reader and reduced motion at desktop/mobile sizes. Verify focus order, spoken status changes, controls, zoom and selection; fix any issues. Automated keyboard/ARIA assertions are not a substitute for this review.
- [ ] Expand integration/regression checks around the complete editor → link → launch → play → resume flow, especially legacy match snapshots, AI failures/retries, fog-safe responses and mobile interactions. Editor, engine, API and browser tests already exist; add targeted tests for gaps uncovered by the manual review rather than reimplementing existing coverage.
- [ ] Measure and tune the local defender AI wait time on real devices. When AI fails, the turn now stays unchanged and offers retry or an explicit offline end turn: defenders hold position but still attack and other turn effects run. Credentials remain server-side.
- [ ] Decide whether preferences besides animation speed should persist locally; pause/resume, speed selection, reduced motion, keyboard orders and combat history are already implemented.

## Tactical expansion

### Interiors, exploration and equipment

- [ ] Model walkable multi-floor house **and castle** interiors, including upper floors, basements and dungeons. Define stairs, ladders, doors and passages, floor/wall collision, route costs, line of sight, AI and combat across levels. Ground-floor house doors and hidden-door discovery already work.
- [ ] Add isometric floor selection, roof/floor cutaways and picking/route previews for indoor and underground spaces; make transitions from outside to rooms and between floors readable and keyboard-accessible.
- [ ] Add discoverable hidden passages and traps: spotting, disarming, avoidance, triggering, effects and fog-safe server/AI behavior. Hidden house doors are already supported.
- [ ] Specify and implement effects for tools beyond rope, torch and shield; document action costs, inventory limits, AI interactions and tests for each new tool. Ground item authoring, carrying, dropping and casualty recovery already work.
- [ ] When flammable castle interiors exist, extend the current grass/wooden-house fire rules to those materials and test spreading, extinguishing and visibility across floors. Fire already spreads on grass and enterable house floors; smoke, damage and extinguishing are implemented.

### Outdoor map authoring

- [ ] Design connected rivers (banks/crossings), vegetation (pine, cactus, willow, hedges, flowers), sloped hills and new terrain (swamp, desert, gravel, grass, plains). Decide tile versus edge placement, decorative versus blocking features, movement costs, sight/cover, fire and horse restrictions; preserve existing road/mud rules.
- [ ] Extend the map schema and validation for joined river segments, crossings, continuous adjacent slopes and terrain on hills. Reject invalid overlap with map bounds, walls, houses, objectives, starts, objects and elevation; keep older authored maps and active match snapshots playable.
- [ ] Update pathfinding, defender AI, line of sight, fog snapshots, movement costs and route previews for the new features; test foot/mounted routes, crossings, elevation and mixed terrain in engine and API tests.
- [ ] Render joined rivers, crossings, vegetation, flowers, hill faces/slopes and each ground type; keep isometric picking and route highlights accurate, with renderer/browser tests.
- [ ] Improve the admin JSON authoring workflow with placement guidance, understandable validation errors, a map preview and a way to test a saved game. Document how to duplicate/create a single game, set bounds/keep/objective/rosters, lay out terrain and rivers, resolve reachability errors, link a scenario, launch and playtest; restart matches to see edits.

## Later: persistent campaign

- [ ] Add mission mechanics for rescuing villagers and taking commanders prisoner without killing them; include rescued people, prisoners and recovered gear in debriefs. Exit-based withdrawal and survivor/casualty/equipment debriefs already exist.
- [ ] Carry survivors, rank/experience, wounds and equipment between linked battles. Define roster persistence, recovery after retreat/defeat and migration/compatibility for standalone games; only temporary in-battle wounds are implemented today.
- [ ] Add camp/fortress preparation: stores, smithy/crafting, infirmary treatment and training. Let prisoners and recovered equipment inform tactics or unlock gear through interrogation/smithing.
- [ ] Build a regional campaign in which defended villages supply resources and noble support, while ignored raids escalate and affect later missions.

## Art and audio

- [ ] Set an original visual direction, palette, tile scale and asset naming/manifest conventions.
- [ ] Produce modular isometric terrain, road, wall, gate, tower, moat, drawbridge, battlements, courtyard, objective, tree and rock art; add new outdoor/interior assets as their mechanics land.
- [ ] Produce original directional attacker/defender sprites with idle, walk, attack, hit and defeat animations.
- [ ] Produce weapons, arrows/bolts, selection indicators, health bars, UI icons and lightweight combat audio.
- [ ] Keep editable source assets, optimized browser exports and licenses/attributions for any external material.
- [ ] Replace procedural placeholders incrementally; confirm readability at desktop/mobile sizes and with the planned floor controls.

## Release and documentation

- [ ] Document the asset workflow and a production deployment/build procedure. Local setup and controls are already in the README; Django settings are development-only, so production needs environment-managed secrets, DEBUG/host/static-file configuration and a deployment security review before publishing.
- [ ] Run engine/API/editor and browser-interaction tests, JS syntax checks and the manual desktop/mobile/accessibility playtest on each release candidate; resolve regressions and tune performance/balance.

## Completed baseline

- [x] Django-served isometric canvas prototype with original placeholder art, six attackers, individual/group selection, click/keyboard movement, pan/zoom, open-gate routing and courtyard capture; start/restart flow and responsive UI.
- [x] Seeded scenario/single-game catalog, staff admin map/roster editing and scenario links; session-owned, revisioned server instances that snapshot definitions, validate actions and support resume. Engine, renderer, input and launch UI are separated.
- [x] Turn-based move/fight points, health, melee/counterattacks, ranged bow/crossbow attacks with reloads and animated projectiles, casualties, morale and veteran promotion, cover, history, capture/defeat and objective-guarding defender AI. The local model can fail without committing a partial turn.
- [x] Gated strongpoints, elevation with ladders/ramps, objects and collision; a village with lanes, fences, wells, ground-floor enterable houses and discoverable hidden doors; cheapest-MP road/grass/mud/swamp routing for foot/mounted soldiers and exact route/turn previews.
- [x] Throne-room capture-king mission, catapult ammunition/aim/reload/wall breaches, impact smoke and spreading grass/house fire with damage and extinguishing.
- [x] Weapons, armor, tools, potions, load limits, dropped/recoverable casualty gear and rope climbing; mounted movement/combat, horse casualties, temporary wounds and potion treatment.
- [x] Daylight/night fog with shared sight, torches, toggled watchfires and ambush damage; crouching, raised shields, reserved attack reactions and reserved-movement evasions.
- [x] Authored exit/withdrawal and debrief for evacuated/fallen soldiers and their equipment; selected-soldier status, combat feedback, pause/resume, saved animation speed and reduced-motion support.
- [x] Automated engine, editor, catalog, API and browser-controller tests cover many of these mechanics, including fire spreading and AI error handling; manual full-scenario and accessibility validation remains open above.

Mechanics references: [UFO: Enemy Unknown gameplay](https://en.wikipedia.org/wiki/X-COM:_UFO_Defense#Gameplay), [terror missions](https://www.ufopaedia.org/Terror_Mission), [research](https://www.ufopaedia.org/Research) and [persistent soldiers](https://www.ufopaedia.org/Soldiers).
