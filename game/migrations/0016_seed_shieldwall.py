from copy import deepcopy
from importlib import import_module

from django.db import migrations


def seed_shieldwall(apps, schema_editor):
    assault = import_module("game.migrations.0006_tune_greywatch_assault")
    equipment = import_module("game.migrations.0010_unit_equipment")
    battlefield = equipment.convert_map(deepcopy(assault.PREVIOUS_ASSAULT))
    battlefield["fog_of_war"] = True
    battlefield["startPositions"][0]["tools"] = ["shield"]
    database = schema_editor.connection.alias
    games = apps.get_model("game", "SingleGame").objects.using(database)
    scenarios = apps.get_model("game", "Scenario").objects.using(database)
    game, _ = games.get_or_create(slug="greywatch-shieldwall", defaults={
        "name": "Greywatch Shieldwall",
        "description": "Advance with a shield against the gatehouse defenders.",
        "introduction": "Raise your shield to block visible blows, but watch for archers outside your narrowed sight.",
        "map_definition": battlefield,
        "sort_order": 6,
    })
    scenario, _ = scenarios.get_or_create(slug="shieldwall-greywatch", defaults={
        "name": "Shieldwall",
        "description": "Protect your company on the approach to Greywatch.",
        "introduction": "A carried shield costs one fight point and one move point to raise.",
        "sort_order": 6,
    })
    scenario.games.add(game)


class Migration(migrations.Migration):
    dependencies = [("game", "0015_seed_night_watch")]

    operations = [migrations.RunPython(seed_shieldwall, migrations.RunPython.noop)]
