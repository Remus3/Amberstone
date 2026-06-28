// rc-shell/test/window_controls.test.js
//
// node:test for the PURE window-controls module (no electron). The companion is
// frameless, so min / close / always-on-top chrome is injected by the main
// process - these strings are what gets injected, and they call back over the
// window.rcShell preload bridge.

"use strict";

const test = require("node:test");
const assert = require("node:assert");

const wc = require("../src/window_controls");

// DOM stub rich enough to behaviorally run the mount JS: getElementById resolves
// against nodes appended to documentElement (the idempotence path), buttons
// capture their click listeners so a test can dispatch them, and classList /
// setAttribute are recorded.
function makeClassList() {
  const set = new Set();
  return {
    add: (c) => set.add(c),
    remove: (c) => set.delete(c),
    contains: (c) => set.has(c),
    _set: set,
  };
}

function makeNode(tag) {
  const listeners = {};
  return {
    tagName: tag,
    id: "",
    className: "",
    classList: makeClassList(),
    attrs: {},
    children: [],
    setAttribute(k, v) {
      this.attrs[k] = v;
    },
    addEventListener(type, fn) {
      (listeners[type] || (listeners[type] = [])).push(fn);
    },
    appendChild(node) {
      this.children.push(node);
      return node;
    },
    click() {
      for (const fn of listeners.click || []) fn({});
    },
  };
}

function makeFakeDocument() {
  const rootChildren = [];
  return {
    rootChildren,
    getElementById(id) {
      return rootChildren.find((c) => c.id === id) || null;
    },
    createElement(tag) {
      return makeNode(tag);
    },
    documentElement: {
      appendChild(node) {
        rootChildren.push(node);
        return node;
      },
    },
  };
}

// A bridge stub that records calls and resolves the always-on-top promises to a
// controllable value, so reflectPinned() can be exercised.
function makeBridge(initialAot) {
  const calls = [];
  let aot = !!initialAot;
  return {
    calls,
    api: {
      winMinimize: () => {
        calls.push("min");
      },
      winClose: () => {
        calls.push("close");
      },
      winToggleAlwaysOnTop: () => {
        calls.push("toggle");
        aot = !aot;
        return Promise.resolve(aot);
      },
      winGetAlwaysOnTop: () => {
        calls.push("get");
        return Promise.resolve(aot);
      },
    },
  };
}

const flush = () => new Promise((r) => setTimeout(r, 0));

test("WINDOW_CONTROLS_DEFAULTS: shape", () => {
  const d = wc.WINDOW_CONTROLS_DEFAULTS;
  assert.ok(typeof d.id === "string" && d.id.length > 0, "id non-empty string");
  assert.ok(typeof d.height === "number" && d.height >= 16, "height >= 16");
  assert.ok(typeof d.zIndex === "number", "zIndex number");
  assert.ok(typeof d.pinnedClass === "string" && d.pinnedClass.length > 0, "pinnedClass");
});

test("windowControlsCSS: cluster id + no-drag + the three control classes", () => {
  const css = wc.windowControlsCSS();
  assert.ok(css.includes("#" + wc.WINDOW_CONTROLS_DEFAULTS.id), css);
  assert.ok(css.includes("-webkit-app-region: no-drag"), css);
  assert.ok(css.includes("position: fixed"), css);
  assert.ok(css.includes("right: 0"), css);
  assert.ok(css.includes(".rc-winctl-min"), css);
  assert.ok(css.includes(".rc-winctl-close"), css);
  assert.ok(css.includes(".rc-winctl-top"), css);
});

test("windowControlsCSS: close hover is destructive-red, pinned state lights the chevron", () => {
  const css = wc.windowControlsCSS();
  assert.ok(css.includes(".rc-winctl-close:hover"), css);
  assert.ok(/#c4283b/i.test(css), "close hover uses a red");
  assert.ok(css.includes("." + wc.WINDOW_CONTROLS_DEFAULTS.pinnedClass), css);
});

test("windowControlsCSS: 7-bit ASCII only (repo hard rule)", () => {
  const css = wc.windowControlsCSS();
  assert.ok(/^[\x00-\x7F]*$/.test(css), "CSS must be pure ASCII (no smart quotes / dashes / glyphs)");
});

test("windowControlsMountJS: idempotence guard + bridge method references", () => {
  const js = wc.windowControlsMountJS();
  assert.ok(js.includes("getElementById"), js);
  assert.ok(js.includes(wc.WINDOW_CONTROLS_DEFAULTS.id), js);
  assert.ok(js.includes("winToggleAlwaysOnTop"), js);
  assert.ok(js.includes("winGetAlwaysOnTop"), js);
  assert.ok(js.includes("winMinimize"), js);
  assert.ok(js.includes("winClose"), js);
  assert.ok(/^[\x00-\x7F]*$/.test(js), "mount JS must be pure ASCII");
});

test("windowControlsMountJS: syntactically valid JS", () => {
  assert.doesNotThrow(() => new Function(wc.windowControlsMountJS()));
  assert.doesNotThrow(() => new Function(wc.windowControlsMountJS({ id: "x-ctl" })));
});

test("windowControlsMountJS: mounts exactly one cluster with three buttons, idempotent", async () => {
  const doc = makeFakeDocument();
  const br = makeBridge(true);
  const run = new Function("document", "window", wc.windowControlsMountJS());
  run(doc, { rcShell: br.api });
  run(doc, { rcShell: br.api }); // second mount is a no-op (guard)
  await flush();

  assert.strictEqual(doc.rootChildren.length, 1, "exactly one cluster mounted");
  const box = doc.rootChildren[0];
  assert.strictEqual(box.id, wc.WINDOW_CONTROLS_DEFAULTS.id);
  assert.strictEqual(box.children.length, 3, "three control buttons");
  // initial always-on-top=true -> cluster reflects the pinned class.
  assert.ok(box.classList.contains(wc.WINDOW_CONTROLS_DEFAULTS.pinnedClass), "pinned reflected on mount");
});

test("windowControlsMountJS: clicking each button drives the matching bridge call", async () => {
  const doc = makeFakeDocument();
  const br = makeBridge(false);
  new Function("document", "window", wc.windowControlsMountJS())(doc, { rcShell: br.api });
  await flush(); // initial winGetAlwaysOnTop

  const box = doc.rootChildren[0];
  const [topBtn, minBtn, closeBtn] = box.children;

  topBtn.click(); // -> winToggleAlwaysOnTop
  minBtn.click(); // -> winMinimize
  closeBtn.click(); // -> winClose
  await flush();

  assert.ok(br.calls.includes("toggle"), "toggle called");
  assert.ok(br.calls.includes("min"), "minimize called");
  assert.ok(br.calls.includes("close"), "close called");
  // toggling from false -> true lights the pinned class.
  assert.ok(box.classList.contains(wc.WINDOW_CONTROLS_DEFAULTS.pinnedClass), "pin state updated after toggle");
});

test("windowControlsMountJS: degrades to no-op when the bridge is absent", async () => {
  const doc = makeFakeDocument();
  const run = new Function("document", "window", wc.windowControlsMountJS());
  assert.doesNotThrow(() => run(doc, {})); // window has no rcShell
  const box = doc.rootChildren[0];
  assert.doesNotThrow(() => box.children[0].click()); // clicking does nothing, no throw
});
