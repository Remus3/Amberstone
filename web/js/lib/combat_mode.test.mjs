// web/js/lib/combat_mode.test.mjs
//
// QA9 overlay combat-mode declutter - pure-logic tests. Run with `node --test`.
// The DOM stamp (body[data-fight]) lives in right_now.js and is exercised in
// the overlay at runtime; these pin the conservative trigger + the hysteresis
// hold that keeps the declutter from strobing mid-fight.

import test from "node:test";
import assert from "node:assert";

import { isFightCue, makeCombatLatch, DEFAULT_HOLD_MS } from "./combat_mode.js";

test("isFightCue: the emergency tier is always a fight", () => {
  for (const cue of ["lethal", "objective_steal", "urgent_headline"]) {
    assert.strictEqual(isFightCue({ cue, tier: "emergency" }), true, cue);
  }
});

test("isFightCue: an explicit fight-band headline is a fight", () => {
  assert.strictEqual(isFightCue({ cue: "fight", tier: "urgent" }), true);
});

test("isFightCue: non-combat cues keep the full HUD", () => {
  assert.strictEqual(isFightCue({ cue: "spike", tier: "urgent" }), false);
  assert.strictEqual(isFightCue({ cue: "choices", tier: "urgent" }), false);
  assert.strictEqual(isFightCue({ cue: "good", tier: "ambient" }), false);
  assert.strictEqual(isFightCue({ cue: "none", tier: "empty" }), false);
});

test("isFightCue: null / garbage never throws and is not a fight", () => {
  assert.strictEqual(isFightCue(null), false);
  assert.strictEqual(isFightCue(undefined), false);
  assert.strictEqual(isFightCue("fight"), false);
  assert.strictEqual(isFightCue({}), false);
});

test("makeCombatLatch: engages immediately on a fight", () => {
  const latch = makeCombatLatch({ holdMs: 1000 });
  assert.strictEqual(latch.update(false, 0), false);
  assert.strictEqual(latch.update(true, 100), true);
});

test("makeCombatLatch: holds through the configured window after the trigger clears", () => {
  const latch = makeCombatLatch({ holdMs: 1000 });
  latch.update(true, 100); // until = 1100
  assert.strictEqual(latch.update(false, 500), true, "within hold");
  assert.strictEqual(latch.update(false, 1099), true, "edge of hold");
  assert.strictEqual(latch.update(false, 1100), false, "hold expired");
});

test("makeCombatLatch: a re-trigger extends the hold", () => {
  const latch = makeCombatLatch({ holdMs: 1000 });
  latch.update(true, 100);   // until = 1100
  latch.update(true, 2000);  // re-engage, until = 3000
  assert.strictEqual(latch.active(2999), true);
  assert.strictEqual(latch.active(3000), false);
});

test("makeCombatLatch: reset clears the hold", () => {
  const latch = makeCombatLatch({ holdMs: 1000 });
  latch.update(true, 100);
  latch.reset();
  assert.strictEqual(latch.active(150), false);
});

test("makeCombatLatch: a never-fight stream is never active", () => {
  const latch = makeCombatLatch({ holdMs: 1000 });
  assert.strictEqual(latch.update(false, 0), false);
  assert.strictEqual(latch.update(false, 5000), false);
  assert.strictEqual(latch.active(10000), false);
});

test("DEFAULT_HOLD_MS is a sane couple-of-ticks value", () => {
  assert.ok(DEFAULT_HOLD_MS >= 2000 && DEFAULT_HOLD_MS <= 6000);
});
