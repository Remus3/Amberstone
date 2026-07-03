// Win-rate-by-game-length panel (Build Insights "Game Length" tab). Renders the
// tracked player's win % per match-duration bucket as horizontal bars over the
// operator's OWN rewind corpus - the win-rate-by-game-length surface popularized
// by public stats sites, here personal + descriptive (no global / Riot / Claude
// data). R71 F1 adds a champion filter (picker next to the mode bar; ALL =
// unfiltered) and R71 F2 a computed early/late tendency chip.
//
// Backend wire:
//   GET /api/duration-winrate?mode=<aram|sr|arena>[&champion=<riot int id>]
//   Response: { ok, mode, champion, n, min_bucket_n,
//     buckets: [{label, lo_s, hi_s, wins, games, winrate|null}, ...] }
//   A bucket with games < min_bucket_n returns winrate null -> a muted "-" with
//   no bar (too thin to trust).
//   ?ui_mock=1 -> /data/ui_mock/duration_winrate.json fixture (renders without a
//   populated rewind DB; mirrors build_insights.js).
//
// Champion picker: CHAMPS.byId (async-hydrated by items_index.js) maps numeric
// riot id -> DDragon slug string; byName maps normalized lowercase -> slug. The
// datalist offers slugs; a typed/picked name resolves client-side to the int id
// for &champion=. If CHAMPS never hydrates the datalist stays empty and the
// panel degrades to ALL-only (resolution just misses).
//
// Tendency chip: n-weighted winrate delta = weighted mean of the SECOND half of
// non-null buckets minus the FIRST half (weights = games). It is a descriptive
// lean label (late-leaning / early-leaning / flat), never a win-probability
// claim. Fewer than 2 non-null buckets in either half -> no chip.
//
// Discipline mirrors player_gpi.js / spike_curve.js: pure ESM, ASCII only, per-
// (mode|champ) cache + TTL, inflight guard, sig-dedup so an unchanged payload
// skips the rebuild, no DOM writes outside renderDurationWinrate(), degraded-
// mode text on error (never a raw error string - repo Error-Handling rule).

import { CHAMPS } from '../lib/items_index.js';

const _MOUNT = 'bi-duration-mount';
const _MODES = ['aram', 'sr', 'arena'];
const _CACHE = Object.create(null);     // `${mode}|${champ||'all'}` -> response JSON
const _INFLIGHT = Object.create(null);
const _TS = Object.create(null);
const _TTL_MS = 5 * 60 * 1000;
// Tendency threshold in winrate percentage points - below it the lean is
// noise and the chip reads "flat".
const _CHIP_DELTA = 5;
let _sig = '';
let _mode = 'aram';
let _champId = null;    // riot int id; null = ALL (unfiltered)
let _champName = '';    // resolved DDragon slug for display
let _slugToId = null;   // lazy lowercase-slug -> int id (from CHAMPS.byId)

function _isMock() {
  try { return new URLSearchParams(location.search).get('ui_mock') === '1'; }
  catch (_e) { return false; }
}

function _esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function _key(mode, champ) {
  return `${mode}|${champ || 'all'}`;
}

function _url(mode, champ) {
  if (_isMock()) return '/data/ui_mock/duration_winrate.json';
  const base = `/api/duration-winrate?mode=${encodeURIComponent(mode)}`;
  return champ ? `${base}&champion=${encodeURIComponent(champ)}` : base;
}

// Resolve typed/picked text to {id, slug} via CHAMPS; null when unknown or
// CHAMPS has not hydrated yet (caller keeps the current filter - graceful).
function _resolveChamp(text) {
  const norm = String(text || '').toLowerCase().replace(/[^a-z0-9]/g, '');
  if (!norm || !CHAMPS || !CHAMPS.byId) return null;
  if (!_slugToId) {
    _slugToId = Object.create(null);
    for (const [id, slug] of Object.entries(CHAMPS.byId)) {
      _slugToId[String(slug).toLowerCase()] = id | 0;
    }
  }
  const slug = (CHAMPS.byName && CHAMPS.byName[norm]) ||
    (Object.prototype.hasOwnProperty.call(_slugToId, norm)
      ? CHAMPS.byId[String(_slugToId[norm])] : null);
  if (!slug) return null;
  const id = _slugToId[String(slug).toLowerCase()];
  return id ? { id, slug: String(slug) } : null;
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

function _champPicker() {
  const byId = (CHAMPS && CHAMPS.byId) || {};
  const opts = Object.values(byId).map(String).sort()
    .map((s) => `<option value="${_esc(s)}"></option>`).join('');
  return (
    `<div class="dw-champ${_champId ? ' is-filtered' : ''}">` +
      `<input class="dw-champ-input" type="text" list="dw-champ-list" ` +
      `placeholder="All champions" aria-label="Champion filter" ` +
      `value="${_esc(_champName)}">` +
      `<button type="button" class="dw-champ-clear" data-dw-champ-clear="1" ` +
      `title="Clear champion filter">ALL</button>` +
      `<datalist id="dw-champ-list">${opts}</datalist>` +
    `</div>`
  );
}

// n-weighted winrate lean over the fetched buckets. Splits the non-null
// buckets into symmetric halves (odd counts drop the middle bucket) and
// returns null (no chip) when either half has < 2 non-null buckets.
function _tendency(buckets) {
  const rows = (buckets || []).filter((b) =>
    b && b.winrate !== null && b.winrate !== undefined);
  const half = Math.floor(rows.length / 2);
  if (half < 2) return null;
  const wmean = (rs) => {
    let w = 0, s = 0;
    rs.forEach((b) => {
      const g = b.games | 0;
      w += g; s += g * Number(b.winrate);
    });
    return w > 0 ? (s / w) : null;
  };
  const first = wmean(rows.slice(0, half));
  const second = wmean(rows.slice(rows.length - half));
  if (first === null || second === null) return null;
  const delta = second - first;
  if (delta >= _CHIP_DELTA) return { label: 'late-leaning', cls: 'dw-good' };
  if (delta <= -_CHIP_DELTA) return { label: 'early-leaning', cls: 'dw-bad' };
  return { label: 'flat', cls: 'dw-dim' };
}

function _chip(buckets) {
  const t = _tendency(buckets);
  if (!t) return '';
  return `<span class="dw-chip ${t.cls}" title="n-weighted win% lean, ` +
    `longer-game buckets vs shorter - a tendency label, not a win ` +
    `probability">${t.label}</span>`;
}

function _head(buckets) {
  return `<div class="dw-head">${_modeBar()}${_champPicker()}${_chip(buckets)}</div>`;
}

function _html(data) {
  const buckets = (data && data.buckets) || [];
  const n = (data && data.n) ? data.n : 0;
  const who = _champName ? `${_esc(_champName)} ` : '';
  if (!n) {
    return _head(null) +
      `<div class="dw-empty">Not enough ${who}${_esc(_mode.toUpperCase())} ` +
      `games tracked yet.</div>`;
  }
  const minN = (data && data.min_bucket_n) || 5;
  const rows = buckets.map(_barRow).join('');
  return (
    _head(buckets) +
    `<div class="dw-chart">${rows}</div>` +
    `<div class="dw-caption">Win % by game length over your own ` +
    `${who}${_esc(_mode.toUpperCase())} games (n=${n}). The tendency chip is ` +
    `the n-weighted read of the slope: bars rising into longer games = ` +
    `late-leaning / scaling, falling = early-leaning / snowball (a lean ` +
    `label, not a win probability). Buckets under ${minN} games show "-" ` +
    `(too thin to trust).</div>`
  );
}

function _wire(mount) {
  const bar = mount.querySelector('.dw-modes');
  if (bar && !bar._wired) {
    bar._wired = true;
    bar.addEventListener('click', (e) => {
      const btn = e.target && e.target.closest ? e.target.closest('.dw-mode-btn') : null;
      if (!btn) return;
      const m = btn.getAttribute('data-dw-mode');
      if (m && m !== _mode) { _mode = m; _sig = ''; renderDurationWinrate(); }
    });
  }
  const input = mount.querySelector('.dw-champ-input');
  if (input && !input._wired) {
    input._wired = true;
    // 'change' fires on datalist pick and on blur/Enter after typing.
    input.addEventListener('change', () => {
      const raw = input.value.trim();
      if (!raw) { _setChamp(null, ''); return; }
      const hit = _resolveChamp(raw);
      if (hit) _setChamp(hit.id, hit.slug);
      // Unresolved text keeps the current filter (no fetch, no error text).
    });
  }
  const clear = mount.querySelector('[data-dw-champ-clear]');
  if (clear && !clear._wired) {
    clear._wired = true;
    clear.addEventListener('click', () => _setChamp(null, ''));
  }
}

function _setChamp(id, slug) {
  if (id === _champId && slug === _champName) return;
  _champId = id;
  _champName = slug || '';
  _sig = '';
  renderDurationWinrate();
}

function _paint(data) {
  const mount = document.getElementById(_MOUNT);
  if (!mount) return;
  const sig = _key(_mode, _champId) + '|' +
    JSON.stringify(data && data.buckets) + '|' + (data && data.n);
  if (sig === _sig) return;
  _sig = sig;
  mount.innerHTML = _html(data);
  _wire(mount);
}

function _degraded() {
  const mount = document.getElementById(_MOUNT);
  if (mount) {
    // Reset the sig: otherwise a refetch after a transient failure whose
    // payload matches the pre-failure sig early-returns in _paint and the
    // degraded text stays stuck on screen.
    _sig = '';
    mount.innerHTML = _head(null) +
      `<div class="dw-empty">Game-length stats unavailable.</div>`;
    _wire(mount);
  }
}

// CHAMPS hydrates async: if the panel painted before the champions index
// landed, force one re-render (sig reset) so the datalist fills. Only when
// the mount already has content - never an eager first fetch. Re-render via
// renderDurationWinrate() keeps the no-DOM-writes-outside-render rule.
document.addEventListener('rc:champs-ready', () => {
  _slugToId = null;
  const mount = document.getElementById(_MOUNT);
  if (mount && mount.firstChild) { _sig = ''; renderDurationWinrate(); }
});

/** Render the Game Length tab. Idempotent - safe on every tab activation. */
export function renderDurationWinrate() {
  const mount = document.getElementById(_MOUNT);
  if (!mount) return;
  const mode = _mode;
  const champ = _champId;
  const key = _key(mode, champ);
  const now = Date.now();
  const cached = _CACHE[key];
  if (cached && _TS[key] && (now - _TS[key]) < _TTL_MS) { _paint(cached); return; }
  if (_INFLIGHT[key]) return;
  _INFLIGHT[key] = true;
  fetch(_url(mode, champ), { headers: { 'Accept': 'application/json' } })
    .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
    .then((data) => {
      if (!data || data.ok === false) { _degraded(); return; }
      _CACHE[key] = data; _TS[key] = Date.now();
      if (_key(_mode, _champId) === key) _paint(data);
    })
    .catch(() => { _degraded(); })
    .finally(() => { _INFLIGHT[key] = false; });
}
