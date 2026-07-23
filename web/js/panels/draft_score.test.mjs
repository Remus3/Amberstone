// web/js/panels/draft_score.test.mjs
//
// Pure-logic tests for the draft-score champ-select card. Run with
// `node --test`. Only the pure core (cache key / signature / score-class /
// layer row / full card HTML) is covered; the DOM-applying wrapper
// (renderDraftScore) needs a live document and is exercised in the dashboard
// at runtime. These pin: the 42-58 score render, the confidence chip class,
// the per-layer contributed/inert breakdown, and the "-" thin sentinel on an
// inert layer so a regression that drops the honesty signal fails loudly.

import test from "node:test";
import assert from "node:assert";

import { __test } from "./draft_score.js";

const {
  _cacheKey, _signature, _scoreClass, _confClass, _layerRow, draftScoreHtml,
  _LAYER_LABEL,
} = __test;

// Mirrors a real /api/draft-score payload (4 of 5 layers contributing;
// scaling inert by design).
const PAYLOAD = {
  ok: true,
  score: 54.4,
  confidence: "MED",
  band: [42.0, 58.0],
  contributing: 4,
  layers: [
    { name: "matchup", weight: 0.3, sub_score: 0.5233, n: 45, trust: 0.9, contributed: true },
    { name: "synergy", weight: 0.2, sub_score: 0.5, n: 10, trust: 0.6667, contributed: true },
    { name: "damage_balance", weight: 0.15, sub_score: 0.59, n: 25, trust: 0.8333, contributed: true },
    { name: "scaling", weight: 0.1, sub_score: null, n: 0, trust: 0.0, contributed: false },
    { name: "base_wr", weight: 0.25, sub_score: 0.5764, n: 13, trust: 0.7222, contributed: true },
  ],
};

test("_cacheKey: sorts ally + enemy, order-invariant", () => {
  const a = _cacheKey([64, 22, 1, 2, 3], [42, 67, 69, 55, 12], null);
  const b = _cacheKey([3, 2, 1, 22, 64], [12, 55, 69, 67, 42], null);
  assert.strictEqual(a, b);
  assert.strictEqual(a, "1,2,3,22,64|12,42,55,67,69|");
});

test("_cacheKey: no enemy leaves the enemy slot empty", () => {
  assert.strictEqual(_cacheKey([1, 2, 3, 4, 5], null, null), "1,2,3,4,5||");
});

test("_scoreClass: bands the 42-58 score", () => {
  assert.strictEqual(_scoreClass(54.4), "ds-good");
  assert.strictEqual(_scoreClass(52), "ds-good");
  assert.strictEqual(_scoreClass(50), "ds-even");
  assert.strictEqual(_scoreClass(48), "ds-bad");
  assert.strictEqual(_scoreClass(42), "ds-bad");
});

test("_scoreClass: non-finite -> dim", () => {
  assert.strictEqual(_scoreClass(NaN), "ds-dim");
  assert.strictEqual(_scoreClass("x"), "ds-dim");
});

test("_confClass: HIGH/MED/LOW map to distinct classes", () => {
  assert.strictEqual(_confClass("HIGH"), "ds-conf-high");
  assert.strictEqual(_confClass("MED"), "ds-conf-med");
  assert.strictEqual(_confClass("LOW"), "ds-conf-low");
  assert.strictEqual(_confClass("garbage"), "ds-conf-med");
});

test("_layerRow: a contributed layer shows its WR% + n + human label", () => {
  const html = _layerRow(PAYLOAD.layers[0]);
  assert.match(html, /Lane matchup/);
  assert.match(html, /52\.3%/);       // 0.5233 * 100
  assert.match(html, /n=45/);
  assert.doesNotMatch(html, /is-inert/);
});

test("_layerRow: an inert layer shows the '-' sentinel + 'reserved' for scaling", () => {
  const html = _layerRow(PAYLOAD.layers[3]);  // scaling, contributed=false
  assert.match(html, /is-inert/);
  assert.match(html, />-</);            // the "-" val
  assert.match(html, /reserved/);       // scaling-specific inert note
  assert.doesNotMatch(html, /n=0/);     // no fake sample count on an inert row
});

test("_layerRow: a non-scaling inert layer reads 'no data'", () => {
  const inertMatchup = { name: "matchup", weight: 0.3, sub_score: null, n: 0, contributed: false };
  const html = _layerRow(inertMatchup);
  assert.match(html, /no data/);
  assert.doesNotMatch(html, /reserved/);
});

test("draftScoreHtml: renders score, confidence chip, all five layer rows, caption", () => {
  const html = draftScoreHtml(PAYLOAD);
  assert.match(html, /54\.4/);
  assert.match(html, /ds-draft-conf ds-conf-med/);
  assert.match(html, />MED</);
  // all five layer labels present
  for (const label of Object.values(_LAYER_LABEL)) {
    assert.match(html, new RegExp(label));
  }
  assert.match(html, /4 of 5 layers contributing/);
  assert.match(html, /42-58 band/);
});

test("draftScoreHtml: not-ok payload -> unavailable text (never a raw error)", () => {
  assert.match(draftScoreHtml({ ok: false, error: "boom" }), /unavailable/);
  assert.doesNotMatch(draftScoreHtml({ ok: false, error: "boom" }), /boom/);
});

test("_signature: stable for equal payloads, changes when a layer flips inert", () => {
  const s1 = _signature(PAYLOAD);
  const s2 = _signature(JSON.parse(JSON.stringify(PAYLOAD)));
  assert.strictEqual(s1, s2);
  const flipped = JSON.parse(JSON.stringify(PAYLOAD));
  flipped.layers[0].contributed = false;
  flipped.layers[0].sub_score = null;
  assert.notStrictEqual(_signature(flipped), s1);
});

test("_signature: null / not-ok -> _empty", () => {
  assert.strictEqual(_signature(null), "_empty");
  assert.strictEqual(_signature({ ok: false }), "_empty");
});
