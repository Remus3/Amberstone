// rc-shell/test/overlay_layout_drag.test.js
//
// RC Overlay Doctrine section 3: widget drag-to-move. Pins the 2026-06-27
// behavior change - in ACTIVE mode the WHOLE widget body is a drag surface (not
// just the 3px corner grip), so the operator can reposition a panel without
// hunting the handle. PASSIVE keeps the body click-through (handle-only), and an
// interactive control inside the widget never starts a drag.
//
// Same zero-dep posture as overlay_layout_hide.test.js: a hand-rolled DOM stub
// (no jsdom), then dynamic-import the real ES module and drive genuine pointer
// events through the module's own _makeHandle wiring.

"use strict";

const test = require("node:test");
const assert = require("node:assert");
const path = require("path");
const url = require("url");

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

// A node with a real listener registry + a settable left/top style, plus the
// pointer-capture no-ops begin()/end() call (the stub swallows them harmlessly).
function makeNode() {
  const listeners = {};
  return {
    classList: makeClassList(),
    dataset: {},
    innerHTML: "",
    style: { left: "", top: "", setProperty() {}, removeProperty() {} },
    setAttribute() {},
    addEventListener(type, fn) {
      (listeners[type] || (listeners[type] = [])).push(fn);
    },
    querySelector() {
      return null;
    },
    appendChild() {},
    setPointerCapture() {},
    releasePointerCapture() {},
    _dispatch(type, ev) {
      for (const fn of listeners[type] || []) fn(ev);
      return ev;
    },
  };
}

// pointerdown event; target.closest decides the body-gate (null => draggable,
// truthy => an interactive control that must NOT start a drag).
function pointerDown(clientX, clientY, closestResult) {
  return {
    type: "pointerdown",
    target: { closest: () => (closestResult === undefined ? null : closestResult) },
    clientX,
    clientY,
    pointerId: 1,
    preventDefault() {},
  };
}

function pointerMove(clientX, clientY) {
  return { type: "pointermove", clientX, clientY, pointerId: 1 };
}

function installDom() {
  const docEl = { classList: makeClassList(), appendChild() {} };
  const body = { dataset: { shell: "overlay" } };
  const store = new Map();
  globalThis.document = {
    documentElement: docEl,
    body,
    querySelector() {
      return null;
    },
    createElement() {
      return makeNode();
    },
    addEventListener() {},
  };
  globalThis.window = { addEventListener() {} };
  globalThis.getComputedStyle = () => ({ zoom: "1" }); // _bodyZoom -> 1
  globalThis.localStorage = {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
  };
  return { docEl, store };
}

function setActive(dom, on) {
  if (on) dom.docEl.classList.add("rc-shell-active");
  else dom.docEl.classList.remove("rc-shell-active");
}

let mod;
test.before(async () => {
  installDom();
  const abs = path.join(__dirname, "..", "..", "web", "js", "lib", "overlay_layout.js");
  mod = await import(url.pathToFileURL(abs).href);
});

// --- (a) ACTIVE body-drag moves the widget -----------------------------------

test("ACTIVE: a body pointerdown + move repositions the widget (left/top + layout)", () => {
  const dom = installDom();
  setActive(dom, true);
  const I = mod._internals;
  I._setLayout({}); // empty -> origin is the widget's default (w.x, w.y)

  const w = I.WIDGETS[0];
  const el = makeNode();
  I._makeHandle(el, w);

  el._dispatch("pointerdown", pointerDown(300, 200)); // closest -> null (draggable)
  el._dispatch("pointermove", pointerMove(350, 230)); // delta +50, +30 at zoom 1

  assert.strictEqual(el.style.left, w.x + 50 + "px", "left advanced by the x delta");
  assert.strictEqual(el.style.top, w.y + 30 + "px", "top advanced by the y delta");
  assert.strictEqual(I._getLayout()[w.id].x, w.x + 50, "layout x updated");
  assert.strictEqual(I._getLayout()[w.id].y, w.y + 30, "layout y updated");
});

// --- (b) PASSIVE body-drag does NOT move (handle-only during play) -----------

test("PASSIVE: a body pointerdown does not start a drag", () => {
  const dom = installDom();
  setActive(dom, false);
  const I = mod._internals;
  I._setLayout({});

  const w = I.WIDGETS[0];
  const el = makeNode();
  I._makeHandle(el, w);

  el._dispatch("pointerdown", pointerDown(300, 200));
  el._dispatch("pointermove", pointerMove(350, 230));

  assert.strictEqual(el.style.left, "", "no position written in PASSIVE");
  assert.strictEqual(I._getLayout()[w.id], undefined, "no layout entry created");
});

// --- (c) ACTIVE but on an interactive control -> no drag ---------------------

test("ACTIVE: a pointerdown on an interactive control does not drag the panel", () => {
  const dom = installDom();
  setActive(dom, true);
  const I = mod._internals;
  I._setLayout({});

  const w = I.WIDGETS[0];
  const el = makeNode();
  I._makeHandle(el, w);

  // target.closest(_NO_BODY_DRAG) returns truthy => the gate must bail.
  el._dispatch("pointerdown", pointerDown(300, 200, {}));
  el._dispatch("pointermove", pointerMove(350, 230));

  assert.strictEqual(el.style.left, "", "interactive control press must not drag");
  assert.strictEqual(I._getLayout()[w.id], undefined, "no layout entry created");
});
