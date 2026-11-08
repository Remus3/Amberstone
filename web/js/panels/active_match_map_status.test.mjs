// web/js/panels/active_match_map_status.test.mjs
//
// S144-U-220: the Active Match MAP pane's status line said
// "0 VISIBLE - 0 MIA - 0 DEAD" whenever /api/vision-state carried no enemy
// data. The server answers {} when no vision state exists
// (dashboard/routes_diag.py _serve_vision_state), and core/vision_tracker.py
// _compute_enemies returns no enemies (a summary of all zeros) until it
// resolves the active player's team. _amUpdateMapText read the missing counts
// as `| 0`, so a feed that knew nothing claimed a count: every enemy accounted
// for and none of them visible, missing or dead. A poll that failed before any
// answer left "loading vision..." up for the rest of the game.
//
// _amMapStatusText(vs) is the status line: the counts only when the tracker
// knows at least one enemy, "no enemy vision yet" (after the clock, when the
// feed has one) otherwise. _AM_MAP_FEED_FAILED is the line for a poll that
// failed with nothing cached.
//
// Shapes are core/vision_tracker.py VisionTracker.ingest's state() dict.
// ASCII only. Run with `node --test`.

import test from "node:test";
import assert from "node:assert";

import { __test as am } from "./active_match.js";

function vs(gameMode, counts, extra) {
  const [visible, missing, dead] = counts;
  return Object.assign({
    t_now: 0, game_time: 587, game_mode: gameMode, active_team: "ORDER",
    enemies: {},
    summary: {
      visible_count: visible, missing_count: missing, dead_count: dead,
      total: visible + missing + dead,
    },
  }, extra || {});
}

test("map status: the empty {} the server sends with no vision state is not a count", () => {
  const txt = am._amMapStatusText({});
  assert.strictEqual(txt, "no enemy vision yet");
  assert.ok(!/\d/.test(txt), txt);
});

test("map status: a non-object answer is not a count", () => {
  for (const bad of [null, undefined, "x", 3, []]) {
    assert.strictEqual(am._amMapStatusText(bad), "no enemy vision yet", String(bad));
  }
});

test("map status: a summary that is not an object is not a count", () => {
  assert.strictEqual(
    am._amMapStatusText({ game_time: 61, summary: "x" }),
    "1:01 - no enemy vision yet");
  assert.strictEqual(
    am._amMapStatusText({ game_time: 61, summary: [1, 2] }),
    "1:01 - no enemy vision yet");
});

test("map status: team not resolved yet (all-zero summary) keeps the clock, drops the counts", () => {
  assert.strictEqual(am._amMapStatusText(vs("CLASSIC", [0, 0, 0])),
    "9:47 - no enemy vision yet");
  assert.strictEqual(am._amMapStatusText(vs("KIWI", [0, 0, 0])),
    "9:47 - no enemy vision yet");
});

test("map status: SR with tracked enemies paints the three counts", () => {
  assert.strictEqual(am._amMapStatusText(vs("CLASSIC", [3, 1, 1])),
    "9:47 - 3 visible - 1 MIA - 1 dead");
});

test("map status: every enemy dead is still a count, not 'no vision'", () => {
  assert.strictEqual(am._amMapStatusText(vs("CLASSIC", [0, 0, 5])),
    "9:47 - 0 visible - 0 MIA - 5 dead");
  assert.strictEqual(am._amMapStatusText(vs("ARAM", [0, 0, 5])),
    "9:47 - 0 on bridge - 5 dead");
});

test("map status: shared-vision modes (ARAM, Mayhem KIWI) say 'on bridge'", () => {
  assert.strictEqual(am._amMapStatusText(vs("KIWI", [4, 0, 1])),
    "9:47 - 4 on bridge - 1 dead");
  assert.strictEqual(am._amMapStatusText(vs("aram", [5, 0, 0])),
    "9:47 - 5 on bridge - 0 dead");
});

test("map status: no game_time means no clock prefix", () => {
  const v = vs("CLASSIC", [2, 3, 0]);
  delete v.game_time;
  assert.strictEqual(am._amMapStatusText(v), "2 visible - 3 MIA - 0 dead");
});

test("map status: a summary without total counts its three parts", () => {
  const v = vs("CLASSIC", [0, 2, 0]);
  delete v.summary.total;
  assert.strictEqual(am._amMapStatusText(v), "9:47 - 0 visible - 2 MIA - 0 dead");
});

test("map status: the failed-poll line is fixed text and names no count", () => {
  assert.strictEqual(am._AM_MAP_FEED_FAILED, "vision feed did not load");
});

// S144-U-221: a stalled feed. core/vision_tracker.py stamps every state() it
// writes with t_now = time.time() (every 0.75 s), but when the Live Client
// relay goes stale it stops writing and data/vision_state.json keeps its last
// in-game state, which /api/vision-state keeps serving with a 200. A poll that
// fails with an answer cached kept the last line too. Either way the line
// claimed "4 on bridge - 1 dead" for the rest of the game. The pane now
// measures how long the feed has gone without a new t_now (client-side, so no
// clock skew between the box and the viewer) and past _AM_MAP_STALE_S says the
// feed stalled instead of repeating the counts.

test("map stale: the threshold matches the coach prompt's 10 s vision cut", () => {
  assert.strictEqual(am._AM_MAP_STALE_S, 10);
});

test("map stale: under the threshold the counts stand", () => {
  for (const s of [undefined, null, 0, 4.9, 9.99]) {
    assert.strictEqual(am._amMapStatusText(vs("KIWI", [4, 0, 1]), s),
      "9:47 - 4 on bridge - 1 dead", String(s));
  }
});

test("map stale: past the threshold the counts give way to the stall and its age", () => {
  assert.strictEqual(am._amMapStatusText(vs("KIWI", [4, 0, 1]), 10),
    "vision feed stalled at 9:47 - 10s ago");
  assert.strictEqual(am._amMapStatusText(vs("CLASSIC", [3, 1, 1]), 125.8),
    "vision feed stalled at 9:47 - 125s ago");
  const v = vs("CLASSIC", [3, 1, 1]);
  delete v.game_time;
  assert.strictEqual(am._amMapStatusText(v, 30), "vision feed stalled - 30s ago");
});

test("map stale: a non-number or non-finite age is not a stall", () => {
  for (const s of ["30", NaN, Infinity, -5, true, {}]) {
    assert.strictEqual(am._amMapStatusText(vs("CLASSIC", [3, 1, 1]), s),
      "9:47 - 3 visible - 1 MIA - 1 dead", String(s));
  }
});

test("map stale: a feed that knows no enemies keeps 'no enemy vision yet'", () => {
  assert.strictEqual(am._amMapStatusText({}, 60), "no enemy vision yet");
  assert.strictEqual(am._amMapStatusText(vs("CLASSIC", [0, 0, 0]), 60),
    "9:47 - no enemy vision yet");
});

test("map stale: the age runs from the last poll that brought a new t_now", () => {
  const tr = am._amMapFeedTrack();
  assert.strictEqual(am._amMapStaleS(tr, 1000), null, "no answer yet is not a stall");
  am._amMapNoteFeed(tr, { t_now: 100 }, 1000);
  assert.strictEqual(am._amMapStaleS(tr, 1000), 0);
  // The same file served again: no advance.
  am._amMapNoteFeed(tr, { t_now: 100 }, 6000);
  am._amMapNoteFeed(tr, { t_now: 100 }, 13000);
  assert.strictEqual(am._amMapStaleS(tr, 13000), 12);
  // A failed poll notes nothing; the age keeps running.
  assert.strictEqual(am._amMapStaleS(tr, 20000), 19);
  // The tracker writes again: fresh.
  am._amMapNoteFeed(tr, { t_now: 125.5 }, 21000);
  assert.strictEqual(am._amMapStaleS(tr, 21500), 0.5);
});

test("map stale: an answer without a numeric t_now counts as fresh on arrival", () => {
  const tr = am._amMapFeedTrack();
  am._amMapNoteFeed(tr, {}, 1000);
  am._amMapNoteFeed(tr, {}, 30000);
  assert.strictEqual(am._amMapStaleS(tr, 30000), 0);
  am._amMapNoteFeed(tr, { t_now: "7" }, 40000);
  assert.strictEqual(am._amMapStaleS(tr, 41000), 1);
  am._amMapNoteFeed(tr, null, 50000);
  assert.strictEqual(am._amMapStaleS(tr, 50000), 10, "a null answer is no answer");
});

test("map stale: a clock that steps back never yields a negative age", () => {
  const tr = am._amMapFeedTrack();
  am._amMapNoteFeed(tr, { t_now: 1 }, 50000);
  assert.strictEqual(am._amMapStaleS(tr, 40000), 0);
});

// S144-U-222: with the status line saying the feed stalled, the per-enemy
// roster still read the frozen answer as live: "on bridge" in green, "MIA 12s"
// and a "DEAD 18s" respawn countdown that never ticked, and in SR the gank
// band kept "WARN <name> missing 25s - ward / back off" up for the rest of the
// game. _amMapIsStale(staleS) is the one cut every layer reads;
// _amMapRosterState(e, stale) is a roster row's state and text, "no feed" in a
// neutral state while the feed is stalled.

test("map stale cut: _amMapIsStale is the status line's own threshold", () => {
  assert.strictEqual(am._amMapIsStale(10), true);
  assert.strictEqual(am._amMapIsStale(125.8), true);
  for (const s of [undefined, null, 0, 9.99, "30", NaN, Infinity, -5, true, {}]) {
    assert.strictEqual(am._amMapIsStale(s), false, String(s));
  }
});

test("map roster: a fresh feed keeps each row's live state and text", () => {
  assert.deepStrictEqual(
    am._amMapRosterState({ is_dead: true, respawn_in_s: 17.2 }, false),
    { state: "dead", text: "DEAD 18s" });
  assert.deepStrictEqual(
    am._amMapRosterState({ is_dead: true }, false),
    { state: "dead", text: "DEAD" });
  assert.deepStrictEqual(
    am._amMapRosterState({ visible: true, last_seen_zone: "on_bridge" }, false),
    { state: "ok", text: "on bridge" });
  assert.deepStrictEqual(
    am._amMapRosterState({ visible: true }, false),
    { state: "ok", text: "visible" });
  assert.deepStrictEqual(
    am._amMapRosterState({ visible: false, missing_for_s: 12.4 }, false),
    { state: "mia", text: "MIA 12s" });
  assert.deepStrictEqual(
    am._amMapRosterState({ visible: false }, false),
    { state: "mia", text: "MIA" });
});

test("map roster: a stalled feed claims no live state on any row", () => {
  for (const e of [
    { is_dead: true, respawn_in_s: 17.2 },
    { visible: true, last_seen_zone: "on_bridge" },
    { visible: false, missing_for_s: 25 },
    {},
  ]) {
    assert.deepStrictEqual(am._amMapRosterState(e, true),
      { state: "stale", text: "no feed" }, JSON.stringify(e));
  }
});

// S144-U-224: a poll request is given up on after _AM_MAP_FETCH_TIMEOUT_MS.
// Longer than a tick (a slow answer is not cut off by the next tick) and
// under the stale cut (a hang before the first answer says "did not load"
// before a live feed could read as stalled).
test("map poll: the request timeout sits between one tick and the stale cut", () => {
  const ms = am._AM_MAP_FETCH_TIMEOUT_MS;
  assert.strictEqual(typeof ms, "number");
  assert.ok(ms > 500, ms);
  assert.ok(ms < am._AM_MAP_STALE_S * 1000, ms);
});
