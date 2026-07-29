# arch: RM-126 - overlay drag listeners must bind once per mount | section=web | frozen=no
"""Node-driven behavioral tests for the RM-126 drag-listener leak.

The sibling `test_overlay_drag_listener_leak.py` parses the source and pins the
SHAPE of the guard. This file pins the BEHAVIOR, which is what actually matters:
drive `_makeHandle` repeatedly against one persistent element, dropping the
`.ovx-handle` child between passes exactly as a renderer rebuild does, and count
the listeners that really get attached.

Browser-free. `web/js/lib/overlay_layout.js` has zero imports and exports
`_makeHandle` through `_internals`, so the ESM module loads under a stub DOM.
Mirrors the node-subprocess pattern in tests/test_coach_choices_trigger_render.py.

The identity assertion is the load-bearing one. A fix that skips the re-bind but
returns a FRESH `begin` closure would keep the bind count flat and still be
broken: the el-level pointermove/pointerup listeners close over the FIRST call's
drag state, so a later handle driving a different closure writes state nobody
reads. Pinning that `_installDrag` hands back the SAME function object across
passes is what rules that out.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
MODULE = REPO / "web" / "js" / "lib" / "overlay_layout.js"

# Stub DOM: only the surface _makeHandle / _installDrag touch at ATTACH time.
# The drag handlers themselves are never invoked here - this measures wiring.
_STUB = """
const BINDS = [];
function mkEl(tag) {
  const el = {
    tagName: tag, dataset: {}, style: {}, children: [], className: "",
    id: "", title: "", innerHTML: "", _probe: tag,
    classList: { add() {}, remove() {}, contains() { return false; } },
    setAttribute() {}, getAttribute() { return null; }, removeAttribute() {},
    appendChild(c) { this.children.push(c); return c; },
    removeChild(c) { this.children = this.children.filter((x) => x !== c); },
    remove() {}, closest() { return null; },
    getBoundingClientRect() { return {left:0,top:0,width:100,height:50}; },
    setPointerCapture() {}, releasePointerCapture() {},
    addEventListener(type, fn) { BINDS.push({host: this._probe, type, fn}); },
    removeEventListener() {},
    querySelector(sel) {
      if (sel.includes("ovx-handle")) {
        return this.children.find((c) => c.className === "ovx-handle") || null;
      }
      return null;
    },
    querySelectorAll() { return []; },
  };
  return el;
}
globalThis.window = {
  addEventListener() {}, removeEventListener() {},
  innerWidth: 1920, innerHeight: 1080,
  localStorage: { getItem() { return null; }, setItem() {} },
  matchMedia() { return { matches: false, addEventListener() {} }; },
};
globalThis.localStorage = globalThis.window.localStorage;
globalThis.document = {
  body: mkEl("body"), documentElement: mkEl("html"), createElement: mkEl,
  getElementById() { return null; }, querySelector() { return null; },
  querySelectorAll() { return []; },
  addEventListener() {}, removeEventListener() {},
};
globalThis.MutationObserver = class { observe() {} disconnect() {} };

const {_internals} = await import('__URI__');
const el = mkEl("div");
el._probe = "el";
const w = {id: "probe", sel: "#probe", tier: 1};

const PASSES = 3;
for (let i = 0; i < PASSES; i += 1) {
  // A renderer rebuild destroys the handle child but keeps the widget element.
  el.children = el.children.filter((c) => c.className !== "ovx-handle");
  _internals._makeHandle(el, w);
}

const elBinds = BINDS.filter((b) => b.host === "el");
const handleBinds = BINDS.filter((b) => b.host !== "el");
// Every pass binds the fresh handle child; all of them must be the SAME begin.
const beginIdentical = handleBinds.every((b) => b.fn === handleBinds[0].fn);
process.stdout.write(JSON.stringify({
  passes: PASSES,
  elTypes: elBinds.map((b) => b.type),
  handleCount: handleBinds.length,
  beginIdentical,
}));
"""


def _run_node(script: str) -> dict:
    node = shutil.which("node")
    if not node:  # pragma: no cover - node is present on Legion
        pytest.skip("node not on PATH")
    full = script.replace("__URI__", MODULE.resolve().as_uri())
    res = subprocess.run(
        [node, "--input-type=module", "-e", full],
        capture_output=True, text=True, cwd=str(REPO), timeout=30,
    )
    assert res.returncode == 0, f"node failed: {res.stderr.strip()}"
    return json.loads(res.stdout)


@pytest.fixture(scope="module")
def probe() -> dict:
    return _run_node(_STUB)


def test_el_level_listeners_bind_exactly_once_across_repaints(probe: dict) -> None:
    # Unfixed, this grows linearly: 4 per pass, 12 after three passes.
    assert probe["elTypes"] == [
        "pointermove", "pointerup", "pointercancel", "pointerdown"
    ], (
        f"{len(probe['elTypes'])} el-level listeners after {probe['passes']} "
        "repaints - the persistent widget element is accumulating drag "
        "listeners (RM-126)"
    )


def test_handle_child_rebinds_on_every_pass(probe: dict) -> None:
    # The handle is destroyed and recreated each repaint, so it MUST rebind -
    # an over-broad latch that also skipped this would silently kill dragging.
    assert probe["handleCount"] == probe["passes"], (
        f"handle bound {probe['handleCount']} times across {probe['passes']} "
        "passes - the recreated .ovx-handle child lost its pointerdown"
    )


def test_every_pass_hands_back_the_same_begin_closure(probe: dict) -> None:
    # The anti-desync pin. See the module docstring.
    assert probe["beginIdentical"], (
        "_installDrag returned a NEW begin closure on a later pass - the "
        "surviving el-level listeners close over the first call's drag state, "
        "so the rebuilt handle would drive state nothing reads (RM-126)"
    )
