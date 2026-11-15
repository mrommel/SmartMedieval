from copy import deepcopy
from importlib import import_module

from django.db import migrations


PREVIOUS_HAMLET = import_module("game.migrations.0007_village_encounter").VILLAGE_MAP


def open_seeded_houses(apps, schema_editor):
    game = apps.get_model("game", "SingleGame").objects.filter(slug="greywatch-hamlet").first()
    if game is None or game.map_definition != PREVIOUS_HAMLET:
        return
    updated = deepcopy(PREVIOUS_HAMLET)
    updated["houses"][0]["door"] = {"x": 7, "y": 4}
    updated["houses"][1]["door"] = {"x": 7, "y": 10}
    game.map_definition = updated
    game.save(update_fields=["map_definition"])


class Migration(migrations.Migration):
    dependencies = [("game", "0007_village_encounter")]

    operations = [migrations.RunPython(open_seeded_houses, migrations.RunPython.noop)]
