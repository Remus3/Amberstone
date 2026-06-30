// web/js/panels/minimap_rect.test.mjs
//
// RC Overlay Doctrine w-mmrect placement - pure-logic tests. Run with
// `node --test`.
//
// Regression guard for the 2026-06-29 minimap-misalignment bug: the box was
// positioned in raw 1920x1080 design px and inherited the body zoom (ovscale - a
// DPI/readability knob clamped [0.8,1.6], NOT the design->native ratio), so on a
// 2560x1440 game it rendered up-and-left of + smaller than the real minimap, and
// the dots/ZOI rode the misplaced box. The fix places the box by WINDOW FRACTION
// and cancels the inherited zoom (zoom=1/ovscale) so it lands pixel-exact on the
// native minimap at ANY ovscale. These pin that placement math.

import test from "node:test";
import assert from "node:assert";

import { __test } from "./minimap_rect.js";

const { normRect, _placement, DESIGN_W, DESIGN_H } = __test;

// The live-measured calibration rect at MinimapScale=1.62 on the 1920x1080
// design canvas (core/minimap_geometry): a 312px square at (1600, 761).
const CAL = { x: 1600, y: 761, w: 312, h: 312, flip: false };

function approx(a, b, eps = 0.6) {
  assert.ok(Math.abs(a - b) <= eps, `expected ~${b}, got ${a}`);
}

test("identity when the window equals the design canvas (1920x1080, zoom 1)", () => {
  const p = _placement(CAL, DESIGN_W, DESIGN_H, 1);
  approx(p.left, 1600);
  approx(p.top, 761);
  approx(p.width, 312);
  approx(p.height, 312);
  assert.strictEqual(p.zoom, 1);
});

test("2560x1440 native: box lands on the real bottom-right minimap", () => {
  // x/1920*2560 = 2133.3, y/1080*1440 = 1014.7, 312/1920*2560 = 416.
  const p = _placement(CAL, 2560, 1440, 1);
  approx(p.left, 2133.3);
  approx(p.top, 1014.7);
  approx(p.width, 416);
  approx(p.height, 416);
});

test("placement is INVARIANT to ovscale (the core bug): only zoom changes", () => {
  // The whole bug was the box scaling with ovscale. Across the full [0.8,1.6]
  // band the on-screen left/top/width/height must NOT move; only the cancelling
  // zoom factor (1/ovscale) changes.
  const base = _placement(CAL, 2560, 1440, 1);
  for (const ov of [0.8, 1.0, 1.25, 1.6]) {
    const p = _placement(CAL, 2560, 1440, ov);
    approx(p.left, base.left);
    approx(p.top, base.top);
    approx(p.width, base.width);
    approx(p.height, base.height);
    approx(p.zoom, 1 / ov, 1e-9);
  }
});

test("a bad/zero zoom degrades to 1 (never NaN/Infinity placement)", () => {
  for (const bad of [0, -1, NaN, undefined]) {
    const p = _placement(CAL, 2560, 1440, bad);
    assert.strictEqual(p.zoom, 1);
    assert.ok(Number.isFinite(p.left) && Number.isFinite(p.width));
  }
});

test("normRect still coerces a clean rect and rejects garbage", () => {
  assert.deepStrictEqual(normRect({ x: 1600, y: 761, w: 312, h: 312, flip: false }),
    { x: 1600, y: 761, w: 312, h: 312, flip: false });
  assert.strictEqual(normRect(null), null);
  assert.strictEqual(normRect({ x: -1, y: 0, w: 10, h: 10 }), null);
  assert.strictEqual(normRect({ x: 0, y: 0, w: 0, h: 10 }), null);
});
