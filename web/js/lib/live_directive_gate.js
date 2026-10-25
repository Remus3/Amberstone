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

//
// S134 T1 - the second arm. MEASURED 2026-10-25 in a live TFT match: TFT now
// runs as a standalone TFTClient process with NOTHING listening on :2999, so
// `liveclient` stayed {} for the whole match and the arm above never fired; the
// dashboard painted SR callouts ("Drake spawns 5:00 - set up vision") through
// the game. Outside the :2999 feed modes the LCU gameflow phase is the live
// signal: `lcu.phase === "InProgress"` is never champ select. The feed modes
// keep the liveclient contract, so their loading screen (LCU already
// InProgress, liveclient not answering yet) stays coached exactly as before.

const GAME_MODE_KEYS = ["sr", "aram", "arena", "tft", "brawl"];

// Modes whose live state arrives through the League :2999 Live Client API.
const FEED_MODE_KEYS = ["sr", "aram", "arena", "brawl"];

function _isNonEmptyObject(v) {
  return !!v && typeof v === "object" && Object.keys(v).length > 0;
}

function _lcuInProgress(state) {
  const lcu = state.lcu;
  return !!lcu && typeof lcu === "object" && !Array.isArray(lcu)
    && lcu.phase === "InProgress";
}

/**
 * True when a game is actually running.
 *
 * @param {object|null} state - the /api/state envelope (or the dashboard's
 *   state.latest cache, which carries the same mode_key / liveclient / lcu).
 * @returns {boolean} false for null/garbage/idle/champ-select.
 */
function isLiveGame(state) {
  if (!state || typeof state !== "object") return false;
  if (GAME_MODE_KEYS.indexOf(state.mode_key) !== -1
      && _isNonEmptyObject(state.liveclient)) return true;
  // No :2999 feed (TFT, or a live game whose mode RC has not resolved).
  return FEED_MODE_KEYS.indexOf(state.mode_key) === -1 && _lcuInProgress(state);
}

// The coach fields the server blanks while a game is live - a mirror of
// LIVE_SUPPRESSED_FIELDS in dashboard/_state_builder.py, pinned equal by
// tests/test_b4_client_directive_gate.py.
const LIVE_SUPPRESSED_FIELDS = [
  "action", "immediate", "fight_rule", "next", "risk",
  "target_priority", "round_strategy", "choices",
];

/**
 * A copy of a coach payload with every LIVE_SUPPRESSED_FIELDS key blanked
 * ("" - or [] for choices, as the server does). For renderers that read the
 * coach payload directly instead of a feed this module already gates; the
 * input is never mutated (it is the replayed state.latest cache). Absent
 * fields stay absent; a non-object passes through unchanged.
 *
 * @param {object} coach - the coach payload (/api/state.coach).
 * @returns {object}
 */
function withoutLiveDirectives(coach) {
  if (!coach || typeof coach !== "object" || Array.isArray(coach)) return coach;
  const out = Object.assign({}, coach);
  for (const f of LIVE_SUPPRESSED_FIELDS) {
    if (f in out) out[f] = (f === "choices") ? [] : "";
  }
  return out;
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
  module.exports = { isLiveGame, directivesAllowed, withoutLiveDirectives,
    GAME_MODE_KEYS, FEED_MODE_KEYS, LIVE_SUPPRESSED_FIELDS };
}
export { isLiveGame, directivesAllowed, withoutLiveDirectives,
  GAME_MODE_KEYS, FEED_MODE_KEYS, LIVE_SUPPRESSED_FIELDS };
