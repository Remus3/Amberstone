// rc-shell/src/crash_guard.js
//
// PURE crash-isolation restart policy. NO electron import - this is the
// node:testable core for Phase 5 (stabilization) of docs/ELECTRON_OVERLAY.md
// section 8 item 5: an overlay window crash must not take down the companion
// or the game; the main process restarts a dead overlay.
//
// Electron already gives each BrowserWindow its own renderer process, so one
// window dying never drags the other down by itself. What it does NOT give us
// is the recovery policy - that is this module. An overlay crash mid-game must
// self-heal invisibly (main recreates the window; the operator keeps playing).
// But a crash LOOP (bad deploy, OOM spiral) must not strobe a half-dead window
// over a live game forever: after maxRestarts restartable crashes inside a
// rolling windowMs the guard answers "give-up" and the surface stays dark
// until the old crashes age out of the window. "killed" (taskkill / external
// teardown) and "clean-exit" (normal navigation/shutdown teardown) are
// deliberate terminations - resurrecting those would fight the operator, so
// they never restart. Unknown reasons are fail-safe: never restart on a
// reason we do not understand.
//
// main.js wires webContents "render-process-gone" ->
// record(key, details.reason) and acts on the returned action; this module
// never touches electron, timers, or the wall clock (now is injectable).

"use strict";

// render-process-gone details.reason values that warrant an auto-restart.
// Everything else ("clean-exit", "killed", anything unrecognized) is
// deliberate, external, or not understood -> no restart.
const RESTART_REASONS = Object.freeze(
  new Set(["crashed", "oom", "abnormal-exit", "launch-failed", "integrity-failure"])
);

const CRASH_GUARD_DEFAULTS = Object.freeze({
  maxRestarts: 3, // restartable crashes tolerated per key per rolling window
  windowMs: 60000, // rolling-window width for the restart budget
});

// Pure predicate: should this render-process-gone reason auto-restart at all?
// Exact-match against RESTART_REASONS; unknown / missing / non-string -> false.
function shouldRestart(reason) {
  return typeof reason === "string" && RESTART_REASONS.has(reason);
}

// Factory for a per-process-lifetime crash tracker. opts:
//   maxRestarts  restart budget per key per rolling window (default 3)
//   windowMs     rolling-window width in ms (default 60000)
//   now          injectable clock fn returning ms (default Date.now)
// Non-finite / non-positive overrides fall back to the defaults. Keys are
// independent window identities ("companion" / "overlay" today, but any
// string works) - one key's crash loop never consumes another's budget.
function makeCrashGuard(opts) {
  const o = opts && typeof opts === "object" ? opts : {};
  const rawMax = Number.isFinite(o.maxRestarts) ? Math.floor(o.maxRestarts) : 0;
  const maxRestarts = rawMax > 0 ? rawMax : CRASH_GUARD_DEFAULTS.maxRestarts;
  const windowMs =
    Number.isFinite(o.windowMs) && o.windowMs > 0
      ? o.windowMs
      : CRASH_GUARD_DEFAULTS.windowMs;
  const now = typeof o.now === "function" ? o.now : Date.now;

  // key -> timestamps (ms) of restartable crashes still inside the window.
  const crashes = new Map();

  // Drop timestamps that have aged out of the trailing window at time t and
  // return the surviving list. A crash exactly windowMs old is out. Storing
  // the pruned list back keeps a long crash history from growing unbounded.
  function prune(key, t) {
    const kept = (crashes.get(key) || []).filter((ts) => ts > t - windowMs);
    if (kept.length > 0) {
      crashes.set(key, kept);
    } else {
      crashes.delete(key);
    }
    return kept;
  }

  return {
    // Record one render-process-gone event for a window identity. Returns
    // { action, reason, count, key } where action is:
    //   "ignore"   not a restartable reason (deliberate/external/unknown);
    //              the budget is untouched.
    //   "restart"  restartable, and the rolling in-window count (including
    //              this crash) is within maxRestarts -> recreate the window.
    //   "give-up"  restartable, but the window budget is exhausted -> leave
    //              the surface dark; the budget refills as crashes age out.
    // count = the in-window restartable-crash count for the key after
    // recording (give-up crashes are recorded too, so a live loop converges
    // to give-up instead of oscillating).
    record(key, reason) {
      const t = now();
      if (!shouldRestart(reason)) {
        return { action: "ignore", reason, count: prune(key, t).length, key };
      }
      const list = prune(key, t);
      list.push(t);
      crashes.set(key, list);
      const count = list.length;
      return {
        action: count <= maxRestarts ? "restart" : "give-up",
        reason,
        count,
        key,
      };
    },

    // Diagnostics snapshot for a key at the current clock: the in-window
    // restartable-crash count and how many restarts remain before give-up
    // (clamped at 0 - never negative).
    state(key) {
      const count = prune(key, now()).length;
      return { count, remaining: Math.max(0, maxRestarts - count) };
    },
  };
}

module.exports = {
  RESTART_REASONS,
  CRASH_GUARD_DEFAULTS,
  shouldRestart,
  makeCrashGuard,
};
