/* Build Insights view (item 273, competitor-WPA lift).
 *
 * Consumes the shipped GET /api/item-wpa as a sortable WPA table:
 *   Item (icon + name) | WPA (signed pp + confidence bar) | Buys (n) |
 *   Expected WP (%) | Win Rate (%)
 *
 * Selection-bias-corrected item performance over the operator's match
 * history (Win Rate minus Expected WP). DESCRIPTIVE personal-corpus
 * lens, not a meta winrate - trust rows by the sample bar.
 *
 * The route already exists + is 5min TTL-cached server-side; this panel
 * fetches once per view-mount (+ debounced min_n re-fetch) and sorts the
 * already-fetched array client-side (no network on a column-header click).
 *
 * ?ui_mock=1 short-circuits to web/data/ui_mock/build_insights.json so
 * #build-insights renders without a populated rewind DB (mirrors the
 * last_match.js _lmMockLoad pattern).
 */
import { ITEMS } from '../lib/items_index.js';

const MOUNT_ID = 'bi-table-mount';
const DEFAULT_MIN_N = 20;

// Item-icon URL: local DDragon mirror first (matches last_match.js +
// item_build.js); the onerror handler falls back to the official CDN
// at the same patch, then hides the broken <img> so the name text
// remains the legible fallback.
function _ddragonVersion() {
  return (ITEMS && ITEMS.version) || '16.10.1';
}
function _itemImgTag(iid) {
  if (!iid && iid !== 0) return '';
  const ver = _ddragonVersion();
  const localUrl = `/data/ddragon/${ver}/img/item/${iid}.png`;
  const cdnUrl = `https://ddragon.leagueoflegends.com/cdn/${ver}/img/item/${iid}.png`;
  const onErr =
    `if(this.dataset.cdn){this.style.display='none';}` +
    `else{this.dataset.cdn='1';this.src='${cdnUrl}';}`;
  return `<img class="bi-item-icon" src="${localUrl}" alt="" loading="lazy" onerror="${onErr}">`;
}

// Confidence bar: how much of the raw wpa survives shrink, in 5 segments.
// shrink(n) = n / (n + 5); segments_filled = round(shrink(n) * 5),
// clamped 1..5. n=5 -> ~3, n=20 -> ~4, n>=45 -> 5.
function _confSegments(n) {
  const nn = Number(n) || 0;
  const shrink = nn / (nn + 5);
  let filled = Math.round(shrink * 5);
  if (filled < 1) filled = 1;
  if (filled > 5) filled = 5;
  return filled;
}

function _pct(frac) {
  // 0..1 fraction -> "NN.N%"
  return (Number(frac) * 100).toFixed(1) + '%';
}

function _signedPP(wpa) {
  // wpa is a 0..1 residual; display as signed percentage points.
  const pp = Number(wpa) * 100;
  const sign = pp >= 0 ? '+' : '';
  return sign + pp.toFixed(2);
}

// --- module state (one view, one table) ----------------------------
const _ST = {
  items: [],          // last fetched rows (sorted in place)
  minN: DEFAULT_MIN_N,
  sortKey: 'wpa',     // wpa | n | observed_winrate
  sortDir: 'desc',    // desc | asc
  loaded: false,
  inFlight: false,
  debounceTimer: null,
  wired: false,
};

function _isMock() {
  return !!(document.body && document.body.dataset.uiMock === '1');
}

let _mockPromise = null;
function _mockLoad() {
  if (_mockPromise) return _mockPromise;
  _mockPromise = fetch('/data/ui_mock/build_insights.json', { cache: 'no-store' })
    .then((r) => (r && r.ok ? r.json() : null))
    .catch(() => null);
  return _mockPromise;
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
  const iid = it && (it.item_id != null ? it.item_id : '');
  const name = (it && it.name) || ('Item ' + iid);
  const wpa = (it && it.wpa) || 0;
  const cls = wpa >= 0 ? 'bi-pos' : 'bi-neg';
  const segMax = 5;
  const filled = _confSegments(it && it.n);
  let segs = '';
  for (let i = 0; i < segMax; i++) {
    const on = i < filled ? ' is-on' : '';
    segs += `<span class="bi-seg ${cls}${on}"></span>`;
  }
  return (
    `<tr>` +
    `<td class="bi-c-item"><span class="bi-item">${_itemImgTag(iid)}` +
    `<span class="bi-item-name">${name}</span></span></td>` +
    `<td class="bi-c-wpa">` +
    `<span class="bi-wpa-val ${cls}">${_signedPP(wpa)}</span>` +
    `<span class="bi-conf" title="sample confidence (${(it && it.n) || 0} buys)">${segs}</span>` +
    `</td>` +
    `<td class="bi-c-n">${(it && it.n) || 0}</td>` +
    `<td class="bi-c-exp">${_pct(it && it.expected_winrate)}</td>` +
    `<td class="bi-c-wr">${_pct(it && it.observed_winrate)}</td>` +
    `</tr>`
  );
}

function _tableHtml() {
  _sortRows();
  const head =
    `<thead><tr>` +
    `<th class="bi-c-item">Item</th>` +
    `<th class="bi-c-wpa bi-sortable" data-sort="wpa" tabindex="0" role="button">WPA${_arrow('wpa')}</th>` +
    `<th class="bi-c-n bi-sortable" data-sort="n" tabindex="0" role="button">Buys${_arrow('n')}</th>` +
    `<th class="bi-c-exp">Expected WP</th>` +
    `<th class="bi-c-wr bi-sortable" data-sort="observed_winrate" tabindex="0" role="button">Win Rate${_arrow('observed_winrate')}</th>` +
    `</tr></thead>`;
  const body = '<tbody>' + _ST.items.map(_rowHtml).join('') + '</tbody>';
  return `<table class="bi-table">${head}${body}</table>`;
}

function _render() {
  const mount = document.getElementById(MOUNT_ID);
  if (!mount) return;
  if (_ST.inFlight && !_ST.loaded) {
    mount.innerHTML = '<div class="bi-empty">loading...</div>';
    return;
  }
  if (!_ST.items || _ST.items.length === 0) {
    mount.innerHTML =
      '<div class="bi-empty">No item data yet - play a few games (need at least ' +
      _ST.minN + ' buys per item).</div>';
    return;
  }
  mount.innerHTML = _tableHtml();
  _wireHeaders(mount);
}

function _wireHeaders(mount) {
  const ths = mount.querySelectorAll('th.bi-sortable');
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
  const url = `/api/item-wpa?min_n=${encodeURIComponent(_ST.minN)}`;
  fetch(url, { cache: 'no-store' })
    .then((r) => (r && r.ok ? r.json() : null))
    .then((d) => finish(d && d.ok ? d : null))
    .catch(() => finish(null));
}

function _wireControlsOnce() {
  if (_ST.wired) return;
  const inp = document.getElementById('bi-min-n');
  if (!inp) return;
  _ST.wired = true;
  inp.value = String(_ST.minN);
  inp.addEventListener('input', () => {
    const v = parseInt(inp.value, 10);
    if (isNaN(v) || v < 1) return;
    _ST.minN = v;
    if (_ST.debounceTimer) clearTimeout(_ST.debounceTimer);
    _ST.debounceTimer = setTimeout(() => {
      _mockPromise = null; // re-fetch the live route on min_n change
      _fetch();
    }, 300);
  });
}

/** Render the Build Insights view. Idempotent - safe on every view switch. */
export function renderBuildInsights() {
  try {
    _wireControlsOnce();
    if (!_ST.loaded && !_ST.inFlight) {
      _fetch();
    } else {
      _render();
    }
  } catch (_e) {
    const mount = document.getElementById(MOUNT_ID);
    if (mount) mount.innerHTML = '<div class="bi-empty">unavailable</div>';
  }
}

// --- test hooks -----------------------------------------------------
export const __test = {
  _confSegments,
  _signedPP,
  _pct,
  _ST,
  _sortRows,
};
