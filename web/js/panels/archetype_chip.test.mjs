// web/js/panels/archetype_chip.test.mjs
//
// R89 competitor lift (Aggregator C per-champion class tag). Pure-logic tests for
// the champ-select combat-style archetype chip. Run with `node --test`.
//
// The DOM mount (My Pick card) is exercised at runtime in champ_select.js; these
// pin the tint mapping, the label, the fail-soft empty branch, and the defensive
// escape so the chip can never render an empty pill, an untinted badge, or raw
// markup. Mirrors the ds_matchup.js pure-function __test idiom.

import test from "node:test";
import assert from "node:assert";

import { __test } from "./archetype_chip.js";

const { archetypeChipHtml, _archTint } = __test;

test("archetypeChipHtml: known archetypes reuse their existing build-badge tint", () => {
  assert.match(archetypeChipHtml("carry"), /csv-build-badge-crit/);
  assert.match(archetypeChipHtml("bruiser"), /csv-build-badge-tank/);
  assert.match(archetypeChipHtml("tank"), /csv-build-badge-tank/);
  assert.match(archetypeChipHtml("mage"), /csv-build-badge-ap/);
  assert.match(archetypeChipHtml("assassin"), /csv-build-badge-lethality/);
  assert.match(archetypeChipHtml("enchanter"), /csv-build-badge-support/);
});

test("archetypeChipHtml: label is the uppercased archetype word", () => {
  assert.match(archetypeChipHtml("bruiser"), />BRUISER</);
  assert.match(archetypeChipHtml("Mage"), />MAGE</);
  assert.match(archetypeChipHtml("enchanter"), />ENCHANTER</);
});

test("archetypeChipHtml: always carries the base pill class + a semantic hook", () => {
  const html = archetypeChipHtml("carry");
  assert.match(html, /class="csv-build-badge /);
  assert.match(html, /csv-archetype-chip/);
});

test("archetypeChipHtml: empty / null / undefined / whitespace -> no chip", () => {
  assert.strictEqual(archetypeChipHtml(""), "");
  assert.strictEqual(archetypeChipHtml(null), "");
  assert.strictEqual(archetypeChipHtml(undefined), "");
  assert.strictEqual(archetypeChipHtml("   "), "");
});

test("archetypeChipHtml: unknown-but-nonempty primary renders with the default tint", () => {
  const html = archetypeChipHtml("specialist");
  assert.match(html, /csv-build-badge-default/);
  assert.match(html, />SPECIALIST</);
});

test("_archTint: case + whitespace insensitive; unknown -> default", () => {
  assert.strictEqual(_archTint("  BRUISER "), "csv-build-badge-tank");
  assert.strictEqual(_archTint("bogus"), "csv-build-badge-default");
  assert.strictEqual(_archTint(""), "csv-build-badge-default");
});

test("archetypeChipHtml: escapes markup in a hostile label (defensive)", () => {
  const html = archetypeChipHtml("<b>x</b>");
  assert.ok(!html.includes("<b>"), "must not emit a raw lowercase tag");
  assert.match(html, /&lt;B&gt;X&lt;\/B&gt;/);
});
