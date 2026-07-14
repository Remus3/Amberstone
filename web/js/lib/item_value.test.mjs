// web/js/lib/item_value.test.mjs
//
// R117 F1 - team item-value differential. Pure-logic tests for the economy
// lens that sums each player's on-board item gold-worth (allPlayers[].items x
// ITEM_COSTS) and diffs ally-team vs enemy-team. No DOM / fetch, so a plain
// object stands in for the liveclient. Run with `node --test`. ASCII only.

import test from "node:test";
import assert from "node:assert";

import { teamItemValueDiff, _resolveMyTeam, _playerItemValue } from "./item_value.js";

// Fake ITEM_COSTS mirroring web/js/lib/items_index.js ITEM_COSTS shape.
const COSTS = {
  ready: true,
  byId: { "3031": 3400, "3006": 1100, "1055": 1200, "3020": 1100, "3340": 0 },
};

function lc(activeName, players) {
  return { activePlayer: { summonerName: activeName }, allPlayers: players };
}

test("_playerItemValue sums known costs, ignores unknown + zero", () => {
  const pl = { items: [{ itemID: 3031 }, { itemID: 1055 }, { itemID: 999999 }, { itemID: 3340 }] };
  // 3400 + 1200 + (unknown 0) + (trinket 0) = 4600
  assert.strictEqual(_playerItemValue(pl, COSTS), 4600);
});

test("_playerItemValue honors the itemId alias + string ids", () => {
  const pl = { items: [{ itemId: "3006" }, { itemID: "3020" }] };
  assert.strictEqual(_playerItemValue(pl, COSTS), 2200);
});

test("_playerItemValue fail-soft on junk", () => {
  assert.strictEqual(_playerItemValue(null, COSTS), 0);
  assert.strictEqual(_playerItemValue({ items: null }, COSTS), 0);
  assert.strictEqual(_playerItemValue({ items: [{}] }, COSTS), 0);
});

test("_resolveMyTeam matches by summonerName / riotIdGameName / name#tag", () => {
  const players = [
    { summonerName: "Me", team: "ORDER" },
    { summonerName: "Foe", team: "CHAOS" },
  ];
  assert.strictEqual(_resolveMyTeam(lc("Me", players)), "ORDER");
  // riotIdGameName + name#tag form
  const p2 = [{ riotIdGameName: "Trist", team: "CHAOS" }, { riotIdGameName: "X", team: "ORDER" }];
  assert.strictEqual(_resolveMyTeam({ activePlayer: { riotIdGameName: "Trist#NA1" }, allPlayers: p2 }), "CHAOS");
});

test("_resolveMyTeam null when unresolvable", () => {
  assert.strictEqual(_resolveMyTeam(null), null);
  assert.strictEqual(_resolveMyTeam({ activePlayer: {}, allPlayers: [] }), null);
  assert.strictEqual(_resolveMyTeam(lc("Ghost", [{ summonerName: "Other", team: "ORDER" }])), null);
});

test("teamItemValueDiff = ally value minus enemy value", () => {
  const players = [
    { summonerName: "Me", team: "ORDER", items: [{ itemID: 3031 }] },      // ally 3400
    { summonerName: "Ally2", team: "ORDER", items: [{ itemID: 3006 }] },   // ally 1100
    { summonerName: "Foe1", team: "CHAOS", items: [{ itemID: 1055 }] },    // enemy 1200
    { summonerName: "Foe2", team: "CHAOS", items: [{ itemID: 3020 }] },    // enemy 1100
  ];
  // ally 4500 - enemy 2300 = +2200
  assert.strictEqual(teamItemValueDiff(lc("Me", players), COSTS), 2200);
});

test("teamItemValueDiff negative when behind", () => {
  const players = [
    { summonerName: "Me", team: "ORDER", items: [{ itemID: 3006 }] },   // ally 1100
    { summonerName: "Foe", team: "CHAOS", items: [{ itemID: 3031 }] },  // enemy 3400
  ];
  assert.strictEqual(teamItemValueDiff(lc("Me", players), COSTS), -2300);
});

test("teamItemValueDiff null (bar hides) on missing inputs", () => {
  const players = [{ summonerName: "Me", team: "ORDER", items: [] }];
  assert.strictEqual(teamItemValueDiff(null, COSTS), null);                       // no lc
  assert.strictEqual(teamItemValueDiff(lc("Me", players), null), null);           // no costs
  assert.strictEqual(teamItemValueDiff(lc("Me", players), { ready: false, byId: {} }), null); // costs not ready
  assert.strictEqual(teamItemValueDiff(lc("Me", []), COSTS), null);               // empty roster
  assert.strictEqual(teamItemValueDiff(lc("Ghost", players), COSTS), null);       // team unresolvable
});
