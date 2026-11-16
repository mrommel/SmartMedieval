# Siege of Greywatch

![Siege of Greywatch castle favicon](game/static/game/android-chrome-192x192.png)

**Siege of Greywatch** is a browser-playable, isometric medieval siege strategy prototype set in the Northern March in 1348. Lead an attacking company through the keep’s open southern gate and capture its courtyard.

> **Prototype status:** Movement, turn-taking, melee and ranged combat, equippable armor, carried-weight and terrain-cost movement, horseback riding, catapults and wall breaches, health, morale, veteran promotion, elevation, projectile animation, cover, courtyard capture, a throne-room mission, and a village with enterable ground-floor houses and healing potions are playable. Defenders move and attack automatically on end turn. The assault has received an initial balance pass; desktop and mobile playtesting remains future work.

The browser controller in `game/static/game/game.js` handles input, actions, and menus; `game/static/game/renderer.js` owns battlefield drawing, projection, and projectile effects.

## Play

- Select a soldier with a click. Hold **Shift** while clicking to add or remove soldiers from your selection.
- Click open ground to order selected soldiers to move; movement spends their move points.
- Raised tiles are marked with their height or a ladder/ramp symbol. Moving one level up or down requires a ladder or ramp on the higher tile; unmarked tiles cost one move point to enter. Melee attacks require both soldiers to be on the same level.
- Move a selected sword-bearing soldier next to a defender, then click the defender to make a melee attack. Soldiers with longbows and crossbows can fire at defenders within range through clear lines of sight, then must reload. Recruits have one fight point per turn. Health bars show remaining health; the selected-soldier panel has labeled bars for health, morale and remaining/current-turn movement and fight points, plus weapon, armor, tools, potions and reload status. Its projected next-turn points reflect the soldier's current morale, rank and load, not points already available this turn. Older saved matches without current-turn capacity data show remaining points without an estimated bar until their next turn.
- Ground-level soldiers beside a wall, tree, or rock on the shooter's side block the first ranged hit against them each turn. The shot still spends a fight point and triggers reload; later shots that turn deal damage. Moving or attacking from another direction can bypass cover. Melee ignores cover, and raised tiles do not receive cover from ground obstacles.
- Starting armor is worn by default: leather (weight 1) absorbs the first 1 damage each turn; mail (weight 3) absorbs the first 2. Armor applies to melee, ranged hits and catapult stones on either side. Cover blocks a shot before armor is spent. Select a single armored attacker and press **Remove armor** or **Equip armor** for one fight point; re-equipping does not replenish spent protection. Removed armor still counts toward carried weight.
- A sword weighs 1, longbow 2, crossbow 3, leather 1, mail 3, and each tool or potion 1. Every 3 weight reduces movement allowance by 1 MP per turn, to a minimum of 1 MP. A soldier may carry at most 8 weight and 2 potions. Picking up, dropping or using a potion immediately adjusts this turn's remaining movement without undoing MP already spent. The selected-soldier panel displays load, penalty and current/next-turn allowances; hovering a destination or using keyboard focus previews the cheapest route, its MP cost and turns required. A costly tile must be entered in one turn; troops with too little MP per turn must go around it.
- In **Greywatch Hamlet**, the first soldier starts on a horse. Select them and press **Mount** (one fight point). A mounted soldier has 6 base MP instead of 4 and ignores the load movement penalty, but still carries their equipment and keeps morale/rank movement bonuses. Mounted sword melee deals 2 damage. On horseback, road costs 1 MP, grass 2, mud 4, and unmarked tiles 1; swamps, houses and ladders cannot be crossed, but ramps can. A rider cannot crew a catapult. **Dismount** costs one fight point and leaves the horse on the soldier's tile for reuse. Incoming hits strike the mounted horse first (2 HP); if it dies, the rider survives on foot. Cover still blocks the first eligible ranged hit before it reaches the horse.
- Defeating an enemy raises the victor's morale by one (up to 5); nearby allies of a fallen soldier lose one (down to 0). Morale 0–1 reduces next turn's movement by one; morale 5 increases it by one. Select one recruit with 5 morale and press **Promote** to gain veteran rank, resetting morale to 3 and granting an extra move and fight point from the following turn.
- Select **End turn** to let defenders move and counterattack, restore your points, and advance courtyard capture. A nearby defender guards the objective, and defenders prioritize attackers capturing it when they can attack. Losing all attackers ends the battle.
- In **Greywatch Assault**, a crossbow guard holds the inside of the southern gate. Clear the gate under fire or use the catapult to breach a different section of wall before taking the courtyard.
- In **Greywatch Hamlet**, take the village roads around houses and fenced yards to avoid the muddy and swampy shortcut on the way to the keep. Your first soldier wears leather; the first defender wears mail. Houses marked **D** have ground-floor doors: click a door or an interior floor tile to enter, move through the room, or exit through the same door. An open-roof cutaway keeps occupants visible and selectable. House walls block shots between inside and outside, including at the door; soldiers can fight in the same room or use melee across the doorway. Other houses remain solid. Wells, trees and rocks block walking and shots; fences block walking but shots can pass over them. Exterior obstacles provide cover to a ground-level unit beside them on the shooter's side.
- Hamlet also has red healing potions, one beneath your first soldier and another inside a house. Select a soldier standing on a potion and press **Pick up potion** (one fight point). A soldier carries at most two potions if the weight limit allows it. To heal, select the carrier, choose a wounded self or adjacent ally in the healing target selector, and press **Heal** (one fight point, restores up to two health without exceeding maximum). **Drop potion** costs one fight point; potions carried by fallen soldiers can be recovered from their tile. House walls and height differences prevent healing across them unless the soldier stands at the doorway.
- In **The Throne Room**, bring a sword-bearing soldier next to the king at the same height and clear any guards standing beside him. Select the soldier and press **Capture king** (or click the king when capture is available) to spend a fight point and win. The king stays on his throne and cannot attack. Killing him, even with a ranged shot, loses the mission; occupying the throne or killing all the guards does not win by itself.
- The seeded assault has a catapult under its second sword-bearing soldier. Select a soldier standing on a catapult, press **Aim catapult** and choose a target tile (walls included), then press **Fire catapult** once the crew has a fight point. Aiming and firing each spend one fight point; recruits can fire on the next turn. Each catapult carries three stones, takes two turn transitions to reload, and hits anyone on its target tile for two damage, including allies and the king. Two hits on a wall tile breach it, opening a passage and line of sight.
- Drag the battlefield to pan. Use the mouse wheel or the **+ / −** buttons to zoom.
- Select **Pause** to freeze animations and prevent new orders; orders already sent to the server still finish. Select **Resume** to continue. The **Animation speed** selector supports Off, 0.5×, 1× and 2× and is saved on your device. The device's reduced-motion preference also turns animations off.

## Run locally

Requires Python 3.12. From the project root:

```sh
make venv
make migrate
make run
```

Open <http://127.0.0.1:8098/>. The project uses Django and SQLite; dependencies are listed in `requirements.txt`.

To edit game definitions and link single games to scenarios, create a staff account with `make createsuperuser` and visit <http://127.0.0.1:8098/admin/>. A single game needs a reachable objective before it can be linked to a scenario.

Starting soldiers have no unit class. In `startPositions` and `enemyStartPositions`, use `{"x": 2, "y": 6, "weapon": "sword", "tools": ["rope"], "armor": "leather"}`. Supported weapons are `sword`, `longbow`, and `crossbow`; `tools` is an optional list of up to two carried labels (not yet usable equipment). Optional `armor` is `"leather"` or `"mail"`; omit it for no armor. Armor starts equipped, and existing active matches remain unarmored until restarted with an updated definition. The server tracks potions separately as items. `make migrate` converts older saved maps and matches from `"type": "vanguard"`, `"longbow"`, or `"crossbow"`; imported legacy definitions are still accepted and converted on edit or match launch.

Maps may include an optional `elevation` list of unique open tiles, for example `[{"x": 3, "y": 5, "height": 1, "access": "ramp"}, {"x": 4, "y": 5, "height": 2, "access": "ladder"}]`. Heights range from 1 to 3; `access` is optional and accepts `ramp` or `ladder`. Equal-height neighbors connect normally, but changing height by one requires access on the **higher** tile. Larger jumps are impassable. Place connectors so every starting unit can reach the objective. Existing maps without `elevation` remain flat; active matches keep their snapshotted maps until restarted.

Maps may also include up to 256 `objects`, such as `[{"x": 4, "y": 5, "type": "tree"}, {"x": 5, "y": 6, "type": "rock"}]`. Both types block movement and line of sight. Place them on distinct ground tiles, away from walls, the gate, elevation, starting units, and the objective; all units must still be able to reach the objective. Older maps without objects remain unchanged, and running matches retain their snapshot after edits.

Maps may include up to 16 additional `strongpoints`, for example `[{"left": 6, "right": 9, "top": 3, "bottom": 6, "gate": {"x": 7, "y": 6}}]`. Each rectangle needs its own gate on its perimeter and must not overlap the keep or another strongpoint. Its walls block movement and shots and provide cover just like keep walls; the interior and gate remain walkable. Keep objects, elevation, starting units, and the objective off the walls, and ensure every starting unit can reach the objective. Maps without `strongpoints` retain their existing layout; ongoing matches retain their map snapshot.

To author a village, add up to 32 `houses` as rectangular footprints of 2–4 tiles on each side, such as `[{"left": 6, "right": 8, "top": 2, "bottom": 4, "door": {"x": 7, "y": 4}}]`. The optional door must be on the perimeter with an unobstructed exterior neighbor. A house without a door remains solid and blocks movement and shots. With a door, its ground-floor tiles become walkable but can only be entered or exited through that door. House walls block ranged attacks even at the door, and stop melee except across the doorway. The roof-cutaway floor is always visible; upper floors and basements are not yet supported. Houses cannot overlap the keep, strongpoints or each other and cannot contain starting units, objects, elevated tiles, catapults or the objective; exterior house walls still provide ranged cover. Use optional `lanes`, for example `[{"x": 5, "y": 7}]`, to mark unique open, flat ground tiles as paths; lane movement costs remain unchanged. The existing `objects` list also accepts `fence` and `well` alongside `tree` and `rock`. Fences block movement but not line of sight; wells block both. All objects provide ranged cover when adjacent to the target on the shooter's side. Map validation rejects obstructed routes from any starting position to the objective. The seeded **Through the Hamlet** scenario demonstrates these fields. Older maps omit them and ongoing matches keep their original map snapshots.

Optional `terrain` assigns distinct outdoor tiles a movement cost on entry: `[{"x": 5, "y": 7, "type": "road"}, {"x": 6, "y": 6, "type": "swamp"}]`. Road costs 1 MP, grass 2, mud 3, and swamp 4; unmarked tiles and old maps cost 1 MP. Terrain cannot cover walls, objects, houses or elevation; it may overlap visual `lanes`. Routes and defender orders use total MP rather than shortest tile count, and map validation requires a route the starting unit can traverse with its weight-adjusted allowance. Changes to map definitions do not affect ongoing matches.

Optional `horses` places up to 16 distinct horses on open, flat outdoor tiles, e.g. `[{"x": 2, "y": 6}]`. They may share a starting soldier's tile but not an objective, obstacle, house or swamp. Horses are tracked separately in each match, so editing the map does not move horses in ongoing matches. Old maps and matches without horses remain playable.

Optional `catapults` are a list of up to 16 distinct open ground positions, such as `[{"x": 3, "y": 7}]`. They may overlap starting soldiers but not walls, objects, elevated tiles or the objective. The match stores their ammunition and aim separately from the map; edited layouts do not affect ongoing matches.

Optional `items` is a list of up to 32 healing potions, for example `[{"x": 2, "y": 6, "type": "healing_potion"}]`. Place them on distinct walkable ground tiles (including enterable house floors); starting units may stand on them. Each match snapshots its map and tracks ground/carried potions separately, so a saved match keeps its own supply after edits. Older maps and matches without items still work. Recoverable equipment remains future work.

To author a throne-room game, set `"mission": "capture_king"` in its map JSON, put the `objective` on an open tile strictly inside the keep, and include `enemyStartPositions` with **exactly one** `{"x": ..., "y": ..., "weapon": null, "is_king": true}` on the objective plus at least one sword-, longbow-, or crossbow-bearing defender on a different tile. `is_king` is a mission-specific flag, not a unit class. Existing maps with a `"type": "king"` start position are supported. Maps without `mission` retain courtyard capture rules. The seeded **Capture the King** scenario and **The Throne Room** single game demonstrate this format.

Defender AI uses a local OpenAI-compatible service at `http://127.0.0.1:11435/v1`. Configure `SPLASH_API_KEY` in a local `.env` file when using that service; do not commit credentials.

## Development checks

```sh
.venv/bin/python3.12 manage.py test game
node --check game/static/game/game.js
node --test game/tests/test_playback.cjs
```

## Favicon

The game favicon is included above. Browser icon variants and the web manifest are in `game/static/game/`. The artwork is Twitter Twemoji castle graphic `1f3f0.svg`, licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). See [`game/static/game/favicon-attribution.txt`](game/static/game/favicon-attribution.txt) for the full attribution and source.
