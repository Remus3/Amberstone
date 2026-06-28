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
  // RC2 4.2: one-way hover ping for click-through ZONES. The overlay page's
  // hover detector (clickthrough_zones.js) calls this when the cursor enters /
  // leaves an interactive control; main.js flips the window interactive so the
  // operator can click it without the global ACTIVE hotkey. send (not invoke) -
  // a hover needs no reply.
  setZoneHover: (on) => ipcRenderer.send("rc-shell:overlay-zone-hover", !!on),
  // RC2 4.4: no-hotkey overlay ACTION (the #ovset panel-set selector + an
  // interact-now button). One-way send (no reply): main.js validates the
  // message through overlay_state.normOverlayAction and runs the same code the
  // Alt+Shift+C / Alt+Shift+A hotkeys do, so the two paths never drift.
  overlayAction: (msg) => ipcRenderer.send("rc-shell:overlay-action", msg),
  // RC Overlay Doctrine section 3: the movable widget field mirrors its
  // {x,y,hidden,scale}-per-id layout to the DURABLE rc-shell state file so it
  // survives a localStorage wipe + is hand-editable. get seeds the field at boot
  // when localStorage is empty; set persists a drag/scale/reset.
  // -> Promise<{ <id>: {x?,y?,hidden?,scale?} }>
  getWidgetLayout: () => ipcRenderer.invoke("rc-shell:overlay-layout:get"),
  // layout: the full { <id>: {x,y,hidden,scale} } blob -> Promise<sanitized layout>
  setWidgetLayout: (layout) =>
    ipcRenderer.invoke("rc-shell:overlay-layout:set", layout),
  // Companion titlebar window controls. The companion is frameless, so the
  // injected top-right strip (window_controls.js) drives these. minimize/close
  // are one-way sends; the always-on-top toggle/get return the new/current
  // boolean so the strip can light its pinned state.
  winMinimize: () => ipcRenderer.send("rc-shell:win:minimize"),
  winClose: () => ipcRenderer.send("rc-shell:win:close"),
  // -> Promise<boolean> the new always-on-top state
  winToggleAlwaysOnTop: () => ipcRenderer.invoke("rc-shell:win:toggle-aot"),
  // -> Promise<boolean> the current always-on-top state
  winGetAlwaysOnTop: () => ipcRenderer.invoke("rc-shell:win:get-aot"),
});
