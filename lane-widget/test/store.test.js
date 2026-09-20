// lane-widget/test/store.test.js
//
// The store is the rc-shell/src/store.js pattern applied to a DIFFERENT state
// file: atomic tmp+rename write, and a load() that never throws. The path is a
// parameter, so nothing here needs electron.

"use strict";

const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const store = require("../src/store.js");

function tmpDir() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "lane-widget-store-"));
}

test("STATE_FILE_NAME is the widget's own file, not rc-shell's", () => {
  assert.strictEqual(store.STATE_FILE_NAME, "lane-widget-state.json");
});

test("load on a missing file returns the fallback and does not throw", () => {
  const dir = tmpDir();
  const got = store.load(path.join(dir, "nope", "missing.json"), { a: 1 });
  assert.deepStrictEqual(got, { a: 1 });
});

test("load with no fallback returns an empty object", () => {
  const dir = tmpDir();
  assert.deepStrictEqual(store.load(path.join(dir, "missing.json")), {});
});

test("load on corrupt JSON returns the fallback", () => {
  const dir = tmpDir();
  const f = path.join(dir, "s.json");
  fs.writeFileSync(f, "{ not json at all", "utf8");
  assert.deepStrictEqual(store.load(f, { fallback: true }), { fallback: true });
});

test("load on valid JSON that is not an object returns the fallback", () => {
  const dir = tmpDir();
  for (const raw of ["[1,2,3]", "42", "null", '"text"']) {
    const f = path.join(dir, "x.json");
    fs.writeFileSync(f, raw, "utf8");
    assert.deepStrictEqual(store.load(f, { d: 1 }), { d: 1 }, raw);
  }
});

test("save then load round-trips", () => {
  const dir = tmpDir();
  const f = path.join(dir, "s.json");
  assert.strictEqual(store.save(f, { x: 12, showFree: false }), true);
  assert.deepStrictEqual(store.load(f), { x: 12, showFree: false });
});

test("save creates the parent directory", () => {
  const dir = tmpDir();
  const f = path.join(dir, "deep", "deeper", "s.json");
  assert.strictEqual(store.save(f, { ok: 1 }), true);
  assert.strictEqual(fs.existsSync(f), true);
});

test("save writes through a .tmp sibling and leaves none behind", () => {
  const dir = tmpDir();
  const f = path.join(dir, "s.json");
  store.save(f, { ok: 1 });
  assert.strictEqual(fs.existsSync(f + ".tmp"), false);
  assert.deepStrictEqual(fs.readdirSync(dir), ["s.json"]);
});

test("save returns false instead of throwing when the path is unusable", () => {
  const dir = tmpDir();
  const f = path.join(dir, "s.json");
  store.save(f, { ok: 1 });
  // A file cannot be a parent directory - mkdir/write must fail softly.
  assert.strictEqual(store.save(path.join(f, "child", "s.json"), { ok: 1 }), false);
});

test("DEFAULTS carries exactly the persisted keys", () => {
  assert.deepStrictEqual(Object.keys(store.DEFAULTS).sort(), [
    "alwaysOnTop",
    "fastMs",
    "height",
    "opacity",
    "showFree",
    "width",
    "x",
    "y",
  ]);
});

test("normalizeState fills defaults and drops junk", () => {
  const n = store.normalizeState({ nonsense: true, width: "wide", opacity: 5 });
  assert.strictEqual(n.width, store.DEFAULTS.width);
  assert.strictEqual(n.nonsense, undefined);
  assert.ok(n.opacity <= 1 && n.opacity > 0, "opacity clamped into (0,1]");
});

test("normalizeState keeps good values and clamps fastMs", () => {
  const n = store.normalizeState({
    x: 10,
    y: 20,
    width: 500,
    height: 400,
    // In range: at or above MIN_OPACITY, so it must survive untouched. It used
    // to be 0.5, which the 0.85 contrast floor now clamps up.
    opacity: 0.9,
    alwaysOnTop: false,
    showFree: false,
    fastMs: 10,
  });
  assert.strictEqual(n.x, 10);
  assert.strictEqual(n.y, 20);
  assert.strictEqual(n.width, 500);
  assert.strictEqual(n.height, 400);
  assert.strictEqual(n.opacity, 0.9);
  assert.strictEqual(n.alwaysOnTop, false);
  assert.strictEqual(n.showFree, false);
  assert.ok(n.fastMs >= store.MIN_FAST_MS, "fastMs floored");
});

// The regression this pins: the clamp floored at 0.1 while the UI slider
// floored higher, so a hand-edited state file could persist a functionally
// invisible panel that the slider could never reach to undo. The floor is now
// MIN_OPACITY and the two are COUPLED - moving one without the other reopens
// exactly this hole.
test("normalizeState clamps a hand-edited low opacity UP to the floor", () => {
  for (const bad of [0.1, 0.3, 0.5, 0.84, 0.0001]) {
    const n = store.normalizeState({ opacity: bad });
    assert.strictEqual(
      n.opacity,
      store.MIN_OPACITY,
      "opacity " + bad + " must be raised to the floor, not honoured"
    );
  }
});

test("normalizeState clamps opacity down to MAX_OPACITY", () => {
  for (const bad of [1.0001, 5, 1e9]) {
    assert.strictEqual(store.normalizeState({ opacity: bad }).opacity, store.MAX_OPACITY, String(bad));
  }
});

test("MIN_OPACITY is the documented contrast floor and DEFAULTS clears it", () => {
  // If this moves, the renderer's slider floor MUST move with it.
  assert.strictEqual(store.MIN_OPACITY, 0.85);
  assert.strictEqual(store.MAX_OPACITY, 1);
  assert.ok(
    store.DEFAULTS.opacity >= store.MIN_OPACITY &&
      store.DEFAULTS.opacity <= store.MAX_OPACITY,
    "the default must itself be inside the clamp range"
  );
});

test("normalizeState on garbage input returns the defaults", () => {
  for (const bad of [null, undefined, 7, "x", []]) {
    assert.deepStrictEqual(store.normalizeState(bad), store.DEFAULTS);
  }
});

test("normalizeState leaves x/y null when never positioned", () => {
  const n = store.normalizeState({});
  assert.strictEqual(n.x, null);
  assert.strictEqual(n.y, null);
});
