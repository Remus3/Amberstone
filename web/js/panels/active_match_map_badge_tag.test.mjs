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

// S144-U-247 (the carried "short-name fallback width" FUTURE row): a cut
// adds "..." (3 chars), so on a short name it is WIDER than the whole tag.
// "Vi 25s" that did not fit came back as "V... 25s", 2 chars wider, and the
// last-resort one-letter tag was returned unmeasured. The badge now never
// draws a tag wider than the whole name: when no cut fits, it draws the
// narrowest candidate, and a tie keeps the longer name.

test("badge tag: a 2-letter name that does not fit stays whole, not V...", () => {
  // "Vi 25s" = 60 px > 50; "V... 25s" = 80 px is wider still.
  assert.strictEqual(am._amMapBadgeTag("Vi", 25, 50, per10), "Vi 25s");
});

test("badge tag: a 3-letter name that does not fit stays whole, not Za...", () => {
  // "Zac 25s" = 70 px > 60; "Za... 25s" 90 px, "Z... 25s" 80 px.
  assert.strictEqual(am._amMapBadgeTag("Zac", 25, 60, per10), "Zac 25s");
});

test("badge tag: when nothing fits, the narrowest candidate is drawn", () => {
  // "Aurelion Sol 25s" = 160 px; nothing fits 20 px; "A... 25s" = 80 px.
  assert.strictEqual(am._amMapBadgeTag("Aurelion Sol", 25, 20, per10), "A... 25s");
  // "Nasus 125s" = 100 px; the cuts are 120 / 110 / 100 / 90 px, so the
  // one-letter cut is the only one narrower than the whole tag.
  assert.strictEqual(am._amMapBadgeTag("Nasus", 125, 50, per10), "N... 125s");
  // "Ahri 9s" = 70 px; the cuts are 90 / 80 / 70 px, so a 70-px tie with
  // the whole tag keeps the whole name.
  assert.strictEqual(am._amMapBadgeTag("Ahri", 9, 40, per10), "Ahri 9s");
});

test("badge tag: never wider than the whole tag, never wider than maxW when a candidate fits", () => {
  const names = ["Vi", "Zac", "Ahri", "Nasus", "Kindred", "Tahm Kench",
    "Aurelion Sol", "Nunu & Willump", ""];
  for (const nm of names) {
    for (const secs of [9, 25, 125]) {
      for (let maxW = 0; maxW <= 200; maxW += 5) {
        const tag = am._amMapBadgeTag(nm, secs, maxW, per10);
        const whole = (nm || "?") + ` ${secs}s`;
        assert.ok(per10(tag) <= per10(whole), `${nm} ${secs} ${maxW}: ${tag}`);
        assert.ok(tag.endsWith(` ${secs}s`), `${nm} ${secs} ${maxW}: ${tag}`);
        assert.ok(/^[^ .]/.test(tag), `${nm} ${secs} ${maxW}: ${tag}`);
        const fits = per10(whole) <= maxW
          || per10((nm || "?").slice(0, 1) + "..." + ` ${secs}s`) <= maxW;
        if (fits) assert.ok(per10(tag) <= maxW, `${nm} ${secs} ${maxW}: ${tag}`);
      }
    }
  }
});

test("badge tag: a cut never leaves the name as bare ... (a leading space is skipped)", () => {
  // A name whose first character is a space would trim to "" at n = 1.
  const tag = am._amMapBadgeTag(" Xin Zhao", 25, 0, per10);
  assert.ok(!tag.startsWith("..."), tag);
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
