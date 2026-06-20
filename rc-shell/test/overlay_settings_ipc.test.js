// rc-shell/test/overlay_settings_ipc.test.js
//
// OVL1: text-contract pins on the overlay-settings IPC wiring. The preload
// contextBridge + the ipcMain handlers run ONLY under an Electron runtime
// (electron is not loadable in `node --test`), so these tests assert the
// wiring EXISTS in source - the live renderer<->main round-trip is OWED and
// validated in a running shell (docs/ELECTRON_OVERLAY.md Phase 4). The pure
// settings logic (overlaySettingsFrom / mergeOverlaySettingsPatch) is covered
// behaviorally in overlay_state.test.js.

"use strict";

const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const path = require("path");

const preload = fs.readFileSync(path.join(__dirname, "..", "src", "preload.js"), "utf8");
const mainjs = fs.readFileSync(path.join(__dirname, "..", "src", "main.js"), "utf8");

const GET = "rc-shell:overlay-settings:get";
const SET = "rc-shell:overlay-settings:set";

test("preload exposes a minimal allow-listed rcShell bridge", () => {
  assert.ok(preload.includes("contextBridge"), "uses contextBridge");
  assert.ok(
    /exposeInMainWorld\(\s*["']rcShell["']/.test(preload),
    "exposes window.rcShell"
  );
  assert.ok(preload.includes("getOverlaySettings"), "getOverlaySettings method");
  assert.ok(preload.includes("setOverlaySettings"), "setOverlaySettings method");
  assert.ok(preload.includes(GET), "get channel name");
  assert.ok(preload.includes(SET), "set channel name");
});

test("preload never hands the renderer the raw ipcRenderer object", () => {
  // exposeInMainWorld must receive a wrapping object literal, not ipcRenderer
  // itself (that would leak the full IPC surface to the remote page).
  assert.ok(
    !/exposeInMainWorld\([^,]*,\s*ipcRenderer\s*\)/.test(preload),
    "raw ipcRenderer must not be exposed"
  );
});

test("main.js registers both overlay-settings IPC channels", () => {
  assert.ok(/\bipcMain\b/.test(mainjs), "imports ipcMain");
  assert.ok(
    mainjs.includes(`ipcMain.handle("${GET}"`) ||
      mainjs.includes(`ipcMain.handle('${GET}'`),
    "handles the get channel"
  );
  assert.ok(
    mainjs.includes(`ipcMain.handle("${SET}"`) ||
      mainjs.includes(`ipcMain.handle('${SET}'`),
    "handles the set channel"
  );
});

test("main.js persists via the pure merger and reads via the pure reader", () => {
  assert.ok(mainjs.includes("mergeOverlaySettingsPatch"), "uses the pure merger");
  assert.ok(mainjs.includes("overlaySettingsFrom"), "uses the pure reader");
});

test("main.js drives the ACTIVE auto-revert off the configurable seconds", () => {
  // The hardcoded OVERLAY_DEFAULTS.activeRevertDelayMs is superseded by the
  // persisted activeRevertSec * 1000 in the revert scheduler.
  assert.ok(
    /activeRevertSec\s*\*\s*1000/.test(mainjs),
    "revert delay derives from the persisted activeRevertSec"
  );
});

// --- RC2 Stage 4.2: non-intrusive overlay (zones + opacity) wiring ------------

const ZONE = "rc-shell:overlay-zone-hover";

test("preload exposes setZoneHover over the zone-hover channel", () => {
  assert.ok(preload.includes("setZoneHover"), "setZoneHover method");
  assert.ok(preload.includes(ZONE), "zone-hover channel name");
  // a one-way send (not invoke) - a hover ping needs no reply.
  assert.ok(/ipcRenderer\.send\(/.test(preload), "uses ipcRenderer.send");
});

test("main.js handles the zone-hover channel and re-applies click-through", () => {
  assert.ok(
    mainjs.includes(`ipcMain.on("${ZONE}"`) || mainjs.includes(`ipcMain.on('${ZONE}'`),
    "listens on the zone-hover channel"
  );
  assert.ok(mainjs.includes("effectiveIgnoreMouse"), "uses the pure zone decision");
});

test("main.js applies the operator overlay opacity to the overlay window", () => {
  assert.ok(/setOpacity\(/.test(mainjs), "calls overlayWindow.setOpacity");
  assert.ok(mainjs.includes("overlayOpacity"), "reads the persisted overlayOpacity");
});

test("main.js injects the click-through-zones hover script into the overlay", () => {
  assert.ok(mainjs.includes("clickthrough_zones") || mainjs.includes("clickThroughZonesMountJS"),
    "injects the zone-hover script");
});

// --- RC2 Stage 4.4: no-hotkey overlay actions wiring -------------------------

const ACTION = "rc-shell:overlay-action";

test("preload exposes overlayAction over the action channel as a one-way send", () => {
  assert.ok(preload.includes("overlayAction"), "overlayAction method");
  assert.ok(preload.includes(ACTION), "action channel name");
  assert.ok(/ipcRenderer\.send\(/.test(preload), "uses ipcRenderer.send (one-way)");
});

test("main.js handles the action channel through the pure validator", () => {
  assert.ok(
    mainjs.includes(`ipcMain.on("${ACTION}"`) || mainjs.includes(`ipcMain.on('${ACTION}'`),
    "listens on the action channel"
  );
  assert.ok(mainjs.includes("normOverlayAction"), "validates via the pure allow-list");
});

test("main.js shares the panel-set apply between the cycle hotkey and the IPC", () => {
  // applyPanelSet is the single panel-set primitive both paths call (no drift).
  assert.ok(mainjs.includes("applyPanelSet"), "uses the shared applyPanelSet");
  assert.ok(mainjs.includes("setOverlayActive"), "uses the shared setOverlayActive");
});
