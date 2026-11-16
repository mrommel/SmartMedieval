from copy import deepcopy
from importlib import import_module

from django.db import migrations


previous = import_module("game.migrations.0012_seed_hamlet_terrain")
PREVIOUS_HAMLET = deepcopy(previous.PREVIOUS_HAMLET)
PREVIOUS_HAMLET["terrain"] = [{"x": tile["x"], "y": tile["y"], "type": "road"}
                              for tile in PREVIOUS_HAMLET["lanes"]]
PREVIOUS_HAMLET["terrain"] += [
    {"x": 5, "y": 6, "type": "mud"},
    {"x": 6, "y": 6, "type": "swamp"},
    {"x": 7, "y": 6, "type": "grass"},
]


def seed_hamlet_horse(apps, schema_editor):
    games = apps.get_model("game", "SingleGame").objects.using(schema_editor.connection.alias)
    game = games.filter(slug="greywatch-hamlet").first()
    if game is None or game.map_definition != PREVIOUS_HAMLET:
        return
    updated = deepcopy(PREVIOUS_HAMLET)
    updated["horses"] = [{"x": 2, "y": 6}]
    games.filter(pk=game.pk).update(map_definition=updated)


class Migration(migrations.Migration):
    dependencies = [("game", "0012_seed_hamlet_terrain")]

    operations = [migrations.RunPython(seed_hamlet_horse, migrations.RunPython.noop)]
