// web/js/panels/session_hygiene.test.mjs
//
// Pure-logic tests for the session-hygiene "Should I Queue" card. Run with
// `node --test`. Covers the readiness band, confidence chip, signed factor
// nudge (+/- sign + neutral band + "-" inert sentinel), the tilt strip, and
// the full card HTML so a regression that drops the honesty signals fails.

import test from "node:test";
import assert from "node:assert";

import { __test } from "./session_hygiene.js";

const {
  _readinessClass, _confClass, _deltaClass, _fmtDelta, _factorRow, _tiltStrip,
  sessionHygieneHtml, _signature,
} = __test;

const PAYLOAD = {
  ok: true, n: 2963, overall_wr: 0.5157,
  readiness: {
    score: 62.0, confidence: "HIGH",
    factors: [
      { factor: "session_position", n: 529, delta_pts: 0.59, contributed: true, note: "next game is #1 this session" },
      { factor: "rust", n: 100, delta_pts: 5.97, contributed: true, note: "63.7h since last game" },
      { factor: "hour", n: 103, delta_pts: -3.13, contributed: true, note: "local hour 14" },
      { factor: "weekday", n: 26, delta_pts: 0.0, contributed: false, note: "" },
    ],
  },
  wr_by_session_position: [
    { position: 1, label: "1", wr: 0.52, games: 529 },
    { position: 8, label: "8+", wr: 0.49, games: 811 },
  ],
};

test("_readinessClass: bands the 0-100 readiness", () => {
  assert.strictEqual(_readinessClass(62), "sh-good");
  assert.strictEqual(_readinessClass(55), "sh-good");
  assert.strictEqual(_readinessClass(50), "sh-even");
  assert.strictEqual(_readinessClass(45), "sh-bad");
  assert.strictEqual(_readinessClass(NaN), "sh-dim");
});

test("_confClass: HIGH/MED/LOW distinct", () => {
  assert.strictEqual(_confClass("HIGH"), "sh-conf-high");
  assert.strictEqual(_confClass("MED"), "sh-conf-med");
  assert.strictEqual(_confClass("LOW"), "sh-conf-low");
});

test("_deltaClass: colors only past +/-2pt, neutral near zero", () => {
  assert.strictEqual(_deltaClass(5.97), "sh-good");
  assert.strictEqual(_deltaClass(-3.13), "sh-bad");
  assert.strictEqual(_deltaClass(0.59), "sh-dim");
  assert.strictEqual(_deltaClass(-1.0), "sh-dim");
});

test("_fmtDelta: signed one-decimal", () => {
  assert.strictEqual(_fmtDelta(5.97), "+6.0");
  assert.strictEqual(_fmtDelta(-3.13), "-3.1");
  assert.strictEqual(_fmtDelta(0), "+0.0");
});

test("_factorRow: contributed shows signed pt + n; inert shows '-' + no data", () => {
  const live = _factorRow(PAYLOAD.readiness.factors[1]);   // rust +5.97
  assert.match(live, /Rust/);
  assert.match(live, /\+6\.0pt/);
  assert.match(live, /n=100/);
  assert.doesNotMatch(live, /is-inert/);
  const inert = _factorRow(PAYLOAD.readiness.factors[3]);   // weekday, contributed=false
  assert.match(inert, /is-inert/);
  assert.match(inert, />-</);
  assert.match(inert, /no data/);
});

test("_tiltStrip: renders a column per position with win% + label", () => {
  const html = _tiltStrip(PAYLOAD.wr_by_session_position);
  assert.match(html, /height:52%/);   // 0.52 -> 52
  assert.match(html, /height:49%/);
  assert.match(html, />8\+</);
});

test("_tiltStrip: null wr -> dim, no bar, '-' in title", () => {
  const html = _tiltStrip([{ position: 3, label: "3", wr: null, games: 0 }]);
  assert.match(html, /sh-dim/);
  assert.match(html, /height:0%/);
});

test("sessionHygieneHtml: score, /100, conf chip, factors, tilt, caption", () => {
  const html = sessionHygieneHtml(PAYLOAD);
  assert.match(html, /SHOULD I QUEUE/);
  assert.match(html, />62</);
  assert.match(html, /\/100/);
  assert.match(html, /sh-conf sh-conf-high/);
  assert.match(html, /Rust/);
  assert.match(html, /Win % by game #/);
  assert.match(html, /51\.6%/);      // overall_wr baseline in caption
});

test("sessionHygieneHtml: not-ok -> unavailable, never a raw error", () => {
  assert.match(sessionHygieneHtml({ ok: false, error: "boom" }), /unavailable/);
  assert.doesNotMatch(sessionHygieneHtml({ ok: false, error: "boom" }), /boom/);
});

test("_signature: stable on equal, changes when a factor flips inert", () => {
  const s1 = _signature(PAYLOAD);
  assert.strictEqual(s1, _signature(JSON.parse(JSON.stringify(PAYLOAD))));
  const flip = JSON.parse(JSON.stringify(PAYLOAD));
  flip.readiness.factors[0].contributed = false;
  assert.notStrictEqual(_signature(flip), s1);
  assert.strictEqual(_signature(null), "_empty");
});
