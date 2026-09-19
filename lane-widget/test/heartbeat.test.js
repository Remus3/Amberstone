"use strict";
// Slice A - heartbeat.js. Newest lane log per lane, plus a stall flag.
//
// The filename grammar mirrors dashboard/routes_loop_status.py:99-102:
// lane_<lane>_<run_id>.log, where the LANE MAY CONTAIN A HYPHEN
// ("true-audit"), so run_id is the LAST underscore-separated segment.
//
// We only ever stat these files. The logs are legitimately mixed UTF-8 /
// UTF-16LE (routes_loop_status.py:118-162) and nothing here decodes them.

const test = require("node:test");
const assert = require("node:assert/strict");

const { LOG_RE, parseLogName, newestPerLane, DEFAULT_STALL_AFTER_S } =
  require("../src/heartbeat.js");

// `now` is epoch SECONDS everywhere in slice A (it pairs with the lock `ts`,
// which is python time.time()). Entry mtimes arrive in MILLISECONDS.
const NOW = 2000;
const ms = (s) => s * 1000;

test("LOG_RE is a regexp over the documented grammar", () => {
  assert.ok(LOG_RE instanceof RegExp);
  assert.ok(LOG_RE.test("lane_queue_203a23be.log"));
  assert.ok(!LOG_RE.test("lane_gated_20260802T152212Z.md"));
});

test("parseLogName splits a simple lane name", () => {
  assert.deepEqual(parseLogName("lane_queue_203a23be.log"),
    { lane: "queue", runId: "203a23be" });
});

test("HYPHENATED LANE: run_id is the LAST underscore segment", () => {
  assert.deepEqual(parseLogName("lane_true-audit_5e9c917b.log"),
    { lane: "true-audit", runId: "5e9c917b" });
});

test("a run id that itself looks like a timestamp still parses", () => {
  assert.deepEqual(parseLogName("lane_gated_20260802T152212Z.log"),
    { lane: "gated", runId: "20260802T152212Z" });
});

test("a lane name containing an underscore keeps the LAST segment as run id", () => {
  assert.deepEqual(parseLogName("lane_a_b_c_run9.log"),
    { lane: "a_b_c", runId: "run9" });
});

test("parseLogName returns null for anything off-grammar", () => {
  for (const n of [
    "lane_queue.log", "lane__x.log", "queue_203a23be.log",
    "lane_gated_20260802T152212Z.md", "lane_queue_203a23be.log.1",
    "controller.log", "lane_.log", "", "lane_queue_.log",
  ]) {
    assert.equal(parseLogName(n), null, `name=${JSON.stringify(n)}`);
  }
});

test("parseLogName is total for null and non-string input", () => {
  for (const n of [null, undefined, 42, {}, [], true]) {
    assert.equal(parseLogName(n), null);
  }
});

test("LOG_RE has no lastIndex state that leaks between calls", () => {
  const n = "lane_queue_203a23be.log";
  assert.notEqual(parseLogName(n), null);
  assert.notEqual(parseLogName(n), null);
  assert.notEqual(parseLogName(n), null);
});

// -------------------------------------------------------------- newestPerLane
test("only the newest entry per LANE survives", () => {
  const rows = newestPerLane([
    { name: "lane_queue_old.log", mtimeMs: ms(1000) },
    { name: "lane_queue_new.log", mtimeMs: ms(1900) },
    { name: "lane_ds_only.log", mtimeMs: ms(1500) },
  ], { now: NOW });
  assert.equal(rows.length, 2);
  assert.deepEqual(rows.map((r) => r.lane), ["queue", "ds"]);
  assert.equal(rows[0].runId, "new");
});

test("rows are newest-first", () => {
  const rows = newestPerLane([
    { name: "lane_a_1.log", mtimeMs: ms(1100) },
    { name: "lane_b_1.log", mtimeMs: ms(1900) },
    { name: "lane_c_1.log", mtimeMs: ms(1500) },
  ], { now: NOW });
  assert.deepEqual(rows.map((r) => r.lane), ["b", "c", "a"]);
});

test("each row carries lane, runId, name, mtimeMs, ageS and stalled", () => {
  const [row] = newestPerLane(
    [{ name: "lane_queue_203a23be.log", mtimeMs: ms(1900) }], { now: NOW });
  assert.deepEqual(row, {
    lane: "queue",
    runId: "203a23be",
    name: "lane_queue_203a23be.log",
    mtimeMs: ms(1900),
    ageS: 100,
    stalled: false,
  });
});

test("ageS is clamped at zero for a future mtime", () => {
  const [row] = newestPerLane(
    [{ name: "lane_q_1.log", mtimeMs: ms(9999) }], { now: NOW });
  assert.equal(row.ageS, 0);
});

test("stalled is ageS > stallAfterS, default 600", () => {
  assert.equal(DEFAULT_STALL_AFTER_S, 600);
  const rows = newestPerLane([
    { name: "lane_a_1.log", mtimeMs: ms(1399) },
    { name: "lane_b_1.log", mtimeMs: ms(1400) },
    { name: "lane_c_1.log", mtimeMs: ms(1401) },
  ], { now: NOW });
  const by = Object.fromEntries(rows.map((r) => [r.lane, r.stalled]));
  assert.equal(by.a, true);   // age 601
  assert.equal(by.b, false);  // age 600, boundary is exclusive
  assert.equal(by.c, false);  // age 599
});

test("stallAfterS is configurable", () => {
  const [row] = newestPerLane(
    [{ name: "lane_a_1.log", mtimeMs: ms(1990) }], { now: NOW, stallAfterS: 5 });
  assert.equal(row.stalled, true);
});

test("a non-finite stallAfterS falls back to the default", () => {
  for (const s of [NaN, Infinity, -1, "x", null]) {
    const [row] = newestPerLane(
      [{ name: "lane_a_1.log", mtimeMs: ms(1900) }], { now: NOW, stallAfterS: s });
    assert.equal(row.stalled, false, `stallAfterS=${String(s)}`);
  }
});

test("off-grammar names are dropped, including the .md siblings on disk", () => {
  const rows = newestPerLane([
    { name: "lane_gated_20260802T152212Z.md", mtimeMs: ms(1999) },
    { name: "controller.log", mtimeMs: ms(1999) },
    { name: "lane_gated_a785e11a.log", mtimeMs: ms(1000) },
  ], { now: NOW });
  assert.equal(rows.length, 1);
  assert.equal(rows[0].name, "lane_gated_a785e11a.log");
});

test("a non-finite mtime yields null ageS, false stalled, and still ranks last", () => {
  const rows = newestPerLane([
    { name: "lane_a_1.log", mtimeMs: NaN },
    { name: "lane_b_1.log", mtimeMs: ms(1000) },
  ], { now: NOW });
  assert.deepEqual(rows.map((r) => r.lane), ["b", "a"]);
  const a = rows.find((r) => r.lane === "a");
  assert.equal(a.mtimeMs, null);
  assert.equal(a.ageS, null);
  assert.equal(a.stalled, false);
});

test("a missing mtime never wins the newest-per-lane contest", () => {
  const rows = newestPerLane([
    { name: "lane_q_bad.log" },
    { name: "lane_q_good.log", mtimeMs: ms(1000) },
  ], { now: NOW });
  assert.equal(rows.length, 1);
  assert.equal(rows[0].runId, "good");
});

test("a non-finite now yields null ageS and no stall claim", () => {
  for (const now of [undefined, null, NaN, Infinity, "x"]) {
    const [row] = newestPerLane(
      [{ name: "lane_a_1.log", mtimeMs: ms(1000) }], { now });
    assert.equal(row.ageS, null, `now=${String(now)}`);
    assert.equal(row.stalled, false);
  }
});

test("empty, null and junk inputs all return an empty array", () => {
  for (const entries of [[], null, undefined, "x", {}, 42]) {
    const rows = newestPerLane(entries, { now: NOW });
    assert.ok(Array.isArray(rows));
    assert.equal(rows.length, 0);
  }
});

test("junk entries inside a good listing are dropped", () => {
  const rows = newestPerLane([
    null, 42, "x", [], {}, { mtimeMs: ms(1000) },
    { name: "lane_q_1.log", mtimeMs: ms(1000) },
  ], { now: NOW });
  assert.equal(rows.length, 1);
});

test("a missing options object is tolerated", () => {
  const rows = newestPerLane([{ name: "lane_q_1.log", mtimeMs: ms(1000) }]);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].ageS, null);
});

test("ties keep a stable order", () => {
  const rows = newestPerLane([
    { name: "lane_a_1.log", mtimeMs: ms(1000) },
    { name: "lane_b_1.log", mtimeMs: ms(1000) },
    { name: "lane_c_1.log", mtimeMs: ms(1000) },
  ], { now: NOW });
  assert.deepEqual(rows.map((r) => r.lane), ["a", "b", "c"]);
});

test("newestPerLane does not mutate the listing it is handed", () => {
  const entries = [{ name: "lane_q_1.log", mtimeMs: ms(1000) }];
  const before = JSON.stringify(entries);
  newestPerLane(entries, { now: NOW });
  assert.equal(JSON.stringify(entries), before);
});
