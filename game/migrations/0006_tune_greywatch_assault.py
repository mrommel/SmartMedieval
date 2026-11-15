from django.db import migrations


# Snapshot the previous seeded layout so editor changes are never overwritten.
PREVIOUS_ASSAULT = {
    "cols": 18,
    "rows": 14,
    "keep": {"left": 11, "right": 17, "top": 3, "bottom": 10},
    "gate": {"x": 14, "y": 10},
    "objective": {"x": 14, "y": 7},
    "startPositions": [
        {"x": 2, "y": 6, "type": "vanguard"},
        {"x": 3, "y": 7, "type": "vanguard"},
        {"x": 2, "y": 8, "type": "longbow"},
        {"x": 4, "y": 6, "type": "longbow"},
        {"x": 4, "y": 8, "type": "crossbow"},
        {"x": 5, "y": 7, "type": "crossbow"},
    ],
    "enemyStartPositions": [
        {"x": 12, "y": 5, "type": "vanguard"},
        {"x": 16, "y": 8, "type": "longbow"},
    ],
    "catapults": [{"x": 3, "y": 7}],
}


def tune_seeded_assault(apps, schema_editor):
    game = apps.get_model("game", "SingleGame").objects.filter(slug="greywatch-assault").first()
    if game and game.map_definition == PREVIOUS_ASSAULT:
        game.map_definition = {
            **PREVIOUS_ASSAULT,
            "enemyStartPositions": [
                *PREVIOUS_ASSAULT["enemyStartPositions"],
                {"x": 14, "y": 9, "type": "crossbow"},
            ],
        }
        game.save(update_fields=["map_definition"])


class Migration(migrations.Migration):
    dependencies = [("game", "0005_catapults")]

    operations = [migrations.RunPython(tune_seeded_assault, migrations.RunPython.noop)]
