import json

from django.db.models import F
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .enemy_ai import EnemyAIError, enemy_turn
from .engine import InvalidAction, apply_action, capture_status, initial_state
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
    return {
        "id": str(instance.pk),
        "kind": "scenarios" if instance.scenario_id else "single-games",
        "game_id": instance.source_game_id or instance.single_game_id,
        "entry": serialize_catalog_entry(entry),
        "map": instance.map_definition,
        "state": {
            **instance.state,
            "capture_status": capture_status(instance.state, instance.map_definition),
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
        map_definition=game.map_definition,
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
                and set(action) == {"type"} and not instance.state["captured"]):
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
    return JsonResponse({**serialize_instance(instance), "combat_events": combat_events})
