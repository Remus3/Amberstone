// DS-Matchup card. Surfaces the EXISTING 1v1 matchup engine for the
// operator's champion against the ROLE-MATCHED lane opponent - a one-glance
// "all-in / trade / back-off / even" read at the level the engine simulates -
// plus a danger grid covering every committed enemy. Pure presentation over
// the existing engine; no new compute lives here.
//
// BACKLOG F5 (2026-07-20): the headline pairing used to be the LEADING pick
// on the enemy roster (index zero), which is the operator's actual laner only
// by coincidence. It now matches on ROLE. Role is already client-side on both
// feeds this panel is driven from - champ-select cells carry
// `assignedPosition` (web/js/panels/champ_select.js:540 renders the role pip
// off it) and the live roster carries `liveclient.players[].position`, an LCU
// ROLE STRING built by dashboard/_liveclient.py:225 from the same allPlayers
// array. No new route and no new backend field.
//
// BACKLOG F1 (2026-07-20): the same per-pair cached /api/ds-matchup call is
// fanned out over all committed enemies and binned into a severity grid, so
// the whole enemy team is readable at a glance and not just the laner.
//
// Backend wire:
//   GET /api/ds-matchup?champ_a=<slug-or-numeric>&champ_b=<slug-or-numeric>&mode=SR
//   Response (ok=true): {
//     ok, champ_a, champ_b, level_a, level_b, mode,
//     verdict("all_in"|"trade"|"back_off"|"even"),
//     net_swing(-1..1), swing_pct(int 0-100, 50=even),
//     favored("A"|"B"|"even"),
//     pct_a_removed(0..1), pct_b_removed(0..1),
//     dmg_a_to_b, dmg_b_to_a,
//     a_can_full_combo(bool), b_can_full_combo(bool),
//     notes(list[str]), elapsed_ms, cached
//   }
//   Failure: ok=false (reason "no_matchup") or non-200 -> panel hides.
//
// champ_a is read from the champ-select-shaped state (cs.my_champion, the
// operator's own numeric LCU id); champ_b is drawn per enemy from
// cs.their_team. Every id resolves to a DDragon slug via resolveChampNames
// (imported from cc_conditional_pressure.js, exactly as ds_profile.js does).
//
// Discipline: pure ESM, ASCII only, per-key cache + TTL, sig-dedup gate,
// inflight guard, no DOM writes outside renderDsMatchup(). Fail-soft on
// null / empty / not-ok payloads (hide via the hidden attr). Mirrors the
// ds_profile.js module shape. ASCII only - no unicode arrows / em-dashes.

import { resolveChampNames } from './cc_conditional_pressure.js';

const _DSM_CACHE = Object.create(null);     // cacheKey -> response JSON
const _DSM_INFLIGHT = Object.create(null);
const _DSM_TS = Object.create(null);
const _DSM_SIG = Object.create(null);       // mount-id -> last-rendered sig
const _DSM_TTL_MS = 5 * 60 * 1000;          // matches backend TTL

function _cacheKey(champA, champB, mode) {
  return `${champA || ""}|${champB || ""}|${(mode || "SR").toUpperCase()}`;
}

// Map a verdict string onto its chip modifier class. Unknown / missing
// verdicts fall back to the neutral "even" tint so a partial payload still
// renders a chip.
function _verdictClass(verdict) {
  const v = String(verdict || "").toLowerCase();
  if (v === "all_in") return "dsm-all_in";
  if (v === "trade") return "dsm-trade";
  if (v === "back_off") return "dsm-back_off";
  return "dsm-even";
}

// Human label for the verdict chip. ASCII only (no arrows).
function _verdictLabel(verdict) {
  const v = String(verdict || "").toLowerCase();
  if (v === "all_in") return "ALL IN";
  if (v === "trade") return "TRADE";
  if (v === "back_off") return "BACK OFF";
  return "EVEN";
}

// Clamp swing_pct into 0..100 so a stray out-of-range value never positions
// the marker outside the bar. Non-numeric collapses to 50 (even / center).
function _clampSwing(pct) {
  const n = +pct;
  if (!isFinite(n)) return 50;
  if (n < 0) return 0;
  if (n > 100) return 100;
  return Math.round(n);
}

// Convert a 0..1 removed fraction into a clamped integer percent for the
// end labels. Non-numeric collapses to 0 (fail-soft).
function _pctRemoved(frac) {
  const n = +frac;
  if (!isFinite(n)) return 0;
  if (n < 0) return 0;
  if (n > 1) return 100;
  return Math.round(n * 100);
}

// Short display name for the bar end labels - first token / trimmed slug.
// Keeps the label compact so both ends fit the bar width. ASCII only.
function _shortName(name) {
  const s = String(name == null ? "" : name).trim();
  if (!s) return "-";
  return s.length > 10 ? s.slice(0, 10) : s;
}

// --- F5 role matching -------------------------------------------------
//
// Both feeds speak the same LCU role vocabulary (TOP / JUNGLE / MIDDLE /
// BOTTOM / UTILITY) with case drift plus a "NONE" sentinel in the role-less
// modes (ARAM, Arena). Aliases fold the short spellings RC renders elsewhere
// (_ROLE_FROM_LCU in champ_select.js). An unknown or NONE role returns "",
// which is the signal to fall back to pick order.
const _ROLE_ALIASES = {
  TOP: "TOP",
  JUNGLE: "JUNGLE", JUNGLER: "JUNGLE", JNG: "JUNGLE",
  MIDDLE: "MIDDLE", MID: "MIDDLE",
  BOTTOM: "BOTTOM", BOT: "BOTTOM", ADC: "BOTTOM",
  UTILITY: "UTILITY", SUPPORT: "UTILITY", SUP: "UTILITY",
};

const _ROLE_SHORT = {
  TOP: "TOP", JUNGLE: "JNG", MIDDLE: "MID", BOTTOM: "BOT", UTILITY: "SUP",
};

function _normRole(pos) {
  const s = String(pos == null ? "" : pos).trim().toUpperCase();
  if (!s || s === "NONE") return "";
  return _ROLE_ALIASES[s] || "";
}

// Compact role label for the grid pip. "" when the role is unknown so the
// pip collapses rather than rendering a placeholder.
function _roleShort(pos) {
  return _ROLE_SHORT[_normRole(pos)] || "";
}

// The operator's own role. The active-match synthetic cs mirrors the live
// is_active roster row onto cs.my_position; a champ-select cs carries it on
// the local cell (mirrors _csvResolveRole in champ_select.js). Neither is
// required - "" degrades to pick order, the pre-F5 behavior.
function _myRole(cs) {
  if (!cs) return "";
  const direct = _normRole(cs.my_position);
  if (direct) return direct;
  const mine = (Array.isArray(cs.my_team) ? cs.my_team : [])
    .find((p) => p && p.cellId != null && p.cellId === cs.local_cell);
  return _normRole(mine && mine.assignedPosition);
}

// Normalize cs.their_team into [{id, role}] rows, dropping uncommitted cells
// (championId 0) and capping at a full roster. Reads assignedPosition (the
// champ-select cell field) with `position` as the alternate spelling.
function _enemyRows(cs) {
  const raw = (cs && Array.isArray(cs.their_team)) ? cs.their_team : [];
  const out = [];
  for (const p of raw) {
    if (!p || typeof p !== "object") continue;
    const id = (p.championId | 0) || 0;
    if (id <= 0) continue;
    out.push({ id: id, role: _normRole(p.assignedPosition || p.position) });
    if (out.length >= 5) break;
  }
  return out;
}

// F5: index of the ROLE-MATCHED lane opponent. Falls back to the first
// committed enemy when the operator's role is unknown (ARAM / Arena report
// NONE) or no enemy declares the matching role - which reproduces the
// pre-fix leading-pick behavior exactly rather than hiding the card.
function _laneOpponentIdx(rows, myRole) {
  const want = _normRole(myRole);
  if (want) {
    for (let i = 0; i < rows.length; i += 1) {
      if (rows[i].role === want) return i;
    }
  }
  return rows.length ? 0 : -1;
}

// --- F1 danger binning ------------------------------------------------
//
// verdict is the primary signal (it is the engine's own call); swing_pct only
// breaks ties inside "even" so a lopsided-but-even cell still leans. Returns
// a modifier suffix read red -> green from the OPERATOR's point of view.
function _severity(payload) {
  if (!payload || !payload.ok) return "unknown";
  const v = String(payload.verdict || "").toLowerCase();
  if (v === "all_in") return "good";
  if (v === "trade") return "lean-good";
  if (v === "back_off") return "bad";
  const swing = _clampSwing(payload.swing_pct);
  if (swing >= 58) return "lean-good";
  if (swing <= 42) return "lean-bad";
  return "even";
}

// Fetch + memoize. Returns nothing - caller re-renders on next tick when the
// cache lands. ``onLand`` is an optional re-render callback.
export function fetchDsMatchup(champA, champB, mode, onLand) {
  if (!champA || !champB) return;
  const key = _cacheKey(champA, champB, mode);
  const fresh = _DSM_CACHE[key] && _DSM_TS[key]
                && (Date.now() - _DSM_TS[key]) < _DSM_TTL_MS;
  if (fresh || _DSM_INFLIGHT[key]) return;
  _DSM_INFLIGHT[key] = true;
  const qs = new URLSearchParams({
    champ_a: String(champA),
    champ_b: String(champB),
    mode: String(mode || "SR").toUpperCase(),
  });
  fetch("/api/ds-matchup?" + qs.toString(), { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      _DSM_INFLIGHT[key] = false;
      if (data) {
        _DSM_CACHE[key] = data;
        _DSM_TS[key] = Date.now();
        if (typeof onLand === "function") onLand();
      }
    })
    .catch(() => { _DSM_INFLIGHT[key] = false; });
}

export function getCachedDsMatchup(champA, champB, mode) {
  return _DSM_CACHE[_cacheKey(champA, champB, mode)] || null;
}

export function getDsMatchupCacheCount() {
  return Object.keys(_DSM_CACHE).length;
}

// Pure-function signature builder for the sig-dedup gate. Anything that
// changes the rendered card (champs, verdict, swing, removed pcts) should
// change the sig so an unchanged payload skips the innerHTML rebuild.
function _signature(payload, grid) {
  const head = (!payload || !payload.ok)
    ? (payload && payload.reason ? `_${payload.reason}` : "_empty")
    : [
      payload.champ_a || "",
      payload.champ_b || "",
      String(payload.verdict || ""),
      _clampSwing(payload.swing_pct),
      _pctRemoved(payload.pct_a_removed),
      _pctRemoved(payload.pct_b_removed),
    ].join("|");
  // The grid re-renders on any cell landing / changing, so its own shape has
  // to be part of the sig or a late-landing enemy fetch would be swallowed.
  const cells = Array.isArray(grid) ? grid : [];
  const tail = cells.map((c) => [
    c && c.champ ? c.champ : "",
    c && c.role ? c.role : "",
    c && c.isLane ? "L" : "",
    _severity(c && c.payload),
    (c && c.payload && c.payload.ok) ? _clampSwing(c.payload.swing_pct) : "-",
  ].join(":")).join(",");
  return head + "#" + tail;
}

// HTML-escape the small free-form strings (champ names, notes) the backend
// passes through. Mirrors the defensive escaping the sibling champ-select
// panels use before innerHTML.
function _esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// Build the casts-gate note lines. The backend notes list is rendered
// verbatim (escaped); a full-combo marker is appended per side when the
// engine reports the champ can land its full combo. Returns an HTML string.
function _notesHtml(payload) {
  const lines = [];
  const aName = _shortName(payload.champ_a);
  const bName = _shortName(payload.champ_b);
  if (payload.a_can_full_combo) {
    lines.push(
      `<div class="dsm-note dsm-note-cast">`
      + `<span class="dsm-cast">full combo</span> ${_esc(aName)} lands full combo`
      + `</div>`
    );
  }
  if (payload.b_can_full_combo) {
    lines.push(
      `<div class="dsm-note dsm-note-cast">`
      + `<span class="dsm-cast">full combo</span> ${_esc(bName)} lands full combo`
      + `</div>`
    );
  }
  const notes = Array.isArray(payload.notes) ? payload.notes : [];
  for (const n of notes) {
    const t = _esc(n);
    if (t) lines.push(`<div class="dsm-note">${t}</div>`);
  }
  return lines.join("");
}

// F1 danger grid. One row per committed enemy: role pip, champion, verdict,
// swing. The role-matched laner is flagged so the grid and the headline card
// visibly agree about which pairing the swing bar above describes. A cell
// whose fetch has not landed renders a muted placeholder rather than
// reflowing the grid when it arrives (no-reflow-on-data-absence).
function _gridHtml(grid) {
  const cells = Array.isArray(grid) ? grid : [];
  if (cells.length < 2) return "";  // a lone enemy IS the headline card
  // AUDIT (HIERARCHY): only claim a lane match when one actually happened.
  // In the role-less modes (ARAM / Arena) _laneOpponentIdx falls back to pick
  // order, so marking that row "lane opponent" and tinting it would assert a
  // pairing the data never established. Without a resolved role the grid is a
  // flat threat list - no marker, no claim.
  const roleMatched = cells.some((c) => c && c.isLane && _normRole(c.role));
  const rows = cells.map((c) => {
    const p = c && c.payload;
    const ok = !!(p && p.ok);
    const sev = _severity(p);
    const role = _roleShort(c && c.role);
    const lane = (roleMatched && c && c.isLane) ? " is-lane" : "";
    const nm = _esc(_shortName(c && c.champ));
    const verdict = ok ? _esc(_verdictLabel(p.verdict)) : "--";
    const swing = ok ? `${_clampSwing(p.swing_pct)}%` : "--";
    return (
      `<li class="dsm-grid-cell dsm-sev-${sev}${lane}">`
      + `<span class="dsm-grid-role">${_esc(role)}</span>`
      + `<span class="dsm-grid-champ">${nm}</span>`
      + `<span class="dsm-grid-verdict">${verdict}</span>`
      + `<span class="dsm-grid-swing">${swing}</span>`
      + `</li>`
    );
  }).join("");
  const title = roleMatched
    ? "Enemy team - lane opponent marked"
    : "Enemy team";
  return (
    `<div class="dsm-grid">`
    + `<div class="dsm-grid-title">${title}</div>`
    + `<ul class="dsm-grid-list">${rows}</ul>`
    + `</div>`
  );
}

// Render the matchup card into the provided element. payload is the backend
// response for the LANE opponent (may be null on cold-load); grid is the
// optional per-enemy severity list. Hides on null / not-ok payloads.
export function renderDsMatchup(blockEl, payload, grid) {
  if (!blockEl) return;
  const sigKey = blockEl.id || "_dsm_default";
  const sig = _signature(payload, grid);
  if (_DSM_SIG[sigKey] === sig) return;
  _DSM_SIG[sigKey] = sig;

  if (!payload || !payload.ok) {
    blockEl.hidden = true;
    return;
  }
  blockEl.hidden = false;

  const aName = _esc(payload.champ_a || "");
  const bName = _esc(payload.champ_b || "");
  const aShort = _esc(_shortName(payload.champ_a));
  const bShort = _esc(_shortName(payload.champ_b));
  const verdictCls = _verdictClass(payload.verdict);
  const verdictLbl = _esc(_verdictLabel(payload.verdict));
  const swing = _clampSwing(payload.swing_pct);
  const aRemoved = _pctRemoved(payload.pct_a_removed);
  const bRemoved = _pctRemoved(payload.pct_b_removed);
  const notes = _notesHtml(payload);
  const gridHtml = _gridHtml(grid);
  // Role of the pairing the swing bar describes, so the operator can see the
  // headline is their LANE and not just whoever picked first (F5).
  const laneCell = (Array.isArray(grid) ? grid : []).find((c) => c && c.isLane);
  const laneRole = _esc(_roleShort(laneCell && laneCell.role));
  const laneTag = laneRole
    ? `<span class="dsm-head-lane">${laneRole} lane</span>`
    : "";

  blockEl.innerHTML = (
    `<div class="dsm-head">`
    + `<span class="dsm-head-title">DS matchup</span>`
    + `<span class="dsm-head-sub">${aName} vs ${bName}</span>`
    + laneTag
    + `<span class="dsm-verdict ${verdictCls}">${verdictLbl}</span>`
    + `</div>`
    + `<div class="dsm-swing">`
    + `<div class="dsm-swing-track">`
    + `<span class="dsm-swing-mid"></span>`
    + `<span class="dsm-swing-marker" style="left:${swing}%"></span>`
    + `</div>`
    + `<div class="dsm-swing-ends">`
    + `<span class="dsm-swing-end dsm-swing-end-a">`
    + `${aShort} <span class="dsm-swing-pct">${bRemoved}% removed</span>`
    + `</span>`
    + `<span class="dsm-swing-end dsm-swing-end-b">`
    + `<span class="dsm-swing-pct">${aRemoved}% removed</span> ${bShort}`
    + `</span>`
    + `</div>`
    + `</div>`
    + (notes ? `<div class="dsm-notes">${notes}</div>` : "")
    + gridHtml
  );
}

// Entry point. Mirrors renderDsProfileForChampSelect(cs): read the operator's
// champion (champ_a = cs.my_champion) plus every committed enemy from
// cs.their_team, resolve the slugs, fetch each pairing, and render the
// ROLE-MATCHED laner as the headline card (F5) over a per-enemy danger grid
// (F1). ``blockId`` defaults to the DS-cluster mount but is overridable for
// tests. Every pairing rides the SAME per-pair cached /api/ds-matchup route -
// no new route, no new backend field.
export function renderDsMatchupForChampSelect(cs, blockId) {
  const block = document.getElementById(blockId || "csv-sugg-ds-matchup");
  if (!block) return;
  const myId = (cs && (cs.my_champion | 0)) || 0;
  if (myId <= 0) {
    block.hidden = true;
    return;
  }
  const rows = _enemyRows(cs);
  if (!rows.length) {
    block.hidden = true;
    return;
  }
  const champA = resolveChampNames([myId])[0] || "";
  if (!champA) {
    // CHAMPS index not yet loaded - keep hidden, resolves next tick.
    block.hidden = true;
    return;
  }
  const mode = "SR";
  const laneIdx = _laneOpponentIdx(rows, _myRole(cs));
  const grid = [];
  for (let i = 0; i < rows.length; i += 1) {
    const champB = resolveChampNames([rows[i].id])[0] || "";
    if (!champB) continue;
    fetchDsMatchup(champA, champB, mode, _dsmOnLand);
    grid.push({
      champ: champB,
      role: rows[i].role,
      isLane: (i === laneIdx),
      payload: getCachedDsMatchup(champA, champB, mode),
    });
  }
  if (!grid.length) {
    block.hidden = true;
    return;
  }
  // The lane row can drop out if its slug failed to resolve; the leading
  // resolved enemy is the same fallback _laneOpponentIdx already uses.
  const lane = grid.find((c) => c.isLane) || grid[0];
  lane.isLane = true;
  renderDsMatchup(block, lane.payload, grid);
}

// Re-render hook fired when a fetch lands. The orchestrator wires the real
// champ-select scheduler in champ_select.js; this module-local default is a
// no-op so the panel is safe to import standalone (tests + cold mount).
let _dsmScheduleRender = null;
function _dsmOnLand() {
  if (typeof _dsmScheduleRender === "function") _dsmScheduleRender();
}
export function setDsMatchupScheduler(fn) {
  _dsmScheduleRender = (typeof fn === "function") ? fn : null;
}

// Reset helper for tests (clears in-memory cache + sig stamps).
export function _resetDsMatchup() {
  for (const k of Object.keys(_DSM_CACHE))    delete _DSM_CACHE[k];
  for (const k of Object.keys(_DSM_INFLIGHT)) delete _DSM_INFLIGHT[k];
  for (const k of Object.keys(_DSM_TS))       delete _DSM_TS[k];
  for (const k of Object.keys(_DSM_SIG))      delete _DSM_SIG[k];
}

export const __test = {
  _cacheKey,
  _verdictClass,
  _verdictLabel,
  _clampSwing,
  _pctRemoved,
  _shortName,
  _signature,
  _notesHtml,
  _esc,
  _normRole,
  _roleShort,
  _myRole,
  _enemyRows,
  _laneOpponentIdx,
  _severity,
  _gridHtml,
  _DSM_TTL_MS,
};
