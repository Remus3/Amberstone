// web/js/panels/ward_cue.test.mjs
//
// QA1 overlay ward-ready glyph cue - pure-logic tests. Run with `node --test`.
//
// Only the PURE core is covered here (normalize / signature / rising-edge /
// html). The DOM-applying wrapper (renderWardCue) needs a live document + the
// body[data-shell="overlay"] gate and is exercised in the overlay at runtime;
// these tests pin the edge-detection that drives the single pulse so a steady
// "ready" state never re-pulses on every 2s state tick.

import test from "node:test";
import assert from "node:assert";

import { __test } from "./ward_cue.js";

const { normWardCue, wardCueSig, risingEdges, wardCueActionable, wardCueHtml } = __test;

test("normWardCue: garbage / missing -> the safe all-off default", () => {
  const d = { trinket_ready: false, trinket_id: null, control_ward: false, control_ward_count: 0 };
  assert.deepStrictEqual(normWardCue(null), d);
  assert.deepStrictEqual(normWardCue(undefined), d);
  assert.deepStrictEqual(normWardCue("nope"), d);
  assert.deepStrictEqual(normWardCue({}), d);
});

test("normWardCue: passes through a real cue, coercing types", () => {
  const c = normWardCue({ trinket_ready: true, trinket_id: 3340, control_ward: true, control_ward_count: 2 });
  assert.strictEqual(c.trinket_ready, true);
  assert.strictEqual(c.trinket_id, 3340);
  assert.strictEqual(c.control_ward, true);
  assert.strictEqual(c.control_ward_count, 2);
});

test("wardCueActionable: true when a trinket is ready OR a control ward is held", () => {
  assert.strictEqual(wardCueActionable({ trinket_ready: true }), true);
  assert.strictEqual(wardCueActionable({ control_ward: true }), true);
  assert.strictEqual(wardCueActionable({ trinket_ready: false, control_ward: false }), false);
  assert.strictEqual(wardCueActionable(null), false);
});

test("wardCueSig: changes with the ready flags / id / count, stable otherwise", () => {
  const a = wardCueSig({ trinket_ready: true, trinket_id: 3340, control_ward: true, control_ward_count: 2 });
  const same = wardCueSig({ trinket_ready: true, trinket_id: 3340, control_ward: true, control_ward_count: 2 });
  assert.strictEqual(a, same);
  assert.notStrictEqual(a, wardCueSig({ trinket_ready: false, trinket_id: 3340, control_ward: true, control_ward_count: 2 }));
  assert.notStrictEqual(a, wardCueSig({ trinket_ready: true, trinket_id: 3340, control_ward: true, control_ward_count: 1 }));
});

test("risingEdges: fires ONLY on the not-ready -> ready transition", () => {
  const ready = { trinket_ready: true, control_ward: true };
  const notReady = { trinket_ready: false, control_ward: false };
  // first appearance (no prev) is a rising edge for whatever is ready
  assert.deepStrictEqual(risingEdges(null, ready), { trinket: true, control: true });
  // steady ready -> ready is NOT an edge (this is the key anti-re-pulse case)
  assert.deepStrictEqual(risingEdges(ready, ready), { trinket: false, control: false });
  // not-ready -> ready is an edge
  assert.deepStrictEqual(risingEdges(notReady, ready), { trinket: true, control: true });
  // ready -> not-ready (used it) is NOT an edge
  assert.deepStrictEqual(risingEdges(ready, notReady), { trinket: false, control: false });
});

test("risingEdges: trinket and control are independent", () => {
  const prev = { trinket_ready: true, control_ward: false };
  const cur = { trinket_ready: true, control_ward: true };
  assert.deepStrictEqual(risingEdges(prev, cur), { trinket: false, control: true });
});

test("wardCueHtml: empty string when nothing is actionable", () => {
  assert.strictEqual(wardCueHtml({ trinket_ready: false, control_ward: false }), "");
  assert.strictEqual(wardCueHtml(null), "");
});

test("wardCueHtml: a ready trinket renders a trinket chip", () => {
  const html = wardCueHtml({ trinket_ready: true, trinket_id: 3340, control_ward: false, control_ward_count: 0 });
  assert.ok(html.includes("ward-chip"));
  assert.ok(html.includes("trinket"));
  assert.ok(/ward/i.test(html));
});

test("wardCueHtml: a held control ward renders its count", () => {
  const html = wardCueHtml({ trinket_ready: false, trinket_id: 3363, control_ward: true, control_ward_count: 2 });
  assert.ok(html.includes("control"));
  assert.ok(html.includes("2"));
});

test("wardCueHtml: escapes nothing it does not control but stays ASCII-safe", () => {
  // Defensive: a wild count should not break out of the markup.
  const html = wardCueHtml({ control_ward: true, control_ward_count: "<x>" });
  assert.ok(!html.includes("<x>"));
});
