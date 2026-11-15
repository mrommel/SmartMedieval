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
    setPointerCapture() {}, append() {}, replaceChildren() {},
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
      if (options.method === "POST") postCount++;
      return { ok: true, headers: { get: () => "application/json" }, json: async () => snapshot };
    }
  });
  return {
    get, store, draws: () => draws, postCount: () => postCount,
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
