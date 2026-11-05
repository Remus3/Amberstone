// web/js/lib/overlay_phase.test.mjs
//
// RC-PHASE-SURFACES (docs/OVERLAY_DOCTRINE.md section 10): the pure half of the
// phase map, one block per phase. Run with `node --test`; the pytest wrapper in
// tests/snapshot_panels/test_overlay_phase_surfaces.py runs this file, and the
// real-browser half lives there too. The shapes come from /api/state as served:
// lcu.phase (lcu/snapshot_shape.py capture_state, the LCU
// /lol-gameflow/v1/gameflow-phase body, or None when it names no phase),
// liveclient (dashboard/_liveclient.py, {} until a game answers on :2999) and
// mode_key.

import test from "node:test";
import assert from "node:assert";

import {
  OVERLAY_PHASES,
  PHASE_UNKNOWN,
  PHASE_WIDGETS,
  overlayPhaseFromState,
  nextOverlayPhase,
  widgetAllowedInPhase,
  stampOverlayPhase,
} from "./overlay_phase.js";

const FEED = { level: 6, game_time_s: 120 };

function st(phase, liveclient, mode_key = "sr") {
  return { mode_key, lcu: { phase }, liveclient };
}

test("lobby: every idle and queueing LCU phase with no :2999 feed", () => {
  for (const p of ["None", "Lobby", "Matchmaking", "ReadyCheck", "CheckedIntoTournament"]) {
    assert.strictEqual(overlayPhaseFromState(st(p, {})), "lobby", p);
  }
  // RC pre-flips mode_key during the lobby; the phase still reads lobby.
  assert.strictEqual(overlayPhaseFromState(st("Lobby", {}, "aram")), "lobby");
});

test("lobby: a stale :2999 read does not turn a queueing phase into a game", () => {
  assert.strictEqual(overlayPhaseFromState(st("Lobby", FEED)), "lobby");
  assert.strictEqual(overlayPhaseFromState(st("ReadyCheck", FEED)), "lobby");
});

test("champ-select: the LCU phase wins over everything, feed or not", () => {
  assert.strictEqual(overlayPhaseFromState(st("ChampSelect", {})), "champ-select");
  assert.strictEqual(overlayPhaseFromState(st("ChampSelect", FEED)), "champ-select");
  assert.strictEqual(overlayPhaseFromState(st("ChampSelect", null, "aram")), "champ-select");
});

test("loading: GameStart, or InProgress before :2999 answers in a feed mode", () => {
  assert.strictEqual(overlayPhaseFromState(st("GameStart", {})), "loading");
  assert.strictEqual(overlayPhaseFromState(st("GameStart", {}, "tft")), "loading");
  for (const mode of ["sr", "aram", "arena", "brawl"]) {
    assert.strictEqual(overlayPhaseFromState(st("InProgress", {}, mode)), "loading", mode);
    assert.strictEqual(overlayPhaseFromState(st("Reconnect", null, mode)), "loading", mode);
  }
});

test("in-game: the feed is up, or the mode has no feed (TFT)", () => {
  assert.strictEqual(overlayPhaseFromState(st("InProgress", FEED)), "in-game");
  assert.strictEqual(overlayPhaseFromState(st("GameStart", FEED)), "in-game");
  assert.strictEqual(overlayPhaseFromState(st("Reconnect", FEED)), "in-game");
  // TFT runs with nothing on :2999 (S134 T1, measured 2026-10-25).
  assert.strictEqual(overlayPhaseFromState(st("InProgress", {}, "tft")), "in-game");
});

test("in-game: the LCU blink keeps the game (lcu_summary drops old snapshots)", () => {
  // dashboard/_liveclient.lcu_summary returns {} for a snapshot older than 5 s,
  // so a real game runs with no lcu.phase for long stretches.
  assert.strictEqual(overlayPhaseFromState({ mode_key: "sr", lcu: {}, liveclient: FEED }), "in-game");
  assert.strictEqual(overlayPhaseFromState({ mode_key: "sr", liveclient: FEED }), "in-game");
  assert.strictEqual(overlayPhaseFromState(st(null, FEED)), "in-game");
  // "None" with a game process up (practice tool, replay): trust the feed.
  assert.strictEqual(overlayPhaseFromState(st("None", FEED)), "in-game");
  // An unmodelled phase string is no claim either.
  assert.strictEqual(overlayPhaseFromState(st("WatchInProgress", FEED)), "in-game");
});

test("post-game: every end phase, and :2999 answering late does not undo it", () => {
  for (const p of ["WaitingForStats", "PreEndOfGame", "EndOfGame", "TerminatedInError"]) {
    assert.strictEqual(overlayPhaseFromState(st(p, {})), "post-game", p);
    assert.strictEqual(overlayPhaseFromState(st(p, FEED)), "post-game", p + " + feed");
  }
});

test("post-game holds across an LCU blink while the feed still answers", () => {
  const blink = { mode_key: "sr", lcu: {}, liveclient: FEED };
  assert.strictEqual(nextOverlayPhase("post-game", blink), "post-game");
  // A definite phase releases the hold.
  assert.strictEqual(nextOverlayPhase("post-game", st("InProgress", FEED)), "in-game");
  assert.strictEqual(nextOverlayPhase("post-game", st("Lobby", {})), "lobby");
  // The feed going away releases it too.
  assert.strictEqual(nextOverlayPhase("post-game", { mode_key: "sr", lcu: {}, liveclient: {} }), PHASE_UNKNOWN);
  // No other phase is sticky: a mid-game blink stays in-game by the feed alone.
  assert.strictEqual(nextOverlayPhase("in-game", blink), "in-game");
  assert.strictEqual(nextOverlayPhase("", blink), "in-game");
});

test("unknown: no phase and no feed, and garbage never throws", () => {
  for (const bad of [null, undefined, 7, "x", [], {}, { lcu: "x", liveclient: "y" },
    { lcu: { phase: 12 }, liveclient: [] }, { lcu: {}, liveclient: {} }]) {
    assert.strictEqual(overlayPhaseFromState(bad), PHASE_UNKNOWN, JSON.stringify(bad));
  }
});

test("the gate: every widget in-game, the list elsewhere, unknown fails open", () => {
  const SOME = "w-objgauges"; // a live-only widget no pre-game row names
  assert.strictEqual(widgetAllowedInPhase(SOME, "in-game"), true);
  assert.strictEqual(widgetAllowedInPhase("w-tft-board", "in-game"), true);
  for (const phase of ["lobby", "champ-select", "loading", "post-game"]) {
    assert.strictEqual(widgetAllowedInPhase(SOME, phase), false, phase);
    assert.strictEqual(widgetAllowedInPhase("w-tft-board", phase), false, phase);
    for (const id of PHASE_WIDGETS[phase]) {
      assert.strictEqual(widgetAllowedInPhase(id, phase), true, phase + " " + id);
    }
  }
  // Not a phase at all: the operator's flags and the data gates are the only
  // gates left (the state before the first tick, and any LCU blink).
  for (const phase of [PHASE_UNKNOWN, "", undefined, "garbage", "__proto__", "constructor"]) {
    assert.strictEqual(widgetAllowedInPhase(SOME, phase), true, String(phase));
  }
});

test("the map carries the matchup host into champ select and loading", () => {
  // w-build hosts #csv-sugg-ds-matchup and #am-draft-elo (web/index.html).
  assert.ok(PHASE_WIDGETS["champ-select"].includes("w-build"));
  assert.ok(PHASE_WIDGETS.loading.includes("w-build"));
  assert.deepStrictEqual(PHASE_WIDGETS.lobby, []);
  assert.deepStrictEqual(PHASE_WIDGETS["post-game"], []);
  assert.deepStrictEqual(
    OVERLAY_PHASES.slice().sort(),
    ["champ-select", "in-game", "loading", "lobby", "post-game"]
  );
});

test("stampOverlayPhase: overlay shell only, reports a change exactly once", () => {
  const doc = { body: { dataset: { shell: "overlay" } } };
  assert.strictEqual(stampOverlayPhase(doc, st("Lobby", {})), true);
  assert.strictEqual(doc.body.dataset.ovxPhase, "lobby");
  assert.strictEqual(stampOverlayPhase(doc, st("Lobby", {})), false);
  assert.strictEqual(stampOverlayPhase(doc, st("ChampSelect", {})), true);
  assert.strictEqual(doc.body.dataset.ovxPhase, "champ-select");
  // The 1920 dashboard is never stamped.
  const dash = { body: { dataset: {} } };
  assert.strictEqual(stampOverlayPhase(dash, st("Lobby", {})), false);
  assert.strictEqual(dash.body.dataset.ovxPhase, undefined);
  // A hostile document degrades to "no change", never a throw.
  assert.strictEqual(stampOverlayPhase(null, st("Lobby", {})), false);
  assert.strictEqual(stampOverlayPhase({ get body() { throw new Error("x"); } }, {}), false);
});
