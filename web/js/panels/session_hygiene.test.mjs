// web/js/panels/session_hygiene.test.mjs
//
// Pure-logic tests for the session-hygiene "Should I Queue" card. Run with
// `node --test`. Covers the readiness band, confidence chip, signed factor
// nudge (+/- sign + neutral band + "-" inert sentinel), the tilt strip, and
// the full card HTML so a regression that drops the honesty signals fails.

import test from "node:test";
import assert from "node:assert";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

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

// ---- Y-04 "unknown is not neutral" (external reference O + Q) -------------

const UNKNOWN = {
  ok: true, n: 0, overall_wr: 0.5,
  readiness: {
    score: null, confidence: "LOW",
    factors: [
      { factor: "session_position", n: 0, delta_pts: 0.0, contributed: false, note: "next game is #1 this session" },
      { factor: "rust", n: 0, delta_pts: 0.0, contributed: false, note: "no prior game" },
    ],
    context: {},
    state: "unknown", flags: [],
    basis: "Unknown: no context bucket has >= 5 games yet, so there is no readiness read.",
  },
  wr_by_session_position: [],
};

const FLAGGED = JSON.parse(JSON.stringify(PAYLOAD));
FLAGGED.readiness.score = 58.0;
FLAGGED.readiness.state = "yellow";
FLAGGED.readiness.basis = "Based on 3 of 4 context factors with >= 5 games.";
FLAGGED.readiness.flags = [
  { flag: "loss_streak", kind: "override", n: 206, delta_pts: -4.35,
    note: "4 straight losses this session; your WR after 3+ straight losses in a session has been 4.4 pts lower (n=206)" },
];

test("_readinessClass: null score is dim, never the Number(null)=0 'bad' band", () => {
  assert.strictEqual(_readinessClass(null), "sh-dim");
  assert.strictEqual(_readinessClass(undefined), "sh-dim");
});

test("sessionHygieneHtml: unknown state -> '-' score + basis line, never 0/100", () => {
  const html = sessionHygieneHtml(UNKNOWN);
  assert.doesNotMatch(html, />0<span class="sh-score-max">/);
  assert.match(html, /sh-score sh-dim">-<span class="sh-score-max">/);
  assert.match(html, /sh-state sh-state-unknown/);
  assert.match(html, /no context bucket has &gt;= 5 games/);
  assert.match(html, /class="sh-basis"/);
});

test("sessionHygieneHtml: no reflow - unknown and known render the same skeleton", () => {
  const skel = (h) => (h.match(/class="sh-[a-z-]+/g) || [])
    .filter((c) => /sh-(head|score|state|conf|basis|flags|factors|tilt-wrap|caption)\b/.test(c)
      && !/sh-score-max/.test(c))
    .map((c) => c.replace(/^class="/, ""));
  const known = skel(sessionHygieneHtml(PAYLOAD));
  const unknown = skel(sessionHygieneHtml(UNKNOWN));
  assert.deepStrictEqual(unknown, known);
});

test("sessionHygieneHtml: flags render as odds-shift lines; none -> placeholder", () => {
  const html = sessionHygieneHtml(FLAGGED);
  assert.match(html, /sh-state sh-state-yellow/);
  assert.match(html, /4\.4 pts lower/);
  assert.match(html, /sh-flag is-override/);
  const none = sessionHygieneHtml(PAYLOAD);
  assert.match(none, /class="sh-flags"/);
  assert.match(none, /No flags/);
});

test("sessionHygieneHtml: legacy payload without state still renders a light", () => {
  const html = sessionHygieneHtml(PAYLOAD);   // no state / flags / basis keys
  assert.match(html, />62</);
  assert.match(html, /sh-state sh-state-green/);
});

test("ui_mock session.json carries an unknown-state payload that renders '-'", () => {
  const p = fileURLToPath(new URL("../../data/ui_mock/session.json", import.meta.url));
  const mock = JSON.parse(readFileSync(p, "utf8")).session_hygiene;
  assert.ok(mock, "session.json must carry a session_hygiene payload");
  assert.strictEqual(mock.readiness.score, null);
  assert.strictEqual(mock.readiness.state, "unknown");
  const html = sessionHygieneHtml(mock);
  assert.match(html, /sh-state-unknown/);
  assert.match(html, /sh-score sh-dim">-</);
});

test("_signature: null score and state participate (unknown != 0)", () => {
  const zero = JSON.parse(JSON.stringify(UNKNOWN));
  zero.readiness.score = 0; zero.readiness.state = "yellow";
  assert.notStrictEqual(_signature(UNKNOWN), _signature(zero));
  assert.notStrictEqual(_signature(FLAGGED), _signature(PAYLOAD));
});

test("_signature: stable on equal, changes when a factor flips inert", () => {
  const s1 = _signature(PAYLOAD);
  assert.strictEqual(s1, _signature(JSON.parse(JSON.stringify(PAYLOAD))));
  const flip = JSON.parse(JSON.stringify(PAYLOAD));
  flip.readiness.factors[0].contributed = false;
  assert.notStrictEqual(_signature(flip), s1);
  assert.strictEqual(_signature(null), "_empty");
});
