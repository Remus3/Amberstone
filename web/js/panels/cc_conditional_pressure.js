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

// item 213 (2026-05-28): plain-language one-liner the operator can act
// on. Built from the team CC-chain totals (seconds of crowd control one
// team can land on a single target). enemyChain / allyChain are the
// load-bearing numbers; conditional = "if the setup condition is met".
function _conditionalVerdict(allyChain, enemyChain) {
  const a = +allyChain || 0;
  const e = +enemyChain || 0;
  if (e <= 0.05 && a <= 0.05) {
    return "Neither team has conditional CC chains to set up.";
  }
  if (e > a + 0.3) {
    return `Enemy out-chains you ${e.toFixed(1)}s vs ${a.toFixed(1)}s of `
         + `conditional CC - consider Cleanse / QSS and do not group tight.`;
  }
  if (a > e + 0.3) {
    return `You out-chain them ${a.toFixed(1)}s vs ${e.toFixed(1)}s - `
         + `set up your conditional CC to lock a target in fights.`;
  }
  return `Even conditional CC: ${a.toFixed(1)}s you vs ${e.toFixed(1)}s enemy.`;
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

  // item 213: the CONDITIONAL chain totals are the actionable numbers -
  // "how many seconds of conditional CC can land on one target if the
  // setup condition is met". Prefer the per-team chain seconds; fall
  // back to the legacy per-champ avg fields if the route omits them.
  const allyChain = (payload.ally_total_cc_seconds != null)
    ? +payload.ally_total_cc_seconds
    : +payload.ally_conditional_cc_s || 0;
  const enemyChain = (payload.enemy_total_cc_seconds != null)
    ? +payload.enemy_total_cc_seconds
    : +payload.enemy_conditional_cc_s || 0;
  const tierLabel = _tierLabel(tier);
  const verdict = _conditionalVerdict(allyChain, enemyChain);

  blockEl.innerHTML = (
    `<div class="cc-conditional-pressure-head">`
    + `<span class="cc-conditional-pressure-tier">${tierLabel}</span>`
    + `<span>Conditional CC (if setup lands)</span>`
    + `</div>`
    + `<div class="cc-conditional-pressure-row">`
    + `<span class="cc-conditional-pressure-row-label">Enemy can chain on one target</span>`
    + `<span class="cc-conditional-pressure-row-value">${enemyChain.toFixed(1)}s</span>`
    + `</div>`
    + `<div class="cc-conditional-pressure-row">`
    + `<span class="cc-conditional-pressure-row-label">You can chain on one target</span>`
    + `<span class="cc-conditional-pressure-row-value">${allyChain.toFixed(1)}s</span>`
    + `</div>`
    + `<div class="cc-conditional-pressure-verdict">${verdict}</div>`
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
