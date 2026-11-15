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
            "Optional objects: [{\"x\": 4, \"y\": 5, \"type\": \"tree\"}]. Trees and rocks "
            "block movement and shots; keep them off walls, gates, elevated tiles, units and the objective. "
            "Optional strongpoints: [{\"left\": 6, \"right\": 9, \"top\": 3, \"bottom\": 6, "
            "\"gate\": {\"x\": 7, \"y\": 6}}]. Up to 16 non-overlapping gated rectangles may be "
            "placed away from the keep; all units must still reach the objective. "
            "Older maps without enemyStartPositions spawn one defender near the objective."
        )}),
    )
