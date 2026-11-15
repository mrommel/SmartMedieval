from django.contrib import admin

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
    list_display = ("name", "slug", "is_available", "sort_order")
    list_filter = ("is_available",)
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name", "description")
    fieldsets = (
        (None, {"fields": ("name", "slug", "description", "introduction", "sort_order", "is_available")}),
        ("Battlefield", {"fields": ("map_definition",), "description": (
            "Edit cols, rows, keep bounds, gate, objective, startPositions and "
            "enemyStartPositions as JSON. Each side needs 1-64 units with x, y and "
            "a type: vanguard, longbow or crossbow. All units must be able to reach "
            "the objective; defenders cannot start on it or on an attacker. "
            "Optional elevation: [{\"x\": 3, \"y\": 5, \"height\": 1, \"access\": \"ramp\"}]. "
            "Heights are 1-3; only a ladder or ramp on the higher tile permits a one-level step. "
            "Optional objects: [{\"x\": 4, \"y\": 5, \"type\": \"well\"}]. Trees, rocks and wells "
            "block movement and shots; fences block movement but allow shots. All provide ranged cover. "
            "Keep objects off walls, houses, gates, elevated tiles, units and the objective. "
            "Optional houses: [{\"left\": 6, \"right\": 7, \"top\": 1, \"bottom\": 2}]. "
            "Up to 32 solid 2-4 tile rectangles outside keeps and strongpoints block movement "
            "and shots; interiors are not yet enterable. Optional lanes: [{\"x\": 5, \"y\": 4}] "
            "mark unique walkable ground tiles without changing movement cost. "
            "Optional strongpoints: [{\"left\": 6, \"right\": 9, \"top\": 3, \"bottom\": 6, "
            "\"gate\": {\"x\": 7, \"y\": 6}}]. Up to 16 non-overlapping gated rectangles may be "
            "placed away from the keep; all units must still reach the objective. "
            "Optional catapults: [{\"x\": 3, \"y\": 7}]. Up to 16 distinct open ground "
            "tiles away from the objective; a soldier on the tile can aim and fire. "
            "Older maps without enemyStartPositions spawn one defender near the objective."
        )}),
    )
