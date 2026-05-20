// Ward Coverage Heat Strip panel (UX wave 1 ship, 2026-05-20).
//
// Renders a 22px horizontal band sitting inside the Active Match MAP
// pane head row, showing rolling-window ward placements per lane for
// both teams. Backend wire: GET /api/ward-heat?window_s=90
// (dashboard/routes_ward_heat.py).
//
// Layout per row: 4 lane cells (TOP / JG / MID / BOT) for one side.
// Each cell color-intensity-encodes the placement COUNT in the rolling
// window; a thin red bottom border highlights lanes with zero friendly
// wards in the last 60s (the "lanes_uncovered" set from the backend).
// Stacked: ally row above, enemy row below. Tiny side label on each row.
//
// Producer status: the backend was previously stubbed (route returned
// empty); the producer wire (core/ward_producer.tick_from_snapshot
// listening on core/liveclient_cache) ships in this same slice. The
// frontend is fail-soft when the buffer is empty (renders a faint
// "no wards yet" placeholder) so a fresh game with no events still
// reserves the strip's height instead of jumping the layout.
//
// Discipline: pure render module, sig-dedup gate, ASCII only.

const _WH_CACHE = { ts: 0, payload: null };
const _WH_INFLIGHT = { busy: false };
const _WH_SIG = Object.create(null);

const _FETCH_INTERVAL_MS = 4000;   // server already caches 2s; client polls 4s
const _WINDOW_S = 90;

// Color ramp - low count = faint, high count = bright. Aligns with the
// ally/enemy palette used in cd_ledger + spike_curve.
const _ALLY_BASE = [80, 150, 255];   // #5096ff blue
const _ENEMY_BASE = [255, 80, 80];   // #ff5050 red
const _UNCOVERED = "#ff3030";

const _LANES = ["top", "jg", "mid", "bot"];

function _intensity(n) {
  // 0 wards -> 0.10 (faint), 1 -> 0.35, 2 -> 0.55, 3+ -> 0.85.
  if (!n || n <= 0) return 0.10;
  if (n === 1) return 0.35;
  if (n === 2) return 0.55;
  return 0.85;
}

function _rgba(rgb, alpha) {
  return `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${alpha.toFixed(2)})`;
}

// Build a single side row's HTML. ``uncovered`` is a Set of lanes with
// zero recent friendly wards (rendered with a 2px red bottom rule).
function _renderRow(sideKey, counts, uncoveredSet) {
  const base = sideKey === "ally" ? _ALLY_BASE : _ENEMY_BASE;
  const label = sideKey === "ally" ? "ally" : "enemy";
  const cells = _LANES.map((lane) => {
    const n = (counts && counts[lane]) | 0;
    const fill = _rgba(base, _intensity(n));
    const uncov = uncoveredSet && uncoveredSet.has(lane);
    const borderRule = uncov
      ? `border-bottom: 2px solid ${_UNCOVERED};`
      : "border-bottom: 1px solid rgba(255,255,255,0.06);";
    const tip = uncov
      ? `${label} ${lane}: ${n} wards (UNCOVERED 60s)`
      : `${label} ${lane}: ${n} wards in last ${_WINDOW_S}s`;
    const count = n > 0 ? n : "";
    return (
      `<span class="wh-cell" data-lane="${lane}" data-uncov="${uncov ? 1 : 0}" `
      + `style="background:${fill}; ${borderRule}" title="${tip}">`
      + `<span class="wh-lane">${lane}</span>`
      + `<span class="wh-count">${count}</span>`
      + `</span>`
    );
  }).join("");
  return (
    `<div class="wh-row wh-${sideKey}">`
    + `<span class="wh-side">${label}</span>`
    + cells
    + `</div>`
  );
}

function _signature(payload) {
  const counts = payload && payload.counts || {};
  const a = counts.ally || {};
  const e = counts.enemy || {};
  const ua = (payload && payload.lanes_uncovered_ally || []).join(",");
  const ue = (payload && payload.lanes_uncovered_enemy || []).join(",");
  return [
    a.top|0, a.jg|0, a.mid|0, a.bot|0,
    e.top|0, e.jg|0, e.mid|0, e.bot|0,
    ua, ue, payload && payload.buffer_size | 0,
  ].join("|");
}

export function fetchWardHeat(onLand) {
  const now = Date.now();
  if (_WH_INFLIGHT.busy) return;
  if (_WH_CACHE.payload && (now - _WH_CACHE.ts) < _FETCH_INTERVAL_MS) {
    if (typeof onLand === "function") onLand(_WH_CACHE.payload);
    return;
  }
  _WH_INFLIGHT.busy = true;
  fetch(`/api/ward-heat?window_s=${_WINDOW_S}`, { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      _WH_INFLIGHT.busy = false;
      if (data && data.ok) {
        _WH_CACHE.payload = data;
        _WH_CACHE.ts = now;
        if (typeof onLand === "function") onLand(data);
      }
    })
    .catch(() => { _WH_INFLIGHT.busy = false; });
}

export function getCachedWardHeat() {
  return _WH_CACHE.payload;
}

export function renderWardHeat(parentEl, payload) {
  if (!parentEl) return;
  const sigKey = parentEl.id || "_wh_default";

  if (!payload || !payload.ok) {
    if (_WH_SIG[sigKey] !== "_empty") {
      _WH_SIG[sigKey] = "_empty";
      parentEl.dataset.whState = "empty";
      parentEl.innerHTML = `<div class="wh-empty">no wards yet</div>`;
    }
    return;
  }

  const sig = _signature(payload);
  if (_WH_SIG[sigKey] === sig) return;
  _WH_SIG[sigKey] = sig;

  const counts = payload.counts || {};
  const allyUncov = new Set(payload.lanes_uncovered_ally || []);
  const enemyUncov = new Set(payload.lanes_uncovered_enemy || []);

  parentEl.dataset.whState = "ready";
  parentEl.innerHTML =
    _renderRow("ally",  counts.ally  || {}, allyUncov)
    + _renderRow("enemy", counts.enemy || {}, enemyUncov);
}

// Test / diagnostic helper - clear cache + sig state.
export function _resetWardHeat() {
  _WH_CACHE.ts = 0;
  _WH_CACHE.payload = null;
  _WH_INFLIGHT.busy = false;
  for (const k of Object.keys(_WH_SIG)) delete _WH_SIG[k];
}

// Surface internals for unit testing.
export const __test = {
  _intensity,
  _rgba,
  _signature,
  _renderRow,
  _ALLY_BASE,
  _ENEMY_BASE,
  _UNCOVERED,
  _LANES,
  _WINDOW_S,
  _FETCH_INTERVAL_MS,
};
