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
//   - Drag region: injected -webkit-app-region strip (companion always;
//     overlay grabbable when ACTIVE) - see ./drag_region.
//   - Overlay persistence: overlay position + panel set ride the same state
//     file under one "overlay" key (ov.mergeOverlayPatch keeps the companion
//     keys intact) so a relaunch restores the HUD where the operator left it.
//   - ACTIVE indicator: injected glow frame on the overlay page lights while
//     the overlay is interactive - see ./active_indicator (overlay-only).
//
// Phase 5 (stabilization): electron-updater + GitHub Releases, on stable/dev
// channels (see ./update_channel, the pure channel/plan core). The updater is
// lazy-loaded so a bare checkout runs identically with updates disabled; all
// update events are console-only (no dialogs over a live game) and a download
// installs on natural quit - never quitAndInstall mid-session.
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
const { app, BrowserWindow, Menu, screen, shell, globalShortcut, ipcMain } = require("electron");

const cfgmod = require("./config");
const store = require("./store");
const ov = require("./overlay_state");
const drag = require("./drag_region");
const ind = require("./active_indicator");
const ctz = require("./clickthrough_zones");
const upd = require("./update_channel");
const cg = require("./crash_guard");

// In-game overlay liveness (CRITICAL). A fullscreen League window fully OCCLUDES
// this always-on-top transparent overlay. On Windows, Chromium's native window-
// occlusion detection then freezes the renderer (timers + paint stop), so the HUD
// goes stale mid-game and keeps showing the static pre-game placeholders - and a
// relaunch alone never stuck, because per-window backgroundThrottling:false cannot
// override native occlusion freezing. These app-level switches (must run before app
// is ready) keep the overlay polling /api/state and repainting while the game is the
// foreground window. Ref: electron/electron#25368, Chromium CalculateNativeWinOcclusion.
app.commandLine.appendSwitch("disable-backgrounding-occluded-windows");
app.commandLine.appendSwitch("disable-renderer-backgrounding");
app.commandLine.appendSwitch("disable-features", "CalculateNativeWinOcclusion");

// electron-updater is an OPTIONAL dependency: a bare checkout (no npm install)
// must run identically, just with updates disabled - no crash, no dialog.
// checkPlan() turns a null autoUpdater into the "updater-missing" branch.
let autoUpdater = null;
try {
  ({ autoUpdater } = require("electron-updater"));
} catch (_e) {
  autoUpdater = null;
}

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
let overlayZoneHover = false; // RC2 4.2: cursor-over-an-interactive-zone (renderer-reported, transient).
let pollTimer = null; // chained setTimeout handle (variable cadence, Phase 4b).
let pollFailures = 0; // consecutive /api/state failures (drives the backoff).
let lastSurface = null; // de-dupe redundant show/hide churn.
let lastMode = ""; // last mode_key seen by the poll (for hotkey re-apply).
let lastInGame = false; // last live-game presence (liveclient non-empty) from the poll; gates overlay HUD vs companion.
let panelSet = null; // current overlay panel set; null = plain overlay=1.
let overlayScale = 1; // RC2 4.1: resolution scale for the overlay box + renderer zoom.
let activeRevertTimer = null; // setTimeout wakeup for the ACTIVE auto-revert.
let overlaySettings = ov.overlaySettingsFrom({}); // operator overlay settings (OVL1); loaded from saved at boot.
let activeRevert = ov.makeActiveRevert({ delayMs: overlaySettings.activeRevertSec * 1000 }); // pure deadline state.
let updateChannel = upd.DEFAULT_CHANNEL; // stable/dev release channel (Phase 5).
let updateInitialTimer = null; // one-shot delay before the first update check.
let updateIntervalTimer = null; // recurring update-check handle.
const crashGuard = cg.makeCrashGuard({}); // per-window renderer restart budget (Phase 5).

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

// Overlay position persists under its own debounce timer so a companion drag
// and an overlay drag can never cancel each other's pending write. The patch
// goes through ov.mergeOverlayPatch so the companion's top-level keys survive.
let overlaySaveTimer = null;
function persistOverlayState() {
  if (!overlayWindow || overlayWindow.isDestroyed()) {
    return;
  }
  if (overlaySaveTimer) {
    clearTimeout(overlaySaveTimer);
  }
  overlaySaveTimer = setTimeout(() => {
    overlaySaveTimer = null;
    if (!overlayWindow || overlayWindow.isDestroyed()) {
      return;
    }
    const b = overlayWindow.getBounds();
    store.save(
      statePath(),
      ov.mergeOverlayPatch(store.load(statePath(), {}), { x: b.x, y: b.y })
    );
  }, 400);
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
  // RC2 E1: keep the persisted overlay-settings companionAlwaysOnTop coherent
  // with the menu toggle so the on-screen control and the menu never disagree.
  overlaySettings = ov.overlaySettingsFrom(
    ov.mergeOverlaySettingsPatch(store.load(statePath(), {}), {
      companionAlwaysOnTop: next,
    })
  );
  store.save(
    statePath(),
    ov.mergeOverlaySettingsPatch(store.load(statePath(), {}), {
      companionAlwaysOnTop: next,
    })
  );
  buildMenu(); // refresh the checkbox state
}

// --- Phase 5: auto-update (electron-updater + GitHub Releases) ----------------
// The shell versions on its OWN cadence, decoupled from RC backend pushes
// (docs/ELECTRON_OVERLAY.md section 8). Every update event is console-only -
// this window runs over a live game, so NO dialogs and NO focus steal. The
// downloaded update installs on natural quit (autoInstallOnAppQuit); never
// quitAndInstall mid-session - the operator may be mid-fight.
function setupAutoUpdater() {
  const plan = upd.checkPlan({
    isPackaged: app.isPackaged,
    updaterPresent: !!autoUpdater,
  });
  if (!plan.enabled) {
    // Dev launch (npm start) or bare checkout - both are normal, not errors.
    console.log("[rc-shell] updates disabled: " + plan.reason);
    return;
  }
  autoUpdater.autoDownload = true;
  autoUpdater.autoInstallOnAppQuit = true;
  autoUpdater.allowPrerelease = upd.channelConfig(updateChannel).allowPrerelease;
  autoUpdater.on("error", (err) => {
    console.log(
      "[rc-shell] update error: " + (err && err.message ? err.message : String(err))
    );
  });
  autoUpdater.on("update-available", (info) => {
    console.log(
      "[rc-shell] update available: " + (info && info.version ? info.version : "?")
    );
  });
  autoUpdater.on("update-downloaded", (info) => {
    console.log(
      "[rc-shell] update downloaded (installs on quit): " +
        (info && info.version ? info.version : "?")
    );
  });
  updateInitialTimer = setTimeout(() => {
    updateInitialTimer = null;
    autoUpdater.checkForUpdates().catch(() => {});
  }, plan.initialDelayMs);
  updateIntervalTimer = setInterval(() => {
    autoUpdater.checkForUpdates().catch(() => {});
  }, plan.intervalMs);
}

// Switch the release channel from the menu: validate, persist via the merge
// patch (window/overlay keys survive), re-aim the updater, and check right
// away - a stable -> dev flip should pick up a waiting prerelease without
// sitting out the 4-hour interval.
function setUpdateChannel(ch) {
  updateChannel = upd.resolveChannel({ updateChannel: ch }, {});
  store.save(
    statePath(),
    upd.mergeChannelPatch(store.load(statePath(), {}), updateChannel)
  );
  if (autoUpdater) {
    autoUpdater.allowPrerelease = upd.channelConfig(updateChannel).allowPrerelease;
  }
  const plan = upd.checkPlan({
    isPackaged: app.isPackaged,
    updaterPresent: !!autoUpdater,
  });
  if (plan.enabled) {
    autoUpdater.checkForUpdates().catch(() => {});
  }
  buildMenu(); // refresh the radio state
}

// A minimal application menu: size presets + always-on-top toggle + update
// channel (Phase 5) + reload. This is the low-risk preset switcher the spec
// marks optional. No global hotkeys (those are Phase 2); these are app-menu
// accelerators only, active while the shell is focused.
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
          label: "Update channel: Stable",
          type: "radio",
          checked: updateChannel === "stable",
          click: () => setUpdateChannel("stable"),
        },
        {
          label: "Update channel: Dev",
          type: "radio",
          checked: updateChannel === "dev",
          click: () => setUpdateChannel("dev"),
        },
        {
          label: "Check for updates now",
          click: () => {
            const plan = upd.checkPlan({
              isPackaged: app.isPackaged,
              updaterPresent: !!autoUpdater,
            });
            if (plan.enabled) {
              autoUpdater.checkForUpdates().catch(() => {});
            } else {
              console.log("[rc-shell] updates disabled: " + plan.reason);
            }
          },
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

// Inject the drag-region strip into a window's page. The remote dashboard
// ships no -webkit-app-region rule of its own, so a frameless window is
// unmovable without this. Both calls swallow rejection - the frame may be
// mid-navigation or already gone; a missed strip self-heals on the next load.
function injectDragRegion(win) {
  if (!win || win.isDestroyed()) {
    return;
  }
  win.webContents.insertCSS(drag.dragRegionCSS()).catch(() => {});
  win.webContents.executeJavaScript(drag.dragRegionMountJS(), true).catch(() => {});
}

// Inject the Phase 4 ACTIVE glow frame (overlay-only; the companion is always
// interactive so a cue there would be noise). The set call re-applies the
// CURRENT click-through state, so a mid-game reload that wipes the page keeps
// an already-ACTIVE overlay lit instead of silently dropping the cue.
function injectActiveIndicator(win) {
  if (!win || win.isDestroyed()) {
    return;
  }
  win.webContents.insertCSS(ind.activeIndicatorCSS()).catch(() => {});
  win.webContents.executeJavaScript(ind.activeIndicatorMountJS(), true).catch(() => {});
  win.webContents
    .executeJavaScript(ind.activeIndicatorSetJS(!overlayClickThrough), true)
    .catch(() => {});
}

// --- Phase 5: crash isolation ---------------------------------------------------
// Each BrowserWindow already runs its own renderer process, so one window's
// crash never takes the other (or the game) down. What the guard adds is
// self-healing: a restartable crash reloads ONLY that window, and a crash LOOP
// converges to give-up (hide) instead of strobing a half-dead window over a
// live game. killed/clean-exit are deliberate terminations - never resurrected.
// The budget is keyed per window identity, so it survives an overlay
// destroy/recreate cycle (a crash-looping page cannot reset its own budget).
function attachCrashGuard(win, key) {
  if (!win || win.isDestroyed()) {
    return;
  }
  win.webContents.on("render-process-gone", (_event, details) => {
    const reason = details && details.reason ? details.reason : "";
    const verdict = crashGuard.record(key, reason);
    console.log(
      "[rc-shell] renderer gone (" + key + "): " + reason + " -> " + verdict.action
    );
    if (win.isDestroyed()) {
      return;
    }
    if (verdict.action === "restart") {
      win.webContents.reload();
    } else if (verdict.action === "give-up") {
      win.hide();
    }
  });
  win.webContents.on("unresponsive", () => {
    // Log only - a long GC or load hitch recovers on its own; killing a
    // merely-slow renderer mid-game would be worse than the hang.
    console.log("[rc-shell] renderer unresponsive (" + key + ")");
  });
}

function createWindow() {
  const saved = store.load(statePath(), {});
  const cfg = cfgmod.resolveConfig(saved, process.env);

  // OVL1: load the operator overlay settings + aim the ACTIVE auto-revert at
  // the saved delay before any hotkey can arm it.
  overlaySettings = ov.overlaySettingsFrom(saved);
  activeRevert = ov.makeActiveRevert({ delayMs: overlaySettings.activeRevertSec * 1000 });

  originHost = cfgmod.originHost(cfg.origin);
  resolvedOrigin = cfg.origin;

  // Restore the overlay panel set before the overlay ever loads. Empty string
  // (nothing saved / unknown) -> null so the plain overlay=1 URL is kept.
  panelSet = ov.overlayStateFrom(saved).panelSet || null;

  // Phase 5: the release channel resolves like the origin - env override
  // beats saved state beats the stable default.
  updateChannel = upd.resolveChannel(saved, process.env);

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
    frame: false, // frameless companion (spec 3.3); drag region injected post-load
    alwaysOnTop: cfg.alwaysOnTop,
    backgroundColor: "#0b0e14", // dark fallback while RC_ORIGIN loads
    title: "Riot Commander",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      // Keep the dashboard live even when unfocused in-game (keepCompanion
      // shows it beside the HUD): same backgroundThrottling reasoning as the
      // overlay window below - a throttled renderer freezes the SSE re-render.
      backgroundThrottling: false,
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

  // Overlay-only (operator 2026-06-21): the companion dashboard no longer
  // auto-surfaces on launch. This boot-show caused a ~2s flash of the big
  // dashboard window over the game before applySurface() switched to the
  // overlay. applySurface (the poll-driven surface machine) still shows the
  // companion out-of-game (surface=companion -> mainWindow.showInactive) and
  // hides it in-game, so visibility stays correct without the launch flash.

  // Re-mount the drag strip on every (re)load - Cmd+R wipes injected DOM.
  mainWindow.webContents.on("did-finish-load", () => injectDragRegion(mainWindow));

  attachCrashGuard(mainWindow, "companion");

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
  // RC2 4.1: DPI + resolution-aware sizing. Grow the box by the work area scale
  // (no-op at the 1920/100% baseline) and hand the same scale to the renderer so
  // its content zoom matches the scaled window.
  const metrics = ov.resolveOverlayMetrics({
    workArea: primary.workArea,
    scaleFactor: primary.scaleFactor,
  });
  overlayScale = metrics.scale;
  // RC Overlay Doctrine 2026-06-21: the overlay is a FULLSCREEN transparent
  // click-through window over the work area (the game shows + plays through it),
  // so the movable widget field (web/js/lib/overlay_layout.js) can place each cue
  // as a tiny accent anywhere on screen - out of the play area - instead of
  // cramming into the old 460px right dock. Per-widget positions are saved by the
  // field manager (rc-overlay-layout), not the window position; metrics.scale
  // still feeds the renderer content zoom (DPI/resolution-aware).
  const _wa = primary.workArea;
  const bounds = { x: _wa.x, y: _wa.y, width: _wa.width, height: _wa.height };
  overlayWindow = new BrowserWindow({
    width: bounds.width,
    height: bounds.height,
    x: bounds.x,
    y: bounds.y,
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
      // CRITICAL for an in-game overlay: Electron defaults backgroundThrottling
      // to true, so when the foreground game OCCLUDES this always-on-top window
      // Chromium suspends its renderer (timers throttled to ~1/s, rAF paused).
      // The /api/state-stream SSE re-render then never runs and the HUD freezes
      // on its initial scaffold ("will render mid-game") even though the backend
      // is feeding live data - the long-standing "overlay dead in-game" symptom.
      // The page itself is correct (it renders fine in a non-occluded browser);
      // only the throttled renderer was the fault. Keep the overlay live.
      backgroundThrottling: false,
    },
  });
  // screen-saver level keeps it above a Borderless game.
  overlayWindow.setAlwaysOnTop(true, "screen-saver");
  // RC2 4.2: passive click-through via the pure zones decision (zoneHover is
  // false at create), and the operator opacity so the HUD recedes into the game.
  overlayWindow.setIgnoreMouseEvents(
    ov.effectiveIgnoreMouse(overlayClickThrough, overlayZoneHover, overlaySettings.clickThroughZones),
    { forward: true }
  );
  overlayWindow.setOpacity(overlaySettings.overlayOpacity);
  overlayWindow.webContents.setWindowOpenHandler(({ url }) => {
    try {
      shell.openExternal(url);
    } catch (_e) {
      // best-effort
    }
    return { action: "deny" };
  });
  overlayWindow.loadURL(ov.overlayUrl(resolvedOrigin, panelSet, overlayScale));
  // Inert while click-through (events forward to the game); once the ACTIVE
  // hotkey flips interactivity the same strip makes the overlay user-movable.
  overlayWindow.webContents.on("did-finish-load", () => {
    injectDragRegion(overlayWindow);
    injectActiveIndicator(overlayWindow);
    injectClickThroughZones(overlayWindow);
  });
  attachCrashGuard(overlayWindow, "overlay");
  overlayWindow.on("move", persistOverlayState);
  overlayWindow.on("closed", () => {
    overlayWindow = null;
  });
  return overlayWindow;
}

// Inject the RC2 4.2 click-through-zones hover detector (overlay-only). The
// page reports cursor-over-a-zone over the preload bridge so a PASSIVE HUD
// becomes interactive on hover without the global ACTIVE hotkey. Idempotent
// (window flag), self-heals on reload, no-ops with no bridge.
function injectClickThroughZones(win) {
  if (!win || win.isDestroyed()) {
    return;
  }
  win.webContents.executeJavaScript(ctz.clickThroughZonesMountJS(), true).catch(() => {});
}

// RC2 4.2: apply the persisted operator overlay opacity (the HUD recedes into
// the game without disappearing). setOpacity is a no-op-safe live call.
function applyOverlayOpacity() {
  if (overlayWindow && !overlayWindow.isDestroyed()) {
    overlayWindow.setOpacity(overlaySettings.overlayOpacity);
  }
}

function applyClickThrough() {
  if (overlayWindow && !overlayWindow.isDestroyed()) {
    // RC2 4.2: the EFFECTIVE ignore layers the transient zone-hover + the
    // zones-enabled setting over the operator/hotkey clickThrough intent.
    const ignore = ov.effectiveIgnoreMouse(
      overlayClickThrough,
      overlayZoneHover,
      overlaySettings.clickThroughZones
    );
    overlayWindow.setIgnoreMouseEvents(ignore, { forward: true });
    overlayWindow.setFocusable(!ignore);
    // The ACTIVE glow tracks the operator intent (clickThrough), NOT the
    // transient zone hover - a micro-hover should not light the full frame.
    overlayWindow.webContents
      .executeJavaScript(ind.activeIndicatorSetJS(!overlayClickThrough), true)
      .catch(() => {});
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
  }, overlaySettings.activeRevertSec * 1000);
}

// --- RC2 Stage 4.4: no-hotkey overlay actions --------------------------------
// Apply a panel-set choice: persist it (a deliberate one-shot action, no
// debounce, so the next launch lands on the same set) and reload the overlay
// window onto the chosen set. Shared by the Alt+Shift+C cycle hotkey AND the
// no-hotkey #ovset selector (over the overlay-action IPC) so the keyboard and
// on-screen paths can never drift.
function applyPanelSet(next) {
  panelSet = next;
  store.save(
    statePath(),
    ov.mergeOverlayPatch(store.load(statePath(), {}), { panelSet: panelSet })
  );
  if (overlayWindow && !overlayWindow.isDestroyed()) {
    overlayWindow.loadURL(ov.overlayUrl(resolvedOrigin, panelSet, overlayScale));
  }
}

// Force the overlay interactive (ACTIVE = not click-through) on demand - the
// no-hotkey "Interact now" button, the on-screen twin of the Alt+Shift+A flip.
// ACTIVE arms the same 20s auto-revert back to the passive HUD.
function setOverlayActive() {
  overlayClickThrough = false;
  applyClickThrough();
  scheduleActiveRevert();
}

// --- RC Overlay Doctrine section 3: reset the movable widget field ------------
// Alt+Shift+R restores every widget to its section-4 default (x,y)+shown state.
// Clears the durable disk mirror immediately (so a close before the renderer's
// debounced re-persist still lands empty) AND tells the overlay page to drop its
// localStorage + re-place at defaults. The renderer exposes window.__rcOverlayReset
// (web/js/lib/overlay_layout.js). No-op-safe if the overlay window is not up.
function resetOverlayLayout() {
  store.save(
    statePath(),
    ov.mergeWidgetLayoutPatch(store.load(statePath(), {}), {})
  );
  if (overlayWindow && !overlayWindow.isDestroyed()) {
    overlayWindow.webContents
      .executeJavaScript("window.__rcOverlayReset && window.__rcOverlayReset()", true)
      .catch(() => {});
  }
}

// --- RC2 E1: companion pin (always-on-top) -----------------------------------
// Apply the persisted companionAlwaysOnTop setting to the companion/dashboard
// window. This is the on-screen pin toggle (no hotkey): the ?overlay=1 renderer
// flips it through the IPC bridge and main.js applies it live + persists it.
function applyCompanionAlwaysOnTop() {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }
  if (mainWindow.isAlwaysOnTop() !== overlaySettings.companionAlwaysOnTop) {
    mainWindow.setAlwaysOnTop(overlaySettings.companionAlwaysOnTop);
    persistWindowState(); // mirror into the top-level alwaysOnTop key
    buildMenu(); // refresh the menu checkbox
  }
}

// --- OVL1: apply changed overlay settings live -------------------------------
// Rebuild the pure deadline state on the new delay so the next arm() honors it,
// and if the overlay is ACTIVE right now, re-arm immediately so a just-changed
// timer takes effect without waiting for the next hotkey press. RC2 E1: also
// re-apply the companion pin and force a surface re-resolve so a just-flipped
// keepCompanion shows/hides the dashboard immediately (lastSurface = null
// defeats the no-op-churn guard in applySurface).
function applyOverlaySettings() {
  activeRevert = ov.makeActiveRevert({ delayMs: overlaySettings.activeRevertSec * 1000 });
  if (!overlayClickThrough) {
    scheduleActiveRevert();
  }
  applyCompanionAlwaysOnTop();
  // RC2 4.2: apply opacity + re-resolve click-through live (a just-flipped
  // clickThroughZones or opacity slider takes effect without a relaunch).
  applyOverlayOpacity();
  applyClickThrough();
  lastSurface = null;
  refreshSurface(lastMode);
}

// IPC bridge handlers (OVL1). The ?overlay=1 renderer reads + writes the
// operator overlay settings through the preload bridge; the state file is the
// authority. set persists via the pure merger (overlay position/panelSet +
// companion keys survive), re-resolves, and applies the new delay live.
function registerIpc() {
  ipcMain.handle("rc-shell:overlay-settings:get", () => {
    overlaySettings = ov.overlaySettingsFrom(store.load(statePath(), {}));
    return overlaySettings;
  });
  // RC Overlay Doctrine section 3: the durable widget-field layout mirror. get
  // seeds the field when localStorage is empty (across a wipe / fresh profile);
  // set persists a drag / scale / reset through the pure merger so the sibling
  // overlay keys (position / panelSet / settings) + the companion keys survive.
  ipcMain.handle("rc-shell:overlay-layout:get", () => {
    return ov.widgetLayoutFrom(store.load(statePath(), {}));
  });
  ipcMain.handle("rc-shell:overlay-layout:set", (_event, layout) => {
    const merged = ov.mergeWidgetLayoutPatch(store.load(statePath(), {}), layout);
    store.save(statePath(), merged);
    return ov.widgetLayoutFrom(merged);
  });
  ipcMain.handle("rc-shell:overlay-settings:set", (_event, patch) => {
    const merged = ov.mergeOverlaySettingsPatch(store.load(statePath(), {}), patch);
    store.save(statePath(), merged);
    overlaySettings = ov.overlaySettingsFrom(merged);
    applyOverlaySettings();
    return overlaySettings;
  });
  // RC2 4.2: a one-way hover ping from the overlay page (no reply needed). The
  // renderer's zone detector reports cursor-over-a-zone; we re-resolve the
  // effective click-through so the HUD captures clicks only over a control.
  ipcMain.on("rc-shell:overlay-zone-hover", (_event, on) => {
    overlayZoneHover = on === true;
    applyClickThrough();
  });
  // RC2 4.4: no-hotkey overlay actions from the #ovset selector. One-way send;
  // ov.normOverlayAction is the allow-list + payload validator (an unlisted /
  // malformed message -> null -> no-op), then we run the SAME primitives the
  // Alt+Shift+C / Alt+Shift+A hotkeys use.
  ipcMain.on("rc-shell:overlay-action", (_event, raw) => {
    const m = ov.normOverlayAction(raw);
    if (!m) {
      return;
    }
    if (m.action === "set-panel") {
      applyPanelSet(m.panelSet);
    } else if (m.action === "set-active") {
      setOverlayActive();
    } else if (m.action === "rearrange") {
      // RC2 4.5: re-separate the overlay + kept dashboard NOW (force past the
      // separateWindows auto kill switch - an explicit operator request).
      applySingleMonitorLayout({ force: true });
    } else if (m.action === "raise-companion") {
      raiseCompanion();
    }
  });
}

// --- RC2 Stage 4.3: single-monitor separated-window arrangement ----------------
// When the in-game overlay shows alongside the kept companion (E1/3.4) on a
// SINGLE monitor, a companion left under the right-docked overlay is visible but
// covered - the dashboard is "available" yet useless. Nudge an overlapping
// companion to the free side so the two windows are SEPARATED side-by-side (the
// dashboard sits beside the HUD, not on top of it). Multi-monitor setups are
// untouched (the operator can punt the dashboard to a 2nd screen). Reposition
// only - never resize - so the size preset survives. ov.resolveSeparatedCompanion
// Bounds is the pure decision (respects a companion already clear of the overlay).
// RC2 4.5: opts.force bypasses the separateWindows kill switch - that switch
// gates the AUTOMATIC arrangement (on the in-game transition), but an explicit
// on-demand "Re-arrange" button press is the operator asking directly, so it
// should run even with auto-arrange turned off. The single-display + overlap
// logic is unchanged either way (reposition only; the size preset survives).
function applySingleMonitorLayout(opts) {
  const force = opts && typeof opts === "object" && opts.force === true;
  if (!force && !overlaySettings.separateWindows) {
    return; // operator kill switch (no-hotkey #ovset toggle).
  }
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }
  if (!overlayWindow || overlayWindow.isDestroyed()) {
    return;
  }
  let displays;
  let work;
  try {
    displays = screen.getAllDisplays();
    work = screen.getPrimaryDisplay().workArea;
  } catch (_e) {
    return; // screen API hiccup -> leave the windows where they are.
  }
  // Single-monitor only: with >= 2 displays the operator arranges freely.
  if (!Array.isArray(displays) || displays.length > 1) {
    return;
  }
  const next = ov.resolveSeparatedCompanionBounds(
    mainWindow.getBounds(),
    overlayWindow.getBounds(),
    work
  );
  if (next.moved && typeof next.x === "number" && typeof next.y === "number") {
    mainWindow.setBounds({
      x: next.x,
      y: next.y,
      width: next.width,
      height: next.height,
    });
    persistWindowState(); // remember where the auto-arrange parked it.
  }
}

// RC2 4.5: bring the kept dashboard forward beside the HUD. The overlay sits at
// the screen-saver z-level so it stays above the game; in-game the companion is
// shown via showInactive (no focus steal) and can fall behind. "Show dashboard"
// (the no-hotkey #ovset button + raise-companion IPC) surfaces it on demand:
// show + moveTop raises it WITHOUT resizing (reposition is the forced layout's
// job), then a forced single-monitor re-arrange tiles it beside the overlay.
// This is the coexistence answer to "where did my dashboard go" - it never
// hides the overlay, so it cannot strand the operator.
function raiseCompanion() {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }
  if (!mainWindow.isVisible()) {
    mainWindow.showInactive(); // make it visible without stealing game focus.
  }
  mainWindow.moveTop();
  applySingleMonitorLayout({ force: true });
}

// Show/hide the two surfaces to match a resolved surface, skipping no-op churn.
// RC2 E1: keepCompanion (operator setting, default ON) keeps the full dashboard
// window available alongside the in-game overlay instead of hiding it - the fix
// for the "dashboard disappears in a game" bug. windowActionsWithPolicy layers
// that override on the base surface actions.
function applySurface(surface) {
  if (surface === lastSurface) {
    return;
  }
  lastSurface = surface;
  const actions = ov.windowActionsWithPolicy(surface, {
    keepCompanion: overlaySettings.keepCompanion,
  });
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
  // RC2 4.3: with both windows up on one monitor, separate them side-by-side.
  if (actions.companion === "show" && actions.overlay === "show") {
    applySingleMonitorLayout();
  }
}

// Re-resolve + apply the surface for the current mode + hidden override.
// inGame defaults to the last poll's live-game presence so the hotkey + pin
// re-apply callers (which pass only the mode) keep the current surface gate.
function refreshSurface(modeKey, inGame = lastInGame) {
  applySurface(ov.resolveSurface(modeKey, surfaceHidden, inGame));
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
            const parsed = JSON.parse(data);
            lastMode = ov.normMode(parsed.mode_key);
            lastInGame = ov.liveGameFromState(parsed);
            refreshSurface(lastMode, lastInGame);
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
      applyPanelSet(ov.cyclePanelSet(panelSet));
      scheduleActiveRevert();
    });
    globalShortcut.register(ov.OVERLAY_DEFAULTS.hotkeyReset, () => {
      resetOverlayLayout();
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
    registerIpc();
    createWindow();
    // RC2 E1: apply the persisted companion pin once the window exists. The
    // saved top-level alwaysOnTop already seeded the BrowserWindow at create;
    // this aligns the overlay-settings companionAlwaysOnTop with it.
    applyCompanionAlwaysOnTop();
    setupAutoUpdater();
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
    if (overlaySaveTimer) {
      clearTimeout(overlaySaveTimer);
      overlaySaveTimer = null;
    }
    if (updateInitialTimer) {
      clearTimeout(updateInitialTimer);
      updateInitialTimer = null;
    }
    if (updateIntervalTimer) {
      clearInterval(updateIntervalTimer);
      updateIntervalTimer = null;
    }
    activeRevert.cancel();
    globalShortcut.unregisterAll();
  });

  app.on("window-all-closed", () => {
    // Quit on all platforms (single-window companion; no tray to keep alive).
    app.quit();
  });
}
