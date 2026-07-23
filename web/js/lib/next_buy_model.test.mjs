// web/js/lib/next_buy_model.test.mjs
//
// NEXT BUY pure model - unit tests. Run with `node --test`.
// The DOM render (panels/next_buy.js renderNextBuy) is exercised by the
// rendered Chromium harness; these pin the mirrors of
// core/build_planner/scoring.stage_for + core/build_planner/replan's
// upgrade_trinket rule, the component-credit gold arithmetic, and the honest
// no-data gates - the same discipline as objective_gauges.test.mjs.

import test from "node:test";
import assert from "node:assert";

import {
  NB_STAGE,
  NB_TRINKET_FROM,
  NB_TRINKET_TO,
  NB_TRINKET_MIN_STAGE,
  stageFor,
  completedCount,
  nextItemName,
  goldRemaining,
  trinketNudge,
  computeNextBuy,
} from "./next_buy_model.js";

// A tiny fake item dictionary. Kraken Slayer 6672 (3100g) is built from
// Noonquiver 6670 (1300g) + Recurve Bow 1043 (1000g); shapes mirror
// items_index.ITEM_COSTS.byId / ITEM_RECIPES.byId.
const COSTS = { byId: { 6672: 3100, 6670: 1300, 1043: 1000, 3006: 1100 } };
const RECIPES = { byId: { 6672: { from: ["6670", "1043"], gold: 3100 } } };
const NAMES = {
  "kraken slayer": "6672",
  "noonquiver": "6670",
  "recurve bow": "1043",
  "berserker's greaves": "3006",
};
const DEPS = {
  costs: COSTS,
  recipes: RECIPES,
  resolve: (n) => NAMES[String(n || "").trim().toLowerCase()] || null,
};

test("NB_STAGE mirrors the core/build_planner/scoring.py constants", () => {
  assert.strictEqual(NB_STAGE.earlyClockS, 600);
  assert.strictEqual(NB_STAGE.lateClockS, 1320);
  assert.strictEqual(NB_STAGE.midOwned, 2);
  assert.strictEqual(NB_STAGE.lateOwned, 4);
});

test("stageFor: clock OR owned count, whichever is further along", () => {
  assert.strictEqual(stageFor(0, 0), "early");
  assert.strictEqual(stageFor(599, 1), "early");
  assert.strictEqual(stageFor(600, 0), "mid");      // clock crosses
  assert.strictEqual(stageFor(0, 2), "mid");        // owned crosses
  assert.strictEqual(stageFor(1320, 0), "late");
  assert.strictEqual(stageFor(0, 4), "late");
  assert.strictEqual(stageFor(1320, 0), "late");
  // Garbage clock degrades to the owned axis, never throws.
  assert.strictEqual(stageFor("x", 4), "late");
  assert.strictEqual(stageFor(null, 0), "early");
});

test("completedCount ignores trinkets and blanks", () => {
  assert.strictEqual(completedCount(null), 0);
  assert.strictEqual(completedCount([]), 0);
  assert.strictEqual(
    completedCount(["Kraken Slayer", "", "Stealth Ward", "Berserker's Greaves"]),
    2);
  // Every trinket spelling the build view skips is excluded.
  assert.strictEqual(completedCount([
    "Farsight Alteration", "Stealth Ward", "Oracle Lens",
    "Scrying Orb", "Warding Totem"]), 0);
});

test("nextItemName picks the first next===true row", () => {
  assert.strictEqual(nextItemName(null), "");
  assert.strictEqual(nextItemName([]), "");
  assert.strictEqual(nextItemName([{ name: "A", owned: true, next: false }]), "");
  assert.strictEqual(nextItemName([
    { name: "A", owned: true, next: false },
    { name: "B", owned: false, next: true },
    { name: "C", owned: false, next: true },
  ]), "B");
  // Defensive: junk rows are skipped, not thrown on.
  assert.strictEqual(nextItemName([null, 7, { next: true }, { name: "D", next: true }]), "D");
});

test("goldRemaining: plain cost minus gold", () => {
  assert.strictEqual(goldRemaining("Kraken Slayer", 0, [], DEPS), 3100);
  assert.strictEqual(goldRemaining("Kraken Slayer", 600, [], DEPS), 2500);
});

test("goldRemaining credits owned DIRECT components once each", () => {
  // Noonquiver owned -> 3100 - 1300 - 500 gold in hand = 1300.
  assert.strictEqual(
    goldRemaining("Kraken Slayer", 500, ["Noonquiver"], DEPS), 1300);
  // Both components owned -> 3100 - 2300 - 0 = 800.
  assert.strictEqual(
    goldRemaining("Kraken Slayer", 0, ["Noonquiver", "Recurve Bow"], DEPS), 800);
  // A duplicate name credits once, never twice.
  assert.strictEqual(
    goldRemaining("Kraken Slayer", 0, ["Noonquiver", "Noonquiver"], DEPS), 1800);
  // An owned item that is NOT a component of the target credits nothing.
  assert.strictEqual(
    goldRemaining("Kraken Slayer", 0, ["Berserker's Greaves"], DEPS), 3100);
});

test("goldRemaining floors at 0 and never goes negative", () => {
  assert.strictEqual(goldRemaining("Kraken Slayer", 9999, [], DEPS), 0);
});

test("goldRemaining returns null (the '-' sentinel) on unknown cost", () => {
  // Unresolvable name.
  assert.strictEqual(goldRemaining("Nonexistent Item", 100, [], DEPS), null);
  // Resolvable but no cost entry.
  const thin = { ...DEPS, costs: { byId: {} } };
  assert.strictEqual(goldRemaining("Kraken Slayer", 100, [], thin), null);
  // Missing deps entirely.
  assert.strictEqual(goldRemaining("Kraken Slayer", 100, [], null), null);
  // Non-numeric gold: unknown, not 0.
  assert.strictEqual(goldRemaining("Kraken Slayer", "x", [], DEPS), null);
  assert.strictEqual(goldRemaining("", 100, [], DEPS), null);
});

test("goldRemaining survives a missing recipe graph (no credit, no throw)", () => {
  const noRecipes = { ...DEPS, recipes: { byId: {} } };
  assert.strictEqual(
    goldRemaining("Kraken Slayer", 0, ["Noonquiver"], noRecipes), 3100);
});

test("trinketNudge mirrors replan upgrade_trinket (3340 -> 3363, stage >= mid)", () => {
  assert.strictEqual(NB_TRINKET_TO, "Farsight Alteration");
  assert.strictEqual(NB_TRINKET_MIN_STAGE, "mid");
  assert.deepStrictEqual(NB_TRINKET_FROM, ["stealth ward", "warding totem"]);
  // Early stage: the free upgrade is NOT yet nudged.
  assert.strictEqual(trinketNudge(["Stealth Ward"], 300, 0), "");
  // Mid by clock.
  assert.strictEqual(trinketNudge(["Stealth Ward"], 600, 0), "Farsight Alteration");
  // Mid by completed-item count even on an early clock.
  assert.strictEqual(trinketNudge(["Warding Totem"], 120, 2), "Farsight Alteration");
  // Late still fires (>= mid).
  assert.strictEqual(trinketNudge(["Stealth Ward"], 1800, 5), "Farsight Alteration");
});

test("trinketNudge stays silent when the yellow trinket is not held", () => {
  assert.strictEqual(trinketNudge(["Farsight Alteration"], 1800, 5), "");
  assert.strictEqual(trinketNudge(["Oracle Lens"], 1800, 5), "");
  assert.strictEqual(trinketNudge([], 1800, 5), "");
  assert.strictEqual(trinketNudge(null, 1800, 5), "");
});

test("computeNextBuy: honest no-data whole-widget gates", () => {
  const ok = {
    game_time_s: 700, gold: 500,
    sr_items: [{ name: "Kraken Slayer", owned: false, next: true }],
    owned_items: [],
  };
  assert.strictEqual(computeNextBuy(null, DEPS), null);
  assert.strictEqual(computeNextBuy({}, DEPS), null);
  // No game clock.
  assert.strictEqual(computeNextBuy({ ...ok, game_time_s: "x" }, DEPS), null);
  // No build path.
  assert.strictEqual(computeNextBuy({ ...ok, sr_items: [] }, DEPS), null);
  assert.strictEqual(computeNextBuy({ ...ok, sr_items: null }, DEPS), null);
  // No gold reading (activePlayer-only field, absent for a spectator frame).
  assert.strictEqual(computeNextBuy({ ...ok, gold: null }, DEPS), null);
  assert.notStrictEqual(computeNextBuy(ok, DEPS), null);
});

test("computeNextBuy assembles both rule lines", () => {
  const m = computeNextBuy({
    game_time_s: 900,
    gold: 500,
    sr_items: [
      { name: "Berserker's Greaves", owned: true, next: false },
      { name: "Kraken Slayer", owned: false, next: true },
    ],
    owned_items: ["Berserker's Greaves", "Noonquiver", "Stealth Ward"],
  }, DEPS);
  assert.strictEqual(m.item, "Kraken Slayer");
  assert.strictEqual(m.remaining, 1300);           // 3100 - 1300 comp - 500 gold
  assert.strictEqual(m.trinket, "Farsight Alteration");
});

test("computeNextBuy keeps the rows present when a value is absent", () => {
  // Build path exists but nothing is flagged next -> item "" + remaining null,
  // so the render falls to the "-" sentinel WITHOUT dropping a row.
  const m = computeNextBuy({
    game_time_s: 200, gold: 0,
    sr_items: [{ name: "Doran's Blade", owned: true, next: false }],
    owned_items: ["Doran's Blade"],
  }, DEPS);
  assert.strictEqual(m.item, "");
  assert.strictEqual(m.remaining, null);
  assert.strictEqual(m.trinket, "");
});
