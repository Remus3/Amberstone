// rc-shell/test/overlay_tft.test.js
//
// S134 N9: the TFT-centric overlay panels (web/js/lib/overlay_tft.js) and the
// game-family scoping of the widget field + panel menu (web/js/lib/
// overlay_layout.js). QA match 3 (ops/runtime/tft_qa/20261025-085349,
// QA_REPORT.md N9): the overlay was ON from 1-2 but painted no TFT data and its
// menu offered only SR / ARAM panels.
//
// Fixtures are REAL /api/state payloads from that match, sanitised (identity
// keys dropped): tests/snapshot_panels/fixtures/tft_overlay_{live,sentinel,
// feed}.json - the same files the headless Playwright audit
// (tests/snapshot_panels/test_overlay_tft_view.py) renders.
//
// Zero-dep posture (like overlay_launcher.test.js): a small hand-rolled DOM on
// globalThis with a selector engine covering exactly the selector forms the two
// modules use, then dynamic imports of the ES modules. No production behavior
// is mocked; the rc-shell bridge (window.rcShell) is a recording stub.

"use strict";

const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const path = require("path");
const url = require("url");

const ROOT = path.join(__dirname, "..", "..");
const FIX = path.join(ROOT, "tests", "snapshot_panels", "fixtures");
const fixture = (name) => JSON.parse(fs.readFileSync(path.join(FIX, name + ".json"), "utf8"));

// --- mini DOM -------------------------------------------------------------------

function parseCompound(src) {
  const c = { tag: null, id: null, classes: [], attrs: [], scope: false };
  let s = src;
  if (s.startsWith(":scope")) {
    c.scope = true;
    s = s.slice(6);
  }
  const re = /^([a-zA-Z][a-zA-Z0-9-]*)|#([\w-]+)|\.([\w-]+)|\[([\w-]+)(?:="([^"]*)")?\]/;
  let m;
  while (s.length && (m = re.exec(s))) {
    if (m[1]) c.tag = m[1].toUpperCase();
    else if (m[2]) c.id = m[2];
    else if (m[3]) c.classes.push(m[3]);
    else if (m[4]) c.attrs.push([m[4], m[5]]);
    s = s.slice(m[0].length);
  }
  if (s.length) throw new Error("mini DOM: unsupported selector part " + JSON.stringify(src));
  return c;
}

function parseSelector(sel) {
  // -> [{c, comb}] left to right; comb = combinator BEFORE this compound.
  const out = [];
  const toks = sel.trim().replace(/\s*>\s*/g, " > ").split(/\s+/);
  let comb = null;
  for (const t of toks) {
    if (t === ">") {
      comb = ">";
      continue;
    }
    out.push({ c: parseCompound(t), comb: out.length ? comb || " " : null });
    comb = null;
  }
  return out;
}

function matchCompound(el, c, scopeEl) {
  if (c.scope) return el === scopeEl;
  if (c.tag && el.tagName !== c.tag) return false;
  if (c.id && el.id !== c.id) return false;
  for (const k of c.classes) if (!el.classList.contains(k)) return false;
  for (const [name, val] of c.attrs) {
    const v = el.getAttribute(name);
    if (v === null) return false;
    if (val !== undefined && v !== val) return false;
  }
  return true;
}

function matchesAt(el, parts, i, scopeEl) {
  if (!el || !matchCompound(el, parts[i].c, scopeEl)) return false;
  if (i === 0) return true;
  const comb = parts[i].comb;
  if (comb === ">") return matchesAt(el.parentNode, parts, i - 1, scopeEl);
  for (let a = el.parentNode; a; a = a.parentNode) {
    if (matchesAt(a, parts, i - 1, scopeEl)) return true;
  }
  return false;
}

function dataKey(attr) {
  return attr.slice(5).replace(/-([a-z])/g, (_m, ch) => ch.toUpperCase());
}

class El {
  constructor(tag, doc) {
    this.tagName = String(tag).toUpperCase();
    this.ownerDocument = doc;
    this.children = [];
    this.parentNode = null;
    this.dataset = {};
    this._attrs = {};
    this._classes = new Set();
    this._text = "";
    this._listeners = {};
    this.hidden = false;
    this.id = "";
    this._html = "";
    const self = this;
    this.classList = {
      add: (...cs) => cs.forEach((c) => self._classes.add(c)),
      remove: (...cs) => cs.forEach((c) => self._classes.delete(c)),
      contains: (c) => self._classes.has(c),
      toggle: (c, on) => {
        const want = on === undefined ? !self._classes.has(c) : !!on;
        if (want) self._classes.add(c);
        else self._classes.delete(c);
        return want;
      },
    };
    this.style = {
      _props: {},
      setProperty(k, v) { this._props[k] = String(v); },
      removeProperty(k) { delete this._props[k]; },
      getPropertyValue(k) { return this._props[k] || ""; },
    };
  }
  // innerHTML: the modules only ever assign markup they never read back, or ""
  // to clear (the menu rebuild), so a set clears the children and keeps the text.
  get innerHTML() { return this._html; }
  set innerHTML(v) {
    for (const c of this.children) c.parentNode = null;
    this.children = [];
    this._text = "";
    this._html = String(v);
  }
  get className() { return [...this._classes].join(" "); }
  set className(v) { this._classes = new Set(String(v).split(/\s+/).filter(Boolean)); }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(""); }
  set textContent(v) {
    for (const c of this.children) c.parentNode = null;
    this.children = [];
    this._text = String(v);
  }
  get isConnected() {
    let n = this;
    while (n.parentNode) n = n.parentNode;
    return n === this.ownerDocument._root;
  }
  appendChild(ch) {
    if (ch.parentNode) ch.parentNode.removeChild(ch);
    ch.parentNode = this;
    this.children.push(ch);
    this.ownerDocument._mutations += 1;
    return ch;
  }
  removeChild(ch) {
    const i = this.children.indexOf(ch);
    if (i >= 0) this.children.splice(i, 1);
    ch.parentNode = null;
    return ch;
  }
  setAttribute(name, val) {
    if (name === "id") this.id = String(val);
    else if (name === "class") this.className = val;
    else if (name.startsWith("data-")) this.dataset[dataKey(name)] = String(val);
    else this._attrs[name] = String(val);
  }
  getAttribute(name) {
    if (name === "id") return this.id || null;
    if (name === "class") return this.className;
    if (name.startsWith("data-")) {
      const k = dataKey(name);
      return k in this.dataset ? this.dataset[k] : null;
    }
    return name in this._attrs ? this._attrs[name] : null;
  }
  hasAttribute(name) { return this.getAttribute(name) !== null; }
  removeAttribute(name) {
    if (name.startsWith("data-")) delete this.dataset[dataKey(name)];
    else delete this._attrs[name];
  }
  addEventListener(type, fn) { (this._listeners[type] || (this._listeners[type] = [])).push(fn); }
  removeEventListener() {}
  dispatch(type, ev) {
    for (const fn of this._listeners[type] || []) fn(ev || {});
  }
  _descendants(out = []) {
    for (const c of this.children) {
      out.push(c);
      c._descendants(out);
    }
    return out;
  }
  querySelectorAll(sel) {
    const parts = parseSelector(sel);
    return this._descendants().filter((el) => matchesAt(el, parts, parts.length - 1, this));
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  closest(sel) {
    const parts = parseSelector(sel);
    for (let n = this; n; n = n.parentNode) if (matchesAt(n, parts, parts.length - 1, null)) return n;
    return null;
  }
  setPointerCapture() {}
  releasePointerCapture() {}
  contains(n) { return n === this || this._descendants().includes(n); }
}

// Text node: never matches a selector, contributes its text.
class TextNode {
  constructor(text) {
    this.tagName = "#text";
    this.id = "";
    this.parentNode = null;
    this.textContent = String(text);
    this.classList = { contains: () => false };
  }
  getAttribute() { return null; }
  _descendants(out = []) { return out; }
}

function installDom() {
  const doc = { _mutations: 0 };
  const root = new El("html", doc);
  const head = new El("head", doc);
  const body = new El("body", doc);
  doc._root = root;
  root.appendChild(head);
  root.appendChild(body);
  body.dataset.shell = "overlay";
  Object.assign(doc, {
    documentElement: root,
    head,
    body,
    activeElement: body,
    createElement: (tag) => new El(tag, doc),
    createTextNode: (text) => new TextNode(text),
    getElementById: (id) => root._descendants().find((e) => e.id === id) || null,
    querySelector: (sel) => root.querySelector(sel),
    querySelectorAll: (sel) => root.querySelectorAll(sel),
    addEventListener() {},
  });
  globalThis.document = doc;
  const actions = [];
  globalThis.window = {
    innerWidth: 1920,
    innerHeight: 1080,
    addEventListener() {},
    removeEventListener() {},
    rcShell: { overlayAction: (msg) => actions.push(msg) },
  };
  globalThis.getComputedStyle = () => ({ zoom: "1" });
  globalThis.MutationObserver = class {
    constructor(cb) { this.cb = cb; }
    observe() {}
    disconnect() {}
  };
  const store = new Map();
  globalThis.localStorage = {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
  };
  return { doc, body, actions };
}

// A League widget mount present in the page (web/index.html carries these), so
// the game-family gate on the League set is observable.
function addLeagueMount(doc, id) {
  const el = doc.createElement("div");
  el.id = id;
  doc.body.appendChild(el);
  return el;
}

let dom;
let tft;
let layout;
let leagueLead;
test.before(async () => {
  dom = installDom();
  leagueLead = addLeagueMount(dom.doc, "rn-lead");
  layout = await import(url.pathToFileURL(path.join(ROOT, "web", "js", "lib", "overlay_layout.js")).href);
  tft = await import(url.pathToFileURL(path.join(ROOT, "web", "js", "lib", "overlay_tft.js")).href);
  layout.initOverlayLayout();
});

const vit = (m) => Object.fromEntries(m.vitals.map((v) => [v.key, v.text]));

// --- pure model on the real payloads ------------------------------------------------

test("model: real live payload -> HP / PLACE / ALIVE / clock / board; stage-level-gold '-'", () => {
  const m = tft.tftOverlayModel(fixture("tft_overlay_live"));
  assert.strictEqual(m.active, true);
  assert.deepStrictEqual(vit(m), {
    hp: "96", place: "#2", alive: "8", stage: "-", level: "-", gold: "-",
  });
  assert.strictEqual(m.time, "14:10");
  assert.strictEqual(m.source, "ROUND FEED");
  assert.strictEqual(m.board.count, "7"); // level unknown -> no "/cap"
  assert.deepStrictEqual(
    m.board.units.map((u) => `${u.name}*${u.star}`),
    ["Yorick*1", "Xayah*2", "Karma*1", "Yunara*2", "Diana*1", "Ahri*1", "Elise*1"]
  );
  assert.strictEqual(m.board.overflow, 0);
  assert.strictEqual(m.lobby, null, "no lobby rows in this payload -> lobby panel stays hidden");
});

test("model: the game-start placeholder file (QA N10: hp/standing -1, players 0) reads unknown", () => {
  const st = fixture("tft_overlay_sentinel");
  assert.strictEqual(st.liveclient.hp, -1, "precondition: the real sentinel payload");
  const m = tft.tftOverlayModel(st);
  assert.deepStrictEqual(vit(m), {
    hp: "-", place: "-", alive: "-", stage: "-", level: "-", gold: "-",
  });
  assert.strictEqual(m.board.count, "-", "an unknown board is not an empty board");
  assert.deepStrictEqual(m.board.units, []);
});

test("model: when OCR + the lobby rows land (feed fixture) every slot fills, same keys", () => {
  const st = fixture("tft_overlay_feed");
  assert.ok(Array.isArray(st.liveclient.players), "precondition: the served P0-F lobby rows");
  assert.ok(!("opponents" in st.liveclient), "precondition: no invented opponents field");
  const m = tft.tftOverlayModel(st);
  assert.deepStrictEqual(vit(m), {
    hp: "96", place: "#1", alive: "7", stage: "5-2", level: "9", gold: "41",
  });
  assert.strictEqual(m.board.count, "9/9");
  assert.deepStrictEqual(
    m.lobby.map((r) => r.text),
    ["38", "36", "26", "21", "19", "3", "OUT"]
  );
  assert.strictEqual(m.lobby[6].alive, false);
});

// The lobby rows are the S134 P0-F board-panel contract (tft/tft_standalone.py
// _lobby -> liveclient.players, copied to coach.tft_players by
// dashboard/_state_builder.py): {standing, health, you, board_size}, opponents
// anonymous, empty until every player's HP is known, an eliminated player's
// health 0.
const lobbyRow = (standing, health, you) => ({ standing, health, you: you === true, board_size: 0 });

test("lobby: reads liveclient.players, drops the local row, eliminated (health 0) reads OUT", () => {
  const players = [
    lobbyRow(1, 80, true), lobbyRow(2, 55), lobbyRow(3, 61), lobbyRow(8, 0),
    lobbyRow(4, 12), lobbyRow(5, 9), lobbyRow(6, 4), lobbyRow(7, 0),
  ];
  const m = tft.tftOverlayModel({ mode_key: "tft", liveclient: { hp: 80, standing: 1, players } });
  assert.deepStrictEqual(m.lobby.map((r) => r.text), ["61", "55", "12", "9", "4", "OUT", "OUT"]);
  assert.deepStrictEqual(m.lobby.map((r) => r.alive), [true, true, true, true, true, false, false]);
});

test("lobby: falls back to coach.tft_players when liveclient carries none", () => {
  const m = tft.tftOverlayModel({
    mode_key: "tft",
    liveclient: { hp: 70 },
    coach: { tft_players: [lobbyRow(2, 70, true), lobbyRow(1, 90)] },
  });
  assert.deepStrictEqual(m.lobby, [{ text: "90", alive: true }]);
});

test("lobby: an empty / sentinel / garbage row list keeps the panel hidden (null)", () => {
  for (const players of [[], [lobbyRow(1, 50, true)], "x", null, [null, 7, "a"]]) {
    const m = tft.tftOverlayModel({ mode_key: "tft", liveclient: { players } });
    assert.strictEqual(m.lobby, null, JSON.stringify(players));
  }
  // an unknown HP (null - P0-F's sentinel form) is never a value
  const m = tft.tftOverlayModel({
    mode_key: "tft",
    liveclient: { players: [lobbyRow(1, 40), { standing: null, health: null, you: false }] },
  });
  assert.deepStrictEqual(m.lobby.map((r) => r.text), ["40", "-"]);
});

test("model: the P0-F start-of-game shape (nulls, no lobby rows) reads unknown", () => {
  const m = tft.tftOverlayModel({
    mode_key: "tft",
    liveclient: { source: "tft_standalone", hp: null, standing: null, players_alive: null, players: [] },
  });
  assert.deepStrictEqual(vit(m), {
    hp: "-", place: "-", alive: "-", stage: "-", level: "-", gold: "-",
  });
  assert.strictEqual(m.board.count, "-");
  assert.strictEqual(m.lobby, null);
});

test("model: the structured board falls back to coach.tft_board (P0-F coach copy)", () => {
  const m = tft.tftOverlayModel({
    mode_key: "tft",
    liveclient: { standing: 4 },
    coach: { tft_board: [{ name: "Ahri", star: 2, items: ["Blue Buff"] }], board_str: "Shen*1" },
  });
  assert.deepStrictEqual(m.board.units, [{ name: "Ahri", star: 2 }]);
});

test("model: vitals keep the same six slots in the same order in every state (no reflow)", () => {
  const keys = (name) => tft.tftOverlayModel(fixture(name)).vitals.map((v) => v.key);
  const want = ["hp", "place", "alive", "stage", "level", "gold"];
  for (const name of ["tft_overlay_live", "tft_overlay_sentinel", "tft_overlay_feed"]) {
    assert.deepStrictEqual(keys(name), want, name);
  }
  assert.deepStrictEqual(tft.tftOverlayModel({}).vitals.map((v) => v.key), want);
});

test("model: a non-TFT state is inactive", () => {
  for (const mk of ["sr", "aram", "arena", "client", "", null, undefined, 7]) {
    assert.strictEqual(tft.tftOverlayModel({ mode_key: mk }).active, false, String(mk));
  }
  assert.strictEqual(tft.tftOverlayModel({ mode_key: " TFT " }).active, true);
});

test("model: HP bands - crit at <= 20 (the one red pop-out), low at <= 40", () => {
  const band = (hp) => tft.tftOverlayModel({ mode_key: "tft", liveclient: { hp } }).vitals[0].band;
  assert.strictEqual(band(15), "crit");
  assert.strictEqual(band(20), "crit");
  assert.strictEqual(band(35), "low");
  assert.strictEqual(band(41), "");
  assert.strictEqual(band(-1), "", "unknown HP carries no band");
});

test("model: a later valid source wins over an earlier sentinel / garbage", () => {
  assert.strictEqual(tft.firstIn([-1, 72], 1, 100), 72);
  assert.strictEqual(tft.firstIn(["50", 60], 1, 100), 60, "a numeric string is not trusted");
  assert.strictEqual(tft.firstIn([NaN, Infinity, null], 1, 100), null);
  const m = tft.tftOverlayModel({ mode_key: "tft", liveclient: { hp: -1 }, coach: { health: 64 } });
  assert.strictEqual(vit(m).hp, "64");
});

// S136 T11: the coach payload carries null for an UNKNOWN health / level / gold
// (tft/tft_coach_engine.py _write_fields; it used to write the placeholders
// health 100, level 1, gold 0). null is the no-data "-" (plain ASCII hyphen);
// a READ gold of 0 stays "0".
test("model: the coach payload's null hp / level / gold read '-', never a placeholder", () => {
  const st = fixture("tft_overlay_live");
  st.coach = { ...st.coach, health: null, level: null, gold: null };
  const m = tft.tftOverlayModel(st);
  const v = vit(m);
  assert.deepStrictEqual([v.level, v.gold], ["-", "-"]);
  assert.strictEqual(v.hp, "96", "the per-round HP still reads");
  assert.strictEqual(m.board.count, "7", "an unknown level is no '/cap'");
  const none = tft.tftOverlayModel({
    mode_key: "tft",
    liveclient: { source: "tft_standalone", hp: -1, standing: null },
    coach: { mode: "tft", health: null, hp: -1, level: null, gold: null },
  });
  const nv = vit(none);
  assert.deepStrictEqual([nv.hp, nv.level, nv.gold], ["-", "-", "-"]);
  assert.ok(/^[\x20-\x7e]+$/.test(Object.values(nv).join("")), "ASCII sentinel");
  const zero = tft.tftOverlayModel({ mode_key: "tft", coach: { level: 4, gold: 0 } });
  assert.deepStrictEqual([vit(zero).level, vit(zero).gold], ["4", "0"], "a read 0 gold is data");
});

test("stageOf: stage_round, an N-M stage string, stage + round ints; garbage -> null", () => {
  assert.strictEqual(tft.stageOf({ stage_round: "3-2" }), "3-2");
  assert.strictEqual(tft.stageOf({ stage_round: " 4 - 5 " }), "4-5");
  assert.strictEqual(tft.stageOf({ stage: "3-6", round: "Round 6" }), "3-6");
  assert.strictEqual(tft.stageOf({ stage: 2, round: 1 }), "2-1");
  assert.strictEqual(tft.stageOf({ stage_round: "", stage: 0, round: 0 }), null);
  assert.strictEqual(tft.stageOf({ stage_round: "26" }), null);
  assert.strictEqual(tft.stageOf(null), null);
});

test("parseBoardStr: the server board_str shape, names made readable and ASCII", () => {
  assert.deepStrictEqual(tft.parseBoardStr("Akali_AD*1, CrimsonRaptor*2"), [
    { name: "Akali AD", star: 1 },
    { name: "CrimsonRaptor", star: 2 },
  ]);
  assert.deepStrictEqual(tft.parseBoardStr("Shen"), [{ name: "Shen", star: 1 }]);
  assert.deepStrictEqual(tft.parseBoardStr("Kai" + String.fromCharCode(0x2019) + "Sa*4"), [{ name: "KaiSa", star: 3 }]);
  assert.deepStrictEqual(tft.parseBoardStr(" , ,"), []);
  assert.deepStrictEqual(tft.parseBoardStr(null), []);
});

test("model: more units than slots -> 11 shown plus a '+N more' slot", () => {
  const names = Array.from({ length: 14 }, (_v, i) => `Unit${i}*1`).join(", ");
  const m = tft.tftOverlayModel({ mode_key: "tft", liveclient: { standing: 3, board_str: names } });
  assert.strictEqual(m.board.units.length, tft.BOARD_SLOTS - 1);
  assert.strictEqual(m.board.overflow, 14 - (tft.BOARD_SLOTS - 1));
  assert.strictEqual(m.board.count, "14");
});

test("model: a structured liveclient.board wins over board_str", () => {
  const m = tft.tftOverlayModel({
    mode_key: "tft",
    liveclient: { standing: 2, board: [{ name: "Xayah", star: 3, items: [] }], board_str: "Shen*1" },
  });
  assert.deepStrictEqual(m.board.units, [{ name: "Xayah", star: 3 }]);
});

// --- registry + game-family scoping ----------------------------------------------

test("TFT_WIDGETS select exactly the overlay_tft mount ids, scoped to TFT", () => {
  const I = layout._internals;
  const sels = I.TFT_WIDGETS.map((w) => w.sel).sort();
  const want = Object.values(tft.TFT_MOUNT_IDS).map((id) => "#" + id).sort();
  assert.deepStrictEqual(sels, want);
  for (const w of I.TFT_WIDGETS) {
    assert.strictEqual(w.game, "tft", w.id);
    assert.ok(/^w-tft-[a-z]+$/.test(w.id), w.id);
    assert.ok(Number.isFinite(w.w) && w.w > 0, `${w.id} carries its fixed width`);
    assert.ok(/^[\x20-\x7e]+$/.test(w.label), `${w.id} label ASCII`);
  }
  const leagueIds = new Set(I.WIDGETS.map((w) => w.id));
  for (const w of I.TFT_WIDGETS) assert.ok(!leagueIds.has(w.id), `${w.id} collides with a League id`);
  assert.strictEqual(I.LAUNCHER.game, "*", "the launcher shows in every game");
});

test("menu rows: TFT lists only TFT panels, League lists only League panels", () => {
  const I = layout._internals;
  const tftIds = I._menuWidgets(true).map((w) => w.id);
  const lolIds = I._menuWidgets(false).map((w) => w.id);
  for (const w of I.TFT_WIDGETS) {
    assert.ok(tftIds.includes(w.id), `TFT menu lists ${w.id}`);
    assert.ok(!lolIds.includes(w.id), `League menu must not list ${w.id}`);
  }
  for (const w of I.WIDGETS) {
    assert.ok(lolIds.includes(w.id), `League menu lists ${w.id}`);
    assert.ok(!tftIds.includes(w.id), `TFT menu must not list ${w.id} (QA match 3: SR/ARAM panels only)`);
  }
});

test("_isTftNow: the state-derived data-ovx-game stamp wins over a flapping data-mode", () => {
  const I = layout._internals;
  const ds = dom.body.dataset;
  const saved = { g: ds.ovxGame, m: ds.mode };
  try {
    delete ds.ovxGame;
    ds.mode = "tft";
    assert.strictEqual(I._isTftNow(), true, "body mode is the pre-state fallback");
    ds.mode = "sr";
    assert.strictEqual(I._isTftNow(), false);
    ds.ovxGame = "tft";
    assert.strictEqual(I._isTftNow(), true, "stamp wins over data-mode=sr");
    ds.ovxGame = "lol";
    ds.mode = "tft";
    assert.strictEqual(I._isTftNow(), false, "stamp wins over data-mode=tft");
  } finally {
    if (saved.g === undefined) delete ds.ovxGame;
    else ds.ovxGame = saved.g;
    if (saved.m === undefined) delete ds.mode;
    else ds.mode = saved.m;
  }
});

// --- DOM render pass (mini DOM, real modules) ---------------------------------------

test("render: a TFT state builds placed, visible TFT widgets and hides the League set", () => {
  const m = tft.renderTftOverlay(fixture("tft_overlay_live"));
  assert.ok(m && m.active);
  assert.strictEqual(dom.body.dataset.ovxGame, "tft");
  const hud = dom.doc.getElementById("ovt-hud");
  const board = dom.doc.getElementById("ovt-board");
  const lobby = dom.doc.getElementById("ovt-lobby");
  assert.ok(hud && board && lobby, "all three mounts exist");
  for (const [el, id, w] of [[hud, "w-tft-hud", "296px"], [board, "w-tft-board", "428px"]]) {
    assert.strictEqual(el.hidden, false, `${id} shown`);
    assert.ok(el.classList.contains("ovx-widget"), `${id} lifted into the widget field`);
    assert.strictEqual(el.dataset.ovxId, id);
    assert.ok(!el.classList.contains("ovx-hidden"), `${id} not game-gated in TFT`);
    assert.strictEqual(el.style._props["--ovx-w"], w, `${id} fixed width from the registry`);
    assert.ok(el.querySelector(":scope > .ovx-handle"), `${id} carries the drag handle`);
  }
  assert.strictEqual(lobby.hidden, true, "lobby is data-gated (no lobby rows)");
  assert.ok(leagueLead.classList.contains("ovx-hidden"), "a League widget is off the field in TFT");
  assert.ok(dom.doc.getElementById("ovt-style"), "the scoped TFT styles are injected once");
  // the painted text
  const val = (k) => hud.querySelector(`.ovt-cell[data-k="${k}"] .ovt-val`).textContent;
  assert.strictEqual(val("hp"), "96");
  assert.strictEqual(val("place"), "#2");
  assert.strictEqual(val("alive"), "8");
  assert.strictEqual(val("gold"), "-");
  assert.ok(hud.querySelector('.ovt-cell[data-k="gold"]').classList.contains("is-empty"));
  assert.strictEqual(hud.querySelector(".ovt-time").textContent, "14:10");
  assert.strictEqual(hud.querySelector(".ovt-src").textContent, "ROUND FEED");
  const names = board.querySelectorAll(".ovt-unit-name").map((n) => n.textContent);
  assert.strictEqual(names.length, tft.BOARD_SLOTS, "fixed slot count");
  assert.deepStrictEqual(names.slice(0, 8), ["Yorick", "Xayah", "Karma", "Yunara", "Diana", "Ahri", "Elise", ""]);
  const xayah = board.querySelectorAll(".ovt-unit")[1];
  assert.strictEqual(xayah.dataset.star, "2");
  assert.deepStrictEqual(xayah.querySelectorAll(".ovt-stars > i").map((p) => p.hidden), [false, false, true]);
});

test("render: a repeat tick is node-stable (no rebuild, drag handle survives)", () => {
  const hud = dom.doc.getElementById("ovt-hud");
  const valNode = hud.querySelector('.ovt-cell[data-k="hp"] .ovt-val');
  const handle = hud.querySelector(":scope > .ovx-handle");
  tft.renderTftOverlay(fixture("tft_overlay_live"));
  assert.strictEqual(hud.querySelector('.ovt-cell[data-k="hp"] .ovt-val'), valNode);
  assert.strictEqual(hud.querySelector(":scope > .ovx-handle"), handle);
  assert.strictEqual(dom.doc.querySelectorAll("#ovt-style").length, 1);
});

test("render: data landing fills slots without changing the slot structure", () => {
  const hud = dom.doc.getElementById("ovt-hud");
  const board = dom.doc.getElementById("ovt-board");
  const before = [hud.querySelectorAll(".ovt-cell").length, board.querySelectorAll(".ovt-unit").length];
  tft.renderTftOverlay(fixture("tft_overlay_feed"));
  const after = [hud.querySelectorAll(".ovt-cell").length, board.querySelectorAll(".ovt-unit").length];
  assert.deepStrictEqual(after, before);
  assert.strictEqual(hud.querySelector('.ovt-cell[data-k="stage"] .ovt-val').textContent, "5-2");
  const lobby = dom.doc.getElementById("ovt-lobby");
  assert.strictEqual(lobby.hidden, false, "lobby shows once opponents exist");
  assert.deepStrictEqual(
    lobby.querySelectorAll(".ovt-opp").map((c) => c.textContent),
    ["38", "36", "26", "21", "19", "3", "OUT"]
  );
  assert.ok(lobby.querySelectorAll(".ovt-opp")[6].classList.contains("is-out"));
});

test("menu: in TFT the launcher menu lists the TFT panels under 'TFT PANELS'", () => {
  const I = layout._internals;
  const menu = dom.doc.getElementById("ovx-launcher-menu");
  assert.ok(menu, "launcher menu exists");
  I._renderMenu(menu);
  assert.strictEqual(menu.querySelector(".ovx-menu-head").textContent, "TFT PANELS");
  const targets = menu.querySelectorAll(".ovx-menu-prow").map((r) => r.dataset.ovxTarget);
  assert.deepStrictEqual(targets, I._menuWidgets(true).map((w) => w.id));
  assert.ok(targets.includes("w-tft-board"));
  assert.ok(!targets.includes("w-call") && !targets.includes("w-arambalance"));
});

test("menu: 'Done (back to play)' asks the shell for PASSIVE, never ACTIVE", () => {
  const I = layout._internals;
  const menu = dom.doc.getElementById("ovx-launcher-menu");
  I._renderMenu(menu);
  dom.actions.length = 0;
  menu.querySelector(".ovx-menu-done").dispatch("click");
  assert.deepStrictEqual(dom.actions, [{ action: "set-passive" }]);
});

test("render: leaving TFT hides the TFT panels and hands the field back to League", () => {
  tft.renderTftOverlay({ mode_key: "sr", liveclient: { champion: "x" } });
  assert.strictEqual(dom.body.dataset.ovxGame, "lol");
  for (const id of Object.values(tft.TFT_MOUNT_IDS)) {
    const el = dom.doc.getElementById(id);
    assert.strictEqual(el.hidden, true, `${id} hidden outside TFT`);
    assert.ok(el.classList.contains("ovx-hidden"), `${id} game-gated outside TFT`);
  }
  assert.ok(!leagueLead.classList.contains("ovx-hidden"), "League widget back on the field");
  const I = layout._internals;
  const menu = dom.doc.getElementById("ovx-launcher-menu");
  I._renderMenu(menu);
  assert.strictEqual(menu.querySelector(".ovx-menu-head").textContent, "PANELS");
  const targets = menu.querySelectorAll(".ovx-menu-prow").map((r) => r.dataset.ovxTarget);
  assert.ok(targets.includes("w-call") && !targets.includes("w-tft-hud"));
});

// --- TFT-14 planner hook (registration only - the picker is NOT built here) ----------

test("planner hook: a registered TFT panel joins the field, the TFT menu and the render pass", () => {
  const I = layout._internals;
  const calls = [];
  const ok = tft.registerTftOverlayPanel(Object.assign({}, tft.TFT_PLANNER_SLOT, {
    render(bodyEl, model, st) {
      calls.push([bodyEl && bodyEl.className, model.active, st.mode_key]);
      bodyEl.textContent = "planner stub";
    },
  }));
  assert.strictEqual(ok, true);
  const entry = I._registry().find((w) => w.id === tft.TFT_PLANNER_SLOT.id);
  assert.ok(entry, "registered into the widget registry");
  assert.strictEqual(entry.game, "tft");
  assert.strictEqual(entry.sel, "#" + tft.TFT_PLANNER_SLOT.mountId);
  assert.deepStrictEqual([entry.x, entry.y, entry.w], [tft.TFT_PLANNER_SLOT.x, tft.TFT_PLANNER_SLOT.y, tft.TFT_PLANNER_SLOT.w]);
  assert.ok(I._menuWidgets(true).some((w) => w.id === entry.id), "listed in the TFT menu");
  assert.ok(!I._menuWidgets(false).some((w) => w.id === entry.id), "not in the League menu");
  tft.renderTftOverlay(fixture("tft_overlay_live"));
  assert.deepStrictEqual(calls, [["ovt-body", true, "tft"]]);
  const el = dom.doc.getElementById(tft.TFT_PLANNER_SLOT.mountId);
  assert.strictEqual(el.hidden, false);
  assert.strictEqual(el.dataset.ovxId, tft.TFT_PLANNER_SLOT.id);
});

test("planner hook: malformed specs are refused", () => {
  const render = () => {};
  assert.strictEqual(tft.registerTftOverlayPanel(null), false);
  assert.strictEqual(tft.registerTftOverlayPanel({ id: "w-planner", mountId: "ovt-x", x: 1, y: 1, render }), false, "id must be w-tft-*");
  assert.strictEqual(tft.registerTftOverlayPanel({ id: "w-tft-x", mountId: "x", x: 1, y: 1, render }), false, "mount must be ovt-*");
  assert.strictEqual(tft.registerTftOverlayPanel({ id: "w-tft-x", mountId: "ovt-hud", x: 1, y: 1, render }), false, "built-in mount");
  assert.strictEqual(tft.registerTftOverlayPanel({ id: "w-tft-x", mountId: "ovt-x", x: 1, y: 1 }), false, "no render");
  assert.strictEqual(tft.registerTftOverlayPanel({ id: "w-tft-x", mountId: "ovt-x", x: "a", y: 1, render }), false, "bad x");
  assert.strictEqual(layout.registerOverlayWidget({ id: "w-tft-hud", sel: "#zz", x: 1, y: 1 }), false, "built-in id");
});

test("planner hook: a throwing panel stays hidden while the built-ins still paint", () => {
  assert.strictEqual(tft.registerTftOverlayPanel({
    id: "w-tft-broken", mountId: "ovt-broken", x: 600, y: 600, w: 100, label: "Broken",
    render() { throw new Error("boom"); },
  }), true);
  const m = tft.renderTftOverlay(fixture("tft_overlay_live"));
  assert.ok(m && m.active, "the render pass survives");
  assert.strictEqual(dom.doc.getElementById("ovt-broken").hidden, true);
  assert.strictEqual(dom.doc.getElementById("ovt-hud").hidden, false);
});

test("render: off the overlay shell nothing is created", () => {
  const before = dom.doc._mutations;
  const shell = dom.body.dataset.shell;
  try {
    delete dom.body.dataset.shell;
    assert.strictEqual(tft.renderTftOverlay(fixture("tft_overlay_live")), null);
    assert.strictEqual(dom.doc._mutations, before);
  } finally {
    dom.body.dataset.shell = shell;
  }
});

// --- source hygiene ----------------------------------------------------------------

test("overlay_tft.js is 7-bit ASCII and its injected CSS uses tokens only (palette law)", () => {
  const src = fs.readFileSync(path.join(ROOT, "web", "js", "lib", "overlay_tft.js"), "utf8");
  assert.ok(/^[\x00-\x7f]*$/.test(src), "ASCII only");
  const css = tft.TFT_OVERLAY_CSS;
  assert.ok(!/#[0-9a-fA-F]{3,8}\b/.test(css), "no hex color literal");
  for (const m of css.matchAll(/rgba?\(([^)]*)\)/g)) {
    // the match stops at the token's own ")" - m[1] is "var(--ovx-name"
    assert.ok(/^\s*var\(--ovx-[a-z-]+$/.test(m[1]), `color from a token: ${m[0]}`);
  }
  for (const m of css.matchAll(/font-size:\s*([^;]+);/g)) {
    assert.ok(/^var\(--fs-/.test(m[1].trim()), `font size from a token: ${m[1]}`);
  }
  assert.ok(css.split("\n").filter((l) => l.includes("{")).every((l) => l.startsWith('body[data-shell="overlay"]')),
    "every rule is scoped to the overlay shell");
});
