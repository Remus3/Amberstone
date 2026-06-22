// Threat donut module (UX-2 frontend, 2026-05-20). Renders a small inline
// SVG donut showing the physical / magical / true / on-hit damage mix for
// one enemy's current itemization. Fetches /api/damage-mix (shipped at
// c7698d9) and caches by (champId, itemsHash) for 60s so a 1Hz state
// envelope doesn't hammer the engine.
//
// The donut is intentionally tiny (28x28) and standalone so it can be
// dropped next to any champion portrait. Empty items array -> grey "?"
// placeholder (the route 400s on empty items, and a "no inventory yet"
// signal is more useful than a fetch error).
//
// Public API:
//   renderThreatDonut(parentEl, champId, items, opts)
//     - parentEl: DOM node to append into (caller controls layout)
//     - champId:  Riot numeric champion key (preferred) OR snapshot
//                 string id (e.g. "Garen"). Required.
//     - items:    array of item ids (numbers or strings). Empty array
//                 renders the "?" placeholder.
//     - opts:     { level: number = 11, mode: string = "SR" }
//
//   The donut is appended synchronously (with a "..." placeholder) and
//   filled async once the fetch resolves. Re-rendering with the same
//   (champId, items) within 60s hits the cache instead of refetching.

const _PALETTE = {
  physical: "#ff5050",
  magical:  "#5070ff",
  true:     "#eeeeee",
  on_hit:   "#ffaa00",
};

// Module-scoped cache. Key = `${champId}:${itemsHash}`, value =
// { mix, fetchedAt }. TTL 60s - same coarse refresh as other DS-derived
// surfaces in the dashboard. Cache is keyed by the SORTED item list so
// reordering doesn't bust it (the engine output is order-invariant).
const _threatDonutCache = new Map();
const _CACHE_TTL_MS = 60_000;

// In-flight registry so 5 enemies on the same tick don't fire 5 fetches
// for the same (champId, items) combo when the cache is cold.
const _inFlight = new Map();

function _itemsHash(items) {
  // Normalize: drop falsy, stringify, sort. Empty array -> "" so
  // callers can detect the placeholder branch without re-checking.
  if (!Array.isArray(items)) return "";
  const norm = items.map((i) => String(i || "").trim()).filter(Boolean);
  norm.sort();
  return norm.join(",");
}

function _cacheKey(champId, itemsHash) {
  return `${champId}:${itemsHash}`;
}

function _readCache(key) {
  const hit = _threatDonutCache.get(key);
  if (!hit) return null;
  if ((Date.now() - hit.fetchedAt) > _CACHE_TTL_MS) {
    _threatDonutCache.delete(key);
    return null;
  }
  return hit.mix;
}

function _writeCache(key, mix) {
  _threatDonutCache.set(key, { mix, fetchedAt: Date.now() });
}

async function _fetchMix(champId, items, level, mode) {
  const url = `/api/damage-mix?champ_id=${encodeURIComponent(champId)}`
            + `&items=${encodeURIComponent(items.join(","))}`
            + `&level=${level | 0}`
            + `&mode=${encodeURIComponent(mode)}`;
  const resp = await fetch(url, { cache: "no-store" });
  if (!resp.ok) {
    // 400 / 500 -> swallow + return null. Caller renders the "?" tile.
    return null;
  }
  const j = await resp.json();
  if (!j || !j.ok || !j.mix) return null;
  return j.mix;
}

function _placeholder(parentEl, label, tooltip) {
  const wrap = document.createElement("span");
  wrap.className = "threat-donut threat-donut-empty";
  wrap.title = tooltip || "no item data yet";
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("width", "28");
  svg.setAttribute("height", "28");
  svg.setAttribute("viewBox", "0 0 28 28");
  const ring = document.createElementNS("http://www.w3.org/2000/svg", "circle");
  ring.setAttribute("cx", "14");
  ring.setAttribute("cy", "14");
  ring.setAttribute("r", "12");
  ring.setAttribute("fill", "none");
  ring.setAttribute("stroke", "#444");
  ring.setAttribute("stroke-width", "4");
  svg.appendChild(ring);
  const txt = document.createElementNS("http://www.w3.org/2000/svg", "text");
  txt.setAttribute("x", "14");
  txt.setAttribute("y", "18");
  txt.setAttribute("text-anchor", "middle");
  // operator-exception: geometry-constrained sigil glyph. This "?" / "."
  // placeholder is centered inside the fixed 28x28 donut viewBox (r=12
  // ring); the --fs-xs 16px floor would overflow the tile. It is a status
  // sigil, not body text. Documented per the R13 v2.1 fixture audit
  // (2026-06-22) - mirrors the cd_ledger.css density operator-exceptions.
  txt.setAttribute("font-size", "12");
  txt.setAttribute("fill", "#888");
  txt.setAttribute("font-weight", "700");
  txt.textContent = label || "?";
  svg.appendChild(txt);
  wrap.appendChild(svg);
  parentEl.appendChild(wrap);
  return wrap;
}

// Build the 4-slice donut SVG from a mix object. Slices in stable
// order: physical, magical, true, on_hit (matches palette dict +
// matches the order operator visually associates with red/blue/white/
// gold). Slices smaller than 0.5% are dropped so we don't render
// hairline arcs that anti-alias to invisible dust.
//
// The donut is drawn as 4 stroked arcs on a single circle (r=10,
// stroke-width=5) so the "hole" is the unstroked center. Using
// stroke-dasharray + stroke-dashoffset is cheaper than 4 path
// elements with explicit arc commands and keeps the slice math
// trivial (one offset per slice).
function _buildDonutSvg(mix) {
  const order = ["physical", "magical", "true", "on_hit"];
  const slices = order.map((k) => ({ key: k, frac: +mix[k] || 0 }))
                      .filter((s) => s.frac >= 0.005);
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("width", "28");
  svg.setAttribute("height", "28");
  svg.setAttribute("viewBox", "0 0 28 28");

  // Background ring (so a single-slice donut still reads as a donut
  // when the dominant slice doesn't quite total 100%).
  const bg = document.createElementNS("http://www.w3.org/2000/svg", "circle");
  bg.setAttribute("cx", "14");
  bg.setAttribute("cy", "14");
  bg.setAttribute("r", "10");
  bg.setAttribute("fill", "none");
  bg.setAttribute("stroke", "#222");
  bg.setAttribute("stroke-width", "5");
  svg.appendChild(bg);

  const C = 2 * Math.PI * 10; // circumference for r=10
  let offset = 0;
  for (const s of slices) {
    const len = C * s.frac;
    const arc = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    arc.setAttribute("cx", "14");
    arc.setAttribute("cy", "14");
    arc.setAttribute("r", "10");
    arc.setAttribute("fill", "none");
    arc.setAttribute("stroke", _PALETTE[s.key] || "#888");
    arc.setAttribute("stroke-width", "5");
    arc.setAttribute("stroke-dasharray", `${len} ${C - len}`);
    arc.setAttribute("stroke-dashoffset", String(-offset));
    // Rotate -90deg so the first slice starts at 12 o'clock (matches
    // operator reading order: physical-red is the visual anchor).
    arc.setAttribute("transform", "rotate(-90 14 14)");
    svg.appendChild(arc);
    offset += len;
  }
  return svg;
}

function _renderInto(wrap, mix) {
  // Clear existing children, then append the new donut + tooltip.
  while (wrap.firstChild) wrap.removeChild(wrap.firstChild);
  wrap.classList.remove("threat-donut-empty", "threat-donut-loading");
  const svg = _buildDonutSvg(mix);
  wrap.appendChild(svg);
  const pct = (k) => Math.round(100 * (+mix[k] || 0));
  wrap.title = `Damage mix: AD ${pct("physical")}% / AP ${pct("magical")}%`
             + ` / true ${pct("true")}% / on-hit ${pct("on_hit")}%`;
}

// Public renderer. Synchronously appends a loading wrap to parentEl and
// returns it; the wrap is filled async once the fetch resolves (or
// stays as a "?" placeholder on empty items / fetch error).
export function renderThreatDonut(parentEl, champId, items, opts) {
  const level = (opts && +opts.level) || 11;
  const mode  = (opts && opts.mode) || "SR";

  if (!parentEl || !champId) return null;

  const itemsHash = _itemsHash(items);
  if (!itemsHash) {
    // Empty items -> grey "?" tile. Useful very early in a game when
    // an enemy has only boots / a long sword and we can't yet say
    // anything meaningful about their damage profile.
    return _placeholder(parentEl, "?", "no items yet");
  }

  // Cache hit -> render synchronously, no fetch.
  const key = _cacheKey(champId, itemsHash);
  const cached = _readCache(key);
  if (cached) {
    const wrap = document.createElement("span");
    wrap.className = "threat-donut";
    parentEl.appendChild(wrap);
    _renderInto(wrap, cached);
    return wrap;
  }

  // Cache miss -> append a loading placeholder, fetch in background.
  const wrap = document.createElement("span");
  wrap.className = "threat-donut threat-donut-loading";
  wrap.title = "computing damage mix...";
  parentEl.appendChild(wrap);
  // Loading visual: same shape as empty placeholder but with a "." label
  // so operators can distinguish "no items" (?) from "fetching" (.).
  _placeholder(wrap, ".", "computing damage mix...");
  // Remove the doubled outer .threat-donut-empty class the placeholder
  // appended (we want the wrap itself to stay .threat-donut-loading
  // until the fetch lands).
  const inner = wrap.firstChild;
  if (inner) inner.classList.remove("threat-donut-empty");

  // De-dupe concurrent fetches for the same key.
  let inflight = _inFlight.get(key);
  if (!inflight) {
    const normItems = String(itemsHash).split(",");
    inflight = _fetchMix(champId, normItems, level, mode)
      .then((mix) => {
        _inFlight.delete(key);
        if (mix) _writeCache(key, mix);
        return mix;
      })
      .catch(() => {
        _inFlight.delete(key);
        return null;
      });
    _inFlight.set(key, inflight);
  }
  inflight.then((mix) => {
    if (!wrap.isConnected) return;
    if (mix) {
      _renderInto(wrap, mix);
    } else {
      // Fetch failed (400 unknown id / 500 / network) -> degrade
      // gracefully to a "?" tile so the row layout still reads.
      while (wrap.firstChild) wrap.removeChild(wrap.firstChild);
      wrap.classList.remove("threat-donut-loading");
      wrap.classList.add("threat-donut-empty");
      wrap.title = "damage mix unavailable";
      _placeholder(wrap, "?", "damage mix unavailable");
      // _placeholder appends a fresh wrap, so the structure is
      // wrap > wrap > svg. Hoist the inner svg up one level for a
      // single-element placeholder.
      const placeholder = wrap.firstChild;
      const svg = placeholder && placeholder.firstChild;
      if (svg) {
        wrap.replaceChild(svg, placeholder);
      }
    }
  });
  return wrap;
}

// Test-only exports. Not part of the public surface but useful for
// unit tests that want to bypass DOM-fetch coupling and verify the
// SVG geometry / cache behavior directly.
export const _internal = {
  itemsHash:     _itemsHash,
  cacheKey:      _cacheKey,
  readCache:     _readCache,
  writeCache:    _writeCache,
  buildDonutSvg: _buildDonutSvg,
  palette:       _PALETTE,
  cacheTtlMs:    _CACHE_TTL_MS,
};
