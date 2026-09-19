// lane-widget/src/main.js
//
// Electron entry point for the lane / worker widget. This file is GLUE ONLY -
// every decision it needs is made by a pure, unit-tested module:
//
//   clamp.js       window geometry (content size vs work area vs min)
//   store.js       persisted state shape + atomic load/save
//   poll.js        all filesystem and process IO, both cadences
//   tray_icon.js   the tray glyph
//
// Nothing electron-coupled is unit tested, so the honest way to keep the suite
// meaningful is to keep the untestable file free of logic. If a behaviour here
// starts needing a branch, that branch belongs in one of the modules above.
//
// The widget is a READ-ONLY observer of every repo it watches. It opens lock
// files for reading and never writes, locks, unlinks or reaps anything. The
// only thing it writes anywhere is its own state file under Electron userData.

"use strict";

const path = require("path");
const {
  app,
  BrowserWindow,
  Menu,
  Tray,
  ipcMain,
  nativeImage,
  screen,
} = require("electron");

const store = require("./store.js");
const clampMod = require("./clamp.js");
const pollMod = require("./poll.js");
const trayIcon = require("./tray_icon.js");

// The repo root this widget was installed into: <root>/lane-widget/src -> root.
// poll.js resolves the rest of the roster from there (RC is always index 0).
const RC_ROOT = path.resolve(__dirname, "..", "..");

// Hard floor for the window. clamp.js will not go below this even on an absurd
// work area - a 20px window is worse than one that overhangs.
const MIN_SIZE = { width: 240, height: 120 };

let mainWindow = null;
let tray = null;
let poller = null;
let isQuitting = false; // ONLY the tray Exit item sets this; close means hide.
let contentSize = { width: 0, height: 0 }; // last renderer-reported content box.

function statePath() {
  return path.join(app.getPath("userData"), store.STATE_FILE_NAME);
}

function loadState() {
  return store.normalizeState(store.load(statePath(), {}));
}

function saveState(next) {
  store.save(statePath(), store.normalizeState(next));
}

// --- persistence ------------------------------------------------------------
// Debounced writer so a drag (many move events) does not hammer the disk. Same
// 400 ms discipline as rc-shell/src/main.js:124-149.

let saveTimer = null;

function currentGeometry() {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return null;
  }
  const b = mainWindow.getBounds();
  return {
    x: b.x,
    y: b.y,
    width: b.width,
    height: b.height,
    alwaysOnTop: mainWindow.isAlwaysOnTop(),
  };
}

function persistWindowStateNow() {
  if (saveTimer) {
    clearTimeout(saveTimer);
    saveTimer = null;
  }
  const geo = currentGeometry();
  if (!geo) {
    return;
  }
  saveState(Object.assign({}, loadState(), geo));
}

function persistWindowState() {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }
  if (saveTimer) {
    clearTimeout(saveTimer);
  }
  saveTimer = setTimeout(() => {
    saveTimer = null;
    persistWindowStateNow();
  }, 400);
}

// --- geometry ---------------------------------------------------------------

function workAreaFor(bounds) {
  try {
    const display =
      bounds && typeof bounds.x === "number"
        ? screen.getDisplayMatching(bounds)
        : screen.getPrimaryDisplay();
    return display.workArea;
  } catch (_e) {
    return { x: 0, y: 0, width: 1920, height: 1080 };
  }
}

// Apply the clamp decision. The window is never larger than its content needs,
// never larger than the work area, and never smaller than MIN_SIZE.
function applyClamp() {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }
  const b = mainWindow.getBounds();
  const next = clampMod.clampToContent({
    requested: b,
    content: contentSize,
    workArea: workAreaFor(b),
    min: MIN_SIZE,
  });
  try {
    mainWindow.setMinimumSize(MIN_SIZE.width, MIN_SIZE.height);
    if (typeof next.x === "number" && typeof next.y === "number") {
      mainWindow.setBounds({
        x: next.x,
        y: next.y,
        width: next.width,
        height: next.height,
      });
    } else {
      mainWindow.setSize(next.width, next.height);
    }
  } catch (_e) {
    // a window that vanished mid-resize is not an error worth crashing over.
  }
  persistWindowState();
}

// --- menus ------------------------------------------------------------------

function showWindow() {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }
  if (mainWindow.isMinimized()) {
    mainWindow.restore();
  }
  mainWindow.show(); // un-hide - focus() alone never un-hides a hidden window.
  mainWindow.focus();
}

function buildWindowMenu() {
  return Menu.buildFromTemplate([
    {
      label: "Minimize",
      click: () => {
        if (mainWindow && !mainWindow.isDestroyed()) {
          mainWindow.minimize();
        }
      },
    },
    {
      label: "Close to tray",
      click: () => {
        if (mainWindow && !mainWindow.isDestroyed()) {
          mainWindow.hide();
        }
      },
    },
  ]);
}

function buildTrayMenu() {
  return Menu.buildFromTemplate([
    { label: "Open", click: showWindow },
    {
      // v1 has no separate settings window: the gear affordance lives in the
      // panel itself. Revealing the window is therefore the whole action. A
      // dedicated channel would extend the FROZEN IPC contract (spec 3) that
      // the renderer slice codes against, so it is deliberately not added here.
      label: "Settings",
      click: showWindow,
    },
    { type: "separator" },
    {
      label: "Exit",
      click: () => {
        isQuitting = true; // the ONLY path that actually quits.
        app.quit();
      },
    },
  ]);
}

function createTray() {
  const image = trayIcon.createTrayImage(nativeImage);
  try {
    tray = image ? new Tray(image) : new Tray(nativeImage.createEmpty());
  } catch (_e) {
    tray = null; // a tray is a convenience - never block startup on it.
    return;
  }
  tray.setToolTip("Lane widget");
  tray.setContextMenu(buildTrayMenu());
  tray.on("click", showWindow);
  tray.on("double-click", showWindow);
}

// --- window -----------------------------------------------------------------

function createWindow() {
  const state = loadState();
  const probe = {
    x: state.x,
    y: state.y,
    width: state.width,
    height: state.height,
  };
  const placed = clampMod.clampToContent({
    requested: probe,
    content: { width: 0, height: 0 }, // no report yet - the saved size stands.
    workArea: workAreaFor(probe),
    min: MIN_SIZE,
  });

  const opts = {
    width: placed.width,
    height: placed.height,
    minWidth: MIN_SIZE.width,
    minHeight: MIN_SIZE.height,
    frame: false,
    transparent: true,
    alwaysOnTop: state.alwaysOnTop,
    skipTaskbar: true,
    resizable: true,
    focusable: true,
    hasShadow: false,
    show: false, // until ready-to-show, so it never appears pre-layout.
    backgroundColor: "#00000000",
    title: "Lane widget",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      backgroundThrottling: false,
    },
  };
  if (typeof placed.x === "number" && typeof placed.y === "number") {
    opts.x = placed.x;
    opts.y = placed.y;
  }

  mainWindow = new BrowserWindow(opts);
  // screen-saver level keeps a frameless widget above a borderless fullscreen
  // app, which plain alwaysOnTop does not (rc-shell/src/main.js:631).
  mainWindow.setAlwaysOnTop(!!state.alwaysOnTop, "screen-saver");
  mainWindow.setOpacity(state.opacity);

  mainWindow.once("ready-to-show", () => {
    mainWindow.show();
  });

  mainWindow.on("move", persistWindowState);
  mainWindow.on("resize", persistWindowState);

  // CLOSE MEANS HIDE. Only the tray Exit item quits (isQuitting).
  mainWindow.on("close", (event) => {
    if (!isQuitting) {
      event.preventDefault();
      persistWindowStateNow(); // synchronous flush - the debounce is too late.
      mainWindow.hide();
      return;
    }
    persistWindowStateNow();
  });

  mainWindow.loadFile(path.join(__dirname, "renderer", "index.html"));
}

// --- IPC --------------------------------------------------------------------
// Exactly the four frozen channels from spec section 3. No others.

function registerIpc() {
  ipcMain.handle("lane-widget:state:get", () => {
    return loadState();
  });

  ipcMain.handle("lane-widget:state:set", (_event, patch) => {
    const p = patch && typeof patch === "object" ? patch : {};
    const next = store.normalizeState(Object.assign({}, loadState(), p));
    saveState(next);
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.setOpacity(next.opacity);
      mainWindow.setAlwaysOnTop(next.alwaysOnTop, "screen-saver");
    }
    if (poller) {
      poller.setFastMs(next.fastMs);
    }
    return next;
  });

  ipcMain.on("lane-widget:win:menu", () => {
    if (!mainWindow || mainWindow.isDestroyed()) {
      return;
    }
    buildWindowMenu().popup({ window: mainWindow });
  });

  ipcMain.on("lane-widget:size", (_event, size) => {
    const s = size && typeof size === "object" ? size : {};
    contentSize = {
      width: Number(s.width) || 0,
      height: Number(s.height) || 0,
    };
    applyClamp();
  });
}

// --- polling ----------------------------------------------------------------

function startPolling() {
  const state = loadState();
  poller = pollMod.createPoller({
    rcRoot: RC_ROOT,
    env: process.env,
    io: pollMod.createDefaultIo({}),
    now: Date.now,
    fastMs: state.fastMs,
    log: (msg) => {
      console.warn(msg);
    },
    onModel: (model) => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send("lane-widget:model", model);
      }
    },
  });
  poller.start();
}

// --- lifecycle --------------------------------------------------------------

// Single instance: a second launch RAISES the existing window instead of
// spawning a duplicate (spec section 4 acceptance: two launches, one window).
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    showWindow();
  });

  // A tray app outlives its window: hiding the last window must not quit.
  app.on("window-all-closed", () => {
    // deliberately empty - tray Exit is the only quit path.
  });

  app.on("before-quit", () => {
    isQuitting = true;
    persistWindowStateNow();
  });

  app.on("will-quit", () => {
    if (poller) {
      poller.stop();
      poller = null;
    }
    if (tray) {
      tray.destroy();
      tray = null;
    }
  });

  app.whenReady().then(() => {
    registerIpc();
    createWindow();
    createTray();
    startPolling();

    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0) {
        createWindow();
      } else {
        showWindow();
      }
    });
  });
}
