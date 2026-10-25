// web/js/lib/overlay_tft.js
//
// S134 N9 - the TFT-centric in-game overlay panels (docs/TFT_PROGRAM.md
// section 4.3 IN-MATCH, the overlay subset).
//
// Match 3 QA (ops/runtime/tft_qa/20261025-085349/QA_REPORT.md N9): the overlay
// was ON from round 1-2 but painted no TFT data, and its panel menu offered only
// SR / ARAM panels. The TFT state the backend serves (hp, standing, board,
// players alive, game time - tft/tft_standalone.py standalone_liveclient_summary,
// copied onto the coach envelope by dashboard/_state_builder.py
// tft_coach_for_standalone) reached the overlay ONLY inside the coach CALL
// widget (active_match.js amLiveFallbackModel), and the operator had that
// widget hidden for SR. So TFT gets its own widgets with their own visibility,
// and in TFT the menu lists only them (lib/overlay_layout.js TFT_WIDGETS).
//
// Three built-in panels, all display-only (the drag handle overlay_layout adds
// is the only interactive part, so the body stays click-through):
//   w-tft-hud    vitals: HP / PLACE / ALIVE, then STAGE / LEVEL / GOLD, with
//                the game clock and the feed kind in the head row. Stage, level
//                and gold are null until the TFT vision OCR lands; every cell
//                renders "-" in a fixed grid, so data arriving changes text,
//                never geometry (feedback_no_reflow_on_data_absence).
//   w-tft-board  the local board: up to 12 fixed unit slots (name + star pips).
//   w-tft-lobby  opponents' HP. DATA-GATED: hidden until /api/state carries
//                the lobby rows (see LOBBY_FIELDS).
//
// Default positions live in overlay_layout.js TFT_WIDGETS and are measured
// against the TFT HUD on real 2560x1440 frames (tests/test_overlay_tft_layout.py
// owns the keep-out regions): top-left scenery for the vitals and lobby, the
// bottom-right scenery right of the shop for the board.
//
// Planner hook (TFT-14, NOT built here): registerTftOverlayPanel() adds a panel
// - a widget registry entry plus a per-tick render callback - without editing
// this module; TFT_PLANNER_SLOT is the reserved default box for it.
//
// Styles: web/css/** belongs to the dashboard TFT slice, so the TFT panel rules
// ship here as one injected <style id="ovt-style">, scoped to the overlay shell
// and built only from the overlay.css section-0 tokens (palette law: no color
// literal). The .ovx-widget frame itself still comes from overlay.css.
//
// Pure core (node-testable, no DOM): tftOverlayModel and its helpers. DOM glue
// (renderTftOverlay) touches the document only at call time and only on the
// overlay shell. ASCII only.

import { placeOverlayField, registerOverlayWidget } from "./overlay_layout.js";

// Mount element ids. overlay_layout.js TFT_WIDGETS selects these ("#ovt-hud"
// etc.); rc-shell/test/overlay_tft.test.js pins the two lists together.
export const TFT_MOUNT_IDS = Object.freeze({
  hud: "ovt-hud",
  lobby: "ovt-lobby",
  board: "ovt-board",
});

// Reserved default box for the TFT-14 prior-top-4 planner picker (design px,
// 1920x1080): bottom-left, under the trait panel and left of the shop.
// tests/test_overlay_tft_layout.py keeps every other default clear of it.
export const TFT_PLANNER_SLOT = Object.freeze({
  id: "w-tft-planner",
  mountId: "ovt-planner",
  label: "TFT Planner",
  x: 12,
  y: 836,
  w: 210,
});

// The /api/state lists the lobby panel reads, first non-empty wins: every
// player's {standing, health, you, board_size} by placement, opponents
// anonymous (tft/tft_standalone.py _lobby). Served by the S134 P0-F
// board-panel slice (liveclient.players, copied to coach.tft_players by
// dashboard/_state_builder.py); empty until every player's HP is known, so
// the panel stays hidden through the start-of-game sentinel window (QA N10)
// and on any build without that slice.
export const LOBBY_FIELDS = Object.freeze(["liveclient.players", "coach.tft_players"]);

export const BOARD_SLOTS = 12;
export const LOBBY_SLOTS = 7;
const DASH = "-";

// HP bands for the vitals cell. Red is the doctrine's ONE emergency pop-out.
const HP_CRIT = 20;
const HP_LOW = 40;

// -- pure helpers ---------------------------------------------------------------

function _obj(v) {
  return v && typeof v === "object" && !Array.isArray(v) ? v : {};
}

// An integer in [lo, hi], else null. Only a real finite number counts - a
// numeric string from a hand-edited file is not trusted (same law as the
// dashboard strip, active_match.js _amIntIn).
export function intIn(v, lo, hi) {
  if (typeof v !== "number" || !Number.isFinite(v)) return null;
  const n = Math.round(v);
  return n >= lo && n <= hi ? n : null;
}

// The first candidate that is a valid integer in [lo, hi]. A -1 start-of-game
// sentinel (QA N10) in an earlier slot falls through to a later valid one.
export function firstIn(cands, lo, hi) {
  for (const c of cands) {
    const n = intIn(c, lo, hi);
    if (n !== null) return n;
  }
  return null;
}

const STAGE_RE = /^\s*(\d)\s*-\s*(\d)\s*$/;

// "3-2" from the coach envelope: stage_round first (set only when the RM-615
// gate accepted the read), then a "N-M" stage string, then stage + round ints.
export function stageOf(c) {
  const p = _obj(c);
  for (const s of [p.stage_round, p.stage]) {
    const m = typeof s === "string" ? STAGE_RE.exec(s) : null;
    if (m && +m[1] >= 1 && +m[2] >= 1) return `${+m[1]}-${+m[2]}`;
  }
  const st = intIn(p.stage, 1, 9);
  const rd = intIn(p.round, 1, 9);
  return st && rd ? `${st}-${rd}` : null;
}

export function fmtClock(sec) {
  if (typeof sec !== "number" || !Number.isFinite(sec) || sec < 0) return null;
  const t = Math.floor(sec);
  return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`;
}

const CLOCK_RE = /^\d{1,3}:\d{2}$/;

// "Akali_AD" -> "Akali AD". Names are already cleaned server-side
// (tft_standalone.clean_unit_name); this only makes them readable and keeps
// them ASCII-safe for the glyph rule.
export function displayUnitName(raw) {
  if (typeof raw !== "string") return "";
  return raw.replace(/_/g, " ").replace(/[^\x20-\x7e]/g, "").trim().slice(0, 24);
}

// "Yorick*1, Xayah*2" -> [{name:"Yorick", star:1}, {name:"Xayah", star:2}].
// The board_str shape is tft_standalone._summary_from_raw. A missing or bad
// star reads as 1 (the server's own default).
export function parseBoardStr(s) {
  if (typeof s !== "string" || !s.trim()) return [];
  const out = [];
  for (const part of s.split(",")) {
    const m = /^\s*(.+?)\s*(?:\*\s*(\d+))?\s*$/.exec(part);
    if (!m) continue;
    const name = displayUnitName(m[1]);
    if (!name) continue;
    const star = intIn(m[2] === undefined ? 1 : Number(m[2]), 1, 4) || 1;
    out.push({ name, star: Math.min(star, 3) });
  }
  return out;
}

// The structured board ([{name, star, items}] - tft_standalone._board, served
// as liveclient.board and copied to coach.tft_board by the S134 P0-F
// board-panel slice) wins over board_str.
function _boardUnits(lc, c) {
  for (const b of [lc.board, c.tft_board]) {
    if (Array.isArray(b) && b.length && b.every((u) => u && typeof u === "object")) {
      const units = [];
      for (const u of b) {
        const name = displayUnitName(u.name);
        if (!name) continue;
        units.push({ name, star: Math.min(intIn(u.star, 1, 4) || 1, 3) });
      }
      return units;
    }
  }
  return parseBoardStr(typeof lc.board_str === "string" ? lc.board_str : c.board_str);
}

// The opponents' HP from the lobby rows (LOBBY_FIELDS, first non-empty list):
// the local row (you: true) is dropped - the vitals already carry it. Sorted
// alive by HP, then unknown HP ("-"), then eliminated (health 0 -> "OUT").
// null when there are no opponent rows (the panel stays hidden).
function _lobby(lc, c) {
  const list = [lc.players, c.tft_players].find((l) => Array.isArray(l) && l.length);
  if (!list) return null;
  const rows = [];
  for (const o of list) {
    if (!o || typeof o !== "object" || Array.isArray(o) || o.you === true) continue;
    const hp = intIn(o.health, 0, 100);
    // rank: 0 alive (by HP), 1 unknown, 2 eliminated
    rows.push({ hp, rank: hp === null ? 1 : hp === 0 ? 2 : 0 });
  }
  if (!rows.length) return null;
  rows.sort((a, b) => (a.rank - b.rank) || ((b.hp || 0) - (a.hp || 0)));
  return rows.slice(0, LOBBY_SLOTS).map((r) => ({
    text: r.rank === 2 ? "OUT" : r.hp === null ? DASH : String(r.hp),
    alive: r.rank !== 2,
  }));
}

export function isTftState(st) {
  return String(_obj(st).mode_key || "").trim().toLowerCase() === "tft";
}

/**
 * Pure view model for the TFT overlay panels from a full /api/state payload.
 * Every display string is final ("-" when unknown) so the renderer only copies.
 *
 * @param {object} st - /api/state (mode_key, liveclient, coach).
 * @returns {{active:boolean, source:string, time:string,
 *   vitals:{key:string,label:string,text:string,major:boolean,band:string}[],
 *   board:{count:string, units:{name:string,star:number}[], overflow:number},
 *   lobby:null|{text:string,alive:boolean}[]}}
 */
export function tftOverlayModel(st) {
  const s = _obj(st);
  const lc = _obj(s.liveclient);
  const c = _obj(s.coach);
  const active = isTftState(s);

  const hp = firstIn([lc.hp, c.hp, c.health], 1, 100);
  const place = firstIn([lc.standing, c.standing], 1, 8);
  const alive = firstIn([lc.players_alive, c.players_alive], 1, 8);
  const stage = stageOf(lc.stage_round ? lc : c);
  const level = firstIn([c.level, lc.level], 1, 10);
  const gold = firstIn([c.gold, lc.gold], 0, 999);

  let time = typeof lc.game_time === "string" && CLOCK_RE.test(lc.game_time) ? lc.game_time : null;
  if (time === null) time = fmtClock(typeof lc.game_time_s === "number" ? lc.game_time_s : c.game_time_s);

  let source = "";
  if (lc.live_api === true) source = "LIVE";
  else if (lc.source === "tft_standalone") source = "ROUND FEED";

  const d = (v) => (v === null || v === undefined ? DASH : String(v));
  let band = "";
  if (hp !== null && hp <= HP_CRIT) band = "crit";
  else if (hp !== null && hp <= HP_LOW) band = "low";

  const vitals = [
    { key: "hp", label: "HP", text: d(hp), major: true, band },
    { key: "place", label: "PLACE", text: place === null ? DASH : `#${place}`, major: true, band: "" },
    { key: "alive", label: "ALIVE", text: d(alive), major: true, band: "" },
    { key: "stage", label: "STAGE", text: d(stage), major: false, band: "" },
    { key: "level", label: "LEVEL", text: d(level), major: false, band: "" },
    { key: "gold", label: "GOLD", text: d(gold), major: false, band: "" },
  ];

  // Board. The per-round file can be a start-of-game placeholder (hp / standing
  // -1, players 0, board 0 - QA N10); with no valid standing AND no units the
  // board is unknown, not empty.
  const all = _boardUnits(lc, c);
  const known = all.length > 0 || place !== null;
  const size = firstIn([lc.board_size, c.board_size], 0, 40);
  let count = DASH;
  if (known) {
    const n = all.length || (size !== null ? size : 0);
    count = level !== null ? `${n}/${level}` : String(n);
  }
  let units = all.slice(0, BOARD_SLOTS);
  let overflow = 0;
  if (all.length > BOARD_SLOTS) {
    units = all.slice(0, BOARD_SLOTS - 1);
    overflow = all.length - (BOARD_SLOTS - 1);
  }

  return {
    active,
    source,
    time: d(time),
    vitals,
    board: { count, units, overflow },
    lobby: _lobby(lc, c),
  };
}

// -- injected styles --------------------------------------------------------------

const STYLE_ID = "ovt-style";

// Overlay-scoped; tokens only (overlay.css section 0 + the RM-139 sub-floor
// type tokens). The widget frame / width / max-height come from .ovx-widget.
// UI audit (S135): the head row sits on the shared 0.58 frame only, and at the
// default top-left spot that is over bright sky - the gold title measured a
// median 2.2:1 across the match-3 frames. It gets the same nested backing as
// the cells (same total height: 4px vertical padding + the 1px rule, as
// before), and a right pad that keeps the clock / count clear of the drag
// handle overlay_layout puts in the top-right corner.
export const TFT_OVERLAY_CSS = [
  'body[data-shell="overlay"] .ovt-panel .ovt-head {',
  "  display: flex; align-items: baseline; gap: 6px;",
  "  padding: 2px 30px 2px 6px; margin: 0 0 5px; border-radius: 4px;",
  "  background: rgba(var(--ovx-bg-nested), 0.9);",
  "  border-bottom: 1px solid rgba(var(--ovx-gold), 0.28);",
  "  white-space: nowrap;",
  "}",
  'body[data-shell="overlay"] .ovt-panel .ovt-title {',
  "  color: rgba(var(--ovx-gold), 0.90); font-size: var(--fs-ov-head);",
  "  font-weight: 700; letter-spacing: 0.15em; text-transform: uppercase;",
  "}",
  'body[data-shell="overlay"] .ovt-panel .ovt-src {',
  "  color: rgba(var(--ovx-cyan), 0.90); font-size: var(--fs-ov-head);",
  "  letter-spacing: 0.08em; text-transform: uppercase;",
  "}",
  'body[data-shell="overlay"] .ovt-panel .ovt-time {',
  "  margin-left: auto; color: rgba(var(--ovx-text), 0.85);",
  "  font-size: var(--fs-ov-chip); font-variant-numeric: tabular-nums;",
  "}",
  'body[data-shell="overlay"] .ovt-panel .ovt-grid {',
  "  display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 4px;",
  "}",
  'body[data-shell="overlay"] .ovt-panel .ovt-cell {',
  "  display: flex; flex-direction: column; min-width: 0;",
  "  padding: 2px 6px; border-radius: 4px;",
  "  background: rgba(var(--ovx-bg-nested), 0.9);",
  "}",
  'body[data-shell="overlay"] .ovt-panel .ovt-lab {',
  "  color: rgba(var(--ovx-text), 0.62); font-size: var(--fs-ov-head);",
  "  letter-spacing: 0.10em; text-transform: uppercase; line-height: 1.25;",
  "}",
  'body[data-shell="overlay"] .ovt-panel .ovt-val {',
  "  color: rgba(var(--ovx-text), 0.95); font-size: var(--fs-xs);",
  "  font-weight: 700; line-height: 1.3; font-variant-numeric: tabular-nums;",
  "  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;",
  "}",
  'body[data-shell="overlay"] .ovt-panel .ovt-cell.ovt-major .ovt-val {',
  "  font-size: var(--fs-sm); line-height: 1.2;",
  "}",
  'body[data-shell="overlay"] .ovt-panel .ovt-cell.is-empty .ovt-val {',
  "  color: rgba(var(--ovx-text), 0.45);",
  "}",
  'body[data-shell="overlay"] .ovt-panel .ovt-cell[data-band="low"] .ovt-val {',
  "  color: rgb(var(--ovx-warn));",
  "}",
  'body[data-shell="overlay"] .ovt-panel .ovt-cell[data-band="crit"] .ovt-val {',
  "  color: rgb(var(--ovx-red));",
  "}",
  'body[data-shell="overlay"] .ovt-panel .ovt-units {',
  "  display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));",
  "  grid-auto-rows: 24px; gap: 3px;",
  "}",
  'body[data-shell="overlay"] .ovt-panel .ovt-unit {',
  "  display: flex; align-items: center; gap: 4px; min-width: 0;",
  "  padding: 0 6px; border-radius: 4px;",
  "  border: 1px solid rgba(var(--ovx-gold), 0.18);",
  "  background: rgba(var(--ovx-bg-nested), 0.9);",
  "}",
  'body[data-shell="overlay"] .ovt-panel .ovt-unit.is-empty {',
  "  border-color: transparent; background: rgba(var(--ovx-bg-nested), 0.35);",
  "}",
  'body[data-shell="overlay"] .ovt-panel .ovt-unit[data-star="3"] {',
  "  border-color: rgba(var(--ovx-gold), 0.85);",
  "}",
  'body[data-shell="overlay"] .ovt-panel .ovt-unit-name {',
  "  flex: 1; min-width: 0; color: rgba(var(--ovx-text), 0.92);",
  "  font-size: var(--fs-ov-chip); line-height: 1.2;",
  "  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;",
  "}",
  'body[data-shell="overlay"] .ovt-panel .ovt-stars {',
  "  display: flex; gap: 2px; flex: none;",
  "}",
  'body[data-shell="overlay"] .ovt-panel .ovt-stars > i {',
  "  display: block; width: 5px; height: 5px; border-radius: 50%;",
  "  background: rgba(var(--ovx-text), 0.55);",
  "}",
  'body[data-shell="overlay"] .ovt-panel .ovt-stars > i[hidden] { display: none; }',
  'body[data-shell="overlay"] .ovt-panel .ovt-unit[data-star="2"] .ovt-stars > i {',
  "  background: rgba(var(--ovx-text), 0.95);",
  "}",
  'body[data-shell="overlay"] .ovt-panel .ovt-unit[data-star="3"] .ovt-stars > i {',
  "  background: rgb(var(--ovx-gold));",
  "}",
  'body[data-shell="overlay"] .ovt-panel .ovt-opps {',
  "  display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 3px;",
  "}",
  'body[data-shell="overlay"] .ovt-panel .ovt-opp {',
  "  padding: 2px 0; border-radius: 4px; text-align: center;",
  "  background: rgba(var(--ovx-bg-nested), 0.9);",
  "  color: rgba(var(--ovx-text), 0.92); font-size: var(--fs-ov-chip);",
  "  font-weight: 700; line-height: 1.3; font-variant-numeric: tabular-nums;",
  "}",
  // dimmed like the "-" placeholders (alpha 0.45, the 4.5:1 floor) at the
  // sibling chips' size - UI audit: 0.40 at 11px measured 3.8:1.
  'body[data-shell="overlay"] .ovt-panel .ovt-opp.is-out {',
  "  color: rgba(var(--ovx-text), 0.45); font-weight: 600;",
  "}",
].join("\n");

// -- DOM glue ---------------------------------------------------------------------

function _doc() {
  return typeof document !== "undefined" ? document : null;
}

function _isOverlayShell(doc) {
  try {
    return !!(doc && doc.body && doc.body.dataset && doc.body.dataset.shell === "overlay");
  } catch (_e) {
    return false;
  }
}

function _el(doc, tag, cls, text) {
  const n = doc.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}

function _setText(node, text) {
  if (node && node.textContent !== text) node.textContent = text;
}

function _setData(node, key, val) {
  if (!node || !node.dataset) return;
  if (val === "" || val === null || val === undefined) {
    if (key in node.dataset) delete node.dataset[key];
  } else if (node.dataset[key] !== String(val)) {
    node.dataset[key] = String(val);
  }
}

function _toggleClass(node, cls, on) {
  if (node && node.classList) node.classList.toggle(cls, !!on);
}

function _ensureStyle(doc) {
  if (doc.getElementById(STYLE_ID)) return;
  const st = doc.createElement("style");
  st.id = STYLE_ID;
  st.textContent = TFT_OVERLAY_CSS;
  (doc.head || doc.documentElement || doc.body).appendChild(st);
}

// A panel mount: <div id class="ovt-panel"><div class="ovt-body">...</div></div>.
// overlay_layout appends its drag handle as a sibling of .ovt-body, so a
// re-render never touches the handle. Created hidden; placed before un-hide.
function _ensureMount(doc, id, build) {
  let el = doc.getElementById(id);
  if (el) return { el, created: false };
  el = _el(doc, "div", "ovt-panel");
  el.id = id;
  el.hidden = true;
  el.setAttribute("role", "group");
  const body = _el(doc, "div", "ovt-body");
  el.appendChild(body);
  if (typeof build === "function") build(doc, body);
  doc.body.appendChild(el);
  return { el, created: true };
}

function _body(el) {
  return (el && el.querySelector && el.querySelector(":scope > .ovt-body")) || el;
}

function _buildHud(doc, body) {
  const head = _el(doc, "div", "ovt-head");
  // titled like its menu row ("TFT Vitals") and its aria label
  head.appendChild(_el(doc, "span", "ovt-title", "TFT Vitals"));
  head.appendChild(_el(doc, "span", "ovt-src", ""));
  head.appendChild(_el(doc, "span", "ovt-time", DASH));
  body.appendChild(head);
  const grid = _el(doc, "div", "ovt-grid");
  for (const [key, label, major] of [
    ["hp", "HP", true], ["place", "PLACE", true], ["alive", "ALIVE", true],
    ["stage", "STAGE", false], ["level", "LEVEL", false], ["gold", "GOLD", false],
  ]) {
    const cell = _el(doc, "div", "ovt-cell is-empty" + (major ? " ovt-major" : ""));
    cell.dataset.k = key;
    cell.appendChild(_el(doc, "span", "ovt-lab", label));
    cell.appendChild(_el(doc, "span", "ovt-val", DASH));
    grid.appendChild(cell);
  }
  body.appendChild(grid);
}

function _buildBoard(doc, body) {
  const head = _el(doc, "div", "ovt-head");
  head.appendChild(_el(doc, "span", "ovt-title", "Board"));
  head.appendChild(_el(doc, "span", "ovt-time", DASH));
  body.appendChild(head);
  const grid = _el(doc, "div", "ovt-units");
  for (let i = 0; i < BOARD_SLOTS; i += 1) {
    const u = _el(doc, "div", "ovt-unit is-empty");
    u.appendChild(_el(doc, "span", "ovt-unit-name", ""));
    const stars = _el(doc, "span", "ovt-stars");
    for (let k = 0; k < 3; k += 1) {
      const pip = _el(doc, "i");
      pip.hidden = true;
      stars.appendChild(pip);
    }
    u.appendChild(stars);
    grid.appendChild(u);
  }
  body.appendChild(grid);
}

function _buildLobby(doc, body) {
  const head = _el(doc, "div", "ovt-head");
  head.appendChild(_el(doc, "span", "ovt-title", "Lobby HP"));
  body.appendChild(head);
  const grid = _el(doc, "div", "ovt-opps");
  for (let i = 0; i < LOBBY_SLOTS; i += 1) grid.appendChild(_el(doc, "div", "ovt-opp", DASH));
  body.appendChild(grid);
}

function _renderHud(el, m) {
  const b = _body(el);
  _setText(b.querySelector(".ovt-src"), m.source);
  _setText(b.querySelector(".ovt-time"), m.time);
  for (const v of m.vitals) {
    const cell = b.querySelector(`.ovt-cell[data-k="${v.key}"]`);
    if (!cell) continue;
    _setText(cell.querySelector(".ovt-val"), v.text);
    _toggleClass(cell, "is-empty", v.text === DASH);
    _setData(cell, "band", v.band);
  }
  el.setAttribute("aria-label", "TFT vitals");
}

function _renderBoard(el, m) {
  const b = _body(el);
  _setText(b.querySelector(".ovt-time"), m.board.count);
  const slots = b.querySelectorAll(".ovt-unit");
  for (let i = 0; i < slots.length; i += 1) {
    const slot = slots[i];
    const name = slot.querySelector(".ovt-unit-name");
    const pips = slot.querySelectorAll(".ovt-stars > i");
    const u = m.board.units[i];
    let text = "";
    let star = 0;
    if (u) {
      text = u.name;
      star = u.star;
    } else if (i === m.board.units.length && m.board.overflow > 0) {
      text = `+${m.board.overflow} more`;
    }
    _setText(name, text);
    _toggleClass(slot, "is-empty", !text);
    _setData(slot, "star", star || "");
    for (let k = 0; k < pips.length; k += 1) {
      const want = k >= star;
      if (pips[k].hidden !== want) pips[k].hidden = want;
    }
    if (u) slot.setAttribute("aria-label", `${u.name}, ${u.star} star`);
    else slot.removeAttribute("aria-label");
  }
  el.setAttribute("aria-label", "TFT board");
}

function _renderLobby(el, m) {
  const b = _body(el);
  const cells = b.querySelectorAll(".ovt-opp");
  const rows = m.lobby || [];
  for (let i = 0; i < cells.length; i += 1) {
    const r = rows[i];
    _setText(cells[i], r ? r.text : DASH);
    _toggleClass(cells[i], "is-out", !!(r && !r.alive));
  }
  el.setAttribute("aria-label", "TFT lobby HP");
}

const BUILTIN = [
  { mountId: TFT_MOUNT_IDS.hud, build: _buildHud, render: _renderHud, gated: false },
  { mountId: TFT_MOUNT_IDS.board, build: _buildBoard, render: _renderBoard, gated: false },
  { mountId: TFT_MOUNT_IDS.lobby, build: _buildLobby, render: _renderLobby, gated: true },
];

// Extra panels registered by later slices (TFT-14 planner). Keyed by widget id.
const _extraPanels = new Map();

/**
 * Planner hook (TFT-14). Adds one TFT overlay panel: a widget-field entry
 * (movable, persisted, listed in the TFT menu) plus a render callback the TFT
 * render pass calls on every state tick with (bodyEl, model, state). The panel
 * owns its own content and marks its own interactive controls [data-rc-zone]
 * (rc-shell clickthrough_zones.js) so the rest stays click-through. Returns
 * false on a malformed spec. Re-registering an id replaces it.
 */
export function registerTftOverlayPanel(spec) {
  const s = _obj(spec);
  const id = typeof s.id === "string" ? s.id : "";
  const mountId = typeof s.mountId === "string" ? s.mountId : "";
  if (!/^w-tft-[a-z0-9-]+$/.test(id) || !/^ovt-[a-z0-9-]+$/.test(mountId)) return false;
  if (typeof s.render !== "function") return false;
  if (Object.values(TFT_MOUNT_IDS).includes(mountId)) return false;
  const ok = registerOverlayWidget({
    id,
    sel: "#" + mountId,
    x: s.x,
    y: s.y,
    w: s.w,
    tier: typeof s.tier === "string" ? s.tier : "ambient",
    label: typeof s.label === "string" && s.label ? s.label : id,
    game: "tft",
  });
  if (!ok) return false;
  _extraPanels.set(id, { mountId, render: s.render });
  return true;
}

function _hideAll(doc) {
  const ids = [...BUILTIN.map((p) => p.mountId), ...[..._extraPanels.values()].map((p) => p.mountId)];
  for (const id of ids) {
    const el = doc.getElementById(id);
    if (el && !el.hidden) el.hidden = true;
  }
}

// Stamp which game family the overlay field shows. overlay_layout.js reads it
// (data-ovx-game wins over body[data-mode], which a health tick can flap) to
// pick the TFT or the League widget set and menu.
function _stampGame(doc, tft) {
  const want = tft ? "tft" : "lol";
  if (doc.body.dataset.ovxGame === want) return false;
  doc.body.dataset.ovxGame = want;
  return true;
}

/**
 * Render the TFT overlay panels from a full /api/state payload. No-op off the
 * overlay shell. Outside TFT it hides the panels (and hands the field back to
 * the League set). Never throws into the state stream.
 * @returns {object|null} the model rendered, or null when nothing rendered.
 */
export function renderTftOverlay(st) {
  const doc = _doc();
  if (!_isOverlayShell(doc)) return null;
  try {
    const m = tftOverlayModel(st);
    const flipped = _stampGame(doc, m.active);
    if (!m.active) {
      _hideAll(doc);
      if (flipped) placeOverlayField();
      return null;
    }
    _ensureStyle(doc);
    let created = false;
    const shown = [];
    for (const p of BUILTIN) {
      const r = _ensureMount(doc, p.mountId, p.build);
      created = created || r.created;
      p.render(r.el, m);
      shown.push([r.el, !(p.gated && !m.lobby)]);
    }
    for (const [, p] of _extraPanels) {
      const r = _ensureMount(doc, p.mountId, null);
      created = created || r.created;
      let ok = true;
      try {
        p.render(_body(r.el), m, st);
      } catch (_e) {
        ok = false; // a broken extra panel stays hidden; the built-ins still paint.
      }
      shown.push([r.el, ok]);
    }
    // Place BEFORE un-hiding so a new mount never paints unpositioned.
    if (created || flipped) placeOverlayField();
    for (const [el, on] of shown) {
      if (el.hidden === on) el.hidden = !on;
    }
    return m;
  } catch (_e) {
    return null;
  }
}

export const _internals = {
  STYLE_ID,
  BUILTIN,
  HP_CRIT,
  HP_LOW,
  _extraPanels,
  _stampGame,
};
