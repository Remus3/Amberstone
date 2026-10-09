"use strict";
/**
 * One tree's inbox responder status, reduced to the operator's "Sync:" line.
 *
 * Every participating tree writes ONE file at the same relative path,
 * ops/loop/control/inbox_status.json, schema 1:
 *
 *   { schema: 1, code, updated, state, task, task_started, task_eta_s,
 *     next_tick, runs_in_window, runs_cap, window_s, cap_frees_at }
 *
 *   state in idle | running | limit | backoff | halted | refused | blocked
 *   (blocked: FLEET-KIT v14, an outside cause such as an unreachable proxy)
 *
 * This widget only READS that file - poll.js hands the raw text in, this module
 * never touches a disk. Pure: the clock arrives as `now` (epoch SECONDS).
 *
 * The rendered grammar, from the operator's order:
 *
 *   Sync: <task> [<elapsed>/<eta>][<runs_in_window>/<runs_cap>]
 *   Sync: Turn Limit Reached [<hours until cap_frees_at>][<runs>/<cap>]
 *   Sync: no signal [<age>]
 *   Sync: attended only
 *
 * NO SIGNAL is total: an absent file, unparseable JSON, a wrong schema, an
 * unknown state, an unreadable `updated` stamp, or a file older than 2x the
 * tree's tick interval all render "no signal" - never the stale numbers the
 * file still carries.
 */

const STATUS_REL = ["ops", "loop", "control", "inbox_status.json"];

const SCHEMA = 1;
const DEFAULT_TICK_S = 300;
const MAX_TASK_CHARS = 24;
const UNKNOWN = "?";

// The basic name per state, used when the file carries no usable task name.
const DEFAULT_TASK = {
  idle: "Idle",
  running: "Running Session",
  limit: "Turn Limit Reached",
  backoff: "Backing Off",
  halted: "Halted",
  refused: "Refused",
  blocked: "Blocked",
};

function isObject(v) {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function finiteOrNull(v) {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/** Epoch SECONDS from an ISO-8601 string, or null. */
function isoToS(v) {
  if (typeof v !== "string" || v.trim() === "") return null;
  const ms = Date.parse(v);
  return Number.isFinite(ms) ? ms / 1000 : null;
}

function countOrNull(v) {
  const n = finiteOrNull(v);
  return n === null || n < 0 ? null : Math.floor(n);
}

/** Printable ASCII only, capped. An empty result is null. */
function cleanTask(v) {
  if (typeof v !== "string") return null;
  const ascii = v.replace(/[^\x20-\x7e]/g, "").replace(/\s+/g, " ").trim();
  if (ascii === "") return null;
  return ascii.length > MAX_TASK_CHARS ? ascii.slice(0, MAX_TASK_CHARS).trim() : ascii;
}

/**
 * A span in seconds -> "<n>m" under 120 minutes, "<n>HR" from there.
 *
 * mode "floor" for time already spent (never overstate progress), "ceil" for a
 * total or a countdown (never understate what is left). The unit is decided on
 * the ROUNDED minute count, so a ceil'd 119.5m reads "2HR", never "120m".
 * Absent, negative or non-finite -> "?".
 */
function formatSpan(seconds, mode) {
  const sec = finiteOrNull(seconds);
  if (sec === null || sec < 0) return UNKNOWN;
  const round = mode === "ceil" ? Math.ceil : Math.floor;
  const minutes = round(sec / 60);
  if (minutes < 120) return minutes + "m";
  return round(sec / 3600) + "HR";
}

/** The parsed schema-1 blob, or null for every shape that is not one. */
function parseStatus(text) {
  if (typeof text !== "string" || text.trim() === "") return null;
  let blob;
  try {
    blob = JSON.parse(text);
  } catch (_err) {
    return null;
  }
  if (!isObject(blob)) return null;
  if (blob.schema !== SCHEMA) return null;
  if (typeof blob.state !== "string" || !Object.prototype.hasOwnProperty.call(DEFAULT_TASK, blob.state)) {
    return null;
  }
  return blob;
}

/**
 * syncFor({ text, now, tickS, attendedOnly }) -> a sync descriptor:
 *
 *   { kind: "attended" }
 *   { kind: "nosignal", ageS }                       ageS null when unknown
 *   { kind: "live", state, task, elapsedS, etaS, freesInS, runs, cap }
 *
 * Total: junk in returns a "nosignal" descriptor, never a throw - this runs on
 * the poll timer path.
 */
function syncFor(opts) {
  const o = isObject(opts) ? opts : {};
  if (o.attendedOnly === true) return { kind: "attended" };

  const now = finiteOrNull(o.now);
  const tickRaw = finiteOrNull(o.tickS);
  const tickS = tickRaw === null || tickRaw <= 0 ? DEFAULT_TICK_S : tickRaw;

  const blob = parseStatus(o.text);
  if (blob === null) return { kind: "nosignal", ageS: null };

  const updated = isoToS(blob.updated);
  if (updated === null || now === null) return { kind: "nosignal", ageS: null };
  const ageS = Math.max(0, now - updated);
  if (ageS > 2 * tickS) return { kind: "nosignal", ageS };

  const state = blob.state;
  const started = isoToS(blob.task_started);
  const elapsedS = started === null ? null : Math.max(0, now - started);
  const nextTick = isoToS(blob.next_tick);
  const etaRaw = finiteOrNull(blob.task_eta_s);
  let etaS = etaRaw === null || etaRaw < 0 ? null : etaRaw;
  // Idle: elapsed idle over the whole idle span, i.e. up to the next tick.
  // Backoff falls back to the same span when it carries no measured ETA.
  if ((state === "idle" || (state === "backoff" && etaS === null)) &&
      nextTick !== null && started !== null) {
    etaS = Math.max(0, nextTick - started);
  }
  const frees = isoToS(blob.cap_frees_at);

  return {
    kind: "live",
    state,
    task: cleanTask(blob.task) || DEFAULT_TASK[state],
    elapsedS,
    etaS,
    freesInS: frees === null ? null : Math.max(0, frees - now),
    runs: countOrNull(blob.runs_in_window),
    cap: countOrNull(blob.runs_cap),
  };
}

/**
 * The two rendered halves: { task, tail }. The renderer ellipsizes `task` and
 * never `tail`, so the numbers survive a narrow row. syncText joins them.
 */
function syncParts(sync) {
  const d = isObject(sync) ? sync : { kind: "nosignal", ageS: null };
  if (d.kind === "attended") return { task: "attended only", tail: "" };
  if (d.kind !== "live") {
    return { task: "no signal", tail: "[" + formatSpan(d.ageS, "floor") + "]" };
  }
  const runs = "[" + (d.runs === null ? UNKNOWN : d.runs) + "/" +
    (d.cap === null ? UNKNOWN : d.cap) + "]";
  if (d.state === "limit") {
    return { task: d.task, tail: "[" + formatSpan(d.freesInS, "ceil") + "]" + runs };
  }
  return {
    task: d.task,
    tail: "[" + formatSpan(d.elapsedS, "floor") + "/" + formatSpan(d.etaS, "ceil") + "]" + runs,
  };
}

function syncText(sync) {
  const p = syncParts(sync);
  return "Sync: " + p.task + (p.tail === "" ? "" : " " + p.tail);
}

module.exports = {
  STATUS_REL,
  SCHEMA,
  DEFAULT_TICK_S,
  MAX_TASK_CHARS,
  DEFAULT_TASK,
  formatSpan,
  parseStatus,
  syncFor,
  syncParts,
  syncText,
};
