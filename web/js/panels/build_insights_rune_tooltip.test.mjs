// web/js/panels/build_insights_rune_tooltip.test.mjs
//
// Unit guard for the descriptive rune HOVER tooltip on the build-insights
// rune-WPA tab (operator 2026-07-04: hovering a rune showed no effect text).
// Run with `node --test`.
//
// The rune-WPA row carries {rune_id, name, icon, ...} with NO description, so
// the tab fetches /api/dictionary/runes and folds shortDesc into a
// {rune_id -> stripped-text} map. These pin the two pure pieces:
//   _stripHtml   - LoL shortDesc HTML -> plain title text (tags removed,
//                  entities decoded, whitespace collapsed, null-safe).
//   _runeTitle   - "name - desc" composition ("name" alone when desc missing).
//
// build_insights.js is an ES module (export const __test). It transitively
// imports duration_winrate.js, which calls document.addEventListener at load,
// so - mirroring ds_shaper.test.mjs - we install a MINIMAL globalThis.document
// shim then dynamic-import AFTER the shim is live.

import test from "node:test";
import assert from "node:assert";

// ----- minimal DOM shim (import-time surface only) ------------------------
globalThis.document = {
  createElement: () => ({ dataset: {}, style: {}, children: [],
    appendChild() {}, addEventListener() {}, setAttribute() {} }),
  getElementById: () => null,
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener: () => {},
  dispatchEvent: () => {},
};

// Import AFTER the shim is live (build_insights.js -> duration_winrate.js reads
// document.addEventListener at load; the pure helpers under test touch no DOM).
const { __test } = await import("./build_insights.js");
const { _stripHtml, _runeTitle } = __test;

test("_stripHtml strips HTML tags and keeps the inner text", () => {
  assert.strictEqual(
    _stripHtml("Hitting a champion with 3 <b>separate</b> attacks deals bonus damage."),
    "Hitting a champion with 3 separate attacks deals bonus damage.",
  );
});

test("_stripHtml strips the LoL keyword-tooltip wrapper, keeping its label", () => {
  assert.strictEqual(
    _stripHtml("deals bonus <lol-uikit-tooltipped-keyword key='LinkTooltip_adaptive'>adaptive damage</lol-uikit-tooltipped-keyword>."),
    "deals bonus adaptive damage.",
  );
});

test("_stripHtml decodes the common HTML entities", () => {
  assert.strictEqual(
    _stripHtml("gain &lt;A&gt; &amp; &#39;B&#39;&nbsp;now"),
    "gain <A> & 'B' now",
  );
});

test("_stripHtml collapses runs of whitespace and trims", () => {
  assert.strictEqual(
    _stripHtml("  lots\n\tof   space   "),
    "lots of space",
  );
});

test("_stripHtml is null / undefined / empty safe", () => {
  assert.strictEqual(_stripHtml(null), "");
  assert.strictEqual(_stripHtml(undefined), "");
  assert.strictEqual(_stripHtml(""), "");
});

test("_runeTitle composes 'name - desc' when a description is present", () => {
  assert.strictEqual(
    _runeTitle("Electrocute", "Hitting a champion deals bonus damage."),
    "Electrocute - Hitting a champion deals bonus damage.",
  );
});

test("_runeTitle strips HTML from the description before composing", () => {
  assert.strictEqual(
    _runeTitle("Press the Attack", "Hitting with <b>3</b> attacks."),
    "Press the Attack - Hitting with 3 attacks.",
  );
});

test("_runeTitle is name-only when the description is missing / blank", () => {
  assert.strictEqual(_runeTitle("Electrocute", ""), "Electrocute");
  assert.strictEqual(_runeTitle("Electrocute", null), "Electrocute");
  assert.strictEqual(_runeTitle("Electrocute", undefined), "Electrocute");
  assert.strictEqual(_runeTitle("Electrocute", "   "), "Electrocute");
});
