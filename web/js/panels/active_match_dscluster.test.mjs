// web/js/panels/active_match_dscluster.test.mjs
//
// C-17 regression: the relocated DS combat-analysis cluster on the Active
// Match surface never rendered, in mock OR in a live game. Run with
// `node --test`.
//
// Root cause: _amDsSyntheticCs resolved the operator's champion with
// `parseInt(_resolveChampId(slug), 10)`. _resolveChampId (web/js/lib/
// items_index.js) returns the CANONICAL DDRAGON SLUG ("Jinx"), never the
// numeric key - so parseInt() produced NaN, myId fell to 0, the synthetic
// champ-select state came back null, and _amRenderDsCluster hid all seven
// cards and returned. The identical defect sat on the enemy loop, so
// their_team was always empty too.
//
// The correct resolver already existed in the same file as the memoized
// _SPK_NAME_TO_KEY map (built from CHAMPS.byId, which is
// {numericKeyString -> Slug}). These tests pin the extracted shared helper
// _champNumericKey and the synthetic-cs consumer that was dead because of it.
//
// CHAMPS is an exported mutable singleton, so the tests seed it directly -
// no fetch, no DOM. ASCII only.

import test from "node:test";
import assert from "node:assert";

import { CHAMPS } from "../lib/items_index.js";
import { __test } from "./active_match.js";

const { _champNumericKey, _amDsSyntheticCs } = __test;

// Real rows out of /data/champions_index.json byId ({numericKeyString -> Slug}).
// Lee Sin / Kha'Zix / Cho'Gath exist here specifically to pin the
// lowercase + strip-non-alphanumeric normalization.
const BY_ID = {
  "222": "Jinx",
  "64": "LeeSin",
  "121": "Khazix",
  "31": "Chogath",
  "412": "Thresh",
  "157": "Yasuo",
  "84": "Akali",
};

function seedChamps(version) {
  CHAMPS.byId = { ...BY_ID };
  CHAMPS.byName = {};
  for (const slug of Object.values(BY_ID)) {
    CHAMPS.byName[String(slug).toLowerCase().replace(/[^a-z0-9]/g, "")] = slug;
  }
  CHAMPS.version = version || "16.14.1";
  CHAMPS.ready = true;
}

test("_champNumericKey: slug 'Jinx' resolves to numeric 222 given a byId index", () => {
  seedChamps();
  const key = _champNumericKey("Jinx");
  assert.strictEqual(key, 222);
  assert.strictEqual(typeof key, "number");
});

test("_champNumericKey: normalizes spaces / apostrophes / case", () => {
  seedChamps();
  assert.strictEqual(_champNumericKey("LeeSin"), 64);
  assert.strictEqual(_champNumericKey("Lee Sin"), 64);
  assert.strictEqual(_champNumericKey("lee sin"), 64);
  assert.strictEqual(_champNumericKey("Kha'Zix"), 121);
  assert.strictEqual(_champNumericKey("KhaZix"), 121);
  assert.strictEqual(_champNumericKey("Cho'Gath"), 31);
});

test("_champNumericKey: unknown / empty / nullish resolve to 0", () => {
  seedChamps();
  assert.strictEqual(_champNumericKey("NotAChampion"), 0);
  assert.strictEqual(_champNumericKey(""), 0);
  assert.strictEqual(_champNumericKey(null), 0);
  assert.strictEqual(_champNumericKey(undefined), 0);
});

test("_champNumericKey: returns 0 when the CHAMPS index has not loaded", () => {
  CHAMPS.byId = {};
  CHAMPS.byName = {};
  CHAMPS.version = "empty-index";
  assert.strictEqual(_champNumericKey("Jinx"), 0);
  seedChamps();
});

test("_champNumericKey: memo rebuilds when CHAMPS.version changes", () => {
  seedChamps("16.14.1");
  assert.strictEqual(_champNumericKey("Jinx"), 222);
  // New patch, different roster: the memo must not serve the stale map.
  CHAMPS.byId = { "999": "Newchamp" };
  CHAMPS.version = "16.15.1";
  assert.strictEqual(_champNumericKey("Newchamp"), 999);
  assert.strictEqual(_champNumericKey("Jinx"), 0);
  seedChamps("16.14.1");
});

// --- the consumer that was dead -------------------------------------------

function liveClient() {
  return {
    activePlayer: { riotIdGameName: "SamplePlayer#Trist" },
    allPlayers: [
      { riotIdGameName: "SamplePlayer#Trist", team: "ORDER", championName: "Jinx", rawChampionName: "Jinx" },
      { riotIdGameName: "Ally2", team: "ORDER", championName: "Thresh", rawChampionName: "Thresh" },
      { riotIdGameName: "Enemy1", team: "CHAOS", championName: "Kha'Zix", rawChampionName: "Khazix" },
      { riotIdGameName: "Enemy2", team: "CHAOS", championName: "Lee Sin", rawChampionName: "LeeSin" },
      { riotIdGameName: "Enemy3", team: "CHAOS", championName: "Yasuo", rawChampionName: "Yasuo" },
    ],
    players: [
      { is_active: true, position: "BOTTOM" },
      { is_active: false, position: "UTILITY" },
      { is_active: false, position: "JUNGLE" },
      { is_active: false, position: "JUNGLE" },
      { is_active: false, position: "MIDDLE" },
    ],
    owned_item_ids: [3006, 6672],
  };
}

test("_amDsSyntheticCs: live Jinx yields my_champion 222, not 0/null", () => {
  seedChamps();
  const cs = _amDsSyntheticCs({ champion: "Jinx" }, { mode: "sr", liveclient: liveClient() });
  assert.ok(cs, "synthetic cs must not be null for a resolvable live champion");
  assert.strictEqual(cs.my_champion, 222);
  assert.strictEqual(cs.queue_id, 420);
  assert.strictEqual(cs.my_position, "BOTTOM");
});

test("_amDsSyntheticCs: every enemy resolves to a numeric championId", () => {
  seedChamps();
  const cs = _amDsSyntheticCs({ champion: "Jinx" }, { mode: "sr", liveclient: liveClient() });
  assert.ok(cs);
  assert.strictEqual(cs.their_team.length, 3, "all three enemies present");
  assert.deepStrictEqual(
    cs.their_team.map((e) => e.championId).sort((a, b) => a - b),
    [64, 121, 157],
  );
  for (const e of cs.their_team) {
    assert.strictEqual(typeof e.championId, "number");
    assert.ok(e.championId > 0, "no enemy may collapse to 0");
  }
});

test("_amDsSyntheticCs: aram / arena map to their representative queue ids", () => {
  seedChamps();
  const aram = _amDsSyntheticCs({ champion: "Jinx" }, { mode: "aram", liveclient: liveClient() });
  assert.strictEqual(aram.queue_id, 450);
  const arena = _amDsSyntheticCs({ champion: "Jinx" }, { mode: "arena", liveclient: liveClient() });
  assert.strictEqual(arena.queue_id, 1750);
});

test("_amDsSyntheticCs: unresolvable / missing champion still returns null", () => {
  seedChamps();
  assert.strictEqual(_amDsSyntheticCs({ champion: "" }, { mode: "sr" }), null);
  assert.strictEqual(_amDsSyntheticCs({ champion: "NotAChampion" }, { mode: "sr" }), null);
  assert.strictEqual(_amDsSyntheticCs(null, { mode: "sr" }), null);
});
