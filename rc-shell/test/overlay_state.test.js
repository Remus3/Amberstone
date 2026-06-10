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

// --- Phase 4a: ACTIVE auto-revert ------------------------------------------

test("OVERLAY_DEFAULTS: activeRevertDelayMs defaults to 20000", () => {
  assert.strictEqual(ov.OVERLAY_DEFAULTS.activeRevertDelayMs, 20000);
});

test("makeActiveRevert: starts disarmed; due() false even far in the future", () => {
  const r = ov.makeActiveRevert({ delayMs: 100, now: () => 0 });
  assert.strictEqual(r.armed(), false);
  assert.strictEqual(r.due(999999), false);
});

test("makeActiveRevert: arm then due fires at/after the deadline only", () => {
  const r = ov.makeActiveRevert({ delayMs: 200, now: () => 1000 });
  r.arm();
  assert.strictEqual(r.armed(), true);
  assert.strictEqual(r.due(1100), false); // before deadline
  assert.strictEqual(r.due(1199), false);
  assert.strictEqual(r.due(1200), true); // exactly at deadline
});

test("makeActiveRevert: due is one-shot (disarms after firing)", () => {
  const r = ov.makeActiveRevert({ delayMs: 50, now: () => 0 });
  r.arm();
  assert.strictEqual(r.due(60), true);
  assert.strictEqual(r.armed(), false);
  assert.strictEqual(r.due(999), false);
});

test("makeActiveRevert: cancel disarms", () => {
  const r = ov.makeActiveRevert({ delayMs: 50, now: () => 0 });
  r.arm();
  r.cancel();
  assert.strictEqual(r.armed(), false);
  assert.strictEqual(r.due(999), false);
});

test("makeActiveRevert: re-arm resets the deadline (hotkey press resets)", () => {
  let t = 0;
  const r = ov.makeActiveRevert({ delayMs: 100, now: () => t });
  r.arm(); // deadline 100
  t = 80;
  r.arm(); // reset -> deadline 180
  assert.strictEqual(r.due(120), false); // old deadline passed, new one not
  assert.strictEqual(r.due(180), true);
});

test("makeActiveRevert: delayMs defaults to OVERLAY_DEFAULTS.activeRevertDelayMs", () => {
  const r = ov.makeActiveRevert({ now: () => 5000 });
  r.arm();
  assert.strictEqual(r.due(5000 + 19999), false);
  assert.strictEqual(r.due(5000 + 20000), true);
});

test("makeActiveRevert: no opts does not throw (Date.now clock)", () => {
  const r = ov.makeActiveRevert();
  assert.strictEqual(r.armed(), false);
  r.arm();
  assert.strictEqual(r.armed(), true);
  assert.strictEqual(r.due(Date.now() - 1), false); // deadline is ~20s out
  r.cancel();
  assert.strictEqual(r.armed(), false);
});

// --- Phase 4b: backend-offline poll backoff ---------------------------------

test("nextPollDelay: zero failures -> base cadence (reset on success)", () => {
  assert.strictEqual(ov.nextPollDelay(0, 2000), 2000);
});

test("nextPollDelay: exponential doubling per consecutive failure", () => {
  assert.strictEqual(ov.nextPollDelay(1, 2000), 4000);
  assert.strictEqual(ov.nextPollDelay(2, 2000), 8000);
});

test("nextPollDelay: capped at 15000ms", () => {
  assert.strictEqual(ov.nextPollDelay(3, 2000), 15000); // raw 16000 -> cap
  assert.strictEqual(ov.nextPollDelay(10, 2000), 15000);
  assert.strictEqual(ov.nextPollDelay(1000, 2000), 15000); // no overflow
});

test("nextPollDelay: garbage inputs fail soft", () => {
  assert.strictEqual(ov.nextPollDelay(-3, 2000), 2000);
  assert.strictEqual(ov.nextPollDelay(NaN, 2000), 2000);
  assert.strictEqual(ov.nextPollDelay(null, 2000), 2000);
  assert.strictEqual(ov.nextPollDelay(0, 0), ov.OVERLAY_DEFAULTS.pollMs);
  assert.strictEqual(ov.nextPollDelay(0), ov.OVERLAY_DEFAULTS.pollMs);
});

test("nextPollDelay: fractional failure counts floor", () => {
  assert.strictEqual(ov.nextPollDelay(1.9, 2000), 4000);
});

// --- Phase 4c: overlay panel-set cycle ---------------------------------------

test("PANEL_SETS: spec sec 5 cycle order", () => {
  assert.deepStrictEqual([...ov.PANEL_SETS], ["coach", "build", "threat"]);
});

test("cyclePanelSet: coach -> build -> threat -> coach", () => {
  assert.strictEqual(ov.cyclePanelSet("coach"), "build");
  assert.strictEqual(ov.cyclePanelSet("build"), "threat");
  assert.strictEqual(ov.cyclePanelSet("threat"), "coach");
});

test("cyclePanelSet: unknown / null / non-string -> first set (coach)", () => {
  assert.strictEqual(ov.cyclePanelSet(null), "coach");
  assert.strictEqual(ov.cyclePanelSet(undefined), "coach");
  assert.strictEqual(ov.cyclePanelSet("zzz"), "coach");
  assert.strictEqual(ov.cyclePanelSet(42), "coach");
});

test("cyclePanelSet: case + whitespace insensitive", () => {
  assert.strictEqual(ov.cyclePanelSet("  Coach "), "build");
});

test("OVERLAY_DEFAULTS: hotkeyCycle is Alt+Shift+C (spec sec 5)", () => {
  assert.strictEqual(ov.OVERLAY_DEFAULTS.hotkeyCycle, "Alt+Shift+C");
});

test("overlayUrl: panelSet appends panelset=NAME alongside overlay=1", () => {
  const out = ov.overlayUrl("https://legion-rc:8888/", "build");
  assert.ok(out.includes("overlay=1"), out);
  assert.ok(out.includes("panelset=build"), out);
});

test("overlayUrl: backward compatible - no panelSet keeps plain overlay=1", () => {
  assert.strictEqual(
    ov.overlayUrl("https://legion-rc:8888/"),
    "https://legion-rc:8888/?overlay=1"
  );
  assert.strictEqual(
    ov.overlayUrl("https://legion-rc:8888/", null),
    "https://legion-rc:8888/?overlay=1"
  );
});

test("overlayUrl: unknown panelSet is dropped (defensive)", () => {
  assert.strictEqual(
    ov.overlayUrl("https://legion-rc:8888/", "garbage"),
    "https://legion-rc:8888/?overlay=1"
  );
});

test("overlayUrl: panelSet normalized (case + whitespace)", () => {
  const out = ov.overlayUrl("https://legion-rc:8888/", "  THREAT ");
  assert.ok(out.includes("panelset=threat"), out);
});
