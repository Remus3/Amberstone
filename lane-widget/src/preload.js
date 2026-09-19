// lane-widget/src/preload.js
//
// Minimal, allow-listed renderer<->main bridge. Same discipline as
// rc-shell/src/preload.js: contextIsolation is on, the raw ipcRenderer is NEVER
// handed to the page, and every exposed member is a thin wrapper over one named
// channel from the frozen IPC list (spec section 3).
//
//   lane-widget:model      main -> renderer  push, payload = buildModel output
//   lane-widget:state:get  invoke -> { opacity, alwaysOnTop, showFree, fastMs }
//   lane-widget:state:set  invoke (patch) -> resolved state
//   lane-widget:win:menu   send   open the window context menu (right-click)
//   lane-widget:size       send   { width, height } content size report
//
// The renderer is a local file with no network access, so there is nothing else
// to expose and nothing here returns a live electron object to the page.

"use strict";

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("laneWidget", {
  // Subscribe to the model push. The listener receives ONLY the payload - the
  // IpcRendererEvent is deliberately not forwarded (it carries a sender handle).
  // Returns an unsubscribe function.
  onModel: (cb) => {
    if (typeof cb !== "function") {
      return () => {};
    }
    const wrapped = (_event, model) => {
      cb(model);
    };
    ipcRenderer.on("lane-widget:model", wrapped);
    return () => {
      ipcRenderer.removeListener("lane-widget:model", wrapped);
    };
  },

  // -> Promise<{ opacity, alwaysOnTop, showFree, fastMs }>
  getState: () => ipcRenderer.invoke("lane-widget:state:get"),

  // patch: any subset of { opacity, alwaysOnTop, showFree, fastMs }
  // -> Promise<resolved state>
  setState: (patch) => ipcRenderer.invoke("lane-widget:state:set", patch),

  // Right-click anywhere on the frameless window: Minimize / Close to tray.
  openWindowMenu: () => ipcRenderer.send("lane-widget:win:menu"),

  // The renderer measures its own content and reports it; main clamps the
  // result through clamp.js so the window is never larger than it needs.
  reportSize: (size) => {
    const s = size && typeof size === "object" ? size : {};
    ipcRenderer.send("lane-widget:size", {
      width: Number(s.width) || 0,
      height: Number(s.height) || 0,
    });
  },
});
