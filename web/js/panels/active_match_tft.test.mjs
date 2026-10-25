// web/js/panels/active_match_tft.test.mjs
//
// S134 T1: the Active Match view during a live TFT game (and during a live
// game whose mode RC has not resolved). Run with `node --test`.
//
// MEASURED 2026-10-25 in a live TFT match: TFT now runs as a standalone
// TFTClient process with NOTHING on :2999, so /api/state.liveclient stayed {}
// for the whole match, mode_key was "tft" only while the LCU champ-select
// retention held (it fell to "client" after an RC restart), and the view
// painted SR scaffolding - "Drake spawns 5:00 - set up vision", the
// TOP/JG/MID/BOT ward strip, "0 VISIBLE - 0 MIA", the DS item build. These pin
// the pure model that replaces that with an honest TFT state.
//
// The COACH fixtures are the real captured /api/state.coach shapes (operator
// identifiers dropped): TFT_COACH_LIVE is the tft_coaching_data payload served
// mid-match, SR_COACH_AFTER_RESTART is what mode_key "client" served after the
// restart (the stale SR coaching_data.json).

import test from "node:test";
import assert from "node:assert";

import { amLiveFallbackModel, amStickyPhase } from "./active_match.js";

const TFT_COACH_LIVE = {
  mode: "tft", action: "", board: "", econ: "", rolldown: "", items: "",
  god_pick: "", placement: "", upgrade: "", risk: "MEDIUM", choices: [],
  immediate: "", fight_rule: "FAIR FIGHT - trade only on cooldowns, avoid coinflips",
};

const SR_COACH_AFTER_RESTART = {
  mode: "client", action: "Drake spawns 5:00 - set up vision",
  immediate: "Drake spawns 5:00 - set up vision", next: "",
  fight_rule: "FAIR FIGHT - trade only on cooldowns, avoid coinflips",
  wave: "", objective: "", reset_item: "", risk: "MEDIUM", map: "",
  win_pct: null, choices: [],
};

// Words that only make sense on the Rift. None may reach a TFT surface.
const SR_WORDS = /drake|herald|baron|ward|vision|lane|\bjg\b|\bmid\b|\bbot\b|\bcs\b|cooldown|coinflip|DS engine/i;

function allText(m) {
  return [m.sub, m.build, m.map, ...m.status, ...m.rows.flat()].join(" | ");
}

const EMPTY_STATS = [["STAGE", "-"], ["LEVEL", "-"], ["HP", "-"], ["GOLD", "-"]];

test("feed modes keep the existing render path (model is null)", () => {
  for (const mode of ["sr", "classic", "aram", "arena", "brawl"]) {
    assert.strictEqual(amLiveFallbackModel(mode, "InProgress", SR_COACH_AFTER_RESTART), null, mode);
  }
});

test("not live -> null (the between-games path owns champ select / loading / post-game)", () => {
  for (const phase of ["", "-", "ChampSelect", "GameStart", "EndOfGame", "Lobby", null, undefined]) {
    assert.strictEqual(amLiveFallbackModel("tft", phase, TFT_COACH_LIVE), null, String(phase));
    assert.strictEqual(amLiveFallbackModel("client", phase, SR_COACH_AFTER_RESTART), null, String(phase));
  }
});

test("live TFT with the real captured coach payload: honest unavailable state", () => {
  const m = amLiveFallbackModel("tft", "InProgress", TFT_COACH_LIVE);
  assert.ok(m, "TFT live must produce a model");
  assert.strictEqual(m.kind, "tft");
  assert.strictEqual(m.hasData, false);
  assert.match(m.sub, /^TFT\b/);
  assert.match(m.sub, /live data unavailable/i);
  assert.strictEqual(m.status[0], "TFT LIVE DATA");
  assert.match(m.status[1], /unavailable/i);
  // The four stat slots are present even with no data - the geometry is the
  // same before and after the feed lands (no reflow on data absence).
  assert.deepStrictEqual(m.rows, EMPTY_STATS);
  assert.doesNotMatch(allText(m), SR_WORDS);
});

test("live TFT never paints a coach imperative, even an SR one (B4 + wrong mode)", () => {
  const m = amLiveFallbackModel("tft", "InProgress", SR_COACH_AFTER_RESTART);
  assert.ok(m);
  assert.doesNotMatch(allText(m), /Drake|set up vision|FAIR FIGHT|MEDIUM/);
});

test("live game with an unresolved mode (client after an RC restart): neutral, no SR text", () => {
  for (const mode of ["client", "", "-", "none", "game"]) {
    const m = amLiveFallbackModel(mode, "InProgress", SR_COACH_AFTER_RESTART);
    assert.ok(m, `mode ${JSON.stringify(mode)} must produce a model`);
    assert.strictEqual(m.kind, "game");
    assert.match(m.sub, /^GAME IN PROGRESS/);
    assert.strictEqual(m.status[0], "LIVE DATA");
    assert.match(m.status[1], /unavailable/i);
    assert.deepStrictEqual(m.rows, [], "unknown mode -> no TFT stat slots");
    assert.doesNotMatch(allText(m), SR_WORDS);
  }
});

test("descriptive TFT state renders as fixed STAGE / LEVEL / HP / GOLD rows", () => {
  const m = amLiveFallbackModel("tft", "InProgress",
    { ...TFT_COACH_LIVE, stage_round: "3-2", level: 6, hp: 64, gold: 32 });
  assert.strictEqual(m.hasData, true);
  assert.deepStrictEqual(m.rows, [["STAGE", "3-2"], ["LEVEL", "6"], ["HP", "64"], ["GOLD", "32"]]);
  assert.deepStrictEqual(m.status, ["TFT LIVE DATA", "Live"]);
  assert.match(m.sub, /^TFT - stage 3-2 - phase InProgress$/);
});

test("stage from separate stage + round numbers", () => {
  const m = amLiveFallbackModel("tft", "InProgress", { stage: 2, round: 1, level: 4 });
  assert.strictEqual(m.rows[0][1], "2-1");
});

test("producer zero sentinels are not data (tft_live_data.json defaults)", () => {
  const m = amLiveFallbackModel("tft", "InProgress",
    { ...TFT_COACH_LIVE, stage_round: "", level: 0, hp: 0 });
  assert.strictEqual(m.hasData, false);
  assert.deepStrictEqual(m.rows, EMPTY_STATS);
  assert.match(m.status[1], /unavailable/i);
});

test("no-data and data states carry the same slot count (stable geometry)", () => {
  const none = amLiveFallbackModel("tft", "InProgress", TFT_COACH_LIVE);
  const full = amLiveFallbackModel("tft", "InProgress", { stage_round: "5-1", level: 8, hp: 40, gold: 12 });
  assert.strictEqual(none.rows.length, full.rows.length);
  assert.deepStrictEqual(none.rows.map((r) => r[0]), full.rows.map((r) => r[0]));
  assert.strictEqual(none.status[0], full.status[0]);
});

test("partial data keeps all four rows (no reflow) with the '-' sentinel", () => {
  const m = amLiveFallbackModel("tft", "InProgress", { level: 5 });
  assert.strictEqual(m.hasData, true);
  assert.deepStrictEqual(m.rows, [["STAGE", "-"], ["LEVEL", "5"], ["HP", "-"], ["GOLD", "-"]]);
});

test("implausible / garbage values fall back to '-'", () => {
  const m = amLiveFallbackModel("tft", "InProgress",
    { stage_round: "<b>9-9</b>", level: 6, hp: "x", gold: -4 });
  assert.deepStrictEqual(m.rows, [["STAGE", "-"], ["LEVEL", "6"], ["HP", "-"], ["GOLD", "-"]]);
  const big = amLiveFallbackModel("tft", "InProgress", { level: 99 });
  assert.strictEqual(big.hasData, false);
});

test("every model string is 7-bit ASCII", () => {
  const models = [
    amLiveFallbackModel("tft", "InProgress", TFT_COACH_LIVE),
    amLiveFallbackModel("tft", "InProgress", { stage_round: "4-5", level: 8, hp: 12, gold: 50 }),
    amLiveFallbackModel("client", "InProgress", SR_COACH_AFTER_RESTART),
  ];
  for (const m of models) {
    assert.ok(/^[\x20-\x7e]*$/.test(allText(m)), allText(m));
  }
});

test("garbage payload is safe", () => {
  for (const p of [null, undefined, "x", 7, []]) {
    const m = amLiveFallbackModel("tft", "InProgress", p);
    assert.ok(m);
    assert.strictEqual(m.hasData, false);
  }
});

// The LCU agent can drop /api/state.lcu.phase for several seconds mid-game
// (dashboard/_liveclient.lcu_summary discards snapshots older than 5s). With no
// :2999 feed in TFT that blink would flip the panes to "no in-game session"
// and back, so the effective phase holds through a blank.
test("amStickyPhase holds InProgress through a blank phase in the same mode", () => {
  const memo = {};
  assert.strictEqual(amStickyPhase(memo, "tft", "InProgress"), "InProgress");
  assert.strictEqual(amStickyPhase(memo, "tft", ""), "InProgress");
  assert.strictEqual(amStickyPhase(memo, "tft", "-"), "InProgress");
  assert.strictEqual(amStickyPhase(memo, "tft", null), "InProgress");
});

test("amStickyPhase releases on a definite phase and on a mode change", () => {
  const memo = {};
  amStickyPhase(memo, "tft", "InProgress");
  assert.strictEqual(amStickyPhase(memo, "tft", "EndOfGame"), "EndOfGame");
  assert.strictEqual(amStickyPhase(memo, "tft", ""), "");
  const memo2 = {};
  amStickyPhase(memo2, "tft", "InProgress");
  assert.strictEqual(amStickyPhase(memo2, "client", ""), "");
});

test("amStickyPhase never invents a live game from blanks alone", () => {
  const memo = {};
  assert.strictEqual(amStickyPhase(memo, "tft", ""), "");
  assert.strictEqual(amStickyPhase(memo, "client", "-"), "-");
});
