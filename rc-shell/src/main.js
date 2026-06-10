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
// Phase 2 + 3 (this slice): a transparent always-on-top OVERLAY window + a
// global hotkey toggle + a /api/state poll that surface-switches companion <->
// overlay by mode_key (see ./overlay_state, the pure state machine).
//
// Phase 4 (partial - shell-side interactivity hardening):
//   - ACTIVE auto-revert: flipping the overlay interactive (Alt+Shift+A) arms
//     a 20s countdown back to the passive click-through HUD; any hotkey press
//     re-arms/cancels it (see ov.makeActiveRevert - the pure deadline state).
//   - Backend-offline backoff: consecutive /api/state failures back the poll
//     off exponentially to 15s (ov.nextPollDelay); a success snaps it back.
//   - Panel-set cycle: Alt+Shift+C rotates the overlay through the PANEL_SETS
//     (coach -> build -> threat) by reloading the overlay URL with
//     panelset=NAME (ov.cyclePanelSet + ov.overlayUrl).
//
// What it does NOT do (Vanguard-safe; see docs/ELECTRON_OVERLAY.md sections 3.8 + 8):
//   - No DXGI / frame capture, no game-memory reads, no input injection - ever.
//     The overlay is a DWM compositor window only; the hotkey is RegisterHotKey
//     (anti-cheat-safe), the same path RC-HotkeyListener uses.
//   - No Pengu / in-client (Phase 6).

"use strict";

const path = require("path");
const https = require("https");
const http = require("http");
const { app, BrowserWindow, Menu, screen, shell, globalShortcut } = require("electron");

const cfgmod = require("./config");
const store = require("./store");
const ov = require("./overlay_state");

// Persistence target: <userData>/rc-shell-state.json. userData is per-app and
// per-OS-user, so two machines / two users never collide.
function statePath() {
  return path.join(app.getPath("userData"), "rc-shell-state.json");
}

let mainWindow = null;
let overlayWindow = null;
let originHost = ""; // host:port we trust the self-signed cert for.
let resolvedOrigin = ""; // the origin resolved at boot (companion + overlay + poll).
let surfaceHidden = false; // hotkey-driven force-hide override.
let overlayClickThrough = ov.OVERLAY_DEFAULTS.clickThrough;
let pollTimer = null; // chained setTimeout handle (variable cadence, Phase 4b).
let pollFailures = 0; // consecutive /api/state failures (drives the backoff).
let lastSurface = null; // de-dupe redundant show/hide churn.
let lastMode = ""; // last mode_key seen by the poll (for hotkey re-apply).
let panelSet = null; // current overlay panel set; null = plain overlay=1.
let activeRevertTimer = null; // setTimeout wakeup for the ACTIVE auto-revert.
const activeRevert = ov.makeActiveRevert({}); // pure deadline state (20s default).

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
  resolvedOrigin = cfg.origin;

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

// --- Phase 3 overlay window ---------------------------------------------------
// A transparent, frameless, always-on-top window loading the overlay route. It
// is created lazily on first show so a session that never enters a game pays
// nothing. Click-through (setIgnoreMouseEvents) makes it a passive HUD by
// default; the ACTIVE hotkey flips it interactive.
function createOverlayWindow() {
  if (overlayWindow && !overlayWindow.isDestroyed()) {
    return overlayWindow;
  }
  const primary = screen.getPrimaryDisplay();
  const area = primary.workArea;
  const w = ov.OVERLAY_DEFAULTS.width;
  const h = ov.OVERLAY_DEFAULTS.height;
  overlayWindow = new BrowserWindow({
    width: w,
    height: h,
    // Dock to the right edge of the primary work area by default.
    x: Math.max(area.x, area.x + area.width - w),
    y: area.y,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    resizable: false,
    focusable: !overlayClickThrough,
    hasShadow: false,
    show: false,
    backgroundColor: "#00000000",
    title: "Riot Commander Overlay",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  // screen-saver level keeps it above a Borderless game.
  overlayWindow.setAlwaysOnTop(true, "screen-saver");
  overlayWindow.setIgnoreMouseEvents(overlayClickThrough, { forward: true });
  overlayWindow.webContents.setWindowOpenHandler(({ url }) => {
    try {
      shell.openExternal(url);
    } catch (_e) {
      // best-effort
    }
    return { action: "deny" };
  });
  overlayWindow.loadURL(ov.overlayUrl(resolvedOrigin, panelSet));
  overlayWindow.on("closed", () => {
    overlayWindow = null;
  });
  return overlayWindow;
}

function applyClickThrough() {
  if (overlayWindow && !overlayWindow.isDestroyed()) {
    overlayWindow.setIgnoreMouseEvents(overlayClickThrough, { forward: true });
    overlayWindow.setFocusable(!overlayClickThrough);
  }
}

// --- Phase 4a: ACTIVE auto-revert ----------------------------------------------
// Re-evaluate the auto-revert countdown after any click-through change or any
// hotkey press. ACTIVE (not click-through) arms a fresh deadline + a setTimeout
// wakeup; PASSIVE cancels both. The pure activeRevert object is the source of
// truth - the timeout only acts if the deadline is genuinely due, so a re-arm
// that raced an in-flight timeout can never cause an early revert.
function scheduleActiveRevert() {
  if (activeRevertTimer) {
    clearTimeout(activeRevertTimer);
    activeRevertTimer = null;
  }
  activeRevert.cancel();
  if (overlayClickThrough) {
    return; // PASSIVE - nothing to revert.
  }
  activeRevert.arm();
  activeRevertTimer = setTimeout(() => {
    activeRevertTimer = null;
    if (activeRevert.due()) {
      overlayClickThrough = true; // auto-revert to the passive HUD.
      applyClickThrough();
    }
  }, ov.OVERLAY_DEFAULTS.activeRevertDelayMs);
}

// Show/hide the two surfaces to match a resolved surface, skipping no-op churn.
function applySurface(surface) {
  if (surface === lastSurface) {
    return;
  }
  lastSurface = surface;
  const actions = ov.windowActions(surface);
  if (mainWindow && !mainWindow.isDestroyed()) {
    if (actions.companion === "show") {
      mainWindow.showInactive();
    } else {
      mainWindow.hide();
    }
  }
  if (actions.overlay === "show") {
    createOverlayWindow();
    if (overlayWindow && !overlayWindow.isDestroyed()) {
      overlayWindow.showInactive();
    }
  } else if (overlayWindow && !overlayWindow.isDestroyed()) {
    overlayWindow.hide();
  }
}

// Re-resolve + apply the surface for the current mode + hidden override.
function refreshSurface(modeKey) {
  applySurface(ov.resolveSurface(modeKey, surfaceHidden));
}

// Best-effort /api/state poll. The shell's own dashboard is a self-signed
// localhost/LAN origin, so the poll request alone relaxes TLS for THAT origin
// (the BrowserWindow cert trust is separately scoped by the app handler). Any
// failure leaves the last surface untouched - never throws. Reports the
// outcome via done(ok) exactly once so the loop can back off (Phase 4b).
function pollState(done) {
  let settled = false;
  const finish = (ok) => {
    if (settled) {
      return;
    }
    settled = true;
    if (typeof done === "function") {
      done(ok);
    }
  };
  if (!resolvedOrigin) {
    finish(false);
    return;
  }
  let url;
  try {
    url = new URL("/api/state", resolvedOrigin);
  } catch (_e) {
    finish(false);
    return;
  }
  const mod = url.protocol === "https:" ? https : http;
  let req;
  try {
    req = mod.request(
      url,
      { method: "GET", timeout: 1500, rejectUnauthorized: false },
      (res) => {
        let data = "";
        res.on("data", (d) => {
          data += d;
        });
        res.on("end", () => {
          try {
            lastMode = ov.normMode(JSON.parse(data).mode_key);
            refreshSurface(lastMode);
            finish(true);
          } catch (_e) {
            // leave surface as-is on a parse miss; counts as a failure.
            finish(false);
          }
        });
      }
    );
  } catch (_e) {
    finish(false);
    return;
  }
  req.on("error", () => finish(false));
  req.on("timeout", () => {
    finish(false);
    req.destroy();
  });
  req.on("close", () => finish(false)); // backstop: no response at all.
  req.end();
}

// Chained-setTimeout poll loop: each completed poll schedules the next at
// ov.nextPollDelay - base cadence while the backend answers, exponential
// backoff (capped 15s) while it is offline, snapping back on first success.
function schedulePoll(delayMs) {
  if (pollTimer) {
    clearTimeout(pollTimer);
  }
  pollTimer = setTimeout(runPoll, delayMs);
}

function runPoll() {
  pollState((ok) => {
    pollFailures = ok ? 0 : pollFailures + 1;
    schedulePoll(ov.nextPollDelay(pollFailures, ov.OVERLAY_DEFAULTS.pollMs));
  });
}

function startPoll() {
  if (pollTimer) {
    clearTimeout(pollTimer);
    pollTimer = null;
  }
  pollFailures = 0;
  runPoll();
}

// Global hotkeys (RegisterHotKey under the hood; anti-cheat-safe). Toggle hides
// the active surface; Active flips overlay click-through (with a 20s auto-
// revert to passive); Cycle rotates the overlay panel set. Every hotkey press
// re-evaluates the auto-revert countdown (press = the operator is interacting).
function registerHotkeys() {
  try {
    globalShortcut.register(ov.OVERLAY_DEFAULTS.hotkeyToggle, () => {
      surfaceHidden = !surfaceHidden;
      lastSurface = null; // force a re-apply
      refreshSurface(lastMode);
      scheduleActiveRevert();
    });
    globalShortcut.register(ov.OVERLAY_DEFAULTS.hotkeyActive, () => {
      overlayClickThrough = !overlayClickThrough;
      applyClickThrough();
      scheduleActiveRevert(); // ACTIVE arms the revert; PASSIVE cancels it.
    });
    globalShortcut.register(ov.OVERLAY_DEFAULTS.hotkeyCycle, () => {
      panelSet = ov.cyclePanelSet(panelSet);
      if (overlayWindow && !overlayWindow.isDestroyed()) {
        overlayWindow.loadURL(ov.overlayUrl(resolvedOrigin, panelSet));
      }
      scheduleActiveRevert();
    });
  } catch (_e) {
    // a busy accelerator is non-fatal; the menu still works.
  }
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
    registerHotkeys();
    startPoll();
    app.on("activate", () => {
      // macOS re-open behavior; harmless on Windows.
      if (BrowserWindow.getAllWindows().length === 0) {
        createWindow();
      }
    });
  });

  app.on("will-quit", () => {
    if (pollTimer) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
    if (activeRevertTimer) {
      clearTimeout(activeRevertTimer);
      activeRevertTimer = null;
    }
    activeRevert.cancel();
    globalShortcut.unregisterAll();
  });

  app.on("window-all-closed", () => {
    // Quit on all platforms (single-window companion; no tray to keep alive).
    app.quit();
  });
}
