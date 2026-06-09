// Ally CC-pairing card (CS1 - operator batch 2026-06-08). Surfaces, for
// the operator's OWN roster, each conditional CC entry whose condition a
// TEAMMATE can set up (dual_enemy / debuffed_target / terrain / traverse),
// plus the plausible enabler teammates + a setup hint.
//
// This is the per-entry PAIRING view the existing cc_conditional surfaces
// do NOT provide: the cc-conditional-pressure chip ratios ally-vs-enemy
// CONDITIONAL CC seconds into a single balance number; cooldown-watch
// surfaces the single highest-threat ENEMY ability. Neither answers
// "which of my team's conditional CC can a teammate chain into?".
//
// Backend wire:
//   GET /api/cc-pairing?ally=<champ,champ,...>[&top_n=6]
//   Response: {
//     ok, cards:[{champion, spell, spell_key, cc_kind, cc_duration_s,
//                 condition, probability, setup_hint, enablers:[...]}],
//     count, elapsed_ms, cached
//   }
//
// Champion ids in the query are canonical DDragon slugs; the host
// (champ_select.js) resolves numeric LCU championId via resolveChampNames
// before fetching.
//
// Discipline: pure ESM, ASCII only, sig-dedup gate, no DOM writes outside
// renderCcPairing(). Mirrors the cooldown_watch.js pattern exactly.

const _CCPAIR_CACHE = Object.create(null);     // cacheKey -> response JSON
const _CCPAIR_INFLIGHT = Object.create(null);
const _CCPAIR_TS = Object.create(null);
const _CCPAIR_SIG = Object.create(null);
const _CCPAIR_TTL_MS = 5 * 60 * 1000;          // matches backend TTL

function _cacheKey(allyNames) {
  return (allyNames || []).slice().sort().join(",");
}

export function fetchCcPairing(allyNames, onLand) {
  if (!Array.isArray(allyNames) || allyNames.length < 1) return;
  const key = _cacheKey(allyNames);
  const fresh = _CCPAIR_CACHE[key] && _CCPAIR_TS[key]
                && (Date.now() - _CCPAIR_TS[key]) < _CCPAIR_TTL_MS;
  if (fresh || _CCPAIR_INFLIGHT[key]) return;
  _CCPAIR_INFLIGHT[key] = true;
  const qs = new URLSearchParams({ ally: allyNames.join(",") });
  fetch("/api/cc-pairing?" + qs.toString(), { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      _CCPAIR_INFLIGHT[key] = false;
      if (data) {
        _CCPAIR_CACHE[key] = data;
        _CCPAIR_TS[key] = Date.now();
        if (typeof onLand === "function") onLand();
      }
    })
    .catch(() => { _CCPAIR_INFLIGHT[key] = false; });
}

export function getCachedCcPairing(allyNames) {
  return _CCPAIR_CACHE[_cacheKey(allyNames)] || null;
}

export function getCcPairingCacheCount() {
  return Object.keys(_CCPAIR_CACHE).length;
}

function _signature(payload) {
  if (!payload || !payload.ok) {
    return payload && payload.reason ? `_${payload.reason}` : "_empty";
  }
  const cards = Array.isArray(payload.cards) ? payload.cards : [];
  return cards
    .map((c) => `${c.champion}:${c.spell}:${(c.enablers || []).join("+")}`)
    .join("|") || "_nocards";
}

// HTML-escape a short slug / hint so a champion name or hint never breaks
// the innerHTML (defense-in-depth; DDragon ids are alnum but the setup
// hint carries punctuation).
function _esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// "1.5s fear (50%)" - the CC descriptor: max-rank duration + kind +
// condition-probability midpoint as a percent.
function _ccText(card) {
  const dur = (+card.cc_duration_s || 0).toFixed(1);
  const kind = card.cc_kind ? String(card.cc_kind) : "lock";
  const pct = Math.round((+card.probability || 0) * 100);
  return `${dur}s ${_esc(kind)} (${pct}%)`;
}

// "set up by: Leona, Nautilus" or the "-" no-data sentinel when no
// teammate carries an enabling tool.
function _enablerText(card) {
  const list = Array.isArray(card.enablers) ? card.enablers : [];
  if (!list.length) return "-";
  return list.map(_esc).join(", ");
}

// Render the ally CC-pairing card into the provided element. payload is the
// backend response (may be null on cold-load).
export function renderCcPairing(blockEl, payload) {
  if (!blockEl) return;
  const sigKey = blockEl.id || "_ccpair_default";
  const sig = _signature(payload);
  if (_CCPAIR_SIG[sigKey] === sig) return;
  _CCPAIR_SIG[sigKey] = sig;

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
    `<div class="ccpair-row">`
    + `<span class="ccpair-slot">${_esc(c.spell || "")}</span>`
    + `<span class="ccpair-main">`
    + `<span class="ccpair-top">`
    + `<span class="ccpair-champ">${_esc(c.champion || "")}</span>`
    + `<span class="ccpair-cc">${_ccText(c)}</span>`
    + `</span>`
    + `<span class="ccpair-hint">${_esc(c.setup_hint || "")}</span>`
    + `<span class="ccpair-enablers">`
    + `<span class="ccpair-enablers-label">set up by</span> `
    + `<span class="ccpair-enablers-list">${_enablerText(c)}</span>`
    + `</span>`
    + `</span>`
    + `</div>`
  )).join("");

  blockEl.innerHTML = (
    `<div class="ccpair-head">`
    + `<span class="ccpair-head-title">CC combos your team can set up</span>`
    + `<span class="ccpair-head-sub">conditional CC a teammate can enable</span>`
    + `</div>`
    + rows
  );
}

// Reset helper for tests (clears in-memory cache + sig stamps).
export function _resetCcPairing() {
  for (const k of Object.keys(_CCPAIR_CACHE))    delete _CCPAIR_CACHE[k];
  for (const k of Object.keys(_CCPAIR_INFLIGHT)) delete _CCPAIR_INFLIGHT[k];
  for (const k of Object.keys(_CCPAIR_TS))       delete _CCPAIR_TS[k];
  for (const k of Object.keys(_CCPAIR_SIG))      delete _CCPAIR_SIG[k];
}

export const __test = {
  _cacheKey,
  _signature,
  _ccText,
  _enablerText,
  _CCPAIR_TTL_MS,
};
