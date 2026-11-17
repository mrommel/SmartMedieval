import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings

from .engine import (STARTING_MORALE, InvalidAction, apply_action, armor_remaining, battle_map,
                     normalize_unit, resolve_defender_goals, visible_tiles)


AI_URL = "http://127.0.0.1:11435/v1/chat/completions"
AI_MODEL = "unsloth/Qwen3.8-27B-GGUF:UD-Q4_K_XL"


class EnemyAIError(Exception):
    def __init__(self, message, status_code=502):
        super().__init__(message)
        self.status_code = status_code


def enemy_turn(state, map_data, combat_events=None):
    defenders = [unit for unit in state["units"]
                 if unit.get("side") == "defenders" and not normalize_unit(unit).get("is_king")]
    if not defenders:
        return apply_action(state, {"type": "end_turn"}, map_data, combat_events=combat_events)
    if not settings.ENEMY_AI_API_KEY:
        raise EnemyAIError("Enemy AI is not configured. Set SPLASH_API_KEY in .env.", 503)

    sight = visible_tiles(state, map_data, "defenders") if map_data.get("fog_of_war", False) else None
    battlefield = {
        "map": {key: map_data[key] for key in ("cols", "rows", "keep", "gate", "objective")}
               | {"elevation": map_data.get("elevation", []), "objects": map_data.get("objects", []),
                   "strongpoints": map_data.get("strongpoints", []),
                   "houses": map_data.get("houses", []), "lanes": map_data.get("lanes", []),
                   "terrain": map_data.get("terrain", []),
                   "fog_of_war": map_data.get("fog_of_war", False),
                   "night": map_data.get("night", False),
                   "watchfires": [fire for fire in map_data.get("watchfires", [])
                                  if fire not in state.get("extinguished_watchfires", [])],
                   "mission": map_data.get("mission", "courtyard"),
                    "breaches": state.get("breaches", []),
                     "smoke": [cloud for cloud in state.get("smoke", [])
                               if sight is None or (cloud["x"], cloud["y"]) in sight],
                     "fire": [flame for flame in state.get("fire", [])
                              if sight is None or (flame["x"], flame["y"]) in sight]},
        "units": [
            {key: unit.get(key) for key in (
                "id", "side", "weapon", "tools", "armor", "armor_equipped", "is_king", "x", "y", "health", "fight_points", "reload_turns",
                "move_points", "z", "mount_id",
            )} | {"morale": unit.get("morale", STARTING_MORALE), "rank": unit.get("rank", "recruit"),
                  "armor_remaining": armor_remaining(unit, state["turn"])}
            for unit in (normalize_unit(value) for value in state["units"])
            if sight is None or unit.get("side", "attackers") == "defenders" or (unit["x"], unit["y"]) in sight
        ],
        "horses": [horse for horse in state.get("horses", [])
                   if sight is None or horse["rider_id"] is None or (horse["x"], horse["y"]) in sight],
    }
    request_data = {
        "model": AI_MODEL,
        "messages": [
            {"role": "system", "content": (
                "You command only defenders in a turn-based siege. Return a JSON object with an "
                "'orders' array of {\"unit_id\": integer, \"x\": integer, \"y\": integer}. "
                "Each x,y is a goal inside the map, not a final destination. The server moves "
                "the defender up to its move allowance toward it (normally 4, minus 1 at morale "
                "0-1 or plus 1 at morale 5, and reduced by carried weight), avoiding walls and "
                "occupied tiles and stopping short of the "
                "objective. A defender may aim at the objective but cannot occupy it. Elevated "
                "tiles have height 1-3; only ladders and ramps on the higher tile permit a "
                "one-level step. Wall tiles listed in breaches are open passages. After "
                "movement, defenders automatically attack when possible: soldiers with swords make melee "
                "attacks against adjacent attackers; longbows have range 5 and crossbows range 6, "
                "with walls, houses, trees, rocks, and wells blocking line of sight and movement. "
                "Catapult impacts leave smoke for two turn transitions; smoke blocks sight and "
                "ranged attacks, including shots from within it, but not movement. "
                 "Impacts on grass or enterable wooden house floors ignite fires lasting three "
                 "transitions, spreading to adjacent grass or floors in the same house. Fire "
                 "blocks sight, adds two MP to entry cost and burns occupants for one damage. "
                "Houses without doors are solid; houses with a door have walkable ground-floor tiles, "
                "but entering and leaving is possible only through the perimeter door tile. "
                "Shots cannot cross house walls even at doors; units in the same room can shoot each other. "
                "Movement costs 1 point per unmarked tile or road, 2 on grass, 3 on mud "
                "and 4 on swamp; a tile's full cost must fit in one turn. Lanes are visual only. Fences block "
                "movement but not shots. Ranged weapons "
                "need one or two full turns to reload. Prefer goals that bring ranged defenders "
                "within a clear shot. Ground-level units beside a wall, tree, or rock on the "
                "shooter-facing side (including fences, houses and wells) block the first "
                "ranged hit against them each turn; melee "
                "ignores cover. Keep at least one defender near the objective when one is "
                "already nearby; prioritize attackers occupying the objective. In a capture_king "
                "mission the king stays on the throne, never moves or attacks, and cannot be "
                "ordered; keep guards adjacent to him to prevent capture, and attack nearby "
                "soldiers with swords before they can capture him. "
                "On fog_of_war maps the units list contains only attackers currently in sight; "
                "do not infer the locations of hidden attackers from their absence. "
                "Defenders can only attack attackers currently visible to their team. At night, unlit "
                "sight is two steps; a torch extends its carrier's sight to five but exposes that "
                "carrier within six clear steps, and watchfires illuminate tiles within three steps. "
                "On fog maps, melee and ranged attacks from a soldier unseen by the target's team "
                "deal one extra damage; cover and armor still apply, but catapults do not ambush. "
                "Equipped leather absorbs one damage per turn and mail absorbs two; cover blocks the first "
                "ranged hit before armor. Armor also protects against melee and catapult hits. "
                "A mounted attacker has six base movement points, cannot enter houses or swamps, "
                "deals two sword melee damage, and takes hits on the horse (two health) before the rider. "
                "Issue at most 8 orders and at most one per defender. "
                "Omit units that should hold position. Do not issue attacker orders."
            )},
            {"role": "user", "content": json.dumps(battlefield) + "\n/no_think"},
        ],
        "response_format": {"type": "json_object"},
        "chat_template_kwargs": {"enable_thinking": False},
        "temperature": 0,
        "max_tokens": 1024,
    }
    for attempt in range(2):
        request = Request(
            AI_URL,
            data=json.dumps(request_data).encode("utf-8"),
            headers={"Authorization": f"Bearer {settings.ENEMY_AI_API_KEY}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=90) as response:
                body = response.read(65537)
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            raise EnemyAIError("Enemy AI is unavailable. Try ending the turn again.", 503) from error
        if len(body) > 65536:
            raise EnemyAIError("Enemy AI returned an oversized response.")
        try:
            content = json.loads(body)["choices"][0]["message"]["content"]
            orders = json.loads(content)["orders"]
        except (ValueError, KeyError, IndexError, TypeError) as error:
            failure = "Enemy AI returned an invalid response."
            if attempt:
                raise EnemyAIError(failure) from error
        else:
            try:
                legal_orders = resolve_defender_goals(state, orders, battle_map(map_data, state))
                return apply_action(state, {"type": "end_turn"}, map_data, enemy_orders=legal_orders,
                                    combat_events=combat_events)
            except InvalidAction as error:
                failure = f"Enemy AI returned an invalid order: {error}"
                if attempt:
                    raise EnemyAIError(failure) from error
        request_data["messages"][1]["content"] = (
            json.dumps(battlefield) + f"\nYour previous answer was rejected: {failure}. "
            "Choose only defender unit IDs and integer x,y goals inside the map, or omit the unit. "
            "Return a valid JSON orders array.\n/no_think"
        )
