(() => {
  "use strict";

  const panel = document.getElementById("map-preview");
  const editor = document.getElementById("id_map_definition");
  if (!panel || !editor) return;

  const button = document.getElementById("preview-map-button");
  const status = document.getElementById("map-preview-status");
  const result = document.getElementById("map-preview-result");
  const canvas = document.getElementById("map-preview-canvas");
  const summary = document.getElementById("map-preview-summary");
  const form = editor.closest("form");
  let generation = 0;
  let pending = null;

  function tiles(points) {
    return new Set((points || []).map(({ x, y }) => `${x},${y}`));
  }

  function rectangleEdge(x, y, rect) {
    return rect.left <= x && x <= rect.right && rect.top <= y && y <= rect.bottom &&
      (x === rect.left || x === rect.right || y === rect.top || y === rect.bottom);
  }

  function draw(map) {
    const size = 24;
    canvas.width = map.cols * size;
    canvas.height = map.rows * size;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("This browser cannot draw the map preview.");
    const terrain = new Map((map.terrain || []).map(tile => [`${tile.x},${tile.y}`, tile.type]));
    const rivers = new Map((map.rivers || []).map(tile => [`${tile.x},${tile.y}`, tile.type]));
    const elevation = new Map((map.elevation || []).map(tile => [`${tile.x},${tile.y}`, tile]));
    const objects = new Map((map.objects || []).map(tile => [`${tile.x},${tile.y}`, tile.type]));
    const attackers = tiles(map.startPositions);
    const defenders = tiles(map.enemyStartPositions);
    const catapults = tiles(map.catapults);
    const items = tiles(map.items);
    const horses = tiles(map.horses);
    const fires = tiles(map.watchfires);
    const lanes = tiles(map.lanes);
    const terrainColors = { road: "#d8d6ca", grass: "#a2c974", mud: "#a6886c", swamp: "#567866" };
    const rects = [map.keep, ...(map.strongpoints || [])];

    for (let y = 0; y < map.rows; y++) {
      for (let x = 0; x < map.cols; x++) {
        const key = `${x},${y}`;
        let color = terrainColors[terrain.get(key)] || (lanes.has(key) ? "#ded4b3" : "#e9e9d8");
        let label = "";
        if (rivers.has(key)) {
          const kind = rivers.get(key);
          color = kind === "water" ? "#377486" : kind === "bridge" ? "#9b8060" : "#62919a";
          label = kind === "water" ? "" : kind === "bridge" ? "B" : "F";
        }
        if (elevation.has(key)) {
          color = "#769fd2";
          label = String(elevation.get(key).height);
        }
        if (rects.some(rect => rectangleEdge(x, y, rect))) color = "#484950";
        if ((map.houses || []).some(house => house.left <= x && x <= house.right && house.top <= y && y <= house.bottom)) color = "#a9744c";
        if (objects.has(key)) { color = "#478b86"; label = objects.get(key)[0].toUpperCase(); }
        if (catapults.has(key)) { color = "#333333"; label = "C"; }
        if (items.has(key)) { color = "#ffffff"; label = "I"; }
        if (horses.has(key) || fires.has(key)) { color = "#6cd4db"; label = horses.has(key) ? "H" : "F"; }
        if (rects.some(rect => rect.gate && rect.gate.x === x && rect.gate.y === y) ||
            (map.gate.x === x && map.gate.y === y)) { color = "#e8c252"; label = "G"; }
        if ((map.houses || []).some(house => house.door && house.door.x === x && house.door.y === y)) {
          color = "#ed963c"; label = "D";
        }
        if (map.exit && map.exit.x === x && map.exit.y === y) { color = "#ac82c2"; label = "X"; }
        if (map.objective.x === x && map.objective.y === y) { color = "#dfad31"; label = "O"; }
        if (defenders.has(key)) { color = "#c65855"; label = "D"; }
        if (attackers.has(key)) { color = "#52a76b"; label = "A"; }
        ctx.fillStyle = color;
        ctx.fillRect(x * size, y * size, size, size);
        ctx.strokeStyle = "#9998";
        ctx.strokeRect(x * size + 0.5, y * size + 0.5, size, size);
        if (label) {
          ctx.fillStyle = color === "#484950" || color === "#333333" ? "#ffffff" : "#172229";
          ctx.font = "bold 14px sans-serif";
          ctx.textAlign = "center";
          ctx.textBaseline = "middle";
          ctx.fillText(label, (x + 0.5) * size, (y + 0.5) * size);
        }
      }
    }
    summary.textContent = `${map.cols} columns by ${map.rows} rows. ` +
      `Gate (${map.gate.x}, ${map.gate.y}); objective (${map.objective.x}, ${map.objective.y}). ` +
      `${attackers.size} attackers, ${defenders.size || 1} defenders, ` +
      `${(map.houses || []).length} houses, ${(map.strongpoints || []).length} strongpoints, ` +
      `${objects.size} objects, ${(map.items || []).length} supplies, ${rivers.size} river tiles.` +
      (map.exit ? ` Exit (${map.exit.x}, ${map.exit.y}).` : "") +
      (map.fog_of_war ? " Fog of war enabled." : "") +
      (map.night ? " Night enabled." : "");
    result.hidden = false;
  }

  editor.addEventListener("input", () => {
    generation++;
    if (pending) pending.abort();
    pending = null;
    button.disabled = false;
    result.hidden = true;
    status.textContent = "Map changed. Validate and preview again to check the current JSON.";
  });

  button.addEventListener("click", async () => {
    const current = ++generation;
    const controller = new AbortController();
    pending = controller;
    button.disabled = true;
    result.hidden = true;
    status.textContent = "Validating map…";
    try {
      const body = new URLSearchParams({ map_definition: editor.value });
      const response = await fetch(panel.dataset.previewUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-CSRFToken": form.querySelector("[name=csrfmiddlewaretoken]").value },
        body,
        signal: controller.signal,
      });
      const data = await response.json();
      if (current !== generation) return;
      if (!response.ok) {
        status.textContent = data.error || "Map preview could not be validated.";
        return;
      }
      draw(data.map);
      status.textContent = "Valid map. Unsaved preview; save before playtesting.";
    } catch (error) {
      if (current === generation) status.textContent = error.message || "Map preview unavailable.";
    } finally {
      if (current === generation) {
        pending = null;
        button.disabled = false;
      }
    }
  });
})();
