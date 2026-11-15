# Siege of Greywatch

![Siege of Greywatch castle favicon](game/static/game/android-chrome-192x192.png)

**Siege of Greywatch** is a browser-playable, isometric medieval siege strategy prototype set in the Northern March in 1348. Lead an attacking company through the keep’s open southern gate and capture its courtyard.

> **Prototype status:** Movement, turn-taking, melee combat, health, fight points, and courtyard capture are playable. Combat currently supports adjacent melee attacks and automatic defender counterattacks; ranged attacks, line of sight, morale, and promotion remain future work.

## Play

- Select a soldier with a click. Hold **Shift** while clicking to add or remove soldiers from your selection.
- Click open ground to order selected soldiers to move; movement spends their move points.
- Move a selected soldier next to a defender, then click the defender to make a melee attack; each soldier has one fight point per turn. Health bars show remaining health.
- Select **End turn** to let defenders move and counterattack, restore your points, and advance courtyard capture. Losing all attackers ends the battle.
- Drag the battlefield to pan. Use the mouse wheel or the **+ / −** buttons to zoom.

## Run locally

Requires Python 3.12. From the project root:

```sh
make venv
make migrate
make run
```

Open <http://127.0.0.1:8098/>. The project uses Django and SQLite; dependencies are listed in `requirements.txt`.

To edit game definitions and link single games to scenarios, create a staff account with `make createsuperuser` and visit <http://127.0.0.1:8098/admin/>. A single game needs a reachable objective before it can be linked to a scenario.

Defender AI uses a local OpenAI-compatible service at `http://127.0.0.1:11435/v1`. Configure `SPLASH_API_KEY` in a local `.env` file when using that service; do not commit credentials.

## Development checks

```sh
.venv/bin/python3.12 manage.py test game
node --check game/static/game/game.js
```

## Favicon

The game favicon is included above. Browser icon variants and the web manifest are in `game/static/game/`. The artwork is Twitter Twemoji castle graphic `1f3f0.svg`, licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). See [`game/static/game/favicon-attribution.txt`](game/static/game/favicon-attribution.txt) for the full attribution and source.

