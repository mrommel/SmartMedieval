export function createBattlefieldRenderer(canvas) {
  const ctx = canvas.getContext("2d");
  let COLS, ROWS, KEEP, GATE, OBJECTIVE;
  let strongpoints = [];
  let elevation = new Map();
  let raisedTiles = [];
  let objects = new Map();
  let houses = new Set();
  let interiors = new Map();
  let doors = new Set();
  let lanes = new Set();
  let terrain = new Map();
  let breaches = new Set();
  let wallDamage = new Set();
  let tileW = 56, tileH = 28, originX = 0, originY = 0, width = 0, height = 0;
  let simulation, cursor, camera, hasAttackOption;
  let projectiles = [];

  function setMap(map) {
    ({ cols: COLS, rows: ROWS, keep: KEEP, gate: GATE, objective: OBJECTIVE } = map);
    strongpoints = map.strongpoints || [];
    raisedTiles = map.elevation || [];
    elevation = new Map(raisedTiles.map(tile => [`${tile.x},${tile.y}`, tile]));
    objects = new Map((map.objects || []).map(obj => [`${obj.x},${obj.y}`, obj]));
    houses = new Set();
    interiors = new Map();
    doors = new Set();
    for (const [index, house] of (map.houses || []).entries()) {
      if (house.door) doors.add(`${house.door.x},${house.door.y}`);
      for (let y = house.top; y <= house.bottom; y++) {
        for (let x = house.left; x <= house.right; x++) {
          houses.add(`${x},${y}`);
          if (house.door) interiors.set(`${x},${y}`, index);
        }
      }
    }
    lanes = new Set((map.lanes || []).map(tile => `${tile.x},${tile.y}`));
    terrain = new Map((map.terrain || []).map(tile => [`${tile.x},${tile.y}`, tile.type]));
    breaches = new Set((map.breaches || []).map(point => `${point.x},${point.y}`));
    wallDamage = new Set((map.wall_damage || []).map(point => `${point.x},${point.y}`));
  }

  function setLayout(layout) {
    ({ tileW, tileH, originX, originY, width, height } = layout);
    ctx.setTransform(layout.ratio, 0, 0, layout.ratio, 0, 0);
  }

  const colors = {
    grass: ["#60815a", "#63845c", "#5d7d57", "#67875e", "#597a55"],
    grassLine: "rgba(36,59,39,.2)",
    path: ["#8a7959", "#8d7b5a", "#837453"],
    wall: "#89836e",
    wallLight: "#b5aa8b",
    wallDark: "#5b5b4b",
    stone: "#746e5e"
  };
  function tileHeight(x, y) {
    return elevation.get(`${x},${y}`)?.height || 0;
  }

  function project(x, y, z = tileHeight(x, y)) {
    return { x: originX + (x - y) * tileW / 2,
      y: originY + (x + y) * tileH / 2 - z * tileH };
  }

  function isWall(x, y) {
    if (breaches.has(`${x},${y}`)) return false;
    return [{ ...KEEP, gate: GATE }, ...strongpoints].some(point => {
      const inside = x >= point.left && x <= point.right && y >= point.top && y <= point.bottom;
      const edge = x === point.left || x === point.right || y === point.top || y === point.bottom;
      return inside && edge && !(x === point.gate.x && y === point.gate.y);
    });
  }

  function isHouse(x, y) {
    return houses.has(`${x},${y}`);
  }

  function isEnterableHouse(x, y) {
    return interiors.has(`${x},${y}`);
  }

  function isHouseDoor(x, y) {
    return doors.has(`${x},${y}`);
  }

  function diamond(x, y, z = tileHeight(x, y)) {
    const p = project(x, y, z);
    return [
      [p.x, p.y],
      [p.x + tileW / 2, p.y + tileH / 2],
      [p.x, p.y + tileH],
      [p.x - tileW / 2, p.y + tileH / 2]
    ];
  }

  function polygon(points, fill, stroke, lineWidth = 1) {
    ctx.beginPath();
    ctx.moveTo(points[0][0], points[0][1]);
    for (let i = 1; i < points.length; i++) ctx.lineTo(points[i][0], points[i][1]);
    ctx.closePath();
    ctx.fillStyle = fill;
    ctx.fill();
    if (stroke) {
      ctx.lineWidth = lineWidth;
      ctx.strokeStyle = stroke;
      ctx.stroke();
    }
  }

  function hash(x, y) {
    return (x * 37 + y * 71 + x * y * 13) % 97;
  }

  function drawGround() {
    for (let y = 0; y < ROWS; y++) {
      for (let x = 0; x < COLS; x++) {
        const tile = diamond(x, y, 0);
        const castle = [KEEP, ...strongpoints].some(point =>
          x >= point.left && x <= point.right && y >= point.top && y <= point.bottom);
        const path = lanes.has(`${x},${y}`) || (x > 5 && x < KEEP.left && y >= 5 && y <= 9) || (x >= 12 && x <= 16 && y >= 4 && y <= 9);
        const type = terrain.get(`${x},${y}`);
        const palette = type === "road" ? colors.path : type === "grass" ? colors.grass :
          type === "mud" ? ["#685642", "#765f47"] : type === "swamp" ? ["#465f53", "#526b5b"] :
          path ? colors.path : colors.grass;
        polygon(tile, palette[hash(x, y) % palette.length], castle ? "rgba(53,53,43,.25)" : colors.grassLine, .7);

        if (type === "mud" || type === "swamp") {
          const center = project(x, y, 0);
          ctx.fillStyle = type === "mud" ? "rgba(36,30,22,.55)" : "rgba(148,185,158,.55)";
          ctx.beginPath();
          ctx.ellipse(center.x, center.y + tileH * .58, tileW * .15, tileH * .12, 0, 0, Math.PI * 2);
          ctx.fill();
        }

        if (isEnterableHouse(x, y)) {
          polygon(tile, "#b3a17e", "#6e5945", 1);
          const center = project(x, y, 0);
          ctx.fillStyle = isHouseDoor(x, y) ? "#f6d689" : "#796c54";
          ctx.font = `bold ${Math.max(10, tileW * .2)}px sans-serif`;
          ctx.textAlign = "center";
          ctx.fillText(isHouseDoor(x, y) ? "D" : "·", center.x, center.y + tileH * .7);
          continue;
        }

        const detail = hash(x + 19, y + 31);
        if (!castle && !path && !type && detail % 9 === 0) {
          const center = project(x, y, 0);
          ctx.fillStyle = "rgba(202,195,139,.24)";
          ctx.beginPath();
          ctx.ellipse(center.x + (detail % 5) - 2, center.y + tileH * .53, 1.5, 1, 0, 0, Math.PI * 2);
          ctx.fill();
        }
      }
    }
  }

  function drawInteriorWalls() {
    for (const [key, room] of interiors) {
      const [x, y] = key.split(",").map(Number);
      const tile = diamond(x, y, 0);
      // Diamond sides correspond to west, north, east and south neighbors.
      for (const [nx, ny, first, last] of [
        [x - 1, y, 3, 0], [x, y - 1, 0, 1],
        [x + 1, y, 1, 2], [x, y + 1, 2, 3]
      ]) {
        if (interiors.get(`${nx},${ny}`) === room) continue;
        if (doors.has(key) && !houses.has(`${nx},${ny}`) && !isWall(nx, ny) &&
            !objects.has(`${nx},${ny}`)) continue;
        ctx.strokeStyle = "#594635";
        ctx.lineWidth = Math.max(2, tileW * .055);
        ctx.beginPath();
        ctx.moveTo(...tile[first]);
        ctx.lineTo(...tile[last]);
        ctx.stroke();
      }
    }
  }

  function drawRaisedTile(tile) {
    const top = diamond(tile.x, tile.y);
    const base = diamond(tile.x, tile.y, 0);
    polygon([top[3], top[2], base[2], base[3]], "#525c4a", "#394638", .8);
    polygon([top[1], top[2], base[2], base[1]], "#697058", "#394638", .8);
    polygon(top, tile.access === "ramp" ? "#9b8e6e" : "#8d9277", "#4e5947", 1);
    const p = project(tile.x, tile.y);
    ctx.fillStyle = "#f1dfab";
    ctx.font = `bold ${Math.max(10, tileW * .19)}px sans-serif`;
    ctx.textAlign = "center";
    ctx.fillText(tile.access === "ladder" ? "H" : tile.access === "ramp" ? "↗" : `↑${tile.height}`,
      p.x, p.y + tileH * .7);
  }

  function drawWall(x, y, point) {
    const base = project(x, y, 0);
    const w = tileW * .5;
    const h = tileH * .5;
    const z = tileH * 1.55;
    const ground = [
      [base.x, base.y + tileH * .15],
      [base.x + w, base.y + tileH * .65],
      [base.x, base.y + tileH * 1.15],
      [base.x - w, base.y + tileH * .65]
    ];
    const top = ground.map(([px, py]) => [px, py - z]);
    polygon([ground[3], ground[2], [ground[2][0], ground[2][1] + tileH * .23], [ground[3][0], ground[3][1] + tileH * .23]], "#4d5044", "#40483d", .8);
    polygon([ground[1], ground[2], [ground[2][0], ground[2][1] + tileH * .23], [ground[1][0], ground[1][1] + tileH * .23]], "#595b4d", "#40483d", .8);
    polygon([top[0], top[1], top[2], top[3]], colors.wall, "#555747", .8);
    polygon([top[3], top[2], ground[2], ground[3]], "#a89f83", "#615e4e", .6);
    polygon([top[1], top[2], ground[2], ground[1]], "#7c7966", "#615e4e", .6);
    for (let i = 0; i < 3; i++) {
      const t = (i + 1) / 4;
      const leftX = top[3][0] + (top[2][0] - top[3][0]) * t;
      const leftY = top[3][1] + (top[2][1] - top[3][1]) * t + z * .35;
      ctx.strokeStyle = "rgba(54,55,47,.42)";
      ctx.beginPath();
      ctx.moveTo(leftX, leftY);
      ctx.lineTo(leftX + tileW * .1, leftY + tileH * .1);
      ctx.stroke();
    }
    if (wallDamage.has(`${x},${y}`)) {
      ctx.strokeStyle = "#342f28";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(base.x, base.y - tileH);
      ctx.lineTo(base.x - tileW * .08, base.y - tileH * .45);
      ctx.lineTo(base.x + tileW * .06, base.y - tileH * .1);
      ctx.stroke();
    }
    if ((y === point.top || y === point.bottom) && x % 2 === 0) {
      polygon([
        [top[0][0] - 3, top[0][1]], [top[1][0] + 3, top[1][1]],
        [top[1][0] + 3, top[1][1] - tileH * .24], [top[1][0] - 3, top[1][1] - tileH * .24],
        [top[0][0] - 3, top[0][1] - tileH * .24]
      ], "#aaa187", "#555747", .6);
    }
  }

  function drawGate(gate) {
    const p = project(gate.x, gate.y, 0);
    const half = tileW * .25;
    const groundY = p.y + tileH * .55;
    ctx.fillStyle = "#342f28";
    ctx.beginPath();
    ctx.moveTo(p.x - half, groundY);
    ctx.lineTo(p.x - half, groundY - tileH * 1.25);
    ctx.quadraticCurveTo(p.x - half, groundY - tileH * 1.62, p.x, groundY - tileH * 1.62);
    ctx.quadraticCurveTo(p.x + half, groundY - tileH * 1.62, p.x + half, groundY - tileH * 1.25);
    ctx.lineTo(p.x + half, groundY);
    ctx.closePath();
    ctx.fill();
    ctx.strokeStyle = "#a99c79";
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.strokeStyle = "#927d58";
    ctx.lineWidth = 1;
    for (let i = -1; i <= 1; i++) {
      ctx.beginPath();
      ctx.moveTo(p.x + i * tileW * .12, groundY - tileH * 1.14);
      ctx.lineTo(p.x + i * tileW * .12, groundY - 2);
      ctx.stroke();
    }
  }

  function drawObject(obj) {
    const p = project(obj.x, obj.y, 0);
    const ground = p.y + tileH * .55;
    ctx.save();
    ctx.fillStyle = "rgba(28,39,28,.32)";
    ctx.beginPath();
    ctx.ellipse(p.x, ground + tileH * .12, tileW * .31, tileH * .22, 0, 0, Math.PI * 2);
    ctx.fill();
    if (obj.type === "tree") {
      ctx.fillStyle = "#594b37";
      ctx.fillRect(p.x - tileW * .055, ground - tileH * 1.05, tileW * .11, tileH * 1.1);
      for (const [dy, size, color] of [
        [1.95, .34, "#344f3c"], [1.45, .4, "#48654a"], [1, .32, "#587650"]
      ]) {
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.moveTo(p.x, ground - tileH * (dy + .8));
        ctx.lineTo(p.x - tileW * size, ground - tileH * (dy - .35));
        ctx.lineTo(p.x + tileW * size, ground - tileH * (dy - .35));
        ctx.closePath();
        ctx.fill();
      }
    } else if (obj.type === "fence") {
      ctx.strokeStyle = "#493c30";
      ctx.lineWidth = Math.max(2, tileW * .055);
      for (const dx of [-.25, .25]) {
        ctx.beginPath();
        ctx.moveTo(p.x + tileW * dx, ground);
        ctx.lineTo(p.x + tileW * dx, ground - tileH * .8);
        ctx.stroke();
      }
      for (const dy of [.3, .65]) {
        ctx.beginPath();
        ctx.moveTo(p.x - tileW * .28, ground - tileH * dy);
        ctx.lineTo(p.x + tileW * .28, ground - tileH * dy);
        ctx.stroke();
      }
    } else if (obj.type === "well") {
      ctx.fillStyle = "#494e4a";
      ctx.beginPath();
      ctx.ellipse(p.x, ground - tileH * .25, tileW * .25, tileH * .26, 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = "#aba994";
      ctx.lineWidth = Math.max(2, tileW * .07);
      ctx.stroke();
      ctx.strokeStyle = "#6e5038";
      ctx.beginPath();
      ctx.moveTo(p.x - tileW * .22, ground - tileH * .23);
      ctx.lineTo(p.x - tileW * .22, ground - tileH * 1.1);
      ctx.lineTo(p.x + tileW * .22, ground - tileH * 1.1);
      ctx.lineTo(p.x + tileW * .22, ground - tileH * .23);
      ctx.stroke();
    } else {
      polygon([
        [p.x - tileW * .29, ground], [p.x - tileW * .25, ground - tileH * .55],
        [p.x - tileW * .06, ground - tileH * .8], [p.x + tileW * .23, ground - tileH * .55],
        [p.x + tileW * .3, ground - tileH * .05]
      ], "#767c72", "#49564e", 1);
      polygon([
        [p.x - tileW * .06, ground - tileH * .8], [p.x + tileW * .23, ground - tileH * .55],
        [p.x + tileW * .3, ground - tileH * .05], [p.x, ground - tileH * .13]
      ], "#555f57", "#49564e", 1);
    }
    ctx.restore();
  }

  function drawHouse(x, y) {
    const base = diamond(x, y, 0);
    const roof = base.map(([px, py]) => [px, py - tileH * 1.35]);
    polygon([roof[3], roof[2], base[2], base[3]], "#c2af8c", "#544739");
    polygon([roof[1], roof[2], base[2], base[1]], "#9b876c", "#544739");
    polygon(roof, "#884f3e", "#513b35", 1.5);
    ctx.strokeStyle = "#b67e5c";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(roof[3][0], roof[3][1]);
    ctx.lineTo(roof[1][0], roof[1][1]);
    ctx.stroke();
  }

  function drawCatapult(catapult) {
    const p = project(catapult.x, catapult.y);
    ctx.save();
    ctx.translate(p.x, p.y + tileH * .48);
    ctx.fillStyle = "#513b2c";
    ctx.fillRect(-tileW * .23, -tileH * .09, tileW * .46, tileH * .18);
    ctx.strokeStyle = "#c5a475";
    ctx.lineWidth = Math.max(2, tileW * .045);
    ctx.beginPath();
    ctx.moveTo(-tileW * .17, -tileH * .18);
    ctx.lineTo(tileW * .18, -tileH * .7);
    ctx.stroke();
    ctx.fillStyle = "#272c2a";
    ctx.beginPath();
    ctx.arc(tileW * .2, -tileH * .76, tileW * .065, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }

  function drawHorse(horse) {
    const p = project(horse.x, horse.y);
    const scale = tileW / 64;
    ctx.save();
    ctx.translate(p.x, p.y + tileH * .45);
    ctx.scale(scale, scale);
    ctx.fillStyle = "#604331";
    ctx.beginPath();
    ctx.ellipse(0, -7, 13, 7, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillRect(7, -21, 5, 15);
    ctx.beginPath();
    ctx.ellipse(12, -20, 6, 4, -.4, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = "#382b26";
    ctx.lineWidth = 3;
    for (const x of [-9, -4, 6, 10]) {
      ctx.beginPath(); ctx.moveTo(x, -3); ctx.lineTo(x + 1, 5); ctx.stroke();
    }
    ctx.restore();
    ctx.fillStyle = "#32271e";
    ctx.fillRect(p.x - 12, p.y - tileH * .35, 24, 3);
    ctx.fillStyle = "#e4b571";
    ctx.fillRect(p.x - 12, p.y - tileH * .35, 24 * horse.health / horse.max_health, 3);
  }

  function drawPotion(item) {
    const p = project(item.x, item.y);
    const size = Math.max(4, tileW * .095);
    ctx.fillStyle = "#e6d3ae";
    ctx.fillRect(p.x - size * .4, p.y + tileH * .25, size * .8, size * .4);
    ctx.fillStyle = "#ad544f";
    ctx.strokeStyle = "#f6d5aa";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.ellipse(p.x, p.y + tileH * .48, size, size * .75, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  }

  function drawAimMarker(catapult) {
    if (!catapult.aim) return;
    const target = project(catapult.aim.x, catapult.aim.y);
    ctx.strokeStyle = "#ffdd8a";
    ctx.lineWidth = 2;
    ctx.setLineDash([4, 3]);
    ctx.beginPath();
    ctx.ellipse(target.x, target.y + tileH * .5, tileW * .3, tileH * .22, 0, 0, Math.PI * 2);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  function drawBreach(point) {
    const p = project(point.x, point.y);
    ctx.fillStyle = "#6e6a58";
    ctx.fillRect(p.x - tileW * .14, p.y + tileH * .4, tileW * .28, tileH * .12);
  }

  function drawObjective(time) {
    const p = project(OBJECTIVE.x, OBJECTIVE.y);
    const pulse = .5 + Math.sin(time / 500) * .5;
    ctx.save();
    ctx.globalAlpha = .2 + pulse * .14;
    ctx.fillStyle = simulation.captured ? "#e5d084" : "#f0d48b";
    ctx.beginPath();
    ctx.ellipse(p.x, p.y + tileH * .56, tileW * (.36 + pulse * .035), tileH * (.34 + pulse * .035), 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
    ctx.strokeStyle = simulation.captured ? "#f5dfa4" : "rgba(246,219,154,.9)";
    ctx.lineWidth = 1.5;
    ctx.setLineDash([4, 3]);
    ctx.beginPath();
    ctx.ellipse(p.x, p.y + tileH * .55, tileW * .34, tileH * .29, 0, 0, Math.PI * 2);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = "#d9c48e";
    ctx.fillRect(p.x - 1, p.y + tileH * .15, 2, -tileH * .8);
    ctx.fillStyle = simulation.captured ? "#e8d294" : "#c5a960";
    ctx.beginPath();
    ctx.moveTo(p.x + 1, p.y - tileH * .62);
    ctx.lineTo(p.x + tileW * .17, p.y - tileH * .51);
    ctx.lineTo(p.x + 1, p.y - tileH * .41);
    ctx.closePath();
    ctx.fill();
  }

  function drawUnit(unit, time) {
    const p = project(unit.x, unit.y);
    const selectedUnit = simulation.selected.has(unit.id);
    const moving = unit.moving;
    const bob = moving ? Math.sin(time / 80 + unit.id) * 1.5 : Math.sin(time / 340 + unit.id) * .7;
    const scale = tileW / 64;

    ctx.save();
    ctx.translate(p.x, p.y + tileH * .48 - (unit.mount_id != null ? tileH * .4 : 0));
    ctx.scale(scale, scale);
    ctx.fillStyle = "rgba(24,30,22,.35)";
    ctx.beginPath();
    ctx.ellipse(0, 1, 12, 5, 0, 0, Math.PI * 2);
    ctx.fill();
    if (selectedUnit) {
      ctx.strokeStyle = "#e8d28d";
      ctx.lineWidth = 1.4;
      ctx.beginPath();
      ctx.ellipse(0, 0, 14, 6, 0, 0, Math.PI * 2);
      ctx.stroke();
      ctx.fillStyle = "#f3d996";
      ctx.beginPath();
      ctx.arc(0, -10, 2, 0, Math.PI * 2);
      ctx.fill();
    }
    const coat = unit.is_king ? "#9b673c" : unit.side === "defenders" ? "#566783" :
      unit.weapon === "sword" ? "#8f5946" : unit.weapon === "longbow" ? "#71824e" : "#526e6b";
    ctx.fillStyle = coat;
    ctx.beginPath();
    ctx.moveTo(-6, -7 + bob); ctx.lineTo(-5, -17 + bob);
    ctx.quadraticCurveTo(0, -20 + bob, 5, -17 + bob);
    ctx.lineTo(7, -7 + bob); ctx.quadraticCurveTo(0, -4 + bob, -6, -7 + bob);
    ctx.fill();
    ctx.fillStyle = "#d1b58b";
    ctx.beginPath();
    ctx.arc(0, -20 + bob, 4.3, 0, Math.PI * 2);
    ctx.fill();
    if (unit.is_king) {
      ctx.fillStyle = "#f0d47a";
      polygon([[-5, -24 + bob], [-5, -29 + bob], [-2, -26 + bob],
        [0, -31 + bob], [2, -26 + bob], [5, -29 + bob], [5, -24 + bob]], "#f0d47a", "#76542e");
    } else {
      ctx.fillStyle = unit.weapon === "sword" ? "#615c4c" : "#665544";
      ctx.beginPath();
      ctx.arc(0, -21.2 + bob, 4.2, Math.PI, Math.PI * 2);
      ctx.lineTo(3.9, -20 + bob); ctx.lineTo(-4, -20 + bob); ctx.fill();
    }

    ctx.strokeStyle = "#d3c7a6";
    ctx.lineWidth = 1.35;
    ctx.lineCap = "round";
    if (unit.weapon === "sword") {
      ctx.beginPath(); ctx.moveTo(4, -12 + bob); ctx.lineTo(12, -22 + bob); ctx.stroke();
      ctx.strokeStyle = "#876846"; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(-7, -12 + bob); ctx.lineTo(-10, -5 + bob); ctx.stroke();
    } else if (unit.is_king) {
      ctx.strokeStyle = "#d8bf72";
      ctx.beginPath(); ctx.moveTo(6, -15 + bob); ctx.lineTo(7, -4 + bob); ctx.stroke();
    } else if (unit.weapon === "longbow") {
      ctx.strokeStyle = "#9c7047"; ctx.lineWidth = 1.7;
      ctx.beginPath(); ctx.moveTo(7, -9 + bob); ctx.quadraticCurveTo(15, -16 + bob, 7, -24 + bob); ctx.stroke();
      ctx.strokeStyle = "#d8c99e"; ctx.lineWidth = .65;
      ctx.beginPath(); ctx.moveTo(7, -9 + bob); ctx.lineTo(7, -24 + bob); ctx.stroke();
    } else if (unit.weapon === "crossbow") {
      ctx.strokeStyle = "#887253"; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(5, -13 + bob); ctx.lineTo(13, -17 + bob); ctx.stroke();
      ctx.strokeStyle = "#d3c7a6"; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(8, -14 + bob); ctx.lineTo(14, -14 + bob); ctx.stroke();
    }
    ctx.restore();
    const healthRatio = Math.max(0, unit.health / unit.max_health);
    ctx.fillStyle = "rgba(20,25,20,.8)";
    ctx.fillRect(p.x - 10, p.y - tileH * (unit.mount_id != null ? .85 : .25), 20, 3);
    ctx.fillStyle = healthRatio > .5 ? "#9aba78" : healthRatio > .25 ? "#d8b260" : "#bd6c58";
    ctx.fillRect(p.x - 10, p.y - tileH * (unit.mount_id != null ? .85 : .25), 20 * healthRatio, 3);
    if (unit.side === "defenders") {
      ctx.strokeStyle = "#b5c9e6";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.ellipse(p.x, p.y + tileH * .5, tileW * .19, tileH * .14, 0, 0, Math.PI * 2);
      ctx.stroke();
      if (hasAttackOption(unit)) {
        ctx.strokeStyle = "#e8a56a";
        ctx.lineWidth = 2;
        ctx.setLineDash([3, 2]);
        ctx.beginPath();
        ctx.ellipse(p.x, p.y + tileH * .5, tileW * .27, tileH * .2, 0, 0, Math.PI * 2);
        ctx.stroke();
        ctx.setLineDash([]);
      }
    }
  }

  function drawProjectiles(time) {
    projectiles = projectiles.filter(shot => time < shot.start + shot.duration);
    for (const shot of projectiles) {
      if (time < shot.start) continue;
      const progress = (time - shot.start) / shot.duration;
      const from = project(shot.from.x, shot.from.y);
      const to = project(shot.to.x, shot.to.y);
      const dx = to.x - from.x, dy = to.y - from.y;
      const arc = shot.weapon === "catapult" ? tileH * 4 : Math.min(tileH * 1.4, Math.hypot(dx, dy) * .16);
      const x = from.x + dx * progress;
      const y = from.y + tileH * .1 + dy * progress - arc * 4 * progress * (1 - progress);
      if (shot.weapon === "catapult") {
        ctx.fillStyle = "#4e4c44";
        ctx.beginPath();
        ctx.arc(x, y, Math.max(3, tileW * .09), 0, Math.PI * 2);
        ctx.fill();
        continue;
      }
      const angle = Math.atan2(dy - arc * 4 * (1 - 2 * progress), dx);
      const length = shot.weapon === "longbow" ? tileW * .25 : tileW * .18;
      ctx.save();
      ctx.translate(x, y);
      ctx.rotate(angle);
      ctx.lineCap = "round";
      ctx.lineWidth = Math.max(1.5, tileW * .035);
      ctx.strokeStyle = shot.weapon === "longbow" ? "#f6dfaa" : "#d8e1e4";
      ctx.beginPath();
      ctx.moveTo(-length, 0);
      ctx.lineTo(0, 0);
      ctx.stroke();
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.lineTo(-length * .25, -3);
      ctx.moveTo(0, 0);
      ctx.lineTo(-length * .25, 3);
      ctx.stroke();
      if (shot.weapon === "longbow") {
        ctx.beginPath();
        ctx.moveTo(-length * .75, 0);
        ctx.lineTo(-length, -3);
        ctx.moveTo(-length * .75, 0);
        ctx.lineTo(-length, 3);
        ctx.stroke();
      }
      ctx.restore();
    }
  }

  function queueProjectiles(events, animationTime) {
    if (!events?.length) return;
    for (const [index, event] of events.entries()) {
      if (event.type !== "projectile") continue;
      const distance = Math.hypot(event.to.x - event.from.x, event.to.y - event.from.y);
      projectiles.push({ ...event, start: animationTime + index * 110, duration: 360 + distance * 65 });
    }
  }

  function drawMovementPreview(preview) {
    if (!preview) return;
    const { route, start, destination } = preview;
    if (route.status === "reachable") {
      let from = start;
      for (const [index, tile] of route.path.entries()) {
        const a = project(from.x, from.y), b = project(tile.x, tile.y);
        ctx.strokeStyle = index < route.thisTurn ? "#b8edb0" : "#f5d286";
        ctx.lineWidth = Math.max(2, tileW * .075);
        ctx.beginPath();
        ctx.moveTo(a.x, a.y + tileH * .5);
        ctx.lineTo(b.x, b.y + tileH * .5);
        ctx.stroke();
        polygon(diamond(tile.x, tile.y), index < route.thisTurn ? "rgba(83,189,116,.27)" :
          "rgba(230,178,83,.26)", ctx.strokeStyle, 1.5);
        from = tile;
      }
    } else if (route.status === "unreachable") {
      polygon(diamond(destination.x, destination.y), "rgba(196,74,65,.2)", "#ff9887", 2);
    }
  }

  function draw(time, scene) {
    ({ simulation, cursor, camera, hasAttackOption } = scene);
    if (!width || !height) return;
    ctx.clearRect(0, 0, width, height);
    const gradient = ctx.createLinearGradient(0, 0, 0, height);
    gradient.addColorStop(0, "#6a8961");
    gradient.addColorStop(1, "#4c6a4e");
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, width, height);
    ctx.save();
    ctx.translate(camera.x, camera.y);
    ctx.scale(camera.zoom, camera.zoom);
    drawGround();
    drawInteriorWalls();
    drawGate(GATE);
    strongpoints.forEach(point => drawGate(point.gate));

    const layers = [];
    for (const point of [KEEP, ...strongpoints]) {
      for (let y = point.top; y <= point.bottom; y++) {
        for (let x = point.left; x <= point.right; x++) {
          if (isWall(x, y)) layers.push({ depth: x + y, kind: "wall", x, y, point });
        }
      }
    }
    raisedTiles.forEach(tile => layers.push({ depth: tile.x + tile.y, kind: "raised", tile }));
    houses.forEach(key => {
      if (interiors.has(key)) return;
      const [x, y] = key.split(",").map(Number);
      layers.push({ depth: x + y + .25, kind: "house", x, y });
    });
    objects.forEach(obj => layers.push({ depth: obj.x + obj.y + .3, kind: "object", obj }));
    breaches.forEach(key => {
      const [x, y] = key.split(",").map(Number);
      layers.push({ depth: x + y, kind: "breach", point: { x, y } });
    });
    (simulation.catapults || []).forEach(catapult =>
      layers.push({ depth: catapult.x + catapult.y + .35, kind: "catapult", catapult }));
    (simulation.horses || []).forEach(horse =>
      layers.push({ depth: horse.x + horse.y + .45, kind: "horse", horse }));
    (simulation.items || []).filter(item => item.carrier_id === null).forEach(item =>
      layers.push({ depth: item.x + item.y + .4, kind: "potion", item }));
    simulation.units.forEach(unit => layers.push({ depth: unit.x + unit.y + .5, kind: "unit", unit }));
    layers.sort((a, b) => a.depth - b.depth);

    let objectiveDrawn = false;
    for (const layer of layers) {
      if (!objectiveDrawn && layer.depth > OBJECTIVE.x + OBJECTIVE.y) {
        drawObjective(time);
        objectiveDrawn = true;
      }
      if (layer.kind === "wall") drawWall(layer.x, layer.y, layer.point);
      else if (layer.kind === "raised") drawRaisedTile(layer.tile);
      else if (layer.kind === "house") drawHouse(layer.x, layer.y);
      else if (layer.kind === "object") drawObject(layer.obj);
      else if (layer.kind === "breach") drawBreach(layer.point);
      else if (layer.kind === "catapult") drawCatapult(layer.catapult);
      else if (layer.kind === "horse") drawHorse(layer.horse);
      else if (layer.kind === "potion") drawPotion(layer.item);
      else drawUnit(layer.unit, time);
    }
    if (!objectiveDrawn) drawObjective(time);
    (simulation.catapults || []).forEach(drawAimMarker);
    drawMovementPreview(scene.movementPreview);
    drawProjectiles(time);
    if (cursor.visible) {
      polygon(diamond(cursor.x, cursor.y), "rgba(241,211,137,.16)", "#ffe2a1", 2);
    }
    ctx.restore();
  }

  function clearProjectiles() {
    projectiles = [];
  }

  return { setMap, setLayout, project, tileHeight, isWall, isHouse, isEnterableHouse, isHouseDoor,
    draw, queueProjectiles, clearProjectiles };
}
