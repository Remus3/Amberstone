"use strict";
// Slice A - proctree.js. Descendants from ONE flat machine-wide snapshot.
// Pure: the snapshot arrives as data, nothing here shells out.

const test = require("node:test");
const assert = require("node:assert/strict");

const { descendants, countByRoot, DEFAULT_MAX_DEPTH } = require("../src/proctree.js");

const SNAP = [
  { pid: 100, ppid: 4, name: "root.exe", startMs: 1 },
  { pid: 200, ppid: 100, name: "child-a.exe", startMs: 2 },
  { pid: 201, ppid: 100, name: "child-b.exe", startMs: 3 },
  { pid: 300, ppid: 200, name: "grand.exe", startMs: 4 },
  { pid: 400, ppid: 999, name: "orphan.exe", startMs: 5 },
];

const pidsOf = (rows) => rows.map((r) => r.pid);

test("descendants returns children and grandchildren, roots EXCLUDED", () => {
  const out = descendants(SNAP, [100]);
  assert.deepEqual(pidsOf(out), [200, 201, 300]);
  assert.ok(!pidsOf(out).includes(100));
});

test("descendants is breadth-first", () => {
  const deep = [
    { pid: 2, ppid: 1 },
    { pid: 3, ppid: 2 },
    { pid: 4, ppid: 1 },
  ];
  assert.deepEqual(pidsOf(descendants(deep, [1])), [2, 4, 3]);
});

test("each row carries pid, ppid, name, startMs and depth", () => {
  const out = descendants(SNAP, [100]);
  assert.deepEqual(out[0], {
    pid: 200, ppid: 100, name: "child-a.exe", startMs: 2, depth: 1,
  });
  assert.equal(out.find((r) => r.pid === 300).depth, 2);
});

test("a missing name or startMs becomes null rather than undefined", () => {
  const out = descendants([{ pid: 2, ppid: 1 }], [1]);
  assert.deepEqual(out, [{ pid: 2, ppid: 1, name: null, startMs: null, depth: 1 }]);
});

test("a snapshot missing the parent row is tolerated", () => {
  // pid 100 itself is absent; its children are still found by ppid.
  const noRoot = SNAP.filter((r) => r.pid !== 100);
  assert.deepEqual(pidsOf(descendants(noRoot, [100])), [200, 201, 300]);
});

test("CYCLIC snapshot terminates and visits each pid at most once", () => {
  const cyclic = [
    { pid: 2, ppid: 1 },
    { pid: 1, ppid: 2 },
    { pid: 3, ppid: 2 },
  ];
  const out = descendants(cyclic, [1]);
  assert.deepEqual(pidsOf(out), [2, 3]);
});

test("a self-parented row does not recurse forever", () => {
  const out = descendants([{ pid: 5, ppid: 5 }, { pid: 6, ppid: 5 }], [5]);
  assert.deepEqual(pidsOf(out), [6]);
});

test("a long cycle among non-root pids terminates", () => {
  const ring = [
    { pid: 2, ppid: 1 },
    { pid: 3, ppid: 2 },
    { pid: 4, ppid: 3 },
    { pid: 2 + 0, ppid: 4 }, // duplicate pid 2 closing the ring
  ];
  const out = descendants(ring, [1], { maxDepth: 64 });
  assert.ok(out.length <= 4);
  assert.deepEqual(new Set(pidsOf(out)).size, pidsOf(out).length);
});

test("depth is capped, default 8", () => {
  assert.equal(DEFAULT_MAX_DEPTH, 8);
  const chain = [];
  for (let i = 2; i <= 40; i += 1) chain.push({ pid: i, ppid: i - 1 });
  assert.equal(descendants(chain, [1]).length, 8);
  assert.equal(descendants(chain, [1], { maxDepth: 3 }).length, 3);
  assert.equal(descendants(chain, [1], { maxDepth: 0 }).length, 0);
});

test("a non-finite or negative maxDepth falls back to the default", () => {
  const chain = [];
  for (let i = 2; i <= 40; i += 1) chain.push({ pid: i, ppid: i - 1 });
  for (const md of [NaN, Infinity, -5, "x", null]) {
    assert.equal(descendants(chain, [1], { maxDepth: md }).length, 8, `md=${String(md)}`);
  }
});

test("several roots are walked together and never re-emitted as descendants", () => {
  const two = [
    { pid: 2, ppid: 1 },
    { pid: 3, ppid: 2 },
    { pid: 5, ppid: 4 },
    { pid: 4, ppid: 2 }, // 4 is BOTH a root and a child of 2
  ];
  const out = descendants(two, [1, 4]);
  assert.ok(!pidsOf(out).includes(1));
  assert.ok(!pidsOf(out).includes(4));
  assert.deepEqual(new Set(pidsOf(out)).size, pidsOf(out).length);
});

test("a bare number root is accepted as well as an array", () => {
  assert.deepEqual(pidsOf(descendants(SNAP, 100)), [200, 201, 300]);
});

test("empty, null and junk inputs all return an empty array", () => {
  for (const [snap, roots] of [
    [[], [100]], [null, [100]], [undefined, [100]], ["x", [100]], [{}, [100]],
    [SNAP, []], [SNAP, null], [SNAP, undefined], [SNAP, "x"], [SNAP, {}],
    [SNAP, [0]], [SNAP, [-1]], [SNAP, [NaN]], [SNAP, [null]],
  ]) {
    const out = descendants(snap, roots);
    assert.ok(Array.isArray(out));
    assert.equal(out.length, 0);
  }
});

test("descendants tolerates junk rows inside an otherwise good snapshot", () => {
  const dirty = [null, 42, "x", [], { pid: "junk", ppid: 100 },
    { ppid: 100 }, { pid: 200, ppid: 100 }];
  assert.deepEqual(pidsOf(descendants(dirty, [100])), [200]);
});

test("numeric-string pid and ppid are accepted", () => {
  const out = descendants([{ pid: "200", ppid: "100" }], [100]);
  assert.deepEqual(pidsOf(out), [200]);
});

test("a duplicate pid row is only visited once", () => {
  const dup = [
    { pid: 2, ppid: 1, name: "first" },
    { pid: 2, ppid: 1, name: "second" },
  ];
  const out = descendants(dup, [1]);
  assert.equal(out.length, 1);
});

test("countByRoot gives a per-root count", () => {
  const m = countByRoot(SNAP, [100, 999]);
  assert.ok(m instanceof Map);
  assert.equal(m.get(100), 3);
  assert.equal(m.get(999), 1);
});

test("countByRoot returns 0 for a root with no children", () => {
  assert.equal(countByRoot(SNAP, [300]).get(300), 0);
});

test("countByRoot counts each root independently, not as one walk", () => {
  const shared = [
    { pid: 3, ppid: 1 },
    { pid: 3 + 0, ppid: 2 },
    { pid: 4, ppid: 3 },
  ];
  const m = countByRoot(shared, [1, 2]);
  assert.equal(typeof m.get(1), "number");
  assert.equal(typeof m.get(2), "number");
});

test("countByRoot is total for empty, null and junk input", () => {
  for (const [snap, roots] of [
    [null, null], [undefined, undefined], [[], []], ["x", "y"], [{}, {}],
  ]) {
    const m = countByRoot(snap, roots);
    assert.ok(m instanceof Map);
    assert.equal(m.size, 0);
  }
});

test("countByRoot skips unusable root pids entirely", () => {
  const m = countByRoot(SNAP, [100, 0, -1, NaN, null, "x"]);
  assert.deepEqual([...m.keys()], [100]);
});

test("countByRoot handles a CYCLIC snapshot", () => {
  const m = countByRoot([{ pid: 2, ppid: 1 }, { pid: 1, ppid: 2 }], [1]);
  assert.equal(m.get(1), 1);
});

test("descendants does not mutate the snapshot it is handed", () => {
  const before = JSON.stringify(SNAP);
  descendants(SNAP, [100]);
  countByRoot(SNAP, [100]);
  assert.equal(JSON.stringify(SNAP), before);
});
