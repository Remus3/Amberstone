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

// Normalize a mode_key to the canonical lower-case token. Non-string -> "".
function normMode(modeKey) {
  return typeof modeKey === "string" ? modeKey.trim().toLowerCase() : "";
}

// Which surface a given mode_key wants, ignoring the hidden override.
function surfaceForMode(modeKey) {
  return GAME_MODES.has(normMode(modeKey)) ? SURFACES.OVERLAY : SURFACES.COMPANION;
}

// Resolve the surface to show: the hidden override wins, else mode decides.
function resolveSurface(modeKey, hidden) {
  if (hidden === true) {
    return SURFACES.HIDDEN;
  }
  return surfaceForMode(modeKey);
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

// Append the overlay route flag so the page renders its compact overlay layout
// instead of the full dashboard grid. Preserves any existing query string.
// Malformed origin -> returned unchanged (defensive; never throws).
// Optional panelSet (a PANEL_SETS member) adds panelset=NAME; absent/unknown
// panelSet keeps the plain overlay=1 URL (backward compatible).
function overlayUrl(origin, panelSet) {
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

module.exports = {
  SURFACES,
  GAME_MODES,
  OVERLAY_DEFAULTS,
  PANEL_SETS,
  normMode,
  surfaceForMode,
  resolveSurface,
  overlayUrl,
  windowActions,
  cyclePanelSet,
  makeActiveRevert,
  nextPollDelay,
};
