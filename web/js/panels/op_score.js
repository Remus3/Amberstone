// Per-interval OP-Score panel (Build Insights "OP Score" tab). Plots the tracked
// player's per-minute composite 0-100 PERFORMANCE score over the operator's OWN
// rewind corpus, split into the games WON (green) vs LOST (red) - an aggregator-A-style
// performance line, here personal + descriptive (no global / Riot / Claude data).
// DISTINCT from the Game Flow tab (perf_curve.js, one raw gold/CS stat): this
// folds normalized gold + xp + cs + damage pace into one transparent index.
// Read: a win line that sits above the loss line early = "I play measurably
// better in the games I win"; the two converging late = "late game looks the
// same win or lose".
//
// Backend wire:
//   GET /api/op-score-curve?mode=<aram|sr|arena>
//   Response: { ok, mode, metric, champion, n_games, min_games_n, weights,
//     minutes: [{minute, win_avg|null, win_n, loss_avg|null, loss_n}, ...] }
//   win_avg/loss_avg are 0-100 composite scores. A minute with a series below
//   min_games_n returns that series null (too thin to trust) and is dropped.
//   ?ui_mock=1 -> /data/ui_mock/op_score.json fixture (renders without a
//   populated rewind DB; mirrors perf_curve.js).
//
// Discipline mirrors perf_curve.js: pure ESM, ASCII only, per-key cache + TTL,
// inflight guard, sig-dedup, no DOM writes outside renderOpScore(), degraded-
// mode text on error (never a raw error string). The Y-axis is a fixed 0-100
// (the score is already normalized) - no dynamic yMax like perf_curve.

const _MOUNT = 'bi-opscore-mount';
const _MODES = ['aram', 'sr', 'arena'];
const _CACHE = Object.create(null);     // key -> response JSON
const _INFLIGHT = Object.create(null);
const _TS = Object.create(null);
const _TTL_MS = 5 * 60 * 1000;
let _sig = '';
let _mode = 'aram';

// SVG geometry (unitless; CSS scales responsively).
const VB_W = 600;
const VB_H = 210;
const PAD_L = 46;
const PAD_R = 12;
const PAD_T = 12;
const PAD_B = 26;
const PLOT_W = VB_W - PAD_L - PAD_R;
const PLOT_H = VB_H - PAD_T - PAD_B;
const Y_MAX = 100;                       // composite score is already 0-100

function _isMock() {
  try { return new URLSearchParams(location.search).get('ui_mock') === '1'; }
  catch (_e) { return false; }
}

function _esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function _key() { return _mode; }

function _url() {
  return _isMock() ? '/data/ui_mock/op_score.json'
    : `/api/op-score-curve?mode=${encodeURIComponent(_mode)}`;
}

function _fmtMmSs(minute) {
  const m = Math.max(0, Math.floor(Number(minute) || 0));
  return `${m}:00`;
}

function _modeBar() {
  const modeBtns = _MODES.map((m) =>
    `<button type="button" class="op-mode-btn${m === _mode ? ' is-active' : ''}" ` +
    `data-op-mode="${m}" role="tab" aria-selected="${m === _mode}">${m.toUpperCase()}</button>`
  ).join('');
  return (
    `<div class="op-controls">` +
    `<div class="op-modes" role="tablist" aria-label="Mode">${modeBtns}</div>` +
    `</div>`
  );
}

// Build a polyline points string for one series over the shared scales,
// dropping null points (a thin-tail gap just shortens the line).
function _poly(minutes, sel, xMin, xSpan) {
  const pts = [];
  minutes.forEach((row) => {
    const v = sel(row);
    if (v === null || v === undefined) return;
    const fx = xSpan > 0 ? (row.minute - xMin) / xSpan : 0;
    const x = PAD_L + fx * PLOT_W;
    const fy = Math.max(0, Math.min(1, Number(v) / Y_MAX));
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
  const winPts = _poly(minutes, (r) => r.win_avg, xMin, xSpan);
  const lossPts = _poly(minutes, (r) => r.loss_avg, xMin, xSpan);
  if (!winPts && !lossPts) return '';
  const yTop = PAD_T;
  const yBot = PAD_T + PLOT_H;
  const yMid = PAD_T + PLOT_H / 2;
  return (
    `<svg class="op-svg" viewBox="0 0 ${VB_W} ${VB_H}" preserveAspectRatio="none" ` +
    `role="img" aria-label="composite OP-Score per minute, wins vs losses">` +
    `<line class="op-axis" x1="${PAD_L}" y1="${yTop}" x2="${PAD_L}" y2="${yBot}"></line>` +
    `<line class="op-axis" x1="${PAD_L}" y1="${yBot}" x2="${PAD_L + PLOT_W}" y2="${yBot}"></line>` +
    `<line class="op-grid" x1="${PAD_L}" y1="${yMid.toFixed(1)}" x2="${(PAD_L + PLOT_W).toFixed(1)}" y2="${yMid.toFixed(1)}"></line>` +
    (lossPts ? `<polyline class="op-line op-line-loss" points="${lossPts}"></polyline>` : '') +
    (winPts ? `<polyline class="op-line op-line-win" points="${winPts}"></polyline>` : '') +
    `<text class="op-ylab" x="4" y="${(yTop + 4).toFixed(0)}">100</text>` +
    `<text class="op-ylab" x="4" y="${(yMid + 4).toFixed(0)}">50</text>` +
    `<text class="op-ylab" x="4" y="${yBot.toFixed(0)}">0</text>` +
    `<text class="op-xlab" x="${PAD_L}" y="${(VB_H - 8).toFixed(0)}">0:00</text>` +
    `<text class="op-xlab op-xlab-end" x="${(PAD_L + PLOT_W).toFixed(0)}" y="${(VB_H - 8).toFixed(0)}">${_esc(_fmtMmSs(xMax))}</text>` +
    `</svg>`
  );
}

function _html(data) {
  const minutes = (data && data.minutes) || [];
  const n = (data && data.n_games) ? data.n_games : 0;
  if (!n || minutes.length < 2) {
    return _modeBar() +
      `<div class="op-empty">Not enough ${_esc(_mode.toUpperCase())} ` +
      `games with timeline data tracked yet.</div>`;
  }
  const svg = _svg(minutes);
  if (!svg) {
    return _modeBar() + `<div class="op-empty">-</div>`;
  }
  return (
    _modeBar() +
    `<div class="op-chart">${svg}</div>` +
    `<div class="op-legend">` +
    `<span class="op-legend-item op-win">Wins</span>` +
    `<span class="op-legend-item op-loss">Losses</span>` +
    `</div>` +
    `<div class="op-caption">Per-minute composite performance score (0-100) over your own ` +
    `${_esc(_mode.toUpperCase())} games (n=${n}), split by result. A transparent blend of ` +
    `normalized gold, xp, CS and damage pace - each scaled against your own best pace at ` +
    `that minute. A win line above the loss line early reads as playing better in games you ` +
    `win; converging late reads as a similar late game either way. ` +
    `Thin minutes (under ${(data && data.min_games_n) || 5} games) are dropped.</div>`
  );
}

function _wire(mount) {
  const ctl = mount.querySelector('.op-controls');
  if (!ctl || ctl._wired) return;
  ctl._wired = true;
  ctl.addEventListener('click', (e) => {
    const t = e.target;
    if (!t || !t.closest) return;
    const mb = t.closest('.op-mode-btn');
    if (mb) {
      const m = mb.getAttribute('data-op-mode');
      if (m && m !== _mode) { _mode = m; _sig = ''; renderOpScore(); }
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
    mount.innerHTML = _modeBar() + `<div class="op-empty">OP-Score stats unavailable.</div>`;
    _wire(mount);
  }
}

/** Render the OP Score tab. Idempotent - safe on every tab activation. */
export function renderOpScore() {
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
export const __test = { _svg, _html, _poly, _fmtMmSs, VB_W, VB_H, Y_MAX };
