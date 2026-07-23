// web/js/panels/patch_impact.test.mjs
//
// Pure-logic tests for the patch-impact card. Run with `node --test`.
// Covers value formatting, WR class, the tooltip cap, the per-section chips,
// the no-change "-" sentinel (the card must NOT drop a champion with zero
// changes - that would reflow the list every patch), the row + head, the cap,
// the empty/reason state, and the descriptive-not-advice caption, so a
// regression that starts calling a build reshuffle a buff fails loudly.

import test from "node:test";
import assert from "node:assert";

import { __test } from "./patch_impact.js";

const {
  _fmtVal, _wrClass, _tip, _chips, _champRow, _head, patchImpactHtml,
  _signature, _MAX_ROWS, _MAX_TIP,
} = __test;

const JINX = {
  champion_id: 222, champion: "Jinx", name: "Jinx",
  games: 81, wins: 53, winrate: 65.1, play_share: 4.0, change_count: 4,
  champion_changes: [{ field: "stats.attackdamage", old: 59, new: 57 }],
  ability_changes: [{ key: "Q", field: "cooldown", old: [0.9], new: [0.8] }],
  build_changes: [{ archetype: "balanced", old: ["3153", "3031"], new: ["3153", "3095"] }],
  item_changes: [{ item_id: "3153", name: "Blade of the Ruined King",
                   fields: [{ field: "gold.total", old: 3200, new: 3100 }] }],
};

const QUIET = {
  champion_id: 18, champion: "Tristana", name: "Tristana",
  games: 61, wins: 40, winrate: 71.4, play_share: 3.0, change_count: 0,
  champion_changes: [], ability_changes: [], build_changes: [], item_changes: [],
};

const PAYLOAD = {
  ok: true, mode: "aram", old_patch: "16.13.1", new_patch: "16.14.1",
  n_matches: 2044, changed_items: 8, reason: null,
  champions: [JINX, QUIET],
};

test("_fmtVal: null -> dash, list -> a count, scalar -> itself", () => {
  assert.strictEqual(_fmtVal(null), "-");
  assert.strictEqual(_fmtVal(undefined), "-");
  assert.strictEqual(_fmtVal(["a", "b", "c"]), "3 items");
  assert.strictEqual(_fmtVal(57), "57");
});

test("_wrClass: >=50 good else bad; non-numeric dim", () => {
  assert.strictEqual(_wrClass(65.1), "pi-good");
  assert.strictEqual(_wrClass(49.9), "pi-bad");
  assert.strictEqual(_wrClass(null), "pi-dim");
});

test("_tip: caps the detail lines and says how many were dropped", () => {
  const lines = Array.from({ length: _MAX_TIP + 3 }, (_v, i) => `line ${i}`);
  const tip = _tip(lines);
  const rows = tip.split("\n");
  assert.strictEqual(rows.length, _MAX_TIP + 1);
  assert.strictEqual(rows[rows.length - 1], "+ 3 more");
});

test("_chips: one chip per populated section, counted", () => {
  const html = _chips(JINX);
  assert.match(html, /1 stat/);
  assert.match(html, /1 ability/);
  assert.match(html, /1 build/);
  assert.match(html, /1 item/);
});

test("_chips: an empty section emits no chip at all", () => {
  assert.strictEqual(_chips(QUIET), "");
});

test("_chips: the tooltip carries the old -> new detail", () => {
  assert.match(_chips(JINX), /stats.attackdamage: 59 -&gt; 57/);
  assert.match(_chips(JINX), /balanced: 2 items -&gt; 2 items/);
});

test("_chips: no chip claims a direction (buff / nerf / better / worse)", () => {
  const html = _chips(JINX);
  assert.doesNotMatch(html, /buff|nerf|better|worse|stronger|weaker/i);
});

test("_champRow: a zero-change champion keeps its row and renders the sentinel", () => {
  const html = _champRow(QUIET);
  assert.match(html, /pi-row/);
  assert.match(html, /Tristana/);
  assert.match(html, /<span class="pi-none">-<\/span>/);
});

test("_champRow: games + winrate render, play share rides in the tooltip", () => {
  const html = _champRow(JINX);
  assert.match(html, /81g/);
  assert.match(html, /65%/);
  assert.match(html, /4% of your games this mode/);
});

test("_champRow: a null winrate degrades to the dash, not NaN", () => {
  const html = _champRow({ ...QUIET, winrate: null });
  assert.match(html, /pi-wr pi-dim">-</);
  assert.doesNotMatch(html, /NaN/);
});

test("_head: names both patches", () => {
  const html = _head(PAYLOAD);
  assert.match(html, /PATCH 16.14.1/);
  assert.match(html, /from 16.13.1/);
});

test("patchImpactHtml: renders every champion, changed or not", () => {
  const html = patchImpactHtml(PAYLOAD);
  assert.match(html, /Jinx/);
  assert.match(html, /Tristana/);
});

test("patchImpactHtml: caps the list and notes the remainder", () => {
  const many = Array.from({ length: _MAX_ROWS + 4 }, (_v, i) =>
    ({ ...QUIET, champion_id: i, name: `Champ${i}` }));
  const html = patchImpactHtml({ ...PAYLOAD, champions: many });
  assert.match(html, /\+ 4 more champions not shown/);
  assert.doesNotMatch(html, new RegExp(`Champ${_MAX_ROWS + 1}<`));
});

test("patchImpactHtml: the caption states the corpus and stays descriptive", () => {
  const html = patchImpactHtml(PAYLOAD);
  assert.match(html, /2044 aram matches/);
  assert.match(html, /8 items changed patch-wide/);
  assert.match(html, /not\s+whether the champion got better/);
});

test("patchImpactHtml: an empty champion list surfaces the backend reason", () => {
  const html = patchImpactHtml({
    ...PAYLOAD, champions: [],
    reason: "fewer than two patch snapshots on disk",
  });
  assert.match(html, /fewer than two patch snapshots on disk/);
});

test("patchImpactHtml: ok:false degrades without leaking the payload", () => {
  const html = patchImpactHtml({ ok: false, error: "C:/secret/path" });
  assert.match(html, /Patch impact unavailable/);
  assert.doesNotMatch(html, /secret/);
});

test("patchImpactHtml: null payload degrades instead of throwing", () => {
  assert.match(patchImpactHtml(null), /Patch impact unavailable/);
});

test("patchImpactHtml: champion names are escaped", () => {
  const html = patchImpactHtml({
    ...PAYLOAD, champions: [{ ...QUIET, name: "<img src=x>" }] });
  assert.doesNotMatch(html, /<img/);
  assert.match(html, /&lt;img/);
});

test("_signature: changes when a champion's change count moves", () => {
  const a = _signature(PAYLOAD);
  const b = _signature({ ...PAYLOAD,
    champions: [{ ...JINX, change_count: 5 }, QUIET] });
  assert.notStrictEqual(a, b);
});

test("_signature: is stable across identical payloads (repaint dedup)", () => {
  assert.strictEqual(_signature(PAYLOAD), _signature(JSON.parse(JSON.stringify(PAYLOAD))));
});

test("_signature: changes when the patch pair moves", () => {
  assert.notStrictEqual(
    _signature(PAYLOAD), _signature({ ...PAYLOAD, new_patch: "16.15.1" }));
});
