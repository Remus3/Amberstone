// web/js/lib/overlay_layout.test.mjs
//
// Pure-logic tests for the widget placement clamp + the tall-only bottom-snap
// (operator 2026-06-29: panels dragged near the minimap flung to the bottom and
// became un-retrievable). Run with `node --test`. The DOM-applying paths
// (_applyPos / the drag handlers) are exercised by the Playwright overlay tests;
// here we pin the pure clamp math + the tall-widget registry flag.

import test from "node:test";
import assert from "node:assert";

import { _internals } from "./overlay_layout.js";

const { _clampXY, MIN_VISIBLE, TALL_IDS, WIDGETS } = _internals;

test("_clampXY keeps the top-left on-screen (within [0, dim - MIN_VISIBLE])", () => {
  const W = 1920;
  const H = 1080;
  // Way off the bottom-right (the minimap corner) - must be pulled back so the
  // handle stays grabbable.
  const c = _clampXY(5000, 5000, W, H);
  assert.strictEqual(c.x, W - MIN_VISIBLE);
  assert.strictEqual(c.y, H - MIN_VISIBLE);
});

test("_clampXY pulls negative coords back to the origin edge", () => {
  const c = _clampXY(-300, -50, 1920, 1080);
  assert.strictEqual(c.x, 0);
  assert.strictEqual(c.y, 0);
});

test("_clampXY leaves an in-bounds position untouched", () => {
  const c = _clampXY(400, 300, 1920, 1080);
  assert.strictEqual(c.x, 400);
  assert.strictEqual(c.y, 300);
});

test("_clampXY coerces non-finite input to 0", () => {
  const c = _clampXY(NaN, undefined, 1920, 1080);
  assert.strictEqual(c.x, 0);
  assert.strictEqual(c.y, 0);
});

test("_clampXY never lets the max bound go negative on a tiny viewport", () => {
  const c = _clampXY(10, 10, 20, 20); // W,H < MIN_VISIBLE
  assert.strictEqual(c.x, 0);
  assert.strictEqual(c.y, 0);
});

test("only the tall BUILD panel carries the bottom-snap flag", () => {
  assert.ok(TALL_IDS.has("w-build"), "BUILD must keep the bottom-corner snap");
  // Sibling panels are free-placed - they must NOT be in the tall set.
  for (const id of ["w-call", "w-threat", "w-callouts", "w-lead", "w-stats"]) {
    assert.ok(!TALL_IDS.has(id), `${id} should be free-placed, not bottom-snapped`);
  }
  // The flag is sourced from the registry, so the set must match it exactly.
  const flagged = WIDGETS.filter((w) => w.tall).map((w) => w.id);
  assert.deepStrictEqual([...TALL_IDS].sort(), flagged.sort());
});
