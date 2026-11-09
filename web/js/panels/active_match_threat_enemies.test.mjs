// web/js/panels/active_match_threat_enemies.test.mjs
//
// S144-U-218: the in-game THREATS strip listed the operator's own champion and
// their teammates as threats whenever the active player's team could not be
// resolved (docs/qa/UI_UX_QUEUE_2026-07-21.md, In-game overlay: "DS panel
// THREATS row renders 5 (SR) / 12 (Arena) EMPTY placeholder circles"; the 12 is
// every player in a 12-player Arena lobby, the operator and the duo included).
//
// Root cause: _renderAmBuildBody filtered the roster with
//   pl.team && pl.team !== myTeam
// and _resolveMyTeam returns null when no allPlayers row matches the
// activePlayer name (or the matched row has no team). Every non-blank team is
// "!== null", so an unresolved team turned the whole lobby into threats.
// S144-U-217 fixed the empty circles (the localization-key champion name); this
// fixes the count. Why the name did not match in that Arena capture is the
// live-gated half (docs/LIVE_GAME_GATED_SYNC.md G5-11 owns the Arena team
// layout) and is not claimed here.
//
// _amThreatEnemies(lc) is the strip's roster: players on a known team other
// than mine, and NONE when my team is unknown, because then nobody on the
// roster can be told apart from the operator.
//
// Rosters are the ui_mock fixtures' own shapes (web/data/ui_mock/), synthetic
// names only. ASCII only. Run with `node --test`.

import test from "node:test";
import assert from "node:assert";
import { readFileSync } from "node:fs";

import { __test as am } from "./active_match.js";

function fixtureLc(name) {
  const url = new URL(`../../data/ui_mock/${name}`, import.meta.url);
  return JSON.parse(readFileSync(url, "utf8")).liveclient;
}

function champs(list) {
  return list.map((pl) => pl.championName);
}

test("threat enemies: Arena 12-player lobby lists the 10 players off my subteam", () => {
  const lc = fixtureLc("active_match_arena.json");
  assert.strictEqual(lc.allPlayers.length, 12);
  const out = am._amThreatEnemies(lc);
  assert.strictEqual(out.length, 10);
  // Me (Jinx) and my duo (Karma) are never threats.
  assert.ok(!champs(out).includes("Jinx"), champs(out));
  assert.ok(!champs(out).includes("Karma"), champs(out));
  assert.ok(out.every((pl) => pl.team !== "100"));
});

test("threat enemies: SR fixture lists the five enemies only", () => {
  const lc = fixtureLc("active_match_sr.json");
  const myTeam = am._resolveMyTeam(lc);
  assert.ok(myTeam, "SR fixture resolves my team");
  const out = am._amThreatEnemies(lc);
  assert.strictEqual(out.length, 5);
  assert.ok(out.every((pl) => pl.team && pl.team !== myTeam));
});

test("threat enemies: an activePlayer name no roster row carries -> no threats, not the whole lobby", () => {
  const lc = fixtureLc("active_match_arena.json");
  const unmatched = Object.assign({}, lc, {
    activePlayer: { summonerName: "NotInThisLobby#TAG", riotIdGameName: "NotInThisLobby" },
  });
  assert.strictEqual(am._resolveMyTeam(unmatched), null);
  assert.deepStrictEqual(am._amThreatEnemies(unmatched), []);
});

test("threat enemies: no activePlayer name at all -> no threats", () => {
  const lc = fixtureLc("active_match_sr.json");
  for (const ap of [undefined, null, {}, { summonerName: "", riotIdGameName: "" }]) {
    const x = Object.assign({}, lc, { activePlayer: ap });
    assert.deepStrictEqual(am._amThreatEnemies(x), [], JSON.stringify(ap));
  }
});

test("threat enemies: my own row has a blank team -> no threats", () => {
  const lc = fixtureLc("active_match_arena.json");
  const rows = lc.allPlayers.map((pl) => (
    pl.summonerName === lc.activePlayer.summonerName ? Object.assign({}, pl, { team: "" }) : pl
  ));
  assert.deepStrictEqual(am._amThreatEnemies(Object.assign({}, lc, { allPlayers: rows })), []);
});

test("threat enemies: a riotId 'Name#Tag' activePlayer still resolves against bare game names", () => {
  const lc = {
    activePlayer: { summonerName: "SamplePlayer#EUW", riotIdGameName: "SamplePlayer" },
    allPlayers: [
      { riotIdGameName: "SamplePlayer", summonerName: "SamplePlayer#EUW", championName: "Jinx", team: "100" },
      { riotIdGameName: "MyDuo", summonerName: "MyDuo#EUW", championName: "Karma", team: "100" },
      { riotIdGameName: "FoeA", summonerName: "FoeA#EUW", championName: "Garen", team: "200" },
      { riotIdGameName: "FoeB", summonerName: "FoeB#EUW", championName: "Lulu", team: "200" },
    ],
  };
  assert.deepStrictEqual(champs(am._amThreatEnemies(lc)), ["Garen", "Lulu"]);
});

test("threat enemies: blank-team rows and junk rows are skipped; junk input is fail-soft", () => {
  const lc = {
    activePlayer: { summonerName: "Me" },
    allPlayers: [
      { summonerName: "Me", championName: "Jinx", team: "ORDER" },
      null,
      "junk",
      { summonerName: "Ghost", championName: "Zed", team: "" },
      { summonerName: "Foe", championName: "Garen", team: "CHAOS" },
    ],
  };
  assert.deepStrictEqual(champs(am._amThreatEnemies(lc)), ["Garen"]);
  for (const bad of [undefined, null, {}, { allPlayers: "x" }, { allPlayers: [] }]) {
    assert.deepStrictEqual(am._amThreatEnemies(bad), [], JSON.stringify(bad));
  }
});
