// web/js/panels/ds_matchup.test.mjs
//
// C-09 no-reflow guard for the F1 all-enemy danger grid. Run with `node --test`.
//
// F1 shipped the 5-enemy grid, but the card still collapsed whole whenever the
// HEADLINE (lane) pairing had not landed or came back not-ok - taking four
// perfectly renderable enemy rows down with it, then popping them all back in
// when the lane fetch resolved. That is the no-reflow-on-data-absence rule:
// a scaffold whose rows exist keeps its geometry and renders the "-" sentinel;
// only a truly-empty roster is allowed to collapse.
//
// renderDsMatchup touches exactly three properties on its mount (id, hidden,
// innerHTML), so a plain object stands in for the element - no DOM needed.
// ASCII only.

import test from "node:test";
import assert from "node:assert";

import { renderDsMatchup, _resetDsMatchup, __test } from "./ds_matchup.js";

const { _severity, _gridHtml } = __test;

function mount(id) {
  return { id: id || "csv-sugg-ds-matchup", hidden: false, innerHTML: "" };
}

function cell(champ, role, isLane, payload) {
  return { champ, champA: "Jinx", role, isLane: !!isLane, payload: payload || null };
}

function landed(champA, champB, verdict, swingPct) {
  return {
    ok: true,
    champ_a: champA,
    champ_b: champB,
    verdict,
    swing_pct: swingPct,
    pct_a_removed: 0.3,
    pct_b_removed: 0.55,
    notes: [],
  };
}

function fullRoster(payloads) {
  const spec = [
    ["Kaisa", "BOTTOM", true],
    ["Teemo", "TOP", false],
    ["Ahri", "MIDDLE", false],
    ["LeeSin", "JUNGLE", false],
    ["Thresh", "UTILITY", false],
  ];
  return spec.map((s, i) => cell(s[0], s[1], s[2], (payloads || [])[i] || null));
}

function countCells(html) {
  return (html.match(/class="dsm-grid-cell/g) || []).length;
}

test("pending lane payload keeps the card mounted - the grid must not collapse", () => {
  _resetDsMatchup();
  const el = mount();
  renderDsMatchup(el, null, fullRoster());
  assert.strictEqual(el.hidden, false, "card collapsed while 5 enemy rows were renderable");
  assert.strictEqual(countCells(el.innerHTML), 5, "pending grid must still render 5 rows");
});

test("a not-ok lane payload still renders the other enemies", () => {
  _resetDsMatchup();
  const el = mount();
  const grid = fullRoster([null, landed("Jinx", "Teemo", "trade", 61)]);
  renderDsMatchup(el, { ok: false, reason: "no_matchup" }, grid);
  assert.strictEqual(el.hidden, false, "one dead pairing hid the whole enemy team");
  assert.strictEqual(countCells(el.innerHTML), 5);
  assert.match(el.innerHTML, /TRADE/, "a landed sibling row lost its verdict");
});

test("row count is identical pending vs landed - zero reflow across the landing", () => {
  _resetDsMatchup();
  const el = mount();
  renderDsMatchup(el, null, fullRoster());
  const before = countCells(el.innerHTML);
  const grid = fullRoster([
    landed("Jinx", "Kaisa", "trade", 58),
    landed("Jinx", "Teemo", "back_off", 31),
    landed("Jinx", "Ahri", "even", 50),
    landed("Jinx", "LeeSin", "all_in", 72),
    landed("Jinx", "Thresh", "trade", 55),
  ]);
  renderDsMatchup(el, grid[0].payload, grid);
  assert.strictEqual(countCells(el.innerHTML), before, "grid changed height on data landing");
  assert.strictEqual(before, 5);
});

test("an unlanded cell renders the single-hyphen no-data sentinel", () => {
  _resetDsMatchup();
  const el = mount();
  renderDsMatchup(el, null, fullRoster());
  assert.ok(!el.innerHTML.includes("--"), "double hyphen is not the repo no-data sentinel");
  assert.match(el.innerHTML, /class="dsm-grid-verdict">-</, "missing the - sentinel");
  assert.match(el.innerHTML, /is-empty/, "no-data cells need the is-empty hook");
});

test("the pending headline still names the pairing it is waiting on", () => {
  _resetDsMatchup();
  const el = mount();
  renderDsMatchup(el, null, fullRoster());
  assert.match(el.innerHTML, /Jinx/, "operator champion missing from the pending head");
  assert.match(el.innerHTML, /Kaisa/, "lane opponent missing from the pending head");
});

test("an empty roster IS allowed to collapse - no data anywhere", () => {
  _resetDsMatchup();
  const el = mount();
  renderDsMatchup(el, null, []);
  assert.strictEqual(el.hidden, true, "nothing to scaffold, so the card must collapse");
  _resetDsMatchup();
  const el2 = mount();
  renderDsMatchup(el2, null);
  assert.strictEqual(el2.hidden, true, "the two-arg call must keep its hide-on-null contract");
});

test("render is idempotent - same inputs produce the same DOM", () => {
  _resetDsMatchup();
  const a = mount("dsm-a");
  const b = mount("dsm-b");
  const grid = fullRoster([landed("Jinx", "Kaisa", "trade", 58)]);
  renderDsMatchup(a, grid[0].payload, grid);
  renderDsMatchup(b, grid[0].payload, fullRoster([landed("Jinx", "Kaisa", "trade", 58)]));
  assert.strictEqual(a.innerHTML, b.innerHTML);
});

test("a late-landing cell is not swallowed by the signature dedup gate", () => {
  _resetDsMatchup();
  const el = mount();
  renderDsMatchup(el, null, fullRoster());
  const pending = el.innerHTML;
  renderDsMatchup(el, null, fullRoster([null, landed("Jinx", "Teemo", "all_in", 80)]));
  assert.notStrictEqual(el.innerHTML, pending, "late enemy landing did not re-render");
  assert.match(el.innerHTML, /ALL IN/);
});

test("an enemy whose slug has not resolved keeps its row rather than shifting the grid", () => {
  _resetDsMatchup();
  const el = mount();
  const grid = fullRoster();
  grid[2].champ = "";
  renderDsMatchup(el, null, grid);
  assert.strictEqual(countCells(el.innerHTML), 5, "unresolved slug dropped a row");
});

test("_severity bins an absent payload as unknown, never as a favorable read", () => {
  assert.strictEqual(_severity(null), "unknown");
  assert.strictEqual(_severity({ ok: false }), "unknown");
  assert.strictEqual(_severity(landed("Jinx", "Kaisa", "back_off", 20)), "bad");
  assert.strictEqual(_severity(landed("Jinx", "Kaisa", "all_in", 80)), "good");
});

test("_gridHtml keeps every row it is handed", () => {
  const html = _gridHtml(fullRoster());
  assert.strictEqual(countCells(html), 5);
});
