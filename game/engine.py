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


class InvalidAction(ValueError):
    pass


class InvalidMap(ValueError):
    pass


def default_map():
    return deepcopy(MAP)


def validate_map(map_data):
    required = set(MAP) - {"enemyStartPositions"}
    if not isinstance(map_data, dict) or not required <= set(map_data) <= set(MAP):
        raise InvalidMap("Map must contain cols, rows, keep, gate, objective and startPositions.")
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
    objective = map_data["objective"]
    if not is_walkable(objective["x"], objective["y"], map_data):
        raise InvalidMap("The objective must be on an open tile.")
    for name in ("startPositions", "enemyStartPositions"):
        if name not in map_data:
            continue
        positions = map_data[name]
        if not isinstance(positions, list) or not 1 <= len(positions) <= 64:
            raise InvalidMap(f"Provide between 1 and 64 units in {name}.")
        for position in positions:
            if (not isinstance(position, dict) or set(position) != {"x", "y", "type"}
                    or type(position["x"]) is not int or type(position["y"]) is not int
                    or position["type"] not in ("vanguard", "longbow", "crossbow")
                    or not is_walkable(position["x"], position["y"], map_data)):
                raise InvalidMap("Every starting unit needs an open tile and a supported type.")
            if find_path((position["x"], position["y"]), (objective["x"], objective["y"]), map_data) is None:
                raise InvalidMap("Every starting unit must be able to reach the objective.")
            if name == "enemyStartPositions" and (position["x"], position["y"]) == (
                    objective["x"], objective["y"]):
                raise InvalidMap("Defenders cannot start on the objective before combat is available.")
    if "enemyStartPositions" in map_data:
        attacker_tiles = {(point["x"], point["y"]) for point in map_data["startPositions"]}
        if any((point["x"], point["y"]) in attacker_tiles for point in map_data["enemyStartPositions"]):
            raise InvalidMap("Defenders cannot start on an attacker tile.")
    else:
        legacy_enemy_position(map_data)


def is_keep_edge(x, y, map_data=MAP):
    keep = map_data["keep"]
    inside = keep["left"] <= x <= keep["right"] and keep["top"] <= y <= keep["bottom"]
    edge = x in (keep["left"], keep["right"]) or y in (keep["top"], keep["bottom"])
    return inside and edge


def is_wall(x, y, map_data=MAP):
    return is_keep_edge(x, y, map_data) and (x, y) != (
        map_data["gate"]["x"], map_data["gate"]["y"]
    )


def is_walkable(x, y, map_data=MAP):
    return 0 <= x < map_data["cols"] and 0 <= y < map_data["rows"] and not is_wall(x, y, map_data)


def find_path(start, goal, map_data=MAP, blocked=()):
    if not is_walkable(*goal, map_data) or goal in blocked:
        return None
    frontier = deque([start])
    previous = {start: None}
    while frontier:
        current = frontier.popleft()
        if current == goal:
            break
        x, y = current
        for neighbor in neighbors(x, y):
            if neighbor not in previous and neighbor not in blocked and is_walkable(*neighbor, map_data):
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


def defender_destinations(unit, map_data=MAP):
    start = (unit["x"], unit["y"])
    objective = (map_data["objective"]["x"], map_data["objective"]["y"])
    frontier = deque([(start, 0)])
    visited = {start}
    destinations = []
    while frontier:
        (x, y), distance = frontier.popleft()
        if (x, y) != start and (x, y) != objective:
            destinations.append((x, y))
        if distance == MOVE_POINTS:
            continue
        for neighbor in neighbors(x, y):
            if neighbor not in visited and neighbor != objective and is_walkable(*neighbor, map_data):
                visited.add(neighbor)
                frontier.append((neighbor, distance + 1))
    return destinations


def resolve_defender_goals(state, goals, map_data=MAP):
    defenders = {unit["id"]: unit for unit in state["units"] if unit.get("side") == "defenders"}
    if not isinstance(goals, list) or len(goals) > len(defenders):
        raise InvalidAction("Invalid defender goals.")
    orders = []
    seen = set()
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
        start = (unit["x"], unit["y"])
        if (x, y) == start:
            continue
        destinations = defender_destinations(unit, map_data)
        if not destinations:
            continue
        objective = (map_data["objective"]["x"], map_data["objective"]["y"])
        route = find_path(start, (x, y), map_data, blocked={objective})
        along_route = [tile for tile in (route or [])[:MOVE_POINTS] if tile in destinations]
        if along_route:
            destination = along_route[-1]
        else:
            destination = min(
                destinations,
                key=lambda tile: (abs(tile[0] - x) + abs(tile[1] - y),
                                  abs(tile[0] - start[0]) + abs(tile[1] - start[1])),
            )
        orders.append({"unit_id": unit_id, "x": destination[0], "y": destination[1]})
    return orders


def legacy_enemy_position(map_data):
    # Existing saved maps need a garrison without changing their snapshotted geometry.
    objective = (map_data["objective"]["x"], map_data["objective"]["y"])
    occupied = {(point["x"], point["y"]) for point in map_data["startPositions"]}
    frontier = deque([objective])
    visited = {objective}
    while frontier:
        x, y = frontier.popleft()
        if (x, y) != objective and (x, y) not in occupied:
            return {"x": x, "y": y, "type": "vanguard"}
        for neighbor in neighbors(x, y):
            if neighbor not in visited and is_walkable(*neighbor, map_data):
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
                "type": point["type"],
                "side": "attackers" if index < len(attackers) else "defenders",
                "facing": 1 if index < len(attackers) else -1,
                "move_points": MOVE_POINTS,
            }
            for index, point in enumerate(attackers + enemy_positions)
        ],
        "capture_progress": 0,
        "captured": False,
    }


def capture_status(state, map_data=MAP):
    if state["captured"]:
        return "SECURED"
    objective = map_data["objective"]
    if any((unit["x"], unit["y"]) == (objective["x"], objective["y"])
           and unit.get("side", "attackers") == "attackers" for unit in state["units"]):
        return "CAPTURING"
    return "CONTESTED" if state["capture_progress"] else "UNCLAIMED"


def apply_action(state, action, map_data=MAP, enemy_orders=()):
    if not isinstance(action, dict) or action.get("type") not in ("move", "end_turn"):
        raise InvalidAction("Unknown action.")
    if state["captured"]:
        raise InvalidAction("The courtyard has already been secured.")

    next_state = {**state, "units": [unit.copy() for unit in state["units"]]}
    if action["type"] == "end_turn":
        if set(action) != {"type"}:
            raise InvalidAction("Invalid end-turn action.")
        defenders = {unit["id"]: unit for unit in next_state["units"] if unit.get("side") == "defenders"}
        if not isinstance(enemy_orders, (list, tuple)) or len(enemy_orders) > len(defenders):
            raise InvalidAction("Invalid defender orders.")
        for unit in defenders.values():
            unit["move_points"] = MOVE_POINTS
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
            if (x, y) not in defender_destinations(unit, map_data):
                raise InvalidAction("Invalid defender destination.")
            objective = (map_data["objective"]["x"], map_data["objective"]["y"])
            path = find_path((unit["x"], unit["y"]), (x, y), map_data, blocked={objective})
            old_x = unit["x"]
            unit["x"], unit["y"] = path[-1]
            unit["facing"] = 1 if unit["x"] >= old_x else -1
            unit["move_points"] -= len(path)
        objective = map_data["objective"]
        occupiers = sum(
            (unit["x"], unit["y"]) == (objective["x"], objective["y"])
            and unit.get("side", "attackers") == "attackers"
            for unit in next_state["units"]
        )
        if occupiers:
            next_state["capture_progress"] = min(1, state["capture_progress"] + occupiers / 2)
            next_state["captured"] = next_state["capture_progress"] == 1
        else:
            next_state["capture_progress"] = max(0, state["capture_progress"] - 0.25)
        next_state["turn"] += 1
        for unit in next_state["units"]:
            if unit.get("side", "attackers") != "attackers":
                continue
            unit["move_points"] = MOVE_POINTS
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
        # Spread group destinations like the prototype, falling back to the clicked tile.
        if len(ids) == 1:
            target = (x, y)
        else:
            angle = 2 * pi * index / len(ids)
            target = (x + round(cos(angle)), y + round(sin(angle)))
            if not is_walkable(*target, map_data):
                target = (x, y)
        path = find_path((unit["x"], unit["y"]), target, map_data)
        if path:
            steps = path[:unit["move_points"]]
            old_x = unit["x"]
            unit["x"], unit["y"] = steps[-1]
            unit["facing"] = 1 if unit["x"] >= old_x else -1
            unit["move_points"] -= len(steps)
            moved = True
    if not moved:
        raise InvalidAction("That route is blocked or the units are already there.")
    return next_state
