// lane-widget/test/clamp.test.js
//
// clampToContent is PURE - no electron, no disk. These cases are the acceptance
// for "the window is never larger than its content needs nor larger than the
// work area, and never smaller than min" (spec section 4).

"use strict";

const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const { clampToContent, minimumSizeFor } = require("../src/clamp.js");

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

// ------------------------------------------------- the geometry FEEDBACK ----
//
// clampToContent is only half a loop. The other half is the renderer, which
// measures the panel INSIDE the window clampToContent just sized and reports
// that measurement straight back. So the real system is an iterated map
//
//     H_next = clamp(measure(H))
//
// and the only interesting question about it is whether that map has a FIXED
// POINT that still shows the content. A single-shot clamp assertion cannot see
// this at all, which is exactly how the ratchet shipped: every case above this
// line passed while a live run watched the window walk down through 24 sizes in
// 590 ms - 415x344, 328, 320, 308, ... 136, 128 - and settle at 415x126 with an
// EMPTY card grid and the footer still reading "STALE 3".
//
// The two models below are the two measurement halves, written as arithmetic so
// the map can be iterated in a unit test. Neither is a paraphrase of the fix:
// test/render.test.js separately asserts that the SHIPPED widget.css carries no
// viewport-relative height bound and that the SHIPPED reporter never reads the
// viewport, which is what makes NATURAL the model that is actually running.

// widget.css .panel { margin: 8px } on every side.
const MARGIN = 8;
// Everything in .panel that is not the card grid: the 2px top rule, 14/12
// padding, the tab strip, the summary strip and the two 10px column gaps.
// The exact value is not load-bearing - the SHAPE of each map is.
const PANEL_CHROME = 110;
// The legacy .cards { max-height: calc(100vh - 130px) } subtrahend.
const LEGACY_CARDS_CHROME = 130;

// The DISPLAY work area. Fixed hardware, so it is a constant of the system -
// this is the value the new cap is derived from, and the whole reason the new
// map is not a feedback loop.
const AVAIL_HEIGHT = 1040;
const WORK = { x: 0, y: 0, width: 1920, height: AVAIL_HEIGHT };

// THE BUG, as arithmetic. Both maxima are viewport-relative and 100vh IS the
// window height (the window is frameless, so there is no chrome to subtract),
// so every term on the right depends on the height we are trying to compute.
function legacyMeasure(windowHeight, naturalCardsHeight) {
  let cards = Math.min(naturalCardsHeight, windowHeight - LEGACY_CARDS_CHROME);
  if (cards < 0) cards = 0;
  const panelNatural = PANEL_CHROME + cards;
  const panel = Math.min(panelNatural, windowHeight - 2 * MARGIN);
  return panel + 2 * MARGIN;
}

// THE FIX, as arithmetic. windowHeight is not a parameter at all: the cap comes
// from the work area, which no clamp result can move.
function naturalMeasure(_windowHeight, naturalCardsHeight) {
  const panelNatural = PANEL_CHROME + naturalCardsHeight;
  const panel = Math.min(panelNatural, AVAIL_HEIGHT - 2 * MARGIN);
  return panel + 2 * MARGIN;
}

// Feed the clamp its own output N times. Returns the whole sequence so a
// failure can print the ratchet rather than just its floor.
function iterate(measure, naturalCardsHeight, startHeight, steps) {
  const seq = [startHeight];
  let h = startHeight;
  for (let i = 0; i < steps; i += 1) {
    const out = clampToContent({
      requested: { x: 40, y: 40, width: 415, height: h },
      content: { width: 415, height: measure(h, naturalCardsHeight) },
      workArea: WORK,
      min: MIN,
    });
    h = out.height;
    seq.push(h);
  }
  return seq;
}

// The acceptance for defect A, in one place so it can be asserted to PASS for
// the new map and to THROW for the old one.
// STEPS is deliberately far more than convergence needs. The legacy map walks
// down in steps of a few pixels, so a short run would report "still moving"
// rather than the thing that actually matters - the empty grid it settles on.
const STEPS = 400;

function assertStableAndShowsContent(measure, naturalCardsHeight, startHeight) {
  const seq = iterate(measure, naturalCardsHeight, startHeight, STEPS);
  const settled = seq[seq.length - 1];

  // (i) a FIXED POINT: the tail must stop moving. A map that is still changing
  // at step 40 is a ratchet however slowly it turns.
  const tail = seq.slice(-8);
  for (const h of tail) {
    assert.strictEqual(
      h,
      settled,
      `never reached a fixed point - tail ${tail.join(" ")}`
    );
  }

  // (ii) and the fixed point must still SHOW the content: either the whole
  // natural box, or the work area when the content genuinely exceeds it.
  const wanted = Math.min(PANEL_CHROME + naturalCardsHeight + 2 * MARGIN, WORK.height);
  assert.ok(
    settled >= wanted,
    `settled at ${settled} but the content needs ${wanted} - sequence ${seq.join(" ")}`
  );
}

test("iterating the clamp on its own output reaches a fixed point that shows content", () => {
  // A roster that fits the screen, and one that does not.
  assertStableAndShowsContent(naturalMeasure, 420, 352);
  assertStableAndShowsContent(naturalMeasure, 4000, 352);
  // And it does not matter where the previous session left the window: a saved
  // height at the collapsed floor must climb back to the content size.
  assertStableAndShowsContent(naturalMeasure, 420, 126);
  assertStableAndShowsContent(naturalMeasure, 420, 900);
});

test("the viewport-bound measurement FAILS that acceptance - this is the ratchet", () => {
  // Proof the test above discriminates. If this ever stops throwing, the
  // acceptance has been weakened and defect A can ship again unnoticed.
  assert.throws(
    () => assertStableAndShowsContent(legacyMeasure, 420, 352),
    /content needs/,
    "the legacy viewport-bound map must not satisfy the fixed-point acceptance"
  );
});

test("the viewport-bound measurement shrinks monotonically to an empty grid", () => {
  const seq = iterate(legacyMeasure, 420, 352, STEPS);
  // Strictly decreasing until it bottoms out - the measured 590ms walk.
  let sawDecrease = false;
  for (let i = 1; i < seq.length; i += 1) {
    assert.ok(seq[i] <= seq[i - 1], `height grew at step ${i}: ${seq.join(" ")}`);
    if (seq[i] < seq[i - 1]) sawDecrease = true;
  }
  assert.ok(sawDecrease, "expected the legacy map to shrink at all");

  // And the floor it settles on has NO room for a card: PANEL_CHROME plus the
  // margins is the panel with a zero-height grid, which is what 415x126 was.
  const settled = seq[seq.length - 1];
  assert.strictEqual(settled, PANEL_CHROME + 2 * MARGIN);
  assert.ok(settled < PANEL_CHROME + 420 + 2 * MARGIN, "floor still shows content");
});

test("the natural measurement is a fixed point after ONE clamp, from any start", () => {
  // Not merely convergent - convergent in one step, because the map does not
  // read its own previous output. Every start lands on the same height.
  const landed = [126, 352, 668, 900, 1040].map(
    (start) => iterate(naturalMeasure, 420, start, 1)[1]
  );
  for (const h of landed) assert.strictEqual(h, landed[0]);
  assert.strictEqual(landed[0], PANEL_CHROME + 420 + 2 * MARGIN);
});

test("content taller than the work area settles ON the work area, not below it", () => {
  // Requirement (ii) of the fix: the window stops at the screen and the
  // overflow becomes the scroll container's problem, never a silent clip.
  const seq = iterate(naturalMeasure, 4000, 352, 10);
  assert.strictEqual(seq[seq.length - 1], WORK.height);
});

// -------------------------------------------------- the MAXIMIZED window ----
//
// Measured on screen: maximizing the widget left it at 2576x1416 at -8,-8 over
// a 2560x1400 work area, with only 409x1185 of content, and it stayed there
// indefinitely. The arithmetic below was never the problem - clampToContent
// returns the right answer for that rect, as the first test asserts. The defect
// was that Windows DISCARDS setBounds on a maximized window, so applyClamp
// recorded lastAppliedSize, believed it had succeeded, and changed nothing.
//
// main.js cannot be require()d here: it imports electron, which is not a
// dependency of this package and is not installed for `npm test`. So the second
// half is a SOURCE guard - narrow, and comment-stripped so it can only pass on
// the actual calls. Its own positive control is below: if the stripper stops
// stripping, the control fails and every assertion under it is void.

const MAIN_SRC = fs.readFileSync(
  path.join(__dirname, "..", "src", "main.js"),
  "utf8"
);

// The body of a top-level `function NAME() {` up to its closing brace at column
// zero, with every comment removed. Neither function below contains a string
// literal holding "//", so stripping to end-of-line is safe for both.
function codeOf(name) {
  const head = "function " + name + "() {";
  const start = MAIN_SRC.indexOf(head);
  assert.ok(start >= 0, name + " is gone from src/main.js");
  const rest = MAIN_SRC.slice(start + head.length);
  const end = rest.indexOf("\n}\n");
  assert.ok(end >= 0, "could not find the end of " + name);
  return rest
    .slice(0, end)
    .split("\n")
    .map((line) => line.replace(/\/\/.*$/, ""))
    .join("\n");
}

test("the measured maximized rect clamps back to the content box", () => {
  const out = clampToContent({
    requested: { x: -8, y: -8, width: 2576, height: 1416 },
    content: { width: 409, height: 1185 },
    workArea: { x: 0, y: 0, width: 2560, height: 1400 },
    min: MIN,
  });
  assert.strictEqual(out.width, 409);
  assert.strictEqual(out.height, 1185);
  assert.strictEqual(out.x, 0);
  assert.strictEqual(out.y, 0);
});

test("the source guard reads CODE, not the comments around it", () => {
  // The positive control for the two tests below. Those words appear ONLY in
  // applyClampNow's comment block, so seeing them here would mean the stripper
  // failed and a raw-text match had been asserting nothing at all.
  const code = codeOf("applyClampNow");
  assert.ok(
    !/WINDOWS IGNORES/.test(code),
    "comments survived the strip - the guards below prove nothing"
  );
  assert.ok(code.includes("clampMod.clampToContent"), "stripped too much");
});

test("the clamp restores a maximized window before it reads bounds", () => {
  const code = codeOf("applyClampNow");
  assert.ok(
    code.includes("mainWindow.isMaximized()"),
    "applyClampNow no longer checks isMaximized - setBounds is inert while maximized"
  );
  assert.ok(
    code.includes("mainWindow.unmaximize()"),
    "applyClampNow no longer calls unmaximize - setBounds is inert while maximized"
  );
  // Order is load-bearing: bounds read before the restore are the maximized
  // rect, and setBounds issued before the restore is silently discarded.
  assert.ok(
    code.indexOf("mainWindow.unmaximize()") < code.indexOf(".getBounds()"),
    "unmaximize must run BEFORE the bounds are read"
  );
});

// ---------------------------------------------------------------------------
// The DRAG FLOOR (minimumSizeFor).
//
// THE DEFECT: MIN_SIZE.width was 240 while .panel is `width:max-content` with a
// 320px min-width, and max-content does not shrink. With the sixth roster
// participant the panel measures about 499px, so the whole 240..499 band of the
// drag was panel clipped by `body { overflow: hidden }` - the gear on the right
// edge included - until the settle clamp snapped the window back out.
//
// The fix is the floor, NOT a new CSS width: making .panel shrink would mean
// bounding it by its own container, and a container-derived width is the exact
// shape of the height ratchet that shipped on 2026-09-19 (window -> viewport ->
// measured box -> window). These cases are the acceptance for the floor being
// content-derived on width, static on height, and never above the clamp.

test("the drag floor tracks the panel content width, not the 240px constant", () => {
  // The measured regression: six participants, about 499px of content.
  const out = minimumSizeFor({
    content: { width: 499, height: 360 },
    workArea: WA,
    min: MIN,
  });
  assert.strictEqual(out.width, 499);
  assert.notStrictEqual(out.width, MIN.width);
});

test("the drag floor never exceeds the width the clamp would apply", () => {
  // A floor ABOVE the clamped width makes the clamp's own setBounds
  // unsatisfiable, so this is checked where the two can disagree: content
  // wider than the work area.
  for (const content of [
    { width: 499, height: 360 },
    { width: 5000, height: 4000 },
    { width: 320, height: 200 },
    { width: 0, height: 0 },
  ]) {
    for (const work of [WA, { x: 0, y: 0, width: 1280, height: 720 }, { x: 0, y: 0, width: 400, height: 300 }]) {
      const floor = minimumSizeFor({ content, workArea: work, min: MIN });
      const next = clampToContent({
        requested: { x: 0, y: 0, width: 900, height: 700 },
        content,
        workArea: work,
        min: MIN,
      });
      assert.ok(
        floor.width <= next.width,
        `floor ${floor.width} > clamped ${next.width} for content ${content.width} in work ${work.width}`
      );
      assert.ok(floor.height <= next.height, "floor height above the clamped height");
    }
  }
});

test("the drag floor height is the static minimum, never the content height", () => {
  // The height axis is the one that carried the shrink ratchet. It stays a
  // constant here on purpose: .panel is capped by the work area and .cards
  // scrolls, so a short window degrades, where a narrow one clips.
  const tall = minimumSizeFor({
    content: { width: 499, height: 1185 },
    workArea: WA,
    min: MIN,
  });
  assert.strictEqual(tall.height, MIN.height);
});

test("the drag floor falls back to min before the first content report", () => {
  const out = minimumSizeFor({
    content: { width: 0, height: 0 },
    workArea: WA,
    min: MIN,
  });
  assert.deepStrictEqual(out, { width: MIN.width, height: MIN.height });
  // And with nothing at all, rather than throwing.
  const bare = minimumSizeFor();
  assert.ok(bare.width > 0 && bare.height > 0);
});

test("the drag floor is a constant function of the content, not of the window", () => {
  // The anti-ratchet acceptance, in the same iterated-map shape as the height
  // case above: feed the floor back in as the window width and it must not
  // walk. A floor derived from the WINDOW instead of from max-content would
  // shrink on every turn.
  const content = { width: 499, height: 360 };
  let width = 1200;
  for (let i = 0; i < 24; i += 1) {
    const floor = minimumSizeFor({ content, workArea: WA, min: MIN });
    const next = clampToContent({
      requested: { x: 0, y: 0, width, height: 400 },
      content,
      workArea: WA,
      min: { width: floor.width, height: floor.height },
    });
    width = next.width;
    assert.strictEqual(width, 499, `width walked on turn ${i}`);
  }
});

test("the clamp enforces the content-derived floor, not the bare constant", () => {
  // Source guard: the pure function above is worthless if main.js still hands
  // setMinimumSize the static MIN_SIZE.
  const code = codeOf("applyClampNow");
  assert.ok(
    code.includes("clampMod.minimumSizeFor"),
    "applyClampNow no longer computes a content-derived floor"
  );
  assert.ok(
    !/setMinimumSize\(\s*MIN_SIZE\.width/.test(code),
    "applyClampNow still floors the drag at the bare MIN_SIZE - the panel will clip"
  );
  assert.match(
    code,
    /setMinimumSize\(\s*floor\.width,\s*floor\.height\s*\)/,
    "applyClampNow must apply the computed floor"
  );
});

test("a maximized rect can never reach the state file", () => {
  // persistWindowStateNow is synchronous and runs on close / before-quit, so a
  // tray Exit taken while maximized would freeze the bad geometry on disk.
  const code = codeOf("currentGeometry");
  assert.ok(
    code.includes("mainWindow.getNormalBounds()"),
    "currentGeometry must persist the normal-state rect while maximized"
  );
  assert.ok(
    code.includes("mainWindow.isMaximized()"),
    "currentGeometry must decide on isMaximized, not unconditionally"
  );
});
