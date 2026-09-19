"use strict";
// Slice A - repos.js. Roster resolution, leak-safe codes.
//
// Fixtures use INVENTED roots ("C:\\fake-a") and INVENTED participant codes
// ("AAA"/"BBB"). No real sibling name, path or slug appears here.

const test = require("node:test");
const assert = require("node:assert/strict");

const { resolveRepos, REPO_CONFIG_REL, joinPath } = require("../src/repos.js");

const RC = "C:\\Riot Commander";
const CFG = joinPath(RC, ...REPO_CONFIG_REL);

function readerFor(map) {
  return (p) => (Object.prototype.hasOwnProperty.call(map, p) ? map[p] : null);
}

test("RC is always index 0 and marked isSelf", () => {
  const out = resolveRepos({ rcRoot: RC, env: {}, readFile: () => null });
  assert.equal(out.length, 1);
  assert.deepEqual(out[0], { code: "RC", root: RC, isSelf: true });
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
    env: { RC_MOON_SYNC_REPOS: "c:/riot commander;C:\\fake-a" },
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
  assert.deepEqual(seen, ["C:\\Riot Commander\\ops\\moon_sync_repos.json"]);
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
  assert.deepEqual(out, [{ code: "RC", root: RC, isSelf: true }]);
});
