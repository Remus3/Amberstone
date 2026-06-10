/* Rune-WPA table panel (item 273 extension to RUNES - the pre-game WPA
 * analog of the item-WPA / skill-WPA build-insights tables).
 *
 * Consumes GET /api/rune-wpa as a sortable WPA table mirroring
 * build_insights.js:
 *   Rune (icon + name) | Slot (keystone/minor badge) | WPA (signed pp +
 *   confidence bar) | Games (n) | Expected WP (%) | Win Rate (%)
 *
 * A rune is a PRE-GAME choice, so its expected baseline is the win-prob at
 * the start-of-game frame (near coinflip), and the residual (Win Rate minus
 * Expected WP) is how much that keystone / minor rune correlates with
 * winning beyond the lobby it was chosen in. DESCRIPTIVE personal-corpus
 * lens, NOT a meta winrate. Runes are an even WEAKER per-choice signal than
 * items (a keystone is largely champion-fixed), so shrink + min_n are
 * load-bearing - trust rows by the sample bar. Stat shards are excluded.
 *
 * The route is 5min TTL-cached server-side; the panel fetches once
 * (+ debounced min_n re-fetch) and sorts the already-fetched array
 * client-side (no network on a column-header click).
 *
 * ?ui_mock=1 short-circuits to web/data/ui_mock/rune_wpa.json so the panel
 * renders without a populated rewind DB (mirrors build_insights.js).
 *
 * Self-contained: renders into #rune-wpa-table-mount with its own rwa-
 * prefixed classes. The nav / router wiring + the 5-phase fixture audit
 * are the integration owner's job.
 */
import { ITEMS } from '../lib/items_index.js';

const MOUNT_ID = 'rune-wpa-table-mount';
const DEFAULT_MIN_N = 20;

function _ddragonVersion() {
  return (ITEMS && ITEMS.version) || '16.10.1';
}

// Rune-icon URL: the API row carries the DDragon perk-images relative path
// (e.g. perk-images/Styles/Domination/Electrocute/Electrocute.png). DDragon
// serves these at cdn/img/<icon>; try the local mirror first, then the
// official CDN, then hide the broken <img> so the name text remains the
// legible fallback. perk-images is patch-invariant (no version segment).
function _runeImgTag(icon) {
  if (!icon) return '';
  const ver = _ddragonVersion();
  const localUrl = `/data/ddragon/${ver}/img/${icon}`;
  const cdnUrl = `https://ddragon.leagueoflegends.com/cdn/img/${icon}`;
  const onErr =
    `if(this.dataset.cdn){this.style.display='none';}` +
    `else{this.dataset.cdn='1';this.src='${cdnUrl}';}`;
  return `<img class="rwa-rune-icon" src="${localUrl}" alt="" loading="lazy" onerror="${onErr}">`;
}

// Confidence bar: how much of the raw wpa survives shrink, in 5 segments.
// shrink(n) = n / (n + 5); segments_filled = round(shrink(n) * 5),
// clamped 1..5. Same formula as build_insights.js _confSegments.
function _confSegments(n) {
  const nn = Number(n) || 0;
  const shrink = nn / (nn + 5);
  let filled = Math.round(shrink * 5);
  if (filled < 1) filled = 1;
  if (filled > 5) filled = 5;
  return filled;
}

function _pct(frac) {
  return (Number(frac) * 100).toFixed(1) + '%';
}

function _signedPP(wpa) {
  const pp = Number(wpa) * 100;
  const sign = pp >= 0 ? '+' : '';
  return sign + pp.toFixed(2);
}

function _confCellHtml(it) {
  const wpa = (it && it.wpa) || 0;
  const cls = wpa >= 0 ? 'rwa-pos' : 'rwa-neg';
  const filled = _confSegments(it && it.n);
  let segs = '';
  for (let i = 0; i < 5; i++) {
    const on = i < filled ? ' is-on' : '';
    segs += `<span class="rwa-seg ${cls}${on}"></span>`;
  }
  return (
    `<span class="rwa-wpa-val ${cls}">${_signedPP(wpa)}</span>` +
    `<span class="rwa-conf" title="sample confidence (${(it && it.n) || 0})">${segs}</span>`
  );
}

function _slotBadgeHtml(it) {
  const kind = (it && it.slot_kind) || 'minor';
  const label = kind === 'keystone' ? 'KEY' : 'MIN';
  return `<span class="rwa-slot-badge rwa-slot-${kind}" title="${kind}">${label}</span>`;
}

function _runeCellHtml(it) {
  const icon = (it && it.icon) || '';
  const rid = it && (it.rune_id != null ? it.rune_id : '');
  const name = (it && it.name) || ('Rune ' + rid);
  return (
    `<td class="rwa-c-rune"><span class="rwa-rune">${_runeImgTag(icon)}` +
    `<span class="rwa-rune-name">${name}</span></span></td>` +
    `<td class="rwa-c-slot">${_slotBadgeHtml(it)}</td>`
  );
}

const _ST = {
  items: [],
  sortKey: 'wpa',
  sortDir: 'desc',
  loaded: false,
  inFlight: false,
  minN: DEFAULT_MIN_N,
  debounceTimer: null,
  wired: false,
};
let _MOCK = null;

function _isMock() {
  return !!(document.body && document.body.dataset.uiMock === '1');
}

function _mockLoad() {
  if (_MOCK) return _MOCK;
  _MOCK = fetch('/data/ui_mock/rune_wpa.json', { cache: 'no-store' })
    .then((r) => (r && r.ok ? r.json() : null))
    .catch(() => null);
  return _MOCK;
}

function _sortRows() {
  const key = _ST.sortKey;
  const dir = _ST.sortDir === 'asc' ? 1 : -1;
  _ST.items.sort((a, b) => {
    const av = Number(a && a[key]) || 0;
    const bv = Number(b && b[key]) || 0;
    if (av < bv) return -1 * dir;
    if (av > bv) return 1 * dir;
    return 0;
  });
}

function _arrow(col) {
  if (_ST.sortKey !== col) return '';
  return _ST.sortDir === 'asc' ? ' ^' : ' v';
}

function _rowHtml(it) {
  return `<tr>${_runeCellHtml(it)}` +
    `<td class="rwa-c-wpa">${_confCellHtml(it)}</td>` +
    `<td class="rwa-c-n">${(it && it.n) || 0}</td>` +
    `<td class="rwa-c-exp">${_pct(it && it.expected_winrate)}</td>` +
    `<td class="rwa-c-wr">${_pct(it && it.observed_winrate)}</td>` +
    `</tr>`;
}

function _tableHtml() {
  _sortRows();
  const head =
    `<thead><tr>` +
    `<th class="rwa-c-head">Rune</th>` +
    `<th class="rwa-c-slot">Slot</th>` +
    `<th class="rwa-c-wpa rwa-sortable" data-sort="wpa" tabindex="0" role="button">WPA${_arrow('wpa')}</th>` +
    `<th class="rwa-c-n rwa-sortable" data-sort="n" tabindex="0" role="button">Games${_arrow('n')}</th>` +
    `<th class="rwa-c-exp">Expected WP</th>` +
    `<th class="rwa-c-wr rwa-sortable" data-sort="observed_winrate" tabindex="0" role="button">Win Rate${_arrow('observed_winrate')}</th>` +
    `</tr></thead>`;
  const body = '<tbody>' + _ST.items.map((it) => _rowHtml(it)).join('') + '</tbody>';
  return `<table class="rwa-table">${head}${body}</table>`;
}

function _render() {
  const mount = document.getElementById(MOUNT_ID);
  if (!mount) return;
  if (_ST.inFlight && !_ST.loaded) {
    mount.innerHTML = '<div class="rwa-empty">loading...</div>';
    return;
  }
  if (!_ST.items || _ST.items.length === 0) {
    mount.innerHTML =
      '<div class="rwa-empty">No rune data yet - play a few games (need at least ' +
      _ST.minN + ' games per rune).</div>';
    return;
  }
  mount.innerHTML = _tableHtml();
  _wireHeaders(mount);
}

function _wireHeaders(mount) {
  const ths = mount.querySelectorAll('th.rwa-sortable');
  ths.forEach((th) => {
    const handler = () => {
      const key = th.getAttribute('data-sort');
      if (!key) return;
      if (_ST.sortKey === key) {
        _ST.sortDir = _ST.sortDir === 'desc' ? 'asc' : 'desc';
      } else {
        _ST.sortKey = key;
        _ST.sortDir = 'desc';
      }
      _render();
    };
    th.addEventListener('click', handler);
    th.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handler(); }
    });
  });
}

function _fetch() {
  if (_ST.inFlight) return;
  _ST.inFlight = true;
  _render();
  const finish = (data) => {
    _ST.inFlight = false;
    _ST.loaded = true;
    _ST.items = (data && Array.isArray(data.items)) ? data.items.slice() : [];
    _render();
  };
  if (_isMock()) {
    _mockLoad().then((d) => finish(d)).catch(() => finish(null));
    return;
  }
  const url = `/api/rune-wpa?min_n=${encodeURIComponent(_ST.minN)}`;
  fetch(url, { cache: 'no-store' })
    .then((r) => (r && r.ok ? r.json() : null))
    .then((d) => finish(d && d.ok ? d : null))
    .catch(() => finish(null));
}

function _ensureFetched() {
  if (!_ST.loaded && !_ST.inFlight) _fetch();
  else _render();
}

function _wireControlsOnce() {
  if (_ST.wired) return;
  const inp = document.getElementById('rwa-min-n');
  if (!inp) return;
  _ST.wired = true;
  inp.value = String(_ST.minN);
  inp.addEventListener('input', () => {
    const v = parseInt(inp.value, 10);
    if (isNaN(v) || v < 1) return;
    _ST.minN = v;
    if (_ST.debounceTimer) clearTimeout(_ST.debounceTimer);
    _ST.debounceTimer = setTimeout(() => {
      _MOCK = null;
      _ST.loaded = false;
      _ensureFetched();
    }, 300);
  });
}

/** Render the rune-WPA table panel. Idempotent - safe on every view switch. */
export function renderRuneWpa() {
  try {
    _wireControlsOnce();
    _ensureFetched();
  } catch (_e) {
    const mount = document.getElementById(MOUNT_ID);
    if (mount) mount.innerHTML = '<div class="rwa-empty">unavailable</div>';
  }
}

// --- test hooks -----------------------------------------------------
export const __test = {
  _confSegments,
  _signedPP,
  _pct,
  _ST,
  _sortRows,
  _runeImgTag,
  _slotBadgeHtml,
  _runeCellHtml,
};
