// web/js/lib/arm_confirm.test.mjs
//
// Mission Control S4. Pins the arm-then-confirm lifecycle, and specifically the
// MEASURED constraint from docs/MISSION_CONTROL_PLAN.md: the idempotency key is
// minted at ARM and DISCARDED on disarm, so a retry after a refusal carries a
// NEW key. Reusing one key across arms replays the refusal forever - the button
// then looks alive and is permanently inert.
//
// Run with `node --test web/js/lib/arm_confirm.test.mjs`.

import test from "node:test";
import assert from "node:assert";

import { createArmController, ARM_WINDOW_MS } from "./arm_confirm.js";

/** Controller with a deterministic clock and a counting key factory. */
function build(windowMs) {
  let t = 1000;
  let n = 0;
  const minted = [];
  const ctl = createArmController({
    now: () => t,
    windowMs: typeof windowMs === "number" ? windowMs : ARM_WINDOW_MS,
    mintKey: () => {
      n += 1;
      const k = "key-" + n;
      minted.push(k);
      return k;
    },
  });
  return {
    ctl,
    minted,
    advance: (ms) => { t += ms; },
    at: () => t,
  };
}

test("a single click only arms - it does not fire", () => {
  const { ctl } = build();
  const snap = ctl.arm("halt_save");
  assert.equal(snap.armedId, "halt_save");
  assert.ok(snap.key, "arming mints a key");
  assert.equal(ctl.isArmed("halt_save"), true);
});

test("a second click inside the window fires with the armed key", () => {
  const { ctl, minted } = build();
  ctl.arm("halt_save");
  const res = ctl.confirm("halt_save");
  assert.equal(res.fired, true);
  assert.equal(res.key, minted[0]);
  assert.equal(ctl.isArmed("halt_save"), false, "firing disarms");
});

test("a stray single click decays to nothing after the window", () => {
  const { ctl, advance } = build(3000);
  ctl.arm("halt_save");
  advance(3000);
  const res = ctl.confirm("halt_save");
  assert.equal(res.fired, false);
  assert.equal(res.reason, "expired");
  assert.equal(res.key, null);
});

test("tick auto-disarms an expired arm from the render path", () => {
  const { ctl, advance } = build(3000);
  ctl.arm("done_continue");
  assert.equal(ctl.tick(), false, "still inside the window");
  advance(3001);
  assert.equal(ctl.tick(), true, "expired arm is dropped");
  assert.equal(ctl.snapshot().key, null, "and its key is discarded");
});

// -- the measured constraint -------------------------------------------------

test("re-arming after a REFUSAL mints a DIFFERENT key", () => {
  // Sequence that broke against the real S2 route: fire while the lane was
  // held (200 ok:false refused:lane_held), lane frees, operator clicks again.
  // A reused key replays the stored refusal and the lane never fires.
  const { ctl, minted } = build();
  ctl.arm("halt_save");
  const first = ctl.confirm("halt_save");
  assert.equal(first.fired, true);

  ctl.arm("halt_save");                       // second operator intent
  const second = ctl.confirm("halt_save");
  assert.equal(second.fired, true);
  assert.notEqual(second.key, first.key,
    "a retry after a refusal must NOT reuse the refused key");
  assert.deepEqual(minted, ["key-1", "key-2"]);
});

test("disarm discards the key so the next arm cannot reuse it", () => {
  const { ctl } = build();
  const armed = ctl.arm("halt_save");
  ctl.disarm();
  assert.equal(ctl.snapshot().key, null);
  const rearmed = ctl.arm("halt_save");
  assert.notEqual(rearmed.key, armed.key);
});

test("an expired arm discards its key too", () => {
  const { ctl, advance } = build(3000);
  const armed = ctl.arm("halt_save");
  advance(3000);
  ctl.confirm("halt_save");                    // expired -> disarms
  const rearmed = ctl.arm("halt_save");
  assert.notEqual(rearmed.key, armed.key);
});

test("one key is never used for two fires", () => {
  const { ctl } = build();
  ctl.arm("halt_save");
  const a = ctl.confirm("halt_save");
  const b = ctl.confirm("halt_save");          // double-tap on an already-fired arm
  assert.equal(a.fired, true);
  assert.equal(b.fired, false);
  assert.equal(b.reason, "not_armed");
  assert.equal(b.key, null);
});

// -- cross-intent isolation --------------------------------------------------

test("arming a second intent disarms the first and discards its key", () => {
  const { ctl } = build();
  const halt = ctl.arm("halt_save");
  const done = ctl.arm("done_continue");
  assert.notEqual(done.key, halt.key);
  assert.equal(ctl.isArmed("halt_save"), false);
  const res = ctl.confirm("halt_save");
  assert.equal(res.fired, false);
  assert.equal(res.reason, "other_armed");
});

test("confirming the wrong intent never fires and never leaks a key", () => {
  const { ctl } = build();
  ctl.arm("halt_save");
  const res = ctl.confirm("done_continue");
  assert.equal(res.fired, false);
  assert.equal(res.key, null);
  assert.equal(ctl.isArmed("halt_save"), true, "the armed intent survives");
});

test("remainingMs counts down and floors at zero", () => {
  const { ctl, advance } = build(3000);
  ctl.arm("halt_save");
  assert.equal(ctl.remainingMs(), 3000);
  advance(1200);
  assert.equal(ctl.remainingMs(), 1800);
  advance(5000);
  assert.equal(ctl.remainingMs(), 0);
});

test("arm rejects an empty id", () => {
  const { ctl } = build();
  assert.throws(() => ctl.arm(""), /requires an id/);
});

test("onChange fires on arm, on fire and on expiry", () => {
  const seen = [];
  let t = 0;
  const ctl = createArmController({
    now: () => t,
    windowMs: 100,
    mintKey: () => "k",
    onChange: (s) => seen.push(s.armedId),
  });
  ctl.arm("halt_save");
  ctl.confirm("halt_save");
  ctl.arm("done_continue");
  t = 500;
  ctl.tick();
  assert.deepEqual(seen, ["halt_save", null, "done_continue", null]);
});

test("the default key factory produces an idempotency-key-safe string", () => {
  // dashboard/_idempotency.is_valid_key accepts hex + dash, 1-64 chars.
  const ctl = createArmController({ now: () => 0 });
  const { key } = ctl.arm("halt_save");
  assert.match(key, /^[0-9a-fA-F-]{1,64}$/);
});
