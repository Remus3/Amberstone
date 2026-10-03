"use strict";
/**
 * Compose the roster, the two lock verdicts, the child counts and the lane-log
 * heartbeats into the single render model slice C paints.
 *
 * Pure: the clock arrives as `now` (epoch SECONDS), everything else arrives as
 * data. No IO, no electron, no writes.
 *
 * LEAK RULE, enforced here because this is the LAST hop before a rendered
 * surface: nothing in a row may carry a filesystem path. `worktreeTail` is the
 * BASENAME and nothing more - a full sibling worktree path is a sibling name.
 * The repo CODE comes from the roster (src/repos.js), which never derives a
 * code from a directory basename.
 */

const locks = require("./locks.js");
const inboxStatus = require("./inbox_status.js");

const KIND_LANE = "lane";
const KIND_CONTROLLER = "controller";

// RUNNING first, then RECLAIMABLE, then FREE. Anything else sorts last.
const STATE_ORDER = {
  [locks.RUNNING]: 0,
  [locks.RECLAIMABLE]: 1,
  [locks.FREE]: 2,
};

function isObject(v) {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function finiteOrNull(v) {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function countOrZero(v) {
  const n = finiteOrNull(v);
  return n === null || n < 0 ? 0 : n;
}

function stringOrNull(v) {
  return typeof v === "string" && v !== "" ? v : null;
}

function stateOf(block) {
  if (!isObject(block)) return locks.FREE;
  const s = stringOrNull(block.state);
  return s === null ? locks.FREE : s;
}

function payloadOf(block) {
  return isObject(block) && isObject(block.payload) ? block.payload : null;
}

/**
 * The BASENAME of a worktree path, and nothing more.
 *
 * Split on BOTH separators - the payload is written by python on Windows
 * (ops/loop/lanes.py:384-387 stores `str(wt)`) and may arrive in either form -
 * then take the last NON-EMPTY segment so a trailing separator does not yield
 * an empty tail. Returns null rather than a path for every unusable shape.
 */
function worktreeTail(payload) {
  if (!isObject(payload)) return null;
  const raw = payload.worktree;
  if (typeof raw !== "string") return null;
  const parts = raw.split(/[\\/]+/).filter((p) => p.trim() !== "");
  if (parts.length === 0) return null;
  const tail = parts[parts.length - 1].trim();
  // A bare drive letter ("C:") is not a basename, and it is still a path.
  if (tail === "" || /^[A-Za-z]:$/.test(tail)) return null;
  return tail;
}

/** The newest log row for this lane, from the repo's already-reduced listing. */
function logFor(logs, laneName) {
  if (!Array.isArray(logs) || laneName === null) return null;
  for (const row of logs) {
    if (!isObject(row)) continue;
    if (stringOrNull(row.lane) === laneName) return row;
  }
  return null;
}

function labelFor(kind, state, laneName) {
  if (state === locks.FREE) return "idle";
  if (kind === KIND_CONTROLLER) return KIND_CONTROLLER;
  return laneName === null ? KIND_LANE : laneName;
}

function makeRow(repoCode, kind, block, opts) {
  const state = stateOf(block);
  const payload = payloadOf(block);
  const laneName = kind === KIND_LANE && payload !== null
    ? stringOrNull(payload.lane)
    : null;
  const log = kind === KIND_LANE ? logFor(opts.logs, laneName) : null;

  return {
    key: `${repoCode}:${kind}`,
    repoCode,
    kind,
    label: labelFor(kind, state, laneName),
    state,
    lane: laneName,
    runId: payload === null ? null : stringOrNull(payload.run_id),
    ageS: locks.ageS(payload, opts.now),
    children: opts.children,
    logAgeS: log === null ? null : finiteOrNull(log.ageS),
    stalled: log === null ? false : log.stalled === true,
    worktreeTail: worktreeTail(payload),
  };
}

/**
 * ONE row per repo for the ALL tab: the lane and the controller folded into a
 * single record (a headless lane cannot run without its controller), plus the
 * tree's "Sync:" parts from its inbox_status.json text.
 *
 * Deliberately carries NO log age - the operator removed it from the row; the
 * `stalled` flag (which is derived from log age upstream) is all that remains.
 * No path field: display comes from the roster, never from a root.
 */
function makeRepoRow(code, repo, laneRow, ctrlRow, now) {
  const order = finiteOrNull(repo.order);
  const ctrlPayload = payloadOf(repo.ctrl);
  const sync = inboxStatus.syncFor({
    text: typeof repo.statusText === "string" ? repo.statusText : null,
    now,
    tickS: finiteOrNull(repo.tickS),
    attendedOnly: repo.attendedOnly === true,
  });
  return {
    key: `repo:${code}`,
    repoCode: code,
    display: stringOrNull(repo.display) || code,
    order,
    noLane: repo.noLane === true,
    attendedOnly: repo.attendedOnly === true,
    laneState: laneRow.state,
    lane: laneRow.lane,
    ageS: laneRow.ageS,
    ctrlState: ctrlRow.state,
    ctrlAgeS: locks.ageS(ctrlPayload, now),
    children: laneRow.children,
    stalled: laneRow.stalled,
    sync: inboxStatus.syncParts(sync),
  };
}

/**
 * buildModel({ repos, now }) -> { rows, repoRows, summary, updatedAt }
 *
 * rows      lane + controller rows, STATE-sorted - the per-repo tabs.
 * repoRows  one row per repo, ROSTER-ordered by `order` - the ALL tab.
 *
 * repos: [ { code, root, isSelf,
 *            lane: { state, payload, pid },   // from locks.classify
 *            ctrl: { state, payload, pid },
 *            children: number,                // descendants of the lane pid
 *            ctrlChildren: number,            // optional, controller pid
 *            logs: [ ...heartbeat.newestPerLane rows ] } ]
 *
 * Total by construction: zero repos, a null argument and an every-field-missing
 * repo all produce a valid model rather than a throw. That is load bearing -
 * this output feeds an IPC push on a timer, and a throw there kills the poll.
 */
function buildModel(opts) {
  const o = isObject(opts) ? opts : {};
  const now = finiteOrNull(o.now);
  const repos = Array.isArray(o.repos) ? o.repos.filter(isObject) : [];

  const decorated = [];
  const perRepo = [];
  repos.forEach((repo, index) => {
    // A repo with no code still renders - with a POSITIONAL placeholder, never
    // a basename derived from its root.
    const code = stringOrNull(repo.code) || (index === 0 ? "RC" : `REPO-${index + 1}`);
    const logs = Array.isArray(repo.logs) ? repo.logs : [];
    const laneRow = makeRow(code, KIND_LANE, repo.lane, {
      now, logs, children: countOrZero(repo.children),
    });
    const ctrlRow = makeRow(code, KIND_CONTROLLER, repo.ctrl, {
      now, logs, children: countOrZero(repo.ctrlChildren),
    });
    // A root-less roster entry has nothing to observe, so it contributes no
    // lane/controller rows - only its one ALL-tab repo row below.
    if (repo.noLane !== true) {
      decorated.push({ row: laneRow, repoIndex: index, kindIndex: 0 });
      decorated.push({ row: ctrlRow, repoIndex: index, kindIndex: 1 });
    }
    perRepo.push({ row: makeRepoRow(code, repo, laneRow, ctrlRow, now), index });
  });

  // Roster order: a finite `order` first, ascending; then unordered repos;
  // roster index breaks every tie, so the order is a property of this function.
  perRepo.sort((a, b) => {
    const oa = a.row.order;
    const ob = b.row.order;
    if (oa !== null && ob !== null && oa !== ob) return oa - ob;
    if (oa !== null && ob === null) return -1;
    if (oa === null && ob !== null) return 1;
    return a.index - b.index;
  });
  const repoRows = perRepo.map((p) => p.row);

  // Decorate-sort-undecorate rather than relying on the engine's sort being
  // stable: the tie break is spelled out, so the order is a property of this
  // function and not of the runtime.
  decorated.sort((a, b) => {
    const sa = STATE_ORDER[a.row.state];
    const sb = STATE_ORDER[b.row.state];
    const ra = sa === undefined ? 3 : sa;
    const rb = sb === undefined ? 3 : sb;
    if (ra !== rb) return ra - rb;
    if (a.repoIndex !== b.repoIndex) return a.repoIndex - b.repoIndex;
    return a.kindIndex - b.kindIndex;
  });

  const rows = decorated.map((d) => d.row);
  const summary = {
    repos: repos.length,
    running: 0,
    reclaimable: 0,
    free: 0,
    children: 0,
    stalled: 0,
  };
  for (const row of rows) {
    if (row.state === locks.RUNNING) summary.running += 1;
    else if (row.state === locks.RECLAIMABLE) summary.reclaimable += 1;
    else if (row.state === locks.FREE) summary.free += 1;
    summary.children += row.children;
    if (row.stalled) summary.stalled += 1;
  }

  return { rows, repoRows, summary, updatedAt: now };
}

module.exports = { KIND_LANE, KIND_CONTROLLER, worktreeTail, buildModel, makeRepoRow };
