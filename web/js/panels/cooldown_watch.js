// Matchup cooldown-watch card (competitor lift #5,
// docs/COMPETITOR_LIFT_2026-05-30.md). Sibling of the cc-conditional-
// pressure chip - surfaces, per ENEMY champion, the single highest-threat
// hard-CC ability + its max-rank base cooldown ("watch their hook - 16s").
//
// Backend wire:
//   GET /api/cooldown-watch?enemy=<champ,champ,...>[&top_n=5]
//   Response: {
//     ok, cards:[{champion, spell_key, spell_name, cc_kind,
//                 cc_duration_s, cooldown_s, cooldown_by_rank,
//                 conditional, probability}], count, elapsed_ms, cached
//   }
//
// Champion ids in the query are canonical DDragon slugs; the frontend
// resolves numeric LCU championId via resolveChampNames (re-exported from
// cc_conditional_pressure.js) before fetching.
//
// Discipline: pure ESM, ASCII only, sig-dedup gate, no DOM writes outside
// renderCooldownWatch(). Mirrors the cc_conditional_pressure.js pattern.

const _CDW_CACHE = Object.create(null);     // cacheKey -> response JSON
const _CDW_INFLIGHT = Object.create(null);
const _CDW_TS = Object.create(null);
const _CDW_SIG = Object.create(null);
const _CDW_TTL_MS = 5 * 60 * 1000;          // matches backend TTL

function _cacheKey(enemyNames) {
  return (enemyNames || []).slice().sort().join(",");
}

export function fetchCooldownWatch(enemyNames, onLand) {
  if (!Array.isArray(enemyNames) || enemyNames.length < 1) return;
  const key = _cacheKey(enemyNames);
  const fresh = _CDW_CACHE[key] && _CDW_TS[key]
                && (Date.now() - _CDW_TS[key]) < _CDW_TTL_MS;
  if (fresh || _CDW_INFLIGHT[key]) return;
  _CDW_INFLIGHT[key] = true;
  const qs = new URLSearchParams({ enemy: enemyNames.join(",") });
  fetch("/api/cooldown-watch?" + qs.toString(), { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      _CDW_INFLIGHT[key] = false;
      if (data) {
        _CDW_CACHE[key] = data;
        _CDW_TS[key] = Date.now();
        if (typeof onLand === "function") onLand();
      }
    })
    .catch(() => { _CDW_INFLIGHT[key] = false; });
}

export function getCachedCooldownWatch(enemyNames) {
  return _CDW_CACHE[_cacheKey(enemyNames)] || null;
}

export function getCooldownWatchCacheCount() {
  return Object.keys(_CDW_CACHE).length;
}

function _signature(payload) {
  if (!payload || !payload.ok) {
    return payload && payload.reason ? `_${payload.reason}` : "_empty";
  }
  const cards = Array.isArray(payload.cards) ? payload.cards : [];
  return cards
    .map((c) => `${c.champion}:${c.spell_key}:${(+c.cooldown_s || 0)}`)
    .join("|") || "_nocards";
}

// "1.0s stun" / "1.0s root (if setup)" - the CC descriptor under the row.
function _ccText(card) {
  const dur = (+card.cc_duration_s || 0).toFixed(1);
  const kind = card.cc_kind ? String(card.cc_kind) : "lock";
  const base = `${dur}s ${kind}`;
  return card.conditional ? `${base} (if setup)` : base;
}

// Round the headline cooldown to a whole second for display.
function _cdLabel(card) {
  const cd = +card.cooldown_s || 0;
  if (cd <= 0) return "?";
  return `${Math.round(cd)}s`;
}

// Render the cooldown-watch card into the provided element. payload is the
// backend response (may be null on cold-load).
export function renderCooldownWatch(blockEl, payload) {
  if (!blockEl) return;
  const sigKey = blockEl.id || "_cdw_default";
  const sig = _signature(payload);
  if (_CDW_SIG[sigKey] === sig) return;
  _CDW_SIG[sigKey] = sig;

  if (!payload || !payload.ok) {
    blockEl.hidden = true;
    return;
  }
  const cards = Array.isArray(payload.cards) ? payload.cards : [];
  if (!cards.length) {
    blockEl.hidden = true;
    return;
  }
  blockEl.hidden = false;

  const rows = cards.map((c) => (
    `<div class="cdw-row"${c.conditional ? ' data-cdw-cond="1"' : ""}>`
    + `<span class="cdw-slot">${String(c.spell_key || "")}</span>`
    + `<span class="cdw-main">`
    + `<span class="cdw-champ">${String(c.champion || "")}</span>`
    + `<span class="cdw-spell">${String(c.spell_name || c.spell_key || "")}</span>`
    + `<span class="cdw-cc">${_ccText(c)}</span>`
    + `</span>`
    + `<span class="cdw-cd">${_cdLabel(c)}</span>`
    + `</div>`
  )).join("");

  blockEl.innerHTML = (
    `<div class="cdw-head">`
    + `<span class="cdw-head-title">Watch their cooldowns</span>`
    + `<span class="cdw-head-sub">after they whiff, this is the window</span>`
    + `</div>`
    + rows
  );
}

// Reset helper for tests (clears in-memory cache + sig stamps).
export function _resetCooldownWatch() {
  for (const k of Object.keys(_CDW_CACHE))    delete _CDW_CACHE[k];
  for (const k of Object.keys(_CDW_INFLIGHT)) delete _CDW_INFLIGHT[k];
  for (const k of Object.keys(_CDW_TS))       delete _CDW_TS[k];
  for (const k of Object.keys(_CDW_SIG))      delete _CDW_SIG[k];
}

export const __test = {
  _cacheKey,
  _signature,
  _ccText,
  _cdLabel,
  _CDW_TTL_MS,
};
