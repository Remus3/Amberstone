// s213: DDragon-driven tooltips for items + runes.
//
// Loads /data/meta/ddragon_items.json + /data/meta/ddragon_runes.json
// once on demand, builds lookup maps, exposes:
//   itemTooltipHtml(itemId)   -> cleaned HTML for the app-wide tooltip
//   keystoneTooltipHtml(name) -> cleaned HTML for keystone rune
//
// Cleaning rules:
//   - Strip <mainText> / <rarityMythic> / <rarityLegendary> / <attention>
//     / <maintext> / </maintext> outer wrappers - keep their text.
//   - Replace LoL's <lol-uikit-tooltipped-keyword key='...'>X</...>
//     with just X (drop the keyword link).
//   - Preserve <br>, <passive>, <active>, <unique>, <stats>, <ornnBonus>,
//     <flavorText>, <consumable> - render as line breaks or styled spans.
//   - Strip <stats>...</stats> wrapper but keep its content (one stat
//     per line).
//   - <attention>X</attention> -> bold "X" so numbers pop.
//   - Output safety (CodeQL js/incomplete-multi-character-sanitization):
//     unknown tags are stripped to a fixpoint, the surviving b / i / br tags
//     keep NO attributes, and any other "<" is escaped as text. The DDragon
//     name / plaintext / tree fields go through the same cleaner (they can
//     carry LoL markup too). The result feeds the app tooltip's data-tt-html.

import { escHtml } from "./helpers.js";

const _ITEMS_CACHE = { ready: false, loading: null, byId: {} };
const _RUNES_CACHE = { ready: false, loading: null, byKey: {}, byId: {} };

function _normKey(s) {
  return String(s || "").toLowerCase().replace(/[^a-z0-9]/g, "");
}

// LoL HTML -> safe-ish HTML for our tooltip surface. The app-tooltip
// system renders innerHTML so we want the cleaned output to be
// pre-styled by our own CSS classes, not LoL's.
function _cleanLolHtml(raw) {
  if (!raw) return "";
  let s = String(raw);
  // Strip outer wrappers we don't need.
  s = s.replace(/<\/?maintext>/gi, "");
  s = s.replace(/<\/?mainText>/g, "");
  s = s.replace(/<\/?stats>/gi, "");
  // Strip the keyword-tooltip wrapper but keep its inner text.
  s = s.replace(/<lol-uikit-tooltipped-keyword[^>]*>([^<]*)<\/lol-uikit-tooltipped-keyword>/gi, "$1");
  // <font color='#X'>...</font> - drop the font tag but keep text.
  s = s.replace(/<\/?font[^>]*>/gi, "");
  // <attention>N</attention> -> bold "N".
  s = s.replace(/<attention>(.*?)<\/attention>/gi, "<b>$1</b>");
  // <passive>NAME</passive> -> bold "NAME".
  s = s.replace(/<passive>(.*?)<\/passive>/gi, "<b>$1</b>");
  s = s.replace(/<active>(.*?)<\/active>/gi, "<b>$1</b>");
  s = s.replace(/<unique>(.*?)<\/unique>/gi, "<b>$1</b>");
  s = s.replace(/<ornnBonus>(.*?)<\/ornnBonus>/gi, "<b>$1</b>");
  s = s.replace(/<status>(.*?)<\/status>/gi, "$1");
  s = s.replace(/<healing>(.*?)<\/healing>/gi, "$1");
  s = s.replace(/<flavorText>(.*?)<\/flavorText>/gi, "<i>$1</i>");
  s = s.replace(/<rules>(.*?)<\/rules>/gi, "<i>$1</i>");
  // Collapse multiple <br> into one + normalize.
  s = s.replace(/<br\s*\/?>(\s*<br\s*\/?>)+/gi, "<br><br>");
  // Strip any remaining unknown tags (defensive). Repeat to a fixpoint:
  // removing one tag can splice another together ("<i<x> on...>" -> "<i on...>").
  let prev;
  do {
    prev = s;
    s = s.replace(/<(?!\/?(b|i|br)\b)[^>]+>/gi, "");
  } while (s !== prev);
  // The surviving b / i / br tags keep NO attributes (an event handler could
  // ride on an allowed tag), and every "<" that does not open one of those
  // bare tags is text, so it is escaped.
  s = s.replace(/<(\/?)(br|b|i)\b[^>]*>/gi, (_m, slash, tag) => `<${slash}${tag.toLowerCase()}>`);
  s = s.replace(/<(?!\/?(?:br|b|i)>)/g, "&lt;");
  return s.trim();
}

async function _loadItems() {
  if (_ITEMS_CACHE.ready) return _ITEMS_CACHE.byId;
  if (_ITEMS_CACHE.loading) return _ITEMS_CACHE.loading;
  _ITEMS_CACHE.loading = (async () => {
    try {
      const r = await fetch("/api/dictionary/items", { cache: "force-cache" });
      if (!r.ok) return _ITEMS_CACHE.byId;
      const j = await r.json();
      const data = (j && j.data) || j || {};
      for (const [id, item] of Object.entries(data)) {
        if (!item || typeof item !== "object") continue;
        _ITEMS_CACHE.byId[String(id)] = {
          name:        item.name || "",
          plaintext:   item.plaintext || "",
          description: _cleanLolHtml(item.description),
          gold:        (item.gold && item.gold.total) || 0,
        };
      }
      _ITEMS_CACHE.ready = true;
      // s213: cache landed - let listeners (e.g. champ_select view)
      // schedule a re-render so the next paint stamps data-tt-html
      // on item icons.
      document.dispatchEvent(new CustomEvent("rc:lol-descriptions-ready", { detail: { kind: "items" } }));
    } catch (_) { /* swallow - tooltips fall back to title text */ }
    return _ITEMS_CACHE.byId;
  })();
  return _ITEMS_CACHE.loading;
}

async function _loadRunes() {
  if (_RUNES_CACHE.ready) return _RUNES_CACHE.byKey;
  if (_RUNES_CACHE.loading) return _RUNES_CACHE.loading;
  _RUNES_CACHE.loading = (async () => {
    try {
      const r = await fetch("/api/dictionary/runes", { cache: "force-cache" });
      if (!r.ok) return _RUNES_CACHE.byKey;
      const trees = await r.json();
      // runesReforged is a list of tree objects, each with .slots[].runes[].
      const list = Array.isArray(trees) ? trees : [];
      for (const tree of list) {
        for (const slot of (tree.slots || [])) {
          for (const rune of (slot.runes || [])) {
            const entry = {
              name:      rune.name || "",
              tree:      tree.name || "",
              shortDesc: _cleanLolHtml(rune.shortDesc),
              longDesc:  _cleanLolHtml(rune.longDesc),
            };
            _RUNES_CACHE.byKey[_normKey(rune.name)] = entry;
            _RUNES_CACHE.byId[String(rune.id || "")] = entry;
          }
        }
      }
      _RUNES_CACHE.ready = true;
      document.dispatchEvent(new CustomEvent("rc:lol-descriptions-ready", { detail: { kind: "runes" } }));
    } catch (_) { /* swallow */ }
    return _RUNES_CACHE.byKey;
  })();
  return _RUNES_CACHE.loading;
}

// Title-row HTML for a DDragon name. Names are LoL HTML too: the Gangplank
// upgrade items (3901-3903) carry
// "<rarityLegendary>Fire at Will</rarityLegendary><br><subtitleLeft>
// <silver>500 Silver Serpents</silver></subtitleLeft>". The old innerHTML
// tooltip kept those unknown wrappers, so the flex .lol-tt-title (base.css)
// had three flex items - name, br, subtitle - and rendered ONE row with the
// subtitle at the right. Cleaning drops the wrappers, which would merge the
// text and the br into one anonymous flex item and stack it on two lines, so
// each <br>-separated part is wrapped in its own <span> to keep the old flex
// items. A name without <br> (every other item / rune) is returned as cleaned.
function _titleHtml(raw) {
  const clean = _cleanLolHtml(raw);
  if (!clean.includes("<br>")) return clean;
  return clean.split("<br>").map((part) => (part ? `<span>${part}</span>` : "")).join("<br>");
}

// Public - synchronous lookups. Kick off the lazy load on first call
// so subsequent renders see the cache. Returns "" until data lands;
// the caller's `data-tt-html` attr will be missing on the first paint
// and present on the next render after the cache resolves.
export function itemTooltipHtml(itemId) {
  if (!_ITEMS_CACHE.ready && !_ITEMS_CACHE.loading) { _loadItems(); }
  const item = _ITEMS_CACHE.byId[String(itemId)];
  if (!item) return "";
  // name / plaintext are LoL HTML too, so they go through the same cleaner as
  // the description: text and <br> are kept, every other tag is dropped or
  // escaped (the name via _titleHtml, which keeps the title row's flex items).
  const goldLine = item.gold ? `<div class="lol-tt-gold">${escHtml(item.gold)}g</div>` : "";
  const body = item.description || (item.plaintext ? `<i>${_cleanLolHtml(item.plaintext)}</i>` : "");
  return `<div class="lol-tt-title">${_titleHtml(item.name)}${goldLine}</div>${body}`;
}

export function keystoneTooltipHtml(keystoneName) {
  if (!_RUNES_CACHE.ready && !_RUNES_CACHE.loading) { _loadRunes(); }
  const rune = _RUNES_CACHE.byKey[_normKey(keystoneName)];
  if (!rune) return "";
  const tree = rune.tree ? `<div class="lol-tt-tree">${_cleanLolHtml(rune.tree)}</div>` : "";
  const body = rune.shortDesc || rune.longDesc || "";
  return `<div class="lol-tt-title">${_titleHtml(rune.name)}${tree}</div>${body}`;
}

// Bulk loaders - call once on view mount to warm the caches so the
// first render after has tooltips ready.
export function preloadLolDescriptions() {
  _loadItems();
  _loadRunes();
}

// Test seam (web/js/panels/codeql_js_hardening.test.mjs).
export const __test = { _cleanLolHtml, _titleHtml };
