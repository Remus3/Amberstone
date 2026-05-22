// CC-conditional pressure balance chip (item 144 - 5th overall consumer
// of the cc_conditional ecosystem; FIRST dashboard UI consumer).
//
// cc_conditional ecosystem to date (engine math chain shipped at
// ENGINE 1.38.0 + 1.39.0; item 144 ships parallel dashboard UI +
// coach prompt as the 4th + 5th overall consumers):
//   1. cc_pressure   (DIRECT  / ENGINE 1.38.0 / item 142 Slice A)
//   2. compute_ehp   (INDIRECT / ENGINE 1.39.0 / item 143 Slice A)
//   3. compute_hybrid (INDIRECT / ENGINE 1.39.0 / item 143 Slice B)
//   4. coach prompt  (Slice A this run, parallel slice)
//   5. dashboard UI  (THIS module + dashboard/routes_cc_conditional_pressure.py)
//
// Backend wire:
//   GET /api/cc-conditional-pressure?ally=<champ,champ,...>
//                                    &enemy=<champ,champ,...>
//                                    [&mode=ARAM]
//   Response: {
//     ok, mode,
//     ally_conditional_cc_s, enemy_conditional_cc_s,
//     ratio, tier,
//     ally_total_cc_seconds, enemy_total_cc_seconds,
//     elapsed_ms, cached
//   }
//
// Champion ids in the query string are canonical DDragon slugs
// (e.g. "Brand", "Mordekaiser", "TwistedFate") - the cc_conditional
// registry is keyed on these. The frontend resolves numeric LCU
// championId via CHAMPS.byId before fetching.
//
// Discipline: pure ESM, ASCII only, sig-dedup gate, no DOM writes
// outside renderCcConditionalPressure(). Mirrors the item 140
// cc_blended_ehp_threat.js pattern exactly so the two chips stay
// visually + behaviourally coherent.

import { CHAMPS } from '../lib/items_index.js';

const _CCP_CACHE = Object.create(null);     // cacheKey -> response JSON
const _CCP_INFLIGHT = Object.create(null);
const _CCP_TS = Object.create(null);
const _CCP_SIG = Object.create(null);
const _CCP_TTL_MS = 5 * 60 * 1000;          // matches backend TTL

function _cacheKey(allyNames, enemyNames, mode) {
  const a = (allyNames || []).slice().sort().join(",");
  const e = (enemyNames || []).slice().sort().join(",");
  const m = (mode || "ARAM").toUpperCase();
  return `${a}|${e}|${m}`;
}

// Convert numeric LCU champion ids into canonical DDragon slugs via the
// CHAMPS.byId map. Unknown / zero ids drop silently (mirrors backend
// fail-soft contract). Returns a fresh array - never mutates input.
export function resolveChampNames(numericIds) {
  if (!Array.isArray(numericIds) || !numericIds.length) return [];
  const byId = (CHAMPS && CHAMPS.byId) ? CHAMPS.byId : {};
  const out = [];
  for (const raw of numericIds) {
    const id = raw | 0;
    if (id <= 0) continue;
    const slug = byId[String(id)];
    if (slug) out.push(String(slug));
  }
  return out;
}

export function fetchCcConditionalPressure(allyNames, enemyNames, mode, onLand) {
  // Need at least one champ on EACH side - otherwise the comparison
  // is meaningless. Mirrors the cc_blended_ehp_threat gate.
  if (!Array.isArray(allyNames) || allyNames.length < 1) return;
  if (!Array.isArray(enemyNames) || enemyNames.length < 1) return;
  const safeMode = (mode || "ARAM").toUpperCase();
  const key = _cacheKey(allyNames, enemyNames, safeMode);
  const fresh = _CCP_CACHE[key] && _CCP_TS[key]
                && (Date.now() - _CCP_TS[key]) < _CCP_TTL_MS;
  if (fresh || _CCP_INFLIGHT[key]) return;
  _CCP_INFLIGHT[key] = true;
  const qs = new URLSearchParams({
    ally:  allyNames.join(","),
    enemy: enemyNames.join(","),
    mode:  safeMode,
  });
  fetch("/api/cc-conditional-pressure?" + qs.toString(), { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      _CCP_INFLIGHT[key] = false;
      if (data) {
        _CCP_CACHE[key] = data;
        _CCP_TS[key] = Date.now();
        if (typeof onLand === "function") onLand();
      }
    })
    .catch(() => { _CCP_INFLIGHT[key] = false; });
}

export function getCachedCcConditionalPressure(allyNames, enemyNames, mode) {
  const safeMode = (mode || "ARAM").toUpperCase();
  return _CCP_CACHE[_cacheKey(allyNames, enemyNames, safeMode)] || null;
}

export function getCcConditionalPressureCacheCount() {
  return Object.keys(_CCP_CACHE).length;
}

function _signature(payload) {
  if (!payload || !payload.ok) {
    return payload && payload.reason ? `_${payload.reason}` : "_empty";
  }
  return [
    payload.tier || "warn",
    (+payload.ally_conditional_cc_s || 0).toFixed(1),
    (+payload.enemy_conditional_cc_s || 0).toFixed(1),
    (+payload.ally_total_cc_seconds || 0).toFixed(1),
    (+payload.enemy_total_cc_seconds || 0).toFixed(1),
    (+payload.ratio || 0).toFixed(2),
  ].join(":");
}

function _tierLabel(tier) {
  if (tier === "good") return "FAVORABLE";
  if (tier === "bad")  return "AT RISK";
  return "EVEN";
}

// Render the CC-conditional pressure chip into the provided element.
// payload is the backend response (may be null on cold-load).
export function renderCcConditionalPressure(blockEl, payload) {
  if (!blockEl) return;
  const sigKey = blockEl.id || "_ccp_default";
  const sig = _signature(payload);
  if (_CCP_SIG[sigKey] === sig) return;
  _CCP_SIG[sigKey] = sig;

  if (!payload) {
    // Cold load - keep hidden until the response lands.
    blockEl.hidden = true;
    return;
  }

  if (!payload.ok) {
    // no_champions or other backend non-ok response. Hide the chip.
    blockEl.hidden = true;
    return;
  }

  const tier = payload.tier || "warn";
  blockEl.hidden = false;
  blockEl.dataset.ccCondTier = tier;

  const allyAvg = (+payload.ally_conditional_cc_s || 0).toFixed(1);
  const enemyAvg = (+payload.enemy_conditional_cc_s || 0).toFixed(1);
  const ratio = (+payload.ratio || 0).toFixed(2);
  const tierLabel = _tierLabel(tier);

  blockEl.innerHTML = (
    `<div class="cc-conditional-pressure-head">`
    + `<span class="cc-conditional-pressure-tier">${tierLabel}</span>`
    + `<span>Conditional CC threat balance</span>`
    + `</div>`
    + `<div class="cc-conditional-pressure-row">`
    + `<span class="cc-conditional-pressure-row-label">Ally conditional CC avg</span>`
    + `<span class="cc-conditional-pressure-row-value">${allyAvg}s</span>`
    + `</div>`
    + `<div class="cc-conditional-pressure-row">`
    + `<span class="cc-conditional-pressure-row-label">Enemy conditional CC avg</span>`
    + `<span class="cc-conditional-pressure-row-value">${enemyAvg}s</span>`
    + `</div>`
    + `<div class="cc-conditional-pressure-ratio">`
    + `<span class="cc-conditional-pressure-row-label">Ratio (ally / enemy)</span>`
    + `<span class="cc-conditional-pressure-ratio-value">${ratio}x</span>`
    + `</div>`
  );
}

// Reset helper for tests (clears in-memory cache + sig stamps).
export function _resetCcConditionalPressure() {
  for (const k of Object.keys(_CCP_CACHE))    delete _CCP_CACHE[k];
  for (const k of Object.keys(_CCP_INFLIGHT)) delete _CCP_INFLIGHT[k];
  for (const k of Object.keys(_CCP_TS))       delete _CCP_TS[k];
  for (const k of Object.keys(_CCP_SIG))      delete _CCP_SIG[k];
}

export const __test = {
  _cacheKey,
  _signature,
  _tierLabel,
  _CCP_TTL_MS,
};
