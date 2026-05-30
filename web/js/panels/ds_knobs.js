// DS engine-knobs control panel (competitor lift #1,
// docs/COMPETITOR_LIFT_2026-05-30.md "Lift 1", lolsolved.gg engine-knobs
// UX). A control strip above a compact ranked-rows list for the LOCKED
// champion: the operator overrides enemy armor / enemy MR / gold cap and
// the DS DPS ranking re-ranks for that chosen fight model, instead of
// accepting the single auto-resolved enemy curve.
//
// Backend wire:
//   GET /api/ds-knobs?champion=<champ>&mode=SR[&items=][&target_armor=]
//       [&target_mr=][&budget=][&level=11]
//   Response: {
//     ok, champion, knobs:{target_armor, target_mr, budget, level, mode,
//                          armor_source, mr_source},
//     rows:[{item_id, name, delta_dps, new_dps, gold, scorer}],
//     count, elapsed_ms, cached
//   }
//
// SCOPED v1: ONLY armor / MR / gold-cap knobs (each maps to an existing
// rank_items arg). The lolsolved fight-length-reweight knob is DEFERRED
// (needs a new engine arg) and is NOT surfaced here.
//
// The locked champion comes from cs.my_champion (numeric LCU championId)
// resolved via resolveChampNames (re-exported from
// cc_conditional_pressure.js). Mode comes from cs.queue_id.
//
// Discipline: pure ESM, ASCII only, sig-dedup gate on the rows render, no
// DOM writes outside renderDsKnobs(). Knob-change re-fetches are debounced.
// Mirrors the cooldown_watch.js / cc_conditional_pressure.js patterns.

import { resolveChampNames } from './cc_conditional_pressure.js';

const _DSK_CACHE = Object.create(null);     // cacheKey -> response JSON
const _DSK_INFLIGHT = Object.create(null);
const _DSK_TS = Object.create(null);
const _DSK_SIG = Object.create(null);
const _DSK_TTL_MS = 5 * 60 * 1000;          // matches backend TTL
const _DSK_DEBOUNCE_MS = 350;

// Per-champion operator knob state. Persists across re-renders so a state
// tick does not wipe a knob the operator just set. null => use auto / no-cap.
const _DSK_KNOBS = Object.create(null);     // champ -> {armor, mr, budget}

// queue_id -> DS mode (mirrors champ_select.js modeMap).
const _DSK_MODE_MAP = {
  450: "ARAM", 920: "ARAM", 2400: "ARAM",
  1750: "ARENA", 1700: "ARENA", 1710: "ARENA",
  400: "SR", 420: "SR", 430: "SR", 440: "SR",
  830: "SR", 840: "SR", 850: "SR",
};

const _DSK_LEVEL = 11;

let _dskDebounceTimer = null;
let _dskWired = false;        // control-strip listeners attached once per block

function _modeForQueue(queueId) {
  return _DSK_MODE_MAP[queueId | 0] || "SR";
}

function _knobsFor(champ) {
  if (!_DSK_KNOBS[champ]) {
    _DSK_KNOBS[champ] = { armor: null, mr: null, budget: null };
  }
  return _DSK_KNOBS[champ];
}

function _numOrNull(raw) {
  if (raw === null || raw === undefined) return null;
  const s = String(raw).trim();
  if (!s) return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

function _cacheKey(champ, mode, items, knobs, level) {
  return [
    champ,
    mode,
    (items || []).slice().sort().join(","),
    knobs.armor === null ? "" : knobs.armor,
    knobs.mr === null ? "" : knobs.mr,
    knobs.budget === null ? "" : knobs.budget,
    level,
  ].join("|");
}

function _buildUrl(champ, mode, items, knobs, level) {
  const p = new URLSearchParams({ champion: champ, mode, level: String(level) });
  if ((items || []).length) p.set("items", items.join(","));
  if (knobs.armor !== null) p.set("target_armor", String(knobs.armor));
  if (knobs.mr !== null) p.set("target_mr", String(knobs.mr));
  if (knobs.budget !== null) p.set("budget", String(knobs.budget));
  return "/api/ds-knobs?" + p.toString();
}

export function fetchDsKnobs(champ, mode, items, knobs, level, onLand) {
  if (!champ) return;
  const key = _cacheKey(champ, mode, items, knobs, level);
  const fresh = _DSK_CACHE[key] && _DSK_TS[key]
                && (Date.now() - _DSK_TS[key]) < _DSK_TTL_MS;
  if (fresh || _DSK_INFLIGHT[key]) return;
  _DSK_INFLIGHT[key] = true;
  fetch(_buildUrl(champ, mode, items, knobs, level), { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      _DSK_INFLIGHT[key] = false;
      if (data) {
        _DSK_CACHE[key] = data;
        _DSK_TS[key] = Date.now();
        if (typeof onLand === "function") onLand();
      }
    })
    .catch(() => { _DSK_INFLIGHT[key] = false; });
}

export function getCachedDsKnobs(champ, mode, items, knobs, level) {
  return _DSK_CACHE[_cacheKey(champ, mode, items, knobs, level)] || null;
}

export function getDsKnobsCacheCount() {
  return Object.keys(_DSK_CACHE).length;
}

function _signature(payload) {
  if (!payload || !payload.ok) {
    return payload && payload.reason ? `_${payload.reason}` : "_empty";
  }
  const k = payload.knobs || {};
  const rows = Array.isArray(payload.rows) ? payload.rows : [];
  const head = `${k.target_armor || 0}/${k.target_mr || 0}/${k.budget || 0}`;
  return head + "#" + (rows
    .map((r) => `${r.item_id}:${Math.round(+r.delta_dps || 0)}`)
    .join("|") || "_norows");
}

function _goldLabel(g) {
  const n = +g || 0;
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
}

function _rowsHtml(payload) {
  const rows = Array.isArray(payload.rows) ? payload.rows : [];
  if (!rows.length) {
    return `<div class="dsk-empty">no items rank under this fight model</div>`;
  }
  return rows.map((r) => (
    `<div class="dsk-row">`
    + `<span class="dsk-item">${String(r.name || r.item_id || "")}</span>`
    + `<span class="dsk-delta">+${Math.round(+r.delta_dps || 0)}</span>`
    + `<span class="dsk-gold">${_goldLabel(r.gold)}g</span>`
    + `</div>`
  )).join("");
}

function _stripHtml(champ, knobs, resolved) {
  // Inputs show the operator override when set, else the resolved auto
  // value as a placeholder so the field reads as "auto: 80".
  const ra = resolved && resolved.target_armor != null ? resolved.target_armor : "";
  const rm = resolved && resolved.target_mr != null ? resolved.target_mr : "";
  const av = knobs.armor === null ? "" : knobs.armor;
  const mv = knobs.mr === null ? "" : knobs.mr;
  const bv = knobs.budget === null ? "" : knobs.budget;
  return (
    `<div class="dsk-head">`
    + `<span class="dsk-head-title">Fight model</span>`
    + `<span class="dsk-head-sub">re-rank ${String(champ)} for a chosen target</span>`
    + `</div>`
    + `<div class="dsk-strip">`
    + `<label class="dsk-knob"><span>Enemy armor</span>`
    + `<input type="number" id="dsk-armor" min="0" max="500" step="5"`
    + ` value="${av}" placeholder="auto ${ra}"></label>`
    + `<label class="dsk-knob"><span>Enemy MR</span>`
    + `<input type="number" id="dsk-mr" min="0" max="500" step="5"`
    + ` value="${mv}" placeholder="auto ${rm}"></label>`
    + `<label class="dsk-knob"><span>Gold cap</span>`
    + `<input type="number" id="dsk-budget" min="0" max="20000" step="250"`
    + ` value="${bv}" placeholder="none"></label>`
    + `</div>`
    + `<div class="dsk-rows" id="dsk-rows"></div>`
  );
}

// Render the DS knobs panel into the provided element from champ-select
// state cs. Reads cs.my_champion (numeric) + cs.queue_id. Hidden until a
// champion is locked.
export function renderDsKnobs(blockEl, cs) {
  if (!blockEl) return;
  cs = cs || {};
  const myId = (cs.my_champion | 0);
  if (myId <= 0) {
    blockEl.hidden = true;
    _dskWired = false;
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
  const knobs = _knobsFor(champ);

  // Kick a fetch with the current knob state; re-render on land.
  fetchDsKnobs(champ, mode, items, knobs, _DSK_LEVEL,
    () => renderDsKnobs(blockEl, cs));
  const payload = getCachedDsKnobs(champ, mode, items, knobs, _DSK_LEVEL);

  // Build the control strip once (or when the champion changes); wiring
  // listeners every tick would stack handlers.
  const wantChamp = blockEl.getAttribute("data-dsk-champ");
  if (!_dskWired || wantChamp !== champ) {
    blockEl.hidden = false;
    const resolved = payload && payload.knobs ? payload.knobs : null;
    blockEl.innerHTML = _stripHtml(champ, knobs, resolved);
    blockEl.setAttribute("data-dsk-champ", champ);
    _wireStrip(blockEl, cs, champ);
    _dskWired = true;
    _DSK_SIG[blockEl.id || "_dsk_default"] = null;  // force first rows paint
  }
  blockEl.hidden = false;

  // Sig-dedup the rows paint only (the strip is static between champ
  // changes). Update auto placeholders if the resolved values arrived.
  const sigKey = blockEl.id || "_dsk_default";
  const sig = _signature(payload);
  if (_DSK_SIG[sigKey] === sig) return;
  _DSK_SIG[sigKey] = sig;

  const rowsEl = blockEl.querySelector("#dsk-rows");
  if (rowsEl) {
    rowsEl.innerHTML = payload && payload.ok ? _rowsHtml(payload)
      : `<div class="dsk-empty">resolving fight model...</div>`;
  }
  if (payload && payload.knobs) _refreshPlaceholders(blockEl, payload.knobs, knobs);
}

function _refreshPlaceholders(blockEl, resolved, knobs) {
  const a = blockEl.querySelector("#dsk-armor");
  const m = blockEl.querySelector("#dsk-mr");
  if (a && knobs.armor === null && resolved.target_armor != null) {
    a.placeholder = `auto ${resolved.target_armor}`;
  }
  if (m && knobs.mr === null && resolved.target_mr != null) {
    m.placeholder = `auto ${resolved.target_mr}`;
  }
}

function _wireStrip(blockEl, cs, champ) {
  const onChange = () => {
    const knobs = _knobsFor(champ);
    const a = blockEl.querySelector("#dsk-armor");
    const m = blockEl.querySelector("#dsk-mr");
    const b = blockEl.querySelector("#dsk-budget");
    knobs.armor = a ? _numOrNull(a.value) : null;
    knobs.mr = m ? _numOrNull(m.value) : null;
    knobs.budget = b ? _numOrNull(b.value) : null;
    if (_dskDebounceTimer) clearTimeout(_dskDebounceTimer);
    _dskDebounceTimer = setTimeout(() => {
      // Force a fresh rows paint after a knob change.
      _DSK_SIG[blockEl.id || "_dsk_default"] = null;
      renderDsKnobs(blockEl, cs);
    }, _DSK_DEBOUNCE_MS);
  };
  ["dsk-armor", "dsk-mr", "dsk-budget"].forEach((id) => {
    const el = blockEl.querySelector("#" + id);
    if (el) el.addEventListener("input", onChange);
  });
}

// Reset helper for tests (clears in-memory cache + knob state + sig stamps).
export function _resetDsKnobs() {
  for (const k of Object.keys(_DSK_CACHE))    delete _DSK_CACHE[k];
  for (const k of Object.keys(_DSK_INFLIGHT)) delete _DSK_INFLIGHT[k];
  for (const k of Object.keys(_DSK_TS))       delete _DSK_TS[k];
  for (const k of Object.keys(_DSK_SIG))      delete _DSK_SIG[k];
  for (const k of Object.keys(_DSK_KNOBS))    delete _DSK_KNOBS[k];
  _dskWired = false;
}

export const __test = {
  _cacheKey,
  _signature,
  _modeForQueue,
  _numOrNull,
  _goldLabel,
  _buildUrl,
  _DSK_TTL_MS,
};
