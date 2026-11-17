const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

const script = fs.readFileSync(path.join(__dirname, "../static/game/game.js"), "utf8");
const rendererScript = fs.readFileSync(path.join(__dirname, "../static/game/renderer.js"), "utf8");
const inputScript = fs.readFileSync(path.join(__dirname, "../static/game/input.js"), "utf8");
const launchScript = fs.readFileSync(path.join(__dirname, "../static/game/launch.js"), "utf8");
const previewScript = fs.readFileSync(path.join(__dirname, "../static/game/path_preview.js"), "utf8");
const previewContext = {};
vm.runInNewContext(previewScript.replace("export function", "function") +
  "\nthis.previewMovement = previewMovement;", previewContext);
const previewMovement = previewContext.previewMovement;

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
  const fogFills = [];
  const gearPaints = [];
  const ctx = new Proxy({}, { get(_, name) {
    if (name === "createLinearGradient") return () => ({ addColorStop() {} });
    if (name === "clearRect") return () => { draws++; };
    return () => {};
  }, set(_, name, value) {
    if (name === "fillStyle" && typeof value === "string") {
      if (value.startsWith("rgba(12,21,30,")) fogFills.push(value);
      if (["#9baeb3", "#d2ac70", "#a4c499"].includes(value)) gearPaints.push(value);
    }
    return true;
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
  vm.runInNewContext(previewScript.replace("export function", "function") +
    "\nthis.previewMovement = previewMovement;", context);
  vm.runInNewContext(script.replace(/^import .*;\n/gm, ""), context);
  return {
    get, store, snapshot, actions, fogFills, gearPaints, draws: () => draws, postCount: () => postCount,
    frame: time => nextFrame(time), createRenderer: context.createBattlefieldRenderer,
    createInput: context.createBattlefieldInput
  };
}

test("exit withdrawal sends the selected soldier and debriefs evacuated gear", async () => {
  const game = setup();
  game.snapshot.map.exit = { x: 0, y: 0 };
  await game.get("continue-game").fire("click");
  const button = game.get("withdraw-unit");
  assert.equal(button.hidden, false);
  assert.equal(button.disabled, false);
  await button.fire("click");
  assert.equal(JSON.stringify(game.actions.at(-1)), JSON.stringify({ type: "withdraw", unit_id: 0 }));
  game.snapshot.state.withdrawn = [{ id: 0, weapon: "sword", armor: "leather", tools: ["rope"],
    items: [{ type: "healing_potion" }] }];
  game.snapshot.state.units = [];
  game.snapshot.state.captured = true;
  game.snapshot.state.capture_status = "WITHDRAWN";
  await game.get("continue-game").fire("click");
  assert.equal(button.disabled, true);
  assert.match(game.get("mission-debrief").textContent, /1 withdrawn, 0 fallen, 0 still on the field/);
  assert.match(game.get("mission-debrief").textContent, /4 carried items and pieces/);
  assert.equal(game.get("victory").hidden, false);
});

test("crouch costs a fight point and shows its movement and ranged-defense trade-off", async () => {
  const game = setup();
  await game.get("continue-game").fire("click");
  const button = game.get("crouch");
  assert.equal(button.disabled, false);
  await button.fire("click");
  assert.equal(game.actions.at(-1).type, "crouch");
  assert.equal(game.actions.at(-1).unit_id, 0);
  game.snapshot.state.units[0].crouched = true;
  game.snapshot.state.units[0].fight_points = 0;
  game.snapshot.state.units[0].move_points = 0;
  await game.get("continue-game").fire("click");
  assert.equal(button.disabled, true);
  assert.equal(button["aria-pressed"], "true");
  assert.match(game.get("selected-stats").textContent, /−1 incoming ranged damage/);
});

test("shield tool enables a sight-limited defensive stance and can be lowered freely", async () => {
  const game = setup();
  await game.get("continue-game").fire("click");
  const button = game.get("raise-shield");
  assert.equal(button.hidden, true);
  game.snapshot.state.units[0].tools = ["shield"];
  await game.get("continue-game").fire("click");
  assert.equal(button.hidden, false);
  assert.equal(button.disabled, false);
  await button.fire("click");
  assert.equal(JSON.stringify(game.actions.at(-1)), JSON.stringify({ type: "raise_shield", unit_id: 0, raised: true }));
  game.snapshot.state.units[0].shield_raised = true;
  game.snapshot.state.units[0].fight_points = 0;
  game.snapshot.state.units[0].move_points = 2;
  await game.get("continue-game").fire("click");
  assert.equal(button.disabled, false);
  assert.equal(button["aria-pressed"], "true");
  assert.match(game.get("selected-stats").textContent, /sight reduced/);
  assert.equal(game.get("crouch").disabled, true);
  await button.fire("click");
  assert.equal(JSON.stringify(game.actions.at(-1)), JSON.stringify({ type: "raise_shield", unit_id: 0, raised: false }));
});

test("reaction control reserves a fight point and shows the selected soldier's reservation", async () => {
  const game = setup();
  await game.get("continue-game").fire("click");
  const button = game.get("reserve-reaction");
  assert.equal(button.disabled, false);
  assert.equal(button["aria-pressed"], "false");
  await button.fire("click");
  assert.equal(game.actions.at(-1).type, "reserve_reaction");
  assert.equal(game.actions.at(-1).unit_id, 0);
  assert.equal(game.actions.at(-1).reserved, true);
  game.snapshot.state.units[0].reaction_reserved = true;
  game.snapshot.state.units[0].fight_points = 0;
  await game.get("continue-game").fire("click");
  assert.equal(button["aria-pressed"], "true");
  assert.match(game.get("selected-stats").textContent, /1 FP reserved/);
  await button.fire("click");
  assert.equal(game.actions.at(-1).reserved, false);
});

test("nearby watchfire controls extinguish and relight saved fires", async () => {
  const game = setup();
  game.snapshot.map.night = true;
  game.snapshot.map.fog_of_war = true;
  game.snapshot.map.watchfires = [{ x: 1, y: 0 }];
  game.snapshot.state.units[0].z = 0;
  await game.get("continue-game").fire("click");
  const button = game.get("toggle-watchfire");
  assert.equal(button.hidden, false);
  assert.equal(button.disabled, false);
  assert.match(button.textContent, /Extinguish/);
  await button.fire("click");
  assert.equal(JSON.stringify(game.actions.at(-1)),
    JSON.stringify({ type: "extinguish_watchfire", unit_id: 0, x: 1, y: 0 }));
  game.snapshot.state.extinguished_watchfires = [{ x: 1, y: 0 }];
  await game.get("continue-game").fire("click");
  assert.match(button.textContent, /Light/);
  await button.fire("click");
  assert.equal(game.actions.at(-1).type, "light_watchfire");
  game.snapshot.state.units[0].fight_points = 0;
  await game.get("continue-game").fire("click");
  assert.equal(button.disabled, true);
});

test("torch control changes light without dropping the tool", async () => {
  const game = setup();
  game.snapshot.map.night = true;
  game.snapshot.map.fog_of_war = true;
  game.snapshot.state.units[0].tools = ["torch"];
  await game.get("continue-game").fire("click");
  const button = game.get("toggle-torch");
  assert.equal(button.hidden, false);
  assert.equal(button.disabled, false);
  assert.equal(button["aria-pressed"], "true");
  assert.match(game.get("selected-stats").textContent, /torch \(lit\)/);
  await button.fire("click");
  assert.equal(JSON.stringify(game.actions.at(-1)),
    JSON.stringify({ type: "toggle_torch", unit_id: 0, lit: false }));
  game.snapshot.state.units[0].torch_lit = false;
  await game.get("continue-game").fire("click");
  assert.equal(button["aria-pressed"], "false");
  assert.match(game.get("selected-stats").textContent, /torch \(unlit\)/);
  await button.fire("click");
  assert.equal(game.actions.at(-1).lit, true);
  game.snapshot.state.units[0].fight_points = 0;
  await game.get("continue-game").fire("click");
  assert.equal(button.disabled, true);
  game.snapshot.state.units[0].tools = [];
  await game.get("continue-game").fire("click");
  assert.equal(button.hidden, true);
});

test("movement reservation control shows reserved MP and allows cancellation", async () => {
  const game = setup();
  await game.get("continue-game").fire("click");
  const button = game.get("reserve-movement");
  assert.equal(button.disabled, false);
  assert.match(button.textContent, /3 MP/);
  await button.fire("click");
  assert.equal(game.actions.at(-1).type, "reserve_movement");
  assert.equal(game.actions.at(-1).reserved, true);
  game.snapshot.state.units[0].move_reserved = 3;
  game.snapshot.state.units[0].move_points = 0;
  await game.get("continue-game").fire("click");
  assert.equal(button["aria-pressed"], "true");
  assert.match(game.get("selected-stats").textContent, /3 MP held/);
  await button.fire("click");
  assert.equal(game.actions.at(-1).reserved, false);
});

test("fog shrouds unseen tiles and does not report lost contact as a casualty", async () => {
  const game = setup();
  game.snapshot.map.fog_of_war = true;
  game.snapshot.map.has_items = true;
  game.snapshot.map.objects = [{ x: 1, y: 0, type: "tree" }];
  game.snapshot.state.visible = [{ x: 0, y: 0 }];
  game.snapshot.state.explored = [{ x: 0, y: 0 }, { x: 1, y: 0 }];
  await game.get("continue-game").fire("click");
  assert.equal(game.get("enemy-count").textContent, "0 IN SIGHT");
  assert.equal(game.get("pickup-potion").hidden, false);
  assert.ok(game.fogFills.length > 0);
  const canvas = game.get("battlefield-canvas");
  canvas.fire("focus");
  canvas.fire("keydown", { key: "ArrowRight", preventDefault() {} });
  assert.match(game.get("cursor-status").textContent, /out of sight/);
  assert.doesNotMatch(game.get("cursor-status").textContent, /tree/);
  game.snapshot.state.visible.push({ x: 0, y: 1 });
  game.snapshot.state.units.push({ id: 1, side: "defenders", weapon: "sword", x: 0, y: 1,
    health: 3, max_health: 3, fight_points: 1 });
  await game.get("continue-game").fire("click");
  assert.equal(game.get("enemy-count").textContent, "1 IN SIGHT");
  game.snapshot.state.visible.pop();
  game.snapshot.state.units.pop();
  await game.get("end-turn").fire("click");
  assert.equal(game.get("enemy-count").textContent, "0 IN SIGHT");
  assert.doesNotMatch(game.get("toast").textContent, /fallen|damage to defenders/);
});

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

test("route preview uses server neighbor order, occupancy, breaches, and turn costs", () => {
  const map = { cols: 8, rows: 8, keep: { left: 5, right: 7, top: 5, bottom: 7 },
    gate: { x: 6, y: 7 }, objective: { x: 6, y: 6 } };
  const unit = { id: 0, x: 0, y: 0, move_points: 2, next_move_capacity: 3 };
  const first = previewMovement(map, [unit], unit, { x: 3, y: 0 });
  assert.equal(first.status, "reachable");
  assert.deepEqual(Array.from(first.path, p => [p.x, p.y]), [[1, 0], [2, 0], [3, 0]]);
  assert.equal(first.thisTurn, 2);
  assert.equal(first.turns, 2);
  const blocker = { id: 1, x: 1, y: 0 };
  const around = previewMovement(map, [unit, blocker], unit, { x: 2, y: 0 });
  assert.deepEqual(Array.from(around.path, p => [p.x, p.y]),
    [[0, 1], [1, 1], [2, 1], [2, 0]]);
  assert.equal(around.turns, 2);
  assert.equal(previewMovement(map, [unit, blocker], unit, { x: 1, y: 0 }).status, "unreachable");
  assert.equal(previewMovement(map, [unit], unit, { x: 5, y: 6 }).status, "unreachable");
  assert.equal(previewMovement({ ...map, breaches: [{ x: 5, y: 6 }] }, [unit], unit,
    { x: 5, y: 6 }).status, "reachable");
  assert.equal(previewMovement(map, [unit], unit, { x: 0, y: 0 }).status, "already_there");
  assert.equal(previewMovement(map, [unit], { ...unit, move_points: 0 },
    { x: 2, y: 0 }).status, "exhausted");
});

test("rope preview opens one-level ledges only while carried on foot", () => {
  const map = { cols: 8, rows: 8, keep: { left: 5, right: 7, top: 5, bottom: 7 },
    gate: { x: 6, y: 7 }, elevation: [{ x: 1, y: 0, height: 1 },
      { x: 2, y: 0, height: 3 }] };
  const unit = { id: 0, x: 0, y: 0, tools: [], move_points: 3,
    move_capacity: 4, next_move_capacity: 4 };
  const goal = { x: 1, y: 0 };
  assert.equal(previewMovement(map, [unit], unit, goal).status, "unreachable");
  const withRope = { ...unit, tools: ["rope"] };
  assert.equal(previewMovement(map, [withRope], withRope, goal).status, "reachable");
  assert.equal(previewMovement(map, [withRope], withRope, { x: 2, y: 0 }).status, "unreachable");
  const mounted = { ...withRope, mount_id: 0 };
  assert.equal(previewMovement(map, [mounted], mounted, goal).status, "unreachable");
});

test("route preview follows weight-adjusted current and future allowances", () => {
  const map = { cols: 8, rows: 8, keep: { left: 5, right: 7, top: 5, bottom: 7 },
    gate: { x: 6, y: 7 } };
  const unit = { id: 0, x: 0, y: 0, move_points: 1, next_move_capacity: 2,
    carried_weight: 8, max_carry_weight: 8, weight_penalty: 2 };
  const route = previewMovement(map, [unit], unit, { x: 4, y: 0 });
  assert.equal(route.thisTurn, 1);
  assert.equal(route.turns, 3);
});

test("mounted preview avoids swamps, houses and ladders while costing 4 MP on mud", () => {
  const map = { cols: 8, rows: 8, keep: { left: 5, right: 7, top: 5, bottom: 7 },
    gate: { x: 6, y: 7 }, houses: [{ left: 2, right: 3, top: 1, bottom: 2,
      door: { x: 2, y: 1 } }], terrain: [{ x: 1, y: 0, type: "mud" },
      { x: 0, y: 1, type: "swamp" }] };
  const rider = { id: 0, x: 0, y: 0, mount_id: 0, move_points: 5,
    move_capacity: 6, next_move_capacity: 6 };
  const mud = previewMovement(map, [rider], rider, { x: 1, y: 0 });
  assert.equal(mud.totalCost, 4);
  assert.equal(mud.thisTurnCost, 4);
  assert.equal(previewMovement(map, [rider], rider, { x: 0, y: 1 }).status, "unreachable");
  assert.equal(previewMovement(map, [rider], rider, { x: 2, y: 1 }).status, "unreachable");
  const ladder = { ...map, elevation: [{ x: 1, y: 0, height: 1, access: "ladder" }] };
  assert.equal(previewMovement(ladder, [rider], rider, { x: 1, y: 0 }).status, "unreachable");
  ladder.elevation[0].access = "ramp";
  assert.equal(previewMovement(ladder, [rider], rider, { x: 1, y: 0 }).status, "reachable");
});

test("horse controls send mount and dismount orders and show mount status", async () => {
  const game = setup();
  game.snapshot.map.horses = [{ x: 0, y: 0 }];
  game.snapshot.state.horses = [{ id: 0, x: 0, y: 0, health: 2, max_health: 2, rider_id: null }];
  await game.get("continue-game").fire("click");
  assert.equal(game.get("mount-horse").disabled, false);
  assert.match(game.get("selected-stats").textContent, /Available here/);
  await game.get("mount-horse").fire("click");
  assert.equal(game.actions.at(-1).type, "mount");
  assert.equal(game.actions.at(-1).horse_id, 0);
  game.snapshot.state.units[0].mount_id = 0;
  game.snapshot.state.horses[0].rider_id = 0;
  await game.get("continue-game").fire("click");
  assert.equal(game.get("mount-horse").textContent, "Dismount");
  await game.get("mount-horse").fire("click");
  assert.equal(game.actions.at(-1).type, "dismount");
});

test("route preview chooses cheaper terrain and never splits a costly tile between turns", () => {
  const map = { cols: 8, rows: 8, keep: { left: 5, right: 7, top: 5, bottom: 7 },
    gate: { x: 6, y: 7 }, terrain: [{ x: 1, y: 0, type: "swamp" },
      { x: 2, y: 0, type: "mud" }] };
  const unit = { id: 0, x: 0, y: 0, move_points: 3, move_capacity: 4, next_move_capacity: 4 };
  const route = previewMovement(map, [unit], unit, { x: 2, y: 0 });
  assert.deepEqual(Array.from(route.path, p => [p.x, p.y]),
    [[0, 1], [1, 1], [2, 1], [2, 0]]);
  assert.equal(route.totalCost, 6);
  assert.equal(route.thisTurn, 3);
  assert.equal(route.thisTurnCost, 3);
  assert.equal(route.turns, 2);
  const slow = { ...unit, move_points: 1, move_capacity: 2, next_move_capacity: 2 };
  assert.equal(previewMovement(map, [slow], slow, { x: 1, y: 0 }).status, "unreachable");
  const forced = { ...map, objects: [{ x: 0, y: 1, type: "rock" }] };
  const waiting = previewMovement(forced, [unit], { ...unit, move_points: 2 }, { x: 2, y: 0 });
  assert.equal(waiting.thisTurn, 0);
  assert.equal(waiting.turns, 3);
});

test("renderer draws reachable route steps and unreachable markers", () => {
  const game = setup();
  const renderer = game.createRenderer(game.get("battlefield-canvas"));
  renderer.setLayout({ width: 600, height: 400, tileW: 56, tileH: 28,
    originX: 300, originY: 100, ratio: 1 });
  renderer.setMap(game.snapshot.map);
  const scene = { simulation: { units: [], selected: new Set(), captured: false },
    camera: { x: 0, y: 0, zoom: 1 }, cursor: { visible: false },
    hasAttackOption: () => false, movementPreview: { start: { x: 0, y: 0 },
      destination: { x: 0, y: 2 }, route: { status: "reachable", thisTurn: 1,
        path: [{ x: 0, y: 1 }, { x: 0, y: 2 }] } } };
  renderer.draw(0, scene);
  scene.movementPreview = { ...scene.movementPreview, route: { status: "unreachable", path: [] } };
  renderer.draw(0, scene);
  assert.equal(game.draws(), 2);
});

test("route preview obeys house doors, objects, and elevation access in both directions", () => {
  const map = { cols: 8, rows: 8, keep: { left: 5, right: 7, top: 5, bottom: 7 },
    gate: { x: 6, y: 7 }, objective: { x: 6, y: 6 },
    houses: [{ left: 2, right: 3, top: 1, bottom: 2, door: { x: 2, y: 1 } }],
    objects: [{ x: 1, y: 0, type: "fence" }] };
  const soldier = { id: 0, x: 1, y: 2, move_points: 3, next_move_capacity: 4 };
  const inside = previewMovement(map, [soldier], soldier, { x: 3, y: 2 });
  assert.equal(inside.status, "reachable");
  assert.deepEqual(Array.from(inside.path, p => [p.x, p.y]),
    [[1, 1], [2, 1], [3, 1], [3, 2]]);
  const trapped = { ...soldier, x: 3, y: 2 };
  const outside = previewMovement(map, [trapped], trapped, { x: 1, y: 2 });
  assert.deepEqual(Array.from(outside.path, p => [p.x, p.y]),
    [[2, 2], [2, 1], [1, 1], [1, 2]]);
  const climb = { ...map, elevation: [{ x: 0, y: 1, height: 1, access: "ladder" }] };
  const climber = { ...soldier, x: 0, y: 0 };
  assert.equal(previewMovement(climb, [climber], climber, { x: 0, y: 1 }).status, "reachable");
  const descending = { ...climber, y: 1 };
  assert.equal(previewMovement(climb, [descending], descending,
    { x: 0, y: 0 }).status, "reachable");
  assert.equal(previewMovement({ ...map, elevation: [{ x: 0, y: 1, height: 1 }] },
    [climber], climber, { x: 0, y: 1 }).status, "unreachable");
});

test("keyboard and hover preview refresh after occupancy, selection, and pause", async () => {
  const game = setup();
  const soldier = game.snapshot.state.units[0];
  soldier.move_points = 1;
  soldier.next_move_capacity = 4;
  await game.get("continue-game").fire("click");
  const canvas = game.get("battlefield-canvas");
  const key = name => canvas.fire("keydown", { key: name, preventDefault() {} });
  canvas.fire("pointermove", { pointerType: "mouse", clientX: 268, clientY: 219.2 });
  assert.match(game.get("route-status").textContent, /1 tile · 1 MP total · 1 MP this turn/);
  canvas.fire("pointerleave");
  assert.match(game.get("route-status").textContent, /Hover over a tile/);
  canvas.fire("focus");
  key("ArrowDown");
  key("ArrowDown");
  assert.match(game.get("route-status").textContent, /2 tiles · 2 MP total · 1 MP this turn \(1 tile\) · approximately 2 turns/);
  game.snapshot.state.units.push({ ...soldier, id: 1, x: 0, y: 2 });
  await game.get("end-turn").fire("click");
  assert.match(game.get("route-status").textContent, /Unreachable/);
  canvas.fire("keydown", { key: "Enter", shiftKey: true, preventDefault() {} });
  assert.match(game.get("route-status").textContent, /Select one soldier to preview/);
  game.get("pause-game").fire("click");
  assert.doesNotMatch(game.get("route-status").textContent, /Route to/);
  game.get("pause-game").fire("click");
  canvas.fire("keydown", { key: "Enter", shiftKey: true, preventDefault() {} });
  assert.match(game.get("route-status").textContent, /Unreachable/);
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
  game.snapshot.state.history.push({ turn: 4, type: "ranged_attack", actor_id: 0,
    actor_side: "attackers", actor_weapon: "crossbow", target_id: 1,
    target_side: "defenders", target_weapon: "sword", damage: 2, ambush: true,
    killed: false, morale_changes: [] });
  await game.get("end-turn").fire("click");
  assert.match(list.children[3].textContent, /2 damage \(ambush \+1\)/);
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

test("armor protection, weight and equip action update with the snapshot", async () => {
  const game = setup();
  const soldier = game.snapshot.state.units[0];
  soldier.armor = "mail";
  soldier.armor_equipped = true;
  soldier.armor_remaining = 2;
  await game.get("continue-game").fire("click");
  const armor = game.get("equip-armor");
  const panel = game.get("selected-stats");
  const armorRow = () => panel.children.find(child => child.children?.[0]?.textContent === "Armor");
  assert.equal(armor.hidden, false);
  assert.equal(armor.disabled, false);
  assert.equal(armor.textContent, "Remove armor");
  assert.equal(armorRow().children[1].textContent, "mail · worn · 2/2 protection left this turn · weight 3");
  await armor.fire("click");
  assert.equal(game.actions.at(-1).type, "equip_armor");
  assert.equal(game.actions.at(-1).equipped, false);
  await new Promise(setImmediate);
  soldier.armor_equipped = false;
  soldier.armor_remaining = 0;
  soldier.fight_points = 0;
  game.snapshot.state.history = [
    { turn: 1, type: "equip_armor", actor_id: 0, actor_side: "attackers", actor_weapon: "sword",
      armor: "mail", equipped: false },
    { turn: 1, type: "attack", actor_id: 1, actor_side: "defenders", actor_weapon: "sword",
      target_id: 0, target_side: "attackers", target_weapon: "sword", target_armor: "mail",
      armor_blocked: 2, damage: 0, killed: false, morale_changes: [] }
  ];
  await game.get("continue-game").fire("click");
  assert.equal(armor.textContent, "Equip armor");
  assert.equal(armor.disabled, true);
  assert.match(armorRow().textContent, /carried · 0\/2 protection left this turn · weight 3/);
  assert.match(game.get("combat-history-list").children[0].textContent, /removed mail armor/);
  assert.match(game.get("combat-history-list").children[1].textContent, /mail armor absorbed 2/);
});

test("load penalty and carrying limit are visible before moving or picking up", async () => {
  const game = setup();
  const unit = game.snapshot.state.units[0];
  Object.assign(unit, { carried_weight: 8, max_carry_weight: 8, weight_penalty: 2,
    move_points: 1, move_capacity: 2, next_move_capacity: 2 });
  game.snapshot.map.items = [{ x: 0, y: 0, type: "healing_potion" }];
  game.snapshot.state.items = [{ id: 0, x: 0, y: 0, type: "healing_potion", carrier_id: null }];
  await game.get("continue-game").fire("click");
  const load = game.get("selected-stats").children.find(row => row.children?.[0]?.textContent === "Load");
  assert.match(load.textContent, /8\/8 weight · −2 MP\/turn/);
  assert.equal(game.get("pickup-potion").disabled, true);
  const canvas = game.get("battlefield-canvas");
  canvas.fire("focus");
  canvas.fire("keydown", { key: "ArrowDown", preventDefault() {} });
  assert.match(game.get("route-status").textContent, /1 MP this turn \(1 tile\) · load 8\/8 \(2 MP penalty\)/);
  assert.match(game.get("selected-stats").textContent, /Projected next turn: 2 MP/);
});

test("wounded soldiers can be treated even at full HP and see their recovery forecast", async () => {
  const game = setup();
  const soldier = game.snapshot.state.units[0];
  soldier.wound_turns = 2;
  soldier.next_move_capacity = 3;
  soldier.health = 3;
  game.snapshot.map.items = [{ x: 0, y: 0, type: "healing_potion" }];
  game.snapshot.state.items = [{ id: 0, carrier_id: 0, x: null, y: null, type: "healing_potion" }];
  game.snapshot.state.history = [{ turn: 1, type: "attack", actor_id: 1, actor_side: "defenders",
    actor_weapon: "sword", target_id: 0, target_side: "attackers", target_weapon: "sword",
    damage: 1, killed: false, wounded: true, morale_changes: [] }];
  await game.get("continue-game").fire("click");
  assert.match(game.get("selected-stats").textContent, /Wounded · −1 MP on foot; 2 turn/);
  assert.match(game.get("selected-stats").textContent, /Projected next turn: 3 MP.*injury/);
  assert.equal(game.get("heal-potion").disabled, false);
  assert.match(game.get("heal-target").children[0].textContent, /wounded/);
  assert.match(game.get("combat-history-list").textContent, /wounded: −1 MP/);
  soldier.wound_turns = 1;
  soldier.next_move_capacity = 4;
  await game.get("continue-game").fire("click");
  assert.match(game.get("selected-stats").textContent, /Projected next turn: 4 MP/);
  assert.doesNotMatch(game.get("selected-stats").textContent, /and injury/);
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

test("fallen gear renders and can be dropped, selected and recovered without stealing potion actions", async () => {
  const game = setup();
  const soldier = game.snapshot.state.units[0];
  soldier.armor = "leather";
  soldier.armor_equipped = true;
  soldier.carried_weight = 2;
  soldier.max_carry_weight = 8;
  game.snapshot.map.items = [{ x: 0, y: 0, type: "healing_potion" }];
  game.snapshot.state.items = [
    { id: 0, type: "healing_potion", x: 0, y: 0, carrier_id: null },
    { id: 1, type: "armor", name: "mail", x: 0, y: 0, carrier_id: null },
    { id: 2, type: "weapon", name: "crossbow", x: 0, y: 0, carrier_id: null }
  ];
  await game.get("continue-game").fire("click");
  assert.ok(game.gearPaints.includes("#9baeb3"));
  assert.ok(game.gearPaints.includes("#d2ac70"));
  assert.equal(game.get("gear-target").children.length, 2);
  assert.equal(game.get("gear-target").children[0].textContent, "mail armor");
  assert.equal(game.get("pickup-equipment").disabled, true);
  assert.match(game.get("selected-stats").textContent, /Equipment here.*mail armor, crossbow/);
  assert.match(game.get("cursor-status").textContent, /healing potion on ground.*mail armor, crossbow on ground/);
  await game.get("pickup-potion").fire("click");
  assert.equal(game.actions.at(-1).item_id, 0);
  await new Promise(setImmediate);
  await game.get("drop-armor").fire("click");
  assert.equal(game.actions.at(-1).type, "drop_armor");
  await new Promise(setImmediate);
  soldier.armor = null;
  soldier.armor_equipped = false;
  game.snapshot.state.history = [{ turn: 1, type: "drop_armor", actor_id: 0,
    actor_side: "attackers", actor_weapon: "sword", equipment: "leather" }];
  await game.get("continue-game").fire("click");
  assert.match(game.get("combat-history-list").textContent, /dropped leather armor/);
  assert.equal(game.get("pickup-equipment").disabled, false);
  await game.get("pickup-equipment").fire("click");
  assert.equal(game.actions.at(-1).type, "pickup_equipment");
  assert.equal(game.actions.at(-1).item_id, 1);
  await new Promise(setImmediate);
  soldier.armor = "mail";
  game.snapshot.state.items.splice(1, 1);
  await game.get("continue-game").fire("click");
  assert.equal(game.get("gear-target").value, "2");
  assert.equal(game.get("pickup-equipment").disabled, true);
  await game.get("drop-weapon").fire("click");
  assert.equal(game.actions.at(-1).type, "drop_weapon");
  await new Promise(setImmediate);
  soldier.weapon = null;
  await game.get("continue-game").fire("click");
  assert.equal(game.get("pickup-equipment").disabled, false);
  await game.get("pickup-equipment").fire("click");
  assert.equal(game.actions.at(-1).item_id, 2);
});

test("tools render separately from equipment and can be picked up or dropped", async () => {
  const game = setup();
  const soldier = game.snapshot.state.units[0];
  soldier.carried_weight = 1;
  soldier.max_carry_weight = 8;
  game.snapshot.state.items = [{ id: 0, type: "tool", name: "rope", x: 0, y: 0, carrier_id: null },
    { id: 1, type: "tool", name: "spade", x: 0, y: 0, carrier_id: null }];
  await game.get("continue-game").fire("click");
  assert.ok(game.gearPaints.includes("#a4c499"));
  assert.equal(game.get("gear-target").children.length, 0);
  assert.match(game.get("selected-stats").textContent, /Tools here.*rope/);
  assert.match(game.get("cursor-status").textContent, /rope, spade tool on ground/);
  assert.equal(game.get("pickup-tool").disabled, false);
  assert.equal(game.get("ground-tool-target").children.length, 2);
  game.get("ground-tool-target").value = "1";
  game.get("ground-tool-target").fire("change");
  await game.get("pickup-tool").fire("click");
  assert.equal(game.actions.at(-1).type, "pickup_tool");
  assert.equal(game.actions.at(-1).item_id, 1);
  await new Promise(setImmediate);
  soldier.tools = ["rope", "spade"];
  soldier.fight_points = 1;
  game.snapshot.state.items = [];
  game.snapshot.state.history = [{ turn: 1, type: "pickup_tool", actor_id: 0,
    actor_side: "attackers", actor_weapon: "sword", tool: "rope" }];
  await game.get("continue-game").fire("click");
  assert.match(game.get("combat-history-list").textContent, /picked up rope tool/);
  assert.equal(game.get("pickup-tool").disabled, true);
  assert.equal(game.get("tool-target").children.length, 2);
  game.get("tool-target").value = "1";
  await game.get("drop-tool").fire("click");
  assert.equal(game.actions.at(-1).type, "drop_tool");
  assert.equal(game.actions.at(-1).tool_index, 1);
});
