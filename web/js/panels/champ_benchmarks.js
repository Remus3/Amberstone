// Per-champion Benchmarks panel (Build Insights "Benchmarks" tab). Renders the
// operator's per-champion early-game stat distribution as a Aggregator-B-style table
// over RC's OWN tracked corpus (core.benchmarks champion_benchmarks.json) - the
// per-champion stat breakdown public stats sites show, here DESCRIPTIVE
// personal-corpus (your own baselines), not a global / meta / Riot / Claude
// winrate. Each metric cell headlines the MEDIAN (p50) with the p25-p75 spread
// shown as a sub + in a hover title; the Games column is the trust column (a
// stat is only as good as its sample).
//
// Backend wire:
//   GET /api/champ-benchmarks?mode=<sr|aram|arena>
//   Response: { ok, mode, n, min_games, metrics:[...5 keys...],
//     rows:[{champion, games, stats:{<metric>:{p50,p25,p75,avg,n}}}, ...] }
//   A mode with no rows returns n:0 -> the same empty state as duration_winrate.
//   ?ui_mock=1 -> /data/ui_mock/champ_benchmarks.json fixture (renders without a
//   populated benchmark file; mirrors build_insights.js).
//
// Discipline mirrors duration_winrate.js: pure ESM, ASCII only, per-mode cache +
// TTL, inflight guard, sig-dedup so an unchanged payload skips the rebuild, no
// DOM writes outside renderChampBenchmarks(), degraded-mode text on error (never
// a raw error string - repo Error-Handling rule).

import { CHAMPS, DDRAGON_FALLBACK_VERSION } from '../lib/items_index.js';

const _MOUNT = 'bi-bench-mount';
const _MODES = ['sr', 'aram', 'arena'];
const _CACHE = Object.create(null);     // mode -> response JSON
const _INFLIGHT = Object.create(null);
const _TS = Object.create(null);
const _TTL_MS = 5 * 60 * 1000;
let _sig = '';
let _mode = 'sr';

// Column metric key -> short header label. Order is the column order; it mirrors
// the route's COLUMN_METRICS so the header set always matches the data.
const _COLS = [
  ['cs_at_10', 'CS@10'],
  ['gold_at_10', 'Gold@10'],
  ['gold_at_15', 'Gold@15'],
  ['kill_participation_pct', 'KP%'],
  ['level_at_10', 'Lvl@10'],
];

function _isMock() {
  try { return new URLSearchParams(location.search).get('ui_mock') === '1'; }
  catch (_e) { return false; }
}

function _esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function _url(mode) {
  return _isMock() ? '/data/ui_mock/champ_benchmarks.json'
                   : `/api/champ-benchmarks?mode=${encodeURIComponent(mode)}`;
}

function _ddragonVersion() {
  return (CHAMPS && CHAMPS.version) || DDRAGON_FALLBACK_VERSION;
}

// Champ icon by slug, local DDragon mirror first then official CDN, then hide -
// copied onerror chain from build_insights.js _champImgTag. The benchmark rows
// already key on a DDragon champion id (e.g. "Vayne"), which IS the png slug, so
// no byId lookup is needed here (unlike build_insights, which starts from a
// numeric id). CHAMPS supplies the DDragon version for the mirror path.
function _champImgTag(champ) {
  const slug = String(champ || '');
  if (!slug) return '';
  const ver = _ddragonVersion();
  const localUrl = `/data/ddragon/${ver}/img/champion/${slug}.png`;
  const cdnUrl = `https://ddragon.leagueoflegends.com/cdn/${ver}/img/champion/${slug}.png`;
  const onErr =
    `if(this.dataset.cdn){this.style.display='none';}` +
    `else{this.dataset.cdn='1';this.src='${cdnUrl}';}`;
  return `<img class="cb-champ-icon" src="${localUrl}" alt="" loading="lazy" onerror="${onErr}">`;
}

function _fmt(v) {
  if (v === null || v === undefined) return '-';
  const n = Number(v);
  if (!isFinite(n)) return '-';
  // Whole-ish numbers (gold, level) read better without a trailing .0; sub-unit
  // metrics (CS@10, KP%) keep one decimal.
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}

function _statCell(stat) {
  if (!stat || stat.p50 === null || stat.p50 === undefined) {
    return `<td class="cb-stat cb-dim">-</td>`;
  }
  const p50 = _fmt(stat.p50);
  const p25 = _fmt(stat.p25);
  const p75 = _fmt(stat.p75);
  const nn = stat.n | 0;
  const title = `p25 ${p25} - p75 ${p75}, n=${nn}`;
  return (
    `<td class="cb-stat" title="${_esc(title)}">` +
      `<span class="cb-p50">${_esc(p50)}</span>` +
      `<span class="cb-range">${_esc(p25)}-${_esc(p75)}</span>` +
    `</td>`
  );
}

function _row(r) {
  const stats = (r && r.stats) || {};
  const cells = _COLS.map(([key]) => _statCell(stats[key])).join('');
  return (
    `<tr>` +
      `<td class="cb-c-champ"><span class="cb-champ">${_champImgTag(r.champion)}` +
        `<span class="cb-champ-name">${_esc(r.champion)}</span></span></td>` +
      cells +
      `<td class="cb-games">${r.games | 0}</td>` +
    `</tr>`
  );
}

function _modeBar() {
  const btns = _MODES.map((m) =>
    `<button type="button" class="cb-mode-btn${m === _mode ? ' is-active' : ''}" ` +
    `data-cb-mode="${m}" role="tab" aria-selected="${m === _mode}">${m.toUpperCase()}</button>`
  ).join('');
  return `<div class="cb-modes" role="tablist" aria-label="Mode">${btns}</div>`;
}

function _html(data) {
  const rows = (data && data.rows) || [];
  const n = (data && data.n) ? data.n : 0;
  if (!n) {
    return _modeBar() +
      `<div class="cb-empty">No ${_esc(_mode.toUpperCase())} ` +
      `benchmark data yet.</div>`;
  }
  const head = _COLS.map(([, label]) =>
    `<th class="cb-h-stat">${_esc(label)}</th>`).join('');
  const body = rows.map(_row).join('');
  const minG = (data && data.min_games) || 3;
  return (
    _modeBar() +
    `<div class="cb-table-wrap"><table class="cb-table">` +
      `<thead><tr>` +
        `<th class="cb-h-champ">Champion</th>` +
        head +
        `<th class="cb-h-games">Games</th>` +
      `</tr></thead>` +
      `<tbody>${body}</tbody>` +
    `</table></div>` +
    `<div class="cb-caption">Your own per-champion ` +
    `${_esc(_mode.toUpperCase())} baselines (median, with the p25-p75 spread). ` +
    `Descriptive personal-corpus - your own stat distribution, not a meta ` +
    `winrate. Each cell pairs with its Games sample; champions under ${minG} ` +
    `games are hidden (too thin to trust).</div>`
  );
}

function _wireModes(mount) {
  const bar = mount.querySelector('.cb-modes');
  if (!bar || bar._wired) return;
  bar._wired = true;
  bar.addEventListener('click', (e) => {
    const btn = e.target && e.target.closest ? e.target.closest('.cb-mode-btn') : null;
    if (!btn) return;
    const m = btn.getAttribute('data-cb-mode');
    if (m && m !== _mode) { _mode = m; _sig = ''; renderChampBenchmarks(); }
  });
}

function _paint(data) {
  const mount = document.getElementById(_MOUNT);
  if (!mount) return;
  const sig = _mode + '|' + JSON.stringify(data && data.rows) + '|' + (data && data.n);
  if (sig === _sig) return;
  _sig = sig;
  mount.innerHTML = _html(data);
  _wireModes(mount);
}

function _degraded() {
  const mount = document.getElementById(_MOUNT);
  if (mount) {
    mount.innerHTML = _modeBar() +
      `<div class="cb-empty">Benchmark stats unavailable.</div>`;
    _wireModes(mount);
  }
}

/** Render the Benchmarks tab. Idempotent - safe on every tab activation. */
export function renderChampBenchmarks() {
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
