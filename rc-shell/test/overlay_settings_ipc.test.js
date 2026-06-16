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
