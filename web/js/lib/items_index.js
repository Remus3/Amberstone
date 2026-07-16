// Async data-index loaders for items, champions, and summoner spells.
// Each exported object is mutable - loaders populate it in-place once ready.
// Callers that need to re-render after load should listen to the custom
// events: "rc:items-ready", "rc:champs-ready", "rc:spells-ready".

// Pre-hydration DDragon patch fallback - unreachable in practice (the
// loaders below overwrite .version before consumers render, and a stale
// guess only 404s into the onerror CDN chain). Single source of truth:
// tests/test_ddragon_path_version_drift.py bans any other quoted semver
// literal in web/js, so bump only this line on a patch refresh.
export const DDRAGON_FALLBACK_VERSION = "16.14.1";

export const ITEMS = { ready: false, version: DDRAGON_FALLBACK_VERSION, byName: {}, byId: {} };
export const ITEM_COSTS = { ready: false, byId: {} };
// WP-B3: recipe `from`-graph (DDragon) for partial-component pips/rings.
export const ITEM_RECIPES = { ready: false, byId: {} };
// WP-D1: per-item tooltip source (name + raw DDragon `description`) for the
// build-module hover tip. Populated off the SAME /api/dictionary/items fetch
// as ITEM_RECIPES; parsed lazily on hover via parseItemTooltip below.
export const ITEM_DETAILS = { ready: false, byId: {} };
export const CHAMPS = { ready: false, version: DDRAGON_FALLBACK_VERSION, byName: {}, byId: {} };
export const SPELLS = { ready: false, byName: {} };

export const _itemResolveCache = new Map();

export function _normItemName(s) {
  return String(s || "").toLowerCase().replace(/[^a-z0-9]/g, "");
}

// Tiered resolver: (1) exact, (2) prefix match (shortest wins), (3) 6-char stem.
// Handles casual names like "Rabadon's" → Rabadon's Deathcap.
export function _resolveItemId(name) {
  const n = _normItemName(name);
  if (!n) return null;
  if (_itemResolveCache.has(n)) return _itemResolveCache.get(n);
  let id = ITEMS.byName[n] || null;
  if (!id) {
    let best = null;
    for (const k in ITEMS.byName) {
      if (k === n) { best = k; break; }
      if (k.startsWith(n) || n.startsWith(k)) {
        if (!best || k.length < best.length) best = k;
      }
    }
    if (!best && n.length >= 5) {
      const stem = n.slice(0, Math.min(n.length, 6));
      for (const k in ITEMS.byName) {
        if (k.startsWith(stem)) {
          if (!best || k.length < best.length) best = k;
        }
      }
    }
    if (best) id = ITEMS.byName[best];
  }
  _itemResolveCache.set(n, id);
  return id;
}

// Split a comma-separated or arrow-separated item list string.
export function _splitItemList(str, splitArrow) {
  if (!str) return [];
  const sep = splitArrow ? /\s*(?:,|→|->)\s*/ : /\s*,\s*/;
  return String(str).split(sep).map(s => s.trim()).filter(Boolean);
}

// Build the set of item_ids that appear in some build variants but NOT
// all - the "differing" items that distinguish one build from another.
// Used by the in-game Build Chooser + champ-select renderers to mark
// items with .cs-build-item--diff so the eye lands on exactly what
// trades off between variants. Returns an empty Set when there's fewer
// than two variants (nothing to diff). Shared from here so item_build.js
// and champ_select.js don't cross-import each other.
export function diffVariantItemIds(variants) {
  const out = new Set();
  if (!variants || variants.length < 2) return out;
  const sets = variants.map((v) =>
    new Set((v.item_ids || []).slice(0, 6).map(String)));
  const union = new Set();
  sets.forEach((s) => s.forEach((id) => union.add(id)));
  union.forEach((id) => {
    if (!sets.every((s) => s.has(id))) out.add(id);
  });
  return out;
}

// DDragon name-rename overrides: champions whose live display name doesn't
// normalize cleanly to their DDragon file. The champions_index.json byName
// map handles apostrophes/spaces (Kai'Sa → kaisa → 'Kaisa'), but a handful
// of champs were renamed by Riot post-release and the display name no
// longer matches the on-disk filename. Keys are lowercase-alphanumeric of
// the display name; values are the DDragon canonical id.
//
// Source of truth is `/data/champion_aliases.json`; this map is hydrated
// by the async loader below and is shared with tools/daemon_slayer_extract.py
// (which reads the same file at build time with .lower() normalization).
// Until the fetch resolves the map is empty - _resolveChampId falls
// back to a null return for the aliased trio, same as for any unknown
// champion name.
const _CHAMP_RENAME_OVERRIDES = {};

// Resolve a champion name to its numeric ID string.
export function _resolveChampId(name) {
  const n = String(name || "").toLowerCase().replace(/[^a-z0-9]/g, "");
  if (!n) return null;
  if (CHAMPS.byName[n]) return CHAMPS.byName[n];
  if (_CHAMP_RENAME_OVERRIDES[n]) return _CHAMP_RENAME_OVERRIDES[n];
  return null;
}

// Resolve a summoner spell name to its DDragon key.
export function _resolveSpell(name) {
  const k = String(name || "").toLowerCase().replace(/[^a-z0-9]/g, "");
  return SPELLS.byName[k] || null;
}

// ── Async loaders ────────────────────────────────────────────────────────────
// Populate in-place; dispatch custom events so consumers can re-render.

(async () => {
  try {
    const r = await fetch("/data/items_index.json");
    if (!r.ok) return;
    const j = await r.json();
    ITEMS.version = j.version || ITEMS.version;
    ITEMS.byName = j.byName || {};
    ITEMS.byId = j.byId || {};
    ITEMS.ready = true;
    _itemResolveCache.clear();
    // Clear tile-sig caches so idempotency guards don't skip re-renders.
    ["ib-owned", "ib-recommended", "cs-ds-tiles"].forEach((id) => {
      const e = document.getElementById(id);
      if (e) delete e.dataset.tilesSig;
    });
    document.dispatchEvent(new CustomEvent("rc:items-ready"));
  } catch (_) {}
})();

(async () => {
  try {
    const r = await fetch("/data/items_costs.json");
    if (!r.ok) return;
    const j = await r.json();
    ITEM_COSTS.byId = j.byId || {};
    ITEM_COSTS.ready = true;
  } catch (_) {}
})();

// WP-B3: recipe from-graph loader. The raw DDragon items dictionary
// (/api/dictionary/items) carries `from` (the recipe components), which
// lol_descriptions.js strips. force-cache makes a 2nd hit a cache read, not a
// network round-trip. Fail-soft - no recipes -> componentProgress returns 0/0.
(async () => {
  try {
    const r = await fetch("/api/dictionary/items", { cache: "force-cache" });
    if (!r.ok) return;
    const j = await r.json();
    const items = j.data || j;
    for (const [id, it] of Object.entries(items)) {
      if (!it || typeof it !== "object") continue;
      ITEM_RECIPES.byId[String(id)] = {
        from: Array.isArray(it.from) ? it.from.map(String) : [],
        gold: (it.gold && it.gold.total) || 0,
      };
      // WP-D1: stash the name + raw description for the hover tooltip (parsed
      // lazily on hover by parseItemTooltip, so the upfront pass stays cheap).
      ITEM_DETAILS.byId[String(id)] = {
        name: it.name || "",
        description: it.description || "",
      };
    }
    ITEM_RECIPES.ready = true;
    ITEM_DETAILS.ready = true;
    document.dispatchEvent(new CustomEvent("rc:recipes-ready"));
  } catch (_) {}
})();

// Pure: how many of targetId's DIRECT recipe components are in ownedSet, and the
// total component count. Drives the partial-component pip (owned/total) + the
// fractional ring. Direct children only (mirrors the server `from` read in
// replan.component_ids_of). A base item with no recipe returns {owned:0,total:0}
// (no pip/ring). ownedSet carries id strings (+ lowercased names); recipe `from`
// are numeric id strings, so the id half matches.
export function componentProgress(targetId, ownedSet) {
  const e = ITEM_RECIPES.byId[String(targetId)];
  const from = (e && e.from) || [];
  if (!from.length) return { owned: 0, total: 0 };
  let owned = 0;
  from.forEach((c) => { if (ownedSet && ownedSet.has(String(c))) owned += 1; });
  return { owned, total: from.length };
}

// WP-D1: parse a DDragon item detail ({name, description}) into the three
// tooltip channels {name, stats:[lines], passive}. The `description` is an HTML
// blob like `<mainText><stats>55 Attack Damage<br>...</stats><br><br>` +
// `<passive>Spellblade</passive><br>After using an Ability ...</mainText>`.
// Pure + fail-soft: a blank/odd description yields empty stats + passive, so a
// base item (or an id with no dict entry) still shows its name. The passive
// channel carries any active prose too - it is the item's effect text.
export function parseItemTooltip(detail) {
  const d = detail || {};
  const name = d.name || "";
  const desc = String(d.description || "");
  const strip = (s) => s
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<[^>]*>/g, "")
    .replace(/&nbsp;/gi, " ")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">")
    .replace(/&amp;/gi, "&");
  const lines = (s) => strip(s).split("\n").map((x) => x.trim()).filter(Boolean);
  let stats = [];
  const sm = desc.match(/<stats>([\s\S]*?)<\/stats>/i);
  if (sm) stats = lines(sm[1]);
  // Effect prose = the body with the stats span removed (or the whole body when
  // there is no stats span).
  const rest = sm ? desc.replace(sm[0], "") : desc;
  const passive = lines(rest).join("\n");
  return { name, stats, passive };
}

// Cache-bust query defeats aggressive PWA/SW caching (2026-04-26 rebuild).
(async () => {
  try {
    const r = await fetch("/data/champions_index.json?v=2026-04-26");
    if (!r.ok) return;
    const j = await r.json();
    CHAMPS.version = j.version || CHAMPS.version;
    CHAMPS.byName = j.byName || {};
    CHAMPS.byId = j.byId || {};
    CHAMPS.ready = true;
    document.dispatchEvent(new CustomEvent("rc:champs-ready"));
  } catch (_) {}
})();

(async () => {
  try {
    const r = await fetch("/data/spells_index.json");
    if (!r.ok) return;
    const j = await r.json();
    SPELLS.byName = j.byName || {};
    SPELLS.ready = true;
    document.dispatchEvent(new CustomEvent("rc:spells-ready"));
  } catch (_) {}
})();

(async () => {
  try {
    const r = await fetch("/data/champion_aliases.json");
    if (!r.ok) return;
    const j = await r.json();
    for (const [k, v] of Object.entries(j)) _CHAMP_RENAME_OVERRIDES[k] = v;
  } catch (_) {}
})();
