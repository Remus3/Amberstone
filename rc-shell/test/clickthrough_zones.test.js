// rc-shell/test/clickthrough_zones.test.js
//
// RC2 Stage 4.2: click-through ZONES. The overlay is a passive click-through
// HUD ({forward:true}), but a handful of interactive controls (the #ovset
// settings strip, the A+B choice chips, the DS fight-model knobs, the drag
// strip) should capture the cursor WITHOUT the operator first hitting the
// global ACTIVE hotkey. The renderer reports "cursor is over a zone" over the
// preload bridge (window.rcShell.setZoneHover); main.js flips the window's
// ignore-mouse via the pure effectiveIgnoreMouse decision (overlay_state.js).
//
// This module is the PURE injected-string half (mirrors active_indicator.js /
// drag_region.js): the sandboxed preload cannot require local modules, so the
// hover-detection script ships as a string main.js executes on the overlay
// page. node:testable - we assert the contract of the emitted strings.

"use strict";

const test = require("node:test");
const assert = require("node:assert");
const ctz = require("../src/clickthrough_zones");

test("ZONE_SELECTOR names the interactive overlay controls", () => {
  assert.strictEqual(typeof ctz.ZONE_SELECTOR, "string");
  // The settings strip + A+B choices + DS knob pane are the must-have zones.
  assert.ok(ctz.ZONE_SELECTOR.includes("#ovset"), "settings strip is a zone");
  assert.ok(ctz.ZONE_SELECTOR.includes("#rn-choices"), "A+B choices are a zone");
  assert.ok(ctz.ZONE_SELECTOR.includes("#am-pane-ovds"), "DS knob pane is a zone");
  // A generic opt-in hook so future controls join without a code change.
  assert.ok(ctz.ZONE_SELECTOR.includes("data-rc-zone"), "generic data-rc-zone hook");
});

test("clickThroughZonesMountJS returns an IIFE string", () => {
  const js = ctz.clickThroughZonesMountJS();
  assert.strictEqual(typeof js, "string");
  assert.ok(js.trim().startsWith("(function"), "wraps in an IIFE");
  assert.ok(js.includes("})()") || js.includes("})();"), "self-invokes");
});

test("mount JS calls the preload bridge window.rcShell.setZoneHover", () => {
  const js = ctz.clickThroughZonesMountJS();
  assert.ok(js.includes("rcShell"), "references the bridge");
  assert.ok(js.includes("setZoneHover"), "calls setZoneHover");
});

test("mount JS guards the bridge being absent (plain browser)", () => {
  // A no-bridge page (no Electron preload) must not throw - typeof / && guard.
  const js = ctz.clickThroughZonesMountJS();
  assert.ok(
    /window\.rcShell\s*&&/.test(js) || js.includes("typeof window.rcShell"),
    "guards window.rcShell before calling"
  );
});

test("mount JS uses closest(ZONE_SELECTOR) to hit-test the cursor", () => {
  const js = ctz.clickThroughZonesMountJS();
  assert.ok(js.includes("closest"), "uses Element.closest for hit-testing");
  // The selector literal must be embedded so the page-side script knows it.
  assert.ok(js.includes("#ovset"), "embeds the zone selector");
});

test("mount JS is idempotent (a re-run / reload guard)", () => {
  const js = ctz.clickThroughZonesMountJS();
  // A window-scoped flag so re-injection on did-finish-load does not stack
  // duplicate listeners (mirrors active_indicator getElementById guard).
  assert.ok(/__rc[A-Za-z]*ZoneHover|rcZoneHoverWired/.test(js), "wired-flag guard");
});

test("mount JS listens on pointer events and resets on leave", () => {
  const js = ctz.clickThroughZonesMountJS();
  assert.ok(js.includes("addEventListener"), "wires listeners");
  assert.ok(/pointermove|pointerover/.test(js), "watches pointer movement");
  // Leaving the overlay region must drop the hover (false) so the HUD goes
  // back to click-through.
  assert.ok(/pointerleave|pointerout|setZoneHover\(false\)|setZoneHover\(!1\)/.test(js),
    "resets hover on leave");
});

test("module is ASCII-only (repo hard rule)", () => {
  const fs = require("fs");
  const path = require("path");
  const raw = fs.readFileSync(path.join(__dirname, "..", "src", "clickthrough_zones.js"));
  for (let i = 0; i < raw.length; i++) {
    assert.ok(raw[i] < 128, "non-ASCII byte at offset " + i);
  }
});
