// lane-widget/src/renderer/widget.js
//
// Renderer for the lane / worker panel.
//
// SHAPE: this file is split into a PURE half and a DUMB half.
//
//   PURE   buildView(model, opts) and its helpers take the model object that
//          src/model.js produces and return a plain description of what should
//          be on screen - tabs, cards, summary. No DOM, no electron, no clock,
//          no IO. That half is unit tested in test/render.test.js.
//
//   SHIM   applyView(dom, view) walks that description and sets text and class
//          names on elements that ALREADY EXIST in index.html. It creates no
//          layout decisions of its own, which is why it needs no test: there is
//          no jsdom in this repo and adding one would be a new dependency.
//
// The split is also what makes the no-reflow rule cheap. buildView always emits
// at least MIN_CARD_SLOTS cards, padding with placeholder descriptors of the
// identical key set, so the empty state occupies the same box as a populated
// one and the shim never adds or removes a container.
//
// Model shape consumed here is the real one from src/model.js:99-113, not a
// paraphrase: { key, repoCode, kind, label, state, lane, runId, ageS, children,
// logAgeS, stalled, worktreeTail } with summary
// { repos, running, reclaimable, free, children, stalled }.

"use strict";

// ops/loop/lanes.py:143-145, mirrored in src/locks.js:25-27.
var STATE_FREE = "FREE";
var STATE_RUNNING = "RUNNING";
var STATE_RECLAIMABLE = "RECLAIMABLE";

var TAB_ALL = "ALL";
var TAB_ALL_LABEL = "All";

// RC is always roster index 0 (src/repos.js contract, src/model.js:138).
var RC_CODE = "RC";

// The empty state and a small populated state must occupy the same box.
var MIN_CARD_SLOTS = 3;

// Shown wherever a value is genuinely absent. RC renders absence as "-".
var NO_DATA = "-";

// --------------------------------------------------------------- pure half --

function isObject(v) {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function finiteOrNull(v) {
  return typeof v === "number" && isFinite(v) ? v : null;
}

function stringOrNull(v) {
  return typeof v === "string" && v !== "" ? v : null;
}

/**
 * The state WORD. This is the accessible carrier of state - the tinted rule and
 * the colored text are redundant encodings on top of it, never the only signal.
 * An unrecognised state reads "unreadable" rather than silently passing as idle.
 */
function stateTextFor(state) {
  if (state === STATE_RUNNING) return "running";
  if (state === STATE_RECLAIMABLE) return "stale";
  if (state === STATE_FREE) return "idle";
  return "unreadable";
}

/** Class suffix for the card, one per state word. */
function stateKeyFor(state) {
  return stateTextFor(state);
}

/**
 * The hero value - the one thing readable from across the room.
 * RUNNING -> the lane name. RECLAIMABLE -> "stale". FREE -> "idle".
 *
 * Deliberately NOT row.label: src/model.js:85-89 returns the lane name for a
 * RECLAIMABLE lane row too, and a stale lane that renders its lane name as the
 * hero is indistinguishable from a running one at a glance. The build contract
 * (spec 4b) asks for "stale", so the hero is computed here.
 */
function heroFor(row) {
  var r = isObject(row) ? row : {};
  var state = r.state;
  if (state === STATE_RUNNING) {
    return stringOrNull(r.lane) || stringOrNull(r.label) || "running";
  }
  if (state === STATE_RECLAIMABLE) return "stale";
  if (state === STATE_FREE) return "idle";
  return "unreadable";
}

/** Card label: repo CODE plus kind, e.g. "RC lane". Never a path, never a name. */
function cardLabelFor(row) {
  var r = isObject(row) ? row : {};
  var code = stringOrNull(r.repoCode) || NO_DATA;
  var kind = stringOrNull(r.kind);
  return kind === null ? code : code + " " + kind;
}

/** Coarse age. Absent, negative or non-finite all read as "-". */
function formatAge(seconds) {
  var s = finiteOrNull(seconds);
  if (s === null || s < 0) return NO_DATA;
  if (s < 60) return Math.round(s) + "s";
  if (s < 3600) return Math.floor(s / 60) + "m";
  if (s < 86400) return Math.floor(s / 3600) + "h";
  return Math.floor(s / 86400) + "d";
}

function formatCount(n) {
  var v = finiteOrNull(n);
  return v === null ? NO_DATA : String(Math.max(0, Math.round(v)));
}

/** The small dim foot line: age, child count, log age. */
function metaFor(row) {
  var r = isObject(row) ? row : {};
  var parts = [
    "age " + formatAge(r.ageS),
    "kids " + formatCount(r.children),
    "log " + formatAge(r.logAgeS),
  ];
  if (r.stalled === true) parts.push("stalled");
  return parts.join(" - ");
}

/**
 * Tab ids: "All" first, then RC, then every other repo CODE in first-appearance
 * order. RC is forced to the front because model.rows is sorted by STATE, so a
 * quiet RC can otherwise appear after a busy sibling.
 */
function buildTabs(model) {
  var m = isObject(model) ? model : {};
  var rows = Array.isArray(m.rows) ? m.rows : [];
  var seen = Object.create(null);
  var codes = [];
  for (var i = 0; i < rows.length; i += 1) {
    var code = isObject(rows[i]) ? stringOrNull(rows[i].repoCode) : null;
    if (code === null || seen[code] === true) continue;
    seen[code] = true;
    codes.push(code);
  }
  if (seen[RC_CODE] === true) {
    codes = [RC_CODE].concat(codes.filter(function (c) { return c !== RC_CODE; }));
  }
  var tabs = [{ id: TAB_ALL, label: TAB_ALL_LABEL }];
  for (var j = 0; j < codes.length; j += 1) {
    tabs.push({ id: codes[j], label: codes[j] });
  }
  return tabs;
}

/** An active tab that no longer exists falls back to "All" rather than blanking. */
function resolveActiveTab(tabs, requested) {
  var list = Array.isArray(tabs) ? tabs : [];
  var want = stringOrNull(requested);
  for (var i = 0; i < list.length; i += 1) {
    if (isObject(list[i]) && list[i].id === want) return want;
  }
  return TAB_ALL;
}

function visibleRows(rows, opts) {
  var list = Array.isArray(rows) ? rows.filter(isObject) : [];
  var o = isObject(opts) ? opts : {};
  var tab = stringOrNull(o.activeTab) || TAB_ALL;
  var showFree = o.showFree !== false;
  return list.filter(function (row) {
    if (tab !== TAB_ALL && row.repoCode !== tab) return false;
    if (!showFree && row.state === STATE_FREE) return false;
    return true;
  });
}

function cardFor(row, index) {
  return {
    key: stringOrNull(isObject(row) ? row.key : null) || "slot-" + index,
    placeholder: false,
    stateKey: stateKeyFor(isObject(row) ? row.state : null),
    stateText: stateTextFor(isObject(row) ? row.state : null),
    label: cardLabelFor(row),
    runId: stringOrNull(isObject(row) ? row.runId : null) || NO_DATA,
    hero: heroFor(row),
    meta: metaFor(row),
    // Every third slot is wide, echoing the reference's mixed-width rows.
    // Index-derived on purpose: a placeholder and a real card at the same slot
    // get the same width, so filling a slot never changes the layout.
    wide: index % 3 === 2,
  };
}

/** Identical key set to cardFor - that identity IS the no-reflow property. */
function placeholderCard(index) {
  return {
    key: "placeholder-" + index,
    placeholder: true,
    stateKey: "idle",
    stateText: "no data",
    label: NO_DATA,
    runId: NO_DATA,
    hero: NO_DATA,
    meta: NO_DATA,
    wide: index % 3 === 2,
  };
}

function buildCards(rows) {
  var list = Array.isArray(rows) ? rows : [];
  var cards = [];
  for (var i = 0; i < list.length; i += 1) {
    cards.push(cardFor(list[i], i));
  }
  while (cards.length < MIN_CARD_SLOTS) {
    cards.push(placeholderCard(cards.length));
  }
  return cards;
}

/** REPOS n - RUNNING n - STALE n - CHILDREN n */
function buildSummary(summary) {
  var s = isObject(summary) ? summary : {};
  return [
    { label: "REPOS", value: formatCount(s.repos) },
    { label: "RUNNING", value: formatCount(s.running) },
    { label: "STALE", value: formatCount(s.reclaimable) },
    { label: "CHILDREN", value: formatCount(s.children) },
  ];
}

/**
 * buildView(model, opts) -> the full render description.
 *
 * Total by construction: a null model, a model with no rows and a model with
 * junk rows all return the same shape. This feeds an IPC push on a timer, so a
 * throw here would stop the panel updating for the rest of the session.
 */
function buildView(model, opts) {
  var m = isObject(model) ? model : {};
  var o = isObject(opts) ? opts : {};
  var rows = Array.isArray(m.rows) ? m.rows.filter(isObject) : [];
  var tabs = buildTabs({ rows: rows });
  var activeTab = resolveActiveTab(tabs, o.activeTab);
  var shown = visibleRows(rows, { activeTab: activeTab, showFree: o.showFree !== false });
  return {
    tabs: tabs,
    activeTab: activeTab,
    cards: buildCards(shown),
    summary: buildSummary(m.summary),
    rowCount: shown.length,
    slots: Math.max(MIN_CARD_SLOTS, shown.length),
    empty: shown.length === 0,
  };
}

// ---------------------------------------------------------------- DOM shim --
// Deliberately decision-free: it reads the description above and writes text
// and class names. No measuring, no branching on data, no layout maths.

function el(doc, tag, cls, text) {
  var node = doc.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function renderTabs(doc, root, view, onSelect) {
  root.textContent = "";
  view.tabs.forEach(function (tab) {
    var btn = el(doc, "button", "tab", tab.label);
    btn.type = "button";
    btn.setAttribute("role", "tab");
    btn.dataset.tabId = tab.id;
    var active = tab.id === view.activeTab;
    if (active) btn.classList.add("is-active");
    btn.setAttribute("aria-selected", active ? "true" : "false");
    btn.addEventListener("click", function () { onSelect(tab.id); });
    root.appendChild(btn);
  });
}

function renderCards(doc, root, view) {
  root.textContent = "";
  view.cards.forEach(function (card) {
    var box = el(doc, "div", "card state-" + card.stateKey);
    if (card.placeholder) box.classList.add("is-placeholder");
    if (card.wide) box.classList.add("is-wide");

    var top = el(doc, "div", "card-top");
    top.appendChild(el(doc, "span", "card-label", card.label));
    top.appendChild(el(doc, "span", "card-run", card.runId));
    box.appendChild(top);

    box.appendChild(el(doc, "div", "card-hero", card.hero));

    var foot = el(doc, "div", "card-foot");
    foot.appendChild(el(doc, "span", "card-state", card.stateText));
    foot.appendChild(el(doc, "span", "card-meta", card.meta));
    box.appendChild(foot);

    box.appendChild(el(doc, "div", "state-rule"));
    root.appendChild(box);
  });
}

function renderSummary(doc, root, view) {
  root.textContent = "";
  view.summary.forEach(function (item, i) {
    if (i > 0) root.appendChild(el(doc, "span", "summary-sep", "-"));
    var wrap = el(doc, "div", "summary-item");
    wrap.appendChild(el(doc, "span", "summary-label", item.label));
    wrap.appendChild(el(doc, "span", "summary-value", item.value));
    root.appendChild(wrap);
  });
}

function applyView(doc, dom, view, onSelect) {
  renderTabs(doc, dom.tabs, view, onSelect);
  renderCards(doc, dom.cards, view);
  renderSummary(doc, dom.summary, view);
}

// ---------------------------------------------------------------- boot ------

function boot(win, doc, bridge) {
  var dom = {
    panel: doc.getElementById("panel"),
    tabs: doc.getElementById("tabstrip-tabs"),
    cards: doc.getElementById("cards"),
    summary: doc.getElementById("summary"),
    settings: doc.getElementById("settings"),
    gear: doc.getElementById("gear"),
    opacity: doc.getElementById("opt-opacity"),
    opacityOut: doc.getElementById("opt-opacity-out"),
    onTop: doc.getElementById("opt-ontop"),
    onTopOut: doc.getElementById("opt-ontop-out"),
    showFree: doc.getElementById("opt-showfree"),
    showFreeOut: doc.getElementById("opt-showfree-out"),
    poll: doc.getElementById("opt-poll"),
    pollOut: doc.getElementById("opt-poll-out"),
  };

  var lastModel = null;
  var activeTab = TAB_ALL;
  // store.js DEFAULTS - the real values arrive from the bridge a tick later.
  var settings = { opacity: 0.94, alwaysOnTop: true, showFree: true, fastMs: 2000 };

  function reportSize() {
    if (!bridge || typeof bridge.reportSize !== "function" || !dom.panel) return;
    var rect = dom.panel.getBoundingClientRect();
    // The panel carries an 8px margin on every side (widget.css .panel).
    bridge.reportSize({
      width: Math.ceil(rect.width) + 16,
      height: Math.ceil(rect.height) + 16,
    });
  }

  function render() {
    var view = buildView(lastModel, {
      activeTab: activeTab,
      showFree: settings.showFree,
    });
    activeTab = view.activeTab;
    applyView(doc, dom, view, selectTab);
    // Measure AFTER paint - a synchronous read here returns the pre-layout box.
    if (typeof win.requestAnimationFrame === "function") {
      win.requestAnimationFrame(reportSize);
    } else {
      reportSize();
    }
  }

  function selectTab(id) {
    activeTab = id;
    render();
  }

  function paintSettings() {
    if (dom.opacity) dom.opacity.value = String(settings.opacity);
    if (dom.opacityOut) dom.opacityOut.textContent = Math.round(settings.opacity * 100) + "%";
    if (dom.onTop) dom.onTop.checked = !!settings.alwaysOnTop;
    if (dom.onTopOut) dom.onTopOut.textContent = settings.alwaysOnTop ? "on" : "off";
    if (dom.showFree) dom.showFree.checked = !!settings.showFree;
    if (dom.showFreeOut) dom.showFreeOut.textContent = settings.showFree ? "on" : "off";
    if (dom.poll) dom.poll.value = String(settings.fastMs);
    if (dom.pollOut) dom.pollOut.textContent = settings.fastMs + "ms";
  }

  function pushSettings(patch) {
    settings = Object.assign({}, settings, patch);
    paintSettings();
    render();
    if (bridge && typeof bridge.setState === "function") {
      Promise.resolve(bridge.setState(patch))
        .then(function (resolved) {
          if (isObject(resolved)) {
            settings = Object.assign({}, settings, resolved);
            paintSettings();
            render();
          }
        })
        .catch(function () { /* main owns the store - a rejected set is not fatal */ });
    }
  }

  if (dom.gear) {
    dom.gear.addEventListener("click", function () {
      var open = dom.settings.hasAttribute("hidden");
      if (open) dom.settings.removeAttribute("hidden");
      else dom.settings.setAttribute("hidden", "");
      dom.gear.classList.toggle("is-open", open);
      dom.gear.setAttribute("aria-expanded", open ? "true" : "false");
      render();
    });
  }
  if (dom.opacity) {
    dom.opacity.addEventListener("input", function () {
      pushSettings({ opacity: Number(dom.opacity.value) });
    });
  }
  if (dom.onTop) {
    dom.onTop.addEventListener("change", function () {
      pushSettings({ alwaysOnTop: !!dom.onTop.checked });
    });
  }
  if (dom.showFree) {
    dom.showFree.addEventListener("change", function () {
      pushSettings({ showFree: !!dom.showFree.checked });
    });
  }
  if (dom.poll) {
    dom.poll.addEventListener("change", function () {
      pushSettings({ fastMs: Number(dom.poll.value) });
    });
  }

  // Right-click anywhere that is NOT an interactive control opens the window
  // menu (Minimize / Close to tray). Controls keep their own default handling.
  doc.addEventListener("contextmenu", function (event) {
    var t = event.target;
    if (t && typeof t.closest === "function" && t.closest("button, input, select, textarea, a, label")) {
      return;
    }
    event.preventDefault();
    if (bridge && typeof bridge.openWindowMenu === "function") bridge.openWindowMenu();
  });

  if (bridge && typeof bridge.onModel === "function") {
    bridge.onModel(function (model) {
      lastModel = model;
      render();
    });
  }
  if (bridge && typeof bridge.getState === "function") {
    Promise.resolve(bridge.getState())
      .then(function (state) {
        if (isObject(state)) settings = Object.assign({}, settings, state);
        paintSettings();
        render();
      })
      .catch(function () { paintSettings(); render(); });
  } else {
    paintSettings();
    render();
  }

  // The panel can change height without a model push (settings toggled, tabs
  // wrapping at a new width), so re-report on any box change too.
  if (typeof win.ResizeObserver === "function" && dom.panel) {
    new win.ResizeObserver(reportSize).observe(dom.panel);
  }

  // First paint before any IPC arrives: the empty state, in its final box.
  paintSettings();
  render();
}

// -------------------------------------------------------------- wiring ------
// Node (the test) gets the pure half. The renderer gets the app. Neither path
// touches the other's globals, so this file loads cleanly in both.

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    STATE_FREE: STATE_FREE,
    STATE_RUNNING: STATE_RUNNING,
    STATE_RECLAIMABLE: STATE_RECLAIMABLE,
    TAB_ALL: TAB_ALL,
    MIN_CARD_SLOTS: MIN_CARD_SLOTS,
    NO_DATA: NO_DATA,
    stateTextFor: stateTextFor,
    stateKeyFor: stateKeyFor,
    heroFor: heroFor,
    cardLabelFor: cardLabelFor,
    formatAge: formatAge,
    formatCount: formatCount,
    metaFor: metaFor,
    buildTabs: buildTabs,
    resolveActiveTab: resolveActiveTab,
    visibleRows: visibleRows,
    buildCards: buildCards,
    buildSummary: buildSummary,
    buildView: buildView,
  };
}

if (typeof window !== "undefined" && typeof document !== "undefined") {
  window.addEventListener("DOMContentLoaded", function () {
    boot(window, document, window.laneWidget);
  });
}
