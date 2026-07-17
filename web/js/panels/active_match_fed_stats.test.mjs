// web/js/panels/active_match_fed_stats.test.mjs
//
// C3 fed-enemy counter-hint frontend slice (2026-07-17). Run with `node --test`.
//
// The in-game BUILD module now folds each enemy's live scoreboard row (kills /
// deaths / assists) and level out of the allPlayers roster and sends them,
// index-aligned with the enemy champion NAME list, to /api/build-plan so the
// backend fed estimator (core/build_planner/fed_threat.assess_fed_threat) can
// light the C3 fed counter-hint chip. These pin the pure, exported helpers so:
//   - enemy scores / levels stay index-aligned with _extractBpEnemies' names
//     (same enemy filter: my-team excluded, nameless skipped), which the route
//     reads by index;
//   - the POST body carries enemy_scores (list of {kills,deaths,assists} dicts)
//     + enemy_levels (list of ints) in the shape the route coercers accept
//     (_coerce_enemy_scores / _coerce_enemy_levels);
//   - with NO live scoreboard (champ-select) the body OMITS both keys, so it is
//     byte-identical to the pre-C3 body and the chip stays dark;
//   - an enemy SNOWBALLING (a kill / death / level tick) changes the build-plan
//     cache key so the fetch re-fires with the fresher lead.
//
// Pure helpers only (no DOM / no fetch) - mirrors active_match_counter_items's style.

import test from "node:test";
import assert from "node:assert";

import {
  _extractBpEnemies,
  _extractBpEnemyStats,
  _bpEnemyStatsKey,
  _buildPlanPostBody,
} from "./active_match.js";

// A live allPlayers roster: my team is ORDER (excluded); the two CHAOS players
// are the enemies whose scoreboard rows + levels we forward. scores carries the
// public per-player kills/deaths/assists; level is the champion level.
const ALL_PLAYERS = [
  { team: "ORDER", championName: "Ashe",  level: 11, scores: { kills: 2, deaths: 3, assists: 8 } },
  { team: "CHAOS", championName: "Garen", level: 14, scores: { kills: 9, deaths: 2, assists: 3 } },
  { team: "ORDER", championName: "Lulu",  level: 10, scores: { kills: 0, deaths: 5, assists: 12 } },
  { team: "CHAOS", championName: "Lux",   level: 12, scores: { kills: 4, deaths: 4, assists: 6 } },
];

// True when x is a plain scoreboard row the _coerce_enemy_scores dict-list +
// fed_threat._as_int path accept: an object with integer kills/deaths/assists.
function isScoreRow(x) {
  return x && typeof x === "object" && !Array.isArray(x)
    && Number.isInteger(x.kills) && Number.isInteger(x.deaths) && Number.isInteger(x.assists);
}

test("_extractBpEnemyStats: enemy scores + levels only, my team excluded, aligned with _extractBpEnemies names", () => {
  const { names } = _extractBpEnemies(ALL_PLAYERS, "ORDER");
  const { scores, levels } = _extractBpEnemyStats(ALL_PLAYERS, "ORDER");
  assert.deepStrictEqual(names, ["Garen", "Lux"], "only the two CHAOS enemies");
  assert.strictEqual(scores.length, names.length, "scores index-aligned with names");
  assert.strictEqual(levels.length, names.length, "levels index-aligned with names");
  assert.deepStrictEqual(scores[0], { kills: 9, deaths: 2, assists: 3 }, "Garen row (names[0])");
  assert.deepStrictEqual(scores[1], { kills: 4, deaths: 4, assists: 6 }, "Lux row (names[1])");
  assert.deepStrictEqual(levels, [14, 12], "levels index-aligned");
  assert.ok(scores.every(isScoreRow), "every row is the coercer-accepted int dict shape");
});

test("_extractBpEnemyStats: a nameless player is dropped (stays aligned with _extractBpEnemies)", () => {
  const roster = [
    { team: "CHAOS", championName: "", level: 9, scores: { kills: 5, deaths: 0, assists: 1 } }, // no name -> skipped
    { team: "CHAOS", championName: "Lux", level: 12, scores: { kills: 4, deaths: 4, assists: 6 } },
  ];
  const { names } = _extractBpEnemies(roster, "ORDER");
  const { scores, levels } = _extractBpEnemyStats(roster, "ORDER");
  assert.deepStrictEqual(names, ["Lux"]);
  assert.strictEqual(scores.length, names.length);
  assert.strictEqual(levels.length, names.length);
  assert.deepStrictEqual(scores, [{ kills: 4, deaths: 4, assists: 6 }]);
  assert.deepStrictEqual(levels, [12]);
});

test("_extractBpEnemyStats: missing scores / junk level coerce to 0 (never fires a wrong chip)", () => {
  const roster = [
    { team: "CHAOS", championName: "Teemo" }, // no scores, no level
    { team: "CHAOS", championName: "Jinx", level: "oops", scores: { kills: "x", deaths: null } },
  ];
  const { scores, levels } = _extractBpEnemyStats(roster, "ORDER");
  assert.deepStrictEqual(scores, [
    { kills: 0, deaths: 0, assists: 0 },
    { kills: 0, deaths: 0, assists: 0 },
  ]);
  assert.deepStrictEqual(levels, [0, 0]);
});

test("_extractBpEnemyStats: no myTeam -> every valid player is an enemy (parity with _extractBpEnemies)", () => {
  const { scores, levels } = _extractBpEnemyStats(ALL_PLAYERS, null);
  assert.strictEqual(scores.length, 4);
  assert.deepStrictEqual(levels, [11, 14, 10, 12]);
});

test("_extractBpEnemyStats: non-array roster is fail-soft (no throw, empty aligned lists)", () => {
  assert.doesNotThrow(() => _extractBpEnemyStats(null, "ORDER"));
  assert.deepStrictEqual(_extractBpEnemyStats(null, "ORDER"), { scores: [], levels: [] });
  assert.deepStrictEqual(_extractBpEnemyStats("nope", "ORDER"), { scores: [], levels: [] });
  assert.deepStrictEqual(_extractBpEnemyStats(undefined, null), { scores: [], levels: [] });
});

// The pre-C3 body shape - the byte-identical baseline every no-scoreboard POST
// must still produce (champion/mode/level/items/enemies/enemy_items/ally_items).
const PRE_C3_BODY = {
  champion: "Ashe",
  mode: "SR",
  level: 11,
  items: ["3153"],
  enemies: ["Garen"],
  enemy_items: [["3068"]],
  ally_items: ["3153"],
};

test("_buildPlanPostBody: a live scoreboard carries enemy_scores + enemy_levels in the coercer shape", () => {
  const scores = [{ kills: 9, deaths: 2, assists: 3 }];
  const levels = [14];
  const body = _buildPlanPostBody(
    "Ashe", "SR", 11, ["3153"], ["Garen"], [["3068"]], ["3153"], scores, levels);
  assert.ok(Array.isArray(body.enemy_scores), "enemy_scores is a list");
  assert.deepStrictEqual(body.enemy_scores, scores, "rows passed through");
  assert.ok(body.enemy_scores.every(isScoreRow), "each row is the _coerce_enemy_scores dict shape");
  assert.ok(Array.isArray(body.enemy_levels), "enemy_levels is a list");
  assert.deepStrictEqual(body.enemy_levels, [14]);
  assert.ok(body.enemy_levels.every(Number.isInteger), "each level is the _coerce_enemy_levels int shape");
  // Index-aligned with enemies (the route reads enemy_scores[i] for enemies[i]).
  assert.strictEqual(body.enemy_scores.length, body.enemies.length);
  assert.strictEqual(body.enemy_levels.length, body.enemies.length);
});

test("_buildPlanPostBody: no scoreboard (empty arrays) OMITS the C3 keys - byte-identical to pre-C3", () => {
  const body = _buildPlanPostBody(
    "Ashe", "SR", 11, ["3153"], ["Garen"], [["3068"]], ["3153"], [], []);
  assert.ok(!("enemy_scores" in body), "enemy_scores omitted");
  assert.ok(!("enemy_levels" in body), "enemy_levels omitted");
  assert.deepStrictEqual(body, PRE_C3_BODY, "byte-identical to the pre-C3 body");
});

test("_buildPlanPostBody: champ-select (no stats args at all) OMITS the C3 keys - byte-identical to pre-C3", () => {
  const body = _buildPlanPostBody(
    "Ashe", "SR", 11, ["3153"], ["Garen"], [["3068"]], ["3153"]);
  assert.ok(!("enemy_scores" in body));
  assert.ok(!("enemy_levels" in body));
  assert.deepStrictEqual(body, PRE_C3_BODY);
});

test("_bpEnemyStatsKey: identical scoreboard leads produce the SAME fingerprint", () => {
  const s = [{ kills: 9, deaths: 2, assists: 3 }, { kills: 4, deaths: 4, assists: 6 }];
  const l = [14, 12];
  assert.strictEqual(
    _bpEnemyStatsKey(s, l),
    _bpEnemyStatsKey([{ kills: 9, deaths: 2 }, { kills: 4, deaths: 4 }], [14, 12]),
  );
});

test("_bpEnemyStatsKey: a kill / death / level tick changes the fingerprint (cache re-fires)", () => {
  const base = _bpEnemyStatsKey([{ kills: 9, deaths: 2 }], [14]);
  assert.notStrictEqual(base, _bpEnemyStatsKey([{ kills: 10, deaths: 2 }], [14]), "a kill re-fires");
  assert.notStrictEqual(base, _bpEnemyStatsKey([{ kills: 9, deaths: 3 }], [14]), "a death re-fires");
  assert.notStrictEqual(base, _bpEnemyStatsKey([{ kills: 9, deaths: 2 }], [15]), "a level re-fires");
});

test("_bpEnemyStatsKey: non-array input is fail-soft (no throw)", () => {
  assert.doesNotThrow(() => _bpEnemyStatsKey(null, null));
  assert.strictEqual(_bpEnemyStatsKey(null, null), "");
  assert.strictEqual(_bpEnemyStatsKey(undefined, undefined), "");
  assert.strictEqual(_bpEnemyStatsKey("nope", "nope"), "");
});
