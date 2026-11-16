from copy import deepcopy
from importlib import import_module

from django.db import migrations


def seed_reconnaissance(apps, schema_editor):
    assault = import_module("game.migrations.0006_tune_greywatch_assault")
    equipment = import_module("game.migrations.0010_unit_equipment")
    battlefield = deepcopy(assault.PREVIOUS_ASSAULT)
    battlefield["enemyStartPositions"].append({"x": 14, "y": 9, "type": "crossbow"})
    battlefield = {**equipment.convert_map(battlefield), "fog_of_war": True}
    database = schema_editor.connection.alias
    games = apps.get_model("game", "SingleGame").objects.using(database)
    scenarios = apps.get_model("game", "Scenario").objects.using(database)
    game, _ = games.get_or_create(slug="greywatch-reconnaissance", defaults={
        "name": "Greywatch Reconnaissance",
        "description": "Scout the unknown garrison before storming the keep.",
        "introduction": "Advance carefully: allies share daylight sight, but unseen guards stay hidden.",
        "map_definition": battlefield,
        "sort_order": 4,
    })
    scenario, _ = scenarios.get_or_create(slug="scout-greywatch", defaults={
        "name": "Scout Greywatch",
        "description": "Find the defenders behind Greywatch's walls.",
        "introduction": "The fog lifts as your company approaches the castle.",
        "sort_order": 4,
    })
    scenario.games.add(game)


class Migration(migrations.Migration):
    dependencies = [("game", "0013_seed_hamlet_horse")]

    operations = [migrations.RunPython(seed_reconnaissance, migrations.RunPython.noop)]
