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
  const reactionButton = document.getElementById("reserve-reaction");
  const movementReactionButton = document.getElementById("reserve-movement");
  const crouchButton = document.getElementById("crouch");
  const shieldButton = document.getElementById("raise-shield");
  const promoteButton = document.getElementById("promote");
  const captureButton = document.getElementById("capture-king");
  const withdrawButton = document.getElementById("withdraw-unit");
  const aimButton = document.getElementById("aim-catapult");
  const fireButton = document.getElementById("fire-catapult");
  const pickupButton = document.getElementById("pickup-potion");
  const dropButton = document.getElementById("drop-potion");
  const healButton = document.getElementById("heal-potion");
  const healTarget = document.getElementById("heal-target");
  const gearTarget = document.getElementById("gear-target");
  const pickupEquipmentButton = document.getElementById("pickup-equipment");
  const dropWeaponButton = document.getElementById("drop-weapon");
  const dropArmorButton = document.getElementById("drop-armor");
  const toolTarget = document.getElementById("tool-target");
  const groundToolTarget = document.getElementById("ground-tool-target");
  const pickupToolButton = document.getElementById("pickup-tool");
  const dropToolButton = document.getElementById("drop-tool");
  const watchfireTarget = document.getElementById("watchfire-target");
  const toggleWatchfireButton = document.getElementById("toggle-watchfire");
  const toggleTorchButton = document.getElementById("toggle-torch");
  const fireTarget = document.getElementById("fire-target");
  const extinguishFireButton = document.getElementById("extinguish-fire");
  const armorButton = document.getElementById("equip-armor");
  const mountButton = document.getElementById("mount-horse");
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
  const simulation = { units: [], catapults: [], horses: [], items: [], smoke: [], fire: [], selected: new Set(), captured: false, defeated: false, captureProgress: 0, visible: null, explored: null };
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
    const nearbyFlames = medic ? simulation.fire.filter(flame =>
      Math.abs(medic.x - flame.x) + Math.abs(medic.y - flame.y) <= 1 &&
      medic.z === renderer.tileHeight(flame.x, flame.y) &&
      (medic.x === flame.x && medic.y === flame.y || canMeleeAttack(medic, flame))) : [];
    const previousFlame = fireTarget.value;
    fireTarget.replaceChildren(...nearbyFlames.map(flame => {
      const option = document.createElement("option");
      option.value = `${flame.x},${flame.y}`;
      option.textContent = `Fire ${flame.x + 1}, ${flame.y + 1}`;
      return option;
    }));
    fireTarget.value = nearbyFlames.some(flame => `${flame.x},${flame.y}` === previousFlame)
      ? previousFlame : nearbyFlames.length ? `${nearbyFlames[0].x},${nearbyFlames[0].y}` : "";
    fireTarget.hidden = extinguishFireButton.hidden = !simulation.fire.length;
    fireTarget.disabled = pendingAction || paused || ended || !nearbyFlames.length;
    extinguishFireButton.disabled = fireTarget.disabled || !medic?.fight_points;
    const nearbyFires = medic && mapData?.night ? (mapData.watchfires || []).filter(fire =>
      Math.abs(medic.x - fire.x) + Math.abs(medic.y - fire.y) <= 1 &&
      medic.z === renderer.tileHeight(fire.x, fire.y)) : [];
    const previousFire = watchfireTarget.value;
    watchfireTarget.replaceChildren(...nearbyFires.map(fire => {
      const option = document.createElement("option");
      option.value = `${fire.x},${fire.y}`;
      option.textContent = `Watchfire ${fire.x + 1}, ${fire.y + 1}`;
      return option;
    }));
    watchfireTarget.value = nearbyFires.some(fire => `${fire.x},${fire.y}` === previousFire)
      ? previousFire : nearbyFires.length ? `${nearbyFires[0].x},${nearbyFires[0].y}` : "";
    const chosenFire = nearbyFires.find(fire => `${fire.x},${fire.y}` === watchfireTarget.value);
    const out = chosenFire && simulation.extinguishedWatchfires?.some(fire => fire.x === chosenFire.x && fire.y === chosenFire.y);
    watchfireTarget.hidden = toggleWatchfireButton.hidden = !mapData?.night || !mapData?.watchfires?.length;
    watchfireTarget.disabled = pendingAction || paused || ended || !nearbyFires.length;
    toggleWatchfireButton.disabled = watchfireTarget.disabled || !medic?.fight_points;
    toggleWatchfireButton.textContent = out ? "Light watchfire (1 FP)" : "Extinguish watchfire (1 FP)";
    const hasTorch = Boolean(medic?.tools?.includes("torch"));
    toggleTorchButton.hidden = !mapData?.night || !hasTorch;
    toggleTorchButton.disabled = pendingAction || paused || ended || !hasTorch || !medic.fight_points;
    toggleTorchButton.textContent = medic?.torch_lit === false ? "Light torch (1 FP)" : "Extinguish torch (1 FP)";
    toggleTorchButton.setAttribute("aria-pressed", String(hasTorch && medic.torch_lit !== false));
    reactionButton.disabled = pendingAction || paused || ended || !medic ||
      (!medic.reaction_reserved && (!medic.fight_points || !["sword", "longbow", "crossbow"].includes(medic.weapon) || medic.reload_turns > 0));
    reactionButton.textContent = medic?.reaction_reserved ? "Cancel reaction" : "Reserve attack (1 FP)";
    reactionButton.setAttribute("aria-pressed", String(Boolean(medic?.reaction_reserved)));
    movementReactionButton.disabled = pendingAction || paused || ended || !medic ||
      (!medic.move_reserved && !medic.move_points);
    movementReactionButton.textContent = medic?.move_reserved ? "Cancel movement reserve" :
      `Reserve movement (${medic?.move_points ?? 0} MP)`;
    movementReactionButton.setAttribute("aria-pressed", String(Boolean(medic?.move_reserved)));
    crouchButton.disabled = pendingAction || paused || ended || !medic || medic.crouched || medic.shield_raised ||
      !medic.fight_points || medic.mount_id != null || Boolean(medic.move_reserved);
    crouchButton.setAttribute("aria-pressed", String(Boolean(medic?.crouched)));
    const hasShield = Boolean(medic?.tools?.includes("shield"));
    shieldButton.hidden = !hasShield;
    shieldButton.disabled = pendingAction || paused || ended || !hasShield ||
      (!medic.shield_raised && (!medic.fight_points || !medic.move_points || medic.crouched ||
        medic.mount_id != null || Boolean(medic.move_reserved)));
    shieldButton.textContent = medic?.shield_raised ? "Lower shield (free)" : "Raise shield (1 FP, 1 MP)";
    shieldButton.setAttribute("aria-pressed", String(Boolean(medic?.shield_raised)));
    const availableHorse = simulation.horses.find(horse => medic && horse.rider_id === null &&
      horse.x === medic.x && horse.y === medic.y);
    mountButton.hidden = !simulation.horses.length;
    mountButton.textContent = medic?.mount_id != null ? "Dismount" : "Mount";
    mountButton.disabled = pendingAction || paused || ended || !medic?.fight_points || medic?.crouched || medic?.shield_raised ||
      (medic.mount_id == null && !availableHorse);
    armorButton.hidden = !medic?.armor;
    armorButton.disabled = pendingAction || paused || ended || !medic?.fight_points;
    armorButton.textContent = medic?.armor_equipped ? "Remove armor" : "Equip armor";
    dropWeaponButton.hidden = !medic?.weapon;
    dropArmorButton.hidden = !medic?.armor;
    dropWeaponButton.disabled = pendingAction || paused || ended || !medic?.fight_points;
    dropArmorButton.disabled = pendingAction || paused || ended || !medic?.fight_points;
    const gear = medic && simulation.items.filter(item => ["weapon", "armor"].includes(item.type) &&
      item.carrier_id === null && item.x === medic.x && item.y === medic.y);
    const selectedGear = gear?.find(item => String(item.id) === gearTarget.value);
    const hasGear = simulation.items.some(item => item.type === "weapon" || item.type === "armor");
    gearTarget.hidden = pickupEquipmentButton.hidden = !hasGear;
    gearTarget.disabled = pendingAction || paused || ended || !gear?.length;
    pickupEquipmentButton.disabled = gearTarget.disabled || !medic?.fight_points || !selectedGear ||
      (selectedGear.type === "weapon" ? medic.weapon != null : medic.armor != null) ||
      (medic.carried_weight != null && medic.carried_weight +
        (selectedGear.type === "weapon" ? { sword: 1, longbow: 2, crossbow: 3 }[selectedGear.name] :
          { leather: 1, mail: 3 }[selectedGear.name]) > (medic.max_carry_weight ?? 8));
    const groundTool = simulation.items.find(item => String(item.id) === groundToolTarget.value && item.type === "tool" &&
      item.carrier_id === null && medic && item.x === medic.x && item.y === medic.y);
    groundToolTarget.hidden = pickupToolButton.hidden = !simulation.items.some(item => item.type === "tool");
    groundToolTarget.disabled = pendingAction || paused || ended || !medic || !groundToolTarget.children.length;
    pickupToolButton.disabled = groundToolTarget.disabled || !medic?.fight_points || !groundTool ||
      medic.tools?.length >= 2 || (medic.carried_weight != null && medic.carried_weight >= (medic.max_carry_weight ?? 8));
    toolTarget.hidden = dropToolButton.hidden = !medic?.tools?.length;
    toolTarget.disabled = dropToolButton.disabled = pendingAction || paused || ended || !medic?.fight_points;
    const carried = medic && simulation.items.filter(item => item.type === "healing_potion" && item.carrier_id === medic.id);
    const hasPotions = Boolean(mapData?.has_items ?? mapData?.items?.some(item => item.type === "healing_potion"));
    pickupButton.hidden = dropButton.hidden = healButton.hidden = healTarget.hidden = !hasPotions;
    pickupButton.disabled = pendingAction || paused || ended || !medic || !medic.fight_points ||
      carried.length >= 2 || (medic.carried_weight != null && medic.carried_weight >= (medic.max_carry_weight ?? 8)) ||
      !simulation.items.some(item => item.type === "healing_potion" && item.carrier_id === null && item.x === medic.x && item.y === medic.y);
    dropButton.disabled = pendingAction || paused || ended || !medic || !medic.fight_points || !carried.length;
    healButton.disabled = pendingAction || paused || ended || !medic || !medic.fight_points || !carried.length || !healTarget.children.length;
    healTarget.disabled = pendingAction || paused || ended || !medic || !carried.length || !healTarget.children.length;
    endTurnButton.disabled = pendingAction || paused || ended;
    promoteButton.disabled = pendingAction || paused || ended ||
      !promotionCandidate();
    captureButton.disabled = pendingAction || paused || ended || captureCandidate() === null;
    withdrawButton.disabled = pendingAction || paused || ended || !medic?.fight_points ||
      !mapData?.exit || medic.x !== mapData.exit.x || medic.y !== mapData.exit.y;
    aimButton.hidden = fireButton.hidden = !simulation.catapults.length;
    aimButton.disabled = pendingAction || paused || ended || !crew || crew.unit.mount_id != null || !crew.unit.fight_points || !crew.catapult.ammo;
    fireButton.disabled = pendingAction || paused || ended || !crew || !crew.unit.fight_points ||
      crew.unit.mount_id != null || !crew.catapult.ammo || !crew.catapult.aim || crew.catapult.reload_turns > 0;
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
      (unit.health < unit.max_health || unit.wound_turns > 0) && (unit.id === medic.id ||
      (unit.z === medic.z && canMeleeAttack(medic, unit)))) : [];
    healTarget.replaceChildren(...candidates.map(unit => {
      const option = document.createElement("option");
      option.value = String(unit.id);
      option.textContent = `Treat #${unit.id + 1} (${unit.health}/${unit.max_health} HP${unit.wound_turns ? ", wounded" : ""})`;
      return option;
    }));
    if (candidates.some(unit => String(unit.id) === previous)) healTarget.value = previous;
  }

  function equipmentName(item) {
    return item.type === "armor" ? `${item.name} armor` : item.name;
  }

  function updateGearTargets() {
    const soldier = selectedMedic();
    const previous = gearTarget.value;
    const gear = soldier ? simulation.items.filter(item => ["weapon", "armor"].includes(item.type) &&
      item.carrier_id === null && item.x === soldier.x && item.y === soldier.y) : [];
    gearTarget.replaceChildren(...gear.map(item => {
      const option = document.createElement("option");
      option.value = String(item.id);
      option.textContent = equipmentName(item);
      return option;
    }));
    if (gear.some(item => String(item.id) === previous)) gearTarget.value = previous;
    else if (gear.length) gearTarget.value = String(gear[0].id);
  }

  function updateToolTargets() {
    const previous = toolTarget.value;
    const tools = selectedMedic()?.tools || [];
    toolTarget.replaceChildren(...tools.map((name, index) => {
      const option = document.createElement("option");
      option.value = String(index);
      option.textContent = name;
      return option;
    }));
    toolTarget.value = tools[Number(previous)] != null ? previous : "0";
    const soldier = selectedMedic();
    const priorGround = groundToolTarget.value;
    const ground = soldier ? simulation.items.filter(item => item.type === "tool" && item.carrier_id === null &&
      item.x === soldier.x && item.y === soldier.y) : [];
    groundToolTarget.replaceChildren(...ground.map(item => {
      const option = document.createElement("option");
      option.value = String(item.id);
      option.textContent = item.name;
      return option;
    }));
    groundToolTarget.value = ground.some(item => String(item.id) === priorGround) ? priorGround : String(ground[0]?.id ?? "");
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
    if (attacker.mount_id != null && (houseAt(target.x, target.y) >= 0 ||
        mapData?.terrain?.some(tile => tile.x === target.x && tile.y === target.y && tile.type === "swamp"))) return false;
    const from = houseAt(attacker.x, attacker.y), to = houseAt(target.x, target.y);
    if (from === to) return true;
    if (from >= 0 && to >= 0) return false;
    const house = mapData.houses[from < 0 ? to : from];
    return (from < 0 ? target.x === house.door.x && target.y === house.door.y :
      attacker.x === house.door.x && attacker.y === house.door.y);
  }

  function blocksSight(x, y, interior = -1) {
    return [...simulation.smoke, ...simulation.fire].some(cloud => cloud.x === x && cloud.y === y) || renderer.isWall(x, y) || (renderer.isHouse(x, y) &&
      (interior < 0 || houseAt(x, y) !== interior)) ||
      (objects.has(`${x},${y}`) && objects.get(`${x},${y}`).type !== "fence");
  }

  function draw() {
    const soldier = selectedMedic();
    const reactionTiles = [];
    const movementReactionTiles = [];
    if (soldier?.reaction_reserved) {
      for (let y = 0; y < ROWS; y++) for (let x = 0; x < COLS; x++) {
        if (!isWalkable(x, y) || simulation.visible && !simulation.visible.has(`${x},${y}`)) continue;
        const target = { x, y };
        if (soldier.weapon === "sword" ? canMeleeAttack(soldier, target) : canRangedAttack(soldier, target)) reactionTiles.push(target);
      }
    }
    if (soldier?.move_reserved) {
      for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
        const x = soldier.x + dx, y = soldier.y + dy;
        if (isWalkable(x, y) && (!simulation.visible || simulation.visible.has(`${x},${y}`)) &&
            canMeleeAttack(soldier, { x, y })) movementReactionTiles.push({ x, y });
      }
    }
    renderer.draw(animationTime, { simulation, camera: input.camera, cursor: input.cursor, hasAttackOption, movementPreview, reactionTiles, movementReactionTiles });
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
        const unit = selected[0];
        const load = unit.carried_weight == null ? "" : unit.mount_id != null ?
          ` · mounted (load ${unit.carried_weight}/${unit.max_carry_weight} does not slow the horse)` :
          ` · load ${unit.carried_weight}/${unit.max_carry_weight} (${unit.weight_penalty} MP penalty)`;
        routeStatus.textContent = `Route to tile ${destination.x + 1}, ${destination.y + 1}: ${route.path.length} ${route.path.length === 1 ? "tile" : "tiles"} · ${route.totalCost} MP total · ${route.thisTurnCost} MP this turn (${route.thisTurn} ${route.thisTurn === 1 ? "tile" : "tiles"})${load}${route.turns > 1 ? ` · approximately ${route.turns} turns if the route stays clear` : route.turns === null ? " · route may require more movement per turn" : ""}.`;
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
    if ([...simulation.smoke, ...simulation.fire].some(cloud => (cloud.x === start[0] && cloud.y === start[1]) ||
      (cloud.x === end[0] && cloud.y === end[1]))) return false;
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
    if (simulation.visible && !simulation.visible.has(`${cursor.x},${cursor.y}`)) {
      cursorStatus.textContent = `Tile ${cursor.x + 1}, ${cursor.y + 1}: ${simulation.explored.has(`${cursor.x},${cursor.y}`) ? "out of sight" : "unexplored"}.`;
      return;
    }
    const unit = simulation.units.find(item => item.x === cursor.x && item.y === cursor.y);
    const horse = simulation.horses.find(item => item.x === cursor.x && item.y === cursor.y);
    const groundItems = simulation.items.filter(item => item.carrier_id === null && item.x === cursor.x && item.y === cursor.y);
    const smoke = simulation.smoke.find(cloud => cloud.x === cursor.x && cloud.y === cursor.y);
    const fire = simulation.fire.find(flame => flame.x === cursor.x && flame.y === cursor.y);
    const potion = groundItems.some(item => item.type === "healing_potion");
    const gear = groundItems.filter(item => item.type === "weapon" || item.type === "armor")
      .map(equipmentName).join(", ");
    const tools = groundItems.filter(item => item.type === "tool").map(item => item.name).join(", ");
    const location = `Tile ${cursor.x + 1}, ${cursor.y + 1}`;
    cursorStatus.textContent = `${location}: ${fire ? `fire (${fire.turns} turns left, +2 MP and 1 damage); ` : ""}${smoke ? `smoke (${smoke.turns} turn${smoke.turns === 1 ? "" : "s"} left); ` : ""}${unit
      ? `${unit.side === "defenders" ? "defender" : "friendly"} ${unit.is_king ? "king" : `with ${unit.weapon || "no weapon"}`} #${unit.id + 1}${unit.mount_id != null ? `, mounted (horse ${horse?.health ?? "?"} HP)` : horse ? ", horse available" : ""}${simulation.selected.has(unit.id) ? ", selected" : ""}${potion ? ", healing potion on ground" : ""}${gear ? `, ${gear} on ground` : ""}${tools ? `, ${tools} tool on ground` : ""}`
      : gear || tools ? `${[gear && `${gear} on ground`, tools && `${tools} tool on ground`].filter(Boolean).join(", ")}${potion ? ", healing potion" : ""}`
      : potion ? "healing potion"
      : horse ? `horse (${horse.health}/${horse.max_health} HP); move a soldier here to mount`
      : simulation.catapults.find(item => item.x === cursor.x && item.y === cursor.y) ? "catapult" :
        objects.get(`${cursor.x},${cursor.y}`)?.type || (renderer.isWall(cursor.x, cursor.y) ? "wall" :
        renderer.isHouseDoor(cursor.x, cursor.y) ? "house door" :
        renderer.isEnterableHouse(cursor.x, cursor.y) ? "house interior" :
        renderer.isHouse(cursor.x, cursor.y) ? "house" : cursor.x === OBJECTIVE.x && cursor.y === OBJECTIVE.y
        ? mapData?.mission === "capture_king" ? "throne" : "courtyard objective" :
        mapData?.terrain?.find(tile => tile.x === cursor.x && tile.y === cursor.y)?.type ||
        (mapData?.lanes?.some(tile => tile.x === cursor.x && tile.y === cursor.y) ? "lane" : "open ground"))}.`;
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
    const potions = unit ? simulation.items.filter(item => item.type === "healing_potion" && item.carrier_id === unit.id).length : 0;
    const gear = unit ? simulation.items.filter(item => ["weapon", "armor"].includes(item.type) &&
      item.carrier_id === null && item.x === unit.x && item.y === unit.y) : [];
    const groundTools = unit ? simulation.items.filter(item => item.type === "tool" &&
      item.carrier_id === null && item.x === unit.x && item.y === unit.y) : [];
    const horse = unit ? simulation.horses.find(item => item.id === unit.mount_id) : null;
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
        : `Projected next turn: ${unit.next_move_capacity} MP · ${unit.next_fight_capacity} FP (at current morale and rank${horse ? " and mount" : unit.carried_weight == null ? "" : " and load"}${unit.wound_turns > 1 ? " and injury" : ""})`;
      selectedStats.replaceChildren(identity,
        statRow("Health", unit.health, unit.max_health, "HP", "health"),
        ...(unit.wound_turns ? [detailRow("Injury", `Wounded · −1 MP on foot; ${unit.wound_turns} turn(s) until recovery. A healing potion treats it immediately.`)] : []),
        statRow("Morale", unit.morale ?? 3, 5, "", "morale"),
        statRow("Movement", unit.move_points, moveCapacity, "MP", "movement"),
        statRow("Fight", unit.fight_points, fightCapacity, "FP", "fight"),
        ...(unit.reaction_reserved ? [detailRow("Reaction", "1 FP reserved  attacks the first visible defender moving into range")] : []),
        ...(unit.move_reserved ? [detailRow("Movement reserve", `${unit.move_reserved} MP held · evade an adjacent visible defender if a legal escape tile is available`)] : []),
        ...(unit.crouched ? [detailRow("Stance", "Crouched · −1 incoming ranged damage per shot; cannot move until next turn")] : []),
        ...(unit.shield_raised ? [detailRow("Stance", "Shield raised · −1 direct damage from visible attackers; sight reduced until next turn")] : []),
        nextTurn,
        detailRow("Weapon", unit.weapon || "none"),
        detailRow("Horse", horse ? `${horse.health}/${horse.max_health} HP · mounted; sword melee deals 2 damage` :
          simulation.horses.some(item => item.rider_id === null && item.x === unit.x && item.y === unit.y)
            ? "Available here · mount for one fight point" : "On foot"),
        detailRow("Armor", unit.armor ? `${unit.armor} · ${unit.armor_equipped ? "worn" : "carried"} · ${unit.armor_remaining ?? 0}/${unit.armor === "mail" ? 2 : 1} protection left this turn · weight ${unit.armor === "mail" ? 3 : 1}` : "none"),
        detailRow("Tools", unit.tools?.length ? unit.tools.map(tool =>
          tool === "torch" && mapData?.night ? `torch (${unit.torch_lit === false ? "unlit" : "lit"})` : tool).join(", ") : "none"),
        detailRow("Potions", `${potions}/2`),
        ...(gear.length ? [detailRow("Equipment here", gear.map(equipmentName).join(", "))] : []),
        ...(groundTools.length ? [detailRow("Tools here", groundTools.map(item => item.name).join(", "))] : []),
        ...(unit.carried_weight == null ? [] : [detailRow("Load", `${unit.carried_weight}/${unit.max_carry_weight} weight · ${horse ? "no mounted penalty" : `−${unit.weight_penalty} MP/turn (1 per 3 weight; minimum 1 MP)`}`)]),
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
    updateGearTargets();
    updateToolTargets();
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
      } else if (event.type === "equip_armor") {
        item.textContent = `Turn ${event.turn} · ${actor} ${event.equipped ? "equipped" : "removed"} ${event.armor} armor.`;
      } else if (event.type === "mount" || event.type === "dismount") {
        item.textContent = `Turn ${event.turn} · ${actor} ${event.type === "mount" ? "mounted" : "dismounted"} horse #${event.horse_id + 1}.`;
      } else if (event.type === "aim_catapult") {
        item.textContent = `Turn ${event.turn} · ${actor} aimed the catapult at ${event.x + 1}, ${event.y + 1}.`;
      } else if (event.type === "catapult_wall" || event.type === "catapult_miss") {
        item.textContent = `Turn ${event.turn} · ${actor} fired at ${event.x + 1}, ${event.y + 1}: ${event.type === "catapult_miss" ? "missed" : event.breached ? "breached the wall" : "damaged the wall"}.`;
      } else if (event.type === "pickup_item" || event.type === "drop_item") {
        item.textContent = `Turn ${event.turn} · ${actor} ${event.type === "pickup_item" ? "picked up" : "dropped"} a healing potion.`;
      } else if (["pickup_equipment", "drop_weapon", "drop_armor"].includes(event.type)) {
        item.textContent = `Turn ${event.turn} · ${actor} ${event.type === "pickup_equipment" ? "recovered" : "dropped"} ${event.equipment}${event.type === "drop_armor" || event.equipment === "mail" || event.equipment === "leather" ? " armor" : ""}.`;
      } else if (event.type === "pickup_tool" || event.type === "drop_tool") {
        item.textContent = `Turn ${event.turn} · ${actor} ${event.type === "pickup_tool" ? "picked up" : "dropped"} ${event.tool} tool.`;
      } else if (event.type === "toggle_torch") {
        item.textContent = `Turn ${event.turn} · ${actor} ${event.lit ? "lit" : "extinguished"} their torch.`;
      } else if (event.type === "light_watchfire" || event.type === "extinguish_watchfire") {
        item.textContent = `Turn ${event.turn} · ${actor} ${event.type === "light_watchfire" ? "lit" : "extinguished"} watchfire at ${event.x + 1}, ${event.y + 1}.`;
      } else if (event.type === "extinguish_fire") {
        item.textContent = `Turn ${event.turn} · ${actor} extinguished fire at ${event.x + 1}, ${event.y + 1}.`;
      } else if (event.type === "fire_damage") {
        item.textContent = `Turn ${event.turn} · Fire burned ${event.target_side === "defenders" ? "defender" : "attacker"} #${event.target_id + 1}${event.horse_hit ? "'s horse" : ""} for ${event.damage} damage${event.armor_blocked ? " (armor absorbed it)" : ""}${event.killed ? " (fallen)" : ""}.`;
      } else if (event.type === "use_item") {
        item.textContent = `Turn ${event.turn} · ${actor} treated attacker #${event.target_id + 1} for ${event.healed} HP${event.treated ? " and cleared their injury" : ""}.`;
      } else {
        const target = `${event.target_is_king ? "king" : event.target_side === "defenders" ? "defender" : "attacker"} #${event.target_id + 1}`;
        const morale = event.morale_changes.map(change =>
          `#${change.unit_id + 1} ${change.change > 0 ? "+" : ""}${change.change}`).join(", ");
        item.textContent = `Turn ${event.turn} · ${actor} ${event.reaction ? "reacted and " : ""}${event.weapon === "catapult" ? "hit with a catapult" : event.type === "ranged_attack" ? "shot" : "struck"} ${event.horse_hit ? `${target}'s horse` : target} for ${event.damage} damage${event.ambush ? " (ambush +1)" : ""}${event.cover ? ` (${event.cover} cover blocked the shot)` : ""}${event.stance_blocked ? ` (crouch absorbed ${event.stance_blocked})` : ""}${event.shield_blocked ? ` (shield absorbed ${event.shield_blocked})` : ""}${event.armor_blocked ? ` (${event.target_armor} armor absorbed ${event.armor_blocked})` : ""}${event.horse_killed ? " (horse fallen; rider dismounted)" : event.killed ? " (fallen)" : event.wounded ? " (wounded: −1 MP on foot)" : ""}.${morale ? ` Morale: ${morale}.` : ""}`;
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
    withdrawButton.hidden = !mapData.exit;
    document.getElementById("objective-name").textContent = throneMission ? "THRONE ROOM" : "KEEP COURTYARD";
    document.getElementById("mission-help").textContent = throneMission
      ? "Reach the throne room. Defeat guards beside the king, then select a soldier with a sword on an adjacent tile at the same height and press Capture king (one fight point). Clicking the king also captures him when ready. Killing the king loses the battle; simply standing on the throne cannot win. End the turn to let defenders act and restore points."
      : "Click open ground to spend move points. Houses marked D can be entered through their doors; their open roofs show interior tiles. Move next to a blue defender, then click it to spend a fight point and deal melee damage. End the turn to let defenders move and counterattack, restore points, and advance courtyard capture. Health bars show remaining health.";
    if (mapData.fog_of_war) document.getElementById("mission-help").textContent +=
      (mapData.night
        ? " Night battle: allies see two steps in the dark. A lit carried torch extends sight to five steps, but reveals its bearer to enemies up to six steps away. Lit watchfires light tiles within three steps for both sides. Walls still block sight. Extinguish or relight a carried torch for one fight point; use watchfire controls beside a fire to extinguish or relight it (one fight point)."
        : " Scout ahead: allies share daylight sight within six tiles. Dark ground is unexplored; shaded ground was explored but is out of sight. Only visible defenders can be attacked.");
    if (mapData.exit) document.getElementById("mission-help").textContent +=
      " At the marked exit, select a soldier and choose Withdraw (one fight point). Escaped soldiers keep their equipment. The battle ends once no soldiers remain in the field; at least one escape secures a retreat.";
    if (mapData.catapults?.length) document.getElementById("mission-help").textContent +=
      " Catapult impacts leave smoke for two turn transitions. Smoke blocks sight and ranged shots but not movement; S2/S1 marks its remaining duration. Impacts on grass or enterable wooden house floors also ignite fire. Fire spreads to neighboring combustible tiles, blocks sight, costs +2 MP to enter and burns occupants for 1 damage. A soldier on or beside a burning tile can extinguish it for one fight point.";
    ({ cols: COLS, rows: ROWS, keep: KEEP, gate: GATE, objective: OBJECTIVE } = mapData);
    renderer.setMap({ ...mapData, breaches: snapshot.state.breaches, wall_damage: snapshot.state.wall_damage,
      watchfires: (mapData.watchfires || []).map(fire => ({ ...fire, lit: !snapshot.state.extinguished_watchfires?.some(
        out => out.x === fire.x && out.y === fire.y) })) });
    previewMap = { ...mapData, breaches: snapshot.state.breaches || [], fire: snapshot.state.fire || [] };
    previewKey = null;
    objects = new Map((snapshot.map.objects || []).map(obj => [`${obj.x},${obj.y}`, obj]));
    simulation.units = snapshot.state.units;
    simulation.visible = snapshot.state.visible ? new Set(snapshot.state.visible.map(tile => `${tile.x},${tile.y}`)) : null;
    simulation.explored = snapshot.state.explored ? new Set(snapshot.state.explored.map(tile => `${tile.x},${tile.y}`)) : null;
    simulation.catapults = snapshot.state.catapults || [];
    simulation.horses = snapshot.state.horses || [];
    simulation.items = snapshot.state.items || [];
    simulation.smoke = snapshot.state.smoke || [];
    simulation.fire = snapshot.state.fire || [];
    simulation.extinguishedWatchfires = snapshot.state.extinguished_watchfires || [];
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
    enemyCount.textContent = mapData.fog_of_war ? `${defenders.length} IN SIGHT` : `${defenders.length} DEFENDERS`;
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
    const withdrawn = snapshot.state.withdrawn || [];
    const retreated = withdrawn.length > 0 && !attackers.length;
    const debrief = document.getElementById("mission-debrief");
    debrief.hidden = !mapData.exit || (!simulation.captured && !simulation.defeated);
    if (!debrief.hidden) {
      const fallen = startingAttackerCount - attackers.length - withdrawn.length;
      const recovered = withdrawn.reduce((count, unit) => count + Number(Boolean(unit.weapon)) +
        Number(Boolean(unit.armor)) + (unit.tools?.length || 0) + (unit.items?.length || 0), 0);
      debrief.textContent = `Mission debrief: ${withdrawn.length} withdrawn, ${fallen} fallen, ` +
        `${attackers.length} still on the field. ${recovered} carried items and pieces of equipment evacuated.`;
    }
    const kingAlive = mapData.fog_of_war ? !snapshot.state.king_fallen : defenders.some(unit => unit.is_king);
    victoryNode.querySelector(".victory-kicker").textContent = simulation.defeated
      ? throneMission && !kingAlive ? "THE KING HAS FALLEN" : "THE COMPANY HAS FALLEN"
      : retreated ? "THE COMPANY HAS WITHDRAWN" : throneMission ? "THE KING IS CAPTIVE" : "GREYWATCH HAS FALLEN";
    victoryNode.querySelector("h2").textContent = simulation.defeated ? "Your assault is broken."
      : retreated ? "Your survivors escaped." : throneMission ? "The king is your prisoner." : "The keep is yours.";
    victoryNode.querySelector("p").textContent = simulation.defeated
      ? throneMission && !kingAlive ? "You needed the king alive. The mission has failed." : "No attackers remain on the field."
      : retreated ? "At least one soldier made it out through the exit." : throneMission ? "Your company captured the king alive." : "Your small band has secured the courtyard.";
    updatePromotion();
    updateMovementPreview();
  }

  function combatSummary(before, after, history = []) {
    const remaining = new Map(after.map(unit => [unit.id, unit]));
    const damage = { attackers: 0, defenders: 0 };
    const losses = { attackers: 0, defenders: 0 };
    for (const unit of before) {
      const current = remaining.get(unit.id);
      const side = unit.side === "defenders" ? "defenders" : "attackers";
      if (!current && side === "defenders" && mapData?.fog_of_war &&
          !history.some(event => event.target_id === unit.id && event.killed)) continue;
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
      const combat = combatSummary(simulation.units, snapshot.state.units, snapshot.state.history);
      applySnapshot(snapshot);
      if (animationsEnabled()) renderer.queueProjectiles(snapshot.combat_events, animationTime);
      if (!wasCaptured && simulation.captured) showToast(snapshot.state.capture_status === "WITHDRAWN" ? "Survivors escaped through the exit." : mapData.mission === "capture_king" ? "The king has been captured alive." : "Greywatch courtyard secured.");
      else if (simulation.defeated) showToast(mapData.mission === "capture_king" &&
        (mapData.fog_of_war ? snapshot.state.king_fallen : !simulation.units.some(unit => unit.is_king)) ?
        "The king was killed. Mission failed." : "Your company has been defeated.");
      else showToast(combat || (action.type === "extinguish_fire" ? "Fire extinguished." : action.type === "withdraw" ? "Soldier evacuated with carried equipment." : action.type === "end_turn" ? `Defenders have taken their turn. Turn ${snapshot.state.turn} begins.` : action.type === "reserve_movement" ? action.reserved ? "Remaining movement reserved for an escape." : "Movement reservation cancelled; points restored." : action.type === "reserve_reaction" ? action.reserved ? "One fight point reserved for a reaction attack." : "Reaction cancelled; fight point restored." : action.type === "promote" ? "Recruit promoted to veteran; bonus points begin next turn." : action.type === "mount" ? "Mounted (one fight point)." : action.type === "dismount" ? "Dismounted (one fight point)." : action.type === "equip_armor" ? "Armor changed (one fight point)." : action.type === "pickup_equipment" ? "Equipment recovered." : action.type === "drop_weapon" || action.type === "drop_armor" ? "Equipment dropped." : action.type === "aim_catapult" ? "Catapult aimed. A crew member can fire when ready." : action.type === "fire_catapult" ? "Catapult fired." : action.type === "pickup_item" ? "Potion collected." : action.type === "drop_item" ? "Potion dropped." : action.type === "use_item" ? "Ally healed." : snapshot.state.history?.at(-1)?.horse_hit ? "The horse took the blow." : snapshot.state.history?.at(-1)?.armor_blocked ? "Armor absorbed the hit." : "Order received."));
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
  reactionButton.addEventListener("click", () => {
    const soldier = selectedMedic();
    if (soldier && !reactionButton.disabled) sendAction({ type: "reserve_reaction", unit_id: soldier.id, reserved: !soldier.reaction_reserved });
  });
  movementReactionButton.addEventListener("click", () => {
    const soldier = selectedMedic();
    if (soldier && !movementReactionButton.disabled) sendAction({ type: "reserve_movement", unit_id: soldier.id, reserved: !soldier.move_reserved });
  });
  crouchButton.addEventListener("click", () => {
    const soldier = selectedMedic();
    if (soldier && !crouchButton.disabled) sendAction({ type: "crouch", unit_id: soldier.id });
  });
  shieldButton.addEventListener("click", () => {
    const soldier = selectedMedic();
    if (soldier && !shieldButton.disabled) sendAction({ type: "raise_shield", unit_id: soldier.id, raised: !soldier.shield_raised });
  });
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
    const item = simulation.items.find(item => medic && item.type === "healing_potion" && item.carrier_id === null && item.x === medic.x && item.y === medic.y);
    if (item && !pickupButton.disabled) sendAction({ type: "pickup_item", unit_id: medic.id, item_id: item.id });
  });
  dropButton.addEventListener("click", () => {
    const medic = selectedMedic();
    const item = simulation.items.find(item => medic && item.type === "healing_potion" && item.carrier_id === medic.id);
    if (item && !dropButton.disabled) sendAction({ type: "drop_item", unit_id: medic.id, item_id: item.id });
  });
  healButton.addEventListener("click", () => {
    const medic = selectedMedic();
    const item = simulation.items.find(item => medic && item.type === "healing_potion" && item.carrier_id === medic.id);
    if (item && !healButton.disabled) sendAction({ type: "use_item", unit_id: medic.id, item_id: item.id, target_id: Number(healTarget.value) });
  });
  armorButton.addEventListener("click", () => {
    const soldier = selectedMedic();
    if (soldier?.armor && !armorButton.disabled) sendAction({ type: "equip_armor", unit_id: soldier.id, equipped: !soldier.armor_equipped });
  });
  gearTarget.addEventListener("change", updateControls);
  pickupEquipmentButton.addEventListener("click", () => {
    const soldier = selectedMedic();
    if (soldier && !pickupEquipmentButton.disabled) sendAction({ type: "pickup_equipment", unit_id: soldier.id, item_id: Number(gearTarget.value) });
  });
  dropWeaponButton.addEventListener("click", () => {
    const soldier = selectedMedic();
    if (soldier?.weapon && !dropWeaponButton.disabled) sendAction({ type: "drop_weapon", unit_id: soldier.id });
  });
  dropArmorButton.addEventListener("click", () => {
    const soldier = selectedMedic();
    if (soldier?.armor && !dropArmorButton.disabled) sendAction({ type: "drop_armor", unit_id: soldier.id });
  });
  pickupToolButton.addEventListener("click", () => {
    const soldier = selectedMedic();
    const tool = simulation.items.find(item => soldier && item.type === "tool" && String(item.id) === groundToolTarget.value &&
      item.carrier_id === null && item.x === soldier.x && item.y === soldier.y);
    if (tool && !pickupToolButton.disabled) sendAction({ type: "pickup_tool", unit_id: soldier.id, item_id: tool.id });
  });
  groundToolTarget.addEventListener("change", updateControls);
  dropToolButton.addEventListener("click", () => {
    const soldier = selectedMedic();
    if (soldier && !dropToolButton.disabled) sendAction({ type: "drop_tool", unit_id: soldier.id, tool_index: Number(toolTarget.value) });
  });
  watchfireTarget.addEventListener("change", updateControls);
  toggleWatchfireButton.addEventListener("click", () => {
    const soldier = selectedMedic();
    if (!soldier || toggleWatchfireButton.disabled) return;
    const [x, y] = watchfireTarget.value.split(",").map(Number);
    const out = simulation.extinguishedWatchfires.some(fire => fire.x === x && fire.y === y);
    sendAction({ type: out ? "light_watchfire" : "extinguish_watchfire", unit_id: soldier.id, x, y });
  });
  toggleTorchButton.addEventListener("click", () => {
    const soldier = selectedMedic();
    if (soldier && !toggleTorchButton.disabled) {
      sendAction({ type: "toggle_torch", unit_id: soldier.id, lit: soldier.torch_lit === false });
    }
  });
  extinguishFireButton.addEventListener("click", () => {
    const soldier = selectedMedic();
    if (!soldier || extinguishFireButton.disabled) return;
    const [x, y] = fireTarget.value.split(",").map(Number);
    sendAction({ type: "extinguish_fire", unit_id: soldier.id, x, y });
  });
  mountButton.addEventListener("click", () => {
    const soldier = selectedMedic();
    if (!soldier || mountButton.disabled) return;
    if (soldier.mount_id != null) sendAction({ type: "dismount", unit_id: soldier.id });
    else {
      const horse = simulation.horses.find(item => item.rider_id === null && item.x === soldier.x && item.y === soldier.y);
      if (horse) sendAction({ type: "mount", unit_id: soldier.id, horse_id: horse.id });
    }
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
  withdrawButton.addEventListener("click", () => {
    const unit = selectedMedic();
    if (unit && !withdrawButton.disabled) sendAction({ type: "withdraw", unit_id: unit.id });
  });
  window.addEventListener("resize", resize);
})();
