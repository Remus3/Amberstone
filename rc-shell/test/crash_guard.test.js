// rc-shell/test/crash_guard.test.js
//
// node:test for the PURE crash-isolation restart policy (no electron).
// Every clock-dependent assertion injects now() - no real sleeps, no
// Date.now in assertions.

"use strict";

const test = require("node:test");
const assert = require("node:assert");

const cg = require("../src/crash_guard");

// Tiny manual clock: mutate clock.t, pass clock.now as the injectable clock.
function makeClock(start) {
  const clock = { t: Number.isFinite(start) ? start : 0 };
  clock.now = () => clock.t;
  return clock;
}

// --- RESTART_REASONS + shouldRestart -----------------------------------------

test("RESTART_REASONS: exactly the 5 restartable render-process-gone reasons", () => {
  assert.deepStrictEqual(
    [...cg.RESTART_REASONS].sort(),
    ["abnormal-exit", "crashed", "integrity-failure", "launch-failed", "oom"]
  );
});

test("shouldRestart: true for every RESTART_REASONS member", () => {
  for (const r of cg.RESTART_REASONS) {
    assert.strictEqual(cg.shouldRestart(r), true, r);
  }
});

test("shouldRestart: false for deliberate / external terminations", () => {
  assert.strictEqual(cg.shouldRestart("clean-exit"), false);
  assert.strictEqual(cg.shouldRestart("killed"), false);
});

test("shouldRestart: unknown / missing reasons are fail-safe false", () => {
  assert.strictEqual(cg.shouldRestart("zzz"), false);
  assert.strictEqual(cg.shouldRestart(undefined), false);
  assert.strictEqual(cg.shouldRestart(null), false);
  assert.strictEqual(cg.shouldRestart(""), false);
  assert.strictEqual(cg.shouldRestart(42), false);
  assert.strictEqual(cg.shouldRestart("CRASHED"), false); // exact-match only
});

// --- record: ignore path ------------------------------------------------------

test("record: killed / clean-exit -> ignore, budget untouched", () => {
  const clock = makeClock(1000);
  const g = cg.makeCrashGuard({ now: clock.now });
  assert.deepStrictEqual(g.record("overlay", "killed"), {
    action: "ignore",
    reason: "killed",
    count: 0,
    key: "overlay",
  });
  assert.deepStrictEqual(g.record("overlay", "clean-exit"), {
    action: "ignore",
    reason: "clean-exit",
    count: 0,
    key: "overlay",
  });
  // Budget untouched: the full default 3 restarts are still available.
  assert.deepStrictEqual(g.state("overlay"), { count: 0, remaining: 3 });
});

test("record: unknown / missing reason -> ignore (fail-safe)", () => {
  const clock = makeClock(0);
  const g = cg.makeCrashGuard({ now: clock.now });
  assert.strictEqual(g.record("overlay", "mystery").action, "ignore");
  assert.strictEqual(g.record("overlay", undefined).action, "ignore");
  assert.deepStrictEqual(g.state("overlay"), { count: 0, remaining: 3 });
});

// --- record: restart budget -> give-up ----------------------------------------

test("record: restart for the first maxRestarts crashes, then give-up", () => {
  const clock = makeClock(0);
  const g = cg.makeCrashGuard({ maxRestarts: 3, windowMs: 60000, now: clock.now });
  for (let i = 1; i <= 3; i++) {
    clock.t += 100;
    const r = g.record("overlay", "crashed");
    assert.strictEqual(r.action, "restart", "crash " + i);
    assert.strictEqual(r.count, i, "crash " + i);
  }
  clock.t += 100;
  assert.deepStrictEqual(g.record("overlay", "crashed"), {
    action: "give-up",
    reason: "crashed",
    count: 4,
    key: "overlay",
  });
});

test("record: a crash loop converges to give-up and stays there in-window", () => {
  const clock = makeClock(0);
  const g = cg.makeCrashGuard({ maxRestarts: 2, windowMs: 60000, now: clock.now });
  const actions = [];
  for (let i = 0; i < 6; i++) {
    clock.t += 50; // tight loop, everything inside one window
    actions.push(g.record("overlay", "oom").action);
  }
  assert.deepStrictEqual(actions, [
    "restart",
    "restart",
    "give-up",
    "give-up",
    "give-up",
    "give-up",
  ]);
});

test("record: every restartable reason consumes the same budget", () => {
  const clock = makeClock(0);
  const g = cg.makeCrashGuard({ maxRestarts: 3, windowMs: 60000, now: clock.now });
  const reasons = ["crashed", "oom", "abnormal-exit", "launch-failed", "integrity-failure"];
  const actions = reasons.map((reason) => {
    clock.t += 10;
    return g.record("overlay", reason).action;
  });
  assert.deepStrictEqual(actions, ["restart", "restart", "restart", "give-up", "give-up"]);
});

// --- rolling window expiry -----------------------------------------------------

test("record: old crashes expire - a crash an hour later restarts again", () => {
  const clock = makeClock(0);
  const g = cg.makeCrashGuard({ maxRestarts: 3, windowMs: 60000, now: clock.now });
  for (const t of [0, 1, 2, 3]) {
    clock.t = t;
    g.record("overlay", "crashed");
  }
  assert.strictEqual(g.state("overlay").remaining, 0); // exhausted
  clock.t = 3600000; // an hour later - everything expired
  const r = g.record("overlay", "crashed");
  assert.strictEqual(r.action, "restart");
  assert.strictEqual(r.count, 1);
});

test("record: expiry boundary - a crash exactly windowMs old is out", () => {
  const clock = makeClock(0);
  const g = cg.makeCrashGuard({ maxRestarts: 1, windowMs: 100, now: clock.now });
  clock.t = 0;
  assert.strictEqual(g.record("overlay", "crashed").action, "restart");
  clock.t = 100; // exactly windowMs later: the t=0 crash has expired
  const r = g.record("overlay", "crashed");
  assert.strictEqual(r.action, "restart");
  assert.strictEqual(r.count, 1);
});

test("record: partial expiry - only in-window crashes count", () => {
  const clock = makeClock(0);
  const g = cg.makeCrashGuard({ maxRestarts: 3, windowMs: 1000, now: clock.now });
  clock.t = 0;
  g.record("overlay", "crashed"); // expired by t=1200
  clock.t = 600;
  g.record("overlay", "crashed"); // still in-window at t=1200
  clock.t = 1200;
  const r = g.record("overlay", "crashed");
  assert.strictEqual(r.count, 2); // t=600 + this one; t=0 expired
  assert.strictEqual(r.action, "restart");
});

// --- per-key independence ------------------------------------------------------

test("record: keys are independent - overlay exhaustion never taxes companion", () => {
  const clock = makeClock(0);
  const g = cg.makeCrashGuard({ maxRestarts: 2, windowMs: 60000, now: clock.now });
  clock.t = 10;
  g.record("overlay", "crashed");
  clock.t = 20;
  g.record("overlay", "crashed");
  clock.t = 30;
  assert.strictEqual(g.record("overlay", "crashed").action, "give-up");
  clock.t = 40;
  const r = g.record("companion", "crashed");
  assert.strictEqual(r.action, "restart");
  assert.strictEqual(r.count, 1);
  assert.strictEqual(r.key, "companion");
  assert.deepStrictEqual(g.state("companion"), { count: 1, remaining: 1 });
});

// --- opts fallback ---------------------------------------------------------------

test("makeCrashGuard: garbage maxRestarts falls back to default 3", () => {
  for (const bad of [0, -1, NaN, Infinity, "junk", null, undefined]) {
    const clock = makeClock(0);
    const g = cg.makeCrashGuard({ maxRestarts: bad, now: clock.now });
    const actions = [];
    for (let i = 0; i < 4; i++) {
      clock.t += 10;
      actions.push(g.record("overlay", "crashed").action);
    }
    assert.deepStrictEqual(
      actions,
      ["restart", "restart", "restart", "give-up"],
      JSON.stringify(bad)
    );
  }
});

test("makeCrashGuard: garbage windowMs falls back to default 60000", () => {
  for (const bad of [0, -5, NaN, Infinity, "junk", null, undefined]) {
    const clock = makeClock(0);
    const g = cg.makeCrashGuard({ maxRestarts: 1, windowMs: bad, now: clock.now });
    // Window floor: a 59999ms-old crash still counts -> give-up.
    clock.t = 0;
    assert.strictEqual(g.record("overlay", "crashed").action, "restart");
    clock.t = 59999;
    assert.strictEqual(g.record("overlay", "crashed").action, "give-up", JSON.stringify(bad));
    // Window ceiling: exactly 60000ms after a lone crash it has expired.
    const g2 = cg.makeCrashGuard({ maxRestarts: 1, windowMs: bad, now: clock.now });
    clock.t = 100000;
    assert.strictEqual(g2.record("overlay", "crashed").action, "restart");
    clock.t = 160000;
    assert.strictEqual(g2.record("overlay", "crashed").action, "restart", JSON.stringify(bad));
  }
});

test("makeCrashGuard: no opts / non-object opts work (defaults + Date.now)", () => {
  for (const opts of [undefined, null, "junk", 42]) {
    const g = cg.makeCrashGuard(opts);
    const r = g.record("overlay", "crashed");
    assert.strictEqual(r.action, "restart", JSON.stringify(opts));
    assert.strictEqual(r.count, 1, JSON.stringify(opts));
  }
});

// --- state(key) -------------------------------------------------------------------

test("state: fresh key -> zero count, full remaining", () => {
  const g = cg.makeCrashGuard({ maxRestarts: 3, now: () => 0 });
  assert.deepStrictEqual(g.state("overlay"), { count: 0, remaining: 3 });
});

test("state: tracks in-window count; remaining clamps at 0 (never negative)", () => {
  const clock = makeClock(0);
  const g = cg.makeCrashGuard({ maxRestarts: 2, windowMs: 60000, now: clock.now });
  clock.t = 10;
  g.record("overlay", "crashed");
  assert.deepStrictEqual(g.state("overlay"), { count: 1, remaining: 1 });
  clock.t = 20;
  g.record("overlay", "crashed");
  assert.deepStrictEqual(g.state("overlay"), { count: 2, remaining: 0 });
  clock.t = 30;
  g.record("overlay", "crashed"); // give-up - still recorded in the window
  assert.deepStrictEqual(g.state("overlay"), { count: 3, remaining: 0 });
});

test("state: prunes by the current clock - count drops once the window passes", () => {
  const clock = makeClock(0);
  const g = cg.makeCrashGuard({ maxRestarts: 3, windowMs: 1000, now: clock.now });
  clock.t = 0;
  g.record("overlay", "crashed");
  assert.deepStrictEqual(g.state("overlay"), { count: 1, remaining: 2 });
  clock.t = 5000;
  assert.deepStrictEqual(g.state("overlay"), { count: 0, remaining: 3 });
});
