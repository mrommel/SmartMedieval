from collections import deque
from copy import deepcopy
from math import cos, pi, sin


MAP = {
    "cols": 18,
    "rows": 14,
    "keep": {"left": 11, "right": 17, "top": 3, "bottom": 10},
    "gate": {"x": 14, "y": 10},
    "objective": {"x": 14, "y": 7},
    "startPositions": [
        {"x": 2, "y": 6, "type": "vanguard"},
        {"x": 3, "y": 7, "type": "vanguard"},
        {"x": 2, "y": 8, "type": "longbow"},
        {"x": 4, "y": 6, "type": "longbow"},
        {"x": 4, "y": 8, "type": "crossbow"},
        {"x": 5, "y": 7, "type": "crossbow"},
    ],
    "enemyStartPositions": [
        {"x": 12, "y": 5, "type": "vanguard"},
        {"x": 16, "y": 8, "type": "longbow"},
    ],
}
MOVE_POINTS = 4
MAX_HEALTH = 3
FIGHT_POINTS = 1
ATTACK_DAMAGE = 1
STARTING_MORALE = 3
MAX_MORALE = 5
HISTORY_LIMIT = 100
RANGED_UNIT_STATS = {
    # End-turn processing ticks cooldowns, including the transition after firing.
    "longbow": {"range": 5, "reload_turns": 2},
    "crossbow": {"range": 6, "reload_turns": 3},
}


class InvalidAction(ValueError):
    pass


class InvalidMap(ValueError):
    pass


def default_map():
    return deepcopy(MAP)


def validate_map(map_data):
    required = set(MAP) - {"enemyStartPositions"}
    if not isinstance(map_data, dict) or not required <= set(map_data) <= set(MAP) | {"elevation", "objects", "strongpoints", "mission"}:
        raise InvalidMap("Map must contain cols, rows, keep, gate, objective and startPositions.")
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
    objects = map_data.get("objects", [])
    if not isinstance(objects, list) or len(objects) > 256:
        raise InvalidMap("Objects must be a list of at most 256 trees and rocks.")
    object_tiles = set()
    for obj in objects:
        if (not isinstance(obj, dict) or set(obj) != {"x", "y", "type"}
                or type(obj["x"]) is not int or type(obj["y"]) is not int
                or obj["type"] not in ("tree", "rock")
                or not (0 <= obj["x"] < cols and 0 <= obj["y"] < rows)
                or is_wall(obj["x"], obj["y"], map_data)
                or (obj["x"], obj["y"]) == (gate["x"], gate["y"])
                or (obj["x"], obj["y"]) in object_tiles):
            raise InvalidMap("Objects must be unique open tiles with type tree or rock, away from the gate.")
        object_tiles.add((obj["x"], obj["y"]))
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
                or not is_walkable(tile["x"], tile["y"], map_data)
                or (tile["x"], tile["y"]) in seen):
            raise InvalidMap("Elevated tiles must be unique open tiles with height 1-3 and optional ladder or ramp access.")
        seen.add((tile["x"], tile["y"]))
    objective = map_data["objective"]
    if not is_walkable(objective["x"], objective["y"], map_data):
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
            if (not isinstance(position, dict) or set(position) != {"x", "y", "type"}
                    or type(position["x"]) is not int or type(position["y"]) is not int
                    or position["type"] not in (("vanguard", "longbow", "crossbow", "king")
                                                if name == "enemyStartPositions" and mission == "capture_king"
                                                else ("vanguard", "longbow", "crossbow"))
                    or not is_walkable(position["x"], position["y"], map_data)):
                raise InvalidMap("Every starting unit needs an open tile and a supported type.")
            tile = (position["x"], position["y"])
            if tile in occupied:
                raise InvalidMap("Starting units must have distinct tiles.")
            occupied.add(tile)
            if name == "enemyStartPositions":
                kings += position["type"] == "king"
                guards += position["type"] != "king"
                if (position["type"] == "king") != (tile == (objective["x"], objective["y"])) and mission == "capture_king":
                    raise InvalidMap("The king must start on the throne and guards must start elsewhere.")
            if find_path((position["x"], position["y"]), (objective["x"], objective["y"]), map_data) is None:
                raise InvalidMap("Every starting unit must be able to reach the objective.")
            if name == "enemyStartPositions" and mission != "capture_king" and tile == (
                    objective["x"], objective["y"]):
                raise InvalidMap("Defenders cannot start on the objective.")
    if mission == "capture_king" and (kings != 1 or guards < 1):
        raise InvalidMap("A throne-room mission needs exactly one king and at least one guard.")
    if "enemyStartPositions" not in map_data:
        legacy_enemy_position(map_data)


def is_keep_edge(x, y, map_data=MAP):
    return is_rectangle_edge(x, y, map_data["keep"])


def is_rectangle_edge(x, y, rectangle):
    inside = rectangle["left"] <= x <= rectangle["right"] and rectangle["top"] <= y <= rectangle["bottom"]
    edge = x in (rectangle["left"], rectangle["right"]) or y in (rectangle["top"], rectangle["bottom"])
    return inside and edge


def is_wall(x, y, map_data=MAP):
    return any(is_rectangle_edge(x, y, point) and (x, y) != (gate["x"], gate["y"])
               for point, gate in [(map_data["keep"], map_data["gate"])]
               + [(point, point["gate"]) for point in map_data.get("strongpoints", ())])


def is_object(x, y, map_data=MAP):
    return any(obj["x"] == x and obj["y"] == y for obj in map_data.get("objects", ()))


def is_walkable(x, y, map_data=MAP):
    return (0 <= x < map_data["cols"] and 0 <= y < map_data["rows"]
            and not is_wall(x, y, map_data) and not is_object(x, y, map_data))


def elevation_index(map_data):
    return {(tile["x"], tile["y"]): tile for tile in map_data.get("elevation", [])}


def tile_height(x, y, map_data=MAP, elevations=None):
    if elevations is not None:
        return elevations.get((x, y), {}).get("height", 0)
    return next((tile["height"] for tile in map_data.get("elevation", [])
                 if tile["x"] == x and tile["y"] == y), 0)


def can_step(start, end, map_data=MAP, elevations=None):
    if not is_walkable(*end, map_data):
        return False
    before = tile_height(*start, map_data, elevations)
    after = tile_height(*end, map_data, elevations)
    if before == after:
        return True
    if abs(before - after) != 1:
        return False
    high = end if after > before else start
    if elevations is not None:
        return elevations[high].get("access") in ("ladder", "ramp")
    return any(tile["x"] == high[0] and tile["y"] == high[1]
               and tile.get("access") in ("ladder", "ramp")
               for tile in map_data.get("elevation", []))


def has_line_of_sight(start, end, map_data=MAP):
    """Return whether a tile-center ray reaches its target without crossing cover."""
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
                    is_wall(x + step_x, y, map_data) or is_object(x + step_x, y, map_data)
                    or is_wall(x, y + step_y, map_data) or is_object(x, y + step_y, map_data)):
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
        if (x, y) != end and (is_wall(x, y, map_data) or is_object(x, y, map_data)):
            return False
    return True


def can_ranged_attack(attacker, target, map_data=MAP):
    stats = RANGED_UNIT_STATS.get(attacker.get("type"))
    if not stats or attacker.get("reload_turns", 0) > 0:
        return False
    distance = max(abs(attacker["x"] - target["x"]), abs(attacker["y"] - target["y"]))
    return (distance > 0 and distance <= stats["range"]
            and has_line_of_sight((attacker["x"], attacker["y"]),
                                  (target["x"], target["y"]), map_data))


def find_path(start, goal, map_data=MAP, blocked=()):
    if not is_walkable(*goal, map_data) or goal in blocked:
        return None
    elevations = elevation_index(map_data)
    frontier = deque([start])
    previous = {start: None}
    while frontier:
        current = frontier.popleft()
        if current == goal:
            break
        x, y = current
        for neighbor in neighbors(x, y):
            if neighbor not in previous and neighbor not in blocked and can_step(current, neighbor, map_data, elevations):
                previous[neighbor] = current
                frontier.append(neighbor)
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


def move_allowance(unit):
    morale = unit.get("morale", STARTING_MORALE)
    return MOVE_POINTS + (unit.get("rank") == "veteran") + (morale == MAX_MORALE) - (morale <= 1)


def fight_allowance(unit):
    return FIGHT_POINTS + (unit.get("rank") == "veteran")


def ranged_cover(attacker, target, map_data):
    """Find ground cover adjoining the target on the shooter's side."""
    if target["z"] != 0:
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
            if (x, y) in objects:
                return objects[x, y]
    return None


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
    state["units"].remove(casualty)
    return morale_changes


def record_attack(state, attacker, target, ranged, map_data=MAP):
    """Resolve damage and retain a compact, chronological account of combat."""
    cover = (ranged_cover(attacker, target, map_data)
             if ranged and target.get("cover_turn") != state["turn"] else None)
    if cover:
        target["cover_turn"] = state["turn"]
    damage = min(0 if cover else ATTACK_DAMAGE, target["health"])
    target["health"] -= damage
    killed = target["health"] <= 0
    morale_changes = record_casualty(state, attacker, target) if killed else []
    state["history"] = (state["history"] + [{
        "turn": state["turn"], "type": "ranged_attack" if ranged else "attack",
        "actor_id": attacker["id"], "actor_side": attacker.get("side", "attackers"),
        "actor_type": attacker["type"], "target_id": target["id"],
        "target_side": target.get("side", "attackers"), "target_type": target["type"],
        "damage": damage, "killed": killed, "morale_changes": morale_changes,
    } | ({"cover": cover} if cover else {})])[-HISTORY_LIMIT:]


def defender_destinations(unit, map_data=MAP, blocked=()):
    start = (unit["x"], unit["y"])
    objective = (map_data["objective"]["x"], map_data["objective"]["y"])
    frontier = deque([(start, 0)])
    visited = {start}
    destinations = []
    elevations = elevation_index(map_data)
    while frontier:
        (x, y), distance = frontier.popleft()
        if (x, y) != start and (x, y) != objective:
            destinations.append((x, y))
        if distance == move_allowance(unit):
            continue
        for neighbor in neighbors(x, y):
            if (neighbor not in visited and neighbor not in blocked and neighbor != objective
                    and can_step((x, y), neighbor, map_data, elevations)):
                visited.add(neighbor)
                frontier.append((neighbor, distance + 1))
    return destinations


def resolve_defender_goals(state, goals, map_data=MAP):
    defenders = {unit["id"]: unit for unit in state["units"]
                 if unit.get("side") == "defenders" and unit.get("type") != "king"}
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
        destinations = defender_destinations(unit, map_data, blocked)
        if not destinations:
            continue
        # A nearby garrison must not abandon the objective unless another defender
        # is already guarding it. Apply this to reachable tiles, not raw AI goals.
        if guarding(start) and not any(
                guarding(positions[other_id]) for other_id in defenders if other_id != unit_id):
            destinations = [tile for tile in destinations if guarding(tile)]
            if not destinations:
                continue
        route = find_path(start, (x, y), map_data, blocked=blocked | {objective})
        along_route = [tile for tile in (route or [])[:move_allowance(unit)] if tile in destinations]
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
            return {"x": x, "y": y, "type": "vanguard"}
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
    return {
        "turn": 1,
        "units": [
            {
                "id": index,
                "x": point["x"],
                "y": point["y"],
                "z": tile_height(point["x"], point["y"], map_data),
                "type": point["type"],
                "side": "attackers" if index < len(attackers) else "defenders",
                "facing": 1 if index < len(attackers) else -1,
                "move_points": MOVE_POINTS,
                "health": MAX_HEALTH,
                "max_health": MAX_HEALTH,
                "fight_points": FIGHT_POINTS,
                "reload_turns": 0,
                "morale": STARTING_MORALE,
                "rank": "recruit",
            }
            for index, point in enumerate(attackers + enemy_positions)
        ],
        "capture_progress": 0,
        "captured": False,
        "defeated": False,
        "history": [],
    }


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
    king = next((unit for unit in state["units"] if unit.get("type") == "king"), None)
    return bool(king and any(
        unit.get("side") == "defenders" and unit.get("type") != "king"
        and abs(unit["x"] - king["x"]) + abs(unit["y"] - king["y"]) == 1
        and unit["z"] == king["z"] for unit in state["units"]
    ))


def apply_action(state, action, map_data=MAP, enemy_orders=(), combat_events=None):
    if not isinstance(action, dict) or action.get("type") not in (
            "move", "attack", "ranged_attack", "capture", "promote", "end_turn"):
        raise InvalidAction("Unknown action.")
    if state["captured"] or state.get("defeated", False):
        raise InvalidAction("The battle has already ended.")

    next_state = {**state, "units": [
        {
            **unit,
            "z": tile_height(unit["x"], unit["y"], map_data),
            "health": unit.get("health", MAX_HEALTH),
            "max_health": unit.get("max_health", MAX_HEALTH),
            "fight_points": unit.get("fight_points", FIGHT_POINTS),
            "reload_turns": unit.get("reload_turns", 0),
            "morale": unit.get("morale", STARTING_MORALE),
            "rank": unit.get("rank", "recruit"),
        }
        for unit in state["units"]
    ], "defeated": state.get("defeated", False), "history": list(state.get("history", []))}
    if action["type"] == "capture":
        if (map_data.get("mission") != "capture_king" or set(action) != {"type", "unit_id"}
                or type(action["unit_id"]) is not int):
            raise InvalidAction("Choose one soldier to capture the king.")
        unit = next((unit for unit in next_state["units"] if unit["id"] == action["unit_id"]
                     and unit.get("side") == "attackers"), None)
        king = next((unit for unit in next_state["units"] if unit.get("type") == "king"), None)
        if not unit or not king or unit["fight_points"] < 1 or unit["type"] != "vanguard":
            raise InvalidAction("A vanguard with a fight point must capture the living king.")
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
            "actor_side": "attackers", "actor_type": unit["type"],
            "target_id": king["id"], "target_side": "defenders", "target_type": "king",
        }])[-HISTORY_LIMIT:]
        return next_state
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
            "actor_side": "attackers", "actor_type": unit["type"],
            "morale_change": STARTING_MORALE - MAX_MORALE,
        }])[-HISTORY_LIMIT:]
        return next_state
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
        if target is None or target.get("side", "attackers") != "defenders":
            raise InvalidAction("Choose a living defender as the target.")
        if ranged and attacker.get("type") not in RANGED_UNIT_STATS:
            raise InvalidAction("Only bow and crossbow units can make ranged attacks.")
        if not ranged and attacker.get("type") in RANGED_UNIT_STATS:
            raise InvalidAction("Bow and crossbow units must use ranged attacks.")
        if attacker["fight_points"] < 1:
            raise InvalidAction("This soldier has no fight points left.")
        if ranged:
            if attacker.get("reload_turns", 0) > 0:
                raise InvalidAction("This soldier is reloading.")
            distance = max(abs(attacker["x"] - target["x"]), abs(attacker["y"] - target["y"]))
            if distance == 0 or distance > RANGED_UNIT_STATS[attacker["type"]]["range"]:
                raise InvalidAction("That defender is outside this weapon's range.")
            if not has_line_of_sight((attacker["x"], attacker["y"]),
                                     (target["x"], target["y"]), map_data):
                raise InvalidAction("An obstacle blocks the line of sight.")
            attacker["reload_turns"] = RANGED_UNIT_STATS[attacker["type"]]["reload_turns"]
            if combat_events is not None:
                combat_events.append({
                    "type": "projectile", "weapon": attacker["type"],
                    "from": {"x": attacker["x"], "y": attacker["y"]},
                    "to": {"x": target["x"], "y": target["y"]},
                })
        elif (abs(attacker["x"] - target["x"]) + abs(attacker["y"] - target["y"]) != 1
              or attacker["z"] != target["z"]):
            raise InvalidAction("Move next to a defender to attack.")
        attacker["fight_points"] -= 1
        record_attack(next_state, attacker, target, ranged, map_data)
        if map_data.get("mission") == "capture_king" and target["type"] == "king" and target["health"] <= 0:
            next_state["defeated"] = True
        return next_state

    if action["type"] == "end_turn":
        if set(action) != {"type"}:
            raise InvalidAction("Invalid end-turn action.")
        defenders = {unit["id"]: unit for unit in next_state["units"]
                     if unit.get("side") == "defenders" and unit.get("type") != "king"}
        if not isinstance(enemy_orders, (list, tuple)) or len(enemy_orders) > len(defenders):
            raise InvalidAction("Invalid defender orders.")
        for unit in defenders.values():
            unit["move_points"] = move_allowance(unit)
            unit["fight_points"] = fight_allowance(unit)
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
            start = (unit["x"], unit["y"])
            blocked = {(other["x"], other["y"]) for other in next_state["units"] if other is not unit}
            if (x, y) not in defender_destinations(unit, map_data, blocked):
                raise InvalidAction("Invalid defender destination.")
            objective = (map_data["objective"]["x"], map_data["objective"]["y"])
            path = find_path(start, (x, y), map_data, blocked=blocked | {objective})
            old_x = unit["x"]
            unit["x"], unit["y"] = path[-1]
            unit["z"] = tile_height(unit["x"], unit["y"], map_data)
            unit["facing"] = 1 if unit["x"] >= old_x else -1
            unit["move_points"] -= len(path)
        for defender in [unit for unit in next_state["units"]
                         if unit.get("side") == "defenders" and unit.get("type") != "king"]:
            if defender["fight_points"] < 1:
                continue
            ranged = defender.get("type") in RANGED_UNIT_STATS
            targets = [
                unit for unit in next_state["units"]
                if unit.get("side", "attackers") == "attackers"
                and (can_ranged_attack(defender, unit, map_data) if ranged else
                     (abs(unit["x"] - defender["x"]) + abs(unit["y"] - defender["y"]) == 1
                      and unit["z"] == defender["z"]))
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
                defender["reload_turns"] = RANGED_UNIT_STATS[defender["type"]]["reload_turns"]
                if combat_events is not None:
                    combat_events.append({
                        "type": "projectile", "weapon": defender["type"],
                        "from": {"x": defender["x"], "y": defender["y"]},
                        "to": {"x": target["x"], "y": target["y"]},
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
                unit["move_points"] = move_allowance(unit)
                unit["fight_points"] = fight_allowance(unit)
                unit["reload_turns"] = max(0, unit.get("reload_turns", 0) - 1)
        return next_state

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
        path = find_path((unit["x"], unit["y"]), target, map_data, blocked=blocked)
        if path:
            steps = path[:unit["move_points"]]
            old_x = unit["x"]
            unit["x"], unit["y"] = steps[-1]
            unit["z"] = tile_height(unit["x"], unit["y"], map_data)
            unit["facing"] = 1 if unit["x"] >= old_x else -1
            unit["move_points"] -= len(steps)
            moved = True
    if not moved:
        raise InvalidAction("That route is blocked or the units are already there.")
    return next_state
