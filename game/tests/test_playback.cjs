const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

const script = fs.readFileSync(path.join(__dirname, "../static/game/game.js"), "utf8");

function element() {
  const listeners = {};
  return {
    hidden: false, disabled: false, value: "1", style: {}, dataset: {},
    classList: { add() {}, remove() {}, toggle() {} },
    addEventListener(type, handler) { listeners[type] = handler; },
    setAttribute(name, value) { this[name] = value; },
    querySelector() { return element(); },
    getBoundingClientRect() { return { width: 600, height: 400, left: 0, top: 0 }; },
    setPointerCapture() {}, append() {}, replaceChildren(...children) { this.children = children; },
    fire(type, event = {}) { return listeners[type]?.(event); }
  };
}

function setup(savedSpeed = null) {
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
    state: { units: [{ id: 0, x: 0, y: 0, side: "attackers", type: "vanguard",
      rank: "recruit", morale: 3, move_points: 3, fight_points: 1,
      health: 3, max_health: 3 }], captured: false, defeated: false,
    capture_progress: 0, capture_status: "UNCLAIMED", turn: 1 }
  };
  let postCount = 0;
  const actions = [];
  let nextFrame;
  const window = {
    devicePixelRatio: 1, localStorage: store,
    matchMedia: () => ({ matches: false, addEventListener() {} }),
    addEventListener() {}
  };
  const document = {
    getElementById: get, createElement: element,
    querySelector: () => ({ content: "csrf" }),
    querySelectorAll: () => []
  };
  vm.runInNewContext(script, {
    document, window, performance: { now: () => 0 },
    requestAnimationFrame: callback => { nextFrame = callback; },
    setTimeout: () => 1, clearTimeout() {},
    fetch: async (_, options = {}) => {
      if (options.method === "POST") {
        postCount++;
        if (options.body) actions.push(JSON.parse(options.body).action);
      }
      return { ok: true, headers: { get: () => "application/json" }, json: async () => snapshot };
    }
  });
  return {
    get, store, snapshot, actions, draws: () => draws, postCount: () => postCount,
    frame: time => nextFrame(time)
  };
}

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
  assert.match(list.children[1].textContent, /Turn 2.*shot attacker vanguard #1 for 1 damage \(fallen\).*Morale: #2 \+1/);
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
  assert.match(game.get("cursor-status").textContent, /Tile 1, 1: friendly vanguard #1, selected/);
  key("ArrowDown");
  key("Enter", true);
  assert.match(game.get("selected-stats").textContent, /2 soldiers selected/);
  key(" ", true);
  assert.match(game.get("selected-stats").textContent, /#1 recruit/);
  key("ArrowDown");
  assert.match(game.get("cursor-status").textContent, /Tile 1, 3: open ground/);
  key("Enter");
  assert.equal(game.actions.at(-1).type, "move");
  assert.equal(game.actions.at(-1).y, 2);
  await new Promise(setImmediate);
  key("ArrowUp");
  key("ArrowUp");
  key("ArrowRight");
  assert.match(game.get("cursor-status").textContent, /defender vanguard/);
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
