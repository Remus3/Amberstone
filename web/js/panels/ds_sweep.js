// DS stat-sweep graph (competitor lift #3,
// docs/COMPETITOR_LIFT_2026-05-30.md). Plots the LOCKED champion's
// auto-attack DPS against a swept enemy-stat axis (default target armor
// 0..300) - the calc.gg "how does my damage scale vs their armor" read.
// A single labelled sparkline over the EXISTING DS DPS engine: pure
// presentation, no new compute.
//
// Backend wire:
//   GET /api/ds-sweep?champion=<slug>&axis=armor[&item_ids=ID,ID][&mode=SR]
//   Response: {
//     ok, champion, axis, mode, level, item_ids,
//     points:[{x, dps, phase}], count, elapsed_ms, cached
//   }
//
// The locked champion is read from the champ-select state (cs.my_champion,
// the operator's own numeric LCU id) and resolved to a DDragon slug via
// resolveChampNames (re-exported from cc_conditional_pressure.js). The
// route resolves the champion's canonical archetype build when item_ids is
// omitted, so the panel sends only the champion + axis.
//
// Discipline: pure ESM, ASCII only, sig-dedup gate, no DOM writes outside
// renderDsSweep(). Sparkline rendering mirrors spike_curve.js. Fail-soft on
// null / empty points.

import { resolveChampNames } from './cc_conditional_pressure.js';

const _DSW_CACHE = Object.create(null);     // cacheKey -> response JSON
const _DSW_INFLIGHT = Object.create(null);
const _DSW_TS = Object.create(null);
const _DSW_SIG = Object.create(null);       // mount-id -> last-rendered sig
const _DSW_TTL_MS = 5 * 60 * 1000;          // matches backend TTL

// SVG layout - mirrors spike_curve.js (40px tall, full width, padded so
// the line + axis labels do not clip).
const _SVG_HEIGHT = 44;
const _PAD_TOP = 4;
const _PAD_BOTTOM = 5;
const _LINE_COLOR = "#5096ff";              // ally-blue, same tint family

function _cacheKey(champion, axis, mode) {
  return `${champion || ""}|${axis || "armor"}|${(mode || "SR").toUpperCase()}`;
}

// Fetch + memoize. Returns nothing - caller re-renders on next tick when
// the cache lands. ``onLand`` is an optional re-render callback.
export function fetchDsSweep(champion, axis, mode, onLand) {
  if (!champion) return;
  const key = _cacheKey(champion, axis, mode);
  const fresh = _DSW_CACHE[key] && _DSW_TS[key]
                && (Date.now() - _DSW_TS[key]) < _DSW_TTL_MS;
  if (fresh || _DSW_INFLIGHT[key]) return;
  _DSW_INFLIGHT[key] = true;
  const qs = new URLSearchParams({
    champion: String(champion),
    axis: String(axis || "armor"),
    mode: String(mode || "SR").toUpperCase(),
  });
  fetch("/api/ds-sweep?" + qs.toString(), { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      _DSW_INFLIGHT[key] = false;
      if (data) {
        _DSW_CACHE[key] = data;
        _DSW_TS[key] = Date.now();
        if (typeof onLand === "function") onLand();
      }
    })
    .catch(() => { _DSW_INFLIGHT[key] = false; });
}

export function getCachedDsSweep(champion, axis, mode) {
  return _DSW_CACHE[_cacheKey(champion, axis, mode)] || null;
}

export function getDsSweepCacheCount() {
  return Object.keys(_DSW_CACHE).length;
}

// Pure-function signature builder for the sig-dedup gate. Anything that
// changes the rendered SVG should change the sig.
function _signature(payload) {
  if (!payload || !payload.ok) {
    return payload && payload.reason ? `_${payload.reason}` : "_empty";
  }
  const pts = Array.isArray(payload.points) ? payload.points : [];
  const body = pts
    .map((p) => `${(+p.x || 0)}:${Math.round((+p.dps || 0) * 10) / 10}`)
    .join(",");
  return `${payload.champion || ""}|${payload.axis || ""}|${body}` || "_nopts";
}

// Linear scale builder. Maps a domain value into the pixel range. Defensive
// against a zero-extent domain (collapses to midpoint). Mirrors
// spike_curve.js _scale.
function _scale(domainMin, domainMax, rangeMin, rangeMax) {
  const dExt = domainMax - domainMin;
  if (dExt <= 0) {
    const mid = (rangeMin + rangeMax) / 2;
    return () => mid;
  }
  const rExt = rangeMax - rangeMin;
  return (v) => rangeMin + ((v - domainMin) / dExt) * rExt;
}

// Build a polyline 'points' attribute from a sweep point array + scale fns.
function _polylinePoints(points, xFn, yFn) {
  if (!Array.isArray(points) || !points.length) return "";
  const out = [];
  for (const p of points) {
    const x = xFn(+p.x || 0);
    const y = yFn(+p.dps || 0);
    out.push(`${x.toFixed(1)},${y.toFixed(1)}`);
  }
  return out.join(" ");
}

// X-axis label for the swept variable.
function _axisLabel(axis) {
  if (axis === "target_mr") return "enemy MR";
  if (axis === "level") return "level";
  return "enemy armor";
}

// Render the stat-sweep card into the provided element. payload is the
// backend response (may be null on cold-load).
export function renderDsSweep(blockEl, payload) {
  if (!blockEl) return;
  const sigKey = blockEl.id || "_dsw_default";
  const sig = _signature(payload);
  if (_DSW_SIG[sigKey] === sig) return;
  _DSW_SIG[sigKey] = sig;

  if (!payload || !payload.ok) {
    blockEl.hidden = true;
    return;
  }
  const points = Array.isArray(payload.points) ? payload.points : [];
  if (points.length < 2) {
    blockEl.hidden = true;
    return;
  }
  blockEl.hidden = false;

  const axis = String(payload.axis || "target_armor");
  const champ = String(payload.champion || "");

  // Domains. X = swept-variable min..max from the data. Y = 0..max DPS with
  // a hair of headroom so the line does not clip the top.
  let xMin = Infinity;
  let xMax = -Infinity;
  let yMax = 0;
  for (const p of points) {
    const x = +p.x || 0;
    const y = +p.dps || 0;
    if (x < xMin) xMin = x;
    if (x > xMax) xMax = x;
    if (y > yMax) yMax = y;
  }
  if (!isFinite(xMin)) xMin = 0;
  if (!isFinite(xMax)) xMax = 1;
  if (yMax <= 0) yMax = 1;

  const widthPx = Math.max(40, blockEl.clientWidth | 0 || 320);
  const xFn = _scale(xMin, xMax, 4, widthPx - 4);
  // Y flipped: dps 0 -> bottom, max -> top.
  const yFn = _scale(0, yMax * 1.05, _SVG_HEIGHT - _PAD_BOTTOM, _PAD_TOP);

  const linePts = _polylinePoints(points, xFn, yFn);

  // Headline read: DPS at the low end vs the high end of the swept axis.
  const firstDps = Math.round(+points[0].dps || 0);
  const lastDps = Math.round(+points[points.length - 1].dps || 0);
  const axisName = _axisLabel(axis);
  const tip = `${champ} DPS vs ${axisName} ${Math.round(xMin)}-${Math.round(xMax)}:`
            + ` ${firstDps} down to ${lastDps}`;

  const svg = `
    <svg class="dsw-svg" xmlns="http://www.w3.org/2000/svg"
         viewBox="0 0 ${widthPx} ${_SVG_HEIGHT}"
         preserveAspectRatio="none"
         width="100%" height="${_SVG_HEIGHT}"
         role="img" aria-label="${tip}">
      <title>${tip}</title>
      <polyline class="dsw-line" points="${linePts}"
                fill="none" stroke="${_LINE_COLOR}" stroke-width="1.5"
                stroke-linejoin="round" stroke-linecap="round"></polyline>
    </svg>`;

  blockEl.innerHTML = (
    `<div class="dsw-head">`
    + `<span class="dsw-head-title">DPS scaling</span>`
    + `<span class="dsw-head-sub">vs ${axisName} ${Math.round(xMin)}-${Math.round(xMax)}</span>`
    + `</div>`
    + `<div class="dsw-chart">${svg}</div>`
    + `<div class="dsw-foot">`
    + `<span class="dsw-foot-lo">${firstDps}</span>`
    + `<span class="dsw-foot-axis">${axisName}</span>`
    + `<span class="dsw-foot-hi">${lastDps}</span>`
    + `</div>`
  );
}

// Champ-select entry point. Mirrors _csvRenderCooldownWatch(cs): read the
// LOCKED champion from the champ-select state, resolve its slug, fetch the
// armor-axis sweep, render the cached payload. ``blockId`` defaults to the
// Suggestions-card mount but is overridable for tests.
export function renderDsSweepForChampSelect(cs, blockId) {
  const block = document.getElementById(blockId || "csv-sugg-ds-sweep");
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
  const axis = "armor";
  const mode = "SR";
  fetchDsSweep(champ, axis, mode, _dswOnLand);
  const payload = getCachedDsSweep(champ, axis, mode);
  renderDsSweep(block, payload);
}

// Re-render hook fired when a fetch lands. The orchestrator wires the real
// champ-select scheduler in champ_select.js; this module-local default is a
// no-op so the panel is safe to import standalone (tests + cold mount).
let _dswScheduleRender = null;
function _dswOnLand() {
  if (typeof _dswScheduleRender === "function") _dswScheduleRender();
}
export function setDsSweepScheduler(fn) {
  _dswScheduleRender = (typeof fn === "function") ? fn : null;
}

// Reset helper for tests (clears in-memory cache + sig stamps).
export function _resetDsSweep() {
  for (const k of Object.keys(_DSW_CACHE))    delete _DSW_CACHE[k];
  for (const k of Object.keys(_DSW_INFLIGHT)) delete _DSW_INFLIGHT[k];
  for (const k of Object.keys(_DSW_TS))       delete _DSW_TS[k];
  for (const k of Object.keys(_DSW_SIG))      delete _DSW_SIG[k];
}

export const __test = {
  _cacheKey,
  _signature,
  _scale,
  _polylinePoints,
  _axisLabel,
  _LINE_COLOR,
  _SVG_HEIGHT,
  _DSW_TTL_MS,
};
