// Spike Curve Sparkline panel (2026-05-20, UX win).
//
// Renders a 40px-tall power-vs-minute sparkline above the BUILD pane in
// the active_match view. Two lines plot ally vs enemy team combat
// strength across game minutes 0..40, with a dashed vertical "now"
// marker at the live game time and small triangle markers at each
// team's spike-online minute. Reference: aggregator C Power Curve graph.
//
// Backend wire: GET /api/spike-curve?ally=ID,ID,...&enemy=ID,ID,...&mode=SR
// (dashboard/routes_spike_curve.py). Response = 41-entry power arrays
// for each side + peak minutes. Fetched once per champ-lock + on major
// phase change (cache key = sorted ally+enemy ids + mode). Cache miss
// re-fetches; cache hit skips render via sig dedup.
//
// Design discipline: pure render module, no business logic - the
// scoring math lives in the backend. Fail-soft on null curve, empty
// arrays, missing peaks. ASCII only (no em / en dashes / smart quotes).

const _CURVE_CACHE = Object.create(null); // cacheKey -> response JSON
const _CURVE_INFLIGHT = Object.create(null);
const _CURVE_SIG = Object.create(null); // mount-id -> last-rendered signature

// Cache TTL on the client side too - 5 min matches the backend response cache
// so a UI re-mount during a single champ-select session doesn't refetch.
const _CURVE_TTL_MS = 5 * 60 * 1000;
const _CURVE_TS = Object.create(null); // cacheKey -> Date.now() at write

// Colors - blue for ally (our side), red for enemy. Matches the
// established 'blue side / red side' tints used in cd_ledger.css.
const _ALLY_COLOR = "#5096ff";
const _ENEMY_COLOR = "#ff5050";
const _NOW_COLOR = "rgba(180, 180, 180, 0.75)";
const _ITEM_TICK_COLOR = "rgba(120, 120, 120, 0.45)";

// SVG layout - 40px tall, full width, with a 2px top + 4px bottom pad
// so the lines + peak triangles don't clip. The X axis runs the full
// width of the SVG; the Y axis spans the inner-padded height.
const _SVG_HEIGHT = 40;
const _PAD_TOP = 3;
const _PAD_BOTTOM = 4;

function _cacheKey(allyIds, enemyIds, mode) {
  // Order-insensitive on team membership so 1,2,3,4,5 and 5,4,3,2,1
  // hit the same key (mirrors backend _response_cache_key).
  const a = (allyIds || []).slice().sort().join(",");
  const e = (enemyIds || []).slice().sort().join(",");
  return `${a}|${e}|${(mode || "SR").toUpperCase()}`;
}

// Fetch + memoize. Returns nothing - caller re-renders on next tick
// when the cache lands. ``onLand`` optional re-render callback.
export function fetchSpikeCurve(allyIds, enemyIds, mode, onLand) {
  if (!Array.isArray(allyIds) || allyIds.length !== 5) return;
  if (!Array.isArray(enemyIds) || enemyIds.length !== 5) return;
  const key = _cacheKey(allyIds, enemyIds, mode);
  const fresh = _CURVE_CACHE[key] && _CURVE_TS[key]
                && (Date.now() - _CURVE_TS[key]) < _CURVE_TTL_MS;
  if (fresh || _CURVE_INFLIGHT[key]) return;
  _CURVE_INFLIGHT[key] = true;
  const qs = new URLSearchParams({
    ally: allyIds.join(","),
    enemy: enemyIds.join(","),
    mode: String(mode || "SR").toUpperCase(),
  });
  fetch("/api/spike-curve?" + qs.toString(), { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      _CURVE_INFLIGHT[key] = false;
      if (data && data.ok) {
        _CURVE_CACHE[key] = data;
        _CURVE_TS[key] = Date.now();
        if (typeof onLand === "function") onLand();
      }
    })
    .catch(() => {
      _CURVE_INFLIGHT[key] = false;
    });
}

export function getCachedSpikeCurve(allyIds, enemyIds, mode) {
  return _CURVE_CACHE[_cacheKey(allyIds, enemyIds, mode)] || null;
}

// Pure-function signature builder for the sig-dedup gate. Anything that
// changes the rendered SVG should change the sig.
function _signature(ally, enemy, peaks, nowMinute, itemMinutes) {
  const a = (ally || []).map((e) => Math.round((e.power || 0) * 100) / 100).join(",");
  const en = (enemy || []).map((e) => Math.round((e.power || 0) * 100) / 100).join(",");
  const pk = peaks ? `${peaks.ally || 0}|${peaks.enemy || 0}` : "0|0";
  const im = (itemMinutes || []).join(",");
  return `${a}::${en}::${pk}::${nowMinute || 0}::${im}`;
}

// Linear scale builder. Returns a function that maps a domain value into
// the pixel range. Defensive against zero-extent domain (collapses to
// midpoint).
function _scale(domainMin, domainMax, rangeMin, rangeMax) {
  const dExt = domainMax - domainMin;
  if (dExt <= 0) {
    const mid = (rangeMin + rangeMax) / 2;
    return () => mid;
  }
  const rExt = rangeMax - rangeMin;
  return (v) => rangeMin + ((v - domainMin) / dExt) * rExt;
}

// Build a polyline 'points' attribute from a power-curve array + scale fns.
function _polylinePoints(curve, xFn, yFn) {
  if (!Array.isArray(curve) || !curve.length) return "";
  const out = [];
  for (const entry of curve) {
    const x = xFn(entry.minute || 0);
    const y = yFn(entry.power || 0);
    out.push(`${x.toFixed(1)},${y.toFixed(1)}`);
  }
  return out.join(" ");
}

// Build a single team's peak triangle (small downward-pointing chevron
// at the curve's peak minute). Returns "" when peak data is missing.
function _peakTriangle(peakMinute, curve, xFn, yFn, color) {
  if (peakMinute == null) return "";
  if (!Array.isArray(curve) || !curve.length) return "";
  // Find the power value at peakMinute (entry may not exist if the
  // backend returned a degenerate peak); fall back to highest power.
  let powerAtPeak = 0;
  for (const entry of curve) {
    if ((entry.minute || 0) === peakMinute) {
      powerAtPeak = entry.power || 0;
      break;
    }
  }
  const x = xFn(peakMinute);
  const y = yFn(powerAtPeak);
  // Downward triangle, 5px wide x 4px tall, sitting just above the data point.
  const p1 = `${(x - 3).toFixed(1)},${(y - 7).toFixed(1)}`;
  const p2 = `${(x + 3).toFixed(1)},${(y - 7).toFixed(1)}`;
  const p3 = `${x.toFixed(1)},${(y - 2).toFixed(1)}`;
  return `<polygon points="${p1} ${p2} ${p3}" fill="${color}" stroke="${color}" stroke-width="0.5"></polygon>`;
}

// Phase-strength strip (R81 F1, competitor lift). A compact early/mid/late
// GREEN/YELLOW/RED block beneath the sparkline, one row per team. Driven by
// the ctx.phases field the backend now returns on /api/spike-curve. Purely
// presentational + fail-soft: a missing / malformed ctx.phases returns "" so
// the sparkline paints byte-identical to before (no strip, no height change).
const _PHASE_ORDER = ["early", "mid", "late"];
const _PHASE_CELL_LABEL = { early: "E", mid: "M", late: "L" };
// Value -> {class suffix, hover word}. Anything outside this set = invalid.
const _PHASE_COLOR = {
  green: { cls: "spk-phase-green", word: "strong" },
  yellow: { cls: "spk-phase-yellow", word: "even" },
  red: { cls: "spk-phase-red", word: "weak" },
};

// Validate one side ({early,mid,late} of color strings). Returns true only
// when every phase key holds a recognized color literal.
function _validPhaseSide(side) {
  if (!side || typeof side !== "object") return false;
  for (const ph of _PHASE_ORDER) {
    if (!Object.prototype.hasOwnProperty.call(_PHASE_COLOR, side[ph])) {
      return false;
    }
  }
  return true;
}

// Build one team's row (label + 3 color cells). Assumes ``side`` already
// passed _validPhaseSide.
function _phaseRow(rowLabel, side) {
  let cells = "";
  for (const ph of _PHASE_ORDER) {
    const meta = _PHASE_COLOR[side[ph]];
    const title = `${ph}: ${meta.word}`;
    cells += `<span class="spk-phase ${meta.cls}" title="${title}">`
           + `${_PHASE_CELL_LABEL[ph]}</span>`;
  }
  return `<div class="spk-phase-row">`
       + `<span class="spk-phase-label">${rowLabel}</span>${cells}</div>`;
}

// Render the full 2-row strip. ``phases`` is ctx.phases (may be null /
// malformed). Returns "" (append nothing) unless BOTH sides validate, so a
// stale / old-schema payload leaves the sparkline untouched.
function _phaseStrip(phases) {
  if (!phases || typeof phases !== "object") return "";
  const ally = phases.ally;
  const enemy = phases.enemy;
  if (!_validPhaseSide(ally) || !_validPhaseSide(enemy)) return "";
  return `<div class="spk-phases">`
       + _phaseRow("You", ally)
       + _phaseRow("Enemy", enemy)
       + `</div>`;
}

// Pure render. ``parentEl`` is the mount node; everything else is data.
// ``itemMinutes`` (optional) renders thin gray vertical ticks at each
// planned item completion. ``nowMinute`` (optional) renders the dashed
// gray "you are here" marker. ``ctx.phases`` (optional) appends the
// early/mid/late strength strip beneath the sparkline (fail-soft when absent).
export function renderSpikeCurve(parentEl, ally_curve, enemy_curve, peaks, now_minute, ctx) {
  if (!parentEl) return;
  ctx = ctx || {};
  const itemMinutes = Array.isArray(ctx.item_minutes) ? ctx.item_minutes : [];
  const phases = (ctx && ctx.phases) || null;

  // Fail-soft: null / empty curves render a 'no data' shell so the
  // 40px reserved space doesn't collapse and trigger layout jitter.
  if (!Array.isArray(ally_curve) || !Array.isArray(enemy_curve)
      || !ally_curve.length || !enemy_curve.length) {
    if (parentEl.dataset.spkState !== "empty") {
      parentEl.dataset.spkState = "empty";
      parentEl.innerHTML = `<div class="spk-empty">power curve unavailable</div>`;
    }
    return;
  }

  // Sig-dedup gate. Same input + same mount node -> skip the rebuild.
  const sigKey = parentEl.id || "_spk_default";
  const sig = _signature(ally_curve, enemy_curve, peaks, now_minute, itemMinutes);
  // Dedup, but only if the DOM still reflects the stamped sig. The outer
  // active_match.js hide path clears parentEl.innerHTML behind our back, so a
  // re-show with identical data must repaint an externally-emptied mount
  // instead of early-returning into a blank (but visible) sparkline.
  if (_CURVE_SIG[sigKey] === sig && parentEl.innerHTML !== "") return;
  _CURVE_SIG[sigKey] = sig;

  // Width measurement - we use clientWidth at render time; falls back to
  // 320px (sensible default for the build-pane width at 1920px).
  const widthPx = Math.max(40, parentEl.clientWidth | 0 || 320);

  // Domains. X always 0..40 (the backend always emits 41 entries).
  // Y = max-of-both-teams' max power, plus a hair of headroom so the
  // peak triangle doesn't clip the top.
  let maxPower = 0;
  for (const e of ally_curve) {
    if ((e.power || 0) > maxPower) maxPower = e.power || 0;
  }
  for (const e of enemy_curve) {
    if ((e.power || 0) > maxPower) maxPower = e.power || 0;
  }
  if (maxPower <= 0) maxPower = 1;

  const xFn = _scale(0, 40, 4, widthPx - 4);
  // Y axis flipped: power 0 -> bottom (height - PAD_BOTTOM), max -> top (PAD_TOP).
  const yFn = _scale(0, maxPower * 1.05, _SVG_HEIGHT - _PAD_BOTTOM, _PAD_TOP);

  // Polyline for each team.
  const allyPts = _polylinePoints(ally_curve, xFn, yFn);
  const enemyPts = _polylinePoints(enemy_curve, xFn, yFn);

  // Optional item-completion ticks - thin gray vertical lines at each
  // planned-item minute. Spans top to bottom of the inner padded area.
  const itemTicks = itemMinutes.map((m) => {
    const x = xFn(m).toFixed(1);
    return `<line x1="${x}" y1="${_PAD_TOP}" x2="${x}" y2="${_SVG_HEIGHT - _PAD_BOTTOM}" stroke="${_ITEM_TICK_COLOR}" stroke-width="1" stroke-dasharray="1,2"></line>`;
  }).join("");

  // Optional "now" marker - dashed 1px vertical line, gray.
  let nowMarker = "";
  if (now_minute != null && now_minute >= 0 && now_minute <= 40) {
    const x = xFn(now_minute).toFixed(1);
    nowMarker = `<line x1="${x}" y1="${_PAD_TOP}" x2="${x}" y2="${_SVG_HEIGHT - _PAD_BOTTOM}" stroke="${_NOW_COLOR}" stroke-width="1" stroke-dasharray="3,2"></line>`;
  }

  // Peak indicators (small triangles).
  let peakMarkers = "";
  if (peaks && peaks.ally != null) {
    peakMarkers += _peakTriangle(peaks.ally, ally_curve, xFn, yFn, _ALLY_COLOR);
  }
  if (peaks && peaks.enemy != null) {
    peakMarkers += _peakTriangle(peaks.enemy, enemy_curve, xFn, yFn, _ENEMY_COLOR);
  }

  // Tooltip - one line summary so hovering the sparkline tells the operator
  // when each team comes online + the relative max-power ratio.
  const allyPeak = (peaks && peaks.ally != null) ? peaks.ally : "?";
  const enemyPeak = (peaks && peaks.enemy != null) ? peaks.enemy : "?";
  const tip = `Power curve: ally spike ~m${allyPeak}, enemy spike ~m${enemyPeak}`;

  const svg = `
    <svg class="spk-svg" xmlns="http://www.w3.org/2000/svg"
         viewBox="0 0 ${widthPx} ${_SVG_HEIGHT}"
         preserveAspectRatio="none"
         width="100%" height="${_SVG_HEIGHT}"
         role="img" aria-label="${tip}">
      <title>${tip}</title>
      ${itemTicks}
      ${nowMarker}
      <polyline class="spk-enemy" points="${enemyPts}"
                fill="none" stroke="${_ENEMY_COLOR}" stroke-width="1.5"
                stroke-linejoin="round" stroke-linecap="round"></polyline>
      <polyline class="spk-ally" points="${allyPts}"
                fill="none" stroke="${_ALLY_COLOR}" stroke-width="1.5"
                stroke-linejoin="round" stroke-linecap="round"></polyline>
      ${peakMarkers}
    </svg>
  `;
  // Phase strip appended in the SAME innerHTML write so the sparkline + strip
  // paint atomically (one assignment). Fail-soft: _phaseStrip("") when phases
  // is null / malformed leaves the sparkline byte-identical to the pre-R81
  // render.
  parentEl.dataset.spkState = "ready";
  parentEl.innerHTML = svg + _phaseStrip(phases);
}

// Test / diagnostic helper - clear all caches + sig state.
export function _resetSpikeCurve() {
  for (const k of Object.keys(_CURVE_CACHE)) delete _CURVE_CACHE[k];
  for (const k of Object.keys(_CURVE_INFLIGHT)) delete _CURVE_INFLIGHT[k];
  for (const k of Object.keys(_CURVE_TS)) delete _CURVE_TS[k];
  for (const k of Object.keys(_CURVE_SIG)) delete _CURVE_SIG[k];
}

// Surface internals for unit testing without polluting the runtime
// surface. Mirrors the cd_ledger.js __test bundle pattern.
export const __test = {
  _cacheKey,
  _signature,
  _scale,
  _polylinePoints,
  _peakTriangle,
  _phaseStrip,
  _phaseRow,
  _validPhaseSide,
  _ALLY_COLOR,
  _ENEMY_COLOR,
  _NOW_COLOR,
  _ITEM_TICK_COLOR,
  _SVG_HEIGHT,
  _CURVE_TTL_MS,
};
