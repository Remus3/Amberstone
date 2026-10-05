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
  assert.deepEqual(m1.rows.map((r) => r.key), ["RC:lane:0", "RC:controller"]);
  assert.deepEqual(m1.rows.map((r) => r.key), m2.rows.map((r) => r.key));
});

test("a row carries exactly the contracted fields", () => {
  const m = buildModel({ repos: [repo({ lane: running(), children: 3 })], now: NOW });
  const row = byKey(m)["RC:lane:0"];
  assert.deepEqual(Object.keys(row).sort(), [
    "ageS", "children", "kind", "key", "label", "lane", "laneIndex", "logAgeS",
    "repoCode", "runId", "stalled", "state", "worktreeTail",
  ].sort());
});

// ------------------------------------------------------------------ labels
test("a RUNNING lane row is labelled with the lane name", () => {
  const m = buildModel({ repos: [repo({ lane: running() })], now: NOW });
  assert.equal(byKey(m)["RC:lane:0"].label, "queue");
  assert.equal(byKey(m)["RC:lane:0"].lane, "queue");
});

test("a FREE lane row is labelled idle", () => {
  const m = buildModel({ repos: [repo()], now: NOW });
  assert.equal(byKey(m)["RC:lane:0"].label, "idle");
  assert.equal(byKey(m)["RC:lane:0"].lane, null);
});

test("a RECLAIMABLE lane keeps its lane name as the label", () => {
  const lane = running();
  lane.state = "RECLAIMABLE";
  const m = buildModel({ repos: [repo({ lane })], now: NOW });
  assert.equal(byKey(m)["RC:lane:0"].state, "RECLAIMABLE");
  assert.equal(byKey(m)["RC:lane:0"].label, "queue");
});

test("a hyphenated lane id survives intact", () => {
  const m = buildModel({
    repos: [repo({ lane: running({ lane: "true-audit", run_id: "5e9c917b" }) })],
    now: NOW,
  });
  const row = byKey(m)["RC:lane:0"];
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
  const row = byKey(m)["RC:lane:0"];
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
    assert.equal(byKey(m)["RC:lane:0"].worktreeTail, want, `wt=${wt}`);
  }
});

test("worktreeTail is null when the worktree is missing or unusable", () => {
  for (const wt of [undefined, null, "", "   ", "///", "\\\\", 42, {}]) {
    const m = buildModel({ repos: [repo({ lane: running({ worktree: wt }) })], now: NOW });
    assert.equal(byKey(m)["RC:lane:0"].worktreeTail, null, `wt=${String(wt)}`);
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
  assert.equal(byKey(m)["RC:lane:0"].ageS, 300);
});

test("ageS is null when ts is missing or not finite", () => {
  for (const ts of [undefined, null, NaN, Infinity, "x"]) {
    const m = buildModel({ repos: [repo({ lane: running({ ts }) })], now: NOW });
    assert.equal(byKey(m)["RC:lane:0"].ageS, null, `ts=${String(ts)}`);
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
  const row = byKey(m)["RC:lane:0"];
  assert.equal(row.logAgeS, 42);
  assert.equal(row.stalled, false);
});

test("a stalled log marks the row stalled", () => {
  const logs = [{ lane: "queue", ageS: 900, stalled: true }];
  const m = buildModel({ repos: [repo({ lane: running(), logs })], now: NOW });
  assert.equal(byKey(m)["RC:lane:0"].stalled, true);
  assert.equal(byKey(m)["RC:lane:0"].logAgeS, 900);
});

test("no matching log row leaves logAgeS null and stalled false", () => {
  const logs = [{ lane: "ds", ageS: 900, stalled: true }];
  const m = buildModel({ repos: [repo({ lane: running(), logs })], now: NOW });
  assert.equal(byKey(m)["RC:lane:0"].logAgeS, null);
  assert.equal(byKey(m)["RC:lane:0"].stalled, false);
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
  const row = byKey(m)["RC:lane:0"];
  assert.equal(row.logAgeS, null);
  assert.equal(row.stalled, false);
});

// ---------------------------------------------------------------- children
test("children lands on the lane row", () => {
  const m = buildModel({ repos: [repo({ lane: running(), children: 5 })], now: NOW });
  assert.equal(byKey(m)["RC:lane:0"].children, 5);
  assert.equal(byKey(m)["RC:controller"].children, 0);
});

test("a non-finite children count becomes 0", () => {
  for (const c of [undefined, null, NaN, Infinity, -3, "x", {}]) {
    const m = buildModel({ repos: [repo({ lane: running(), children: c })], now: NOW });
    assert.equal(byKey(m)["RC:lane:0"].children, 0, `children=${String(c)}`);
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

// --------------------------------------- attribution is a ROSTER fact only --
//
// A lock payload is written by another repo's loop and is therefore the one
// input here that RC cannot enforce the spelling of. These three pin that the
// payload has no say in WHICH repo a row belongs to: attribution flows from the
// roster code alone, so a remote tree's spelling cannot desync RC's view.
//
// Today this is true because buildModel reads only pid / claimed_by_pid / lane
// / run_id / worktree / ts / pid_started off a payload and takes repoCode from
// the roster (src/model.js:91-113). These tests exist so that adding a payload
// side to the attribution later has to be a deliberate act that turns them red,
// rather than a quiet one-line change nobody notices until a lane stops
// appearing.

test("a payload repo field never overrides the ROSTER code, whatever its case", () => {
  for (const spelling of ["aa", "AA", "Aa", "ZZZ", "", 42, null]) {
    const lane = running();
    lane.payload.repo = spelling;
    const m = buildModel({ repos: [repo({ code: "AA", isSelf: false, lane })], now: NOW });
    const row = byKey(m)["AA:lane:0"];
    assert.ok(row, `the row must exist for payload repo=${String(spelling)}`);
    assert.equal(row.repoCode, "AA");
    assert.equal(row.key, "AA:lane:0");
    assert.equal(row.state, "RUNNING", "a payload repo field must not drop the row");
  }
});

test("a payload repo field is not copied onto the row", () => {
  // The row contract is pinned in full by "a row carries exactly the contracted
  // fields" above. This says the same thing from the other direction, about the
  // ONE field a sibling repo controls: it must not arrive on a rendered row at
  // all, under any casing.
  const lane = running();
  lane.payload.repo = "aa";
  const m = buildModel({ repos: [repo({ code: "AA", isSelf: false, lane })], now: NOW });
  for (const row of m.rows) {
    assert.equal(
      Object.prototype.hasOwnProperty.call(row, "repo"),
      false,
      "no row may carry a payload-sourced repo field"
    );
  }
});

test("two repos are attributed by roster code even when both payloads disagree", () => {
  // The mis-attribution shape: if anything keyed on the payload, these two rows
  // would swap or collapse. Both codes must survive, each with its own lane.
  const a = running({ lane: "queue" });
  a.payload.repo = "bb";
  const b = running({ lane: "repo" });
  b.payload.repo = "aa";
  const m = buildModel({
    repos: [
      repo({ code: "AA", isSelf: false, lane: a }),
      repo({ code: "BB", isSelf: false, lane: b }),
    ],
    now: NOW,
  });
  const rows = byKey(m);
  assert.equal(rows["AA:lane:0"].lane, "queue");
  assert.equal(rows["BB:lane:0"].lane, "repo");
  assert.equal(m.summary.repos, 2);
});

test("a non-finite now yields a null updatedAt and null ages", () => {
  for (const now of [undefined, null, NaN, Infinity, "x"]) {
    const m = buildModel({ repos: [repo({ lane: running() })], now });
    assert.equal(m.updatedAt, null, `now=${String(now)}`);
    assert.equal(byKey(m)["RC:lane:0"].ageS, null);
  }
});

test("a lane block that is not an object is treated as FREE", () => {
  for (const lane of [null, undefined, 42, "x", []]) {
    const m = buildModel({ repos: [repo({ lane })], now: NOW });
    assert.equal(byKey(m)["RC:lane:0"].state, "FREE");
    assert.equal(byKey(m)["RC:lane:0"].label, "idle");
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

// ------------------------------------------------------------- repoRows
// The ALL tab is ONE ROW PER REPO in fixed roster order. model.rows stays the
// state-sorted lane/controller list the per-repo tabs render; repoRows is the
// roster-ordered list the ALL tab renders. Codes here are placeholders.

function isoAt(epochS) {
  return new Date(epochS * 1000).toISOString();
}

function liveStatus(over) {
  return JSON.stringify(Object.assign({
    schema: 1, code: "AAA", updated: isoAt(NOW - 5), state: "running",
    task: "Appending Ledger", task_started: isoAt(NOW - (35 * 60 + 20)),
    task_eta_s: 42 * 60, next_tick: null, runs_in_window: 25, runs_cap: 120,
    window_s: 86400, cap_frees_at: null,
  }, over || {}));
}

// Seven repos handed over in a SHUFFLED order with root-less ones included,
// so only the roster `order` can produce the expected sequence.
function sevenRepos() {
  const spec = [
    ["CCC", 3], ["RC", 2], ["ZZZ", 0], ["FFF", 6], ["AAA", 1], ["EEE", 5], ["DDD", 4],
  ];
  return spec.map(([code, order]) => repo({
    code,
    isSelf: code === "RC",
    root: code === "ZZZ" || code === "EEE" ? null : "C:\\fake-" + code,
    noLane: code === "ZZZ" || code === "EEE",
    attendedOnly: code === "ZZZ",
    display: "Display " + code,
    order,
  }));
}

test("repoRows is exactly one row per repo, in roster order", () => {
  const m = buildModel({ repos: sevenRepos(), now: NOW });
  assert.equal(m.repoRows.length, 7);
  assert.deepEqual(
    m.repoRows.map((r) => r.repoCode),
    ["ZZZ", "AAA", "RC", "CCC", "DDD", "EEE", "FFF"]
  );
});

test("a repo with no checkout still gets its repo row, and no lane rows", () => {
  const m = buildModel({ repos: sevenRepos(), now: NOW });
  const e = m.repoRows.find((r) => r.repoCode === "EEE");
  assert.ok(e);
  assert.equal(e.noLane, true);
  assert.equal(m.rows.some((r) => r.repoCode === "EEE"), false);
  assert.equal(m.rows.some((r) => r.repoCode === "ZZZ"), false);
});

test("repoRows without any order keep roster index order", () => {
  const m = buildModel({
    repos: [repo({ code: "RC" }), repo({ code: "BBB" }), repo({ code: "AAA" })],
    now: NOW,
  });
  assert.deepEqual(m.repoRows.map((r) => r.repoCode), ["RC", "BBB", "AAA"]);
});

test("an ordered repo sorts before an unordered one", () => {
  const m = buildModel({
    repos: [repo({ code: "RC" }), repo({ code: "BBB", order: 1 })],
    now: NOW,
  });
  assert.deepEqual(m.repoRows.map((r) => r.repoCode), ["BBB", "RC"]);
});

test("a repo row folds the lane AND the controller into one record", () => {
  const m = buildModel({
    repos: [repo({
      lane: running({ ts: NOW - 720 }),
      ctrl: { state: "RUNNING", pid: 11, payload: { pid: 11, ts: NOW - 900 } },
      children: 3,
      logs: [{ lane: "queue", ageS: 9, stalled: true }],
    })],
    now: NOW,
  });
  const r = m.repoRows[0];
  assert.equal(r.laneState, "RUNNING");
  assert.equal(r.lane, "queue");
  assert.equal(r.ageS, 720);
  assert.equal(r.ctrlState, "RUNNING");
  assert.equal(r.ctrlAgeS, 900);
  assert.equal(r.children, 3);
  assert.equal(r.stalled, true);
  assert.equal(Object.prototype.hasOwnProperty.call(r, "logAgeS"), false, "log age is not carried to the row");
});

test("a repo row carries display name, falling back to the code", () => {
  const m = buildModel({
    repos: [repo({ display: "Display RC" }), repo({ code: "BBB", root: "C:\\fake-b" })],
    now: NOW,
  });
  assert.deepEqual(m.repoRows.map((r) => r.display), ["Display RC", "BBB"]);
});

test("a repo row carries the Sync parts from that tree's status text", () => {
  const m = buildModel({ repos: [repo({ statusText: liveStatus() })], now: NOW });
  assert.deepEqual(m.repoRows[0].sync, { task: "Appending Ledger", tail: "[35m/42m][25/120]" });
});

test("an absent status is no signal, and attended-only beats any file", () => {
  const m = buildModel({
    repos: [
      repo({ statusText: null }),
      repo({ code: "ZZZ", root: null, noLane: true, attendedOnly: true, statusText: liveStatus() }),
    ],
    now: NOW,
  });
  assert.deepEqual(m.repoRows[0].sync, { task: "no signal", tail: "[?]" });
  assert.deepEqual(m.repoRows[1].sync, { task: "attended only", tail: "" });
});

test("a repo's own tick interval decides when its status goes stale", () => {
  const text = liveStatus({ updated: isoAt(NOW - 700) });
  const m = buildModel({
    repos: [repo({ statusText: text, tickS: 300 }), repo({ code: "BBB", statusText: text, tickS: 600 })],
    now: NOW,
  });
  assert.equal(m.repoRows[0].sync.task, "no signal");
  assert.equal(m.repoRows[1].sync.task, "Appending Ledger");
});

test("NO repo row field ever contains a path separator", () => {
  const m = buildModel({ repos: sevenRepos(), now: NOW });
  for (const r of m.repoRows) {
    for (const [k, v] of Object.entries(r)) {
      if (typeof v === "string") assert.ok(!/[\\/]/.test(v), `${k}=${v}`);
    }
  }
});

test("repoRows is total on junk and JSON-serialisable", () => {
  for (const arg of [null, undefined, {}, { repos: "x" }, { repos: [null, 5] }]) {
    const m = buildModel(arg);
    assert.deepEqual(m.repoRows, []);
  }
  const m = buildModel({ repos: sevenRepos(), now: NOW });
  assert.deepEqual(JSON.parse(JSON.stringify(m)), m);
});

// ------------------------------------------------------------- accounts ----
// MAIN 0925 addendum: the ACCOUNTS strip rides on the model as rendered lines
// only - no identifier ever enters the model, because the model crosses IPC.

test("no accounts input leaves model.accounts null (strip off)", () => {
  const m = buildModel({ repos: [], now: NOW });
  assert.equal(m.accounts, null);
});

test("accounts input becomes rendered strip lines on the model, identifiers stripped", () => {
  const uuid = "12345678-1234-4234-8234-123456789abc";
  const email = "someone@example.invalid";
  const text = JSON.stringify({
    quota: [{
      accountUuid: uuid,
      name: email,
      quota: {
        unified5h: 0.23,
        unified7d: 0.07,
        unified5hReset: (NOW + 2 * 3600 + 600) * 1000,
        unified7dReset: (NOW + 3 * 86400 + 4 * 3600) * 1000,
        unifiedStatus: "allowed",
      },
    }],
  });
  const m = buildModel({
    repos: [],
    now: NOW,
    accounts: { text, mtimeMs: NOW * 1000, probeS: 300, roles: [{ account_uuid: uuid, role: "Headless" }] },
  });
  assert.deepEqual(
    m.accounts.lines.map((l) => l.text),
    ["Headless     5h 23% (resets 2h10m)   7d 7% (resets 3d4h)   allowed"]
  );
  const blob = JSON.stringify(m);
  assert.equal(blob.indexOf(uuid), -1);
  assert.equal(blob.indexOf(email), -1);
});

// ------------------------------------------------ FLEET-KIT v6/v7 lanes ----
// v6: up to three lanes per repo (lanes/0..2.lock), one row each. v7: a LIVE
// lane carries its remaining checklist; a non-live lane carries none.

const FREE_BLOCK = { state: "FREE", payload: null, pid: 0 };

function progressText(n, over) {
  const rows = [];
  for (let i = 1; i <= n; i += 1) rows.push({ id: "C" + i, task: "Task " + i, state: null, eta_s: null });
  return JSON.stringify(Object.assign({ eta_s: 300, updated: isoAt(NOW - 10), checklist: rows }, over || {}));
}

test("v6: three lane blocks give three lane rows keyed by index, plus the controller", () => {
  const m = buildModel({
    repos: [repo({ lanes: [running(), FREE_BLOCK, Object.assign(running({ lane: "ds" }), { state: "RECLAIMABLE" })] })],
    now: NOW,
  });
  const keys = m.rows.map((r) => r.key).sort();
  assert.deepEqual(keys, ["RC:controller", "RC:lane:0", "RC:lane:1", "RC:lane:2"]);
  assert.equal(byKey(m)["RC:lane:2"].laneIndex, 2);
  assert.equal(byKey(m)["RC:lane:2"].state, "RECLAIMABLE");
  assert.equal(byKey(m)["RC:controller"].laneIndex, null);
});

test("v6: the repo row carries one entry per lane index, in index order", () => {
  const m = buildModel({
    repos: [repo({
      lanes: [FREE_BLOCK, running({ ts: NOW - 720 }), FREE_BLOCK],
      laneChildren: [0, 4, 0],
    })],
    now: NOW,
  });
  const lanes = m.repoRows[0].lanes;
  assert.deepEqual(lanes.map((l) => l.index), [0, 1, 2]);
  assert.deepEqual(lanes.map((l) => l.state), ["FREE", "RUNNING", "FREE"]);
  assert.equal(lanes[1].lane, "queue");
  assert.equal(lanes[1].ageS, 720);
  assert.equal(lanes[1].children, 4);
  // The aggregate fields still describe the repo as a whole.
  assert.equal(m.repoRows[0].laneState, "RUNNING");
  assert.equal(m.repoRows[0].lane, "queue");
});

test("v7: a LIVE lane carries its checklist; free and stale-lock lanes carry null", () => {
  const live = Object.assign(running(), { progressText: progressText(4) });
  const dead = Object.assign(running(), { state: "RECLAIMABLE", progressText: progressText(2) });
  const m = buildModel({ repos: [repo({ lanes: [live, dead, FREE_BLOCK] })], now: NOW });
  const lanes = m.repoRows[0].lanes;
  assert.equal(lanes[0].checklist.status, "live");
  assert.deepEqual(lanes[0].checklist.items.map((i) => i.id), ["C1", "C2", "C3"]);
  assert.equal(lanes[0].checklist.more, 1);
  assert.equal(lanes[1].checklist, null, "a stale lock never shows a list");
  assert.equal(lanes[2].checklist, null);
});

test("v7: a live lane with no progress text reads no checklist", () => {
  const m = buildModel({ repos: [repo({ lanes: [running(), FREE_BLOCK, FREE_BLOCK] })], now: NOW });
  assert.deepEqual(m.repoRows[0].lanes[0].checklist, { status: "none", items: [], more: 0 });
});

test("legacy single lane input still yields one lane at index 0", () => {
  const m = buildModel({ repos: [repo({ lane: running() })], now: NOW });
  assert.equal(m.repoRows[0].lanes.length, 1);
  assert.equal(m.repoRows[0].lanes[0].index, 0);
});

test("v6: the governor verdict becomes ONE strip line on the model; absent -> null", () => {
  const m = buildModel({ repos: [], now: NOW, governor: { width: 3, held: 2, stale: 0, repos: ["RC", "CS"], queue: 3 } });
  assert.deepEqual(m.governor, { text: "Governor 2/3 - RC, CS - queue 3", alarm: false });
  assert.equal(buildModel({ repos: [], now: NOW }).governor, null);
});

test("no lane entry on a repo row carries a path", () => {
  const live = Object.assign(running(), { progressText: progressText(1) });
  const m = buildModel({ repos: [repo({ lanes: [live, FREE_BLOCK, FREE_BLOCK] })], now: NOW });
  const blob = JSON.stringify(m.repoRows);
  assert.ok(!/fake-worktrees/.test(blob), blob);
});
