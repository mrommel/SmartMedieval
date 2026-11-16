const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

const script = fs.readFileSync(path.join(__dirname, "../static/game/game.js"), "utf8");
const rendererScript = fs.readFileSync(path.join(__dirname, "../static/game/renderer.js"), "utf8");
const inputScript = fs.readFileSync(path.join(__dirname, "../static/game/input.js"), "utf8");
const launchScript = fs.readFileSync(path.join(__dirname, "../static/game/launch.js"), "utf8");

function element() {
  const listeners = {};
  let text = "";
  return {
    hidden: false, disabled: false, value: "1", style: {}, dataset: {},
    get textContent() { return text + (this.children || []).map(child => child.textContent).join(""); },
    set textContent(value) { text = String(value); this.children = []; },
    classList: { add() {}, remove() {}, toggle() {} },
    addEventListener(type, handler) { listeners[type] = handler; },
    setAttribute(name, value) { this[name] = value; },
    querySelector() { return element(); },
    getBoundingClientRect() { return { width: 600, height: 400, left: 0, top: 0 }; },
    setPointerCapture() {}, append(...children) { this.children = [...(this.children || []), ...children]; },
    replaceChildren(...children) { text = ""; this.children = children; },
    fire(type, event = {}) { return listeners[type]?.(event); }
  };
}

function setup(savedSpeed = null, catalogFetch = null) {
  const nodes = new Map();
  const get = id => {
    if (!nodes.has(id)) nodes.set(id, element());
    return nodes.get(id);
  };
  let draws = 0;
  const ctx = new Proxy({}, { get(_, name) {
    if (name === "createLinearGradient") return () => ({ addColorStop() {} });
    if (name === "clearRect") return () => { draws++; };
    return () => {};
  } });
  get("battlefield-canvas").getContext = () => ctx;
  const storage = new Map(savedSpeed === null ? [] : [["greywatch.animationSpeed", savedSpeed]]);
  const store = {
    getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, value)
  };
  const snapshot = {
    id: 1, revision: 1, kind: "single-games", game_id: 1,
    entry: { id: 1, name: "Test battle", description: "Test" },
    map: { cols: 4, rows: 4, keep: { left: 1, right: 2, top: 1, bottom: 2 },
      gate: { x: 1, y: 2 }, objective: { x: 2, y: 2 }, startPositions: [{ x: 0, y: 0 }] },
    state: { units: [{ id: 0, x: 0, y: 0, side: "attackers", weapon: "sword", tools: [],
      rank: "recruit", morale: 3, move_points: 3, move_capacity: 4, next_move_capacity: 4,
      fight_points: 1, fight_capacity: 1, next_fight_capacity: 1,
      health: 3, max_health: 3 }], captured: false, defeated: false,
    capture_progress: 0, capture_status: "UNCLAIMED", turn: 1 }
  };
  let postCount = 0;
  const actions = [];
  let nextFrame;
  const window = {
    devicePixelRatio: 1, localStorage: store,
    confirm: () => true,
    matchMedia: () => ({ matches: false, addEventListener() {} }),
    addEventListener() {}
  };
  const document = {
    getElementById: get, createElement: element,
    querySelector: () => ({ content: "csrf" }),
    querySelectorAll: () => ["scenarios", "single-games"].map(kind => {
      const button = get(`catalog-${kind}`);
      button.dataset.catalog = kind;
      return button;
    })
  };
  const context = {
    document, window, performance: { now: () => 0 },
    requestAnimationFrame: callback => { nextFrame = callback; },
    setTimeout: () => 1, clearTimeout() {},
    fetch: async (url, options = {}) => {
      if (url === "/api/scenarios/" || url === "/api/single-games/") {
        return { ok: true, headers: { get: () => "application/json" },
          json: () => catalogFetch ? catalogFetch(url) : [] };
      }
      if (options.method === "POST") {
        postCount++;
        if (options.body) actions.push(JSON.parse(options.body).action);
      }
      return { ok: true, headers: { get: () => "application/json" }, json: async () => snapshot };
    }
  };
  vm.runInNewContext(rendererScript.replace("export function", "function") +
    "\nthis.createBattlefieldRenderer = createBattlefieldRenderer;", context);
  vm.runInNewContext(inputScript.replace("export function", "function") +
    "\nthis.createBattlefieldInput = createBattlefieldInput;", context);
  vm.runInNewContext(launchScript.replace("export function", "function") +
    "\nthis.createLaunchUI = createLaunchUI;", context);
  vm.runInNewContext(script.replace(/^import .*;\n/gm, ""), context);
  return {
    get, store, snapshot, actions, draws: () => draws, postCount: () => postCount,
    frame: time => nextFrame(time), createRenderer: context.createBattlefieldRenderer,
    createInput: context.createBattlefieldInput
  };
}

test("throne mission enables capture only for an unguarded adjacent king", async () => {
  const game = setup();
  game.snapshot.map.mission = "capture_king";
  game.snapshot.map.objective = { x: 2, y: 2 };
  game.snapshot.state.units[0].x = 2;
  game.snapshot.state.units[0].y = 3;
  game.snapshot.state.units.push({ id: 1, side: "defenders", weapon: null, is_king: true, x: 2, y: 2,
    health: 3, max_health: 3, fight_points: 1 });
  game.snapshot.state.units.push({ id: 2, side: "defenders", weapon: "sword", x: 2, y: 1,
    health: 3, max_health: 3, fight_points: 1 });
  await game.get("continue-game").fire("click");
  assert.equal(game.get("capture-king").hidden, false);
  assert.equal(game.get("capture-king").disabled, true);
  assert.equal(game.get("objective-name").textContent, "THRONE ROOM");
  assert.match(game.get("mission-help").textContent, /Killing the king loses/);
  game.snapshot.state.units.pop();
  await game.get("continue-game").fire("click");
  assert.equal(game.get("capture-king").disabled, false);
  await game.get("capture-king").fire("click");
  assert.equal(game.actions.at(-1).type, "capture");
  assert.equal(game.actions.at(-1).unit_id, 0);
});

test("renderer projects raised tiles and draws updated maps independently", () => {
  const game = setup();
  const renderer = game.createRenderer(game.get("battlefield-canvas"));
  renderer.setLayout({ width: 600, height: 400, tileW: 56, tileH: 28,
    originX: 300, originY: 100, ratio: 1 });
  renderer.setMap({ cols: 4, rows: 4, keep: { left: 1, right: 2, top: 1, bottom: 2 },
    gate: { x: 1, y: 2 }, objective: { x: 2, y: 2 },
    elevation: [{ x: 0, y: 1, height: 1, access: "ramp" }],
    objects: [{ x: 3, y: 1, type: "tree" }] });
  assert.equal(renderer.tileHeight(0, 1), 1);
  assert.equal(renderer.project(0, 1).y, 86);
  assert.equal(renderer.isWall(2, 1), true);
  assert.equal(renderer.isWall(1, 2), false);
  renderer.draw(0, { simulation: { units: [], selected: new Set(), captured: false },
    camera: { x: 0, y: 0, zoom: 1 }, cursor: { visible: false },
    hasAttackOption: () => false });
  assert.equal(game.draws(), 1);
  renderer.setMap({ cols: 4, rows: 4, keep: { left: 1, right: 2, top: 1, bottom: 2 },
    gate: { x: 1, y: 2 }, objective: { x: 2, y: 2 } });
  assert.equal(renderer.project(0, 1).y, 114);
  renderer.draw(0, { simulation: { units: [], selected: new Set(), captured: false },
    camera: { x: 0, y: 0, zoom: 1 }, cursor: { visible: false },
    hasAttackOption: () => false });
  assert.equal(game.draws(), 2);
});

test("renderer draws village structures and clears house footprints when the map changes", () => {
  const game = setup();
  const renderer = game.createRenderer(game.get("battlefield-canvas"));
  renderer.setLayout({ width: 600, height: 400, tileW: 56, tileH: 28,
    originX: 300, originY: 100, ratio: 1 });
  const base = { cols: 5, rows: 5, keep: { left: 2, right: 4, top: 2, bottom: 4 },
    gate: { x: 2, y: 3 }, objective: { x: 3, y: 3 } };
  renderer.setMap({ ...base, houses: [{ left: 0, right: 1, top: 0, bottom: 1 }],
    lanes: [{ x: 0, y: 3 }], objects: [{ x: 1, y: 3, type: "fence" },
      { x: 1, y: 4, type: "well" }] });
  assert.equal(renderer.isHouse(1, 1), true);
  assert.equal(renderer.isHouse(2, 1), false);
  renderer.draw(0, { simulation: { units: [], selected: new Set(), captured: false },
    camera: { x: 0, y: 0, zoom: 1 }, cursor: { visible: false },
    hasAttackOption: () => false });
  assert.equal(game.draws(), 1);
  renderer.setMap(base);
  assert.equal(renderer.isHouse(1, 1), false);
});

test("enterable houses render as cutaway floors and pick tiles at ground level", () => {
  const game = setup();
  const canvas = game.get("battlefield-canvas");
  const renderer = game.createRenderer(canvas);
  const layout = { width: 600, height: 400, tileW: 56, tileH: 28,
    originX: 300, originY: 100, ratio: 1 };
  const map = { cols: 6, rows: 6, keep: { left: 4, right: 5, top: 3, bottom: 5 },
    gate: { x: 4, y: 4 }, objective: { x: 5, y: 4 },
    houses: [{ left: 2, right: 3, top: 2, bottom: 3, door: { x: 2, y: 3 } }] };
  renderer.setMap(map);
  renderer.setLayout(layout);
  assert.equal(renderer.isEnterableHouse(3, 2), true);
  assert.equal(renderer.isHouseDoor(2, 3), true);
  renderer.draw(0, { simulation: { units: [{ id: 1, x: 3, y: 2, health: 3,
    max_health: 3, weapon: "sword", side: "attackers" }], selected: new Set(), captured: false },
    camera: { x: 0, y: 0, zoom: 1 }, cursor: { visible: false }, hasAttackOption: () => false });
  assert.equal(game.draws(), 1);
  let ordered;
  game.createInput({ canvas, renderer, simulation: { units: [], selected: new Set() },
    getMap: () => map, getLayout: () => layout, canOrder: () => true,
    isWalkable: () => true, isAiming: () => false, onAim() {},
    onMove: (x, y) => { ordered = { x, y }; }, onAttack() {}, onSelection() {},
    onBlocked() {}, onDraw() {}, onCursor() {} });
  const floor = renderer.project(2, 3);
  const event = { button: 0, pointerId: 1, clientX: floor.x, clientY: floor.y + layout.tileH / 2 };
  canvas.fire("pointerdown", event);
  canvas.fire("pointerup", event);
  assert.deepEqual(ordered, { x: 2, y: 3 });
  renderer.setMap({ ...map, houses: [] });
  assert.equal(renderer.isEnterableHouse(3, 2), false);
  assert.equal(renderer.isHouseDoor(2, 3), false);
});

test("keyboard can issue orders to a house door and interior", async () => {
  const game = setup();
  game.snapshot.map = { cols: 8, rows: 8,
    keep: { left: 4, right: 7, top: 4, bottom: 7 }, gate: { x: 5, y: 7 },
    objective: { x: 5, y: 5 }, startPositions: [{ x: 0, y: 2 }],
    houses: [{ left: 1, right: 2, top: 2, bottom: 3, door: { x: 1, y: 2 } }] };
  game.snapshot.state.units[0].y = 2;
  await game.get("continue-game").fire("click");
  const canvas = game.get("battlefield-canvas");
  canvas.fire("focus");
  canvas.fire("keydown", { key: "ArrowRight", preventDefault() {} });
  assert.match(game.get("cursor-status").textContent, /house door/);
  canvas.fire("keydown", { key: "Enter", preventDefault() {} });
  assert.equal(game.actions.at(-1).x, 1);
  await new Promise(setImmediate);
  canvas.fire("keydown", { key: "ArrowRight", preventDefault() {} });
  assert.match(game.get("cursor-status").textContent, /house interior/);
  canvas.fire("keydown", { key: "Enter", preventDefault() {} });
  assert.equal(game.actions.at(-1).x, 2);
});

test("combat previews allow doorway melee but not shots or melee through house walls", async () => {
  for (const [weapon, y, expected] of [
    ["sword", 2, "attack"], ["sword", 3, null], ["longbow", 2, null]
  ]) {
    const game = setup();
    game.snapshot.map.houses = [{ left: 1, right: 2, top: 2, bottom: 3,
      door: { x: 1, y: 2 } }];
    game.snapshot.map.startPositions = [{ x: 0, y }];
    game.snapshot.state.units[0].x = 0;
    game.snapshot.state.units[0].y = y;
    game.snapshot.state.units[0].weapon = weapon;
    game.snapshot.state.units.push({ ...game.snapshot.state.units[0],
      id: 1, x: 1, side: "defenders", weapon: "sword" });
    await game.get("continue-game").fire("click");
    const canvas = game.get("battlefield-canvas");
    canvas.fire("focus");
    canvas.fire("keydown", { key: "ArrowRight", preventDefault() {} });
    canvas.fire("keydown", { key: "Enter", preventDefault() {} });
    assert.equal(game.actions.at(-1)?.type ?? null, expected, `${weapon} at row ${y}`);
  }
});

test("clicking a house roof picks its footprint rather than ground behind it", () => {
  const game = setup();
  const canvas = game.get("battlefield-canvas");
  const renderer = game.createRenderer(canvas);
  const layout = { width: 600, height: 400, tileW: 56, tileH: 28,
    originX: 300, originY: 100, ratio: 1 };
  const map = { cols: 6, rows: 6, keep: { left: 4, right: 5, top: 3, bottom: 5 },
    gate: { x: 4, y: 4 }, objective: { x: 5, y: 4 },
    houses: [{ left: 2, right: 3, top: 2, bottom: 3 }] };
  renderer.setMap(map);
  renderer.setLayout(layout);
  let ordered;
  game.createInput({ canvas, renderer, simulation: { units: [], selected: new Set() },
    getMap: () => map, getLayout: () => layout, canOrder: () => true,
    isWalkable: () => true, isAiming: () => false, onAim() {},
    onMove: (x, y) => { ordered = { x, y }; }, onAttack() {}, onSelection() {},
    onBlocked() {}, onDraw() {}, onCursor() {} });
  const roof = renderer.project(2, 2);
  const event = { button: 0, pointerId: 1, clientX: roof.x, clientY: roof.y - layout.tileH * .85 };
  canvas.fire("pointerdown", event);
  canvas.fire("pointerup", event);
  assert.deepEqual(ordered, { x: 2, y: 2 });
});

test("keyboard shooting passes fences but not wells or houses; houses block orders", async () => {
  for (const obstacle of ["fence", "well", "house"]) {
    const game = setup();
    game.snapshot.state.units[0].weapon = "longbow";
    game.snapshot.state.units.push({ ...game.snapshot.state.units[0],
      id: 1, x: obstacle === "house" ? 3 : 2, y: 0, side: "defenders", weapon: "sword" });
    if (obstacle === "house") game.snapshot.map.houses = [{ left: 1, right: 2, top: 0, bottom: 1 }];
    else game.snapshot.map.objects = [{ x: 1, y: 0, type: obstacle }];
    await game.get("continue-game").fire("click");
    const canvas = game.get("battlefield-canvas");
    const key = name => canvas.fire("keydown", { key: name, shiftKey: false, preventDefault() {} });
    canvas.fire("focus");
    key("ArrowRight"); key("ArrowRight");
    if (obstacle === "house") key("ArrowRight");
    key("Enter");
    assert.equal(game.actions.length, obstacle === "fence" ? 1 : 0, obstacle);
    if (obstacle === "fence") assert.equal(game.actions[0].type, "ranged_attack");
    if (obstacle === "house") {
      key("ArrowLeft"); key("ArrowLeft"); key("Enter");
      assert.equal(game.actions.length, 0, "house tiles are not movement destinations");
      assert.match(game.get("cursor-status").textContent, /house/);
    }
  }
});

test("renderer draws additional strongpoints and respects each gate after map changes", () => {
  const game = setup();
  const renderer = game.createRenderer(game.get("battlefield-canvas"));
  renderer.setLayout({ width: 600, height: 400, tileW: 56, tileH: 28,
    originX: 300, originY: 100, ratio: 1 });
  const base = { cols: 12, rows: 10, keep: { left: 7, right: 10, top: 2, bottom: 7 },
    gate: { x: 8, y: 7 }, objective: { x: 8, y: 5 } };
  renderer.setMap({ ...base, strongpoints: [
    { left: 1, right: 4, top: 1, bottom: 4, gate: { x: 2, y: 4 } },
    { left: 1, right: 4, top: 6, bottom: 9, gate: { x: 2, y: 6 } }
  ] });
  assert.equal(renderer.isWall(1, 2), true);
  assert.equal(renderer.isWall(2, 4), false);
  assert.equal(renderer.isWall(2, 6), false);
  assert.equal(renderer.isWall(8, 7), false);
  renderer.draw(0, { simulation: { units: [], selected: new Set(), captured: false },
    camera: { x: 0, y: 0, zoom: 1 }, cursor: { visible: false },
    hasAttackOption: () => false });
  assert.equal(game.draws(), 1);
  renderer.setMap(base);
  assert.equal(renderer.isWall(1, 2), false);
});

test("pointer orders still pick the raised surface rather than its ground tile", async () => {
  const game = setup();
  game.snapshot.map.elevation = [{ x: 0, y: 1, height: 1, access: "ramp" }];
  await game.get("continue-game").fire("click");
  const canvas = game.get("battlefield-canvas");
  const event = { button: 0, pointerId: 1, clientX: 268, clientY: 187.2 };
  canvas.fire("pointerdown", event);
  canvas.fire("pointerup", event);
  assert.equal(game.actions.at(-1).type, "move");
  assert.equal(game.actions.at(-1).x, 0);
  assert.equal(game.actions.at(-1).y, 1);
});

test("dragging pans without ordering; clicking after a drag still orders", async () => {
  const game = setup();
  await game.get("continue-game").fire("click");
  const canvas = game.get("battlefield-canvas");
  const down = { button: 0, pointerId: 1, clientX: 268, clientY: 219.2 };
  canvas.fire("pointerdown", down);
  canvas.fire("pointermove", { ...down, clientX: 340 });
  canvas.fire("pointerup", { ...down, clientX: 340 });
  assert.equal(game.actions.length, 0);
  canvas.fire("pointerdown", { ...down, clientX: 308 });
  canvas.fire("pointerup", { ...down, clientX: 308 });
  assert.equal(game.actions.length, 1);
  assert.equal(game.actions[0].type, "move");
});

test("catalog navigation renders linked games and starts a selected scenario", async () => {
  const game = setup(null, () => [{ id: 8, name: "Siege", description: "Hold fast",
    games: [{ id: 3, name: "Gate", description: "Break through" }] }]);
  game.get("play-game").fire("click");
  assert.equal(game.get("main-menu").hidden, false);
  await game.get("catalog-scenarios").fire("click");
  const group = game.get("catalog-list").children[0];
  assert.equal(group.children[0].textContent, "Siege");
  await group.children[2].fire("click");
  assert.equal(game.get("game-screen").hidden, false);
  assert.equal(game.get("game-title").textContent, "Test battle");
  assert.equal(game.postCount(), 1);
  game.get("main-menu-button").fire("click");
  assert.equal(game.get("game-screen").hidden, true);
});

test("a slow catalog response cannot overwrite a newer catalog", async () => {
  let resolveScenarios;
  const game = setup(null, url => url === "/api/scenarios/"
    ? new Promise(resolve => { resolveScenarios = resolve; })
    : [{ id: 1, name: "Solo", description: "One battle" }]);
  game.get("play-game").fire("click");
  const slow = game.get("catalog-scenarios").fire("click");
  await game.get("catalog-single-games").fire("click");
  resolveScenarios([{ id: 2, name: "Old", description: "Stale", games: [] }]);
  await slow;
  assert.equal(game.get("catalog-title").textContent, "Single games");
  assert.equal(game.get("catalog-list").children[0].children[0].textContent, "Solo");
});

test("pause blocks orders and freezes the animation clock until resumed", async () => {
  const game = setup();
  await game.get("continue-game").fire("click");
  game.frame(0);
  game.frame(16);
  const beforePause = game.draws();
  assert.ok(beforePause > 0);

  game.get("pause-game").fire("click");
  assert.equal(game.get("pause-game")["aria-pressed"], "true");
  assert.equal(game.get("pause-indicator").hidden, false);
  assert.equal(game.get("end-turn").disabled, true);
  const pausedDraws = game.draws();
  game.frame(1000);
  assert.equal(game.draws(), pausedDraws);
  await game.get("end-turn").fire("click");
  assert.equal(game.postCount(), 0);

  game.get("pause-game").fire("click");
  game.frame(1016);
  assert.ok(game.draws() > pausedDraws);
  await game.get("end-turn").fire("click");
  assert.equal(game.postCount(), 1);
});

test("speed persists, restores, and off disables per-frame drawing", async () => {
  const game = setup("0.5");
  assert.equal(game.get("animation-speed").value, "0.5");
  await game.get("continue-game").fire("click");
  game.frame(0);
  game.get("animation-speed").value = "0";
  game.get("animation-speed").fire("change");
  assert.equal(game.store.getItem("greywatch.animationSpeed"), "0");
  const count = game.draws();
  game.frame(16);
  assert.equal(game.draws(), count);
  assert.equal(setup("0").get("animation-speed").value, "0");
});

test("combat history renders on resume and updates after an action", async () => {
  const game = setup();
  game.snapshot.state.history = [{ turn: 1, type: "promote", actor_id: 0,
    actor_side: "attackers", actor_type: "vanguard", morale_change: -2 }];
  await game.get("continue-game").fire("click");
  const list = game.get("combat-history-list");
  assert.match(list.children[0].textContent, /Turn 1.*promoted to veteran/);
  game.snapshot.state.history.push({ turn: 2, type: "ranged_attack", actor_id: 1,
    actor_side: "defenders", actor_type: "longbow", target_id: 0,
    target_side: "attackers", target_type: "vanguard", damage: 1, killed: true,
    morale_changes: [{ unit_id: 1, change: 1 }] });
  await game.get("end-turn").fire("click");
  assert.equal(list.children.length, 2);
  assert.match(list.children[1].textContent, /Turn 2.*shot attacker #1 for 1 damage \(fallen\).*Morale: #2 \+1/);
  game.snapshot.state.history.push({ turn: 3, type: "ranged_attack", actor_id: 1,
    actor_side: "defenders", actor_type: "longbow", target_id: 0,
    target_side: "attackers", target_type: "vanguard", damage: 0, killed: false,
    cover: "wall", morale_changes: [] });
  await game.get("end-turn").fire("click");
  assert.match(list.children[2].textContent, /0 damage \(wall cover blocked the shot\)/);
});

test("selected soldier displays remaining stats and carried equipment after actions", async () => {
  const game = setup();
  game.snapshot.state.units[0].tools = ["rope"];
  await game.get("continue-game").fire("click");
  const panel = game.get("selected-stats");
  const row = label => panel.children.find(child =>
    child.children?.[0]?.children?.[0]?.textContent === label || child.children?.[0]?.textContent === label);
  assert.equal(row("Health").children[0].children[1].textContent, "3/3 HP");
  assert.equal(row("Morale").children[0].children[1].textContent, "3/5");
  assert.equal(row("Movement").children[0].children[1].textContent, "3/4 MP left");
  assert.equal(row("Movement").children[1].children[0].style.width, "75%");
  assert.equal(row("Fight").children[0].children[1].textContent, "1/1 FP left");
  assert.equal(row("Weapon").children[1].textContent, "sword");
  assert.equal(row("Tools").children[1].textContent, "rope");
  game.snapshot.state.units[0].health = 1;
  game.snapshot.state.units[0].morale = 5;
  game.snapshot.state.units[0].move_points = 0;
  game.snapshot.state.units[0].fight_points = 0;
  await game.get("end-turn").fire("click");
  assert.equal(row("Health").children[0].children[1].textContent, "1/3 HP");
  assert.equal(row("Morale").children[0].children[1].textContent, "5/5");
  assert.equal(row("Movement").children[0].children[1].textContent, "0/4 MP left");
  assert.equal(row("Movement").children[1].children[0].style.width, "0%");
  assert.equal(row("Fight").children[0].children[1].textContent, "0/1 FP left");
});

test("selected panel separates turn capacity from future morale and rank bonuses", async () => {
  const game = setup();
  const soldier = game.snapshot.state.units[0];
  soldier.morale = 5;
  soldier.move_points = 1;
  soldier.fight_points = 0;
  soldier.next_move_capacity = 5;
  await game.get("continue-game").fire("click");
  const panel = game.get("selected-stats");
  const stat = label => panel.children.find(child => child.children?.[0]?.children?.[0]?.textContent === label);
  assert.equal(stat("Movement").children[0].children[1].textContent, "1/4 MP left");
  assert.equal(stat("Movement").children[1].children[0].style.width, "25%");
  assert.equal(panel.children.find(child => child.className === "next-turn-preview").textContent,
    "Projected next turn: 5 MP · 1 FP (at current morale and rank)");
  soldier.morale = 3;
  soldier.rank = "veteran";
  soldier.next_fight_capacity = 2;
  await game.get("promote").fire("click");
  await new Promise(setImmediate);
  assert.equal(stat("Fight").children[0].children[1].textContent, "0/1 FP left");
  assert.equal(panel.children.find(child => child.className === "next-turn-preview").textContent,
    "Projected next turn: 5 MP · 2 FP (at current morale and rank)");
});

test("selection changes, casualties and resume clear stale readouts", async () => {
  const game = setup();
  game.snapshot.state.units.push({ ...game.snapshot.state.units[0], id: 1, y: 1 });
  await game.get("continue-game").fire("click");
  const canvas = game.get("battlefield-canvas");
  const key = (name, shiftKey = false) => canvas.fire("keydown", { key: name, shiftKey, preventDefault() {} });
  canvas.fire("focus");
  key("Enter", true);
  assert.match(game.get("selected-stats").textContent, /Select a soldier to inspect/);
  assert.equal(game.get("selected-stats").children.length, 0);
  key("Enter");
  key("ArrowDown");
  key("Enter", true);
  assert.match(game.get("selected-stats").textContent, /2 soldiers selected/);
  key("Enter");
  assert.match(game.get("selected-stats").textContent, /Soldier #2/);
  game.snapshot.state.units.pop();
  await game.get("end-turn").fire("click");
  assert.match(game.get("selected-stats").textContent, /Select a soldier to inspect/);
  await game.get("continue-game").fire("click");
  assert.match(game.get("selected-stats").textContent, /Select a soldier to inspect/);
});

test("ranged reload and older saves without turn capacities remain readable", async () => {
  const game = setup();
  const soldier = game.snapshot.state.units[0];
  soldier.weapon = "crossbow";
  soldier.reload_turns = 2;
  delete soldier.move_capacity;
  delete soldier.fight_capacity;
  await game.get("continue-game").fire("click");
  const panel = game.get("selected-stats");
  const stat = label => panel.children.find(child => child.children?.[0]?.children?.[0]?.textContent === label);
  assert.equal(stat("Movement").children[0].children[1].textContent, "3 MP left");
  assert.equal(stat("Movement").children.length, 1, "do not invent a current-turn maximum for an old save");
  assert.equal(panel.children.at(-1).children[1].textContent, "2 turn(s) left");
  soldier.reload_turns = 0;
  soldier.move_capacity = 4;
  soldier.fight_capacity = 1;
  await game.get("continue-game").fire("click");
  assert.equal(panel.children.at(-1).children[1].textContent, "Ready");
  assert.equal(stat("Movement").children[1].children[0].style.width, "75%");
});

test("keyboard cursor selects groups, moves, attacks, and cannot order while paused", async () => {
  const game = setup();
  game.snapshot.state.units.push(
    { ...game.snapshot.state.units[0], id: 1, x: 0, y: 1 },
    { ...game.snapshot.state.units[0], id: 2, side: "defenders", x: 1, y: 0 }
  );
  await game.get("continue-game").fire("click");
  const canvas = game.get("battlefield-canvas");
  const key = (name, shiftKey = false) => {
    let prevented = false;
    canvas.fire("keydown", { key: name, shiftKey, preventDefault() { prevented = true; } });
    assert.ok(prevented, `${name} should not scroll or activate another control`);
  };
  canvas.fire("focus");
  assert.match(game.get("cursor-status").textContent, /Tile 1, 1: friendly with sword #1, selected/);
  key("ArrowDown");
  key("Enter", true);
  assert.match(game.get("selected-stats").textContent, /2 soldiers selected/);
  key(" ", true);
  assert.match(game.get("selected-stats").textContent, /Soldier #1 · recruit/);
  key("ArrowDown");
  assert.match(game.get("cursor-status").textContent, /Tile 1, 3: open ground/);
  key("Enter");
  assert.equal(game.actions.at(-1).type, "move");
  assert.equal(game.actions.at(-1).y, 2);
  await new Promise(setImmediate);
  key("ArrowUp");
  key("ArrowUp");
  key("ArrowRight");
  assert.match(game.get("cursor-status").textContent, /defender with sword/);
  key("Enter");
  assert.equal(game.actions.at(-1).type, "attack");
  assert.equal(game.actions.at(-1).target_id, 2);
  await new Promise(setImmediate);
  key("ArrowDown");
  assert.match(game.get("cursor-status").textContent, /Tile 2, 2: wall/);
  key("Enter");
  assert.equal(game.actions.length, 2);
  game.get("pause-game").fire("click");
  key("Enter");
  assert.equal(game.actions.length, 2);
});

test("trees and rocks are described and reject keyboard movement orders", async () => {
  const game = setup();
  game.snapshot.map.objects = [{ x: 1, y: 0, type: "tree" }, { x: 1, y: 1, type: "rock" }];
  await game.get("continue-game").fire("click");
  const canvas = game.get("battlefield-canvas");
  canvas.fire("focus");
  canvas.fire("keydown", { key: "ArrowRight", preventDefault() {} });
  assert.match(game.get("cursor-status").textContent, /tree/);
  canvas.fire("keydown", { key: "Enter", preventDefault() {} });
  canvas.fire("keydown", { key: "ArrowDown", preventDefault() {} });
  assert.match(game.get("cursor-status").textContent, /rock/);
  canvas.fire("keydown", { key: "Enter", preventDefault() {} });
  assert.equal(game.actions.length, 0);
});

test("catapult crew can aim at walls using the keyboard and fire when ready", async () => {
  const game = setup();
  game.snapshot.map.catapults = [{ x: 0, y: 0 }];
  game.snapshot.state.catapults = [{ id: 0, x: 0, y: 0, ammo: 3,
    reload_turns: 0, aim: null }];
  await game.get("continue-game").fire("click");
  assert.equal(game.get("aim-catapult").hidden, false);
  assert.equal(game.get("aim-catapult").disabled, false);
  assert.equal(game.get("fire-catapult").disabled, true);
  assert.equal(game.get("selected-stats").children.at(-1).children[1].textContent, "3 stones");
  game.get("aim-catapult").fire("click");
  const canvas = game.get("battlefield-canvas");
  for (const key of ["ArrowRight", "ArrowRight", "ArrowDown", "Enter"]) {
    canvas.fire("keydown", { key, preventDefault() {} });
  }
  assert.equal(game.actions.at(-1).type, "aim_catapult");
  assert.equal(game.actions.at(-1).x, 2);
  assert.equal(game.actions.at(-1).y, 1);
  await new Promise(setImmediate);
  game.snapshot.state.catapults[0].aim = { x: 2, y: 1 };
  await game.get("end-turn").fire("click");
  assert.equal(game.get("fire-catapult").disabled, false);
  await game.get("fire-catapult").fire("click");
  assert.equal(game.actions.at(-1).type, "fire_catapult");
  assert.equal(game.actions.at(-1).catapult_id, 0);
  assert.equal(game.actions.at(-1).unit_id, 0);
  await new Promise(setImmediate);
  game.snapshot.state.breaches = [{ x: 2, y: 1 }];
  await game.get("end-turn").fire("click");
  assert.match(game.get("cursor-status").textContent, /open ground/);
});

test("potions appear on the map and enable pickup, drop, and allied healing", async () => {
  const game = setup();
  game.snapshot.map.items = [{ x: 0, y: 0, type: "healing_potion" }];
  game.snapshot.state.items = [{ id: 0, x: 0, y: 0, type: "healing_potion", carrier_id: null }];
  game.snapshot.state.units.push({ ...game.snapshot.state.units[0], id: 1, x: 1, health: 1 });
  await game.get("continue-game").fire("click");
  assert.equal(game.get("pickup-potion").hidden, false);
  assert.equal(game.get("pickup-potion").disabled, false);
  assert.equal(game.get("heal-potion").disabled, true);
  assert.match(game.get("cursor-status").textContent, /healing potion on ground/);
  await game.get("pickup-potion").fire("click");
  assert.equal(game.actions.at(-1).type, "pickup_item");
  await new Promise(setImmediate);
  game.snapshot.state.items[0].carrier_id = 0;
  game.snapshot.state.items[0].x = game.snapshot.state.items[0].y = null;
  game.snapshot.state.history = [{ turn: 1, type: "pickup_item", actor_id: 0,
    actor_side: "attackers", actor_type: "vanguard", item_id: 0 }];
  await game.get("continue-game").fire("click");
  assert.equal(game.get("selected-stats").children.find(child => child.children?.[0]?.textContent === "Potions").children[1].textContent, "1/2");
  assert.equal(game.get("drop-potion").disabled, false);
  assert.equal(game.get("heal-potion").disabled, false);
  assert.equal(game.get("heal-target").children[0].value, "1");
  assert.match(game.get("combat-history-list").children[0].textContent, /picked up a healing potion/);
  game.get("heal-target").value = "1";
  await game.get("heal-potion").fire("click");
  assert.equal(game.actions.at(-1).type, "use_item");
  assert.equal(game.actions.at(-1).target_id, 1);
  await new Promise(setImmediate);
  await game.get("drop-potion").fire("click");
  assert.equal(game.actions.at(-1).type, "drop_item");
});
