// web/js/panels/moment_flags.test.mjs
//
// RM-638 (directive X-38, external reference C): the player's in-game
// "mark this moment" presses arrive on /api/replay/events and
// /api/post-game-wpa as an additive `you_flagged` list. This pins that both
// panels RENDER them as "you flagged" pins:
//   - replay_events.js: a seekable ribbon row (data-kind="flag",
//     data-clock = game seconds) interleaved with the events by clock,
//   - pgr_winprob.js: a dashed vertical marker on the win-prob curve with a
//     "you flagged M:SS" <title>, clamped into the plotted range.
// Run by tests/test_web_panels_node_suite.py (node --test over this dir).

import test from "node:test";
import assert from "node:assert";

// ----- minimal DOM shim (import-time + _escHtml surface only) -------------
globalThis.document = {
  createElement: () => {
    let t = "";
    return {
      dataset: {}, style: {},
      set textContent(v) { t = String(v); },
      get innerHTML() {
        return t.replace(/&/g, "&amp;").replace(/</g, "&lt;")
          .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
      },
    };
  },
  getElementById: () => null,
  addEventListener: () => {},
  dispatchEvent: () => {},
  body: { dataset: {} },
};
globalThis.fetch = () => Promise.reject(new Error("no network in tests"));
globalThis.CustomEvent = globalThis.CustomEvent || class { constructor(n) { this.type = n; } };

const replay = (await import("./replay_events.js")).__test;
const pgr = (await import("./pgr_winprob.js")).__test;

const EVENTS = [
  { clock_s: 60, type: "CHAMPION_KILL", team: 100, actor: 2, victim: 8 },
  { clock_s: 360, type: "BUILDING_KILL", team: 200, subtype: "OUTER_TURRET" },
];
const FLAGS = [
  { clock_s: 200, game_time_s: 200.4, wall_ts: 1, label: "you flagged" },
  { clock_s: 60, game_time_s: 60.9, wall_ts: 2, label: "you flagged" },
];

// ---------------- Replay ribbon ----------------

test("replay: flag rows render with the flag kind, label and seek clock", () => {
  const html = replay._flagRowHtml(FLAGS[0]);
  assert.match(html, /class="replay-events-row"/);
  assert.match(html, /data-kind="flag"/);
  assert.match(html, /data-clock="200"/);
  assert.match(html, /role="button" tabindex="0"/);
  assert.ok(html.includes(">you flagged<"), html);
  assert.strictEqual(replay.FLAG_LABEL, "you flagged");
});

test("replay: flags interleave with events by clock, flag after a same-second event", () => {
  const html = replay._rowsHtml(EVENTS, FLAGS);
  const order = [...html.matchAll(/data-kind="(\w+)"[^>]*?data-team="\d+"\s+data-clock="(\d+)"/g)]
    .map((m) => `${m[1]}@${m[2]}`);
  assert.deepStrictEqual(order, ["kill@60", "flag@60", "flag@200", "structure@360"]);
});

test("replay: no flags renders the events exactly as before", () => {
  const html = replay._rowsHtml(EVENTS, []);
  assert.strictEqual(html, EVENTS.map(replay._eventRowHtml).join(""));
  assert.ok(!html.includes("data-kind=\"flag\""));
});

test("replay: flags alone (no timeline events) still render", () => {
  const html = replay._rowsHtml([], [FLAGS[0]]);
  assert.match(html, /data-kind="flag"/);
});

test("replay: malformed pins are skipped, render is idempotent", () => {
  const bad = [null, {}, { game_time_s: "x" }, FLAGS[0]];
  const a = replay._rowsHtml(EVENTS, bad);
  assert.strictEqual((a.match(/data-kind="flag"/g) || []).length, 1);
  assert.strictEqual(a, replay._rowsHtml(EVENTS, bad));
});

// ---------------- PGR win-prob curve ----------------

const WPA_EVENTS = [
  { game_time: 0, prob_after: 0.5, wpa: 0, type: "CHAMPION_KILL" },
  { game_time: 600, prob_after: 0.6, wpa: 0.1, type: "CHAMPION_KILL" },
  { game_time: 1200, prob_after: 0.7, wpa: 0.1, type: "CHAMPION_KILL" },
];

test("pgr: each flag draws one titled 'you flagged' marker", () => {
  const svg = pgr._svgHtml(WPA_EVENTS, [], 100, FLAGS);
  assert.strictEqual((svg.match(/class="pwp-flag-mark"/g) || []).length, 2);
  assert.ok(svg.includes("<title>you flagged 3:20</title>"), svg);
  assert.ok(svg.includes("<title>you flagged 1:00</title>"), svg);
  assert.match(svg, /class="pwp-flag"/);
});

test("pgr: no flags leaves the curve markup unchanged", () => {
  assert.strictEqual(pgr._svgHtml(WPA_EVENTS, [], 100, []),
                     pgr._svgHtml(WPA_EVENTS, [], 100));
  assert.ok(!pgr._svgHtml(WPA_EVENTS, [], 100).includes("pwp-flag"));
});

test("pgr: a flag past the last event is clamped onto the plot edge", () => {
  const m = pgr._flagMarksHtml([{ game_time_s: 99999 }], 0, 1200, 1200);
  const x = Number(/x1="([\d.]+)"/.exec(m)[1]);
  // PAD_L 40 + PLOT_W 548 = 588 (viewBox geometry in pgr_winprob.js)
  assert.strictEqual(x, 588);
});

test("pgr: the card legend names the flags only when present", () => {
  const base = { ok: true, events: WPA_EVENTS, top_phases: [], model: "fallback" };
  assert.ok(!pgr._cardHtml(base, 100).includes("you flagged"));
  const withFlags = pgr._cardHtml({ ...base, you_flagged: FLAGS }, 100);
  assert.ok(withFlags.includes("dashed marker = you flagged (2)"), withFlags);
});
