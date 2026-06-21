// rc-shell/src/overlay_state.js
//
// PURE overlay surface-switch state machine + overlay constants. NO electron
// import - this is the node:testable core for Phase 2 (state machine + hotkeys)
// and Phase 3 (transparent overlay window) of docs/ELECTRON_OVERLAY.md.
//
// The shell shows ONE of two surfaces at a time, driven by the dashboard
// mode_key (which the main process polls from RC_ORIGIN/api/state):
//   - COMPANION: the dockable frameless window (out of a game - client/lobby/
//     champ-select). This is the Phase 1 window.
//   - OVERLAY:   the transparent always-on-top in-game HUD (in a game).
// A hotkey-driven "hidden" override force-hides whatever surface is active so
// the operator can clear the screen mid-game without alt-tabbing.
//
// Vanguard-safe by construction (see docs/ELECTRON_OVERLAY.md section 8): the
// overlay is a DWM compositor window only. NO DXGI / frame capture, NO game-
// memory reads, NO input injection. The hotkey uses RegisterHotKey under the
// hood (Electron globalShortcut), which is the same anti-cheat-safe path the
// RC-HotkeyListener task already uses. Borderless is mandatory for the game
// (an exclusive-fullscreen game hides any compositor overlay).

"use strict";

// Pure sibling (clampPosition) - still no electron anywhere in this module.
const cfg = require("./config");

const SURFACES = Object.freeze({
  COMPANION: "companion",
  OVERLAY: "overlay",
  HIDDEN: "hidden",
});

// Dashboard mode_key values that mean "in a live game" -> show the overlay.
// Everything else (client / lobby / champ-select / none / unknown) -> companion.
const GAME_MODES = Object.freeze(
  new Set(["sr", "aram", "arena", "tft", "brawl", "game"])
);

// Overlay window + interaction defaults. clickThrough true = the passive HUD
// (mouse events pass to the game underneath); the ACTIVE hotkey flips it off so
// the operator can interact with overlay controls (Phase 4 wires the controls).
const OVERLAY_DEFAULTS = Object.freeze({
  hotkeyToggle: "Alt+Shift+O", // show/hide the active surface
  hotkeyActive: "Alt+Shift+A", // toggle overlay click-through (passive <-> active)
  hotkeyCycle: "Alt+Shift+C", // cycle overlay panel set (spec sec 5)
  hotkeyReset: "Alt+Shift+R", // reset the movable widget field to defaults (doctrine sec 3)
  pollMs: 2000, // /api/state poll cadence (no sub-500ms per the cost rule)
  pollMaxMs: 15000, // backoff ceiling while the backend is offline
  clickThrough: true, // passive HUD by default
  activeRevertDelayMs: 20000, // ACTIVE auto-reverts to PASSIVE after this idle delay
  width: 460,
  height: 900,
});

// Overlay panel sets the cycle hotkey rotates through (spec sec 5). Order is
// the cycle order; index 0 is the landing set for unknown/initial state.
const PANEL_SETS = Object.freeze(["coach", "build", "threat"]);

// --- RC2 Stage 4.4: no-hotkey overlay actions --------------------------------
// The overlay's three hotkeys (Alt+Shift+O/A/C) were the last overlay behaviors
// reachable ONLY by keyboard. 4.4 surfaces the two that make sense as on-screen
// controls over a one-way renderer->main action channel: pick the panel set
// (was the Alt+Shift+C cycle) and interact-now (was the Alt+Shift+A passive<->
// active toggle). The hide/show toggle (Alt+Shift+O) stays a hotkey on purpose:
// it hides BOTH surfaces (panic clear-screen), so a self-hiding on-screen control
// would leave no on-screen way back. This is the allow-list of action names.
// RC2 Stage 4.5 (overlay + dashboard coexistence) adds two payload-free
// COEXISTENCE commands on the same validated channel: "rearrange" (re-separate
// the overlay + kept dashboard on a single monitor, on demand) and
// "raise-companion" (bring the kept dashboard forward beside the HUD). Neither
// hides the overlay, so - unlike the toggle-hidden hotkey - there is no
// stranding risk and they are safe to surface as on-screen buttons.
const OVERLAY_ACTIONS = Object.freeze(["set-panel", "set-active", "rearrange", "raise-companion"]);

// Normalize a mode_key to the canonical lower-case token. Non-string -> "".
function normMode(modeKey) {
  return typeof modeKey === "string" ? modeKey.trim().toLowerCase() : "";
}

// Which surface a given mode_key wants, ignoring the hidden override.
// inGame gates the overlay HUD: a game mode_key only shows the HUD when a live
// game is actually present. RC pre-flips mode_key to the game mode during the
// lobby / champ-select (so the web dashboard shows that mode early), but there
// is no game to overlay yet, so those states stay on the companion. Defaults
// true so the mode-only callers + tests keep their original behavior.
function surfaceForMode(modeKey, inGame = true) {
  const wantsOverlay = GAME_MODES.has(normMode(modeKey)) && inGame !== false;
  return wantsOverlay ? SURFACES.OVERLAY : SURFACES.COMPANION;
}

// Resolve the surface to show: the hidden override wins, else mode + inGame.
function resolveSurface(modeKey, hidden, inGame = true) {
  if (hidden === true) {
    return SURFACES.HIDDEN;
  }
  return surfaceForMode(modeKey, inGame);
}

// True when /api/state shows a live game in progress: a non-empty liveclient
// object (the in-game :2999 read). mode_key alone is insufficient - RC pre-
// flips it to the game mode during the lobby / champ-select, where there is no
// game to overlay yet, so the surface gate keys off this, not the bare mode.
function liveGameFromState(state) {
  if (!state || typeof state !== "object" || Array.isArray(state)) {
    return false;
  }
  const lc = state.liveclient;
  return (
    !!lc &&
    typeof lc === "object" &&
    !Array.isArray(lc) &&
    Object.keys(lc).length > 0
  );
}

// Normalize a panel-set name to a canonical PANEL_SETS member, else "".
function normPanelSet(panelSet) {
  const p = typeof panelSet === "string" ? panelSet.trim().toLowerCase() : "";
  return PANEL_SETS.includes(p) ? p : "";
}

// Next panel set in the cycle. Unknown / null / non-string lands on the first
// set, so the first hotkey press from the default overlay is deterministic.
function cyclePanelSet(current) {
  const i = PANEL_SETS.indexOf(normPanelSet(current));
  return PANEL_SETS[(i + 1) % PANEL_SETS.length];
}

// Validate + normalize a no-hotkey overlay action message from the renderer
// (RC2 4.4). The main process trusts this as the security boundary: only an
// OVERLAY_ACTIONS member passes, and "set-panel" additionally requires a real
// PANEL_SETS target (case/whitespace-insensitive on both fields). Anything
// malformed -> null so the caller no-ops rather than running an unlisted action.
// A stray panelSet on a non-panel action is dropped (never echoed back).
function normOverlayAction(raw) {
  const m = raw && typeof raw === "object" && !Array.isArray(raw) ? raw : {};
  const action = typeof m.action === "string" ? m.action.trim().toLowerCase() : "";
  if (!OVERLAY_ACTIONS.includes(action)) {
    return null;
  }
  if (action === "set-panel") {
    const p = normPanelSet(m.panelSet);
    if (!p) {
      return null;
    }
    return { action, panelSet: p };
  }
  return { action };
}

// Append the overlay route flag so the page renders its compact overlay layout
// instead of the full dashboard grid. Preserves any existing query string.
// Malformed origin -> returned unchanged (defensive; never throws).
// Optional panelSet (a PANEL_SETS member) adds panelset=NAME; absent/unknown
// panelSet keeps the plain overlay=1 URL (backward compatible).
// Optional scale (RC2 4.1, resolveOverlayMetrics.scale) adds ovscale=N so the
// renderer can match its content zoom to the scaled overlay WINDOW; only a
// finite scale meaningfully != 1 is appended, so the baseline URL is unchanged.
function overlayUrl(origin, panelSet, scale) {
  if (typeof origin !== "string" || !origin.trim()) {
    return origin;
  }
  try {
    const u = new URL(origin);
    u.searchParams.set("overlay", "1");
    const p = normPanelSet(panelSet);
    if (p) {
      u.searchParams.set("panelset", p);
    }
    if (typeof scale === "number" && Number.isFinite(scale) && scale > 0 && Math.abs(scale - 1) > 0.001) {
      u.searchParams.set("ovscale", String(scale));
    }
    return u.toString();
  } catch (_e) {
    return origin;
  }
}

// --- Phase 4a: ACTIVE auto-revert deadline state -----------------------------
// Pure deadline bookkeeping for the ACTIVE -> PASSIVE auto-revert. The main
// process owns the actual setTimeout; this object is the source of truth so
// the revert decision is testable without electron or real timers.
//   arm()      (re)start the countdown from now() (any hotkey press re-arms)
//   cancel()   disarm (flip back to PASSIVE, manual or auto)
//   armed()    is a countdown pending?
//   due(nowMs) one-shot: true exactly once when armed and the deadline passed;
//              disarms itself on firing. nowMs optional (defaults to now()).
function makeActiveRevert(opts) {
  const o = opts && typeof opts === "object" ? opts : {};
  const delayMs =
    Number.isFinite(o.delayMs) && o.delayMs > 0
      ? o.delayMs
      : OVERLAY_DEFAULTS.activeRevertDelayMs;
  const now = typeof o.now === "function" ? o.now : Date.now;
  let deadline = null;
  return {
    arm() {
      deadline = now() + delayMs;
      return deadline;
    },
    cancel() {
      deadline = null;
    },
    armed() {
      return deadline !== null;
    },
    due(nowMs) {
      if (deadline === null) {
        return false;
      }
      const t = Number.isFinite(nowMs) ? nowMs : now();
      if (t >= deadline) {
        deadline = null; // one-shot: a fired revert never re-fires
        return true;
      }
      return false;
    },
  };
}

// --- Phase 4b: backend-offline poll backoff ----------------------------------
// Delay before the NEXT /api/state poll given how many consecutive polls have
// failed. 0 failures -> base cadence (success resets); each failure doubles
// the delay, capped at OVERLAY_DEFAULTS.pollMaxMs so a long backend outage
// settles at a quiet 15s probe instead of hammering every 2s.
function nextPollDelay(consecutiveFailures, baseMs) {
  const base =
    Number.isFinite(baseMs) && baseMs > 0 ? baseMs : OVERLAY_DEFAULTS.pollMs;
  const n =
    Number.isFinite(consecutiveFailures) && consecutiveFailures > 0
      ? Math.floor(consecutiveFailures)
      : 0;
  if (n === 0) {
    return base;
  }
  return Math.min(OVERLAY_DEFAULTS.pollMaxMs, base * Math.pow(2, n));
}

// Does a surface transition require showing/hiding either window? Pure helper
// the poll loop uses to avoid redundant show()/hide() churn: returns the set of
// actions {companion: "show"|"hide", overlay: "show"|"hide"} for a target
// surface. HIDDEN hides both; COMPANION shows companion + hides overlay;
// OVERLAY shows overlay + hides companion.
function windowActions(surface) {
  switch (surface) {
    case SURFACES.OVERLAY:
      return { companion: "hide", overlay: "show" };
    case SURFACES.COMPANION:
      return { companion: "show", overlay: "hide" };
    default: // HIDDEN or anything unknown -> hide both (fail-safe to dark).
      return { companion: "hide", overlay: "hide" };
  }
}

// --- RC2 E1: dashboard-persist policy ----------------------------------------
// The base windowActions() hard-hides the companion the moment a game starts -
// that is the operator-reported "dashboard disappears" bug. The overlay-centric
// model wants the full dashboard to STAY available (a second window) while the
// HUD is up. windowActionsWithPolicy layers a keepCompanion override on top of
// the base actions: when set AND the resolved surface is OVERLAY, the companion
// is kept SHOWN alongside the overlay instead of hidden. The HIDDEN force-hide
// (hotkey) is never overridden - clearing the screen must clear both windows.
// Garbage / missing opts fall through to the legacy windowActions (no behavior
// change), so an old saved state with no policy is exactly backward compatible.
function windowActionsWithPolicy(surface, opts) {
  const base = windowActions(surface);
  const o = opts && typeof opts === "object" && !Array.isArray(opts) ? opts : {};
  if (surface === SURFACES.OVERLAY && o.keepCompanion === true) {
    return { companion: "show", overlay: base.overlay };
  }
  return base;
}

// --- HZ-D1 slice 2: overlay position + panel-set persistence -----------------
// The overlay rides the SAME state file as the companion, under one "overlay"
// sub-object, so the two surfaces can never clobber each other's keys. These
// helpers are the pure read/merge halves; main.js owns the store I/O.

// A usable work-area rectangle no matter what the caller hands us. The
// 1920x1080 fallback matches the fleet's design baseline so a garbage display
// probe still yields a sane right-edge dock.
function normWorkArea(workArea) {
  const a = workArea && typeof workArea === "object" ? workArea : {};
  return {
    x: Number.isFinite(a.x) ? a.x : 0,
    y: Number.isFinite(a.y) ? a.y : 0,
    width: Number.isFinite(a.width) && a.width > 0 ? a.width : 1920,
    height: Number.isFinite(a.height) && a.height > 0 ? a.height : 1080,
  };
}

// Defensively read the overlay sub-object out of a saved state blob. The file
// is hand-editable and survives schema drift, so every field is validated:
// x/y must be finite numbers (else null = "not yet positioned"); panelSet is
// normalized to a PANEL_SETS member (else "" = plain overlay=1). Never throws.
function overlayStateFrom(saved) {
  const s = saved && typeof saved === "object" ? saved : {};
  const o = s.overlay && typeof s.overlay === "object" ? s.overlay : {};
  return {
    x: typeof o.x === "number" && Number.isFinite(o.x) ? o.x : null,
    y: typeof o.y === "number" && Number.isFinite(o.y) ? o.y : null,
    panelSet: normPanelSet(o.panelSet),
  };
}

// --- RC2 Stage 4.1: DPI + resolution-aware overlay sizing --------------------
// LIFT-C (docs/research/RC2_RESEARCH_overlay_sizing.md): a family-#2 compositor
// overlay must SIZE itself against the measured display, not a hard 1920/100%
// baseline, or it clips/shrinks at a non-1920 borderless res (the operator now
// runs 2560x1440) or under 125%/150% Windows scaling (Overlay App F's documented
// "content too big" failure). Electron sizes windows in DIPs and Chromium maps
// CSS px -> DIPs -> device px by deviceScaleFactor, so the CORRECT DPI model is
// to size the DIP box against the DIP work area (NOT to multiply by scaleFactor,
// which would double-apply). scaleFactor is read only to GUARD electron#6571
// (scaleFactor returns 1 under Windows scaling) and for diagnostics.

// The DIP design baseline the overlay box (OVERLAY_DEFAULTS 460x900) was authored
// against. The resolution scale is the work area measured relative to this.
const OVERLAY_SIZE_BASELINE = Object.freeze({ width: 1920, height: 1080 });

// Scale clamp: never below 0.8 (a tiny laptop work area should not crush the
// HUD past readability) nor above 1.6 (4K should not balloon the dock to fill
// the screen). 1.0 is the exact design baseline -> a true no-op.
const OVERLAY_SCALE_MIN = 0.8;
const OVERLAY_SCALE_MAX = 1.6;

// electron#6571 guard: screen.getPrimaryDisplay().scaleFactor has a documented
// history of returning a non-positive / non-number under Windows display
// scaling. Coerce anything that is not a finite positive number to 1.
function normScaleFactor(scaleFactor) {
  return typeof scaleFactor === "number" && Number.isFinite(scaleFactor) && scaleFactor > 0
    ? scaleFactor
    : 1;
}

// Resolution scale for the overlay box from a work area. min() of the two axis
// ratios preserves the box aspect and avoids over-scaling on ultrawide (a wide
// 21:9 work area must not grow the column by its width ratio). Clamped to
// [MIN, MAX] and rounded to 2 decimals so the value is stable + URL-clean.
function resolveOverlayScale(workArea) {
  const area = normWorkArea(workArea);
  const ratio = Math.min(
    area.width / OVERLAY_SIZE_BASELINE.width,
    area.height / OVERLAY_SIZE_BASELINE.height
  );
  const clamped = Math.min(OVERLAY_SCALE_MAX, Math.max(OVERLAY_SCALE_MIN, ratio));
  return Math.round(clamped * 100) / 100;
}

// Resolve the full overlay sizing metrics from a display descriptor
// ({ workArea, scaleFactor } - the shape of electron's screen.getPrimaryDisplay
// subset). Returns { scale, scaleFactor, width, height }: the box is the
// OVERLAY_DEFAULTS box grown by the resolution scale, with height never
// exceeding the work area so the dock always fits on-screen. Garbage display
// -> the safe 1.0 baseline box (zero behavior change at 1920/100%).
function resolveOverlayMetrics(display) {
  const d = display && typeof display === "object" && !Array.isArray(display) ? display : {};
  const area = normWorkArea(d.workArea);
  const scale = resolveOverlayScale(area);
  const height = Math.min(Math.round(OVERLAY_DEFAULTS.height * scale), area.height);
  return Object.freeze({
    scale,
    scaleFactor: normScaleFactor(d.scaleFactor),
    width: Math.round(OVERLAY_DEFAULTS.width * scale),
    height,
  });
}

// Where the overlay window goes at create time. Size is the OVERLAY_DEFAULTS box
// scaled by an optional metrics {width,height} (resolveOverlayMetrics) - garbage
// or absent metrics fall back to the fixed default box (backward compatible).
// Saved coords win but are clamped on-screen - a display that shrank or vanished
// since the save must not strand the HUD off-screen; no saved coords -> right-
// edge dock against the SCALED width.
function resolveOverlayBounds(saved, workArea, metrics) {
  const area = normWorkArea(workArea);
  const m = metrics && typeof metrics === "object" && !Array.isArray(metrics) ? metrics : {};
  const w = Number.isFinite(m.width) && m.width > 0 ? m.width : OVERLAY_DEFAULTS.width;
  const h = Number.isFinite(m.height) && m.height > 0 ? m.height : OVERLAY_DEFAULTS.height;
  const o = overlayStateFrom(saved);
  if (o.x !== null && o.y !== null) {
    const clamped = cfg.clampPosition({ x: o.x, y: o.y, width: w, height: h }, area);
    if (clamped.x !== null && clamped.y !== null) {
      return { x: clamped.x, y: clamped.y, width: w, height: h };
    }
  }
  return {
    x: Math.max(area.x, area.x + area.width - w),
    y: area.y,
    width: w,
    height: h,
  };
}

// Merge an overlay patch into a full saved-state blob WITHOUT touching the
// companion's top-level keys - this is what main.js hands to store.save so a
// move of one surface can never wipe the other's persisted state. Returns a
// new object; never mutates either input; garbage prev starts fresh.
function mergeOverlayPatch(prevState, patch) {
  const prev =
    prevState && typeof prevState === "object" && !Array.isArray(prevState)
      ? prevState
      : {};
  const prevOverlay =
    prev.overlay && typeof prev.overlay === "object" && !Array.isArray(prev.overlay)
      ? prev.overlay
      : {};
  const p = patch && typeof patch === "object" && !Array.isArray(patch) ? patch : {};
  return Object.assign({}, prev, { overlay: Object.assign({}, prevOverlay, p) });
}

// --- OVL1: operator overlay settings (pulse-notify + ACTIVE auto-revert sec) -
// Two user-configurable overlay behaviors, persisted under overlay.settings in
// the same state file (so they never clobber position/panelSet/companion keys).
// The renderer (?overlay=1 dashboard) reads/writes them over the preload IPC
// bridge; main.js is the authority that applies them (revert delay) + returns
// the resolved values. activeRevertSec is the seconds form of the legacy
// OVERLAY_DEFAULTS.activeRevertDelayMs - one default, two units.
const OVERLAY_SETTINGS_DEFAULTS = Object.freeze({
  pulseNotify: true,
  activeRevertSec: Math.round(OVERLAY_DEFAULTS.activeRevertDelayMs / 1000),
  // RC2 E1: keepCompanion default TRUE is the dashboard-persist bug fix - the
  // full dashboard window stays available while the in-game overlay is shown
  // unless the operator opts out. companionAlwaysOnTop is the persisted
  // on-screen pin toggle for the companion/dashboard window.
  keepCompanion: true,
  companionAlwaysOnTop: true,
  // RC2 4.2 (non-intrusive overlay): operator-tunable window opacity (the HUD
  // recedes into the game without going away) + click-through ZONES (PASSIVE
  // stays click-through everywhere EXCEPT over an interactive control). Both
  // default to the current behavior - opacity 1.0 = fully opaque, zones ON adds
  // hover-to-interact without changing the legacy global ACTIVE hotkey.
  overlayOpacity: 1,
  clickThroughZones: true,
  // RC2 4.3 (single-monitor window management): when both the overlay and the
  // kept companion are shown on ONE monitor, auto-arrange them as SEPARATED
  // side-by-side windows so the dashboard sits beside the HUD, not under it.
  // Default ON; the no-hotkey kill switch lives in the #ovset strip.
  separateWindows: true,
});

// ACTIVE auto-revert bounds: a 3s floor (an instantly-reverting overlay is
// useless) and a 120s ceiling. Non-finite -> null so the caller can fall back
// to the default rather than persist garbage.
const ACTIVE_REVERT_MIN_SEC = 3;
const ACTIVE_REVERT_MAX_SEC = 120;

function clampRevertSec(v) {
  if (!(typeof v === "number" && Number.isFinite(v))) {
    return null;
  }
  return Math.min(ACTIVE_REVERT_MAX_SEC, Math.max(ACTIVE_REVERT_MIN_SEC, Math.round(v)));
}

// --- RC2 Stage 4.2: non-intrusive overlay (opacity + click-through zones) -----
// Overlay opacity bounds: 0.3 floor (a near-invisible HUD is useless) to 1.0
// (fully opaque, the current behavior). Applied via overlayWindow.setOpacity in
// main.js. Non-finite -> null so the caller falls back to the default rather
// than persist garbage (mirrors clampRevertSec).
const OVERLAY_OPACITY_MIN = 0.3;
const OVERLAY_OPACITY_MAX = 1;

function clampOpacity(v) {
  if (!(typeof v === "number" && Number.isFinite(v))) {
    return null;
  }
  const c = Math.min(OVERLAY_OPACITY_MAX, Math.max(OVERLAY_OPACITY_MIN, v));
  return Math.round(c * 100) / 100;
}

// The click-through ZONES decision: what to pass to setIgnoreMouseEvents given
// the current intent (clickThrough = the operator/hotkey PASSIVE<->ACTIVE
// state), a transient zoneHover (cursor is over an interactive control - the
// renderer reports it over IPC), and whether zones are enabled. Pure so main.js
// stays a thin applier.
//   - zones OFF        -> legacy whole-window behavior (ignore == clickThrough)
//   - ACTIVE           -> fully interactive (ignore false) regardless of hover
//   - PASSIVE + zones  -> click-through (ignore true) UNLESS hovering a zone
// Only a strict boolean true counts, so undefined/NaN args coerce to the safe
// interactive side rather than leaking a non-boolean into setIgnoreMouseEvents.
function effectiveIgnoreMouse(clickThrough, zoneHover, zonesEnabled) {
  if (zonesEnabled !== true) {
    return clickThrough === true; // legacy: whole window follows clickThrough
  }
  if (clickThrough !== true) {
    return false; // ACTIVE: the whole overlay is interactive
  }
  return zoneHover !== true; // PASSIVE: click-through except over a zone
}

// --- RC2 Stage 4.3: single-monitor window management (separated windows) ------
// On a SINGLE monitor the keepCompanion fix (E1/3.4) shows the full dashboard
// alongside the right-docked in-game overlay - but a companion last left under
// the overlay is visible-yet-covered, which defeats "the dashboard stays
// available". You cannot punt it to a 2nd screen on one monitor, so arrange the
// two as SEPARATED non-overlapping side-by-side windows: the overlay keeps its
// HUD anchor; the companion is docked to whichever side of the overlay has more
// free room (top-aligned), KEEPING its size (reposition only - never resize, so
// the size preset is never corrupted). Operator intent wins: a companion that
// does NOT already overlap the overlay is left exactly where it is.

// Coerce a window-bounds blob to a fully-finite, positive-size rect, else null.
// A garbage rect makes the geometry no-op (the caller treats null/false as
// "do not auto-arrange"), which is the safe default for a window move.
function _finiteRect(r) {
  const o = r && typeof r === "object" && !Array.isArray(r) ? r : null;
  if (!o) {
    return null;
  }
  if (!(Number.isFinite(o.x) && Number.isFinite(o.y))) {
    return null;
  }
  if (!(Number.isFinite(o.width) && o.width > 0 && Number.isFinite(o.height) && o.height > 0)) {
    return null;
  }
  return { x: o.x, y: o.y, width: o.width, height: o.height };
}

// Strict axis-aligned overlap test. Touching edges do NOT count as overlap
// (a.right === b.left is a clean tile, not a collision). A garbage rect on
// either side -> false (no overlap -> the caller no-ops the auto-arrange).
function rectsOverlap(a, b) {
  const ra = _finiteRect(a);
  const rb = _finiteRect(b);
  if (!ra || !rb) {
    return false;
  }
  return (
    ra.x < rb.x + rb.width &&
    rb.x < ra.x + ra.width &&
    ra.y < rb.y + rb.height &&
    rb.y < ra.y + ra.height
  );
}

// Where the companion window should sit so it does NOT cover the overlay on a
// single monitor. Returns { x, y, width, height, moved }:
//   - companion garbage            -> { x:null, ..., moved:false } (no-op)
//   - overlay garbage / no overlap -> echo the companion (moved:false): respect
//                                     the operator's existing placement.
//   - overlapping                  -> dock the companion to the work-area edge
//                                     on whichever side of the overlay has more
//                                     free room, top-aligned, size preserved
//                                     (moved:true). Best effort if the screen is
//                                     too narrow for a full clear (still reduces
//                                     the overlap; the kill switch disables it).
function resolveSeparatedCompanionBounds(companion, overlayBounds, workArea) {
  const c = _finiteRect(companion);
  if (!c) {
    return { x: null, y: null, width: null, height: null, moved: false };
  }
  const ovb = _finiteRect(overlayBounds);
  if (!ovb || !rectsOverlap(c, ovb)) {
    return { x: c.x, y: c.y, width: c.width, height: c.height, moved: false };
  }
  const area = normWorkArea(workArea);
  const leftRoom = ovb.x - area.x;
  const rightRoom = area.x + area.width - (ovb.x + ovb.width);
  const x = leftRoom >= rightRoom ? area.x : area.x + area.width - c.width;
  return {
    x: Math.round(x),
    y: Math.round(area.y),
    width: c.width,
    height: c.height,
    moved: true,
  };
}

// Resolve the operator overlay settings out of a saved state blob. Every field
// is validated against the hand-editable file: pulseNotify must be a real
// boolean (else default true), activeRevertSec a finite number clamped to
// [3,120] (else default). Never throws.
function overlaySettingsFrom(saved) {
  const s = saved && typeof saved === "object" && !Array.isArray(saved) ? saved : {};
  const o = s.overlay && typeof s.overlay === "object" && !Array.isArray(s.overlay) ? s.overlay : {};
  const set = o.settings && typeof o.settings === "object" && !Array.isArray(o.settings) ? o.settings : {};
  const sec = clampRevertSec(set.activeRevertSec);
  const op = clampOpacity(set.overlayOpacity);
  return {
    pulseNotify: typeof set.pulseNotify === "boolean" ? set.pulseNotify : OVERLAY_SETTINGS_DEFAULTS.pulseNotify,
    activeRevertSec: sec === null ? OVERLAY_SETTINGS_DEFAULTS.activeRevertSec : sec,
    keepCompanion: typeof set.keepCompanion === "boolean" ? set.keepCompanion : OVERLAY_SETTINGS_DEFAULTS.keepCompanion,
    companionAlwaysOnTop:
      typeof set.companionAlwaysOnTop === "boolean"
        ? set.companionAlwaysOnTop
        : OVERLAY_SETTINGS_DEFAULTS.companionAlwaysOnTop,
    overlayOpacity: op === null ? OVERLAY_SETTINGS_DEFAULTS.overlayOpacity : op,
    clickThroughZones:
      typeof set.clickThroughZones === "boolean"
        ? set.clickThroughZones
        : OVERLAY_SETTINGS_DEFAULTS.clickThroughZones,
    separateWindows:
      typeof set.separateWindows === "boolean"
        ? set.separateWindows
        : OVERLAY_SETTINGS_DEFAULTS.separateWindows,
  };
}

// Sanitize a settings patch to only the known, well-typed fields. pulseNotify
// must be boolean; activeRevertSec must clamp to a finite [3,120]. Unknown keys
// and wrong types are dropped (never persisted).
function sanitizeSettingsPatch(patch) {
  const p = patch && typeof patch === "object" && !Array.isArray(patch) ? patch : {};
  const out = {};
  if (typeof p.pulseNotify === "boolean") {
    out.pulseNotify = p.pulseNotify;
  }
  const sec = clampRevertSec(p.activeRevertSec);
  if (sec !== null) {
    out.activeRevertSec = sec;
  }
  if (typeof p.keepCompanion === "boolean") {
    out.keepCompanion = p.keepCompanion;
  }
  if (typeof p.companionAlwaysOnTop === "boolean") {
    out.companionAlwaysOnTop = p.companionAlwaysOnTop;
  }
  const op = clampOpacity(p.overlayOpacity);
  if (op !== null) {
    out.overlayOpacity = op;
  }
  if (typeof p.clickThroughZones === "boolean") {
    out.clickThroughZones = p.clickThroughZones;
  }
  if (typeof p.separateWindows === "boolean") {
    out.separateWindows = p.separateWindows;
  }
  return out;
}

// Merge a settings patch into overlay.settings WITHOUT touching the overlay's
// position/panelSet or the companion's top-level keys (mirrors mergeOverlayPatch
// one level deeper). Returns a new object; never mutates; garbage prev starts
// fresh.
function mergeOverlaySettingsPatch(prevState, patch) {
  const prev =
    prevState && typeof prevState === "object" && !Array.isArray(prevState) ? prevState : {};
  const prevOverlay =
    prev.overlay && typeof prev.overlay === "object" && !Array.isArray(prev.overlay)
      ? prev.overlay
      : {};
  const prevSettings =
    prevOverlay.settings && typeof prevOverlay.settings === "object" && !Array.isArray(prevOverlay.settings)
      ? prevOverlay.settings
      : {};
  const clean = sanitizeSettingsPatch(patch);
  const nextOverlay = Object.assign({}, prevOverlay, {
    settings: Object.assign({}, prevSettings, clean),
  });
  return Object.assign({}, prev, { overlay: nextOverlay });
}

// --- RC Overlay Doctrine section 3: durable widget-field layout mirror --------
// The movable widget field (web/js/lib/overlay_layout.js) persists each cue's
// {x,y,hidden,scale} keyed by widget id. localStorage is the authoritative store
// (the overlay shares the dashboard origin), but the doctrine wants a DURABLE
// disk mirror so the layout survives a localStorage wipe + is hand-editable. We
// keep it in the SAME rc-shell-state.json (operator choice) under overlay.
// widgetLayout, alongside position / panelSet / settings (never clobbering them).

// Coerce an arbitrary layout blob to { <id>: {x?,y?,hidden?,scale?} } with typed
// fields only - a corrupt / hand-edited mirror can never feed the renderer junk.
function sanitizeWidgetLayout(layout) {
  const src =
    layout && typeof layout === "object" && !Array.isArray(layout) ? layout : {};
  const out = {};
  for (const id of Object.keys(src)) {
    const e = src[id];
    if (!e || typeof e !== "object" || Array.isArray(e)) {
      continue;
    }
    const clean = {};
    if (Number.isFinite(e.x)) {
      clean.x = Math.round(e.x);
    }
    if (Number.isFinite(e.y)) {
      clean.y = Math.round(e.y);
    }
    if (typeof e.hidden === "boolean") {
      clean.hidden = e.hidden;
    }
    if (Number.isFinite(e.scale)) {
      clean.scale = e.scale;
    }
    out[id] = clean;
  }
  return out;
}

// Read the persisted widget layout out of a full saved-state blob. Never throws;
// garbage / absent -> {} (the renderer then falls back to the section-4 defaults).
function widgetLayoutFrom(state) {
  const s = state && typeof state === "object" && !Array.isArray(state) ? state : {};
  const overlay =
    s.overlay && typeof s.overlay === "object" && !Array.isArray(s.overlay)
      ? s.overlay
      : {};
  return sanitizeWidgetLayout(overlay.widgetLayout);
}

// Merge a full widget-layout blob into a saved-state blob WITHOUT touching the
// companion's top-level keys OR the sibling overlay keys (position / panelSet /
// settings). The renderer sends the WHOLE layout each save, so widgetLayout is
// REPLACED (not deep-merged). Returns a new object; never mutates either input.
function mergeWidgetLayoutPatch(prevState, layout) {
  const prev =
    prevState && typeof prevState === "object" && !Array.isArray(prevState)
      ? prevState
      : {};
  const prevOverlay =
    prev.overlay && typeof prev.overlay === "object" && !Array.isArray(prev.overlay)
      ? prev.overlay
      : {};
  const nextOverlay = Object.assign({}, prevOverlay, {
    widgetLayout: sanitizeWidgetLayout(layout),
  });
  return Object.assign({}, prev, { overlay: nextOverlay });
}

module.exports = {
  SURFACES,
  GAME_MODES,
  OVERLAY_DEFAULTS,
  OVERLAY_SETTINGS_DEFAULTS,
  PANEL_SETS,
  normMode,
  surfaceForMode,
  resolveSurface,
  liveGameFromState,
  overlayUrl,
  windowActions,
  windowActionsWithPolicy,
  cyclePanelSet,
  OVERLAY_ACTIONS,
  normOverlayAction,
  makeActiveRevert,
  nextPollDelay,
  overlayStateFrom,
  resolveOverlayBounds,
  normScaleFactor,
  resolveOverlayScale,
  resolveOverlayMetrics,
  OVERLAY_SIZE_BASELINE,
  mergeOverlayPatch,
  overlaySettingsFrom,
  mergeOverlaySettingsPatch,
  sanitizeWidgetLayout,
  widgetLayoutFrom,
  mergeWidgetLayoutPatch,
  OVERLAY_OPACITY_MIN,
  OVERLAY_OPACITY_MAX,
  clampOpacity,
  effectiveIgnoreMouse,
  rectsOverlap,
  resolveSeparatedCompanionBounds,
};
