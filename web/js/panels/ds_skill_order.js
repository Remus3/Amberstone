// DS-Skill-Order champion panel. Renders the LOCKED champion's ability MAX
// ORDER (e.g. "Q > E > W") plus the ult level-ups (6/11/16) as a small card -
// a one-glance read on how the operator's own pick maxes its abilities. Pure
// presentation over data the DS snapshot already ships; no compute lives here.
//
// Backend wire:
//   GET /api/ds-skill-order?champion=<slug-or-numeric>&mode=SR
//   Response: {
//     ok, champion, mode,
//     skill_order:[<18 strings>], max_order:["Q","E","W"],
//     max_order_str:"Q > E > W", ult_levels:[6,11,16],
//     elapsed_ms, cached
//   }
//   Failure: ok=false (reason "no_skill_order" for unknown champ) -> panel hides.
//
// Priority is rendered with the ASCII '>' character - NO unicode arrows
// (repo ASCII hard rule). The locked champion is read from the champ-select
// state (cs.my_champion, the operator's own numeric LCU id) and resolved to a
// DDragon slug via resolveChampNames (re-exported from
// cc_conditional_pressure.js).
//
// Discipline: pure ESM, ASCII only, sig-dedup gate, inflight guard, no DOM
// writes outside renderDsSkillOrder(). Module shape mirrors ds_profile.js
// (per-key cache + TTL, sig stamp). Fail-soft on null / empty / not-ok
// payloads.

import { resolveChampNames } from './cc_conditional_pressure.js';

const _DSSO_CACHE = Object.create(null);     // cacheKey -> response JSON
const _DSSO_INFLIGHT = Object.create(null);
const _DSSO_TS = Object.create(null);
const _DSSO_SIG = Object.create(null);       // mount-id -> last-rendered sig
const _DSSO_TTL_MS = 5 * 60 * 1000;          // matches backend TTL

function _cacheKey(champion, mode) {
  return `${champion || ""}|${(mode || "SR").toUpperCase()}`;
}

// Fetch + memoize. Returns nothing - caller re-renders on next tick when the
// cache lands. ``onLand`` is an optional re-render callback.
export function fetchDsSkillOrder(champion, mode, onLand) {
  if (!champion) return;
  const key = _cacheKey(champion, mode);
  const fresh = _DSSO_CACHE[key] && _DSSO_TS[key]
                && (Date.now() - _DSSO_TS[key]) < _DSSO_TTL_MS;
  if (fresh || _DSSO_INFLIGHT[key]) return;
  _DSSO_INFLIGHT[key] = true;
  const qs = new URLSearchParams({
    champion: String(champion),
    mode: String(mode || "SR").toUpperCase(),
  });
  fetch("/api/ds-skill-order?" + qs.toString(), { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      _DSSO_INFLIGHT[key] = false;
      if (data) {
        _DSSO_CACHE[key] = data;
        _DSSO_TS[key] = Date.now();
        if (typeof onLand === "function") onLand();
      }
    })
    .catch(() => { _DSSO_INFLIGHT[key] = false; });
}

export function getCachedDsSkillOrder(champion, mode) {
  return _DSSO_CACHE[_cacheKey(champion, mode)] || null;
}

export function getDsSkillOrderCacheCount() {
  return Object.keys(_DSSO_CACHE).length;
}

// Pure-function signature builder for the sig-dedup gate. Anything that changes
// the rendered card (champion, max order, ult levels) changes the sig so an
// unchanged payload skips the innerHTML rebuild.
function _signature(payload) {
  if (!payload || !payload.ok) {
    return payload && payload.reason ? `_${payload.reason}` : "_empty";
  }
  const mo = Array.isArray(payload.max_order) ? payload.max_order.join(">") : "";
  const ult = Array.isArray(payload.ult_levels)
    ? payload.ult_levels.join("/") : "";
  return `${payload.champion || ""}|${mo}|${ult}` || "_noorder";
}

// HTML-escape the small free-form strings (champion display name, max-order
// string) the backend passes through. Mirrors the defensive escaping the
// sibling champ-select panels use before innerHTML.
function _esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// Render the skill-order card into the provided element. payload is the backend
// response (may be null on cold-load). Hides on null / not-ok / empty max_order.
export function renderDsSkillOrder(blockEl, payload) {
  if (!blockEl) return;
  const sigKey = blockEl.id || "_dsso_default";
  const sig = _signature(payload);
  if (_DSSO_SIG[sigKey] === sig) return;
  _DSSO_SIG[sigKey] = sig;

  const maxOrder = payload && Array.isArray(payload.max_order)
    ? payload.max_order : null;
  if (!payload || !payload.ok || !maxOrder || maxOrder.length === 0) {
    blockEl.hidden = true;
    return;
  }
  blockEl.hidden = false;

  const champ = _esc(payload.champion || "");
  const maxStr = _esc(payload.max_order_str || maxOrder.join(" > "));
  const ult = Array.isArray(payload.ult_levels)
    ? payload.ult_levels.join("/") : "";

  blockEl.innerHTML = (
    `<div class="dsso-head">`
    + `<span class="dsso-head-title">Skill order</span>`
    + `<span class="dsso-head-sub">${champ}</span>`
    + `</div>`
    + `<div class="dsso-max">Max: ${maxStr}</div>`
    + `<div class="dsso-ult">Ult: ${_esc(ult)}</div>`
  );
}

// Champ-select entry point. Mirrors renderDsProfileForChampSelect(cs): read the
// LOCKED champion from the champ-select state, resolve its slug, fetch the SR
// skill order, render the cached payload. ``blockId`` defaults to the
// Suggestions-card mount but is overridable for tests.
export function renderDsSkillOrderForChampSelect(cs, blockId) {
  const block = document.getElementById(blockId || "csv-sugg-ds-skill-order");
  if (!block) return;
  const myId = (cs && (cs.my_champion | 0)) || 0;
  if (myId <= 0) {
    block.hidden = true;
    return;
  }
  const names = resolveChampNames([myId]);
  if (!names.length) {
    // CHAMPS index not yet loaded - keep hidden, resolves next tick.
    block.hidden = true;
    return;
  }
  const champ = names[0];
  const mode = "SR";
  fetchDsSkillOrder(champ, mode, _dssoOnLand);
  const payload = getCachedDsSkillOrder(champ, mode);
  renderDsSkillOrder(block, payload);
}

// Re-render hook fired when a fetch lands. The orchestrator wires the real
// champ-select scheduler in champ_select.js; this module-local default is a
// no-op so the panel is safe to import standalone (tests + cold mount).
let _dssoScheduleRender = null;
function _dssoOnLand() {
  if (typeof _dssoScheduleRender === "function") _dssoScheduleRender();
}
export function setDsSkillOrderScheduler(fn) {
  _dssoScheduleRender = (typeof fn === "function") ? fn : null;
}

// Reset helper for tests (clears in-memory cache + sig stamps).
export function _resetDsSkillOrder() {
  for (const k of Object.keys(_DSSO_CACHE))    delete _DSSO_CACHE[k];
  for (const k of Object.keys(_DSSO_INFLIGHT)) delete _DSSO_INFLIGHT[k];
  for (const k of Object.keys(_DSSO_TS))       delete _DSSO_TS[k];
  for (const k of Object.keys(_DSSO_SIG))      delete _DSSO_SIG[k];
}

export const __test = {
  _cacheKey,
  _signature,
  _esc,
  _DSSO_TTL_MS,
};
