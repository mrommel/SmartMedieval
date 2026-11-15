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
                raise InvalidMap("Defenders cannot start on the objective.")
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


def has_line_of_sight(start, end, map_data=MAP):
    """Return whether a tile-center ray reaches its target without crossing a wall."""
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
            # At a corner, either adjoining wall blocks the shot.
            if ix < nx and iy < ny and (
                    is_wall(x + step_x, y, map_data) or is_wall(x, y + step_y, map_data)):
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
        if (x, y) != end and is_wall(x, y, map_data):
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


def move_allowance(unit):
    morale = unit.get("morale", STARTING_MORALE)
    return MOVE_POINTS + (unit.get("rank") == "veteran") + (morale == MAX_MORALE) - (morale <= 1)


def fight_allowance(unit):
    return FIGHT_POINTS + (unit.get("rank") == "veteran")


def record_casualty(state, killer, casualty):
    """A kill rallies its victor; nearby surviving comrades lose heart."""
    killer["morale"] = min(MAX_MORALE, killer["morale"] + 1)
    for unit in state["units"]:
        if unit is not casualty and unit.get("side", "attackers") == casualty.get("side", "attackers"):
            if max(abs(unit["x"] - casualty["x"]), abs(unit["y"] - casualty["y"])) <= 3:
                unit["morale"] = max(0, unit["morale"] - 1)
    state["units"].remove(casualty)


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
        if distance == move_allowance(unit):
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
    }


def capture_status(state, map_data=MAP):
    if state.get("defeated", False):
        return "DEFEATED"
    if state["captured"]:
        return "SECURED"
    objective = map_data["objective"]
    if any((unit["x"], unit["y"]) == (objective["x"], objective["y"])
           and unit.get("side", "attackers") == "attackers" for unit in state["units"]):
        return "CAPTURING"
    return "CONTESTED" if state["capture_progress"] else "UNCLAIMED"


def apply_action(state, action, map_data=MAP, enemy_orders=(), combat_events=None):
    if not isinstance(action, dict) or action.get("type") not in (
            "move", "attack", "ranged_attack", "promote", "end_turn"):
        raise InvalidAction("Unknown action.")
    if state["captured"] or state.get("defeated", False):
        raise InvalidAction("The courtyard has already been secured.")

    next_state = {**state, "units": [
        {
            **unit,
            "health": unit.get("health", MAX_HEALTH),
            "max_health": unit.get("max_health", MAX_HEALTH),
            "fight_points": unit.get("fight_points", FIGHT_POINTS),
            "reload_turns": unit.get("reload_turns", 0),
            "morale": unit.get("morale", STARTING_MORALE),
            "rank": unit.get("rank", "recruit"),
        }
        for unit in state["units"]
    ], "defeated": state.get("defeated", False)}
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
                raise InvalidAction("A wall blocks the line of sight.")
            attacker["reload_turns"] = RANGED_UNIT_STATS[attacker["type"]]["reload_turns"]
            if combat_events is not None:
                combat_events.append({
                    "type": "projectile", "weapon": attacker["type"],
                    "from": {"x": attacker["x"], "y": attacker["y"]},
                    "to": {"x": target["x"], "y": target["y"]},
                })
        elif abs(attacker["x"] - target["x"]) + abs(attacker["y"] - target["y"]) != 1:
            raise InvalidAction("Move next to a defender to attack.")
        attacker["fight_points"] -= 1
        target["health"] -= ATTACK_DAMAGE
        if target["health"] <= 0:
            record_casualty(next_state, attacker, target)
        return next_state

    if action["type"] == "end_turn":
        if set(action) != {"type"}:
            raise InvalidAction("Invalid end-turn action.")
        defenders = {unit["id"]: unit for unit in next_state["units"] if unit.get("side") == "defenders"}
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
            if (x, y) not in defender_destinations(unit, map_data):
                raise InvalidAction("Invalid defender destination.")
            objective = (map_data["objective"]["x"], map_data["objective"]["y"])
            path = find_path((unit["x"], unit["y"]), (x, y), map_data, blocked={objective})
            old_x = unit["x"]
            unit["x"], unit["y"] = path[-1]
            unit["facing"] = 1 if unit["x"] >= old_x else -1
            unit["move_points"] -= len(path)
        for defender in [unit for unit in next_state["units"] if unit.get("side") == "defenders"]:
            if defender["fight_points"] < 1:
                continue
            ranged = defender.get("type") in RANGED_UNIT_STATS
            targets = [
                unit for unit in next_state["units"]
                if unit.get("side", "attackers") == "attackers"
                and (can_ranged_attack(defender, unit, map_data) if ranged else
                     abs(unit["x"] - defender["x"]) + abs(unit["y"] - defender["y"]) == 1)
            ]
            if not targets:
                continue
            target = min(targets, key=lambda unit: (unit["health"], unit["id"]))
            defender["fight_points"] -= 1
            if ranged:
                defender["reload_turns"] = RANGED_UNIT_STATS[defender["type"]]["reload_turns"]
                if combat_events is not None:
                    combat_events.append({
                        "type": "projectile", "weapon": defender["type"],
                        "from": {"x": defender["x"], "y": defender["y"]},
                        "to": {"x": target["x"], "y": target["y"]},
                    })
            target["health"] -= ATTACK_DAMAGE
            if target["health"] <= 0:
                record_casualty(next_state, defender, target)
        next_state["defeated"] = not any(
            unit.get("side", "attackers") == "attackers" for unit in next_state["units"]
        )
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
