// web/js/panels/spike_cue.test.mjs
//
// RC Overlay Doctrine w-spike (ultimate power-spike crossed cue) - pure-logic
// tests. Run with `node --test`.
//
// Only the PURE core is covered (normalize / cross-edge / label / html). The
// DOM-applying wrapper (renderSpikeCue) needs a live document + the
// body[data-shell="overlay"] gate + the transient self-expire timer and is
// exercised in the overlay at runtime; these tests pin the rising-level cross
// that drives the single one-shot pulse so a steady level never re-fires on
// every 2s state tick, and a mid-game attach never spuriously "spikes".

import test from "node:test";
import assert from "node:assert";

import { __test } from "./spike_cue.js";

const { normSpikeLevel, crossedSpike, _spikeLabel, spikeCueHtml, _SPIKE_LEVELS } = __test;

test("normSpikeLevel: garbage / missing -> 0", () => {
  assert.strictEqual(normSpikeLevel(null), 0);
  assert.strictEqual(normSpikeLevel(undefined), 0);
  assert.strictEqual(normSpikeLevel("nope"), 0);
  assert.strictEqual(normSpikeLevel({}), 0);
  assert.strictEqual(normSpikeLevel({ level: "x" }), 0);
});

test("normSpikeLevel: clamps to [0,18], floors floats", () => {
  assert.strictEqual(normSpikeLevel({ level: 6 }), 6);
  assert.strictEqual(normSpikeLevel({ level: 11.9 }), 11);
  assert.strictEqual(normSpikeLevel({ level: 99 }), 18);
  assert.strictEqual(normSpikeLevel({ level: -3 }), 0);
});

test("_SPIKE_LEVELS are the ultimate milestones 6/11/16", () => {
  assert.deepStrictEqual(_SPIKE_LEVELS, [6, 11, 16]);
});

test("crossedSpike: fires the milestone JUST crossed going up", () => {
  assert.strictEqual(crossedSpike(5, 6), 6); // R unlocked
  assert.strictEqual(crossedSpike(10, 11), 11); // R rank 2
  assert.strictEqual(crossedSpike(15, 16), 16); // R rank 3
});

test("crossedSpike: no fire when no milestone is in the step", () => {
  assert.strictEqual(crossedSpike(6, 7), 0);
  assert.strictEqual(crossedSpike(11, 12), 0);
  assert.strictEqual(crossedSpike(16, 17), 0);
});

test("crossedSpike: a steady level never re-fires (the anti-re-pulse case)", () => {
  assert.strictEqual(crossedSpike(6, 6), 0);
  assert.strictEqual(crossedSpike(11, 11), 0);
});

test("crossedSpike: first render / fresh mid-game attach never spikes", () => {
  // prev 0 (null/unseen) must NOT fire even if already past a milestone.
  assert.strictEqual(crossedSpike(0, 12), 0);
  assert.strictEqual(crossedSpike(0, 6), 0);
});

test("crossedSpike: a multi-level jump reports the HIGHEST milestone crossed", () => {
  // a double level-up from 10 -> 12 crosses 11 only.
  assert.strictEqual(crossedSpike(10, 12), 11);
  // a big catch-up 5 -> 12 crosses both 6 and 11 -> report 11 (the latest spike).
  assert.strictEqual(crossedSpike(5, 12), 11);
  // 15 -> 18 crosses 16.
  assert.strictEqual(crossedSpike(15, 18), 16);
});

test("crossedSpike: a level DOWN never fires", () => {
  assert.strictEqual(crossedSpike(11, 6), 0);
});

test("_spikeLabel: the three ult milestones", () => {
  assert.strictEqual(_spikeLabel(6), "ULT ONLINE");
  assert.strictEqual(_spikeLabel(11), "ULT R2");
  assert.strictEqual(_spikeLabel(16), "ULT R3");
});

test("spikeCueHtml: empty string for no milestone", () => {
  assert.strictEqual(spikeCueHtml(0), "");
});

test("spikeCueHtml: a crossed milestone renders the spike chip + label", () => {
  const html = spikeCueHtml(6);
  assert.ok(html.includes("spike-chip"));
  assert.ok(html.includes('data-cue="spike"'));
  assert.ok(html.includes("ULT ONLINE"));
});
