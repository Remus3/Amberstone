// rc-shell/src/backend_update.js
//
// PKG-6b (docs/PACKAGING_PLAN.md section 3.4, residual WA11): the shell side
// of a BACKEND update. NO electron import - the testable core; main.js only
// applies what these return.
//
// The shell runs ONE windowless child per update cycle, the backend's own
//     <python> -I <root>/ops/launcher/update_cycle.py --root <root> run
//              --source <src> --channel <stable|dev> [--shell-version <v>]
//              --parent-pid <electron pid>
// (check -> stage -> apply -> finish -> verify -> recover, all in Python,
// tested under pytest with the real deploy worker), reads its ONE JSON line,
// and then owes the restarts it names:
//   - host_services  -> one JSON line to the service host's stdin:
//                       {"cmd": "restart", "id": ..., "services": [...]}
//   - respawn_host   -> stop the host and spawn it again (its own code or
//                       the dependency set changed: every service restarts)
//   - relaunch_shell -> rc-shell code; electron-updater owns that path.
// Restarts wait until the last fresh /api/state said no game is live, the
// same gate the shell-update relaunch uses (launcher.relaunchDecision).
// A cycle only runs when that gate is open AND the host OWNS the services
// (attach mode = the pre-cutover tasks own them; nothing to update here).
//
// Source: RC_BACKEND_UPDATE_SOURCE = github | github:<owner>/<repo> |
// local:<absolute folder> (the operator's local channel); default github
// (the repo's own Releases, the same feed as the shell; none is published
// yet - PACKAGING_PLAN section 6). A packaged launch checks on the shell's
// cadence; a checkout launch only with RC_BACKEND_UPDATES=1 (a linked
// checkout updates through git + hot_reload, and the cycle refuses it).

"use strict";

const path = require("path");

const CYCLE_SCRIPT = Object.freeze(["ops", "launcher", "update_cycle.py"]);
const SOURCE_ENV = "RC_BACKEND_UPDATE_SOURCE";
const ENABLE_ENV = "RC_BACKEND_UPDATES";
const DEFAULT_SOURCE = "github";
const CHANNELS = Object.freeze(["stable", "dev"]);
// The cycle bounds its own waits (finish 300 s + verify 180 s + settle +
// stable windows); this is the shell's outer guard, and it never fires while
// the cycle's own phase says deploying or recovering (watchdogDecision).
const CYCLE_TIMEOUT_MS = 60 * 60 * 1000;
const PROTECTED_PHASES = Object.freeze(["deploying", "recovering"]);
// Resume (fix round F1): what an earlier cycle left is picked up at launch
// and on this interval while a record exists - even with main.py down.
const RESUME_DELAY_MS = 30000;
const RESUME_INTERVAL_MS = 60000;
// F2: while a deploy_requests/*.deploying exists the quit waits this long for
// the host (the host's own deploy grace is 150 s), never forever.
const DEPLOY_STOP_GRACE_MS = 165000;
// F5: the restart / update gate. Idle only in these LCU gameflow phases (or
// with no LCU phase at all) and with no live game signal in /api/state.
const IDLE_PHASES = Object.freeze(["", "None", "Lobby"]);
const LIVE_GAME_FLAGS = Object.freeze(["has_game", "aram_mode", "arena_mode", "tft_mode", "brawl_mode"]);
const MAX_OUTPUT_BYTES = 1024 * 1024;
const CHECK_DEFAULTS = Object.freeze({
  initialDelayMs: 120000, // let the services settle before the first check
  intervalMs: 14400000, // 4 hours, the shell-update cadence
});
// A deferred / pending / interrupted / busy cycle is tried again this soon
// (still through the idle gate), not after the full interval.
const RETRY_DELAY_MS = 10 * 60 * 1000;
const MAX_HOST_SERVICES = 16; // ops/launcher/service_host.py MAX_COMMAND_SERVICES
// ops/launcher/service_host.py _NAME_RE (and the shell status reader's).
const NAME_RE = /^[a-z][a-z0-9_]{0,63}$/;
const ID_RE = /^[A-Za-z0-9_.:-]{1,64}$/;
const SLUG_RE = /^[A-Za-z0-9_.-]{1,100}$/;
const VERSION_RE = /^[0-9A-Za-z.+-]{1,64}$/;
const STATUSES = Object.freeze([
  "up-to-date", "noop", "applied", "pending", "interrupted", "busy", "owed", "skipped", "idle",
  "deferred", "refused", "failed", "lost", "recovered", "error",
]);
// Results that carry restarts to perform: a verified deploy, restarts still
// owed, and a recover (the old code must be loaded again).
const ACTION_STATUSES = Object.freeze(["applied", "owed", "recovered"]);

function isAbsLocal(p) {
  return typeof p === "string" && p.trim() !== "" && path.isAbsolute(p.trim());
}

function ascii(s, max) {
  const t = typeof s === "string" ? s.replace(/[^\x20-\x7e]+/g, " ").trim() : "";
  return t.slice(0, max || 200);
}

// {source, origin: "env" | "default", rejected: [reason]}.
function resolveSource(env) {
  const e = env && typeof env === "object" ? env : {};
  const raw = typeof e[SOURCE_ENV] === "string" ? e[SOURCE_ENV].trim() : "";
  if (!raw) {
    return { source: DEFAULT_SOURCE, origin: "default", rejected: [] };
  }
  if (raw === "github") {
    return { source: raw, origin: "env", rejected: [] };
  }
  if (raw.startsWith("github:")) {
    const parts = raw.slice("github:".length).split("/");
    if (parts.length === 2 && SLUG_RE.test(parts[0]) && SLUG_RE.test(parts[1])) {
      return { source: raw, origin: "env", rejected: [] };
    }
    return { source: DEFAULT_SOURCE, origin: "default", rejected: ["bad-github-slug"] };
  }
  if (raw.startsWith("local:")) {
    const dir = raw.slice("local:".length);
    if (isAbsLocal(dir)) {
      return { source: "local:" + path.resolve(dir.trim()), origin: "env", rejected: [] };
    }
    return { source: DEFAULT_SOURCE, origin: "default", rejected: ["local-not-absolute"] };
  }
  return { source: DEFAULT_SOURCE, origin: "default", rejected: ["unknown-source"] };
}

// Is a backend cycle allowed on this launch at all? A packaged launch: yes;
// a checkout launch: only when RC_BACKEND_UPDATES=1.
function cyclesEnabled(opts) {
  const o = opts && typeof opts === "object" ? opts : {};
  if (o.isPackaged === true) {
    return { enabled: true, reason: "packaged" };
  }
  const env = o.env && typeof o.env === "object" ? o.env : {};
  const v = typeof env[ENABLE_ENV] === "string" ? env[ENABLE_ENV].trim().toLowerCase() : "";
  if (v === "1" || v === "true" || v === "yes") {
    return { enabled: true, reason: "env" };
  }
  return { enabled: false, reason: "checkout-launch" };
}

// The cycle spawn, or {enabled: false, reason}. opts: root, python (the
// host's interpreter), hostOwned, channel, shellVersion, parentPid, env,
// isPackaged, probe (path -> "file" | null), mode ("run" default | "resume"),
// restartsSent (resume only). A resume needs no owned host: it is how a
// failed host respawn gets recovered.
function cyclePlan(opts) {
  const o = opts && typeof opts === "object" ? opts : {};
  const mode = o.mode === undefined ? "run" : o.mode;
  if (mode !== "run" && mode !== "resume") {
    return { enabled: false, reason: "bad-mode" };
  }
  const gate = cyclesEnabled(o);
  if (!gate.enabled) {
    return { enabled: false, reason: gate.reason };
  }
  if (!isAbsLocal(o.root)) {
    return { enabled: false, reason: "no-root" };
  }
  if (!isAbsLocal(o.python)) {
    return { enabled: false, reason: "no-interpreter" };
  }
  if (mode === "run" && o.hostOwned !== true) {
    return { enabled: false, reason: "host-not-owning" };
  }
  const root = path.resolve(o.root.trim());
  const script = path.join(root, ...CYCLE_SCRIPT);
  const probe = typeof o.probe === "function" ? o.probe : () => null;
  if (probe(script) !== "file") {
    return { enabled: false, reason: "no-cycle-script" };
  }
  const src = resolveSource(o.env);
  const channel = CHANNELS.includes(o.channel) ? o.channel : "stable";
  const args = mode === "run"
    ? ["-I", script, "--root", root, "run", "--source", src.source, "--channel", channel]
    : ["-I", script, "--root", root, "resume"];
  if (mode === "resume" && o.restartsSent === true) {
    args.push("--restarts-sent");
  }
  if (mode === "run" && typeof o.shellVersion === "string" && VERSION_RE.test(o.shellVersion)) {
    args.push("--shell-version", o.shellVersion);
  }
  if (Number.isInteger(o.parentPid) && o.parentPid > 0) {
    args.push("--parent-pid", String(o.parentPid));
  }
  return {
    enabled: true,
    reason: "ok",
    mode,
    command: path.resolve(o.python.trim()),
    args,
    cwd: root,
    source: src.source,
    sourceOrigin: src.origin,
    rejected: src.rejected,
    timeoutMs: CYCLE_TIMEOUT_MS,
  };
}

// F5: is this /api/state answer an idle moment for an update or a service
// restart? Stricter than the overlay's liveGameFromState: champ select,
// ready check, queue, loading and the post-game screens all count as busy.
function idleForUpdate(state) {
  if (!state || typeof state !== "object" || Array.isArray(state)) {
    return false;
  }
  const lc = state.liveclient;
  if (lc && typeof lc === "object" && !Array.isArray(lc) && Object.keys(lc).length > 0) {
    return false;
  }
  for (const flag of LIVE_GAME_FLAGS) {
    if (state[flag] === true) {
      return false;
    }
  }
  const lcu = state.lcu && typeof state.lcu === "object" && !Array.isArray(state.lcu) ? state.lcu : {};
  const phase = lcu.phase === undefined || lcu.phase === null ? "" : String(lcu.phase);
  return IDLE_PHASES.includes(phase);
}

function parseJsonObject(text) {
  try {
    const d = typeof text === "string" && text ? JSON.parse(text) : null;
    return d && typeof d === "object" && !Array.isArray(d) ? d : null;
  } catch (_e) {
    return null;
  }
}

// F1: what an earlier cycle left on disk - update_cycle.json (verify, owed,
// phase) and the updater's update_state.json (pending, recovering).
function recordsFrom(cycleText, stateText) {
  const c = parseJsonObject(cycleText) || {};
  const st = parseJsonObject(stateText) || {};
  const isObj = (v) => !!v && typeof v === "object" && !Array.isArray(v);
  return {
    verify: isObj(c.verify),
    owed: isObj(c.owed),
    pending: isObj(st.pending),
    recovering: isObj(st.recovering),
    phase: typeof c.phase === "string" ? ascii(c.phase, 32) : null,
  };
}

// F1: run `resume` now? A verify / pending / recovering record resumes every
// RESUME_INTERVAL_MS with NO /api/state requirement (main.py may be down);
// an owed record only once per launch (the shell then owns the restarts).
function resumeDue(opts) {
  const o = opts && typeof opts === "object" ? opts : {};
  const r = o.records && typeof o.records === "object" ? o.records : {};
  if (o.inFlight === true) {
    return { run: false, reason: "in-flight" };
  }
  const urgent = r.verify === true || r.pending === true || r.recovering === true;
  const first = typeof o.lastResumeMs !== "number" || !Number.isFinite(o.lastResumeMs);
  if (urgent) {
    if (first || o.nowMs - o.lastResumeMs >= RESUME_INTERVAL_MS) {
      return { run: true, reason: "record" };
    }
    return { run: false, reason: "not-due" };
  }
  if (r.owed === true) {
    return first ? { run: true, reason: "owed-at-launch" } : { run: false, reason: "owed-known" };
  }
  return { run: false, reason: "nothing-recorded" };
}

// F2: the quit's wait for the host (base = launcher.HOST_STOP_GRACE_MS).
function hostStopGraceMs(baseMs, inFlight) {
  return inFlight === true ? DEPLOY_STOP_GRACE_MS : baseMs;
}

function deployInFlight(names) {
  return Array.isArray(names) && names.some((n) => typeof n === "string" && n.endsWith(".deploying"));
}

// F6: the outer guard. "kill" only past CYCLE_TIMEOUT_MS and never while the
// cycle reports a protected phase (its recover is re-entrant anyway).
function watchdogDecision(opts) {
  const o = opts && typeof opts === "object" ? opts : {};
  if (typeof o.elapsedMs !== "number" || o.elapsedMs < CYCLE_TIMEOUT_MS) {
    return "wait";
  }
  return PROTECTED_PHASES.includes(o.phase) ? "wait" : "kill";
}

// Run a cycle now? opts: nowMs, lastRunMs, intervalMs, manual, inFlight,
// inGame, stateFresh. Never during a game, never on a stale state, one at a
// time; a manual check skips only the interval.
function cycleDue(opts) {
  const o = opts && typeof opts === "object" ? opts : {};
  if (o.inFlight === true) {
    return { run: false, reason: "in-flight" };
  }
  if (o.stateFresh !== true) {
    return { run: false, reason: "state-unknown" };
  }
  if (o.inGame !== false) {
    return { run: false, reason: "game-live" };
  }
  if (o.manual === true) {
    return { run: true, reason: "manual" };
  }
  if (typeof o.lastRunMs !== "number" || !Number.isFinite(o.lastRunMs)) {
    return { run: true, reason: "first" };
  }
  const interval =
    typeof o.intervalMs === "number" && o.intervalMs > 0 ? o.intervalMs : CHECK_DEFAULTS.intervalMs;
  return o.nowMs - o.lastRunMs >= interval ? { run: true, reason: "due" } : { run: false, reason: "not-due" };
}

// The lastRunMs to record for a cycle that started at startedMs: a result
// to retry makes the next cycle due RETRY_DELAY_MS later instead.
function lastRunAfter(result, startedMs, intervalMs) {
  const interval = typeof intervalMs === "number" && intervalMs > 0 ? intervalMs : CHECK_DEFAULTS.intervalMs;
  const r = result && typeof result === "object" ? result : {};
  return r.retryLater === true ? startedMs - interval + Math.min(RETRY_DELAY_MS, interval) : startedMs;
}

function emptyOwed() {
  return { hostServices: [], respawnHost: false, relaunchShell: false };
}

function normActions(raw) {
  const r = raw && typeof raw === "object" && !Array.isArray(raw) ? raw : {};
  const names = Array.isArray(r.host_services) ? r.host_services : [];
  const host = [];
  for (const n of names) {
    if (typeof n === "string" && NAME_RE.test(n) && !host.includes(n) && host.length < MAX_HOST_SERVICES) {
      host.push(n);
    }
  }
  const respawn = r.respawn_host === true;
  return { hostServices: respawn ? [] : host.sort(), respawnHost: respawn, relaunchShell: r.relaunch_shell === true };
}

// The cycle's stdout + exit code -> a result. Never throws. The LAST
// non-empty line is the JSON document; exit 3 is a live-game deferral.
function parseCycleOutput(stdout, exitCode) {
  const text = typeof stdout === "string" ? stdout.slice(-MAX_OUTPUT_BYTES) : "";
  const lines = text.split(/\r?\n/).filter((l) => l.trim());
  let doc = null;
  try {
    doc = lines.length ? JSON.parse(lines[lines.length - 1]) : null;
  } catch (_e) {
    doc = null;
  }
  if (!doc || typeof doc !== "object" || Array.isArray(doc) || !STATUSES.includes(doc.status)) {
    return {
      status: "error",
      ok: false,
      code: "bad-output",
      version: null,
      detail: "the update cycle printed no result (exit " + String(exitCode) + ")",
      actions: emptyOwed(),
      retryLater: false,
    };
  }
  const deferred = exitCode === 3 || doc.status === "deferred";
  const status = deferred ? "deferred" : doc.status;
  const applied = ACTION_STATUSES.includes(status);
  return {
    status,
    ok: exitCode === 0 && doc.ok === true,
    code: typeof doc.code === "string" ? ascii(doc.code, 40) : null,
    version: typeof doc.version === "string" && VERSION_RE.test(doc.version) ? doc.version : null,
    detail: ascii(doc.detail, 200),
    // Restarts: a verified deploy, restarts still owed, or a recover.
    actions: applied ? normActions(doc.restart) : emptyOwed(),
    retryLater: deferred || status === "pending" || status === "interrupted" || status === "busy",
  };
}

// Fold new actions into what is already owed (restarts accumulate until
// the idle gate opens; a host respawn covers every service).
function mergeOwed(owed, actions) {
  const a = owed && typeof owed === "object" ? owed : emptyOwed();
  const b = actions && typeof actions === "object" ? actions : emptyOwed();
  const respawn = a.respawnHost === true || b.respawnHost === true;
  const names = respawn ? [] : Array.from(new Set([].concat(a.hostServices || [], b.hostServices || []))).sort();
  return {
    hostServices: names.slice(0, MAX_HOST_SERVICES),
    respawnHost: respawn,
    relaunchShell: a.relaunchShell === true || b.relaunchShell === true,
  };
}

function owesHostWork(owed) {
  return !!owed && (owed.respawnHost === true || (Array.isArray(owed.hostServices) && owed.hostServices.length > 0));
}

// What to do with the owed restarts now. opts: owed, inGame, stateFresh,
// hostRunning. act: "none" | "wait" | "respawn-host" | "restart-services".
function owedDecision(opts) {
  const o = opts && typeof opts === "object" ? opts : {};
  if (!owesHostWork(o.owed)) {
    return { act: "none", reason: "nothing-owed" };
  }
  if (o.hostRunning !== true) {
    return { act: "wait", reason: "no-host" };
  }
  if (o.stateFresh !== true) {
    return { act: "wait", reason: "state-unknown" };
  }
  if (o.inGame !== false) {
    return { act: "wait", reason: "game-live" };
  }
  return o.owed.respawnHost === true
    ? { act: "respawn-host", reason: "idle" }
    : { act: "restart-services", reason: "idle" };
}

// The host's stdin command line (ASCII JSON + LF), or null when invalid.
function restartCommandLine(services, id) {
  const names = Array.isArray(services) ? services.filter((n) => typeof n === "string" && NAME_RE.test(n)) : [];
  if (!names.length || names.length > MAX_HOST_SERVICES || typeof id !== "string" || !ID_RE.test(id)) {
    return null;
  }
  return JSON.stringify({ cmd: "restart", id, services: Array.from(new Set(names)) }) + "\n";
}

// One console line for a cycle result (ASCII, no raw error text beyond the
// cycle's own sanitised detail).
function logLine(result) {
  const r = result && typeof result === "object" ? result : {};
  const bits = ["backend update: " + ascii(r.status, 20)];
  if (r.version) {
    bits.push("version " + r.version);
  }
  if (r.code) {
    bits.push("code " + r.code);
  }
  if (r.detail) {
    bits.push(r.detail);
  }
  return ascii(bits.join(" - "), 300);
}

module.exports = {
  CYCLE_SCRIPT,
  SOURCE_ENV,
  ENABLE_ENV,
  DEFAULT_SOURCE,
  CYCLE_TIMEOUT_MS,
  RESUME_DELAY_MS,
  RESUME_INTERVAL_MS,
  DEPLOY_STOP_GRACE_MS,
  IDLE_PHASES,
  MAX_OUTPUT_BYTES,
  CHECK_DEFAULTS,
  RETRY_DELAY_MS,
  MAX_HOST_SERVICES,
  STATUSES,
  resolveSource,
  cyclesEnabled,
  cyclePlan,
  idleForUpdate,
  recordsFrom,
  resumeDue,
  hostStopGraceMs,
  deployInFlight,
  watchdogDecision,
  cycleDue,
  lastRunAfter,
  emptyOwed,
  parseCycleOutput,
  mergeOwed,
  owesHostWork,
  owedDecision,
  restartCommandLine,
  logLine,
};
