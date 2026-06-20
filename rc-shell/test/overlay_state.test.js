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

// --- HZ-D1 slice 2: overlay position + panel-set persistence -----------------

test("overlayStateFrom: extracts x/y/panelSet from the overlay sub-object", () => {
  const s = ov.overlayStateFrom({ overlay: { x: 12, y: 34, panelSet: "build" } });
  assert.deepStrictEqual(s, { x: 12, y: 34, panelSet: "build" });
});

test("overlayStateFrom: garbage-safe (null / arrays / strings / missing)", () => {
  const garbage = [
    null,
    undefined,
    [],
    "junk",
    42,
    {},
    { overlay: null },
    { overlay: [] },
    { overlay: "junk" },
  ];
  for (const g of garbage) {
    const s = ov.overlayStateFrom(g);
    assert.deepStrictEqual(s, { x: null, y: null, panelSet: "" }, JSON.stringify(g));
  }
});

test("overlayStateFrom: non-numeric / non-finite x/y -> null", () => {
  assert.deepStrictEqual(ov.overlayStateFrom({ overlay: { x: "5", y: NaN } }), {
    x: null,
    y: null,
    panelSet: "",
  });
  assert.deepStrictEqual(ov.overlayStateFrom({ overlay: { x: Infinity, y: 3 } }), {
    x: null,
    y: 3,
    panelSet: "",
  });
});

test("overlayStateFrom: panelSet normalized; unknown -> empty string", () => {
  assert.strictEqual(ov.overlayStateFrom({ overlay: { panelSet: "  THREAT " } }).panelSet, "threat");
  assert.strictEqual(ov.overlayStateFrom({ overlay: { panelSet: "zzz" } }).panelSet, "");
  assert.strictEqual(ov.overlayStateFrom({ overlay: { panelSet: 42 } }).panelSet, "");
});

test("resolveOverlayBounds: no saved coords -> right-edge dock at default size", () => {
  const area = { x: 0, y: 0, width: 1920, height: 1080 };
  assert.deepStrictEqual(ov.resolveOverlayBounds({}, area), {
    x: 1920 - ov.OVERLAY_DEFAULTS.width,
    y: 0,
    width: ov.OVERLAY_DEFAULTS.width,
    height: ov.OVERLAY_DEFAULTS.height,
  });
});

test("resolveOverlayBounds: dock respects an offset work area (second display)", () => {
  const area = { x: 2560, y: 100, width: 1920, height: 1080 };
  const b = ov.resolveOverlayBounds({}, area);
  assert.strictEqual(b.x, 2560 + 1920 - ov.OVERLAY_DEFAULTS.width);
  assert.strictEqual(b.y, 100);
});

test("resolveOverlayBounds: saved coords inside the work area pass through", () => {
  const area = { x: 0, y: 0, width: 1920, height: 1080 };
  const b = ov.resolveOverlayBounds({ overlay: { x: 100, y: 50 } }, area);
  assert.deepStrictEqual(b, {
    x: 100,
    y: 50,
    width: ov.OVERLAY_DEFAULTS.width,
    height: ov.OVERLAY_DEFAULTS.height,
  });
});

test("resolveOverlayBounds: off-screen saved coords pulled back on-screen", () => {
  const area = { x: 0, y: 0, width: 1920, height: 1080 };
  const b = ov.resolveOverlayBounds({ overlay: { x: 5000, y: -300 } }, area);
  assert.strictEqual(b.x, 1920 - ov.OVERLAY_DEFAULTS.width);
  assert.strictEqual(b.y, 0);
});

test("resolveOverlayBounds: partial saved coords (x only) fall back to the dock", () => {
  const area = { x: 0, y: 0, width: 1920, height: 1080 };
  const b = ov.resolveOverlayBounds({ overlay: { x: 100 } }, area);
  assert.strictEqual(b.x, 1920 - ov.OVERLAY_DEFAULTS.width);
  assert.strictEqual(b.y, 0);
});

test("resolveOverlayBounds: garbage workArea falls back to 1920x1080", () => {
  for (const g of [null, undefined, "junk", [], {}]) {
    const b = ov.resolveOverlayBounds({}, g);
    assert.strictEqual(b.x, 1920 - ov.OVERLAY_DEFAULTS.width, JSON.stringify(g));
    assert.strictEqual(b.y, 0, JSON.stringify(g));
    assert.strictEqual(b.width, ov.OVERLAY_DEFAULTS.width);
    assert.strictEqual(b.height, ov.OVERLAY_DEFAULTS.height);
  }
});

test("mergeOverlayPatch: preserves companion keys, merges the overlay sub-object", () => {
  const prev = { x: 1, y: 2, width: 520, sizePreset: "standard", overlay: { x: 9 } };
  const next = ov.mergeOverlayPatch(prev, { y: 7, panelSet: "build" });
  assert.strictEqual(next.x, 1);
  assert.strictEqual(next.y, 2);
  assert.strictEqual(next.width, 520);
  assert.strictEqual(next.sizePreset, "standard");
  assert.deepStrictEqual(next.overlay, { x: 9, y: 7, panelSet: "build" });
});

test("mergeOverlayPatch: never mutates inputs, returns a new object", () => {
  const prev = { overlay: { x: 9, panelSet: "coach" } };
  const patch = { x: 1 };
  const next = ov.mergeOverlayPatch(prev, patch);
  assert.deepStrictEqual(prev, { overlay: { x: 9, panelSet: "coach" } });
  assert.deepStrictEqual(patch, { x: 1 });
  assert.notStrictEqual(next, prev);
  assert.notStrictEqual(next.overlay, prev.overlay);
});

test("mergeOverlayPatch: garbage prev -> fresh object carrying just the patch", () => {
  for (const g of [null, undefined, [], "junk", 42]) {
    const next = ov.mergeOverlayPatch(g, { panelSet: "build" });
    assert.deepStrictEqual(next, { overlay: { panelSet: "build" } }, JSON.stringify(g));
  }
});

test("mergeOverlayPatch: garbage patch keeps the previous overlay intact", () => {
  const next = ov.mergeOverlayPatch({ a: 1, overlay: { x: 5 } }, null);
  assert.deepStrictEqual(next, { a: 1, overlay: { x: 5 } });
});

test("mergeOverlayPatch: non-object previous overlay is discarded", () => {
  const next = ov.mergeOverlayPatch({ overlay: "junk" }, { x: 3 });
  assert.deepStrictEqual(next.overlay, { x: 3 });
});

// --- OVL1: overlay-settings model (pulse-notify + ACTIVE auto-revert seconds) --

test("OVERLAY_SETTINGS_DEFAULTS: pulseNotify on, revert 20s (== activeRevertDelayMs)", () => {
  assert.strictEqual(ov.OVERLAY_SETTINGS_DEFAULTS.pulseNotify, true);
  assert.strictEqual(ov.OVERLAY_SETTINGS_DEFAULTS.activeRevertSec, 20);
  // the seconds setting and the legacy ms default must agree (one truth).
  assert.strictEqual(
    ov.OVERLAY_SETTINGS_DEFAULTS.activeRevertSec * 1000,
    ov.OVERLAY_DEFAULTS.activeRevertDelayMs
  );
});

test("overlaySettingsFrom: defaults when nothing saved", () => {
  assert.deepStrictEqual(ov.overlaySettingsFrom({}), {
    pulseNotify: true,
    activeRevertSec: 20,
    keepCompanion: true,
    companionAlwaysOnTop: true,
  });
});

test("overlaySettingsFrom: reads saved overlay.settings", () => {
  const s = ov.overlaySettingsFrom({
    overlay: { settings: { pulseNotify: false, activeRevertSec: 45 } },
  });
  assert.deepStrictEqual(s, {
    pulseNotify: false,
    activeRevertSec: 45,
    keepCompanion: true,
    companionAlwaysOnTop: true,
  });
});

test("overlaySettingsFrom: activeRevertSec clamped to [3,120] and rounded", () => {
  const f = (v) =>
    ov.overlaySettingsFrom({ overlay: { settings: { activeRevertSec: v } } })
      .activeRevertSec;
  assert.strictEqual(f(0), 3);
  assert.strictEqual(f(-99), 3);
  assert.strictEqual(f(9999), 120);
  assert.strictEqual(f(12.7), 13);
});

test("overlaySettingsFrom: non-boolean pulse / non-finite revert -> defaults", () => {
  const s = ov.overlaySettingsFrom({
    overlay: { settings: { pulseNotify: "yes", activeRevertSec: NaN } },
  });
  assert.deepStrictEqual(s, {
    pulseNotify: true,
    activeRevertSec: 20,
    keepCompanion: true,
    companionAlwaysOnTop: true,
  });
});

test("overlaySettingsFrom: pulseNotify false is honored (boolean false valid)", () => {
  assert.strictEqual(
    ov.overlaySettingsFrom({ overlay: { settings: { pulseNotify: false } } })
      .pulseNotify,
    false
  );
});

test("overlaySettingsFrom: garbage-safe (null / arrays / strings / junk overlay)", () => {
  for (const g of [
    null,
    undefined,
    [],
    "junk",
    42,
    {},
    { overlay: null },
    { overlay: "junk" },
    { overlay: { settings: "junk" } },
    { overlay: { settings: [] } },
  ]) {
    assert.deepStrictEqual(
      ov.overlaySettingsFrom(g),
      {
        pulseNotify: true,
        activeRevertSec: 20,
        keepCompanion: true,
        companionAlwaysOnTop: true,
      },
      JSON.stringify(g)
    );
  }
});

test("mergeOverlaySettingsPatch: writes overlay.settings, preserving x/y/panelSet + companion keys", () => {
  const prev = {
    x: 1,
    width: 520,
    overlay: { x: 9, y: 8, panelSet: "build", settings: { pulseNotify: true, activeRevertSec: 20 } },
  };
  const next = ov.mergeOverlaySettingsPatch(prev, { activeRevertSec: 30 });
  assert.strictEqual(next.x, 1);
  assert.strictEqual(next.width, 520);
  assert.strictEqual(next.overlay.x, 9);
  assert.strictEqual(next.overlay.y, 8);
  assert.strictEqual(next.overlay.panelSet, "build");
  assert.deepStrictEqual(next.overlay.settings, { pulseNotify: true, activeRevertSec: 30 });
});

test("mergeOverlaySettingsPatch: clamps + drops unknown / wrong-typed patch fields", () => {
  const next = ov.mergeOverlaySettingsPatch({}, {
    activeRevertSec: 1, // clamp up to 3
    pulseNotify: "nope", // wrong type -> dropped
    bogus: 5, // unknown -> dropped
  });
  assert.strictEqual(next.overlay.settings.activeRevertSec, 3);
  assert.ok(!("pulseNotify" in next.overlay.settings));
  assert.ok(!("bogus" in next.overlay.settings));
});

test("mergeOverlaySettingsPatch: pulseNotify false persists", () => {
  const next = ov.mergeOverlaySettingsPatch({}, { pulseNotify: false });
  assert.strictEqual(next.overlay.settings.pulseNotify, false);
});

test("mergeOverlaySettingsPatch: never mutates inputs", () => {
  const prev = { overlay: { settings: { activeRevertSec: 20 } } };
  const patch = { activeRevertSec: 40 };
  const next = ov.mergeOverlaySettingsPatch(prev, patch);
  assert.deepStrictEqual(prev, { overlay: { settings: { activeRevertSec: 20 } } });
  assert.deepStrictEqual(patch, { activeRevertSec: 40 });
  assert.notStrictEqual(next.overlay.settings, prev.overlay.settings);
});

test("mergeOverlaySettingsPatch: garbage prev -> fresh object carrying just the clean patch", () => {
  for (const g of [null, undefined, [], "junk", 42]) {
    const next = ov.mergeOverlaySettingsPatch(g, { activeRevertSec: 25 });
    assert.deepStrictEqual(
      next,
      { overlay: { settings: { activeRevertSec: 25 } } },
      JSON.stringify(g)
    );
  }
});

test("overlaySettingsFrom round-trips a mergeOverlaySettingsPatch write (position survives)", () => {
  const saved = ov.mergeOverlaySettingsPatch(
    { overlay: { x: 5, panelSet: "coach" } },
    { pulseNotify: false, activeRevertSec: 33 }
  );
  assert.deepStrictEqual(ov.overlaySettingsFrom(saved), {
    pulseNotify: false,
    activeRevertSec: 33,
    keepCompanion: true,
    companionAlwaysOnTop: true,
  });
  assert.strictEqual(saved.overlay.x, 5);
  assert.strictEqual(saved.overlay.panelSet, "coach");
});

// --- RC2 E1: dashboard-persist policy + on-screen pin toggle ------------------
// Root cause of the operator "dashboard disappears" bug: windowActions(OVERLAY)
// hard-hides the companion, so entering a game strands the full dashboard. The
// keepCompanion policy keeps the companion window available alongside the HUD.

test("windowActionsWithPolicy: keepCompanion shows companion alongside the overlay", () => {
  assert.deepStrictEqual(
    ov.windowActionsWithPolicy(ov.SURFACES.OVERLAY, { keepCompanion: true }),
    { companion: "show", overlay: "show" }
  );
});

test("windowActionsWithPolicy: keepCompanion=false matches the legacy hide-companion behavior", () => {
  assert.deepStrictEqual(
    ov.windowActionsWithPolicy(ov.SURFACES.OVERLAY, { keepCompanion: false }),
    ov.windowActions(ov.SURFACES.OVERLAY)
  );
  assert.deepStrictEqual(
    ov.windowActionsWithPolicy(ov.SURFACES.OVERLAY, { keepCompanion: false }),
    { companion: "hide", overlay: "show" }
  );
});

test("windowActionsWithPolicy: keepCompanion never resurrects a HIDDEN surface", () => {
  // The hotkey force-hide must still clear BOTH windows, policy regardless.
  assert.deepStrictEqual(
    ov.windowActionsWithPolicy(ov.SURFACES.HIDDEN, { keepCompanion: true }),
    { companion: "hide", overlay: "hide" }
  );
});

test("windowActionsWithPolicy: COMPANION surface is unchanged by the policy", () => {
  for (const keep of [true, false]) {
    assert.deepStrictEqual(
      ov.windowActionsWithPolicy(ov.SURFACES.COMPANION, { keepCompanion: keep }),
      { companion: "show", overlay: "hide" }
    );
  }
});

test("windowActionsWithPolicy: missing / garbage opts default to legacy actions", () => {
  for (const g of [undefined, null, {}, [], "junk", 42]) {
    assert.deepStrictEqual(
      ov.windowActionsWithPolicy(ov.SURFACES.OVERLAY, g),
      ov.windowActions(ov.SURFACES.OVERLAY),
      JSON.stringify(g)
    );
  }
});

// --- RC2 E1: keepCompanion + companionAlwaysOnTop overlay settings -----------

test("OVERLAY_SETTINGS_DEFAULTS: keepCompanion on, companionAlwaysOnTop on", () => {
  // Default ON for keepCompanion is the bug fix - the dashboard PERSISTS unless
  // the operator opts out.
  assert.strictEqual(ov.OVERLAY_SETTINGS_DEFAULTS.keepCompanion, true);
  assert.strictEqual(ov.OVERLAY_SETTINGS_DEFAULTS.companionAlwaysOnTop, true);
});

test("overlaySettingsFrom: defaults include keepCompanion + companionAlwaysOnTop", () => {
  const s = ov.overlaySettingsFrom({});
  assert.strictEqual(s.keepCompanion, true);
  assert.strictEqual(s.companionAlwaysOnTop, true);
});

test("overlaySettingsFrom: reads saved keepCompanion + companionAlwaysOnTop booleans", () => {
  const s = ov.overlaySettingsFrom({
    overlay: { settings: { keepCompanion: false, companionAlwaysOnTop: false } },
  });
  assert.strictEqual(s.keepCompanion, false);
  assert.strictEqual(s.companionAlwaysOnTop, false);
});

test("overlaySettingsFrom: non-boolean keepCompanion / companionAlwaysOnTop -> default true", () => {
  const s = ov.overlaySettingsFrom({
    overlay: { settings: { keepCompanion: "no", companionAlwaysOnTop: 0 } },
  });
  assert.strictEqual(s.keepCompanion, true);
  assert.strictEqual(s.companionAlwaysOnTop, true);
});

test("mergeOverlaySettingsPatch: keepCompanion false persists; preserves siblings", () => {
  const prev = {
    overlay: { x: 9, panelSet: "build", settings: { pulseNotify: true } },
  };
  const next = ov.mergeOverlaySettingsPatch(prev, { keepCompanion: false });
  assert.strictEqual(next.overlay.settings.keepCompanion, false);
  assert.strictEqual(next.overlay.settings.pulseNotify, true);
  assert.strictEqual(next.overlay.x, 9);
  assert.strictEqual(next.overlay.panelSet, "build");
});

test("mergeOverlaySettingsPatch: companionAlwaysOnTop true persists", () => {
  const next = ov.mergeOverlaySettingsPatch({}, { companionAlwaysOnTop: true });
  assert.strictEqual(next.overlay.settings.companionAlwaysOnTop, true);
});

test("mergeOverlaySettingsPatch: non-boolean keepCompanion / companionAlwaysOnTop dropped", () => {
  const next = ov.mergeOverlaySettingsPatch({}, {
    keepCompanion: "nope",
    companionAlwaysOnTop: 1,
  });
  assert.ok(!("keepCompanion" in next.overlay.settings));
  assert.ok(!("companionAlwaysOnTop" in next.overlay.settings));
});

// --- RC2 Stage 4.1: DPI + resolution-aware overlay sizing --------------------
// LIFT-C (docs/research/RC2_RESEARCH_overlay_sizing.md): size the overlay box
// against the measured display so a non-1920 borderless res (operator now runs
// 2560x1440) or a 125%/150% Windows scale does not clip/shrink the HUD. Pure
// logic here; main.js wires it from screen.getPrimaryDisplay().

test("normScaleFactor: electron#6571 guard - non-finite / <=0 -> 1", () => {
  assert.strictEqual(ov.normScaleFactor(0), 1);
  assert.strictEqual(ov.normScaleFactor(-2), 1);
  assert.strictEqual(ov.normScaleFactor(NaN), 1);
  assert.strictEqual(ov.normScaleFactor(undefined), 1);
  assert.strictEqual(ov.normScaleFactor("1.5"), 1); // non-number -> 1
});

test("normScaleFactor: valid scale passes through", () => {
  assert.strictEqual(ov.normScaleFactor(1), 1);
  assert.strictEqual(ov.normScaleFactor(1.25), 1.25);
  assert.strictEqual(ov.normScaleFactor(1.5), 1.5);
  assert.strictEqual(ov.normScaleFactor(2), 2);
});

test("resolveOverlayScale: 1920x1080 design baseline -> exactly 1.0 (no-op)", () => {
  assert.strictEqual(
    ov.resolveOverlayScale({ x: 0, y: 0, width: 1920, height: 1080 }),
    1
  );
});

test("resolveOverlayScale: 2560x1440 scales up (min of the two ratios)", () => {
  // min(2560/1920, 1440/1080) = min(1.333, 1.333) = 1.33 (2-dp)
  assert.strictEqual(
    ov.resolveOverlayScale({ x: 0, y: 0, width: 2560, height: 1440 }),
    1.33
  );
});

test("resolveOverlayScale: ultrawide clamps by the smaller (height) ratio", () => {
  // 3440x1440: min(3440/1920=1.79, 1440/1080=1.33) -> 1.33, not 1.79
  assert.strictEqual(
    ov.resolveOverlayScale({ x: 0, y: 0, width: 3440, height: 1440 }),
    1.33
  );
});

test("resolveOverlayScale: clamps to [0.8, 1.6]", () => {
  // tiny work area floors at 0.8
  assert.strictEqual(
    ov.resolveOverlayScale({ x: 0, y: 0, width: 800, height: 600 }),
    0.8
  );
  // 4K ceils at 1.6 (min(2.0, 2.0) -> 1.6)
  assert.strictEqual(
    ov.resolveOverlayScale({ x: 0, y: 0, width: 3840, height: 2160 }),
    1.6
  );
});

test("resolveOverlayScale: garbage work area -> 1920x1080 fallback -> 1.0", () => {
  assert.strictEqual(ov.resolveOverlayScale(null), 1);
  assert.strictEqual(ov.resolveOverlayScale({}), 1);
  assert.strictEqual(ov.resolveOverlayScale({ width: -1, height: 0 }), 1);
});

test("resolveOverlayMetrics: baseline display -> default box, scale 1, sf 1", () => {
  const m = ov.resolveOverlayMetrics({
    workArea: { x: 0, y: 0, width: 1920, height: 1080 },
    scaleFactor: 1,
  });
  assert.strictEqual(m.scale, 1);
  assert.strictEqual(m.scaleFactor, 1);
  assert.strictEqual(m.width, ov.OVERLAY_DEFAULTS.width); // 460
  assert.strictEqual(m.height, ov.OVERLAY_DEFAULTS.height); // 900
});

test("resolveOverlayMetrics: 2560x1440 grows the box by the scale", () => {
  const m = ov.resolveOverlayMetrics({
    workArea: { x: 0, y: 0, width: 2560, height: 1400 },
    scaleFactor: 1,
  });
  assert.strictEqual(m.scale, 1.3); // min(1.333, 1400/1080=1.296) -> 1.30
  assert.strictEqual(m.width, Math.round(460 * 1.3)); // 598
  assert.strictEqual(m.height, Math.round(900 * 1.3)); // 1170
});

test("resolveOverlayMetrics: height never exceeds the work area", () => {
  // A short work area must clamp the scaled height so the dock fits on-screen.
  const m = ov.resolveOverlayMetrics({
    workArea: { x: 0, y: 0, width: 3840, height: 1000 },
    scaleFactor: 1,
  });
  assert.ok(m.height <= 1000, `height ${m.height} <= 1000`);
});

test("resolveOverlayMetrics: bad scaleFactor guarded to 1 (electron#6571)", () => {
  const m = ov.resolveOverlayMetrics({
    workArea: { x: 0, y: 0, width: 1920, height: 1080 },
    scaleFactor: 0,
  });
  assert.strictEqual(m.scaleFactor, 1);
});

test("resolveOverlayMetrics: garbage display -> safe baseline box", () => {
  const m = ov.resolveOverlayMetrics(null);
  assert.strictEqual(m.scale, 1);
  assert.strictEqual(m.width, ov.OVERLAY_DEFAULTS.width);
  assert.strictEqual(m.height, ov.OVERLAY_DEFAULTS.height);
});

test("resolveOverlayBounds: metrics override the default box size", () => {
  const area = { x: 0, y: 0, width: 2560, height: 1440 };
  const metrics = { width: 600, height: 1200 };
  const b = ov.resolveOverlayBounds({}, area, metrics);
  assert.strictEqual(b.width, 600);
  assert.strictEqual(b.height, 1200);
  // right-edge dock with the SCALED width: 2560 - 600 = 1960
  assert.strictEqual(b.x, 1960);
  assert.strictEqual(b.y, 0);
});

test("resolveOverlayBounds: no metrics -> default box (backward compatible)", () => {
  const b = ov.resolveOverlayBounds({}, { x: 0, y: 0, width: 1920, height: 1080 });
  assert.strictEqual(b.width, ov.OVERLAY_DEFAULTS.width);
  assert.strictEqual(b.height, ov.OVERLAY_DEFAULTS.height);
});

test("resolveOverlayBounds: garbage metrics fall back to default box", () => {
  const area = { x: 0, y: 0, width: 1920, height: 1080 };
  const b = ov.resolveOverlayBounds({}, area, { width: 0, height: -5 });
  assert.strictEqual(b.width, ov.OVERLAY_DEFAULTS.width);
  assert.strictEqual(b.height, ov.OVERLAY_DEFAULTS.height);
});

test("overlayUrl: scale != 1 appends ovscale", () => {
  assert.strictEqual(
    ov.overlayUrl("https://legion-rc:8888/", null, 1.3),
    "https://legion-rc:8888/?overlay=1&ovscale=1.3"
  );
});

test("overlayUrl: scale == 1 omits ovscale (baseline URL unchanged)", () => {
  assert.strictEqual(
    ov.overlayUrl("https://legion-rc:8888/", null, 1),
    "https://legion-rc:8888/?overlay=1"
  );
});

test("overlayUrl: garbage / absent scale omits ovscale", () => {
  assert.ok(!ov.overlayUrl("https://x:8888/", null, NaN).includes("ovscale"));
  assert.ok(!ov.overlayUrl("https://x:8888/", null, 0).includes("ovscale"));
  assert.ok(!ov.overlayUrl("https://x:8888/", null).includes("ovscale"));
});

test("overlayUrl: scale composes with panelSet", () => {
  const out = ov.overlayUrl("https://x:8888/", "build", 1.3);
  assert.ok(out.includes("overlay=1"));
  assert.ok(out.includes("panelset=build"));
  assert.ok(out.includes("ovscale=1.3"));
});
