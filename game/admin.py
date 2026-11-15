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
            "Older maps without enemyStartPositions spawn one defender near the objective."
        )}),
    )
