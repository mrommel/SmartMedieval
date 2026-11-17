from copy import deepcopy
from importlib import import_module

from django.db import migrations


def seed_night_watch(apps, schema_editor):
    assault = import_module("game.migrations.0006_tune_greywatch_assault")
    equipment = import_module("game.migrations.0010_unit_equipment")
    battlefield = equipment.convert_map(deepcopy(assault.PREVIOUS_ASSAULT))
    battlefield["fog_of_war"] = True
    battlefield["night"] = True
    battlefield["watchfires"] = [{"x": 8, "y": 6}, {"x": 14, "y": 9}]
    battlefield["startPositions"][0]["tools"] = ["torch"]
    database = schema_editor.connection.alias
    games = apps.get_model("game", "SingleGame").objects.using(database)
    scenarios = apps.get_model("game", "Scenario").objects.using(database)
    game, _ = games.get_or_create(slug="greywatch-night-watch", defaults={
        "name": "Greywatch Night Watch",
        "description": "Slip past torchlit sentries on a night assault.",
        "introduction": "Carry a torch to scout ahead, or drop it to hide in the dark.",
        "map_definition": battlefield,
        "sort_order": 5,
    })
    scenario, _ = scenarios.get_or_create(slug="night-watch-greywatch", defaults={
        "name": "Night Watch",
        "description": "Reach the keep under cover of darkness.",
        "introduction": "Watchfires light the approach for both your soldiers and the defenders.",
        "sort_order": 5,
    })
    scenario.games.add(game)


class Migration(migrations.Migration):
    dependencies = [("game", "0014_seed_reconnaissance")]

    operations = [migrations.RunPython(seed_night_watch, migrations.RunPython.noop)]
