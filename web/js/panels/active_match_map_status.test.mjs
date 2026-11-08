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
