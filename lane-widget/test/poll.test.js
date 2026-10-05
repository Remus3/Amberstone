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
    // Deterministic by default: without it a fast tick falls back to a NATIVE
    // signal-0 probe of pid 4242 on this machine, and a live lane adds a
    // progress-file read, so the read counts below would depend on the host.
    pidAlive() {
      return false;
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

test("the fast tick reads exactly 4 named lock files per repo and lists nothing", async () => {
  const io = fakeIo();
  const deps = fakeDeps();
  const p = mkPoller(io, deps);
  await p.tickFast();

  assert.strictEqual(io.calls.listDir.length, 0, "fast tick must not list directories");
  assert.strictEqual(io.calls.processSnapshot, 0, "fast tick must not snapshot processes");
  assert.strictEqual(io.calls.readFile.length, 8, "2 repos x (3 lane locks + 1 controller lock)");
  assert.ok(io.calls.readFile.every((f) => /lanes[\\/][012]\.lock$/.test(f) || /RUNNING\.lock$/.test(f)));
});

test("the fast tick stays bounded across repeated ticks", async () => {
  const io = fakeIo();
  const p = mkPoller(io, fakeDeps());
  await p.tickFast();
  await p.tickFast();
  await p.tickFast();
  assert.strictEqual(io.calls.readFile.length, 24);
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
  assert.strictEqual(io.calls.readFile.length, 8, "one pass of 2 repos x 4 locks");
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

// --- inbox status: one bounded read per tree, slow tick only ---------------
// Each tree publishes ops/loop/control/inbox_status.json. The poller READS it
// (never writes), once per repo per SLOW tick, and never on the fast tick, so
// the fast tick's "exactly 2 lock reads per repo" bound is untouched.

function rosterDeps(entries, captured) {
  return fakeDeps({
    repos: { resolveRepos: () => entries },
    model: {
      buildModel({ repos, now }) {
        captured.push(repos);
        return { rows: [], repoRows: [], summary: {}, updatedAt: now };
      },
    },
  });
}

const STATUS_ENTRIES = () => [
  { code: "RC", root: ROOT_A, isSelf: true, display: "RC", order: 2, attendedOnly: false, tickS: null, noLane: false },
  { code: "BBB", root: ROOT_B, isSelf: false, display: "Placeholder B", order: 1, attendedOnly: false, tickS: 600, noLane: false },
  { code: "ZZZ", root: null, isSelf: false, display: "Placeholder Z", order: 0, attendedOnly: true, tickS: null, noLane: true },
];

const isStatus = (p) => p.indexOf("inbox_status.json") !== -1;

test("the slow tick reads ONE inbox_status.json per rooted tree and none for a root-less one", async () => {
  const io = fakeIo();
  const captured = [];
  const p = mkPoller(io, rosterDeps(STATUS_ENTRIES(), captured));
  await p.tickSlow();
  const reads = io.calls.readFile.filter(isStatus);
  assert.strictEqual(reads.length, 2, reads.join(","));
  assert.ok(reads.every((f) => /ops[\\/]loop[\\/]control[\\/]inbox_status\.json$/.test(f)));
  assert.ok(reads.some((f) => f.indexOf(ROOT_A) === 0));
  assert.ok(reads.some((f) => f.indexOf(ROOT_B) === 0));
});

test("the fast tick never reads a status file and never touches a root-less tree", async () => {
  const io = fakeIo();
  const p = mkPoller(io, rosterDeps(STATUS_ENTRIES(), []));
  await p.tickFast();
  assert.strictEqual(io.calls.readFile.filter(isStatus).length, 0);
  assert.strictEqual(io.calls.readFile.length, 8, "2 rooted repos x 4 lock files, nothing for ZZZ");
});

test("status text and roster fields reach buildModel; a missing file is null", async () => {
  const body = JSON.stringify({ schema: 1, state: "idle" });
  const io = fakeIo({
    readFile(p) {
      io.calls.readFile.push(p);
      if (isStatus(p) && p.indexOf(ROOT_B) === 0) return body;
      return null;
    },
  });
  const captured = [];
  const p = mkPoller(io, rosterDeps(STATUS_ENTRIES(), captured));
  await p.tickSlow();
  await p.tickFast();
  const last = captured[captured.length - 1];
  const by = Object.fromEntries(last.map((r) => [r.code, r]));
  assert.strictEqual(by.BBB.statusText, body);
  assert.strictEqual(by.RC.statusText, null);
  assert.strictEqual(by.ZZZ.statusText, null);
  assert.strictEqual(by.BBB.display, "Placeholder B");
  assert.strictEqual(by.BBB.order, 1);
  assert.strictEqual(by.BBB.tickS, 600);
  assert.strictEqual(by.ZZZ.attendedOnly, true);
  assert.strictEqual(by.ZZZ.noLane, true);
});

test("a status file that vanishes renders as missing, never as the last value", async () => {
  let present = true;
  const io = fakeIo({
    readFile(p) {
      io.calls.readFile.push(p);
      if (isStatus(p)) return present ? "{\"schema\":1}" : null;
      return null;
    },
  });
  const captured = [];
  const p = mkPoller(io, rosterDeps(STATUS_ENTRIES(), captured));
  await p.tickSlow();
  present = false;
  await p.tickSlow();
  const last = captured[captured.length - 1];
  assert.strictEqual(last.find((r) => r.code === "RC").statusText, null);
});

test("a throwing status read still produces a model", async () => {
  const io = fakeIo({
    readFile(p) {
      if (isStatus(p)) throw new Error("EBUSY");
      return null;
    },
  });
  const captured = [];
  const p = mkPoller(io, rosterDeps(STATUS_ENTRIES(), captured));
  const m = await p.tickSlow();
  assert.ok(m && Array.isArray(m.rows));
  assert.strictEqual(captured[captured.length - 1].find((r) => r.code === "RC").statusText, null);
});

// --- accounts: the proxy state file, slow tick only, read-only -------------

const STATE_FILE = "C:\\fake-profile\\proxy.state.json";

function accountsDeps(captured, accountsCfg) {
  return fakeDeps({
    repos: {
      resolveRepos: () => [{ code: "RC", root: ROOT_A, isSelf: true }],
      resolveAccounts: () => accountsCfg,
    },
    model: {
      buildModel(input) {
        captured.push(input);
        return { rows: [], repoRows: [], summary: {}, updatedAt: input.now };
      },
    },
  });
}

const ACCOUNTS_CFG = { stateFile: STATE_FILE, probeS: 300, roles: [{ account_uuid: "u", role: "Headless" }] };

test("the slow tick reads the proxy state file once (one stat + one read) and hands it to buildModel", async () => {
  const io = fakeIo({
    readFile(p) {
      io.calls.readFile.push(p);
      return p === STATE_FILE ? "{\"quota\":[]}" : null;
    },
    statFile(p) {
      io.calls.statFile.push(p);
      return { mtimeMs: p === STATE_FILE ? 1699999990000 : 1000 };
    },
  });
  const captured = [];
  const p = mkPoller(io, accountsDeps(captured, ACCOUNTS_CFG));
  await p.tickSlow();
  assert.strictEqual(io.calls.readFile.filter((f) => f === STATE_FILE).length, 1);
  assert.strictEqual(io.calls.statFile.filter((f) => f === STATE_FILE).length, 1);
  const last = captured[captured.length - 1];
  assert.deepEqual(last.accounts, {
    text: "{\"quota\":[]}", mtimeMs: 1699999990000, probeS: 300, roles: ACCOUNTS_CFG.roles,
  });
});

test("the fast tick never touches the proxy state file but keeps the last slow reading", async () => {
  const io = fakeIo({
    readFile(p) {
      io.calls.readFile.push(p);
      return p === STATE_FILE ? "{}" : null;
    },
  });
  const captured = [];
  const p = mkPoller(io, accountsDeps(captured, ACCOUNTS_CFG));
  await p.tickSlow();
  const before = io.calls.readFile.length;
  await p.tickFast();
  const fastReads = io.calls.readFile.slice(before);
  assert.strictEqual(fastReads.filter((f) => f === STATE_FILE).length, 0);
  assert.strictEqual(fastReads.length, 4, "fast tick bound: 4 lock reads per repo, nothing else");
  assert.strictEqual(captured[captured.length - 1].accounts.text, "{}");
});

test("no accounts config: the state file is never read and buildModel gets accounts null", async () => {
  const io = fakeIo();
  const captured = [];
  const p = mkPoller(io, accountsDeps(captured, null));
  await p.tickSlow();
  assert.strictEqual(captured[captured.length - 1].accounts, null);
  assert.ok(io.calls.readFile.every((f) => f.indexOf("proxy.state") === -1));
});

test("a vanished or throwing state file reaches the model as null text, never the old value", async () => {
  let mode = "ok";
  const io = fakeIo({
    readFile(p) {
      io.calls.readFile.push(p);
      if (p !== STATE_FILE) return null;
      if (mode === "throw") throw new Error("EBUSY");
      return mode === "ok" ? "{\"quota\":[]}" : null;
    },
    statFile(p) {
      if (p === STATE_FILE && mode !== "ok") throw new Error("ENOENT");
      return { mtimeMs: 1000 };
    },
  });
  const captured = [];
  const p = mkPoller(io, accountsDeps(captured, ACCOUNTS_CFG));
  await p.tickSlow();
  mode = "gone";
  await p.tickSlow();
  assert.strictEqual(captured[captured.length - 1].accounts.text, null);
  assert.strictEqual(captured[captured.length - 1].accounts.mtimeMs, null);
  mode = "throw";
  const m = await p.tickSlow();
  assert.ok(m && Array.isArray(m.rows));
  assert.strictEqual(captured[captured.length - 1].accounts.text, null);
});

// --- FLEET-KIT v6/v7: three lanes, per-lane checklist, governor strip -------
// v6 4b: lanes/0.lock 1.lock 2.lock per repo, NAMED reads. v7 4b-4c: for each
// LIVE lane ONE named read of ops/loop/control/progress/lane-<i>.json under
// that repo's checkout. v6 4b: ONE governor strip from <slot root>/0..2.lock
// plus its sibling queue directory. Every read below is checked against an
// explicit allow-list - reads stay within the named files.

const PD = "C:\\fake-pd";
const LIVE_A = 100;
const LIVE_B = 101;
const DEAD_A = 200;

function progressBody(n) {
  const rows = [];
  for (let i = 1; i <= n; i += 1) rows.push({ id: "C" + i, task: "Task " + i, state: null, eta_s: 60 });
  return JSON.stringify({
    task: "lane-0", pct: 10, step: "s", eta_s: 600, status: "running",
    updated: new Date((FIXED_NOW_S - 30) * 1000).toISOString(), checklist: rows,
  });
}

function laneIo(files, extra) {
  const io = {
    calls: { readFile: [], listDir: [], statFile: [] },
    readFile(p) {
      io.calls.readFile.push(p);
      for (const [suffix, body] of Object.entries(files)) {
        if (p.replace(/\//g, "\\").endsWith(suffix)) return body;
      }
      return null;
    },
    statFile(p) {
      io.calls.statFile.push(p);
      return { mtimeMs: (FIXED_NOW_S - 30) * 1000 };
    },
    listDir(dir) {
      io.calls.listDir.push(dir);
      return [];
    },
    processSnapshot() {
      return [];
    },
    pidAlive(pid) {
      return pid === LIVE_A || pid === LIVE_B;
    },
    procStarted() {
      return null;
    },
  };
  return Object.assign(io, extra || {});
}

function capturingRealDeps(captured, roster) {
  return Object.assign({}, realDeps, {
    repos: { resolveRepos: () => roster, resolveAccounts: () => null },
    model: {
      buildModel(input) {
        captured.push(input);
        return realDeps.model.buildModel(input);
      },
    },
  });
}

const ONE_REPO = [{ code: "RC", root: ROOT_A, isSelf: true, display: "RC", order: 0 }];
const lockBody = (pid, lane) => JSON.stringify({ pid, lane, run_id: "r-" + lane, ts: FIXED_NOW_S - 720 });

test("v7: a LIVE lane gets exactly ONE named progress read; free and dead lanes get none", async () => {
  const io = laneIo({
    "lanes\\0.lock": lockBody(LIVE_A, "queue"),
    "lanes\\1.lock": lockBody(DEAD_A, "repo"),
    "progress\\lane-0.json": progressBody(2),
    "progress\\lane-1.json": progressBody(2),
  });
  const captured = [];
  const p = createPoller({ rcRoot: ROOT_A, env: {}, io, now: () => FIXED_NOW_S, deps: capturingRealDeps(captured, ONE_REPO) });
  await p.tickFast();
  const allowed = [
    "ops\\loop\\control\\lanes\\0.lock",
    "ops\\loop\\control\\lanes\\1.lock",
    "ops\\loop\\control\\lanes\\2.lock",
    "ops\\loop\\control\\RUNNING.lock",
    "ops\\loop\\control\\progress\\lane-0.json",
  ].map((rel) => ROOT_A + "\\" + rel);
  const reads = io.calls.readFile.map((f) => f.replace(/\//g, "\\"));
  assert.deepStrictEqual(reads.slice().sort(), allowed.slice().sort(), reads.join(","));
  assert.strictEqual(io.calls.listDir.length, 0, "no directory walk on the fast tick");
  const lanes = captured[captured.length - 1].repos[0].lanes;
  assert.strictEqual(lanes.length, 3);
  assert.strictEqual(lanes[0].state, "RUNNING");
  assert.strictEqual(typeof lanes[0].progressText, "string");
  assert.strictEqual(lanes[1].state, "RECLAIMABLE");
  assert.strictEqual(lanes[1].progressText, null, "a dead lane's progress file is never read");
  assert.strictEqual(lanes[2].state, "FREE");
  assert.strictEqual(lanes[2].progressText, null);
});

test("v7: a live lane's checklist reaches the ALL row in order, capped at 3 plus +N more", async () => {
  const io = laneIo({
    "lanes\\0.lock": lockBody(LIVE_A, "queue"),
    "progress\\lane-0.json": progressBody(5),
  });
  let model = null;
  const p = createPoller({ rcRoot: ROOT_A, env: {}, io, now: () => FIXED_NOW_S, deps: capturingRealDeps([], ONE_REPO), onModel(m) { model = m; } });
  await p.tickFast();
  const lane0 = model.repoRows[0].lanes[0];
  assert.strictEqual(lane0.checklist.status, "live");
  assert.deepStrictEqual(lane0.checklist.items.map((i) => i.id), ["C1", "C2", "C3"]);
  assert.strictEqual(lane0.checklist.more, 2);
});

test("v7: a missing or stale progress file reaches the row as its fallback, never a list", async () => {
  const stale = JSON.stringify({
    eta_s: 60, updated: new Date((FIXED_NOW_S - 121) * 1000).toISOString(),
    checklist: [{ id: "C1", task: "Old", state: null, eta_s: null }],
  });
  const io = laneIo({
    "lanes\\0.lock": lockBody(LIVE_A, "queue"),
    "lanes\\1.lock": lockBody(LIVE_B, "ds"),
    "progress\\lane-1.json": stale,
  });
  let model = null;
  const p = createPoller({ rcRoot: ROOT_A, env: {}, io, now: () => FIXED_NOW_S, deps: capturingRealDeps([], ONE_REPO), onModel(m) { model = m; } });
  await p.tickFast();
  const lanes = model.repoRows[0].lanes;
  assert.strictEqual(lanes[0].checklist.status, "none");
  assert.strictEqual(lanes[1].checklist.status, "stale");
  assert.deepStrictEqual(lanes[1].checklist.items, []);
});

test("v7: a progress file that vanishes is not carried forward from the last tick", async () => {
  const files = { "lanes\\0.lock": lockBody(LIVE_A, "queue"), "progress\\lane-0.json": progressBody(2) };
  const io = laneIo(files);
  let model = null;
  const p = createPoller({ rcRoot: ROOT_A, env: {}, io, now: () => FIXED_NOW_S, deps: capturingRealDeps([], ONE_REPO), onModel(m) { model = m; } });
  await p.tickFast();
  assert.strictEqual(model.repoRows[0].lanes[0].checklist.status, "live");
  delete files["progress\\lane-0.json"];
  await p.tickFast();
  assert.strictEqual(model.repoRows[0].lanes[0].checklist.status, "none");
});

test("v6: the slow tick reads exactly the three governor slots and lists the queue once", async () => {
  const slotsDir = PD + "\\lw-loop\\slots\\";
  const queueDir = PD + "\\lw-loop\\queue";
  const io = laneIo({
    "slots\\0.lock": JSON.stringify({ pid: LIVE_A, repo: ROOT_A, run_id: "x", cycle: 1, ts: FIXED_NOW_S - 60 }),
    "slots\\2.lock": JSON.stringify({ pid: LIVE_B, repo: "CS", run_id: "y", cycle: 1, ts: FIXED_NOW_S - 60 }),
    "queue\\1.ticket": JSON.stringify({ pid: LIVE_A, repo: "EW", ts: FIXED_NOW_S - 10 }),
  }, {
    listDir(dir) {
      io.calls.listDir.push(dir);
      if (dir.replace(/\//g, "\\") === queueDir) {
        return [
          { name: "1.ticket", mtimeMs: (FIXED_NOW_S - 5) * 1000 },
          { name: "notes.txt", mtimeMs: (FIXED_NOW_S - 5) * 1000 },
        ];
      }
      return [];
    },
  });
  const captured = [];
  const p = createPoller({ rcRoot: ROOT_A, env: { ProgramData: PD }, io, now: () => FIXED_NOW_S, deps: capturingRealDeps(captured, ONE_REPO) });
  await p.tickSlow();
  const pdReads = io.calls.readFile.map((f) => f.replace(/\//g, "\\")).filter((f) => f.indexOf(PD) === 0);
  assert.deepStrictEqual(pdReads.sort(), [slotsDir + "0.lock", slotsDir + "1.lock", slotsDir + "2.lock", queueDir + "\\1.ticket"].sort());
  const pdLists = io.calls.listDir.map((d) => d.replace(/\//g, "\\")).filter((d) => d.indexOf(PD) === 0);
  assert.deepStrictEqual(pdLists, [queueDir], "ONE non-recursive listing of the queue, never the slot root");
  const g = captured[captured.length - 1].governor;
  assert.deepStrictEqual(g, { width: 3, held: 2, stale: 0, repos: ["RC", "CS"], queue: 1 });
});

test("v6: the governor slot payload's repo PATH never reaches the model", async () => {
  const io = laneIo({
    "slots\\0.lock": JSON.stringify({ pid: LIVE_A, repo: "C:\\Some Sibling Checkout", run_id: "x", ts: FIXED_NOW_S - 60 }),
  });
  let model = null;
  const p = createPoller({ rcRoot: ROOT_A, env: { ProgramData: PD }, io, now: () => FIXED_NOW_S, deps: capturingRealDeps([], ONE_REPO), onModel(m) { model = m; } });
  await p.tickSlow();
  assert.ok(!JSON.stringify(model).includes("Sibling"), JSON.stringify(model.governor));
  assert.strictEqual(model.governor.text, "Governor 1/3 - ? - queue 0");
});

test("v6: no ProgramData in the environment means no governor reads and no strip", async () => {
  const io = laneIo({});
  const captured = [];
  const p = createPoller({ rcRoot: ROOT_A, env: {}, io, now: () => FIXED_NOW_S, deps: capturingRealDeps(captured, ONE_REPO) });
  await p.tickSlow();
  assert.ok(io.calls.readFile.every((f) => f.indexOf("lw-loop") === -1));
  assert.strictEqual(captured[captured.length - 1].governor, null);
});
