// DS relative-score bar panel (competitor lift #3,
// docs/COMPETITOR_LIFT_2026-05-30.md "Lift 3", Aggregator P relative-score
// bars). A READ-ONLY ranked bar list for the LOCKED champion: each row is
// an item name + a horizontal bar filled to that item's DPS delta as a
// percent of the best item, with the percent label. NO control inputs -
// this is a relative-power view, not the operator-knob surface
// (/api/ds-knobs -> ds_knobs.js owns the knobs).
//
// This is the long-HELD competitor lift #3 surface: item 200 deleted the
// old DS-top-picks render row, so the relative-score bar needed a NEW home.
// It ships as its OWN champ-select panel - the same pattern the 4 item-219
// lifts used.
//
// Backend wire:
//   GET /api/ds-relscore?champion=<champ>&mode=SR[&items=][&level=11]
//   Response: {
//     ok, champion, target:{armor, mr, level, mode},
//     rows:[{item_id, name, delta_dps, score_pct, gold}],
//     count, elapsed_ms, cached
//   }
//
// The locked champion comes from cs.my_champion (numeric LCU championId)
// resolved via resolveChampNames (re-exported from
// cc_conditional_pressure.js). Mode comes from cs.queue_id.
//
// Discipline: pure ESM, ASCII only, sig-dedup gate on the render, no DOM
// writes outside renderDsRelscore(). Mirrors the ds_knobs.js /
// cooldown_watch.js fetch discipline.

import { resolveChampNames } from './cc_conditional_pressure.js';

const _DSR_CACHE = Object.create(null);     // cacheKey -> response JSON
const _DSR_INFLIGHT = Object.create(null);
const _DSR_TS = Object.create(null);
const _DSR_SIG = Object.create(null);
const _DSR_TTL_MS = 5 * 60 * 1000;          // matches backend TTL

// queue_id -> DS mode (mirrors ds_knobs.js _DSK_MODE_MAP).
const _DSR_MODE_MAP = {
  450: "ARAM", 920: "ARAM", 2400: "ARAM",
  1750: "ARENA", 1700: "ARENA", 1710: "ARENA",
  400: "SR", 420: "SR", 430: "SR", 440: "SR",
  830: "SR", 840: "SR", 850: "SR",
};

const _DSR_LEVEL = 11;

function _modeForQueue(queueId) {
  return _DSR_MODE_MAP[queueId | 0] || "SR";
}

function _cacheKey(champ, mode, items, level) {
  return [
    champ,
    mode,
    (items || []).slice().sort().join(","),
    level,
  ].join("|");
}

function _buildUrl(champ, mode, items, level) {
  const p = new URLSearchParams({ champion: champ, mode, level: String(level) });
  if ((items || []).length) p.set("items", items.join(","));
  return "/api/ds-relscore?" + p.toString();
}

export function fetchDsRelscore(champ, mode, items, level, onLand) {
  if (!champ) return;
  const key = _cacheKey(champ, mode, items, level);
  const fresh = _DSR_CACHE[key] && _DSR_TS[key]
                && (Date.now() - _DSR_TS[key]) < _DSR_TTL_MS;
  if (fresh || _DSR_INFLIGHT[key]) return;
  _DSR_INFLIGHT[key] = true;
  fetch(_buildUrl(champ, mode, items, level), { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      _DSR_INFLIGHT[key] = false;
      if (data) {
        _DSR_CACHE[key] = data;
        _DSR_TS[key] = Date.now();
        if (typeof onLand === "function") onLand();
      }
    })
    .catch(() => { _DSR_INFLIGHT[key] = false; });
}

export function getCachedDsRelscore(champ, mode, items, level) {
  return _DSR_CACHE[_cacheKey(champ, mode, items, level)] || null;
}

export function getDsRelscoreCacheCount() {
  return Object.keys(_DSR_CACHE).length;
}

function _signature(payload) {
  if (!payload || !payload.ok) {
    return payload && payload.reason ? `_${payload.reason}` : "_empty";
  }
  const rows = Array.isArray(payload.rows) ? payload.rows : [];
  return rows
    .map((r) => `${r.item_id}:${Math.round(+r.score_pct || 0)}`)
    .join("|") || "_norows";
}

// HTML-escape backend item names / champ slug before innerHTML
// interpolation (defense-in-depth at the render boundary).
function _esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function _goldLabel(g) {
  const n = +g || 0;
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
}

function _clampPct(p) {
  const n = +p || 0;
  if (n < 0) return 0;
  if (n > 100) return 100;
  return n;
}

function _rowsHtml(payload) {
  const rows = Array.isArray(payload.rows) ? payload.rows : [];
  if (!rows.length) {
    return `<div class="dsr-empty">no items rank for this build</div>`;
  }
  return rows.map((r) => {
    const pct = _clampPct(r.score_pct);
    const label = pct.toFixed(0);
    return (
      `<div class="dsr-row">`
      + `<span class="dsr-item">${_esc(r.name || r.item_id || "")}</span>`
      + `<span class="dsr-bar"><span class="dsr-bar-fill" style="width:${pct}%"></span></span>`
      + `<span class="dsr-pct">${label}</span>`
      + `<span class="dsr-gold">${_goldLabel(r.gold)}g</span>`
      + `</div>`
    );
  }).join("");
}

function _shellHtml(champ) {
  return (
    `<div class="dsr-head">`
    + `<span class="dsr-head-title">Relative item power</span>`
    + `<span class="dsr-head-sub">${_esc(champ)} DPS delta vs best</span>`
    + `</div>`
    + `<div class="dsr-rows" id="dsr-rows"></div>`
  );
}

// Render the relative-score bar panel into the provided element from
// champ-select state cs. Reads cs.my_champion (numeric) + cs.queue_id.
// Hidden until a champion is locked.
export function renderDsRelscore(blockEl, cs) {
  if (!blockEl) return;
  cs = cs || {};
  const myId = (cs.my_champion | 0);
  if (myId <= 0) {
    blockEl.hidden = true;
    return;
  }
  const names = resolveChampNames([myId]);
  const champ = names.length ? names[0] : "";
  if (!champ) {
    // CHAMPS index not yet loaded - keep hidden, resolves next tick.
    blockEl.hidden = true;
    return;
  }
  const mode = _modeForQueue(cs.queue_id);
  const items = (cs.my_owned_items || cs.owned_items || [])
    .map((x) => String(x)).filter(Boolean);

  // Kick a fetch; re-render on land.
  fetchDsRelscore(champ, mode, items, _DSR_LEVEL,
    () => renderDsRelscore(blockEl, cs));
  const payload = getCachedDsRelscore(champ, mode, items, _DSR_LEVEL);

  // Build the static shell once (or when the champion changes); rewiring
  // the header every tick would thrash the DOM.
  const wantChamp = blockEl.getAttribute("data-dsr-champ");
  if (wantChamp !== champ) {
    blockEl.innerHTML = _shellHtml(champ);
    blockEl.setAttribute("data-dsr-champ", champ);
    _DSR_SIG[blockEl.id || "_dsr_default"] = null;  // force first rows paint
  }
  blockEl.hidden = false;

  // Sig-dedup the rows paint (the shell is static between champ changes).
  const sigKey = blockEl.id || "_dsr_default";
  const sig = _signature(payload);
  if (_DSR_SIG[sigKey] === sig) return;
  _DSR_SIG[sigKey] = sig;

  const rowsEl = blockEl.querySelector("#dsr-rows");
  if (rowsEl) {
    rowsEl.innerHTML = payload && payload.ok ? _rowsHtml(payload)
      : `<div class="dsr-empty">resolving relative power...</div>`;
  }
}

// Reset helper for tests (clears in-memory cache + sig stamps).
export function _resetDsRelscore() {
  for (const k of Object.keys(_DSR_CACHE))    delete _DSR_CACHE[k];
  for (const k of Object.keys(_DSR_INFLIGHT)) delete _DSR_INFLIGHT[k];
  for (const k of Object.keys(_DSR_TS))       delete _DSR_TS[k];
  for (const k of Object.keys(_DSR_SIG))      delete _DSR_SIG[k];
}

export const __test = {
  _cacheKey,
  _signature,
  _modeForQueue,
  _goldLabel,
  _clampPct,
  _buildUrl,
  _DSR_TTL_MS,
};
