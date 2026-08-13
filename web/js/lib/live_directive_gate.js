// live_directive_gate.js - B4 (RM-189) client-side directive gate.
//
// Riot's third-party rules ban "notifications that dictate player action based
// on the current game state". The AUTHORITATIVE gate is server-side: while a
// game is live, dashboard/_state_builder.py blanks the coach imperatives
// (suppress_live_directives) and the deterministic callout / lead feeds
// (suppress_live_envelope), so a compliant client has nothing to paint.
//
// This module is DEFENCE IN DEPTH ONLY. It exists because the served envelope
// is cached client-side (state.latest) and replayed on re-render, so a payload
// captured a tick before the game started could still repaint a directive
// after it. It is deliberately NOT the only gate: a renderer-only boundary
// still ships the banned content to the client, where a reviewer can read it
// straight off the network tab.
//
// PREDICATE - why not the health flags. `health.aram_mode` and friends are
// MIRRORED onto the served health during LCU champ select by
// apply_preflip_mirror (dashboard/_state_builder.py), so the flags alone
// cannot tell "in an ARAM" from "sitting in an ARAM lobby". Champ select is
// pre-game, where coaching is explicitly still allowed and is the single most
// useful surface RC has. So the client predicate is instead:
//
//     a game-shaped mode_key  AND  a non-empty liveclient
//
// `liveclient` is {} until a game is actually running (measured against the
// live endpoint 2026-08-12), which is the same contract the game-monitor tick
// already uses. Server-side the equivalent question is answered by
// is_live_game(health, preflip_active), which HAS the preflip flag and does
// not need this proxy.

const GAME_MODE_KEYS = ["sr", "aram", "arena", "tft", "brawl"];

function _isNonEmptyObject(v) {
  return !!v && typeof v === "object" && Object.keys(v).length > 0;
}

/**
 * True when a game is actually running.
 *
 * @param {object|null} state - the /api/state envelope.
 * @returns {boolean} false for null/garbage/idle/champ-select.
 */
function isLiveGame(state) {
  if (!state || typeof state !== "object") return false;
  if (GAME_MODE_KEYS.indexOf(state.mode_key) === -1) return false;
  return _isNonEmptyObject(state.liveclient);
}

/**
 * True when a coach imperative may be painted.
 *
 * Fail-SAFE on garbage: an unreadable state is not a live game, so directives
 * are allowed. The compliance guarantee rests on the server blanking the
 * fields, not on this returning false - a fail-closed default here would
 * instead blank the legitimate pre-game and post-game coaching surfaces every
 * time a tick arrived malformed.
 *
 * @param {object|null} state - the /api/state envelope.
 * @returns {boolean}
 */
function directivesAllowed(state) {
  return !isLiveGame(state);
}

// Dual export, mirroring web/js/lib/overlay_priority.js: ES module for the
// browser, CommonJS for the node-run test. The browser never sees `module`.
if (typeof module !== "undefined" && module.exports) {
  module.exports = { isLiveGame, directivesAllowed, GAME_MODE_KEYS };
}
export { isLiveGame, directivesAllowed, GAME_MODE_KEYS };
