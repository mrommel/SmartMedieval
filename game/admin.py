from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.urls import path, reverse
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST

from .engine import initial_state, normalize_map
from .models import GameInstance
from .models import Scenario, SingleGame


@admin.register(Scenario)
class ScenarioAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_available", "sort_order")
    list_filter = ("is_available",)
    filter_horizontal = ("games",)
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name", "description")


@admin.register(SingleGame)
class SingleGameAdmin(admin.ModelAdmin):
    change_form_template = "admin/game/singlegame/change_form.html"

    def get_urls(self):
        return [
            path("<int:object_id>/playtest/", self.admin_site.admin_view(self.playtest),
                 name="game_singlegame_playtest"),
        ] + super().get_urls()

    @method_decorator(require_POST)
    def playtest(self, request, object_id):
        game = get_object_or_404(SingleGame, pk=object_id)
        if not self.has_change_permission(request, game):
            raise PermissionDenied
        if not game.is_available:
            raise PermissionDenied
        instance = GameInstance.objects.create(
            single_game=game, source_game=game,
            map_definition=normalize_map(game.map_definition),
            state=initial_state(game.map_definition),
        )
        request.session["active_game_id"] = str(instance.pk)
        return redirect(reverse("home") + "?playtest=1")

    list_display = ("name", "slug", "is_available", "sort_order")
    list_filter = ("is_available",)
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name", "description")
    fieldsets = (
        (None, {"fields": ("name", "slug", "description", "introduction", "sort_order", "is_available")}),
        ("Battlefield", {"fields": ("map_definition",), "description": (
            "Edit cols, rows, keep bounds, gate, objective, startPositions and "
            "enemyStartPositions as JSON. Each side needs 1-64 units with x, y and "
            "weapon: sword, longbow or crossbow. Optional tools are up to two labels; "
            "optional armor is leather (weight 1, absorbs 1 damage per turn) or mail "
            "(weight 3, absorbs 2). Armor starts equipped; carried weight reduces movement allowance. "
            "All units must be able to reach "
            "the objective; defenders cannot start on it or on an attacker. "
            "Optional exit: {\"x\": 2, \"y\": 6} marks an open, flat outdoor tile "
            "reachable by every attacker and away from the objective. A soldier on the exit "
            "may withdraw for one fight point, taking carried gear along. Once no attackers "
            "remain, a surviving evacuee makes the retreat successful. "
            "Optional elevation: [{\"x\": 3, \"y\": 5, \"height\": 1, \"access\": \"ramp\"}]. "
            "Heights are 1-3; only a ladder or ramp on the higher tile permits a one-level step. "
            "Optional objects: [{\"x\": 4, \"y\": 5, \"type\": \"well\"}]. Trees, rocks and wells "
            "block movement and shots; fences block movement but allow shots. All provide ranged cover. "
            "Keep objects off walls, houses, gates, elevated tiles, units and the objective. "
            "Optional houses: [{\"left\": 6, \"right\": 7, \"top\": 1, \"bottom\": 2}]. "
            "Up to 32 solid 2-4 tile rectangles outside keeps and strongpoints block movement "
            "and shots; an optional perimeter door makes the ground floor enterable. "
            "Optional lanes: [{\"x\": 5, \"y\": 4}] mark visual paths without changing movement cost. "
            "Optional terrain: [{\"x\": 5, \"y\": 4, \"type\": \"road\"}]. "
            "Distinct walkable outdoor tiles can be road (1 MP), grass (2 MP), mud (3 MP) "
            "or swamp (4 MP); unmarked tiles cost 1 MP. A single step must fit within "
            "a soldier's turn allowance, including their carried-weight penalty. "
            "Optional horses: [{\"x\": 2, \"y\": 6}]. Up to 16 distinct open, flat outdoor "
            "tiles (starting soldiers may share a tile); no swamps or objective. Mounting "
            "costs one fight point, gives 6 base MP without load penalty and 2-damage sword "
            "melee. Horses cannot enter houses, swamps or ladders; mud costs 4 MP. "
            "Optional strongpoints: [{\"left\": 6, \"right\": 9, \"top\": 3, \"bottom\": 6, "
            "\"gate\": {\"x\": 7, \"y\": 6}}]. Up to 16 non-overlapping gated rectangles may be "
            "placed away from the keep; all units must still reach the objective. "
            "Optional catapults: [{\"x\": 3, \"y\": 7}]. Up to 16 distinct open ground "
            "tiles away from the objective; a soldier on the tile can aim and fire. "
            "Optional items: [{\"x\": 2, \"y\": 6, \"type\": \"healing_potion\"}, "
            "{\"x\": 3, \"y\": 7, \"type\": \"weapon\", \"name\": \"longbow\"}, "
            "{\"x\": 4, \"y\": 6, \"type\": \"armor\", \"name\": \"mail\"}, "
            "{\"x\": 5, \"y\": 6, \"type\": \"tool\", \"name\": \"rope\"}]. "
            "Up to 32 items on distinct walkable ground tiles; weapons are sword, longbow "
            "or crossbow, armor is leather or mail. Recover equipment in an empty slot "
            "for one fight point. Tools use the same up-to-40-character labels as starting tools; "
            "soldiers can pick up or drop them for one fight point (up to two carried). "
            "Optional fog_of_war: true shares daylight sight within six tiles and remembers "
            "explored ground; hidden units and supplies are not sent to the browser. "
            "Optional night: true requires fog_of_war: true and limits unlit sight to two steps. "
            "A carried torch tool gives its side five-step sight, but exposes its bearer to both sides. "
            "Optional watchfires: [{\"x\": 6, \"y\": 6}] light tiles within three steps; "
            "place up to 16 on distinct open outdoor tiles away from objects. "
            "Older maps without enemyStartPositions spawn one defender near the objective."
        )}),
    )
