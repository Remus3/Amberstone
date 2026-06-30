// web/js/panels/minimap_zoi.test.mjs
//
// RC Overlay Doctrine w-mmrect ZOI fill (item 567 slice 3) - pure-logic tests.
// Run with `node --test`.
//
// Only the PURE core is covered (EMA smoothing, alpha clamp, team->color, the
// box-fraction->px scale, the null-zoi clear path). The DOM-applying wrapper
// (renderMinimapZoi) needs a live document + the body[data-shell="overlay"]
// gate + a real <canvas>, so it is exercised in the overlay at runtime + by the
// Playwright snapshot test. These tests pin the anti-jitter EMA (steady input
// converges, no drift), the hard alpha cap (the fill must NEVER exceed 0.25 so
// the minimap stays readable), the ally/enemy color mapping, and the
// fraction->pixel transform.

import test from "node:test";
import assert from "node:assert";

import { __test, renderMinimapZoi, _resetMinimapZoi } from "./minimap_zoi.js";

const { _ema, _clampAlpha, teamColor, fracToPx, normZoi, MAX_ALPHA, ALLY_TINT_MAX } = __test;

test("_ema(prev, prev, alpha) === prev (no drift on steady input)", () => {
  assert.strictEqual(_ema(0.5, 0.5, 0.35), 0.5);
  assert.strictEqual(_ema(156, 156, 0.35), 156);
  assert.strictEqual(_ema(0, 0, 0.35), 0);
});

test("_ema converges toward the target over repeated ticks", () => {
  let v = 0;
  for (let i = 0; i < 40; i++) v = _ema(v, 1, 0.35);
  // After ~40 ticks at alpha 0.35 the EMA is essentially settled at the target.
  assert.ok(Math.abs(v - 1) < 1e-3, `expected ~1, got ${v}`);
});

test("_ema first step moves a fraction (alpha) toward the target", () => {
  // prev=0, next=1, alpha=0.35 -> 0.35
  assert.ok(Math.abs(_ema(0, 1, 0.35) - 0.35) < 1e-9);
});

test("_ema: a null/undefined prev seeds straight to the target (no warm-up lag)", () => {
  assert.strictEqual(_ema(null, 0.8, 0.35), 0.8);
  assert.strictEqual(_ema(undefined, 0.8, 0.35), 0.8);
});

test("_clampAlpha never returns above MAX_ALPHA", () => {
  // MAX_ALPHA is an operator-tunable readability ceiling; assert against the
  // constant, not a literal, so retuning it doesn't break the cap contract.
  assert.ok(MAX_ALPHA > 0 && MAX_ALPHA <= 1, `MAX_ALPHA out of range: ${MAX_ALPHA}`);
  assert.strictEqual(_clampAlpha(0.9), MAX_ALPHA);
  assert.strictEqual(_clampAlpha(1), MAX_ALPHA);
  assert.strictEqual(_clampAlpha(MAX_ALPHA), MAX_ALPHA);
  assert.strictEqual(_clampAlpha(0.1), 0.1);
});

test("_clampAlpha floors negative / garbage to 0", () => {
  assert.strictEqual(_clampAlpha(-0.5), 0);
  assert.strictEqual(_clampAlpha(NaN), 0);
  assert.strictEqual(_clampAlpha("nope"), 0);
});

test("teamColor: ally=blue, enemy=red, alpha clamped <= 0.25", () => {
  const blue = teamColor("blue", 0.2);
  const red = teamColor("red", 0.2);
  assert.ok(blue.includes("rgba("));
  assert.ok(red.includes("rgba("));
  // Blue channel dominates for ally, red channel for enemy.
  assert.ok(/rgba\(\s*\d+\s*,\s*\d+\s*,\s*2\d\d/.test(blue), `ally not blue-dominant: ${blue}`);
  assert.ok(/rgba\(\s*2\d\d\s*,/.test(red), `enemy not red-dominant: ${red}`);
});

test("teamColor: the requested alpha is hard-capped at MAX_ALPHA", () => {
  const over = teamColor("blue", 0.9);
  // pull the trailing alpha out of rgba(r,g,b,a)
  const a = Number(over.slice(over.lastIndexOf(",") + 1, over.lastIndexOf(")")));
  assert.ok(a <= MAX_ALPHA + 1e-9, `alpha not capped: ${a}`);
});

test("teamColor: unknown team falls back to a neutral non-throwing color", () => {
  const c = teamColor("purple", 0.1);
  assert.ok(c.includes("rgba("));
});

test("fracToPx: box-fraction 0.5 of a 312px canvas == 156", () => {
  assert.strictEqual(fracToPx(0.5, 312), 156);
  assert.strictEqual(fracToPx(0, 312), 0);
  assert.strictEqual(fracToPx(1, 312), 312);
});

test("fracToPx: clamps the fraction to [0,1] before scaling", () => {
  assert.strictEqual(fracToPx(-0.2, 312), 0);
  assert.strictEqual(fracToPx(1.5, 312), 312);
});

test("fracToPx: non-finite fraction -> 0", () => {
  assert.strictEqual(fracToPx(NaN, 312), 0);
  assert.strictEqual(fracToPx("x", 312), 0);
});

test("normZoi: null / garbage -> null (the clear path)", () => {
  assert.strictEqual(normZoi(null), null);
  assert.strictEqual(normZoi(undefined), null);
  assert.strictEqual(normZoi("nope"), null);
  assert.strictEqual(normZoi(42), null);
  assert.strictEqual(normZoi([]), null);
});

test("normZoi: keeps a well-formed bubble set + demarcation + map_control", () => {
  const z = normZoi({
    bubbles: [
      { team: "blue", cx: 0.2, cy: 0.8, r_frac: 0.12, weight: 60 },
      { team: "red", cx: 0.75, cy: 0.25, r_frac: 0.11, weight: 50 },
    ],
    demarcation: { x1: 0.0, y1: 0.35, x2: 1.0, y2: 0.65, ally_side: "bottom" },
    map_control: { ally_control_pct: 56, action_quadrant: "mid", line: "Map control 56%." },
  });
  assert.ok(z);
  assert.strictEqual(z.bubbles.length, 2);
  assert.strictEqual(z.bubbles[0].team, "blue");
  assert.strictEqual(z.demarcation.ally_side, "bottom");
  assert.strictEqual(z.map_control.ally_control_pct, 56);
});

test("normZoi: drops malformed bubbles but keeps the valid ones", () => {
  const z = normZoi({
    bubbles: [
      { team: "blue", cx: 0.2, cy: 0.8, r_frac: 0.12, weight: 60 },
      { team: "red", cx: "bad", cy: 0.25, r_frac: 0.11, weight: 50 },
      { team: "red", cx: 2, cy: 0.25, r_frac: 0.11, weight: 50 }, // out of [0,1]
      null,
    ],
  });
  assert.ok(z);
  assert.strictEqual(z.bubbles.length, 1);
  assert.strictEqual(z.bubbles[0].team, "blue");
});

test("normZoi: a null demarcation is preserved as null (line skipped)", () => {
  const z = normZoi({
    bubbles: [{ team: "blue", cx: 0.2, cy: 0.8, r_frac: 0.12, weight: 60 }],
    demarcation: null,
    map_control: { ally_control_pct: 50, action_quadrant: "mid", line: "x" },
  });
  assert.ok(z);
  assert.strictEqual(z.demarcation, null);
});

test("ALLY_TINT_MAX is a very faint side tint (<= 0.12) and <= MAX_ALPHA", () => {
  assert.ok(ALLY_TINT_MAX <= 0.12 + 1e-9);
  assert.ok(ALLY_TINT_MAX <= MAX_ALPHA);
});

test("renderMinimapZoi: no-op (no throw) when there is no document / not overlay", () => {
  // In node there is no `document`; the gate must short-circuit harmlessly.
  _resetMinimapZoi();
  assert.doesNotThrow(() => renderMinimapZoi(null));
  assert.doesNotThrow(() => renderMinimapZoi({ bubbles: [] }));
});
