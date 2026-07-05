// web/js/panels/objective_gauges.test.mjs
//
// OQ16 objective gauge cluster - pure-logic tests. Run with `node --test`.
// The DOM render (renderObjectiveGauges) is exercised by the rendered
// Chromium harness (tests/snapshot_panels/test_objective_gauges_view.py);
// these pin the schedule mirror of core/event_callouts.py (drake soul
// suppression, kill-anchored respawns, the static cadence + active window,
// the elder nominal one-shot) and the honest no-data gates - the same
// discipline as objective_chips.test.mjs.

import test from "node:test";
import assert from "node:assert";

import { __test } from "./objective_gauges.js";

const { OG_SCHED, computeGauges, fmtEta, dialHtml, gaugesSig } = __test;

function byKey(dials, key) {
  return dials.find((d) => d.key === key);
}

test("OG_SCHED mirrors the core/event_callouts.py constants", () => {
  assert.strictEqual(OG_SCHED.drakeFirstS, 300);
  assert.strictEqual(OG_SCHED.drakeRespawnS, 300);
  assert.strictEqual(OG_SCHED.baronFirstS, 1200);
  assert.strictEqual(OG_SCHED.baronRespawnS, 360);
  assert.strictEqual(OG_SCHED.elderNominalS, 2100);
  assert.strictEqual(OG_SCHED.activeWindowS, 30);
  assert.strictEqual(OG_SCHED.soulSecuredStacks, 4);
});

test("computeGauges: honest no-data whole-widget gates", () => {
  // Not SR -> null (ARAM/Arena have no epic objectives).
  assert.strictEqual(computeGauges("aram", { game_time_s: 300 }, null), null);
  assert.strictEqual(computeGauges("", { game_time_s: 300 }, null), null);
  // SR but no live game clock -> null.
  assert.strictEqual(computeGauges("sr", null, null), null);
  assert.strictEqual(computeGauges("sr", {}, null), null);
  assert.strictEqual(computeGauges("sr", { game_time_s: "x" }, null), null);
});

test("computeGauges: early SR game - static first-spawn countdowns", () => {
  const dials = computeGauges("sr", { game_time_s: 60, objective_events: [] });
  assert.strictEqual(dials.length, 3);
  const drake = byKey(dials, "drake");
  assert.strictEqual(drake.state, "eta");
  assert.strictEqual(drake.etaS, 240); // 300 - 60
  const baron = byKey(dials, "baron");
  assert.strictEqual(baron.state, "eta");
  assert.strictEqual(baron.etaS, 1140); // 1200 - 60
  const elder = byKey(dials, "elder");
  assert.strictEqual(elder.state, "eta");
  assert.strictEqual(elder.etaS, 2040); // 2100 - 60
});

test("drake: kill-anchored respawn = last elemental kill + 300", () => {
  const ev = [{ name: "dragon", killer_team: "ally", down_at_s: 300, dragon_type: "Fire" }];
  const dials = computeGauges("sr", { game_time_s: 360, objective_events: ev }, null);
  const drake = byKey(dials, "drake");
  assert.strictEqual(drake.state, "eta");
  assert.strictEqual(drake.etaS, 240); // 300 + 300 - 360
  // Once past the anchor the pit really is up - UP until the next kill event.
  const up = computeGauges("sr", { game_time_s: 700, objective_events: ev }, null);
  assert.strictEqual(byKey(up, "drake").state, "up");
  assert.strictEqual(byKey(up, "drake").frac, 1);
});

test("drake: an Elder kill is NOT an elemental respawn anchor", () => {
  // Mirror of _last_kill_t(elemental_only=True) - the Elder take must not
  // move the elemental drake timer.
  const ev = [
    { name: "dragon", killer_team: "ally", down_at_s: 300, dragon_type: "Fire" },
    { name: "dragon", killer_team: "enemy", down_at_s: 900, dragon_type: "Elder" },
  ];
  const dials = computeGauges("sr", { game_time_s: 910, objective_events: ev }, null);
  assert.strictEqual(byKey(dials, "drake").state, "up"); // 300+300=600 < 910
});

test("drake: soul secured (4 elemental) suppresses the dial to '-'", () => {
  const ev = [];
  for (let i = 0; i < 4; i++) {
    ev.push({ name: "dragon", killer_team: "ally", down_at_s: 300 + i * 320,
              dragon_type: "Fire" });
  }
  const dials = computeGauges("sr", { game_time_s: 1600, objective_events: ev }, null);
  assert.strictEqual(byKey(dials, "drake").state, "none");
  assert.strictEqual(byKey(dials, "drake").frac, 0);
});

test("drake static cadence: UP inside the 30s active window, then next spawn", () => {
  // No kill events ever recorded; gt 310 is 10s past the 300 static spawn.
  const inWin = computeGauges("sr", { game_time_s: 310, objective_events: [] }, null);
  assert.strictEqual(byKey(inWin, "drake").state, "up");
  // 340 is past the window -> counts to the next cadence boundary (600).
  const past = computeGauges("sr", { game_time_s: 340, objective_events: [] }, null);
  assert.strictEqual(byKey(past, "drake").state, "eta");
  assert.strictEqual(byKey(past, "drake").etaS, 260);
});

test("baron: kill-anchored respawn + static one-shot window", () => {
  const ev = [{ name: "baron", killer_team: "enemy", down_at_s: 1300 }];
  const dials = computeGauges("sr", { game_time_s: 1400, objective_events: ev }, null);
  assert.strictEqual(byKey(dials, "baron").etaS, 260); // 1300 + 360 - 1400
  // Static: UP just after 20:00 with no kill; "-" once long past (ec.py:334).
  const up = computeGauges("sr", { game_time_s: 1210, objective_events: [] }, null);
  assert.strictEqual(byKey(up, "baron").state, "up");
  const dropped = computeGauges("sr", { game_time_s: 1300, objective_events: [] }, null);
  assert.strictEqual(byKey(dropped, "baron").state, "none");
});

test("elder: nominal one-shot; post-kill has no canonical timer -> '-'", () => {
  const nominal = computeGauges("sr", { game_time_s: 2000, objective_events: [] }, null);
  assert.strictEqual(byKey(nominal, "elder").etaS, 100);
  const ev = [{ name: "dragon", killer_team: "ally", down_at_s: 2200,
                dragon_type: "Elder" }];
  const after = computeGauges("sr", { game_time_s: 2300, objective_events: ev }, null);
  assert.strictEqual(byKey(after, "elder").state, "none");
});

test("fmtEta: M:SS floored, never negative", () => {
  assert.strictEqual(fmtEta(240), "4:00");
  assert.strictEqual(fmtEta(90.7), "1:30");
  assert.strictEqual(fmtEta(0), "0:00");
  assert.strictEqual(fmtEta(-12), "0:00");
});

test("dialHtml: states render UP / '-' / M:SS with the state attribute", () => {
  const up = dialHtml({ key: "drake", label: "DRAKE", state: "up", etaS: 0, frac: 1 });
  assert.ok(up.includes('data-og-state="up"'));
  assert.ok(up.includes(">UP<"));
  const none = dialHtml({ key: "elder", label: "ELDER", state: "none", etaS: 0, frac: 0 });
  assert.ok(none.includes(">-<"));
  const eta = dialHtml({ key: "baron", label: "BARON", state: "eta", etaS: 192, frac: 0.5 });
  assert.ok(eta.includes(">3:12<"));
  assert.ok(eta.includes('stroke-dasharray="113.1 226.19"'));
});

test("gaugesSig: stable for an unchanged tick", () => {
  const dials = computeGauges("sr", { game_time_s: 60, objective_events: [] }, null);
  assert.strictEqual(gaugesSig(dials), gaugesSig(dials.map((d) => ({ ...d }))));
});
