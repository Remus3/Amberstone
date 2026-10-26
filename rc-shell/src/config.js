// rc-shell/src/config.js
//
// PURE config module. NO electron import - this is the testable core.
//
// First principle (docs/ELECTRON_OVERLAY.md section 1): origin is config, not
// code. The shell is a thin client that just points a window at RC_ORIGIN. The
// single value RC_ORIGIN is the ONLY thing that changes if the game host moves -
// https://127.0.0.1:8888 (default, local on Legion) or the machine's tailnet
// name (per-host config, never a tracked literal). No JS, no panel, no
// Electron code change.
//
// Precedence for resolveConfig: env RC_ORIGIN  >  host-served origin  >  saved
// state  >  defaults - and every origin candidate is VALIDATED first (PKG-3,
// docs/PACKAGING_PLAN.md S2): http(s) on loopback, or https on a host named in
// the per-host ops/local_hosts.json. An invalid candidate is skipped and
// reported as {source, reason}; the next one is tried. The preload bridge and
// the scoped cert trust follow the origin, so it must never be "any URL".

"use strict";

// Default origin: the Legion dashboard over loopback (1-PC, ADR-011; the
// mkcert leaf carries 127.0.0.1). An operator can point RC_ORIGIN at the
// machine's tailnet name with zero code change. See docs/ELECTRON_OVERLAY.md
// section 1.
const DEFAULT_ORIGIN = "https://127.0.0.1:8888";

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

// ---- origin validation (PKG-3, S2) -------------------------------------------

const ORIGIN_SCHEMES = Object.freeze(["http:", "https:"]);

// Cap on the per-host allow-list so a bloated local_hosts.json cannot grow it.
const MAX_ALLOWED_HOSTS = 64;

// Dotted-quad IPv4 with no leading-zero octet (WHATWG URL reads "010" as
// octal, so such a value would not mean what it says).
function ipv4Octets(s) {
  if (typeof s !== "string") {
    return null;
  }
  const m = /^(0|[1-9]\d{0,2})\.(0|[1-9]\d{0,2})\.(0|[1-9]\d{0,2})\.(0|[1-9]\d{0,2})$/.exec(s.trim());
  if (!m) {
    return null;
  }
  const o = m.slice(1).map(Number);
  return o.every((n) => n <= 255) ? o : null;
}

// True for localhost, 127.0.0.0/8 and ::1 (bracketed as URL.hostname gives it,
// or bare). Case-insensitive; never throws.
function isLoopbackHost(hostname) {
  if (typeof hostname !== "string") {
    return false;
  }
  const h = hostname.toLowerCase();
  if (h === "localhost" || h === "[::1]" || h === "::1") {
    return true;
  }
  const o = ipv4Octets(h);
  return !!o && o[0] === 127;
}

// One per-host entry -> the lower-case hostname URL parsing would give it, or
// null for anything that is not a bare host (port, path, wildcard, space).
function normalizeHostEntry(entry) {
  if (typeof entry !== "string") {
    return null;
  }
  const e = entry.trim();
  if (!e || e.length > 253 || /[\s/\\@*?#%]/.test(e)) {
    return null;
  }
  const wrapped = e.includes(":") && !e.startsWith("[") ? "[" + e + "]" : e;
  try {
    const u = new URL("https://" + wrapped + "/");
    if (u.port !== "" || u.username || u.password || u.pathname !== "/") {
      return null;
    }
    return u.hostname.toLowerCase();
  } catch (_e) {
    return null;
  }
}

// The non-loopback hosts an origin may name, from the per-host config
// (ops/local_hosts.json shape, core/local_hosts.py): tailnet_name,
// tailnet_fqdn, tailnet_ipv4 (only inside 100.64.0.0/10, as
// core/local_hosts.py tailnet_ipv4 does), lan_ipv4, cert_sans. Absent or
// malformed config -> [] (loopback only).
function allowedOriginHosts(localHosts) {
  const lh = localHosts && typeof localHosts === "object" && !Array.isArray(localHosts) ? localHosts : {};
  const out = [];
  const add = (v) => {
    const h = normalizeHostEntry(v);
    if (h && !out.includes(h) && out.length < MAX_ALLOWED_HOSTS) {
      out.push(h);
    }
  };
  add(lh.tailnet_name);
  add(lh.tailnet_fqdn);
  const t = ipv4Octets(lh.tailnet_ipv4);
  if (t && t[0] === 100 && t[1] >= 64 && t[1] <= 127) {
    add(lh.tailnet_ipv4);
  }
  if (ipv4Octets(lh.lan_ipv4)) {
    add(lh.lan_ipv4);
  }
  if (Array.isArray(lh.cert_sans)) {
    for (const san of lh.cert_sans) {
      add(san);
    }
  }
  return out;
}

// Validate one origin string. opts.localHosts = the per-host config object.
// Returns {ok, origin, reason}: origin is the normalised URL.origin when ok,
// else null. reason: "ok", "empty", "malformed", "bad-scheme", "credentials",
// "not-an-origin" (a path / query / fragment), "host-not-allowed",
// "insecure-remote" (plain http off loopback). Never throws.
function validateOrigin(origin, opts) {
  const o = opts && typeof opts === "object" ? opts : {};
  const fail = (reason) => ({ ok: false, origin: null, reason });
  if (typeof origin !== "string" || !origin.trim()) {
    return fail("empty");
  }
  let u;
  try {
    u = new URL(origin.trim());
  } catch (_e) {
    return fail("malformed");
  }
  if (!ORIGIN_SCHEMES.includes(u.protocol)) {
    return fail("bad-scheme");
  }
  if (u.username || u.password) {
    return fail("credentials");
  }
  if (u.pathname !== "/" || u.search || u.hash) {
    return fail("not-an-origin");
  }
  const host = u.hostname.toLowerCase();
  if (!isLoopbackHost(host)) {
    if (!allowedOriginHosts(o.localHosts).includes(host)) {
      return fail("host-not-allowed");
    }
    if (u.protocol !== "https:") {
      return fail("insecure-remote");
    }
  }
  return { ok: true, origin: u.origin, reason: "ok" };
}

// Merge saved state + RC_ORIGIN env override + defaults into a resolved config.
//
//   origin precedence (highest first): env.RC_ORIGIN, opts.servedOrigin,
//   saved.origin, DEFAULT_ORIGIN - the first candidate that passes
//   validateOrigin wins
//
// - saved is whatever store.js loaded (may be {} / null / partial / garbage).
// - env is a plain object (e.g. process.env); only RC_ORIGIN is consulted.
// - opts (optional): {localHosts, servedOrigin}. localHosts widens the origin
//   allow-list (rc_root.readLocalHosts); servedOrigin is the origin the
//   launcher reports it actually serves (section 3.6, fixes M4).
// - width/height fall back through saved -> preset -> default-preset.
// - sizePreset is validated against SIZE_PRESETS; unknown -> DEFAULT_PRESET.
// - originSource names the winning candidate ("env" | "served" | "saved" |
//   "default"); originRejected lists the skipped ones as {source, reason},
//   never their value (a caller may log it).
function resolveConfig(saved, env, opts) {
  const d = defaultConfig();
  const s = saved && typeof saved === "object" ? saved : {};
  const e = env && typeof env === "object" ? env : {};
  const op = opts && typeof opts === "object" ? opts : {};

  // sizePreset: saved wins if it names a real preset, else default.
  let sizePreset =
    typeof s.sizePreset === "string" && SIZE_PRESETS[s.sizePreset]
      ? s.sizePreset
      : d.sizePreset;
  const preset = SIZE_PRESETS[sizePreset];

  // origin: env override beats the served origin beats saved beats default. A
  // blank/whitespace value is ignored (treated as unset) so an empty
  // RC_ORIGIN= cannot wipe it; an invalid one is skipped and reported.
  const candidates = [];
  if (typeof e.RC_ORIGIN === "string" && e.RC_ORIGIN.trim()) {
    candidates.push({ source: "env", value: e.RC_ORIGIN });
  }
  if (typeof op.servedOrigin === "string" && op.servedOrigin.trim()) {
    candidates.push({ source: "served", value: op.servedOrigin });
  }
  if (typeof s.origin === "string" && s.origin.trim()) {
    candidates.push({ source: "saved", value: s.origin });
  }
  let origin = d.origin;
  let originSource = "default";
  const originRejected = [];
  for (const c of candidates) {
    const v = validateOrigin(c.value, { localHosts: op.localHosts });
    if (v.ok) {
      origin = v.origin;
      originSource = c.source;
      break;
    }
    originRejected.push({ source: c.source, reason: v.reason });
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

  return {
    origin,
    width,
    height,
    x,
    y,
    alwaysOnTop,
    sizePreset,
    originSource,
    originRejected,
  };
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
  ORIGIN_SCHEMES,
  isLoopbackHost,
  allowedOriginHosts,
  validateOrigin,
};
