// lane-widget/test/render.test.js
//
// Unit tests for the PURE half of src/renderer/widget.js.
//
// There is no jsdom in this repo and adding one would be a new dependency, so
// widget.js is written as pure functions over the model that return a plain
// DESCRIPTION of what to render, plus a DOM shim dumb enough to need no test.
// Everything below tests the pure half against the real model shape from
// src/model.js:99-113 - not a paraphrase of it.
//
// FIXTURES USE INVENTED REPO CODES ("AAA", "BBB"). No sibling repo name, path
// or slug appears here, and no fixture carries a filesystem path at all.

"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const w = require("../src/renderer/widget.js");

// A row exactly as src/model.js:99-113 emits one.
function row(over) {
  return Object.assign(
    {
      key: "RC:lane",
      repoCode: "RC",
      kind: "lane",
      label: "upgrade",
      state: "RUNNING",
      lane: "upgrade",
      runId: "a1b2c3",
      ageS: 42,
      children: 3,
      logAgeS: 12,
      stalled: false,
      worktreeTail: "lane-upgrade",
    },
    over || {}
  );
}

function model(rows, summary) {
  return {
    rows: rows || [],
    summary: Object.assign(
      { repos: 1, running: 0, reclaimable: 0, free: 0, children: 0, stalled: 0 },
      summary || {}
    ),
    updatedAt: 1000,
  };
}

// ------------------------------------------------------------- no reflow ----

test("zero rows yields the same card-container shape as N rows", () => {
  const empty = w.buildView(model([]), {});
  const full = w.buildView(
    model([
      row({ key: "RC:lane" }),
      row({ key: "RC:controller", kind: "controller", lane: null, label: "controller" }),
      row({ key: "AAA:lane", repoCode: "AAA", lane: "ds", label: "ds" }),
    ]),
    {}
  );

  // Same number of card slots: the empty state occupies the same box.
  assert.equal(empty.cards.length, w.MIN_CARD_SLOTS);
  assert.equal(full.cards.length, 3);
  assert.equal(empty.cards.length, full.cards.length);

  // Same container keys.
  assert.deepEqual(Object.keys(empty).sort(), Object.keys(full).sort());

  // Same per-card key set, slot for slot - that identity IS the no-reflow
  // property: filling a slot changes text and class, never structure.
  for (let i = 0; i < empty.cards.length; i += 1) {
    assert.deepEqual(
      Object.keys(empty.cards[i]).sort(),
      Object.keys(full.cards[i]).sort(),
      `card ${i} key set differs`
    );
    assert.equal(empty.cards[i].wide, full.cards[i].wide, `card ${i} width differs`);
  }
});

test("padding only ever tops up to the minimum, never truncates", () => {
  const rows = [];
  for (let i = 0; i < 5; i += 1) {
    rows.push(row({ key: `AAA:lane-${i}`, repoCode: "AAA" }));
  }
  const view = w.buildView(model(rows), {});
  assert.equal(view.cards.length, 5);
  assert.equal(view.cards.filter((c) => c.placeholder).length, 0);
});

test("a padded empty view marks its slots as placeholders", () => {
  const view = w.buildView(model([]), {});
  assert.equal(view.empty, true);
  assert.equal(view.rowCount, 0);
  assert.deepEqual(view.cards.map((c) => c.placeholder), [true, true, true]);
  // A placeholder states its absence in words, not by being blank-with-color.
  assert.equal(view.cards[0].stateText, "no data");
  assert.equal(view.cards[0].hero, w.NO_DATA);
});

// ---------------------------------------------------------------- state -----

test("a RECLAIMABLE row is labelled stale and never running", () => {
  // model.js:85-89 hands back the LANE NAME as `label` for a reclaimable lane.
  // The hero must not echo that, or a dead lane reads like a live one.
  const r = row({ state: "RECLAIMABLE", lane: "ds", label: "ds" });
  const view = w.buildView(model([r]), {});
  const card = view.cards[0];

  assert.equal(card.hero, "stale");
  assert.equal(card.stateText, "stale");
  assert.equal(card.stateKey, "stale");
  assert.notEqual(card.hero, "running");
  assert.notEqual(card.stateText, "running");
  assert.equal(card.hero.includes("ds"), false);
});

test("state is carried by a text label for every state, not by color alone", () => {
  assert.equal(w.stateTextFor("RUNNING"), "running");
  assert.equal(w.stateTextFor("RECLAIMABLE"), "stale");
  assert.equal(w.stateTextFor("FREE"), "idle");
  // An unknown or missing state must not silently read as idle.
  assert.equal(w.stateTextFor("WAT"), "unreadable");
  assert.equal(w.stateTextFor(undefined), "unreadable");
  assert.equal(w.stateTextFor(null), "unreadable");

  const view = w.buildView(
    model([
      row({ key: "RC:lane", state: "RUNNING" }),
      row({ key: "AAA:lane", repoCode: "AAA", state: "RECLAIMABLE" }),
      row({ key: "BBB:lane", repoCode: "BBB", state: "FREE", lane: null, label: "idle" }),
      row({ key: "BBB:controller", repoCode: "BBB", kind: "controller", state: "???" }),
    ]),
    {}
  );
  // Every card says its state in words, and no descriptor field is a color.
  for (const card of view.cards) {
    assert.equal(typeof card.stateText, "string");
    assert.ok(card.stateText.length > 0);
    assert.equal(/#|rgb|oklch/i.test(JSON.stringify(card)), false);
  }
  assert.deepEqual(
    view.cards.map((c) => c.stateText),
    ["running", "stale", "idle", "unreadable"]
  );
});

test("hero reads the lane name when running and idle when free", () => {
  assert.equal(w.heroFor(row({ state: "RUNNING", lane: "queue" })), "queue");
  assert.equal(w.heroFor(row({ state: "FREE", lane: null, label: "idle" })), "idle");
  // A running controller row has no lane name - it falls back to its label.
  assert.equal(
    w.heroFor(row({ state: "RUNNING", kind: "controller", lane: null, label: "controller" })),
    "controller"
  );
  assert.equal(w.heroFor(null), "unreadable");
});

// ------------------------------------------------------------- card body ----

test("run id and age render on the card", () => {
  const view = w.buildView(
    model([row({ runId: "r7f21", ageS: 95, children: 4, logAgeS: 3 })]),
    {}
  );
  const card = view.cards[0];
  assert.equal(card.runId, "r7f21");
  assert.equal(card.label, "RC lane");
  assert.ok(card.meta.includes("age 1m"), `meta was ${card.meta}`);
  assert.ok(card.meta.includes("kids 4"), `meta was ${card.meta}`);
  assert.ok(card.meta.includes("log 3s"), `meta was ${card.meta}`);
});

test("a missing run id or age renders the no-data sentinel, not blank", () => {
  const view = w.buildView(
    model([row({ runId: null, ageS: null, children: 0, logAgeS: null })]),
    {}
  );
  const card = view.cards[0];
  assert.equal(card.runId, w.NO_DATA);
  assert.equal(card.meta, "age - - kids 0 - log -");
});

test("formatAge buckets seconds and rejects junk", () => {
  assert.equal(w.formatAge(0), "0s");
  assert.equal(w.formatAge(59), "59s");
  assert.equal(w.formatAge(60), "1m");
  assert.equal(w.formatAge(3599), "59m");
  assert.equal(w.formatAge(3600), "1h");
  assert.equal(w.formatAge(86400), "1d");
  assert.equal(w.formatAge(null), w.NO_DATA);
  assert.equal(w.formatAge(-5), w.NO_DATA);
  assert.equal(w.formatAge(NaN), w.NO_DATA);
  assert.equal(w.formatAge("60"), w.NO_DATA);
});

test("a stalled row says so in words", () => {
  const view = w.buildView(model([row({ stalled: true })]), {});
  assert.ok(view.cards[0].meta.includes("stalled"));
});

// ------------------------------------------------------------------ tabs ----

test("the tab list is All first, then RC, then each other repo code once", () => {
  // Rows arrive STATE-sorted (model.js:153-161), so a busy sibling can precede
  // RC. The tab strip must still put RC first.
  const tabs = w.buildTabs(
    model([
      row({ key: "AAA:lane", repoCode: "AAA" }),
      row({ key: "BBB:lane", repoCode: "BBB" }),
      row({ key: "AAA:controller", repoCode: "AAA", kind: "controller" }),
      row({ key: "RC:lane", repoCode: "RC" }),
      row({ key: "RC:controller", repoCode: "RC", kind: "controller" }),
    ])
  );
  assert.deepEqual(tabs, [
    { id: "ALL", label: "All" },
    { id: "RC", label: "RC" },
    { id: "AAA", label: "AAA" },
    { id: "BBB", label: "BBB" },
  ]);
});

test("zero rows still yields the All tab", () => {
  assert.deepEqual(w.buildTabs(model([])), [{ id: "ALL", label: "All" }]);
  assert.deepEqual(w.buildTabs(null), [{ id: "ALL", label: "All" }]);
});

test("All is the default and an unknown active tab falls back to it", () => {
  const m = model([row({ repoCode: "AAA", key: "AAA:lane" })]);
  assert.equal(w.buildView(m, {}).activeTab, "ALL");
  assert.equal(w.buildView(m, { activeTab: "AAA" }).activeTab, "AAA");
  // A repo that dropped out of the roster must not blank the panel.
  assert.equal(w.buildView(m, { activeTab: "BBB" }).activeTab, "ALL");
});

test("selecting a repo tab filters to that repo only", () => {
  const m = model([
    row({ key: "RC:lane", repoCode: "RC" }),
    row({ key: "AAA:lane", repoCode: "AAA" }),
    row({ key: "AAA:controller", repoCode: "AAA", kind: "controller" }),
  ]);
  const view = w.buildView(m, { activeTab: "AAA" });
  assert.equal(view.rowCount, 2);
  assert.deepEqual(
    view.cards.filter((c) => !c.placeholder).map((c) => c.label),
    ["AAA lane", "AAA controller"]
  );
  // Filtered down to 2, the container is still padded to the stable minimum.
  assert.equal(view.cards.length, w.MIN_CARD_SLOTS);
});

// --------------------------------------------------------------- settings ---

test("showFree false hides FREE rows without changing the container shape", () => {
  const m = model([
    row({ key: "RC:lane", state: "RUNNING" }),
    row({ key: "AAA:lane", repoCode: "AAA", state: "FREE", lane: null, label: "idle" }),
  ]);
  const shown = w.buildView(m, { showFree: true });
  const hidden = w.buildView(m, { showFree: false });
  assert.equal(shown.rowCount, 2);
  assert.equal(hidden.rowCount, 1);
  assert.equal(shown.cards.length, hidden.cards.length);
  assert.equal(hidden.cards.length, w.MIN_CARD_SLOTS);
  assert.equal(hidden.cards.filter((c) => c.stateText === "idle" && !c.placeholder).length, 0);
});

// ---------------------------------------------------------------- summary ---

test("the summary strip reads REPOS RUNNING STALE CHILDREN", () => {
  const view = w.buildView(
    model([], { repos: 3, running: 2, reclaimable: 1, free: 3, children: 11 }),
    {}
  );
  assert.deepEqual(view.summary, [
    { label: "REPOS", value: "3" },
    { label: "RUNNING", value: "2" },
    { label: "STALE", value: "1" },
    { label: "CHILDREN", value: "11" },
  ]);
});

test("a missing summary renders the sentinel rather than throwing", () => {
  const view = w.buildView({ rows: [] }, {});
  assert.deepEqual(view.summary.map((s) => s.label), [
    "REPOS",
    "RUNNING",
    "STALE",
    "CHILDREN",
  ]);
  assert.deepEqual(view.summary.map((s) => s.value), ["-", "-", "-", "-"]);
});

// ------------------------------------------------------------- totality -----

test("buildView never throws on a junk model", () => {
  const junk = [null, undefined, 0, "x", [], { rows: "no" }, { rows: [null, 7, "z"] }];
  for (const m of junk) {
    const view = w.buildView(m, null);
    assert.equal(view.cards.length, w.MIN_CARD_SLOTS);
    assert.equal(view.activeTab, "ALL");
    assert.deepEqual(view.tabs, [{ id: "ALL", label: "All" }]);
  }
});

test("no rendered card field carries a filesystem path", () => {
  // The LAST hop before a rendered surface. model.js already reduces worktree
  // to a basename; this asserts the renderer never surfaces even that, and
  // never surfaces anything separator-shaped.
  const view = w.buildView(
    model([row({ worktreeTail: "lane-ds" })]),
    {}
  );
  const text = JSON.stringify(view.cards);
  assert.equal(text.includes("/"), false, text);
  assert.equal(text.includes("\\"), false, text);
  assert.equal(text.includes(":\\"), false, text);
  assert.equal(text.includes("lane-ds"), false, text);
});
