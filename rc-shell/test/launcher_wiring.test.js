// rc-shell/test/launcher_wiring.test.js
//
// PKG-6 (docs/PACKAGING_PLAN.md section 4): the shell becomes the launcher.
// Two layers, like nav_guard.test.js:
//   1. the pure decisions in src/launcher.js (no electron, real asserts), and
//   2. source contracts on src/main.js, electron-builder.yml and package.json
//      (main.js imports electron, so node cannot load it; the wiring is pinned
//      by its text instead).
//
// Every path here is COMPUTED at runtime (os.tmpdir() based) - no drive-root
// literal lives in this file (pre-push sweep). The filesystem is a fake probe.
// NO electron. Run with: npm test

"use strict";

const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");

const lch = require("../src/launcher");
const svc = require("../src/service_status");

const SRC = path.join(__dirname, "..", "src");
const MAIN_SRC = fs.readFileSync(path.join(SRC, "main.js"), "utf8");
const BUILDER_YML = fs.readFileSync(path.join(__dirname, "..", "electron-builder.yml"), "utf8");
const PKG = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "package.json"), "utf8"));

const BASE = path.join(os.tmpdir(), "rc-pkg6-fixture");
const ROOT = path.join(BASE, "backend");
const HOST = path.join(ROOT, "ops", "launcher", "service_host.py");
const EMBED = path.join(ROOT, "python-embed", "python.exe");
const LOCALAPPDATA = path.join(BASE, "localappdata");
const DEV_PY = path.join(LOCALAPPDATA, "Programs", "Python", "Python314", "python.exe");
const OVERRIDE_PY = path.join(BASE, "custom", "python.exe");
const ORIGIN = "https://127.0.0.1:8888";

function fakeFs(files) {
  const set = new Set(files);
  return (p) => (set.has(p) ? "file" : null);
}

// ---- profile + opt-out ---------------------------------------------------------

test("resolveProfile: packaged by default when packaged, dev for a checkout launch", () => {
  assert.deepStrictEqual(lch.resolveProfile({ isPackaged: true }).profile, "packaged");
  assert.deepStrictEqual(lch.resolveProfile({ isPackaged: false }).profile, "dev");
  assert.strictEqual(lch.resolveProfile({}).profile, "packaged", "unknown = the safe loopback profile");
});

test("resolveProfile: argv beats env beats default; a bad value is skipped and reported", () => {
  const r = lch.resolveProfile({
    isPackaged: true,
    argv: ["x", "--profile=dev"],
    env: { RC_LAUNCHER_PROFILE: "packaged" },
  });
  assert.strictEqual(r.profile, "dev");
  assert.strictEqual(r.source, "argv");
  const e = lch.resolveProfile({ isPackaged: true, argv: ["--profile", "evil"], env: { RC_LAUNCHER_PROFILE: "dev" } });
  assert.strictEqual(e.profile, "dev");
  assert.strictEqual(e.source, "env");
  assert.deepStrictEqual(e.rejected, [{ source: "argv", reason: "unknown-profile" }]);
});

test("hostDisabled: --no-host or RC_SHELL_NO_HOST=1 turns the host off, nothing else does", () => {
  assert.strictEqual(lch.hostDisabled({ argv: ["a", "--no-host"] }), "argv");
  assert.strictEqual(lch.hostDisabled({ env: { RC_SHELL_NO_HOST: "1" } }), "env");
  assert.strictEqual(lch.hostDisabled({ env: { RC_SHELL_NO_HOST: "true" } }), "env");
  assert.strictEqual(lch.hostDisabled({ env: { RC_SHELL_NO_HOST: "0" } }), null);
  assert.strictEqual(lch.hostDisabled({ env: { RC_SHELL_NO_HOST: "" } }), null);
  assert.strictEqual(lch.hostDisabled({ argv: ["--no-hostile"] }), null);
});

// ---- interpreter ----------------------------------------------------------------

test("resolvePython: RC_PYTHON override, then the embedded runtime, then (dev only) the canonical one", () => {
  const all = fakeFs([OVERRIDE_PY, EMBED, DEV_PY]);
  const env = { RC_PYTHON: OVERRIDE_PY, LOCALAPPDATA };
  assert.strictEqual(lch.resolvePython({ root: ROOT, env, isPackaged: true, probe: all }).source, "env");
  const noOverride = { LOCALAPPDATA };
  const embedded = lch.resolvePython({ root: ROOT, env: noOverride, isPackaged: true, probe: all });
  assert.strictEqual(embedded.python, EMBED);
  assert.strictEqual(embedded.source, "embedded");
  const devOnly = fakeFs([DEV_PY]);
  assert.strictEqual(lch.resolvePython({ root: ROOT, env: noOverride, isPackaged: false, probe: devOnly }).python, DEV_PY);
  const packagedNone = lch.resolvePython({ root: ROOT, env: noOverride, isPackaged: true, probe: devOnly });
  assert.strictEqual(packagedNone.python, null, "a packaged build never falls back to a machine interpreter");
  assert.strictEqual(packagedNone.reason, "no-interpreter");
});

test("resolvePython: a relative or missing RC_PYTHON is refused, not trusted", () => {
  const r = lch.resolvePython({ root: ROOT, env: { RC_PYTHON: "python.exe" }, isPackaged: true, probe: fakeFs([EMBED]) });
  assert.strictEqual(r.source, "embedded");
  assert.deepStrictEqual(r.rejected, [{ source: "env", reason: "not-absolute" }]);
  const m = lch.resolvePython({ root: ROOT, env: { RC_PYTHON: OVERRIDE_PY }, isPackaged: true, probe: fakeFs([EMBED]) });
  assert.deepStrictEqual(m.rejected, [{ source: "env", reason: "missing" }]);
});

// ---- host launch plan -----------------------------------------------------------

test("hostLaunchPlan: the documented argv (-I, the host script, root, profile, parent pid)", () => {
  const plan = lch.hostLaunchPlan({
    root: ROOT, isPackaged: true, env: {}, argv: [], parentPid: 4242, probe: fakeFs([HOST, EMBED]),
  });
  assert.strictEqual(plan.enabled, true);
  assert.strictEqual(plan.command, EMBED);
  assert.deepStrictEqual(plan.args, ["-I", HOST, "--root", ROOT, "--profile", "packaged", "--parent-pid", "4242"]);
  assert.strictEqual(plan.cwd, ROOT);
  assert.strictEqual(plan.profile, "packaged");
});

test("hostLaunchPlan: each missing piece disables the host with a reason (the shell then runs as before)", () => {
  const base = { isPackaged: true, env: {}, argv: [], parentPid: 1 };
  assert.strictEqual(lch.hostLaunchPlan(Object.assign({}, base, { root: null, probe: fakeFs([]) })).reason, "no-root");
  assert.strictEqual(lch.hostLaunchPlan(Object.assign({}, base, { root: ROOT, probe: fakeFs([EMBED]) })).reason, "no-host-script");
  assert.strictEqual(lch.hostLaunchPlan(Object.assign({}, base, { root: ROOT, probe: fakeFs([HOST]) })).reason, "no-interpreter");
  const off = lch.hostLaunchPlan(Object.assign({}, base, { root: ROOT, argv: ["--no-host"], probe: fakeFs([HOST, EMBED]) }));
  assert.strictEqual(off.enabled, false);
  assert.strictEqual(off.reason, "disabled:argv");
});

test("hostLaunchPlan: a checkout launch starts the host only when a profile is named (pre-cutover safety)", () => {
  const probe = fakeFs([HOST, DEV_PY]);
  const env = { LOCALAPPDATA };
  const bare = lch.hostLaunchPlan({ root: ROOT, isPackaged: false, env, argv: ["electron", "."], parentPid: 9, probe });
  assert.strictEqual(bare.enabled, false);
  assert.strictEqual(bare.reason, "checkout-launch-needs-profile");
  const dev = lch.hostLaunchPlan({ root: ROOT, isPackaged: false, env, argv: ["electron", ".", "--profile", "dev"], parentPid: 9, probe });
  assert.strictEqual(dev.enabled, true);
  assert.strictEqual(dev.profile, "dev");
  assert.strictEqual(dev.command, DEV_PY);
  assert.strictEqual(dev.pythonSource, "canonical");
  const viaEnv = lch.hostLaunchPlan({
    root: ROOT, isPackaged: false, env: { LOCALAPPDATA, RC_LAUNCHER_PROFILE: "dev" }, argv: [], parentPid: 9, probe,
  });
  assert.strictEqual(viaEnv.enabled, true);
  const bad = lch.hostLaunchPlan({ root: ROOT, isPackaged: false, env, argv: ["--profile=nope"], parentPid: 9, probe });
  assert.strictEqual(bad.enabled, false, "an unknown profile is not an opt-in");
});

test("hostLaunchPlan: a bogus parent pid is left out instead of passed through", () => {
  const plan = lch.hostLaunchPlan({ root: ROOT, isPackaged: true, env: {}, argv: [], parentPid: -3, probe: fakeFs([HOST, EMBED]) });
  assert.ok(!plan.args.includes("--parent-pid"));
});

test("bundledBackendDir: <resources>/backend, never inside an asar", () => {
  const res = path.join(BASE, "install", "resources");
  assert.strictEqual(lch.bundledBackendDir(res), path.join(res, "backend"));
  assert.strictEqual(lch.bundledBackendDir(""), null);
  assert.strictEqual(lch.bundledBackendDir("relative/resources"), null);
});

// ---- token header ----------------------------------------------------------------

test("readToken: first line, printable ASCII only, else null", () => {
  assert.strictEqual(lch.readToken("ab12cd\r\nignored"), "ab12cd");
  assert.strictEqual(lch.readToken("  tok  \n"), "tok");
  assert.strictEqual(lch.readToken(""), null);
  assert.strictEqual(lch.readToken("has space"), null);
  assert.strictEqual(lch.readToken("caf" + String.fromCharCode(0xe9)), null);
  assert.strictEqual(lch.readToken("x".repeat(lch.MAX_TOKEN_CHARS + 1)), null);
  assert.strictEqual(lch.readToken(null), null);
});

test("withTokenHeader: added for the shell's own origin only, replacing any page-set spelling", () => {
  const own = lch.withTokenHeader({ "x-rc-token": "stale", Accept: "a" }, ORIGIN + "/api/lcu-cmd", ORIGIN, "tok");
  assert.strictEqual(own.added, true);
  assert.deepStrictEqual(own.headers, { Accept: "a", "X-RC-Token": "tok" });
  const port = lch.withTokenHeader({}, "https://127.0.0.1:9999/x", ORIGIN, "tok");
  assert.strictEqual(port.added, false, "another port is another origin");
  assert.strictEqual(lch.withTokenHeader({}, ORIGIN + "/x", ORIGIN, null).added, false);
  assert.strictEqual(lch.withTokenHeader({}, ORIGIN + "/x", ORIGIN, "bad token").added, false);
});

// SF1 (verifier s142): Chromium keeps a header added on the first hop across a
// redirect, so a request redirected off the RC origin re-enters the hook still
// carrying X-RC-Token. Every non-RC origin has the header STRIPPED, never
// passed through.
test("withTokenHeader: X-RC-Token is stripped from every non-RC origin (SF1)", () => {
  const foreign = { Accept: "a", "X-RC-Token": "tok" };
  const other = lch.withTokenHeader(foreign, "https://example.com/x", ORIGIN, "tok");
  assert.strictEqual(other.added, false);
  assert.strictEqual(other.stripped, true);
  assert.deepStrictEqual(other.headers, { Accept: "a" }, "a redirected foreign request loses the token");
  assert.deepStrictEqual(foreign, { Accept: "a", "X-RC-Token": "tok" }, "the caller's object is not mutated");
  const port = lch.withTokenHeader({ "X-RC-Token": "tok" }, "https://127.0.0.1:9999/x", ORIGIN, "tok");
  assert.deepStrictEqual(port.headers, {}, "another port is another origin: stripped");
  const plain = lch.withTokenHeader({ "X-RC-Token": "tok" }, ORIGIN.replace("https:", "http:") + "/x", ORIGIN, "tok");
  assert.deepStrictEqual(plain.headers, {}, "another scheme is another origin: stripped");
  const clean = lch.withTokenHeader({ Accept: "a" }, "https://example.com/x", ORIGIN, "tok");
  assert.strictEqual(clean.stripped, false);
  assert.deepStrictEqual(clean.headers, { Accept: "a" }, "other headers survive");
});

test("withTokenHeader: the strip matches every case spelling of the header (SF1)", () => {
  const spellings = { "x-rc-token": "a", "X-Rc-Token": "b", "X-RC-TOKEN": "c", "x-RC-token": "d", Accept: "keep" };
  const r = lch.withTokenHeader(spellings, "https://example.com/x", ORIGIN, "tok");
  assert.deepStrictEqual(r.headers, { Accept: "keep" });
  assert.strictEqual(r.stripped, true);
});

test("withTokenHeader: stripped on a foreign origin whatever the token state (SF1)", () => {
  for (const tok of ["tok", null, "bad token", undefined]) {
    const r = lch.withTokenHeader({ "x-rc-token": "leak" }, "https://example.com/x", ORIGIN, tok);
    assert.deepStrictEqual(r.headers, {}, "token " + String(tok));
    assert.strictEqual(r.added, false);
  }
  for (const o of [null, "", "not a url"]) {
    const r = lch.withTokenHeader({ "X-RC-Token": "leak" }, ORIGIN + "/x", o, "tok");
    assert.deepStrictEqual(r.headers, {}, "no resolved origin = every origin is foreign: " + String(o));
  }
  assert.deepStrictEqual(lch.withTokenHeader({ "X-RC-Token": "leak" }, "not a url", ORIGIN, "tok").headers, {});
  assert.deepStrictEqual(lch.withTokenHeader(null, "https://example.com/x", ORIGIN, "tok").headers, {});
});

test("stripTokenHeader: pure, case-insensitive, copies (SF1)", () => {
  const src = { "X-RC-TOKEN": "x", Accept: "a" };
  const out = lch.stripTokenHeader(src);
  assert.deepStrictEqual(out, { Accept: "a" });
  assert.notStrictEqual(out, src);
  assert.deepStrictEqual(src, { "X-RC-TOKEN": "x", Accept: "a" });
  assert.deepStrictEqual(lch.stripTokenHeader(null), {});
});

// ---- IPC sender ------------------------------------------------------------------

test("senderAllowed: a known bridge window on the RC origin only (S3)", () => {
  assert.strictEqual(lch.senderAllowed({ frameUrl: ORIGIN + "/?overlay=1", origin: ORIGIN, knownWindow: true }), true);
  assert.strictEqual(lch.senderAllowed({ frameUrl: ORIGIN + "/", origin: ORIGIN, knownWindow: false }), false);
  assert.strictEqual(lch.senderAllowed({ frameUrl: "https://evil.example/", origin: ORIGIN, knownWindow: true }), false);
  assert.strictEqual(lch.senderAllowed({ frameUrl: "file:///starting.html", origin: ORIGIN, knownWindow: true }), false);
  assert.strictEqual(lch.senderAllowed({ frameUrl: null, origin: ORIGIN, knownWindow: true }), false);
  assert.strictEqual(lch.senderAllowed({ frameUrl: ORIGIN + "/", origin: "", knownWindow: true }), false);
});

// ---- health + boot view ----------------------------------------------------------

test("healthOk: 200 with an alive health document only", () => {
  assert.strictEqual(lch.healthOk(200, '{"alive": true, "pid": 1}'), true);
  assert.strictEqual(lch.healthOk(200, '{"alive": false}'), false);
  assert.strictEqual(lch.healthOk(503, '{"alive": true}'), false);
  assert.strictEqual(lch.healthOk(200, "not json"), false);
  assert.strictEqual(lch.healthOk(200, "[true]"), false);
});

test("bootView: a dead host is an error view unless health already answers", () => {
  const starting = { view: "starting", reason: "no-status", degraded: false, failing: [] };
  assert.strictEqual(lch.bootView({ view: starting, hostEnabled: true, hostRunning: false, hostExitCode: 2 }).reason, "host-exit-2");
  assert.strictEqual(lch.bootView({ view: starting, hostEnabled: true, hostRunning: true, hostExitCode: null }).view, "starting");
  const app = { view: "app", reason: "health-ok", degraded: false, failing: [] };
  assert.strictEqual(lch.bootView({ view: app, hostEnabled: true, hostRunning: false, hostExitCode: 1 }).view, "app");
  assert.strictEqual(
    lch.bootView({ view: starting, hostEnabled: true, hostRunning: false, hostExitCode: 3 }).view,
    "starting",
    "exit 3 = another host owns the services; keep waiting on its status"
  );
});

test("statusHostPid: the status file is filtered by our host pid, except when another host owns it", () => {
  assert.strictEqual(lch.statusHostPid({ hostPid: 77, hostExitCode: null }), 77);
  assert.strictEqual(lch.statusHostPid({ hostPid: 77, hostExitCode: 3 }), null);
  assert.strictEqual(lch.statusHostPid({ hostPid: null, hostExitCode: null }), null);
});

test("startingModel: ASCII text for each view, service rows from the status file", () => {
  const status = svc.parseStatus(
    JSON.stringify({
      schema: 1,
      updated: 1800000000,
      mode: "owned",
      host_pid: 5,
      services: [{ name: "supervisor", state: "running" }, { name: "lcu_agent", state: "failed", last_error: "boom" }],
    }),
    { now: 1800000000 * 1000 }
  );
  const view = svc.shellView({ status, healthOk: false, sinceLaunchMs: 10, hostPid: 5 });
  const m = lch.startingModel(view, status);
  assert.strictEqual(m.view, "error");
  assert.ok(/lcu_agent/.test(m.detail));
  assert.strictEqual(m.rows.length, 2);
  for (const s of [m.title, m.detail].concat(m.rows.map((r) => r.name + r.row + r.word))) {
    assert.ok(/^[\x20-\x7e]*$/.test(s), "printable ASCII only: " + s);
  }
  const start = lch.startingModel({ view: "starting", reason: "no-status", failing: [] }, null);
  assert.strictEqual(start.view, "starting");
  assert.deepStrictEqual(start.rows, []);
  const dead = lch.startingModel({ view: "error", reason: "host-exit-2", failing: [] }, null);
  assert.ok(/code 2/.test(dead.detail));
});

// ---- starting page (DOM stub) ------------------------------------------------------

function fakeDoc() {
  const make = (tag) => ({
    tag,
    className: "",
    textContent: "",
    children: [],
    get firstChild() {
      return this.children[0] || null;
    },
    appendChild(c) {
      this.children.push(c);
      return c;
    },
    removeChild(c) {
      this.children.splice(this.children.indexOf(c), 1);
      return c;
    },
  });
  const ids = { view: make("main"), title: make("h1"), detail: make("p"), rows: make("ul") };
  return { ids, getElementById: (id) => ids[id] || null, createElement: make };
}

test("starting_page.render: text only - markup in the model is never interpreted", () => {
  const page = require("../src/starting_page");
  const doc = fakeDoc();
  doc.ids.rows.appendChild({ tag: "li" }); // a previous render's row is replaced
  const ok = page.render(doc, {
    view: "error",
    title: "<b>t</b>",
    detail: "d",
    rows: [{ name: "<img src=x>", row: "[x]", word: "failed" }, null],
  });
  assert.strictEqual(ok, true);
  assert.strictEqual(doc.ids.view.className, "error");
  assert.strictEqual(doc.ids.title.textContent, "<b>t</b>");
  assert.strictEqual(doc.ids.rows.children.length, 1);
  assert.strictEqual(doc.ids.rows.children[0].textContent, "[x] <img src=x> ");
  assert.strictEqual(doc.ids.rows.children[0].children[0].textContent, "failed");
  assert.strictEqual(page.render(doc, null), false);
  const pageSrc = fs.readFileSync(path.join(SRC, "starting_page.js"), "utf8");
  assert.ok(!/innerHTML|outerHTML|insertAdjacentHTML|document\.write/.test(pageSrc), "no HTML sinks");
});

// ---- relaunch when idle ----------------------------------------------------------

test("relaunchDecision: only an armed, downloaded shell update, on a fresh not-in-game state", () => {
  const ok = { pending: "1.2.0", armed: true, inGame: false, stateFresh: true };
  assert.deepStrictEqual(lch.relaunchDecision(ok), { relaunch: true, reason: "idle" });
  assert.strictEqual(lch.relaunchDecision(Object.assign({}, ok, { pending: null })).reason, "no-update");
  assert.strictEqual(lch.relaunchDecision(Object.assign({}, ok, { armed: false })).reason, "not-armed");
  assert.strictEqual(lch.relaunchDecision(Object.assign({}, ok, { stateFresh: false })).reason, "state-unknown");
  assert.strictEqual(lch.relaunchDecision(Object.assign({}, ok, { inGame: true })).reason, "game-live");
});

// ---- state-file migration (S6) ---------------------------------------------------

test("userDataMigration: copy the old rc-shell state once into the productName folder", () => {
  const appData = path.join(BASE, "appdata");
  const oldFile = path.join(appData, "rc-shell", "rc-shell-state.json");
  const newDir = path.join(appData, "Amberstone Shell");
  const newFile = path.join(newDir, "rc-shell-state.json");
  const m = lch.userDataMigration({ userDataDir: newDir, appDataDir: appData, probe: fakeFs([oldFile]) });
  assert.deepStrictEqual(m, { migrate: true, from: oldFile, to: newFile, reason: "migrate" });
  assert.strictEqual(
    lch.userDataMigration({ userDataDir: newDir, appDataDir: appData, probe: fakeFs([oldFile, newFile]) }).reason,
    "already-migrated"
  );
  assert.strictEqual(lch.userDataMigration({ userDataDir: newDir, appDataDir: appData, probe: fakeFs([]) }).reason, "nothing-to-migrate");
  assert.strictEqual(
    lch.userDataMigration({ userDataDir: path.join(appData, "rc-shell"), appDataDir: appData, probe: fakeFs([oldFile]) }).reason,
    "same-dir"
  );
});

// ---- TLS mode + pin refresh ------------------------------------------------------

test("pollTlsMode: plain http, pinned https, or normal verification without a pin", () => {
  assert.strictEqual(lch.pollTlsMode("http://127.0.0.1:8888", []), "plain");
  assert.strictEqual(lch.pollTlsMode(ORIGIN, ["a".repeat(64)]), "pin");
  assert.strictEqual(lch.pollTlsMode(ORIGIN, []), "verify");
  assert.strictEqual(lch.pollTlsMode("ftp://x", []), "invalid");
  assert.strictEqual(lch.pollTlsMode("", []), "invalid");
});

test("refreshDue: a secret file is re-read at most once per refresh window", () => {
  assert.strictEqual(lch.refreshDue(null, 1000), true);
  assert.strictEqual(lch.refreshDue(1000, 1000 + lch.SECRET_REFRESH_MS - 1), false);
  assert.strictEqual(lch.refreshDue(1000, 1000 + lch.SECRET_REFRESH_MS), true);
});

test("quitNeedsHostStop: hold the quit only while an owned host still runs", () => {
  assert.strictEqual(lch.quitNeedsHostStop({ running: true, stopped: false }), true);
  assert.strictEqual(lch.quitNeedsHostStop({ running: true, stopped: true }), false);
  assert.strictEqual(lch.quitNeedsHostStop({ running: false, stopped: false }), false);
});

// ---- main.js wiring (source contract) --------------------------------------------

function fnBody(name) {
  const at = MAIN_SRC.indexOf("function " + name + "(");
  assert.ok(at !== -1, "main.js defines " + name);
  const rest = MAIN_SRC.slice(at);
  return rest.slice(0, rest.indexOf("\n}\n"));
}

test("main.js: the hotkey signal files come from rc_root, never from __dirname (M3)", () => {
  assert.ok(!/__dirname,\s*"\.\.",\s*"\.\.",\s*"ops"/.test(MAIN_SRC), "no __dirname/../../ops path left");
  assert.ok(MAIN_SRC.includes("rcRoot.signalPaths(backendRoot)"), "signal paths from the resolved root");
  assert.ok(MAIN_SRC.includes("rcRoot.resolveRcRoot("), "the root is resolved, not derived");
  assert.ok(MAIN_SRC.includes("lch.bundledBackendDir(process.resourcesPath)"), "packaged root = resources/backend");
});

test("main.js: the service host is spawned from the pure plan, windowless, with a stdin quit channel", () => {
  const body = fnBody("startServiceHost");
  assert.ok(body.includes("lch.hostLaunchPlan("), "the plan decides");
  assert.ok(body.includes("windowsHide: true"), "no console window");
  assert.ok(/stdio:\s*\[\s*"pipe"/.test(body), "stdin is the quit channel");
  assert.ok(MAIN_SRC.includes("startServiceHost();"), "called at launch");
});

test("main.js: quit stops the host first (stop line, bounded grace, then kill)", () => {
  const stop = fnBody("stopServiceHost");
  assert.ok(stop.includes('.write("stop\\n")'), "the documented stop line");
  assert.ok(stop.includes("lch.HOST_STOP_GRACE_MS"), "bounded wait");
  assert.ok(stop.includes(".kill()"), "a host that does not exit is ended (its job object takes the services)");
  assert.ok(/app\.on\("before-quit"/.test(MAIN_SRC), "a before-quit hook exists");
  const hook = MAIN_SRC.slice(MAIN_SRC.indexOf('app.on("before-quit"'));
  assert.ok(hook.slice(0, 600).includes("lch.quitNeedsHostStop("), "the hook holds the quit only while needed");
});

test("main.js: certificate trust and the https poll go through the leaf pin (S1)", () => {
  const cert = MAIN_SRC.slice(MAIN_SRC.indexOf('app.on("certificate-error"'));
  const certBody = cert.slice(0, cert.indexOf("\n});\n"));
  assert.ok(certBody.includes("pinTrust("), "certificate-error asks the pin");
  assert.ok(!certBody.includes("host === originHost"), "the any-cert-for-the-host rule is gone");
  assert.ok(fnBody("pinTrust").includes("tls.pinDecision("), "through tls_pin.pinDecision");
  const poll = fnBody("originRequest");
  assert.ok(poll.includes("lch.pollTlsMode("), "the request picks plain / pin / verify");
  assert.ok(poll.includes("getPeerCertificate"), "a pinned response is checked before it is read");
  assert.ok(fnBody("pollState").includes("originRequest("), "the state poll uses the pinned request");
});

test("main.js: every rcShell IPC channel checks its sender (S3)", () => {
  const re = /ipcMain\.(?:handle|on)\("(rc-shell:[^"]+)",\s*\(([^)]*)\)\s*=>\s*\{([\s\S]*?)\n  \}\);/g;
  let m;
  let count = 0;
  while ((m = re.exec(MAIN_SRC)) !== null) {
    count += 1;
    const head = m[3].split("\n").slice(0, 4).join("\n");
    const guarded = head.includes("trustedSender(") || head.includes("event.sender !== toggleWindow.webContents");
    assert.ok(guarded, m[1] + " checks its sender first");
  }
  assert.ok(count >= 12, "found the IPC handlers (" + count + ")");
  assert.ok(fnBody("trustedSender").includes("lch.senderAllowed("), "through the pure rule");
});

test("main.js: X-RC-Token is injected for the own origin only", () => {
  assert.ok(MAIN_SRC.includes("onBeforeSendHeaders("), "a request hook exists");
  assert.ok(fnBody("installTokenHeader").includes("lch.withTokenHeader("), "through the pure own-origin rule");
});

test("main.js: the token hook sees EVERY url and fails closed (SF1)", () => {
  const body = fnBody("installTokenHeader");
  // No filter argument: a URL filter would skip the foreign hop of a redirect,
  // and the strip would never run on it.
  assert.ok(/onBeforeSendHeaders\(\(details, callback\) =>/.test(body), "registered without a URL filter");
  assert.strictEqual((MAIN_SRC.match(/onBeforeSendHeaders\(/g) || []).length, 1, "one hook, no second unfiltered path");
  const catchBody = body.slice(body.indexOf("catch"));
  assert.ok(catchBody.includes("lch.stripTokenHeader("), "an error strips the header, never forwards it");
});

test("main.js: will-redirect and will-frame-navigate apply the navigation policy (V2)", () => {
  const body = fnBody("guardNavigation");
  assert.ok(body.includes('"will-redirect"'), "redirects are checked");
  assert.ok(body.includes('"will-frame-navigate"'), "frame navigations are checked");
});

test("main.js: the origin resolves with the per-host allow-list and the host-served origin (S2, M4)", () => {
  const body = fnBody("resolveShellConfig");
  assert.ok(body.includes("cfgmod.resolveConfig("), "one resolver");
  assert.ok(body.includes("localHosts"), "localHosts passed");
  assert.ok(body.includes("servedOrigin"), "the host-served origin is passed");
  assert.strictEqual((MAIN_SRC.match(/cfgmod\.resolveConfig\(/g) || []).length, 1, "no second, unvalidated resolve");
  assert.ok(fnBody("bootTick").includes("resolveShellConfig("), "the boot watch resolves with the served origin");
});

test("main.js: a starting view is shown until /api/health answers", () => {
  assert.ok(MAIN_SRC.includes("svc.shellView("), "the pure view decision");
  assert.ok(MAIN_SRC.includes('"starting.html"'), "the local starting page");
  assert.ok(fs.existsSync(path.join(SRC, "starting.html")), "starting.html exists");
  const page = fs.readFileSync(path.join(SRC, "starting.html"), "utf8");
  assert.ok(page.includes("Content-Security-Policy"), "the starting page carries a CSP");
  assert.ok(!/<script>/.test(page), "no inline script");
});

test("main.js: shell updates relaunch only when idle, through the pure decision", () => {
  assert.ok(MAIN_SRC.includes("lch.relaunchDecision("), "pure decision");
  assert.ok(MAIN_SRC.includes("quitAndInstall("), "the relaunch installs");
  const fn = fnBody("maybeRelaunchForUpdate");
  assert.ok(fn.indexOf("stopServiceHost(") < fn.indexOf("quitAndInstall("), "the host stops before the installer runs");
});

test("main.js + builder: the app user model id equals the builder appId (N3)", () => {
  const id = /^appId:\s*(\S+)\s*$/m.exec(BUILDER_YML)[1];
  assert.ok(MAIN_SRC.includes('app.setAppUserModelId("' + id + '")'));
});

// ---- never at login (intent 3) ----------------------------------------------------

test("no shell code or builder option starts the app at login or boot", () => {
  const banned = [/setLoginItemSettings/, /openAtLogin/, /CurrentVersion\\\\Run/i, /Startup\\\\/i, /schtasks/i];
  for (const f of fs.readdirSync(SRC)) {
    const text = fs.readFileSync(path.join(SRC, f), "utf8");
    for (const re of banned) {
      assert.ok(!re.test(text), f + " must not match " + re);
    }
  }
  for (const re of [/runAtStartup/i, /openAtLogin/i, /^\s*include:/m, /^\s*script:/m, /CurrentVersion/i]) {
    assert.ok(!re.test(BUILDER_YML), "electron-builder.yml must not match " + re);
  }
});

// ---- builder + package -----------------------------------------------------------

test("builder: extraResources carry the built backend (with python-embed) to resources/backend", () => {
  assert.ok(/extraResources:/.test(BUILDER_YML));
  assert.ok(/from:\s*\.\.\/dist\/portable_staging/.test(BUILDER_YML), "from the PKG-4 staging folder");
  assert.ok(/to:\s*backend\b/.test(BUILDER_YML), "to resources/backend (lch.BUNDLED_BACKEND_DIR)");
  assert.strictEqual(lch.BUNDLED_BACKEND_DIR, "backend");
});

test("builder + package: productName aligned (S6) and an RC-own icon declared (S5)", () => {
  const product = /^productName:\s*(.+?)\s*$/m.exec(BUILDER_YML)[1];
  assert.strictEqual(PKG.productName, product);
  const icon = /^\s*icon:\s*(\S+)\s*$/m.exec(BUILDER_YML);
  assert.ok(icon, "an icon is declared");
  const iconPath = path.join(__dirname, "..", icon[1]);
  assert.ok(fs.existsSync(iconPath), "the icon file is tracked");
  const head = fs.readFileSync(iconPath).subarray(0, 4);
  assert.deepStrictEqual([...head], [0, 0, 1, 0], "a Windows .ico");
});
