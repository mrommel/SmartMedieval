import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings

from .engine import InvalidAction, apply_action, resolve_defender_goals


AI_URL = "http://127.0.0.1:11435/v1/chat/completions"
AI_MODEL = "unsloth/Qwen3.8-27B-GGUF:UD-Q4_K_XL"


class EnemyAIError(Exception):
    def __init__(self, message, status_code=502):
        super().__init__(message)
        self.status_code = status_code


def enemy_turn(state, map_data):
    defenders = [unit for unit in state["units"] if unit.get("side") == "defenders"]
    if not defenders:
        return apply_action(state, {"type": "end_turn"}, map_data)
    if not settings.ENEMY_AI_API_KEY:
        raise EnemyAIError("Enemy AI is not configured. Set SPLASH_API_KEY in .env.", 503)

    battlefield = {
        "map": {key: map_data[key] for key in ("cols", "rows", "keep", "gate", "objective")},
        "units": [
            {key: unit[key] for key in ("id", "side", "x", "y")}
            for unit in state["units"]
        ],
    }
    request_data = {
        "model": AI_MODEL,
        "messages": [
            {"role": "system", "content": (
                "You command only defenders in a turn-based siege. Return a JSON object with an "
                "'orders' array of {\"unit_id\": integer, \"x\": integer, \"y\": integer}. "
                "Each x,y is a goal inside the map, not a final destination. The server moves "
                "the defender up to 4 steps toward it, avoiding walls and stopping short of the "
                "objective. A defender may aim at the objective but cannot occupy it. After "
                "movement, defenders automatically make one melee attack against an adjacent "
                "attacker when possible. "
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
                legal_orders = resolve_defender_goals(state, orders, map_data)
                return apply_action(state, {"type": "end_turn"}, map_data, enemy_orders=legal_orders)
            except InvalidAction as error:
                failure = f"Enemy AI returned an invalid order: {error}"
                if attempt:
                    raise EnemyAIError(failure) from error
        request_data["messages"][1]["content"] = (
            json.dumps(battlefield) + f"\nYour previous answer was rejected: {failure}. "
            "Choose only defender unit IDs and integer x,y goals inside the map, or omit the unit. "
            "Return a valid JSON orders array.\n/no_think"
        )
