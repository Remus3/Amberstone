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
//
// This is the floor of LAST RESORT, not the floor the user drags against. Once
// the renderer has reported a content box, applyClampNow raises the enforced
// minimum WIDTH to clamp.js minimumSizeFor - the width the clamp is going to
// impose anyway - because .panel is width:max-content and does not shrink, so
// every pixel of drag below it is clipped panel (the gear first). Until that
// first report there is no content box to track and this constant stands.
const MIN_SIZE = { width: 240, height: 120 };

// First paint used to land the pre-layout box (404x352) and the first model
// push then resized it to its real size about 110 ms later - a visible pop on
// every launch. The window is now held hidden until the first clamp has sized
// it. This is the SAFETY net for that: if the renderer never reports a content
// size (a poll that yields no model, a renderer that failed to boot) the window
// must still appear rather than being invisible forever. 1500 ms is ~13x the
// measured 110 ms first-push latency, so it never fires on a healthy launch.
const FIRST_LAYOUT_TIMEOUT_MS = 1500;

// --- user-resize settle (see scheduleSettleClamp) ----------------------------
// A manual resize is re-clamped when the DRAG ENDS, not on every `resize` tick:
// Windows streams `resize` continuously while a handle is held, and snapping on
// each one makes the window feel stuck. `resized` (electron 33.4.11
// electron.d.ts:4306-4314, @platform darwin,win32) is exactly "emitted once when
// the window has finished being resized", so that is the primary trigger.
//
// These two timers are the fallback for the resizes `resized` does NOT cover.
//   RESIZE_SETTLE_MS  no drag is in progress (an Aero snap, a programmatic
//                     resize, or a platform where `resized` never fires).
//                     Short, because there is no drag to interrupt.
//                     A MAXIMIZE arms this timer too, and that used to read as
//                     coverage when it was none: the timer fired on schedule
//                     and the clamp it ran was INERT, because Windows silently
//                     discards setBounds on a maximized window. Measured on
//                     screen: 2576x1416 at -8,-8 over a 2560x1400 work area,
//                     uncorrected for 9 s, with 409x1185 of content - the rest
//                     invisible transparent gutter still eating mouse input
//                     across the whole desktop, and persisted in that state.
//                     The timer was never the missing piece; applyClamp
//                     calling unmaximize() first is.
//   DRAG_WATCHDOG_MS  a drag IS in progress (`will-resize` seen, `resized` not
//                     yet). Purely a latch-breaker so `userResizing` cannot stay
//                     true forever on a platform without `resized`. Every
//                     will-resize / resize tick re-arms it, so on a real drag it
//                     only fires if the handle is held perfectly still for two
//                     full seconds - far longer than a normal mid-drag pause.
const RESIZE_SETTLE_MS = 400;
const DRAG_WATCHDOG_MS = 2000;

let mainWindow = null;
let tray = null;
let poller = null;
let isQuitting = false; // ONLY the tray Exit item sets this; close means hide.
let contentSize = { width: 0, height: 0 }; // last renderer-reported content box.

// --- re-entrancy guard for the clamp (see reclampAfterUserResize) ------------
// setBounds/setSize themselves emit `resize`, so a clamp that re-triggers its
// own clamp is a genuine ratchet - an earlier build of this widget walked down
// through 24 sizes to a collapsed 415x126. The guard is EXACT rather than
// time-based: applyClamp records the size it asked the OS for, and the resize
// path no-ops when the window already measures that. Our own echo therefore
// terminates in one step, and a real user drag (which by definition lands on
// some OTHER size) is still handled.
let lastAppliedSize = null; // { width, height } applyClamp last asked for.
let userResizing = false; // a manual drag is in flight (will-resize seen).
let settleTimer = null;

// --- first-show gating (see FIRST_LAYOUT_TIMEOUT_MS) -------------------------
let readyToShow = false; // the renderer has painted at least once.
let firstClampDone = false; // a content size has been reported and applied.
let windowShown = false; // reveal is idempotent - show() only ever runs once.
let showTimer = null;

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
  // A MAXIMIZED RECT MUST NEVER REACH THE STATE FILE. applyClamp restores and
  // re-clamps within one settle interval, so the debounced writer normally sees
  // the clamped box - but persistWindowStateNow is SYNCHRONOUS and runs on
  // close / before-quit, so a tray Exit inside that window would otherwise
  // freeze the bad geometry on disk and reload it maximized at next launch.
  // getNormalBounds (electron 33.4.11 electron.d.ts:2596-2604 BaseWindow /
  // :5164-5172 BrowserWindow) is documented to return "the position and size of
  // the window in normal state" whatever the current state, and to equal
  // getBounds in the normal state - so it is only consulted while maximized,
  // keeping every other path byte-for-byte what it already was.
  let b;
  try {
    b = mainWindow.isMaximized()
      ? mainWindow.getNormalBounds()
      : mainWindow.getBounds();
  } catch (_e) {
    b = mainWindow.getBounds();
  }
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

// Re-entrancy latch for applyClamp. unmaximize / setBounds / setSize all emit
// `resize`, and `resized` (whose handler calls straight back into the clamp) is
// documented only as "usually" manual, so a nested call is not something to
// reason about per platform. A nested call is dropped instead: the outer call
// is already going to finish by applying the clamped box, and the very resize
// events that could nest also arm the settle timer, which re-checks the real
// bounds afterwards. Nothing is lost by dropping the inner call.
let clampInFlight = false;

// Apply the clamp decision. The window is never larger than its content needs,
// never larger than the work area, and never smaller than MIN_SIZE.
function applyClamp() {
  if (!mainWindow || mainWindow.isDestroyed() || clampInFlight) {
    return;
  }
  clampInFlight = true;
  try {
    applyClampNow();
  } finally {
    clampInFlight = false;
  }
}

function applyClampNow() {
  // WINDOWS IGNORES setBounds ON A MAXIMIZED WINDOW - it does not fail, it does
  // nothing, so the clamp below would record lastAppliedSize and believe it had
  // succeeded while the window stayed at the maximized rect forever. Restoring
  // FIRST is what makes every line after this one able to take effect.
  // isMaximized (electron 33.4.11 electron.d.ts:2734 BaseWindow / :5306
  // BrowserWindow, "Whether the window is maximized") and unmaximize
  // (electron.d.ts:3344 / :5974, "Unmaximizes the window") are both unqualified
  // by @platform, so this needs no platform test.
  //
  // Bounds are read AFTER the restore on purpose: unmaximize returns the window
  // to its pre-maximize rect, which is a box this same clamp already approved,
  // so the usual path finds nothing to change and skips the OS call entirely.
  // If a platform ever reports the maximized rect here anyway, the clamp caps
  // it to the work area and setBounds - now legal, the window is restored -
  // corrects it in the same single step. Neither branch needs the other.
  try {
    if (mainWindow.isMaximized()) {
      mainWindow.unmaximize();
    }
  } catch (_e) {
    // a window that vanished mid-restore is not an error worth crashing over.
  }
  if (mainWindow.isDestroyed()) {
    return;
  }
  const b = mainWindow.getBounds();
  const work = workAreaFor(b);
  const next = clampMod.clampToContent({
    requested: b,
    content: contentSize,
    workArea: work,
    min: MIN_SIZE,
  });
  // The floor the USER drags against, which tracks the content width - see the
  // note on minimumSizeFor. It is never wider than next.width, so it cannot
  // make the setBounds below unsatisfiable.
  const floor = clampMod.minimumSizeFor({
    content: contentSize,
    workArea: work,
    min: MIN_SIZE,
  });
  // Remember what we are about to ask for BEFORE asking - setBounds can emit
  // `resize` synchronously, and the handler reads this to recognise the echo.
  lastAppliedSize = { width: next.width, height: next.height };
  const sameSize = b.width === next.width && b.height === next.height;
  const hasPos = typeof next.x === "number" && typeof next.y === "number";
  const samePos = !hasPos || (b.x === next.x && b.y === next.y);
  try {
    mainWindow.setMinimumSize(floor.width, floor.height);
    // Skip the OS call when the window is already exactly right. Geometry is
    // unchanged either way; what this avoids is a pointless `resize` event.
    if (!sameSize || !samePos) {
      if (hasPos) {
        mainWindow.setBounds({
          x: next.x,
          y: next.y,
          width: next.width,
          height: next.height,
        });
      } else {
        mainWindow.setSize(next.width, next.height);
      }
    }
  } catch (_e) {
    // a window that vanished mid-resize is not an error worth crashing over.
  }
  // The window is now at its real size, so it is safe to reveal.
  firstClampDone = true;
  revealWindow();
  persistWindowState();
}

// Show the window exactly once, and never before the renderer has painted -
// showing unpainted content just trades the resize pop for a blank flash. Both
// preconditions can arrive in either order, so both callers try and whichever
// completes the pair wins.
function revealWindow() {
  if (windowShown || !readyToShow) {
    return;
  }
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }
  windowShown = true;
  clearShowTimer();
  mainWindow.show();
}

function clearShowTimer() {
  if (showTimer) {
    clearTimeout(showTimer);
    showTimer = null;
  }
}

// --- user-resize re-clamp ----------------------------------------------------
// The defect this closes: `resize` was wired to persistWindowState ONLY, and
// applyClamp ran solely from the lane-widget:size IPC. The renderer de-dupes
// identical content sizes, so a user drag changed no MEASURED content box,
// re-reported nothing, and was never corrected - a drag to 250x220 hard-clipped
// the tab strip and put the gear and footer out of reach, and a drag to
// 1800x1500 sat outside a 2560x1400 work area until the next content change
// happened to heal it.
//
// The fix runs the SAME applyClamp against the SAME last-known content size, so
// the result is identical no matter who initiated the resize.

function clearSettleTimer() {
  if (settleTimer) {
    clearTimeout(settleTimer);
    settleTimer = null;
  }
}

function onResizeSettled() {
  settleTimer = null;
  userResizing = false;
  reclampAfterUserResize();
}

function scheduleSettleClamp() {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }
  clearSettleTimer();
  settleTimer = setTimeout(
    onResizeSettled,
    userResizing ? DRAG_WATCHDOG_MS : RESIZE_SETTLE_MS
  );
}

function reclampAfterUserResize() {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }
  // Before the first layout the reveal gate owns sizing. Clamping here would
  // set firstClampDone and show the window early, which is the pop this widget
  // was built to avoid.
  if (!firstClampDone) {
    return;
  }
  const b = mainWindow.getBounds();
  if (
    lastAppliedSize &&
    b.width === lastAppliedSize.width &&
    b.height === lastAppliedSize.height
  ) {
    return; // the echo of our own setBounds, not a user resize. No loop.
  }
  clearSettleTimer();
  applyClamp();
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

// Pop the window menu at the cursor.
//
// NO x/y is passed, on purpose. `PopupOptions` (electron 33.4.11
// electron.d.ts:20772-20786) documents x and y only as "Default is the current
// mouse cursor position. Must be declared if `y` is declared." - it never
// states their frame of reference, so any coordinate supplied here is a guess.
// The first implementation guessed window-relative and translated the screen
// point into it; that was measured WRONG on live screen - a right-click at
// screen (1406,401) with the window at (1272,304) popped the menu at roughly
// screen (137,105), exactly the untranslated delta, so popup() had treated the
// window-relative offset as a screen point.
//
// Both callers are mouse-driven and both want the menu exactly where the click
// landed, so the documented default IS the correct answer for both:
//   - the system-context-menu handler, whose Point (electron.d.ts:2330-2334,
//     "The screen coordinates the context menu was triggered at") is by
//     definition the cursor position at that instant;
//   - the lane-widget:win:menu IPC from a DOM contextmenu in a no-drag control
//     area, which carries no point at all (preload.js:46 sends none).
// Deferring to the default removes the coordinate math, the frame-of-reference
// question and the whole class of error with it.
function popupWindowMenu() {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }
  buildWindowMenu().popup({ window: mainWindow });
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
  // The show-gating flags describe THIS window, so reset them for every window
  // this function builds. Without the reset a second createWindow (the
  // "activate" path) would inherit windowShown = true from the first and the
  // new window would never be revealed at all.
  clearShowTimer();
  readyToShow = false;
  firstClampDone = false;
  windowShown = false;
  contentSize = { width: 0, height: 0 }; // the old window's box is meaningless.

  // Same reasoning for the resize-settle state: it describes THIS window, and a
  // stale lastAppliedSize carried over from a destroyed window could make the
  // new window's first real resize look like our own echo and be skipped.
  clearSettleTimer();
  userResizing = false;
  lastAppliedSize = null;

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
    // A maximized state is meaningless for a window that sizes itself to its
    // content, and on a frame:false + transparent:true window it is harmful:
    // nothing calls setIgnoreMouseEvents, so the empty gutter is invisible and
    // still takes mouse input over everything beneath it. maximizable:false
    // (BaseWindowConstructorOptions, electron 33.4.11 electron.d.ts:3607-3612,
    // @platform darwin,win32; the live property is electron.d.ts:3422 / :6048)
    // clears WS_MAXIMIZEBOX, which is the gate Windows checks for Win+Up, the
    // maximize button and a caption double-click - and widget.css makes the
    // whole panel a drag region, i.e. caption, so that double-click is a real
    // path here rather than a hypothetical one.
    //
    // PREVENTION ONLY, and deliberately not the whole fix. A half-screen Aero
    // snap is gated on WS_THICKFRAME (resizable:true) and not on this flag, a
    // third-party window manager can size the window however it likes, and any
    // future programmatic maximize() ignores it outright - so this flag can
    // never be the only defence. applyClamp's unmaximize() is the correction
    // that holds no matter how the window got maximized; this only keeps the
    // common paths from ever painting a full-desktop blocker in the first
    // place, which the correction alone would leave on screen for up to one
    // RESIZE_SETTLE_MS. Belt and braces, with the braces doing the work.
    maximizable: false,
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
    readyToShow = true;
    if (firstClampDone) {
      revealWindow(); // the size arrived first - nothing left to wait for.
      return;
    }
    // Painted but not yet sized. Wait for the first clamp, under a timeout so a
    // renderer that never reports a size cannot leave the window invisible.
    clearShowTimer();
    showTimer = setTimeout(() => {
      showTimer = null;
      firstClampDone = true; // give up waiting; show at the pre-layout size.
      revealWindow();
    }, FIRST_LAYOUT_TIMEOUT_MS);
  });

  // WINDOWS ONLY. widget.css puts `-webkit-app-region: drag` on the whole
  // panel, which makes every pixel non-client area: a right-click there raises
  // the Windows system menu and the DOM contextmenu event NEVER fires, so the
  // lane-widget:win:menu IPC could never be reached from the panel body and
  // "Close to tray" was unreachable. Electron emits this event for exactly that
  // case (verified against electron 33.4.11, @platform win32, electron.d.ts:
  // 2330-2334). Preventing the system menu and popping our own reaches the drag
  // region WITHOUT giving up full-window drag; the IPC path still serves the
  // no-drag control areas, and on any other platform this event never fires.
  // The event's second argument (the trigger point, in SCREEN coordinates) is
  // deliberately ignored - it is the cursor position, which is what popup()
  // defaults to anyway. See popupWindowMenu for why passing it was wrong.
  mainWindow.on("system-context-menu", (event) => {
    if (!mainWindow || mainWindow.isDestroyed()) {
      return;
    }
    event.preventDefault();
    popupWindowMenu();
  });

  mainWindow.on("move", persistWindowState);

  // A manual resize is corrected when the drag ENDS. `resize` keeps doing what
  // it always did (debounced persistence - the gate confirmed geometry survives
  // a tray Exit and relaunch) and additionally arms the settle fallback; it
  // never clamps directly, because clamping on a stream of drag ticks is the
  // "fighting the user" failure.
  mainWindow.on("resize", () => {
    persistWindowState();
    scheduleSettleClamp();
  });

  // `will-resize` fires ONLY for a manual resize - "Resizing the window with
  // `setBounds`/`setSize` will not emit this event" (electron 33.4.11
  // electron.d.ts:4873-4891, @platform darwin,win32). That makes it an exact
  // "a drag is in flight" marker, which is what lengthens the settle fallback
  // so a mid-drag pause cannot snap the window out from under the cursor. The
  // newBounds/details arguments are deliberately unused: we clamp the REAL
  // bounds at drag end, not a predicted one, and the event is never prevented.
  mainWindow.on("will-resize", () => {
    userResizing = true;
    scheduleSettleClamp();
  });

  // The primary trigger. "Emitted once when the window has finished being
  // resized... usually emitted when the window has been resized manually"
  // (electron 33.4.11 electron.d.ts:4306-4314, @platform darwin,win32).
  mainWindow.on("resized", () => {
    userResizing = false;
    reclampAfterUserResize();
  });

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

  // The no-drag path: a DOM contextmenu inside a control area, where the
  // renderer DOES get the event. The frozen channel carries no payload, so the
  // menu pops at the cursor - which is where that right-click landed. The drag
  // region is covered by the system-context-menu handler.
  ipcMain.on("lane-widget:win:menu", () => {
    popupWindowMenu();
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
    // NO `now` key on purpose. poll.js defaults to nowSeconds() and every pure
    // module downstream (locks.js ageS, heartbeat.js, model.js) documents `now`
    // as epoch SECONDS, because the lock `ts` is written by python time.time().
    // Passing Date.now (MILLISECONDS) here made every age 1000x too large - the
    // live run rendered "age 20695328d" - and silently tripped every age-based
    // threshold in the app, including the heartbeat stall check. Inheriting the
    // module's own default is one fewer place to get the unit wrong.
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
    clearShowTimer();
    clearSettleTimer();
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
