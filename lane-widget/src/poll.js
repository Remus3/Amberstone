// lane-widget/src/poll.js
//
// The widget's only IO. Every call is INJECTED (io.readFile / io.statFile /
// io.listDir / io.processSnapshot) so the unit suite drives it with fakes and
// touches no real disk and spawns no process.
//
// Two cadences, both deliberately BOUNDED:
//
//   FAST (2000 ms)  exactly 2 file reads per repo - the lane lock and the
//                   controller lock - and nothing else. No listing, no stat,
//                   no snapshot.
//   SLOW (10000 ms) ONE non-recursive listing of <root>/ops/loop/reports per
//                   repo, plus ONE machine-wide process snapshot that every
//                   repo reuses.
//
// There is NO recursive walk on any timer, ever. An idle recursive walker in
// this repo was measured at tens of thousands of metadata operations per second
// and that is a standing prohibition, not a preference.
//
// The poller is a READ-ONLY observer: it opens lock files for reading and never
// writes, locks, unlinks or reaps anything in any repo.
//
// Fail-soft is absolute. Every IO call is wrapped; a failure logs and leaves the
// previous value in place (children counts fall back to 0) so the widget keeps
// rendering. Nothing here may throw into the event loop, and a tick never
// overlaps itself.

"use strict";

const fs = require("fs");
const path = require("path");
const cp = require("child_process");

const DEFAULT_FAST_MS = 2000;
const DEFAULT_SLOW_MS = 10000;
const DEFAULT_STALL_AFTER_S = 600;
const REPORTS_REL = ["ops", "loop", "reports"];

// PowerShell one-liner for the machine-wide snapshot. ONE spawn per slow tick,
// reused by every repo.
const SNAPSHOT_ARGS = [
  "-NoProfile",
  "-NonInteractive",
  "-ExecutionPolicy",
  "Bypass",
  "-Command",
  "Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name,CreationDate | ConvertTo-Json -Compress",
];

function posInt(v, fallback) {
  return typeof v === "number" && isFinite(v) && v > 0 ? Math.floor(v) : fallback;
}

// Parse whatever CreationDate shape PowerShell emits into epoch ms.
//   "/Date(1700000000000)/"  (ConvertTo-Json on a DateTime)
//   "2026-09-19T10:00:00Z"   (already a string)
function creationToMs(raw) {
  if (typeof raw === "number" && isFinite(raw)) {
    return raw;
  }
  if (typeof raw !== "string" || !raw) {
    return 0;
  }
  const m = /\/Date\((-?\d+)/.exec(raw);
  if (m) {
    const n = Number(m[1]);
    return isFinite(n) ? n : 0;
  }
  const parsed = Date.parse(raw);
  return isFinite(parsed) ? parsed : 0;
}

function normalizeSnapshotRows(parsed) {
  const rows = Array.isArray(parsed) ? parsed : parsed && typeof parsed === "object" ? [parsed] : [];
  const out = [];
  for (const r of rows) {
    if (!r || typeof r !== "object") {
      continue;
    }
    const pid = Number(r.ProcessId);
    if (!isFinite(pid) || pid <= 0) {
      continue;
    }
    const ppid = Number(r.ParentProcessId);
    out.push({
      pid: pid,
      ppid: isFinite(ppid) && ppid > 0 ? ppid : 0,
      name: typeof r.Name === "string" ? r.Name : "",
      startMs: creationToMs(r.CreationDate),
    });
  }
  return out;
}

// The production io. execFile + platform are injectable so the suite can prove
// the windowsHide flag without spawning anything.
function createDefaultIo(opts) {
  const o = opts && typeof opts === "object" ? opts : {};
  const execFile = typeof o.execFile === "function" ? o.execFile : cp.execFile;
  const platform = typeof o.platform === "string" ? o.platform : process.platform;

  function readFile(absPath) {
    try {
      return fs.readFileSync(absPath, "utf8");
    } catch (_e) {
      return null; // missing / locked / unreadable - all the same to us.
    }
  }

  function statFile(absPath) {
    try {
      const st = fs.statSync(absPath);
      return { mtimeMs: st.mtimeMs };
    } catch (_e) {
      return null;
    }
  }

  // ONE non-recursive listing. withFileTypes keeps directories out without a
  // stat, and the per-file stat that follows is bounded by this one directory.
  function listDir(dir) {
    let names = [];
    try {
      names = fs.readdirSync(dir, { withFileTypes: true });
    } catch (_e) {
      return [];
    }
    const out = [];
    for (const ent of names) {
      try {
        if (!ent.isFile()) {
          continue;
        }
        const st = fs.statSync(path.join(dir, ent.name));
        out.push({ name: ent.name, mtimeMs: st.mtimeMs });
      } catch (_e) {
        // a file that vanished between readdir and stat is simply skipped.
      }
    }
    return out;
  }

  // ONE execFile per call. windowsHide is MANDATORY: a console-subsystem child
  // of a windowless GUI parent flashes a console window without it, which is a
  // standing operator complaint in this repo.
  function processSnapshot() {
    if (platform !== "win32") {
      return Promise.resolve([]);
    }
    return new Promise((resolve) => {
      let settled = false;
      const done = (rows) => {
        if (!settled) {
          settled = true;
          resolve(rows);
        }
      };
      try {
        execFile(
          "powershell",
          SNAPSHOT_ARGS,
          { windowsHide: true, maxBuffer: 16 * 1024 * 1024, timeout: 15000 },
          (err, stdout) => {
            if (err) {
              done([]); // fail-soft: children counts go to 0.
              return;
            }
            try {
              done(normalizeSnapshotRows(JSON.parse(String(stdout || "[]"))));
            } catch (_e) {
              done([]);
            }
          }
        );
      } catch (_e) {
        done([]);
      }
    });
  }

  return { readFile, statFile, listDir, processSnapshot };
}

// The slice A pure modules, required lazily so this file can be unit tested
// with injected fakes before they land and so a missing module degrades to an
// empty model instead of taking the app down.
let cachedDeps = null;
function loadDeps() {
  if (cachedDeps) {
    return cachedDeps;
  }
  cachedDeps = {
    repos: require("./repos.js"),
    locks: require("./locks.js"),
    proctree: require("./proctree.js"),
    heartbeat: require("./heartbeat.js"),
    model: require("./model.js"),
  };
  return cachedDeps;
}

function emptyModel(ts) {
  return {
    rows: [],
    summary: { repos: 0, running: 0, reclaimable: 0, free: 0, children: 0, stalled: 0 },
    updatedAt: ts,
  };
}

// Last-resort liveness probe when no process snapshot is available. Signal 0 is
// an existence check - it sends nothing and changes nothing.
function nativePidAlive(pid) {
  if (!isFinite(pid) || pid <= 0) {
    return false;
  }
  try {
    process.kill(pid, 0);
    return true;
  } catch (e) {
    return !!(e && e.code === "EPERM"); // alive but not ours.
  }
}

/** Epoch SECONDS - the unit every pure module in this app expects. */
function nowSeconds() {
  return Date.now() / 1000;
}

function createPoller(opts) {
  const o = opts && typeof opts === "object" ? opts : {};
  const rcRoot = typeof o.rcRoot === "string" && o.rcRoot ? o.rcRoot : process.cwd();
  const env = o.env && typeof o.env === "object" ? o.env : process.env;
  const io = o.io && typeof o.io === "object" ? o.io : createDefaultIo({});
  // UNITS: epoch SECONDS, not milliseconds. locks.js and heartbeat.js both
  // document `now` as seconds because the lock `ts` is written by python
  // time.time() (ops/loop/lanes.py:388). Date.now() here computed every age
  // about 1e3 too large, which silently tripped the WRITE_GRACE_S = 30.0
  // branch in locks.js - see the two integration tests in test/poll.test.js.
  const now = typeof o.now === "function" ? o.now : nowSeconds;
  const log = typeof o.log === "function" ? o.log : function () {};
  const stallAfterS = posInt(o.stallAfterS, DEFAULT_STALL_AFTER_S);
  const injectedDeps = o.deps && typeof o.deps === "object" ? o.deps : null;

  let onModel = typeof o.onModel === "function" ? o.onModel : function () {};
  let fastMs = posInt(o.fastMs, DEFAULT_FAST_MS);
  let slowMs = posInt(o.slowMs, DEFAULT_SLOW_MS);

  let repos = null; // resolved once - the roster does not change under us.
  let snapshotRows = null; // null means "no snapshot available"
  let snapshotPids = null; // Set<pid>
  let snapshotStart = null; // Map<pid, startMs>
  let lockByRoot = new Map(); // root -> { lane, ctrl }
  let logsByRoot = new Map(); // root -> newestPerLane rows
  let childrenByPid = new Map(); // pid -> descendant count
  let lastModelValue = emptyModel(now());

  let fastInFlight = false;
  let slowInFlight = false;
  let fastTimer = null;
  let slowTimer = null;
  let stopped = false;

  function deps() {
    if (injectedDeps) {
      return injectedDeps;
    }
    try {
      return loadDeps();
    } catch (e) {
      log("lane-widget: pure modules unavailable: " + (e && e.message));
      return null;
    }
  }

  // Run fn, swallow anything it throws, and await a promise result. Returns
  // fallback on any failure. This is the single fail-soft chokepoint.
  async function guard(fn, fallback, what) {
    try {
      const v = fn();
      return v && typeof v.then === "function" ? await v : v;
    } catch (e) {
      log("lane-widget: " + what + " failed: " + (e && e.message ? e.message : e));
      return fallback;
    }
  }

  function repoList() {
    if (repos) {
      return repos;
    }
    const d = deps();
    if (!d || !d.repos || typeof d.repos.resolveRepos !== "function") {
      repos = [{ code: "RC", root: rcRoot, isSelf: true }];
      return repos;
    }
    try {
      const got = d.repos.resolveRepos({
        rcRoot: rcRoot,
        env: env,
        readFile: (p) => {
          try {
            const v = io.readFile(p);
            return typeof v === "string" ? v : null;
          } catch (_e) {
            return null;
          }
        },
      });
      repos = Array.isArray(got) && got.length ? got : [{ code: "RC", root: rcRoot, isSelf: true }];
    } catch (e) {
      log("lane-widget: roster resolve failed: " + (e && e.message));
      repos = [{ code: "RC", root: rcRoot, isSelf: true }];
    }
    return repos;
  }

  // Liveness: an injected probe wins, then the machine snapshot, then a native
  // signal-0 check. Without any of those a lock would be classified from file
  // EXISTENCE, which is exactly the phantom-lane bug this widget must not have.
  function pidAlive(pid) {
    if (typeof io.pidAlive === "function") {
      try {
        return !!io.pidAlive(pid);
      } catch (_e) {
        return false;
      }
    }
    if (snapshotPids) {
      return snapshotPids.has(Number(pid));
    }
    return nativePidAlive(Number(pid));
  }

  // Epoch SECONDS, or null for UNKNOWN. Unknown must never be read as a
  // stranger - that is the pid-reuse guard's stated intent.
  function procStarted(pid) {
    if (typeof io.procStarted === "function") {
      try {
        const v = io.procStarted(pid);
        return typeof v === "number" && isFinite(v) ? v : null;
      } catch (_e) {
        return null;
      }
    }
    if (!snapshotStart) {
      return null;
    }
    const ms = snapshotStart.get(Number(pid));
    return typeof ms === "number" && isFinite(ms) && ms > 0 ? Math.floor(ms / 1000) : null;
  }

  function classifyText(d, text, ts) {
    const empty = { state: "FREE", payload: null, pid: 0, reason: "no lock" };
    if (!d || !d.locks) {
      return empty;
    }
    let payload = null;
    try {
      payload = d.locks.parseLock(text);
    } catch (_e) {
      payload = null;
    }
    try {
      const c = d.locks.classify({
        payload: payload,
        now: ts,
        pidAlive: pidAlive,
        procStarted: procStarted,
        // ops/loop/lanes.py:280 keys FREE on lock.exists(), NOT on the payload
        // parsing. io.readFile returns a string when the file was read and null
        // when it was absent or unreadable, so this is the only place that can
        // tell a half-written lock from no lock at all.
        lockExists: typeof text === "string",
      });
      return {
        state: c && c.state ? c.state : "FREE",
        payload: payload,
        pid: c && typeof c.pid === "number" ? c.pid : 0,
        reason: c && c.reason ? c.reason : "",
      };
    } catch (e) {
      log("lane-widget: classify failed: " + (e && e.message));
      return empty;
    }
  }

  function compose(ts) {
    const d = deps();
    const list = repoList();
    const built = [];
    for (const r of list) {
      const locks = lockByRoot.get(r.root) || {};
      const lane = locks.lane || { state: "FREE", payload: null, pid: 0 };
      const ctrl = locks.ctrl || { state: "FREE", payload: null, pid: 0 };
      built.push({
        code: r.code,
        root: r.root,
        isSelf: !!r.isSelf,
        lane: lane,
        ctrl: ctrl,
        children: childrenByPid.get(lane.pid) || 0,
        logs: logsByRoot.get(r.root) || [],
      });
    }
    let model = null;
    if (d && d.model && typeof d.model.buildModel === "function") {
      try {
        model = d.model.buildModel({ repos: built, now: ts });
      } catch (e) {
        log("lane-widget: buildModel failed: " + (e && e.message));
        model = null;
      }
    }
    if (!model || typeof model !== "object" || !Array.isArray(model.rows)) {
      model = emptyModel(ts);
    }
    lastModelValue = model;
    try {
      onModel(model);
    } catch (e) {
      log("lane-widget: onModel threw: " + (e && e.message));
    }
    return model;
  }

  // FAST: 2 * repoCount reads. Nothing else. Ever.
  async function tickFast() {
    if (stopped || fastInFlight) {
      return lastModelValue;
    }
    fastInFlight = true;
    try {
      const d = deps();
      const laneRel = d && d.locks && d.locks.LANE_LOCK_REL
        ? d.locks.LANE_LOCK_REL
        : ["ops", "loop", "control", "lanes", "0.lock"];
      const ctrlRel = d && d.locks && d.locks.CTRL_LOCK_REL
        ? d.locks.CTRL_LOCK_REL
        : ["ops", "loop", "control", "RUNNING.lock"];
      const ts = now();
      const next = new Map();
      for (const r of repoList()) {
        const laneText = await guard(
          () => io.readFile(path.join.apply(path, [r.root].concat(laneRel))),
          null,
          "read lane lock"
        );
        const ctrlText = await guard(
          () => io.readFile(path.join.apply(path, [r.root].concat(ctrlRel))),
          null,
          "read controller lock"
        );
        next.set(r.root, {
          lane: classifyText(d, laneText, ts),
          ctrl: classifyText(d, ctrlText, ts),
        });
      }
      lockByRoot = next;
      return compose(ts);
    } catch (e) {
      log("lane-widget: fast tick failed: " + (e && e.message));
      return lastModelValue;
    } finally {
      fastInFlight = false;
    }
  }

  // SLOW: one listing per repo + ONE machine-wide snapshot reused by all.
  async function tickSlow() {
    if (stopped || slowInFlight) {
      return lastModelValue;
    }
    slowInFlight = true;
    try {
      const d = deps();
      const ts = now();

      const rows = await guard(() => io.processSnapshot(), null, "process snapshot");
      if (Array.isArray(rows)) {
        snapshotRows = rows;
        snapshotPids = new Set();
        snapshotStart = new Map();
        for (const p of rows) {
          if (p && isFinite(p.pid)) {
            snapshotPids.add(Number(p.pid));
            snapshotStart.set(Number(p.pid), Number(p.startMs) || 0);
          }
        }
      } else {
        // Fail-soft: keep the previous snapshot if we had one, otherwise leave
        // it unavailable so pidAlive falls back to the native probe.
        log("lane-widget: snapshot unavailable, children counts fall back to 0");
      }

      const nextLogs = new Map();
      for (const r of repoList()) {
        const dir = path.join.apply(path, [r.root].concat(REPORTS_REL));
        const listed = await guard(() => io.listDir(dir), [], "list reports");
        const entries = [];
        for (const ent of Array.isArray(listed) ? listed : []) {
          if (typeof ent === "string") {
            const st = await guard(() => io.statFile(path.join(dir, ent)), null, "stat report");
            entries.push({ name: ent, mtimeMs: st && isFinite(st.mtimeMs) ? st.mtimeMs : 0 });
          } else if (ent && typeof ent === "object" && typeof ent.name === "string") {
            entries.push({ name: ent.name, mtimeMs: isFinite(ent.mtimeMs) ? ent.mtimeMs : 0 });
          }
        }
        let newest = [];
        if (d && d.heartbeat && typeof d.heartbeat.newestPerLane === "function") {
          newest = await guard(
            () => d.heartbeat.newestPerLane(entries, { now: ts, stallAfterS: stallAfterS }),
            [],
            "newestPerLane"
          );
        }
        nextLogs.set(r.root, Array.isArray(newest) ? newest : []);
      }
      logsByRoot = nextLogs;

      // Descendant counts for every pid we are currently tracking - one pass
      // over the single snapshot, no per-repo process work.
      const rootPids = [];
      for (const v of lockByRoot.values()) {
        for (const side of [v.lane, v.ctrl]) {
          if (side && side.pid > 0 && rootPids.indexOf(side.pid) === -1) {
            rootPids.push(side.pid);
          }
        }
      }
      const counts = new Map();
      if (snapshotRows && rootPids.length && d && d.proctree && typeof d.proctree.countByRoot === "function") {
        const got = await guard(
          () => d.proctree.countByRoot(snapshotRows, rootPids, {}),
          null,
          "countByRoot"
        );
        if (got && typeof got.get === "function") {
          for (const pid of rootPids) {
            const n = got.get(pid);
            counts.set(pid, typeof n === "number" && isFinite(n) ? n : 0);
          }
        }
      }
      childrenByPid = counts;

      return compose(ts);
    } catch (e) {
      log("lane-widget: slow tick failed: " + (e && e.message));
      return lastModelValue;
    } finally {
      slowInFlight = false;
    }
  }

  function start() {
    if (fastTimer || slowTimer) {
      return; // idempotent
    }
    stopped = false;
    // Prime the snapshot FIRST so the very first render classifies from a real
    // pid probe and never from file existence.
    tickSlow().then(() => tickFast());
    slowTimer = setInterval(() => {
      tickSlow();
    }, slowMs);
    fastTimer = setInterval(() => {
      tickFast();
    }, fastMs);
    if (typeof slowTimer.unref === "function") {
      slowTimer.unref();
    }
    if (typeof fastTimer.unref === "function") {
      fastTimer.unref();
    }
  }

  function stop() {
    stopped = true;
    if (fastTimer) {
      clearInterval(fastTimer);
      fastTimer = null;
    }
    if (slowTimer) {
      clearInterval(slowTimer);
      slowTimer = null;
    }
  }

  // Change the fast cadence live (the settings panel writes fastMs).
  function setFastMs(ms) {
    const next = posInt(ms, fastMs);
    if (next === fastMs) {
      return fastMs;
    }
    fastMs = next;
    if (fastTimer) {
      clearInterval(fastTimer);
      fastTimer = setInterval(() => {
        tickFast();
      }, fastMs);
      if (typeof fastTimer.unref === "function") {
        fastTimer.unref();
      }
    }
    return fastMs;
  }

  function setOnModel(fn) {
    onModel = typeof fn === "function" ? fn : function () {};
  }

  function lastModel() {
    return lastModelValue;
  }

  return { start, stop, tickFast, tickSlow, lastModel, setFastMs, setOnModel };
}

module.exports = {
  DEFAULT_FAST_MS,
  DEFAULT_SLOW_MS,
  REPORTS_REL,
  SNAPSHOT_ARGS,
  creationToMs,
  normalizeSnapshotRows,
  createDefaultIo,
  createPoller,
};
