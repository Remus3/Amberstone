"use strict";
/**
 * Parse and classify the lane lock and the controller lock.
 *
 * THE correctness property of this widget: liveness is decided by a PID PROBE
 * and NEVER by file existence. RC carries stale lane locks on disk whose pids
 * are long dead; a classifier that trusts the file renders phantom RUNNING
 * lanes. Mirrors ops/loop/lanes.py:271-312 (`lane_state`) and :225-242
 * (`_holder_is_a_stranger`), and dashboard/routes_loop_status.py:401-444 for
 * the controller lock, which applies the identical rule.
 *
 * READ-ONLY OBSERVER. Nothing here writes, locks, unlinks or reaps. Clearing a
 * RECLAIMABLE lock is `try_acquire_lane`'s job in the owning repo, never ours.
 *
 * Pure: the clock and both process probes arrive as parameters.
 * `now` is epoch SECONDS, pairing with the lock's own `ts` (python time.time()).
 */

// ops/loop/lanes.py:138-141 - MAX_SLOTS = 1, root control/lanes, LOCK_NAME "0.lock".
const LANE_LOCK_REL = ["ops", "loop", "control", "lanes", "0.lock"];
// dashboard/routes_loop_status.py:322 CONTROLLER_LOCK_NAME = "RUNNING.lock".
const CTRL_LOCK_REL = ["ops", "loop", "control", "RUNNING.lock"];

// ops/loop/lanes.py:143-145
const FREE = "FREE";
const RUNNING = "RUNNING";
const RECLAIMABLE = "RECLAIMABLE";

/**
 * ops/loop/lanes.py:225 `_PID_IDENTITY_EPS_S = 1.0`.
 *
 * SOURCE WINS: the build spec said 2. This is a guard against clock
 * representation drift, not a tolerance to tune - a real pid reuse is
 * separated by whole seconds at minimum.
 */
const START_TOLERANCE_S = 1.0;

/**
 * ops/loop/lanes.py:150 `WRITE_GRACE_S = 30.0`. A lock is created empty by
 * O_EXCL and filled a moment later; inside that window an unparseable lock is
 * presumed live, past it nothing about it can be proven alive.
 */
const WRITE_GRACE_S = 30.0;

function isObject(v) {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function finiteOrNull(v) {
  const n = typeof v === "string" ? Number(v) : v;
  return typeof n === "number" && Number.isFinite(n) ? n : null;
}

/** A usable pid is a positive integer. Mirrors slots.pid_alive's `pid <= 0` guard. */
function pidOrZero(v) {
  const n = finiteOrNull(v);
  if (n === null || !Number.isInteger(n) || n <= 0) return 0;
  return n;
}

/**
 * parseLock(text) -> payload object, or null for null / empty / invalid JSON /
 * non-object. Mirrors ops/loop/lanes.py:250-262 `_read_payload`, which returns
 * {} for exactly these shapes.
 */
function parseLock(text) {
  if (typeof text !== "string" || text.trim() === "") return null;
  let rec;
  try {
    rec = JSON.parse(text);
  } catch (_err) {
    return null;
  }
  return isObject(rec) ? rec : null;
}

/**
 * The pid to PROBE.
 *
 * SOURCE WINS, and this one matters. The build spec said
 * `claimed_by_pid ?? pid`. That is INVERTED. ops/loop/lanes.py:441-443
 * (`repoint_lane_pid`) sets `rec["pid"]` to the WORKER and
 * `rec["claimed_by_pid"]` to the long-lived RC server that claimed the lane,
 * and `lane_state` (:286) probes `rec.get("pid")` alone. Probing
 * claimed_by_pid would hit a process that is ALWAYS alive, so every repointed
 * lock - which is every real lane fire - would read RUNNING forever after its
 * worker died. That is precisely the stale-lock failure the three states exist
 * to prevent.
 *
 * claimed_by_pid is kept only as a last resort when `pid` is absent or
 * unusable, where the source would have no pid to probe at all.
 */
function effectivePid(payload) {
  if (!isObject(payload)) return 0;
  const pid = pidOrZero(payload.pid);
  if (pid > 0) return pid;
  return pidOrZero(payload.claimed_by_pid);
}

/** Seconds since the lock's `ts`, clamped at zero. Null when undatable. */
function ageS(payload, now) {
  if (!isObject(payload)) return null;
  const ts = finiteOrNull(payload.ts);
  const t = finiteOrNull(now);
  if (ts === null || t === null) return null;
  return Math.max(0, t - ts);
}

/** Call an injected probe without ever letting it throw into the caller. */
function safeCall(fn, arg, fallback) {
  if (typeof fn !== "function") return fallback;
  try {
    return fn(arg);
  } catch (_err) {
    return fallback;
  }
}

/**
 * True only when the live pid is PROVABLY not the process that claimed it.
 *
 * Mirrors ops/loop/lanes.py:228-242. EVERY uncertain case answers false: no
 * recorded value, an unparseable one, or no readable start time for the live
 * pid. Its docstring is the reason - "Freeing a lane on a guess double-books a
 * running worker, which is strictly worse than the wedge this function exists
 * to prevent."
 */
function isStranger(pid, recorded, procStarted) {
  const want = finiteOrNull(recorded);
  if (want === null) return false;
  const actual = finiteOrNull(safeCall(procStarted, pid, null));
  if (actual === null) return false;
  return Math.abs(actual - want) > START_TOLERANCE_S;
}

/**
 * classify({ payload, now, pidAlive, procStarted, lockExists })
 *   pidAlive:    (pid) => boolean
 *   procStarted: (pid) => number | null   (epoch seconds, null when unknown)
 *   lockExists:  optional. Defaults to "the payload parsed", which is what a
 *                caller that only has the text can say. Pass it explicitly to
 *                distinguish an ABSENT lock from a present-but-unparseable one
 *                - ops/loop/lanes.py:280 keys FREE on `lock.exists()`, not on
 *                the payload parsing.
 * -> { state, pid, reason }
 *
 * Total: every junk shape returns one of the three states rather than throwing.
 */
function classify(opts) {
  const o = isObject(opts) ? opts : {};
  const payload = isObject(o.payload) ? o.payload : null;
  const exists = o.lockExists === undefined ? payload !== null : Boolean(o.lockExists);

  // ops/loop/lanes.py:280-282 - no lock file at all is the only FREE.
  if (!exists) return { state: FREE, pid: 0, reason: "no_lock" };

  const pid = effectivePid(payload);
  const age = ageS(payload, o.now);

  if (pid <= 0) {
    // ops/loop/lanes.py:294-300 - no readable holder. Presumed live inside the
    // write-grace window; past it nothing about it can be proven alive. An
    // undatable lock stays RUNNING, exactly as lane_state does.
    if (age !== null && age > WRITE_GRACE_S) {
      return { state: RECLAIMABLE, pid: 0, reason: "no_pid_past_write_grace" };
    }
    return { state: RUNNING, pid: 0, reason: "no_pid_within_write_grace" };
  }

  // ops/loop/slots.py:55-57 - a pid we cannot query is treated as ALIVE
  // (conservative: rather wait than double-book a slot). So an absent or
  // throwing probe must NOT free the lane.
  const alive = safeCall(o.pidAlive, pid, true);
  if (alive === false) {
    return { state: RECLAIMABLE, pid, reason: "dead_pid" };
  }

  if (payload !== null && isStranger(pid, payload.pid_started, o.procStarted)) {
    // Alive, but not the same process: the holder died and the OS reissued its
    // pid. ops/loop/lanes.py:186-206 records the measured incident.
    return { state: RECLAIMABLE, pid, reason: "pid_reuse_stranger" };
  }

  return { state: RUNNING, pid, reason: "alive" };
}

module.exports = {
  LANE_LOCK_REL,
  CTRL_LOCK_REL,
  FREE,
  RUNNING,
  RECLAIMABLE,
  START_TOLERANCE_S,
  WRITE_GRACE_S,
  parseLock,
  effectivePid,
  ageS,
  classify,
};
