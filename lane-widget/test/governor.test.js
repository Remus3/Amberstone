"use strict";
// FLEET-KIT v6 governor strip (MAIN order 2026-10-04 2237, section 4b): ONE
// machine strip from the shared slot root's 0..2.lock and its sibling queue
// directory. Mirrors fleet_lanes.py _slot_stale / _ticket_live. Read-only;
// fixtures are invented.

const test = require("node:test");
const assert = require("node:assert/strict");

const G = require("../src/governor.js");

const NOW = 1700000000;
const LIVE = 7676;
const LIVE2 = 7677;
const DEAD = 4242;
const alive = (pid) => pid === LIVE || pid === LIVE2;
const noStart = () => null;

const ROSTER = [
  { code: "RC", root: "C:\\fake-a" },
  { code: "CS", root: "C:\\fake-b" },
];

function slot(over) {
  return { text: JSON.stringify(Object.assign({ pid: LIVE, repo: "RC", run_id: "r", cycle: 0, ts: NOW - 60 }, over || {})), mtimeS: NOW - 60 };
}

const FREE_SLOT = { text: null, mtimeS: null };

test("the slot root mirrors fleet_lanes.governor_root and the queue is its sibling", () => {
  assert.equal(G.GOVERNOR_WIDTH, 3);
  assert.deepEqual(G.SLOT_NAMES, ["0.lock", "1.lock", "2.lock"]);
  const root = G.governorRoot({ ProgramData: "C:\\fake-pd" });
  assert.match(root, /fake-pd[\\/]lw-loop[\\/]slots$/);
  assert.match(G.queueRoot(root), /fake-pd[\\/]lw-loop[\\/]queue$/);
  assert.equal(G.governorRoot({ PROGRAMDATA: "C:\\fake-pd2" }).indexOf("fake-pd2") !== -1, true);
  assert.equal(G.governorRoot({}), null, "no ProgramData -> no strip, never a guessed path");
});

test("slotState: absent FREE, live pid RUNNING, dead pid RECLAIMABLE", () => {
  const o = { now: NOW, pidAlive: alive, procStarted: noStart };
  assert.equal(G.slotState(Object.assign({}, FREE_SLOT, o)), "FREE");
  assert.equal(G.slotState(Object.assign({}, slot(), o)), "RUNNING");
  assert.equal(G.slotState(Object.assign({}, slot({ pid: DEAD }), o)), "RECLAIMABLE");
});

test("slotState: a live executor child keeps the slot (mark_child)", () => {
  const s = slot({ pid: DEAD, child_pid: LIVE, child_started: 5 });
  assert.equal(G.slotState(Object.assign({}, s, { now: NOW, pidAlive: alive, procStarted: noStart })), "RUNNING");
});

test("slotState: a reused pid (start time differs) is RECLAIMABLE", () => {
  const s = slot({ pid_started: 100 });
  assert.equal(G.slotState(Object.assign({}, s, { now: NOW, pidAlive: alive, procStarted: () => 900 })), "RECLAIMABLE");
});

test("slotState: past the hard ceiling (2x stale_after) even a live pid is RECLAIMABLE", () => {
  const s = slot({ ts: NOW - 2 * G.DEFAULT_STALE_AFTER_S - 1 });
  assert.equal(G.slotState(Object.assign({}, s, { now: NOW, pidAlive: alive, procStarted: noStart })), "RECLAIMABLE");
});

test("slotState: an empty / half-written slot is judged by its mtime against stale_after", () => {
  const o = { now: NOW, pidAlive: alive, procStarted: noStart };
  assert.equal(G.slotState(Object.assign({ text: "", mtimeS: NOW - 5 }, o)), "RUNNING");
  assert.equal(G.slotState(Object.assign({ text: "", mtimeS: NOW - G.DEFAULT_STALE_AFTER_S - 1 }, o)), "RECLAIMABLE");
  assert.equal(G.slotState(Object.assign({ text: "{x", mtimeS: null }, o)), "RECLAIMABLE");
});

test("ticketLive: heartbeat within 120 s and a live, non-stranger pid", () => {
  const o = { now: NOW, pidAlive: alive, procStarted: noStart };
  const t = (over, mt) => Object.assign({ text: JSON.stringify(Object.assign({ pid: LIVE, repo: "CS", ts: NOW - 300 }, over || {})), mtimeS: mt }, o);
  assert.equal(G.ticketLive(t({}, NOW - 10)), true);
  assert.equal(G.ticketLive(t({}, NOW - 121)), false, "stopped polling");
  assert.equal(G.ticketLive(t({ pid: DEAD }, NOW - 10)), false, "dead waiter");
  assert.equal(G.ticketLive(Object.assign({ text: "", mtimeS: NOW - 5 }, o)), true, "just filed");
  assert.equal(G.ticketLive(Object.assign({ text: "", mtimeS: NOW - 31 }, o)), false);
  assert.equal(G.ticketLive(Object.assign({ text: "{}", mtimeS: null }, o)), false);
});

test("repoLabel: a code passes, a ROOT PATH maps to its roster code, anything else is ?", () => {
  // RC's loop_controller passes repo=str(ROOT) - a path. It must never render.
  assert.equal(G.repoLabel("RC", ROSTER), "RC");
  assert.equal(G.repoLabel("cs", ROSTER), "CS");
  assert.equal(G.repoLabel("C:\\fake-b", ROSTER), "CS");
  assert.equal(G.repoLabel("c:/FAKE-A/", ROSTER), "RC");
  assert.equal(G.repoLabel("C:\\Some Unknown Sibling", ROSTER), "?");
  assert.equal(G.repoLabel("", ROSTER), "?");
  assert.equal(G.repoLabel(null, ROSTER), "?");
});

test("governorFor + governorLine: held count, holders in slot order, queue depth", () => {
  const g = G.governorFor({
    slots: [slot({ repo: "C:\\fake-a" }), FREE_SLOT, slot({ pid: LIVE2, repo: "CS" })],
    tickets: [
      { text: JSON.stringify({ pid: LIVE, repo: "RC", ts: NOW - 5 }), mtimeS: NOW - 2 },
      { text: JSON.stringify({ pid: DEAD, repo: "RC", ts: NOW - 5 }), mtimeS: NOW - 2 },
    ],
    roster: ROSTER,
    now: NOW,
    pidAlive: alive,
    procStarted: noStart,
  });
  assert.deepEqual(g, { width: 3, held: 2, stale: 0, repos: ["RC", "CS"], queue: 1 });
  assert.deepEqual(G.governorLine(g), { text: "Governor 2/3 - RC, CS - queue 1", alarm: false });
});

test("governorLine: idle machine, and a stale slot is said and alarmed", () => {
  assert.deepEqual(G.governorLine({ width: 3, held: 0, stale: 0, repos: [], queue: 0 }),
    { text: "Governor 0/3 - queue 0", alarm: false });
  assert.deepEqual(G.governorLine({ width: 3, held: 1, stale: 1, repos: ["EW"], queue: 0 }),
    { text: "Governor 1/3 - EW - queue 0 - 1 stale", alarm: true });
  assert.equal(G.governorLine(null), null);
});

test("governorFor is total over junk", () => {
  const g = G.governorFor({});
  assert.deepEqual(g, { width: 3, held: 0, stale: 0, repos: [], queue: 0 });
});
