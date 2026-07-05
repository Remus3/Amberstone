// web/js/panels/spike_curve.test.mjs
//
// R81 F1 - early/mid/late phase-strength strip on the active-match sparkline.
// Pure-logic + render tests for the phase strip added beneath the spike-curve
// sparkline. Run with `node --test`.
//
// renderSpikeCurve only touches parentEl.{id, clientWidth, dataset, innerHTML}
// so a minimal fake element (no jsdom) exercises the full innerHTML write. The
// key contract pinned here: the strip paints in the SAME innerHTML assignment
// as the SVG, and a missing / malformed ctx.phases appends NOTHING (fail-soft,
// sparkline byte-identical to the pre-R81 render). ASCII only.

import test from "node:test";
import assert from "node:assert";

import { renderSpikeCurve, __test } from "./spike_curve.js";

const { _phaseStrip, _validPhaseSide } = __test;

// Minimal DOM stand-in: renderSpikeCurve writes id/clientWidth/dataset/innerHTML.
function fakeEl(id) {
  return { id: id || "am-spike-curve", clientWidth: 320, dataset: {}, innerHTML: "" };
}

// Two non-degenerate curves so the render takes the SVG (not empty) branch.
function curve() {
  const out = [];
  for (let m = 0; m <= 40; m++) out.push({ minute: m, power: 100 + m });
  return out;
}

const PHASES = {
  ally: { early: "green", mid: "yellow", late: "red" },
  enemy: { early: "red", mid: "yellow", late: "green" },
};

test("_validPhaseSide: accepts a full valid color triple", () => {
  assert.strictEqual(_validPhaseSide({ early: "green", mid: "yellow", late: "red" }), true);
});

test("_validPhaseSide: rejects missing / bad / non-object sides", () => {
  assert.strictEqual(_validPhaseSide(null), false);
  assert.strictEqual(_validPhaseSide(undefined), false);
  assert.strictEqual(_validPhaseSide({ early: "green", mid: "yellow" }), false); // missing late
  assert.strictEqual(_validPhaseSide({ early: "blue", mid: "yellow", late: "red" }), false); // bad color
  assert.strictEqual(_validPhaseSide("green"), false);
});

test("_phaseStrip: null / malformed -> empty string (append nothing)", () => {
  assert.strictEqual(_phaseStrip(null), "");
  assert.strictEqual(_phaseStrip(undefined), "");
  assert.strictEqual(_phaseStrip({}), "");
  assert.strictEqual(_phaseStrip({ ally: PHASES.ally }), ""); // enemy missing
  assert.strictEqual(_phaseStrip({ ally: { early: "green" }, enemy: PHASES.enemy }), "");
});

test("_phaseStrip: valid phases -> 2 rows, right color classes on right cells", () => {
  const html = _phaseStrip(PHASES);
  assert.ok(html.includes("spk-phases"));
  assert.ok(html.includes("You"));
  assert.ok(html.includes("Enemy"));
  // ally early = green, late = red; enemy early = red, late = green.
  assert.ok(html.includes("spk-phase-green"));
  assert.ok(html.includes("spk-phase-yellow"));
  assert.ok(html.includes("spk-phase-red"));
  // Cell labels E / M / L present.
  assert.ok(html.includes(">E</span>"));
  assert.ok(html.includes(">M</span>"));
  assert.ok(html.includes(">L</span>"));
  // Hover titles map color -> word.
  assert.ok(html.includes('title="early: strong"')); // ally early green
  assert.ok(html.includes('title="late: weak"'));     // ally late red
  assert.ok(html.includes('title="mid: even"'));       // yellow
});

test("_phaseStrip: exactly two rows rendered (You then Enemy)", () => {
  const html = _phaseStrip(PHASES);
  const rows = html.split("spk-phase-row").length - 1;
  assert.strictEqual(rows, 2);
  assert.ok(html.indexOf("You") < html.indexOf("Enemy"), "You row before Enemy row");
});

test("render: phases present -> sparkline AND strip in one innerHTML write", () => {
  const el = fakeEl();
  renderSpikeCurve(el, curve(), curve(), { ally: 20, enemy: 20 }, 15, {
    item_minutes: [],
    phases: PHASES,
  });
  assert.ok(el.innerHTML.includes("<svg"), "sparkline SVG present");
  assert.ok(el.innerHTML.includes("spk-phases"), "phase strip present");
  assert.strictEqual(el.dataset.spkState, "ready");
});

test("render: phases ABSENT -> byte-identical to no-phases; NO .spk-phases", () => {
  const withoutKey = fakeEl();
  renderSpikeCurve(withoutKey, curve(), curve(), { ally: 20, enemy: 20 }, 15, {
    item_minutes: [],
  });
  const nullPhases = fakeEl();
  renderSpikeCurve(nullPhases, curve(), curve(), { ally: 20, enemy: 20 }, 15, {
    item_minutes: [],
    phases: null,
  });
  // Fail-soft: no strip at all.
  assert.ok(!withoutKey.innerHTML.includes("spk-phases"), "no strip when phases absent");
  assert.ok(!nullPhases.innerHTML.includes("spk-phases"), "no strip when phases null");
  // And the two absent-phase renders are byte-identical to each other.
  assert.strictEqual(withoutKey.innerHTML, nullPhases.innerHTML);
});

test("render: malformed phases -> fail-soft, no strip, sparkline intact", () => {
  const el = fakeEl();
  renderSpikeCurve(el, curve(), curve(), { ally: 20, enemy: 20 }, 15, {
    item_minutes: [],
    phases: { ally: { early: "green" }, enemy: PHASES.enemy }, // ally incomplete
  });
  assert.ok(el.innerHTML.includes("<svg"), "sparkline still renders");
  assert.ok(!el.innerHTML.includes("spk-phases"), "malformed phases append nothing");
});

test("render: phases-present vs phases-absent produce different innerHTML (repaint)", () => {
  const absent = fakeEl();
  renderSpikeCurve(absent, curve(), curve(), { ally: 20, enemy: 20 }, 15, { item_minutes: [] });
  const present = fakeEl();
  renderSpikeCurve(present, curve(), curve(), { ally: 20, enemy: 20 }, 15, {
    item_minutes: [],
    phases: PHASES,
  });
  assert.notStrictEqual(absent.innerHTML, present.innerHTML);
});
