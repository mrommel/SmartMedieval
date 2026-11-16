from django.db import migrations


LEGACY_WEAPONS = {"vanguard": "sword", "longbow": "longbow", "crossbow": "crossbow", "king": None}


def convert_position(position):
    point = {key: value for key, value in position.items() if key != "type"}
    if "type" in position:
        point["weapon"] = LEGACY_WEAPONS[position["type"]]
        if position["type"] == "king":
            point["is_king"] = True
    return point


def convert_map(map_data):
    return {**map_data, **{name: [convert_position(point) for point in map_data[name]]
                          for name in ("startPositions", "enemyStartPositions") if name in map_data}}


def convert_unit(unit):
    result = {key: value for key, value in unit.items() if key != "type"}
    if "weapon" not in result:
        result["weapon"] = LEGACY_WEAPONS[unit["type"]]
    if unit.get("type") == "king":
        result["is_king"] = True
    result.setdefault("tools", [])
    return result


def convert_event(event):
    result = {key: value for key, value in event.items() if key not in ("actor_type", "target_type")}
    for who in ("actor", "target"):
        label = event.get(f"{who}_type")
        if label in LEGACY_WEAPONS:
            result[f"{who}_weapon"] = LEGACY_WEAPONS[label]
            if label == "king":
                result[f"{who}_is_king"] = True
    return result


def migrate_equipment(apps, schema_editor):
    games = apps.get_model("game", "SingleGame")
    instances = apps.get_model("game", "GameInstance")
    for game in games.objects.using(schema_editor.connection.alias).iterator():
        converted = convert_map(game.map_definition)
        if converted != game.map_definition:
            games.objects.using(schema_editor.connection.alias).filter(pk=game.pk).update(map_definition=converted)
    for instance in instances.objects.using(schema_editor.connection.alias).iterator():
        state = instance.state
        converted_state = {
            **state,
            "units": [convert_unit(unit) for unit in state["units"]],
            **({"history": [convert_event(event) for event in state["history"]]} if "history" in state else {}),
        }
        converted_map = convert_map(instance.map_definition)
        if converted_map != instance.map_definition or converted_state != state:
            instances.objects.using(schema_editor.connection.alias).filter(pk=instance.pk).update(
                map_definition=converted_map, state=converted_state,
            )


class Migration(migrations.Migration):
    dependencies = [("game", "0009_hamlet_healing_potions")]

    operations = [migrations.RunPython(migrate_equipment, migrations.RunPython.noop)]

