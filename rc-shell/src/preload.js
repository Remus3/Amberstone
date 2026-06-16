// rc-shell/src/preload.js
//
// Minimal, allow-listed renderer<->main bridge (OVL1, Phase 4).
//
// The dashboard at RC_ORIGIN is a self-contained web app and needs no Node /
// Electron APIs to render. The ONLY privileged surface we expose is the overlay
// settings round-trip: the ?overlay=1 surface lets the operator toggle the
// change-pulse and set the ACTIVE auto-revert delay, and those persist into the
// shell config (across launches) over these two channels. contextIsolation is
// on and the raw ipcRenderer is NEVER handed to the page - only two thin,
// promise-returning wrappers over named invoke channels. main.js owns the
// ipcMain handlers + applies the settings.

"use strict";

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("rcShell", {
  // -> Promise<{ pulseNotify: boolean, activeRevertSec: number }>
  getOverlaySettings: () => ipcRenderer.invoke("rc-shell:overlay-settings:get"),
  // patch: { pulseNotify?: boolean, activeRevertSec?: number }
  // -> Promise<resolved settings>
  setOverlaySettings: (patch) =>
    ipcRenderer.invoke("rc-shell:overlay-settings:set", patch),
});
