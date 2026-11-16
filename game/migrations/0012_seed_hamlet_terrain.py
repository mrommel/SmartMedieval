from copy import deepcopy
from importlib import import_module

from django.db import migrations


previous = import_module("game.migrations.0011_seed_hamlet_armor")
PREVIOUS_HAMLET = deepcopy(previous.PREVIOUS_HAMLET)
PREVIOUS_HAMLET["startPositions"][0]["armor"] = "leather"
PREVIOUS_HAMLET["enemyStartPositions"][0]["armor"] = "mail"


def seed_hamlet_terrain(apps, schema_editor):
    games = apps.get_model("game", "SingleGame").objects.using(schema_editor.connection.alias)
    game = games.filter(slug="greywatch-hamlet").first()
    if game is None or game.map_definition != PREVIOUS_HAMLET:
        return
    updated = deepcopy(PREVIOUS_HAMLET)
    updated["terrain"] = [{"x": tile["x"], "y": tile["y"], "type": "road"}
                          for tile in updated["lanes"]]
    updated["terrain"] += [
        {"x": 5, "y": 6, "type": "mud"},
        {"x": 6, "y": 6, "type": "swamp"},
        {"x": 7, "y": 6, "type": "grass"},
    ]
    games.filter(pk=game.pk).update(map_definition=updated)


class Migration(migrations.Migration):
    dependencies = [("game", "0011_seed_hamlet_armor")]

    operations = [migrations.RunPython(seed_hamlet_terrain, migrations.RunPython.noop)]
