// web/js/panels/active_match_coach_table.test.mjs
//
// Coach markdown-table render fix (2026-07-12). Run with `node --test`.
//
// The Haiku macro coach occasionally emits a `| FIELD | DECISION |` markdown
// TABLE instead of the `Label: value` line format. coach_integration/_coach.py
// ::_parse_response space-joins the table's continuation lines into ONE field
// string, so the CALL pane rendered it as a raw-pipe WALL that overflowed the
// card (operator-reported live). _parseCoachTable detects that leaked table and
// hands _line clean {title, rows:[{label,value}]} so it lays out label:value
// rows instead of the pipes. These pin the pure parser (no DOM):
//   - a space-joined table parses via the all-dash separator anchor (newlines
//     are already lost by the Python join);
//   - normal coach prose with a stray single pipe / single dashes does NOT
//     false-trigger (returns null -> plain text path).

import test from "node:test";
import assert from "node:assert";

import { _parseCoachTable } from "./active_match.js";

// The exact shape _parse_response produces from a leaked markdown table (its
// `" ".join(current_val)` collapses the newlines to spaces).
const LEAKED =
  "DEFEND & SETUP TEAMFIGHT | FIELD | DECISION | |------|--------| " +
  "| WAVE | HOLD/THIN - DO NOT PUSH, keep minions mid | " +
  "| OBJECTIVE | DRAKE + BARON BOTH LIVE - contest drake first | " +
  "| FIGHT RULE | ONLY TRADE IF ALL 4 ALLIES ARE VISIBLE |";

test("_parseCoachTable: space-joined leaked table -> title + clean rows", () => {
  const t = _parseCoachTable(LEAKED);
  assert.ok(t, "a leaked table must be detected");
  assert.equal(t.title, "DEFEND & SETUP TEAMFIGHT");
  assert.equal(t.rows.length, 3, "WAVE / OBJECTIVE / FIGHT RULE = 3 rows");
  assert.deepEqual(
    t.rows.map((r) => r.label),
    ["WAVE", "OBJECTIVE", "FIGHT RULE"],
  );
  assert.equal(t.rows[0].value, "HOLD/THIN - DO NOT PUSH, keep minions mid");
  assert.equal(t.rows[2].value, "ONLY TRADE IF ALL 4 ALLIES ARE VISIBLE");
  // The FIELD/DECISION header row + the |---| separator are stripped, not rendered.
  for (const r of t.rows) {
    assert.ok(!/\|/.test(r.value), "no raw pipe survives into a row value");
    assert.ok(r.label !== "FIELD", "the header row must be dropped");
  }
});

test("_parseCoachTable: table with a leading pipe (no title) -> empty title", () => {
  const t = _parseCoachTable("| KEY | VAL | |---|---| | PUSH | shove mid |");
  assert.ok(t);
  assert.equal(t.title, "");
  assert.deepEqual(t.rows, [{ label: "PUSH", value: "shove mid" }]);
});

test("_parseCoachTable: newlines-intact table also parses", () => {
  const nl = "SETUP\n| FIELD | DECISION |\n|---|---|\n| WAVE | freeze |\n| WARD | pixel |";
  const t = _parseCoachTable(nl);
  assert.ok(t);
  assert.equal(t.title, "SETUP");
  assert.deepEqual(t.rows.map((r) => r.label), ["WAVE", "WARD"]);
});

test("_parseCoachTable: plain coach prose -> null (no false trigger)", () => {
  assert.equal(_parseCoachTable("Hard shove - crash the wave and roam bot"), null);
  assert.equal(_parseCoachTable("Never fight 2v1 vs Malphite + Lux without Flash"), null);
  assert.equal(_parseCoachTable(""), null);
  assert.equal(_parseCoachTable(null), null);
  assert.equal(_parseCoachTable(undefined), null);
});

test("_parseCoachTable: a stray single pipe / single dashes do NOT trigger", () => {
  // A lone pipe with no dash-separator cell is not a table.
  assert.equal(_parseCoachTable("back | mid | top rotation"), null);
  // Single dashes (a range / clause break) are not a separator row.
  assert.equal(_parseCoachTable("hold until 50-100 gold | then back"), null);
});
