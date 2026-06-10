/* Build Insights view (item 273 item-WPA + item 275 skill-WPA tab +
 * rune-WPA tab, competitor-WPA lift).
 *
 * Three tabs share one render engine:
 *   Items  -> GET /api/item-wpa  (the shipped item table, default tab):
 *     Item (icon + name) | WPA (signed pp + confidence bar) | Buys (n) |
 *     Expected WP (%) | Win Rate (%)
 *   Skills -> GET /api/skill-wpa (the first-maxed basic, ult excluded):
 *     Champion (icon + name) | Skill (Q/W/E badge) | WPA (signed pp +
 *     confidence bar) | Games (n) | Expected WP (%) | Win Rate (%)
 *   Runes  -> GET /api/rune-wpa  (the per-rune pick, stat shards excluded):
 *     Rune (icon + name) | Slot (keystone/minor badge) | WPA (signed pp +
 *     confidence bar) | Picks (n) | Expected WP (%) | Win Rate (%)
 *
 * All are selection-bias-corrected residuals (Win Rate minus Expected WP)
 * over the operator's match history - DESCRIPTIVE personal-corpus lenses,
 * not meta winrates. Skills are a WEAKER signal than items: shrink + min_n
 * are load-bearing, trust rows by the sample bar. Each route is 5min
 * TTL-cached server-side; each tab fetches once per tab-switch (+ debounced
 * min_n re-fetch) and sorts the already-fetched array client-side (no
 * network on a column-header click).
 *
 * ?ui_mock=1 short-circuits each tab to its fixture under web/data/ui_mock/
 * (build_insights.json / build_insights_skill.json / rune_wpa.json) so
 * #build-insights renders without a populated rewind DB (mirrors the
 * last_match.js _lmMockLoad pattern).
 */
import { ITEMS, CHAMPS } from '../lib/items_index.js';

const ITEM_MOUNT_ID = 'bi-table-mount';
const SKILL_MOUNT_ID = 'bi-skill-table-mount';
const RUNE_MOUNT_ID = 'bi-rune-table-mount';
const DEFAULT_MIN_N = 20;

function _ddragonVersion() {
  return (ITEMS && ITEMS.version) || '16.10.1';
}

// Item-icon URL: local DDragon mirror first (matches last_match.js +
// item_build.js); the onerror handler falls back to the official CDN
// at the same patch, then hides the broken <img> so the name text
// remains the legible fallback.
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

// Champion-square URL: resolve championId -> DDragon slug via CHAMPS.byId
// (async-hydrated from /data/champions_index.json by items_index.js).
// Mirrors last_match.js:692-693. When the index is not yet loaded the
// slug is empty -> name-only render (documented fallback). Same local-then
// -CDN onerror chain as the item icon.
function _champImgTag(cid) {
  const slug = (CHAMPS && CHAMPS.byId && CHAMPS.byId[String(cid)]) || '';
  if (!slug) return '';
  const ver = (CHAMPS && CHAMPS.version) || _ddragonVersion();
  const localUrl = `/data/ddragon/${ver}/img/champion/${slug}.png`;
  const cdnUrl = `https://ddragon.leagueoflegends.com/cdn/${ver}/img/champion/${slug}.png`;
  const onErr =
    `if(this.dataset.cdn){this.style.display='none';}` +
    `else{this.dataset.cdn='1';this.src='${cdnUrl}';}`;
  return `<img class="bi-champ-icon" src="${localUrl}" alt="" loading="lazy" onerror="${onErr}">`;
}

// Rune-icon URL: the API row carries the DDragon perk-images relative path
// (e.g. perk-images/Styles/Domination/Electrocute/Electrocute.png). DDragon
// serves these at cdn/img/<icon>; try the local mirror first, then the
// official CDN, then hide the broken <img> so the name text remains the
// legible fallback. perk-images is patch-invariant (no version segment in
// the relative path itself).
function _runeImgTag(icon) {
  if (!icon) return '';
  const ver = _ddragonVersion();
  const localUrl = `/data/ddragon/${ver}/img/${icon}`;
  const cdnUrl = `https://ddragon.leagueoflegends.com/cdn/img/${icon}`;
  const onErr =
    `if(this.dataset.cdn){this.style.display='none';}` +
    `else{this.dataset.cdn='1';this.src='${cdnUrl}';}`;
  return `<img class="bi-rune-icon" src="${localUrl}" alt="" loading="lazy" onerror="${onErr}">`;
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

function _confCellHtml(it) {
  const wpa = (it && it.wpa) || 0;
  const cls = wpa >= 0 ? 'bi-pos' : 'bi-neg';
  const filled = _confSegments(it && it.n);
  let segs = '';
  for (let i = 0; i < 5; i++) {
    const on = i < filled ? ' is-on' : '';
    segs += `<span class="bi-seg ${cls}${on}"></span>`;
  }
  return (
    `<span class="bi-wpa-val ${cls}">${_signedPP(wpa)}</span>` +
    `<span class="bi-conf" title="sample confidence (${(it && it.n) || 0})">${segs}</span>`
  );
}

// --- per-tab state + config -----------------------------------------
function _mkState() {
  return {
    items: [],
    sortKey: 'wpa',
    sortDir: 'desc',
    loaded: false,
    inFlight: false,
  };
}

const _ITEMS_TAB = {
  key: 'items',
  mountId: ITEM_MOUNT_ID,
  endpoint: '/api/item-wpa',
  mockUrl: '/data/ui_mock/build_insights.json',
  emptyMsg: 'No item data yet - play a few games',
  emptyUnit: 'buys per item',
  headLabel: 'Item',
  nLabel: 'Buys',
  rowCells(it) {
    const iid = it && (it.item_id != null ? it.item_id : '');
    const name = (it && it.name) || ('Item ' + iid);
    return (
      `<td class="bi-c-item"><span class="bi-item">${_itemImgTag(iid)}` +
      `<span class="bi-item-name">${name}</span></span></td>`
    );
  },
};

const _SKILLS_TAB = {
  key: 'skills',
  mountId: SKILL_MOUNT_ID,
  endpoint: '/api/skill-wpa',
  mockUrl: '/data/ui_mock/build_insights_skill.json',
  emptyMsg: 'No skill data yet - play a few games',
  emptyUnit: 'games per champion skill-max',
  headLabel: 'Champion',
  extraHead: 'Skill',
  nLabel: 'Games',
  rowCells(it) {
    const cid = it && (it.champion_id != null ? it.champion_id : '');
    const name = (it && it.champion) || ('Champ ' + cid);
    const skill = (it && it.skill) || '?';
    return (
      `<td class="bi-c-champ"><span class="bi-champ">${_champImgTag(cid)}` +
      `<span class="bi-champ-name">${name}</span></span></td>` +
      `<td class="bi-c-skill"><span class="bi-skill-badge">${skill}</span></td>`
    );
  },
};

// Slot-kind badge for a rune row: KEY (keystone) vs MIN (minor).
function _slotBadgeHtml(it) {
  const kind = (it && it.slot_kind) || 'minor';
  const label = kind === 'keystone' ? 'KEY' : 'MIN';
  return `<span class="bi-slot-badge bi-slot-${kind}" title="${kind}">${label}</span>`;
}

const _RUNES_TAB = {
  key: 'runes',
  mountId: RUNE_MOUNT_ID,
  endpoint: '/api/rune-wpa',
  mockUrl: '/data/ui_mock/rune_wpa.json',
  emptyMsg: 'No rune data yet - play a few games',
  emptyUnit: 'picks per rune',
  headLabel: 'Rune',
  extraHead: 'Slot',
  nLabel: 'Picks',
  rowCells(it) {
    const rid = it && (it.rune_id != null ? it.rune_id : '');
    const name = (it && it.name) || ('Rune ' + rid);
    const icon = (it && it.icon) || '';
    return (
      `<td class="bi-c-rune"><span class="bi-rune">${_runeImgTag(icon)}` +
      `<span class="bi-rune-name">${name}</span></span></td>` +
      `<td class="bi-c-slot">${_slotBadgeHtml(it)}</td>`
    );
  },
};

const _ST = {
  items: _mkState(),
  skills: _mkState(),
  runes: _mkState(),
  minN: DEFAULT_MIN_N,
  active: 'items',
  debounceTimer: null,
  wired: false,
};
// Mock promises are per-tab so a min_n change can null + re-fetch one.
const _MOCK = { items: null, skills: null, runes: null };

function _isMock() {
  return !!(document.body && document.body.dataset.uiMock === '1');
}

function _mockLoad(tab) {
  if (_MOCK[tab.key]) return _MOCK[tab.key];
  _MOCK[tab.key] = fetch(tab.mockUrl, { cache: 'no-store' })
    .then((r) => (r && r.ok ? r.json() : null))
    .catch(() => null);
  return _MOCK[tab.key];
}

function _sortRows(st) {
  const key = st.sortKey;
  const dir = st.sortDir === 'asc' ? 1 : -1;
  st.items.sort((a, b) => {
    const av = Number(a && a[key]) || 0;
    const bv = Number(b && b[key]) || 0;
    if (av < bv) return -1 * dir;
    if (av > bv) return 1 * dir;
    return 0;
  });
}

function _arrow(st, col) {
  if (st.sortKey !== col) return '';
  return st.sortDir === 'asc' ? ' ^' : ' v';
}

function _rowHtml(tab, it) {
  return `<tr>${tab.rowCells(it)}` +
    `<td class="bi-c-wpa">${_confCellHtml(it)}</td>` +
    `<td class="bi-c-n">${(it && it.n) || 0}</td>` +
    `<td class="bi-c-exp">${_pct(it && it.expected_winrate)}</td>` +
    `<td class="bi-c-wr">${_pct(it && it.observed_winrate)}</td>` +
    `</tr>`;
}

function _tableHtml(tab, st) {
  _sortRows(st);
  const head =
    `<thead><tr>` +
    `<th class="bi-c-head">${tab.headLabel}</th>` +
    (tab.extraHead ? `<th class="bi-c-extra">${tab.extraHead}</th>` : '') +
    `<th class="bi-c-wpa bi-sortable" data-sort="wpa" tabindex="0" role="button">WPA${_arrow(st, 'wpa')}</th>` +
    `<th class="bi-c-n bi-sortable" data-sort="n" tabindex="0" role="button">${tab.nLabel}${_arrow(st, 'n')}</th>` +
    `<th class="bi-c-exp">Expected WP</th>` +
    `<th class="bi-c-wr bi-sortable" data-sort="observed_winrate" tabindex="0" role="button">Win Rate${_arrow(st, 'observed_winrate')}</th>` +
    `</tr></thead>`;
  const body = '<tbody>' + st.items.map((it) => _rowHtml(tab, it)).join('') + '</tbody>';
  return `<table class="bi-table">${head}${body}</table>`;
}

function _render(tab) {
  const st = _ST[tab.key];
  const mount = document.getElementById(tab.mountId);
  if (!mount) return;
  if (st.inFlight && !st.loaded) {
    mount.innerHTML = '<div class="bi-empty">loading...</div>';
    return;
  }
  if (!st.items || st.items.length === 0) {
    mount.innerHTML =
      '<div class="bi-empty">' + tab.emptyMsg + ' (need at least ' +
      _ST.minN + ' ' + tab.emptyUnit + ').</div>';
    return;
  }
  mount.innerHTML = _tableHtml(tab, st);
  _wireHeaders(tab, mount);
}

function _wireHeaders(tab, mount) {
  const st = _ST[tab.key];
  const ths = mount.querySelectorAll('th.bi-sortable');
  ths.forEach((th) => {
    const handler = () => {
      const key = th.getAttribute('data-sort');
      if (!key) return;
      if (st.sortKey === key) {
        st.sortDir = st.sortDir === 'desc' ? 'asc' : 'desc';
      } else {
        st.sortKey = key;
        st.sortDir = 'desc';
      }
      _render(tab);
    };
    th.addEventListener('click', handler);
    th.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handler(); }
    });
  });
}

function _fetch(tab) {
  const st = _ST[tab.key];
  if (st.inFlight) return;
  st.inFlight = true;
  _render(tab);
  const finish = (data) => {
    st.inFlight = false;
    st.loaded = true;
    st.items = (data && Array.isArray(data.items)) ? data.items.slice() : [];
    _render(tab);
  };
  if (_isMock()) {
    _mockLoad(tab).then((d) => finish(d)).catch(() => finish(null));
    return;
  }
  const url = `${tab.endpoint}?min_n=${encodeURIComponent(_ST.minN)}`;
  fetch(url, { cache: 'no-store' })
    .then((r) => (r && r.ok ? r.json() : null))
    .then((d) => finish(d && d.ok ? d : null))
    .catch(() => finish(null));
}

function _tabByKey(key) {
  if (key === 'skills') return _SKILLS_TAB;
  if (key === 'runes') return _RUNES_TAB;
  return _ITEMS_TAB;
}

// Fetch-once-per-tab-switch: only fetch when this tab has not loaded.
function _ensureFetched(tab) {
  const st = _ST[tab.key];
  if (!st.loaded && !st.inFlight) _fetch(tab);
  else _render(tab);
}

function _activateTab(key) {
  _ST.active = key;
  // Toggle tab-button active state + pane visibility.
  const btns = document.querySelectorAll('#bi-tabs .bi-tab');
  btns.forEach((b) => {
    const on = b.getAttribute('data-bi-tab') === key;
    b.classList.toggle('is-active', on);
    b.setAttribute('aria-selected', on ? 'true' : 'false');
  });
  document.querySelectorAll('[data-bi-pane]').forEach((p) => {
    p.hidden = p.getAttribute('data-bi-pane') !== key;
  });
  _ensureFetched(_tabByKey(key));
}

function _wireControlsOnce() {
  if (_ST.wired) return;
  const inp = document.getElementById('bi-min-n');
  const tabsEl = document.getElementById('bi-tabs');
  if (!inp || !tabsEl) return;
  _ST.wired = true;
  inp.value = String(_ST.minN);
  inp.addEventListener('input', () => {
    const v = parseInt(inp.value, 10);
    if (isNaN(v) || v < 1) return;
    _ST.minN = v;
    if (_ST.debounceTimer) clearTimeout(_ST.debounceTimer);
    _ST.debounceTimer = setTimeout(() => {
      // min_n changed: invalidate both caches + the loaded flags so the
      // active tab re-fetches now + the other tab re-fetches on next switch.
      _MOCK.items = null;
      _MOCK.skills = null;
      _MOCK.runes = null;
      _ST.items.loaded = false;
      _ST.skills.loaded = false;
      _ST.runes.loaded = false;
      _ensureFetched(_tabByKey(_ST.active));
    }, 300);
  });
  tabsEl.addEventListener('click', (e) => {
    const btn = e.target && e.target.closest ? e.target.closest('.bi-tab') : null;
    if (!btn) return;
    const key = btn.getAttribute('data-bi-tab');
    if (key && key !== _ST.active) _activateTab(key);
  });
}

/** Render the Build Insights view. Idempotent - safe on every view switch. */
export function renderBuildInsights() {
  try {
    _wireControlsOnce();
    _ensureFetched(_tabByKey(_ST.active));
  } catch (_e) {
    const mount = document.getElementById(ITEM_MOUNT_ID);
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
  _ITEMS_TAB,
  _SKILLS_TAB,
  _RUNES_TAB,
  _runeImgTag,
  _slotBadgeHtml,
};
