// rc-shell/test/overlay_layout_hide.test.js
//
// RC Overlay Doctrine section 2/3: the per-widget HIDE affordance. The READ side
// (web/js/lib/overlay_layout.js applying a per-widget `hidden` flag) was already
// covered by the durable-mirror string contracts in overlay_settings_ipc.test.js
// + overlay_state.test.js; this file pins the WRITE side that sets it from the
// UI - the ACTIVE-only right-click (contextmenu) hide.
//
// overlay_layout.js is a browser ES module with no DOM, and the harness ships no
// jsdom (matches the existing overlay node tests' zero-dep posture). So this test
// builds a MINIMAL hand-rolled DOM stub - just the surface the hide path touches
// (classList, style, dataset, a real addEventListener/dispatch for contextmenu,
// localStorage, getComputedStyle) - installs it on globalThis, then dynamic-
// imports the ES module and drives a genuine contextmenu Event through the real
// listener. No production behavior is mocked: the module's own _installHideMenu /
// _hideWidget / resetOverlayLayout run against the stub.

"use strict";

const test = require("node:test");
const assert = require("node:assert");
const path = require("path");
const url = require("url");

// --- minimal DOM stub --------------------------------------------------------

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

// A tiny EventTarget-ish node: real listener registry + dispatch so the module's
// own el.addEventListener("contextmenu", ...) is exercised end to end.
function makeNode() {
  const listeners = {};
  return {
    classList: makeClassList(),
    dataset: {},
    innerHTML: "",
    style: {
      _props: {},
      left: "",
      top: "",
      setProperty(k, v) {
        this._props[k] = v;
      },
      removeProperty(k) {
        delete this._props[k];
      },
    },
    setAttribute() {},
    addEventListener(type, fn) {
      (listeners[type] || (listeners[type] = [])).push(fn);
    },
    querySelector() {
      return null;
    },
    appendChild() {},
    // test helper: fire a real event object through the registered listeners.
    _dispatch(type, ev) {
      for (const fn of listeners[type] || []) fn(ev);
      return ev;
    },
  };
}

function makeContextMenuEvent() {
  return {
    type: "contextmenu",
    defaultPrevented: false,
    preventDefault() {
      this.defaultPrevented = true;
    },
  };
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
  globalThis.getComputedStyle = () => ({ zoom: "1" });
  globalThis.localStorage = {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
  };
  // _persist() debounces with setTimeout; node has it globally. No rcShell bridge
  // is installed, so the mirror call path degrades to localStorage-only (exactly
  // the plain-browser branch), which is what we assert against.
  return { docEl, store };
}

function setActive(dom, on) {
  if (on) dom.docEl.classList.add("rc-shell-active");
  else dom.docEl.classList.remove("rc-shell-active");
}

// _persist() debounces the localStorage write ~400ms; wait past it so the
// durable mirror assertion sees the settled value (the in-memory _layout is
// already updated synchronously - this only flushes the storage write).
const PERSIST_FLUSH_MS = 500;
const flushPersist = () => new Promise((r) => setTimeout(r, PERSIST_FLUSH_MS));

// Dynamic import AFTER the globals are installed (the module reads document /
// window lazily inside functions, but import once and reuse).
let mod;
test.before(async () => {
  installDom(); // baseline globals so the import never sees bare globals
  const abs = path.join(__dirname, "..", "..", "web", "js", "lib", "overlay_layout.js");
  mod = await import(url.pathToFileURL(abs).href);
});

// --- (a) ACTIVE contextmenu sets hidden:true + persists ----------------------

test("contextmenu while ACTIVE: sets hidden:true, preventDefault, persists", async () => {
  const dom = installDom();
  setActive(dom, true);
  const I = mod._internals;
  I._setLayout({});

  const w = I.WIDGETS[0];
  const el = makeNode();
  I._installHideMenu(el, w);

  const ev = makeContextMenuEvent();
  el._dispatch("contextmenu", ev);

  assert.strictEqual(ev.defaultPrevented, true, "ACTIVE must preventDefault");
  assert.strictEqual(
    I._getLayout()[w.id].hidden,
    true,
    "hidden must be set true in the layout"
  );
  // applied to the mount via the SAME read-side path (.ovx-hidden toggled on).
  assert.strictEqual(el.classList.contains("ovx-hidden"), true, "mount hidden applied");

  // persisted to the authoritative localStorage store (no new key invented).
  await flushPersist();
  const raw = dom.store.get(I.LS_KEY);
  assert.ok(raw, "layout persisted to LS_KEY");
  assert.strictEqual(JSON.parse(raw)[w.id].hidden, true, "persisted hidden:true");
});

test("contextmenu while ACTIVE: a separate _hideWidget call also persists hidden", async () => {
  const dom = installDom();
  setActive(dom, true);
  const I = mod._internals;
  I._setLayout({});

  const w = I.WIDGETS[1];
  const el = makeNode();
  I._hideWidget(el, w); // the primitive the listener calls

  assert.strictEqual(I._getLayout()[w.id].hidden, true);
  await flushPersist();
  assert.strictEqual(JSON.parse(dom.store.get(I.LS_KEY))[w.id].hidden, true);
});

// --- (b) PASSIVE contextmenu is a pure no-op ---------------------------------

test("contextmenu while PASSIVE: no preventDefault, no layout mutation, no persist", async () => {
  const dom = installDom();
  setActive(dom, false); // PASSIVE / click-through
  const I = mod._internals;
  I._setLayout({});

  const w = I.WIDGETS[0];
  const el = makeNode();
  I._installHideMenu(el, w);

  const ev = makeContextMenuEvent();
  el._dispatch("contextmenu", ev);

  // The whole point: the event falls through to the game underneath.
  assert.strictEqual(ev.defaultPrevented, false, "PASSIVE must NOT preventDefault");
  assert.deepStrictEqual(I._getLayout(), {}, "PASSIVE must not mutate the layout");
  assert.strictEqual(el.classList.contains("ovx-hidden"), false, "no hide applied");
  // even past the debounce window, nothing was scheduled to persist.
  await flushPersist();
  assert.strictEqual(dom.store.has(I.LS_KEY), false, "PASSIVE must not persist");
});

test("_isActiveMode tracks the rc-shell-active class on <html>", () => {
  const dom = installDom();
  const I = mod._internals;
  setActive(dom, false);
  assert.strictEqual(I._isActiveMode(), false);
  setActive(dom, true);
  assert.strictEqual(I._isActiveMode(), true);
});

// --- (c) a hidden widget is cleared by the existing Alt+Shift+R reset ---------

test("resetOverlayLayout clears a hidden widget (existing reset restores it)", () => {
  const dom = installDom();
  setActive(dom, true);
  const I = mod._internals;
  I._setLayout({});

  const w = I.WIDGETS[0];
  const el = makeNode();
  // place the mount where _placeAll would find it so reset's _placeAll re-applies.
  document.querySelector = (sel) => (sel === w.sel ? el : null);

  I._installHideMenu(el, w);
  el._dispatch("contextmenu", makeContextMenuEvent());
  assert.strictEqual(I._getLayout()[w.id].hidden, true, "precondition: hidden");
  assert.strictEqual(el.classList.contains("ovx-hidden"), true);

  // the EXISTING reset (the Alt+Shift+R path) - clears _layout + re-places.
  mod.resetOverlayLayout();

  assert.deepStrictEqual(I._getLayout(), {}, "reset clears the layout");
  assert.strictEqual(
    el.classList.contains("ovx-hidden"),
    false,
    "reset un-hides the widget via the read-side path"
  );
});
