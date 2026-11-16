from copy import deepcopy
from importlib import import_module

from django.db import migrations


previous = import_module("game.migrations.0009_hamlet_healing_potions")
convert_map = import_module("game.migrations.0010_unit_equipment").convert_map
PREVIOUS_HAMLET = deepcopy(previous.PREVIOUS_HAMLET)
PREVIOUS_HAMLET["items"] = [
    {"x": 2, "y": 6, "type": "healing_potion"},
    {"x": 7, "y": 3, "type": "healing_potion"},
]
PREVIOUS_HAMLET = convert_map(PREVIOUS_HAMLET)


def equip_seeded_hamlet(apps, schema_editor):
    games = apps.get_model("game", "SingleGame").objects.using(schema_editor.connection.alias)
    game = games.filter(slug="greywatch-hamlet").first()
    if game is None or game.map_definition != PREVIOUS_HAMLET:
        return
    updated = deepcopy(PREVIOUS_HAMLET)
    updated["startPositions"][0]["armor"] = "leather"
    updated["enemyStartPositions"][0]["armor"] = "mail"
    games.filter(pk=game.pk).update(map_definition=updated)


class Migration(migrations.Migration):
    dependencies = [("game", "0010_unit_equipment")]

    operations = [migrations.RunPython(equip_seeded_hamlet, migrations.RunPython.noop)]
