/* Post-Game descriptive loadout strip (PGR reframe S5 -
 * docs/PGR_REFRAME_S2.md staging S5).
 *
 * The "augment-vs-rune variant" the reframe spec calls for. Mode-aware:
 *   SR / ARAM -> the rune page (keystone + primary minors + secondary
 *                runes) + summoner spells.
 *   Arena     -> the 6 picked augments (the defining Arena loadout) +
 *                summoner spells, INSTEAD of runes (spec line 85).
 *
 * DESCRIPTIVE only - runes / augments / summoner spells have no
 * purchase-frame, so they carry NO WPA residual (item 275 verify-first
 * established the ~0.5-baseline degeneracy). This card complements the
 * career-WPA strip (pgr_build_wpa.js, items + skill max-order) - that one
 * is "graded by your career", this one is "what you actually ran".
 *
 * Icon sources (all already served by RC, no new route):
 *   runes    -> GET /api/dictionary/runes (runesReforged) id -> {name,icon};
 *               icon is the perk-images path under the local ddragon mirror.
 *   spells   -> summoner_spells.js sumImg(id) / sumName(id) -> /icons/spells.
 *   augments -> GET /api/dictionary/augments id -> {name,icon_url,rarity}
 *               (the same dict the PGR roster augment strip uses, s-PGR-S2).
 * The two dict fetches are module-cached (patch-stable). Renders straight
 * from the loaded /api/last-match payload (or its ARAM/Arena mock under
 * ?ui_mock=1&mode=...), so all three mode variants are audit-capturable.
 * Idempotent. Fail-soft: a missing dict / empty loadout hides the card.
 */
import { sumImg, sumName } from '../lib/summoner_spells.js';
import { ITEMS, DDRAGON_FALLBACK_VERSION } from '../lib/items_index.js';

const MOUNT_ID = 'pgr-loadout-mount';

// Matches main.js _RP_DDRAGON_BASE - the local mirror that carries the
// perk-images tree. CDN is the onerror fallback (rune icons are unversioned
// on the CDN: /cdn/img/<perk-images-path>). Patch follows the hydrated
// items index so stale mirror dirs can be pruned.
function _runeLocalBase() {
  return '/data/ddragon/' + ((ITEMS && ITEMS.version) || DDRAGON_FALLBACK_VERSION) + '/img/';
}
const _RUNE_CDN_BASE = 'https://ddragon.leagueoflegends.com/cdn/img/';

// --- module-cached patch-stable dictionaries ------------------------
const _DICT = { runeById: null, augById: null, promise: null };

function _escHtml(s) {
  const div = document.createElement('div');
  div.textContent = String(s == null ? '' : s);
  return div.innerHTML;
}

function _indexRunes(trees) {
  const by = {};
  (Array.isArray(trees) ? trees : []).forEach((tree) => {
    if (tree && tree.id != null) {
      by['style:' + tree.id] = { name: tree.name || '', icon: tree.icon || '' };
    }
    (tree && tree.slots ? tree.slots : []).forEach((slot) => {
      (slot && slot.runes ? slot.runes : []).forEach((rune) => {
        if (rune && rune.id != null) {
          by[String(rune.id)] = { name: rune.name || '', icon: rune.icon || '' };
        }
      });
    });
  });
  return by;
}

function _loadDicts() {
  if (_DICT.promise) return _DICT.promise;
  const runes = fetch('/api/dictionary/runes', { cache: 'force-cache' })
    .then((r) => (r && r.ok ? r.json() : null))
    .then((trees) => _indexRunes(trees))
    .catch(() => ({}));
  const augs = fetch('/api/dictionary/augments', { cache: 'force-cache' })
    .then((r) => (r && r.ok ? r.json() : null))
    .then((d) => (d && d.augments) || {})
    .catch(() => ({}));
  _DICT.promise = Promise.all([runes, augs]).then(([r, a]) => {
    _DICT.runeById = r;
    _DICT.augById = a;
    return _DICT;
  });
  return _DICT.promise;
}

// --- icon tag builders ----------------------------------------------
function _runeIconTag(perkId, runeById, opts) {
  const o = opts || {};
  const row = runeById[String(perkId)];
  const icon = row && row.icon;
  const name = (row && row.name) || '';
  const cls = 'pld-rune' + (o.key ? ' pld-rune-key' : '') + (o.style ? ' pld-rune-style' : '');
  if (!icon) {
    return `<span class="${cls} pld-rune-noimg" title="${_escHtml(name)}"></span>`;
  }
  const local = _runeLocalBase() + icon;
  const cdn = _RUNE_CDN_BASE + icon;
  const onErr =
    `if(this.dataset.cdn){this.style.display='none';}` +
    `else{this.dataset.cdn='1';this.src='${cdn}';}`;
  return (
    `<img class="${cls}" src="${local}" alt="${_escHtml(name)}"` +
    ` title="${_escHtml(name)}" loading="lazy" onerror="${onErr}">`
  );
}

function _augTag(augId, augById) {
  const info = augById[String(augId)];
  if (!info || !info.icon_url) return '';
  const name = info.name || `augment ${augId}`;
  const rar = String(info.rarity || '').replace(/^k/, '').toLowerCase();
  return (
    `<div class="pld-aug" data-rarity="${_escHtml(rar)}" title="${_escHtml(name)}">` +
    `<img class="pld-aug-icon" src="${_escHtml(info.icon_url)}" alt=""` +
    ` loading="lazy" onerror="this.style.display='none'">` +
    `<span class="pld-aug-name">${_escHtml(name)}</span></div>`
  );
}

function _spellTag(spellId) {
  const img = sumImg(spellId);
  const nm = sumName(spellId);
  if (!img) return '';
  return (
    `<img class="pld-spell" src="${img}" alt="${_escHtml(nm)}"` +
    ` title="${_escHtml(nm)}" loading="lazy" onerror="this.style.display='none'">`
  );
}

// --- row builders ---------------------------------------------------
function _runeRowHtml(runes, runeById) {
  const r = runes || {};
  const primary = Array.isArray(r.primary) ? r.primary : [];
  const secondary = Array.isArray(r.secondary) ? r.secondary : [];
  const keystone = r.keystone != null ? r.keystone : primary[0];
  if (keystone == null && !primary.length) return '';
  const primMinors = primary.slice(1).filter((x) => x);
  const secRunes = secondary.filter((x) => x);
  const keyTag = keystone != null ? _runeIconTag(keystone, runeById, { key: true }) : '';
  const primTags = primMinors.map((id) => _runeIconTag(id, runeById, {})).join('');
  const styleTag = r.sub_style != null
    ? _runeIconTag('style:' + r.sub_style, runeById, { style: true }) : '';
  const secTags = secRunes.map((id) => _runeIconTag(id, runeById, {})).join('');
  return (
    `<div class="pld-row pld-row-runes">` +
    `<span class="pld-label">Runes</span>` +
    `<div class="pld-icons">` +
    `<span class="pld-group">${keyTag}${primTags}</span>` +
    (secTags || styleTag ? `<span class="pld-sep"></span><span class="pld-group">${styleTag}${secTags}</span>` : '') +
    `</div></div>`
  );
}

function _augRowHtml(augArr, augById) {
  const ids = (Array.isArray(augArr) ? augArr : []).filter((x) => Number(x) > 0);
  const tags = ids.map((id) => _augTag(id, augById)).filter((s) => s).join('');
  if (!tags) return '';
  return (
    `<div class="pld-row pld-row-augs">` +
    `<span class="pld-label">Augments</span>` +
    `<div class="pld-augs">${tags}</div></div>`
  );
}

function _spellRowHtml(sp1, sp2) {
  const tags = [_spellTag(sp1), _spellTag(sp2)].filter((s) => s).join('');
  if (!tags) return '';
  return (
    `<div class="pld-row pld-row-spells">` +
    `<span class="pld-label">Spells</span>` +
    `<div class="pld-icons">${tags}</div></div>`
  );
}

/** True when this match's loadout headlines augments (Arena) over runes. */
function _isAugmentMode(match) {
  const en = (match && match.enriched) || {};
  const augs = en.arena_augments;
  if (Array.isArray(augs) && augs.some((x) => Number(x) > 0)) return true;
  return /CHERRY|ARENA/i.test(String(match && match.mode));
}

function _cardHtml(match, dicts) {
  const en = (match && match.enriched) || {};
  const champ = (match && match.champion) || '';
  const augMode = _isAugmentMode(match);
  const loadoutRow = augMode
    ? _augRowHtml(en.arena_augments, dicts.augById || {})
    : _runeRowHtml(en.runes, dicts.runeById || {});
  const spellRow = _spellRowHtml(en.spell1_id, en.spell2_id);
  if (!loadoutRow && !spellRow) return '';
  const sub = augMode ? 'augments + spells (descriptive)' : 'runes + spells (descriptive)';
  return (
    `<div class="pld-card">` +
    `<div class="pld-head">` +
    `<span class="pld-title">LOADOUT</span>` +
    `<span class="pld-sub">${champ ? _escHtml(champ) + ' . ' : ''}${sub}</span>` +
    `</div>` +
    loadoutRow + spellRow +
    `</div>`
  );
}

/** Render the descriptive loadout strip for the reviewed match. Idempotent.
 *  `data` is the /api/last-match payload (or its mock fixture). */
export function renderPgrLoadout(data) {
  const mount = document.getElementById(MOUNT_ID);
  if (!mount) return;
  if (!data || !data.found || !data.match) {
    mount.innerHTML = '';
    mount.hidden = true;
    return;
  }
  const match = data.match;
  const draw = (dicts) => {
    try {
      const html = _cardHtml(match, dicts || {});
      mount.innerHTML = html;
      mount.hidden = !html;
    } catch (_e) {
      mount.innerHTML = '';
      mount.hidden = true;
    }
  };
  _loadDicts().then(draw).catch(() => draw({}));
}

// --- test hooks -----------------------------------------------------
export const __test = {
  _indexRunes,
  _runeIconTag,
  _augTag,
  _spellTag,
  _runeRowHtml,
  _augRowHtml,
  _spellRowHtml,
  _isAugmentMode,
  _cardHtml,
};
