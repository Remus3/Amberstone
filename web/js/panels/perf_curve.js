// Per-minute performance-curve panel (Build Insights "Game Flow" tab). Plots
// the tracked player's average cumulative gold (or CS) at each game minute over
// the operator's OWN rewind corpus, split into the games WON (green) vs LOST
// (red) - the per-minute performance graph popularized by public player-
// analytics sites, here personal + descriptive (no global / Riot / Claude data).
// Read: a win line that pulls away early = "I snowball my leads"; a loss line
// that flattens = "my losses stall there".
//
// Backend wire:
//   GET /api/perf-curve?mode=<aram|sr|arena>&metric=<gold|cs>
//   Response: { ok, mode, metric, champion, n_games, min_games_n,
//     minutes: [{minute, win_avg|null, win_n, loss_avg|null, loss_n}, ...] }
//   A minute with a series below min_games_n returns that series null (too thin
//   to trust) and is dropped from that line.
//   ?ui_mock=1 -> /data/ui_mock/perf_curve.json fixture (renders without a
//   populated rewind DB; mirrors duration_winrate.js).
//
// Discipline mirrors duration_winrate.js: pure ESM, ASCII only, per-key cache +
// TTL, inflight guard, sig-dedup, no DOM writes outside renderPerfCurve(),
// degraded-mode text on error (never a raw error string).

const _MOUNT = 'bi-flow-mount';
const _MODES = ['aram', 'sr', 'arena'];
const _METRICS = [['gold', 'Gold'], ['cs', 'CS']];
const _CACHE = Object.create(null);     // key -> response JSON
const _INFLIGHT = Object.create(null);
const _TS = Object.create(null);
const _TTL_MS = 5 * 60 * 1000;
let _sig = '';
let _mode = 'aram';
let _metric = 'gold';

// SVG geometry (unitless; CSS scales responsively).
const VB_W = 600;
const VB_H = 210;
const PAD_L = 46;
const PAD_R = 12;
const PAD_T = 12;
const PAD_B = 26;
const PLOT_W = VB_W - PAD_L - PAD_R;
const PLOT_H = VB_H - PAD_T - PAD_B;

function _isMock() {
  try { return new URLSearchParams(location.search).get('ui_mock') === '1'; }
  catch (_e) { return false; }
}

function _esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function _key() { return _mode + '|' + _metric; }

function _url() {
  return _isMock() ? '/data/ui_mock/perf_curve.json'
    : `/api/perf-curve?mode=${encodeURIComponent(_mode)}&metric=${encodeURIComponent(_metric)}`;
}

function _fmtMmSs(minute) {
  const m = Math.max(0, Math.floor(Number(minute) || 0));
  return `${m}:00`;
}

function _fmtVal(v) {
  const n = Number(v) || 0;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(Math.round(n));
}

function _modeBar() {
  const modeBtns = _MODES.map((m) =>
    `<button type="button" class="pf-mode-btn${m === _mode ? ' is-active' : ''}" ` +
    `data-pf-mode="${m}" role="tab" aria-selected="${m === _mode}">${m.toUpperCase()}</button>`
  ).join('');
  const metricBtns = _METRICS.map(([k, lbl]) =>
    `<button type="button" class="pf-metric-btn${k === _metric ? ' is-active' : ''}" ` +
    `data-pf-metric="${k}" aria-pressed="${k === _metric}">${_esc(lbl)}</button>`
  ).join('');
  return (
    `<div class="pf-controls">` +
    `<div class="pf-modes" role="tablist" aria-label="Mode">${modeBtns}</div>` +
    `<div class="pf-metrics" role="group" aria-label="Metric">${metricBtns}</div>` +
    `</div>`
  );
}

// Build a polyline points string for one series over the shared scales,
// dropping null points (a thin-tail gap just shortens the line).
function _poly(minutes, sel, xMin, xSpan, yMax) {
  const pts = [];
  minutes.forEach((row) => {
    const v = sel(row);
    if (v === null || v === undefined) return;
    const fx = xSpan > 0 ? (row.minute - xMin) / xSpan : 0;
    const x = PAD_L + fx * PLOT_W;
    const fy = yMax > 0 ? Math.max(0, Math.min(1, Number(v) / yMax)) : 0;
    const y = PAD_T + (1 - fy) * PLOT_H;
    pts.push(`${x.toFixed(1)},${y.toFixed(1)}`);
  });
  return pts.join(' ');
}

function _svg(minutes) {
  const xs = minutes.map((r) => r.minute);
  const xMin = Math.min(...xs, 0);
  const xMax = Math.max(...xs, 1);
  const xSpan = xMax - xMin || 1;
  let yMax = 0;
  minutes.forEach((r) => {
    if (r.win_avg != null) yMax = Math.max(yMax, Number(r.win_avg));
    if (r.loss_avg != null) yMax = Math.max(yMax, Number(r.loss_avg));
  });
  if (yMax <= 0) return '';
  const winPts = _poly(minutes, (r) => r.win_avg, xMin, xSpan, yMax);
  const lossPts = _poly(minutes, (r) => r.loss_avg, xMin, xSpan, yMax);
  const yTop = PAD_T;
  const yBot = PAD_T + PLOT_H;
  const yMid = PAD_T + PLOT_H / 2;
  return (
    `<svg class="pf-svg" viewBox="0 0 ${VB_W} ${VB_H}" preserveAspectRatio="none" ` +
    `role="img" aria-label="average ${_esc(_metric)} per minute, wins vs losses">` +
    `<line class="pf-axis" x1="${PAD_L}" y1="${yTop}" x2="${PAD_L}" y2="${yBot}"></line>` +
    `<line class="pf-axis" x1="${PAD_L}" y1="${yBot}" x2="${PAD_L + PLOT_W}" y2="${yBot}"></line>` +
    `<line class="pf-grid" x1="${PAD_L}" y1="${yMid.toFixed(1)}" x2="${(PAD_L + PLOT_W).toFixed(1)}" y2="${yMid.toFixed(1)}"></line>` +
    (lossPts ? `<polyline class="pf-line pf-line-loss" points="${lossPts}"></polyline>` : '') +
    (winPts ? `<polyline class="pf-line pf-line-win" points="${winPts}"></polyline>` : '') +
    `<text class="pf-ylab" x="4" y="${(yTop + 4).toFixed(0)}">${_esc(_fmtVal(yMax))}</text>` +
    `<text class="pf-ylab" x="4" y="${(yMid + 4).toFixed(0)}">${_esc(_fmtVal(yMax / 2))}</text>` +
    `<text class="pf-ylab" x="4" y="${yBot.toFixed(0)}">0</text>` +
    `<text class="pf-xlab" x="${PAD_L}" y="${(VB_H - 8).toFixed(0)}">0:00</text>` +
    `<text class="pf-xlab pf-xlab-end" x="${(PAD_L + PLOT_W).toFixed(0)}" y="${(VB_H - 8).toFixed(0)}">${_esc(_fmtMmSs(xMax))}</text>` +
    `</svg>`
  );
}

function _html(data) {
  const minutes = (data && data.minutes) || [];
  const n = (data && data.n_games) ? data.n_games : 0;
  if (!n || minutes.length < 2) {
    return _modeBar() +
      `<div class="pf-empty">Not enough ${_esc(_mode.toUpperCase())} ` +
      `games with timeline data tracked yet.</div>`;
  }
  const svg = _svg(minutes);
  if (!svg) {
    return _modeBar() + `<div class="pf-empty">No curve to draw yet.</div>`;
  }
  const unit = _metric === 'gold' ? 'gold' : 'creep score';
  return (
    _modeBar() +
    `<div class="pf-chart">${svg}</div>` +
    `<div class="pf-legend">` +
    `<span class="pf-legend-item pf-win">Wins</span>` +
    `<span class="pf-legend-item pf-loss">Losses</span>` +
    `</div>` +
    `<div class="pf-caption">Average cumulative ${_esc(unit)} per minute over your own ` +
    `${_esc(_mode.toUpperCase())} games (n=${n}), split by result. A win line pulling ` +
    `away early reads as snowballing your leads; a flat loss line reads as stalling there. ` +
    `Thin minutes (under ${(data && data.min_games_n) || 5} games) are dropped.</div>`
  );
}

function _wire(mount) {
  const ctl = mount.querySelector('.pf-controls');
  if (!ctl || ctl._wired) return;
  ctl._wired = true;
  ctl.addEventListener('click', (e) => {
    const t = e.target;
    if (!t || !t.closest) return;
    const mb = t.closest('.pf-mode-btn');
    if (mb) {
      const m = mb.getAttribute('data-pf-mode');
      if (m && m !== _mode) { _mode = m; _sig = ''; renderPerfCurve(); }
      return;
    }
    const xb = t.closest('.pf-metric-btn');
    if (xb) {
      const k = xb.getAttribute('data-pf-metric');
      if (k && k !== _metric) { _metric = k; _sig = ''; renderPerfCurve(); }
    }
  });
}

function _paint(data) {
  const mount = document.getElementById(_MOUNT);
  if (!mount) return;
  const sig = _key() + '|' + JSON.stringify(data && data.minutes) + '|' + (data && data.n_games);
  if (sig === _sig) return;
  _sig = sig;
  mount.innerHTML = _html(data);
  _wire(mount);
}

function _degraded() {
  const mount = document.getElementById(_MOUNT);
  if (mount) {
    mount.innerHTML = _modeBar() + `<div class="pf-empty">Game-flow stats unavailable.</div>`;
    _wire(mount);
  }
}

/** Render the Game Flow tab. Idempotent - safe on every tab activation. */
export function renderPerfCurve() {
  const mount = document.getElementById(_MOUNT);
  if (!mount) return;
  const key = _key();
  const now = Date.now();
  const cached = _CACHE[key];
  if (cached && _TS[key] && (now - _TS[key]) < _TTL_MS) { _paint(cached); return; }
  if (_INFLIGHT[key]) return;
  _INFLIGHT[key] = true;
  fetch(_url(), { headers: { 'Accept': 'application/json' } })
    .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
    .then((data) => {
      if (!data || data.ok === false) { _degraded(); return; }
      _CACHE[key] = data; _TS[key] = Date.now();
      if (_key() === key) _paint(data);
    })
    .catch(() => { _degraded(); })
    .finally(() => { _INFLIGHT[key] = false; });
}

// --- test hooks -----------------------------------------------------
export const __test = { _svg, _html, _poly, _fmtVal, _fmtMmSs, VB_W, VB_H };
