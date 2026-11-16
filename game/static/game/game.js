import { createBattlefieldRenderer } from "./renderer.js";
import { createBattlefieldInput } from "./input.js";
import { createLaunchUI } from "./launch.js";
import { previewMovement } from "./path_preview.js";

(() => {
  "use strict";

  const canvas = document.getElementById("battlefield-canvas");
  const renderer = createBattlefieldRenderer(canvas);
  const countNode = document.getElementById("soldier-count");
  const rosterCount = document.getElementById("roster-count");
  const enemyCount = document.getElementById("enemy-count");
  const rosterList = document.getElementById("roster-list");
  const statusNode = document.getElementById("objective-status");
  const progressNode = document.getElementById("capture-progress");
  const toastNode = document.getElementById("toast");
  const victoryNode = document.getElementById("victory");
  const turnNode = document.getElementById("turn-status");
  const endTurnButton = document.getElementById("end-turn");
  const promoteButton = document.getElementById("promote");
  const captureButton = document.getElementById("capture-king");
  const aimButton = document.getElementById("aim-catapult");
  const fireButton = document.getElementById("fire-catapult");
  const pickupButton = document.getElementById("pickup-potion");
  const dropButton = document.getElementById("drop-potion");
  const healButton = document.getElementById("heal-potion");
  const healTarget = document.getElementById("heal-target");
  const pauseButton = document.getElementById("pause-game");
  const pauseIndicator = document.getElementById("pause-indicator");
  const speedSelect = document.getElementById("animation-speed");
  const selectedStats = document.getElementById("selected-stats");
  const historyList = document.getElementById("combat-history-list");
  const cursorStatus = document.getElementById("cursor-status");
  const routeStatus = document.getElementById("route-status");
  const csrfToken = document.querySelector('meta[name="csrf-token"]').content;

  let COLS, ROWS, KEEP, GATE, OBJECTIVE, mapData;
  let objects = new Map();
  const simulation = { units: [], catapults: [], items: [], selected: new Set(), captured: false, defeated: false, captureProgress: 0 };
  let aimingCatapult = false;
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
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const speedKey = "greywatch.animationSpeed";
  const validSpeeds = [0, .5, 1, 2];
  let animationSpeed = 1;
  let paused = false;
  let animationTime = 0;
  let lastFrameTime = null;
  let previewMap = null;
  let movementPreview = null;
  let previewKey = null;
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
    const crew = selectedCrew();
    const medic = selectedMedic();
    const carried = medic && simulation.items.filter(item => item.carrier_id === medic.id);
    const hasPotions = Boolean(mapData?.items?.length);
    pickupButton.hidden = dropButton.hidden = healButton.hidden = healTarget.hidden = !hasPotions;
    pickupButton.disabled = pendingAction || paused || ended || !medic || !medic.fight_points ||
      carried.length >= 2 || !simulation.items.some(item => item.carrier_id === null && item.x === medic.x && item.y === medic.y);
    dropButton.disabled = pendingAction || paused || ended || !medic || !medic.fight_points || !carried.length;
    healButton.disabled = pendingAction || paused || ended || !medic || !medic.fight_points || !carried.length || !healTarget.children.length;
    healTarget.disabled = pendingAction || paused || ended || !medic || !carried.length || !healTarget.children.length;
    endTurnButton.disabled = pendingAction || paused || ended;
    promoteButton.disabled = pendingAction || paused || ended ||
      !promotionCandidate();
    captureButton.disabled = pendingAction || paused || ended || captureCandidate() === null;
    aimButton.hidden = fireButton.hidden = !simulation.catapults.length;
    aimButton.disabled = pendingAction || paused || ended || !crew || !crew.unit.fight_points || !crew.catapult.ammo;
    fireButton.disabled = pendingAction || paused || ended || !crew || !crew.unit.fight_points ||
      !crew.catapult.ammo || !crew.catapult.aim || crew.catapult.reload_turns > 0;
    aimButton.setAttribute("aria-pressed", String(aimingCatapult));
    aimButton.textContent = aimingCatapult ? "Cancel aim" : "Aim catapult";
    pauseButton.disabled = ended;
    pauseButton.textContent = paused ? "Resume" : "Pause";
    pauseButton.setAttribute("aria-pressed", String(paused));
    pauseIndicator.hidden = !paused || ended;
  }

  function selectedCrew() {
    if (simulation.selected.size !== 1) return null;
    const unit = simulation.units.find(item => simulation.selected.has(item.id) && item.side !== "defenders");
    const catapult = simulation.catapults.find(item => unit && item.x === unit.x && item.y === unit.y);
    return catapult ? { unit, catapult } : null;
  }

  function selectedMedic() {
    if (simulation.selected.size !== 1) return null;
    return simulation.units.find(unit => simulation.selected.has(unit.id) && unit.side !== "defenders") || null;
  }

  function updateHealTargets() {
    const medic = selectedMedic();
    const previous = healTarget.value;
    const candidates = medic ? simulation.units.filter(unit => unit.side !== "defenders" &&
      unit.health < unit.max_health && (unit.id === medic.id ||
      (unit.z === medic.z && canMeleeAttack(medic, unit)))) : [];
    healTarget.replaceChildren(...candidates.map(unit => {
      const option = document.createElement("option");
      option.value = String(unit.id);
      option.textContent = `Heal #${unit.id + 1} (${unit.health}/${unit.max_health} HP)`;
      return option;
    }));
    if (candidates.some(unit => String(unit.id) === previous)) healTarget.value = previous;
  }

  function aimCatapultAt(x, y) {
    const crew = selectedCrew();
    if (!aimingCatapult || !crew) return;
    const distance = Math.max(Math.abs(x - crew.catapult.x), Math.abs(y - crew.catapult.y));
    if (x < 0 || x >= COLS || y < 0 || y >= ROWS || distance < 2 || distance > 10) {
      showToast("Aim between 2 and 10 tiles from the catapult.");
      return;
    }
    aimingCatapult = false;
    sendAction({ type: "aim_catapult", unit_id: crew.unit.id, catapult_id: crew.catapult.id, x, y });
  }

  function promotionCandidate() {
    const selected = simulation.units.filter(unit => unit.side !== "defenders" && simulation.selected.has(unit.id));
    return selected.length === 1 && (selected[0].rank || "recruit") === "recruit" &&
      (selected[0].morale ?? 3) >= 5;
  }

  function captureCandidate() {
    if (mapData?.mission !== "capture_king") return null;
    const king = simulation.units.find(unit => unit.is_king && unit.side === "defenders");
    if (!king || simulation.units.some(unit => unit.side === "defenders" && !unit.is_king &&
      Math.abs(unit.x - king.x) + Math.abs(unit.y - king.y) === 1 &&
      renderer.tileHeight(unit.x, unit.y) === renderer.tileHeight(king.x, king.y))) return null;
    return simulation.units.find(unit => unit.side !== "defenders" && simulation.selected.has(unit.id) &&
      unit.weapon === "sword" && unit.fight_points > 0 &&
      Math.abs(unit.x - king.x) + Math.abs(unit.y - king.y) === 1 &&
      renderer.tileHeight(unit.x, unit.y) === renderer.tileHeight(king.x, king.y))?.id ?? null;
  }

  function resize() {
    if (!instanceId) return;
    const rect = canvas.getBoundingClientRect();
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    width = rect.width;
    height = rect.height;
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    tileW = Math.min(64, width * 1.72 / (COLS + ROWS));
    tileH = tileW * 0.5;
    originX = width * 0.5;
    const mapHeight = (COLS + ROWS - 2) * tileH * 0.5;
    originY = Math.max(42, (height - mapHeight) * 0.5 + tileH * 1.1);
    renderer.setLayout({ width, height, tileW, tileH, originX, originY, ratio });
    input.clampCamera();
    draw();
  }

  function isWalkable(x, y) {
    return x >= 0 && x < COLS && y >= 0 && y < ROWS &&
      !renderer.isWall(x, y) && (!renderer.isHouse(x, y) || renderer.isEnterableHouse(x, y)) &&
      !objects.has(`${x},${y}`);
  }

  function houseAt(x, y) {
    return mapData?.houses?.findIndex(house => house.door && x >= house.left && x <= house.right &&
      y >= house.top && y <= house.bottom) ?? -1;
  }

  function canMeleeAttack(attacker, target) {
    if (Math.abs(attacker.x - target.x) + Math.abs(attacker.y - target.y) !== 1 ||
        renderer.tileHeight(attacker.x, attacker.y) !== renderer.tileHeight(target.x, target.y)) return false;
    const from = houseAt(attacker.x, attacker.y), to = houseAt(target.x, target.y);
    if (from === to) return true;
    if (from >= 0 && to >= 0) return false;
    const house = mapData.houses[from < 0 ? to : from];
    return (from < 0 ? target.x === house.door.x && target.y === house.door.y :
      attacker.x === house.door.x && attacker.y === house.door.y);
  }

  function blocksSight(x, y, interior = -1) {
    return renderer.isWall(x, y) || (renderer.isHouse(x, y) &&
      (interior < 0 || houseAt(x, y) !== interior)) ||
      (objects.has(`${x},${y}`) && objects.get(`${x},${y}`).type !== "fence");
  }

  function draw() {
    renderer.draw(animationTime, { simulation, camera: input.camera, cursor: input.cursor, hasAttackOption, movementPreview });
  }

  function updateMovementPreview() {
    const destination = input.previewDestination();
    const selected = simulation.units.filter(unit => unit.side !== "defenders" && simulation.selected.has(unit.id));
    const available = gameIsVisible && !pendingAction && !paused && !aimingCatapult &&
      !simulation.captured && !simulation.defeated && selected.length === 1 && destination;
    const key = available ? `${revision}:${selected[0].id}:${destination.x},${destination.y}` : null;
    if (key !== null && key === previewKey) return;
    previewKey = key;
    movementPreview = available ? {
      start: { x: selected[0].x, y: selected[0].y }, destination,
      route: previewMovement(previewMap, simulation.units, selected[0], destination)
    } : null;
    if (movementPreview) {
      const { route } = movementPreview;
      if (route.status === "reachable") {
        routeStatus.textContent = `Route to tile ${destination.x + 1}, ${destination.y + 1}: ${route.path.length} ${route.path.length === 1 ? "tile" : "tiles"} · ${route.path.length} MP total · ${route.thisTurn} this turn${route.turns > 1 ? ` · approximately ${route.turns} turns if the route stays clear` : route.turns === null ? " · later turns needed (future allowance unavailable)" : ""}.`;
      } else {
        routeStatus.textContent = route.status === "exhausted" ? "No movement points left. End the turn to move again." :
          route.status === "already_there" ? "Soldier is already on this tile." : "Unreachable: blocked route or occupied destination.";
      }
    } else {
      routeStatus.textContent = selected.length > 1 && destination ? "Select one soldier to preview their route; group orders spread to nearby tiles." :
        selected.length === 0 && destination ? "Select a soldier to preview a route." :
        "Hover over a tile, or focus the battlefield and use arrow keys, to preview a route.";
    }
    draw();
  }

  function moveSelected(x, y) {
    if (!simulation.selected.size) return;
    sendAction({ type: "move", units: [...simulation.selected], x, y });
  }

  function attackSelected(target) {
    if (target.is_king && captureCandidate() !== null) {
      sendAction({ type: "capture", unit_id: captureCandidate() });
      return;
    }
    const selected = simulation.units.filter(unit => simulation.selected.has(unit.id));
    const melee = selected.find(unit => unit.weapon === "sword" && unit.fight_points > 0 &&
      canMeleeAttack(unit, target));
    const ranged = selected.find(unit => ["longbow", "crossbow"].includes(unit.weapon) && unit.fight_points > 0 &&
      !(unit.reload_turns > 0) && canRangedAttack(unit, target));
    const attacker = melee || ranged;
    if (!attacker) {
      showToast(target.is_king ? "Move a sword-bearing soldier next to the king and remove adjacent guards to capture him." :
        "Select a ready soldier with a clear shot or move a sword-bearing soldier next to the defender.");
      return;
    }
    if (target.is_king && !window.confirm("Killing the king loses the mission. Attack him instead of capturing him?")) return;
    sendAction({ type: melee ? "attack" : "ranged_attack", unit_id: attacker.id, target_id: target.id });
  }

  function hasLineOfSight(start, end) {
    const interior = houseAt(...start);
    if (interior !== houseAt(...end)) return false;
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
        if (ix < nx && iy < ny && (blocksSight(x + stepX, y, interior) || blocksSight(x, y + stepY, interior))) return false;
        x += stepX; y += stepY; ix++; iy++;
      } else if (horizontal < vertical) {
        x += stepX; ix++;
      } else {
        y += stepY; iy++;
      }
      if ((x !== targetX || y !== targetY) && blocksSight(x, y, interior)) return false;
    }
    return true;
  }

  function canRangedAttack(attacker, target) {
    const range = attacker.weapon === "longbow" ? 5 : attacker.weapon === "crossbow" ? 6 : 0;
    const distance = Math.max(Math.abs(attacker.x - target.x), Math.abs(attacker.y - target.y));
    return distance > 0 && distance <= range &&
      hasLineOfSight([attacker.x, attacker.y], [target.x, target.y]);
  }

  function hasAttackOption(target) {
    return simulation.units.some(unit => unit.side !== "defenders" && simulation.selected.has(unit.id) &&
      unit.fight_points > 0 && (unit.weapon === "sword"
        ? canMeleeAttack(unit, target)
        : ["longbow", "crossbow"].includes(unit.weapon) && !(unit.reload_turns > 0) && canRangedAttack(unit, target)));
  }

  function describeCursor(cursor) {
    const unit = simulation.units.find(item => item.x === cursor.x && item.y === cursor.y);
    const potion = simulation.items.some(item => item.carrier_id === null && item.x === cursor.x && item.y === cursor.y);
    const location = `Tile ${cursor.x + 1}, ${cursor.y + 1}`;
    cursorStatus.textContent = `${location}: ${unit
      ? `${unit.side === "defenders" ? "defender" : "friendly"} ${unit.is_king ? "king" : `with ${unit.weapon}`} #${unit.id + 1}${simulation.selected.has(unit.id) ? ", selected" : ""}${potion ? ", healing potion on ground" : ""}`
      : potion ? "healing potion"
      : simulation.catapults.find(item => item.x === cursor.x && item.y === cursor.y) ? "catapult" :
        objects.get(`${cursor.x},${cursor.y}`)?.type || (renderer.isWall(cursor.x, cursor.y) ? "wall" :
        renderer.isHouseDoor(cursor.x, cursor.y) ? "house door" :
        renderer.isEnterableHouse(cursor.x, cursor.y) ? "house interior" :
        renderer.isHouse(cursor.x, cursor.y) ? "house" : cursor.x === OBJECTIVE.x && cursor.y === OBJECTIVE.y
        ? mapData?.mission === "capture_king" ? "throne" : "courtyard objective" :
        mapData?.lanes?.some(tile => tile.x === cursor.x && tile.y === cursor.y) ? "lane" : "open ground")}.`;
  }

  function updateSelection() {
    const selected = simulation.units.filter(unit => unit.side !== "defenders" && simulation.selected.has(unit.id));
    if (selected.length) showToast(`${selected.length} selected · ${Math.min(...selected.map(unit => unit.move_points))} move points remaining.`);
    updatePromotion();
    updateMovementPreview();
  }

  function statRow(label, remaining, maximum, unit, tone) {
    const row = document.createElement("div");
    row.className = "stat-row";
    const header = document.createElement("div");
    header.className = "stat-row-header";
    const title = document.createElement("span");
    title.textContent = label;
    const value = document.createElement("strong");
    value.textContent = maximum == null ? `${remaining} ${unit} left` :
      `${remaining}/${maximum}${unit ? ` ${unit}` : ""}${unit === "MP" || unit === "FP" ? " left" : ""}`;
    header.append(title, value);
    row.append(header);
    if (maximum > 0) {
      const track = document.createElement("div");
      track.className = `stat-track ${tone}${tone === "health" && remaining / maximum <= .35 ? " low" : ""}`;
      track.setAttribute("aria-hidden", "true");
      const fill = document.createElement("div");
      fill.className = "stat-fill";
      fill.style.width = `${Math.round(100 * Math.max(0, Math.min(1, remaining / maximum)))}%`;
      track.append(fill);
      row.append(track);
    }
    return row;
  }

  function detailRow(label, value) {
    const row = document.createElement("div");
    row.className = "selected-detail";
    const title = document.createElement("span");
    title.textContent = label;
    const detail = document.createElement("strong");
    detail.textContent = value;
    row.append(title, detail);
    return row;
  }

  function updatePromotion() {
    const selected = simulation.units.filter(unit => unit.side !== "defenders" && simulation.selected.has(unit.id));
    const unit = selected.length === 1 ? selected[0] : null;
    const crew = selectedCrew();
    const potions = unit ? simulation.items.filter(item => item.carrier_id === unit.id).length : 0;
    if (unit) {
      const identity = document.createElement("div");
      identity.className = "selected-identity";
      identity.textContent = `Soldier #${unit.id + 1} · ${unit.rank || "recruit"}`;
      const moveCapacity = unit.move_capacity ?? null;
      const fightCapacity = unit.fight_capacity ?? null;
      const nextTurn = document.createElement("p");
      nextTurn.className = "next-turn-preview";
      nextTurn.textContent = unit.next_move_capacity == null || unit.next_fight_capacity == null
        ? "Next turn: allowance unavailable until the game refreshes."
        : `Projected next turn: ${unit.next_move_capacity} MP · ${unit.next_fight_capacity} FP (at current morale and rank)`;
      selectedStats.replaceChildren(identity,
        statRow("Health", unit.health, unit.max_health, "HP", "health"),
        statRow("Morale", unit.morale ?? 3, 5, "", "morale"),
        statRow("Movement", unit.move_points, moveCapacity, "MP", "movement"),
        statRow("Fight", unit.fight_points, fightCapacity, "FP", "fight"),
        nextTurn,
        detailRow("Weapon", unit.weapon || "none"),
        detailRow("Tools", unit.tools?.length ? unit.tools.join(", ") : "none"),
        detailRow("Potions", `${potions}/2`),
        ...(["longbow", "crossbow"].includes(unit.weapon)
          ? [detailRow("Reload", unit.reload_turns ? `${unit.reload_turns} turn(s) left` : "Ready")]
          : []),
        ...(crew ? [detailRow("Catapult", `${crew.catapult.ammo} stones${crew.catapult.aim ?
          ` · aimed at ${crew.catapult.aim.x + 1}, ${crew.catapult.aim.y + 1}` : ""}${crew.catapult.reload_turns ?
          ` · reload ${crew.catapult.reload_turns}` : ""}`)] : []));
    } else {
      selectedStats.textContent = selected.length
        ? `${selected.length} soldiers selected · choose one to inspect`
        : "Select a soldier to inspect their condition and equipment.";
    }
    updateHealTargets();
    updateControls();
  }

  function renderHistory(history) {
    const entries = history || [];
    if (!entries.length) {
      const empty = document.createElement("li");
      empty.textContent = "No combat yet.";
      historyList.replaceChildren(empty);
      return;
    }
    historyList.replaceChildren(...entries.map(event => {
      const item = document.createElement("li");
      const actor = `${event.actor_side === "defenders" ? "Defender" : "Attacker"} #${event.actor_id + 1}${event.actor_weapon ? ` (${event.actor_weapon})` : ""}`;
      if (event.type === "promote") {
        item.textContent = `Turn ${event.turn} · ${actor} promoted to veteran (morale ${event.morale_change}).`;
      } else if (event.type === "capture") {
        item.textContent = `Turn ${event.turn} · ${actor} captured the living king.`;
      } else if (event.type === "aim_catapult") {
        item.textContent = `Turn ${event.turn} · ${actor} aimed the catapult at ${event.x + 1}, ${event.y + 1}.`;
      } else if (event.type === "catapult_wall" || event.type === "catapult_miss") {
        item.textContent = `Turn ${event.turn} · ${actor} fired at ${event.x + 1}, ${event.y + 1}: ${event.type === "catapult_miss" ? "missed" : event.breached ? "breached the wall" : "damaged the wall"}.`;
      } else if (event.type === "pickup_item" || event.type === "drop_item") {
        item.textContent = `Turn ${event.turn} · ${actor} ${event.type === "pickup_item" ? "picked up" : "dropped"} a healing potion.`;
      } else if (event.type === "use_item") {
        item.textContent = `Turn ${event.turn} · ${actor} healed attacker #${event.target_id + 1} for ${event.healed} HP.`;
      } else {
        const target = `${event.target_is_king ? "king" : event.target_side === "defenders" ? "defender" : "attacker"} #${event.target_id + 1}`;
        const morale = event.morale_changes.map(change =>
          `#${change.unit_id + 1} ${change.change > 0 ? "+" : ""}${change.change}`).join(", ");
        item.textContent = `Turn ${event.turn} · ${actor} ${event.weapon === "catapult" ? "hit with a catapult" : event.type === "ranged_attack" ? "shot" : "struck"} ${target} for ${event.damage} damage${event.cover ? ` (${event.cover} cover blocked the shot)` : ""}${event.killed ? " (fallen)" : ""}.${morale ? ` Morale: ${morale}.` : ""}`;
      }
      return item;
    }));
    historyList.scrollTop = historyList.scrollHeight;
  }

  function applySnapshot(snapshot) {
    const newGame = instanceId !== snapshot.id;
    if (newGame) {
      input.cancelPointer();
      renderer.clearProjectiles();
      paused = false;
    }
    aimingCatapult = false;
    instanceId = snapshot.id;
    revision = snapshot.revision;
    mapData = snapshot.map;
    const throneMission = mapData.mission === "capture_king";
    captureButton.hidden = !throneMission;
    document.getElementById("objective-name").textContent = throneMission ? "THRONE ROOM" : "KEEP COURTYARD";
    document.getElementById("mission-help").textContent = throneMission
      ? "Reach the throne room. Defeat guards beside the king, then select a soldier with a sword on an adjacent tile at the same height and press Capture king (one fight point). Clicking the king also captures him when ready. Killing the king loses the battle; simply standing on the throne cannot win. End the turn to let defenders act and restore points."
      : "Click open ground to spend move points. Houses marked D can be entered through their doors; their open roofs show interior tiles. Move next to a blue defender, then click it to spend a fight point and deal melee damage. End the turn to let defenders move and counterattack, restore points, and advance courtyard capture. Health bars show remaining health.";
    ({ cols: COLS, rows: ROWS, keep: KEEP, gate: GATE, objective: OBJECTIVE } = mapData);
    renderer.setMap({ ...mapData, breaches: snapshot.state.breaches, wall_damage: snapshot.state.wall_damage });
    previewMap = { ...mapData, breaches: snapshot.state.breaches || [] };
    previewKey = null;
    objects = new Map((snapshot.map.objects || []).map(obj => [`${obj.x},${obj.y}`, obj]));
    simulation.units = snapshot.state.units;
    simulation.catapults = snapshot.state.catapults || [];
    simulation.items = snapshot.state.items || [];
    simulation.captured = snapshot.state.captured;
    simulation.defeated = snapshot.state.defeated || false;
    simulation.captureProgress = snapshot.state.capture_progress;
    const attackers = simulation.units.filter(unit => unit.side !== "defenders");
    const defenders = simulation.units.filter(unit => unit.side === "defenders");
    startingAttackerCount = snapshot.map.startPositions.length;
    if (newGame) simulation.selected = new Set([attackers[0].id]);
    else simulation.selected = new Set([...simulation.selected].filter(id => attackers.some(unit => unit.id === id)));
    const cursor = input.cursor;
    input.resetCursor(newGame ? attackers[0]?.x ?? OBJECTIVE.x : cursor.x,
      newGame ? attackers[0]?.y ?? OBJECTIVE.y : cursor.y);
    const roster = [
      { weapon: "sword", name: "Swords", icon: "⚔", role: "close-quarters" },
      { weapon: "longbow", name: "Longbows", icon: "⌁", role: "ranged support" },
      { weapon: "crossbow", name: "Crossbows", icon: "✣", role: "ranged support" }
    ];
    rosterCount.textContent = `${attackers.length} SOLDIERS`;
    enemyCount.textContent = `${defenders.length} DEFENDERS`;
    rosterList.replaceChildren(...roster.filter(item => attackers.some(unit => unit.weapon === item.weapon)).map(item => {
      const row = document.createElement("div");
      row.className = "roster-unit";
      const swatch = document.createElement("span");
      swatch.className = `unit-swatch ${item.weapon}`;
      swatch.textContent = item.icon;
      const copy = document.createElement("span");
      const title = document.createElement("b");
      title.textContent = item.name;
      const detail = document.createElement("small");
      const equipped = attackers.filter(unit => unit.weapon === item.weapon);
      const health = equipped.reduce((total, unit) => total + unit.health, 0);
      const maxHealth = equipped.reduce((total, unit) => total + unit.max_health, 0);
      const fightPoints = equipped.reduce((total, unit) => total + unit.fight_points, 0);
      const reloading = equipped.filter(unit => unit.reload_turns > 0).length;
      const weapon = item.weapon === "longbow" ? " · range 5" : item.weapon === "crossbow" ? " · range 6" : "";
      const reload = reloading ? ` · ${reloading} reloading` : "";
      detail.textContent = `${equipped.length} · ${item.role}${weapon} · ${health}/${maxHealth} HP · ${fightPoints} FP${reload}`;
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
    renderHistory(snapshot.state.history);
    victoryNode.hidden = !simulation.captured && !simulation.defeated;
    victoryNode.classList.toggle("defeat", simulation.defeated);
    const kingAlive = defenders.some(unit => unit.is_king);
    victoryNode.querySelector(".victory-kicker").textContent = simulation.defeated
      ? throneMission && !kingAlive ? "THE KING HAS FALLEN" : "THE COMPANY HAS FALLEN"
      : throneMission ? "THE KING IS CAPTIVE" : "GREYWATCH HAS FALLEN";
    victoryNode.querySelector("h2").textContent = simulation.defeated ? "Your assault is broken."
      : throneMission ? "The king is your prisoner." : "The keep is yours.";
    victoryNode.querySelector("p").textContent = simulation.defeated
      ? throneMission && !kingAlive ? "You needed the king alive. The mission has failed." : "No attackers remain on the field."
      : throneMission ? "Your company captured the king alive." : "Your small band has secured the courtyard.";
    updatePromotion();
    updateMovementPreview();
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
    updateMovementPreview();
    if (action.type === "end_turn") showToast("Defenders are taking their turn...");
    try {
      const snapshot = await api("/api/games/actions/", { revision, action });
      const wasCaptured = simulation.captured;
      const combat = combatSummary(simulation.units, snapshot.state.units);
      applySnapshot(snapshot);
      if (animationsEnabled()) renderer.queueProjectiles(snapshot.combat_events, animationTime);
      if (!wasCaptured && simulation.captured) showToast(mapData.mission === "capture_king" ? "The king has been captured alive." : "Greywatch courtyard secured.");
      else if (simulation.defeated) showToast(mapData.mission === "capture_king" && !simulation.units.some(unit => unit.is_king) ? "The king was killed. Mission failed." : "Your company has been defeated.");
      else showToast(combat || (action.type === "end_turn" ? `Defenders have taken their turn. Turn ${snapshot.state.turn} begins.` : action.type === "promote" ? "Recruit promoted to veteran; bonus points begin next turn." : action.type === "aim_catapult" ? "Catapult aimed. A crew member can fire when ready." : action.type === "fire_catapult" ? "Catapult fired." : action.type === "pickup_item" ? "Potion collected." : action.type === "drop_item" ? "Potion dropped." : action.type === "use_item" ? "Ally healed." : "Order received."));
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
      updateMovementPreview();
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

  function enterGame(snapshot) {
    const { entry, kind } = snapshot;
    currentEntryId = entry.id;
    currentKind = kind;
    currentGameId = snapshot.game_id;
    applySnapshot(snapshot);
    gameIsVisible = true;
    launchUI.enterGame(snapshot);
    updateMovementPreview();
    input.resetCamera();
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
    } catch (error) {
      if (gameIsVisible) showToast(`Could not restart game: ${error.message}`);
      else launchUI.renderCatalogMessage(`Could not start game: ${error.message}`, true);
    } finally {
      pendingAction = false;
      updatePromotion();
    }
  }

  const input = createBattlefieldInput({ canvas, renderer, simulation,
    getMap: () => mapData,
    getLayout: () => ({ width, height, tileW, tileH, originX, originY }),
    canOrder: () => gameIsVisible && !simulation.captured && !simulation.defeated && !pendingAction && !paused,
    isWalkable, onMove: moveSelected, onAttack: attackSelected, onSelection: updateSelection,
    isAiming: () => aimingCatapult, onAim: aimCatapultAt,
    onBlocked: () => showToast("An obstacle bars the way. Choose an open tile."),
    onDraw: draw, onCursor: describeCursor, onPreviewChange: updateMovementPreview });
  const launchUI = createLaunchUI({ api, onStart: launchGame,
    onResume: async () => enterGame(await api("/api/games/current/")),
    onLeaveGame: () => {
      gameIsVisible = false;
      input.cancelPointer();
      renderer.clearProjectiles();
      aimingCatapult = false;
      updateMovementPreview();
    } });
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
  aimButton.addEventListener("click", () => {
    aimingCatapult = !aimingCatapult;
    updateControls();
    updateMovementPreview();
    if (aimingCatapult) showToast("Select a target tile (including walls) on the battlefield. Aiming costs one fight point.");
  });
  fireButton.addEventListener("click", () => {
    const crew = selectedCrew();
    if (crew && !fireButton.disabled) sendAction({ type: "fire_catapult", unit_id: crew.unit.id, catapult_id: crew.catapult.id });
  });
  pickupButton.addEventListener("click", () => {
    const medic = selectedMedic();
    const item = simulation.items.find(item => medic && item.carrier_id === null && item.x === medic.x && item.y === medic.y);
    if (item && !pickupButton.disabled) sendAction({ type: "pickup_item", unit_id: medic.id, item_id: item.id });
  });
  dropButton.addEventListener("click", () => {
    const medic = selectedMedic();
    const item = simulation.items.find(item => medic && item.carrier_id === medic.id);
    if (item && !dropButton.disabled) sendAction({ type: "drop_item", unit_id: medic.id, item_id: item.id });
  });
  healButton.addEventListener("click", () => {
    const medic = selectedMedic();
    const item = simulation.items.find(item => medic && item.carrier_id === medic.id);
    if (item && !healButton.disabled) sendAction({ type: "use_item", unit_id: medic.id, item_id: item.id, target_id: Number(healTarget.value) });
  });
  pauseButton.addEventListener("click", () => {
    if (simulation.captured || simulation.defeated) return;
    paused = !paused;
    input.cancelPointer();
    updateControls();
    updateMovementPreview();
  });
  speedSelect.addEventListener("change", () => {
    const nextSpeed = Number(speedSelect.value);
    if (!validSpeeds.includes(nextSpeed)) return;
    animationSpeed = nextSpeed;
    if (!animationsEnabled()) renderer.clearProjectiles();
    try { window.localStorage.setItem(speedKey, speedSelect.value); } catch (_) { /* Storage is optional. */ }
    draw();
  });
  reducedMotion.addEventListener?.("change", () => {
    if (!animationsEnabled()) renderer.clearProjectiles();
    draw();
  });
  promoteButton.addEventListener("click", () => {
    const [unitId] = simulation.selected;
    if (unitId !== undefined && !promoteButton.disabled) sendAction({ type: "promote", unit_id: unitId });
  });
  captureButton.addEventListener("click", () => {
    const unitId = captureCandidate();
    if (unitId !== null && !captureButton.disabled) sendAction({ type: "capture", unit_id: unitId });
  });
  window.addEventListener("resize", resize);
})();
