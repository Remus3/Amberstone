// rc-shell/src/preload.js
//
// Phase 1 preload: intentionally near-empty.
//
// The dashboard at RC_ORIGIN is a self-contained web app - it does not need any
// Node/Electron APIs injected to render. We keep contextIsolation: true and
// nodeIntegration: false in main.js, so the loaded page runs as a plain web
// page with no privileged bridge. That is the safest posture for Phase 1
// (Vanguard-safe, no attack surface).
//
// When Phase 2+ needs the renderer to talk to the main process (e.g. report a
// preset change from an in-page control), expose a minimal, allow-listed bridge
// here via contextBridge.exposeInMainWorld. Do NOT expose ipcRenderer raw.

"use strict";

// No bridge exposed in Phase 1.
