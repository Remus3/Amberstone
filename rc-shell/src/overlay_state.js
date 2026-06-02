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
  pollMs: 2000, // /api/state poll cadence (no sub-500ms per the cost rule)
  clickThrough: true, // passive HUD by default
  width: 460,
  height: 900,
});

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

// Append the overlay route flag so the page renders its compact overlay layout
// instead of the full dashboard grid. Preserves any existing query string.
// Malformed origin -> returned unchanged (defensive; never throws).
function overlayUrl(origin) {
  if (typeof origin !== "string" || !origin.trim()) {
    return origin;
  }
  try {
    const u = new URL(origin);
    u.searchParams.set("overlay", "1");
    return u.toString();
  } catch (_e) {
    return origin;
  }
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
  normMode,
  surfaceForMode,
  resolveSurface,
  overlayUrl,
  windowActions,
};
