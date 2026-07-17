// web/js/panels/enemy_spells_timer.test.mjs
//
// RM-05 round-2 regression: "PR enemy-spell chip starts no cooldown timer"
// (operator live recon 2026-07-05). Run with `node --test`.
//
// Root cause (two layers, both in enemy_spells.js):
//   1. SPELL_CD keys are Live Client displayNames, but the S13+ jungle-pet
//      Smite upgrade tiers ("Unleashed Smite" -> "Primal Smite") were missing,
//      so mid-game the enemy jungler's chip fell into the cd=0 fallback. The
//      _abbr fallback rendered "Primal Smite" as "PR" - the operator's "PR
//      chip".
//   2. The documented cd=0 fallback ("a plain used/UP toggle ... 'burned'
//      marker", header lines 20-21) never worked: _remaining computed
//      rem = ceil(t + 0 - now) <= 0 and auto-DELETED the just-tapped entry,
//      so the tap was a total visible no-op.
// The delegated click handler itself was proven live (sibling chips in the
// same mount counted down), so these tests pin the pure state layer the tap
// drives: _toggle -> _remaining through _esInternals.

import test from "node:test";
import assert from "node:assert";

import { _esInternals, _resetEnemySpells } from "./enemy_spells.js";

const { SPELL_CD, SPELL_ABBR, _abbr, _toggle, _remaining, _load } = _esInternals;

const CHAMP = "Nunu & Willump";
const SLOT = "1";

test("SPELL_CD covers both Smite upgrade tiers at the 90s base recharge", () => {
  assert.strictEqual(SPELL_CD["Smite"], 90);
  assert.strictEqual(SPELL_CD["Unleashed Smite"], 90);
  assert.strictEqual(SPELL_CD["Primal Smite"], 90);
});

test("Smite upgrade tiers abbreviate to SM (the Unleashed Teleport -> TP idiom)", () => {
  assert.strictEqual(_abbr("Unleashed Smite"), "SM");
  assert.strictEqual(_abbr("Primal Smite"), "SM");
  // The mapped tags stay within the 2-char no-ellipsis budget.
  assert.ok(SPELL_ABBR["Unleashed Smite"].length <= 2);
  assert.ok(SPELL_ABBR["Primal Smite"].length <= 2);
});

test("REPRO: tapping the upgraded-Smite chip starts a real countdown", () => {
  _resetEnemySpells();
  _load("game-1");
  _toggle(CHAMP, SLOT);
  const rem = _remaining(CHAMP, SLOT, "Primal Smite");
  // Pre-fix: SPELL_CD miss -> cd 0 -> rem <= 0 -> the entry was auto-deleted
  // and this returned null (the "starts no cooldown timer" no-op).
  assert.ok(Number.isFinite(rem), "tap must start a countdown, got " + rem);
  assert.ok(rem > 0 && rem <= 90, "countdown must be within the 90s base CD");
});

test("an unknown spell keeps the documented sticky burned marker (no insta-clear)", () => {
  _resetEnemySpells();
  _load("game-2");
  _toggle(CHAMP, SLOT);
  // Header contract (lines 20-21): unknown spell -> a plain used/UP toggle
  // with no countdown. The marker must SURVIVE repeated reads (per-tick
  // _updateTimers), not auto-clear like an expired countdown.
  assert.strictEqual(_remaining(CHAMP, SLOT, "Mystery Spell"), Infinity);
  assert.strictEqual(_remaining(CHAMP, SLOT, "Mystery Spell"), Infinity);
  // The second tap (mis-tap correction) is the only way back to UP.
  _toggle(CHAMP, SLOT);
  assert.strictEqual(_remaining(CHAMP, SLOT, "Mystery Spell"), null);
});

test("known spells keep the tap -> countdown -> toggle-off cycle", () => {
  _resetEnemySpells();
  _load("game-3");
  _toggle(CHAMP, SLOT);
  const rem = _remaining(CHAMP, SLOT, "Flash");
  assert.ok(rem > 0 && rem <= 300, "Flash countdown within its 300s base CD");
  _toggle(CHAMP, SLOT);
  assert.strictEqual(_remaining(CHAMP, SLOT, "Flash"), null);
});

test("an expired known-spell countdown still auto-clears back to UP", () => {
  _resetEnemySpells();
  const store = _load("game-4");
  // Backdate the tap far past Flash's 300s base CD.
  store.map[CHAMP + "|" + SLOT] = 1;
  assert.strictEqual(_remaining(CHAMP, SLOT, "Flash"), null);
  // And the expired entry is gone (auto-clear preserved).
  assert.strictEqual(store.map[CHAMP + "|" + SLOT], undefined);
});
