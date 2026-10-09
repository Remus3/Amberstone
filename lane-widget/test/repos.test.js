"use strict";
// Slice A - repos.js. Roster resolution, leak-safe codes.
//
// Fixtures use INVENTED roots ("C:\\fake-a") and INVENTED participant codes
// ("AAA"/"BBB"). No real sibling name, path or slug appears here.

const test = require("node:test");
const assert = require("node:assert/strict");

const { resolveRepos, REPO_CONFIG_REL, joinPath } = require("../src/repos.js");

const RC = "C:\\Example Repo";
const CFG = joinPath(RC, ...REPO_CONFIG_REL);

function rcEntry() {
  return {
    code: "RC", root: RC, isSelf: true,
    display: "RC", order: null, attendedOnly: false, tickS: null, noLane: false,
  };
}

function readerFor(map) {
  return (p) => (Object.prototype.hasOwnProperty.call(map, p) ? map[p] : null);
}

test("RC is always index 0 and marked isSelf", () => {
  const out = resolveRepos({ rcRoot: RC, env: {}, readFile: () => null });
  assert.equal(out.length, 1);
  assert.deepEqual(out[0], rcEntry());
});

test("a missing config file is the correct fresh-clone answer, not an error", () => {
  const out = resolveRepos({ rcRoot: RC, env: {}, readFile: () => null });
  assert.deepEqual(out.map((r) => r.code), ["RC"]);
});

test("corrupt JSON degrades to RC only", () => {
  const out = resolveRepos({
    rcRoot: RC,
    env: {},
    readFile: readerFor({ [CFG]: "{not json" }),
  });
  assert.deepEqual(out.map((r) => r.code), ["RC"]);
});

test("a non-object config body degrades to RC only", () => {
  for (const body of ["[1,2,3]", "null", "42", '"text"', ""]) {
    const out = resolveRepos({
      rcRoot: RC,
      env: {},
      readFile: readerFor({ [CFG]: body }),
    });
    assert.deepEqual(out.map((r) => r.code), ["RC"], `body=${body}`);
  }
});

test("a readFile that throws is fail-soft", () => {
  const out = resolveRepos({
    rcRoot: RC,
    env: {},
    readFile: () => {
      throw new Error("EACCES");
    },
  });
  assert.deepEqual(out.map((r) => r.code), ["RC"]);
});

test("participants map a root to its CODE", () => {
  const cfg = JSON.stringify({
    repos: ["C:\\fake-a", "C:\\fake-b"],
    participants: { AAA: "C:\\fake-a", BBB: "C:\\fake-b" },
  });
  const out = resolveRepos({
    rcRoot: RC,
    env: {},
    readFile: readerFor({ [CFG]: cfg }),
  });
  assert.deepEqual(out.map((r) => r.code), ["RC", "AAA", "BBB"]);
  assert.deepEqual(out.map((r) => r.isSelf), [true, false, false]);
});

test("participant matching is case-insensitive and separator-insensitive", () => {
  const cfg = JSON.stringify({
    repos: ["C:/fake-a/"],
    participants: { AAA: "c:\\FAKE-A" },
  });
  const out = resolveRepos({
    rcRoot: RC,
    env: {},
    readFile: readerFor({ [CFG]: cfg }),
  });
  assert.deepEqual(out.map((r) => r.code), ["RC", "AAA"]);
});

test("an unmapped root gets a POSITIONAL code, never the directory basename", () => {
  const cfg = JSON.stringify({ repos: ["C:\\fake-a", "C:\\fake-b"] });
  const out = resolveRepos({
    rcRoot: RC,
    env: {},
    readFile: readerFor({ [CFG]: cfg }),
  });
  assert.deepEqual(out.map((r) => r.code), ["RC", "REPO-2", "REPO-3"]);
  for (const row of out) {
    assert.ok(!/fake-a|fake-b/i.test(row.code), "code must not carry a basename");
  }
});

test("a partially mapped roster mixes codes and positional placeholders", () => {
  const cfg = JSON.stringify({
    repos: ["C:\\fake-a", "C:\\fake-b"],
    participants: { BBB: "C:\\fake-b" },
  });
  const out = resolveRepos({
    rcRoot: RC,
    env: {},
    readFile: readerFor({ [CFG]: cfg }),
  });
  assert.deepEqual(out.map((r) => r.code), ["RC", "REPO-2", "BBB"]);
});

test("RC_MOON_SYNC_REPOS overrides the file entirely", () => {
  const cfg = JSON.stringify({ repos: ["C:\\fake-z"] });
  const out = resolveRepos({
    rcRoot: RC,
    env: { RC_MOON_SYNC_REPOS: "C:\\fake-a;C:\\fake-b" },
    readFile: readerFor({ [CFG]: cfg }),
  });
  assert.deepEqual(out.map((r) => r.root), [RC, "C:\\fake-a", "C:\\fake-b"]);
});

test("the env override still takes codes from the participants file", () => {
  const cfg = JSON.stringify({ participants: { AAA: "C:\\fake-a" } });
  const out = resolveRepos({
    rcRoot: RC,
    env: { RC_MOON_SYNC_REPOS: "C:\\fake-a" },
    readFile: readerFor({ [CFG]: cfg }),
  });
  assert.deepEqual(out.map((r) => r.code), ["RC", "AAA"]);
});

test("env override trims, drops empties and tolerates a trailing delimiter", () => {
  const out = resolveRepos({
    rcRoot: RC,
    env: { RC_MOON_SYNC_REPOS: " C:\\fake-a ;; ;C:\\fake-b;" },
    readFile: () => null,
  });
  assert.deepEqual(out.map((r) => r.root), [RC, "C:\\fake-a", "C:\\fake-b"]);
});

test("an empty or whitespace env override falls through to the file", () => {
  const cfg = JSON.stringify({ repos: ["C:\\fake-a"] });
  for (const raw of ["", "   ", ";;;"]) {
    const out = resolveRepos({
      rcRoot: RC,
      env: { RC_MOON_SYNC_REPOS: raw },
      readFile: readerFor({ [CFG]: cfg }),
    });
    assert.deepEqual(out.map((r) => r.root), [RC, "C:\\fake-a"], `raw=${JSON.stringify(raw)}`);
  }
});

test("duplicate roots are deduped, including case and separator variants", () => {
  const out = resolveRepos({
    rcRoot: RC,
    env: { RC_MOON_SYNC_REPOS: "C:\\fake-a;C:/fake-a;c:\\FAKE-A\\;C:\\fake-b" },
    readFile: () => null,
  });
  assert.deepEqual(out.map((r) => r.root), [RC, "C:\\fake-a", "C:\\fake-b"]);
});

test("RC's own root is never re-added by the roster", () => {
  const out = resolveRepos({
    rcRoot: RC,
    env: { RC_MOON_SYNC_REPOS: "c:/example repo;C:\\fake-a" },
    readFile: () => null,
  });
  assert.deepEqual(out.map((r) => r.root), [RC, "C:\\fake-a"]);
  assert.equal(out.filter((r) => r.isSelf).length, 1);
});

test("non-string roster entries are dropped", () => {
  const cfg = JSON.stringify({ repos: [null, 7, {}, [], "  ", "C:\\fake-a"] });
  const out = resolveRepos({
    rcRoot: RC,
    env: {},
    readFile: readerFor({ [CFG]: cfg }),
  });
  assert.deepEqual(out.map((r) => r.root), [RC, "C:\\fake-a"]);
});

test("a participants value that is not a string is ignored", () => {
  const cfg = JSON.stringify({
    repos: ["C:\\fake-a"],
    participants: { AAA: 42, BBB: null },
  });
  const out = resolveRepos({
    rcRoot: RC,
    env: {},
    readFile: readerFor({ [CFG]: cfg }),
  });
  assert.deepEqual(out.map((r) => r.code), ["RC", "REPO-2"]);
});

test("a participants map that is not an object is ignored", () => {
  const cfg = JSON.stringify({ repos: ["C:\\fake-a"], participants: ["AAA"] });
  const out = resolveRepos({
    rcRoot: RC,
    env: {},
    readFile: readerFor({ [CFG]: cfg }),
  });
  assert.deepEqual(out.map((r) => r.code), ["RC", "REPO-2"]);
});

test("a participant may relabel RC itself without duplicating the row", () => {
  const cfg = JSON.stringify({ participants: { RCX: RC } });
  const out = resolveRepos({
    rcRoot: RC,
    env: {},
    readFile: readerFor({ [CFG]: cfg }),
  });
  assert.equal(out.length, 1);
  assert.equal(out[0].code, "RCX");
  assert.equal(out[0].isSelf, true);
});

test("null / empty / absent arguments are all total", () => {
  for (const arg of [undefined, null, {}, { rcRoot: null }, { rcRoot: "" }]) {
    const out = resolveRepos(arg);
    assert.ok(Array.isArray(out), `arg=${JSON.stringify(arg)}`);
    assert.equal(out.length, 1);
    assert.equal(out[0].code, "RC");
    assert.equal(out[0].isSelf, true);
    assert.equal(typeof out[0].root, "string");
  }
});

test("a non-function readFile is tolerated", () => {
  const out = resolveRepos({ rcRoot: RC, env: {}, readFile: "nope" });
  assert.deepEqual(out.map((r) => r.code), ["RC"]);
});

test("a non-object env is tolerated", () => {
  const out = resolveRepos({ rcRoot: RC, env: "nope", readFile: () => null });
  assert.deepEqual(out.map((r) => r.code), ["RC"]);
});

test("the config path is <rcRoot>/ops/moon_sync_repos.json", () => {
  const seen = [];
  resolveRepos({
    rcRoot: RC,
    env: {},
    readFile: (p) => {
      seen.push(p);
      return null;
    },
  });
  assert.deepEqual(REPO_CONFIG_REL, ["ops", "moon_sync_repos.json"]);
  assert.deepEqual(seen, ["C:\\Example Repo\\ops\\moon_sync_repos.json"]);
});

test("joinPath picks the separator already present in the root", () => {
  assert.equal(joinPath("C:/fake-a", "ops", "x.json"), "C:/fake-a/ops/x.json");
  assert.equal(joinPath("C:\\fake-a", "ops", "x.json"), "C:\\fake-a\\ops\\x.json");
  assert.equal(joinPath("C:\\fake-a\\", "ops"), "C:\\fake-a\\ops");
});

test("codes are UNIQUE across the roster - model.js keys on them", () => {
  // buildModel's row key is `${repoCode}:${kind}`, so a duplicate code would
  // collide two rows. This is the invariant that makes that key safe.
  const cfg = JSON.stringify({
    repos: ["C:\\fake-a", "C:\\fake-b", "C:\\fake-c", "C:\\fake-d"],
    participants: { AAA: "C:\\fake-a", BBB: "C:\\fake-c" },
  });
  const out = resolveRepos({
    rcRoot: RC,
    env: {},
    readFile: readerFor({ [CFG]: cfg }),
  });
  assert.equal(out.length, 5);
  assert.equal(new Set(out.map((r) => r.code)).size, out.length);
});

test("zero roster entries still yields exactly the RC row", () => {
  const cfg = JSON.stringify({ repos: [], participants: {} });
  const out = resolveRepos({
    rcRoot: RC,
    env: {},
    readFile: readerFor({ [CFG]: cfg }),
  });
  assert.deepEqual(out, [rcEntry()]);
});

// ------------------------------------------------- roster display + order --
// The "roster" key is the per-host display/order map the ALL tab renders by.
// Display names are sibling names, so they live ONLY in the gitignored file;
// every fixture here is an invented placeholder.

function cfgReader(blob) {
  return readerFor({ [CFG]: JSON.stringify(blob) });
}

test("an entry with no roster record defaults display to its code", () => {
  const out = resolveRepos({
    rcRoot: RC,
    env: {},
    readFile: cfgReader({ repos: ["C:\\fake-a"], participants: { AAA: "C:\\fake-a" } }),
  });
  assert.deepEqual(
    out.map((r) => [r.code, r.display, r.order, r.attendedOnly, r.tickS, r.noLane]),
    [["RC", "RC", null, false, null, false], ["AAA", "AAA", null, false, null, false]]
  );
});

test("roster display, order, tick and attended flag land on the matching code", () => {
  const out = resolveRepos({
    rcRoot: RC,
    env: {},
    readFile: cfgReader({
      repos: ["C:\\fake-a"],
      participants: { AAA: "C:\\fake-a" },
      roster: {
        RC: { display: "Home Placeholder", order: 3 },
        AAA: { display: "Sibling Placeholder", order: 2, tick_s: 600 },
      },
    }),
  });
  const byCode = Object.fromEntries(out.map((r) => [r.code, r]));
  assert.equal(byCode.RC.display, "Home Placeholder");
  assert.equal(byCode.RC.order, 3);
  assert.equal(byCode.AAA.display, "Sibling Placeholder");
  assert.equal(byCode.AAA.order, 2);
  assert.equal(byCode.AAA.tickS, 600);
});

test("a roster code with no checkout is still listed, root-less and lane-less", () => {
  const out = resolveRepos({
    rcRoot: RC,
    env: {},
    readFile: cfgReader({
      repos: [],
      participants: {},
      roster: { ZZZ: { display: "Supervisor Placeholder", order: 0, attended_only: true } },
    }),
  });
  assert.deepEqual(out.map((r) => r.code), ["RC", "ZZZ"]);
  const z = out[1];
  assert.equal(z.root, null);
  assert.equal(z.noLane, true);
  assert.equal(z.attendedOnly, true);
  assert.equal(z.isSelf, false);
});

test("a roster code whose participant path is not in repos is polled at that path", () => {
  const out = resolveRepos({
    rcRoot: RC,
    env: {},
    readFile: cfgReader({
      repos: [],
      participants: { BBB: "C:\\fake-b" },
      roster: { BBB: { order: 1 } },
    }),
  });
  assert.deepEqual(out.map((r) => [r.code, r.root, r.noLane]), [
    ["RC", RC, false],
    ["BBB", "C:\\fake-b", false],
  ]);
});

test("a roster record never duplicates an already-listed code", () => {
  const out = resolveRepos({
    rcRoot: RC,
    env: {},
    readFile: cfgReader({
      repos: ["C:\\fake-a"],
      participants: { AAA: "C:\\fake-a" },
      roster: { AAA: { order: 1 }, RC: { order: 0 } },
    }),
  });
  assert.deepEqual(out.map((r) => r.code), ["RC", "AAA"]);
});

test("junk roster records and fields are ignored, never thrown on", () => {
  for (const roster of [null, 5, "x", [], { AAA: 5 }, { AAA: null }, { "": {} },
    { AAA: { display: 7, order: "first", tick_s: -1, attended_only: "yes" } }]) {
    const out = resolveRepos({
      rcRoot: RC,
      env: {},
      readFile: cfgReader({ repos: ["C:\\fake-a"], participants: { AAA: "C:\\fake-a" }, roster }),
    });
    const a = out.find((r) => r.code === "AAA");
    assert.ok(a, JSON.stringify(roster));
    assert.equal(a.display, "AAA");
    assert.equal(a.order, null);
    assert.equal(a.tickS, null);
    assert.equal(a.attendedOnly, false);
  }
});

test("a display name is trimmed and capped so one config typo cannot blow the row", () => {
  const out = resolveRepos({
    rcRoot: RC,
    env: {},
    readFile: cfgReader({ roster: { RC: { display: "  " + "x".repeat(80) + "  " } } }),
  });
  assert.equal(out[0].display.length, 32);
});

// ------------------------------------------------------------- accounts ----
// The optional, additive "accounts" key: where the proxy's state file is and
// which account plays which ROLE. Paths and account ids are host config, so the
// real ones live only in the gitignored file; these are placeholders.

const { resolveAccounts } = require("../src/repos.js");

test("no accounts key means the strip is off (null), never an error", () => {
  assert.equal(resolveAccounts({ rcRoot: RC, env: {}, readFile: () => null }), null);
  assert.equal(resolveAccounts({ rcRoot: RC, env: {}, readFile: cfgReader({ repos: [] }) }), null);
  assert.equal(resolveAccounts(null), null);
});

test("accounts state_file, probe_s and roles are read in roster order", () => {
  const got = resolveAccounts({
    rcRoot: RC,
    env: {},
    readFile: cfgReader({
      accounts: {
        state_file: "C:\\fake-profile\\proxy.state.json",
        probe_s: 120,
        roles: [
          { account_uuid: "placeholder-uuid-2", role: "Headless" },
          { account_uuid: "placeholder-uuid-1", role: "Interactive" },
        ],
      },
    }),
  });
  assert.deepEqual(got, {
    stateFile: "C:\\fake-profile\\proxy.state.json",
    probeS: 120,
    roles: [
      { account_uuid: "placeholder-uuid-2", role: "Headless" },
      { account_uuid: "placeholder-uuid-1", role: "Interactive" },
    ],
  });
});

test("junk accounts config degrades: no state_file is off, junk roles and probe are dropped", () => {
  const read = (accounts) => resolveAccounts({ rcRoot: RC, env: {}, readFile: cfgReader({ accounts }) });
  assert.equal(read({ roles: [] }), null);
  assert.equal(read({ state_file: 5 }), null);
  assert.equal(read("x"), null);
  const got = read({
    state_file: "C:\\fake\\s.json",
    probe_s: -3,
    roles: [null, 5, { role: "X" }, { account_uuid: "u", role: 7 }, { account_uuid: "u2", role: "Ok" }],
  });
  assert.equal(got.probeS, 300);
  assert.deepEqual(got.roles, [{ account_uuid: "u2", role: "Ok" }]);
});
