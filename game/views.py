import json

from django.db.models import F
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .enemy_ai import EnemyAIError, enemy_turn
from .engine import (MAX_CARRY_WEIGHT, InvalidAction, apply_action, armor_remaining, capture_status,
                     carried_weight, fight_allowance, initial_state, move_allowance,
                     normalize_history_event, normalize_map, normalize_unit, visible_tiles, weight_penalty)
from .models import GameInstance, Scenario, SingleGame


@ensure_csrf_cookie
def home(request):
    return render(request, "game/game.html")


def serialize_catalog_entry(entry):
    data = {
        "id": entry.pk,
        "name": entry.name,
        "slug": entry.slug,
        "description": entry.description,
        "introduction": entry.introduction,
    }
    if isinstance(entry, Scenario):
        data["games"] = [
            serialize_catalog_entry(game) for game in entry.games.all() if game.is_available
        ]
    return data


@require_GET
def scenarios_api(request):
    scenarios = Scenario.objects.filter(is_available=True).prefetch_related("games")
    return JsonResponse([serialize_catalog_entry(item) for item in scenarios], safe=False)


@require_GET
def single_games_api(request):
    games = SingleGame.objects.filter(is_available=True)
    return JsonResponse([serialize_catalog_entry(item) for item in games], safe=False)


def serialize_instance(instance):
    entry = instance.scenario if instance.scenario_id else instance.single_game
    map_data = normalize_map(instance.map_definition)
    state = instance.state
    fog = map_data.get("fog_of_war", False)
    visible = visible_tiles(state, map_data) if fog else set()
    friendly_ids = {unit["id"] for unit in state["units"] if unit.get("side", "attackers") == "attackers"}
    units = [unit for unit in state["units"] if not fog or unit.get("side", "attackers") == "attackers"
             or (unit["x"], unit["y"]) in visible]
    history = [normalize_history_event(event) for event in state.get("history", [])
               if not fog or event.get("witnessed", True)]
    if fog:
        # A map definition is an editor document, not a player-safe battlefield snapshot.
        map_data = {key: value for key, value in map_data.items()
                    if key not in ("enemyStartPositions", "items", "horses")}
        map_data["has_items"] = bool(instance.map_definition.get("items"))
        history = [{key: value for key, value in event.items() if key != "witnessed"}
                   | ({"morale_changes": [change for change in event["morale_changes"]
                                           if change["unit_id"] < len(instance.map_definition["startPositions"])]}
                      if "morale_changes" in event else {}) for event in history]
    status = capture_status(state, instance.map_definition)
    if fog and status == "KING GUARDED":
        king = next((unit for unit in units if unit.get("is_king")), None)
        if king is None or not any(unit.get("side") == "defenders" and not unit.get("is_king")
                                   and abs(unit["x"] - king["x"]) + abs(unit["y"] - king["y"]) == 1
                                   and unit["z"] == king["z"] for unit in units):
            status = "CAPTURE THE KING"
    return {
        "id": str(instance.pk),
        "kind": "scenarios" if instance.scenario_id else "single-games",
        "game_id": instance.source_game_id or instance.single_game_id,
        "entry": serialize_catalog_entry(entry),
        "map": map_data,
        "state": {
            **{key: value for key, value in state.items() if key != "next_item_id"},
            "units": [{**normalize_unit(unit), "armor_remaining": armor_remaining(unit, instance.state["turn"]),
                       "carried_weight": carried_weight(unit, instance.state.get("items", ())),
                       "max_carry_weight": MAX_CARRY_WEIGHT,
                       "weight_penalty": weight_penalty(unit, instance.state.get("items", ())),
                       "next_move_capacity": move_allowance(unit, instance.state.get("items", ())),
                       "next_fight_capacity": fight_allowance(unit)} for unit in units],
            "history": history,
            **({"items": [item for item in state.get("items", []) if item["carrier_id"] in friendly_ids
                           or (item["x"], item["y"]) in visible],
                "horses": [horse for horse in state.get("horses", [])
                           if (horse["x"], horse["y"]) in visible],
                "visible": [{"x": x, "y": y} for x, y in sorted(visible)],
                "explored": [{"x": x, "y": y} for x, y in sorted(
                    {(tile["x"], tile["y"]) for tile in state.get("explored", ())} | visible)],
                "king_fallen": state.get("defeated", False) and instance.map_definition.get("mission") == "capture_king"
                and not any(unit.get("is_king") for unit in state["units"])}
               if fog else {}),
            "capture_status": status,
        },
        "revision": instance.revision,
    }


def active_instance(request):
    instance_id = request.session.get("active_game_id")
    if not instance_id:
        return None
    return GameInstance.objects.select_related("scenario", "single_game").filter(pk=instance_id).first()


@require_POST
def start_game(request, kind, entry_id):
    catalog = {"scenarios": Scenario, "single-games": SingleGame}.get(kind)
    if catalog is None:
        return JsonResponse({"error": "Unknown catalog."}, status=404)
    entry = get_object_or_404(catalog, pk=entry_id, is_available=True)
    if kind == "scenarios":
        try:
            payload = json.loads(request.body) if request.body else {}
        except (ValueError, UnicodeDecodeError):
            return JsonResponse({"error": "Invalid JSON."}, status=400)
        if not isinstance(payload, dict) or set(payload) - {"single_game_id"}:
            return JsonResponse({"error": "Invalid game selection."}, status=400)
        games = entry.games.filter(is_available=True)
        if "single_game_id" in payload:
            game_id = payload["single_game_id"]
            if type(game_id) is not int:
                return JsonResponse({"error": "Choose a linked game."}, status=400)
            game = games.filter(pk=game_id).first()
        else:
            game = games.first() if games.count() == 1 else None
        if game is None:
            return JsonResponse({"error": "Choose an available game linked to this scenario."}, status=400)
    else:
        game = entry
    instance = GameInstance.objects.create(
        scenario=entry if kind == "scenarios" else None,
        single_game=entry if kind == "single-games" else None,
        source_game=game,
        map_definition=normalize_map(game.map_definition),
        state=initial_state(game.map_definition),
    )
    request.session["active_game_id"] = str(instance.pk)
    return JsonResponse(serialize_instance(instance), status=201)


@require_GET
def current_game(request):
    instance = active_instance(request)
    if instance is None:
        return JsonResponse({"error": "No active game."}, status=404)
    return JsonResponse(serialize_instance(instance))


@require_POST
def game_action(request):
    instance = active_instance(request)
    if instance is None:
        return JsonResponse({"error": "No active game."}, status=404)
    try:
        payload = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)
    if not isinstance(payload, dict) or type(payload.get("revision")) is not int:
        return JsonResponse({"error": "A game revision is required."}, status=400)
    if instance.revision != payload["revision"]:
        return JsonResponse({"error": "Game state has changed. Reload the match."}, status=409)
    combat_events = []
    try:
        action = payload.get("action")
        if (isinstance(action, dict) and action.get("type") == "end_turn"
                and set(action) == {"type"} and not instance.state["captured"]
                and not instance.state.get("defeated", False)):
            state = enemy_turn(instance.state, instance.map_definition, combat_events=combat_events)
        else:
            state = apply_action(instance.state, action, instance.map_definition, combat_events=combat_events)
    except InvalidAction as error:
        return JsonResponse({"error": str(error)}, status=400)
    except EnemyAIError as error:
        return JsonResponse({"error": str(error)}, status=error.status_code)
    updated = GameInstance.objects.filter(pk=instance.pk, revision=instance.revision).update(
        state=state,
        revision=F("revision") + 1,
        updated_at=timezone.now(),
    )
    if not updated:
        return JsonResponse({"error": "Game state has changed. Reload the match."}, status=409)
    instance.state = state
    instance.revision += 1
    if instance.map_definition.get("fog_of_war", False):
        combat_events = [{key: value for key, value in event.items() if key != "witnessed"}
                         for event in combat_events if event.get("witnessed", True)]
    return JsonResponse({**serialize_instance(instance), "combat_events": combat_events})
