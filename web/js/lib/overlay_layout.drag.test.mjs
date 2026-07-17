// web/js/lib/overlay_layout.drag.test.mjs
//
// RM-05 round-2 drag/move regression suite. Run with `node --test` (same
// runner + zero-dep hand-rolled DOM stub posture as overlay_layout.test.mjs
// and rc-shell/test/overlay_layout_drag.test.js - no jsdom in this repo).
//
// Pins the three operator-reported live-overlay failures:
//  (a) drag anchored to the raw STORED (x,y) while the widget RENDERS at a
//      clamped / bottom-anchored position - grabbing it teleported the panel
//      or dead-zoned the cursor. The drag must start from the effective
//      rendered position (_effectiveXY mirrors _applyPos's decision).
//  (b) move/up listeners lived only on the mount node, so a mid-drag panel
//      re-render (or a failed pointer capture once the cursor left the 3px
//      handle) silently killed the drag; and the rc-shell zone machine
//      hit-tests e.target per move, so a captured drag un-zoned the window.
//      The drag must track at window level and mark el [data-rc-zone].
//  (c) border/chrome presses (target === el) and presses belonging to a
//      nested/overlapping widget started a drag of the whole container
//      instead of the intended widget; a launcher-menu row-gap press armed a
//      whole-launcher drag and toggled the menu on release.

import test from "node:test";
import assert from "node:assert";

import { _internals } from "./overlay_layout.js";

const I = _internals;

// --- stubs -------------------------------------------------------------------

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

// A mount node with a real listener registry, an attribute map (the zone mark
// needs has/set/removeAttribute), a settable offsetHeight (tall-widget origin
// measurement) and isConnected (mid-drag re-render simulation).
function makeNode() {
  const listeners = {};
  const attrs = {};
  const node = {
    classList: makeClassList(),
    dataset: {},
    innerHTML: "",
    isConnected: true,
    offsetHeight: 0,
    style: {
      left: "",
      top: "",
      bottom: "",
      opacity: "",
      setProperty() {},
      removeProperty() {},
    },
    setAttribute(k, v) {
      attrs[k] = String(v);
    },
    removeAttribute(k) {
      delete attrs[k];
    },
    hasAttribute(k) {
      return Object.prototype.hasOwnProperty.call(attrs, k);
    },
    _attrs: attrs,
    addEventListener(type, fn) {
      (listeners[type] || (listeners[type] = [])).push(fn);
    },
    // _makeHandle stores its handle via appendChild; querySelector returns it
    // so the idempotency guard behaves like the real DOM.
    _children: [],
    appendChild(child) {
      node._children.push(child);
      return child;
    },
    querySelector(sel) {
      if (typeof sel === "string" && sel.indexOf(".ovx-handle") !== -1) {
        return node._children.find((c) => c.className === "ovx-handle") || null;
      }
      return null;
    },
    setPointerCapture() {
      node._captured = true;
    },
    releasePointerCapture() {
      node._captured = false;
    },
    _dispatch(type, ev) {
      for (const fn of listeners[type] || []) fn(ev);
      return ev;
    },
  };
  return node;
}

// Window stub with a real listener registry so the window-level drag tracking
// (attach in begin, detach in end) is observable. Set semantics match the real
// addEventListener dedup of an identical (type, fn) pair.
function makeWindow() {
  const listeners = {};
  return {
    innerWidth: 1920,
    innerHeight: 1080,
    addEventListener(type, fn) {
      (listeners[type] || (listeners[type] = new Set())).add(fn);
    },
    removeEventListener(type, fn) {
      if (listeners[type]) listeners[type].delete(fn);
    },
    _dispatch(type, ev) {
      for (const fn of [...(listeners[type] || [])]) fn(ev);
      return ev;
    },
    _count(type) {
      return listeners[type] ? listeners[type].size : 0;
    },
  };
}

function installDom() {
  const docEl = { classList: makeClassList(), appendChild() {} };
  const nodes = {};
  const store = new Map();
  globalThis.document = {
    documentElement: docEl,
    body: { dataset: { shell: "overlay" }, classList: makeClassList() },
    querySelector: (sel) => nodes[sel] || null,
    createElement: () => {
      const n = makeNode();
      // real elements expose className assignment; _makeHandle sets it.
      let cls = "";
      Object.defineProperty(n, "className", {
        get: () => cls,
        set: (v) => {
          cls = v;
        },
      });
      return n;
    },
    createTextNode: (s) => ({ nodeValue: String(s) }),
    addEventListener() {},
  };
  globalThis.window = makeWindow();
  globalThis.getComputedStyle = () => ({ zoom: "1" }); // _bodyZoom -> 1
  globalThis.localStorage = {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
  };
  return { docEl, nodes, store };
}

function setActive(dom, on) {
  if (on) dom.docEl.classList.add("rc-shell-active");
  else dom.docEl.classList.remove("rc-shell-active");
}

// Pointer events. `closestMap` keys are matched by substring against the
// selector the code passes, so the stub can answer the interactive-control
// list and ".ovx-widget" differently (a real closest walks ancestors).
function pDown(x, y, closestMap, target) {
  const t = target || {
    closest: (sel) => {
      if (!closestMap) return null;
      for (const key of Object.keys(closestMap)) {
        if (sel.indexOf(key) !== -1) return closestMap[key];
      }
      return null;
    },
  };
  return { type: "pointerdown", target: t, clientX: x, clientY: y, pointerId: 1, preventDefault() {} };
}

function pMove(x, y) {
  return { type: "pointermove", clientX: x, clientY: y, pointerId: 1 };
}

function pUp(x, y) {
  return { type: "pointerup", clientX: x, clientY: y, pointerId: 1 };
}

// Press the injected drag handle (the always-grabbable path) of a wired mount.
function handleOf(el) {
  const h = el._children.find((c) => c.className === "ovx-handle");
  assert.ok(h, "handle was appended by _makeHandle");
  return h;
}

const W_LEAD = () => I.WIDGETS.find((w) => w.id === "w-lead");
const W_BUILD = () => I.WIDGETS.find((w) => w.id === "w-build");

// --- (a) pure effective-origin math -------------------------------------------

test("_effectiveXY clamps a stale off-field stored position", () => {
  const c = I._effectiveXY("w-lead", 5000, 5000, 1920, 1080, NaN);
  assert.strictEqual(c.x, 1920 - I.MIN_VISIBLE);
  assert.strictEqual(c.y, 1080 - I.MIN_VISIBLE);
});

test("_effectiveXY bottom-anchors a tall widget in the lower half (mirrors _applyPos)", () => {
  // stored y=900 but the panel renders bottom-anchored: top = 1080 - 16 - 600.
  const c = I._effectiveXY("w-build", 70, 900, 1920, 1080, 600);
  assert.strictEqual(c.x, 70);
  assert.strictEqual(c.y, 1080 - 16 - 600);
});

test("_effectiveXY leaves a tall widget in the upper half at its stored spot", () => {
  const c = I._effectiveXY("w-build", 70, 200, 1920, 1080, 600);
  assert.strictEqual(c.y, 200);
});

test("_effectiveXY ignores height for non-tall widgets and non-finite heights", () => {
  assert.strictEqual(I._effectiveXY("w-lead", 100, 900, 1920, 1080, 600).y, 900);
  assert.strictEqual(I._effectiveXY("w-build", 70, 900, 1920, 1080, NaN).y, 900);
});

// --- (a) drag anchors at the rendered position, not the raw stored one --------

test("drag of a stale off-screen save tracks the cursor 1:1 from the first tick", () => {
  const dom = installDom();
  setActive(dom, false);
  const w = W_LEAD();
  I._setLayout({ [w.id]: { x: 5000, y: 300 } }); // renders clamped at x=1872
  const el = makeNode();
  I._makeHandle(el, w);

  handleOf(el)._dispatch("pointerdown", pDown(500, 400));
  el._dispatch("pointermove", pMove(490, 400)); // 10px left, no dead zone

  assert.strictEqual(el.style.left, 1920 - I.MIN_VISIBLE - 10 + "px",
    "widget must move immediately from its clamped render position");
});

test("tall bottom-anchored widget does not teleport when grabbed", () => {
  const dom = installDom();
  setActive(dom, false);
  const w = W_BUILD();
  I._setLayout({ [w.id]: { x: 70, y: 900 } });
  const el = makeNode();
  el.dataset.ovxId = w.id;
  el.offsetHeight = 600; // rendered top = 1080 - 16 - 600 = 464
  I._makeHandle(el, w);

  handleOf(el)._dispatch("pointerdown", pDown(100, 500));
  el._dispatch("pointermove", pMove(110, 510));

  assert.strictEqual(el.style.top, 464 + 10 + "px",
    "first move tick must continue from the rendered (bottom-anchored) top");
  assert.strictEqual(el.style.left, 70 + 10 + "px");
});

// --- (b) drags survive leaving the handle / losing the mount ------------------

test("pointermove/up at WINDOW level keep tracking after the cursor leaves el", () => {
  const dom = installDom();
  setActive(dom, false);
  const w = W_LEAD();
  I._setLayout({});
  const el = makeNode();
  I._makeHandle(el, w);

  handleOf(el)._dispatch("pointerdown", pDown(300, 200));
  // No el dispatch at all - the cursor left the mount; only window sees moves.
  globalThis.window._dispatch("pointermove", pMove(350, 230));

  assert.strictEqual(el.style.left, w.x + 50 + "px", "window-level move tracked");
  assert.strictEqual(el.style.top, w.y + 30 + "px");

  globalThis.window._dispatch("pointerup", pUp(350, 230));
  assert.strictEqual(el.classList.contains("ovx-dragging"), false, "drag ended");
  assert.strictEqual(globalThis.window._count("pointermove"), 0,
    "window listeners detached on end");

  globalThis.window._dispatch("pointermove", pMove(900, 900));
  assert.strictEqual(el.style.left, w.x + 50 + "px", "no tracking after end");
});

test("drag marks el a click-through zone for its duration (and restores it)", () => {
  const dom = installDom();
  setActive(dom, false);
  const w = W_LEAD();
  I._setLayout({});
  const el = makeNode();
  I._makeHandle(el, w);

  handleOf(el)._dispatch("pointerdown", pDown(300, 200));
  assert.ok(el.hasAttribute("data-rc-zone"),
    "el must be a zone mid-drag so the shell keeps the window interactive");

  globalThis.window._dispatch("pointerup", pUp(300, 200));
  assert.ok(!el.hasAttribute("data-rc-zone"), "temporary zone mark removed");
});

test("a widget that was already a zone keeps its zone mark after a drag", () => {
  const dom = installDom();
  setActive(dom, false);
  const w = I.WIDGETS.find((x) => x.zone === true);
  I._setLayout({});
  const el = makeNode();
  el.setAttribute("data-rc-zone", "");
  I._makeHandle(el, w);

  handleOf(el)._dispatch("pointerdown", pDown(10, 10));
  globalThis.window._dispatch("pointerup", pUp(10, 10));
  assert.ok(el.hasAttribute("data-rc-zone"), "pre-existing zone mark preserved");
});

test("a mid-drag mount rebuild does not kill the drag (writes go to the live node)", () => {
  const dom = installDom();
  setActive(dom, false);
  const w = W_LEAD();
  I._setLayout({});
  const el = makeNode();
  I._makeHandle(el, w);

  handleOf(el)._dispatch("pointerdown", pDown(300, 200));
  // Renderer rebuilt the mount: the wired node is orphaned, a fresh node is live.
  el.isConnected = false;
  const fresh = makeNode();
  dom.nodes[w.sel] = fresh;

  globalThis.window._dispatch("pointermove", pMove(350, 230));
  assert.strictEqual(fresh.style.left, w.x + 50 + "px",
    "position must land on the re-rendered live mount");
});

// --- (c) hit-testing: borders and foreign widgets never start a body drag -----

test("ACTIVE: a border/chrome press (target === el) does not start a drag", () => {
  const dom = installDom();
  setActive(dom, true);
  const w = W_LEAD();
  I._setLayout({});
  const el = makeNode();
  I._makeHandle(el, w);

  el._dispatch("pointerdown", pDown(300, 200, null, el));
  el._dispatch("pointermove", pMove(350, 230));

  assert.strictEqual(el.style.left, "", "border press must not drag the panel");
  assert.strictEqual(I._getLayout()[w.id], undefined, "no layout entry created");
});

test("ACTIVE: a press inside a nested/overlapping widget does not drag this one", () => {
  const dom = installDom();
  setActive(dom, true);
  const w = W_LEAD();
  I._setLayout({});
  const el = makeNode();
  I._makeHandle(el, w);

  const foreignWidget = makeNode();
  el._dispatch("pointerdown", pDown(300, 200, { ".ovx-widget": foreignWidget }));
  el._dispatch("pointermove", pMove(350, 230));

  assert.strictEqual(el.style.left, "", "press belongs to the other widget");
  assert.strictEqual(I._getLayout()[w.id], undefined, "no layout entry created");
});

test("ACTIVE: a content-child press still body-drags this widget (2026-06-27 keep)", () => {
  const dom = installDom();
  setActive(dom, true);
  const w = W_LEAD();
  I._setLayout({});
  const el = makeNode();
  I._makeHandle(el, w);

  el._dispatch("pointerdown", pDown(300, 200, { ".ovx-widget": el }));
  el._dispatch("pointermove", pMove(350, 230));

  assert.strictEqual(el.style.left, w.x + 50 + "px", "content press drags");
  assert.strictEqual(I._getLayout()[w.id].x, w.x + 50);
});

// --- (c) launcher: menu presses never arm a launcher drag/tap ------------------

test("a press inside the open launcher menu neither drags the launcher nor re-taps", () => {
  const dom = installDom();
  setActive(dom, false);
  I._setLayout({});
  const grid = makeNode();
  dom.nodes["#am-grid"] = grid;
  const el = I._ensureLauncher();
  assert.ok(el, "launcher created");
  const menu = el._children.find((c) => c.className === "ovx-launcher-menu");
  assert.ok(menu, "menu child exists");

  // Row-gap / label / border press inside the menu: bubbles to the launcher el.
  el._dispatch("pointerdown", pDown(40, 40, { ".ovx-launcher-menu": menu }));
  el._dispatch("pointermove", pMove(80, 90));
  el._dispatch("pointerup", pUp(80, 90));

  assert.strictEqual(I._getLayout()[I.LAUNCHER.id], undefined,
    "menu press must not move the launcher");
  assert.strictEqual(menu.classList.contains("ovx-menu-open"), false,
    "menu press must not toggle the menu closed/open");
});

test("a press on the launcher square itself still taps (menu toggles open)", () => {
  const dom = installDom();
  setActive(dom, false);
  I._setLayout({});
  const grid = makeNode();
  dom.nodes["#am-grid"] = grid;
  const el = I._ensureLauncher();
  const menu = el._children.find((c) => c.className === "ovx-launcher-menu");

  el._dispatch("pointerdown", pDown(30, 30));
  el._dispatch("pointerup", pUp(30, 30)); // no movement past THRESH => tap

  assert.strictEqual(menu.classList.contains("ovx-menu-open"), true,
    "square tap opens the menu");
});
