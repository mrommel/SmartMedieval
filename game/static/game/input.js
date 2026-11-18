export function createBattlefieldInput({ canvas, renderer, simulation, getMap, getLayout,
  canOrder, isWalkable, isAiming, onAim, onMove, onAttack, onSelection, onBlocked, onDraw, onCursor,
  isGroupSelection = () => false, onPreviewChange = () => {} }) {
  const camera = { x: 0, y: 0, zoom: 1 };
  const cursor = { x: 0, y: 0, visible: false };
  let activePointer = null;
  const touches = new Map();
  let pinch = null;
  let hoveredTile = null;
  let keyboardPreview = false;
  let inspectTouch = false;

  function previewDestination() {
    return hoveredTile || (cursor.visible && keyboardPreview ? { x: cursor.x, y: cursor.y } : null);
  }

  function setHover(tile) {
    if (hoveredTile?.x === tile?.x && hoveredTile?.y === tile?.y && Boolean(hoveredTile) === Boolean(tile)) return;
    hoveredTile = tile;
    onPreviewChange();
  }

  function clampCamera() {
    const { width, height, tileW, tileH, originX, originY } = getLayout();
    const map = getMap();
    if (!map || !width || !height) return;
    const mapWidth = (map.cols + map.rows - 2) * tileW * 0.5;
    const mapHeight = (map.cols + map.rows - 2) * tileH * 0.5;
    const left = originX - mapWidth;
    const right = originX + mapWidth;
    const top = originY - tileH * (2.7 + Math.max(0, ...(map.elevation || []).map(tile => tile.height)));
    const bottom = originY + mapHeight + tileH;
    const margin = Math.min(72, width * 0.2, height * 0.2);
    const minX = margin - right * camera.zoom;
    const maxX = width - margin - left * camera.zoom;
    const minY = margin - bottom * camera.zoom;
    const maxY = height - margin - top * camera.zoom;
    camera.x = minX > maxX ? (minX + maxX) / 2 : Math.max(minX, Math.min(maxX, camera.x));
    camera.y = minY > maxY ? (minY + maxY) / 2 : Math.max(minY, Math.min(maxY, camera.y));
  }

  function resetCamera() {
    camera.x = 0;
    camera.y = 0;
    camera.zoom = 1;
    clampCamera();
  }

  function zoomAt(screenX, screenY, factor) {
    const nextZoom = Math.max(.7, Math.min(1.8, camera.zoom * factor));
    const worldX = (screenX - camera.x) / camera.zoom;
    const worldY = (screenY - camera.y) / camera.zoom;
    camera.zoom = nextZoom;
    camera.x = screenX - worldX * nextZoom;
    camera.y = screenY - worldY * nextZoom;
    clampCamera();
    onDraw();
  }

  function startPinch() {
    const [first, second] = [...touches.values()];
    const rect = canvas.getBoundingClientRect();
    const x = (first.x + second.x) / 2 - rect.left;
    const y = (first.y + second.y) / 2 - rect.top;
    pinch = { distance: Math.hypot(first.x - second.x, first.y - second.y),
      zoom: camera.zoom, worldX: (x - camera.x) / camera.zoom,
      worldY: (y - camera.y) / camera.zoom };
    activePointer = null;
    setHover(null);
  }

  function movePinch() {
    const [first, second] = [...touches.values()];
    const rect = canvas.getBoundingClientRect();
    const distance = Math.hypot(first.x - second.x, first.y - second.y);
    camera.zoom = Math.max(.7, Math.min(1.8, pinch.zoom * distance / (pinch.distance || 1)));
    camera.x = (first.x + second.x) / 2 - rect.left - pinch.worldX * camera.zoom;
    camera.y = (first.y + second.y) / 2 - rect.top - pinch.worldY * camera.zoom;
    clampCamera();
    onDraw();
  }

  function pickTile(localX, localY) {
    const { tileW, tileH, originX, originY } = getLayout();
    for (const tile of [...(getMap().elevation || [])].sort((a, b) => b.x + b.y - a.x - a.y)) {
      const p = renderer.project(tile.x, tile.y);
      if (Math.abs(localX - p.x) / (tileW / 2) +
          Math.abs(localY - p.y - tileH / 2) / (tileH / 2) <= 1) {
        return { x: tile.x, y: tile.y };
      }
    }
    const houseTiles = [];
    for (const house of getMap().houses || []) {
      if (house.door) continue; // Roof-cutaway interiors are picked at ground level.
      for (let y = house.top; y <= house.bottom; y++) {
        for (let x = house.left; x <= house.right; x++) houseTiles.push({ x, y });
      }
    }
    for (const tile of houseTiles.sort((a, b) => b.x + b.y - a.x - a.y)) {
      const p = renderer.project(tile.x, tile.y);
      if (Math.abs(localX - p.x) / (tileW / 2) +
          Math.abs(localY - (p.y - tileH * .85)) / (tileH / 2) <= 1) {
        return tile;
      }
    }
    const a = (localX - originX) / (tileW / 2);
    const b = (localY - originY) / (tileH / 2);
    return { x: Math.floor((a + b) / 2), y: Math.floor((b - a) / 2) };
  }

  function select(unit, shiftKey) {
    if (shiftKey || isGroupSelection()) {
      if (simulation.selected.has(unit.id)) simulation.selected.delete(unit.id);
      else simulation.selected.add(unit.id);
    } else {
      simulation.selected = new Set([unit.id]);
    }
    onSelection();
  }

  function orderTile(x, y) {
    if (!isWalkable(x, y)) onBlocked();
    else onMove(x, y);
  }

  function handlePointer(event) {
    if (!canOrder()) return;
    const rect = canvas.getBoundingClientRect();
    const px = (event.clientX - rect.left - camera.x) / camera.zoom;
    const py = (event.clientY - rect.top - camera.y) / camera.zoom;
    if (event.pointerType === "touch" && inspectTouch) {
      const tile = pickTile(px, py);
      const map = getMap();
      setHover(tile.x >= 0 && tile.x < map.cols && tile.y >= 0 && tile.y < map.rows ? tile : null);
      return;
    }
    if (isAiming()) {
      const tile = pickTile(px, py);
      onAim(tile.x, tile.y);
      return;
    }
    const { tileW, tileH } = getLayout();
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
    if (clicked) return select(clicked, event.shiftKey);
    const target = simulation.units.find(unit => {
      if (unit.side !== "defenders") return false;
      const p = renderer.project(unit.x, unit.y);
      return Math.hypot(px - p.x, py - (p.y + tileH * .1)) < Math.max(17, tileW * .29);
    });
    if (target) return onAttack(target);
    const tile = pickTile(px, py);
    orderTile(tile.x, tile.y);
  }

  function describeCursor() {
    onCursor(cursor);
  }

  function resetCursor(x, y) {
    const map = getMap();
    cursor.x = Math.max(0, Math.min(map.cols - 1, x));
    cursor.y = Math.max(0, Math.min(map.rows - 1, y));
    describeCursor();
  }

  function focusTile(x, y) {
    resetCursor(x, y);
    cursor.visible = true;
    keyboardPreview = true;
    setHover(null);
    revealCursor();
    canvas.focus();
    onPreviewChange();
    onDraw();
  }

  function revealCursor() {
    const { width, height, tileH } = getLayout();
    const point = renderer.project(cursor.x, cursor.y);
    const screenX = point.x * camera.zoom + camera.x;
    const screenY = (point.y + tileH / 2) * camera.zoom + camera.y;
    const margin = 32;
    camera.x += Math.max(margin - screenX, 0) - Math.max(screenX - (width - margin), 0);
    camera.y += Math.max(margin - screenY, 0) - Math.max(screenY - (height - margin), 0);
    clampCamera();
  }

  function keyboardOrder(shiftKey) {
    if (isAiming()) {
      onAim(cursor.x, cursor.y);
      return;
    }
    const unit = simulation.units.find(item => item.x === cursor.x && item.y === cursor.y);
    if (unit?.side === "defenders") onAttack(unit);
    else if (unit) {
      select(unit, shiftKey);
      describeCursor();
    } else orderTile(cursor.x, cursor.y);
  }

  canvas.addEventListener("pointerdown", event => {
    if (event.button !== 0 || !canOrder()) return;
    keyboardPreview = false;
    onPreviewChange();
    if (event.pointerType === "touch") {
      touches.set(event.pointerId, { x: event.clientX, y: event.clientY });
      setHover(null);
      canvas.setPointerCapture(event.pointerId);
      if (touches.size === 2) startPinch();
      else if (touches.size === 1 && !pinch) activePointer = {
        id: event.pointerId, x: event.clientX, y: event.clientY,
        cameraX: camera.x, cameraY: camera.y, dragging: false
      };
      return;
    }
    if (activePointer) return;
    activePointer = { id: event.pointerId, x: event.clientX, y: event.clientY,
      cameraX: camera.x, cameraY: camera.y, dragging: false };
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointermove", event => {
    if (event.pointerType === "touch" && touches.has(event.pointerId)) {
      touches.set(event.pointerId, { x: event.clientX, y: event.clientY });
      if (pinch && touches.size >= 2) movePinch();
      if (pinch) return;
    }
    if (!activePointer) {
      if (event.pointerType === "touch" || !canOrder()) return;
      const rect = canvas.getBoundingClientRect();
      const tile = pickTile((event.clientX - rect.left - camera.x) / camera.zoom,
        (event.clientY - rect.top - camera.y) / camera.zoom);
      setHover(tile.x >= 0 && tile.x < getMap().cols && tile.y >= 0 && tile.y < getMap().rows ? tile : null);
      return;
    }
    if (!activePointer || event.pointerId !== activePointer.id) return;
    const dx = event.clientX - activePointer.x;
    const dy = event.clientY - activePointer.y;
    if (!activePointer.dragging && Math.hypot(dx, dy) > 4) activePointer.dragging = true;
    if (activePointer.dragging) {
      setHover(null);
      camera.x = activePointer.cameraX + dx;
      camera.y = activePointer.cameraY + dy;
      clampCamera();
      onDraw();
    }
  });
  canvas.addEventListener("pointerup", event => {
    if (touches.has(event.pointerId)) {
      touches.delete(event.pointerId);
      if (pinch) {
        if (touches.size >= 2) startPinch();
        else if (!touches.size) pinch = null;
        return;
      }
    }
    if (!activePointer || event.pointerId !== activePointer.id) return;
    if (!activePointer.dragging) handlePointer(event);
    activePointer = null;
  });
  canvas.addEventListener("pointercancel", event => {
    touches.delete(event.pointerId);
    if (pinch && touches.size >= 2) startPinch();
    else if (!touches.size) pinch = null;
    if (activePointer?.id === event.pointerId) activePointer = null;
  });
  canvas.addEventListener("pointerleave", event => {
    if (event.pointerType !== "touch") setHover(null);
  });
  canvas.addEventListener("focus", () => {
    cursor.visible = true;
    keyboardPreview = !activePointer;
    describeCursor();
    onPreviewChange();
    onDraw();
  });
  canvas.addEventListener("blur", () => {
    cursor.visible = false;
    keyboardPreview = false;
    setHover(null);
    onPreviewChange();
    onDraw();
  });
  canvas.addEventListener("keydown", event => {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    const directions = {
      ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1]
    };
    if (event.key === "Home" || event.key === "End") {
      const tile = event.key === "Home"
        ? simulation.units.find(unit => unit.side !== "defenders" && simulation.selected.has(unit.id))
        : getMap().objective;
      if (!tile) return;
      event.preventDefault();
      cursor.x = tile.x;
      cursor.y = tile.y;
      keyboardPreview = true;
      setHover(null);
      describeCursor();
      onPreviewChange();
      revealCursor();
      onDraw();
    } else if (directions[event.key]) {
      event.preventDefault();
      const [dx, dy] = directions[event.key];
      const map = getMap();
      keyboardPreview = true;
      cursor.x = Math.max(0, Math.min(map.cols - 1, cursor.x + dx));
      cursor.y = Math.max(0, Math.min(map.rows - 1, cursor.y + dy));
      setHover(null);
      describeCursor();
      onPreviewChange();
      revealCursor();
      onDraw();
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      if (canOrder()) keyboardOrder(event.shiftKey);
    } else if (["+", "=", "-", "_"].includes(event.key)) {
      event.preventDefault();
      const { width, height, tileH } = getLayout();
      const point = renderer.project(cursor.x, cursor.y);
      const screenX = cursor.visible ? point.x * camera.zoom + camera.x : width / 2;
      const screenY = cursor.visible ? (point.y + tileH / 2) * camera.zoom + camera.y : height / 2;
      zoomAt(screenX, screenY, event.key === "+" || event.key === "=" ? 1.15 : 1 / 1.15);
      if (cursor.visible) {
        revealCursor();
        onDraw();
      }
    }
  });
  canvas.addEventListener("wheel", event => {
    event.preventDefault();
    const rect = canvas.getBoundingClientRect();
    zoomAt(event.clientX - rect.left, event.clientY - rect.top, event.deltaY < 0 ? 1.12 : 1 / 1.12);
  }, { passive: false });
  document.getElementById("zoom-in").addEventListener("click", () => {
    const { width, height } = getLayout();
    zoomAt(width / 2, height / 2, 1.15);
  });
  document.getElementById("zoom-out").addEventListener("click", () => {
    const { width, height } = getLayout();
    zoomAt(width / 2, height / 2, 1 / 1.15);
  });

  return { camera, cursor, clampCamera, resetCamera, resetCursor, focusTile, describeCursor, previewDestination,
    setInspectTouch(enabled) { inspectTouch = enabled; setHover(null); },
    cancelPointer() { activePointer = null; touches.clear(); pinch = null; setHover(null); } };
}
