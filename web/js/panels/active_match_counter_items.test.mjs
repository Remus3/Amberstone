// web/js/panels/active_match_counter_items.test.mjs
//
// R103 counter-build frontend slice (2026-07-13). Run with `node --test`.
//
// The in-game BUILD module now folds each enemy's OWNED items out of the live
// allPlayers roster and sends them, index-aligned with the enemy champion NAME
// list, to /api/build-plan so the backend can compute situational counter-build
// hints (C4/C5). These pin the two pure, exported helpers that do the extract +
// the staleness fingerprint so:
//   - the enemy NAMES and enemy ITEMS stay index-aligned (names[i] <-> items[i])
//     and my-team players are excluded (the counter-profile is enemy-only).
//   - an enemy PURCHASE (a new item id appended to any enemy's list) changes the
//     build-plan cache key so the fetch re-fires with the fresher roster.
//
// Pure helpers only (no DOM / no fetch) - mirrors active_match_buildrows's style.

import test from "node:test";
import assert from "node:assert";

import {
  _extractBpEnemies,
  _extractBpAllyItems,
  _bpEnemyItemsKey,
} from "./active_match.js";

// A live allPlayers roster: my team is ORDER (excluded); the two CHAOS players
// are the enemies whose names + owned item ids we forward. Item ids arrive as
// objects carrying itemID (or the itemId alias), sometimes numeric.
const ALL_PLAYERS = [
  { team: "ORDER", championName: "Ashe",  items: [{ itemID: "3153" }] },
  { team: "CHAOS", championName: "Garen", items: [{ itemID: "3068" }, { itemID: "3075" }] },
  { team: "ORDER", championName: "Lulu",  items: [{ itemID: "3222" }] },
  { team: "CHAOS", championName: "Lux",   items: [{ itemID: "3135" }, { itemID: 3157 }] },
];

test("_extractBpEnemies: only enemy names, item ids index-aligned as strings, my team excluded", () => {
  const { names, items } = _extractBpEnemies(ALL_PLAYERS, "ORDER");
  assert.deepStrictEqual(names, ["Garen", "Lux"], "only the two CHAOS enemies");
  assert.strictEqual(items.length, names.length, "items index-aligned with names");
  assert.deepStrictEqual(items[0], ["3068", "3075"], "Garen owned ids (names[0])");
  // 3157 arrived numeric - proves String() coercion.
  assert.deepStrictEqual(items[1], ["3135", "3157"], "Lux owned ids incl coerced numeric");
});

test("_extractBpEnemies: itemId alias field is honored", () => {
  const roster = [
    { team: "CHAOS", championName: "Jinx", items: [{ itemId: "3031" }, { itemId: "3094" }] },
  ];
  const { names, items } = _extractBpEnemies(roster, "ORDER");
  assert.deepStrictEqual(names, ["Jinx"]);
  assert.deepStrictEqual(items[0], ["3031", "3094"]);
});

test("_extractBpEnemies: an enemy with no items yields an empty inner list (still aligned)", () => {
  const roster = [
    { team: "CHAOS", championName: "Garen", items: [{ itemID: "3068" }] },
    { team: "CHAOS", championName: "Teemo" }, // no items field
  ];
  const { names, items } = _extractBpEnemies(roster, "ORDER");
  assert.deepStrictEqual(names, ["Garen", "Teemo"]);
  assert.strictEqual(items.length, 2, "index count matches names");
  assert.deepStrictEqual(items[0], ["3068"]);
  assert.deepStrictEqual(items[1], [], "no items -> empty inner list, still aligned");
});

test("_extractBpEnemies: a nameless player is dropped from BOTH lists (indices stay aligned)", () => {
  const roster = [
    { team: "CHAOS", championName: "", items: [{ itemID: "9999" }] }, // no name -> skipped
    { team: "CHAOS", championName: "Lux", items: [{ itemID: "3135" }] },
  ];
  const { names, items } = _extractBpEnemies(roster, "ORDER");
  assert.deepStrictEqual(names, ["Lux"]);
  assert.deepStrictEqual(items, [["3135"]]);
});

test("_extractBpEnemies: no myTeam -> every valid player is an enemy", () => {
  const { names } = _extractBpEnemies(ALL_PLAYERS, null);
  assert.deepStrictEqual(names, ["Ashe", "Garen", "Lulu", "Lux"]);
});

test("_extractBpEnemies: non-array roster is fail-soft (no throw, empty aligned lists)", () => {
  assert.doesNotThrow(() => _extractBpEnemies(null, "ORDER"));
  assert.deepStrictEqual(_extractBpEnemies(null, "ORDER"), { names: [], items: [] });
  assert.deepStrictEqual(_extractBpEnemies("nope", "ORDER"), { names: [], items: [] });
  assert.deepStrictEqual(_extractBpEnemies(undefined, null), { names: [], items: [] });
});

test("_bpEnemyItemsKey: identical enemy items produce the SAME fingerprint", () => {
  const a = [["3068", "3075"], ["3135"]];
  const b = [["3068", "3075"], ["3135"]];
  assert.strictEqual(_bpEnemyItemsKey(a), _bpEnemyItemsKey(b));
});

test("_bpEnemyItemsKey: an enemy PURCHASE changes the fingerprint (cache re-fires)", () => {
  const before = [["3068", "3075"], ["3135"]];
  const after  = [["3068", "3075"], ["3135", "3157"]]; // Lux bought 3157
  assert.notStrictEqual(
    _bpEnemyItemsKey(before),
    _bpEnemyItemsKey(after),
    "a new enemy item must invalidate the build-plan cache key",
  );
});

test("_bpEnemyItemsKey: non-array input is fail-soft (no throw)", () => {
  assert.doesNotThrow(() => _bpEnemyItemsKey(null));
  assert.strictEqual(_bpEnemyItemsKey(null), "");
  assert.strictEqual(_bpEnemyItemsKey(undefined), "");
  assert.strictEqual(_bpEnemyItemsKey("nope"), "");
});

// C2 antiheal (2026-07-16): the my-team owned-items extractor. A flat list of
// ally item ids feeds the backend AllyState.has_antiheal de-dup (an ally
// Grievous item suppresses the antiheal chip). Enemies are excluded.
test("_extractBpAllyItems: only my-team item ids, flat, enemies excluded", () => {
  // ORDER = Ashe (3153) + Lulu (3222); the two CHAOS players are excluded.
  assert.deepStrictEqual(_extractBpAllyItems(ALL_PLAYERS, "ORDER"), ["3153", "3222"]);
});

test("_extractBpAllyItems: itemId alias + numeric coercion", () => {
  const roster = [
    { team: "ORDER", championName: "Lulu", items: [{ itemId: "3075" }, { itemID: 3222 }] },
    { team: "CHAOS", championName: "Soraka", items: [{ itemID: "3072" }] },
  ];
  assert.deepStrictEqual(_extractBpAllyItems(roster, "ORDER"), ["3075", "3222"]);
});

test("_extractBpAllyItems: fail-soft on non-array roster / missing myTeam", () => {
  assert.doesNotThrow(() => _extractBpAllyItems(null, "ORDER"));
  assert.deepStrictEqual(_extractBpAllyItems(null, "ORDER"), []);
  assert.deepStrictEqual(_extractBpAllyItems(ALL_PLAYERS, null), []);
});
