// Keep neighbor order, occupancy, terrain costs, door and elevation rules in sync with engine.find_path/can_step.
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
  const mounted = unit.mount_id != null;
  const rope = !mounted && (unit.tools || []).includes("rope");
  const costs = mounted ? { road: 1, grass: 2, mud: 4, swamp: Infinity } :
    { road: 1, grass: 2, mud: 3, swamp: 4 };
  const terrain = new Map((map.terrain || []).map(tile => [key(tile.x, tile.y), costs[tile.type]]));
  const fire = new Set((map.fire || []).map(tile => key(tile.x, tile.y)));
  const costAt = tile => (terrain.get(key(tile.x, tile.y)) || 1) + (fire.has(key(tile.x, tile.y)) ? 2 : 0);
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
    if (mounted && (before !== null || after !== null)) return false;
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
    if (rope) return true;
    return (mounted ? ["ramp"] : ["ladder", "ramp"]).includes((toHeight > fromHeight ? toTile : fromTile)?.access);
  };

  if (!unit.move_points) return { status: "exhausted", path: [] };
  const goal = key(destination.x, destination.y);
  if (!walkable(destination.x, destination.y) || blocked.has(goal) ||
      (mounted && houseAt(destination.x, destination.y) !== null)) return { status: "unreachable", path: [] };
  const start = key(unit.x, unit.y);
  const maxStepCost = Math.max(unit.move_capacity ?? unit.next_move_capacity ?? unit.move_points,
    unit.next_move_capacity ?? unit.move_points);
  const frontier = [];
  let sequence = 0;
  const push = entry => {
    frontier.push(entry);
    let child = frontier.length - 1;
    while (child > 0) {
      const parent = Math.floor((child - 1) / 2);
      if (frontier[parent].distance < entry.distance ||
          (frontier[parent].distance === entry.distance && frontier[parent].order < entry.order)) break;
      frontier[child] = frontier[parent];
      child = parent;
    }
    frontier[child] = entry;
  };
  const pop = () => {
    const first = frontier[0], last = frontier.pop();
    if (frontier.length) {
      let parent = 0;
      while (parent * 2 + 1 < frontier.length) {
        let child = parent * 2 + 1;
        if (child + 1 < frontier.length && (frontier[child + 1].distance < frontier[child].distance ||
            (frontier[child + 1].distance === frontier[child].distance &&
              frontier[child + 1].order < frontier[child].order))) child++;
        if (last.distance < frontier[child].distance ||
            (last.distance === frontier[child].distance && last.order < frontier[child].order)) break;
        frontier[parent] = frontier[child];
        parent = child;
      }
      frontier[parent] = last;
    }
    return first;
  };
  push({ tile: { x: unit.x, y: unit.y }, distance: 0, order: sequence });
  const distances = new Map([[start, 0]]);
  const previous = new Map([[start, null]]);
  while (frontier.length) {
    const { tile: current, distance } = pop();
    if (distance !== distances.get(key(current.x, current.y))) continue;
    if (key(current.x, current.y) === goal) break;
    for (const [x, y] of [[current.x + 1, current.y], [current.x - 1, current.y],
      [current.x, current.y + 1], [current.x, current.y - 1]]) {
      const next = key(x, y);
      if (blocked.has(next) || !canStep(current, { x, y })) continue;
      const stepCost = costAt({ x, y });
      const newDistance = distance + stepCost;
      if (stepCost <= maxStepCost && newDistance < (distances.get(next) ?? Infinity)) {
        distances.set(next, newDistance);
        previous.set(next, current);
        push({ tile: { x, y }, distance: newDistance, order: ++sequence });
      }
    }
  }
  if (!previous.has(goal)) return { status: "unreachable", path: [] };
  const path = [];
  for (let tile = destination; key(tile.x, tile.y) !== start; tile = previous.get(key(tile.x, tile.y))) {
    path.push(tile);
  }
  path.reverse();
  const totalCost = path.reduce((total, tile) => total + costAt(tile), 0);
  let thisTurn = 0, thisTurnCost = 0;
  while (thisTurn < path.length && thisTurnCost + costAt(path[thisTurn]) <= unit.move_points) {
    thisTurnCost += costAt(path[thisTurn++]);
  }
  const laterCapacity = unit.next_move_capacity || null;
  let turns = 1, index = thisTurn;
  while (index < path.length && laterCapacity && costAt(path[index]) <= laterCapacity) {
    turns++;
    let spent = 0;
    while (index < path.length && spent + costAt(path[index]) <= laterCapacity) {
      spent += costAt(path[index++]);
    }
  }
  if (index < path.length) turns = null;
  return { status: path.length ? "reachable" : "already_there", path, thisTurn,
    thisTurnCost, totalCost, turns };
}
