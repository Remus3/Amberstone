// rc-shell/src/config.js
//
// PURE config module. NO electron import - this is the testable core.
//
// First principle (docs/ELECTRON_OVERLAY.md section 1): origin is config, not
// code. The shell is a thin client that just points a window at RC_ORIGIN. The
// single value RC_ORIGIN is the ONLY thing that changes if the game host moves -
// https://legion-rc:8888 (default) or https://127.0.0.1:8888 (local on Legion).
// No JS, no panel, no Electron code change.
//
// Precedence for resolveConfig: env RC_ORIGIN  >  saved state  >  defaults.

"use strict";

// Default origin: the Legion dashboard (1-PC, ADR-011). An operator can flip
// RC_ORIGIN to https://127.0.0.1:8888 (local on Legion) with zero code
// change. See docs/ELECTRON_OVERLAY.md section 1.
const DEFAULT_ORIGIN = "https://legion-rc:8888";

// Size presets (docs/ELECTRON_OVERLAY.md section 3.7). standard is the
// DEFAULT_PRESET - the size a fresh companion opens at, since resolveConfig
// falls back to it when no width/height is saved. It is set to the operator's
// settled companion size (920x1280, the comfortable read on the portrait
// companion display); the dashboard home + out-of-game views are responsively
// reflowed to fit this width (web/css/panels/*.css @media max-width:1200px).
// compact stays the minimize-to-strip option; tall sits above standard so the
// Compact / Standard / Tall menu ladder stays monotonic.
const SIZE_PRESETS = Object.freeze({
  compact: Object.freeze({ width: 380, height: 720 }),
  standard: Object.freeze({ width: 920, height: 1280 }),
  tall: Object.freeze({ width: 1100, height: 1560 }),
});

const DEFAULT_PRESET = "standard";

// The default config. x/y null means "let the OS / centering decide on first
// launch"; once the window moves, store.js persists real coords.
function defaultConfig() {
  const preset = SIZE_PRESETS[DEFAULT_PRESET];
  return {
    origin: DEFAULT_ORIGIN,
    width: preset.width,
    height: preset.height,
    x: null,
    y: null,
    alwaysOnTop: true,
    sizePreset: DEFAULT_PRESET,
  };
}

// Apply a named size preset to a config, returning a NEW config object with
// width/height/sizePreset updated. Unknown preset name -> config returned
// unchanged (defensive; never throws).
function applyPreset(cfg, presetName) {
  const base = cfg && typeof cfg === "object" ? cfg : defaultConfig();
  const preset = SIZE_PRESETS[presetName];
  if (!preset) {
    return Object.assign({}, base);
  }
  return Object.assign({}, base, {
    width: preset.width,
    height: preset.height,
    sizePreset: presetName,
  });
}

// Derive the origin host (host:port) from an origin URL string. Used by the
// scoped certificate-error handler so we trust ONLY the RC origin's self-signed
// cert, never globally. Returns "" on a malformed origin.
function originHost(origin) {
  try {
    return new URL(origin).host;
  } catch (_e) {
    return "";
  }
}

// Pull a positive finite number, else fallback.
function posNum(v, fallback) {
  return typeof v === "number" && isFinite(v) && v > 0 ? v : fallback;
}

// Merge saved state + RC_ORIGIN env override + defaults into a resolved config.
//
//   precedence (highest first): env.RC_ORIGIN, saved, defaults
//
// - saved is whatever store.js loaded (may be {} / null / partial / garbage).
// - env is a plain object (e.g. process.env); only RC_ORIGIN is consulted.
// - width/height fall back through saved -> preset -> default-preset.
// - sizePreset is validated against SIZE_PRESETS; unknown -> DEFAULT_PRESET.
function resolveConfig(saved, env) {
  const d = defaultConfig();
  const s = saved && typeof saved === "object" ? saved : {};
  const e = env && typeof env === "object" ? env : {};

  // sizePreset: saved wins if it names a real preset, else default.
  let sizePreset =
    typeof s.sizePreset === "string" && SIZE_PRESETS[s.sizePreset]
      ? s.sizePreset
      : d.sizePreset;
  const preset = SIZE_PRESETS[sizePreset];

  // origin: env override beats saved beats default. A blank/whitespace env
  // value is ignored (treated as unset) so an empty RC_ORIGIN= cannot wipe it.
  let origin = d.origin;
  if (typeof s.origin === "string" && s.origin.trim()) {
    origin = s.origin.trim();
  }
  if (typeof e.RC_ORIGIN === "string" && e.RC_ORIGIN.trim()) {
    origin = e.RC_ORIGIN.trim();
  }

  // width/height: saved -> preset (selected above) -> hard default.
  const width = posNum(s.width, preset.width);
  const height = posNum(s.height, preset.height);

  // x/y: saved coords if numeric, else null (centering on first launch). These
  // are clamped to a real display by clampPosition() in main.js.
  const x = typeof s.x === "number" && isFinite(s.x) ? s.x : null;
  const y = typeof s.y === "number" && isFinite(s.y) ? s.y : null;

  // alwaysOnTop: saved boolean wins, else default true.
  const alwaysOnTop =
    typeof s.alwaysOnTop === "boolean" ? s.alwaysOnTop : d.alwaysOnTop;

  return { origin, width, height, x, y, alwaysOnTop, sizePreset };
}

// Keep a window position on-screen. Given a desired pos {x, y, width, height}
// and a display work-area bounds {x, y, width, height}, return clamped {x, y}
// so the window's top-left stays inside the display and the window does not
// hang off the right/bottom edge (best effort if the window is larger than the
// display: pin to display origin).
//
// If pos.x / pos.y are null/undefined (first launch, not yet positioned),
// returns {x: null, y: null} so the caller lets the OS center the window.
function clampPosition(pos, displayBounds) {
  const p = pos && typeof pos === "object" ? pos : {};
  const b = displayBounds && typeof displayBounds === "object" ? displayBounds : {};

  // Not-yet-positioned: signal "center me".
  if (
    !(typeof p.x === "number" && isFinite(p.x)) ||
    !(typeof p.y === "number" && isFinite(p.y))
  ) {
    return { x: null, y: null };
  }

  const dx = typeof b.x === "number" && isFinite(b.x) ? b.x : 0;
  const dy = typeof b.y === "number" && isFinite(b.y) ? b.y : 0;
  const dw = posNum(b.width, 1920);
  const dh = posNum(b.height, 1080);

  const w = posNum(p.width, 0);
  const h = posNum(p.height, 0);

  // Max top-left so the window's far edge stays inside the display. If the
  // window is wider/taller than the display, max collapses below min; we then
  // pin to the display origin (Math.max wins).
  const minX = dx;
  const minY = dy;
  const maxX = dx + dw - w;
  const maxY = dy + dh - h;

  const x = Math.round(Math.max(minX, Math.min(p.x, Math.max(minX, maxX))));
  const y = Math.round(Math.max(minY, Math.min(p.y, Math.max(minY, maxY))));

  return { x, y };
}

module.exports = {
  DEFAULT_ORIGIN,
  DEFAULT_PRESET,
  SIZE_PRESETS,
  defaultConfig,
  applyPreset,
  resolveConfig,
  clampPosition,
  originHost,
};
