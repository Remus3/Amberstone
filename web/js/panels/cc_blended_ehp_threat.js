// CC-blended EHP threat balance chip (item 139 carry (a)).
//
// FIRST DASHBOARD UI CONSUMER of cc_blended_ehp. Surfaces the dual-team
// CC-blended EHP balance shipped by:
//   - item 137 (engine math, compute_ehp)
//   - item 138 Slice A (coach prompt, cc_blended_ehp_impact_line)
//   - item 139 Slice A (DS scorer, compute_hybrid)
//
// Backend wire:
//   GET /api/cc-blended-ehp-threat?ally=<champ,champ,...>
//                                  &enemy=<champ,champ,...>
//                                  [&mode=ARAM]
//   Response: {
//     ok, mode,
//     ally_avg_cc_blended_ehp, enemy_avg_cc_blended_ehp,
//     ratio, tier,
//     ally_total_cc_seconds, enemy_total_cc_seconds,
//     elapsed_ms, cached
//   }
//
// Champion ids in the query string are canonical DDragon slugs
// (e.g. "Annie", "Galio", "MonkeyKing") - the cc_pressure registry
// is keyed on these. The frontend resolves numeric LCU championId
// via CHAMPS.byId before fetching.
//
// Discipline: pure ESM, ASCII only, sig-dedup gate, no DOM writes
// outside renderCcBlendedEhpThreat().

import { CHAMPS } from '../lib/items_index.js';

const _CC_CACHE = Object.create(null);     // cacheKey -> response JSON
const _CC_INFLIGHT = Object.create(null);
const _CC_TS = Object.create(null);
const _CC_SIG = Object.create(null);
const _CC_TTL_MS = 5 * 60 * 1000;          // matches backend TTL

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

export function fetchCcBlendedEhpThreat(allyNames, enemyNames, mode, onLand) {
  // Need at least one champ on EACH side - otherwise the comparison
  // is meaningless (the backend returns ok=false reason=no_champions
  // when both sides resolve to zero, which we render as hidden).
  if (!Array.isArray(allyNames) || allyNames.length < 1) return;
  if (!Array.isArray(enemyNames) || enemyNames.length < 1) return;
  const safeMode = (mode || "ARAM").toUpperCase();
  const key = _cacheKey(allyNames, enemyNames, safeMode);
  const fresh = _CC_CACHE[key] && _CC_TS[key]
                && (Date.now() - _CC_TS[key]) < _CC_TTL_MS;
  if (fresh || _CC_INFLIGHT[key]) return;
  _CC_INFLIGHT[key] = true;
  const qs = new URLSearchParams({
    ally:  allyNames.join(","),
    enemy: enemyNames.join(","),
    mode:  safeMode,
  });
  fetch("/api/cc-blended-ehp-threat?" + qs.toString(), { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      _CC_INFLIGHT[key] = false;
      if (data) {
        _CC_CACHE[key] = data;
        _CC_TS[key] = Date.now();
        if (typeof onLand === "function") onLand();
      }
    })
    .catch(() => { _CC_INFLIGHT[key] = false; });
}

export function getCachedCcBlendedEhpThreat(allyNames, enemyNames, mode) {
  const safeMode = (mode || "ARAM").toUpperCase();
  return _CC_CACHE[_cacheKey(allyNames, enemyNames, safeMode)] || null;
}

export function getCcBlendedEhpThreatCacheCount() {
  return Object.keys(_CC_CACHE).length;
}

function _signature(payload) {
  if (!payload || !payload.ok) {
    return payload && payload.reason ? `_${payload.reason}` : "_empty";
  }
  return [
    payload.tier || "warn",
    Math.round(+payload.ally_avg_cc_blended_ehp || 0),
    Math.round(+payload.enemy_avg_cc_blended_ehp || 0),
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

// item 213 (2026-05-28): plain-language verdict for the unconditional
// CC card. enemyCc / allyCc are seconds of crowd control a team can
// chain onto ONE target. A teamfight is roughly 5-6s, so "X seconds
// locked" is framed as a share of a fight the operator loses control.
const _CC_FIGHT_S = 6;
function _ccVerdict(allyCc, enemyCc) {
  const a = +allyCc || 0;
  const e = +enemyCc || 0;
  if (e <= 0.05 && a <= 0.05) {
    return "Neither team has meaningful hard CC to chain.";
  }
  const lossPct = Math.min(99, Math.round((e / _CC_FIGHT_S) * 100));
  if (e > a + 0.5) {
    return `Enemy out-chains you ${e.toFixed(1)}s vs ${a.toFixed(1)}s - you `
         + `lose ~${lossPct}% of a fight locked down. Consider Cleanse / QSS `
         + `and spread out.`;
  }
  if (a > e + 0.5) {
    return `You out-chain them ${a.toFixed(1)}s vs ${e.toFixed(1)}s - force `
         + `fights and chain your CC to delete a target.`;
  }
  return `Even CC: ${a.toFixed(1)}s you vs ${e.toFixed(1)}s enemy - `
       + `whoever lands first CC wins the trade.`;
}

// Render the CC-blended EHP threat chip into the provided element.
// payload is the backend response (may be null on cold-load).
export function renderCcBlendedEhpThreat(blockEl, payload) {
  if (!blockEl) return;
  const sigKey = blockEl.id || "_cc_default";
  const sig = _signature(payload);
  if (_CC_SIG[sigKey] === sig) return;
  _CC_SIG[sigKey] = sig;

  if (!payload) {
    // Cold load - keep hidden until the response lands.
    blockEl.hidden = true;
    return;
  }

  if (!payload.ok) {
    // no_champions or other backend non-ok response. Hide the chip
    // (it's not informative without data).
    blockEl.hidden = true;
    return;
  }

  const tier = payload.tier || "warn";
  blockEl.hidden = false;
  blockEl.dataset.ccTier = tier;

  // item 213: lead with the CC-CHAIN seconds (the actionable number:
  // "how long one target can be locked down") not the bare cc-blended
  // EHP figure. EHP is kept as a secondary "effective HP under that CC
  // pressure" caption so the tier still has its underlying math, but it
  // no longer headlines the card.
  const allyAvg = Math.round(+payload.ally_avg_cc_blended_ehp || 0);
  const enemyAvg = Math.round(+payload.enemy_avg_cc_blended_ehp || 0);
  const allyCc = (+payload.ally_total_cc_seconds || 0).toFixed(1);
  const enemyCc = (+payload.enemy_total_cc_seconds || 0).toFixed(1);
  const tierLabel = _tierLabel(tier);
  const verdict = _ccVerdict(allyCc, enemyCc);

  blockEl.innerHTML = (
    `<div class="cc-blended-ehp-threat-head">`
    + `<span class="cc-blended-ehp-threat-tier">${tierLabel}</span>`
    + `<span>CC chain on one target</span>`
    + `</div>`
    + `<div class="cc-blended-ehp-threat-row">`
    + `<span class="cc-blended-ehp-threat-row-label">Enemy can chain on you</span>`
    + `<span>`
    + `<span class="cc-blended-ehp-threat-row-value">${enemyCc}s</span> `
    + `<span class="cc-blended-ehp-threat-row-cc"`
    + ` title="Your team's effective HP under that CC pressure">`
    + `(your EHP ${allyAvg})</span>`
    + `</span>`
    + `</div>`
    + `<div class="cc-blended-ehp-threat-row">`
    + `<span class="cc-blended-ehp-threat-row-label">You can chain on them</span>`
    + `<span>`
    + `<span class="cc-blended-ehp-threat-row-value">${allyCc}s</span> `
    + `<span class="cc-blended-ehp-threat-row-cc"`
    + ` title="Enemy team's effective HP under your CC pressure">`
    + `(enemy EHP ${enemyAvg})</span>`
    + `</span>`
    + `</div>`
    + `<div class="cc-blended-ehp-threat-verdict">${verdict}</div>`
  );
}

// Reset helper for tests (clears in-memory cache + sig stamps).
export function _resetCcBlendedEhpThreat() {
  for (const k of Object.keys(_CC_CACHE))    delete _CC_CACHE[k];
  for (const k of Object.keys(_CC_INFLIGHT)) delete _CC_INFLIGHT[k];
  for (const k of Object.keys(_CC_TS))       delete _CC_TS[k];
  for (const k of Object.keys(_CC_SIG))      delete _CC_SIG[k];
}

export const __test = {
  _cacheKey,
  _signature,
  _tierLabel,
  _CC_TTL_MS,
};
