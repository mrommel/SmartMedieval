# Agent guide

## Project

Siege of Greywatch is a Django-served, browser-playable isometric siege prototype. `TODO.md` tracks the implementation plan; the current playable milestone includes movement through the open gate, adjacent melee combat, and courtyard capture.

## Target design and remaining work

- Provide a game editor for creating single games and linking them to scenarios.
- Store editable game definitions on the server. Single games now own editable maps and rosters; active instances snapshot the selected definition, and scenarios link to available single games.
- Extend the current move-point/turn rules with morale and promotion to higher ranks with more points. Units now have health and fight points; adjacent melee attacks and defender counterattacks are implemented.
- Support elevation levels and movement between them via ladders and ramps. Exactly one opposing enemy side has units, moves on end turn, and automatically attacks: vanguards use adjacent melee and bow/crossbow units use ranged attacks through clear lines of sight with reload cooldowns. Projectile animation is not implemented yet.
- `game/enemy_ai.py` runs defender AI on the server using `http://127.0.0.1:11435/v1` and model `unsloth/Qwen3.8-27B-GGUF:UD-Q4_K_XL`. AI coordinates are goals; the engine routes defenders to legal destinations without entering the objective, and retries malformed orders once. The server reads `SPLASH_API_KEY` from `.env`; never send it to the client, log it, or commit it. An unavailable or persistently invalid AI response leaves the turn unchanged.

## Where to work

- `setup/` contains Django settings and project URLs; `game/` contains catalog models, views, URLs, migrations, and Django tests.
- `game/templates/game/game.html` is the launch/menu/battlefield page; `game/static/game/game.css` styles it.
- `game/static/game/game.js` handles canvas rendering, camera and pointer input, menus, and loading/sending actions; it does not advance game state on animation frames.
- `game/engine.py` owns editable map geometry, both rosters, pathfinding, move-point rules, turns, and capture. `GameInstance` persists state and a revision in SQLite; the current session controls access to the active instance.
- Catalog entries are exposed at `/api/scenarios/` and `/api/single-games/`. Migration `game/migrations/0001_initial.py` seeds an entry in each catalog. Starting a match uses `POST /api/games/<kind>/<entry_id>/start/`; `GET /api/games/current/` resumes it; `POST /api/games/actions/` applies a revisioned action. POST requests require CSRF.
- Authenticated staff edit single-game map JSON (cols, rows, keep, gate, objective, startPositions, enemyStartPositions) and link games to scenarios in `/admin/`. Older maps without enemyStartPositions spawn one defender near the objective; existing active matches keep their earlier state until restarted. A scenario launch selects a linked game with `single_game_id` in its JSON POST body; a sole linked game can be launched with `{}`. New instances snapshot the map so later edits do not change active matches.

## Local workflow

- Use Python 3.12 and the dependencies in `requirements.txt`. Run `make venv`, `make migrate`, and `make run` to serve the game at `http://127.0.0.1:8098/`.
- Run `make createsuperuser` to create an editor login, then open `/admin/`. Save a single game with a reachable objective before linking it to a scenario; only available linked games can be launched.
- Run `.venv/bin/python3.12 manage.py test game` for engine and API tests; use `node --check game/static/game/game.js` to check browser script syntax.
- When changing map geometry, update simulation walkability, pathfinding expectations, rendering, and pointer-to-tile behavior together. When changing catalog fields, update models, migrations, API serialization, UI, and tests together.
- Keep original placeholder art and any added assets' attribution/license information intact. Do not treat `.venv/`, `.idea/`, or the local `db.sqlite3` as source files to edit.
- The settings are development-only; do not rely on them for production deployment or put credentials in code or documentation.
