from copy import deepcopy
from importlib import import_module

from django.db import migrations


PREVIOUS_HAMLET = deepcopy(import_module("game.migrations.0007_village_encounter").VILLAGE_MAP)
PREVIOUS_HAMLET["houses"][0]["door"] = {"x": 7, "y": 4}
PREVIOUS_HAMLET["houses"][1]["door"] = {"x": 7, "y": 10}


def stock_hamlet(apps, schema_editor):
    game = apps.get_model("game", "SingleGame").objects.filter(slug="greywatch-hamlet").first()
    if game is None or game.map_definition != PREVIOUS_HAMLET:
        return
    updated = deepcopy(PREVIOUS_HAMLET)
    updated["items"] = [
        {"x": 2, "y": 6, "type": "healing_potion"},
        {"x": 7, "y": 3, "type": "healing_potion"},
    ]
    game.map_definition = updated
    game.save(update_fields=["map_definition"])


class Migration(migrations.Migration):
    dependencies = [("game", "0008_hamlet_house_doors")]

    operations = [migrations.RunPython(stock_hamlet, migrations.RunPython.noop)]
