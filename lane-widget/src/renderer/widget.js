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

// The card region's element id (index.html:84). Every tab's aria-controls points
// here and the region points back at the active tab with aria-labelledby, which
// is the half of the tab pattern that only DOM ids can express.
var CARDS_ID = "cards";

// A live region read aloud on a 2000ms cadence has to stay short. Past this
// many simultaneous transitions the message summarises the remainder instead of
// reciting it - a ten-clause sentence is a sentence nobody hears the end of.
var MAX_STATUS_CHANGES = 3;

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

/**
 * The small dim foot line: the stall alarm, then age, child count, log age.
 *
 * ORDER IS LOAD-BEARING. This line is white-space:nowrap inside an
 * overflow-hidden card, so at the minimum column width the TAIL is what
 * disappears. "stalled" used to be pushed LAST, which made the single most
 * operationally important token on the card the first one to be clipped -
 * observed on screen rendering as "age ... - kids 0 - log 2(" cut mid-glyph.
 * It now leads, so it survives any truncation the card width imposes.
 */
function metaFor(row) {
  var r = isObject(row) ? row : {};
  var parts = [];
  if (r.stalled === true) parts.push("stalled");
  parts.push("age " + formatAge(r.ageS));
  parts.push("kids " + formatCount(r.children));
  parts.push("log " + formatAge(r.logAgeS));
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

/**
 * A stable, valid HTML id for a tab button.
 *
 * aria-controls and aria-labelledby are IDREFs, so a tab and the card region
 * can only point at each other through real ids - which means the renderer has
 * to MINT one, and tab ids are repo CODES that arrive from the roster rather
 * than from this file. A code is not guaranteed to be bare letters: a space
 * would split an IDREF list and silently mis-target, and a leading digit is a
 * legal id but not a legal bare CSS selector.
 *
 * The escape is INJECTIVE rather than a lossy strip, and that is the load-
 * bearing part. Replacing junk with "_" would map "A B" and "A_B" onto the same
 * id, two tabs would then claim the same panel, and the second one would
 * silently win while the first announced a panel it does not control. Here
 * every character outside [A-Za-z0-9-] becomes "_<hex>_" and a literal "_"
 * doubles to "__"; hex digits are never "_", so the two forms cannot be
 * confused and two different codes can never collapse together.
 */
function tabDomId(tabId) {
  var raw = stringOrNull(tabId);
  var out = "";
  if (raw !== null) {
    for (var i = 0; i < raw.length; i += 1) {
      var ch = raw.charAt(i);
      if (
        (ch >= "A" && ch <= "Z") ||
        (ch >= "a" && ch <= "z") ||
        (ch >= "0" && ch <= "9") ||
        ch === "-"
      ) {
        out += ch;
      } else if (ch === "_") {
        out += "__";
      } else {
        out += "_" + raw.charCodeAt(i).toString(16) + "_";
      }
    }
  }
  // The "tab-" prefix is not cosmetic: it guarantees the id starts with a
  // letter whatever the code was, and it keeps the widget's ids out of the way
  // of the hand-written ones in index.html.
  return "tab-" + out;
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

/**
 * statusMessageFor(prevView, nextView) -> a short ASCII sentence, or null.
 *
 * The accessible announcement channel. index.html carries a visually-hidden
 * role=status live region; the CARD REGION itself is deliberately NOT live,
 * because renderCards tears the whole region down every repaint and an
 * aria-live on it made a screen reader re-announce every card, every label and
 * every meta line once per poll, forever.
 *
 * Only a genuine state TRANSITION earns a sentence:
 *   - a card present in both views whose state word changed.
 * Everything else is silent on purpose. A row that merely APPEARS is not a
 * transition (it may be the first paint, or a tab switch widening the filter),
 * and a row that LEAVES the view is usually a filter change, not an event.
 * Writing unconditionally would re-announce just as badly as the old live
 * region did, so this returns null when nothing changed and the caller then
 * leaves the node completely untouched.
 *
 * Total by construction - it runs on the same timer path as buildView.
 */
function statusMessageFor(prevView, nextView) {
  var prev = isObject(prevView) ? prevView : null;
  var next = isObject(nextView) ? nextView : null;
  if (prev === null || next === null) return null;

  var prevCards = Array.isArray(prev.cards) ? prev.cards : [];
  var nextCards = Array.isArray(next.cards) ? next.cards : [];

  var before = Object.create(null);
  for (var i = 0; i < prevCards.length; i += 1) {
    var p = prevCards[i];
    if (!isObject(p) || p.placeholder === true) continue;
    var pk = stringOrNull(p.key);
    if (pk === null) continue;
    before[pk] = stringOrNull(p.stateText);
  }

  var changes = [];
  for (var j = 0; j < nextCards.length; j += 1) {
    var c = nextCards[j];
    if (!isObject(c) || c.placeholder === true) continue;
    var ck = stringOrNull(c.key);
    if (ck === null) continue;
    var was = before[ck];
    var now = stringOrNull(c.stateText);
    // undefined == the row was not on screen before, so this is an arrival.
    if (was === undefined || was === null || now === null || was === now) continue;
    changes.push((stringOrNull(c.label) || ck) + " went " + now);
  }

  if (changes.length === 0) return null;
  if (changes.length > MAX_STATUS_CHANGES) {
    return (
      changes.slice(0, MAX_STATUS_CHANGES).join("; ") +
      "; and " +
      (changes.length - MAX_STATUS_CHANGES) +
      " more"
    );
  }
  return changes.join("; ");
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

/**
 * Reconcile the tab strip IN PLACE - never wipe it.
 *
 * The panel repaints on a 2000ms timer and on every tab click, and the old
 * implementation opened with `root.textContent = ""`, rebuilding every button.
 * Detaching a node drops focus, so a focused tab silently lost its focus ring
 * at an arbitrary tick with zero user input, and the keyboard position was lost
 * rather than moved. The Enter path was worse and deterministic: activating a
 * tab fires the click handler -> selectTab -> render -> wipe, so keyboard tab
 * switching lost focus 100 percent of the time.
 *
 * Reconciliation - rather than the save-and-restore-activeElement fallback -
 * because it fixes the whole family rather than the one symptom: :hover no
 * longer flickers back to resting every 2s, the pressed/active state survives,
 * and no node churns when nothing about the strip changed. A button is matched
 * by dataset.tabId, updated in place, and only the genuine difference is
 * inserted or removed.
 */
/** The tab buttons currently in the strip, in DOM order. */
function tabButtons(root) {
  var out = [];
  var scan = root ? root.firstChild : null;
  while (scan) {
    if (scan.dataset && typeof scan.dataset.tabId === "string") out.push(scan);
    scan = scan.nextSibling;
  }
  return out;
}

/**
 * Arrow-key roving over the strip - the other half of role="tab".
 *
 * Once a control carries role="tab", assistive tech stops exposing it as an
 * ordinary button and starts announcing "tab 1 of N, use the arrow keys". A
 * strip that says that and then ignores the arrows is WORSE than one with no
 * roles at all, because the user is told a navigation method that does nothing.
 *
 * The strip is read from the DOM at press time rather than captured, for the
 * same reason the click handler reads btn.dataset.tabId: buttons are long-lived
 * now, so a handler that closed over its neighbour or its index at creation
 * would keep roving the strip as it stood when a repo first appeared.
 *
 * Both ends wrap, and Home/End jump outright. preventDefault is not optional -
 * #cards is a scroll container and an unclaimed arrow scrolls it instead.
 */
function handleTabKey(event, btn, onSelect) {
  var key = event ? event.key : null;
  var buttons = tabButtons(btn.parentNode);
  var at = buttons.indexOf(btn);
  if (at < 0) return;

  var to;
  if (key === "ArrowRight") to = (at + 1) % buttons.length;
  else if (key === "ArrowLeft") to = (at - 1 + buttons.length) % buttons.length;
  else if (key === "Home") to = 0;
  else if (key === "End") to = buttons.length - 1;
  else return;

  if (typeof event.preventDefault === "function") event.preventDefault();
  var target = buttons[to];
  // Focus FIRST: roving means the focus ring travels with the selection, and
  // doing it here keeps that true even if the select path below is a no-op.
  target.focus();
  onSelect(target.dataset.tabId);
}

function renderTabs(doc, root, view, onSelect) {
  var existing = Object.create(null);
  var present = tabButtons(root);
  for (var e = 0; e < present.length; e += 1) {
    existing[present[e].dataset.tabId] = present[e];
  }

  var wanted = Object.create(null);
  view.tabs.forEach(function (tab, index) {
    wanted[tab.id] = true;
    var btn = existing[tab.id];
    if (!btn) {
      btn = el(doc, "button", "tab", tab.label);
      btn.type = "button";
      btn.setAttribute("role", "tab");
      // Minted once. dataset.tabId is the reconciliation key and never changes
      // for a given node, so neither does the id derived from it.
      btn.setAttribute("id", tabDomId(tab.id));
      btn.setAttribute("aria-controls", CARDS_ID);
      btn.dataset.tabId = tab.id;
      // Reads the id off the node, not off a captured `tab`, so the handler
      // stays correct for the whole life of a button that is never rebuilt.
      btn.addEventListener("click", function () { onSelect(btn.dataset.tabId); });
      btn.addEventListener("keydown", function (event) { handleTabKey(event, btn, onSelect); });
    } else if (btn.textContent !== tab.label) {
      btn.textContent = tab.label;
    }

    var active = tab.id === view.activeTab;
    btn.classList.toggle("is-active", active);
    btn.setAttribute("aria-selected", active ? "true" : "false");
    // Roving tabindex: exactly one stop in the strip, always the active tab.
    // Without it Tab walks through every pill one repo at a time, which is the
    // thing the arrow keys exist to replace. Writing tabindex does NOT blur the
    // element that holds focus, so this is safe to re-run on every repaint -
    // and it has to be re-run, because the active tab moves.
    btn.setAttribute("tabindex", active ? "0" : "-1");

    // Move only if it is not already sitting at the right index. A no-op
    // insertBefore would still detach and re-attach the node, which is exactly
    // the thing that costs focus.
    var at = root.childNodes[index];
    if (at !== btn) root.insertBefore(btn, at || null);
  });

  var kids = Array.prototype.slice.call(root.childNodes);
  for (var i = 0; i < kids.length; i += 1) {
    var id = kids[i].dataset ? kids[i].dataset.tabId : undefined;
    if (typeof id !== "string" || wanted[id] !== true) root.removeChild(kids[i]);
  }
}

function renderCards(doc, root, view) {
  // .cards is a scroll container, so the wipe below would otherwise snap the
  // operator back to the top of the list on every 2000ms repaint.
  var scrollTop = typeof root.scrollTop === "number" ? root.scrollTop : 0;
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
  if (scrollTop > 0) root.scrollTop = scrollTop;
}

/**
 * Write the live region, and ONLY when there is something to say.
 *
 * Guarded on the node so this file does not hard-depend on the #status element
 * existing. A null message leaves the node completely alone - re-writing the
 * same text, or blanking it, is another announcement.
 */
function writeStatus(node, message) {
  if (!node) return;
  var text = stringOrNull(message);
  if (text === null) return;
  node.textContent = text;
}

/**
 * Point the card region back at the tab that owns it.
 *
 * aria-controls alone is a one-way arrow. index.html gives #cards a static
 * aria-label as the pre-first-paint fallback; aria-labelledby overrides it once
 * there is a real tab to name, so the panel announces the repo it is showing
 * rather than a fixed word that is true of every tab equally.
 *
 * Guarded and total like writeStatus - it runs on the same 2000ms timer path.
 */
function renderPanel(node, view) {
  if (!node) return;
  var v = isObject(view) ? view : {};
  var active = stringOrNull(v.activeTab);
  // No active tab means no tab to be labelled BY. Pointing at a minted id for a
  // tab that does not exist is a dangling IDREF, which drops the accessible
  // name entirely rather than falling back to the static aria-label.
  if (active === null) return;
  node.setAttribute("aria-labelledby", tabDomId(active));
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
  renderPanel(dom.cards, view);
  renderSummary(doc, dom.summary, view);
}

// ----------------------------------------------------- window geometry ------
//
// THE ONE RULE IN THIS SECTION: the size the renderer reports must not be a
// function of the size the renderer currently IS.
//
// main.js feeds every reported box to clamp.js and applies the result with
// setBounds, so anything that makes the measurement depend on the current
// window closes a loop:
//
//     window height -> viewport -> measured content -> window height
//
// That loop shipped. widget.css bounded .panel by calc(100vh - 16px) and
// .cards by calc(100vh - 130px), each turn therefore took a constant off the
// height, and a live run measured the window ratcheting down through 24 sizes
// in 590ms to 415x126 with no cards drawn at all. The fix is structural, not a
// retuned constant: the panel's cap comes from screen.availHeight - the
// DISPLAY WORK AREA, which no clamp result can move - and nothing on this path
// reads innerHeight, outerHeight or visualViewport. The map is then constant in
// its own output, so it reaches its fixed point on the first clamp.
//
// test/clamp.test.js iterates the map and asserts that fixed point (and that
// the old viewport-bound arithmetic fails the same acceptance).
// test/render.test.js asserts that this reporter reads no viewport quantity and
// that widget.css carries no viewport unit on either measured rule.

// widget.css .panel { margin: 8px } on all four sides.
var PANEL_MARGIN_PX = 8;

/**
 * The work-area-derived cap handed to CSS as --panel-max-height.
 *
 * availHeight is the display WORK AREA in CSS pixels - taskbar already
 * subtracted - so the panel is allowed to fill the screen and not one pixel
 * more. Returns null when the host cannot tell us, in which case the cap is
 * left unset rather than guessed: a guess here would be a second, silently
 * wrong source of truth for a number clamp.js already owns.
 */
function panelCapFor(availHeight, marginPx) {
  var m = typeof marginPx === "number" && isFinite(marginPx) ? marginPx : PANEL_MARGIN_PX;
  if (typeof availHeight !== "number" || !isFinite(availHeight) || availHeight <= 0) {
    return null;
  }
  var cap = availHeight - 2 * m;
  return cap > 0 ? cap : null;
}

/**
 * The outer window box for a measured panel border box, or null when the box
 * is not a real one yet.
 *
 * Rounding is UP on both axes: a fractional box rounded down loses its last
 * device pixel, which on a grid of fixed-height cards is a clipped row.
 *
 * The null case is defect B. A 0x0 panel is not a small content size, it is
 * the ABSENCE of one - layout has not run. Reporting it would hand main.js a
 * pre-layout box to reveal the window at.
 */
function reportedSizeFor(rect, marginPx) {
  if (!rect || typeof rect !== "object") return null;
  var m = typeof marginPx === "number" && isFinite(marginPx) ? marginPx : PANEL_MARGIN_PX;
  var wRaw = rect.width;
  var hRaw = rect.height;
  if (typeof wRaw !== "number" || !isFinite(wRaw) || wRaw <= 0) return null;
  if (typeof hRaw !== "number" || !isFinite(hRaw) || hRaw <= 0) return null;
  return {
    width: Math.ceil(wRaw) + 2 * m,
    height: Math.ceil(hRaw) + 2 * m,
  };
}

/**
 * Build the size reporter for a panel. Viewport-free by construction.
 *
 * Also de-duplicates: the widget repaints every poll forever, and re-sending
 * an identical size is an IPC round trip plus a setBounds per tick for no
 * change on screen.
 */
function createSizeReporter(win, panel, bridge) {
  var lastW = -1;
  var lastH = -1;
  var lastCap = null;

  return function reportSize() {
    if (!panel || typeof panel.getBoundingClientRect !== "function") return;

    // The cap, from the WORK AREA. Re-applied only when the number moves, so
    // dragging the widget to a second display with a different work area still
    // re-caps, without invalidating style on every poll.
    var screen = win && win.screen ? win.screen : null;
    var cap = panelCapFor(screen ? screen.availHeight : null, PANEL_MARGIN_PX);
    if (cap !== lastCap) {
      lastCap = cap;
      if (panel.style && typeof panel.style.setProperty === "function") {
        if (cap === null) {
          if (typeof panel.style.removeProperty === "function") {
            panel.style.removeProperty("--panel-max-height");
          }
        } else {
          panel.style.setProperty("--panel-max-height", cap + "px");
        }
      }
    }

    var size = reportedSizeFor(panel.getBoundingClientRect(), PANEL_MARGIN_PX);
    if (size === null) return;
    if (size.width === lastW && size.height === lastH) return;
    lastW = size.width;
    lastH = size.height;
    if (bridge && typeof bridge.reportSize === "function") bridge.reportSize(size);
  };
}

// ------------------------------------------------------ right-click policy --
//
// Defect D. The handler used to bail out for
// "button, input, select, textarea, a, label" so that those kept "their own
// default handling" - but they are all -webkit-app-region: no-drag, and
// Electron does not raise system-context-menu over a no-drag region either.
// The net effect was that right-clicking a tab pill or the gear produced NO
// MENU AT ALL, which is strictly worse than the app menu those spots now get.
//
// THE RULE: the native menu is kept exactly where its items mean something -
// somewhere the user can TYPE, so Cut / Copy / Paste / Select All are real
// commands. Everywhere else, including every button, slider, checkbox, label
// and link, right-click opens the window menu like the rest of the panel.

// An <input> with no type attribute is a text input, hence the "" key.
var TEXT_ENTRY_INPUT_TYPES = {
  "": true, text: true, search: true, url: true, tel: true,
  email: true, password: true, number: true,
};

/**
 * Is this node (or an ancestor of it) something the user can type into?
 *
 * Walks parentElement because the click can land on a child of a
 * contenteditable region. Pure and total - junk in returns false.
 */
function wantsNativeTextMenu(node) {
  var el = node;
  var hops = 0;
  while (el && typeof el === "object" && hops < 64) {
    hops += 1;
    if (el.isContentEditable === true) return true;
    var tag = typeof el.tagName === "string" ? el.tagName.toLowerCase() : "";
    if (tag === "textarea") return true;
    if (tag === "input") {
      var type = typeof el.getAttribute === "function" ? el.getAttribute("type") : null;
      var key = type === null || type === undefined ? "" : String(type).toLowerCase();
      return TEXT_ENTRY_INPUT_TYPES[key] === true;
    }
    el = el.parentElement;
  }
  return false;
}

// ---------------------------------------------------------------- boot ------

function boot(win, doc, bridge) {
  var dom = {
    panel: doc.getElementById("panel"),
    tabs: doc.getElementById("tabstrip-tabs"),
    cards: doc.getElementById("cards"),
    summary: doc.getElementById("summary"),
    // Visually-hidden role=status live region. Absent until index.html carries
    // it, and every write is guarded, so a missing node is not an error.
    status: doc.getElementById("status"),
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
  var lastView = null;
  var activeTab = TAB_ALL;
  // store.js DEFAULTS - the real values arrive from the bridge a tick later.
  var settings = { opacity: 0.94, alwaysOnTop: true, showFree: true, fastMs: 2000 };

  // Viewport-free - see the window-geometry section above for why that is the
  // whole point and not an implementation detail.
  var reportSize = createSizeReporter(win, dom.panel, bridge);

  function render() {
    var view = buildView(lastModel, {
      activeTab: activeTab,
      showFree: settings.showFree,
    });
    activeTab = view.activeTab;
    // Diff BEFORE the paint overwrites the record of what was on screen.
    var message = statusMessageFor(lastView, view);
    lastView = view;
    applyView(doc, dom, view, selectTab);
    writeStatus(dom.status, message);
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

  // Right-click opens the window menu (Minimize / Close to tray) EVERYWHERE
  // except a field the user can type into, which keeps the native text menu.
  // See the right-click policy section above - the old control-wide bail-out
  // left the gear and the tab pills with no menu of any kind.
  doc.addEventListener("contextmenu", function (event) {
    if (wantsNativeTextMenu(event ? event.target : null)) return;
    if (event && typeof event.preventDefault === "function") event.preventDefault();
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
  // wrapping at a new width), so re-report on any box change too. This is also
  // the recovery path for defect B: the first render's measurement is dropped
  // when layout has not run yet, and the observer fires the moment it has.
  if (typeof win.ResizeObserver === "function" && dom.panel) {
    new win.ResizeObserver(reportSize).observe(dom.panel);
  }

  // Webfonts land after first layout and change every text metric in the
  // panel, so the box measured before they resolve is a real box but not the
  // FINAL one. Re-report once they settle. Guarded - document.fonts is absent
  // in the test shim and optional in the spec.
  if (doc.fonts && typeof doc.fonts.ready === "object" && doc.fonts.ready !== null &&
      typeof doc.fonts.ready.then === "function") {
    doc.fonts.ready.then(reportSize).catch(function () { /* metrics stay as measured */ });
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
    CARDS_ID: CARDS_ID,
    tabDomId: tabDomId,
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
    statusMessageFor: statusMessageFor,
    MAX_STATUS_CHANGES: MAX_STATUS_CHANGES,
    // The shim half is exported too, now that three of its behaviours are
    // load-bearing and regression-tested against a minimal fake DOM in
    // test/render.test.js: tab-node identity (focus), card scroll position and
    // the guarded live-region write.
    renderTabs: renderTabs,
    renderCards: renderCards,
    renderPanel: renderPanel,
    applyView: applyView,
    writeStatus: writeStatus,
    // Window geometry. These are the halves of the measurement that used to
    // live inline in boot(), pulled out because the defect they carry is pure
    // arithmetic and therefore unit-testable: the reported box must not be a
    // function of the current window. test/render.test.js drives the real
    // reporter against a counted-getter window stub to assert exactly that.
    PANEL_MARGIN_PX: PANEL_MARGIN_PX,
    panelCapFor: panelCapFor,
    reportedSizeFor: reportedSizeFor,
    createSizeReporter: createSizeReporter,
    wantsNativeTextMenu: wantsNativeTextMenu,
  };
}

if (typeof window !== "undefined" && typeof document !== "undefined") {
  window.addEventListener("DOMContentLoaded", function () {
    boot(window, document, window.laneWidget);
  });
}
