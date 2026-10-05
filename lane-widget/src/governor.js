"use strict";
/**
 * The machine-wide GOVERNOR strip (FLEET-KIT v6, MAIN order 2026-10-04 2237,
 * section 4b): `Governor 2/3 - RC, CS - queue 1`.
 *
 * Source of truth: fleet_lanes.py (vendored at ops/fleet_kit/ by the kit
 * adoption). The governor is GOVERNOR_WIDTH slots, <slot root>/0.lock 1.lock
 * 2.lock, on-disk compatible with ops/loop/slots.py; waiters file tickets in
 * the slot root's SIBLING `queue` directory.
 *
 * Mirrors, rule for rule:
 *   slotState  <- fleet_lanes._slot_stale  (empty slot judged by mtime; past
 *                 2x stale_after always stale; else stale unless pid or
 *                 child_pid is live and not a start-time stranger)
 *   ticketLive <- fleet_lanes._ticket_live (empty ticket live inside the write
 *                 grace; heartbeat older than TICKET_HEARTBEAT_S is dead; else
 *                 a live, non-stranger pid)
 *
 * LEAK RULE: a slot payload's `repo` is whatever the holder passed - RC's own
 * loop_controller passes repo=str(ROOT), a FULL PATH. repoLabel maps a path
 * to its roster CODE, passes a bare code through, and renders anything else
 * as "?" - never the path.
 *
 * Pure and READ-ONLY: the texts, mtimes, clock (epoch SECONDS) and both
 * process probes arrive as parameters. Nothing here writes, reaps or unlinks.
 */

const path = require("path");

const GOVERNOR_WIDTH = 3;
const SLOT_NAMES = ["0.lock", "1.lock", "2.lock"];
const DEFAULT_STALE_AFTER_S = 3.0 * 5400.0; // fleet_lanes.DEFAULT_STALE_AFTER
const HARD_STALE_MULTIPLE = 2.0;
const WRITE_GRACE_S = 30.0;
const TICKET_HEARTBEAT_S = 120.0;
const PID_IDENTITY_EPS_S = 1.0;
const TICKET_SUFFIX = ".ticket";
// A queue deeper than this is a defect, not a workload; the poller stops
// reading tickets past it so one runaway directory cannot grow a tick.
const MAX_TICKETS_READ = 32;

const FREE = "FREE";
const RUNNING = "RUNNING";
const RECLAIMABLE = "RECLAIMABLE";

function isObject(v) {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function finiteOrNull(v) {
  const n = typeof v === "string" && v.trim() !== "" ? Number(v) : v;
  return typeof n === "number" && Number.isFinite(n) ? n : null;
}

function safeCall(fn, arg, fallback) {
  if (typeof fn !== "function") return fallback;
  try {
    return fn(arg);
  } catch (_err) {
    return fallback;
  }
}

function parse(text) {
  if (typeof text !== "string" || text.trim() === "") return null;
  try {
    const rec = JSON.parse(text);
    return isObject(rec) && Object.keys(rec).length > 0 ? rec : null;
  } catch (_err) {
    return null;
  }
}

/** fleet_lanes.governor_root: %ProgramData%/lw-loop/slots. null = no strip. */
function governorRoot(env) {
  const e = isObject(env) ? env : {};
  const base = e.ProgramData || e.PROGRAMDATA;
  if (typeof base !== "string" || base === "") return null;
  return path.join(base, "lw-loop", "slots");
}

/** fleet_lanes.queue_root: the slot root's sibling `queue` directory. */
function queueRoot(root) {
  return path.join(path.dirname(String(root)), "queue");
}

/** fleet_lanes._live: a truthy pid, alive, and not provably a reused pid. */
function live(pid, started, o) {
  const p = finiteOrNull(pid);
  if (p === null || !Number.isInteger(p) || p <= 0) return false;
  // A pid we cannot query counts as ALIVE (wait rather than double-book).
  if (safeCall(o.pidAlive, p, true) === false) return false;
  const want = finiteOrNull(started);
  if (want === null) return true;
  const actual = finiteOrNull(safeCall(o.procStarted, p, null));
  if (actual === null) return true;
  return Math.abs(actual - want) <= PID_IDENTITY_EPS_S;
}

/** slotState({ text, mtimeS, now, pidAlive, procStarted, staleAfterS }) -> FREE|RUNNING|RECLAIMABLE */
function slotState(opts) {
  const o = isObject(opts) ? opts : {};
  if (typeof o.text !== "string") return FREE;
  const now = finiteOrNull(o.now);
  const staleAfter = finiteOrNull(o.staleAfterS) || DEFAULT_STALE_AFTER_S;
  const rec = parse(o.text);
  if (rec === null) {
    const mt = finiteOrNull(o.mtimeS);
    if (mt === null || now === null) return RECLAIMABLE;
    return now - mt > staleAfter ? RECLAIMABLE : RUNNING;
  }
  const ts = finiteOrNull(rec.ts === undefined ? 0 : rec.ts);
  const age = ts === null || now === null ? Infinity : now - ts;
  if (age > staleAfter * HARD_STALE_MULTIPLE) return RECLAIMABLE;
  if (live(rec.pid, rec.pid_started, o) || live(rec.child_pid, rec.child_started, o)) return RUNNING;
  return RECLAIMABLE;
}

/** ticketLive({ text, mtimeS, now, pidAlive, procStarted }) -> boolean */
function ticketLive(opts) {
  const o = isObject(opts) ? opts : {};
  const beat = finiteOrNull(o.mtimeS);
  const now = finiteOrNull(o.now);
  if (beat === null || now === null) return false;
  const rec = parse(o.text);
  if (rec === null) return now - beat <= WRITE_GRACE_S;
  if (now - beat > TICKET_HEARTBEAT_S) return false;
  return live(rec.pid, rec.pid_started, o);
}

function normPath(p) {
  return String(p).replace(/\//g, "\\").replace(/\\+$/, "").toLowerCase();
}

/**
 * The CODE to print for a slot's `repo` field. A roster root (any case, any
 * separator, trailing separator or not) maps to its code; a bare 1-8 char
 * alphanumeric code passes through upper-cased; anything else is "?".
 */
function repoLabel(repo, roster) {
  if (typeof repo !== "string" || repo.trim() === "") return "?";
  const r = repo.trim();
  const list = Array.isArray(roster) ? roster : [];
  for (const entry of list) {
    if (!isObject(entry) || typeof entry.code !== "string") continue;
    if (entry.code.toUpperCase() === r.toUpperCase()) return entry.code;
    if (typeof entry.root === "string" && entry.root !== "" && normPath(entry.root) === normPath(r)) {
      return entry.code;
    }
  }
  if (/^[A-Za-z0-9]{1,8}$/.test(r)) return r.toUpperCase();
  return "?";
}

/**
 * governorFor({ slots: [{text, mtimeS}] x width, tickets: [{text, mtimeS}],
 *               roster, now, pidAlive, procStarted })
 * -> { width, held, stale, repos: [code per RUNNING slot, slot order], queue }
 */
function governorFor(opts) {
  const o = isObject(opts) ? opts : {};
  const slots = Array.isArray(o.slots) ? o.slots : [];
  const out = { width: GOVERNOR_WIDTH, held: 0, stale: 0, repos: [], queue: 0 };
  for (let i = 0; i < GOVERNOR_WIDTH; i += 1) {
    const s = isObject(slots[i]) ? slots[i] : {};
    const state = slotState(Object.assign({}, o, { text: s.text, mtimeS: s.mtimeS }));
    if (state === RUNNING) {
      out.held += 1;
      const rec = parse(s.text);
      out.repos.push(repoLabel(rec === null ? null : rec.repo, o.roster));
    } else if (state === RECLAIMABLE) {
      out.stale += 1;
    }
  }
  const tickets = Array.isArray(o.tickets) ? o.tickets : [];
  for (const t of tickets) {
    if (!isObject(t)) continue;
    if (ticketLive(Object.assign({}, o, { text: t.text, mtimeS: t.mtimeS }))) out.queue += 1;
  }
  return out;
}

/** `Governor 2/3 - RC, CS - queue 1[ - N stale]`, alarm on a stale slot. null in, null out. */
function governorLine(g) {
  if (!isObject(g)) return null;
  const width = finiteOrNull(g.width) || GOVERNOR_WIDTH;
  const held = Math.max(0, finiteOrNull(g.held) || 0);
  const stale = Math.max(0, finiteOrNull(g.stale) || 0);
  const queue = Math.max(0, finiteOrNull(g.queue) || 0);
  const repos = Array.isArray(g.repos)
    ? g.repos.filter((c) => typeof c === "string" && c !== "").map((c) => c.replace(/[^\x20-\x7e]/g, ""))
    : [];
  const parts = [`Governor ${held}/${width}`];
  if (repos.length > 0) parts.push(repos.join(", "));
  parts.push(`queue ${queue}`);
  if (stale > 0) parts.push(`${stale} stale`);
  return { text: parts.join(" - "), alarm: stale > 0 };
}

module.exports = {
  GOVERNOR_WIDTH,
  SLOT_NAMES,
  DEFAULT_STALE_AFTER_S,
  TICKET_HEARTBEAT_S,
  TICKET_SUFFIX,
  MAX_TICKETS_READ,
  governorRoot,
  queueRoot,
  slotState,
  ticketLive,
  repoLabel,
  governorFor,
  governorLine,
};
