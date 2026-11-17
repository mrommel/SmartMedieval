from collections import deque
from copy import deepcopy
from heapq import heappop, heappush
from math import cos, pi, sin


MAP = {
    "cols": 18,
    "rows": 14,
    "keep": {"left": 11, "right": 17, "top": 3, "bottom": 10},
    "gate": {"x": 14, "y": 10},
    "objective": {"x": 14, "y": 7},
    "startPositions": [
        {"x": 2, "y": 6, "weapon": "sword"},
        {"x": 3, "y": 7, "weapon": "sword"},
        {"x": 2, "y": 8, "weapon": "longbow"},
        {"x": 4, "y": 6, "weapon": "longbow"},
        {"x": 4, "y": 8, "weapon": "crossbow"},
        {"x": 5, "y": 7, "weapon": "crossbow"},
    ],
    "enemyStartPositions": [
        {"x": 12, "y": 5, "weapon": "sword"},
        {"x": 16, "y": 8, "weapon": "longbow"},
        {"x": 14, "y": 9, "weapon": "crossbow"},
    ],
    "catapults": [{"x": 3, "y": 7}],
}
MOVE_POINTS = 4
TERRAIN_COSTS = {"road": 1, "grass": 2, "mud": 3, "swamp": 4}
MOUNTED_TERRAIN_COSTS = {"road": 1, "grass": 2, "mud": 4}
HORSE_MOVE_POINTS = 6
HORSE_HEALTH = 2
MAX_HEALTH = 3
FIGHT_POINTS = 1
ATTACK_DAMAGE = 1
AMBUSH_BONUS = 1
STARTING_MORALE = 3
MAX_MORALE = 5
HISTORY_LIMIT = 100
CATAPULT_AMMO = 3
CATAPULT_RANGE = 10
CATAPULT_RELOAD = 2
WALL_HEALTH = 2
INVENTORY_LIMIT = 2
POTION_HEAL = 2
MAX_CARRY_WEIGHT = 8
WEAPON_WEIGHTS = {None: 0, "sword": 1, "longbow": 2, "crossbow": 3}
TOOL_WEIGHT = 1
POTION_WEIGHT = 1
WEIGHT_PER_MOVE_PENALTY = 3
ARMOR_STATS = {
    # Armor absorbs this many HP of damage per turn; weight is carried even when removed.
    "leather": {"protection": 1, "weight": 1},
    "mail": {"protection": 2, "weight": 3},
}
RANGED_WEAPON_STATS = {
    # End-turn processing ticks cooldowns, including the transition after firing.
    "longbow": {"range": 5, "reload_turns": 2},
    "crossbow": {"range": 6, "reload_turns": 3},
}
VISION_RANGE = 6
NIGHT_VISION_RANGE = 2
TORCH_VISION_RANGE = 5
WATCHFIRE_LIGHT_RANGE = 3
LEGACY_WEAPONS = {"vanguard": "sword", "longbow": "longbow", "crossbow": "crossbow", "king": None}


def normalize_position(position):
    point = {key: value for key, value in position.items() if key != "type"}
    if "type" in position:
        point["weapon"] = LEGACY_WEAPONS[position["type"]]
        if position["type"] == "king":
            point["is_king"] = True
    return point


def normalize_map(map_data):
    """Convert persisted legacy rosters without changing the saved definition."""
    return {**map_data, **{name: [normalize_position(point) for point in map_data[name]]
                          for name in ("startPositions", "enemyStartPositions") if name in map_data}}


def normalize_unit(unit):
    result = {key: value for key, value in unit.items() if key != "type"}
    if "weapon" not in result:
        result["weapon"] = LEGACY_WEAPONS[unit["type"]]
    if unit.get("type") == "king":
        result["is_king"] = True
    result.setdefault("tools", [])
    result.setdefault("armor", None)
    result.setdefault("armor_equipped", result["armor"] is not None)
    result.setdefault("mount_id", None)
    result.setdefault("move_reserved", 0)
    result.setdefault("torch_lit", True)
    result.setdefault("crouched", False)
    return result


def normalize_history_event(event):
    result = {key: value for key, value in event.items() if key not in ("actor_type", "target_type")}
    for who in ("actor", "target"):
        legacy = event.get(f"{who}_type")
        if legacy in LEGACY_WEAPONS:
            result[f"{who}_weapon"] = LEGACY_WEAPONS[legacy]
            if legacy == "king":
                result[f"{who}_is_king"] = True
    return result


class InvalidAction(ValueError):
    pass


class InvalidMap(ValueError):
    pass


def default_map():
    return deepcopy(MAP)


def validate_map(map_data):
    required = set(MAP) - {"enemyStartPositions", "catapults"}
    if not isinstance(map_data, dict) or not required <= set(map_data) <= set(MAP) | {"elevation", "objects", "strongpoints", "mission", "houses", "lanes", "items", "terrain", "horses", "fog_of_war", "night", "watchfires"}:
        raise InvalidMap("Map must contain cols, rows, keep, gate, objective and startPositions.")
    if "fog_of_war" in map_data and type(map_data["fog_of_war"]) is not bool:
        raise InvalidMap("fog_of_war must be true or false.")
    if "night" in map_data and type(map_data["night"]) is not bool:
        raise InvalidMap("night must be true or false.")
    if map_data.get("night") and not map_data.get("fog_of_war", False):
        raise InvalidMap("Night maps require fog_of_war: true.")
    if "watchfires" in map_data and not map_data.get("night", False):
        raise InvalidMap("Watchfires require a night map.")
    mission = map_data.get("mission", "courtyard")
    if mission not in ("courtyard", "capture_king"):
        raise InvalidMap("Mission must be courtyard or capture_king.")
    if mission == "capture_king" and "enemyStartPositions" not in map_data:
        raise InvalidMap("A throne-room mission needs a king and guards in enemyStartPositions.")
    cols, rows = map_data["cols"], map_data["rows"]
    if type(cols) is not int or type(rows) is not int or not (8 <= cols <= 64 and 8 <= rows <= 64):
        raise InvalidMap("Map dimensions must be between 8 and 64 tiles.")
    keep = map_data["keep"]
    if (not isinstance(keep, dict) or set(keep) != {"left", "right", "top", "bottom"}
            or any(type(value) is not int for value in keep.values())
            or not (0 <= keep["left"] < keep["right"] < cols)
            or not (0 <= keep["top"] < keep["bottom"] < rows)):
        raise InvalidMap("Keep bounds must form a rectangle inside the map.")
    for name in ("gate", "objective"):
        point = map_data[name]
        if (not isinstance(point, dict) or set(point) != {"x", "y"}
                or any(type(value) is not int for value in point.values())
                or not (0 <= point["x"] < cols and 0 <= point["y"] < rows)):
            raise InvalidMap(f"{name} must be a tile inside the map.")
    gate = map_data["gate"]
    if not is_keep_edge(gate["x"], gate["y"], map_data):
        raise InvalidMap("The gate must lie on the keep wall.")
    strongpoints = map_data.get("strongpoints", [])
    if not isinstance(strongpoints, list) or len(strongpoints) > 16:
        raise InvalidMap("Strongpoints must be a list of at most 16 gated rectangles.")
    rectangles = [keep]
    for point in strongpoints:
        if not isinstance(point, dict) or set(point) != {"left", "right", "top", "bottom", "gate"}:
            raise InvalidMap("Each strongpoint needs bounds and a gate.")
        if (any(type(point[key]) is not int for key in ("left", "right", "top", "bottom"))
                or not (0 <= point["left"] < point["right"] < cols)
                or not (0 <= point["top"] < point["bottom"] < rows)):
            raise InvalidMap("Strongpoint bounds must form a rectangle inside the map.")
        entrance = point["gate"]
        if (not isinstance(entrance, dict) or set(entrance) != {"x", "y"}
                or type(entrance["x"]) is not int or type(entrance["y"]) is not int
                or not is_rectangle_edge(entrance["x"], entrance["y"], point)):
            raise InvalidMap("Each strongpoint gate must lie on its wall.")
        if any(point["left"] <= other["right"] and other["left"] <= point["right"]
               and point["top"] <= other["bottom"] and other["top"] <= point["bottom"]
               for other in rectangles):
            raise InvalidMap("Strongpoints cannot overlap the keep or each other.")
        rectangles.append(point)
    houses = map_data.get("houses", [])
    if not isinstance(houses, list) or len(houses) > 32:
        raise InvalidMap("Houses must be a list of at most 32 rectangular footprints.")
    for house in houses:
        if (not isinstance(house, dict) or set(house) not in (
                {"left", "right", "top", "bottom"}, {"left", "right", "top", "bottom", "door"})
                or any(type(house[key]) is not int for key in ("left", "right", "top", "bottom"))
                or not (0 <= house["left"] < house["right"] < cols
                        and 0 <= house["top"] < house["bottom"] < rows)
                or house["right"] - house["left"] > 3 or house["bottom"] - house["top"] > 3
                or any(house["left"] <= other["right"] and other["left"] <= house["right"]
                       and house["top"] <= other["bottom"] and other["top"] <= house["bottom"]
                       for other in rectangles)):
            raise InvalidMap("Houses must be distinct 2-4 tile rectangles outside keeps and strongpoints.")
        if "door" in house:
            door = house["door"]
            if (not isinstance(door, dict) or set(door) != {"x", "y"}
                    or type(door["x"]) is not int or type(door["y"]) is not int
                    or not is_rectangle_edge(door["x"], door["y"], house)):
                raise InvalidMap("A house door needs a perimeter tile.")
        rectangles.append(house)
    objects = map_data.get("objects", [])
    if not isinstance(objects, list) or len(objects) > 256:
        raise InvalidMap("Objects must be a list of at most 256 trees, rocks, fences and wells.")
    object_tiles = set()
    for obj in objects:
        if (not isinstance(obj, dict) or set(obj) != {"x", "y", "type"}
                or type(obj["x"]) is not int or type(obj["y"]) is not int
                or obj["type"] not in ("tree", "rock", "fence", "well")
                or not (0 <= obj["x"] < cols and 0 <= obj["y"] < rows)
                or is_wall(obj["x"], obj["y"], map_data)
                or is_house(obj["x"], obj["y"], map_data)
                or (obj["x"], obj["y"]) == (gate["x"], gate["y"])
                or (obj["x"], obj["y"]) in object_tiles):
            raise InvalidMap("Objects must be unique open tiles with type tree, rock, fence or well, away from the gate.")
        object_tiles.add((obj["x"], obj["y"]))
    watchfires = map_data.get("watchfires", [])
    if not isinstance(watchfires, list) or len(watchfires) > 16:
        raise InvalidMap("Watchfires must be a list of at most 16 open outdoor tiles.")
    seen_fires = set()
    for point in watchfires:
        if (not isinstance(point, dict) or set(point) != {"x", "y"}
                or type(point["x"]) is not int or type(point["y"]) is not int
                or not is_walkable(point["x"], point["y"], map_data)
                or is_house(point["x"], point["y"], map_data)
                or (point["x"], point["y"]) in object_tiles
                or (point["x"], point["y"]) in seen_fires):
            raise InvalidMap("Watchfires need distinct open outdoor tiles away from objects.")
        seen_fires.add((point["x"], point["y"]))
    for house in houses:
        if "door" in house and not any(
                is_walkable(x, y, map_data) for x, y in neighbors(house["door"]["x"], house["door"]["y"])
                if not is_house(x, y, map_data)):
            raise InvalidMap("A house door needs an unobstructed exterior neighbor.")
    elevation = map_data.get("elevation", [])
    if not isinstance(elevation, list) or len(elevation) > cols * rows:
        raise InvalidMap("Elevation must be a list of tiles inside the map.")
    seen = set()
    for tile in elevation:
        if (not isinstance(tile, dict) or set(tile) not in ({"x", "y", "height"},
                                                           {"x", "y", "height", "access"})
                or any(type(tile[key]) is not int for key in ("x", "y", "height"))
                or not 1 <= tile["height"] <= 3
                or ("access" in tile and tile["access"] not in ("ladder", "ramp"))
                or (tile["x"], tile["y"]) in object_tiles
                or is_house(tile["x"], tile["y"], map_data)
                or not is_walkable(tile["x"], tile["y"], map_data)
                or (tile["x"], tile["y"]) in seen):
            raise InvalidMap("Elevated tiles must be unique open tiles with height 1-3 and optional ladder or ramp access.")
        seen.add((tile["x"], tile["y"]))
    lanes = map_data.get("lanes", [])
    if not isinstance(lanes, list) or len(lanes) > cols * rows:
        raise InvalidMap("Lanes must be a list of unique open ground tiles.")
    seen_lanes = set()
    for lane in lanes:
        if (not isinstance(lane, dict) or set(lane) != {"x", "y"}
                or any(type(value) is not int for value in lane.values())
                or is_house(lane["x"], lane["y"], map_data)
                or not is_walkable(lane["x"], lane["y"], map_data)
                or (lane["x"], lane["y"]) in seen
                or (lane["x"], lane["y"]) in seen_lanes):
            raise InvalidMap("Lanes must be unique open ground tiles without elevation.")
        seen_lanes.add((lane["x"], lane["y"]))
    terrain = map_data.get("terrain", [])
    if not isinstance(terrain, list) or len(terrain) > cols * rows:
        raise InvalidMap("Terrain must be a list of unique open ground tiles.")
    seen_terrain = set()
    for tile in terrain:
        if (not isinstance(tile, dict) or set(tile) != {"x", "y", "type"}
                or type(tile["x"]) is not int or type(tile["y"]) is not int
                or type(tile["type"]) is not str or tile["type"] not in TERRAIN_COSTS
                or (tile["x"], tile["y"]) in seen_terrain
                or (tile["x"], tile["y"]) in seen
                or is_house(tile["x"], tile["y"], map_data)
                or not is_walkable(tile["x"], tile["y"], map_data)):
            raise InvalidMap("Terrain tiles must be distinct open ground tiles of type road, grass, mud or swamp.")
        seen_terrain.add((tile["x"], tile["y"]))
    objective = map_data["objective"]
    if is_house(objective["x"], objective["y"], map_data) or not is_walkable(objective["x"], objective["y"], map_data):
        raise InvalidMap("The objective must be on an open tile.")
    if mission == "capture_king" and not (keep["left"] < objective["x"] < keep["right"]
                                          and keep["top"] < objective["y"] < keep["bottom"]):
        raise InvalidMap("The throne must be inside the keep.")
    occupied = set()
    kings = 0
    guards = 0
    for name in ("startPositions", "enemyStartPositions"):
        if name not in map_data:
            continue
        positions = map_data[name]
        if not isinstance(positions, list) or not 1 <= len(positions) <= 64:
            raise InvalidMap(f"Provide between 1 and 64 units in {name}.")
        for position in positions:
            if not isinstance(position, dict):
                raise InvalidMap("Every starting unit needs an open tile and a supported weapon.")
            legacy = set(position) == {"x", "y", "type"} and position["type"] in LEGACY_WEAPONS
            if legacy:
                position = normalize_position(position)
            if (not {"x", "y", "weapon"} <= set(position) <= {"x", "y", "weapon", "tools", "is_king", "armor"}
                    or type(position["x"]) is not int or type(position["y"]) is not int
                     or position["weapon"] not in ("sword", "longbow", "crossbow", None)
                     or position.get("armor") not in (None, *ARMOR_STATS)
                     or (position["weapon"] is None) != position.get("is_king", False)
                     or ("is_king" in position and position["is_king"] is not True)
                     or (position.get("is_king", False) and (name != "enemyStartPositions" or mission != "capture_king"))
                     or not isinstance(position.get("tools", []), list)
                     or len(position.get("tools", [])) > INVENTORY_LIMIT
                     or any(not isinstance(tool, str) or not tool or len(tool) > 40 for tool in position.get("tools", []))
                    or is_house(position["x"], position["y"], map_data)
                    or not is_walkable(position["x"], position["y"], map_data)):
                raise InvalidMap("Every starting unit needs an open tile and a supported weapon.")
            tile = (position["x"], position["y"])
            if tile in occupied:
                raise InvalidMap("Starting units must have distinct tiles.")
            occupied.add(tile)
            if name == "enemyStartPositions":
                kings += position.get("is_king", False)
                guards += not position.get("is_king", False)
                if position.get("is_king", False) != (tile == (objective["x"], objective["y"])) and mission == "capture_king":
                    raise InvalidMap("The king must start on the throne and guards must start elsewhere.")
            if find_path((position["x"], position["y"]), (objective["x"], objective["y"]), map_data,
                         max_step_cost=move_allowance(position),
                         rope="rope" in position.get("tools", ())) is None:
                raise InvalidMap("Every starting unit must be able to reach the objective.")
            if name == "enemyStartPositions" and mission != "capture_king" and tile == (
                    objective["x"], objective["y"]):
                raise InvalidMap("Defenders cannot start on the objective.")
    if mission == "capture_king" and (kings != 1 or guards < 1):
        raise InvalidMap("A throne-room mission needs exactly one king and at least one guard.")
    catapults = map_data.get("catapults", [])
    if not isinstance(catapults, list) or len(catapults) > 16:
        raise InvalidMap("Catapults must be a list of at most 16 open ground tiles.")
    seen_catapults = set()
    for point in catapults:
        if (not isinstance(point, dict) or set(point) != {"x", "y"}
                or type(point["x"]) is not int or type(point["y"]) is not int
                or is_house(point["x"], point["y"], map_data)
                or not is_walkable(point["x"], point["y"], map_data)
                or tile_height(point["x"], point["y"], map_data) != 0
                or (point["x"], point["y"]) == (objective["x"], objective["y"])
                or (point["x"], point["y"]) in seen_catapults):
            raise InvalidMap("Catapults need distinct open ground tiles away from the objective.")
        seen_catapults.add((point["x"], point["y"]))
    horses = map_data.get("horses", [])
    if not isinstance(horses, list) or len(horses) > 16:
        raise InvalidMap("Horses must be a list of at most 16 open ground tiles.")
    seen_horses = set()
    for point in horses:
        if (not isinstance(point, dict) or set(point) != {"x", "y"}
                or type(point["x"]) is not int or type(point["y"]) is not int
                or not is_walkable(point["x"], point["y"], map_data)
                or is_house(point["x"], point["y"], map_data)
                or tile_height(point["x"], point["y"], map_data) != 0
                or (point["x"], point["y"]) == (objective["x"], objective["y"])
                or (point["x"], point["y"]) in seen_horses
                or any(tile["x"] == point["x"] and tile["y"] == point["y"] and tile["type"] == "swamp"
                       for tile in terrain)):
            raise InvalidMap("Horses need distinct open, flat, outdoor tiles away from the objective and swamps.")
        seen_horses.add((point["x"], point["y"]))
    items = map_data.get("items", [])
    if not isinstance(items, list) or len(items) > 32:
        raise InvalidMap("Items must be a list of at most 32 potions, tools or pieces of equipment.")
    seen_items = set()
    for item in items:
        if (not isinstance(item, dict) or set(item) not in ({"x", "y", "type"}, {"x", "y", "type", "name"})
                or type(item["x"]) is not int or type(item["y"]) is not int
                or not ((item["type"] == "healing_potion" and "name" not in item)
                        or (item["type"] == "weapon" and item.get("name") in ("sword", "longbow", "crossbow"))
                        or (item["type"] == "armor" and isinstance(item.get("name"), str)
                            and item["name"] in ARMOR_STATS)
                        or (item["type"] == "tool" and isinstance(item.get("name"), str)
                            and 0 < len(item["name"]) <= 40))
                or not is_walkable(item["x"], item["y"], map_data)
                or tile_height(item["x"], item["y"], map_data) != 0
                or (item["x"], item["y"]) in seen_items):
            raise InvalidMap("Items need valid types and names on distinct walkable ground tiles.")
        seen_items.add((item["x"], item["y"]))
    if "enemyStartPositions" not in map_data:
        legacy_enemy_position(map_data)


def is_keep_edge(x, y, map_data=MAP):
    return is_rectangle_edge(x, y, map_data["keep"])


def is_rectangle_edge(x, y, rectangle):
    inside = rectangle["left"] <= x <= rectangle["right"] and rectangle["top"] <= y <= rectangle["bottom"]
    edge = x in (rectangle["left"], rectangle["right"]) or y in (rectangle["top"], rectangle["bottom"])
    return inside and edge


def is_wall(x, y, map_data=MAP):
    return (x, y) not in map_data.get("breaches", ()) and any(
               is_rectangle_edge(x, y, point) and (x, y) != (gate["x"], gate["y"])
               for point, gate in [(map_data["keep"], map_data["gate"])]
               + [(point, point["gate"]) for point in map_data.get("strongpoints", ())])


def battle_map(map_data, state):
    """Use breached walls for all movement, cover and line-of-sight decisions."""
    return {**map_data, "breaches": {(point["x"], point["y"]) for point in state.get("breaches", [])}}


def is_object(x, y, map_data=MAP):
    return any(obj["x"] == x and obj["y"] == y for obj in map_data.get("objects", ()))


def is_house(x, y, map_data=MAP):
    return any(house["left"] <= x <= house["right"] and house["top"] <= y <= house["bottom"]
               for house in map_data.get("houses", ()))


def house_at(x, y, map_data=MAP):
    return next((index for index, house in enumerate(map_data.get("houses", ()))
                 if house["left"] <= x <= house["right"] and house["top"] <= y <= house["bottom"]
                 and "door" in house), None)


def blocks_sight(x, y, map_data=MAP, interior=None):
    return (is_wall(x, y, map_data) or (is_house(x, y, map_data)
            and (interior is None or house_at(x, y, map_data) != interior))
            or any(obj["x"] == x and obj["y"] == y and obj["type"] != "fence"
                   for obj in map_data.get("objects", ())))


def is_walkable(x, y, map_data=MAP):
    return (0 <= x < map_data["cols"] and 0 <= y < map_data["rows"]
            and not is_wall(x, y, map_data) and (not is_house(x, y, map_data) or house_at(x, y, map_data) is not None)
            and not is_object(x, y, map_data))


def elevation_index(map_data):
    return {(tile["x"], tile["y"]): tile for tile in map_data.get("elevation", [])}


def tile_height(x, y, map_data=MAP, elevations=None):
    if elevations is not None:
        return elevations.get((x, y), {}).get("height", 0)
    return next((tile["height"] for tile in map_data.get("elevation", [])
                 if tile["x"] == x and tile["y"] == y), 0)


def can_step(start, end, map_data=MAP, elevations=None, mounted=False, rope=False):
    if not is_walkable(*end, map_data):
        return False
    if mounted and any(tile["x"] == end[0] and tile["y"] == end[1] and tile["type"] == "swamp"
                       for tile in map_data.get("terrain", ())):
        return False
    before_house = house_at(*start, map_data)
    after_house = house_at(*end, map_data)
    if mounted and (before_house is not None or after_house is not None):
        return False
    if before_house != after_house:
        if before_house is not None and after_house is not None:
            return False
        house = map_data["houses"][before_house if before_house is not None else after_house]
        if (start if before_house is not None else end) != (house["door"]["x"], house["door"]["y"]):
            return False
    before = tile_height(*start, map_data, elevations)
    after = tile_height(*end, map_data, elevations)
    if before == after:
        return True
    if abs(before - after) != 1:
        return False
    high = end if after > before else start
    if rope and not mounted:
        return True
    if elevations is not None:
        return elevations[high].get("access") in (("ramp",) if mounted else ("ladder", "ramp"))
    return any(tile["x"] == high[0] and tile["y"] == high[1]
               and tile.get("access") in (("ramp",) if mounted else ("ladder", "ramp"))
               for tile in map_data.get("elevation", []))


def has_line_of_sight(start, end, map_data=MAP):
    """Return whether a tile-center ray reaches its target without crossing cover."""
    interior = house_at(*start, map_data)
    if interior != house_at(*end, map_data):
        return False
    x, y = start
    target_x, target_y = end
    dx, dy = target_x - x, target_y - y
    nx, ny = abs(dx), abs(dy)
    step_x = 1 if dx > 0 else -1 if dx < 0 else 0
    step_y = 1 if dy > 0 else -1 if dy < 0 else 0
    ix = iy = 0
    while ix < nx or iy < ny:
        horizontal = (1 + 2 * ix) * ny
        vertical = (1 + 2 * iy) * nx
        if horizontal == vertical:
            # At a corner, either adjoining obstacle blocks the shot.
            if ix < nx and iy < ny and (
                    blocks_sight(x + step_x, y, map_data, interior)
                    or blocks_sight(x, y + step_y, map_data, interior)):
                return False
            x += step_x
            y += step_y
            ix += 1
            iy += 1
        elif horizontal < vertical:
            x += step_x
            ix += 1
        else:
            y += step_y
            iy += 1
        if (x, y) != end and blocks_sight(x, y, map_data, interior):
            return False
    return True


def visible_tiles(state, map_data=MAP, side="attackers"):
    """Share line-of-sight visibility; at night only nearby or illuminated tiles are seen."""
    battlefield = battle_map(map_data, state)
    visible = set()
    night = map_data.get("night", False)
    extinguished = {(fire["x"], fire["y"]) for fire in state.get("extinguished_watchfires", ())}
    fires = [(fire["x"], fire["y"]) for fire in map_data.get("watchfires", ())
             if (fire["x"], fire["y"]) not in extinguished] if night else []
    # A carried torch lights its bearer to either side, but only its own side gets
    # the longer torch sight radius. A fire lights tiles, not observers behind walls.
    torch_bearers = {(unit["x"], unit["y"]) for unit in state["units"]
                     if "torch" in unit.get("tools", ()) and unit.get("torch_lit", True)} if night else set()
    for unit in state["units"]:
        if unit.get("side", "attackers") != side:
            continue
        start = (unit["x"], unit["y"])
        visible.add(start)
        for y in range(max(0, unit["y"] - VISION_RANGE), min(battlefield["rows"], unit["y"] + VISION_RANGE + 1)):
            for x in range(max(0, unit["x"] - VISION_RANGE), min(battlefield["cols"], unit["x"] + VISION_RANGE + 1)):
                tile = (x, y)
                if tile in visible:
                    continue
                distance = abs(x - unit["x"]) + abs(y - unit["y"])
                if night and distance > VISION_RANGE:
                    continue
                if night and not (distance <= NIGHT_VISION_RANGE
                                  or ("torch" in unit.get("tools", ()) and unit.get("torch_lit", True)
                                      and distance <= TORCH_VISION_RANGE)
                                  or tile in torch_bearers
                                  or any(abs(x - fx) + abs(y - fy) <= WATCHFIRE_LIGHT_RANGE
                                         and has_line_of_sight((fx, fy), tile, battlefield) for fx, fy in fires)):
                    continue
                if (distance == 1 and can_step(start, tile, battlefield)) or has_line_of_sight(start, tile, battlefield):
                    visible.add(tile)
    return visible


def remember_visibility(state, map_data=MAP):
    """Remember discovered ground in the server-owned snapshot, not enemy positions."""
    if map_data.get("fog_of_war", False):
        explored = {(tile["x"], tile["y"]) for tile in state.get("explored", ())}
        explored.update(visible_tiles(state, map_data))
        state["explored"] = [{"x": x, "y": y} for x, y in sorted(explored)]
    return state


def can_ranged_attack(attacker, target, map_data=MAP):
    stats = RANGED_WEAPON_STATS.get(normalize_unit(attacker)["weapon"])
    if not stats or attacker.get("reload_turns", 0) > 0:
        return False
    distance = max(abs(attacker["x"] - target["x"]), abs(attacker["y"] - target["y"]))
    return (distance > 0 and distance <= stats["range"]
            and has_line_of_sight((attacker["x"], attacker["y"]),
                                  (target["x"], target["y"]), map_data))


def trigger_reactions(state, target, map_data, combat_events=None):
    """Spend reserved attacks when a moving defender first enters a legal firing tile."""
    for attacker in state["units"][:]:
        if target not in state["units"]:
            break
        if attacker.get("side", "attackers") != "attackers" or not attacker.get("reaction_reserved"):
            continue
        ranged = attacker["weapon"] in RANGED_WEAPON_STATS
        eligible = (can_ranged_attack(attacker, target, map_data) if ranged else
                    attacker["weapon"] == "sword" and
                    abs(attacker["x"] - target["x"]) + abs(attacker["y"] - target["y"]) == 1 and
                    attacker["z"] == target["z"] and
                    can_step((attacker["x"], attacker["y"]), (target["x"], target["y"]), map_data,
                             mounted=attacker.get("mount_id") is not None))
        if not eligible or (map_data.get("fog_of_war", False) and
                            (target["x"], target["y"]) not in visible_tiles(state, map_data)):
            continue
        attacker["reaction_reserved"] = False
        if ranged:
            attacker["reload_turns"] = RANGED_WEAPON_STATS[attacker["weapon"]]["reload_turns"]
            if combat_events is not None:
                combat_events.append({
                    "type": "projectile", "weapon": attacker["weapon"],
                    "from": {"x": attacker["x"], "y": attacker["y"]},
                    "to": {"x": target["x"], "y": target["y"]},
                    **({"witnessed": True} if map_data.get("fog_of_war", False) else {}),
                })
        record_attack(state, attacker, target, ranged, map_data,
                      damage=2 if not ranged and attacker.get("mount_id") is not None else ATTACK_DAMAGE)
        state["history"][-1]["reaction"] = True


def trigger_movement_reactions(state, target, map_data):
    """Evade an adjacent visible mover by one affordable, unoccupied legal step."""
    for soldier in state["units"]:
        budget = soldier.get("move_reserved", 0)
        if not budget or soldier.get("side", "attackers") != "attackers":
            continue
        start = (soldier["x"], soldier["y"])
        threat = (target["x"], target["y"])
        if (abs(start[0] - threat[0]) + abs(start[1] - threat[1]) != 1
                or soldier["z"] != target["z"]
                or not can_step(start, threat, map_data)
                or map_data.get("fog_of_war", False) and threat not in visible_tiles(state, map_data)):
            continue
        occupied = {(unit["x"], unit["y"]) for unit in state["units"] if unit is not soldier}
        mounted = soldier.get("mount_id") is not None
        costs = terrain_cost_index(map_data, mounted)
        options = [tile for tile in neighbors(*start)
                   if tile not in occupied and costs.get(tile, 1) <= budget
                   and can_step(start, tile, map_data, mounted=mounted)
                   and abs(tile[0] - threat[0]) + abs(tile[1] - threat[1]) > 1]
        if not options:
            continue
        # Prefer distance, then lower terrain cost and stable map coordinates.
        tile = min(options, key=lambda point: (-abs(point[0] - threat[0]) - abs(point[1] - threat[1]),
                                                costs.get(point, 1), point[0], point[1]))
        soldier["x"], soldier["y"] = tile
        soldier["z"] = tile_height(*tile, map_data)
        soldier["facing"] = 1 if tile[0] >= start[0] else -1
        soldier["move_reserved"] = 0
        for horse in state["horses"]:
            if horse["rider_id"] == soldier["id"]:
                horse["x"], horse["y"] = tile


def terrain_cost_index(map_data, mounted=False):
    costs = MOUNTED_TERRAIN_COSTS if mounted else TERRAIN_COSTS
    return {(tile["x"], tile["y"]): costs.get(tile["type"])
            for tile in map_data.get("terrain", ())}


def affordable_steps(path, budget, terrain_costs):
    """Return the traversable prefix and MP spent without splitting a step across turns."""
    steps = []
    spent = 0
    for tile in path:
        cost = terrain_costs.get(tile, 1)
        if spent + cost > budget:
            break
        steps.append(tile)
        spent += cost
    return steps, spent


def find_path(start, goal, map_data=MAP, blocked=(), max_step_cost=None, mounted=False, rope=False):
    if (not is_walkable(*goal, map_data) or goal in blocked
            or mounted and house_at(*goal, map_data) is not None):
        return None
    elevations = elevation_index(map_data)
    terrain_costs = terrain_cost_index(map_data, mounted)
    frontier = [(0, 0, start)]
    sequence = 0
    distances = {start: 0}
    previous = {start: None}
    while frontier:
        distance, _, current = heappop(frontier)
        if distance != distances[current]:
            continue
        if current == goal:
            break
        x, y = current
        for neighbor in neighbors(x, y):
            if (neighbor in blocked or not can_step(current, neighbor, map_data, elevations, mounted, rope)
                    or terrain_costs.get(neighbor, 1) is None):
                continue
            cost = terrain_costs.get(neighbor, 1)
            if max_step_cost is not None and cost > max_step_cost:
                continue
            new_distance = distance + cost
            if new_distance < distances.get(neighbor, float("inf")):
                distances[neighbor] = new_distance
                previous[neighbor] = current
                sequence += 1
                heappush(frontier, (new_distance, sequence, neighbor))
    if goal not in previous:
        return None
    path = []
    point = goal
    while point != start:
        path.append(point)
        point = previous[point]
    return list(reversed(path))


def neighbors(x, y):
    return ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1))


def carried_weight(unit, items=()):
    """Everything carried counts, including unequipped armor and tools."""
    weapon = unit.get("weapon", LEGACY_WEAPONS.get(unit.get("type")))
    return (WEAPON_WEIGHTS.get(weapon, 0)
            + ARMOR_STATS.get(unit.get("armor"), {}).get("weight", 0)
            + len(unit.get("tools", [])) * TOOL_WEIGHT
            + sum(unit.get("id") is not None and item.get("carrier_id") == unit["id"]
                  for item in items) * POTION_WEIGHT)


def weight_penalty(unit, items=()):
    return carried_weight(unit, items) // WEIGHT_PER_MOVE_PENALTY


def move_allowance(unit, items=()):
    morale = unit.get("morale", STARTING_MORALE)
    mounted = unit.get("mount_id") is not None
    return max(1, (HORSE_MOVE_POINTS if mounted else MOVE_POINTS) + (unit.get("rank") == "veteran")
               + (morale == MAX_MORALE) - (morale <= 1) - (0 if mounted else weight_penalty(unit, items)))


def change_mount_movement(unit, old_capacity, items):
    """Change riding allowance without restoring points already spent this turn."""
    capacity = max(1, unit.get("move_capacity", old_capacity) + move_allowance(unit, items) - old_capacity)
    reserved = unit.get("move_reserved", 0)
    spent = max(0, unit.get("move_capacity", old_capacity) - unit["move_points"] - reserved)
    unit["move_reserved"] = min(reserved, max(0, capacity - spent))
    unit["move_capacity"] = capacity
    unit["move_points"] = max(0, capacity - spent - unit["move_reserved"])


def refresh_inventory_movement(unit, old_penalty, items):
    """Preserve points spent this turn when changing a load, without resetting morale/rank bonuses."""
    if unit.get("mount_id") is not None:
        old_penalty = new_penalty = 0
    else:
        new_penalty = weight_penalty(unit, items)
    if "move_capacity" not in unit:
        # Older matches do not record how many points were already spent this turn.
        unit["move_points"] = max(0, unit["move_points"] + old_penalty - new_penalty)
        unit["move_reserved"] = min(unit.get("move_reserved", 0), move_allowance(unit, items))
        if unit.get("crouched"):
            unit["move_points"] = 0
        return
    previous_capacity = unit["move_capacity"]
    capacity = max(1, previous_capacity + old_penalty - new_penalty)
    reserved = unit.get("move_reserved", 0)
    spent = max(0, previous_capacity - unit["move_points"] - reserved)
    unit["move_reserved"] = min(reserved, max(0, capacity - spent))
    unit["move_capacity"] = capacity
    unit["move_points"] = max(0, capacity - spent - unit["move_reserved"])
    if unit.get("crouched"):
        unit["move_points"] = 0


def fight_allowance(unit):
    return FIGHT_POINTS + (unit.get("rank") == "veteran")


def ranged_cover(attacker, target, map_data):
    """Find ground cover adjoining the target on the shooter's side."""
    if target["z"] != 0 or house_at(target["x"], target["y"], map_data) is not None:
        return None
    objects = {(obj["x"], obj["y"]): obj["type"] for obj in map_data.get("objects", ())}
    for x in range(target["x"] - 1, target["x"] + 2):
        for y in range(target["y"] - 1, target["y"] + 2):
            if (x, y) == (target["x"], target["y"]):
                continue
            if ((x - target["x"]) * (attacker["x"] - target["x"])
                    + (y - target["y"]) * (attacker["y"] - target["y"]) <= 0):
                continue
            if is_wall(x, y, map_data):
                return "wall"
            if is_house(x, y, map_data):
                return "house"
            if (x, y) in objects:
                return objects[x, y]
    return None


def drop_equipment(state, unit, kind, name):
    """Create a ground item with a stable ID, including on imported older matches."""
    if not name:
        return
    next_id = state.get("next_item_id")
    if next_id is None:
        previous = [item["id"] for item in state.get("items", ())]
        previous += [event["item_id"] for event in state.get("history", ()) if "item_id" in event]
        next_id = max(previous, default=-1) + 1
    state.setdefault("items", []).append({"id": next_id, "type": kind, "name": name,
                                           "x": unit["x"], "y": unit["y"], "carrier_id": None})
    state["next_item_id"] = next_id + 1


def record_casualty(state, killer, casualty):
    """A kill rallies its victor; nearby surviving comrades lose heart."""
    morale_changes = []
    before = killer["morale"]
    killer["morale"] = min(MAX_MORALE, killer["morale"] + 1)
    if killer["morale"] != before:
        morale_changes.append({"unit_id": killer["id"], "change": killer["morale"] - before})
    for unit in state["units"]:
        if unit is not casualty and unit.get("side", "attackers") == casualty.get("side", "attackers"):
            if max(abs(unit["x"] - casualty["x"]), abs(unit["y"] - casualty["y"])) <= 3:
                before = unit["morale"]
                unit["morale"] = max(0, unit["morale"] - 1)
                if unit["morale"] != before:
                    morale_changes.append({"unit_id": unit["id"], "change": unit["morale"] - before})
    for item in state.get("items", []):
        if item["carrier_id"] == casualty["id"]:
            item.update(carrier_id=None, x=casualty["x"], y=casualty["y"])
    for tool in casualty.get("tools", []):
        drop_equipment(state, casualty, "tool", tool)
    drop_equipment(state, casualty, "weapon", normalize_unit(casualty)["weapon"])
    drop_equipment(state, casualty, "armor", casualty.get("armor"))
    for horse in state.get("horses", []):
        if horse["rider_id"] == casualty["id"]:
            horse["rider_id"] = None
    state["units"].remove(casualty)
    return morale_changes


def armor_remaining(unit, turn):
    """Armor protection is spent by hits, not by equipping or blocked shots."""
    if not unit.get("armor_equipped", unit.get("armor") is not None):
        return 0
    armor = unit.get("armor")
    if armor not in ARMOR_STATS:
        return 0
    spent = unit.get("armor_absorbed", 0) if unit.get("armor_turn") == turn else 0
    return max(0, ARMOR_STATS[armor]["protection"] - spent)


def record_attack(state, attacker, target, ranged, map_data=MAP, damage=ATTACK_DAMAGE, weapon=None):
    """Resolve damage and retain a compact, chronological account of combat."""
    fog = map_data.get("fog_of_war", False)
    enemy = attacker if attacker.get("side", "attackers") == "defenders" else target
    witnessed = not fog or (enemy["x"], enemy["y"]) in visible_tiles(state, map_data)
    # Determine surprise before casualties change team sight. Catapult impacts are
    # indirect fire, not attacks made from a hidden soldier's position.
    ambush = (fog and weapon != "catapult" and
              (attacker["x"], attacker["y"]) not in visible_tiles(
                  state, map_data, target.get("side", "attackers")))
    if ambush:
        damage += AMBUSH_BONUS
    cover = (ranged_cover(attacker, target, map_data)
             if ranged and target.get("cover_turn") != state["turn"] else None)
    if cover:
        target["cover_turn"] = state["turn"]
    horse = next((horse for horse in state.get("horses", ()) if horse["id"] == target.get("mount_id")), None)
    stance_blocked = min(damage, 1) if ranged and weapon != "catapult" and not cover and not horse and target.get("crouched") else 0
    damage -= stance_blocked
    absorbed = 0 if cover or horse else min(damage, armor_remaining(target, state["turn"]))
    if absorbed:
        target["armor_absorbed"] = (target.get("armor_absorbed", 0)
                                    if target.get("armor_turn") == state["turn"] else 0) + absorbed
        target["armor_turn"] = state["turn"]
    damage = min(0 if cover else damage - absorbed, horse["health"] if horse else target["health"])
    if horse:
        horse["health"] -= damage
        if horse["health"] <= 0:
            state["horses"].remove(horse)
            old_capacity = move_allowance(target, state.get("items", ()))
            target["mount_id"] = None
            change_mount_movement(target, old_capacity, state.get("items", ()))
    else:
        target["health"] -= damage
    killed = target["health"] <= 0
    morale_changes = record_casualty(state, attacker, target) if killed else []
    state["history"] = (state["history"] + [{
        "turn": state["turn"], "type": "ranged_attack" if ranged else "attack",
        "actor_id": attacker["id"], "actor_side": attacker.get("side", "attackers"),
        "actor_weapon": attacker["weapon"], "target_id": target["id"],
        "target_side": target.get("side", "attackers"), "target_weapon": target["weapon"],
        "target_is_king": target.get("is_king", False),
        "damage": damage, "killed": killed, "morale_changes": morale_changes,
        **({"stance_blocked": stance_blocked} if stance_blocked else {}),
        **({"ambush": True} if ambush else {}),
        **({"witnessed": witnessed} if fog else {}),
        **({"horse_hit": True, "horse_killed": horse["health"] <= 0} if horse else {}),
        **({"weapon": weapon} if weapon else {}),
    } | ({"cover": cover} if cover else {}) | ({"armor_blocked": absorbed,
        "target_armor": target["armor"]} if absorbed else {})])[-HISTORY_LIMIT:]


def defender_destinations(unit, map_data=MAP, blocked=(), items=()):
    start = (unit["x"], unit["y"])
    objective = (map_data["objective"]["x"], map_data["objective"]["y"])
    frontier = [(0, 0, start)]
    distances = {start: 0}
    sequence = 0
    destinations = []
    elevations = elevation_index(map_data)
    mounted = unit.get("mount_id") is not None
    terrain_costs = terrain_cost_index(map_data, mounted)
    allowance = move_allowance(unit, items)
    while frontier:
        distance, _, (x, y) = heappop(frontier)
        if distance != distances[x, y]:
            continue
        if (x, y) != start and (x, y) != objective:
            destinations.append((x, y))
        for neighbor in neighbors(x, y):
            if (neighbor in blocked or neighbor == objective
                    or not can_step((x, y), neighbor, map_data, elevations, mounted,
                                    "rope" in unit.get("tools", ()))
                    or terrain_costs.get(neighbor, 1) is None):
                continue
            new_distance = distance + terrain_costs.get(neighbor, 1)
            if new_distance <= allowance and new_distance < distances.get(neighbor, float("inf")):
                distances[neighbor] = new_distance
                sequence += 1
                heappush(frontier, (new_distance, sequence, neighbor))
    return destinations


def resolve_defender_goals(state, goals, map_data=MAP):
    defenders = {unit["id"]: unit for unit in state["units"]
                 if unit.get("side") == "defenders" and not normalize_unit(unit).get("is_king")}
    if not isinstance(goals, list) or len(goals) > len(defenders):
        raise InvalidAction("Invalid defender goals.")
    orders = []
    seen = set()
    positions = {unit["id"]: (unit["x"], unit["y"]) for unit in state["units"]}
    objective = (map_data["objective"]["x"], map_data["objective"]["y"])

    def guarding(tile):
        return abs(tile[0] - objective[0]) + abs(tile[1] - objective[1]) <= 2

    for goal in goals:
        if not isinstance(goal, dict) or set(goal) != {"unit_id", "x", "y"}:
            raise InvalidAction("Invalid defender goal.")
        unit_id, x, y = goal["unit_id"], goal["x"], goal["y"]
        if (type(unit_id) is not int or unit_id not in defenders or unit_id in seen
                or type(x) is not int or type(y) is not int
                or not (0 <= x < map_data["cols"] and 0 <= y < map_data["rows"])):
            raise InvalidAction("Invalid defender goal.")
        seen.add(unit_id)
        unit = defenders[unit_id]
        start = positions[unit_id]
        if (x, y) == start:
            continue
        blocked = set(positions.values()) - {start}
        destinations = defender_destinations(unit, map_data, blocked, state.get("items", ()))
        if not destinations:
            continue
        # A nearby garrison must not abandon the objective unless another defender
        # is already guarding it. Apply this to reachable tiles, not raw AI goals.
        if guarding(start) and not any(
                guarding(positions[other_id]) for other_id in defenders if other_id != unit_id):
            destinations = [tile for tile in destinations if guarding(tile)]
            if not destinations:
                continue
        route = find_path(start, (x, y), map_data, blocked=blocked | {objective},
                          max_step_cost=move_allowance(unit, state.get("items", ())),
                          mounted=unit.get("mount_id") is not None,
                          rope="rope" in unit.get("tools", ()))
        affordable, _ = affordable_steps(route or [], move_allowance(unit, state.get("items", ())),
                                          terrain_cost_index(map_data, unit.get("mount_id") is not None))
        along_route = [tile for tile in affordable if tile in destinations]
        if along_route:
            destination = along_route[-1]
        else:
            destination = min(
                destinations,
                key=lambda tile: (abs(tile[0] - x) + abs(tile[1] - y),
                                  abs(tile[0] - start[0]) + abs(tile[1] - start[1])),
            )
        orders.append({"unit_id": unit_id, "x": destination[0], "y": destination[1]})
        positions[unit_id] = destination
    return orders


def legacy_enemy_position(map_data):
    # Existing saved maps need a garrison without changing their snapshotted geometry.
    objective = (map_data["objective"]["x"], map_data["objective"]["y"])
    occupied = {(point["x"], point["y"]) for point in map_data["startPositions"]}
    frontier = deque([objective])
    visited = {objective}
    elevations = elevation_index(map_data)
    while frontier:
        x, y = frontier.popleft()
        if (x, y) != objective and (x, y) not in occupied:
            return {"x": x, "y": y, "weapon": "sword"}
        for neighbor in neighbors(x, y):
            if neighbor not in visited and can_step((x, y), neighbor, map_data, elevations):
                visited.add(neighbor)
                frontier.append(neighbor)
    raise InvalidMap("The objective needs a reachable free tile for a defender.")


def initial_state(map_data=MAP):
    enemy_positions = map_data.get("enemyStartPositions")
    if enemy_positions is None:
        enemy_positions = [legacy_enemy_position(map_data)]
    attackers = map_data["startPositions"]
    state = {
        "turn": 1,
        "units": [
            {
                "id": index,
                "x": point["x"],
                "y": point["y"],
                "z": tile_height(point["x"], point["y"], map_data),
                "weapon": normalize_position(point)["weapon"],
                "tools": list(point.get("tools", [])),
                "torch_lit": True,
                "armor": point.get("armor"),
                "armor_equipped": point.get("armor") is not None,
                "mount_id": None,
                **({"is_king": True} if normalize_position(point).get("is_king") else {}),
                "side": "attackers" if index < len(attackers) else "defenders",
                "facing": 1 if index < len(attackers) else -1,
                "move_points": move_allowance(point),
                "move_capacity": move_allowance(point),
                "health": MAX_HEALTH,
                "max_health": MAX_HEALTH,
                "fight_points": FIGHT_POINTS,
                "fight_capacity": FIGHT_POINTS,
                "reload_turns": 0,
                "reaction_reserved": False,
                "move_reserved": 0,
                "crouched": False,
                "morale": STARTING_MORALE,
                "rank": "recruit",
            }
            for index, point in enumerate(attackers + enemy_positions)
        ],
        "capture_progress": 0,
        "captured": False,
        "defeated": False,
        "history": [],
        "catapults": [
            {"id": index, "x": point["x"], "y": point["y"], "ammo": CATAPULT_AMMO,
             "reload_turns": 0, "aim": None}
            for index, point in enumerate(map_data.get("catapults", []))
        ],
        "horses": [
            {"id": index, "x": point["x"], "y": point["y"], "health": HORSE_HEALTH,
             "max_health": HORSE_HEALTH, "rider_id": None}
            for index, point in enumerate(map_data.get("horses", []))
        ],
        "wall_damage": [],
        "breaches": [],
        "extinguished_watchfires": [],
        "items": [
            {"id": index, "type": item["type"], **({"name": item["name"]} if "name" in item else {}),
             "x": item["x"], "y": item["y"], "carrier_id": None}
            for index, item in enumerate(map_data.get("items", []))
        ],
        "next_item_id": len(map_data.get("items", [])),
    }
    return remember_visibility(state, map_data)


def capture_status(state, map_data=MAP):
    if state.get("defeated", False):
        return "DEFEATED"
    if state["captured"]:
        return "KING CAPTURED" if map_data.get("mission") == "capture_king" else "SECURED"
    if map_data.get("mission") == "capture_king":
        return "KING GUARDED" if king_is_guarded(state) else "CAPTURE THE KING"
    objective = map_data["objective"]
    if any((unit["x"], unit["y"]) == (objective["x"], objective["y"])
           and unit.get("side", "attackers") == "attackers" for unit in state["units"]):
        return "CAPTURING"
    return "CONTESTED" if state["capture_progress"] else "UNCLAIMED"


def king_is_guarded(state):
    king = next((unit for unit in state["units"] if normalize_unit(unit).get("is_king")), None)
    return bool(king and any(
        unit.get("side") == "defenders" and not normalize_unit(unit).get("is_king")
        and abs(unit["x"] - king["x"]) + abs(unit["y"] - king["y"]) == 1
        and unit["z"] == king["z"] for unit in state["units"]
    ))


def apply_action(state, action, map_data=MAP, enemy_orders=(), combat_events=None):
    if not isinstance(action, dict) or action.get("type") not in (
            "move", "attack", "ranged_attack", "capture", "promote", "end_turn",
            "aim_catapult", "fire_catapult", "pickup_item", "drop_item", "use_item", "equip_armor",
            "pickup_equipment", "drop_weapon", "drop_armor", "pickup_tool", "drop_tool",
            "mount", "dismount", "reserve_reaction", "reserve_movement",
            "crouch",
            "light_watchfire", "extinguish_watchfire", "toggle_torch"):
        raise InvalidAction("Unknown action.")
    if state["captured"] or state.get("defeated", False):
        raise InvalidAction("The battle has already ended.")

    map_data = battle_map(map_data, state)
    next_state = {**state, "units": [
        {
            **normalize_unit(unit),
            "tools": list(unit.get("tools", [])),
            "z": tile_height(unit["x"], unit["y"], map_data),
            "health": unit.get("health", MAX_HEALTH),
            "max_health": unit.get("max_health", MAX_HEALTH),
            "fight_points": unit.get("fight_points", FIGHT_POINTS),
            "reload_turns": unit.get("reload_turns", 0),
            "morale": unit.get("morale", STARTING_MORALE),
            "rank": unit.get("rank", "recruit"),
        }
        for unit in state["units"]
    ], "defeated": state.get("defeated", False),
        "history": [normalize_history_event(event) for event in state.get("history", [])],
        "catapults": [
            {**catapult, "aim": catapult.get("aim"), "reload_turns": catapult.get("reload_turns", 0)}
            for catapult in state.get("catapults", [])
        ], "horses": [dict(horse) for horse in state.get("horses", [])],
        "wall_damage": [dict(point) for point in state.get("wall_damage", [])],
        "breaches": [dict(point) for point in state.get("breaches", [])],
        "extinguished_watchfires": [dict(point) for point in state.get("extinguished_watchfires", [])],
        "items": [dict(item) for item in state.get("items", [])]}
    if action["type"] == "crouch":
        if set(action) != {"type", "unit_id"} or type(action["unit_id"]) is not int:
            raise InvalidAction("Choose a soldier to crouch.")
        unit = next((unit for unit in next_state["units"] if unit["id"] == action["unit_id"]
                     and unit.get("side", "attackers") == "attackers"), None)
        if (unit is None or unit["fight_points"] < 1 or unit["crouched"]
                or unit.get("mount_id") is not None or unit["move_reserved"]):
            raise InvalidAction("Crouching requires one fight point, no mount and no movement reservation.")
        unit["fight_points"] -= 1
        unit["move_points"] = 0
        unit["crouched"] = True
        return next_state
    if action["type"] == "toggle_torch":
        if (set(action) != {"type", "unit_id", "lit"} or type(action["unit_id"]) is not int
                or type(action["lit"]) is not bool):
            raise InvalidAction("Choose a soldier and whether to light their torch.")
        unit = next((unit for unit in next_state["units"] if unit["id"] == action["unit_id"]
                     and unit.get("side", "attackers") == "attackers"), None)
        if (not map_data.get("night") or unit is None or "torch" not in unit["tools"]
                or unit["fight_points"] < 1 or unit["torch_lit"] == action["lit"]):
            raise InvalidAction("A soldier needs a carried torch and one fight point to change its light.")
        unit["torch_lit"] = action["lit"]
        unit["fight_points"] -= 1
        next_state["history"] = (next_state["history"] + [{
            "turn": state["turn"], "type": "toggle_torch", "actor_id": unit["id"],
            "actor_side": "attackers", "actor_weapon": unit["weapon"], "lit": unit["torch_lit"],
        }])[-HISTORY_LIMIT:]
        return remember_visibility(next_state, map_data)
    if action["type"] in ("light_watchfire", "extinguish_watchfire"):
        if (set(action) != {"type", "unit_id", "x", "y"}
                or any(type(action[key]) is not int for key in ("unit_id", "x", "y"))):
            raise InvalidAction("Choose a soldier and a watchfire tile.")
        unit = next((unit for unit in next_state["units"] if unit["id"] == action["unit_id"]
                     and unit.get("side", "attackers") == "attackers"), None)
        position = (action["x"], action["y"])
        if (not map_data.get("night") or unit is None or unit["fight_points"] < 1
                or position not in {(fire["x"], fire["y"]) for fire in map_data.get("watchfires", ())}
                or abs(unit["x"] - position[0]) + abs(unit["y"] - position[1]) > 1
                or unit["z"] != tile_height(*position, map_data)
                or (unit["x"], unit["y"]) != position
                and not can_step((unit["x"], unit["y"]), position, map_data)):
            raise InvalidAction("A soldier needs one fight point on or beside a reachable watchfire.")
        extinguished = next_state["extinguished_watchfires"]
        is_out = any((fire["x"], fire["y"]) == position for fire in extinguished)
        if is_out != (action["type"] == "light_watchfire"):
            raise InvalidAction("That watchfire is already in the requested state.")
        if is_out:
            extinguished[:] = [fire for fire in extinguished if (fire["x"], fire["y"]) != position]
        else:
            extinguished.append({"x": position[0], "y": position[1]})
        unit["fight_points"] -= 1
        next_state["history"] = (next_state["history"] + [{
            "turn": state["turn"], "type": action["type"], "actor_id": unit["id"],
            "actor_side": "attackers", "actor_weapon": unit["weapon"],
            "x": position[0], "y": position[1],
        }])[-HISTORY_LIMIT:]
        return remember_visibility(next_state, map_data)
    if action["type"] == "reserve_reaction":
        if (set(action) != {"type", "unit_id", "reserved"} or type(action["unit_id"]) is not int
                or type(action["reserved"]) is not bool):
            raise InvalidAction("Choose a soldier and whether to reserve a reaction.")
        unit = next((unit for unit in next_state["units"] if unit["id"] == action["unit_id"]
                     and unit.get("side", "attackers") == "attackers"), None)
        if (unit is None or unit.get("reaction_reserved", False) == action["reserved"]
                or action["reserved"] and (unit["fight_points"] < 1 or
                                            unit["weapon"] not in ("sword", *RANGED_WEAPON_STATS) or
                                            unit.get("reload_turns", 0) > 0)):
            raise InvalidAction("This soldier cannot change their reaction reservation.")
        unit["reaction_reserved"] = action["reserved"]
        unit["fight_points"] += -1 if action["reserved"] else 1
        return next_state
    if action["type"] == "reserve_movement":
        if (set(action) != {"type", "unit_id", "reserved"} or type(action["unit_id"]) is not int
                or type(action["reserved"]) is not bool):
            raise InvalidAction("Choose a soldier and whether to reserve movement.")
        unit = next((unit for unit in next_state["units"] if unit["id"] == action["unit_id"]
                     and unit.get("side", "attackers") == "attackers"), None)
        if (unit is None or bool(unit["move_reserved"]) == action["reserved"]
                or action["reserved"] and (unit["move_points"] < 1 or unit["crouched"])):
            raise InvalidAction("This soldier cannot change their movement reservation.")
        if action["reserved"]:
            unit["move_reserved"] = unit["move_points"]
            unit["move_points"] = 0
        else:
            unit["move_points"] += unit["move_reserved"]
            unit["move_reserved"] = 0
        return next_state
    if action["type"] in ("mount", "dismount"):
        mounting = action["type"] == "mount"
        required = {"type", "unit_id", "horse_id"} if mounting else {"type", "unit_id"}
        if set(action) != required or type(action["unit_id"]) is not int or (mounting and type(action["horse_id"]) is not int):
            raise InvalidAction("Choose a soldier and a valid horse.")
        unit = next((unit for unit in next_state["units"] if unit["id"] == action["unit_id"]
                     and unit.get("side", "attackers") == "attackers"), None)
        if unit is None or unit["fight_points"] < 1 or unit["crouched"]:
            raise InvalidAction("A living soldier needs one fight point to mount or dismount.")
        if mounting:
            horse = next((horse for horse in next_state["horses"] if horse["id"] == action["horse_id"]), None)
            if (not horse or horse["rider_id"] is not None or unit["mount_id"] is not None
                    or (horse["x"], horse["y"]) != (unit["x"], unit["y"])
                    or house_at(unit["x"], unit["y"], map_data) is not None):
                raise InvalidAction("Stand on an unmounted horse on open, level ground.")
        else:
            horse = next((horse for horse in next_state["horses"] if horse["id"] == unit["mount_id"]), None)
            if horse is None:
                raise InvalidAction("This soldier is not mounted.")
        old_capacity = move_allowance(unit, next_state["items"])
        unit["mount_id"] = horse["id"] if mounting else None
        horse["rider_id"] = unit["id"] if mounting else None
        change_mount_movement(unit, old_capacity, next_state["items"])
        unit["fight_points"] -= 1
        next_state["history"] = (next_state["history"] + [{
            "turn": state["turn"], "type": action["type"], "actor_id": unit["id"],
            "actor_side": "attackers", "actor_weapon": unit["weapon"], "horse_id": horse["id"],
        }])[-HISTORY_LIMIT:]
        return remember_visibility(next_state, map_data)
    if action["type"] == "equip_armor":
        if (set(action) != {"type", "unit_id", "equipped"}
                or type(action["unit_id"]) is not int or type(action["equipped"]) is not bool):
            raise InvalidAction("Choose a soldier and whether to equip their armor.")
        unit = next((unit for unit in next_state["units"] if unit["id"] == action["unit_id"]
                     and unit.get("side", "attackers") == "attackers"), None)
        if (unit is None or unit["armor"] not in ARMOR_STATS or unit["fight_points"] < 1
                or unit["armor_equipped"] == action["equipped"]):
            raise InvalidAction("A living soldier needs armor and a fight point to change equipment.")
        unit["armor_equipped"] = action["equipped"]
        unit["fight_points"] -= 1
        next_state["history"] = (next_state["history"] + [{
            "turn": state["turn"], "type": "equip_armor", "actor_id": unit["id"],
            "actor_side": "attackers", "actor_weapon": unit["weapon"],
            "armor": unit["armor"], "equipped": unit["armor_equipped"],
        }])[-HISTORY_LIMIT:]
        return remember_visibility(next_state, map_data)
    if action["type"] in ("drop_weapon", "drop_armor", "pickup_equipment"):
        picking_up = action["type"] == "pickup_equipment"
        required = {"type", "unit_id", "item_id"} if picking_up else {"type", "unit_id"}
        if set(action) != required or any(type(action[key]) is not int for key in required - {"type"}):
            raise InvalidAction("Choose a soldier and valid equipment.")
        unit = next((unit for unit in next_state["units"] if unit["id"] == action["unit_id"]
                     and unit.get("side", "attackers") == "attackers"), None)
        if unit is None or unit["fight_points"] < 1:
            raise InvalidAction("A living soldier needs one fight point to handle equipment.")
        if picking_up:
            item = next((item for item in next_state["items"] if item["id"] == action["item_id"]), None)
            if (item is None or item["type"] not in ("weapon", "armor") or item["carrier_id"] is not None
                    or (item["x"], item["y"]) != (unit["x"], unit["y"])):
                raise InvalidAction("Stand on a piece of equipment to recover it.")
            kind, name = item["type"], item.get("name")
            if ((kind == "weapon" and (name not in ("sword", "longbow", "crossbow") or unit["weapon"] is not None))
                    or (kind == "armor" and (name not in ARMOR_STATS or unit["armor"] is not None))):
                raise InvalidAction("Free the matching weapon or armor slot before recovering equipment.")
            weight = WEAPON_WEIGHTS[name] if kind == "weapon" else ARMOR_STATS[name]["weight"]
            if carried_weight(unit, next_state["items"]) + weight > MAX_CARRY_WEIGHT:
                raise InvalidAction("This soldier cannot carry more than eight weight.")
        else:
            kind = "weapon" if action["type"] == "drop_weapon" else "armor"
            name = unit[kind]
            if not name:
                raise InvalidAction("That soldier has no equipment in this slot.")
        old_penalty = weight_penalty(unit, next_state["items"])
        actor_weapon = unit["weapon"]
        if picking_up:
            next_state["items"].remove(item)
            unit[kind] = name
            if kind == "armor":
                unit["armor_equipped"] = True
        else:
            drop_equipment(next_state, unit, kind, name)
            unit[kind] = None
            if kind == "armor":
                unit["armor_equipped"] = False
        refresh_inventory_movement(unit, old_penalty, next_state["items"])
        unit["fight_points"] -= 1
        next_state["history"] = (next_state["history"] + [{
            "turn": state["turn"], "type": action["type"], "actor_id": unit["id"],
            "actor_side": "attackers", "actor_weapon": actor_weapon, "equipment": name,
        }])[-HISTORY_LIMIT:]
        return remember_visibility(next_state, map_data)
    if action["type"] in ("pickup_tool", "drop_tool"):
        picking_up = action["type"] == "pickup_tool"
        required = {"type", "unit_id", "item_id" if picking_up else "tool_index"}
        if set(action) != required or any(type(action[key]) is not int for key in required - {"type"}):
            raise InvalidAction("Choose a soldier and a valid tool.")
        unit = next((unit for unit in next_state["units"] if unit["id"] == action["unit_id"]
                     and unit.get("side", "attackers") == "attackers"), None)
        if unit is None or unit["fight_points"] < 1:
            raise InvalidAction("A living soldier needs one fight point to handle a tool.")
        if picking_up:
            item = next((item for item in next_state["items"] if item["id"] == action["item_id"]), None)
            if (item is None or item["type"] != "tool" or item["carrier_id"] is not None
                    or (item["x"], item["y"]) != (unit["x"], unit["y"])):
                raise InvalidAction("Stand on a tool to pick it up.")
            if len(unit["tools"]) >= INVENTORY_LIMIT or carried_weight(unit, next_state["items"]) + TOOL_WEIGHT > MAX_CARRY_WEIGHT:
                raise InvalidAction("A soldier can carry at most two tools and eight weight.")
            name = item["name"]
        else:
            index = action["tool_index"]
            if not 0 <= index < len(unit["tools"]):
                raise InvalidAction("Choose a carried tool to drop.")
            name = unit["tools"][index]
        old_penalty = weight_penalty(unit, next_state["items"])
        if picking_up:
            next_state["items"].remove(item)
            if name == "torch" and "torch" not in unit["tools"]:
                unit["torch_lit"] = True
            unit["tools"].append(name)
        else:
            drop_equipment(next_state, unit, "tool", name)
            unit["tools"].pop(index)
            if name == "torch" and "torch" not in unit["tools"]:
                unit["torch_lit"] = True
        refresh_inventory_movement(unit, old_penalty, next_state["items"])
        unit["fight_points"] -= 1
        next_state["history"] = (next_state["history"] + [{
            "turn": state["turn"], "type": action["type"], "actor_id": unit["id"],
            "actor_side": "attackers", "actor_weapon": unit["weapon"], "tool": name,
        }])[-HISTORY_LIMIT:]
        return remember_visibility(next_state, map_data)
    if action["type"] in ("pickup_item", "drop_item", "use_item"):
        operation = action["type"]
        required_fields = {"type", "unit_id", "item_id"} | ({"target_id"} if operation == "use_item" else set())
        if set(action) != required_fields or any(type(action[key]) is not int for key in required_fields - {"type"}):
            raise InvalidAction("Choose a soldier, potion and valid healing target.")
        unit = next((unit for unit in next_state["units"] if unit["id"] == action["unit_id"]
                     and unit.get("side", "attackers") == "attackers"), None)
        item = next((item for item in next_state["items"] if item["id"] == action["item_id"]), None)
        if not unit or not item or item["type"] != "healing_potion" or unit["fight_points"] < 1:
            raise InvalidAction("A living soldier needs a fight point to handle a potion.")
        if operation == "pickup_item":
            if (item["carrier_id"] is not None or (item["x"], item["y"]) != (unit["x"], unit["y"]) or
                    sum(other["carrier_id"] == unit["id"] for other in next_state["items"]) >= INVENTORY_LIMIT):
                raise InvalidAction("Stand on the potion with room to carry it (maximum two).")
            if carried_weight(unit, next_state["items"]) + POTION_WEIGHT > MAX_CARRY_WEIGHT:
                raise InvalidAction("This soldier cannot carry more than eight weight.")
            old_penalty = weight_penalty(unit, next_state["items"])
            item.update(carrier_id=unit["id"], x=None, y=None)
        elif item["carrier_id"] != unit["id"]:
            raise InvalidAction("That soldier is not carrying this potion.")
        elif operation == "drop_item":
            old_penalty = weight_penalty(unit, next_state["items"])
            item.update(carrier_id=None, x=unit["x"], y=unit["y"])
        else:
            target = next((other for other in next_state["units"] if other["id"] == action["target_id"]
                           and other.get("side", "attackers") == "attackers"), None)
            if (not target or target["health"] >= target["max_health"] or
                    (target is not unit and (abs(target["x"] - unit["x"]) + abs(target["y"] - unit["y"]) != 1
                     or target["z"] != unit["z"]
                     or not can_step((unit["x"], unit["y"]), (target["x"], target["y"]), map_data)))):
                raise InvalidAction("Heal a wounded ally on your tile or an adjacent reachable tile at the same height.")
            healed = min(POTION_HEAL, target["max_health"] - target["health"])
            target["health"] += healed
            old_penalty = weight_penalty(unit, next_state["items"])
            next_state["items"].remove(item)
        refresh_inventory_movement(unit, old_penalty, next_state["items"])
        unit["fight_points"] -= 1
        next_state["history"] = (next_state["history"] + [{
            "turn": state["turn"], "type": operation, "actor_id": unit["id"],
            "actor_side": "attackers", "actor_weapon": unit["weapon"],
            "item_id": item["id"],
            **({"target_id": target["id"], "healed": healed} if operation == "use_item" else {}),
        }])[-HISTORY_LIMIT:]
        return remember_visibility(next_state, map_data)
    if action["type"] in ("aim_catapult", "fire_catapult"):
        aiming = action["type"] == "aim_catapult"
        if (set(action) != ({"type", "unit_id", "catapult_id", "x", "y"} if aiming else
                            {"type", "unit_id", "catapult_id"})
                or type(action["unit_id"]) is not int or type(action["catapult_id"]) is not int
                or (aiming and (type(action["x"]) is not int or type(action["y"]) is not int))):
            raise InvalidAction("Choose a soldier, catapult and valid target tile.")
        unit = next((unit for unit in next_state["units"] if unit["id"] == action["unit_id"]
                     and unit.get("side", "attackers") == "attackers"), None)
        catapult = next((item for item in next_state["catapults"] if item["id"] == action["catapult_id"]), None)
        if (not unit or not catapult or (unit["x"], unit["y"]) != (catapult["x"], catapult["y"])
                or unit["fight_points"] < 1 or unit["mount_id"] is not None):
            raise InvalidAction("A soldier on the catapult needs a fight point to crew it.")
        if catapult["ammo"] < 1:
            raise InvalidAction("The catapult is out of ammunition.")
        if aiming:
            x, y = action["x"], action["y"]
            distance = max(abs(x - catapult["x"]), abs(y - catapult["y"]))
            if not (0 <= x < map_data["cols"] and 0 <= y < map_data["rows"] and 2 <= distance <= CATAPULT_RANGE):
                raise InvalidAction("Aim at a tile between 2 and 10 tiles from the catapult.")
            catapult["aim"] = {"x": x, "y": y}
            unit["fight_points"] -= 1
            next_state["history"] = (next_state["history"] + [{
                "turn": state["turn"], "type": "aim_catapult", "actor_id": unit["id"],
                "actor_side": "attackers", "actor_weapon": unit["weapon"], "x": x, "y": y,
            }])[-HISTORY_LIMIT:]
        else:
            if catapult["aim"] is None or catapult["reload_turns"]:
                raise InvalidAction("Aim the catapult and wait for it to reload before firing.")
            target = catapult["aim"]
            x, y = target["x"], target["y"]
            unit["fight_points"] -= 1
            catapult["ammo"] -= 1
            catapult["reload_turns"] = CATAPULT_RELOAD
            catapult["aim"] = None
            if combat_events is not None:
                combat_events.append({"type": "projectile", "weapon": "catapult",
                                      "from": {"x": catapult["x"], "y": catapult["y"]}, "to": target})
            victim = next((other for other in next_state["units"] if (other["x"], other["y"]) == (x, y)
                           and house_at(x, y, map_data) is None), None)
            if victim:
                record_attack(next_state, unit, victim, False, map_data, damage=2, weapon="catapult")
                if map_data.get("mission") == "capture_king" and victim.get("is_king") and victim["health"] <= 0:
                    next_state["defeated"] = True
                if not any(other.get("side", "attackers") == "attackers" for other in next_state["units"]):
                    next_state["defeated"] = True
            elif is_wall(x, y, map_data):
                damaged = next((point for point in next_state["wall_damage"] if (point["x"], point["y"]) == (x, y)), None)
                if damaged is None:
                    damaged = {"x": x, "y": y, "damage": 0}
                    next_state["wall_damage"].append(damaged)
                damaged["damage"] += 1
                if damaged["damage"] >= WALL_HEALTH:
                    next_state["breaches"].append({"x": x, "y": y})
                    next_state["wall_damage"].remove(damaged)
                next_state["history"] = (next_state["history"] + [{
                    "turn": state["turn"], "type": "catapult_wall", "actor_id": unit["id"],
                    "actor_side": "attackers", "actor_weapon": unit["weapon"], "x": x, "y": y,
                    "breached": damaged["damage"] >= WALL_HEALTH,
                }])[-HISTORY_LIMIT:]
            else:
                next_state["history"] = (next_state["history"] + [{
                    "turn": state["turn"], "type": "catapult_miss", "actor_id": unit["id"],
                    "actor_side": "attackers", "actor_weapon": unit["weapon"], "x": x, "y": y,
                }])[-HISTORY_LIMIT:]
        return remember_visibility(next_state, map_data)
    if action["type"] == "capture":
        if (map_data.get("mission") != "capture_king" or set(action) != {"type", "unit_id"}
                or type(action["unit_id"]) is not int):
            raise InvalidAction("Choose one soldier to capture the king.")
        unit = next((unit for unit in next_state["units"] if unit["id"] == action["unit_id"]
                     and unit.get("side") == "attackers"), None)
        king = next((unit for unit in next_state["units"] if unit.get("is_king")), None)
        if not unit or not king or unit["fight_points"] < 1 or unit["weapon"] != "sword":
            raise InvalidAction("A soldier with a sword and a fight point must capture the living king.")
        if (abs(unit["x"] - king["x"]) + abs(unit["y"] - king["y"]) != 1
                or unit["z"] != king["z"]):
            raise InvalidAction("Move beside the king on the same level to capture him.")
        if king_is_guarded(next_state):
            raise InvalidAction("Remove the guards beside the king before capturing him.")
        unit["fight_points"] -= 1
        next_state["captured"] = True
        next_state["capture_progress"] = 1
        next_state["history"] = (next_state["history"] + [{
            "turn": state["turn"], "type": "capture", "actor_id": unit["id"],
            "actor_side": "attackers", "actor_weapon": unit["weapon"],
            "target_id": king["id"], "target_side": "defenders", "target_weapon": king["weapon"],
            "target_is_king": True,
        }])[-HISTORY_LIMIT:]
        return remember_visibility(next_state, map_data)
    if action["type"] == "promote":
        if set(action) != {"type", "unit_id"} or type(action["unit_id"]) is not int:
            raise InvalidAction("Choose one soldier to promote.")
        unit = next((unit for unit in next_state["units"] if unit["id"] == action["unit_id"]
                     and unit.get("side", "attackers") == "attackers"), None)
        if unit is None or unit["rank"] != "recruit" or unit["morale"] < MAX_MORALE:
            raise InvalidAction("Only a recruit with five morale can become a veteran.")
        unit["rank"] = "veteran"
        unit["morale"] = STARTING_MORALE
        # New point allowances take effect on the next turn, not mid-turn.
        next_state["history"] = (next_state["history"] + [{
            "turn": next_state["turn"], "type": "promote", "actor_id": unit["id"],
            "actor_side": "attackers", "actor_weapon": unit["weapon"],
            "morale_change": STARTING_MORALE - MAX_MORALE,
        }])[-HISTORY_LIMIT:]
        return remember_visibility(next_state, map_data)
    if action["type"] in ("attack", "ranged_attack"):
        ranged = action["type"] == "ranged_attack"
        if set(action) != {"type", "unit_id", "target_id"}:
            raise InvalidAction("Invalid attack action.")
        unit_id, target_id = action["unit_id"], action["target_id"]
        if type(unit_id) is not int or type(target_id) is not int:
            raise InvalidAction("Choose a valid attacker and target.")
        units = {unit["id"]: unit for unit in next_state["units"]}
        attacker, target = units.get(unit_id), units.get(target_id)
        if attacker is None or attacker.get("side", "attackers") != "attackers":
            raise InvalidAction("Only your soldiers can attack.")
        if (target is None or target.get("side", "attackers") != "defenders"
                or map_data.get("fog_of_war", False) and (target["x"], target["y"]) not in visible_tiles(state, map_data)):
            raise InvalidAction("Choose a visible defender as the target." if map_data.get("fog_of_war", False)
                                else "Choose a living defender as the target.")
        if ranged and attacker["weapon"] not in RANGED_WEAPON_STATS:
            raise InvalidAction("Only soldiers carrying bows or crossbows can make ranged attacks.")
        if not ranged and attacker["weapon"] in RANGED_WEAPON_STATS:
            raise InvalidAction("Soldiers carrying bows or crossbows must use ranged attacks.")
        if not ranged and attacker["weapon"] != "sword":
            raise InvalidAction("A soldier needs a sword to make a melee attack.")
        if attacker["fight_points"] < 1:
            raise InvalidAction("This soldier has no fight points left.")
        if ranged:
            if attacker.get("reload_turns", 0) > 0:
                raise InvalidAction("This soldier is reloading.")
            distance = max(abs(attacker["x"] - target["x"]), abs(attacker["y"] - target["y"]))
            if distance == 0 or distance > RANGED_WEAPON_STATS[attacker["weapon"]]["range"]:
                raise InvalidAction("That defender is outside this weapon's range.")
            if not has_line_of_sight((attacker["x"], attacker["y"]),
                                     (target["x"], target["y"]), map_data):
                raise InvalidAction("An obstacle blocks the line of sight.")
            attacker["reload_turns"] = RANGED_WEAPON_STATS[attacker["weapon"]]["reload_turns"]
            if combat_events is not None:
                combat_events.append({
                    "type": "projectile", "weapon": attacker["weapon"],
                    "from": {"x": attacker["x"], "y": attacker["y"]},
                    "to": {"x": target["x"], "y": target["y"]},
                })
        elif (abs(attacker["x"] - target["x"]) + abs(attacker["y"] - target["y"]) != 1
              or attacker["z"] != target["z"]
              or not can_step((attacker["x"], attacker["y"]), (target["x"], target["y"]), map_data,
                              mounted=attacker["mount_id"] is not None)):
            raise InvalidAction("Move next to a defender to attack.")
        attacker["fight_points"] -= 1
        record_attack(next_state, attacker, target, ranged, map_data,
                      damage=2 if not ranged and attacker["mount_id"] is not None else ATTACK_DAMAGE)
        if map_data.get("mission") == "capture_king" and target.get("is_king") and target["health"] <= 0:
            next_state["defeated"] = True
        return remember_visibility(next_state, map_data)

    if action["type"] == "end_turn":
        if set(action) != {"type"}:
            raise InvalidAction("Invalid end-turn action.")
        for catapult in next_state["catapults"]:
            catapult["reload_turns"] = max(0, catapult["reload_turns"] - 1)
        defenders = {unit["id"]: unit for unit in next_state["units"]
                     if unit.get("side") == "defenders" and not unit.get("is_king")}
        if not isinstance(enemy_orders, (list, tuple)) or len(enemy_orders) > len(defenders):
            raise InvalidAction("Invalid defender orders.")
        for unit in defenders.values():
            unit["move_capacity"] = unit["move_points"] = move_allowance(unit, next_state["items"])
            unit["fight_capacity"] = unit["fight_points"] = fight_allowance(unit)
            unit["reload_turns"] = max(0, unit.get("reload_turns", 0) - 1)
        ordered = set()
        for order in enemy_orders:
            if not isinstance(order, dict) or set(order) != {"unit_id", "x", "y"}:
                raise InvalidAction("Invalid defender order.")
            unit_id, x, y = order["unit_id"], order["x"], order["y"]
            if (type(unit_id) is not int or unit_id not in defenders or unit_id in ordered
                    or type(x) is not int or type(y) is not int):
                raise InvalidAction("Invalid defender destination.")
            ordered.add(unit_id)
            unit = defenders[unit_id]
            if unit not in next_state["units"]:
                continue
            start = (unit["x"], unit["y"])
            blocked = {(other["x"], other["y"]) for other in next_state["units"] if other is not unit}
            if (x, y) not in defender_destinations(unit, map_data, blocked, next_state["items"]):
                raise InvalidAction("Invalid defender destination.")
            objective = (map_data["objective"]["x"], map_data["objective"]["y"])
            path = find_path(start, (x, y), map_data, blocked=blocked | {objective},
                             max_step_cost=unit["move_points"], mounted=unit["mount_id"] is not None)
            if path is None:
                raise InvalidAction("Invalid defender destination.")
            terrain_costs = terrain_cost_index(map_data, unit["mount_id"] is not None)
            for tile in path:
                if any((other["x"], other["y"]) == tile for other in next_state["units"] if other is not unit):
                    break
                old_x = unit["x"]
                unit["x"], unit["y"] = tile
                unit["z"] = tile_height(*tile, map_data)
                unit["facing"] = 1 if unit["x"] >= old_x else -1
                unit["move_points"] -= terrain_costs.get(tile, 1)
                for horse in next_state["horses"]:
                    if horse["rider_id"] == unit["id"]:
                        horse["x"], horse["y"] = tile
                trigger_reactions(next_state, unit, map_data, combat_events)
                if unit not in next_state["units"]:
                    break
                trigger_movement_reactions(next_state, unit, map_data)
        for defender in [unit for unit in next_state["units"]
                         if unit.get("side") == "defenders" and not unit.get("is_king")]:
            if defender["fight_points"] < 1:
                continue
            ranged = defender["weapon"] in RANGED_WEAPON_STATS
            sight = visible_tiles(next_state, map_data, "defenders") if map_data.get("fog_of_war", False) else None
            targets = [
                unit for unit in next_state["units"]
                if unit.get("side", "attackers") == "attackers"
                and (sight is None or (unit["x"], unit["y"]) in sight)
                and (can_ranged_attack(defender, unit, map_data) if ranged else
                     (abs(unit["x"] - defender["x"]) + abs(unit["y"] - defender["y"]) == 1
                      and unit["z"] == defender["z"]
                      and can_step((defender["x"], defender["y"]), (unit["x"], unit["y"]), map_data)))
            ]
            if not targets:
                continue
            objective = map_data["objective"]
            target = min(targets, key=lambda unit: (
                (unit["x"], unit["y"]) != (objective["x"], objective["y"]),
                unit["health"], unit["id"],
            ))
            defender["fight_points"] -= 1
            if ranged:
                defender["reload_turns"] = RANGED_WEAPON_STATS[defender["weapon"]]["reload_turns"]
                if combat_events is not None:
                    combat_events.append({
                        "type": "projectile", "weapon": defender["weapon"],
                        "from": {"x": defender["x"], "y": defender["y"]},
                        "to": {"x": target["x"], "y": target["y"]},
                        **({"witnessed": (defender["x"], defender["y"]) in visible_tiles(next_state, map_data)}
                           if map_data.get("fog_of_war", False) else {}),
                    })
            record_attack(next_state, defender, target, ranged, map_data)
        next_state["defeated"] = not any(
            unit.get("side", "attackers") == "attackers" for unit in next_state["units"]
        )
        objective = map_data["objective"]
        occupiers = sum(
            (unit["x"], unit["y"]) == (objective["x"], objective["y"])
            and unit.get("side", "attackers") == "attackers"
            for unit in next_state["units"]
        )
        if map_data.get("mission") == "capture_king":
            next_state["capture_progress"] = 0
        elif occupiers:
            next_state["capture_progress"] = min(1, state["capture_progress"] + occupiers / 2)
            next_state["captured"] = next_state["capture_progress"] == 1
        else:
            next_state["capture_progress"] = max(0, state["capture_progress"] - 0.25)
        next_state["turn"] += 1
        for unit in next_state["units"]:
            if unit.get("side", "attackers") == "attackers":
                unit["reaction_reserved"] = False
                unit["move_reserved"] = 0
                unit["crouched"] = False
                unit["move_capacity"] = unit["move_points"] = move_allowance(unit, next_state["items"])
                unit["fight_capacity"] = unit["fight_points"] = fight_allowance(unit)
                unit["reload_turns"] = max(0, unit.get("reload_turns", 0) - 1)
        return remember_visibility(next_state, map_data)

    if set(action) != {"type", "units", "x", "y"}:
        raise InvalidAction("Invalid movement action.")
    x, y, ids = action["x"], action["y"], action["units"]
    if not all(type(value) is int for value in (x, y)) or not is_walkable(x, y, map_data):
        raise InvalidAction("Choose an open tile on the map.")
    if not isinstance(ids, list) or not ids or any(type(unit_id) is not int for unit_id in ids):
        raise InvalidAction("Select at least one valid unit.")
    if len(set(ids)) != len(ids):
        raise InvalidAction("Select each unit only once.")
    units = {
        unit["id"]: unit for unit in next_state["units"]
        if unit.get("side", "attackers") == "attackers"
    }
    if any(unit_id not in units for unit_id in ids):
        raise InvalidAction("Unknown unit.")
    if any(units[unit_id]["crouched"] for unit_id in ids):
        raise InvalidAction("Crouching soldiers cannot move until next turn.")
    if any(units[unit_id]["move_points"] == 0 for unit_id in ids):
        raise InvalidAction("Selected units have no move points left. End the turn.")

    moved = False
    for index, unit_id in enumerate(ids):
        unit = units[unit_id]
        blocked = {(other["x"], other["y"]) for other in next_state["units"] if other is not unit}
        # Spread group destinations like the prototype, falling back to the clicked tile.
        if len(ids) == 1:
            target = (x, y)
        else:
            angle = 2 * pi * index / len(ids)
            target = (x + round(cos(angle)), y + round(sin(angle)))
            if not is_walkable(*target, map_data) or target in blocked:
                target = (x, y)
        path = find_path((unit["x"], unit["y"]), target, map_data, blocked=blocked,
                         max_step_cost=max(unit.get("move_capacity", move_allowance(unit, next_state["items"])),
                                           move_allowance(unit, next_state["items"])),
                         mounted=unit["mount_id"] is not None, rope="rope" in unit["tools"])
        if path:
            steps, spent = affordable_steps(path, unit["move_points"],
                                            terrain_cost_index(map_data, unit["mount_id"] is not None))
            if not steps:
                continue
            old_x = unit["x"]
            unit["x"], unit["y"] = steps[-1]
            for horse in next_state["horses"]:
                if horse["rider_id"] == unit["id"]:
                    horse["x"], horse["y"] = unit["x"], unit["y"]
            unit["z"] = tile_height(unit["x"], unit["y"], map_data)
            unit["facing"] = 1 if unit["x"] >= old_x else -1
            unit["move_points"] -= spent
            moved = True
    if not moved:
        raise InvalidAction("That route is blocked, too costly for this turn, or the units are already there.")
    return remember_visibility(next_state, map_data)
