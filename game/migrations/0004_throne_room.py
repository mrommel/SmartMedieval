from django.db import migrations


def seed_throne_room(apps, schema_editor):
    game, _ = apps.get_model("game", "SingleGame").objects.get_or_create(
        slug="greywatch-throne-room",
        defaults={
            "name": "The Throne Room",
            "description": "Capture the king alive inside Greywatch keep.",
            "introduction": "The king holds the throne behind his guard. Bring a vanguard close,"
                            " defeat the guards beside him, and take him alive. Killing him fails the mission.",
            "sort_order": 2,
            "map_definition": {
                "cols": 18, "rows": 14,
                "keep": {"left": 11, "right": 17, "top": 3, "bottom": 10},
                "gate": {"x": 14, "y": 10},
                "objective": {"x": 14, "y": 7},
                "mission": "capture_king",
                "startPositions": [
                    {"x": 2, "y": 6, "type": "vanguard"},
                    {"x": 3, "y": 7, "type": "vanguard"},
                    {"x": 2, "y": 8, "type": "longbow"},
                    {"x": 4, "y": 6, "type": "longbow"},
                    {"x": 4, "y": 8, "type": "crossbow"},
                    {"x": 5, "y": 7, "type": "crossbow"},
                ],
                "enemyStartPositions": [
                    {"x": 14, "y": 7, "type": "king"},
                    {"x": 13, "y": 7, "type": "vanguard"},
                    {"x": 12, "y": 5, "type": "vanguard"},
                    {"x": 16, "y": 8, "type": "longbow"},
                ],
            },
        },
    )
    scenario, _ = apps.get_model("game", "Scenario").objects.get_or_create(
        slug="capture-the-king",
        defaults={
            "name": "Capture the King",
            "description": "Take the Greywatch throne without killing its ruler.",
            "introduction": "The king must survive. Secure the throne room and capture him alive.",
            "sort_order": 2,
        },
    )
    scenario.games.add(game)


class Migration(migrations.Migration):
    dependencies = [("game", "0003_gameinstance_map_definition_gameinstance_source_game_and_more")]

    operations = [migrations.RunPython(seed_throne_room, migrations.RunPython.noop)]
