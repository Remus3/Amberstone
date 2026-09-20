// lane-widget/test/poll.test.js
//
// Every IO the poller performs is injected, so this suite never touches a real
// disk and never spawns a process. Fixture roots are invented (C:\fake-a /
// C:\fake-b) - never a real checkout path.
//
// The three properties this file exists to prove:
//   1. the FAST tick lists no directories (no timer-driven recursion, ever)
//   2. a SLOW tick already in flight is not re-entered
//   3. a thrown IO error still produces a model

"use strict";

const test = require("node:test");
const assert = require("node:assert");

const { createPoller, createDefaultIo } = require("../src/poll.js");

const ROOT_A = "C:\\fake-a";
const ROOT_B = "C:\\fake-b";

// --- fakes standing in for the slice A pure modules (spec section 3) ---------

function fakeDeps(overrides) {
  const calls = { resolveRepos: 0, buildModel: 0, newestPerLane: 0, countByRoot: 0 };
  const deps = {
    calls,
    repos: {
      resolveRepos() {
        calls.resolveRepos += 1;
        return [
          { code: "RC", root: ROOT_A, isSelf: true },
          { code: "REPO-2", root: ROOT_B, isSelf: false },
        ];
      },
    },
    locks: {
      LANE_LOCK_REL: ["ops", "loop", "control", "lanes", "0.lock"],
      CTRL_LOCK_REL: ["ops", "loop", "control", "RUNNING.lock"],
      parseLock(text) {
        if (typeof text !== "string" || !text.trim()) {
          return null;
        }
        try {
          const p = JSON.parse(text);
          return p && typeof p === "object" && !Array.isArray(p) ? p : null;
        } catch (_e) {
          return null;
        }
      },
      effectivePid(p) {
        if (!p) {
          return 0;
        }
        return p.claimed_by_pid || p.pid || 0;
      },
      classify({ payload, pidAlive }) {
        if (!payload || !payload.pid) {
          return { state: "FREE", pid: 0, reason: "no payload" };
        }
        const alive = typeof pidAlive === "function" ? pidAlive(payload.pid) : false;
        return {
          state: alive ? "RUNNING" : "RECLAIMABLE",
          pid: payload.pid,
          reason: alive ? "alive" : "dead pid",
        };
      },
      ageS() {
        return 1;
      },
    },
    proctree: {
      countByRoot(snapshot, rootPids) {
        calls.countByRoot += 1;
        const m = new Map();
        for (const pid of rootPids || []) {
          m.set(pid, Array.isArray(snapshot) ? snapshot.length : 0);
        }
        return m;
      },
    },
    heartbeat: {
      newestPerLane(entries) {
        calls.newestPerLane += 1;
        return (entries || []).map((e) => ({
          lane: "ds",
          runId: "r1",
          name: e.name,
          mtimeMs: e.mtimeMs,
          ageS: 5,
          stalled: false,
        }));
      },
    },
    model: {
      buildModel({ repos, now }) {
        calls.buildModel += 1;
        return {
          rows: (repos || []).map((r) => ({
            key: r.code + ":lane",
            repoCode: r.code,
            kind: "lane",
            state: r.lane ? r.lane.state : "FREE",
            children: r.children || 0,
            logCount: (r.logs || []).length,
          })),
          summary: { repos: (repos || []).length },
          updatedAt: now,
        };
      },
    },
  };
  return Object.assign(deps, overrides || {});
}

function fakeIo(overrides) {
  const calls = { readFile: [], listDir: [], statFile: [], processSnapshot: 0 };
  const io = {
    calls,
    readFile(p) {
      calls.readFile.push(p);
      if (p.indexOf("0.lock") !== -1) {
        return JSON.stringify({ pid: 4242, lane: "ds", run_id: "r1", ts: 1, worktree: "C:\\fake-a\\wt\\ds" });
      }
      return null;
    },
    statFile(p) {
      calls.statFile.push(p);
      return { mtimeMs: 1000 };
    },
    listDir(dir) {
      calls.listDir.push(dir);
      return [{ name: "lane_ds_r1.log", mtimeMs: 1000 }];
    },
    processSnapshot() {
      calls.processSnapshot += 1;
      return [{ pid: 4242, ppid: 1, name: "python.exe", startMs: 5000 }];
    },
  };
  return Object.assign(io, overrides || {});
}

function mkPoller(io, deps, extra) {
  return createPoller(
    Object.assign(
      {
        rcRoot: ROOT_A,
        env: {},
        io,
        now: () => 1700000000, // epoch SECONDS - see the units note below.
        onModel() {},
        deps,
      },
      extra || {}
    )
  );
}

// --- property 1: the fast tick never lists a directory -----------------------

test("the fast tick reads exactly 2 lock files per repo and lists nothing", async () => {
  const io = fakeIo();
  const deps = fakeDeps();
  const p = mkPoller(io, deps);
  await p.tickFast();

  assert.strictEqual(io.calls.listDir.length, 0, "fast tick must not list directories");
  assert.strictEqual(io.calls.processSnapshot, 0, "fast tick must not snapshot processes");
  assert.strictEqual(io.calls.readFile.length, 4, "2 repos x 2 lock files");
  assert.ok(io.calls.readFile.every((f) => f.indexOf("0.lock") !== -1 || f.indexOf("RUNNING.lock") !== -1));
});

test("the fast tick stays bounded across repeated ticks", async () => {
  const io = fakeIo();
  const p = mkPoller(io, fakeDeps());
  await p.tickFast();
  await p.tickFast();
  await p.tickFast();
  assert.strictEqual(io.calls.readFile.length, 12);
  assert.strictEqual(io.calls.listDir.length, 0);
});

test("the roster is resolved once, not once per tick", async () => {
  const deps = fakeDeps();
  const p = mkPoller(fakeIo(), deps);
  await p.tickFast();
  await p.tickFast();
  assert.strictEqual(deps.calls.resolveRepos, 1);
});

// --- property 2: no self-overlap --------------------------------------------

test("a slow tick already in flight is not re-entered", async () => {
  let release = null;
  const gate = new Promise((resolve) => {
    release = resolve;
  });
  const io = fakeIo({
    processSnapshot() {
      io.calls.processSnapshot += 1;
      return gate.then(() => [{ pid: 4242, ppid: 1, name: "x.exe", startMs: 1 }]);
    },
  });
  const p = mkPoller(io, fakeDeps());

  const first = p.tickSlow();
  const second = p.tickSlow(); // must be a no-op while the first is in flight
  release();
  await Promise.all([first, second]);

  assert.strictEqual(io.calls.processSnapshot, 1, "one snapshot, not two");
  assert.strictEqual(io.calls.listDir.length, 2, "one listing per repo, once");
});

test("a fast tick already in flight is not re-entered", async () => {
  let release = null;
  const gate = new Promise((resolve) => {
    release = resolve;
  });
  let first = true;
  const io = fakeIo({
    readFile(p2) {
      io.calls.readFile.push(p2);
      if (first) {
        first = false;
        return gate.then(() => null);
      }
      return null;
    },
  });
  const p = mkPoller(io, fakeDeps());
  const a = p.tickFast();
  const b = p.tickFast();
  release();
  await Promise.all([a, b]);
  assert.strictEqual(io.calls.readFile.length, 4, "one pass of 2 repos x 2 locks");
});

test("the slow tick takes ONE machine-wide snapshot reused by every repo", async () => {
  const io = fakeIo();
  const p = mkPoller(io, fakeDeps());
  await p.tickSlow();
  assert.strictEqual(io.calls.processSnapshot, 1);
  assert.strictEqual(io.calls.listDir.length, 2, "one non-recursive listing per repo");
});

// --- property 3: fail-soft ---------------------------------------------------

test("a thrown readFile still produces a model", async () => {
  const io = fakeIo({
    readFile() {
      throw new Error("EACCES boom");
    },
  });
  let seen = null;
  const p = mkPoller(io, fakeDeps(), { onModel: (m) => { seen = m; } });
  await p.tickFast();
  assert.ok(seen, "onModel fired despite the IO throw");
  assert.ok(Array.isArray(seen.rows));
  assert.ok(p.lastModel());
});

test("a thrown listDir and a thrown processSnapshot still produce a model", async () => {
  const io = fakeIo({
    listDir() {
      throw new Error("ENOENT reports");
    },
    processSnapshot() {
      throw new Error("powershell missing");
    },
  });
  let seen = null;
  const p = mkPoller(io, fakeDeps(), { onModel: (m) => { seen = m; } });
  await p.tickSlow();
  assert.ok(seen, "onModel fired despite two IO throws");
  assert.ok(seen.rows.every((r) => r.children === 0), "children fail soft to 0");
});

test("a participant with NO ops/loop/reports directory still renders its rows", async () => {
  // The common shape, not an edge case: a participant only grows that directory
  // once its loop has run at least once, so a freshly joined repo has none and
  // several established ones never will. listDir is fail-soft on a missing
  // directory (src/poll.js:121-131 catches and returns []), and this pins what
  // the poller does with that empty answer: the repo keeps its rows with no
  // heartbeat, and the OTHER repo's logs stay where they belong.
  //
  // The failure this excludes is a bleed, not a throw. A poller that carried one
  // repo's listing forward would decorate the reports-less repo with a sibling's
  // heartbeat, and the row would look alive on evidence from another machine.
  const io = fakeIo({
    listDir(dir) {
      this.calls.listDir.push(dir);
      if (dir.indexOf(ROOT_B) === 0) {
        return []; // absent directory, exactly as the real listDir reports one
      }
      return [{ name: "lane_ds_r1.log", mtimeMs: 1000 }];
    },
  });
  let seen = null;
  const deps = fakeDeps();
  const p = mkPoller(io, deps, { onModel: (m) => { seen = m; } });
  await p.tickSlow();

  assert.ok(seen, "a model is still produced");
  assert.strictEqual(seen.rows.length, 2, "both participants still have a row");
  const byCode = Object.fromEntries(seen.rows.map((r) => [r.repoCode, r]));
  assert.ok(byCode["REPO-2"], "the reports-less participant is not dropped");
  assert.strictEqual(byCode["REPO-2"].logCount, 0, "it carries no heartbeat rows");
  assert.strictEqual(byCode.RC.logCount, 1, "the other participant keeps its own");
  assert.ok(
    io.calls.listDir.some((d) => d.indexOf(ROOT_B) === 0),
    "the directory is still ATTEMPTED - absence is discovered, not assumed"
  );
});

test("a reports-less participant stays reports-less across repeated slow ticks", async () => {
  // The bleed above could also arrive as staleness: a cache that keeps the last
  // non-empty listing per repo would populate on tick one and never clear.
  const io = fakeIo({
    listDir(dir) {
      this.calls.listDir.push(dir);
      return dir.indexOf(ROOT_B) === 0 ? [] : [{ name: "lane_ds_r1.log", mtimeMs: 1000 }];
    },
  });
  const seen = [];
  const p = mkPoller(io, fakeDeps(), { onModel: (m) => { seen.push(m); } });
  await p.tickSlow();
  await p.tickSlow();
  await p.tickSlow();
  assert.strictEqual(seen.length, 3);
  for (let i = 0; i < seen.length; i += 1) {
    const byCode = Object.fromEntries(seen[i].rows.map((r) => [r.repoCode, r]));
    assert.strictEqual(byCode["REPO-2"].logCount, 0, `tick ${i + 1} stays empty`);
  }
});

test("a rejected processSnapshot promise is fail-soft", async () => {
  const io = fakeIo({
    processSnapshot() {
      return Promise.reject(new Error("nope"));
    },
  });
  let seen = null;
  const p = mkPoller(io, fakeDeps(), { onModel: (m) => { seen = m; } });
  await p.tickSlow();
  assert.ok(seen);
});

test("a throwing onModel does not break the next tick", async () => {
  const io = fakeIo();
  let count = 0;
  const p = mkPoller(io, fakeDeps(), {
    onModel() {
      count += 1;
      throw new Error("renderer gone");
    },
  });
  await p.tickFast();
  await p.tickFast();
  assert.strictEqual(count, 2);
});

test("a throwing dep still produces a model and never escapes the tick", async () => {
  const deps = fakeDeps();
  deps.model.buildModel = () => {
    throw new Error("model blew up");
  };
  const p = mkPoller(fakeIo(), deps);
  await p.tickFast();
  assert.ok(p.lastModel(), "an empty but valid model is retained");
  assert.deepStrictEqual(p.lastModel().rows, []);
});

// --- snapshot wiring ---------------------------------------------------------

test("a dead pid renders RECLAIMABLE, never RUNNING", async () => {
  const io = fakeIo({
    processSnapshot() {
      io.calls.processSnapshot += 1;
      return []; // nothing alive on the machine
    },
  });
  let seen = null;
  const p = mkPoller(io, fakeDeps(), { onModel: (m) => { seen = m; } });
  await p.tickSlow();
  await p.tickFast();
  assert.ok(seen.rows.length > 0);
  assert.ok(seen.rows.every((r) => r.state !== "RUNNING"), "dead pid is not RUNNING");
});

test("stop() is safe before start() and start() is idempotent", () => {
  const p = mkPoller(fakeIo(), fakeDeps());
  p.stop();
  p.start();
  p.start();
  p.stop();
  p.stop();
});

// --- the default IO builder: windowsHide is MANDATORY ------------------------

test("createDefaultIo spawns powershell with windowsHide true", async () => {
  const seen = [];
  const io = createDefaultIo({
    platform: "win32",
    execFile(file, args, opts, cb) {
      seen.push({ file, args, opts });
      cb(null, JSON.stringify([]), "");
    },
  });
  await io.processSnapshot();
  assert.strictEqual(seen.length, 1);
  assert.strictEqual(seen[0].file, "powershell");
  assert.strictEqual(seen[0].opts.windowsHide, true, "windowsHide is mandatory");
  assert.ok(seen[0].args.join(" ").indexOf("Win32_Process") !== -1);
});

test("createDefaultIo parses a snapshot into pid/ppid/name/startMs", async () => {
  const io = createDefaultIo({
    platform: "win32",
    execFile(_f, _a, _o, cb) {
      cb(
        null,
        JSON.stringify([
          { ProcessId: 10, ParentProcessId: 4, Name: "a.exe", CreationDate: "/Date(1700000000000)/" },
          { ProcessId: 11, ParentProcessId: 10, Name: "b.exe", CreationDate: "2026-09-19T10:00:00Z" },
        ]),
        ""
      );
    },
  });
  const snap = await io.processSnapshot();
  assert.strictEqual(snap.length, 2);
  assert.strictEqual(snap[0].pid, 10);
  assert.strictEqual(snap[0].ppid, 4);
  assert.strictEqual(snap[0].name, "a.exe");
  assert.strictEqual(snap[0].startMs, 1700000000000);
  assert.ok(snap[1].startMs > 0);
});

test("createDefaultIo snapshot failure is fail-soft, returning an empty array", async () => {
  const io = createDefaultIo({
    platform: "win32",
    execFile(_f, _a, _o, cb) {
      cb(new Error("not found"), "", "boom");
    },
  });
  assert.deepStrictEqual(await io.processSnapshot(), []);
});

test("createDefaultIo returns an empty snapshot off win32 rather than throwing", async () => {
  let spawned = 0;
  const io = createDefaultIo({
    platform: "linux",
    execFile() {
      spawned += 1;
    },
  });
  assert.deepStrictEqual(await io.processSnapshot(), []);
  assert.strictEqual(spawned, 0);
});

test("createDefaultIo readFile and listDir are fail-soft on a missing path", () => {
  const io = createDefaultIo({ platform: "win32", execFile() {} });
  assert.strictEqual(io.readFile("C:\\fake-a\\definitely\\missing.lock"), null);
  assert.deepStrictEqual(io.listDir("C:\\fake-a\\definitely\\missing"), []);
  assert.strictEqual(io.statFile("C:\\fake-a\\definitely\\missing.log"), null);
});

// --- integration against the REAL pure modules -------------------------------
//
// Everything above stubs slice A behind fakeDeps(), which is the right shape for
// proving the poller's OWN properties but cannot catch a seam defect between the
// two halves. These two tests wire the real modules in on purpose.
//
// UNITS ARE THE SEAM. locks.js and heartbeat.js document `now` as epoch SECONDS
// because the lock `ts` is written by python time.time() (ops/loop/lanes.py:388).
// A poller that feeds Date.now() milliseconds computes every age about 1e3 too
// large, which silently trips the WRITE_GRACE_S = 30.0 branch in locks.js.

const realDeps = {
  repos: require("../src/repos.js"),
  locks: require("../src/locks.js"),
  proctree: require("../src/proctree.js"),
  heartbeat: require("../src/heartbeat.js"),
  model: require("../src/model.js"),
};

const FIXED_NOW_S = 1700000000; // epoch SECONDS, not milliseconds.

function realIo(laneText) {
  return {
    readFile(p) {
      return p.indexOf("0.lock") !== -1 ? laneText : null;
    },
    statFile() {
      return null;
    },
    listDir() {
      return [];
    },
    processSnapshot() {
      return [];
    },
  };
}

test("ages are computed in SECONDS against the lock ts, not milliseconds", async () => {
  // `now` is deliberately NOT injected here - the defect this test exists to
  // catch is the DEFAULT clock's unit, and injecting a clock hides it.
  const laneText = JSON.stringify({
    pid: 4242,
    lane: "ds",
    run_id: "r1",
    ts: Date.now() / 1000 - 5,
    worktree: "C:\\fake-a\\wt\\ds",
  });
  let model = null;
  const p = createPoller({
    rcRoot: ROOT_A,
    env: {},
    io: realIo(laneText),
    deps: realDeps,
    onModel(m) {
      model = m;
    },
    pidAlive: () => true,
  });
  await p.tickFast();

  const lane = model.rows.find((r) => r.kind === "lane");
  assert.ok(lane, "a lane row must be present");
  assert.ok(
    lane.ageS >= 4 && lane.ageS <= 6,
    "a lock written 5 seconds ago must read about 5s, got " + lane.ageS
  );
});

test("a present but UNPARSEABLE lock is not reported FREE", async () => {
  // ops/loop/lanes.py:280 keys FREE on lock.exists(), never on the payload
  // parsing - a half-written lock is a lock. The poller knows the difference
  // (readFile returned a string rather than null) and must say so via
  // lockExists, or a lane mid-claim renders as idle.
  let model = null;
  const p = createPoller({
    rcRoot: ROOT_A,
    env: {},
    io: realIo("{ not json"),
    now: () => FIXED_NOW_S,
    deps: realDeps,
    onModel(m) {
      model = m;
    },
    pidAlive: () => true,
  });
  await p.tickFast();

  const lane = model.rows.find((r) => r.kind === "lane");
  assert.ok(lane, "a lane row must be present");
  assert.notStrictEqual(
    lane.state,
    "FREE",
    "a lock file that exists but does not parse must not read as FREE"
  );
});
