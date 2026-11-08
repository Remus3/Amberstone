// web/js/panels/active_match_unresolved_team_roster.test.mjs
//
// S144-U-219: the Active Match DS matchup roster (_amDsSyntheticCs
// their_team) and the capability-gap chip's enemy names (_amCapgapEnemyNames)
// never count the operator's own side as enemies. Run with `node --test`.
//
// Both sites filtered with `if (myTeam && pl.team === myTeam) continue;`.
// _resolveMyTeam returns null when no allPlayers row carries the activePlayer
// name, so that guard passed EVERY player: the matchup card took the first
// five rows (the operator's own team, the operator included) and, with the
// operator's role still known from liveclient.players is_active, headlined
// the operator's own champion as the lane opponent; the capability gap was
// asked about all ten champions. S144-U-218 fixed the same fail-open on the
// THREATS strip. Now both rosters are the players on a KNOWN team other
// than the active player's, and EMPTY when that team is unresolved (the
// matchup card and the chip hide, rather than show a wrong roster).
//
// CHAMPS is an exported mutable singleton, so the tests seed it directly.
// Synthetic names only. ASCII only.

import test from "node:test";
import assert from "node:assert";

import { CHAMPS } from "../lib/items_index.js";
import { __test } from "./active_match.js";

const { _amDsSyntheticCs, _amCapgapEnemyNames } = __test;

const BY_ID = {
  "222": "Jinx",
  "412": "Thresh",
  "24": "Jax",
  "17": "Teemo",
  "60": "Elise",
  "145": "Kaisa",
};

function seedChamps() {
  CHAMPS.byId = { ...BY_ID };
  CHAMPS.byName = {};
  for (const slug of Object.values(BY_ID)) {
    CHAMPS.byName[String(slug).toLowerCase().replace(/[^a-z0-9]/g, "")] = slug;
  }
  CHAMPS.version = "s144u219-test";
  CHAMPS.ready = true;
}

// SR-shaped: ORDER listed first, the operator's row inside it, the summary
// roster index-aligned with is_active on the operator's row.
function liveClient(activeName) {
  return {
    activePlayer: { summonerName: activeName, riotIdGameName: activeName },
    allPlayers: [
      { summonerName: "TopUnit", team: "ORDER", championName: "Jax", rawChampionName: "Jax" },
      { summonerName: "SamplePlayer", team: "ORDER", championName: "Jinx", rawChampionName: "Jinx" },
      { summonerName: "HookUnit", team: "ORDER", championName: "Thresh", rawChampionName: "Thresh" },
      { summonerName: "BlindPick", team: "CHAOS", championName: "Teemo", rawChampionName: "Teemo" },
      { summonerName: "SpiderUnit", team: "CHAOS", championName: "Elise", rawChampionName: "Elise" },
      { summonerName: "BotUnit", team: "CHAOS", championName: "Kai'Sa", rawChampionName: "Kaisa" },
    ],
    players: [
      { position: "TOP", team: "ORDER", is_active: false },
      { position: "BOTTOM", team: "ORDER", is_active: true },
      { position: "UTILITY", team: "ORDER", is_active: false },
      { position: "TOP", team: "CHAOS", is_active: false },
      { position: "JUNGLE", team: "CHAOS", is_active: false },
      { position: "BOTTOM", team: "CHAOS", is_active: false },
    ],
  };
}

const RESOLVED = "SamplePlayer";
const UNMATCHED = "NotInThisLobby";

test("_amDsSyntheticCs: resolved team -> their_team is the three CHAOS champions", () => {
  seedChamps();
  const cs = _amDsSyntheticCs({ champion: "Jinx" }, { mode: "sr", liveclient: liveClient(RESOLVED) });
  assert.ok(cs);
  assert.deepStrictEqual(cs.their_team.map((e) => e.championId), [17, 60, 145]);
  assert.deepStrictEqual(cs.their_team.map((e) => e.assignedPosition), ["TOP", "JUNGLE", "BOTTOM"]);
  assert.strictEqual(cs.my_position, "BOTTOM");
});

test("_amDsSyntheticCs: unresolved team -> their_team is EMPTY, never the operator's side", () => {
  seedChamps();
  const cs = _amDsSyntheticCs({ champion: "Jinx" }, { mode: "sr", liveclient: liveClient(UNMATCHED) });
  assert.ok(cs, "the operator's own champion still resolves, so the cluster still renders");
  assert.strictEqual(cs.my_champion, 222);
  const ids = cs.their_team.map((e) => e.championId);
  assert.ok(!ids.includes(222), "the operator's own Jinx is never an enemy: " + JSON.stringify(ids));
  assert.ok(!ids.includes(24) && !ids.includes(412), "no ally is an enemy: " + JSON.stringify(ids));
  assert.deepStrictEqual(cs.their_team, []);
});

test("_amDsSyntheticCs: a teamless row is not an enemy when the team resolves", () => {
  seedChamps();
  const lc = liveClient(RESOLVED);
  delete lc.allPlayers[4].team;
  const cs = _amDsSyntheticCs({ champion: "Jinx" }, { mode: "sr", liveclient: lc });
  assert.deepStrictEqual(cs.their_team.map((e) => e.championId), [17, 145]);
});

test("_amDsSyntheticCs: the operator's row without a team leaves the roster empty", () => {
  seedChamps();
  const lc = liveClient(RESOLVED);
  delete lc.allPlayers[1].team;
  const cs = _amDsSyntheticCs({ champion: "Jinx" }, { mode: "sr", liveclient: lc });
  assert.deepStrictEqual(cs.their_team, []);
});

test("_amCapgapEnemyNames: resolved team -> the three CHAOS champion names", () => {
  assert.deepStrictEqual(_amCapgapEnemyNames(liveClient(RESOLVED)), ["Teemo", "Elise", "Kai'Sa"]);
});

test("_amCapgapEnemyNames: unresolved team -> [] (the chip hides)", () => {
  assert.deepStrictEqual(_amCapgapEnemyNames(liveClient(UNMATCHED)), []);
});

test("_amCapgapEnemyNames: championName first, rawChampionName fallback, blanks dropped", () => {
  const lc = liveClient(RESOLVED);
  lc.allPlayers[3].championName = "";
  lc.allPlayers[4].championName = "";
  lc.allPlayers[4].rawChampionName = "";
  assert.deepStrictEqual(_amCapgapEnemyNames(lc), ["Teemo", "Kai'Sa"]);
});

test("_amCapgapEnemyNames: no liveclient / no roster -> []", () => {
  assert.deepStrictEqual(_amCapgapEnemyNames(null), []);
  assert.deepStrictEqual(_amCapgapEnemyNames({}), []);
  assert.deepStrictEqual(_amCapgapEnemyNames({ allPlayers: "x" }), []);
});
