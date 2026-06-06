// DS-Profile champion panel. Renders the LOCKED champion's DS "profile" as
// EIGHT labelled horizontal bars (Mobility / Sustain / Scaling / Waveclear /
// Range / Zone / Objective / Duel) - a one-glance read on how the operator's
// own pick is shaped along the axes the DS engine already scores. Pure
// presentation over the existing engine; no new compute lives here.
//
// Backend wire:
//   GET /api/ds-profile?champion=<slug-or-numeric>&mode=SR
//   Response: {
//     ok, champion, mode,
//     axes:[{key, label, score, pct, tier, detail,
//            slope?, trajectory?, ranged_shove?,
//            is_artillery?, controls_terrain?, pressures_structures?,
//            ramps?}],
//     elapsed_ms, cached
//   }
//   Failure: ok=false (reason "no_profile" for unknown champ) -> panel hides.
//
// Per-axis marker tags appended to the detail chip (all share the .dsp-flag
// look alongside the legacy .dsp-traj / .dsp-shove markers):
//   scaling     -> trajectory word (up/flat/down) via .dsp-traj
//   waveclear   -> "ranged" when ranged_shove           via .dsp-shove
//   threatrange -> "artillery" when is_artillery        via .dsp-flag
//   zonecontrol -> "terrain" when controls_terrain      via .dsp-flag
//   objdamage   -> "towers" when pressures_structures   via .dsp-flag
//   extendedduel-> "ramps" when ramps                   via .dsp-flag
//
// The locked champion is read from the champ-select state (cs.my_champion,
// the operator's own numeric LCU id) and resolved to a DDragon slug via
// resolveChampNames (re-exported from cc_conditional_pressure.js).
//
// Discipline: pure ESM, ASCII only, sig-dedup gate, no DOM writes outside
// renderDsProfile(). Bar rendering mirrors the ds_sweep.js module shape
// (per-key cache + TTL, inflight guard, sig stamp). Fail-soft on null / empty
// / not-ok payloads. ASCII trajectory markers (up/flat/down) - no unicode
// arrows.

import { resolveChampNames } from './cc_conditional_pressure.js';

const _DSP_CACHE = Object.create(null);     // cacheKey -> response JSON
const _DSP_INFLIGHT = Object.create(null);
const _DSP_TS = Object.create(null);
const _DSP_SIG = Object.create(null);       // mount-id -> last-rendered sig
const _DSP_TTL_MS = 5 * 60 * 1000;          // matches backend TTL

function _cacheKey(champion, mode) {
  return `${champion || ""}|${(mode || "SR").toUpperCase()}`;
}

// Map a tier string onto its row modifier class. Unknown / missing tiers fall
// back to the neutral "med" tint so a partial payload still renders a bar.
function _tierClass(tier) {
  const t = String(tier || "").toUpperCase();
  if (t === "HIGH") return "dsp-tier-high";
  if (t === "LOW") return "dsp-tier-low";
  return "dsp-tier-med";
}

// ASCII trajectory marker for the scaling axis. The engine sends UP/EVEN/DOWN;
// we render a short ASCII word (no unicode arrows - repo ASCII hard rule).
function _trajWord(trajectory) {
  const t = String(trajectory || "").toUpperCase();
  if (t === "UP") return "up";
  if (t === "DOWN") return "down";
  return "flat";
}

// Clamp a pct into 0..100 so a stray out-of-range score never overflows the
// track width. Non-numeric collapses to 0 (fail-soft).
function _clampPct(pct) {
  const n = +pct;
  if (!isFinite(n)) return 0;
  if (n < 0) return 0;
  if (n > 100) return 100;
  return Math.round(n);
}

// Fetch + memoize. Returns nothing - caller re-renders on next tick when the
// cache lands. ``onLand`` is an optional re-render callback.
export function fetchDsProfile(champion, mode, onLand) {
  if (!champion) return;
  const key = _cacheKey(champion, mode);
  const fresh = _DSP_CACHE[key] && _DSP_TS[key]
                && (Date.now() - _DSP_TS[key]) < _DSP_TTL_MS;
  if (fresh || _DSP_INFLIGHT[key]) return;
  _DSP_INFLIGHT[key] = true;
  const qs = new URLSearchParams({
    champion: String(champion),
    mode: String(mode || "SR").toUpperCase(),
  });
  fetch("/api/ds-profile?" + qs.toString(), { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      _DSP_INFLIGHT[key] = false;
      if (data) {
        _DSP_CACHE[key] = data;
        _DSP_TS[key] = Date.now();
        if (typeof onLand === "function") onLand();
      }
    })
    .catch(() => { _DSP_INFLIGHT[key] = false; });
}

export function getCachedDsProfile(champion, mode) {
  return _DSP_CACHE[_cacheKey(champion, mode)] || null;
}

export function getDsProfileCacheCount() {
  return Object.keys(_DSP_CACHE).length;
}

// Pure-function signature builder for the sig-dedup gate. Anything that
// changes the rendered bars (champion, or any axis key/pct/tier) should change
// the sig so an unchanged payload skips the innerHTML rebuild.
function _signature(payload) {
  if (!payload || !payload.ok) {
    return payload && payload.reason ? `_${payload.reason}` : "_empty";
  }
  const axes = Array.isArray(payload.axes) ? payload.axes : [];
  const body = axes
    .map((a) => `${a.key || ""}:${_clampPct(a.pct)}:${String(a.tier || "")}`)
    .join(",");
  return `${payload.champion || ""}|${body}` || "_noaxes";
}

// HTML-escape the small free-form strings (champion display name, detail chip)
// the backend passes through. Mirrors the defensive escaping the sibling
// champ-select panels use before innerHTML.
function _esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// Build a single axis row. Returns an HTML string. The fill width is the
// clamped pct; the row carries the tier modifier class; scaling rows append a
// trajectory word and waveclear rows a ranged-shove marker when flagged.
function _axisRow(axis) {
  const pct = _clampPct(axis && axis.pct);
  const tierCls = _tierClass(axis && axis.tier);
  const label = _esc(axis && axis.label);
  const detail = _esc(axis && axis.detail);

  let extra = "";
  if (axis && axis.key === "scaling" && axis.trajectory != null) {
    extra = `<span class="dsp-traj">${_esc(_trajWord(axis.trajectory))}</span>`;
  } else if (axis && axis.key === "waveclear" && axis.ranged_shove) {
    extra = `<span class="dsp-shove">ranged</span>`;
  } else if (axis && axis.key === "threatrange" && axis.is_artillery) {
    extra = `<span class="dsp-flag">artillery</span>`;
  } else if (axis && axis.key === "zonecontrol" && axis.controls_terrain) {
    extra = `<span class="dsp-flag">terrain</span>`;
  } else if (axis && axis.key === "objdamage" && axis.pressures_structures) {
    extra = `<span class="dsp-flag">towers</span>`;
  } else if (axis && axis.key === "extendedduel" && axis.ramps) {
    extra = `<span class="dsp-flag">ramps</span>`;
  }

  return (
    `<div class="dsp-row ${tierCls}">`
    + `<span class="dsp-label">${label}</span>`
    + `<span class="dsp-track">`
    + `<span class="dsp-fill" style="width:${pct}%"></span>`
    + `</span>`
    + `<span class="dsp-val">${pct}</span>`
    + `<span class="dsp-detail">${detail}${extra}</span>`
    + `</div>`
  );
}

// Render the profile card into the provided element. payload is the backend
// response (may be null on cold-load). Hides on null / not-ok / empty axes.
export function renderDsProfile(blockEl, payload) {
  if (!blockEl) return;
  const sigKey = blockEl.id || "_dsp_default";
  const sig = _signature(payload);
  if (_DSP_SIG[sigKey] === sig) return;
  _DSP_SIG[sigKey] = sig;

  const axes = payload && Array.isArray(payload.axes) ? payload.axes : null;
  if (!payload || !payload.ok || !axes || axes.length === 0) {
    blockEl.hidden = true;
    return;
  }
  blockEl.hidden = false;

  const champ = _esc(payload.champion || "");
  const rows = axes.map(_axisRow).join("");

  blockEl.innerHTML = (
    `<div class="dsp-head">`
    + `<span class="dsp-head-title">DS profile</span>`
    + `<span class="dsp-head-sub">${champ}</span>`
    + `</div>`
    + rows
  );
}

// Champ-select entry point. Mirrors renderDsSweepForChampSelect(cs): read the
// LOCKED champion from the champ-select state, resolve its slug, fetch the SR
// profile, render the cached payload. ``blockId`` defaults to the
// Suggestions-card mount but is overridable for tests.
export function renderDsProfileForChampSelect(cs, blockId) {
  const block = document.getElementById(blockId || "csv-sugg-ds-profile");
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
  fetchDsProfile(champ, mode, _dspOnLand);
  const payload = getCachedDsProfile(champ, mode);
  renderDsProfile(block, payload);
}

// Re-render hook fired when a fetch lands. The orchestrator wires the real
// champ-select scheduler in champ_select.js; this module-local default is a
// no-op so the panel is safe to import standalone (tests + cold mount).
let _dspScheduleRender = null;
function _dspOnLand() {
  if (typeof _dspScheduleRender === "function") _dspScheduleRender();
}
export function setDsProfileScheduler(fn) {
  _dspScheduleRender = (typeof fn === "function") ? fn : null;
}

// Reset helper for tests (clears in-memory cache + sig stamps).
export function _resetDsProfile() {
  for (const k of Object.keys(_DSP_CACHE))    delete _DSP_CACHE[k];
  for (const k of Object.keys(_DSP_INFLIGHT)) delete _DSP_INFLIGHT[k];
  for (const k of Object.keys(_DSP_TS))       delete _DSP_TS[k];
  for (const k of Object.keys(_DSP_SIG))      delete _DSP_SIG[k];
}

export const __test = {
  _cacheKey,
  _tierClass,
  _trajWord,
  _clampPct,
  _signature,
  _axisRow,
  _esc,
  _DSP_TTL_MS,
};
