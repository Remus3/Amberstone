// web/js/panels/active_match_map_badge_tag.test.mjs
//
// S144-U-231: the SR MAP canvas's red MIA badge cut every enemy name to its
// first 6 characters (`name.slice(0, 6)`), so it read "Nidale 25s",
// "Kindre 25s", "Tahm K 25s", "Aureli 25s" and "Nunu & 25s". The keys of
// /api/vision-state `enemies` are Live Client display names
// (core/vision_tracker.py _compute_enemies, championName), so the badge was
// the one place on the map that did not name the enemy it was about.
//
// _amMapBadgeTag(name, secs, maxW, measure) is the badge text: the whole
// name and the seconds when that fits maxW; otherwise the name is cut and
// ended with "..." until the tag fits, and the seconds are never cut.
// measure(str) is the canvas measureText width; the tests use a fixed
// per-character width so they need no canvas.
//
// ASCII only. Run with `node --test`.

import test from "node:test";
import assert from "node:assert";

import { __test as am } from "./active_match.js";

const per10 = (s) => s.length * 10;

test("badge tag: a 7-letter name is drawn whole, not cut to 6", () => {
  assert.strictEqual(am._amMapBadgeTag("Nidalee", 25, 300, per10), "Nidalee 25s");
  assert.strictEqual(am._amMapBadgeTag("Kindred", 25.4, 300, per10), "Kindred 25s");
});

test("badge tag: a two-word display name keeps both words", () => {
  assert.strictEqual(am._amMapBadgeTag("Tahm Kench", 31, 300, per10), "Tahm Kench 31s");
  assert.strictEqual(am._amMapBadgeTag("Nunu & Willump", 14, 300, per10), "Nunu & Willump 14s");
});

test("badge tag: the seconds round to a whole number", () => {
  assert.strictEqual(am._amMapBadgeTag("Ahri", 12.6, 300, per10), "Ahri 13s");
});

test("badge tag: a name too wide for the canvas ends in ... and the seconds stay whole", () => {
  // "Aurelion Sol 25s" is 16 chars = 160 px; 120 px fits 12 chars.
  const tag = am._amMapBadgeTag("Aurelion Sol", 25, 120, per10);
  assert.ok(per10(tag) <= 120, tag);
  assert.ok(tag.endsWith("... 25s"), tag);
  assert.strictEqual(tag, "Aurel... 25s");
});

test("badge tag: at least one letter of the name survives a very narrow canvas", () => {
  const tag = am._amMapBadgeTag("Aurelion Sol", 25, 20, per10);
  assert.strictEqual(tag, "A... 25s");
});

test("badge tag: a missing name still yields the seconds", () => {
  assert.strictEqual(am._amMapBadgeTag("", 25, 300, per10), "? 25s");
  assert.strictEqual(am._amMapBadgeTag(null, 25, 300, per10), "? 25s");
});

test("badge tag: ASCII only, whatever the name", () => {
  const tag = am._amMapBadgeTag("Aurelion Sol", 25, 120, per10);
  assert.ok(/^[\x20-\x7e]*$/.test(tag), tag);
});

// S144-U-231 (carried FUTURE from S144-U-229): the badge box clamp took
// min(far edge, max(near edge, wanted)), so on a canvas too small for the
// box the far-edge bound won and the box started at a negative coordinate,
// off the top / left of the map. _amMapBadgeBox(px, py, txtW, boxH, w, h)
// returns {bx, top}: the text's left x and the box's top y, never above or
// left of the 2 px / 4 px margins, and inside the far edges whenever the
// box fits the canvas at all.

test("badge box: the box sits right of the dot with its bottom on the dot line", () => {
  assert.deepStrictEqual(am._amMapBadgeBox(100, 100, 50, 22, 358, 358), { bx: 108, top: 78 });
});

test("badge box: a dot at the top-right corner clamps the box inside the canvas", () => {
  const b = am._amMapBadgeBox(355, 3, 80, 22, 358, 358);
  assert.ok(b.bx - 3 >= 1 && b.bx + 80 + 3 <= 358 - 2, JSON.stringify(b));
  assert.ok(b.top >= 2 && b.top + 22 <= 358 - 2, JSON.stringify(b));
});

test("badge box: a canvas shorter than the box never puts the box above the top edge", () => {
  const b = am._amMapBadgeBox(10, 10, 50, 22, 200, 20);
  assert.ok(b.top >= 2, JSON.stringify(b));
  assert.ok(b.bx >= 4, JSON.stringify(b));
});

test("badge box: a canvas narrower than the text never puts the box left of the edge", () => {
  const b = am._amMapBadgeBox(10, 100, 120, 22, 60, 358);
  assert.ok(b.bx >= 4, JSON.stringify(b));
});
