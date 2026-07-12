// web/js/lib/overlay_settings.js
//
// Shared overlay-settings access for the ?overlay=1 surface (OVL1,
// docs/ELECTRON_OVERLAY.md Phase 4). ONE source of the in-page settings shape
// so the controls (panels/overlay_ds_controls.js) and the change-pulse gate
// (overlay_pulse.js) can never drift.
//
// Two settings:
//   - pulseNotify     gate the in-page change-pulse glow (overlay_pulse.js).
//   - activeRevertSec  the ACTIVE auto-revert delay the rc-shell main process
//                      enforces; mirrored here so the control shows the value.
//
// Storage model: a synchronous localStorage mirror is the read path (the
// render + pulse hooks must not await), and when the rc-shell Electron bridge
// is present (window.rcShell) writes ALSO persist to the shell config over IPC
// so the setting survives across shell launches, and hydrateOverlaySettings()
// pulls the authoritative shell value into the mirror once on boot. In a plain
// browser (no bridge) it degrades to localStorage-only - the controls still
// work for preview + the pulse gate still honors the toggle.

const LS_KEY = "rc_overlay_settings";

// Overlay item 8: the in-game stats panel benchmarks against a SELECTED
// rank-tier average. The tier lives here as a first-class overlay setting
// (benchmarkRankTier) BUT the single source of truth is the EXISTING
// rc-pgr-rank-tier localStorage key that the Post Game Review page + the
// desktop Settings row already share (web/js/panels/last_match.js /
// web/js/panels/dev.js). We mirror BOTH ways so a pick in PGR/Settings shows
// in the overlay and vice-versa; a same-origin custom event repaints the panel
// in THIS window (the native `storage` event only reaches OTHER windows).
export const PGR_RANK_KEY = "rc-pgr-rank-tier";
export const RANK_TIER_EVENT = "rc:rank-tier-change";
// The global 10-tier ladder (mirrors core.rank_tier_bench.VALID_TIERS +
// the index.html rank <select> option set). "" = off / no benchmark.
const _VALID_TIERS = [
  "iron", "bronze", "silver", "gold", "platinum",
  "emerald", "diamond", "master", "grandmaster", "challenger",
];
// The relocated stats-panel role override (was the in-panel .sp-role select,
// now a DS Settings control). "" = auto (the panel's _detectRole default).
const _VALID_ROLES = ["top", "jungle", "mid", "bot", "support"];

function _coerceTier(v) {
  const t = String(v == null ? "" : v).trim().toLowerCase();
  return _VALID_TIERS.indexOf(t) >= 0 ? t : "";
}

function _coerceRole(v) {
  const r = String(v == null ? "" : v).trim().toLowerCase();
  return _VALID_ROLES.indexOf(r) >= 0 ? r : "";
}

// keepCompanion / companionAlwaysOnTop default ON: RC2 3.4 (E1) - the full
// dashboard window STAYS available alongside the in-game overlay and is pinned
// on top unless the operator opts out. The rc-shell main process is the
// authority (overlay_state.overlaySettingsFrom mirrors these same defaults); the
// helper carries them so a dashboard toggle reaches the shell over IPC instead
// of being silently dropped here.
// RC2 4.2: overlayOpacity (the HUD recedes into the game; 1.0 = fully opaque)
// + clickThroughZones (PASSIVE captures the cursor over an interactive control
// without the global ACTIVE hotkey). Defaults match the rc-shell authority
// (overlay_state.OVERLAY_SETTINGS_DEFAULTS): opacity 1, zones on.
// RC2 4.3: separateWindows default ON - on a single monitor the rc-shell arranges
// the overlay + kept dashboard as SEPARATED side-by-side windows instead of
// leaving the dashboard under the HUD. Mirrors overlay_state.OVERLAY_SETTINGS_
// DEFAULTS; the #ovset toggle is the no-hotkey kill switch.
export const OVERLAY_SETTINGS_DEFAULTS = {
  pulseNotify: true,
  activeRevertSec: 20,
  keepCompanion: true,
  companionAlwaysOnTop: true,
  overlayOpacity: 1,
  clickThroughZones: true,
  separateWindows: true,
  // Overlay item 8: the stats-panel rank-tier benchmark ("" = off) + the
  // relocated stats-panel role override ("" = auto). benchmarkRankTier is
  // kept in lock-step with the shared rc-pgr-rank-tier key (see below).
  benchmarkRankTier: "",
  roleOverride: "",
};

// Clamp the ACTIVE auto-revert seconds to [3,120] (mirrors the rc-shell
// overlaySettingsFrom bounds). Non-finite -> the default.
function _clampSec(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return OVERLAY_SETTINGS_DEFAULTS.activeRevertSec;
  return Math.min(120, Math.max(3, Math.round(n)));
}

// Clamp overlay opacity to [0.3,1.0] 2-dp (mirrors rc-shell clampOpacity).
// Non-finite -> the default.
function _clampOpacity(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return OVERLAY_SETTINGS_DEFAULTS.overlayOpacity;
  return Math.round(Math.min(1, Math.max(0.3, n)) * 100) / 100;
}

function _coerce(raw) {
  const o = raw && typeof raw === "object" ? raw : {};
  return {
    pulseNotify: typeof o.pulseNotify === "boolean" ? o.pulseNotify : OVERLAY_SETTINGS_DEFAULTS.pulseNotify,
    activeRevertSec: _clampSec(o.activeRevertSec),
    keepCompanion: typeof o.keepCompanion === "boolean" ? o.keepCompanion : OVERLAY_SETTINGS_DEFAULTS.keepCompanion,
    companionAlwaysOnTop:
      typeof o.companionAlwaysOnTop === "boolean"
        ? o.companionAlwaysOnTop
        : OVERLAY_SETTINGS_DEFAULTS.companionAlwaysOnTop,
    overlayOpacity: _clampOpacity(o.overlayOpacity),
    clickThroughZones:
      typeof o.clickThroughZones === "boolean"
        ? o.clickThroughZones
        : OVERLAY_SETTINGS_DEFAULTS.clickThroughZones,
    separateWindows:
      typeof o.separateWindows === "boolean"
        ? o.separateWindows
        : OVERLAY_SETTINGS_DEFAULTS.separateWindows,
    benchmarkRankTier: _coerceTier(o.benchmarkRankTier),
    roleOverride: _coerceRole(o.roleOverride),
  };
}

// Read the shared rc-pgr-rank-tier value directly (canonical single source of
// truth). Never throws; "" when absent / storage disabled.
function _readPgrRank() {
  try {
    return _coerceTier(localStorage.getItem(PGR_RANK_KEY) || "");
  } catch (_e) {
    return "";
  }
}

// Synchronous read from the in-page mirror. Never throws (a corrupt / absent
// value -> defaults), so the render + pulse hot paths can call it freely.
export function readOverlaySettings() {
  let s;
  try {
    s = _coerce(JSON.parse(localStorage.getItem(LS_KEY) || "{}"));
  } catch (_e) {
    s = { ...OVERLAY_SETTINGS_DEFAULTS };
  }
  // rc-pgr-rank-tier is the shared single source of truth: a pick made on the
  // PGR page or the desktop Settings row wins over a stale mirror here, so the
  // overlay reflects it without an explicit write back through this helper.
  const pgr = _readPgrRank();
  if (pgr) s.benchmarkRankTier = pgr;
  return s;
}

// Apply a partial patch ({pulseNotify?, activeRevertSec?}), persist to the
// localStorage mirror, and mirror to the rc-shell config over IPC when the
// bridge is present (fire-and-forget; a missing handler is swallowed). Returns
// the resolved settings so a caller can reflect the clamp back into the input.
export function writeOverlaySettings(patch) {
  const cur = readOverlaySettings();
  const next = { ...cur };
  if (patch && typeof patch.pulseNotify === "boolean") next.pulseNotify = patch.pulseNotify;
  if (patch && patch.activeRevertSec !== undefined) next.activeRevertSec = _clampSec(patch.activeRevertSec);
  if (patch && typeof patch.keepCompanion === "boolean") next.keepCompanion = patch.keepCompanion;
  if (patch && typeof patch.companionAlwaysOnTop === "boolean") next.companionAlwaysOnTop = patch.companionAlwaysOnTop;
  if (patch && patch.overlayOpacity !== undefined) next.overlayOpacity = _clampOpacity(patch.overlayOpacity);
  if (patch && typeof patch.clickThroughZones === "boolean") next.clickThroughZones = patch.clickThroughZones;
  if (patch && typeof patch.separateWindows === "boolean") next.separateWindows = patch.separateWindows;
  // Overlay item 8: rank-tier + role override. A benchmarkRankTier change also
  // mirrors to the shared rc-pgr-rank-tier key (both-ways sync) and fires a
  // same-origin event so the stats panel repaints in THIS window.
  let rankChanged = false;
  if (patch && patch.benchmarkRankTier !== undefined) {
    const t = _coerceTier(patch.benchmarkRankTier);
    rankChanged = t !== next.benchmarkRankTier;
    next.benchmarkRankTier = t;
  }
  if (patch && patch.roleOverride !== undefined) next.roleOverride = _coerceRole(patch.roleOverride);
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(next));
  } catch (_e) {
    // best-effort; a full / disabled storage must not break the control.
  }
  if (rankChanged) {
    // Mirror to the shared PGR/Settings key (the single source of truth) and
    // notify same-window listeners (the native storage event only fires in
    // OTHER windows of the origin).
    try {
      localStorage.setItem(PGR_RANK_KEY, next.benchmarkRankTier);
    } catch (_e) {
      // storage disabled - the rc-shell IPC mirror below still carries it.
    }
    try {
      if (typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
        window.dispatchEvent(new Event(RANK_TIER_EVENT));
      }
    } catch (_e) {
      // no window (node / test) - the event is a browser-only repaint nudge.
    }
  }
  try {
    if (window.rcShell && typeof window.rcShell.setOverlaySettings === "function") {
      Promise.resolve(window.rcShell.setOverlaySettings(next)).catch(() => {});
    }
  } catch (_e) {
    // no bridge (plain browser) - localStorage already holds the value.
  }
  // A1: apply the global overlay opacity page-side as a CSS var so a plain
  // browser (preview / headless) actually dims - #ovset-opacity had no page-side
  // consumer and was a no-op outside Electron. INSIDE the rc-shell the Electron
  // window opacity is the authority (main.js applyOverlayOpacity), so gate on the
  // bridge being ABSENT or the two would double-dim. overlay.css consumes the var
  // on body[data-shell="overlay"]; per-panel inline opacity composes over it.
  try {
    if (!window.rcShell && document.body) {
      document.body.style.setProperty("--rc-overlay-opacity", String(next.overlayOpacity));
    }
  } catch (_e) {
    // no document (node / test) - the CSS var is a browser-only convenience.
  }
  return next;
}

// RC2 4.4: fire a no-hotkey overlay ACTION (panel-set pick / interact-now) at
// the rc-shell over IPC. Unlike the persisted settings, these are runtime
// COMMANDS (the shell reloads the overlay window / flips click-through), so
// there is no localStorage mirror - a plain browser (no bridge) is a silent
// no-op. Fire-and-forget; returns true only if the shell bridge took it.
export function sendOverlayAction(msg) {
  try {
    if (window.rcShell && typeof window.rcShell.overlayAction === "function") {
      window.rcShell.overlayAction(msg);
      return true;
    }
  } catch (_e) {
    // no bridge (plain browser) / send failed - nothing to do.
  }
  return false;
}

// Pull the authoritative rc-shell config value into the in-page mirror once on
// boot, so a fresh page inside the Electron shell shows the persisted settings
// (the shell config outlives a single page). No-op in a plain browser. Always
// resolves to a settings object (never rejects).
export function hydrateOverlaySettings() {
  try {
    if (window.rcShell && typeof window.rcShell.getOverlaySettings === "function") {
      return Promise.resolve(window.rcShell.getOverlaySettings())
        .then((s) => {
          const merged = _coerce(s);
          try {
            localStorage.setItem(LS_KEY, JSON.stringify(merged));
          } catch (_e) {
            // best-effort mirror.
          }
          return merged;
        })
        .catch(() => readOverlaySettings());
    }
  } catch (_e) {
    // fall through to the local mirror.
  }
  return Promise.resolve(readOverlaySettings());
}

// Overlay item 8 convenience API over the shared rc-pgr-rank-tier key. The
// stats panel + the DS Settings rank selector go through these so the
// both-ways mirror + the same-origin repaint event stay in one place.
export function readBenchmarkRankTier() {
  return readOverlaySettings().benchmarkRankTier;
}

export function writeBenchmarkRankTier(tier) {
  return writeOverlaySettings({ benchmarkRankTier: tier }).benchmarkRankTier;
}

// The relocated stats-panel role override ("" = auto / detect). The DS Settings
// role selector writes it; the stats panel reads it (no cross-panel import).
export function readRoleOverride() {
  return readOverlaySettings().roleOverride;
}

export function writeRoleOverride(role) {
  return writeOverlaySettings({ roleOverride: role }).roleOverride;
}
