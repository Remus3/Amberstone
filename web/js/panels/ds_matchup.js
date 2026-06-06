// DS-Matchup champ-select card. Surfaces the EXISTING 1v1 matchup engine
// for the operator's LOCKED champion against the FIRST committed enemy
// champion - a one-glance "all-in / trade / back-off / even" read at the
// level the engine simulates. Pure presentation over the existing engine;
// no new compute lives here.
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
// champ_a is read from the champ-select state (cs.my_champion, the
// operator's own numeric LCU id); champ_b is the FIRST committed enemy
// champion id from cs.their_team. Both resolve to DDragon slugs via
// resolveChampNames (imported from cc_conditional_pressure.js, exactly
// as ds_profile.js does).
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
function _signature(payload) {
  if (!payload || !payload.ok) {
    return payload && payload.reason ? `_${payload.reason}` : "_empty";
  }
  return [
    payload.champ_a || "",
    payload.champ_b || "",
    String(payload.verdict || ""),
    _clampSwing(payload.swing_pct),
    _pctRemoved(payload.pct_a_removed),
    _pctRemoved(payload.pct_b_removed),
  ].join("|");
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

// Render the matchup card into the provided element. payload is the backend
// response (may be null on cold-load). Hides on null / not-ok payloads.
export function renderDsMatchup(blockEl, payload) {
  if (!blockEl) return;
  const sigKey = blockEl.id || "_dsm_default";
  const sig = _signature(payload);
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

  blockEl.innerHTML = (
    `<div class="dsm-head">`
    + `<span class="dsm-head-title">DS matchup</span>`
    + `<span class="dsm-head-sub">${aName} vs ${bName}</span>`
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
  );
}

// Champ-select entry point. Mirrors renderDsProfileForChampSelect(cs): read
// the LOCKED champion (champ_a = cs.my_champion) + the FIRST committed enemy
// champion (champ_b) from the champ-select state, resolve both slugs, fetch
// the matchup, render the cached payload. ``blockId`` defaults to the
// Suggestions-card mount but is overridable for tests.
export function renderDsMatchupForChampSelect(cs, blockId) {
  const block = document.getElementById(blockId || "csv-sugg-ds-matchup");
  if (!block) return;
  const myId = (cs && (cs.my_champion | 0)) || 0;
  if (myId <= 0) {
    block.hidden = true;
    return;
  }
  // First committed enemy: the leading non-zero championId on their_team.
  const enemyIds = (cs && Array.isArray(cs.their_team))
    ? cs.their_team.map((p) => (p && (p.championId | 0)) || 0).filter((x) => x > 0)
    : [];
  const enemyId = enemyIds.length ? enemyIds[0] : 0;
  if (enemyId <= 0) {
    block.hidden = true;
    return;
  }
  const names = resolveChampNames([myId, enemyId]);
  if (names.length < 2) {
    // CHAMPS index not yet loaded - keep hidden, resolves next tick.
    block.hidden = true;
    return;
  }
  const champA = names[0];
  const champB = names[1];
  const mode = "SR";
  fetchDsMatchup(champA, champB, mode, _dsmOnLand);
  const payload = getCachedDsMatchup(champA, champB, mode);
  renderDsMatchup(block, payload);
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
  _DSM_TTL_MS,
};
