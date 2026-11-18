const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const script = fs.readFileSync(path.join(__dirname, "../static/game/admin_map_preview.js"), "utf8");
const map = { cols: 8, rows: 8, keep: { left: 4, right: 7, top: 2, bottom: 6 },
  gate: { x: 5, y: 6 }, objective: { x: 5, y: 4 },
  startPositions: [{ x: 1, y: 2 }], enemyStartPositions: [{ x: 6, y: 3 }] };

function setup(fetch) {
  const nodes = new Map();
  const form = { querySelector: () => ({ value: "csrf-token" }) };
  for (const id of ["map-preview", "id_map_definition", "preview-map-button", "map-preview-status",
    "map-preview-result", "map-preview-canvas", "map-preview-summary"]) {
    nodes.set(id, { hidden: false, disabled: false, dataset: {},
      addEventListener(type, handler) { this[type] = handler; },
      closest: () => form });
  }
  const panel = nodes.get("map-preview");
  panel.dataset.previewUrl = "/admin/game/singlegame/preview/";
  const editor = nodes.get("id_map_definition");
  editor.value = JSON.stringify(map);
  const canvas = nodes.get("map-preview-canvas");
  let draws = 0;
  const labels = [];
  canvas.getContext = () => ({ fillRect() { draws++; }, strokeRect() {}, fillText(text) { labels.push(text); } });
  vm.runInNewContext(script, { document: { getElementById: id => nodes.get(id) },
    fetch, URLSearchParams, AbortController });
  return { nodes, editor, panel, canvas, labels, get draws() { return draws; },
    click: () => nodes.get("preview-map-button").click() };
}

test("previews unsaved JSON with CSRF and invalidates on editing", async () => {
  const ui = setup(async (url, options) => {
    assert.equal(url, ui.panel.dataset.previewUrl);
    assert.equal(options.method, "POST");
    assert.equal(options.headers["X-CSRFToken"], "csrf-token");
    assert.deepEqual(JSON.parse(options.body.get("map_definition")), map);
    return { ok: true, json: async () => ({ map }) };
  });
  await ui.click();
  assert.equal(ui.canvas.width, 192);
  assert.equal(ui.draws, 64);
  assert.equal(ui.nodes.get("map-preview-result").hidden, false);
  assert.match(ui.nodes.get("map-preview-summary").textContent, /1 attackers, 1 defenders/);
  ui.editor.input();
  assert.equal(ui.nodes.get("map-preview-result").hidden, true);
  assert.match(ui.nodes.get("map-preview-status").textContent, /Map changed/);
});

test("previews water, bridges and fords with a river tile count", async () => {
  const withRivers = { ...map, rivers: [{ x: 2, y: 1, type: "water" },
    { x: 2, y: 2, type: "bridge" }, { x: 2, y: 3, type: "ford" }] };
  const ui = setup(async () => ({ ok: true, json: async () => ({ map: withRivers }) }));
  await ui.click();
  assert.match(ui.nodes.get("map-preview-summary").textContent, /3 river tiles/);
  assert.ok(ui.labels.includes("B"));
  assert.ok(ui.labels.includes("F"));
});

test("invalid maps never display stale previews", async () => {
  let resolve;
  const ui = setup(() => new Promise(done => { resolve = done; }));
  const first = ui.click();
  ui.editor.input();
  resolve({ ok: true, json: async () => ({ map }) });
  await first;
  assert.equal(ui.nodes.get("map-preview-result").hidden, true);
  const invalid = setup(async () => ({ ok: false, json: async () => ({ error: "The gate must lie on the keep wall." }) }));
  await invalid.click();
  assert.equal(invalid.nodes.get("map-preview-result").hidden, true);
  assert.match(invalid.nodes.get("map-preview-status").textContent, /gate must lie/);
});
