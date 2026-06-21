// web/js/panels/objective_chips.test.mjs
//
// QA4 overlay objective respawn chips - pure-logic tests. Run with `node --test`.
// The DOM render (renderObjectiveChips) is exercised in the overlay at runtime;
// these pin the ETA math (latest kill + spawn cycle), the formatting, and the
// up-now edge so a glance chip can never show a stale "in 0:30" once it is up.
//
// Live Client carries neutral-objective KILL events (dashboard/_liveclient.py
// objective_events: {name, killer_team, down_at_s}); it carries NO jungle-camp
// events, so QA4 is objective-only (camps are infeasible from this feed, same
// gap as wards). Pre-first-kill there is no chip - the cue appears once an
// objective has been taken and a respawn is pending.

import test from "node:test";
import assert from "node:assert";

import { __test } from "./objective_chips.js";

const { OBJ_CYCLE, objectiveEtas, fmtEta, objectiveChipsHtml } = __test;

test("OBJ_CYCLE matches the codebase spawn-cycle constants", () => {
  assert.strictEqual(OBJ_CYCLE.dragon, 300);
  assert.strictEqual(OBJ_CYCLE.baron, 360);
  assert.strictEqual(OBJ_CYCLE.herald, 360);
});

test("objectiveEtas: empty / garbage / no game clock -> no chips", () => {
  assert.deepStrictEqual(objectiveEtas([], 600), []);
  assert.deepStrictEqual(objectiveEtas(null, 600), []);
  assert.deepStrictEqual(objectiveEtas("nope", 600), []);
  assert.deepStrictEqual(objectiveEtas([{ name: "dragon", down_at_s: 300 }], NaN), []);
});

test("objectiveEtas: a dragon kill yields a respawn ETA = kill + 300", () => {
  // killed at 5:00 (300s); now 6:00 (360s) -> respawn at 600s -> 240s out
  const out = objectiveEtas([{ name: "dragon", down_at_s: 300 }], 360);
  assert.strictEqual(out.length, 1);
  assert.strictEqual(out[0].name, "dragon");
  assert.strictEqual(out[0].etaS, 240);
  assert.strictEqual(out[0].up, false);
});

test("objectiveEtas: an objective already respawned reads UP (eta clamped to 0)", () => {
  // baron killed at 600s, cycle 360 -> respawn 960s; now 1000s -> past due
  const out = objectiveEtas([{ name: "baron", down_at_s: 600 }], 1000);
  assert.strictEqual(out[0].up, true);
  assert.strictEqual(out[0].etaS, 0);
});

test("objectiveEtas: uses the LATEST kill of an objective", () => {
  const events = [
    { name: "dragon", down_at_s: 300 },
    { name: "dragon", down_at_s: 700 }, // most recent
  ];
  // latest 700 + 300 = 1000; now 800 -> 200 out
  const out = objectiveEtas(events, 800);
  assert.strictEqual(out.length, 1);
  assert.strictEqual(out[0].etaS, 200);
});

test("objectiveEtas: orders baron, dragon, herald and includes only taken objectives", () => {
  const events = [
    { name: "dragon", down_at_s: 300 },
    { name: "baron", down_at_s: 400 },
  ];
  const out = objectiveEtas(events, 500);
  assert.deepStrictEqual(out.map((c) => c.name), ["baron", "dragon"]);
  // herald never taken -> absent
  assert.ok(!out.some((c) => c.name === "herald"));
});

test("objectiveEtas: unknown objective names + non-numeric times are ignored", () => {
  const events = [
    { name: "voidgrub", down_at_s: 300 },     // not a tracked objective
    { name: "dragon", down_at_s: "later" },   // non-numeric time
    { name: "baron", down_at_s: 400 },        // the one good event
  ];
  const out = objectiveEtas(events, 450);
  assert.deepStrictEqual(out.map((c) => c.name), ["baron"]);
});

test("fmtEta: M:SS with zero-padded seconds, floored, never negative", () => {
  assert.strictEqual(fmtEta(0), "0:00");
  assert.strictEqual(fmtEta(65), "1:05");
  assert.strictEqual(fmtEta(125.9), "2:05");
  assert.strictEqual(fmtEta(-10), "0:00");
});

test("objectiveChipsHtml: empty list -> empty string", () => {
  assert.strictEqual(objectiveChipsHtml([]), "");
  assert.strictEqual(objectiveChipsHtml(null), "");
});

test("objectiveChipsHtml: renders label + ETA, and UP for a respawned objective", () => {
  const html = objectiveChipsHtml([
    { name: "baron", label: "BARON", etaS: 90, up: false },
    { name: "dragon", label: "DRAKE", etaS: 0, up: true },
  ]);
  assert.ok(html.includes("obj-chip"));
  assert.ok(html.includes("baron"));
  assert.ok(html.includes("BARON"));
  assert.ok(html.includes("1:30"));
  assert.ok(html.includes("DRAKE"));
  assert.ok(html.includes("UP"));
  assert.ok(html.includes("is-up"));
});
