// Win-rate-by-game-length panel (Build Insights "Game Length" tab). Renders the
// tracked player's win % per match-duration bucket as horizontal bars over the
// operator's OWN rewind corpus - the win-rate-by-game-length surface popularized
// by public stats sites, here personal + descriptive (no global / Riot / Claude
// data). Read: bars sloping DOWN across longer buckets = an early-game / snowball
// tendency; sloping UP = a scaling / late-game tendency.
//
// Backend wire:
//   GET /api/duration-winrate?mode=<aram|sr|arena>
//   Response: { ok, mode, champion, n, min_bucket_n,
//     buckets: [{label, lo_s, hi_s, wins, games, winrate|null}, ...] }
//   A bucket with games < min_bucket_n returns winrate null -> a muted "-" with
//   no bar (too thin to trust).
//   ?ui_mock=1 -> /data/ui_mock/duration_winrate.json fixture (renders without a
//   populated rewind DB; mirrors build_insights.js).
//
// Discipline mirrors player_gpi.js / spike_curve.js: pure ESM, ASCII only, per-
// mode cache + TTL, inflight guard, sig-dedup so an unchanged payload skips the
// rebuild, no DOM writes outside renderDurationWinrate(), degraded-mode text on
// error (never a raw error string - repo Error-Handling rule).

const _MOUNT = 'bi-duration-mount';
const _MODES = ['aram', 'sr', 'arena'];
const _CACHE = Object.create(null);     // mode -> response JSON
const _INFLIGHT = Object.create(null);
const _TS = Object.create(null);
const _TTL_MS = 5 * 60 * 1000;
let _sig = '';
let _mode = 'aram';

function _isMock() {
  try { return new URLSearchParams(location.search).get('ui_mock') === '1'; }
  catch (_e) { return false; }
}

function _esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function _url(mode) {
  return _isMock() ? '/data/ui_mock/duration_winrate.json'
                   : `/api/duration-winrate?mode=${encodeURIComponent(mode)}`;
}

function _barRow(b) {
  const wr = b.winrate;
  const hasWr = (wr !== null && wr !== undefined);
  const pct = hasWr ? Math.max(0, Math.min(100, wr)) : 0;
  const cls = !hasWr ? 'dw-dim' : (wr >= 50 ? 'dw-good' : 'dw-bad');
  const val = hasWr ? `${Number(wr).toFixed(1)}%` : '-';
  return (
    `<div class="dw-row">` +
      `<div class="dw-label">${_esc(b.label)}</div>` +
      `<div class="dw-track"><div class="dw-fill ${cls}" style="width:${pct}%"></div></div>` +
      `<div class="dw-val ${cls}">${val}<span class="dw-n">n=${b.games | 0}</span></div>` +
    `</div>`
  );
}

function _modeBar() {
  const btns = _MODES.map((m) =>
    `<button type="button" class="dw-mode-btn${m === _mode ? ' is-active' : ''}" ` +
    `data-dw-mode="${m}" role="tab" aria-selected="${m === _mode}">${m.toUpperCase()}</button>`
  ).join('');
  return `<div class="dw-modes" role="tablist" aria-label="Mode">${btns}</div>`;
}

function _html(data) {
  const buckets = (data && data.buckets) || [];
  const n = (data && data.n) ? data.n : 0;
  if (!n) {
    return _modeBar() +
      `<div class="dw-empty">Not enough ${_esc(_mode.toUpperCase())} ` +
      `games tracked yet.</div>`;
  }
  const minN = (data && data.min_bucket_n) || 5;
  const rows = buckets.map(_barRow).join('');
  return (
    _modeBar() +
    `<div class="dw-chart">${rows}</div>` +
    `<div class="dw-caption">Win % by game length over your own ` +
    `${_esc(_mode.toUpperCase())} games (n=${n}). Bars sloping down across ` +
    `longer games read as an early-game / snowball tendency; sloping up reads ` +
    `as a scaling / late-game tendency. Buckets under ${minN} games show "-" ` +
    `(too thin to trust).</div>`
  );
}

function _wireModes(mount) {
  const bar = mount.querySelector('.dw-modes');
  if (!bar || bar._wired) return;
  bar._wired = true;
  bar.addEventListener('click', (e) => {
    const btn = e.target && e.target.closest ? e.target.closest('.dw-mode-btn') : null;
    if (!btn) return;
    const m = btn.getAttribute('data-dw-mode');
    if (m && m !== _mode) { _mode = m; _sig = ''; renderDurationWinrate(); }
  });
}

function _paint(data) {
  const mount = document.getElementById(_MOUNT);
  if (!mount) return;
  const sig = _mode + '|' + JSON.stringify(data && data.buckets) + '|' + (data && data.n);
  if (sig === _sig) return;
  _sig = sig;
  mount.innerHTML = _html(data);
  _wireModes(mount);
}

function _degraded() {
  const mount = document.getElementById(_MOUNT);
  if (mount) {
    mount.innerHTML = _modeBar() +
      `<div class="dw-empty">Game-length stats unavailable.</div>`;
    _wireModes(mount);
  }
}

/** Render the Game Length tab. Idempotent - safe on every tab activation. */
export function renderDurationWinrate() {
  const mount = document.getElementById(_MOUNT);
  if (!mount) return;
  const mode = _mode;
  const now = Date.now();
  const cached = _CACHE[mode];
  if (cached && _TS[mode] && (now - _TS[mode]) < _TTL_MS) { _paint(cached); return; }
  if (_INFLIGHT[mode]) return;
  _INFLIGHT[mode] = true;
  fetch(_url(mode), { headers: { 'Accept': 'application/json' } })
    .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
    .then((data) => {
      if (!data || data.ok === false) { _degraded(); return; }
      _CACHE[mode] = data; _TS[mode] = Date.now();
      if (_mode === mode) _paint(data);
    })
    .catch(() => { _degraded(); })
    .finally(() => { _INFLIGHT[mode] = false; });
}
