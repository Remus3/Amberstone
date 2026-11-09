// web/js/panels/objective_gauges.test.mjs
//
// OQ16 objective gauge cluster - pure-logic tests. Run with `node --test`.
// The DOM render (renderObjectiveGauges) is exercised by the rendered
// Chromium harness (tests/snapshot_panels/test_objective_gauges_view.py);
// these pin the schedule mirror of core/event_callouts.py (drake soul
// suppression, kill-anchored respawns, the static cadence + active window,
// the soul-driven Elder, s156 RM-518) and the honest no-data gates - the same
// discipline as objective_chips.test.mjs.

import test from "node:test";
import assert from "node:assert";

import { __test } from "./objective_gauges.js";

const {
  OG_SCHED, computeGauges, _alertTier, _drakeDial, fmtEta, dialHtml, gaugesSig,
} = __test;

function byKey(dials, key) {
  return dials.find((d) => d.key === key);
}

test("OG_SCHED mirrors the core/event_callouts.py constants", () => {
  assert.strictEqual(OG_SCHED.drakeFirstS, 300);
  assert.strictEqual(OG_SCHED.drakeRespawnS, 300);
  assert.strictEqual(OG_SCHED.baronFirstS, 1200);
  assert.strictEqual(OG_SCHED.baronRespawnS, 360);
  assert.strictEqual(OG_SCHED.elderAfterSoulS, 360);
  assert.strictEqual(OG_SCHED.elderRespawnS, 360);
  assert.strictEqual(OG_SCHED.elderNominalS, undefined); // invented 35:00 marker gone
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
  // No soul yet -> Elder cannot exist -> "-" (s156: no invented 35:00 marker).
  const elder = byKey(dials, "elder");
  assert.strictEqual(elder.state, "none");
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
  // Mirror of _last_kill_t(elemental_only=True) - the Elder take must not move
  // the elemental drake timer. Tested on _drakeDial directly: computeGauges now
  // suppresses the whole drake dial once Elder is taken (the redundant-pit rule),
  // which would otherwise mask this internal property.
  const ev = [
    { name: "dragon", killer_team: "ally", down_at_s: 300, dragon_type: "Fire" },
    { name: "dragon", killer_team: "enemy", down_at_s: 900, dragon_type: "Elder" },
  ];
  assert.strictEqual(_drakeDial(ev, 910).state, "up"); // 300+300=600 < 910
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

const SOUL = [
  { name: "dragon", killer_team: "ally", down_at_s: 300, dragon_type: "Fire" },
  { name: "dragon", killer_team: "ally", down_at_s: 650, dragon_type: "Water" },
  { name: "dragon", killer_team: "enemy", down_at_s: 1000, dragon_type: "Air" },
  { name: "dragon", killer_team: "ally", down_at_s: 1300, dragon_type: "Earth" },
  { name: "dragon", killer_team: "ally", down_at_s: 1600, dragon_type: "Hextech" },
];

test("elder: no soul -> '-'; soul secured -> soul_time + 360 countdown", () => {
  const none = computeGauges("sr", { game_time_s: 2000, objective_events: [] }, null);
  assert.strictEqual(byKey(none, "elder").state, "none");
  // Ally takes the 4th elemental at 1600 -> soul secured -> Elder at 1960.
  const pre = computeGauges("sr", { game_time_s: 1700, objective_events: SOUL }, null);
  assert.strictEqual(byKey(pre, "elder").state, "eta");
  assert.strictEqual(byKey(pre, "elder").etaS, 260); // 1600 + 360 - 1700
  const up = computeGauges("sr", { game_time_s: 2000, objective_events: SOUL }, null);
  assert.strictEqual(byKey(up, "elder").state, "up");
});

test("elder: after an Elder take the respawn anchors on the kill (+360)", () => {
  const ev = SOUL.concat([{ name: "dragon", killer_team: "ally", down_at_s: 2000,
                            dragon_type: "Elder" }]);
  const after = computeGauges("sr", { game_time_s: 2100, objective_events: ev }, null);
  assert.strictEqual(byKey(after, "elder").state, "eta");
  assert.strictEqual(byKey(after, "elder").etaS, 260); // 2000 + 360 - 2100
});

test("_soulSecuredAt mirrors _soul_secured_at (sided 4th; unresolved fallback)", () => {
  assert.strictEqual(__test._soulSecuredAt(SOUL), 1600);
  assert.strictEqual(__test._soulSecuredAt([]), null);
  // 3 ally + 1 enemy: nobody has 4 -> no soul.
  assert.strictEqual(__test._soulSecuredAt(SOUL.slice(0, 4)), null);
  // Unresolved killers: the 4th elemental overall counts (RM-307 fallback).
  const unk = SOUL.slice(0, 4).map((e) => ({ ...e, killer_team: "unknown" }));
  assert.strictEqual(__test._soulSecuredAt(unk), 1300);
});

test("drake dial suppressed to '-' once Elder is up or taken (redundant pit)", () => {
  // Soul secured and Elder spawned -> the drake pit is Elder, so the
  // elemental dial is redundant (operator 2026-07-05).
  const elderUp = computeGauges("sr", { game_time_s: 2000, objective_events: SOUL });
  assert.strictEqual(byKey(elderUp, "elder").state, "up");
  assert.strictEqual(byKey(elderUp, "drake").state, "none");
  // Elder taken -> drake stays suppressed after the kill.
  const ev = [{ name: "dragon", killer_team: "ally", down_at_s: 2200,
                dragon_type: "Elder" }];
  const elderDead = computeGauges("sr", { game_time_s: 2300, objective_events: ev });
  assert.strictEqual(byKey(elderDead, "drake").state, "none");
  // Early game (no Elder yet) -> the drake dial is NOT suppressed.
  const early = computeGauges("sr", { game_time_s: 60, objective_events: [] });
  assert.notStrictEqual(byKey(early, "drake").state, "none");
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

// --- double-alert cadence (BACKLOG "Overlay HUD micro-lifts") -----------------

test("OG_SCHED carries the 90s / 10s double-alert thresholds", () => {
  assert.strictEqual(OG_SCHED.alertSoonS, 90);
  assert.strictEqual(OG_SCHED.alertImminentS, 10);
});

test("_alertTier: two escalations, inclusive at each boundary", () => {
  assert.strictEqual(_alertTier("eta", 300), "");
  assert.strictEqual(_alertTier("eta", 91), "");
  assert.strictEqual(_alertTier("eta", 90), "soon");
  assert.strictEqual(_alertTier("eta", 11), "soon");
  assert.strictEqual(_alertTier("eta", 10), "imminent");
  assert.strictEqual(_alertTier("eta", 0.5), "imminent");
});

test("_alertTier: only a counting-down dial alerts", () => {
  // UP is already the loud green state; "-" has no clock. Neither escalates.
  assert.strictEqual(_alertTier("up", 0), "");
  assert.strictEqual(_alertTier("none", 0), "");
  // A non-positive or junk eta never alerts (no fabricated urgency).
  assert.strictEqual(_alertTier("eta", 0), "");
  assert.strictEqual(_alertTier("eta", -5), "");
  assert.strictEqual(_alertTier("eta", "x"), "");
});

test("computeGauges: the alert tier rides the live dials", () => {
  // Baron static one-shot at 1200: at 1150 the eta is 50s -> "soon".
  const soon = computeGauges("sr", { game_time_s: 1150, objective_events: [] });
  assert.strictEqual(byKey(soon, "baron").state, "eta");
  assert.strictEqual(byKey(soon, "baron").alert, "soon");
  // At 1195 the eta is 5s -> "imminent".
  const imm = computeGauges("sr", { game_time_s: 1195, objective_events: [] });
  assert.strictEqual(byKey(imm, "baron").alert, "imminent");
  // Far out -> quiet.
  const quiet = computeGauges("sr", { game_time_s: 60, objective_events: [] });
  assert.strictEqual(byKey(quiet, "baron").alert, "");
  // An UP dial never carries an alert.
  const up = computeGauges("sr", { game_time_s: 1210, objective_events: [] });
  assert.strictEqual(byKey(up, "baron").state, "up");
  assert.strictEqual(byKey(up, "baron").alert, "");
});

test("dialHtml emits data-og-alert; gaugesSig separates the tiers", () => {
  const d = (alert) => ({
    key: "baron", label: "BARON", state: "eta", etaS: 50, frac: 0.9, alert,
  });
  assert.ok(dialHtml(d("soon")).includes('data-og-alert="soon"'));
  assert.ok(dialHtml(d("imminent")).includes('data-og-alert="imminent"'));
  assert.ok(dialHtml(d("")).includes('data-og-alert=""'));
  // A dial descriptor with no alert key at all still renders (defensive).
  const bare = dialHtml({ key: "drake", label: "DRAKE", state: "up", etaS: 0, frac: 1 });
  assert.ok(bare.includes('data-og-alert=""'));
  // The sig must change when only the tier changes, or the DOM would keep a
  // stale alert class through a threshold crossing.
  assert.notStrictEqual(gaugesSig([d("soon")]), gaugesSig([d("imminent")]));
});
