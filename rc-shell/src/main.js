// rc-shell/src/main.js
//
// Riot Commander Electron Phase 1 companion shell - the main process.
//
// What it does (and ONLY this):
//   - Creates one frameless, always-on-top BrowserWindow.
//   - Loads RC_ORIGIN (config, not code; default https://legion-rc:8888).
//   - Restores saved window position/size (clamped on-screen) across launches.
//   - Persists position/size/preset on move/resize/close.
//   - Trusts ONLY the RC origin's self-signed (mkcert) cert - scoped, never global.
//   - Offers a small app menu to switch size presets (low-risk; optional in spec).
//
// What it does NOT do (Vanguard-safe; see docs/ELECTRON_OVERLAY.md sections 3.8 + 8):
//   - No transparent overlay, no click-through (Phase 3+).
//   - No global hotkeys (Phase 2+).
//   - No DXGI / frame capture, no game-memory reads, no input injection - ever.
//   - No Pengu / in-client (Phase 6).

"use strict";

const path = require("path");
const { app, BrowserWindow, Menu, screen, shell } = require("electron");

const cfgmod = require("./config");
const store = require("./store");

// Persistence target: <userData>/rc-shell-state.json. userData is per-app and
// per-OS-user, so two machines / two users never collide.
function statePath() {
  return path.join(app.getPath("userData"), "rc-shell-state.json");
}

let mainWindow = null;
let originHost = ""; // host:port we trust the self-signed cert for.

// Debounced state writer so a drag (many move events) does not hammer the disk.
let saveTimer = null;
function persistWindowState() {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }
  if (saveTimer) {
    clearTimeout(saveTimer);
  }
  saveTimer = setTimeout(() => {
    saveTimer = null;
    if (!mainWindow || mainWindow.isDestroyed()) {
      return;
    }
    const b = mainWindow.getBounds();
    const prev = store.load(statePath(), {});
    const next = Object.assign({}, prev, {
      origin: prev.origin, // origin is resolved at boot; keep whatever was saved
      x: b.x,
      y: b.y,
      width: b.width,
      height: b.height,
      alwaysOnTop: mainWindow.isAlwaysOnTop(),
      sizePreset: prev.sizePreset || cfgmod.DEFAULT_PRESET,
    });
    store.save(statePath(), next);
  }, 400);
}

// Synchronous final flush (used on close, where the debounce would be too late).
function persistWindowStateNow() {
  if (saveTimer) {
    clearTimeout(saveTimer);
    saveTimer = null;
  }
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }
  const b = mainWindow.getBounds();
  const prev = store.load(statePath(), {});
  const next = Object.assign({}, prev, {
    x: b.x,
    y: b.y,
    width: b.width,
    height: b.height,
    alwaysOnTop: mainWindow.isAlwaysOnTop(),
    sizePreset: prev.sizePreset || cfgmod.DEFAULT_PRESET,
  });
  store.save(statePath(), next);
}

// Apply a named size preset live, resize the window, and persist it.
function selectPreset(presetName) {
  const preset = cfgmod.SIZE_PRESETS[presetName];
  if (!preset || !mainWindow || mainWindow.isDestroyed()) {
    return;
  }
  mainWindow.setSize(preset.width, preset.height);
  const prev = store.load(statePath(), {});
  store.save(
    statePath(),
    Object.assign({}, prev, {
      width: preset.width,
      height: preset.height,
      sizePreset: presetName,
    })
  );
}

function toggleAlwaysOnTop() {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }
  const next = !mainWindow.isAlwaysOnTop();
  mainWindow.setAlwaysOnTop(next);
  persistWindowState();
  buildMenu(); // refresh the checkbox state
}

// A minimal application menu: size presets + always-on-top toggle + reload.
// This is the low-risk preset switcher the spec marks optional. No global
// hotkeys (those are Phase 2); these are app-menu accelerators only, active
// while the shell is focused.
function buildMenu() {
  const aot = mainWindow && !mainWindow.isDestroyed() ? mainWindow.isAlwaysOnTop() : true;
  const template = [
    {
      label: "Shell",
      submenu: [
        {
          label: "Size: Compact",
          accelerator: "CmdOrCtrl+1",
          click: () => selectPreset("compact"),
        },
        {
          label: "Size: Standard",
          accelerator: "CmdOrCtrl+2",
          click: () => selectPreset("standard"),
        },
        {
          label: "Size: Tall",
          accelerator: "CmdOrCtrl+3",
          click: () => selectPreset("tall"),
        },
        { type: "separator" },
        {
          label: "Always on top",
          type: "checkbox",
          checked: aot,
          click: () => toggleAlwaysOnTop(),
        },
        { type: "separator" },
        {
          label: "Reload",
          accelerator: "CmdOrCtrl+R",
          click: () => {
            if (mainWindow && !mainWindow.isDestroyed()) {
              mainWindow.reload();
            }
          },
        },
        { type: "separator" },
        { role: "quit" },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

function createWindow() {
  const saved = store.load(statePath(), {});
  const cfg = cfgmod.resolveConfig(saved, process.env);

  originHost = cfgmod.originHost(cfg.origin);

  // Resolve the on-screen position. If saved coords exist, clamp them to the
  // display nearest those coords; if not, leave x/y unset so Electron centers.
  let x;
  let y;
  if (typeof cfg.x === "number" && typeof cfg.y === "number") {
    const display = screen.getDisplayNearestPoint({ x: cfg.x, y: cfg.y });
    const clamped = cfgmod.clampPosition(
      { x: cfg.x, y: cfg.y, width: cfg.width, height: cfg.height },
      display.workArea
    );
    if (clamped.x !== null && clamped.y !== null) {
      x = clamped.x;
      y = clamped.y;
    }
  }

  const opts = {
    width: cfg.width,
    height: cfg.height,
    frame: false, // frameless companion (spec 3.3); drag region is CSS in the page
    alwaysOnTop: cfg.alwaysOnTop,
    backgroundColor: "#0b0e14", // dark fallback while RC_ORIGIN loads
    title: "Riot Commander",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  };
  if (typeof x === "number" && typeof y === "number") {
    opts.x = x;
    opts.y = y;
  }

  mainWindow = new BrowserWindow(opts);

  // Open target=_blank / external links in the default browser, never a new
  // Electron window (keeps the shell single-window + avoids loading arbitrary
  // origins inside the trusted shell).
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    try {
      shell.openExternal(url);
    } catch (_e) {
      // best-effort
    }
    return { action: "deny" };
  });

  mainWindow.loadURL(cfg.origin);

  mainWindow.on("move", persistWindowState);
  mainWindow.on("resize", persistWindowState);
  mainWindow.on("close", persistWindowStateNow);
  mainWindow.on("closed", () => {
    mainWindow = null;
  });

  buildMenu();
}

// Scoped certificate trust: trust ONLY the RC origin host's self-signed cert.
// Every other host falls through to normal cert validation. This is the spec's
// hard requirement (section 3.4): never globally disable cert errors.
app.on("certificate-error", (event, _webContents, url, _error, _cert, callback) => {
  let host = "";
  try {
    host = new URL(url).host;
  } catch (_e) {
    host = "";
  }
  if (host && originHost && host === originHost) {
    event.preventDefault();
    callback(true); // trust RC's mkcert self-signed cert
  } else {
    callback(false); // everything else: normal cert rules
  }
});

// Single-instance: a second launch focuses the existing window instead of
// spawning a duplicate companion.
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      if (mainWindow.isMinimized()) {
        mainWindow.restore();
      }
      mainWindow.focus();
    }
  });

  app.whenReady().then(() => {
    createWindow();
    app.on("activate", () => {
      // macOS re-open behavior; harmless on Windows.
      if (BrowserWindow.getAllWindows().length === 0) {
        createWindow();
      }
    });
  });

  app.on("window-all-closed", () => {
    // Quit on all platforms (single-window companion; no tray to keep alive).
    app.quit();
  });
}
