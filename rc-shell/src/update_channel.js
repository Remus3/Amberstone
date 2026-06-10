// rc-shell/src/update_channel.js
//
// PURE update-channel module. NO electron import - this is the testable core
// for Phase 5 stabilization (docs/ELECTRON_OVERLAY.md sections 8 + 10): the
// shell versions and auto-updates on its OWN cadence (electron-updater +
// GitHub Releases), decoupled from RC backend versioning.
//
// Two release channels (spec section 8.4):
//   - stable: the operator daily driver. Rides FULL GitHub Releases only.
//   - dev:    the iterating channel. Also rides PRERELEASE GitHub Releases
//             (electron-updater GitHub provider: allowPrerelease=true).
//
// Precedence for resolveChannel: env RC_SHELL_CHANNEL > saved state > stable.
// Same shape as config.resolveConfig so the two resolutions read alike.
//
// checkPlan() is the pure scheduling decision: a dev launch (not packaged) or
// a bare checkout (electron-updater not installed) disables update checks
// gracefully - the shell must run identically either way. main.js owns the
// actual timers + the autoUpdater wiring.

"use strict";

const CHANNELS = Object.freeze(["stable", "dev"]);
const DEFAULT_CHANNEL = "stable";

// Update-check cadence. The initial delay lets the shell boot + first paint
// before touching the network; the interval keeps the check quiet (a packaged
// shell changes rarely - 4 hours is plenty).
const CHECK_DEFAULTS = Object.freeze({
  initialDelayMs: 15000,
  intervalMs: 14400000, // 4 hours
});

// Normalize a raw channel value to a CHANNELS member, else "". Non-string or
// blank input -> "" (callers decide the fallback).
function normChannel(value) {
  const c = typeof value === "string" ? value.trim().toLowerCase() : "";
  return CHANNELS.includes(c) ? c : "";
}

// Resolve the effective channel: env RC_SHELL_CHANNEL > saved.updateChannel >
// DEFAULT_CHANNEL. Each layer must name a real channel to win - garbage or a
// blank value falls through to the next layer (so a stray RC_SHELL_CHANNEL=
// cannot wipe a saved choice). Null/undefined saved or env tolerated.
function resolveChannel(saved, env) {
  const s = saved && typeof saved === "object" ? saved : {};
  const e = env && typeof env === "object" ? env : {};
  return (
    normChannel(e.RC_SHELL_CHANNEL) || normChannel(s.updateChannel) || DEFAULT_CHANNEL
  );
}

// electron-updater GitHub-provider settings for a channel. Unknown input
// resolves through the same fallback first, so garbage can never flip a
// packaged shell onto prereleases.
function channelConfig(channel) {
  const c = normChannel(channel) || DEFAULT_CHANNEL;
  return { channel: c, allowPrerelease: c === "dev" };
}

// Merge a channel choice into a full saved-state blob WITHOUT touching any
// other key - mirrors ov.mergeOverlayPatch's contract so a channel switch can
// never wipe window/overlay state. Returns a new object; never mutates;
// garbage prev starts fresh; the channel is validated on the way in.
function mergeChannelPatch(prevState, channel) {
  const prev =
    prevState && typeof prevState === "object" && !Array.isArray(prevState)
      ? prevState
      : {};
  return Object.assign({}, prev, {
    updateChannel: normChannel(channel) || DEFAULT_CHANNEL,
  });
}

// Pure update-check scheduling decision. opts: { isPackaged, updaterPresent,
// intervalMs }. Checks are pointless (and electron-updater errors) when the
// app is not packaged, and impossible when the package is absent - both
// disable gracefully instead of crashing or dialog-spamming the operator.
function checkPlan(opts) {
  const o = opts && typeof opts === "object" ? opts : {};
  if (o.isPackaged !== true) {
    return {
      enabled: false,
      reason: "not-packaged",
      initialDelayMs: CHECK_DEFAULTS.initialDelayMs,
      intervalMs: CHECK_DEFAULTS.intervalMs,
    };
  }
  if (o.updaterPresent !== true) {
    return {
      enabled: false,
      reason: "updater-missing",
      initialDelayMs: CHECK_DEFAULTS.initialDelayMs,
      intervalMs: CHECK_DEFAULTS.intervalMs,
    };
  }
  const interval =
    typeof o.intervalMs === "number" && Number.isFinite(o.intervalMs) && o.intervalMs > 0
      ? o.intervalMs
      : CHECK_DEFAULTS.intervalMs;
  return {
    enabled: true,
    reason: "ok",
    initialDelayMs: CHECK_DEFAULTS.initialDelayMs,
    intervalMs: interval,
  };
}

module.exports = {
  CHANNELS,
  DEFAULT_CHANNEL,
  CHECK_DEFAULTS,
  normChannel,
  resolveChannel,
  channelConfig,
  mergeChannelPatch,
  checkPlan,
};
