// web/js/lib/overlay_phase.js
//
// RC-PHASE-SURFACES (MAIN ORDER 2215 item 9, docs/OVERLAY_DOCTRINE.md section 10):
// which widgets the field paints in each game phase. Pure mapping + one stamp;
// lib/overlay_layout.js applies it through the same .ovx-hidden read-side path as
// the game-family gate, computed and never persisted, so the operator's per-widget
// hide survives every phase untouched.
//
// Sources, official only, both already on /api/state:
//   lcu.phase   the LCU /lol-gameflow/v1/gameflow-phase body (lcu/snapshot_shape.py),
//               falsy when it names no phase. It BLINKS mid-game:
//               dashboard/_liveclient.lcu_summary returns {} for a snapshot older
//               than 5 s, so a real game runs with no lcu.phase for long stretches.
//   liveclient  the Live Client Data API :2999 block, {} until a game answers.
//
// The rule: a definite LCU phase says what the client is doing, and only the
// liveclient block can say the game process is up. Any uncertainty fails OPEN to
// "unknown", which gates nothing: the panel a real game is showing must never blink
// off because a poll was late. The rc-shell window gate sits above all of this
// (rc-shell/src/overlay_state.js liveGameFromState) and is unchanged.

import { FEED_MODE_KEYS } from "./live_directive_gate.js";

export const OVERLAY_PHASES = Object.freeze([
  "lobby", "champ-select", "loading", "in-game", "post-game",
]);
export const PHASE_UNKNOWN = "unknown";

// Widgets each out-of-game phase paints, besides the launcher (game "*", the
// always-on escape hatch). "in-game" has NO list: every widget of the game family,
// including ones registered at runtime, and a widget a list does not name is
// live-only by default. The doctrine table is machine-read against this
// (rc-shell/test/overlay_phase_contract.test.js).
export const PHASE_WIDGETS = Object.freeze({
  lobby: Object.freeze([]),
  // Pre-game coaching is allowed (live_directive_gate.js). w-build is placed so
  // its matchup card + draft-elo chip can paint the tick the :2999 roster answers,
  // but both read that roster (active_match.js _amDsSyntheticCs,
  // _renderDraftEloFromCtx), so before the feed the pane paints whatever the coach
  // payload carries or its own empty line, and never a matchup answer: in champ
  // select that answer is the companion's (doctrine section 10, RM-1384 / RM-1385).
  // w-ovds is the knob pane worth touching only while a pick can still change;
  // w-arambalance self-gates to ARAM.
  "champ-select": Object.freeze(["w-call", "w-choices", "w-build", "w-ovds", "w-arambalance"]),
  loading: Object.freeze(["w-call", "w-choices", "w-build", "w-arambalance"]),
  "post-game": Object.freeze([]),
});

const _LOBBY = new Set(["Lobby", "Matchmaking", "ReadyCheck", "CheckedIntoTournament"]);
const _POST_GAME = new Set(["WaitingForStats", "PreEndOfGame", "EndOfGame", "TerminatedInError"]);
const _GAME = new Set(["GameStart", "InProgress", "Reconnect"]);

function _obj(v) {
  return v && typeof v === "object" && !Array.isArray(v) ? v : null;
}

function _rawPhase(st) {
  const lcu = _obj(st.lcu);
  return lcu && typeof lcu.phase === "string" ? lcu.phase : "";
}

function _hasFeed(st) {
  const lc = _obj(st.liveclient);
  return !!lc && Object.keys(lc).length > 0;
}

/**
 * The overlay phase of an /api/state envelope.
 *
 * @param {object|null} state - the /api/state envelope.
 * @returns {string} an OVERLAY_PHASES member or PHASE_UNKNOWN. Never throws.
 */
export function overlayPhaseFromState(state) {
  const st = _obj(state);
  if (!st) return PHASE_UNKNOWN;
  const raw = _rawPhase(st);
  const feed = _hasFeed(st);
  if (_POST_GAME.has(raw)) return "post-game";
  if (raw === "ChampSelect") return "champ-select";
  if (_LOBBY.has(raw)) return "lobby";
  if (_GAME.has(raw)) {
    if (feed) return "in-game";
    // No :2999 answer yet. In a feed mode that is the loading screen; TFT (and a
    // mode RC has not resolved) has no feed to wait for, so InProgress IS the game.
    if (raw === "GameStart" || FEED_MODE_KEYS.includes(st.mode_key)) return "loading";
    return "in-game";
  }
  // Blank, "None" or a phase this map does not model: only the feed can speak. A
  // practice tool or replay reports "None" with a game process up.
  if (feed) return "in-game";
  return raw === "None" ? "lobby" : PHASE_UNKNOWN;
}

/**
 * The next stamped phase. Post-game holds across an LCU blink while :2999 still
 * answers: the blank tick alone would read in-game and flash the HUD back over the
 * end-of-game screen. A definite phase or the feed going away releases it.
 */
export function nextOverlayPhase(prev, state) {
  const next = overlayPhaseFromState(state);
  if (prev === "post-game" && next === "in-game" && !_rawPhase(_obj(state) || {})) {
    return "post-game";
  }
  return next;
}

/**
 * May this widget paint in this phase? True for every widget in-game and for
 * anything that is not a phase at all (fails open). The launcher is exempted by the
 * caller, overlay_layout.js _posFor.
 */
export function widgetAllowedInPhase(id, phase) {
  if (!Object.prototype.hasOwnProperty.call(PHASE_WIDGETS, phase)) return true;
  return PHASE_WIDGETS[phase].includes(id);
}

/**
 * Stamp body[data-ovx-phase] from a full /api/state payload. Overlay shell only.
 * lib/overlay_tft.js renderTftOverlay calls it, the per-tick full-state seam that
 * already stamps the game family, so web/js/main.js needs no new wire.
 *
 * @returns {boolean} true when the stamp changed (the caller re-places the field).
 */
export function stampOverlayPhase(doc, state) {
  try {
    const body = doc && doc.body;
    if (!body || !body.dataset || body.dataset.shell !== "overlay") return false;
    const next = nextOverlayPhase(body.dataset.ovxPhase || "", state);
    if (body.dataset.ovxPhase === next) return false;
    body.dataset.ovxPhase = next;
    return true;
  } catch (_e) {
    return false; // additive; never break the state stream over a stamp.
  }
}
