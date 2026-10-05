"use strict";
/**
 * A LIVE lane's remaining checklist (FLEET-KIT v7, MAIN order 2026-10-05 0215,
 * section 4b; FLEET-COMMON item 13 d).
 *
 * A lane writes ops/loop/control/progress/lane-<i>.json in the MAIN checkout
 * (fleet_headless.write_progress + fleet_checklist.lane_task(i)), with
 *   { task, pct, step, eta_s, status, updated, checklist: [{id, task, state, eta_s}] }
 * where checklist holds the REMAINING tasks only, in execution order.
 *
 * The rules this module enforces:
 *   - no file, unparseable, or no "checklist" array  -> status "none"
 *   - "updated" older than 2x its eta_s               -> status "stale", NO items
 *     (an undatable "updated" or a missing eta_s cannot be proven fresh, so it
 *     is stale too - a stale list must never be shown as live)
 *   - otherwise the first ITEM_CAP items in order, plus a count of the rest.
 *
 * Pure: the text and the clock (epoch SECONDS) arrive as parameters. No IO.
 * Rendered text is 7-bit ASCII: the kit's U+2610 box becomes "[ ]".
 */

const ITEM_CAP = 3;

/**
 * eta_s 0 is legal (a final step with nothing left to estimate). Without a
 * floor such a file would be stale the instant it was written, so the window
 * never drops below this many seconds - fleet_lanes' WRITE_GRACE_S.
 */
const MIN_STALE_WINDOW_S = 30;

const BOX = "[ ]";

function isObject(v) {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function finiteOrNull(v) {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/** ops/loop/control/progress/lane-<i>.json - ONE named file per lane index. */
function progressRel(index) {
  return ["ops", "loop", "control", "progress", `lane-${Number(index)}.json`];
}

/** "updated" is ISO 8601 with a local offset (fleet_headless._iso). Seconds or null. */
function parseUpdated(v) {
  if (typeof v !== "string" || v === "") return null;
  const ms = Date.parse(v);
  return Number.isFinite(ms) ? ms / 1000 : null;
}

function cleanRow(r) {
  if (!isObject(r)) return null;
  if (typeof r.id !== "string" || r.id.trim() === "") return null;
  if (typeof r.task !== "string" || r.task.trim() === "") return null;
  const eta = finiteOrNull(r.eta_s);
  return {
    id: r.id.trim(),
    task: r.task.split(/\s+/).filter(Boolean).join(" "),
    state: typeof r.state === "string" && r.state.trim() !== "" ? r.state.trim() : null,
    eta_s: eta === null ? null : Math.max(0, eta),
  };
}

/**
 * checklistFor({ text, now }) -> { status: "live"|"stale"|"none", items, more }
 * Total: every junk input answers "none" rather than throwing.
 */
function checklistFor(opts) {
  const o = isObject(opts) ? opts : {};
  const none = { status: "none", items: [], more: 0 };
  if (typeof o.text !== "string" || o.text.trim() === "") return none;
  let doc;
  try {
    doc = JSON.parse(o.text);
  } catch (_err) {
    return none;
  }
  if (!isObject(doc) || !Array.isArray(doc.checklist)) return none;

  const now = finiteOrNull(o.now);
  const updated = parseUpdated(doc.updated);
  const eta = finiteOrNull(doc.eta_s);
  if (now === null || updated === null || eta === null || eta < 0) {
    return { status: "stale", items: [], more: 0 };
  }
  const window = 2 * Math.max(eta, MIN_STALE_WINDOW_S);
  if (now - updated > window) return { status: "stale", items: [], more: 0 };

  const rows = doc.checklist.map(cleanRow).filter((r) => r !== null);
  // Each shown item carries its rendered line, so the renderer (which cannot
  // require this module) paints text and never re-derives the format.
  return {
    status: "live",
    items: rows.slice(0, ITEM_CAP).map((r) => Object.assign(r, { text: itemLine(r) })),
    more: Math.max(0, rows.length - ITEM_CAP),
  };
}

/** fleet_checklist.fmt_eta units: s under 120 s, m under 120 m, h beyond. */
function fmtEta(etaS) {
  const s = finiteOrNull(etaS);
  if (s === null) return "";
  const n = Math.max(0, Math.floor(s));
  if (n < 120) return `~${n}s`;
  if (n < 7200) return `~${Math.round(n / 60)}m`;
  return `~${Math.round(n / 3600)}h`;
}

function asciiOnly(text) {
  return String(text).replace(/[^\x20-\x7e]/g, "");
}

/**
 * `[ ] <ID>: <task> (<state>, ~ETA)` - the state only when it is not
 * "pending", the ETA whenever one is set, the parenthesis only when either is.
 */
function itemLine(row) {
  const r = isObject(row) ? row : {};
  const parts = [];
  if (typeof r.state === "string" && r.state !== "" && r.state !== "pending") parts.push(r.state);
  const eta = fmtEta(r.eta_s);
  if (eta !== "") parts.push(eta);
  const tail = parts.length > 0 ? ` (${parts.join(", ")})` : "";
  const text = `${BOX} ${String(r.id)}: ${String(r.task)}${tail}`;
  return asciiOnly(text).replace(/\s+/g, " ").trim();
}

module.exports = {
  ITEM_CAP,
  MIN_STALE_WINDOW_S,
  progressRel,
  checklistFor,
  fmtEta,
  itemLine,
};
