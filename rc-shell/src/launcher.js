// rc-shell/src/launcher.js
//
// The shell-as-launcher decisions. NO electron import - the testable core
// behind PACKAGING_PLAN slice PKG-6 (docs/PACKAGING_PLAN.md sections 3.1 -
// 3.6); main.js only applies what these return.
//
// What the launcher does (main.js):
//   - at launch, spawn ONE windowless child, the PKG-1 service host:
//       <python> -I <root>/ops/launcher/service_host.py --root <root>
//                --profile <packaged|dev> --parent-pid <electron pid>
//     which owns every RC service inside one Windows job object;
//   - show a local starting view until GET <origin>/api/health answers;
//   - on quit, write "stop" to the host's stdin, wait a bounded grace, then
//     end the host (its job object takes every service with it).
// Nothing here starts anything at login or boot (PACKAGING_PLAN intent 3).
//
// Backend root: rc_root.resolveRcRoot (argv --rc-root, env RC_ROOT, the
// packaged resources/backend, the dev checkout). Interpreter precedence:
//   1. RC_PYTHON           an absolute path to an existing interpreter
//   2. embedded            <root>/python-embed/python.exe (PKG-4 bundle)
//   3. canonical (dev)     %LOCALAPPDATA%/Programs/Python/Python314/python.exe,
//                          ONLY for a checkout launch (isPackaged false): a
//                          packaged build never falls back to whatever
//                          interpreter the machine happens to have.
// Profile: --profile=<p> > RC_LAUNCHER_PROFILE > packaged when packaged, dev
// for a checkout launch (dev keeps the wildcard :8888 bind the tailnet view
// needs, PACKAGING_PLAN V3). Opt-out: --no-host or RC_SHELL_NO_HOST=1 - the
// shell then behaves exactly as before PKG-6 (it loads the origin and
// starts nothing).
//
// A CHECKOUT launch (npm start, rc-shell/launch_overlay.bat) starts the host
// only when a profile is NAMED (--profile dev, or RC_LAUNCHER_PROFILE): before
// the section-5 cutover the RC-* scheduled tasks own the agents, and while
// the host's probe attaches to a healthy supervisor (PACKAGING_PLAN 3.3), a
// host that found the supervisor down would start second copies of the
// task-run LCU agent / relay / hotkey listener. After the cutover Legion
// launches the shell with --profile dev. A packaged launch always starts it.

"use strict";

const path = require("path");
const fs = require("fs");
const nav = require("./nav_guard");
const svc = require("./service_status");

const PROFILES = Object.freeze(["packaged", "dev"]);
const PROFILE_ARG = "--profile";
const PROFILE_ENV = "RC_LAUNCHER_PROFILE";
const NO_HOST_ARG = "--no-host";
const NO_HOST_ENV = "RC_SHELL_NO_HOST";
const PYTHON_ENV = "RC_PYTHON";

const HOST_SCRIPT = Object.freeze(["ops", "launcher", "service_host.py"]);
const EMBED_PYTHON = Object.freeze(["python-embed", "python.exe"]);
// Under %LOCALAPPDATA%: the canonical dev interpreter (CLAUDE.md "Paths").
const DEV_PYTHON = Object.freeze(["Programs", "Python", "Python314", "python.exe"]);
// electron-builder.yml extraResources `to:` - resources/<this>.
const BUNDLED_BACKEND_DIR = "backend";
// The per-install dashboard token (ops/launcher/first_run.py DASH_TOKEN_REL).
const DASH_TOKEN_FILE = Object.freeze(["ops", "runtime", "dash_token.txt"]);
const TOKEN_HEADER = "X-RC-Token";
const MAX_TOKEN_CHARS = 512;
const MAX_TOKEN_FILE_BYTES = 4096;

// services.json stop_grace_s (15 s) plus the host's own teardown margin.
const HOST_STOP_GRACE_MS = 25 * 1000;
// A per-install secret (pin file, token file) is re-read at most this often.
const SECRET_REFRESH_MS = 5 * 1000;
// The starting view appears only when the start takes longer than this, so a
// healthy attach-mode launch never flashes it.
const STARTING_SHOW_DELAY_MS = 1500;
const BOOT_TICK_MS = 1000;
const HEALTH_TIMEOUT_MS = 1500;
const MAX_HEALTH_BYTES = 1 << 20;

// The pre-PKG-6 userData folder name (package.json "name") and its state file.
const LEGACY_USERDATA_DIR = "rc-shell";
const STATE_FILE = "rc-shell-state.json";

function defaultProbe(p) {
  if (typeof p !== "string" || !p) {
    return null;
  }
  try {
    const st = fs.statSync(p);
    return st.isFile() ? "file" : st.isDirectory() ? "dir" : null;
  } catch (_e) {
    return null;
  }
}

function probeOf(probe) {
  const pr = typeof probe === "function" ? probe : defaultProbe;
  return (p) => {
    try {
      return pr(p);
    } catch (_e) {
      return null;
    }
  };
}

function isAbsLocal(p) {
  return typeof p === "string" && p.trim() !== "" && !/^[\\/]{2}/.test(p.trim()) && path.isAbsolute(p.trim());
}

// The last value of a --name=<v> / --name <v> flag in argv, or null.
function argValue(argv, name) {
  if (!Array.isArray(argv)) {
    return null;
  }
  let found = null;
  for (let i = 0; i < argv.length; i += 1) {
    const tok = argv[i];
    if (typeof tok !== "string") {
      continue;
    }
    if (tok === name) {
      const next = argv[i + 1];
      found = typeof next === "string" && next.trim() && !next.startsWith("--") ? next.trim() : null;
      if (found !== null) {
        i += 1;
      }
    } else if (tok.startsWith(name + "=")) {
      found = tok.slice(name.length + 1).trim() || null;
    }
  }
  return found;
}

function truthyEnv(v) {
  return typeof v === "string" && /^(1|true|yes|on)$/i.test(v.trim());
}

// "argv" | "env" when the operator turned the host off, else null.
function hostDisabled(opts) {
  const o = opts && typeof opts === "object" ? opts : {};
  if (Array.isArray(o.argv) && o.argv.includes(NO_HOST_ARG)) {
    return "argv";
  }
  const env = o.env && typeof o.env === "object" ? o.env : {};
  return truthyEnv(env[NO_HOST_ENV]) ? "env" : null;
}

// {profile, source, rejected}. Default: packaged unless isPackaged === false.
function resolveProfile(opts) {
  const o = opts && typeof opts === "object" ? opts : {};
  const env = o.env && typeof o.env === "object" ? o.env : {};
  const rejected = [];
  const candidates = [];
  const a = argValue(o.argv, PROFILE_ARG);
  if (a !== null) {
    candidates.push({ source: "argv", value: a });
  }
  if (typeof env[PROFILE_ENV] === "string" && env[PROFILE_ENV].trim()) {
    candidates.push({ source: "env", value: env[PROFILE_ENV].trim() });
  }
  for (const c of candidates) {
    if (PROFILES.includes(c.value)) {
      return { profile: c.value, source: c.source, rejected };
    }
    rejected.push({ source: c.source, reason: "unknown-profile" });
  }
  return { profile: o.isPackaged === false ? "dev" : "packaged", source: "default", rejected };
}

// {python, source, reason, rejected}: source "env" | "embedded" | "canonical".
function resolvePython(opts) {
  const o = opts && typeof opts === "object" ? opts : {};
  const env = o.env && typeof o.env === "object" ? o.env : {};
  const probe = probeOf(o.probe);
  const rejected = [];
  const override = typeof env[PYTHON_ENV] === "string" ? env[PYTHON_ENV].trim() : "";
  if (override) {
    if (!isAbsLocal(override)) {
      rejected.push({ source: "env", reason: "not-absolute" });
    } else if (probe(path.resolve(override)) !== "file") {
      rejected.push({ source: "env", reason: "missing" });
    } else {
      return { python: path.resolve(override), source: "env", reason: "ok", rejected };
    }
  }
  if (isAbsLocal(o.root)) {
    const embedded = path.join(o.root, ...EMBED_PYTHON);
    if (probe(embedded) === "file") {
      return { python: embedded, source: "embedded", reason: "ok", rejected };
    }
  }
  if (o.isPackaged === false && isAbsLocal(env.LOCALAPPDATA)) {
    const canonical = path.join(env.LOCALAPPDATA.trim(), ...DEV_PYTHON);
    if (probe(canonical) === "file") {
      return { python: canonical, source: "canonical", reason: "ok", rejected };
    }
  }
  return { python: null, source: null, reason: "no-interpreter", rejected };
}

// resources/backend for a packaged build, or null.
function bundledBackendDir(resourcesPath) {
  return isAbsLocal(resourcesPath) ? path.join(resourcesPath.trim(), BUNDLED_BACKEND_DIR) : null;
}

// The host spawn, or {enabled: false, reason}. opts: root, argv, env,
// isPackaged, parentPid, probe.
function hostLaunchPlan(opts) {
  const o = opts && typeof opts === "object" ? opts : {};
  const off = hostDisabled(o);
  if (off) {
    return { enabled: false, reason: "disabled:" + off };
  }
  if (!isAbsLocal(o.root)) {
    return { enabled: false, reason: "no-root" };
  }
  const root = path.resolve(o.root);
  const probe = probeOf(o.probe);
  const script = path.join(root, ...HOST_SCRIPT);
  if (probe(script) !== "file") {
    return { enabled: false, reason: "no-host-script" };
  }
  const py = resolvePython({ root, env: o.env, isPackaged: o.isPackaged, probe: o.probe });
  if (!py.python) {
    return { enabled: false, reason: py.reason, rejected: py.rejected };
  }
  const prof = resolveProfile(o);
  if (o.isPackaged !== true && prof.source === "default") {
    // A checkout launch (npm start, launch_overlay.bat) starts the host only
    // when a profile is named: before the section-5 cutover the scheduled
    // tasks own the agents, and a host that found the supervisor down would
    // start second copies of them beside the task-run ones.
    return { enabled: false, reason: "checkout-launch-needs-profile" };
  }
  const args = ["-I", script, "--root", root, "--profile", prof.profile];
  if (Number.isInteger(o.parentPid) && o.parentPid > 0) {
    args.push("--parent-pid", String(o.parentPid));
  }
  return {
    enabled: true,
    reason: "ok",
    command: py.python,
    args,
    cwd: root,
    profile: prof.profile,
    profileSource: prof.source,
    pythonSource: py.source,
  };
}

// ---- dashboard token (PACKAGING_PLAN 3.6, V3) --------------------------------

function dashTokenPath(root) {
  return isAbsLocal(root) ? path.join(root, ...DASH_TOKEN_FILE) : null;
}

// The first line, stripped, when it is a legal header value (printable ASCII
// 0x21-0x7e, ops/launcher/first_run.py valid_token); else null.
function readToken(text) {
  if (typeof text !== "string" || text.length > MAX_TOKEN_FILE_BYTES) {
    return null;
  }
  const first = text.split(/\r?\n/)[0].trim();
  if (!first || first.length > MAX_TOKEN_CHARS || !/^[\x21-\x7e]+$/.test(first)) {
    return null;
  }
  return first;
}

// Add X-RC-Token to a request for the shell's own origin only. A request for
// any other origin keeps its headers object untouched. Any spelling the page
// set is replaced by the install's own token.
function withTokenHeader(headers, url, origin, token) {
  const h = headers && typeof headers === "object" ? headers : {};
  const valid = readToken(token);
  if (valid === null || valid !== token || !nav.isSameOrigin(url, origin)) {
    return { headers: h, added: false };
  }
  const out = {};
  for (const k of Object.keys(h)) {
    if (k.toLowerCase() !== TOKEN_HEADER.toLowerCase()) {
      out[k] = h[k];
    }
  }
  out[TOKEN_HEADER] = token;
  return { headers: out, added: true };
}

// ---- IPC sender (PACKAGING_PLAN S3) ------------------------------------------

// A bridge message counts only from one of the shell's own bridge windows
// whose sending frame is on the RC origin.
function senderAllowed(opts) {
  const o = opts && typeof opts === "object" ? opts : {};
  return o.knownWindow === true && nav.isSameOrigin(o.frameUrl, o.origin);
}

// ---- health + boot view -------------------------------------------------------

// GET /api/health answered: HTTP 200 and a health document with alive true
// (the same rule as ops/launcher/service_host.py fetch_health_origin).
function healthOk(statusCode, body) {
  if (statusCode !== 200 || typeof body !== "string" || body.length > MAX_HEALTH_BYTES) {
    return false;
  }
  try {
    const doc = JSON.parse(body);
    return !!doc && typeof doc === "object" && !Array.isArray(doc) && !!doc.alive;
  } catch (_e) {
    return false;
  }
}

// The status file is read for OUR host only, except when our host exited 3
// (another host held ops/runtime/service_host.pid): its status is then the
// one that matters.
function statusHostPid(opts) {
  const o = opts && typeof opts === "object" ? opts : {};
  if (o.hostExitCode === 3) {
    return null;
  }
  return Number.isInteger(o.hostPid) && o.hostPid > 0 ? o.hostPid : null;
}

// Layer the host process outcome over service_status.shellView: a host that
// exited (any code but 3) before health answered is an error, not a wait.
function bootView(opts) {
  const o = opts && typeof opts === "object" ? opts : {};
  const v = o.view && typeof o.view === "object" ? o.view : { view: "starting", reason: "no-status", failing: [] };
  if (v.view === "app") {
    return v;
  }
  if (o.hostEnabled === true && o.hostRunning !== true && Number.isInteger(o.hostExitCode) && o.hostExitCode !== 3) {
    return {
      view: "error",
      reason: "host-exit-" + o.hostExitCode,
      degraded: true,
      failing: Array.isArray(v.failing) ? v.failing : [],
    };
  }
  return v;
}

const LOG_HINT = "Log: ops/runtime/logs/service_host.log in the backend folder.";

function ascii(s, max) {
  return String(s)
    .replace(/[^\x20-\x7e]/g, " ")
    .replace(/ {2,}/g, " ")
    .trim()
    .slice(0, max || 400);
}

// The text the starting page renders: {view, title, detail, rows}.
function startingModel(view, status) {
  const v = view && typeof view === "object" ? view : { view: "starting", reason: "no-status" };
  const reason = typeof v.reason === "string" ? v.reason : "";
  const failing = Array.isArray(v.failing) ? v.failing.slice(0, 8).join(", ") : "";
  const isError = v.view === "error";
  let detail;
  if (reason === "no-status") {
    detail = "Starting the local services...";
  } else if (reason === "starting") {
    detail = "Waiting for the dashboard to answer...";
  } else if (reason === "start-timeout") {
    detail = "The local services did not answer in time. They may still come up. " + LOG_HINT;
  } else if (reason === "service-blocked") {
    detail = "Port 8888 is held by something that is not a healthy Amberstone. Close it and relaunch. " + LOG_HINT;
  } else if (reason.startsWith("service-")) {
    detail = "A local service failed" + (failing ? ": " + failing : "") + ". " + LOG_HINT;
  } else if (reason.startsWith("host-exit-")) {
    detail = "The service host exited (code " + reason.slice("host-exit-".length) + "). " + LOG_HINT;
  } else {
    detail = isError ? "Amberstone could not start. " + LOG_HINT : "Starting...";
  }
  const rows = svc.describe(status).map((r) => ({ name: ascii(r.name, 64), row: r.row, word: r.word }));
  return {
    view: isError ? "error" : "starting",
    title: isError ? "Amberstone could not start" : "Amberstone is starting",
    detail: ascii(detail),
    rows,
  };
}

// ---- shell update relaunch (PACKAGING_PLAN 3.4) -------------------------------

// Relaunch to install a downloaded shell update only when the operator armed
// it and the last /api/state answer said no game is live.
function relaunchDecision(opts) {
  const o = opts && typeof opts === "object" ? opts : {};
  if (!o.pending) {
    return { relaunch: false, reason: "no-update" };
  }
  if (o.armed !== true) {
    return { relaunch: false, reason: "not-armed" };
  }
  if (o.stateFresh !== true) {
    return { relaunch: false, reason: "state-unknown" };
  }
  if (o.inGame !== false) {
    return { relaunch: false, reason: "game-live" };
  }
  return { relaunch: true, reason: "idle" };
}

function quitNeedsHostStop(opts) {
  const o = opts && typeof opts === "object" ? opts : {};
  return o.running === true && o.stopped !== true;
}

// ---- userData migration (PACKAGING_PLAN S6) -----------------------------------

function samePath(a, b) {
  const ra = path.resolve(a);
  const rb = path.resolve(b);
  return process.platform === "win32" ? ra.toLowerCase() === rb.toLowerCase() : ra === rb;
}

// productName moved userData from <appData>/rc-shell to <appData>/<productName>:
// copy the old state file once so window, overlay and widget layout survive.
function userDataMigration(opts) {
  const o = opts && typeof opts === "object" ? opts : {};
  if (!isAbsLocal(o.userDataDir) || !isAbsLocal(o.appDataDir)) {
    return { migrate: false, from: null, to: null, reason: "no-paths" };
  }
  const legacyDir = path.join(o.appDataDir, LEGACY_USERDATA_DIR);
  const from = path.join(legacyDir, STATE_FILE);
  const to = path.join(o.userDataDir, STATE_FILE);
  if (samePath(legacyDir, o.userDataDir)) {
    return { migrate: false, from, to, reason: "same-dir" };
  }
  const probe = probeOf(o.probe);
  if (probe(to) === "file") {
    return { migrate: false, from, to, reason: "already-migrated" };
  }
  if (probe(from) !== "file") {
    return { migrate: false, from, to, reason: "nothing-to-migrate" };
  }
  return { migrate: true, from, to, reason: "migrate" };
}

// ---- TLS (PACKAGING_PLAN S1) --------------------------------------------------

// How a request to `origin` is secured: "plain" (http), "pin" (https, the
// install's leaf pin is checked on the response), "verify" (https with no
// pin: normal certificate validation, never a blanket accept), "invalid".
function pollTlsMode(origin, pins) {
  let u = null;
  try {
    u = typeof origin === "string" && origin ? new URL(origin) : null;
  } catch (_e) {
    u = null;
  }
  if (!u) {
    return "invalid";
  }
  if (u.protocol === "http:") {
    return "plain";
  }
  if (u.protocol !== "https:") {
    return "invalid";
  }
  return Array.isArray(pins) && pins.length > 0 ? "pin" : "verify";
}

function refreshDue(lastReadMs, nowMs) {
  if (typeof lastReadMs !== "number" || !Number.isFinite(lastReadMs)) {
    return true;
  }
  return nowMs - lastReadMs >= SECRET_REFRESH_MS;
}

module.exports = {
  PROFILES,
  PROFILE_ARG,
  PROFILE_ENV,
  NO_HOST_ARG,
  NO_HOST_ENV,
  PYTHON_ENV,
  HOST_SCRIPT,
  EMBED_PYTHON,
  DEV_PYTHON,
  BUNDLED_BACKEND_DIR,
  DASH_TOKEN_FILE,
  TOKEN_HEADER,
  MAX_TOKEN_CHARS,
  HOST_STOP_GRACE_MS,
  SECRET_REFRESH_MS,
  STARTING_SHOW_DELAY_MS,
  BOOT_TICK_MS,
  HEALTH_TIMEOUT_MS,
  MAX_HEALTH_BYTES,
  LEGACY_USERDATA_DIR,
  STATE_FILE,
  argValue,
  hostDisabled,
  resolveProfile,
  resolvePython,
  bundledBackendDir,
  hostLaunchPlan,
  dashTokenPath,
  readToken,
  withTokenHeader,
  senderAllowed,
  healthOk,
  statusHostPid,
  bootView,
  startingModel,
  relaunchDecision,
  quitNeedsHostStop,
  userDataMigration,
  pollTlsMode,
  refreshDue,
};
