// web/js/panels/playstyle_labels.test.mjs
//
// Pure-logic tests for the playstyle-labels card. Run with `node --test`.
// Covers tag tone mapping, WR class, label chip (verdict tooltip), champion
// row, the labeled-only + sort + cap behavior, baseline chip, and the empty
// state, so a regression that leaks unlabeled noise or drops the honesty
// framing fails loudly.

import test from "node:test";
import assert from "node:assert";

import { __test } from "./playstyle_labels.js";

const {
  _tagTone, _wrClass, _labelChip, _champRow, playstyleLabelsHtml, _signature,
  _MAX_ROWS,
} = __test;

const PAYLOAD = {
  ok: true, n: 2966, overall_wr: 0.5162,
  baseline: { kills: 10.74, deaths: 9.71, assists: 18.45, kp: 61.33, kda_ratio: 3.41 },
  champions: [
    { champion_id: 18, champion_name: "Tristana", games: 151, wins: 90, wr: 0.5948, kda_cv: 0.799,
      labels: [{ tag: "high-variance", verdict: "coinflip games - swings hard", basis: "kda_cv", value: 0.799 }] },
    { champion_id: 67, champion_name: "Vayne", games: 193, wins: 109, wr: 0.5641, kda_cv: 0.616, labels: [] },
    { champion_id: 22, champion_name: "Ashe", games: 40, wins: 18, wr: 0.45, kda_cv: 0.5,
      labels: [{ tag: "death-averse", verdict: "dies less than your norm", basis: "deaths", value: 7.2 }] },
  ],
};

test("_tagTone: known verdict tags map to a tone; unknown -> dim", () => {
  assert.strictEqual(_tagTone("death-averse"), "pl-good");
  assert.strictEqual(_tagTone("high-variance"), "pl-bad");
  assert.strictEqual(_tagTone("solo-leaning"), "pl-dim");
  assert.strictEqual(_tagTone("nonsense"), "pl-dim");
});

test("_wrClass: >=50% good else bad", () => {
  assert.strictEqual(_wrClass(0.5948), "pl-good");
  assert.strictEqual(_wrClass(0.45), "pl-bad");
  assert.strictEqual(_wrClass(NaN), "pl-dim");
});

test("_labelChip: carries the tag text + verdict tooltip", () => {
  const html = _labelChip(PAYLOAD.champions[0].labels[0]);
  assert.match(html, /high-variance/);
  assert.match(html, /pl-bad/);
  assert.match(html, /title="coinflip games - swings hard"/);
});

test("_champRow: shows champ name, games, wr%, label chips", () => {
  const html = _champRow(PAYLOAD.champions[0]);
  assert.match(html, /Tristana/);
  assert.match(html, /151g/);
  assert.match(html, /59%/);
  assert.match(html, /high-variance/);
});

test("playstyleLabelsHtml: only labeled champs render, sorted by games desc", () => {
  const html = playstyleLabelsHtml(PAYLOAD);
  assert.match(html, /Tristana/);   // labeled
  assert.match(html, /Ashe/);       // labeled
  assert.doesNotMatch(html, /Vayne/); // no labels -> omitted
  // Tristana (151g) before Ashe (40g)
  assert.ok(html.indexOf("Tristana") < html.indexOf("Ashe"));
  assert.match(html, /your norm: 10\.7\/9\.7\//);  // baseline chip
  assert.match(html, /3\.41 KDA/);
  assert.match(html, /PLAYSTYLE/);
});

test("playstyleLabelsHtml: empty labeled set -> honest empty text, keeps baseline", () => {
  const html = playstyleLabelsHtml({ ok: true, n: 10, baseline: PAYLOAD.baseline, champions: [
    { champion_id: 1, champion_name: "Annie", games: 3, wr: 0.5, labels: [] },
  ] });
  assert.match(html, /No champion stands out/);
  assert.match(html, /your norm/);
});

test("playstyleLabelsHtml: caps at _MAX_ROWS and notes the remainder", () => {
  const many = { ok: true, n: 5000, baseline: PAYLOAD.baseline, champions: [] };
  for (let i = 0; i < _MAX_ROWS + 4; i++) {
    many.champions.push({ champion_id: i, champion_name: `C${i}`, games: 100 - i, wr: 0.5,
      labels: [{ tag: "death-prone", verdict: "v" }] });
  }
  const html = playstyleLabelsHtml(many);
  assert.match(html, /\+ 4 more labeled champions not shown/);
});

test("playstyleLabelsHtml: not-ok -> unavailable, never a raw error", () => {
  assert.match(playstyleLabelsHtml({ ok: false, error: "boom" }), /unavailable/);
  assert.doesNotMatch(playstyleLabelsHtml({ ok: false, error: "boom" }), /boom/);
});

test("_signature: stable on equal, changes when labels change", () => {
  const s1 = _signature(PAYLOAD);
  assert.strictEqual(s1, _signature(JSON.parse(JSON.stringify(PAYLOAD))));
  const mut = JSON.parse(JSON.stringify(PAYLOAD));
  mut.champions[0].labels.push({ tag: "kill-focused", verdict: "x" });
  assert.notStrictEqual(_signature(mut), s1);
  assert.strictEqual(_signature(null), "_empty");
});
