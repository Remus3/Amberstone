"use strict";
// FLEET-KIT v7 (MAIN order 2026-10-05 0215, section 4b-4c): each LIVE lane's
// remaining checklist, read from ops/loop/control/progress/lane-<i>.json in
// that repo's main checkout. Fixtures are invented.

const test = require("node:test");
const assert = require("node:assert/strict");

const C = require("../src/checklist.js");

const NOW = 1700000000; // epoch seconds

function iso(epochS) {
  return new Date(epochS * 1000).toISOString();
}

function progress(over) {
  return JSON.stringify(Object.assign({
    task: "lane-0",
    pct: 40,
    step: "suite",
    eta_s: 600,
    status: "running",
    updated: iso(NOW - 60),
    checklist: [
      { id: "C2", task: "Run the suite", state: "builder running", eta_s: 240 },
      { id: "C3", task: "Commit the adoption", state: null, eta_s: null },
    ],
  }, over || {}));
}

test("the progress path is one NAMED file per lane index", () => {
  assert.deepEqual(C.progressRel(0), ["ops", "loop", "control", "progress", "lane-0.json"]);
  assert.deepEqual(C.progressRel(2), ["ops", "loop", "control", "progress", "lane-2.json"]);
  assert.equal(C.ITEM_CAP, 3);
});

test("a fresh progress file yields its remaining items IN ORDER", () => {
  const c = C.checklistFor({ text: progress(), now: NOW });
  assert.equal(c.status, "live");
  assert.deepEqual(c.items.map((i) => i.id), ["C2", "C3"]);
  assert.equal(c.more, 0);
});

test("more than three items caps at three and counts the rest", () => {
  const rows = [1, 2, 3, 4, 5].map((n) => ({ id: "C" + n, task: "Task " + n, state: null, eta_s: null }));
  const c = C.checklistFor({ text: progress({ checklist: rows }), now: NOW });
  assert.deepEqual(c.items.map((i) => i.id), ["C1", "C2", "C3"]);
  assert.equal(c.more, 2);
});

test("absent, unparseable or checklist-less progress is no checklist", () => {
  for (const text of [null, undefined, "", "{ nope", "[]", JSON.stringify({ eta_s: 60, updated: iso(NOW) })]) {
    assert.equal(C.checklistFor({ text, now: NOW }).status, "none", String(text));
  }
  assert.equal(C.checklistFor({ text: progress({ checklist: "x" }), now: NOW }).status, "none");
});

test("updated older than 2x eta_s is STALE and carries NO items", () => {
  const c = C.checklistFor({ text: progress({ eta_s: 100, updated: iso(NOW - 201) }), now: NOW });
  assert.equal(c.status, "stale");
  assert.deepEqual(c.items, []);
  assert.equal(c.more, 0);
  assert.equal(
    C.checklistFor({ text: progress({ eta_s: 100, updated: iso(NOW - 199) }), now: NOW }).status,
    "live"
  );
});

test("an undatable updated or a missing eta_s cannot be proven fresh - STALE", () => {
  assert.equal(C.checklistFor({ text: progress({ updated: "not a date" }), now: NOW }).status, "stale");
  assert.equal(C.checklistFor({ text: progress({ updated: null }), now: NOW }).status, "stale");
  assert.equal(C.checklistFor({ text: progress({ eta_s: null }), now: NOW }).status, "stale");
});

test("eta_s 0 gets the write-grace floor, not instant staleness", () => {
  assert.equal(C.checklistFor({ text: progress({ eta_s: 0, updated: iso(NOW - 20) }), now: NOW }).status, "live");
  assert.equal(C.checklistFor({ text: progress({ eta_s: 0, updated: iso(NOW - 61) }), now: NOW }).status, "stale");
});

test("an ISO stamp with a local offset parses (fleet_headless writes astimezone())", () => {
  const d = new Date((NOW - 30) * 1000);
  const local = d.toISOString().replace(/\.\d{3}Z$/, "+00:00");
  assert.equal(C.checklistFor({ text: progress({ updated: local }), now: NOW }).status, "live");
});

test("junk rows are dropped, order of the good ones kept", () => {
  const rows = [{ id: "A1", task: "First" }, null, { id: 7, task: "x" }, { id: "A2", task: "" }, { id: "A3", task: "Third" }];
  const c = C.checklistFor({ text: progress({ checklist: rows }), now: NOW });
  assert.deepEqual(c.items.map((i) => i.id), ["A1", "A3"]);
});

test("itemLine: ASCII box, id, task, then state and ETA in kit units", () => {
  assert.equal(C.itemLine({ id: "C2", task: "Run the suite", state: "builder running", eta_s: 240 }),
    "[ ] C2: Run the suite (builder running, ~4m)");
  assert.equal(C.itemLine({ id: "C3", task: "Commit the adoption", state: null, eta_s: null }),
    "[ ] C3: Commit the adoption");
  assert.equal(C.itemLine({ id: "C4", task: "Wait", state: "pending", eta_s: 90 }), "[ ] C4: Wait (~90s)");
  assert.equal(C.itemLine({ id: "C5", task: "Long", state: null, eta_s: 3 * 3600 }), "[ ] C5: Long (~3h)");
});

test("itemLine never emits a non-ASCII glyph, whatever the file carried", () => {
  const s = C.itemLine({ id: "C1", task: "Caf" + String.fromCharCode(0xe9, 0x20, 0x2014, 0x20, 0x2610) + " build", state: "r" + String.fromCharCode(0xfc) + "n", eta_s: 5 });
  assert.match(s, /^[\x20-\x7e]*$/, s);
});
