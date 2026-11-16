// Keep neighbor order, occupancy, door and elevation rules in sync with engine.find_path/can_step.
export function previewMovement(map, units, unit, destination) {
  if (!map || !unit || !destination) return null;
  const { cols, rows } = map;
  const key = (x, y) => y * cols + x;
  const houses = new Map();
  (map.houses || []).forEach((house, index) => {
    for (let y = house.top; y <= house.bottom; y++) {
      for (let x = house.left; x <= house.right; x++) houses.set(key(x, y), house.door ? index : -1);
    }
  });
  const elevations = new Map((map.elevation || []).map(tile => [key(tile.x, tile.y), tile]));
  const objects = new Set((map.objects || []).map(tile => key(tile.x, tile.y)));
  const breaches = new Set((map.breaches || []).map(tile => key(tile.x, tile.y)));
  const strongpoints = [{ ...map.keep, gate: map.gate }, ...(map.strongpoints || [])];
  const blocked = new Set(units.filter(other => other !== unit).map(other => key(other.x, other.y)));
  const houseAt = (x, y) => {
    const index = houses.get(key(x, y));
    return index === undefined || index === -1 ? null : index;
  };
  const isWall = (x, y) => !breaches.has(key(x, y)) &&
    strongpoints.some(point =>
      x >= point.left && x <= point.right && y >= point.top && y <= point.bottom &&
      (x === point.left || x === point.right || y === point.top || y === point.bottom) &&
      (x !== point.gate.x || y !== point.gate.y));
  const walkable = (x, y) => x >= 0 && x < cols && y >= 0 && y < rows &&
    !isWall(x, y) && (!houses.has(key(x, y)) || houseAt(x, y) !== null) && !objects.has(key(x, y));
  const canStep = (from, to) => {
    if (!walkable(to.x, to.y)) return false;
    const before = houseAt(from.x, from.y), after = houseAt(to.x, to.y);
    if (before !== after) {
      if (before !== null && after !== null) return false;
      const door = map.houses[before === null ? after : before].door;
      const inside = before === null ? to : from;
      if (inside.x !== door.x || inside.y !== door.y) return false;
    }
    const fromTile = elevations.get(key(from.x, from.y));
    const toTile = elevations.get(key(to.x, to.y));
    const fromHeight = fromTile?.height || 0, toHeight = toTile?.height || 0;
    if (fromHeight === toHeight) return true;
    if (Math.abs(fromHeight - toHeight) !== 1) return false;
    return ["ladder", "ramp"].includes((toHeight > fromHeight ? toTile : fromTile)?.access);
  };

  if (!unit.move_points) return { status: "exhausted", path: [] };
  const goal = key(destination.x, destination.y);
  if (!walkable(destination.x, destination.y) || blocked.has(goal)) return { status: "unreachable", path: [] };
  const start = key(unit.x, unit.y);
  const frontier = [{ x: unit.x, y: unit.y }];
  const previous = new Map([[start, null]]);
  for (let index = 0; index < frontier.length; index++) {
    const current = frontier[index];
    if (key(current.x, current.y) === goal) break;
    for (const [x, y] of [[current.x + 1, current.y], [current.x - 1, current.y],
      [current.x, current.y + 1], [current.x, current.y - 1]]) {
      const next = key(x, y);
      if (!previous.has(next) && !blocked.has(next) && canStep(current, { x, y })) {
        previous.set(next, current);
        frontier.push({ x, y });
      }
    }
  }
  if (!previous.has(goal)) return { status: "unreachable", path: [] };
  const path = [];
  for (let tile = destination; key(tile.x, tile.y) !== start; tile = previous.get(key(tile.x, tile.y))) {
    path.push(tile);
  }
  path.reverse();
  const thisTurn = Math.min(path.length, unit.move_points);
  const laterCapacity = unit.next_move_capacity || null;
  const turns = path.length <= thisTurn ? 1 : laterCapacity
    ? 1 + Math.ceil((path.length - thisTurn) / laterCapacity) : null;
  return { status: path.length ? "reachable" : "already_there", path, thisTurn, turns };
}
