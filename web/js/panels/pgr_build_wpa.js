/* Post-Game "Your Build, Graded by Your Career" WPA strip (item 275, PGR
 * reframe S2 - docs/PGR_REFRAME_S2.md).
 *
 * The connective tissue the reframe spec calls for: ties RC's career WPA
 * lenses (item-WPA + skill-WPA) to THIS match's actual loadout. For the
 * operator's final items of the reviewed match it shows each completed
 * legendary's CAREER item-WPA residual (+/- pp + confidence bar from
 * GET /api/item-wpa), and for the reviewed champion it shows the three
 * basics' CAREER first-maxed skill-WPA (GET /api/skill-wpa), best
 * max-order highlighted.
 *
 * Distinct from the s219-removed DS-picks (those were recommendations);
 * this is a retrospective: "how have these buys / this max order actually
 * paid off for YOU". DESCRIPTIVE personal-corpus lens, not a meta winrate.
 *
 * Career WPA is match-INVARIANT (an aggregate over the whole corpus), so
 * the two route fetches are module-cached and reused across renders; only
 * the match's items + champion_id change per render. Fail-soft: a missing
 * route / empty corpus hides the strip rather than erroring the PGR.
 */
import { ITEMS } from '../lib/items_index.js';

const MOUNT_ID = 'pgr-build-wpa-mount';

// Items that never carry a career item-WPA chip even if present in the
// final inventory: trinkets + the empty slot. Components / boots simply
// have no item-WPA entry and fall through to "no chip".
const _SKIP_ITEM_IDS = new Set([0, 3340, 3363, 3364, 3330]);

// --- icon + format helpers (mirror build_insights.js) ---------------
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
  return `<img class="pbw-item-icon" src="${localUrl}" alt="" loading="lazy" onerror="${onErr}">`;
}
function _confSegments(n) {
  const nn = Number(n) || 0;
  const shrink = nn / (nn + 5);
  let filled = Math.round(shrink * 5);
  if (filled < 1) filled = 1;
  if (filled > 5) filled = 5;
  return filled;
}
function _signedPP(wpa) {
  const pp = Number(wpa) * 100;
  return (pp >= 0 ? '+' : '') + pp.toFixed(1);
}

// --- module-cached career WPA (match-invariant) ---------------------
const _CAREER = { itemById: null, skillByChamp: null, promise: null };

function _isMock() {
  return !!(document.body && document.body.dataset.uiMock === '1');
}

function _indexItems(items) {
  const out = {};
  (items || []).forEach((it) => {
    if (it && it.item_id != null) out[it.item_id] = it;
  });
  return out;
}
function _indexSkills(items) {
  // champion_id -> [rows], one per basic slot.
  const out = {};
  (items || []).forEach((it) => {
    if (!it || it.champion_id == null) return;
    (out[it.champion_id] = out[it.champion_id] || []).push(it);
  });
  return out;
}

function _loadCareer() {
  if (_CAREER.promise) return _CAREER.promise;
  const item = fetch('/api/item-wpa?min_n=20', { cache: 'no-store' })
    .then((r) => (r && r.ok ? r.json() : null))
    .then((d) => (d && d.ok && Array.isArray(d.items) ? d.items : []))
    .catch(() => []);
  const skill = fetch('/api/skill-wpa?min_n=20', { cache: 'no-store' })
    .then((r) => (r && r.ok ? r.json() : null))
    .then((d) => (d && d.ok && Array.isArray(d.items) ? d.items : []))
    .catch(() => []);
  _CAREER.promise = Promise.all([item, skill]).then(([its, sks]) => {
    _CAREER.itemById = _indexItems(its);
    _CAREER.skillByChamp = _indexSkills(sks);
    return _CAREER;
  });
  return _CAREER.promise;
}

// --- html builders --------------------------------------------------
function _chipHtml(wpa, n) {
  const cls = Number(wpa) >= 0 ? 'pbw-pos' : 'pbw-neg';
  const filled = _confSegments(n);
  let segs = '';
  for (let i = 0; i < 5; i++) {
    segs += `<span class="pbw-seg ${cls}${i < filled ? ' is-on' : ''}"></span>`;
  }
  return (
    `<span class="pbw-chip ${cls}" title="career WPA over ${Number(n) || 0} buys">` +
    `<span class="pbw-chip-val">${_signedPP(wpa)}</span>` +
    `<span class="pbw-chip-conf">${segs}</span></span>`
  );
}

function _itemCellHtml(iid, itemById) {
  const row = itemById[iid];
  const name = (row && row.name) || '';
  const chip = row ? _chipHtml(row.wpa, row.n) : '<span class="pbw-chip pbw-na">no data</span>';
  return (
    `<div class="pbw-item" title="${name}">${_itemImgTag(iid)}${chip}</div>`
  );
}

function _skillRowHtml(champId, skillByChamp) {
  const rows = (skillByChamp[champId] || []).slice();
  if (!rows.length) return '';
  // Best (highest wpa) max-order gets the highlight.
  let bestWpa = -Infinity;
  rows.forEach((r) => { if (Number(r.wpa) > bestWpa) bestWpa = Number(r.wpa); });
  const order = { Q: 0, W: 1, E: 2 };
  rows.sort((a, b) => (order[a.skill] ?? 9) - (order[b.skill] ?? 9));
  const cells = rows.map((r) => {
    const best = Number(r.wpa) === bestWpa ? ' is-best' : '';
    return (
      `<div class="pbw-skill${best}">` +
      `<span class="pbw-skill-key">${r.skill}</span>` +
      `${_chipHtml(r.wpa, r.n)}</div>`
    );
  }).join('');
  return (
    `<div class="pbw-skill-row">` +
    `<span class="pbw-strip-label">Max order</span>${cells}</div>`
  );
}

function _strH(match, itemById, skillByChamp) {
  const en = (match && match.enriched) || {};
  const items = (en.items || []).filter(
    (iid) => iid && !_SKIP_ITEM_IDS.has(iid),
  );
  if (!items.length && en.champion_id == null) return '';
  const champ = (match && match.champion) || '';
  const itemCells = items.map((iid) => _itemCellHtml(iid, itemById)).join('');
  const skillRow = en.champion_id != null
    ? _skillRowHtml(en.champion_id, skillByChamp) : '';
  return (
    `<div class="pbw-card">` +
    `<div class="pbw-head">` +
    `<span class="pbw-title">YOUR BUILD - GRADED BY YOUR CAREER</span>` +
    `<span class="pbw-sub">${champ ? champ + ' . ' : ''}career WPA over your match history (descriptive, not meta)</span>` +
    `</div>` +
    `<div class="pbw-item-row"><span class="pbw-strip-label">Items</span>${itemCells}</div>` +
    skillRow +
    `</div>`
  );
}

/** Render the build-WPA strip for the reviewed match. Idempotent.
 *  `data` is the /api/last-match payload (or its mock fixture). */
export function renderPgrBuildWpa(data) {
  const mount = document.getElementById(MOUNT_ID);
  if (!mount) return;
  if (!data || !data.found || !data.match) {
    mount.innerHTML = '';
    mount.hidden = true;
    return;
  }
  const match = data.match;
  // Mock fixtures may carry embedded career maps so the audit renders
  // without a populated corpus; otherwise fetch the live career routes.
  const embedded = _isMock() && match.enriched
    && (match.enriched.career_item_wpa || match.enriched.career_skill_wpa);
  const draw = (itemById, skillByChamp) => {
    try {
      const html = _strH(match, itemById || {}, skillByChamp || {});
      mount.innerHTML = html;
      mount.hidden = !html;
    } catch (_e) {
      mount.innerHTML = '';
      mount.hidden = true;
    }
  };
  if (embedded) {
    draw(_indexItems(match.enriched.career_item_wpa || []),
         _indexSkills(match.enriched.career_skill_wpa || []));
    return;
  }
  _loadCareer().then((c) => draw(c.itemById, c.skillByChamp))
    .catch(() => draw({}, {}));
}

// --- test hooks -----------------------------------------------------
export const __test = {
  _confSegments,
  _signedPP,
  _indexItems,
  _indexSkills,
  _itemCellHtml,
  _skillRowHtml,
  _strH,
  _SKIP_ITEM_IDS,
};
