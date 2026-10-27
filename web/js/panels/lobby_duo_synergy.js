// Lobby duo-synergy block (RM-881 (b), QA23 "lobby re-fire of duo synergy").
//
// /api/duo-synergy (dashboard/routes_duo_synergy.py) serves the bot + support
// pairing rows, but since item 213 replaced the champ-select duo grid nothing in
// web/ called it. This module re-fires it from the lobby: when the party size
// reaches 2 (a duo or bigger party has formed) in a Summoner's Rift queue (the
// only map with a bot + support pairing) the controller fetches the route
// ONCE for that party episode, and again only when the party drops back to solo
// and re-forms or the operator's first lane preference changes its role. The 2 s
// lobby refresh therefore never spams the route.
//
// In the lobby no champion is locked or hovered, so the route resolves mode
// "none": the top bot and top support picks. The RC_DUO_SYNERGY_LIVE kill switch
// lives server-side (core/smoothed_rates_101qq.py) and is untouched; with it off
// the route still answers from the static seed.
//
// Discipline: pure ESM, DOM-free (node --test importable), ASCII only, fail-soft.
// A failed fetch renders a friendly line and never the raw error (CLAUDE.md
// "Error handling"). The champion icon URL is injected by the caller so this
// module does not import the DDragon index (which fetches at import time).

const ROUTE = "/api/duo-synergy";
const MOCK_URL = "/data/ui_mock/duo_synergy.json";
const TOP_N = 4;

function _esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function _partySize(lobby) {
  if (!lobby || typeof lobby !== "object") return 0;
  const n = Number(lobby.party_size);
  if (Number.isFinite(n) && n > 0) return n;
  return Array.isArray(lobby.members) ? lobby.members.length : 0;
}

// LCU lane preference -> the route's my_role. UTILITY is the LCU's support enum;
// every other lane (and no preference yet) takes the route's own default, bot.
function roleForPref(pref) {
  return String(pref || "").toUpperCase() === "UTILITY" ? "sup" : "bot";
}

function _myRole(lobby) {
  const lm = lobby && (lobby.local_member || lobby.localMember);
  const prefs = lm && (lm.position_preferences || lm.positionPreferences);
  const first = prefs && (prefs.first_preference || prefs.firstPreference);
  return roleForPref(first);
}

// The request a lobby calls for, or null while solo / before the lobby lands /
// in a queue with no bot lane. isDuoQueue(queue_id) is the caller's queue gate
// (main.js passes its SR_QUEUE_IDS, the set that gates the lane-pair control):
// ARAM and Arena have no bot + support pairing, so they never fetch it.
export function duoSynergyQuery(lobby, isDuoQueue = () => true) {
  if (_partySize(lobby) < 2) return null;
  if (!isDuoQueue(Number(lobby.queue_id) || 0)) return null;
  const params = new URLSearchParams({ my_role: _myRole(lobby),
                                       top_n: String(TOP_N) });
  return `${ROUTE}?${params.toString()}`;
}

// Controller. update(lobby) returns the in-flight promise when it fires a
// request and null otherwise; state() is {status, payload}; status is one of
// idle | loading | ready | error.
export function createLobbyDuoSynergy(opts = {}) {
  const fetchImpl = opts.fetchImpl || ((u, o) => fetch(u, o));
  const isMock = opts.isMock || (() => false);
  const onChange = opts.onChange || (() => {});
  const isDuoQueue = opts.isDuoQueue || (() => true);
  let st = { status: "idle", payload: null };
  let firedFor = null;   // the query the current party episode fetched
  let seq = 0;           // drops a response that a later update superseded

  function _set(next) {
    st = next;
    try { onChange(st); } catch (_) { /* a render bug must not stop the poll */ }
  }

  function update(lobby) {
    const q = duoSynergyQuery(lobby, isDuoQueue);
    if (q === null) {
      firedFor = null;
      seq += 1;
      if (st.status !== "idle") _set({ status: "idle", payload: null });
      return null;
    }
    if (q === firedFor) return null;
    firedFor = q;
    const mine = ++seq;
    _set({ status: "loading", payload: null });
    const url = isMock() ? MOCK_URL : q;
    return Promise.resolve()
      .then(() => fetchImpl(url, { cache: "no-store" }))
      .then((r) => (r && r.ok ? r.json() : null))
      .then((data) => {
        if (mine !== seq) return;
        if (data && data.ok) _set({ status: "ready", payload: data });
        else _set({ status: "error", payload: null });
      })
      .catch(() => {
        if (mine !== seq) return;
        _set({ status: "error", payload: null });
      });
  }

  return { update, state: () => st };
}

function _pct(rate) {
  const n = Number(rate);
  return Number.isFinite(n) && n > 0 ? `${(n * 100).toFixed(1)}%` : "-";
}

function _cellHtml(cell, iconUrlFor) {
  const name = (cell && cell.champ) || "";
  const src = name ? iconUrlFor(name) : "";
  const img = src
    ? `<img class="lv-duosyn-icon" src="${_esc(src)}" alt="" loading="lazy" />`
    : `<span class="lv-duosyn-icon is-blank" aria-hidden="true"></span>`;
  return `<li class="lv-duosyn-cell" title="${_esc(name)}">${img}` +
    `<span class="lv-duosyn-name">${_esc(name)}</span>` +
    `<span class="lv-duosyn-wr">${_pct(cell && cell.smoothed_rate)}</span></li>`;
}

function _rowHtml(kind, label, cells, iconUrlFor) {
  const list = Array.isArray(cells) ? cells : [];
  return `<div class="lv-duosyn-row lv-duosyn-row-${kind}">` +
    `<span class="lv-duosyn-role">${label}</span>` +
    `<ul class="lv-duosyn-cells">${list.map((c) => _cellHtml(c, iconUrlFor)).join("")}</ul>` +
    `</div>`;
}

// Block body for a controller state. "" means: hide the block (solo).
export function lobbyDuoSynergyHtml(state, iconUrlFor) {
  const s = state || {};
  const icon = typeof iconUrlFor === "function" ? iconUrlFor : () => "";
  const head = `<div class="lv-duosyn-title">DUO PICKS</div>`;
  if (s.status === "loading") {
    return head + `<div class="lv-duosyn-note">loading duo picks...</div>`;
  }
  if (s.status === "error") {
    return head + `<div class="lv-duosyn-note">duo picks unavailable right now</div>`;
  }
  if (s.status !== "ready" || !s.payload) return "";
  const top = s.payload.top_row || [];
  const bottom = s.payload.bottom_row || [];
  if (!top.length && !bottom.length) {
    return head + `<div class="lv-duosyn-note">no duo picks yet</div>`;
  }
  return head +
    _rowHtml("bot", "BOT", top, icon) +
    _rowHtml("sup", "SUPPORT", bottom, icon);
}

export const __test = { roleForPref, _partySize, _myRole, _esc, _pct };
