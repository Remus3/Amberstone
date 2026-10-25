// rc-shell/src/toggle_preload.js
//
// Preload for the overlay ON/OFF toggle icon window ONLY (overlay_toggle.html).
// Least privilege: the icon page gets exactly the toggle protocol - never the
// overlay bridge in ./preload.js - and the raw ipcRenderer is never handed to
// the page. main.js validates every message through
// overlay_toggle.normToggleAction and accepts it only from the toggle window's
// own webContents.

"use strict";

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("rcToggle", {
  // action: "press" | "move" | "release" | "cancel" | "activate" (one-way)
  send: (action) => ipcRenderer.send("rc-shell:overlay-toggle", { action: String(action) }),
  // -> Promise<{ visible: boolean }>
  getState: () => ipcRenderer.invoke("rc-shell:overlay-toggle:get"),
  // cb({ visible: boolean }) on every ON/OFF change; only the data is passed on.
  onState: (cb) => {
    ipcRenderer.on("rc-shell:overlay-toggle:state", (_event, state) => {
      try {
        cb(state && typeof state === "object" ? { visible: state.visible !== false } : { visible: true });
      } catch (_e) {
        // a page-side render error must not break the bridge
      }
    });
  },
});
