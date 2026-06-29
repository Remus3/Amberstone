// rc-shell/test/overlay_flash.test.js
//
// First-match overlay flash regression (headless run 2026-06-29-01). On the FIRST
// match launch the transparent Electron overlay popped to full screen BEFORE its
// content laid out: applySurface() called overlayWindow.showInactive() in the same
// tick as createOverlayWindow(), so the 2560x1440 window appeared mid-load and the
// widgets reflowed from their natural unscaled/unpositioned ("max size") paint to
// their saved tiny boxes. Two gates close it:
//   1) main.js defers the FIRST show to the window's 'ready-to-show' (first paint).
//      The decision is the pure shouldShowOverlayNow() so it is testable here
//      without electron.
//   2) the renderer hides .ovx-widget (visibility:hidden) until overlay_layout sets
//      .ovx-ready on <body> after the FIRST _placeAll pass, so the first paint stays
//      hidden until laid out.
//
// .ovx-ready is a NEW load-time gate, distinct from the per-widget .ovx-hidden gate
// (retired panel-set CSS, b16bfce1) - the two are never conflated here.
//
// overlay_layout.js is a browser ES module with no DOM and the harness ships no
// jsdom, so (mirroring overlay_layout_hide.test.js) a minimal hand-rolled DOM stub
// drives the real initOverlayLayout pass; the CSS gate is asserted by reading the
// authored stylesheet.

"use strict";

const test = require("node:test");
const assert = require("node:assert");
const path = require("path");
const url = require("url");
const fs = require("fs");

const ov = require("../src/overlay_state");

// --- (1) main.js show-gate decision (pure) -----------------------------------
// shouldShowOverlayNow(overlayReady, surfaceWantsOverlay): applySurface may show
// the overlay immediately ONLY once the window has fired 'ready-to-show'. Before
// that the 'ready-to-show' handler owns the first show (gated on the same
// surfaceWantsOverlay), so applySurface must NOT show early - that early show is
// the flash.

test("shouldShowOverlayNow: ready + wanted -> show now", () => {
  assert.strictEqual(ov.shouldShowOverlayNow(true, true), true);
});

test("shouldShowOverlayNow: not-ready defers the first show (no early flash)", () => {
  // The window has not painted yet; the ready-to-show handler will show it.
  assert.strictEqual(ov.shouldShowOverlayNow(false, true), false);
});

test("shouldShowOverlayNow: surface does not want the overlay -> never show", () => {
  assert.strictEqual(ov.shouldShowOverlayNow(true, false), false);
  assert.strictEqual(ov.shouldShowOverlayNow(false, false), false);
});

test("shouldShowOverlayNow: non-true args coerce to false (no truthy leak)", () => {
  for (const v of [undefined, null, 1, "yes", {}, NaN]) {
    assert.strictEqual(ov.shouldShowOverlayNow(v, true), false, JSON.stringify(v));
    assert.strictEqual(ov.shouldShowOverlayNow(true, v), false, JSON.stringify(v));
  }
});

// --- (2a) CSS gate: .ovx-widget hidden until .ovx-ready ----------------------

test("overlay.css hides the widget field until .ovx-ready (visibility, not display)", () => {
  const cssPath = path.join(__dirname, "..", "..", "web", "css", "overlay.css");
  const css = fs.readFileSync(cssPath, "utf8");

  // A rule scoped to the overlay body, gated on :not(.ovx-ready), targeting
  // .ovx-widget with visibility:hidden. Tolerant of whitespace + an !important.
  const re =
    /body\[data-shell="overlay"\]:not\(\.ovx-ready\)[^{]*\.ovx-widget[^{]*\{[^}]*visibility\s*:\s*hidden/;
  assert.ok(
    re.test(css),
    "expected a body[data-shell=overlay]:not(.ovx-ready) .ovx-widget { visibility: hidden } gate"
  );

  // It must be a visibility gate, never display:none on this selector (display
  // would drop the box and defeat positioning/measurement during the gated paint).
  const ready = css.match(/:not\(\.ovx-ready\)[^{]*\.ovx-widget[^{]*\{[^}]*\}/);
  assert.ok(ready, "ovx-ready gate block present");
  assert.ok(!/display\s*:\s*none/.test(ready[0]), "the ready gate must not use display:none");
});

// --- (2b) overlay_layout sets .ovx-ready after the first apply pass ----------

function makeClassList() {
  const set = new Set();
  return {
    add: (c) => set.add(c),
    remove: (c) => set.delete(c),
    contains: (c) => set.has(c),
    toggle: (c, on) => {
      const want = on === undefined ? !set.has(c) : !!on;
      if (want) set.add(c);
      else set.delete(c);
      return want;
    },
  };
}

function makeNode() {
  const listeners = {};
  return {
    classList: makeClassList(),
    dataset: {},
    innerHTML: "",
    style: { _props: {}, left: "", top: "", opacity: "", setProperty(k, v) { this._props[k] = v; }, removeProperty(k) { delete this._props[k]; } },
    setAttribute() {},
    addEventListener(type, fn) { (listeners[type] || (listeners[type] = [])).push(fn); },
    querySelector() { return null; },
    appendChild() {},
  };
}

// Install a DOM where every WIDGETS selector resolves (so _placeAll runs a full
// pass) and <body> carries the overlay shell flag + a real classList we assert on.
function installDom() {
  const bodyClass = makeClassList();
  const body = { dataset: { shell: "overlay" }, classList: bodyClass };
  const docEl = { classList: makeClassList(), appendChild() {} };
  const store = new Map();
  const grid = makeNode();

  globalThis.document = {
    documentElement: docEl,
    body,
    querySelector(sel) {
      if (sel === "#am-grid") return grid;
      if (sel === "#w-launcher") return null;
      return makeNode(); // every widget mount resolves -> a full _placeAll pass
    },
    createElement() { return makeNode(); },
    addEventListener() {},
  };
  globalThis.window = { addEventListener() {} };
  globalThis.getComputedStyle = () => ({ zoom: "1" });
  globalThis.localStorage = {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
  };
  globalThis.MutationObserver = class {
    observe() {}
    disconnect() {}
  };
  return { body, bodyClass, store };
}

let mod;
test.before(async () => {
  installDom();
  const abs = path.join(__dirname, "..", "..", "web", "js", "lib", "overlay_layout.js");
  mod = await import(url.pathToFileURL(abs).href);
});

test("initOverlayLayout sets .ovx-ready on <body> after the first place pass", () => {
  const dom = installDom();
  assert.strictEqual(dom.bodyClass.contains("ovx-ready"), false, "precondition: not ready");

  mod.initOverlayLayout();

  assert.strictEqual(
    dom.bodyClass.contains("ovx-ready"),
    true,
    "the field must be marked ready once the first _placeAll pass completes"
  );
});

test("initOverlayLayout: a non-overlay body is never marked ready (inert on the dashboard)", () => {
  const dom = installDom();
  dom.body.dataset.shell = ""; // not the overlay surface
  mod.initOverlayLayout();
  assert.strictEqual(dom.bodyClass.contains("ovx-ready"), false);
});
