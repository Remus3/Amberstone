// rc-shell/test/service_status.test.js
//
// PKG-3 (docs/PACKAGING_PLAN.md section 3.1 "Status surface"): parse the
// launcher's ops/runtime/launcher_status.json into kit-vocabulary service
// states and decide which shell view shows (starting / app / error). Pure:
// the clock and the reader are injected. NO electron. Run with: npm test

"use strict";

const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const path = require("path");

const ss = require("../src/service_status");

const NOW = 1_800_000_000_000; // a fixed ms epoch; nothing reads the wall clock
const NOW_S = NOW / 1000;

function doc(over) {
  return Object.assign(
    {
      schema: 1,
      updated: NOW_S - 2,
      mode: "owned",
      host_pid: 4242,
      origin: "http://127.0.0.1:8888",
      services: {
        supervisor: { state: "running", pid: 100, port: null, restarts: 0, last_error: null },
        dashboard: { state: "running", pid: 101, port: 8888, restarts: 1, last_error: "" },
        lcu_agent: { state: "pending", pid: null, port: null, restarts: 0 },
      },
    },
    over || {}
  );
}

const parse = (d, opts) =>
  ss.parseStatus(typeof d === "string" ? d : JSON.stringify(d), Object.assign({ now: NOW }, opts || {}));

// ---- kit vocabulary ----------------------------------------------------------

test("KIT_STATES mirrors ops/fleet_kit/tokens.json states (word + row + glyph)", () => {
  const tokens = JSON.parse(
    fs.readFileSync(path.join(__dirname, "..", "..", "ops", "fleet_kit", "tokens.json"), "utf8")
  );
  const kit = Object.assign({}, tokens.states);
  delete kit._README;
  assert.deepStrictEqual(Object.keys(ss.KIT_STATES).sort(), Object.keys(kit).sort());
  for (const [name, v] of Object.entries(kit)) {
    assert.strictEqual(ss.KIT_STATES[name].word, v.word, name);
    assert.strictEqual(ss.KIT_STATES[name].row, v.row, name);
    assert.strictEqual(ss.KIT_STATES[name].glyph, v.glyph, name);
  }
  assert.ok(Object.isFrozen(ss.KIT_STATES));
});

test("STATUS_FILE_NAME is the launcher status file the host writes", () => {
  assert.strictEqual(ss.STATUS_FILE_NAME, "launcher_status.json");
});

// ---- parseStatus: happy path ---------------------------------------------------

test("parseStatus: a well-formed owned-mode document", () => {
  const r = parse(doc());
  assert.strictEqual(r.ok, true);
  assert.strictEqual(r.reason, "ok");
  assert.strictEqual(r.mode, "owned");
  assert.strictEqual(r.hostPid, 4242);
  assert.strictEqual(r.origin, "http://127.0.0.1:8888");
  assert.strictEqual(r.stale, false);
  assert.strictEqual(r.ageMs, 2000);
  assert.deepStrictEqual(r.services, [
    { name: "supervisor", state: "running", unknownState: false, pid: 100, port: null, restarts: 0, lastError: "" },
    { name: "dashboard", state: "running", unknownState: false, pid: 101, port: 8888, restarts: 1, lastError: "" },
    { name: "lcu_agent", state: "pending", unknownState: false, pid: null, port: null, restarts: 0, lastError: "" },
  ]);
  assert.strictEqual(r.overall, "pending"); // worst of running, running, pending
});

test("parseStatus: services may also be a list of {name, ...}", () => {
  const r = parse(
    doc({ services: [{ name: "supervisor", state: "running", restart_count: 3, error: "boom" }] })
  );
  assert.strictEqual(r.ok, true);
  assert.deepStrictEqual(r.services, [
    { name: "supervisor", state: "running", unknownState: false, pid: null, port: null, restarts: 3, lastError: "boom" },
  ]);
  assert.strictEqual(r.overall, "running");
});

test("parseStatus: updated may be epoch seconds, epoch ms or ISO-8601", () => {
  assert.strictEqual(parse(doc({ updated: NOW_S - 5 })).ageMs, 5000);
  assert.strictEqual(parse(doc({ updated: NOW - 5000 })).ageMs, 5000);
  assert.strictEqual(parse(doc({ updated: new Date(NOW - 7000).toISOString() })).ageMs, 7000);
});

test("parseStatus: state words are case-insensitive kit states", () => {
  const r = parse(doc({ services: { a: { state: "  RUNNING " }, b: { state: "Needs-Operator" } } }));
  assert.deepStrictEqual(
    r.services.map((s) => s.state),
    ["running", "needs-operator"]
  );
});

// ---- parseStatus: aggregation ------------------------------------------------------

test("overall: the worst service state wins (failed > stale > blocked > ... > idle)", () => {
  const order = ["failed", "stale", "blocked", "needs-operator", "halted", "pending", "fallback", "running", "done", "idle"];
  assert.deepStrictEqual(ss.SEVERITY_ORDER, order);
  for (let i = 0; i < order.length; i += 1) {
    const services = {};
    for (let j = i; j < order.length; j += 1) {
      services["s" + j] = { state: order[j] };
    }
    assert.strictEqual(parse(doc({ services })).overall, order[i], order[i]);
  }
});

test("overall: an idle / done optional service does not hold readiness back", () => {
  const r = parse(doc({ services: { a: { state: "running" }, dev_only: { state: "idle" }, oneshot: { state: "done" } } }));
  assert.strictEqual(r.overall, "running");
});

test("overall: no services = idle in attach mode, pending when owned", () => {
  assert.strictEqual(parse(doc({ mode: "attach", services: {} })).overall, "idle");
  assert.strictEqual(parse(doc({ mode: "owned", services: {} })).overall, "pending");
});

test("an unknown state word is pending + flagged, never running or failed", () => {
  const r = parse(doc({ services: { a: { state: "warming-up" }, b: { state: 7 } } }));
  assert.deepStrictEqual(
    r.services.map((s) => [s.state, s.unknownState]),
    [
      ["pending", true],
      ["pending", true],
    ]
  );
  assert.strictEqual(r.overall, "pending");
});

// ---- parseStatus: staleness --------------------------------------------------------

test("stale: an old heartbeat makes the whole file stale", () => {
  const r = parse(doc({ updated: NOW_S - 31 }));
  assert.strictEqual(r.ok, true);
  assert.strictEqual(r.stale, true);
  assert.strictEqual(r.overall, "stale");
  assert.strictEqual(parse(doc({ updated: NOW_S - 31 }), { staleAfterMs: 60000 }).stale, false);
});

test("stale: missing, unparsable or far-future updated is stale", () => {
  for (const updated of [undefined, null, "yesterday", NaN, {}, NOW_S + 3600]) {
    const r = parse(doc({ updated }));
    assert.strictEqual(r.stale, true, String(updated));
    assert.strictEqual(r.overall, "stale", String(updated));
  }
  // a little clock skew is tolerated
  assert.strictEqual(parse(doc({ updated: NOW_S + 5 })).stale, false);
});

// ---- parseStatus: hostile / broken input -------------------------------------------------

test("parseStatus: empty / malformed / non-object / oversized input is not ok", () => {
  assert.strictEqual(ss.parseStatus("", { now: NOW }).reason, "empty");
  assert.strictEqual(ss.parseStatus(undefined, { now: NOW }).reason, "empty");
  assert.strictEqual(ss.parseStatus("{ nope", { now: NOW }).reason, "malformed");
  assert.strictEqual(ss.parseStatus("[1]", { now: NOW }).reason, "not-an-object");
  assert.strictEqual(ss.parseStatus("null", { now: NOW }).reason, "not-an-object");
  const big = JSON.stringify(doc({ pad: "x".repeat(ss.MAX_STATUS_BYTES) }));
  assert.strictEqual(ss.parseStatus(big, { now: NOW }).reason, "too-large");
  for (const r of [ss.parseStatus("", { now: NOW }), ss.parseStatus(big, { now: NOW })]) {
    assert.strictEqual(r.ok, false);
    assert.deepStrictEqual(r.services, []);
    assert.strictEqual(r.overall, null);
  }
});

test("parseStatus: an unknown schema version is refused (fail closed)", () => {
  assert.strictEqual(parse(doc({ schema: 2 })).reason, "unsupported-schema");
  assert.strictEqual(parse(doc({ schema: "1" })).reason, "unsupported-schema");
  assert.strictEqual(parse(doc({ schema: undefined })).ok, true); // absent = v1
});

test("parseStatus: bad names are dropped; the service list is capped", () => {
  const services = { "ok-name.1": { state: "running" }, "bad name": { state: "failed" }, "": { state: "failed" } };
  services["x".repeat(65)] = { state: "failed" };
  services["../evil"] = { state: "failed" };
  const r = parse(doc({ services }));
  assert.deepStrictEqual(r.services.map((s) => s.name), ["ok-name.1"]);
  assert.strictEqual(r.overall, "running");

  const many = {};
  for (let i = 0; i < ss.MAX_SERVICES + 5; i += 1) {
    many["s" + i] = { state: "running" };
  }
  const r2 = parse(doc({ services: many }));
  assert.strictEqual(r2.services.length, ss.MAX_SERVICES);
  assert.strictEqual(r2.truncated, true);
});

test("parseStatus: list entries that are not objects, or duplicate names, are dropped", () => {
  const r = parse(doc({ services: [null, 5, "x", { name: "a", state: "running" }, { name: "a", state: "failed" }] }));
  assert.deepStrictEqual(r.services.map((s) => [s.name, s.state]), [["a", "running"]]);
});

test("parseStatus: pid / port / restarts are range-checked integers", () => {
  const r = parse(
    doc({
      services: {
        a: { state: "running", pid: -1, port: 70000, restarts: -3 },
        b: { state: "running", pid: 1.5, port: "8888", restarts: "2" },
        c: { state: "running", pid: 77, port: 8860, restarts: 4 },
      },
    })
  );
  assert.deepStrictEqual(
    r.services.map((s) => [s.pid, s.port, s.restarts]),
    [
      [null, null, 0],
      [null, null, 0],
      [77, 8860, 4],
    ]
  );
  assert.strictEqual(parse(doc({ host_pid: "x" })).hostPid, null);
});

test("parseStatus: last_error is single-line printable ASCII, capped", () => {
  // the non-ASCII dash is built from its code point so this source stays ASCII
  const raw =
    "line1\nline2\r\t" + String.fromCharCode(0) + "end " + String.fromCharCode(0x2014) +
    " dash " + "y".repeat(ss.MAX_ERROR_CHARS * 2);
  const r = parse(doc({ services: { a: { state: "failed", last_error: raw } } }));
  const e = r.services[0].lastError;
  assert.ok(e.length <= ss.MAX_ERROR_CHARS, String(e.length));
  assert.ok(/^[\x20-\x7e]*$/.test(e), "printable ASCII only");
  assert.ok(e.startsWith("line1 line2"), e.slice(0, 20));
  assert.strictEqual(parse(doc({ services: { a: { state: "failed", last_error: { x: 1 } } } })).services[0].lastError, "");
});

test("parseStatus: origin is passed through as a trimmed, capped string only", () => {
  assert.strictEqual(parse(doc({ origin: "  http://127.0.0.1:8888  " })).origin, "http://127.0.0.1:8888");
  assert.strictEqual(parse(doc({ origin: 5 })).origin, null);
  assert.strictEqual(parse(doc({ origin: "h".repeat(300) })).origin, null);
  assert.strictEqual(parse(doc({ mode: "weird" })).mode, null);
});

// ---- readStatus -------------------------------------------------------------------------

test("readStatus: an unreadable file is 'absent'; the reader is injected", () => {
  const r = ss.readStatus("x.json", {
    now: NOW,
    readFile: () => {
      throw new Error("ENOENT");
    },
  });
  assert.strictEqual(r.ok, false);
  assert.strictEqual(r.reason, "absent");
  const r2 = ss.readStatus("x.json", { now: NOW, readFile: () => JSON.stringify(doc()) });
  assert.strictEqual(r2.ok, true);
  assert.strictEqual(ss.readStatus(null, { now: NOW, readFile: () => "{}" }).reason, "absent");
});

// ---- shellView --------------------------------------------------------------------------

test("shellView: /api/health answering means the normal surfaces (app)", () => {
  const v = ss.shellView({ status: parse(doc()), healthOk: true });
  assert.strictEqual(v.view, "app");
  assert.strictEqual(v.degraded, false);
  assert.deepStrictEqual(v.failing, []);
});

test("shellView: app view still names failing services (degraded banner)", () => {
  const status = parse(doc({ services: { dashboard: { state: "running" }, lcu_agent: { state: "failed" }, relay: { state: "blocked" } } }));
  const v = ss.shellView({ status, healthOk: true });
  assert.strictEqual(v.view, "app");
  assert.strictEqual(v.degraded, true);
  assert.deepStrictEqual(v.failing, ["lcu_agent", "relay"]);
});

test("shellView: attach mode with no status file but a healthy origin is the app", () => {
  const v = ss.shellView({ status: ss.parseStatus("", { now: NOW }), healthOk: true });
  assert.strictEqual(v.view, "app");
  assert.strictEqual(v.degraded, false);
});

test("shellView: before health answers, a progressing host shows the starting view", () => {
  for (const state of ["pending", "running", "halted", "fallback"]) {
    const v = ss.shellView({ status: parse(doc({ services: { a: { state } } })), healthOk: false, sinceLaunchMs: 1000 });
    assert.strictEqual(v.view, "starting", state);
  }
});

test("shellView: a failed / blocked / needs-operator host shows the error view", () => {
  for (const state of ["failed", "blocked", "needs-operator"]) {
    const v = ss.shellView({ status: parse(doc({ services: { supervisor: { state } } })), healthOk: false, sinceLaunchMs: 1000 });
    assert.strictEqual(v.view, "error", state);
    assert.deepStrictEqual(v.failing, ["supervisor"], state);
    assert.strictEqual(v.reason, "service-" + state);
  }
});

test("shellView: no / stale / foreign status is 'starting' until the start timeout", () => {
  const absent = ss.parseStatus("", { now: NOW });
  const stale = parse(doc({ updated: NOW_S - 600, services: { a: { state: "failed" } } }));
  const foreign = parse(doc({ host_pid: 1, services: { a: { state: "failed" } } }));
  for (const status of [absent, stale, foreign]) {
    const early = ss.shellView({ status, healthOk: false, sinceLaunchMs: 5000, hostPid: 4242 });
    assert.strictEqual(early.view, "starting");
    const late = ss.shellView({ status, healthOk: false, sinceLaunchMs: ss.START_TIMEOUT_MS + 1, hostPid: 4242 });
    assert.strictEqual(late.view, "error");
    assert.strictEqual(late.reason, "start-timeout");
  }
});

test("shellView: a matching host pid is trusted; no pid given trusts the file", () => {
  const status = parse(doc({ services: { a: { state: "failed" } } }));
  assert.strictEqual(ss.shellView({ status, healthOk: false, sinceLaunchMs: 1, hostPid: 4242 }).view, "error");
  assert.strictEqual(ss.shellView({ status, healthOk: false, sinceLaunchMs: 1 }).view, "error");
});

test("shellView: garbage never throws and never claims the app view", () => {
  for (const v of [undefined, null, 42, "x", {}, { status: "nope" }, { status: null, healthOk: "yes" }]) {
    const r = ss.shellView(v);
    assert.notStrictEqual(r.view, "app", JSON.stringify(v));
    assert.ok(["starting", "error"].includes(r.view));
  }
});

// ---- describe (status rows for the starting view) ------------------------------------------

test("describe: one kit-vocabulary row per service, ASCII only", () => {
  const status = parse(doc({ services: { supervisor: { state: "running" }, lcu_agent: { state: "needs-operator" } } }));
  assert.deepStrictEqual(ss.describe(status), [
    { name: "supervisor", state: "running", row: "[>]", word: "running", token: "running" },
    { name: "lcu_agent", state: "needs-operator", row: "[?]", word: "needs you", token: "warn" },
  ]);
  assert.deepStrictEqual(ss.describe(null), []);
  assert.deepStrictEqual(ss.describe(ss.parseStatus("", { now: NOW })), []);
});

test("contract: service_status.js is electron-free with no require beyond fs", () => {
  const src = fs.readFileSync(path.join(__dirname, "..", "src", "service_status.js"), "utf8");
  const reqs = [...src.matchAll(/require\(["']([^"']+)["']\)/g)].map((m) => m[1]).sort();
  assert.deepStrictEqual(reqs, ["fs"]);
});
