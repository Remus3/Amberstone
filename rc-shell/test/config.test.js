// rc-shell/test/config.test.js
//
// Pure-logic tests for config.js. NO electron. Run with: node --test test/

"use strict";

const test = require("node:test");
const assert = require("node:assert");

const {
  DEFAULT_ORIGIN,
  DEFAULT_PRESET,
  SIZE_PRESETS,
  defaultConfig,
  applyPreset,
  resolveConfig,
  clampPosition,
  originHost,
} = require("../src/config");

// ---- defaultConfig ----------------------------------------------------------

test("defaultConfig returns the standard preset dims + RC default origin", () => {
  const c = defaultConfig();
  assert.strictEqual(c.origin, DEFAULT_ORIGIN);
  assert.strictEqual(c.sizePreset, DEFAULT_PRESET);
  assert.strictEqual(c.width, SIZE_PRESETS[DEFAULT_PRESET].width);
  assert.strictEqual(c.height, SIZE_PRESETS[DEFAULT_PRESET].height);
  assert.strictEqual(c.alwaysOnTop, true);
  assert.strictEqual(c.x, null);
  assert.strictEqual(c.y, null);
});

test("DEFAULT_ORIGIN is the 2-PC dashboard origin", () => {
  assert.strictEqual(DEFAULT_ORIGIN, "https://legion-rc:8888");
});

// ---- resolveConfig precedence ----------------------------------------------

test("resolveConfig: defaults when saved + env are empty", () => {
  const c = resolveConfig({}, {});
  assert.strictEqual(c.origin, DEFAULT_ORIGIN);
  assert.strictEqual(c.width, SIZE_PRESETS.standard.width);
  assert.strictEqual(c.height, SIZE_PRESETS.standard.height);
});

test("resolveConfig: saved origin beats default", () => {
  const c = resolveConfig({ origin: "https://saved-host:9000" }, {});
  assert.strictEqual(c.origin, "https://saved-host:9000");
});

test("resolveConfig: env RC_ORIGIN beats saved AND default (highest precedence)", () => {
  const c = resolveConfig(
    { origin: "https://saved-host:9000" },
    { RC_ORIGIN: "https://127.0.0.1:8888" }
  );
  assert.strictEqual(c.origin, "https://127.0.0.1:8888");
});

test("resolveConfig: env RC_ORIGIN beats default when no saved origin", () => {
  const c = resolveConfig({}, { RC_ORIGIN: "https://127.0.0.1:8888" });
  assert.strictEqual(c.origin, "https://127.0.0.1:8888");
});

test("resolveConfig: blank/whitespace env RC_ORIGIN is ignored (does not wipe)", () => {
  const c1 = resolveConfig({ origin: "https://saved:9000" }, { RC_ORIGIN: "" });
  assert.strictEqual(c1.origin, "https://saved:9000");
  const c2 = resolveConfig({ origin: "https://saved:9000" }, { RC_ORIGIN: "   " });
  assert.strictEqual(c2.origin, "https://saved:9000");
});

test("resolveConfig: env RC_ORIGIN is trimmed", () => {
  const c = resolveConfig({}, { RC_ORIGIN: "  https://trim-me:8888  " });
  assert.strictEqual(c.origin, "https://trim-me:8888");
});

test("resolveConfig: saved width/height win over preset dims", () => {
  const c = resolveConfig({ width: 444, height: 999 }, {});
  assert.strictEqual(c.width, 444);
  assert.strictEqual(c.height, 999);
});

test("resolveConfig: saved sizePreset selects preset dims when width/height absent", () => {
  const c = resolveConfig({ sizePreset: "tall" }, {});
  assert.strictEqual(c.sizePreset, "tall");
  assert.strictEqual(c.width, SIZE_PRESETS.tall.width);
  assert.strictEqual(c.height, SIZE_PRESETS.tall.height);
});

test("resolveConfig: unknown saved sizePreset falls back to default preset", () => {
  const c = resolveConfig({ sizePreset: "ginormous" }, {});
  assert.strictEqual(c.sizePreset, DEFAULT_PRESET);
  assert.strictEqual(c.width, SIZE_PRESETS[DEFAULT_PRESET].width);
});

test("resolveConfig: garbage saved (null) does not throw, returns defaults", () => {
  const c = resolveConfig(null, null);
  assert.strictEqual(c.origin, DEFAULT_ORIGIN);
  assert.strictEqual(c.width, SIZE_PRESETS.standard.width);
});

test("resolveConfig: saved x/y kept when numeric; null otherwise", () => {
  const c1 = resolveConfig({ x: 100, y: 200 }, {});
  assert.strictEqual(c1.x, 100);
  assert.strictEqual(c1.y, 200);
  const c2 = resolveConfig({ x: "nope", y: undefined }, {});
  assert.strictEqual(c2.x, null);
  assert.strictEqual(c2.y, null);
});

test("resolveConfig: alwaysOnTop saved boolean wins, else default true", () => {
  assert.strictEqual(resolveConfig({ alwaysOnTop: false }, {}).alwaysOnTop, false);
  assert.strictEqual(resolveConfig({}, {}).alwaysOnTop, true);
});

test("resolveConfig: non-positive saved width/height fall back to preset", () => {
  const c = resolveConfig({ width: 0, height: -5 }, {});
  assert.strictEqual(c.width, SIZE_PRESETS.standard.width);
  assert.strictEqual(c.height, SIZE_PRESETS.standard.height);
});

// ---- applyPreset ------------------------------------------------------------

test("applyPreset: sets width/height/sizePreset from SIZE_PRESETS", () => {
  const c = applyPreset(defaultConfig(), "compact");
  assert.strictEqual(c.sizePreset, "compact");
  assert.strictEqual(c.width, SIZE_PRESETS.compact.width);
  assert.strictEqual(c.height, SIZE_PRESETS.compact.height);
});

test("applyPreset: all three presets resolve to their declared dims", () => {
  for (const name of ["compact", "standard", "tall"]) {
    const c = applyPreset(defaultConfig(), name);
    assert.strictEqual(c.width, SIZE_PRESETS[name].width);
    assert.strictEqual(c.height, SIZE_PRESETS[name].height);
  }
});

test("applyPreset: unknown preset returns config unchanged (no throw)", () => {
  const base = defaultConfig();
  const c = applyPreset(base, "nope");
  assert.strictEqual(c.width, base.width);
  assert.strictEqual(c.height, base.height);
  assert.strictEqual(c.sizePreset, base.sizePreset);
});

test("applyPreset: preserves other config fields (origin, alwaysOnTop, x/y)", () => {
  const base = Object.assign(defaultConfig(), {
    origin: "https://x:1",
    alwaysOnTop: false,
    x: 12,
    y: 34,
  });
  const c = applyPreset(base, "tall");
  assert.strictEqual(c.origin, "https://x:1");
  assert.strictEqual(c.alwaysOnTop, false);
  assert.strictEqual(c.x, 12);
  assert.strictEqual(c.y, 34);
});

// ---- clampPosition ----------------------------------------------------------

const DISPLAY = { x: 0, y: 0, width: 1920, height: 1080 };

test("clampPosition: in-bounds position is unchanged", () => {
  const r = clampPosition({ x: 100, y: 100, width: 520, height: 900 }, DISPLAY);
  assert.strictEqual(r.x, 100);
  assert.strictEqual(r.y, 100);
});

test("clampPosition: off the right/bottom edge is pulled back on-screen", () => {
  // window 520x900 at x=1800 would hang off the right; clamp to 1920-520=1400.
  const r = clampPosition({ x: 1800, y: 900, width: 520, height: 900 }, DISPLAY);
  assert.strictEqual(r.x, 1920 - 520);
  assert.strictEqual(r.y, 1080 - 900);
});

test("clampPosition: negative coords are pulled to the display origin", () => {
  const r = clampPosition({ x: -300, y: -50, width: 520, height: 900 }, DISPLAY);
  assert.strictEqual(r.x, 0);
  assert.strictEqual(r.y, 0);
});

test("clampPosition: far off-screen saved coords (stale 2nd monitor) clamp on", () => {
  // simulate a saved coord from a now-disconnected monitor at x=5000
  const r = clampPosition({ x: 5000, y: 3000, width: 380, height: 720 }, DISPLAY);
  assert.ok(r.x >= 0 && r.x <= 1920 - 380, "x within display");
  assert.ok(r.y >= 0 && r.y <= 1080 - 720, "y within display");
});

test("clampPosition: honors a non-zero display origin (multi-monitor offset)", () => {
  const right = { x: 1920, y: 0, width: 1920, height: 1080 };
  const r = clampPosition({ x: 1950, y: 100, width: 520, height: 900 }, right);
  assert.strictEqual(r.x, 1950); // in-bounds on the right display
  assert.strictEqual(r.y, 100);
  // and an x below that display's origin is pinned to it
  const r2 = clampPosition({ x: 0, y: 100, width: 520, height: 900 }, right);
  assert.strictEqual(r2.x, 1920);
});

test("clampPosition: window larger than display pins to origin (no NaN)", () => {
  const r = clampPosition({ x: 50, y: 50, width: 3000, height: 2000 }, DISPLAY);
  assert.strictEqual(r.x, 0);
  assert.strictEqual(r.y, 0);
});

test("clampPosition: null/missing x or y returns {x:null,y:null} (center me)", () => {
  assert.deepStrictEqual(clampPosition({ x: null, y: null }, DISPLAY), {
    x: null,
    y: null,
  });
  assert.deepStrictEqual(clampPosition({ width: 520, height: 900 }, DISPLAY), {
    x: null,
    y: null,
  });
});

test("clampPosition: garbage display bounds fall back to 1920x1080 (no throw)", () => {
  const r = clampPosition({ x: 100, y: 100, width: 520, height: 900 }, null);
  assert.strictEqual(r.x, 100);
  assert.strictEqual(r.y, 100);
});

// ---- originHost -------------------------------------------------------------

test("originHost: extracts host:port from an origin URL", () => {
  assert.strictEqual(originHost("https://legion-rc:8888"), "legion-rc:8888");
  assert.strictEqual(originHost("https://127.0.0.1:8888"), "127.0.0.1:8888");
});

test("originHost: malformed origin returns empty string (no throw)", () => {
  assert.strictEqual(originHost("not a url"), "");
  assert.strictEqual(originHost(""), "");
});
