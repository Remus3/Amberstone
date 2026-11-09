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
  for (const id of ["w-call", "w-callouts", "w-lead", "w-stats"]) {
    assert.ok(!TALL_IDS.has(id), `${id} should be free-placed, not bottom-snapped`);
  }
  // The flag is sourced from the registry, so the set must match it exactly.
  const flagged = WIDGETS.filter((w) => w.tall).map((w) => w.id);
  assert.deepStrictEqual([...TALL_IDS].sort(), flagged.sort());
});

// S144-U-283: the floor a bottom-anchored tall widget stops at, under a visible
// primary widget (w-call) sharing its column. Boxes are design px.
test("_tallFloorTop stops the grown box TALL_FLOOR_GAP below a primary widget in its column", () => {
  const { _tallFloorTop, TALL_FLOOR_GAP } = _internals;
  assert.strictEqual(TALL_FLOOR_GAP, 12);
  // w-build x 70..482, bottom anchor 1064; w-call x 180..390, y 130..320.
  const call = { left: 180, right: 390, top: 130, bottom: 320 };
  assert.strictEqual(_tallFloorTop(70, 482, 1064, [call]), 332);
  // The lowest of several primary boxes wins.
  const lower = { left: 100, right: 200, top: 300, bottom: 400 };
  assert.strictEqual(_tallFloorTop(70, 482, 1064, [call, lower]), 412);
});

test("_tallFloorTop ignores a primary widget outside the column, below the anchor, or too low to leave room", () => {
  const { _tallFloorTop, TALL_MIN_H } = _internals;
  // Another column (w-call dragged right of w-build's 482 edge).
  assert.strictEqual(_tallFloorTop(70, 482, 1064, [{ left: 482, right: 692, top: 130, bottom: 320 }]), null);
  // Starts below the anchor.
  assert.strictEqual(_tallFloorTop(70, 482, 1064, [{ left: 180, right: 390, top: 1070, bottom: 1075 }]), null);
  // Leaves less than TALL_MIN_H of room: the operator put it there, ignore it.
  const low = { left: 180, right: 390, top: 700, bottom: 1064 - TALL_MIN_H - 12 + 1 };
  assert.strictEqual(_tallFloorTop(70, 482, 1064, [low]), null);
  // Exactly TALL_MIN_H of room still counts.
  const edge = { left: 180, right: 390, top: 700, bottom: 1064 - TALL_MIN_H - 12 };
  assert.strictEqual(_tallFloorTop(70, 482, 1064, [edge]), 1064 - TALL_MIN_H);
  // No boxes / junk entries: no floor.
  assert.strictEqual(_tallFloorTop(70, 482, 1064, []), null);
  assert.strictEqual(_tallFloorTop(70, 482, 1064, [null, undefined]), null);
});
