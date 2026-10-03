"use strict";
// inbox_status.js - parse one tree's ops/loop/control/inbox_status.json (schema
// 1) and reduce it to the operator's "Sync:" line.
//
// The four operator example lines are asserted VERBATIM. Fixtures carry no
// filesystem path and no sibling name; codes are invented placeholders.

const test = require("node:test");
const assert = require("node:assert/strict");

const s = require("../src/inbox_status.js");

// A fixed clock. 2026-10-03T12:00:00Z in epoch SECONDS.
const NOW = Date.parse("2026-10-03T12:00:00Z") / 1000;

function iso(epochS) {
  return new Date(epochS * 1000).toISOString();
}

function status(over) {
  return Object.assign(
    {
      schema: 1,
      code: "AAA",
      updated: iso(NOW - 10),
      state: "running",
      task: "Running Session",
      task_started: iso(NOW - 60),
      task_eta_s: null,
      next_tick: null,
      runs_in_window: 0,
      runs_cap: 120,
      window_s: 86400,
      cap_frees_at: null,
    },
    over || {}
  );
}

function line(blob, opts) {
  const text = blob === null ? null : JSON.stringify(blob);
  return s.syncText(s.syncFor(Object.assign({ text, now: NOW, tickS: 300 }, opts || {})));
}

// ---------------------------------------------------- operator examples ----

test("operator example 1 renders verbatim: Appending Ledger", () => {
  const got = line(status({
    task: "Appending Ledger",
    task_started: iso(NOW - (35 * 60 + 20)),
    task_eta_s: 42 * 60,
    runs_in_window: 25,
  }));
  assert.equal(got, "Sync: Appending Ledger [35m/42m][25/120]");
});

test("operator example 2 renders verbatim: Running a Command", () => {
  const got = line(status({
    task: "Running a Command",
    task_started: iso(NOW - 90),
    task_eta_s: 180,
    runs_in_window: 12,
  }));
  assert.equal(got, "Sync: Running a Command [1m/3m][12/120]");
});

test("operator example 3 renders verbatim: Idle is elapsed idle over the tick span", () => {
  const started = NOW - (4 * 60 + 10);
  const got = line(status({
    state: "idle",
    task: "Idle",
    task_started: iso(started),
    next_tick: iso(started + 300),
    runs_in_window: 110,
  }));
  assert.equal(got, "Sync: Idle [4m/5m][110/120]");
});

test("operator example 4 renders verbatim: Turn Limit Reached counts hours to cap_frees_at", () => {
  const got = line(status({
    state: "limit",
    task: "Turn Limit Reached",
    task_started: iso(NOW - 3600),
    cap_frees_at: iso(NOW + 4 * 3600 - 900),
    runs_in_window: 120,
  }));
  assert.equal(got, "Sync: Turn Limit Reached [4HR][120/120]");
});

// ----------------------------------------------------------- unknowns ------

test("an unknown ETA renders a question mark, never a guess", () => {
  const got = line(status({
    task: "Appending Ledger",
    task_started: iso(NOW - 35 * 60),
    task_eta_s: null,
    runs_in_window: 25,
  }));
  assert.equal(got, "Sync: Appending Ledger [35m/?][25/120]");
});

test("a limit with no cap_frees_at renders a question mark", () => {
  const got = line(status({ state: "limit", task: "Turn Limit Reached", runs_in_window: 120 }));
  assert.equal(got, "Sync: Turn Limit Reached [?][120/120]");
});

test("missing run counters render question marks rather than zeros", () => {
  const got = line(status({ task_eta_s: 300, runs_in_window: "x", runs_cap: null }));
  assert.equal(got, "Sync: Running Session [1m/5m][?/?]");
});

// ----------------------------------------------------------- no signal -----

test("an absent file is no signal with an unknown age", () => {
  assert.equal(line(null), "Sync: no signal [?]");
});

test("an unparseable file is no signal, never a crash", () => {
  const got = s.syncText(s.syncFor({ text: "{not json", now: NOW, tickS: 300 }));
  assert.equal(got, "Sync: no signal [?]");
});

test("a wrong schema or an unknown state is no signal", () => {
  assert.equal(line(status({ schema: 2 })), "Sync: no signal [?]");
  assert.equal(line(status({ state: "dancing" })), "Sync: no signal [?]");
});

test("a file older than 2x the tick is no signal with its age, never stale numbers", () => {
  const got = line(status({
    updated: iso(NOW - 601),
    task: "Appending Ledger",
    task_eta_s: 42 * 60,
    runs_in_window: 25,
  }), { tickS: 300 });
  assert.equal(got, "Sync: no signal [10m]");
});

test("exactly 2x the tick is still live", () => {
  const got = line(status({ updated: iso(NOW - 600), task_eta_s: 300 }), { tickS: 300 });
  assert.ok(got.startsWith("Sync: Running Session"), got);
});

test("a long-dead file reports its age in hours past 120 minutes", () => {
  assert.equal(line(status({ updated: iso(NOW - 5 * 3600) })), "Sync: no signal [5HR]");
});

test("a missing or junk updated stamp is no signal", () => {
  assert.equal(line(status({ updated: "yesterday-ish" })), "Sync: no signal [?]");
  assert.equal(line(status({ updated: undefined })), "Sync: no signal [?]");
});

// ------------------------------------------------------------ attended -----

test("an attended-only tree renders attended only and reads nothing", () => {
  const got = s.syncText(s.syncFor({ attendedOnly: true, text: JSON.stringify(status()), now: NOW }));
  assert.equal(got, "Sync: attended only");
});

// ------------------------------------------------------------ hygiene ------

test("the task is capped at 24 chars and stripped to printable ASCII", () => {
  // Built from char codes so this source file itself stays 7-bit ASCII.
  const nonAscii = "Caf" + String.fromCharCode(0xe9) + " " + String.fromCharCode(0x2014);
  const got = line(status({ task: nonAscii + " a very long task name indeed", task_eta_s: 300 }));
  const task = got.slice("Sync: ".length, got.indexOf(" ["));
  assert.ok(task.length <= 24, task);
  assert.match(got, /^[\x20-\x7e]+$/);
});

test("an empty task falls back to the basic name for the state", () => {
  assert.equal(
    line(status({ state: "backoff", task: "", task_eta_s: 120 })),
    "Sync: Backing Off [1m/2m][0/120]"
  );
});

test("durations: minutes under 120m, then HR", () => {
  assert.equal(s.formatSpan(0, "floor"), "0m");
  assert.equal(s.formatSpan(119 * 60 + 59, "floor"), "119m");
  assert.equal(s.formatSpan(120 * 60, "floor"), "2HR");
  assert.equal(s.formatSpan(119 * 60 + 30, "ceil"), "2HR");
  assert.equal(s.formatSpan(null, "ceil"), "?");
  assert.equal(s.formatSpan(-5, "floor"), "?");
});

test("a task_started in the future clamps elapsed to zero", () => {
  assert.equal(
    line(status({ task_started: iso(NOW + 50), task_eta_s: 60 })),
    "Sync: Running Session [0m/1m][0/120]"
  );
});

test("syncFor and syncText never throw on junk", () => {
  for (const junk of [undefined, null, 0, "x", [], { text: 5 }, { text: "[]" }, { text: "null" }]) {
    assert.match(s.syncText(s.syncFor(junk)), /^Sync: /);
  }
  assert.match(s.syncText(null), /^Sync: /);
});

test("the status path is ops/loop/control/inbox_status.json", () => {
  assert.deepEqual(s.STATUS_REL, ["ops", "loop", "control", "inbox_status.json"]);
});
