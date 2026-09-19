// lane-widget/test/clamp.test.js
//
// clampToContent is PURE - no electron, no disk. These cases are the acceptance
// for "the window is never larger than its content needs nor larger than the
// work area, and never smaller than min" (spec section 4).

"use strict";

const test = require("node:test");
const assert = require("node:assert");

const { clampToContent } = require("../src/clamp.js");

const WA = { x: 0, y: 0, width: 1920, height: 1080 };
const MIN = { width: 240, height: 120 };

test("content sized inside the work area wins over the request", () => {
  const out = clampToContent({
    requested: { width: 900, height: 900 },
    content: { width: 420, height: 300 },
    workArea: WA,
    min: MIN,
  });
  assert.strictEqual(out.width, 420);
  assert.strictEqual(out.height, 300);
});

test("content larger than the work area is capped to the work area", () => {
  const out = clampToContent({
    requested: { width: 400, height: 400 },
    content: { width: 5000, height: 4000 },
    workArea: { x: 0, y: 0, width: 1280, height: 720 },
    min: MIN,
  });
  assert.strictEqual(out.width, 1280);
  assert.strictEqual(out.height, 720);
});

test("content smaller than min is raised to min", () => {
  const out = clampToContent({
    requested: { width: 300, height: 300 },
    content: { width: 10, height: 4 },
    workArea: WA,
    min: MIN,
  });
  assert.strictEqual(out.width, MIN.width);
  assert.strictEqual(out.height, MIN.height);
});

test("a request smaller than the content does not clip the content", () => {
  const out = clampToContent({
    requested: { width: 260, height: 130 },
    content: { width: 640, height: 480 },
    workArea: WA,
    min: MIN,
  });
  assert.strictEqual(out.width, 640);
  assert.strictEqual(out.height, 480);
});

test("a request larger than the work area is capped", () => {
  const out = clampToContent({
    requested: { width: 9999, height: 9999 },
    content: { width: 0, height: 0 },
    workArea: { x: 0, y: 0, width: 800, height: 600 },
    min: MIN,
  });
  assert.strictEqual(out.width, 800);
  assert.strictEqual(out.height, 600);
});

test("zero content falls back to the request", () => {
  const out = clampToContent({
    requested: { width: 500, height: 400 },
    content: { width: 0, height: 0 },
    workArea: WA,
    min: MIN,
  });
  assert.strictEqual(out.width, 500);
  assert.strictEqual(out.height, 400);
});

test("negative and non-finite inputs never escape min", () => {
  const out = clampToContent({
    requested: { width: -100, height: Number.NaN },
    content: { width: -5, height: Number.POSITIVE_INFINITY },
    workArea: WA,
    min: MIN,
  });
  assert.strictEqual(out.width, MIN.width);
  assert.strictEqual(out.height, MIN.height);
});

test("everything missing still returns finite positive numbers", () => {
  const out = clampToContent({});
  assert.ok(Number.isFinite(out.width) && out.width > 0, "width finite positive");
  assert.ok(Number.isFinite(out.height) && out.height > 0, "height finite positive");
});

test("min wins when the work area is absurdly small", () => {
  const out = clampToContent({
    requested: { width: 100, height: 100 },
    content: { width: 100, height: 100 },
    workArea: { x: 0, y: 0, width: 20, height: 20 },
    min: MIN,
  });
  assert.strictEqual(out.width, MIN.width);
  assert.strictEqual(out.height, MIN.height);
});

test("a finite x/y is kept inside the work area", () => {
  const out = clampToContent({
    requested: { x: 5000, y: -400, width: 300, height: 200 },
    content: { width: 300, height: 200 },
    workArea: { x: 100, y: 50, width: 1000, height: 800 },
    min: MIN,
  });
  assert.strictEqual(out.x, 100 + 1000 - 300);
  assert.strictEqual(out.y, 50);
});

test("a missing x/y is reported as null so the caller can centre", () => {
  const out = clampToContent({
    requested: { width: 300, height: 200 },
    content: { width: 300, height: 200 },
    workArea: WA,
    min: MIN,
  });
  assert.strictEqual(out.x, null);
  assert.strictEqual(out.y, null);
});

test("results are integers", () => {
  const out = clampToContent({
    requested: { x: 10.4, y: 20.6, width: 301.7, height: 200.2 },
    content: { width: 301.7, height: 200.2 },
    workArea: WA,
    min: MIN,
  });
  assert.strictEqual(out.width, Math.round(301.7));
  assert.strictEqual(out.height, Math.round(200.2));
  assert.strictEqual(out.x, 10);
  assert.strictEqual(out.y, 21);
});
