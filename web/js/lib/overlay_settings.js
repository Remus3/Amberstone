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

// keepCompanion / companionAlwaysOnTop default ON: RC2 3.4 (E1) - the full
// dashboard window STAYS available alongside the in-game overlay and is pinned
// on top unless the operator opts out. The rc-shell main process is the
// authority (overlay_state.overlaySettingsFrom mirrors these same defaults); the
// helper carries them so a dashboard toggle reaches the shell over IPC instead
// of being silently dropped here.
export const OVERLAY_SETTINGS_DEFAULTS = {
  pulseNotify: true,
  activeRevertSec: 20,
  keepCompanion: true,
  companionAlwaysOnTop: true,
};

// Clamp the ACTIVE auto-revert seconds to [3,120] (mirrors the rc-shell
// overlaySettingsFrom bounds). Non-finite -> the default.
function _clampSec(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return OVERLAY_SETTINGS_DEFAULTS.activeRevertSec;
  return Math.min(120, Math.max(3, Math.round(n)));
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
  };
}

// Synchronous read from the in-page mirror. Never throws (a corrupt / absent
// value -> defaults), so the render + pulse hot paths can call it freely.
export function readOverlaySettings() {
  try {
    return _coerce(JSON.parse(localStorage.getItem(LS_KEY) || "{}"));
  } catch (_e) {
    return { ...OVERLAY_SETTINGS_DEFAULTS };
  }
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
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(next));
  } catch (_e) {
    // best-effort; a full / disabled storage must not break the control.
  }
  try {
    if (window.rcShell && typeof window.rcShell.setOverlaySettings === "function") {
      Promise.resolve(window.rcShell.setOverlaySettings(next)).catch(() => {});
    }
  } catch (_e) {
    // no bridge (plain browser) - localStorage already holds the value.
  }
  return next;
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
