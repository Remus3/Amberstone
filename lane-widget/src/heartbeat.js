"use strict";
/**
 * The newest lane log per lane, plus a stall flag.
 *
 * Pure: it consumes ONE flat directory listing (already filtered to files) and
 * an injected clock. No directory walk, no recursion, no decode.
 *
 * WE ONLY STAT THESE FILES. Lane logs are legitimately MIXED UTF-8 / UTF-16LE -
 * measured and documented at dashboard/routes_loop_status.py:118-162, where a
 * 4298-byte log was UTF-8 for 119 bytes and UTF-16LE for the rest. Nothing here
 * reads a byte of content, so that trap is sidestepped rather than handled. Do
 * not add log tailing to this module.
 *
 * UNITS: `now` is epoch SECONDS (it pairs with the lock `ts`, which is python
 * time.time()); entry mtimes arrive in MILLISECONDS, as node's fs.Stats reports
 * them. ageS is in seconds.
 */

/**
 * lane_<lane>_<run_id>.log
 *
 * The lane id MAY CONTAIN A HYPHEN ("true-audit"), so the run id is the LAST
 * underscore-separated segment, not the second. The leading group is greedy
 * for exactly that reason. Byte-for-byte the same grammar as
 * dashboard/routes_loop_status.py:99-102 `_LANE_LOG_RE`.
 */
const LOG_RE = /^lane_(.+)_([^_]+)\.log$/;

const DEFAULT_STALL_AFTER_S = 600;

function isObject(v) {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function finiteOrNull(v) {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/**
 * parseLogName(name) -> { lane, runId } | null
 *
 * Total: null for every off-grammar, empty or non-string input. LOG_RE carries
 * no /g flag, so it holds no lastIndex state between calls.
 */
function parseLogName(name) {
  if (typeof name !== "string") return null;
  const m = LOG_RE.exec(name);
  if (!m) return null;
  const lane = m[1];
  const runId = m[2];
  if (!lane || !runId) return null;
  return { lane, runId };
}

/**
 * newestPerLane(entries, { now, stallAfterS = 600 })
 *   entries: [ { name, mtimeMs } ] - one flat dir listing, files only
 *   -> [ { lane, runId, name, mtimeMs, ageS, stalled } ], NEWEST FIRST
 *
 * Only the newest entry per LANE survives. `stalled` is `ageS > stallAfterS`;
 * an undatable row can make no stall claim, so it is false.
 */
function newestPerLane(entries, opts) {
  if (!Array.isArray(entries)) return [];

  const o = isObject(opts) ? opts : {};
  const now = finiteOrNull(o.now);
  const rawStall = finiteOrNull(o.stallAfterS);
  const stallAfterS =
    rawStall !== null && rawStall >= 0 ? rawStall : DEFAULT_STALL_AFTER_S;

  const best = new Map(); // lane -> { row, order }
  let order = 0;

  for (const entry of entries) {
    if (!isObject(entry)) continue;
    const parsed = parseLogName(entry.name);
    if (parsed === null) continue;

    const mtimeMs = finiteOrNull(entry.mtimeMs);
    const ageS =
      mtimeMs === null || now === null ? null : Math.max(0, now - mtimeMs / 1000);
    const row = {
      lane: parsed.lane,
      runId: parsed.runId,
      name: entry.name,
      mtimeMs,
      ageS,
      stalled: ageS !== null && ageS > stallAfterS,
    };

    const seat = order;
    order += 1;
    const held = best.get(row.lane);
    // An undatable row never outranks a datable one.
    if (held === undefined || isNewer(row, held.row)) {
      best.set(row.lane, { row, order: seat });
    }
  }

  return [...best.values()].sort(cmpNewestFirst).map((e) => e.row);
}

function isNewer(candidate, held) {
  if (candidate.mtimeMs === null) return false;
  if (held.mtimeMs === null) return true;
  return candidate.mtimeMs > held.mtimeMs;
}

/** Newest first, undatable rows last, ties broken by listing order (STABLE).
 *  Written out longhand rather than as a subtraction, because subtracting two
 *  -Infinity sentinels yields NaN and a NaN comparator silently corrupts the
 *  sort order. */
function cmpNewestFirst(a, b) {
  const am = a.row.mtimeMs;
  const bm = b.row.mtimeMs;
  if (am === null && bm === null) return a.order - b.order;
  if (am === null) return 1;
  if (bm === null) return -1;
  if (am !== bm) return bm - am;
  return a.order - b.order;
}

module.exports = { LOG_RE, DEFAULT_STALL_AFTER_S, parseLogName, newestPerLane };
