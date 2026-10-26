// rc-shell/src/service_status.js
//
// Launcher status parsing + the shell's view decision. NO electron import -
// the testable core behind docs/PACKAGING_PLAN.md section 3.1 "Status
// surface" (slice PKG-3; PKG-1 writes the file, PKG-6 wires this in).
//
// The service host writes <root>/ops/runtime/launcher_status.json atomically
// (rc_root.runtimeFile(root, STATUS_FILE_NAME)). The shape this module reads -
// the contract PKG-1 writes to:
//
//   {
//     "schema": 1,                       optional; any other value is refused
//     "updated": 1800000000.5,           epoch seconds, epoch ms, or ISO-8601;
//                                        rewritten at least every 10 s while
//                                        the host lives (heartbeat)
//     "mode": "owned" | "attach",        attach = a healthy supervisor already
//                                        held :8888, the host started nothing
//     "host_pid": 4242,
//     "origin": "http://127.0.0.1:8888", the origin the dashboard actually
//                                        serves; the shell passes it to
//                                        config.resolveConfig as servedOrigin,
//                                        which VALIDATES it (never trusted here)
//     "services": {                      or a list of {"name": ..., ...}
//       "<name>": {"state": "<kit state>", "pid": 1, "port": 8888,
//                  "restarts": 0, "last_error": "..."}
//     }
//   }
//
// Service states use the fleet kit vocabulary (ops/fleet_kit/tokens.json
// "states", mirrored in KIT_STATES and pinned by a test). An unknown state
// word reads as "pending" with unknownState: true - it never claims running
// and never escalates to an error by itself.
//
// The view decision (shellView): the plan's rule is "a starting view until
// /api/health answers, then the normal surfaces", so health decides "app";
// the status file only decides between "starting" and "error" before that,
// and names failing services for a degraded banner after it. A stale file, a
// file from another host process, or no file at all is "no information":
// starting, until the start timeout turns it into an error.
//
// Everything a page could later render (names, errors) is bounded and
// reduced to printable ASCII here, and a hostile file cannot grow the result.

"use strict";

const fs = require("fs");

const STATUS_FILE_NAME = "launcher_status.json";
const SCHEMA_VERSION = 1;

const MAX_STATUS_BYTES = 64 * 1024;
const MAX_SERVICES = 32;
const MAX_ERROR_CHARS = 240;
const MAX_ORIGIN_CHARS = 256;
const MAX_PID = 0xffffffff;
const MAX_RESTARTS = 1e9;

// The host rewrites the file at least every 10 s; three missed beats = stale.
const DEFAULT_STALE_AFTER_MS = 30 * 1000;
// Tolerated clock skew for an "updated" stamp in the future.
const FUTURE_SKEW_MS = 60 * 1000;
// Before /api/health answers: how long "no information" stays "starting".
const START_TIMEOUT_MS = 90 * 1000;

const NAME_RE = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/;

function kitState(glyph, row, word, token) {
  return Object.freeze({ glyph, row, word, token });
}

// Mirror of ops/fleet_kit/tokens.json "states" (kit v20). The packaged shell
// cannot read the kit (dev-only tree), so it is embedded; a test pins it.
const KIT_STATES = Object.freeze({
  running: kitState(">", "[>]", "running", "running"),
  done: kitState("+", "[+]", "done", "ok"),
  failed: kitState("x", "[x]", "failed", "bad"),
  stale: kitState("!", "[!]", "STALE", "bad"),
  halted: kitState("=", "[=]", "halted", "halted"),
  pending: kitState(".", "[ ]", "pending", "idle"),
  "needs-operator": kitState("?", "[?]", "needs you", "warn"),
  blocked: kitState("#", "[#]", "blocked", "warn"),
  fallback: kitState("~", "[~]", "fallback", "warn"),
  idle: kitState("-", "[-]", "idle", "idle"),
});

// Worst first. The overall state of a document is its worst service state.
const SEVERITY_ORDER = Object.freeze([
  "failed",
  "stale",
  "blocked",
  "needs-operator",
  "halted",
  "pending",
  "fallback",
  "running",
  "done",
  "idle",
]);

// Services in these states are named in the failing list (degraded banner).
const FAILING_STATES = Object.freeze(["failed", "stale", "blocked", "needs-operator"]);
// Before health answers, an overall state in this set shows the error view.
const ERROR_VIEW_STATES = Object.freeze(["failed", "blocked", "needs-operator"]);

function finiteNum(v) {
  return typeof v === "number" && Number.isFinite(v);
}

function intIn(v, lo, hi) {
  return Number.isInteger(v) && v >= lo && v <= hi ? v : null;
}

// epoch seconds | epoch ms | ISO-8601 -> epoch ms, or null.
function toMs(v) {
  if (finiteNum(v) && v > 0) {
    return v < 1e12 ? v * 1000 : v;
  }
  if (typeof v === "string" && v.trim()) {
    const t = Date.parse(v.trim());
    return Number.isFinite(t) ? t : null;
  }
  return null;
}

// One-line printable ASCII, whitespace collapsed, capped.
function cleanError(v) {
  if (typeof v !== "string") {
    return "";
  }
  return v
    .replace(/[^\x20-\x7e]/g, " ")
    .replace(/ {2,}/g, " ")
    .trim()
    .slice(0, MAX_ERROR_CHARS);
}

function normService(name, s) {
  const raw = typeof s.state === "string" ? s.state.trim().toLowerCase() : "";
  const known = Object.prototype.hasOwnProperty.call(KIT_STATES, raw);
  return {
    name,
    state: known ? raw : "pending",
    unknownState: !known,
    pid: intIn(s.pid, 1, MAX_PID),
    port: intIn(s.port, 1, 65535),
    restarts: intIn(s.restarts ?? s.restart_count, 0, MAX_RESTARTS) ?? 0,
    lastError: cleanError(s.last_error ?? s.error),
  };
}

function aggregate(services, mode, stale) {
  if (stale) {
    return "stale";
  }
  if (services.length === 0) {
    return mode === "attach" ? "idle" : "pending";
  }
  let worst = SEVERITY_ORDER.length;
  for (const s of services) {
    const i = SEVERITY_ORDER.indexOf(s.state);
    if (i !== -1 && i < worst) {
      worst = i;
    }
  }
  return SEVERITY_ORDER[worst] || "pending";
}

function notOk(reason) {
  return {
    ok: false,
    reason,
    updatedMs: null,
    ageMs: null,
    stale: true,
    mode: null,
    hostPid: null,
    origin: null,
    services: [],
    truncated: false,
    overall: null,
  };
}

// Parse the status file text. opts: {now (ms), staleAfterMs}. Never throws.
// reason: "ok", "empty", "too-large", "malformed", "not-an-object",
// "unsupported-schema".
function parseStatus(text, opts) {
  const o = opts && typeof opts === "object" ? opts : {};
  const now = finiteNum(o.now) ? o.now : Date.now();
  const staleAfter =
    finiteNum(o.staleAfterMs) && o.staleAfterMs > 0 ? o.staleAfterMs : DEFAULT_STALE_AFTER_MS;

  if (typeof text !== "string" || !text.trim()) {
    return notOk("empty");
  }
  if (text.length > MAX_STATUS_BYTES) {
    return notOk("too-large");
  }
  let doc;
  try {
    doc = JSON.parse(text);
  } catch (_e) {
    return notOk("malformed");
  }
  if (!doc || typeof doc !== "object" || Array.isArray(doc)) {
    return notOk("not-an-object");
  }
  if (doc.schema !== undefined && doc.schema !== SCHEMA_VERSION) {
    return notOk("unsupported-schema");
  }

  const updatedMs = toMs(doc.updated);
  const ageMs = updatedMs === null ? null : now - updatedMs;
  const stale = ageMs === null || ageMs > staleAfter || ageMs < -FUTURE_SKEW_MS;
  const mode = doc.mode === "owned" || doc.mode === "attach" ? doc.mode : null;
  const hostPid = intIn(doc.host_pid, 1, MAX_PID);
  let origin = null;
  if (typeof doc.origin === "string") {
    const t = doc.origin.trim();
    origin = t && t.length <= MAX_ORIGIN_CHARS ? t : null;
  }

  const entries = [];
  const isObj = (v) => v && typeof v === "object" && !Array.isArray(v);
  if (Array.isArray(doc.services)) {
    for (const s of doc.services) {
      if (isObj(s)) {
        entries.push([s.name, s]);
      }
    }
  } else if (isObj(doc.services)) {
    for (const [k, v] of Object.entries(doc.services)) {
      if (isObj(v)) {
        entries.push([k, v]);
      }
    }
  }
  const services = [];
  const seen = new Set();
  let truncated = false;
  for (const [name, s] of entries) {
    if (typeof name !== "string" || !NAME_RE.test(name) || seen.has(name)) {
      continue;
    }
    if (services.length >= MAX_SERVICES) {
      truncated = true;
      break;
    }
    seen.add(name);
    services.push(normService(name, s));
  }

  return {
    ok: true,
    reason: "ok",
    updatedMs,
    ageMs,
    stale,
    mode,
    hostPid,
    origin,
    services,
    truncated,
    overall: aggregate(services, mode, stale),
  };
}

// Read + parse. opts: {readFile ((path) -> string, may throw), now,
// staleAfterMs}. An unreadable / missing file is {ok: false, reason: "absent"}.
function readStatus(filePath, opts) {
  const o = opts && typeof opts === "object" ? opts : {};
  if (typeof filePath !== "string" || !filePath) {
    return notOk("absent");
  }
  const read = typeof o.readFile === "function" ? o.readFile : (p) => fs.readFileSync(p, "utf8");
  let text;
  try {
    text = read(filePath);
  } catch (_e) {
    return notOk("absent");
  }
  return parseStatus(text, o);
}

// The shell's view. opts:
//   status         a parseStatus / readStatus result
//   healthOk       true once GET /api/health answered on the resolved origin
//   sinceLaunchMs  ms since the shell spawned the host
//   hostPid        the pid of the host this shell spawned (optional; a file
//                  naming another pid is a leftover and is ignored)
//   startTimeoutMs override of START_TIMEOUT_MS
// Returns {view: "app" | "starting" | "error", reason, degraded, failing}.
function shellView(opts) {
  const o = opts && typeof opts === "object" ? opts : {};
  const st = o.status && typeof o.status === "object" ? o.status : null;
  const wantPid = intIn(o.hostPid, 1, MAX_PID);
  const usable =
    !!st &&
    st.ok === true &&
    st.stale === false &&
    Array.isArray(st.services) &&
    (wantPid === null || st.hostPid === wantPid);
  const failing = usable
    ? st.services.filter((s) => s && FAILING_STATES.includes(s.state)).map((s) => s.name)
    : [];

  if (o.healthOk === true) {
    return { view: "app", reason: "health-ok", degraded: failing.length > 0, failing };
  }
  if (usable && ERROR_VIEW_STATES.includes(st.overall)) {
    return { view: "error", reason: "service-" + st.overall, degraded: true, failing };
  }
  const timeout =
    finiteNum(o.startTimeoutMs) && o.startTimeoutMs > 0 ? o.startTimeoutMs : START_TIMEOUT_MS;
  if (finiteNum(o.sinceLaunchMs) && o.sinceLaunchMs > timeout) {
    return { view: "error", reason: "start-timeout", degraded: true, failing };
  }
  return {
    view: "starting",
    reason: usable ? "starting" : "no-status",
    degraded: failing.length > 0,
    failing,
  };
}

// One kit-vocabulary row per parsed service, for the starting / error view.
function describe(status) {
  if (!status || typeof status !== "object" || !Array.isArray(status.services)) {
    return [];
  }
  return status.services
    .filter((s) => s && Object.prototype.hasOwnProperty.call(KIT_STATES, s.state))
    .map((s) => ({
      name: s.name,
      state: s.state,
      row: KIT_STATES[s.state].row,
      word: KIT_STATES[s.state].word,
      token: KIT_STATES[s.state].token,
    }));
}

module.exports = {
  STATUS_FILE_NAME,
  SCHEMA_VERSION,
  MAX_STATUS_BYTES,
  MAX_SERVICES,
  MAX_ERROR_CHARS,
  DEFAULT_STALE_AFTER_MS,
  START_TIMEOUT_MS,
  KIT_STATES,
  SEVERITY_ORDER,
  FAILING_STATES,
  ERROR_VIEW_STATES,
  parseStatus,
  readStatus,
  shellView,
  describe,
};
