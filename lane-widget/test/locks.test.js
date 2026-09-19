"use strict";
// Slice A - locks.js. THE correctness property of this build:
// liveness is decided by a PID PROBE and never by file existence.
//
// Mirrors ops/loop/lanes.py:271-312 (lane_state) and :186-242
// (_holder_is_a_stranger). Fixtures are invented; no real sibling path appears.

const test = require("node:test");
const assert = require("node:assert/strict");

const L = require("../src/locks.js");

const DEAD = 4242;
const LIVE = 7676;

const aliveOnly = (pid) => pid === LIVE;
const noStart = () => null;

function payload(over) {
  return Object.assign(
    {
      pid: LIVE,
      lane: "queue",
      run_id: "203a23be",
      worktree: "C:\\fake-worktrees\\wt-queue",
      ts: 1000,
      repo: "C:\\fake-a",
      pid_started: 900,
    },
    over || {}
  );
}

// ---------------------------------------------------------------- constants
test("lock relative paths match the python contract", () => {
  assert.deepEqual(L.LANE_LOCK_REL, ["ops", "loop", "control", "lanes", "0.lock"]);
  assert.deepEqual(L.CTRL_LOCK_REL, ["ops", "loop", "control", "RUNNING.lock"]);
});

test("the three state strings are exactly the python ones", () => {
  assert.equal(L.FREE, "FREE");
  assert.equal(L.RUNNING, "RUNNING");
  assert.equal(L.RECLAIMABLE, "RECLAIMABLE");
});

test("tolerances mirror lanes.py, not the spec prose", () => {
  // ops/loop/lanes.py:225 _PID_IDENTITY_EPS_S = 1.0 (the spec said 2).
  assert.equal(L.START_TOLERANCE_S, 1.0);
  // ops/loop/lanes.py:150 WRITE_GRACE_S = 30.0
  assert.equal(L.WRITE_GRACE_S, 30.0);
});

// ---------------------------------------------------------------- parseLock
test("parseLock returns null for null, empty and blank input", () => {
  for (const raw of [null, undefined, "", "   ", "\n\t "]) {
    assert.equal(L.parseLock(raw), null, `raw=${JSON.stringify(raw)}`);
  }
});

test("parseLock returns null for malformed JSON", () => {
  for (const raw of ["{", "{not json}", "{'a':1}", "[1,2", "undefined"]) {
    assert.equal(L.parseLock(raw), null, `raw=${raw}`);
  }
});

test("parseLock returns null for valid JSON that is not an object", () => {
  for (const raw of ["[]", "[1,2]", "42", '"text"', "null", "true"]) {
    assert.equal(L.parseLock(raw), null, `raw=${raw}`);
  }
});

test("parseLock returns the payload object for a real lock body", () => {
  const raw =
    '{"pid": 7676, "lane": "queue", "run_id": "203a23be", ' +
    '"worktree": "C:\\\\fake-worktrees\\\\wt-queue", "ts": 1788737070.5, ' +
    '"repo": "C:\\\\fake-a", "pid_started": 1788737070.5, "claimed_by_pid": 9932}';
  const p = L.parseLock(raw);
  assert.equal(p.pid, 7676);
  assert.equal(p.lane, "queue");
  assert.equal(p.run_id, "203a23be");
  assert.equal(p.claimed_by_pid, 9932);
});

test("parseLock never throws on a non-string argument", () => {
  for (const raw of [{}, [], 42, true, Symbol.iterator]) {
    assert.equal(L.parseLock(raw), null);
  }
});

// -------------------------------------------------------------- effectivePid
test("effectivePid prefers `pid` - claimed_by_pid is the HISTORICAL claimer", () => {
  // ops/loop/lanes.py:441-443 sets rec["pid"] = worker pid and
  // rec["claimed_by_pid"] = the long-lived RC server that claimed the lane.
  // Probing claimed_by_pid would read RUNNING forever after the worker died.
  assert.equal(L.effectivePid({ pid: 7676, claimed_by_pid: 9932 }), 7676);
});

test("effectivePid falls back to claimed_by_pid only when pid is unusable", () => {
  assert.equal(L.effectivePid({ claimed_by_pid: 9932 }), 9932);
  assert.equal(L.effectivePid({ pid: null, claimed_by_pid: 9932 }), 9932);
  assert.equal(L.effectivePid({ pid: "junk", claimed_by_pid: 9932 }), 9932);
});

test("effectivePid returns 0 for every unreadable shape", () => {
  for (const p of [null, undefined, {}, [], 42, "x", { pid: 0 }, { pid: -3 },
    { pid: NaN }, { pid: Infinity }, { pid: 1.5 }, { pid: "junk" }]) {
    assert.equal(L.effectivePid(p), 0, `p=${JSON.stringify(p)}`);
  }
});

test("effectivePid accepts a numeric string pid", () => {
  assert.equal(L.effectivePid({ pid: "7676" }), 7676);
});

// --------------------------------------------------------------------- ageS
test("ageS is seconds since ts, clamped at zero", () => {
  assert.equal(L.ageS({ ts: 1000 }, 1300), 300);
  assert.equal(L.ageS({ ts: 1000 }, 900), 0);
});

test("ageS is null when ts is missing or not finite", () => {
  for (const p of [null, undefined, {}, { ts: null }, { ts: "x" },
    { ts: NaN }, { ts: Infinity }, { ts: -Infinity }]) {
    assert.equal(L.ageS(p, 1000), null, `p=${JSON.stringify(p)}`);
  }
});

test("ageS is null when now is not finite", () => {
  for (const now of [undefined, null, NaN, Infinity, "x"]) {
    assert.equal(L.ageS({ ts: 1000 }, now), null);
  }
});

test("ageS accepts a numeric string ts", () => {
  assert.equal(L.ageS({ ts: "1000" }, 1100), 100);
});

// ----------------------------------------------------------------- classify
test("no lock at all is FREE", () => {
  const r = L.classify({ payload: null, now: 2000, pidAlive: aliveOnly, procStarted: noStart });
  assert.equal(r.state, "FREE");
  assert.equal(r.pid, 0);
  assert.equal(typeof r.reason, "string");
});

test("a live holder is RUNNING", () => {
  const r = L.classify({
    payload: payload({ pid_started: undefined }),
    now: 2000,
    pidAlive: aliveOnly,
    procStarted: noStart,
  });
  assert.equal(r.state, "RUNNING");
  assert.equal(r.pid, LIVE);
});

// ---- THE REGRESSION THAT MATTERS ----
test("REGRESSION: a well-formed payload whose pid is DEAD is RECLAIMABLE", () => {
  // RC has stale lane locks on disk right now. A classifier that trusted file
  // existence would render them as phantom RUNNING lanes.
  const r = L.classify({
    payload: payload({ pid: DEAD }),
    now: 2000,
    pidAlive: aliveOnly,
    procStarted: noStart,
  });
  assert.equal(r.state, "RECLAIMABLE");
  assert.equal(r.pid, DEAD);
  assert.match(r.reason, /pid/);
});

test("REGRESSION: file existence alone never yields RUNNING", () => {
  // Every field present, perfectly parseable, recent ts - and still stale,
  // because the only thing that decides liveness is the pid probe.
  const r = L.classify({
    payload: payload({ pid: DEAD, ts: 1999 }),
    now: 2000,
    pidAlive: () => false,
    procStarted: noStart,
  });
  assert.equal(r.state, "RECLAIMABLE");
});

test("REGRESSION: the repointed real-world shape is probed on `pid`, not claimed_by_pid", () => {
  // Live shape measured on disk: pid = dead worker, claimed_by_pid = live RC.
  const r = L.classify({
    payload: payload({ pid: DEAD, claimed_by_pid: LIVE, pid_started: undefined }),
    now: 2000,
    pidAlive: aliveOnly,
    procStarted: noStart,
  });
  assert.equal(r.state, "RECLAIMABLE");
  assert.equal(r.pid, DEAD);
});

// ---- stranger guard, both directions ----
test("STRANGER GUARD: a live pid with a MISMATCHED pid_started is RECLAIMABLE", () => {
  const r = L.classify({
    payload: payload({ pid: LIVE, pid_started: 900 }),
    now: 2000,
    pidAlive: aliveOnly,
    procStarted: () => 1500, // the OS reissued the pid
  });
  assert.equal(r.state, "RECLAIMABLE");
  assert.match(r.reason, /reuse|stranger/i);
});

test("STRANGER GUARD: an UNKNOWN (null) procStarted is NOT a stranger", () => {
  // ops/loop/lanes.py:232-240 - every uncertain case answers False. Freeing a
  // lane on a guess double-books a running worker.
  const r = L.classify({
    payload: payload({ pid: LIVE, pid_started: 900 }),
    now: 2000,
    pidAlive: aliveOnly,
    procStarted: () => null,
  });
  assert.equal(r.state, "RUNNING");
});

test("STRANGER GUARD: a non-finite procStarted result is NOT a stranger", () => {
  for (const v of [NaN, Infinity, -Infinity, undefined, "x", {}]) {
    const r = L.classify({
      payload: payload({ pid: LIVE, pid_started: 900 }),
      now: 2000,
      pidAlive: aliveOnly,
      procStarted: () => v,
    });
    assert.equal(r.state, "RUNNING", `v=${String(v)}`);
  }
});

test("STRANGER GUARD: an absent or unparseable pid_started is NOT a stranger", () => {
  for (const rec of [undefined, null, "x", NaN, {}]) {
    const r = L.classify({
      payload: payload({ pid: LIVE, pid_started: rec }),
      now: 2000,
      pidAlive: aliveOnly,
      procStarted: () => 1500,
    });
    assert.equal(r.state, "RUNNING", `pid_started=${String(rec)}`);
  }
});

test("STRANGER GUARD: a drift inside the tolerance is NOT a stranger", () => {
  const r = L.classify({
    payload: payload({ pid: LIVE, pid_started: 900 }),
    now: 2000,
    pidAlive: aliveOnly,
    procStarted: () => 900.5,
  });
  assert.equal(r.state, "RUNNING");
});

test("STRANGER GUARD: drift is absolute, so a NEGATIVE difference also catches", () => {
  const r = L.classify({
    payload: payload({ pid: LIVE, pid_started: 1500 }),
    now: 2000,
    pidAlive: aliveOnly,
    procStarted: () => 900,
  });
  assert.equal(r.state, "RECLAIMABLE");
});

test("STRANGER GUARD: the dead-pid probe wins before the guard is consulted", () => {
  let asked = false;
  const r = L.classify({
    payload: payload({ pid: DEAD, pid_started: 900 }),
    now: 2000,
    pidAlive: () => false,
    procStarted: () => {
      asked = true;
      return 900;
    },
  });
  assert.equal(r.state, "RECLAIMABLE");
  assert.equal(asked, false);
});

// ---- the WRITE_GRACE window (lanes.py:296-300) ----
test("a present lock with no readable pid is presumed live inside the grace window", () => {
  const r = L.classify({
    payload: { lane: "ds", ts: 1990 },
    now: 2000,
    pidAlive: aliveOnly,
    procStarted: noStart,
  });
  assert.equal(r.state, "RUNNING");
  assert.equal(r.pid, 0);
});

test("a present lock with no readable pid past the grace window is RECLAIMABLE", () => {
  const r = L.classify({
    payload: { lane: "ds", ts: 1000 },
    now: 2000,
    pidAlive: aliveOnly,
    procStarted: noStart,
  });
  assert.equal(r.state, "RECLAIMABLE");
});

test("a present lock with no pid and no age stays RUNNING, as lanes.py does", () => {
  const r = L.classify({
    payload: { lane: "ds" },
    now: 2000,
    pidAlive: aliveOnly,
    procStarted: noStart,
  });
  assert.equal(r.state, "RUNNING");
});

test("lockExists=false forces FREE even when a payload is supplied", () => {
  const r = L.classify({
    payload: payload(),
    now: 2000,
    lockExists: false,
    pidAlive: aliveOnly,
    procStarted: noStart,
  });
  assert.equal(r.state, "FREE");
});

test("lockExists=true with a null payload uses the grace rule, not FREE", () => {
  // An unparseable-but-present lock: lanes.py presumes it live inside the
  // grace window and cannot date it, so it stays RUNNING.
  const r = L.classify({
    payload: null,
    now: 2000,
    lockExists: true,
    pidAlive: aliveOnly,
    procStarted: noStart,
  });
  assert.equal(r.state, "RUNNING");
});

// ---- totality ----
test("classify is total for null, empty and junk arguments", () => {
  const ok = new Set(["FREE", "RUNNING", "RECLAIMABLE"]);
  for (const arg of [undefined, null, {}, { payload: undefined },
    { payload: 42 }, { payload: [] }, { payload: "x" },
    { payload: { pid: NaN }, now: NaN }]) {
    const r = L.classify(arg);
    assert.ok(ok.has(r.state), `arg=${JSON.stringify(arg)} -> ${r.state}`);
    assert.equal(typeof r.pid, "number");
    assert.equal(typeof r.reason, "string");
  }
});

test("classify tolerates missing probe functions and stays conservative", () => {
  const r = L.classify({ payload: payload(), now: 2000 });
  assert.equal(r.state, "RUNNING");
});

test("classify tolerates a pidAlive that throws", () => {
  const r = L.classify({
    payload: payload(),
    now: 2000,
    pidAlive: () => {
      throw new Error("access denied");
    },
    procStarted: noStart,
  });
  // Unqueryable is treated as ALIVE - ops/loop/slots.py:55-57.
  assert.equal(r.state, "RUNNING");
});

test("classify tolerates a procStarted that throws", () => {
  const r = L.classify({
    payload: payload({ pid_started: 900 }),
    now: 2000,
    pidAlive: aliveOnly,
    procStarted: () => {
      throw new Error("no such process");
    },
  });
  assert.equal(r.state, "RUNNING");
});

test("classify never mutates the payload it is handed", () => {
  const p = payload({ pid: DEAD });
  const before = JSON.stringify(p);
  L.classify({ payload: p, now: 2000, pidAlive: aliveOnly, procStarted: noStart });
  assert.equal(JSON.stringify(p), before);
});

test("the module exposes no writer, unlinker or reaper FUNCTION", () => {
  // WRITE_GRACE_S is a constant lifted from lanes.py, not a writer - so this
  // predicate is anchored on callable exports only.
  for (const [name, value] of Object.entries(L)) {
    if (typeof value !== "function") continue;
    assert.ok(
      !/write|unlink|reap|acquire|release|delete|remove/i.test(name),
      `read-only observer must not export ${name}`
    );
  }
});
