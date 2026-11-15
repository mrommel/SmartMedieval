import { createBattlefieldRenderer } from "./renderer.js";

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
  const historyList = document.getElementById("combat-history-list");
  const cursorStatus = document.getElementById("cursor-status");
  const continueButton = document.getElementById("continue-game");
  const launchError = document.getElementById("launch-error");
  const csrfToken = document.querySelector('meta[name="csrf-token"]').content;

  let COLS, ROWS, KEEP, GATE, OBJECTIVE, mapData;
  let objects = new Map();
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
  const cursor = { x: 0, y: 0, visible: false };
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
    tileW = Math.min(64, width * 1.72 / (COLS + ROWS));
    tileH = tileW * 0.5;
    originX = width * 0.5;
    const mapHeight = (COLS + ROWS - 2) * tileH * 0.5;
    originY = Math.max(42, (height - mapHeight) * 0.5 + tileH * 1.1);
    renderer.setLayout({ width, height, tileW, tileH, originX, originY, ratio });
    clampCamera();
    draw();
  }

  function clampCamera() {
    const mapWidth = (COLS + ROWS - 2) * tileW * 0.5;
    const mapHeight = (COLS + ROWS - 2) * tileH * 0.5;
    const left = originX - mapWidth;
    const right = originX + mapWidth;
    const top = originY - tileH * (2.7 + Math.max(0, ...(mapData.elevation || []).map(tile => tile.height)));
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

  function isWalkable(x, y) {
    return x >= 0 && x < COLS && y >= 0 && y < ROWS && !renderer.isWall(x, y) && !objects.has(`${x},${y}`);
  }

  function draw() {
    renderer.draw(animationTime, { simulation, camera, cursor, hasAttackOption });
  }

  function moveSelected(x, y) {
    if (!simulation.selected.size) return;
    sendAction({ type: "move", units: [...simulation.selected], x, y });
  }

  function attackSelected(target) {
    const selected = simulation.units.filter(unit => simulation.selected.has(unit.id));
    const melee = selected.find(unit => unit.type === "vanguard" && unit.fight_points > 0 &&
      Math.abs(unit.x - target.x) + Math.abs(unit.y - target.y) === 1 &&
      renderer.tileHeight(unit.x, unit.y) === renderer.tileHeight(target.x, target.y));
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
        if (ix < nx && iy < ny && (!isWalkable(x + stepX, y) || !isWalkable(x, y + stepY))) return false;
        x += stepX; y += stepY; ix++; iy++;
      } else if (horizontal < vertical) {
        x += stepX; ix++;
      } else {
        y += stepY; iy++;
      }
      if ((x !== targetX || y !== targetY) && !isWalkable(x, y)) return false;
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
          renderer.tileHeight(unit.x, unit.y) === renderer.tileHeight(target.x, target.y)
        : !(unit.reload_turns > 0) && canRangedAttack(unit, target)));
  }

  function pickTile(localX, localY) {
    for (const tile of [...(mapData.elevation || [])].sort((a, b) => b.x + b.y - a.x - a.y)) {
      const p = renderer.project(tile.x, tile.y);
      if (Math.abs(localX - p.x) / (tileW / 2) +
          Math.abs(localY - p.y - tileH / 2) / (tileH / 2) <= 1) {
        return { x: tile.x, y: tile.y };
      }
    }
    const a = (localX - originX) / (tileW / 2);
    const b = (localY - originY) / (tileH / 2);
    // Projection places the top corner of each diamond at (x, y).
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
      const p = renderer.project(unit.x, unit.y);
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
      const p = renderer.project(unit.x, unit.y);
      return Math.hypot(px - p.x, py - (p.y + tileH * .1)) < Math.max(17, tileW * .29);
    });
    if (target) {
      attackSelected(target);
      return;
    }
    const tile = pickTile(px, py);
    if (!isWalkable(tile.x, tile.y)) {
      showToast("An obstacle bars the way. Choose an open tile.");
      return;
    }
    moveSelected(tile.x, tile.y);
  }

  function describeCursor() {
    const unit = simulation.units.find(item => item.x === cursor.x && item.y === cursor.y);
    const location = `Tile ${cursor.x + 1}, ${cursor.y + 1}`;
    cursorStatus.textContent = `${location}: ${unit
      ? `${unit.side === "defenders" ? "defender" : "friendly"} ${unit.type} #${unit.id + 1}${simulation.selected.has(unit.id) ? ", selected" : ""}`
      : objects.get(`${cursor.x},${cursor.y}`)?.type || (renderer.isWall(cursor.x, cursor.y) ? "wall" : cursor.x === OBJECTIVE.x && cursor.y === OBJECTIVE.y
        ? "courtyard objective" : "open ground")}.`;
  }

  function revealCursor() {
    const point = renderer.project(cursor.x, cursor.y);
    const screenX = point.x * camera.zoom + camera.x;
    const screenY = (point.y + tileH / 2) * camera.zoom + camera.y;
    const margin = 32;
    camera.x += Math.max(margin - screenX, 0) - Math.max(screenX - (width - margin), 0);
    camera.y += Math.max(margin - screenY, 0) - Math.max(screenY - (height - margin), 0);
    clampCamera();
  }

  function handleKeyboardOrder(shiftKey) {
    const unit = simulation.units.find(item => item.x === cursor.x && item.y === cursor.y);
    if (unit?.side === "defenders") {
      attackSelected(unit);
    } else if (unit) {
      if (shiftKey) {
        if (simulation.selected.has(unit.id)) simulation.selected.delete(unit.id);
        else simulation.selected.add(unit.id);
      } else {
        simulation.selected = new Set([unit.id]);
      }
      updateSelection();
      describeCursor();
    } else if (!isWalkable(cursor.x, cursor.y)) {
      showToast("An obstacle bars the way. Choose an open tile.");
    } else {
      moveSelected(cursor.x, cursor.y);
    }
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
      const actor = `${event.actor_side === "defenders" ? "Defender" : "Attacker"} ${event.actor_type} #${event.actor_id + 1}`;
      if (event.type === "promote") {
        item.textContent = `Turn ${event.turn} · ${actor} promoted to veteran (morale ${event.morale_change}).`;
      } else {
        const target = `${event.target_side === "defenders" ? "defender" : "attacker"} ${event.target_type} #${event.target_id + 1}`;
        const morale = event.morale_changes.map(change =>
          `#${change.unit_id + 1} ${change.change > 0 ? "+" : ""}${change.change}`).join(", ");
        item.textContent = `Turn ${event.turn} · ${actor} ${event.type === "ranged_attack" ? "shot" : "struck"} ${target} for ${event.damage} damage${event.cover ? ` (${event.cover} cover blocked the shot)` : ""}${event.killed ? " (fallen)" : ""}.${morale ? ` Morale: ${morale}.` : ""}`;
      }
      return item;
    }));
    historyList.scrollTop = historyList.scrollHeight;
  }

  function applySnapshot(snapshot) {
    const newGame = instanceId !== snapshot.id;
    if (newGame) {
      renderer.clearProjectiles();
      paused = false;
    }
    instanceId = snapshot.id;
    revision = snapshot.revision;
    mapData = snapshot.map;
    ({ cols: COLS, rows: ROWS, keep: KEEP, gate: GATE, objective: OBJECTIVE } = mapData);
    renderer.setMap(mapData);
    objects = new Map((snapshot.map.objects || []).map(obj => [`${obj.x},${obj.y}`, obj]));
    simulation.units = snapshot.state.units;
    simulation.captured = snapshot.state.captured;
    simulation.defeated = snapshot.state.defeated || false;
    simulation.captureProgress = snapshot.state.capture_progress;
    const attackers = simulation.units.filter(unit => unit.side !== "defenders");
    const defenders = simulation.units.filter(unit => unit.side === "defenders");
    startingAttackerCount = snapshot.map.startPositions.length;
    if (newGame) simulation.selected = new Set([attackers[0].id]);
    else simulation.selected = new Set([...simulation.selected].filter(id => attackers.some(unit => unit.id === id)));
    if (newGame) {
      cursor.x = attackers[0]?.x ?? OBJECTIVE.x;
      cursor.y = attackers[0]?.y ?? OBJECTIVE.y;
    }
    cursor.x = Math.max(0, Math.min(COLS - 1, cursor.x));
    cursor.y = Math.max(0, Math.min(ROWS - 1, cursor.y));
    describeCursor();
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
    renderHistory(snapshot.state.history);
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
      if (animationsEnabled()) renderer.queueProjectiles(snapshot.combat_events, animationTime);
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
    renderer.clearProjectiles();
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
  canvas.addEventListener("focus", () => {
    cursor.visible = true;
    describeCursor();
    draw();
  });
  canvas.addEventListener("blur", () => {
    cursor.visible = false;
    draw();
  });
  canvas.addEventListener("keydown", event => {
    const directions = {
      ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1]
    };
    if (directions[event.key]) {
      event.preventDefault();
      const [dx, dy] = directions[event.key];
      cursor.x = Math.max(0, Math.min(COLS - 1, cursor.x + dx));
      cursor.y = Math.max(0, Math.min(ROWS - 1, cursor.y + dy));
      describeCursor();
      revealCursor();
      draw();
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      if (!paused && !pendingAction && !simulation.captured && !simulation.defeated) handleKeyboardOrder(event.shiftKey);
    }
  });
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
