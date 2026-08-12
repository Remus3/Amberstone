// rc-shell/test/overlay_launcher.test.js
//
// Launcher control widget + layout control center (operator 2026-06-28). The
// launcher is a small always-visible square the operator drags anywhere and taps
// (in ACTIVE) to open a menu: per-panel show/hide toggles, "reset all", and the
// panel-set / back-to-play actions. It is the in-game escape hatch back to a
// panel that was right-click-hidden - the only other un-hide path (Alt+Shift+R)
// is Electron-globalShortcut-only and so dead while League holds foreground.
//
// Same zero-dep posture as overlay_layout_hide.test.js: a hand-rolled DOM stub on
// globalThis, then a dynamic import of the ES module, driving the module's own
// pure seams (_setHidden / _toggleHidden / _shellAction) - no production behavior
// is mocked.

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

function makeNode() {
  const listeners = {};
  return {
    classList: makeClassList(),
    dataset: {},
    innerHTML: "",
    textContent: "",
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
    _dispatch(type, ev) {
      for (const fn of listeners[type] || []) fn(ev);
      return ev;
    },
  };
}

function installDom() {
  const docEl = { classList: makeClassList(), appendChild() {} };
  const body = { dataset: { shell: "overlay" } };
  const store = new Map();
  const nodes = {}; // sel -> node, for the querySelector override

  globalThis.document = {
    documentElement: docEl,
    body,
    querySelector(sel) {
      return nodes[sel] || null;
    },
    createElement() {
      return makeNode();
    },
    addEventListener() {},
    _nodes: nodes,
  };
  globalThis.window = { addEventListener() {} };
  globalThis.getComputedStyle = () => ({ zoom: "1" });
  globalThis.localStorage = {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
  };
  return { docEl, store, nodes };
}

function setActive(dom, on) {
  if (on) dom.docEl.classList.add("rc-shell-active");
  else dom.docEl.classList.remove("rc-shell-active");
}

const PERSIST_FLUSH_MS = 500;
const flushPersist = () => new Promise((r) => setTimeout(r, PERSIST_FLUSH_MS));

let mod;
test.before(async () => {
  installDom();
  const abs = path.join(__dirname, "..", "..", "web", "js", "lib", "overlay_layout.js");
  mod = await import(url.pathToFileURL(abs).href);
});

// --- registry shape: labels + the launcher is a non-panel control ------------

test("every panel widget carries a human label for the menu", () => {
  const I = mod._internals;
  for (const w of I.WIDGETS) {
    assert.ok(
      typeof w.label === "string" && w.label.length > 0,
      `widget ${w.id} must have a non-empty label`
    );
  }
});

test("LAUNCHER is a control widget, never a panel (excluded from WIDGETS)", () => {
  const I = mod._internals;
  assert.ok(I.LAUNCHER && typeof I.LAUNCHER.id === "string", "LAUNCHER descriptor exists");
  assert.strictEqual(I.LAUNCHER.tier, "control", "launcher is the control tier");
  const inPanels = I.WIDGETS.some((w) => w.id === I.LAUNCHER.id);
  assert.strictEqual(inPanels, false, "launcher must NOT appear in the panel list");
});

// Riot compliance 2026-08-11: w-enemyspells (the enemy summoner-spell
// tap-tracker) was removed, and with it the "spell panel is a click-through
// zone" contract. w-threat (the enemy CD ledger) had already gone 2026-07-05.
// Neither may come back - Riot bans tracking enemy summoner-spell cooldowns.
test("no enemy summoner-spell or cooldown widget is registered (Riot compliance)", () => {
  const I = mod._internals;
  const banned = I.WIDGETS.filter((w) => w.id === "w-enemyspells" || w.id === "w-threat" || w.id === "w-spike");
  assert.deepStrictEqual(banned, [], "w-enemyspells / w-threat / w-spike must stay removed");
});

// --- _setHidden / _toggleHidden: bidirectional show/hide for the menu ---------

test("_setHidden(false) reopens a previously hidden panel and persists it", async () => {
  const dom = installDom();
  const I = mod._internals;
  I._setLayout({});
  const w = I.WIDGETS[0];
  const el = makeNode();
  dom.nodes[w.sel] = el; // so _setHidden's querySelector(w.sel) finds the mount

  // hide, then reopen via the menu path.
  I._setHidden(w, true);
  assert.strictEqual(I._getLayout()[w.id].hidden, true);
  assert.strictEqual(el.classList.contains("ovx-hidden"), true, "hide applied to mount");

  I._setHidden(w, false);
  assert.strictEqual(I._getLayout()[w.id].hidden, false, "reopened in layout");
  assert.strictEqual(el.classList.contains("ovx-hidden"), false, "mount un-hidden");

  await flushPersist();
  assert.strictEqual(
    JSON.parse(dom.store.get(I.LS_KEY))[w.id].hidden,
    false,
    "reopen persisted to the authoritative store"
  );
});

test("_toggleHidden flips state and returns the new hidden value", () => {
  const dom = installDom();
  const I = mod._internals;
  I._setLayout({});
  const w = I.WIDGETS[1];
  dom.nodes[w.sel] = makeNode();

  const first = I._toggleHidden(w); // shown -> hidden
  assert.strictEqual(first, true);
  assert.strictEqual(I._posFor(w).hidden, true);

  const second = I._toggleHidden(w); // hidden -> shown
  assert.strictEqual(second, false);
  assert.strictEqual(I._posFor(w).hidden, false);
});

// --- _shellAction: the panel-set / back-to-play bridge -----------------------

test("_shellAction sends the exact payload through the rcShell bridge", () => {
  installDom();
  const I = mod._internals;
  const sent = [];
  globalThis.window.rcShell = { overlayAction: (m) => sent.push(m) };

  assert.strictEqual(I._shellAction({ action: "set-panel", panelSet: "build" }), true);
  assert.strictEqual(I._shellAction({ action: "set-active" }), true);
  assert.deepStrictEqual(sent, [
    { action: "set-panel", panelSet: "build" },
    { action: "set-active" },
  ]);
});

test("_shellAction degrades to a no-op (no throw) when the bridge is absent", () => {
  installDom(); // window has no rcShell
  const I = mod._internals;
  assert.strictEqual(I._shellAction({ action: "set-active" }), false);
});

// --- per-panel opacity + scale (the menu sliders) ----------------------------

test("_setOpacity clamps to [0.3,1], applies inline opacity, persists", async () => {
  const dom = installDom();
  const I = mod._internals;
  I._setLayout({});
  const w = I.WIDGETS[0];
  const el = makeNode();
  dom.nodes[w.sel] = el;

  I._setOpacity(w, 0.5);
  assert.strictEqual(I._posFor(w).opacity, 0.5);
  assert.strictEqual(el.style.opacity, "0.5", "dimmed opacity applied inline");

  I._setOpacity(w, 5);   // out of range high -> clamps to 1
  assert.strictEqual(I._posFor(w).opacity, 1);
  // opacity 1 is the default -> inline style is removed (clean DOM)
  assert.strictEqual(el.style.opacity, "", "opacity 1 clears the inline style");

  I._setOpacity(w, 0.05); // out of range low -> clamps to 0.3
  assert.strictEqual(I._posFor(w).opacity, 0.3);

  await flushPersist();
  assert.strictEqual(JSON.parse(dom.store.get(I.LS_KEY))[w.id].opacity, 0.3, "opacity persisted");
});

test("_setScale clamps to [0.5,1.6], drives --ovx-scale, persists", async () => {
  const dom = installDom();
  const I = mod._internals;
  I._setLayout({});
  const w = I.WIDGETS[1];
  const el = makeNode();
  dom.nodes[w.sel] = el;

  I._setScale(w, 1.4);
  assert.strictEqual(I._posFor(w).scale, 1.4);
  assert.strictEqual(el.style._props["--ovx-scale"], "1.4", "scale drives the CSS var");

  I._setScale(w, 9);   // clamps to 1.6
  assert.strictEqual(I._posFor(w).scale, 1.6);
  I._setScale(w, 0.1); // clamps to 0.5
  assert.strictEqual(I._posFor(w).scale, 0.5);

  await flushPersist();
  assert.strictEqual(JSON.parse(dom.store.get(I.LS_KEY))[w.id].scale, 0.5, "scale persisted");
});

test("_posFor defaults opacity to 1 and scale to 1 when unset", () => {
  installDom();
  const I = mod._internals;
  I._setLayout({});
  const p = I._posFor(I.WIDGETS[0]);
  assert.strictEqual(p.opacity, 1);
  assert.strictEqual(p.scale, 1);
});

// --- regression: the existing reset still works with the launcher present ----

test("resetOverlayLayout reopens a menu-hidden panel and leaves the launcher", () => {
  const dom = installDom();
  const I = mod._internals;
  I._setLayout({});
  const w = I.WIDGETS[0];
  const el = makeNode();
  dom.nodes[w.sel] = el;

  I._setHidden(w, true);
  assert.strictEqual(el.classList.contains("ovx-hidden"), true);

  mod.resetOverlayLayout();
  assert.deepStrictEqual(I._getLayout(), {}, "reset clears the layout");
  assert.strictEqual(el.classList.contains("ovx-hidden"), false, "panel reopened by reset");
  // launcher has no hidden default -> stays visible after a reset (escape hatch).
  assert.strictEqual(I._posFor(I.LAUNCHER).hidden, false, "launcher survives reset visible");
});
