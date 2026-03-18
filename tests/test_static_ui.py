from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from .utils import repo_root

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is required for frontend runtime tests")


def _run_node_json(script: str) -> dict[str, object]:
    result = subprocess.run(
        [NODE, "-e", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        cwd=repo_root(),
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return json.loads(result.stdout)


def test_static_ui_queue_row_treats_hostile_filename_as_text() -> None:
    script = r"""
globalThis.window = globalThis;
require("./src/markforge/static/ui_helpers.js");
const helpers = globalThis.MarkforgeUiHelpers;

class FakeClassList {
  constructor() {
    this.values = new Set();
  }
  add(value) {
    this.values.add(value);
  }
}

class FakeElement {
  constructor(tagName) {
    this.tagName = tagName;
    this.children = [];
    this.attributes = {};
    this.textContent = "";
    this.className = "";
    this.classList = new FakeClassList();
    this.listeners = {};
  }
  setAttribute(name, value) {
    this.attributes[name] = value;
  }
  appendChild(child) {
    this.children.push(child);
    return child;
  }
  addEventListener(name, handler) {
    this.listeners[name] = handler;
  }
}

const document = {
  createElement(tagName) {
    return new FakeElement(tagName);
  }
};

const row = helpers.createQueueRow(
  document,
  { id: "file-1", name: "<img src=x onerror=1>.png", width: 12, height: 34, size: 56 },
  "file-1",
  (size) => `${size} B`,
  () => {}
);

const nameText = row.children[0].children[1].children[0].textContent;
const detailsText = row.children[0].children[1].children[1].textContent;
const chipText = row.children[1].textContent;

console.log(JSON.stringify({ nameText, detailsText, chipText, hasClick: Boolean(row.listeners.click) }));
"""
    payload = _run_node_json(script)
    assert payload["nameText"] == "<img src=x onerror=1>.png"
    assert payload["detailsText"] == "12×34 · 56 B"
    assert payload["chipText"] == "Selected"
    assert payload["hasClick"] is True


def test_static_ui_settings_preserve_zero_values_and_reject_invalid_color() -> None:
    script = r"""
globalThis.window = globalThis;
require("./src/markforge/static/ui_helpers.js");
const helpers = globalThis.MarkforgeUiHelpers;

const zeroValues = helpers.gatherSettings({
  textValue: "Zero",
  fontSizeValue: "56",
  fillValue: "#000000",
  blendValue: "normal",
  angleValue: "0",
  paddingValue: "0",
  opacityValue: "0",
  tile: true,
  center: false,
  antialias: true,
  offsetValue: "0, 0",
  fontId: "font-test"
});

let invalidMessage = null;
try {
  helpers.gatherSettings({
    textValue: "Bad",
    fontSizeValue: "56",
    fillValue: "not-a-color",
    blendValue: "normal",
    angleValue: "0",
    paddingValue: "0",
    opacityValue: "0",
    tile: true,
    center: false,
    antialias: true,
    offsetValue: "0, 0",
    fontId: null
  });
} catch (err) {
  invalidMessage = err.message;
}

console.log(JSON.stringify({ zeroValues, invalidMessage }));
"""
    payload = _run_node_json(script)
    zero_values = payload["zeroValues"]
    assert zero_values["angle"] == 0
    assert zero_values["opacity"] == 0
    assert zero_values["offset_x"] == 0
    assert zero_values["offset_y"] == 0
    assert zero_values["font_id"] == "font-test"
    assert payload["invalidMessage"] == "Invalid color. Use #RGB or #RRGGBB."


def test_static_ui_uses_helper_file_and_system_fonts_only() -> None:
    html = Path("src/markforge/static/index.html").read_text(encoding="utf-8")
    assert '<script src="/static/ui_helpers.js"></script>' in html
    assert 'id="font-input"' not in html
    assert "/api/pick-font" not in html
    assert "/api/upload-font" not in html
    assert "Custom…" not in html
