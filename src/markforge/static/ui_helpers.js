(function (global) {
  const MARKFORGE_DEFAULTS = {
    text: "MARKFORGE",
    fontSize: 56,
    angle: -30,
    padding: 0,
    opacity: 0.18,
  };

  function normalizeColor(value) {
    if (!value && value !== 0) return null;
    const raw = String(value).trim().toLowerCase();
    if (!raw) return null;
    if (raw === "0") return "#000000";
    let hex = raw;
    if (hex.startsWith("0x")) hex = hex.slice(2);
    if (hex.startsWith("#")) hex = hex.slice(1);
    if (/^[0-9a-f]{3}$/i.test(hex)) {
      return `#${hex.split("").map((c) => c + c).join("")}`.toUpperCase();
    }
    if (/^[0-9a-f]{6}$/i.test(hex)) {
      return `#${hex}`.toUpperCase();
    }
    return null;
  }

  function parseIntegerInput(value, fallback) {
    const parsed = Number.parseInt(value, 10);
    return Number.isFinite(parsed) ? parsed : fallback;
  }

  function parseNumberInput(value, fallback) {
    const parsed = Number.parseFloat(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  }

  function parseOffset(value) {
    const parts = String(value || "")
      .split(/[, ]+/)
      .map((part) => part.trim())
      .filter(Boolean);
    const x = parseIntegerInput(parts[0] || "0", 0);
    const y = parseIntegerInput(parts[1] || "0", 0);
    return { x, y };
  }

  function gatherSettings(values) {
    const normalized = normalizeColor(values.fillValue);
    if (!normalized) {
      throw new Error("Invalid color. Use #RGB or #RRGGBB.");
    }
    const offset = parseOffset(values.offsetValue);
    return {
      text: String(values.textValue || "").trim() || MARKFORGE_DEFAULTS.text,
      font_size: parseIntegerInput(values.fontSizeValue, MARKFORGE_DEFAULTS.fontSize),
      fill: normalized,
      blend: values.blendValue,
      angle: parseNumberInput(values.angleValue, MARKFORGE_DEFAULTS.angle),
      padding: parseIntegerInput(values.paddingValue, MARKFORGE_DEFAULTS.padding),
      opacity: Math.max(0, Math.min(1, parseNumberInput(values.opacityValue, MARKFORGE_DEFAULTS.opacity))),
      tile: Boolean(values.tile),
      center: Boolean(values.center),
      antialias: Boolean(values.antialias),
      offset_x: offset.x,
      offset_y: offset.y,
      font_id: values.fontId || null,
    };
  }

  function createQueueRow(doc, file, selectedId, formatBytes, onSelect) {
    const row = doc.createElement("div");
    row.className = "file";
    if (file.id === selectedId) {
      row.classList.add("selected");
    }

    const left = doc.createElement("div");
    left.className = "left";

    const badge = doc.createElement("div");
    badge.className = "badge";
    badge.setAttribute("aria-hidden", "true");

    const meta = doc.createElement("div");
    meta.className = "meta";

    const nameEl = doc.createElement("p");
    nameEl.className = "name";
    nameEl.textContent = file.name;

    const detailsEl = doc.createElement("p");
    detailsEl.className = "details";
    detailsEl.textContent = `${file.width}×${file.height} · ${formatBytes(file.size)}`;

    meta.appendChild(nameEl);
    meta.appendChild(detailsEl);
    left.appendChild(badge);
    left.appendChild(meta);

    const chip = doc.createElement("span");
    chip.className = "chip";
    chip.textContent = file.id === selectedId ? "Selected" : "Queued";

    row.appendChild(left);
    row.appendChild(chip);
    row.addEventListener("click", onSelect);
    return row;
  }

  global.MarkforgeUiHelpers = {
    createQueueRow,
    gatherSettings,
    normalizeColor,
    parseIntegerInput,
    parseNumberInput,
    parseOffset,
  };
})(typeof window !== "undefined" ? window : globalThis);
