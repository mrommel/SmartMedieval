(() => {
  "use strict";

  const canvas = document.getElementById("battlefield-canvas");
  const ctx = canvas.getContext("2d");
  const countNode = document.getElementById("soldier-count");
  const rosterCount = document.getElementById("roster-count");
  const enemyCount = document.getElementById("enemy-count");
  const rosterList = document.getElementById("roster-list");
  const statusNode = document.getElementById("objective-status");
  const progressNode = document.getElementById("capture-progress");
  const toastNode = document.getElementById("toast");
  const victoryNode = document.getElementById("victory");
  const startScreen = document.getElementById("start-screen");
  const mainMenu = document.getElementById("main-menu");
  const catalogScreen = document.getElementById("catalog-screen");
  const gameScreen = document.getElementById("game-screen");
  const catalogList = document.getElementById("catalog-list");
  const catalogTitle = document.getElementById("catalog-title");
  const catalogKicker = document.getElementById("catalog-kicker");
  const gameTitle = document.getElementById("game-title");
  const briefingCopy = document.getElementById("briefing-copy");
  const missionLabel = document.getElementById("mission-label");
  const turnNode = document.getElementById("turn-status");
  const endTurnButton = document.getElementById("end-turn");
  const promoteButton = document.getElementById("promote");
  const pauseButton = document.getElementById("pause-game");
  const pauseIndicator = document.getElementById("pause-indicator");
  const speedSelect = document.getElementById("animation-speed");
  const selectedStats = document.getElementById("selected-stats");
  const continueButton = document.getElementById("continue-game");
  const launchError = document.getElementById("launch-error");
  const csrfToken = document.querySelector('meta[name="csrf-token"]').content;

  let COLS, ROWS, KEEP, GATE, OBJECTIVE;
  let elevation = new Map();
  let raisedTiles = [];
  const colors = {
    grass: ["#60815a", "#63845c", "#5d7d57", "#67875e", "#597a55"],
    grassLine: "rgba(36,59,39,.2)",
    path: ["#8a7959", "#8d7b5a", "#837453"],
    wall: "#89836e",
    wallLight: "#b5aa8b",
    wallDark: "#5b5b4b",
    stone: "#746e5e"
  };
  const simulation = { units: [], selected: new Set(), captured: false, defeated: false, captureProgress: 0 };
  let startingAttackerCount = 0;
  let instanceId = null;
  let revision = 0;
  let pendingAction = false;
  let tileW = 56;
  let tileH = 28;
  let originX = 0;
  let originY = 0;
  let toastTimer;
  let width = 0;
  let height = 0;
  let gameIsVisible = false;
  let animationStarted = false;
  const camera = { x: 0, y: 0, zoom: 1 };
  let activePointer = null;
  let projectiles = [];
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const speedKey = "greywatch.animationSpeed";
  const validSpeeds = [0, .5, 1, 2];
  let animationSpeed = 1;
  let paused = false;
  let animationTime = 0;
  let lastFrameTime = null;
  try {
    const savedValue = window.localStorage.getItem(speedKey);
    if (savedValue !== null && validSpeeds.includes(Number(savedValue))) animationSpeed = Number(savedValue);
  } catch (_) { /* Private browsing may disable storage. */ }
  speedSelect.value = String(animationSpeed);

  function animationsEnabled() {
    return animationSpeed > 0 && !reducedMotion.matches;
  }

  function updateControls() {
    const ended = simulation.captured || simulation.defeated;
    endTurnButton.disabled = pendingAction || paused || ended;
    promoteButton.disabled = pendingAction || paused || ended ||
      !promotionCandidate();
    pauseButton.disabled = ended;
    pauseButton.textContent = paused ? "Resume" : "Pause";
    pauseButton.setAttribute("aria-pressed", String(paused));
    pauseIndicator.hidden = !paused || ended;
  }

  function promotionCandidate() {
    const selected = simulation.units.filter(unit => unit.side !== "defenders" && simulation.selected.has(unit.id));
    return selected.length === 1 && (selected[0].rank || "recruit") === "recruit" &&
      (selected[0].morale ?? 3) >= 5;
  }

  function resetCamera() {
    camera.x = 0;
    camera.y = 0;
    camera.zoom = 1;
    if (width && height) clampCamera();
  }

  function resize() {
    if (!instanceId) return;
    const rect = canvas.getBoundingClientRect();
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    width = rect.width;
    height = rect.height;
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    tileW = Math.min(64, width * 1.72 / (COLS + ROWS));
    tileH = tileW * 0.5;
    originX = width * 0.5;
    const mapHeight = (COLS + ROWS - 2) * tileH * 0.5;
    originY = Math.max(42, (height - mapHeight) * 0.5 + tileH * 1.1);
    clampCamera();
    draw();
  }

  function clampCamera() {
    const mapWidth = (COLS + ROWS - 2) * tileW * 0.5;
    const mapHeight = (COLS + ROWS - 2) * tileH * 0.5;
    const left = originX - mapWidth;
    const right = originX + mapWidth;
    const top = originY - tileH * (2.7 + Math.max(0, ...raisedTiles.map(tile => tile.height)));
    const bottom = originY + mapHeight + tileH;
    const margin = Math.min(72, width * 0.2, height * 0.2);
    const minX = margin - right * camera.zoom;
    const maxX = width - margin - left * camera.zoom;
    const minY = margin - bottom * camera.zoom;
    const maxY = height - margin - top * camera.zoom;
    camera.x = minX > maxX ? (minX + maxX) / 2 : Math.max(minX, Math.min(maxX, camera.x));
    camera.y = minY > maxY ? (minY + maxY) / 2 : Math.max(minY, Math.min(maxY, camera.y));
  }

  function zoomAt(screenX, screenY, factor) {
    const nextZoom = Math.max(.7, Math.min(1.8, camera.zoom * factor));
    const worldX = (screenX - camera.x) / camera.zoom;
    const worldY = (screenY - camera.y) / camera.zoom;
    camera.zoom = nextZoom;
    camera.x = screenX - worldX * nextZoom;
    camera.y = screenY - worldY * nextZoom;
    clampCamera();
    draw();
  }

  function zoomAtCenter(factor) {
    zoomAt(width / 2, height / 2, factor);
  }

  function tileHeight(x, y) {
    return elevation.get(`${x},${y}`)?.height || 0;
  }

  function project(x, y, z = tileHeight(x, y)) {
    return { x: originX + (x - y) * tileW / 2,
      y: originY + (x + y) * tileH / 2 - z * tileH };
  }

  function isWall(x, y) {
    const inside = x >= KEEP.left && x <= KEEP.right && y >= KEEP.top && y <= KEEP.bottom;
    const edge = x === KEEP.left || x === KEEP.right || y === KEEP.top || y === KEEP.bottom;
    return inside && edge && !(x === GATE.x && y === GATE.y);
  }

  function isWalkable(x, y) {
    return x >= 0 && x < COLS && y >= 0 && y < ROWS && !isWall(x, y);
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
        const castle = x >= KEEP.left && x <= KEEP.right && y >= KEEP.top && y <= KEEP.bottom;
        const path = (x > 5 && x < KEEP.left && y >= 5 && y <= 9) || (x >= 12 && x <= 16 && y >= 4 && y <= 9);
        const palette = path ? colors.path : colors.grass;
        polygon(tile, palette[hash(x, y) % palette.length], castle ? "rgba(53,53,43,.25)" : colors.grassLine, .7);

        const detail = hash(x + 19, y + 31);
        if (!castle && !path && detail % 9 === 0) {
          const center = project(x, y, 0);
          ctx.fillStyle = "rgba(202,195,139,.24)";
          ctx.beginPath();
          ctx.ellipse(center.x + (detail % 5) - 2, center.y + tileH * .53, 1.5, 1, 0, 0, Math.PI * 2);
          ctx.fill();
        }
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

  function drawWall(x, y) {
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
    if ((y === KEEP.top || y === KEEP.bottom) && x % 2 === 0) {
      polygon([
        [top[0][0] - 3, top[0][1]], [top[1][0] + 3, top[1][1]],
        [top[1][0] + 3, top[1][1] - tileH * .24], [top[1][0] - 3, top[1][1] - tileH * .24],
        [top[0][0] - 3, top[0][1] - tileH * .24]
      ], "#aaa187", "#555747", .6);
    }
  }

  function drawGate() {
    const p = project(GATE.x, GATE.y, 0);
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
    ctx.translate(p.x, p.y + tileH * .48);
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
    const coat = unit.side === "defenders" ? "#566783" :
      unit.type === "vanguard" ? "#8f5946" : unit.type === "longbow" ? "#71824e" : "#526e6b";
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
    ctx.fillStyle = unit.type === "vanguard" ? "#615c4c" : "#665544";
    ctx.beginPath();
    ctx.arc(0, -21.2 + bob, 4.2, Math.PI, Math.PI * 2);
    ctx.lineTo(3.9, -20 + bob); ctx.lineTo(-4, -20 + bob); ctx.fill();

    ctx.strokeStyle = "#d3c7a6";
    ctx.lineWidth = 1.35;
    ctx.lineCap = "round";
    if (unit.type === "vanguard") {
      ctx.beginPath(); ctx.moveTo(4, -12 + bob); ctx.lineTo(12, -22 + bob); ctx.stroke();
      ctx.strokeStyle = "#876846"; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(-7, -12 + bob); ctx.lineTo(-10, -5 + bob); ctx.stroke();
    } else if (unit.type === "longbow") {
      ctx.strokeStyle = "#9c7047"; ctx.lineWidth = 1.7;
      ctx.beginPath(); ctx.moveTo(7, -9 + bob); ctx.quadraticCurveTo(15, -16 + bob, 7, -24 + bob); ctx.stroke();
      ctx.strokeStyle = "#d8c99e"; ctx.lineWidth = .65;
      ctx.beginPath(); ctx.moveTo(7, -9 + bob); ctx.lineTo(7, -24 + bob); ctx.stroke();
    } else {
      ctx.strokeStyle = "#887253"; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(5, -13 + bob); ctx.lineTo(13, -17 + bob); ctx.stroke();
      ctx.strokeStyle = "#d3c7a6"; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(8, -14 + bob); ctx.lineTo(14, -14 + bob); ctx.stroke();
    }
    ctx.restore();
    const healthRatio = Math.max(0, unit.health / unit.max_health);
    ctx.fillStyle = "rgba(20,25,20,.8)";
    ctx.fillRect(p.x - 10, p.y - tileH * .25, 20, 3);
    ctx.fillStyle = healthRatio > .5 ? "#9aba78" : healthRatio > .25 ? "#d8b260" : "#bd6c58";
    ctx.fillRect(p.x - 10, p.y - tileH * .25, 20 * healthRatio, 3);
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
      const arc = Math.min(tileH * 1.4, Math.hypot(dx, dy) * .16);
      const x = from.x + dx * progress;
      const y = from.y + tileH * .1 + dy * progress - arc * 4 * progress * (1 - progress);
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

  function queueProjectiles(events) {
    if (!animationsEnabled() || !events?.length) return;
    for (const [index, event] of events.entries()) {
      if (event.type !== "projectile") continue;
      const distance = Math.hypot(event.to.x - event.from.x, event.to.y - event.from.y);
      projectiles.push({ ...event, start: animationTime + index * 110, duration: 360 + distance * 65 });
    }
  }

  function draw(time = animationTime) {
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
    drawGate();

    const layers = [];
    for (let y = KEEP.top; y <= KEEP.bottom; y++) {
      for (let x = KEEP.left; x <= KEEP.right; x++) {
        if (isWall(x, y)) layers.push({ depth: x + y, kind: "wall", x, y });
      }
    }
    raisedTiles.forEach(tile => layers.push({ depth: tile.x + tile.y, kind: "raised", tile }));
    simulation.units.forEach(unit => layers.push({ depth: unit.x + unit.y + .5, kind: "unit", unit }));
    layers.sort((a, b) => a.depth - b.depth);

    let objectiveDrawn = false;
    for (const layer of layers) {
      if (!objectiveDrawn && layer.depth > OBJECTIVE.x + OBJECTIVE.y) {
        drawObjective(time);
        objectiveDrawn = true;
      }
      if (layer.kind === "wall") drawWall(layer.x, layer.y);
      else if (layer.kind === "raised") drawRaisedTile(layer.tile);
      else drawUnit(layer.unit, time);
    }
    if (!objectiveDrawn) drawObjective(time);
    drawProjectiles(time);
    ctx.restore();
  }

  function moveSelected(x, y) {
    if (!simulation.selected.size) return;
    sendAction({ type: "move", units: [...simulation.selected], x, y });
  }

  function attackSelected(target) {
    const selected = simulation.units.filter(unit => simulation.selected.has(unit.id));
    const melee = selected.find(unit => unit.type === "vanguard" && unit.fight_points > 0 &&
      Math.abs(unit.x - target.x) + Math.abs(unit.y - target.y) === 1 &&
      tileHeight(unit.x, unit.y) === tileHeight(target.x, target.y));
    const ranged = selected.find(unit => unit.type !== "vanguard" && unit.fight_points > 0 &&
      !(unit.reload_turns > 0) && canRangedAttack(unit, target));
    const attacker = melee || ranged;
    if (!attacker) {
      showToast("Select a ready soldier with a clear shot or move a vanguard next to the defender.");
      return;
    }
    sendAction({ type: melee ? "attack" : "ranged_attack", unit_id: attacker.id, target_id: target.id });
  }

  function hasLineOfSight(start, end) {
    let [x, y] = start;
    const [targetX, targetY] = end;
    const dx = targetX - x, dy = targetY - y;
    const nx = Math.abs(dx), ny = Math.abs(dy);
    const stepX = dx > 0 ? 1 : dx < 0 ? -1 : 0;
    const stepY = dy > 0 ? 1 : dy < 0 ? -1 : 0;
    let ix = 0, iy = 0;
    while (ix < nx || iy < ny) {
      const horizontal = (1 + 2 * ix) * ny;
      const vertical = (1 + 2 * iy) * nx;
      if (horizontal === vertical) {
        if (ix < nx && iy < ny && (isWall(x + stepX, y) || isWall(x, y + stepY))) return false;
        x += stepX; y += stepY; ix++; iy++;
      } else if (horizontal < vertical) {
        x += stepX; ix++;
      } else {
        y += stepY; iy++;
      }
      if ((x !== targetX || y !== targetY) && isWall(x, y)) return false;
    }
    return true;
  }

  function canRangedAttack(attacker, target) {
    const range = attacker.type === "longbow" ? 5 : attacker.type === "crossbow" ? 6 : 0;
    const distance = Math.max(Math.abs(attacker.x - target.x), Math.abs(attacker.y - target.y));
    return distance > 0 && distance <= range &&
      hasLineOfSight([attacker.x, attacker.y], [target.x, target.y]);
  }

  function hasAttackOption(target) {
    return simulation.units.some(unit => unit.side !== "defenders" && simulation.selected.has(unit.id) &&
      unit.fight_points > 0 && (unit.type === "vanguard"
        ? Math.abs(unit.x - target.x) + Math.abs(unit.y - target.y) === 1 &&
          tileHeight(unit.x, unit.y) === tileHeight(target.x, target.y)
        : !(unit.reload_turns > 0) && canRangedAttack(unit, target)));
  }

  function pickTile(localX, localY) {
    for (const tile of [...raisedTiles].sort((a, b) => b.x + b.y - a.x - a.y)) {
      const p = project(tile.x, tile.y);
      if (Math.abs(localX - p.x) / (tileW / 2) +
          Math.abs(localY - p.y - tileH / 2) / (tileH / 2) <= 1) {
        return { x: tile.x, y: tile.y };
      }
    }
    const a = (localX - originX) / (tileW / 2);
    const b = (localY - originY) / (tileH / 2);
    // project() places the top corner of each diamond at (x, y).
    // Inverse coordinates span [x, x + 1) and [y, y + 1) inside it.
    const x = Math.floor((a + b) / 2);
    const y = Math.floor((b - a) / 2);
    return { x, y };
  }

  function handlePointer(event) {
    if (simulation.captured || simulation.defeated || pendingAction || paused) return;
    const rect = canvas.getBoundingClientRect();
    const px = (event.clientX - rect.left - camera.x) / camera.zoom;
    const py = (event.clientY - rect.top - camera.y) / camera.zoom;
    let clicked = null;
    let nearest = Infinity;
    for (const unit of simulation.units.filter(item => item.side !== "defenders")) {
      const p = project(unit.x, unit.y);
      const distance = Math.hypot(px - p.x, py - (p.y + tileH * .1));
      if (distance < Math.max(17, tileW * .29) && distance < nearest) {
        clicked = unit;
        nearest = distance;
      }
    }
    if (clicked) {
      if (event.shiftKey) {
        if (simulation.selected.has(clicked.id)) simulation.selected.delete(clicked.id);
        else simulation.selected.add(clicked.id);
      } else {
        simulation.selected = new Set([clicked.id]);
      }
      updateSelection();
      return;
    }
    const target = simulation.units.find(unit => {
      if (unit.side !== "defenders") return false;
      const p = project(unit.x, unit.y);
      return Math.hypot(px - p.x, py - (p.y + tileH * .1)) < Math.max(17, tileW * .29);
    });
    if (target) {
      attackSelected(target);
      return;
    }
    const tile = pickTile(px, py);
    if (!isWalkable(tile.x, tile.y)) {
      showToast("Stone walls bar the way. Enter through the south gate.");
      return;
    }
    moveSelected(tile.x, tile.y);
  }

  function updateSelection() {
    const selected = simulation.units.filter(unit => unit.side !== "defenders" && simulation.selected.has(unit.id));
    if (selected.length) showToast(`${selected.length} selected · ${Math.min(...selected.map(unit => unit.move_points))} move points remaining.`);
    updatePromotion();
    draw();
  }

  function updatePromotion() {
    const selected = simulation.units.filter(unit => unit.side !== "defenders" && simulation.selected.has(unit.id));
    const unit = selected.length === 1 ? selected[0] : null;
    selectedStats.textContent = unit
      ? `#${unit.id + 1} ${unit.rank || "recruit"} · morale ${unit.morale ?? 3}/5 · ${unit.move_points} MP · ${unit.fight_points} FP`
      : `${selected.length} soldiers selected · choose one to inspect or promote`;
    updateControls();
  }

  function applySnapshot(snapshot) {
    const newGame = instanceId !== snapshot.id;
    if (newGame) {
      projectiles = [];
      paused = false;
    }
    instanceId = snapshot.id;
    revision = snapshot.revision;
    ({ cols: COLS, rows: ROWS, keep: KEEP, gate: GATE, objective: OBJECTIVE } = snapshot.map);
    raisedTiles = snapshot.map.elevation || [];
    elevation = new Map(raisedTiles.map(tile => [`${tile.x},${tile.y}`, tile]));
    simulation.units = snapshot.state.units;
    simulation.captured = snapshot.state.captured;
    simulation.defeated = snapshot.state.defeated || false;
    simulation.captureProgress = snapshot.state.capture_progress;
    const attackers = simulation.units.filter(unit => unit.side !== "defenders");
    const defenders = simulation.units.filter(unit => unit.side === "defenders");
    startingAttackerCount = snapshot.map.startPositions.length;
    if (newGame) simulation.selected = new Set([attackers[0].id]);
    else simulation.selected = new Set([...simulation.selected].filter(id => attackers.some(unit => unit.id === id)));
    const roster = [
      { type: "vanguard", name: "Vanguard", icon: "⚔", role: "close-quarters" },
      { type: "longbow", name: "Longbow", icon: "⌁", role: "ranged support" },
      { type: "crossbow", name: "Crossbow", icon: "✣", role: "ranged support" }
    ];
    rosterCount.textContent = `${attackers.length} SOLDIERS`;
    enemyCount.textContent = `${defenders.length} DEFENDERS`;
    rosterList.replaceChildren(...roster.filter(item => attackers.some(unit => unit.type === item.type)).map(item => {
      const row = document.createElement("div");
      row.className = "roster-unit";
      const swatch = document.createElement("span");
      swatch.className = `unit-swatch ${item.type}`;
      swatch.textContent = item.icon;
      const copy = document.createElement("span");
      const title = document.createElement("b");
      title.textContent = item.name;
      const detail = document.createElement("small");
      const typeUnits = attackers.filter(unit => unit.type === item.type);
      const health = typeUnits.reduce((total, unit) => total + unit.health, 0);
      const maxHealth = typeUnits.reduce((total, unit) => total + unit.max_health, 0);
      const fightPoints = typeUnits.reduce((total, unit) => total + unit.fight_points, 0);
      const reloading = typeUnits.filter(unit => unit.reload_turns > 0).length;
      const weapon = item.type === "longbow" ? " · range 5" : item.type === "crossbow" ? " · range 6" : "";
      const reload = reloading ? ` · ${reloading} reloading` : "";
      detail.textContent = `${typeUnits.length} · ${item.role}${weapon} · ${health}/${maxHealth} HP · ${fightPoints} FP${reload}`;
      copy.append(title, detail);
      const dot = document.createElement("i");
      dot.className = "health-dot";
      row.append(swatch, copy, dot);
      return row;
    }));
    statusNode.textContent = snapshot.state.capture_status;
    progressNode.style.width = `${Math.round(simulation.captureProgress * 100)}%`;
    countNode.textContent = `${String(attackers.length).padStart(2, "0")} / ${String(startingAttackerCount).padStart(2, "0")}`;
    turnNode.textContent = `Turn ${snapshot.state.turn}`;
    victoryNode.hidden = !simulation.captured && !simulation.defeated;
    victoryNode.classList.toggle("defeat", simulation.defeated);
    victoryNode.querySelector(".victory-kicker").textContent = simulation.defeated ? "THE COMPANY HAS FALLEN" : "GREYWATCH HAS FALLEN";
    victoryNode.querySelector("h2").textContent = simulation.defeated ? "Your assault is broken." : "The keep is yours.";
    victoryNode.querySelector("p").textContent = simulation.defeated ? "No attackers remain on the field." : "Your small band has secured the courtyard.";
    updatePromotion();
    draw();
  }

  function combatSummary(before, after) {
    const remaining = new Map(after.map(unit => [unit.id, unit]));
    const damage = { attackers: 0, defenders: 0 };
    const losses = { attackers: 0, defenders: 0 };
    for (const unit of before) {
      const current = remaining.get(unit.id);
      const side = unit.side === "defenders" ? "defenders" : "attackers";
      damage[side] += Math.max(0, unit.health - (current?.health || 0));
      if (!current) losses[side]++;
    }
    if (!damage.attackers && !damage.defenders) return "";
    const detail = side => `${damage[side]} damage to ${side}${losses[side] ? ` (${losses[side]} fallen)` : ""}`;
    return ["defenders", "attackers"].filter(side => damage[side]).map(detail).join(" · ");
  }

  async function api(url, body) {
    const response = await fetch(url, {
      method: body === undefined ? "GET" : "POST",
      headers: {
        Accept: "application/json",
        ...(body === undefined ? {} : { "Content-Type": "application/json", "X-CSRFToken": csrfToken })
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) })
    });
    const data = response.headers.get("content-type")?.includes("application/json") ? await response.json() : null;
    if (!response.ok) {
      const error = new Error(data?.error || `Request failed (${response.status}).`);
      error.status = response.status;
      throw error;
    }
    if (!data) throw new Error("The game response is invalid.");
    return data;
  }

  async function sendAction(action) {
    if (pendingAction || !instanceId || paused || simulation.captured || simulation.defeated) return;
    pendingAction = true;
    updateControls();
    if (action.type === "end_turn") showToast("Defenders are taking their turn...");
    try {
      const snapshot = await api("/api/games/actions/", { revision, action });
      const wasCaptured = simulation.captured;
      const combat = combatSummary(simulation.units, snapshot.state.units);
      applySnapshot(snapshot);
      queueProjectiles(snapshot.combat_events);
      if (!wasCaptured && simulation.captured) showToast("Greywatch courtyard secured.");
      else if (simulation.defeated) showToast("Your company has been defeated.");
      else showToast(combat || (action.type === "end_turn" ? `Defenders have taken their turn. Turn ${snapshot.state.turn} begins.` : action.type === "promote" ? "Recruit promoted to veteran; bonus points begin next turn." : "Order received."));
    } catch (error) {
      if (error.status === 409) {
        try {
          applySnapshot(await api("/api/games/current/"));
        } catch (refreshError) {
          showToast(`Could not refresh game: ${refreshError.message}`);
          return;
        }
      }
      showToast(`Order failed: ${error.message}`);
    } finally {
      pendingAction = false;
      updatePromotion();
    }
  }

  function showToast(message) {
    toastNode.textContent = message;
    toastNode.classList.add("visible");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastNode.classList.remove("visible"), 2300);
  }

  function frame(time) {
    if (lastFrameTime !== null && gameIsVisible && !paused && animationsEnabled()) {
      animationTime += Math.min(time - lastFrameTime, 100) * animationSpeed;
      draw();
    }
    lastFrameTime = time;
    requestAnimationFrame(frame);
  }

  function showLaunchScreen(screen) {
    gameIsVisible = false;
    projectiles = [];
    startScreen.hidden = screen !== startScreen;
    mainMenu.hidden = screen !== mainMenu;
    catalogScreen.hidden = screen !== catalogScreen;
    gameScreen.hidden = true;
  }

  function renderCatalogMessage(message, isError = false) {
    const paragraph = document.createElement("p");
    paragraph.className = "catalog-message";
    paragraph.textContent = message;
    catalogList.replaceChildren(paragraph);
    if (isError) {
      const retry = document.createElement("button");
      retry.className = "menu-back";
      retry.type = "button";
      retry.textContent = "Try again";
      retry.addEventListener("click", () => loadCatalog(currentCatalog));
      catalogList.append(retry);
    }
  }

  let currentCatalog = "scenarios";

  async function loadCatalog(kind) {
    currentCatalog = kind;
    const catalog = kind === "scenarios"
      ? { title: "Scenarios", endpoint: "/api/scenarios/", noun: "scenarios" }
      : { title: "Single games", endpoint: "/api/single-games/", noun: "single games" };
    catalogTitle.textContent = catalog.title;
    catalogKicker.textContent = `AVAILABLE ${catalog.title.toUpperCase()}`;
    renderCatalogMessage("Loading...");
    try {
      const response = await fetch(catalog.endpoint, { headers: { Accept: "application/json" } });
      if (!response.ok) throw new Error(`Request failed (${response.status}).`);
      const entries = await response.json();
      if (!Array.isArray(entries)) throw new Error("The catalog response is invalid.");
      if (!entries.length) {
        renderCatalogMessage(`No ${catalog.noun} are available yet.`);
        return;
      }
      const cards = entries.map(entry => {
        if (kind === "scenarios") {
          const group = document.createElement("div");
          group.className = "catalog-group";
          const name = document.createElement("strong");
          name.textContent = entry.name;
          const description = document.createElement("p");
          description.textContent = entry.description;
          group.append(name, description);
          if (!entry.games.length) {
            const empty = document.createElement("p");
            empty.textContent = "No available games in this scenario.";
            group.append(empty);
          }
          for (const game of entry.games) {
            const button = document.createElement("button");
            button.className = "catalog-entry";
            button.type = "button";
            const label = document.createElement("strong");
            label.textContent = game.name;
            const summary = document.createElement("span");
            summary.textContent = game.description;
            button.append(label, summary);
            button.addEventListener("click", () => launchGame(entry, kind, game.id));
            group.append(button);
          }
          return group;
        }
        const button = document.createElement("button");
        button.className = "catalog-entry";
        button.type = "button";
        const name = document.createElement("strong");
        name.textContent = entry.name;
        const description = document.createElement("span");
        description.textContent = entry.description;
        button.append(name, description);
        button.addEventListener("click", () => launchGame(entry, kind));
        return button;
      });
      catalogList.replaceChildren(...cards);
    } catch (error) {
      renderCatalogMessage(`Could not load ${catalog.noun}: ${error.message}`, true);
    }
  }

  function enterGame(snapshot) {
    const { entry, kind } = snapshot;
    currentEntryId = entry.id;
    currentKind = kind;
    currentGameId = snapshot.game_id;
    gameTitle.textContent = entry.name;
    briefingCopy.textContent = entry.introduction || entry.description;
    missionLabel.textContent = kind === "scenarios" ? "SCENARIO" : "SINGLE GAME";
    applySnapshot(snapshot);
    gameIsVisible = true;
    startScreen.hidden = true;
    mainMenu.hidden = true;
    catalogScreen.hidden = true;
    gameScreen.hidden = false;
    resetCamera();
    resize();
    if (!animationStarted) {
      animationStarted = true;
      requestAnimationFrame(frame);
    }
    showToast(`Playing ${entry.name}. Select a unit, move or attack, then end the turn.`);
  }

  async function launchGame(entry, kind, gameId = null) {
    if (pendingAction) return;
    pendingAction = true;
    try {
      const snapshot = await api(
        `/api/games/${kind}/${entry.id}/start/`,
        kind === "scenarios" ? { single_game_id: gameId } : {}
      );
      enterGame(snapshot);
      continueButton.hidden = false;
    } catch (error) {
      if (gameIsVisible) showToast(`Could not restart game: ${error.message}`);
      else renderCatalogMessage(`Could not start game: ${error.message}`, true);
    } finally {
      pendingAction = false;
      updatePromotion();
    }
  }

  canvas.addEventListener("pointerdown", event => {
    if (event.button !== 0 || simulation.captured || simulation.defeated || pendingAction || paused) return;
    activePointer = {
      id: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      cameraX: camera.x,
      cameraY: camera.y,
      dragging: false
    };
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointermove", event => {
    if (!activePointer || event.pointerId !== activePointer.id) return;
    const dx = event.clientX - activePointer.x;
    const dy = event.clientY - activePointer.y;
    if (!activePointer.dragging && Math.hypot(dx, dy) > 4) activePointer.dragging = true;
    if (activePointer.dragging) {
      camera.x = activePointer.cameraX + dx;
      camera.y = activePointer.cameraY + dy;
      clampCamera();
      draw();
    }
  });
  canvas.addEventListener("pointerup", event => {
    if (!activePointer || event.pointerId !== activePointer.id) return;
    if (!activePointer.dragging) handlePointer(event);
    activePointer = null;
  });
  canvas.addEventListener("pointercancel", () => { activePointer = null; });
  canvas.addEventListener("wheel", event => {
    event.preventDefault();
    const rect = canvas.getBoundingClientRect();
    zoomAt(event.clientX - rect.left, event.clientY - rect.top, event.deltaY < 0 ? 1.12 : 1 / 1.12);
  }, { passive: false });
  document.getElementById("zoom-in").addEventListener("click", () => zoomAtCenter(1.15));
  document.getElementById("zoom-out").addEventListener("click", () => zoomAtCenter(1 / 1.15));
  function restart() {
    if (!instanceId) return;
    launchGame({ id: currentEntryId }, currentKind, currentGameId);
  }
  let currentEntryId = null;
  let currentKind = null;
  let currentGameId = null;
  document.getElementById("restart").addEventListener("click", restart);
  document.getElementById("victory-restart").addEventListener("click", restart);
  endTurnButton.addEventListener("click", () => sendAction({ type: "end_turn" }));
  pauseButton.addEventListener("click", () => {
    if (simulation.captured || simulation.defeated) return;
    paused = !paused;
    activePointer = null;
    updateControls();
    draw();
  });
  speedSelect.addEventListener("change", () => {
    const nextSpeed = Number(speedSelect.value);
    if (!validSpeeds.includes(nextSpeed)) return;
    animationSpeed = nextSpeed;
    if (!animationsEnabled()) projectiles = [];
    try { window.localStorage.setItem(speedKey, speedSelect.value); } catch (_) { /* Storage is optional. */ }
    draw();
  });
  reducedMotion.addEventListener?.("change", () => {
    if (!animationsEnabled()) projectiles = [];
    draw();
  });
  promoteButton.addEventListener("click", () => {
    const [unitId] = simulation.selected;
    if (unitId !== undefined && !promoteButton.disabled) sendAction({ type: "promote", unit_id: unitId });
  });
  continueButton.addEventListener("click", async () => {
    try {
      enterGame(await api("/api/games/current/"));
      launchError.hidden = true;
    } catch (error) {
      launchError.textContent = `Could not resume game: ${error.message}`;
      launchError.hidden = false;
    }
  });
  document.getElementById("play-game").addEventListener("click", () => showLaunchScreen(mainMenu));
  document.getElementById("menu-back").addEventListener("click", () => showLaunchScreen(startScreen));
  document.getElementById("catalog-back").addEventListener("click", () => showLaunchScreen(mainMenu));
  document.getElementById("main-menu-button").addEventListener("click", () => showLaunchScreen(mainMenu));
  document.querySelectorAll("[data-catalog]").forEach(button => {
    button.addEventListener("click", () => {
      showLaunchScreen(catalogScreen);
      loadCatalog(button.dataset.catalog);
    });
  });
  window.addEventListener("resize", resize);
  api("/api/games/current/").then(snapshot => {
    continueButton.hidden = false;
  }).catch(error => {
    if (error.status === 404) return;
    launchError.textContent = `Could not check saved game: ${error.message}`;
    launchError.hidden = false;
  });
})();
