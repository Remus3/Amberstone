// rc-shell/test/overlay_state.test.js
//
// node:test for the PURE overlay surface-switch state machine (no electron).

"use strict";

const test = require("node:test");
const assert = require("node:assert");

const ov = require("../src/overlay_state");

test("surfaceForMode: game modes -> overlay", () => {
  for (const m of ["sr", "aram", "arena", "tft", "brawl", "game"]) {
    assert.strictEqual(ov.surfaceForMode(m), ov.SURFACES.OVERLAY, m);
  }
});

test("surfaceForMode: out-of-game / unknown -> companion", () => {
  for (const m of ["client", "none", "", "lobby", "champ-select", "zzz"]) {
    assert.strictEqual(ov.surfaceForMode(m), ov.SURFACES.COMPANION, JSON.stringify(m));
  }
});

test("surfaceForMode: non-string -> companion (fail-soft)", () => {
  assert.strictEqual(ov.surfaceForMode(null), ov.SURFACES.COMPANION);
  assert.strictEqual(ov.surfaceForMode(undefined), ov.SURFACES.COMPANION);
  assert.strictEqual(ov.surfaceForMode(42), ov.SURFACES.COMPANION);
});

test("surfaceForMode: case + whitespace insensitive", () => {
  assert.strictEqual(ov.surfaceForMode("  SR  "), ov.SURFACES.OVERLAY);
  assert.strictEqual(ov.surfaceForMode("ArAm"), ov.SURFACES.OVERLAY);
});

test("resolveSurface: hidden override wins over any mode", () => {
  assert.strictEqual(ov.resolveSurface("sr", true), ov.SURFACES.HIDDEN);
  assert.strictEqual(ov.resolveSurface("client", true), ov.SURFACES.HIDDEN);
});

test("resolveSurface: not hidden -> mode-driven", () => {
  assert.strictEqual(ov.resolveSurface("sr", false), ov.SURFACES.OVERLAY);
  assert.strictEqual(ov.resolveSurface("client", false), ov.SURFACES.COMPANION);
  // non-bool hidden is treated as not-hidden.
  assert.strictEqual(ov.resolveSurface("sr", undefined), ov.SURFACES.OVERLAY);
});

test("overlayUrl: appends overlay=1", () => {
  assert.strictEqual(
    ov.overlayUrl("https://legion-rc:8888/"),
    "https://legion-rc:8888/?overlay=1"
  );
});

test("overlayUrl: preserves an existing query", () => {
  const out = ov.overlayUrl("https://legion-rc:8888/?ui_mock=1");
  assert.ok(out.includes("ui_mock=1"));
  assert.ok(out.includes("overlay=1"));
});

test("overlayUrl: malformed / non-string returned unchanged", () => {
  assert.strictEqual(ov.overlayUrl("not a url"), "not a url");
  assert.strictEqual(ov.overlayUrl(""), "");
  assert.strictEqual(ov.overlayUrl(null), null);
});

test("windowActions: overlay shows overlay, hides companion", () => {
  assert.deepStrictEqual(ov.windowActions(ov.SURFACES.OVERLAY), {
    companion: "hide",
    overlay: "show",
  });
});

test("windowActions: companion shows companion, hides overlay", () => {
  assert.deepStrictEqual(ov.windowActions(ov.SURFACES.COMPANION), {
    companion: "show",
    overlay: "hide",
  });
});

test("windowActions: hidden / unknown hides both (fail-safe to dark)", () => {
  assert.deepStrictEqual(ov.windowActions(ov.SURFACES.HIDDEN), {
    companion: "hide",
    overlay: "hide",
  });
  assert.deepStrictEqual(ov.windowActions("garbage"), {
    companion: "hide",
    overlay: "hide",
  });
});

test("normMode: trims, lowercases, non-string -> empty", () => {
  assert.strictEqual(ov.normMode("  ARAM "), "aram");
  assert.strictEqual(ov.normMode(null), "");
  assert.strictEqual(ov.normMode(7), "");
});

test("OVERLAY_DEFAULTS: poll cadence respects the >=500ms cost rule", () => {
  assert.ok(ov.OVERLAY_DEFAULTS.pollMs >= 500, "poll must not be sub-500ms");
  assert.strictEqual(ov.OVERLAY_DEFAULTS.clickThrough, true);
  assert.ok(typeof ov.OVERLAY_DEFAULTS.hotkeyToggle === "string");
});
