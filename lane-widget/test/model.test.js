"use strict";
// Slice A - model.js. Compose repos + locks + proctree + heartbeat into the
// render model slice C paints.
//
// worktreeTail is the BASENAME ONLY. A full sibling worktree path is a sibling
// name, and a sibling name must never reach a rendered surface.

const test = require("node:test");
const assert = require("node:assert/strict");

const { buildModel } = require("../src/model.js");

const NOW = 2000;

function repo(over) {
  return Object.assign(
    {
      code: "RC",
      root: "C:\\Riot Commander",
      isSelf: true,
      lane: { state: "FREE", payload: null, pid: 0 },
      ctrl: { state: "FREE", payload: null, pid: 0 },
      children: 0,
      logs: [],
    },
    over || {}
  );
}

function running(over) {
  return {
    state: "RUNNING",
    pid: 7676,
    payload: Object.assign(
      {
        pid: 7676,
        lane: "queue",
        run_id: "203a23be",
        worktree: "C:\\fake-worktrees\\wt-queue",
        ts: 1700,
      },
      over || {}
    ),
  };
}

const byKey = (m) => Object.fromEntries(m.rows.map((r) => [r.key, r]));

// ------------------------------------------------------------------- shape
test("the model has rows, summary and updatedAt", () => {
  const m = buildModel({ repos: [repo()], now: NOW });
  assert.ok(Array.isArray(m.rows));
  assert.equal(typeof m.summary, "object");
  assert.equal(m.updatedAt, NOW);
});

test("each repo yields a lane row and a controller row", () => {
  const m = buildModel({ repos: [repo()], now: NOW });
  assert.deepEqual(m.rows.map((r) => r.kind), ["lane", "controller"]);
});

test("key is stable across polls and is repoCode:kind", () => {
  const m1 = buildModel({ repos: [repo()], now: NOW });
  const m2 = buildModel({ repos: [repo()], now: NOW + 5 });
  assert.deepEqual(m1.rows.map((r) => r.key), ["RC:lane", "RC:controller"]);
  assert.deepEqual(m1.rows.map((r) => r.key), m2.rows.map((r) => r.key));
});

test("a row carries exactly the contracted fields", () => {
  const m = buildModel({ repos: [repo({ lane: running(), children: 3 })], now: NOW });
  const row = byKey(m)["RC:lane"];
  assert.deepEqual(Object.keys(row).sort(), [
    "ageS", "children", "kind", "key", "label", "lane", "logAgeS",
    "repoCode", "runId", "stalled", "state", "worktreeTail",
  ].sort());
});

// ------------------------------------------------------------------ labels
test("a RUNNING lane row is labelled with the lane name", () => {
  const m = buildModel({ repos: [repo({ lane: running() })], now: NOW });
  assert.equal(byKey(m)["RC:lane"].label, "queue");
  assert.equal(byKey(m)["RC:lane"].lane, "queue");
});

test("a FREE lane row is labelled idle", () => {
  const m = buildModel({ repos: [repo()], now: NOW });
  assert.equal(byKey(m)["RC:lane"].label, "idle");
  assert.equal(byKey(m)["RC:lane"].lane, null);
});

test("a RECLAIMABLE lane keeps its lane name as the label", () => {
  const lane = running();
  lane.state = "RECLAIMABLE";
  const m = buildModel({ repos: [repo({ lane })], now: NOW });
  assert.equal(byKey(m)["RC:lane"].state, "RECLAIMABLE");
  assert.equal(byKey(m)["RC:lane"].label, "queue");
});

test("a hyphenated lane id survives intact", () => {
  const m = buildModel({
    repos: [repo({ lane: running({ lane: "true-audit", run_id: "5e9c917b" }) })],
    now: NOW,
  });
  const row = byKey(m)["RC:lane"];
  assert.equal(row.lane, "true-audit");
  assert.equal(row.label, "true-audit");
  assert.equal(row.runId, "5e9c917b");
});

test("a controller row is labelled controller and carries no lane name", () => {
  const ctrl = { state: "RUNNING", pid: 9932, payload: { pid: 9932, ts: 1900 } };
  const m = buildModel({ repos: [repo({ ctrl })], now: NOW });
  const row = byKey(m)["RC:controller"];
  assert.equal(row.label, "controller");
  assert.equal(row.lane, null);
});

// ------------------------------------------------------------ worktreeTail
test("worktreeTail is the BASENAME only, never a full path", () => {
  const m = buildModel({ repos: [repo({ lane: running() })], now: NOW });
  const row = byKey(m)["RC:lane"];
  assert.equal(row.worktreeTail, "wt-queue");
  assert.ok(!row.worktreeTail.includes("\\"));
  assert.ok(!row.worktreeTail.includes("/"));
  assert.ok(!row.worktreeTail.includes(":"));
});

test("worktreeTail splits on BOTH separators and skips trailing empties", () => {
  const cases = [
    ["C:/fake-worktrees/wt-ds", "wt-ds"],
    ["C:\\fake-worktrees\\wt-ds\\", "wt-ds"],
    ["C:/fake-worktrees\\wt-ds//", "wt-ds"],
    ["wt-ds", "wt-ds"],
    ["/wt-ds/", "wt-ds"],
  ];
  for (const [wt, want] of cases) {
    const m = buildModel({ repos: [repo({ lane: running({ worktree: wt }) })], now: NOW });
    assert.equal(byKey(m)["RC:lane"].worktreeTail, want, `wt=${wt}`);
  }
});

test("worktreeTail is null when the worktree is missing or unusable", () => {
  for (const wt of [undefined, null, "", "   ", "///", "\\\\", 42, {}]) {
    const m = buildModel({ repos: [repo({ lane: running({ worktree: wt }) })], now: NOW });
    assert.equal(byKey(m)["RC:lane"].worktreeTail, null, `wt=${String(wt)}`);
  }
});

test("NO row field ever contains a path separator", () => {
  const m = buildModel({
    repos: [repo({ lane: running(), ctrl: running(), children: 2 })],
    now: NOW,
  });
  for (const row of m.rows) {
    for (const [k, v] of Object.entries(row)) {
      if (typeof v !== "string") continue;
      assert.ok(!/[\\/]|^[A-Za-z]:/.test(v), `row.${k} leaks a path: ${v}`);
    }
  }
});

// --------------------------------------------------------------- ages, logs
test("ageS is derived from the payload ts and now", () => {
  const m = buildModel({ repos: [repo({ lane: running() })], now: NOW });
  assert.equal(byKey(m)["RC:lane"].ageS, 300);
});

test("ageS is null when ts is missing or not finite", () => {
  for (const ts of [undefined, null, NaN, Infinity, "x"]) {
    const m = buildModel({ repos: [repo({ lane: running({ ts }) })], now: NOW });
    assert.equal(byKey(m)["RC:lane"].ageS, null, `ts=${String(ts)}`);
  }
});

test("logAgeS and stalled come from the log row matching the lane name", () => {
  const logs = [
    { lane: "queue", runId: "203a23be", name: "lane_queue_203a23be.log",
      mtimeMs: 1e6, ageS: 42, stalled: false },
    { lane: "ds", runId: "x", name: "lane_ds_x.log",
      mtimeMs: 1e6, ageS: 900, stalled: true },
  ];
  const m = buildModel({ repos: [repo({ lane: running(), logs })], now: NOW });
  const row = byKey(m)["RC:lane"];
  assert.equal(row.logAgeS, 42);
  assert.equal(row.stalled, false);
});

test("a stalled log marks the row stalled", () => {
  const logs = [{ lane: "queue", ageS: 900, stalled: true }];
  const m = buildModel({ repos: [repo({ lane: running(), logs })], now: NOW });
  assert.equal(byKey(m)["RC:lane"].stalled, true);
  assert.equal(byKey(m)["RC:lane"].logAgeS, 900);
});

test("no matching log row leaves logAgeS null and stalled false", () => {
  const logs = [{ lane: "ds", ageS: 900, stalled: true }];
  const m = buildModel({ repos: [repo({ lane: running(), logs })], now: NOW });
  assert.equal(byKey(m)["RC:lane"].logAgeS, null);
  assert.equal(byKey(m)["RC:lane"].stalled, false);
});

test("a controller row never claims a log age", () => {
  const logs = [{ lane: "queue", ageS: 10, stalled: true }];
  const m = buildModel({ repos: [repo({ lane: running(), logs })], now: NOW });
  assert.equal(byKey(m)["RC:controller"].logAgeS, null);
  assert.equal(byKey(m)["RC:controller"].stalled, false);
});

test("junk log rows are ignored", () => {
  const logs = [null, 42, "x", {}, { lane: "queue", ageS: "junk", stalled: "yes" }];
  const m = buildModel({ repos: [repo({ lane: running(), logs })], now: NOW });
  const row = byKey(m)["RC:lane"];
  assert.equal(row.logAgeS, null);
  assert.equal(row.stalled, false);
});

// ---------------------------------------------------------------- children
test("children lands on the lane row", () => {
  const m = buildModel({ repos: [repo({ lane: running(), children: 5 })], now: NOW });
  assert.equal(byKey(m)["RC:lane"].children, 5);
  assert.equal(byKey(m)["RC:controller"].children, 0);
});

test("a non-finite children count becomes 0", () => {
  for (const c of [undefined, null, NaN, Infinity, -3, "x", {}]) {
    const m = buildModel({ repos: [repo({ lane: running(), children: c })], now: NOW });
    assert.equal(byKey(m)["RC:lane"].children, 0, `children=${String(c)}`);
  }
});

test("ctrlChildren, when supplied, lands on the controller row", () => {
  const m = buildModel({
    repos: [repo({ lane: running(), children: 5, ctrlChildren: 2 })], now: NOW });
  assert.equal(byKey(m)["RC:controller"].children, 2);
});

// -------------------------------------------------------------------- sort
test("RUNNING first, then RECLAIMABLE, then FREE", () => {
  const free = repo({ code: "AAA", isSelf: false });
  const stale = repo({ code: "BBB", isSelf: false,
    lane: Object.assign(running(), { state: "RECLAIMABLE" }) });
  const live = repo({ code: "CCC", isSelf: false, lane: running() });
  const m = buildModel({ repos: [free, stale, live], now: NOW });
  assert.deepEqual(
    m.rows.filter((r) => r.kind === "lane").map((r) => r.state),
    ["RUNNING", "RECLAIMABLE", "FREE"]
  );
});

test("within a state, repo order wins and RC comes first", () => {
  const rc = repo({ code: "RC", lane: running() });
  const a = repo({ code: "AAA", isSelf: false, lane: running() });
  const b = repo({ code: "BBB", isSelf: false, lane: running() });
  const m = buildModel({ repos: [rc, a, b], now: NOW });
  assert.deepEqual(
    m.rows.filter((r) => r.kind === "lane").map((r) => r.repoCode),
    ["RC", "AAA", "BBB"]
  );
});

test("within a repo and state, lane sorts before controller", () => {
  const rc = repo({ lane: running(), ctrl: running() });
  const m = buildModel({ repos: [rc], now: NOW });
  assert.deepEqual(m.rows.map((r) => r.kind), ["lane", "controller"]);
});

test("the sort is STABLE for fully tied rows", () => {
  const repos = ["RC", "AAA", "BBB", "CCC"].map((code, i) =>
    repo({ code, isSelf: i === 0 }));
  const m = buildModel({ repos, now: NOW });
  assert.deepEqual(
    m.rows.filter((r) => r.kind === "lane").map((r) => r.repoCode),
    ["RC", "AAA", "BBB", "CCC"]
  );
});

test("an unknown state is preserved verbatim and sorts last", () => {
  const odd = repo({ code: "AAA", isSelf: false,
    lane: { state: "UNREADABLE", payload: null, pid: 0 } });
  const free = repo({ code: "BBB", isSelf: false });
  const m = buildModel({ repos: [odd, free], now: NOW });
  const lanes = m.rows.filter((r) => r.kind === "lane");
  assert.deepEqual(lanes.map((r) => r.state), ["FREE", "UNREADABLE"]);
});

// ----------------------------------------------------------------- summary
test("summary counts repos, states, children and stalls", () => {
  const rc = repo({ lane: running(), children: 4,
    logs: [{ lane: "queue", ageS: 900, stalled: true }] });
  const a = repo({ code: "AAA", isSelf: false,
    lane: Object.assign(running({ lane: "ds" }), { state: "RECLAIMABLE" }) });
  const m = buildModel({ repos: [rc, a], now: NOW });
  assert.deepEqual(m.summary, {
    repos: 2, running: 1, reclaimable: 1, free: 2, children: 4, stalled: 1,
  });
});

test("summary children never double counts across rows", () => {
  const m = buildModel({
    repos: [repo({ lane: running(), children: 4, ctrlChildren: 3 })], now: NOW });
  assert.equal(m.summary.children, 7);
});

// ---------------------------------------------------------------- totality
test("zero repos produces a valid empty model", () => {
  const m = buildModel({ repos: [], now: NOW });
  assert.deepEqual(m.rows, []);
  assert.deepEqual(m.summary, {
    repos: 0, running: 0, reclaimable: 0, free: 0, children: 0, stalled: 0,
  });
  assert.equal(m.updatedAt, NOW);
});

test("null, undefined and junk arguments produce a valid empty model", () => {
  for (const arg of [undefined, null, {}, 42, "x", [], { repos: null },
    { repos: "x" }, { repos: 42 }, { repos: {} }]) {
    const m = buildModel(arg);
    assert.ok(Array.isArray(m.rows), `arg=${JSON.stringify(arg)}`);
    assert.equal(m.rows.length, 0);
    assert.equal(m.summary.repos, 0);
  }
});

test("junk repo entries are dropped, not rendered", () => {
  const m = buildModel({ repos: [null, 42, "x", [], repo()], now: NOW });
  assert.equal(m.summary.repos, 1);
  assert.equal(m.rows.length, 2);
});

test("an every-field-missing repo still produces two valid rows", () => {
  const m = buildModel({ repos: [{}], now: NOW });
  assert.equal(m.rows.length, 2);
  for (const row of m.rows) {
    assert.equal(typeof row.key, "string");
    assert.equal(typeof row.repoCode, "string");
    assert.equal(row.state, "FREE");
    assert.equal(row.children, 0);
    assert.equal(row.ageS, null);
    assert.equal(row.logAgeS, null);
    assert.equal(row.stalled, false);
    assert.equal(row.worktreeTail, null);
    assert.equal(row.runId, null);
  }
});

test("a repo with no code still gets a non-leaking placeholder code", () => {
  const m = buildModel({ repos: [{ root: "C:\\fake-a" }], now: NOW });
  const code = m.rows[0].repoCode;
  assert.equal(typeof code, "string");
  assert.ok(code.length > 0);
  assert.ok(!/fake-a/i.test(code));
  assert.ok(!/[\\/:]/.test(code));
});

test("duplicate repo codes are rendered, not dropped", () => {
  // `key` is FROZEN as `${repoCode}:${kind}` by the build contract, so two
  // repos sharing a code share a key. That is safe because resolveRepos cannot
  // emit a duplicate code - participants keys are unique by JSON object
  // semantics and the positional fallback is index-derived. The uniqueness
  // invariant is asserted where it actually lives, in repos.test.js.
  const m = buildModel({
    repos: [repo({ code: "AAA", isSelf: false }), repo({ code: "AAA", isSelf: false })],
    now: NOW,
  });
  assert.equal(m.rows.length, 4);
  assert.equal(m.summary.repos, 2);
});

test("a non-finite now yields a null updatedAt and null ages", () => {
  for (const now of [undefined, null, NaN, Infinity, "x"]) {
    const m = buildModel({ repos: [repo({ lane: running() })], now });
    assert.equal(m.updatedAt, null, `now=${String(now)}`);
    assert.equal(byKey(m)["RC:lane"].ageS, null);
  }
});

test("a lane block that is not an object is treated as FREE", () => {
  for (const lane of [null, undefined, 42, "x", []]) {
    const m = buildModel({ repos: [repo({ lane })], now: NOW });
    assert.equal(byKey(m)["RC:lane"].state, "FREE");
    assert.equal(byKey(m)["RC:lane"].label, "idle");
  }
});

test("buildModel does not mutate the repos it is handed", () => {
  const repos = [repo({ lane: running(), children: 2 })];
  const before = JSON.stringify(repos);
  buildModel({ repos, now: NOW });
  assert.equal(JSON.stringify(repos), before);
});

test("buildModel output is JSON-serialisable for the IPC push", () => {
  const m = buildModel({ repos: [repo({ lane: running(), children: 2 })], now: NOW });
  assert.deepEqual(JSON.parse(JSON.stringify(m)), m);
});
