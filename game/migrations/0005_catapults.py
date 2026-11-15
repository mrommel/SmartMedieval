from django.db import migrations


def equip_seeded_assault(apps, schema_editor):
    game = apps.get_model("game", "SingleGame").objects.filter(slug="greywatch-assault").first()
    if not game:
        return
    from game.engine import default_map

    standard = default_map()
    original_layout = {key: value for key, value in standard.items()
                       if key not in ("catapults", "enemyStartPositions")}
    saved_layout = {key: value for key, value in game.map_definition.items()
                    if key not in ("catapults", "enemyStartPositions")}
    if "catapults" not in game.map_definition and saved_layout == original_layout:
        game.map_definition = {**game.map_definition, "catapults": standard["catapults"]}
        game.save(update_fields=["map_definition"])


class Migration(migrations.Migration):
    dependencies = [("game", "0004_throne_room")]

    operations = [migrations.RunPython(equip_seeded_assault, migrations.RunPython.noop)]
