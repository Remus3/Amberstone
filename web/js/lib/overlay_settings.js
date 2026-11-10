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

// Only a string can name a tier / role: String() on an arbitrary object runs
// its toString (which may throw) and could never match the ladder anyway.
function _coerceTier(v) {
  const t = typeof v === "string" ? v.trim().toLowerCase() : "";
  return _VALID_TIERS.indexOf(t) >= 0 ? t : "";
}

function _coerceRole(v) {
  const r = typeof v === "string" ? v.trim().toLowerCase() : "";
  return _VALID_ROLES.indexOf(r) >= 0 ? r : "";
}

function _isPlainObject(v) {
  return v !== null && typeof v === "object" && !Array.isArray(v);
}

// A real number, or a non-blank numeric string (an <input> value), else NaN.
// Number() alone maps "" / null / false / [] to 0 and true to 1, which the
// clamps below would silently turn into the 3 s / 30 % floor.
function _toNumber(v) {
  if (typeof v === "number") return v;
  if (typeof v === "string" && v.trim() !== "") return Number(v);
  return NaN;
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
// clampRevertSec bounds). Not a number -> null, so the read path falls back to
// the default and the write path keeps the current value (as the shell's
// sanitizeSettingsPatch drops it).
function _clampSec(v) {
  const n = _toNumber(v);
  if (!Number.isFinite(n)) return null;
  return Math.min(120, Math.max(3, Math.round(n)));
}

// Clamp overlay opacity to [0.3,1.0] 2-dp (mirrors rc-shell clampOpacity).
// Not a number -> null (same fallback contract as _clampSec).
function _clampOpacity(v) {
  const n = _toNumber(v);
  if (!Number.isFinite(n)) return null;
  return Math.round(Math.min(1, Math.max(0.3, n)) * 100) / 100;
}

function _orDefault(v, d) {
  return v === null ? d : v;
}

function _coerce(raw) {
  const o = _isPlainObject(raw) ? raw : {};
  return {
    pulseNotify: typeof o.pulseNotify === "boolean" ? o.pulseNotify : OVERLAY_SETTINGS_DEFAULTS.pulseNotify,
    activeRevertSec: _orDefault(_clampSec(o.activeRevertSec), OVERLAY_SETTINGS_DEFAULTS.activeRevertSec),
    keepCompanion: typeof o.keepCompanion === "boolean" ? o.keepCompanion : OVERLAY_SETTINGS_DEFAULTS.keepCompanion,
    companionAlwaysOnTop:
      typeof o.companionAlwaysOnTop === "boolean"
        ? o.companionAlwaysOnTop
        : OVERLAY_SETTINGS_DEFAULTS.companionAlwaysOnTop,
    overlayOpacity: _orDefault(_clampOpacity(o.overlayOpacity), OVERLAY_SETTINGS_DEFAULTS.overlayOpacity),
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
// truth). Never throws. null when the key is ABSENT (nobody has picked yet) or
// storage is disabled; otherwise the coerced tier, where "" is an explicit off
// (the PGR / Settings "- off -" option writes "") and junk reads as off.
function _readPgrRank() {
  try {
    const v = localStorage.getItem(PGR_RANK_KEY);
    return v === null || v === undefined ? null : _coerceTier(v);
  } catch (_e) {
    return null;
  }
}

// The raw in-page mirror, coerced; defaults when absent / corrupt.
function _readMirror() {
  try {
    return _coerce(JSON.parse(localStorage.getItem(LS_KEY) || "{}"));
  } catch (_e) {
    return { ...OVERLAY_SETTINGS_DEFAULTS };
  }
}

// Synchronous read from the in-page mirror. Never throws (a corrupt / absent
// value -> defaults), so the render + pulse hot paths can call it freely.
export function readOverlaySettings() {
  const s = _readMirror();
  // rc-pgr-rank-tier is the shared single source of truth: a pick made on the
  // PGR page or the desktop Settings row - "off" included - wins over a stale
  // mirror here, so the overlay reflects it without an explicit write back
  // through this helper. Only an ABSENT key falls back to the mirror.
  const pgr = _readPgrRank();
  if (pgr !== null) s.benchmarkRankTier = pgr;
  return s;
}

// Apply a partial patch (any subset of the OVERLAY_SETTINGS_DEFAULTS keys),
// persist to the localStorage mirror, and mirror to the rc-shell config over
// IPC when the bridge is present (fire-and-forget; a missing handler is
// swallowed). A wrong-typed boolean, or a blank / non-numeric number, is
// dropped and the current value kept (the shell's sanitizeSettingsPatch drops
// the same values). Returns the resolved settings so a caller can reflect the
// clamp back into the input.
export function writeOverlaySettings(patch) {
  const p = _isPlainObject(patch) ? patch : {};
  const cur = readOverlaySettings();
  const next = { ...cur };
  if (typeof p.pulseNotify === "boolean") next.pulseNotify = p.pulseNotify;
  next.activeRevertSec = _orDefault(_clampSec(p.activeRevertSec), next.activeRevertSec);
  if (typeof p.keepCompanion === "boolean") next.keepCompanion = p.keepCompanion;
  if (typeof p.companionAlwaysOnTop === "boolean") next.companionAlwaysOnTop = p.companionAlwaysOnTop;
  next.overlayOpacity = _orDefault(_clampOpacity(p.overlayOpacity), next.overlayOpacity);
  if (typeof p.clickThroughZones === "boolean") next.clickThroughZones = p.clickThroughZones;
  if (typeof p.separateWindows === "boolean") next.separateWindows = p.separateWindows;
  // Overlay item 8: rank-tier + role override. A benchmarkRankTier write also
  // mirrors to the shared rc-pgr-rank-tier key (both-ways sync) and fires a
  // same-origin event so the stats panel repaints in THIS window. The key is
  // re-written whenever it does not already hold the tier, not only when the
  // resolved value changed, so a key cleared or absent never stays behind.
  let rankChanged = false;
  let rankMirror = false;
  if (p.benchmarkRankTier !== undefined) {
    const t = _coerceTier(p.benchmarkRankTier);
    rankChanged = t !== next.benchmarkRankTier;
    rankMirror = rankChanged || _readPgrRank() !== t;
    next.benchmarkRankTier = t;
  }
  if (p.roleOverride !== undefined) next.roleOverride = _coerceRole(p.roleOverride);
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(next));
  } catch (_e) {
    // best-effort; a full / disabled storage must not break the control.
  }
  if (rankMirror) {
    // Mirror to the shared PGR/Settings key (the single source of truth).
    try {
      localStorage.setItem(PGR_RANK_KEY, next.benchmarkRankTier);
    } catch (_e) {
      // storage disabled - the in-page mirror above still carries it.
    }
  }
  if (rankChanged) {
    // Notify same-window listeners (the native storage event only fires in
    // OTHER windows of the origin).
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
// no-op. Fire-and-forget; returns true only if the shell bridge took it. Only a
// plain object naming a non-empty string action crosses the IPC boundary; the
// shell re-validates, this just keeps junk off the channel.
export function sendOverlayAction(msg) {
  if (!_isPlainObject(msg) || typeof msg.action !== "string" || msg.action === "") return false;
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
// resolves to a settings object (never rejects), equal to what
// readOverlaySettings() returns afterwards whenever storage accepted the write
// (with disabled storage it still carries the shell values for this page).
//
// The shell owns only the keys its overlaySettingsFrom returns; the page-only
// keys (benchmarkRankTier, roleOverride) are not in its reply, so only keys
// the reply actually carries replace the mirror - a whole-object replace reset
// the role override to auto on every shell page boot. A non-object reply
// (no config yet, an older shell) leaves the mirror untouched.
export function hydrateOverlaySettings() {
  try {
    if (window.rcShell && typeof window.rcShell.getOverlaySettings === "function") {
      return Promise.resolve(window.rcShell.getOverlaySettings())
        .then((s) => {
          if (!_isPlainObject(s)) return readOverlaySettings();
          const local = _readMirror();
          const shell = _coerce(s);
          for (const k of Object.keys(OVERLAY_SETTINGS_DEFAULTS)) {
            if (Object.prototype.hasOwnProperty.call(s, k) && s[k] !== undefined) local[k] = shell[k];
          }
          try {
            localStorage.setItem(LS_KEY, JSON.stringify(local));
          } catch (_e) {
            // best-effort mirror.
          }
          // Same PGR precedence as readOverlaySettings, without re-reading a
          // mirror that disabled storage could not have written.
          const pgr = _readPgrRank();
          if (pgr !== null) local.benchmarkRankTier = pgr;
          return local;
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
