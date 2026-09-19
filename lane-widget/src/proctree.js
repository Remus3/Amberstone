"use strict";
/**
 * Descendants of a set of root pids, computed from ONE flat machine-wide
 * process snapshot.
 *
 * Pure: the snapshot arrives as data. Nothing here shells out, and nothing here
 * enumerates a directory - the poller takes exactly one snapshot per slow tick
 * and reuses it for every repo (build contract section 3, src/poll.js).
 *
 * Defensive by construction: a real snapshot is a race against the scheduler,
 * so it routinely contains a row whose parent has already exited, and it can
 * present an apparent CYCLE once the OS reissues a pid. Both are tolerated -
 * every pid is visited at most once and the walk is depth-capped.
 */

const DEFAULT_MAX_DEPTH = 8;

function isObject(v) {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

/** A usable pid is a positive integer; a numeric string is accepted. */
function pidOrNull(v) {
  const n = typeof v === "string" ? Number(v) : v;
  if (typeof n !== "number" || !Number.isFinite(n)) return null;
  if (!Number.isInteger(n) || n <= 0) return null;
  return n;
}

function depthLimit(opts) {
  const raw = isObject(opts) ? opts.maxDepth : undefined;
  if (raw === undefined) return DEFAULT_MAX_DEPTH;
  const n = typeof raw === "string" ? Number(raw) : raw;
  if (typeof n !== "number" || !Number.isFinite(n) || n < 0) return DEFAULT_MAX_DEPTH;
  return Math.floor(n);
}

/** Normalise a pid or array of pids into a de-duplicated list of usable pids. */
function rootList(rootPids) {
  const raw = Array.isArray(rootPids) ? rootPids : [rootPids];
  const out = [];
  const seen = new Set();
  for (const r of raw) {
    const pid = pidOrNull(r);
    if (pid === null || seen.has(pid)) continue;
    seen.add(pid);
    out.push(pid);
  }
  return out;
}

/** ppid -> [row, ...], built once per call. Junk rows are skipped. */
function childIndex(snapshot) {
  const index = new Map();
  if (!Array.isArray(snapshot)) return index;
  for (const raw of snapshot) {
    if (!isObject(raw)) continue;
    const pid = pidOrNull(raw.pid);
    const ppid = pidOrNull(raw.ppid);
    if (pid === null || ppid === null) continue;
    const row = {
      pid,
      ppid,
      name: typeof raw.name === "string" ? raw.name : null,
      startMs:
        typeof raw.startMs === "number" && Number.isFinite(raw.startMs)
          ? raw.startMs
          : null,
    };
    const bucket = index.get(ppid);
    if (bucket) bucket.push(row);
    else index.set(ppid, [row]);
  }
  return index;
}

/**
 * descendants(snapshot, rootPids, { maxDepth = 8 }) -> [ row + depth ], BFS,
 * roots EXCLUDED. Cycle-safe (each pid is visited at most once) and tolerant of
 * a snapshot that is missing a parent row.
 */
function descendants(snapshot, rootPids, opts) {
  const roots = rootList(rootPids);
  if (roots.length === 0) return [];

  const maxDepth = depthLimit(opts);
  if (maxDepth === 0) return [];

  const index = childIndex(snapshot);
  // Seeding `visited` with the roots is what excludes them from the output AND
  // what stops a root that is also a descendant of another root from being
  // emitted twice.
  const visited = new Set(roots);
  const out = [];

  let frontier = roots;
  for (let depth = 1; depth <= maxDepth && frontier.length > 0; depth += 1) {
    const next = [];
    for (const parent of frontier) {
      const kids = index.get(parent);
      if (!kids) continue;
      for (const kid of kids) {
        if (visited.has(kid.pid)) continue; // cycle / duplicate pid guard
        visited.add(kid.pid);
        out.push({
          pid: kid.pid,
          ppid: kid.ppid,
          name: kid.name,
          startMs: kid.startMs,
          depth,
        });
        next.push(kid.pid);
      }
    }
    frontier = next;
  }
  return out;
}

/**
 * countByRoot(snapshot, rootPids, opts) -> Map<rootPid, number>
 *
 * Each root is walked INDEPENDENTLY, so a process reachable from two roots is
 * counted under both - the number answers "how many processes hang off this
 * lane's worker", which is a per-root question.
 */
function countByRoot(snapshot, rootPids, opts) {
  const out = new Map();
  for (const root of rootList(rootPids)) {
    out.set(root, descendants(snapshot, [root], opts).length);
  }
  return out;
}

module.exports = { DEFAULT_MAX_DEPTH, descendants, countByRoot };
