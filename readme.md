# Siege of Greywatch

![Siege of Greywatch castle favicon](game/static/game/android-chrome-192x192.png)

**Siege of Greywatch** is a browser-playable, isometric medieval siege strategy prototype set in the Northern March in 1348. Lead an attacking company through the keep’s open southern gate and capture its courtyard.

> **Prototype status:** Movement, turn-taking, melee and ranged combat, health, morale, veteran promotion, elevation, projectile animation, cover, and courtyard capture are playable. Defenders move and attack automatically on end turn. Further encounter balancing remains future work.

The browser controller in `game/static/game/game.js` handles input, actions, and menus; `game/static/game/renderer.js` owns battlefield drawing, projection, and projectile effects.

## Play

- Select a soldier with a click. Hold **Shift** while clicking to add or remove soldiers from your selection.
- Click open ground to order selected soldiers to move; movement spends their move points.
- Raised tiles are marked with their height or a ladder/ramp symbol. Moving one level up or down requires a ladder or ramp on the higher tile; each step costs one move point. Melee attacks require both soldiers to be on the same level.
- Move a selected vanguard next to a defender, then click the defender to make a melee attack. Longbows and crossbows can fire at defenders within range through clear lines of sight, then must reload. Recruits have one fight point per turn. Health bars show remaining health.
- Ground-level soldiers beside a wall, tree, or rock on the shooter's side block the first ranged hit against them each turn. The shot still spends a fight point and triggers reload; later shots that turn deal damage. Moving or attacking from another direction can bypass cover. Melee ignores cover, and raised tiles do not receive cover from ground obstacles.
- Defeating an enemy raises the victor's morale by one (up to 5); nearby allies of a fallen soldier lose one (down to 0). Morale 0–1 reduces next turn's movement by one; morale 5 increases it by one. Select one recruit with 5 morale and press **Promote** to gain veteran rank, resetting morale to 3 and granting an extra move and fight point from the following turn.
- Select **End turn** to let defenders move and counterattack, restore your points, and advance courtyard capture. A nearby defender guards the objective, and defenders prioritize attackers capturing it when they can attack. Losing all attackers ends the battle.
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

Maps may include an optional `elevation` list of unique open tiles, for example `[{"x": 3, "y": 5, "height": 1, "access": "ramp"}, {"x": 4, "y": 5, "height": 2, "access": "ladder"}]`. Heights range from 1 to 3; `access` is optional and accepts `ramp` or `ladder`. Equal-height neighbors connect normally, but changing height by one requires access on the **higher** tile. Larger jumps are impassable. Place connectors so every starting unit can reach the objective. Existing maps without `elevation` remain flat; active matches keep their snapshotted maps until restarted.

Maps may also include up to 256 `objects`, such as `[{"x": 4, "y": 5, "type": "tree"}, {"x": 5, "y": 6, "type": "rock"}]`. Both types block movement and line of sight. Place them on distinct ground tiles, away from walls, the gate, elevation, starting units, and the objective; all units must still be able to reach the objective. Older maps without objects remain unchanged, and running matches retain their snapshot after edits.

Defender AI uses a local OpenAI-compatible service at `http://127.0.0.1:11435/v1`. Configure `SPLASH_API_KEY` in a local `.env` file when using that service; do not commit credentials.

## Development checks

```sh
.venv/bin/python3.12 manage.py test game
node --check game/static/game/game.js
node --test game/tests/test_playback.cjs
```

## Favicon

The game favicon is included above. Browser icon variants and the web manifest are in `game/static/game/`. The artwork is Twitter Twemoji castle graphic `1f3f0.svg`, licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). See [`game/static/game/favicon-attribution.txt`](game/static/game/favicon-attribution.txt) for the full attribution and source.
