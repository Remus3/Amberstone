// rc-shell/test/backend_update.test.js
//
// PKG-6b (docs/PACKAGING_PLAN.md section 4, WA11): the shell runs the backend
// update cycle (ops/launcher/update_cycle.py) and owes the restarts it names.
// Two layers, like launcher_wiring.test.js:
//   1. the pure decisions in src/backend_update.js (no electron, real asserts);
//   2. source contracts on src/main.js (it imports electron, so node cannot
//      load it; the wiring is pinned by its text).
// Every path is COMPUTED (os.tmpdir() based); the filesystem is a fake probe.
// NO electron. Run with: npm test

"use strict";

const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");

const bu = require("../src/backend_update");

const SRC = path.join(__dirname, "..", "src");
const MAIN_SRC = fs.readFileSync(path.join(SRC, "main.js"), "utf8");
const PKG = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "package.json"), "utf8"));

const BASE = path.join(os.tmpdir(), "rc-pkg6b-fixture");
const ROOT = path.join(BASE, "backend");
const CYCLE = path.join(ROOT, "ops", "launcher", "update_cycle.py");
const PY = path.join(ROOT, "python-embed", "python.exe");
const LOCAL_REL = path.join(BASE, "releases");

function probe(p) {
  return p === CYCLE ? "file" : null;
}

function fnBody(name) {
  const start = MAIN_SRC.indexOf("function " + name + "(");
  assert.ok(start >= 0, "main.js defines " + name);
  const next = MAIN_SRC.indexOf("\nfunction ", start + 10);
  return MAIN_SRC.slice(start, next < 0 ? undefined : next);
}

// ---- source ---------------------------------------------------------------------

test("resolveSource: default github; env github, github:<owner>/<repo>, local:<abs>", () => {
  assert.deepStrictEqual(bu.resolveSource({}), { source: "github", origin: "default", rejected: [] });
  assert.strictEqual(bu.resolveSource({ RC_BACKEND_UPDATE_SOURCE: "github" }).origin, "env");
  assert.strictEqual(bu.resolveSource({ RC_BACKEND_UPDATE_SOURCE: "github:Some-Owner/repo.x" }).source,
    "github:Some-Owner/repo.x");
  const l = bu.resolveSource({ RC_BACKEND_UPDATE_SOURCE: "local:" + LOCAL_REL });
  assert.strictEqual(l.source, "local:" + path.resolve(LOCAL_REL));
});

test("resolveSource: a bad value falls back to the default feed and says why", () => {
  for (const [raw, why] of [
    ["local:relative/dir", "local-not-absolute"],
    ["github:a/b/c", "bad-github-slug"],
    ["github:bad owner/x", "bad-github-slug"],
    ["https://evil.example/feed", "unknown-source"],
  ]) {
    const r = bu.resolveSource({ RC_BACKEND_UPDATE_SOURCE: raw });
    assert.strictEqual(r.source, "github", raw);
    assert.deepStrictEqual(r.rejected, [why], raw);
  }
});

// ---- plan -------------------------------------------------------------------------

function plan(over) {
  return bu.cyclePlan(Object.assign({
    root: ROOT, python: PY, hostOwned: true, isPackaged: true, channel: "stable",
    shellVersion: "0.4.0", parentPid: 4242, env: {}, probe,
  }, over || {}));
}

test("cyclePlan: the documented argv (-I, the cycle script, root, run, source, channel, versions, parent)", () => {
  const p = plan();
  assert.strictEqual(p.enabled, true);
  assert.strictEqual(p.command, path.resolve(PY));
  assert.deepStrictEqual(p.args, ["-I", CYCLE, "--root", path.resolve(ROOT), "run", "--source", "github",
    "--channel", "stable", "--shell-version", "0.4.0", "--parent-pid", "4242"]);
  assert.strictEqual(p.cwd, path.resolve(ROOT));
  assert.strictEqual(p.timeoutMs, bu.CYCLE_TIMEOUT_MS);
});

test("cyclePlan: each missing piece disables the cycle with a reason", () => {
  assert.strictEqual(plan({ isPackaged: false }).reason, "checkout-launch");
  assert.strictEqual(plan({ root: "relative" }).reason, "no-root");
  assert.strictEqual(plan({ python: null }).reason, "no-interpreter");
  assert.strictEqual(plan({ hostOwned: false }).reason, "host-not-owning");
  assert.strictEqual(plan({ probe: () => null }).reason, "no-cycle-script");
});

test("cyclePlan: a checkout launch opts in only with RC_BACKEND_UPDATES=1", () => {
  assert.strictEqual(plan({ isPackaged: false, env: { RC_BACKEND_UPDATES: "1" } }).enabled, true);
  assert.strictEqual(plan({ isPackaged: false, env: { RC_BACKEND_UPDATES: "0" } }).enabled, false);
});

test("cyclePlan: a bad channel, version or pid never reaches the argv", () => {
  const p = plan({ channel: "evil", shellVersion: "1.0.0; rm", parentPid: -1 });
  assert.ok(p.args.includes("stable"));
  assert.ok(!p.args.includes("--shell-version"));
  assert.ok(!p.args.includes("--parent-pid"));
  assert.ok(plan({ channel: "dev" }).args.includes("dev"));
});

// ---- when -------------------------------------------------------------------------

test("cycleDue: never in a game, never on a stale state, one at a time", () => {
  const base = { nowMs: 10, lastRunMs: null, inGame: false, stateFresh: true };
  assert.deepStrictEqual(bu.cycleDue(base), { run: true, reason: "first" });
  assert.strictEqual(bu.cycleDue(Object.assign({}, base, { inGame: true })).reason, "game-live");
  assert.strictEqual(bu.cycleDue(Object.assign({}, base, { inGame: undefined })).reason, "game-live");
  assert.strictEqual(bu.cycleDue(Object.assign({}, base, { stateFresh: false })).reason, "state-unknown");
  assert.strictEqual(bu.cycleDue(Object.assign({}, base, { inFlight: true, manual: true })).reason, "in-flight");
});

test("cycleDue: the interval, and a manual check skips only the interval", () => {
  const base = { inGame: false, stateFresh: true, intervalMs: 1000, lastRunMs: 5000 };
  assert.strictEqual(bu.cycleDue(Object.assign({}, base, { nowMs: 5500 })).reason, "not-due");
  assert.strictEqual(bu.cycleDue(Object.assign({}, base, { nowMs: 6000 })).reason, "due");
  assert.strictEqual(bu.cycleDue(Object.assign({}, base, { nowMs: 5500, manual: true })).reason, "manual");
  assert.strictEqual(bu.cycleDue(Object.assign({}, base, { nowMs: 5500, manual: true, inGame: true })).run, false);
});

test("lastRunAfter: a result to retry comes due RETRY_DELAY_MS later, else a full interval", () => {
  const iv = 1000000;
  const retry = bu.lastRunAfter({ retryLater: true }, 50000000, iv);
  assert.strictEqual(retry, 50000000 - iv + bu.RETRY_DELAY_MS);
  const due = { inGame: false, stateFresh: true, intervalMs: iv, lastRunMs: retry };
  assert.strictEqual(bu.cycleDue(Object.assign({}, due, { nowMs: 50000000 + bu.RETRY_DELAY_MS - 1 })).run, false);
  assert.strictEqual(bu.cycleDue(Object.assign({}, due, { nowMs: 50000000 + bu.RETRY_DELAY_MS })).run, true);
  assert.strictEqual(bu.lastRunAfter({ retryLater: false }, 7, iv), 7);
});

// ---- result -----------------------------------------------------------------------

function out(doc) {
  return "noise line\n" + JSON.stringify(doc) + "\n";
}

test("parseCycleOutput: an applied cycle owes the restarts it names", () => {
  const r = bu.parseCycleOutput(out({
    ok: true, status: "applied", version: "1.2.0", detail: "verified",
    restart: { host_services: ["vision", "lcu_agent", "Bad Name", "vision"], respawn_host: false,
      relaunch_shell: false },
  }), 0);
  assert.strictEqual(r.status, "applied");
  assert.strictEqual(r.ok, true);
  assert.strictEqual(r.version, "1.2.0");
  assert.deepStrictEqual(r.actions, { hostServices: ["lcu_agent", "vision"], respawnHost: false, relaunchShell: false });
});

test("parseCycleOutput: a host respawn covers every service", () => {
  const r = bu.parseCycleOutput(out({ ok: true, status: "applied",
    restart: { host_services: ["vision"], respawn_host: true } }), 0);
  assert.deepStrictEqual(r.actions, { hostServices: [], respawnHost: true, relaunchShell: false });
});

test("parseCycleOutput: exit 3 is a live-game deferral, retried later; nothing is owed", () => {
  const r = bu.parseCycleOutput(out({ ok: false, status: "deferred", code: "game_live" }), 3);
  assert.strictEqual(r.status, "deferred");
  assert.strictEqual(r.retryLater, true);
  assert.deepStrictEqual(r.actions, bu.emptyOwed());
});

test("parseCycleOutput: restarts are owed for applied, owed and recovered results only", () => {
  for (const status of ["owed", "recovered"]) {
    const r = bu.parseCycleOutput(out({ ok: status === "owed", status,
      restart: { host_services: ["vision"], respawn_host: false } }), status === "owed" ? 0 : 1);
    assert.deepStrictEqual(r.actions.hostServices, ["vision"], status);
  }
  for (const status of ["pending", "failed", "refused", "up-to-date", "skipped", "idle"]) {
    const r = bu.parseCycleOutput(out({ ok: status !== "failed", status,
      restart: { host_services: ["vision"], respawn_host: true } }), status === "failed" ? 1 : 0);
    assert.deepStrictEqual(r.actions, bu.emptyOwed(), status);
  }
});

test("parseCycleOutput: garbage, an unknown status or no output is an error, never a throw", () => {
  for (const [text, code] of [["", 1], ["not json", 1], [out({ status: "pwned" }), 0], [null, 0]]) {
    const r = bu.parseCycleOutput(text, code);
    assert.strictEqual(r.status, "error");
    assert.strictEqual(r.code, "bad-output");
    assert.deepStrictEqual(r.actions, bu.emptyOwed());
  }
});

test("parseCycleOutput: detail is ASCII and capped", () => {
  const r = bu.parseCycleOutput(out({ ok: false, status: "refused", code: "integrity",
    detail: "bad " + String.fromCharCode(0x2014) + " bytes" + "x".repeat(500) }), 1);
  assert.ok(/^[\x20-\x7e]*$/.test(r.detail));
  assert.ok(r.detail.length <= 200);
});

// ---- owed restarts ------------------------------------------------------------------

test("mergeOwed: restarts accumulate; a respawn absorbs the service list", () => {
  let o = bu.mergeOwed(bu.emptyOwed(), { hostServices: ["vision"], respawnHost: false, relaunchShell: false });
  o = bu.mergeOwed(o, { hostServices: ["ds", "vision"], respawnHost: false, relaunchShell: true });
  assert.deepStrictEqual(o, { hostServices: ["ds", "vision"], respawnHost: false, relaunchShell: true });
  o = bu.mergeOwed(o, { hostServices: [], respawnHost: true, relaunchShell: false });
  assert.deepStrictEqual(o, { hostServices: [], respawnHost: true, relaunchShell: true });
});

test("owedDecision: owed restarts wait for an idle, fresh state and a running host", () => {
  const owed = { hostServices: ["vision"], respawnHost: false, relaunchShell: false };
  const idle = { owed, inGame: false, stateFresh: true, hostRunning: true, hostEnabled: false };
  assert.strictEqual(bu.owedDecision(idle).act, "restart-services");
  assert.strictEqual(bu.owedDecision(Object.assign({}, idle, { inGame: true })).act, "wait");
  assert.strictEqual(bu.owedDecision(Object.assign({}, idle, { stateFresh: false })).act, "wait");
  assert.strictEqual(bu.owedDecision(Object.assign({}, idle, { hostRunning: false })).act, "wait");
  assert.strictEqual(bu.owedDecision(Object.assign({}, idle, { owed: bu.emptyOwed() })).act, "none");
  assert.strictEqual(bu.owedDecision(Object.assign({}, idle,
    { owed: { hostServices: [], respawnHost: true, relaunchShell: false } })).act, "respawn-host");
});

test("restartCommandLine: the host's JSON line, validated", () => {
  const line = bu.restartCommandLine(["vision", "lcu_agent"], "shell-1");
  assert.ok(line.endsWith("\n"));
  assert.deepStrictEqual(JSON.parse(line), { cmd: "restart", id: "shell-1", services: ["vision", "lcu_agent"] });
  assert.ok(/^[\x20-\x7e]*\n$/.test(line));
  assert.strictEqual(bu.restartCommandLine([], "x"), null);
  assert.strictEqual(bu.restartCommandLine(["vision"], "bad id"), null);
  assert.strictEqual(bu.restartCommandLine(["Bad Name"], "x"), null);
});

test("logLine: one ASCII line", () => {
  const l = bu.logLine({ status: "applied", version: "1.2.0", code: null, detail: "verified" });
  assert.strictEqual(l, "backend update: applied - version 1.2.0 - verified");
});

// ---- main.js wiring (source contracts) ------------------------------------------------

test("main.js: the cycle is spawned from the pure plan, windowless, bounded, never through a shell", () => {
  assert.ok(fnBody("backendPlan").includes("bu.cyclePlan("), "the plan decides");
  assert.ok(fnBody("runBackendCycle").includes('backendPlan("run"'), "run mode");
  assert.ok(fnBody("runBackendResume").includes('backendPlan("resume"'), "resume mode");
  const body = fnBody("runBackendChild");
  assert.ok(body.includes("execFile("), "execFile, never a shell string");
  assert.ok(body.includes("windowsHide: true"), "no console window");
  assert.ok(body.includes("bu.watchdogDecision("), "bounded by the phase-aware watchdog (F6)");
  assert.ok(body.includes("bu.parseCycleOutput("), "the result is parsed by the pure core");
  assert.ok(!/shell:\s*true/.test(body), "never shell: true");
});

test("main.js: cycles run only through the idle gate and the owned-host check", () => {
  const body = fnBody("maybeRunBackendCycle");
  assert.ok(body.includes("bu.cycleDue("), "pure gate");
  assert.ok(body.includes("!lastUpdateIdle") && body.includes("pollFresh"), "the strict idle gate (F5)");
  assert.ok(fnBody("hostOwnsServices").includes('status.mode === "owned"'), "attach mode never updates");
});

test("main.js: owed restarts go to the host stdin or respawn it, only when idle", () => {
  const body = fnBody("applyOwedRestarts");
  assert.ok(body.includes("bu.owedDecision("), "pure decision");
  assert.ok(body.includes("bu.restartCommandLine("), "the documented JSON line");
  assert.ok(body.includes("hostChild.stdin.write("), "the host's stdin channel");
  assert.ok(body.includes("respawnServiceHost("), "a host respawn for app-level changes");
  const respawn = fnBody("respawnServiceHost");
  assert.ok(respawn.indexOf("stopServiceHost(") < respawn.indexOf("startServiceHost("), "stop, then start");
  assert.ok(MAIN_SRC.includes("applyOwedRestarts();"), "applied from the poll loop");
});

test("main.js: quit starts no new cycle; a running one stops itself through --parent-pid", () => {
  const hook = MAIN_SRC.slice(MAIN_SRC.indexOf('app.on("will-quit"'));
  assert.ok(hook.slice(0, 2500).includes("stopBackendCycles("), "the cycle timers end on quit");
  const stop = fnBody("stopBackendCycles");
  assert.ok(!stop.includes(".kill("), "never killed mid-write: every cycle write is atomic and resumable");
  assert.ok(fnBody("runBackendCycle").includes("bu.lastRunAfter("), "a deferral retries sooner");
  const respawn = fnBody("respawnServiceHost");
  assert.ok(respawn.includes("shellQuitting"), "a respawn never restarts the host during a quit");
});

test("main.js: a manual backend check is in the menu", () => {
  assert.ok(MAIN_SRC.includes("Check for backend updates now"));
  assert.ok(MAIN_SRC.includes("maybeRunBackendCycle(true)"));
});

test("package.json: the backend_update tests are in the enumerated npm test script", () => {
  assert.ok(PKG.scripts.test.includes("test/backend_update.test.js"));
});

// ---- fix round (review of 6e09c8bc1) ---------------------------------------------

test("F5 idleForUpdate: only a lobby or no LCU phase, with no live game, is idle", () => {
  assert.strictEqual(bu.idleForUpdate({ liveclient: {}, lcu: { phase: "Lobby" } }), true);
  assert.strictEqual(bu.idleForUpdate({ liveclient: {}, lcu: { phase: "None" } }), true);
  assert.strictEqual(bu.idleForUpdate({ liveclient: {}, lcu: {} }), true);
  assert.strictEqual(bu.idleForUpdate({ mode_key: "client" }), true);
  for (const phase of ["Matchmaking", "ReadyCheck", "ChampSelect", "GameStart", "InProgress",
    "Reconnect", "WaitingForStats", "PreEndOfGame", "EndOfGame", "SomethingNew"]) {
    assert.strictEqual(bu.idleForUpdate({ liveclient: {}, lcu: { phase } }), false, phase);
  }
  assert.strictEqual(bu.idleForUpdate({ liveclient: { activePlayer: {} }, lcu: { phase: "Lobby" } }), false);
  assert.strictEqual(bu.idleForUpdate(null), false, "no state = not idle");
  assert.strictEqual(bu.idleForUpdate([]), false);
});

test("F1 cyclePlan resume: no source, no owned host needed, --restarts-sent on request", () => {
  const p = plan({ mode: "resume", hostOwned: false, restartsSent: true });
  assert.strictEqual(p.enabled, true);
  assert.deepStrictEqual(p.args, ["-I", CYCLE, "--root", path.resolve(ROOT), "resume",
    "--restarts-sent", "--parent-pid", "4242"]);
  assert.ok(!plan({ mode: "resume" }).args.includes("--restarts-sent"));
  assert.strictEqual(plan({ mode: "bogus" }).reason, "bad-mode");
});

test("F1 recordsFrom: what an earlier cycle left on disk", () => {
  const cyc = JSON.stringify({ verify: { version: "1.1.0" }, owed: null, phase: "verifying" });
  const st = JSON.stringify({ pending: null, recovering: { version: "1.1.0" } });
  assert.deepStrictEqual(bu.recordsFrom(cyc, st),
    { verify: true, owed: false, owedSent: false, retryAfterMs: null, pending: false, recovering: true, phase: "verifying" });
  assert.deepStrictEqual(bu.recordsFrom("garbage", null),
    { verify: false, owed: false, owedSent: false, retryAfterMs: null, pending: false, recovering: false, phase: null });
});

test("F1 resumeDue: a verify / pending / recovering record resumes on its interval, any state", () => {
  const rec = { verify: true, owed: false, pending: false, recovering: false };
  assert.strictEqual(bu.resumeDue({ records: rec, lastResumeMs: null, nowMs: 1 }).run, true);
  assert.strictEqual(bu.resumeDue({ records: rec, lastResumeMs: 1000, nowMs: 1000 + bu.RESUME_INTERVAL_MS - 1 }).run, false);
  assert.strictEqual(bu.resumeDue({ records: rec, lastResumeMs: 1000, nowMs: 1000 + bu.RESUME_INTERVAL_MS }).run, true);
  assert.strictEqual(bu.resumeDue({ records: rec, inFlight: true, nowMs: 1 }).reason, "in-flight");
  const owed = { verify: false, owed: true, pending: false, recovering: false };
  assert.strictEqual(bu.resumeDue({ records: owed, lastResumeMs: null, nowMs: 1 }).run, true, "owed: once per launch");
  assert.strictEqual(bu.resumeDue({ records: owed, lastResumeMs: 5, nowMs: 1e9 }).run, false);
  assert.strictEqual(bu.resumeDue({ records: bu.recordsFrom(null, null), nowMs: 1 }).reason, "nothing-recorded");
});

test("F2 hostStopGraceMs: a deploy in flight stretches the quit grace, bounded", () => {
  assert.strictEqual(bu.hostStopGraceMs(25000, false), 25000);
  assert.strictEqual(bu.hostStopGraceMs(25000, true), bu.DEPLOY_STOP_GRACE_MS);
  assert.ok(bu.DEPLOY_STOP_GRACE_MS > 150000, "past the host's own deploy grace");
  assert.ok(bu.DEPLOY_STOP_GRACE_MS <= 5 * 60 * 1000, "bounded");
  assert.strictEqual(bu.deployInFlight(["a.json", "b.deploying"]), true);
  assert.strictEqual(bu.deployInFlight(["a.json", "x.deploying.stale"]), false);
  assert.strictEqual(bu.deployInFlight(null), false);
});

test("F6 watchdogDecision: never kills a cycle that is deploying or recovering", () => {
  const over = bu.CYCLE_TIMEOUT_MS + 1;
  assert.strictEqual(bu.watchdogDecision({ elapsedMs: over, phase: "checking" }), "kill");
  assert.strictEqual(bu.watchdogDecision({ elapsedMs: over, phase: null }), "kill");
  assert.strictEqual(bu.watchdogDecision({ elapsedMs: over, phase: "recovering" }), "wait");
  assert.strictEqual(bu.watchdogDecision({ elapsedMs: over, phase: "deploying" }), "wait");
  assert.strictEqual(bu.watchdogDecision({ elapsedMs: 10, phase: "checking" }), "wait");
  assert.ok(bu.CYCLE_TIMEOUT_MS >= 60 * 60 * 1000, "far past the cycle's own bounded waits");
});

test("main.js F1/F2/F5/F6 wiring", () => {
  const run = fnBody("runBackendChild");
  assert.ok(!/timeout:\s*plan\.timeoutMs/.test(run), "no execFile hard timeout (F6)");
  assert.ok(run.includes("bu.watchdogDecision("), "the watchdog decides from the cycle phase");
  const resume = fnBody("maybeResumeBackend");
  assert.ok(resume.includes("bu.resumeDue("), "resume gate");
  // F1: never gated on a fresh /api/state; pollFresh only feeds the B4 idle
  // flag that bu.resumeDue applies to a SENT owed check alone.
  assert.ok(!/if\s*\(\s*!?\s*pollFresh/.test(resume), "resume needs no fresh /api/state (F1)");
  assert.strictEqual(bu.resumeDue({ records: { verify: true }, lastResumeMs: null, nowMs: 1, idle: false }).run,
    true, "a verify record resumes while busy / down");
  assert.ok(MAIN_SRC.includes("lastUpdateIdle = bu.idleForUpdate(parsed)"), "F5 gate from /api/state");
  assert.ok(fnBody("maybeRunBackendCycle").includes("!lastUpdateIdle"), "cycles use the strict gate");
  assert.ok(fnBody("applyOwedRestarts").includes("!lastUpdateIdle"), "restarts use the strict gate");
  assert.ok(fnBody("applyOwedRestarts").includes("runBackendResume(true)"), "restarts are health-checked (F3)");
  assert.ok(fnBody("stopServiceHost").includes("bu.stopGraceExpired("),
    "quit grace stretches under a deploy, re-evaluated while waiting (F2, R6)");
});


// ---- fix round 2 -------------------------------------------------------------------

// The /api/state document as dashboard/_state_builder.py:1051-1077 builds it:
// the live-game flags live under `health` (lines 1058-1072), `liveclient`
// (1076) and `lcu` (1077) at the top level.
function apiState(over) {
  const base = {
    mode_key: "client",
    tft_context: { active: false, phase: null, queue_id: null, source: null },
    coach_source: null,
    health: {
      alive: true, pid: 1234, mode: "client", has_game: false,
      aram_mode: false, arena_mode: false, brawl_mode: false, tft_mode: false,
      ui_pulse_age_s: 0.5, game_poll_age_s: 0.5,
    },
    coach: {},
    liveclient: {},
    lcu: { phase: "Lobby" },
  };
  const s = JSON.parse(JSON.stringify(base));
  for (const [k, v] of Object.entries(over || {})) {
    s[k] = v && typeof v === "object" && !Array.isArray(v) && s[k] && typeof s[k] === "object"
      ? Object.assign(s[k], v) : v;
  }
  return s;
}

test("B3 idleForUpdate reads the live-game flags where /api/state puts them (health.*)", () => {
  assert.strictEqual(bu.idleForUpdate(apiState()), true);
  for (const flag of ["has_game", "aram_mode", "arena_mode", "brawl_mode", "tft_mode"]) {
    assert.strictEqual(bu.idleForUpdate(apiState({ health: { [flag]: true } })), false, flag);
  }
  assert.strictEqual(bu.idleForUpdate(apiState({ lcu: { phase: "ChampSelect" } })), false);
  assert.strictEqual(bu.idleForUpdate(apiState({ liveclient: { activePlayer: {} } })), false);
  assert.strictEqual(bu.idleForUpdate(apiState({ health: "garbage" })), true, "a bad health block is no flag");
});

test("B3 gameInTasklist: the updater's game processes in tasklist CSV, fail closed", () => {
  const csv = '"System Idle Process","0","Services","0","8 K"\r\n' +
    '"League of Legends.exe","4321","Console","1","2,000,000 K"\r\n';
  assert.deepStrictEqual(bu.gameInTasklist(csv), { ok: true, running: true });
  assert.deepStrictEqual(bu.gameInTasklist('"TFTClient-Win64-Shipping.exe","1","C","1","1 K"'),
    { ok: true, running: true });
  assert.deepStrictEqual(bu.gameInTasklist('"explorer.exe","1","C","1","1 K"\r\n'), { ok: true, running: false });
  assert.deepStrictEqual(bu.gameInTasklist(""), { ok: false, running: true }, "no listing = assume a game");
  assert.deepStrictEqual(bu.gameInTasklist(null), { ok: false, running: true });
  assert.deepStrictEqual(bu.GAME_PROCESS_NAMES.slice().sort(),
    ["league of legends.exe", "tftclient-win64-shipping.exe"], "mirrors updater.GAME_PROCESS_NAMES");
});

test("B4 resumeDue: a SENT owed check is retried on the interval, only when idle", () => {
  const sent = { verify: false, owed: true, owedSent: true, pending: false, recovering: false };
  const busy = bu.resumeDue({ records: sent, lastResumeMs: 1000, nowMs: 1000 + bu.RESUME_INTERVAL_MS, idle: false });
  assert.strictEqual(busy.run, false);
  assert.strictEqual(busy.reason, "owed-waits-for-idle");
  const due = bu.resumeDue({ records: sent, lastResumeMs: 1000, nowMs: 1000 + bu.RESUME_INTERVAL_MS, idle: true });
  assert.deepStrictEqual([due.run, due.restartsSent], [true, true]);
  const early = bu.resumeDue({ records: sent, lastResumeMs: 1000, nowMs: 1001, idle: true });
  assert.strictEqual(early.run, false);
  const st = JSON.stringify({ pending: null });
  assert.strictEqual(bu.recordsFrom(JSON.stringify({ owed: { sent_at: "2026-10-26T00:00:00+00:00" } }), st).owedSent, true);
  assert.strictEqual(bu.recordsFrom(JSON.stringify({ owed: { sent_at: null } }), st).owedSent, false);
});

// ---- fix round 3 (behaviour through exported functions; R8 replaces the
// round-2 source-string wiring test) -------------------------------------------

const OWED_SVC = { hostServices: ["vision"], respawnHost: false, relaunchShell: false };
const OWED_HOST = { hostServices: [], respawnHost: true, relaunchShell: false };
const IDLE = { inGame: false, stateFresh: true, hostRunning: true, hostEnabled: true, nowMs: 1000 };

test("B1/R8 owedDecision: an owed respawn with the host already down starts it - no idle gate", () => {
  const d = bu.owedDecision(Object.assign({}, IDLE, { owed: OWED_HOST, hostRunning: false, inGame: true, stateFresh: false }));
  assert.strictEqual(d.act, "start-host");
  assert.strictEqual(d.thenCheck, true, "then health-checked (resume --restarts-sent)");
  assert.strictEqual(bu.owedDecision(Object.assign({}, IDLE, { owed: OWED_HOST, hostRunning: false, hostEnabled: false })).act,
    "wait", "no host was ever planned: nothing to start");
  assert.strictEqual(bu.owedDecision(Object.assign({}, IDLE, { owed: OWED_HOST, blocked: true })).act, "wait");
  assert.strictEqual(bu.owedDecision(Object.assign({}, IDLE, { owed: OWED_HOST })).thenCheck, true);
  assert.strictEqual(bu.owedDecision(Object.assign({}, IDLE, { owed: OWED_SVC })).thenCheck, true);
});

test("R3 owedDecision + deferralBackoffMs: consecutive host deferrals back off, capped at 10 min", () => {
  assert.strictEqual(bu.deferralBackoffMs(0), 0);
  assert.strictEqual(bu.deferralBackoffMs(1), 30000);
  assert.strictEqual(bu.deferralBackoffMs(2), 60000);
  assert.strictEqual(bu.deferralBackoffMs(50), 600000);
  const held = bu.owedDecision(Object.assign({}, IDLE, { owed: OWED_SVC, notBeforeMs: 1000 + 30000 }));
  assert.deepStrictEqual([held.act, held.reason], ["wait", "backoff"]);
  assert.strictEqual(bu.owedDecision(Object.assign({}, IDLE, { owed: OWED_SVC, notBeforeMs: 1000 })).act,
    "restart-services");
  assert.deepStrictEqual(bu.nextDeferral(0, { code: "host_deferred" }, 5000), { count: 1, notBeforeMs: 35000 });
  assert.deepStrictEqual(bu.nextDeferral(3, { code: "host_deferred" }, 0), { count: 4, notBeforeMs: 240000 });
  assert.deepStrictEqual(bu.nextDeferral(3, { code: null, status: "applied" }, 0), { count: 0, notBeforeMs: 0 });
});

test("B5/R8 queueResume / takeQueued: a resume asked for during a child is kept, a sent check wins", () => {
  let q = bu.queueResume(null, false);
  q = bu.queueResume(q, true);
  q = bu.queueResume(q, false);
  assert.deepStrictEqual(q, { restartsSent: true });
  assert.deepStrictEqual(bu.takeQueued(q, true), { run: false, restartsSent: false, queued: q }, "still busy");
  assert.deepStrictEqual(bu.takeQueued(q, false), { run: true, restartsSent: true, queued: null });
  assert.deepStrictEqual(bu.takeQueued(null, false), { run: false, restartsSent: false, queued: null });
});

test("R2/R7 friendlyNotice: plain words for the states the operator must act on, never raw errors", () => {
  const unrestarted = bu.parseCycleOutput(out({ ok: true, status: "applied-unrestarted", version: "1.2.0",
    detail: "installed; restart Amberstone to finish the update - not ours to restart: ds (refused:open-failed)" }), 0);
  assert.strictEqual(unrestarted.status, "applied-unrestarted");
  assert.strictEqual(unrestarted.ok, true);
  assert.strictEqual(bu.friendlyNotice(unrestarted), "Backend update 1.2.0 installed - restart Amberstone to finish it");
  const attention = bu.parseCycleOutput(out({ ok: false, status: "failed", code: "recovery_attention",
    detail: "completing the recover failed (OSError); next try in 240 s" }), 1);
  assert.strictEqual(bu.friendlyNotice(attention),
    "Backend update recovery needs attention - see ops/runtime/logs/update_cycle.log");
  for (const r of [{ status: "applied" }, { status: "error", code: "bad-output" }, null]) {
    assert.strictEqual(bu.friendlyNotice(r), null);
  }
  assert.deepStrictEqual(bu.menuNotice("x"), { label: "x", enabled: false });
  assert.strictEqual(bu.menuNotice(null), null);
});

test("R7 resumeDue honours the cycle's retry_after backoff for a stuck recover", () => {
  const cyc = JSON.stringify({ retry_after: 2000 });
  const st = JSON.stringify({ recovering: { version: "1.1.0" } });
  const rec = bu.recordsFrom(cyc, st);
  assert.strictEqual(rec.retryAfterMs, 2000000);
  assert.deepStrictEqual(bu.resumeDue({ records: rec, lastResumeMs: null, nowMs: 1999999 }).reason, "backoff");
  assert.strictEqual(bu.resumeDue({ records: rec, lastResumeMs: null, nowMs: 2000000 }).run, true);
});

test("R6 stopGraceExpired: re-evaluated while waiting - a deploy that appears extends the grace", () => {
  const base = 25000;
  assert.strictEqual(bu.stopGraceExpired({ elapsedMs: 24999, baseMs: base, deployInFlight: false }), false);
  assert.strictEqual(bu.stopGraceExpired({ elapsedMs: 25000, baseMs: base, deployInFlight: false }), true);
  assert.strictEqual(bu.stopGraceExpired({ elapsedMs: 26000, baseMs: base, deployInFlight: true }), false);
  assert.strictEqual(bu.stopGraceExpired({ elapsedMs: bu.DEPLOY_STOP_GRACE_MS, baseMs: base, deployInFlight: true }), true);
});
