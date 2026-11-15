from django.db import migrations


VILLAGE_MAP = {
    "cols": 18, "rows": 14,
    "keep": {"left": 11, "right": 17, "top": 3, "bottom": 10},
    "gate": {"x": 14, "y": 10},
    "objective": {"x": 14, "y": 7},
    "startPositions": [
        {"x": 2, "y": 6, "type": "vanguard"},
        {"x": 3, "y": 7, "type": "vanguard"},
        {"x": 2, "y": 8, "type": "longbow"},
        {"x": 4, "y": 8, "type": "crossbow"},
    ],
    "enemyStartPositions": [
        {"x": 12, "y": 5, "type": "vanguard"},
        {"x": 16, "y": 8, "type": "longbow"},
        {"x": 14, "y": 9, "type": "crossbow"},
    ],
    "houses": [
        {"left": 6, "right": 8, "top": 2, "bottom": 4},
        {"left": 6, "right": 8, "top": 10, "bottom": 12},
    ],
    "lanes": [{"x": x, "y": 7} for x in range(5, 11)] +
             [{"x": 9, "y": y} for y in range(8, 11)],
    "objects": [
        {"x": 9, "y": 3, "type": "fence"},
        {"x": 9, "y": 4, "type": "fence"},
        {"x": 9, "y": 11, "type": "fence"},
        {"x": 8, "y": 8, "type": "well"},
        {"x": 5, "y": 10, "type": "tree"},
    ],
}


def seed_village(apps, schema_editor):
    game, _ = apps.get_model("game", "SingleGame").objects.get_or_create(
        slug="greywatch-hamlet",
        defaults={
            "name": "Greywatch Hamlet",
            "description": "Advance through houses, fenced yards and a village well to reach the keep.",
            "introduction": "The hamlet lies across the approach. Use the lanes and cover to reach the keep gate.",
            "sort_order": 3,
            "map_definition": VILLAGE_MAP,
        },
    )
    scenario, _ = apps.get_model("game", "Scenario").objects.get_or_create(
        slug="through-the-hamlet",
        defaults={
            "name": "Through the Hamlet",
            "description": "Navigate Greywatch's village on the way to the courtyard.",
            "introduction": "Keep to the lanes or circle the fenced yards before assaulting Greywatch.",
            "sort_order": 3,
        },
    )
    scenario.games.add(game)


class Migration(migrations.Migration):
    dependencies = [("game", "0006_tune_greywatch_assault")]

    operations = [migrations.RunPython(seed_village, migrations.RunPython.noop)]
