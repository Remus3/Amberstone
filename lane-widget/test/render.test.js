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

test("stalled leads the meta line so truncation cannot eat the alarm", () => {
  // The meta line is nowrap inside an overflow-hidden card, so at the 172px
  // minimum column width the TAIL clips first. "stalled" is the single most
  // operationally important token on the card, so it must occupy the position
  // that survives truncation - the front.
  const meta = w.metaFor(row({ stalled: true, ageS: 42, children: 3, logAgeS: 12 }));
  assert.equal(meta, "stalled - age 42s - kids 3 - log 12s");
  assert.equal(meta.indexOf("stalled"), 0);
  assert.ok(meta.indexOf("stalled") < meta.indexOf("age"));
  assert.ok(meta.indexOf("stalled") < meta.indexOf("log"));

  // A healthy row carries no alarm token at all, and is otherwise unchanged.
  assert.equal(
    w.metaFor(row({ stalled: false, ageS: 42, children: 3, logAgeS: 12 })),
    "age 42s - kids 3 - log 12s"
  );
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

// ------------------------------------------------------- status transitions --
// The panel repaints on a 2000ms timer. index.html used to carry aria-live on
// the whole #cards region, so a screen reader re-announced every card, every
// label and every meta line once per poll, forever. The live region now lives
// on a separate visually-hidden #status node and is written ONLY on a real
// state transition - an unconditional write re-announces just as badly.

test("no state change produces no announcement", () => {
  const m = model([row({ key: "RC:lane", state: "RUNNING" })]);
  const a = w.buildView(m, {});
  const b = w.buildView(m, {});
  assert.equal(w.statusMessageFor(a, b), null);
  // The very first paint has no previous view to diff against, so it is silent
  // too - the cards themselves are already on screen and readable.
  assert.equal(w.statusMessageFor(null, b), null);
});

test("a real state transition produces one short ASCII sentence", () => {
  const before = w.buildView(model([row({ key: "RC:lane", state: "RUNNING" })]), {});
  const after = w.buildView(
    model([row({ key: "RC:lane", state: "RECLAIMABLE", lane: "ds", label: "ds" })]),
    {}
  );
  const msg = w.statusMessageFor(before, after);
  assert.equal(msg, "RC lane went stale");
  // Strictly 7-bit ASCII - this string is read aloud and also lands in the DOM.
  assert.equal(/^[\x20-\x7e]+$/.test(msg), true, msg);
  assert.ok(msg.length < 120, msg);
});

test("several simultaneous transitions are capped, not recited in full", () => {
  const codes = ["RC", "AAA", "BBB", "CCC", "DDD"];
  const before = w.buildView(
    model(codes.map((c) => row({ key: `${c}:lane`, repoCode: c, state: "RUNNING" }))),
    {}
  );
  const after = w.buildView(
    model(
      codes.map((c) =>
        row({ key: `${c}:lane`, repoCode: c, state: "FREE", lane: null, label: "idle" })
      )
    ),
    {}
  );
  const msg = w.statusMessageFor(before, after);
  assert.ok(msg.includes("RC lane went idle"), msg);
  assert.ok(msg.includes("2 more"), msg);
  assert.equal(msg.includes("DDD"), false, msg);
});

test("switching tabs announces nothing - the cards did not change state", () => {
  const m = model([
    row({ key: "RC:lane", repoCode: "RC", state: "RUNNING" }),
    row({ key: "AAA:lane", repoCode: "AAA", state: "RECLAIMABLE" }),
  ]);
  const all = w.buildView(m, { activeTab: "ALL" });
  const one = w.buildView(m, { activeTab: "AAA" });
  // Rows LEAVING the view are not transitions, so a filter change is silent.
  assert.equal(w.statusMessageFor(all, one), null);
  assert.equal(w.statusMessageFor(one, all), null);
});

test("a brand new row is not announced as a transition", () => {
  const before = w.buildView(model([row({ key: "RC:lane" })]), {});
  const after = w.buildView(
    model([row({ key: "RC:lane" }), row({ key: "AAA:lane", repoCode: "AAA" })]),
    {}
  );
  assert.equal(w.statusMessageFor(before, after), null);
});

test("statusMessageFor never throws on junk views", () => {
  const junk = [null, undefined, 0, "x", [], {}, { cards: "no" }, { cards: [null, 7] }];
  for (const a of junk) {
    for (const b of junk) {
      assert.equal(w.statusMessageFor(a, b), null);
    }
  }
});

// ------------------------------------------------------------- fake DOM ------
// There is still no jsdom in this repo and adding one would be a new runtime
// dependency. The shim below is the smallest node model that the three real
// failure modes need: identity (did the node survive the repaint), focus (is it
// still document.activeElement) and scrollTop (did the wipe clobber it).
// Detaching a node clears focus, exactly as a browser does - that is precisely
// the bug FIX 1 is about.

function makeNode(doc, tag) {
  const node = {
    tagName: String(tag).toUpperCase(),
    ownerDocument: doc,
    className: "",
    dataset: {},
    attrs: {},
    childNodes: [],
    parentNode: null,
    scrollTop: 0,
    _listeners: {},
    _text: "",
  };

  const classes = () => node.className.split(" ").filter((c) => c.length > 0);
  const setClasses = (list) => { node.className = list.join(" "); };
  node.classList = {
    add(c) { const l = classes(); if (!l.includes(c)) { l.push(c); setClasses(l); } },
    remove(c) { setClasses(classes().filter((x) => x !== c)); },
    contains(c) { return classes().includes(c); },
    toggle(c, on) { if (on) node.classList.add(c); else node.classList.remove(c); },
  };

  node.addEventListener = (type, fn) => {
    node._listeners[type] = node._listeners[type] || [];
    node._listeners[type].push(fn);
  };
  node.setAttribute = (name, value) => { node.attrs[name] = String(value); };
  node.getAttribute = (name) =>
    (Object.prototype.hasOwnProperty.call(node.attrs, name) ? node.attrs[name] : null);
  node.focus = () => { doc.activeElement = node; };
  node.click = () => { (node._listeners.click || []).forEach((fn) => fn({ target: node })); };
  // A key press, modelled well enough to test roving: the key name, the node it
  // was dispatched on, and whether the handler claimed it. defaultPrevented is
  // the observable that separates "the strip handles this key" from "the key
  // fell through to the browser and scrolled the panel instead".
  node.press = (key) => {
    const ev = { key: key, target: node, defaultPrevented: false };
    ev.preventDefault = () => { ev.defaultPrevented = true; };
    (node._listeners.keydown || []).forEach((fn) => fn(ev));
    return ev;
  };

  node.removeChild = (child) => {
    const i = node.childNodes.indexOf(child);
    if (i >= 0) node.childNodes.splice(i, 1);
    child.parentNode = null;
    // A detached node cannot hold focus. This is the whole bug.
    if (doc.activeElement === child) doc.activeElement = null;
    return child;
  };
  node.appendChild = (child) => {
    if (child.parentNode) child.parentNode.removeChild(child);
    child.parentNode = node;
    node.childNodes.push(child);
    return child;
  };
  node.insertBefore = (child, ref) => {
    if (child.parentNode) child.parentNode.removeChild(child);
    child.parentNode = node;
    const i = ref ? node.childNodes.indexOf(ref) : -1;
    if (i < 0) node.childNodes.push(child);
    else node.childNodes.splice(i, 0, child);
    return child;
  };

  Object.defineProperty(node, "firstChild", {
    get() { return node.childNodes[0] || null; },
  });
  Object.defineProperty(node, "nextSibling", {
    get() {
      const p = node.parentNode;
      if (!p) return null;
      return p.childNodes[p.childNodes.indexOf(node) + 1] || null;
    },
  });
  Object.defineProperty(node, "textContent", {
    get() {
      if (node.childNodes.length === 0) return node._text;
      return node.childNodes.map((c) => c.textContent).join("");
    },
    set(v) {
      // Counted, not just stored. A live region that is RE-WRITTEN with the
      // same text announces again, so "did anything touch this node" is the
      // property under test - the resulting string cannot tell you that.
      node.textWrites += 1;
      const emptied = node.childNodes.length > 0;
      while (node.childNodes.length > 0) node.removeChild(node.childNodes[0]);
      node._text = String(v);
      // Emptying a scroll container collapses its content height, so the
      // browser clamps scrollTop back to 0. Modelling that is what makes the
      // scroll-preservation test able to fail.
      if (emptied) node.scrollTop = 0;
    },
  });
  node.textWrites = 0;
  return node;
}

function makeDoc() {
  const doc = { activeElement: null };
  doc.createElement = (tag) => makeNode(doc, tag);
  return doc;
}

const tabIds = (root) => root.childNodes.map((n) => n.dataset.tabId);
const tabById = (root, id) => root.childNodes.filter((n) => n.dataset.tabId === id)[0] || null;

// --------------------------------------------------- tab strip reconciliation

test("an identical repaint leaves every tab node in place and keeps focus", () => {
  const doc = makeDoc();
  const root = makeNode(doc, "div");
  const m = model([
    row({ key: "RC:lane", repoCode: "RC" }),
    row({ key: "AAA:lane", repoCode: "AAA" }),
  ]);
  const view = w.buildView(m, {});
  w.renderTabs(doc, root, view, () => {});

  assert.deepEqual(tabIds(root), ["ALL", "RC", "AAA"]);
  const rc = tabById(root, "RC");
  rc.focus();
  assert.equal(doc.activeElement, rc);

  // The 2000ms tick: same model, same view, nothing at all changed.
  w.renderTabs(doc, root, w.buildView(m, {}), () => {});

  assert.deepEqual(tabIds(root), ["ALL", "RC", "AAA"]);
  assert.equal(tabById(root, "RC"), rc, "the RC tab node was rebuilt");
  assert.equal(doc.activeElement, rc, "the repaint destroyed keyboard focus");
  assert.equal(rc.parentNode, root, "the focused node was detached");
});

test("pressing Enter on a tab does not lose focus to the re-render it triggers", () => {
  // The worse path: activating a tab calls selectTab -> render -> renderTabs.
  // Before the fix this lost focus 100 percent of the time, not intermittently.
  const doc = makeDoc();
  const root = makeNode(doc, "div");
  const m = model([
    row({ key: "RC:lane", repoCode: "RC" }),
    row({ key: "AAA:lane", repoCode: "AAA" }),
  ]);
  let activeTab = "ALL";
  const onSelect = (id) => {
    activeTab = id;
    w.renderTabs(doc, root, w.buildView(m, { activeTab: activeTab }), onSelect);
  };
  w.renderTabs(doc, root, w.buildView(m, { activeTab: activeTab }), onSelect);

  const aaa = tabById(root, "AAA");
  aaa.focus();
  aaa.click(); // what Enter on a focused button dispatches

  assert.equal(activeTab, "AAA", "the reconciled handler stopped firing");
  assert.equal(tabById(root, "AAA"), aaa, "the activated tab node was rebuilt");
  assert.equal(doc.activeElement, aaa, "activating a tab lost keyboard focus");
  assert.equal(aaa.getAttribute("aria-selected"), "true");
  assert.equal(tabById(root, "ALL").getAttribute("aria-selected"), "false");
  assert.equal(aaa.classList.contains("is-active"), true);
  assert.equal(tabById(root, "ALL").classList.contains("is-active"), false);
});

test("a changed tab set inserts in order and keeps focus on a surviving tab", () => {
  const doc = makeDoc();
  const root = makeNode(doc, "div");
  const before = w.buildView(
    model([
      row({ key: "RC:lane", repoCode: "RC" }),
      row({ key: "BBB:lane", repoCode: "BBB" }),
    ]),
    {}
  );
  w.renderTabs(doc, root, before, () => {});
  assert.deepEqual(tabIds(root), ["ALL", "RC", "BBB"]);

  const rc = tabById(root, "RC");
  const bbb = tabById(root, "BBB");
  bbb.focus();

  // A new repo appears BETWEEN the two existing ones in tab order.
  const after = w.buildView(
    model([
      row({ key: "RC:lane", repoCode: "RC" }),
      row({ key: "AAA:lane", repoCode: "AAA" }),
      row({ key: "BBB:lane", repoCode: "BBB" }),
    ]),
    {}
  );
  w.renderTabs(doc, root, after, () => {});

  assert.deepEqual(tabIds(root), ["ALL", "RC", "AAA", "BBB"]);
  assert.equal(tabById(root, "RC"), rc, "an untouched tab was rebuilt");
  assert.equal(tabById(root, "BBB"), bbb, "a re-ordered tab was rebuilt");
  assert.equal(doc.activeElement, bbb, "re-ordering destroyed keyboard focus");
});

test("a tab that leaves the roster is removed and leaves no stale focus", () => {
  const doc = makeDoc();
  const root = makeNode(doc, "div");
  w.renderTabs(
    doc,
    root,
    w.buildView(
      model([
        row({ key: "RC:lane", repoCode: "RC" }),
        row({ key: "AAA:lane", repoCode: "AAA" }),
      ]),
      {}
    ),
    () => {}
  );
  const aaa = tabById(root, "AAA");
  aaa.focus();

  w.renderTabs(doc, root, w.buildView(model([row({ key: "RC:lane", repoCode: "RC" })]), {}), () => {});

  assert.deepEqual(tabIds(root), ["ALL", "RC"]);
  // Focus cannot survive on a node that is gone - but it must not be left
  // pointing at a DETACHED node either.
  assert.equal(aaa.parentNode, null);
  assert.notEqual(doc.activeElement, aaa);
});

// ------------------------------------------------------ card scroll position

test("a card repaint preserves the scroll position of the card region", () => {
  // .cards gains overflow-y:auto, so the wipe would otherwise reset the
  // operator's scroll position to the top every 2000ms.
  const doc = makeDoc();
  const root = makeNode(doc, "div");
  const rows = [];
  for (let i = 0; i < 12; i += 1) {
    rows.push(row({ key: `AAA:lane-${i}`, repoCode: "AAA" }));
  }
  const view = w.buildView(model(rows), {});
  w.renderCards(doc, root, view);
  assert.equal(root.childNodes.length, 12);

  root.scrollTop = 140;
  w.renderCards(doc, root, w.buildView(model(rows), {}));
  assert.equal(root.scrollTop, 140, "the repaint clobbered the scroll position");
  assert.equal(root.childNodes.length, 12);

  // A view scrolled to the top stays at the top - the restore must not invent
  // a scroll offset of its own.
  root.scrollTop = 0;
  w.renderCards(doc, root, w.buildView(model(rows), {}));
  assert.equal(root.scrollTop, 0);
});

// -------------------------------------------------------- status live region

test("writeStatus tolerates a missing node and writes only real messages", () => {
  const doc = makeDoc();
  const node = makeNode(doc, "div");

  // Slice B may not have landed yet - this must not hard-depend on #status.
  assert.doesNotThrow(() => w.writeStatus(null, "RC lane went stale"));
  assert.doesNotThrow(() => w.writeStatus(undefined, "RC lane went stale"));

  // Nothing changed: the live region must be left COMPLETELY untouched. A
  // blanking write is still a write, and an assertion on the resulting text
  // cannot tell the two apart - so this asserts on the write count.
  w.writeStatus(node, null);
  w.writeStatus(node, undefined);
  w.writeStatus(node, "");
  assert.equal(node.textWrites, 0, "the live region was written with no news");
  assert.equal(node.textContent, "");

  w.writeStatus(node, "RC lane went stale");
  assert.equal(node.textWrites, 1);
  assert.equal(node.textContent, "RC lane went stale");
});

// ------------------------------------------------------------ the tab pattern
// index.html carries role="tablist" on #tabstrip-tabs and role="tabpanel" on
// #cards, and renderTabs writes role="tab". Those roles are a CONTRACT, not
// decoration: once assistive tech sees role="tab" it announces "tab 1 of N, use
// arrow keys" and stops exposing the pills as ordinary buttons. A strip that
// announces that and then ignores the arrows is worse than one with no roles at
// all, so the whole pattern is pinned here - ids both ways, arrow roving, and
// the roving tabindex that keeps Tab moving PAST the strip instead of through
// every pill.

const strip = (rows, activeTab, onSelect) => {
  const doc = makeDoc();
  const root = makeNode(doc, "div");
  const cards = makeNode(doc, "section");
  const state = { activeTab: activeTab || "ALL" };
  const select =
    onSelect ||
    ((id) => {
      state.activeTab = id;
      const v = w.buildView(model(rows), { activeTab: state.activeTab });
      w.renderTabs(doc, root, v, select);
      w.renderPanel(cards, v);
    });
  const view = w.buildView(model(rows), { activeTab: state.activeTab });
  w.renderTabs(doc, root, view, select);
  w.renderPanel(cards, view);
  return { doc, root, cards, state };
};

const twoRepos = [
  row({ key: "RC:lane", repoCode: "RC" }),
  row({ key: "AAA:lane", repoCode: "AAA" }),
];

test("tabDomId yields a valid HTML id for an awkward repo code", () => {
  // Repo CODES come from the roster, not from this file, so the renderer cannot
  // assume they are bare letters. An id is an IDREF target here: a space would
  // split an aria-controls list and silently mis-target, and the result also
  // has to survive being written into a document at all.
  const awkward = ["ALL", "RC", "A B", "A.B", "7UP", "x+y", "a_b", "", "a-b"];
  for (const code of awkward) {
    const id = w.tabDomId(code);
    assert.ok(/^[A-Za-z][A-Za-z0-9_-]*$/.test(id), `bad id ${JSON.stringify(id)} for ${code}`);
    assert.equal(/\s/.test(id), false, id);
    assert.equal(/^[\x20-\x7e]+$/.test(id), true, id);
  }
  // Plain codes stay readable rather than being hashed into noise.
  assert.equal(w.tabDomId("ALL"), "tab-ALL");
  assert.equal(w.tabDomId("RC"), "tab-RC");
  assert.equal(w.tabDomId("a-b"), "tab-a-b");
});

test("tabDomId never collapses two different repo codes onto one id", () => {
  // A lossy strip would map "A B" and "A_B" onto the same id, and the two tabs
  // would then claim the same panel - the second one silently wins and the
  // first announces a panel it does not control. The escape must be injective.
  const codes = ["A B", "A_B", "A-B", "A.B", "AB", "A__B", "A_20_B", "a b", "A  B"];
  const seen = new Map();
  for (const code of codes) {
    const id = w.tabDomId(code);
    assert.equal(seen.has(id), false, `${code} collided with ${seen.get(id)} on ${id}`);
    seen.set(id, code);
  }
});

test("every tab carries a stable dom id and points at the card region", () => {
  const { root, cards } = strip(twoRepos);
  assert.equal(w.CARDS_ID, "cards", "aria-controls target must match index.html:84");

  const ids = root.childNodes.map((n) => n.getAttribute("id"));
  assert.deepEqual(ids, ["tab-ALL", "tab-RC", "tab-AAA"]);
  assert.equal(new Set(ids).size, 3, "two tabs share a dom id");

  for (const btn of root.childNodes) {
    assert.equal(btn.getAttribute("role"), "tab");
    assert.equal(btn.getAttribute("aria-controls"), "cards", "a tab controls nothing");
  }
  // And the panel points back, or the relationship is one-way and useless.
  assert.equal(cards.getAttribute("aria-labelledby"), "tab-ALL");
});

test("the card region is labelled by the ACTIVE tab and follows a switch", () => {
  const { root, cards } = strip(twoRepos);
  assert.equal(cards.getAttribute("aria-labelledby"), "tab-ALL");

  tabById(root, "AAA").click();

  assert.equal(cards.getAttribute("aria-labelledby"), "tab-AAA");
  const target = tabById(root, "AAA").getAttribute("id");
  assert.equal(target, "tab-AAA");
  // The IDREF must resolve to a node that is actually in the strip.
  assert.equal(root.childNodes.filter((n) => n.getAttribute("id") === target).length, 1);
});

test("only the active tab is tabindex 0 - Tab moves past the strip, not through it", () => {
  const { root } = strip(twoRepos);
  assert.deepEqual(
    root.childNodes.map((n) => n.getAttribute("tabindex")),
    ["0", "-1", "-1"]
  );

  tabById(root, "AAA").click();
  assert.deepEqual(
    root.childNodes.map((n) => n.getAttribute("tabindex")),
    ["-1", "-1", "0"]
  );
  // Exactly one stop, always - two would put the strip back in the Tab order
  // twice, none would make it unreachable by keyboard at all.
  assert.equal(root.childNodes.filter((n) => n.getAttribute("tabindex") === "0").length, 1);
});

test("ArrowRight moves the selection and takes focus with it", () => {
  const { doc, root, cards } = strip(twoRepos);
  const all = tabById(root, "ALL");
  all.focus();

  const ev = all.press("ArrowRight");

  assert.equal(ev.defaultPrevented, true, "the arrow fell through and scrolled the panel");
  const rc = tabById(root, "RC");
  assert.equal(doc.activeElement, rc, "roving moved the selection but not the focus");
  assert.equal(rc.getAttribute("aria-selected"), "true");
  assert.equal(rc.getAttribute("tabindex"), "0");
  assert.equal(all.getAttribute("aria-selected"), "false");
  assert.equal(all.getAttribute("tabindex"), "-1");
  assert.equal(cards.getAttribute("aria-labelledby"), "tab-RC");
});

test("ArrowLeft walks back and both arrows wrap at the ends", () => {
  const { doc, root } = strip(twoRepos);
  const all = tabById(root, "ALL");
  all.focus();

  all.press("ArrowLeft");
  const aaa = tabById(root, "AAA");
  assert.equal(doc.activeElement, aaa, "ArrowLeft at the head did not wrap to the tail");
  assert.equal(aaa.getAttribute("aria-selected"), "true");

  aaa.press("ArrowRight");
  assert.equal(doc.activeElement, all, "ArrowRight at the tail did not wrap to the head");
  assert.equal(all.getAttribute("aria-selected"), "true");

  all.press("ArrowRight");
  assert.equal(doc.activeElement, tabById(root, "RC"));
});

test("Home and End jump to the ends of the strip", () => {
  const { doc, root } = strip(twoRepos, "RC");
  const rc = tabById(root, "RC");
  rc.focus();

  rc.press("End");
  const aaa = tabById(root, "AAA");
  assert.equal(doc.activeElement, aaa);
  assert.equal(aaa.getAttribute("aria-selected"), "true");

  aaa.press("Home");
  const all = tabById(root, "ALL");
  assert.equal(doc.activeElement, all);
  assert.equal(all.getAttribute("aria-selected"), "true");
});

test("a key the strip does not own is left alone", () => {
  const { doc, root } = strip(twoRepos);
  const all = tabById(root, "ALL");
  all.focus();

  for (const key of ["ArrowUp", "ArrowDown", "PageDown", "a", "Tab", "Escape", undefined]) {
    const ev = all.press(key);
    assert.equal(ev.defaultPrevented, false, `the strip swallowed ${key}`);
    assert.equal(doc.activeElement, all, `${key} moved focus`);
    assert.equal(all.getAttribute("aria-selected"), "true", `${key} changed the selection`);
  }
});

test("the key handler reads the live strip, not a captured index or id", () => {
  // Same property the click handler has: buttons are long-lived now, so a
  // handler that closed over its neighbour or its position at creation time
  // would keep roving the OLD strip after a repo appeared in the middle.
  const doc = makeDoc();
  const root = makeNode(doc, "div");
  const cards = makeNode(doc, "section");
  let rows = [
    row({ key: "RC:lane", repoCode: "RC" }),
    row({ key: "BBB:lane", repoCode: "BBB" }),
  ];
  let activeTab = "ALL";
  const onSelect = (id) => {
    activeTab = id;
    const v = w.buildView(model(rows), { activeTab: activeTab });
    w.renderTabs(doc, root, v, onSelect);
    w.renderPanel(cards, v);
  };
  w.renderTabs(doc, root, w.buildView(model(rows), { activeTab: activeTab }), onSelect);
  assert.deepEqual(tabIds(root), ["ALL", "RC", "BBB"]);

  // A new repo appears BETWEEN RC and BBB. Nodes are reconciled, not rebuilt,
  // so RC keeps the handler it was created with - and RC's right neighbour is
  // no longer the node it was when that handler was installed.
  rows = [
    row({ key: "RC:lane", repoCode: "RC" }),
    row({ key: "AAA:lane", repoCode: "AAA" }),
    row({ key: "BBB:lane", repoCode: "BBB" }),
  ];
  w.renderTabs(doc, root, w.buildView(model(rows), { activeTab: activeTab }), onSelect);
  assert.deepEqual(tabIds(root), ["ALL", "RC", "AAA", "BBB"]);

  const rc = tabById(root, "RC");
  rc.focus();
  rc.press("ArrowRight");

  assert.equal(activeTab, "AAA", "roving used a stale neighbour");
  assert.equal(doc.activeElement, tabById(root, "AAA"));
  assert.equal(cards.getAttribute("aria-labelledby"), "tab-AAA");
});

test("the aria pass did not cost the repaint-survives-focus property", () => {
  // FIX 1 regression guard, re-asserted with the roving tabindex in place. The
  // repaint now WRITES tabindex on every pill every 2000ms; that must remain an
  // attribute write on a surviving node, never a rebuild. Focus on an INACTIVE
  // pill is the interesting case - that is the one whose tabindex stays "-1"
  // while it holds the focus ring.
  const doc = makeDoc();
  const root = makeNode(doc, "div");
  const m = model(twoRepos);
  w.renderTabs(doc, root, w.buildView(m, {}), () => {});

  const aaa = tabById(root, "AAA");
  aaa.focus();
  assert.equal(aaa.getAttribute("tabindex"), "-1", "the inactive pill is not the roving stop");

  w.renderTabs(doc, root, w.buildView(m, {}), () => {});

  assert.equal(tabById(root, "AAA"), aaa, "the repaint rebuilt the focused tab");
  assert.equal(aaa.parentNode, root, "the repaint detached the focused tab");
  assert.equal(doc.activeElement, aaa, "the repaint destroyed keyboard focus");
  assert.equal(aaa.getAttribute("tabindex"), "-1");
  assert.equal(root.childNodes.filter((n) => n.getAttribute("tabindex") === "0").length, 1);
});

test("renderPanel tolerates a missing node and a junk view", () => {
  // Same guard as writeStatus: this file must not hard-depend on #cards, and it
  // runs on the same timer path as buildView, so it has to be total.
  assert.doesNotThrow(() => w.renderPanel(null, w.buildView(model([]), {})));
  assert.doesNotThrow(() => w.renderPanel(undefined, w.buildView(model([]), {})));
  const doc = makeDoc();
  const node = makeNode(doc, "section");
  assert.doesNotThrow(() => w.renderPanel(node, null));
  assert.doesNotThrow(() => w.renderPanel(node, {}));
});

test("applyView actually wires the panel up, not just renderPanel in isolation", () => {
  // Testing renderPanel alone would leave the CALL untested: dropping its line
  // out of applyView would ship a strip whose tabs point at a panel that does
  // not point back, and every other test here would still be green.
  const doc = makeDoc();
  const dom = {
    tabs: makeNode(doc, "div"),
    cards: makeNode(doc, "section"),
    summary: makeNode(doc, "footer"),
  };
  const m = model(twoRepos);
  w.applyView(doc, dom, w.buildView(m, { activeTab: "AAA" }), () => {});

  assert.equal(dom.cards.getAttribute("aria-labelledby"), "tab-AAA");
  assert.equal(tabById(dom.tabs, "AAA").getAttribute("aria-controls"), "cards");
  assert.equal(tabById(dom.tabs, "AAA").getAttribute("tabindex"), "0");
  assert.equal(tabById(dom.tabs, "ALL").getAttribute("tabindex"), "-1");
  // The rest of applyView still ran - the panel wiring is additive.
  assert.ok(dom.cards.childNodes.length >= w.MIN_CARD_SLOTS);
  assert.ok(dom.summary.childNodes.length > 0);
});

test("switching tabs by keyboard still announces nothing", () => {
  // The #status live region is deliberately silent on a tab change. Roving now
  // fires selectTab on every arrow press, so a regression here would make the
  // strip chatter once per keystroke.
  const m = model(twoRepos);
  const all = w.buildView(m, { activeTab: "ALL" });
  const one = w.buildView(m, { activeTab: "AAA" });
  assert.equal(w.statusMessageFor(all, one), null);
  assert.equal(w.statusMessageFor(one, all), null);
});

// ------------------------------------------------- window-size reporting ----
//
// test/clamp.test.js proves, as arithmetic, that a measurement which reads the
// VIEWPORT makes the window ratchet down to an empty grid, and that one which
// reads only the WORK AREA lands on a fixed point in a single step. The tests
// below are what bind that arithmetic to the code actually shipping: they
// assert the reporter never touches a viewport quantity, and that the
// stylesheet carries no viewport-relative bound on anything the reporter
// measures. Either one alone would be a model of a fix rather than the fix.

const fs = require("node:fs");
const path = require("node:path");

const CSS_TEXT = fs.readFileSync(
  path.join(__dirname, "..", "src", "renderer", "widget.css"),
  "utf8"
);

// Pull one top-level rule body out of the stylesheet by selector. Good enough
// for this file: every selector here is a single class on its own line.
function cssBlock(selector) {
  const at = CSS_TEXT.indexOf("\n" + selector + " {");
  assert.notEqual(at, -1, `no "${selector}" rule in widget.css`);
  const open = CSS_TEXT.indexOf("{", at);
  const close = CSS_TEXT.indexOf("}", open);
  assert.ok(close > open, `unterminated "${selector}" rule`);
  return CSS_TEXT.slice(open + 1, close);
}

// Strip /* ... */ so a comment that merely DISCUSSES 100vh is not a hit.
function withoutComments(text) {
  return text.replace(/\/\*[\s\S]*?\*\//g, " ");
}

test("no rule the reporter measures is bounded by a viewport unit", () => {
  // THE WHOLE DEFECT, as a single grep. .panel is what gets measured and
  // .cards is its scrolling child; a vh/vmin/vmax/dvh bound on either one
  // makes the reported box a function of the window height that the report
  // itself just set, which is the feedback loop. A constant is not a fix, so
  // this bans the UNIT rather than a particular number.
  for (const selector of [".panel", ".cards"]) {
    const body = withoutComments(cssBlock(selector));
    assert.ok(
      !/\d\s*(vh|vmin|vmax|dvh|svh|lvh)\b/.test(body),
      `${selector} still carries a viewport-relative length: ${body.trim()}`
    );
  }
});

test("the panel is capped by a value the renderer supplies, not by the viewport", () => {
  const panel = withoutComments(cssBlock(".panel"));
  assert.match(
    panel,
    /max-height:\s*var\(--panel-max-height/,
    ".panel must take its cap from --panel-max-height"
  );
});

test("the card grid is still a reachable scroll container inside the panel", () => {
  // Requirement (ii): when the content genuinely exceeds the work area the
  // window stops at the screen, and the rows past the edge must be SCROLLABLE.
  // Before the max-height existed they were silently clipped and lanes just
  // vanished, so removing the loop must not remove the scroller with it.
  const cards = withoutComments(cssBlock(".cards"));
  assert.match(cards, /overflow-y:\s*auto/, ".cards must scroll");
  assert.match(cards, /min-height:\s*0/, ".cards must be allowed to shrink");
  assert.match(cards, /flex:\s*1\s+1\s+auto/, ".cards must be the flexing child");
  const panel = withoutComments(cssBlock(".panel"));
  assert.match(panel, /flex-direction:\s*column/, ".panel must be a column flexbox");
});

test("the card grid is the only child of the panel that may shrink", () => {
  // The bound now comes from the parent box, so whatever the other children
  // surrender under the cap is height the grid does NOT get. Only .cards has a
  // scrollbar, so only .cards may give any up - otherwise the tab strip or the
  // settings pane quietly loses rows with nothing on screen to reach them.
  for (const selector of [".tabstrip", ".settings", ".summary"]) {
    assert.match(
      withoutComments(cssBlock(selector)),
      /flex:\s*0\s+0\s+auto/,
      `${selector} must not shrink`
    );
  }
});

// --- focus indicators, resolved through a cascade model ---------------------
//
// THE DEFECT THIS GUARDS, measured on screen 2026-09-19: arrow-keying onto a
// tab pill showed NO focus ring, while the gear and #cards both showed one in
// the same frame. The generic `:focus-visible { outline:none; box-shadow:
// var(--focus-ring) }` is specificity (0,1,0); `.tab.is-active` is (0,2,0) and
// also declares box-shadow, so the active rule won and the ring never painted.
// The roving tabindex keeps the strip's only tab stop ON the active pill, so no
// pill could ever show one, and `outline:none` had already removed the browser
// fallback.
//
// A text assertion that one particular selector exists would not catch the NEXT
// rule to do this, and this is a defect FAMILY: any box-shadow rule that can
// co-occur with focus defeats the ring, on specificity or - at a tie - on
// source order (that is how `.card` would swallow it, being (0,1,0) but
// declared later). So these tests model the cascade instead: flatten the
// stylesheet, resolve the winning box-shadow for a given class set plus
// :focus-visible, and assert the winner carries the ring.

function flatRules() {
  const text = withoutComments(CSS_TEXT);
  const out = [];
  const re = /([^{}]+)\{([^{}]*)\}/g;
  let m;
  while ((m = re.exec(text)) !== null) {
    const selectors = m[1].trim();
    if (!selectors || selectors.startsWith("@")) continue;
    for (const sel of selectors.split(",")) {
      const trimmed = sel.trim();
      if (trimmed) out.push({ selector: trimmed, body: m[2], order: out.length });
    }
  }
  return out;
}

// (ids, classes+attributes+pseudo-classes, elements). `::x` is a pseudo-ELEMENT
// and must not count in the second column, hence the (?!:) and the [^:] before.
function specificity(selector) {
  const count = (re) => (selector.match(re) || []).length;
  const ids = count(/#[\w-]+/g);
  const classes = count(/\.[\w-]+/g);
  const attrs = count(/\[[^\]]*\]/g);
  const pseudoClasses = count(/(^|[^:]):(?!:)[\w-]+/g);
  return [ids, classes + attrs + pseudoClasses];
}

function beats(a, b) {
  const sa = specificity(a.selector);
  const sb = specificity(b.selector);
  if (sa[0] !== sb[0]) return sa[0] > sb[0];
  if (sa[1] !== sb[1]) return sa[1] > sb[1];
  return a.order > b.order;
}

function lastBoxShadow(body) {
  // box-shadow values carry commas but never semicolons, so this split is safe.
  let value = null;
  for (const decl of body.split(";")) {
    const m = /^\s*box-shadow\s*:\s*([\s\S]+)$/.exec(decl);
    if (m) value = m[1].trim();
  }
  return value;
}

// Resolve box-shadow for a hypothetical element carrying `classes` and in the
// pseudo-states `pseudos`. Returns the winning declaration's value.
function resolvedBoxShadow(classes, pseudos) {
  const has = new Set(classes);
  const inState = new Set(pseudos);
  let best = null;
  for (const rule of flatRules()) {
    if (!/box-shadow\s*:/.test(rule.body)) continue;
    assert.match(
      rule.selector,
      /^(\.[\w-]+|:[\w-]+)+$/,
      `box-shadow rule "${rule.selector}" is not a simple compound of classes ` +
        "and pseudo-classes, so the cascade model in this test no longer " +
        "describes the stylesheet - extend the model before trusting it"
    );
    const wantClasses = (rule.selector.match(/\.[\w-]+/g) || [])
      .map((c) => c.slice(1));
    const wantPseudos = (rule.selector.match(/(^|[^:]):(?!:)[\w-]+/g) || [])
      .map((p) => p.slice(p.indexOf(":") + 1));
    if (!wantClasses.every((c) => has.has(c))) continue;
    if (!wantPseudos.every((p) => inState.has(p))) continue;
    if (best === null || beats(rule, best)) best = rule;
  }
  return best === null ? null : lastBoxShadow(best.body);
}

test("every box-shadow sits at the top level, so the cascade model holds", () => {
  // The model above flattens @media wrappers away. A box-shadow inside one
  // would be silently mis-ordered by it, so ban the case rather than model it.
  // forced-colors does not paint box-shadow anyway; it restores an outline.
  const text = withoutComments(CSS_TEXT);
  let depth = 0;
  for (let i = 0; i < text.length; i += 1) {
    if (text[i] === "{") depth += 1;
    else if (text[i] === "}") depth -= 1;
    else if (text.startsWith("box-shadow:", i)) {
      assert.equal(depth, 1, `box-shadow at index ${i} is nested in an at-rule`);
    }
  }
});

test("a focused tab pill resolves to a box-shadow that carries the focus ring", () => {
  // The exact shipped case: roving tabindex means the focused pill is ALWAYS
  // the active one, so this is the only tab state that can ever be focused.
  const active = resolvedBoxShadow(["tab", "is-active"], ["focus-visible"]);
  assert.ok(active, "no box-shadow resolves for a focused active tab");
  assert.match(
    active,
    /--focus-ring/,
    "the focused ACTIVE tab must win with the focus ring, not with " +
      `.tab.is-active's own shadow (resolved: ${active})`
  );
  // Compose, do not replace: an active pill keeps its raised look as well.
  assert.match(
    active,
    /--shadow-card-soft/,
    "the focus ring must be composed WITH the active pill's shadow, not " +
      `swapped for it (resolved: ${active})`
  );
  const inactive = resolvedBoxShadow(["tab"], ["focus-visible"]);
  assert.match(inactive, /--focus-ring/, "a focused inactive tab needs a ring too");
});

test("the focus ring is not simply painted on tabs that are not focused", () => {
  // Without this the test above passes trivially if someone puts the ring on
  // .tab.is-active itself, which would light every active pill permanently.
  const resting = resolvedBoxShadow(["tab", "is-active"], []);
  assert.ok(resting, "an active tab should still carry its own shadow");
  assert.doesNotMatch(
    resting,
    /--focus-ring/,
    `an unfocused active tab must not show the ring (resolved: ${resting})`
  );
});

test("no box-shadow rule anywhere swallows the focus ring", () => {
  // The family sweep. .card is (0,1,0) like :focus-visible but declared AFTER
  // it, so it would win on source order the moment anything makes a card
  // focusable - latent today, guarded now. .panel and .gear are the controls:
  // .panel loses on source order and .gear declares no shadow at all, which is
  // exactly why the gear was the element that visibly worked.
  for (const classes of [["card"], ["card", "is-wide"], ["panel"], ["gear"]]) {
    const value = resolvedBoxShadow(classes, ["focus-visible"]);
    assert.ok(value, `no box-shadow resolves for focused .${classes.join(".")}`);
    assert.match(
      value,
      /--focus-ring/,
      `focused .${classes.join(".")} resolves to "${value}", which has no ` +
        "focus ring - see the focus-indicator note in widget.css"
    );
  }
});

test("the scrolling card grid opts out of the window drag region", () => {
  // -webkit-app-region:drag hit-tests as window CAPTION, so the compositor eats
  // the pointer and the wheel never reaches the page. Measured 2026-09-19: with
  // the grid overflowing, the wheel moved nothing in either direction, focused
  // or unfocused, while Tab-to-#cards then End still reached the last card.
  assert.match(
    withoutComments(cssBlock(".panel")),
    /-webkit-app-region:\s*drag/,
    ".panel is what makes the frameless window draggable"
  );
  assert.match(
    withoutComments(cssBlock(".cards")),
    /-webkit-app-region:\s*no-drag/,
    ".cards must opt out of the drag region or the wheel cannot scroll it"
  );
});

test("the summary footer stays draggable, because it is the grab handle", () => {
  // The trade for the line above: .cards is most of the panel, so the footer
  // (full content width, no no-drag inside it) plus the padding gutters are
  // what is left to move the window by. Making the footer no-drag would leave
  // the widget hard to reposition, which is not an acceptable outcome either.
  assert.doesNotMatch(
    withoutComments(cssBlock(".summary")),
    /-webkit-app-region:\s*no-drag/,
    ".summary must stay draggable - it is the always-present grab handle"
  );
});

// A window stub whose every VIEWPORT quantity is a counted getter. Reading any
// one of them is the defect, so the counter is the assertion.
function makeWin(availHeight, viewportHeight) {
  const reads = [];
  const win = { screen: { availHeight: availHeight, availWidth: 1920 } };
  for (const prop of [
    "innerHeight", "innerWidth", "outerHeight", "outerWidth", "visualViewport",
  ]) {
    Object.defineProperty(win, prop, {
      get() {
        reads.push(prop);
        return viewportHeight;
      },
    });
  }
  win._reads = reads;
  return win;
}

function makePanel(width, height) {
  const props = {};
  return {
    _props: props,
    style: {
      setProperty(k, v) { props[k] = v; },
      removeProperty(k) { delete props[k]; },
    },
    getBoundingClientRect() { return { width: width, height: height }; },
  };
}

function makeBridge() {
  const sent = [];
  return { sent: sent, reportSize(s) { sent.push(s); } };
}

test("the reported size is the panel box plus its margins", () => {
  const win = makeWin(1040, 352);
  const panel = makePanel(399, 336);
  const bridge = makeBridge();
  w.createSizeReporter(win, panel, bridge)();
  // widget.css .panel { margin: 8px } on all four sides.
  assert.deepEqual(bridge.sent, [{ width: 415, height: 352 }]);
});

test("the reporter never reads a viewport quantity", () => {
  // This is defect A at its root. If the reported box can see the window it is
  // inside, the clamp feeds it back and the window ratchets.
  const win = makeWin(1040, 352);
  const panel = makePanel(399, 336);
  const report = w.createSizeReporter(win, panel, makeBridge());
  report();
  report();
  assert.deepEqual(win._reads, [], `reporter read the viewport: ${win._reads.join(", ")}`);
});

test("the reported size does not depend on the previous window height", () => {
  // Same content, two wildly different windows - the pre-reveal 352 and the
  // collapsed floor 126 the state file is currently sitting at. Identical
  // reports is what makes the map a one-step fixed point.
  const panelA = makePanel(399, 336);
  const panelB = makePanel(399, 336);
  const tall = makeBridge();
  const short = makeBridge();
  w.createSizeReporter(makeWin(1040, 900), panelA, tall)();
  w.createSizeReporter(makeWin(1040, 126), panelB, short)();
  assert.deepEqual(short.sent, tall.sent);
});

test("the panel cap is derived from the display work area", () => {
  const win = makeWin(1040, 352);
  const panel = makePanel(399, 336);
  w.createSizeReporter(win, panel, makeBridge())();
  // availHeight minus the panel's own 8px margins: the panel may fill the
  // work area and not one pixel more, and that bound is a HARDWARE constant.
  assert.equal(panel._props["--panel-max-height"], "1024px");
});

test("a screen with no work area leaves the cap unset rather than guessing", () => {
  const win = { screen: null };
  const panel = makePanel(399, 336);
  const bridge = makeBridge();
  w.createSizeReporter(win, panel, bridge)();
  assert.equal(panel._props["--panel-max-height"], undefined);
  // and it still reports, so a headless/odd host does not lose sizing entirely.
  assert.deepEqual(bridge.sent, [{ width: 415, height: 352 }]);
});

test("a pre-layout zero box is not reported - defect B", () => {
  // The window was revealed at 404x352 and then walked. Whatever the reveal
  // gate does, the renderer must never hand main.js a box it measured before
  // layout ran: a 0x0 panel is not a content size, it is the absence of one.
  const bridge = makeBridge();
  const panel = makePanel(0, 0);
  const report = w.createSizeReporter(makeWin(1040, 352), panel, bridge);
  report();
  assert.deepEqual(bridge.sent, [], "reported a pre-layout box");
  // Once layout lands, the very first thing main.js sees is a real box.
  panel.getBoundingClientRect = () => ({ width: 399, height: 336 });
  report();
  assert.deepEqual(bridge.sent, [{ width: 415, height: 352 }]);
});

test("an unchanged box is reported once, not once per repaint", () => {
  // The widget repaints every 2000ms forever. Re-sending an identical size is
  // pure IPC churn, and it is also a setBounds per tick on the main side.
  const bridge = makeBridge();
  const panel = makePanel(399, 336);
  const report = w.createSizeReporter(makeWin(1040, 352), panel, bridge);
  report();
  report();
  report();
  assert.equal(bridge.sent.length, 1);
  panel.getBoundingClientRect = () => ({ width: 399, height: 444 });
  report();
  assert.equal(bridge.sent.length, 2);
  assert.deepEqual(bridge.sent[1], { width: 415, height: 460 });
});

test("a fractional box is rounded UP so the content never loses its last row", () => {
  const bridge = makeBridge();
  w.createSizeReporter(makeWin(1040, 352), makePanel(398.2, 335.4), bridge)();
  assert.deepEqual(bridge.sent, [{ width: 415, height: 352 }]);
});

test("the real reporter and the real clamp settle in one step - end to end", () => {
  // clamp.test.js iterates the map as arithmetic; this runs the SAME loop
  // through both shipped implementations, so a regression in either half shows
  // up here even if each half still looks right on its own.
  const { clampToContent } = require("../src/clamp.js");
  const AVAIL = 1040;
  const WORK = { x: 0, y: 0, width: 1920, height: AVAIL };
  const MIN = { width: 240, height: 120 };
  const PANEL_CHROME = 110; // everything in .panel that is not the card grid

  function run(naturalCards, startHeight) {
    const props = {};
    const panel = {
      style: {
        setProperty(k, v) { props[k] = v; },
        removeProperty(k) { delete props[k]; },
      },
      // The CSS model, honouring whatever cap the reporter just applied. Note
      // what is NOT in this function: the window height. That is the fix.
      getBoundingClientRect() {
        const natural = PANEL_CHROME + naturalCards;
        const cap = props["--panel-max-height"];
        const capPx = cap ? parseFloat(cap) : Infinity;
        return { width: 399, height: Math.min(natural, capPx) };
      },
    };
    let sent = null;
    const report = w.createSizeReporter(
      { screen: { availHeight: AVAIL } },
      panel,
      { reportSize(s) { sent = s; } }
    );

    const seq = [startHeight];
    let h = startHeight;
    for (let i = 0; i < 25; i += 1) {
      sent = null; // only count sizes this turn actually pushed
      report();
      if (sent === null) continue; // de-duped: nothing to apply, so nothing moves
      h = clampToContent({
        requested: { x: 40, y: 40, width: 415, height: h },
        content: sent,
        workArea: WORK,
        min: MIN,
      }).height;
      seq.push(h);
    }
    return seq;
  }

  // Fits the screen: lands on the content size and stays there, from a start
  // above it, below it, and at the collapsed floor the state file holds today.
  for (const start of [900, 352, 126]) {
    const seq = run(420, start);
    const settled = seq[seq.length - 1];
    assert.equal(settled, PANEL_CHROME + 420 + 16, `start ${start} -> ${seq.join(" ")}`);
    // One clamp, then nothing: the de-dupe means no further sizes are applied.
    assert.equal(seq.length, 2, `more than one resize from ${start}: ${seq.join(" ")}`);
  }

  // Exceeds the screen: stops ON the work area and does not walk past it.
  const tall = run(4000, 352);
  assert.equal(tall[tall.length - 1], WORK.height);
  assert.equal(tall.length, 2);
});

test("the reporter survives a missing bridge or panel", () => {
  assert.doesNotThrow(() => w.createSizeReporter(makeWin(1040, 352), null, makeBridge())());
  assert.doesNotThrow(() => w.createSizeReporter(makeWin(1040, 352), makePanel(9, 9), null)());
  assert.doesNotThrow(() => w.createSizeReporter(null, null, null)());
});

// --------------------------------------------------- right-click routing ----

function elem(tag, attrs, parent) {
  const a = attrs || {};
  return {
    tagName: String(tag).toUpperCase(),
    isContentEditable: a.contentEditable === true,
    parentElement: parent || null,
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(a, k) ? a[k] : null; },
  };
}

test("right-clicking a non-text control asks for the app menu - defect D", () => {
  // The old handler bailed out for "button, input, select, textarea, a, label",
  // and those elements are -webkit-app-region: no-drag, so Electron's own
  // system-context-menu never fires over them either. A right-click on a tab
  // pill or the gear therefore produced NOTHING AT ALL.
  assert.equal(w.wantsNativeTextMenu(elem("button")), false, "gear / tab pill");
  assert.equal(w.wantsNativeTextMenu(elem("input", { type: "range" })), false, "opacity slider");
  assert.equal(w.wantsNativeTextMenu(elem("input", { type: "checkbox" })), false, "always-on-top");
  assert.equal(w.wantsNativeTextMenu(elem("label")), false);
  assert.equal(w.wantsNativeTextMenu(elem("a")), false);
  assert.equal(w.wantsNativeTextMenu(elem("select")), false);
  assert.equal(w.wantsNativeTextMenu(elem("div")), false);
  assert.equal(w.wantsNativeTextMenu(elem("span")), false);
});

test("right-clicking something the user can TYPE into keeps the native menu", () => {
  // The carve-out, and the whole carve-out: a native context menu is worth
  // having exactly where Cut / Copy / Paste / Select All mean something.
  assert.equal(w.wantsNativeTextMenu(elem("textarea")), true);
  assert.equal(w.wantsNativeTextMenu(elem("input", { type: "text" })), true);
  assert.equal(w.wantsNativeTextMenu(elem("input", { type: "search" })), true);
  assert.equal(w.wantsNativeTextMenu(elem("input", { type: "password" })), true);
  assert.equal(w.wantsNativeTextMenu(elem("input", { type: "number" })), true);
  assert.equal(w.wantsNativeTextMenu(elem("input", { type: "TEXT" })), true, "case folded");
  assert.equal(w.wantsNativeTextMenu(elem("input", {})), true, "no type attribute is type=text");
  assert.equal(w.wantsNativeTextMenu(elem("div", { contentEditable: true })), true);
});

test("the text carve-out follows the ancestor chain, not just the target", () => {
  const editable = elem("div", { contentEditable: true });
  assert.equal(w.wantsNativeTextMenu(elem("span", {}, editable)), true);
  const pill = elem("button");
  assert.equal(w.wantsNativeTextMenu(elem("span", {}, pill)), false);
});

test("wantsNativeTextMenu never throws on junk", () => {
  for (const junk of [null, undefined, 0, "", {}, { tagName: 7 }]) {
    assert.doesNotThrow(() => w.wantsNativeTextMenu(junk));
    assert.equal(w.wantsNativeTextMenu(junk), false);
  }
});
