// s213 v2: champion 2-piece tag lookup for the enemies panel.
//
// Mirrors the lol_descriptions.js pattern - lazy-fetches once on first
// access, dispatches `rc:champion-tags-ready` when the cache lands so
// dependent panels can re-render. Returns `{tags: [t1, t2], primary,
// attack, magic, defense}` per champion display name.

const _CACHE = { ready: false, loading: null, byName: {} };

function _norm(s) {
  return String(s || "").toLowerCase().replace(/[^a-z0-9]/g, "");
}

async function _load() {
  if (_CACHE.ready) return _CACHE.byName;
  if (_CACHE.loading) return _CACHE.loading;
  _CACHE.loading = (async () => {
    try {
      // s213 v3: `default` cache mode (vs `force-cache`) so HTTP
       // validation runs - operator-edited counters / DDragon refreshes
       // pick up without a hard refresh. Body is ~50KB so the
       // round-trip is cheap.
      const r = await fetch("/api/dictionary/champion-tags", { cache: "default" });
      if (!r.ok) return _CACHE.byName;
      const data = await r.json();
      for (const [name, entry] of Object.entries(data || {})) {
        if (!entry || typeof entry !== "object") continue;
        // Store under display-name + slug variants so callers can pass
        // whatever spelling they have.
        _CACHE.byName[name] = entry;
        _CACHE.byName[name.replace("'", "")] = entry;
        _CACHE.byName[name.replace(" ", "")] = entry;
        _CACHE.byName[name.replace("'", "").replace(" ", "")] = entry;
      }
      _CACHE.ready = true;
      document.dispatchEvent(new CustomEvent("rc:champion-tags-ready"));
    } catch (_) { /* swallow */ }
    return _CACHE.byName;
  })();
  return _CACHE.loading;
}

// Public - kick off lazy load on first call. Returns null until the
// cache lands; callers re-render on the `rc:champion-tags-ready` event.
export function championTags(name) {
  if (!_CACHE.ready && !_CACHE.loading) _load();
  return _CACHE.byName[name] || null;
}

export function preloadChampionTags() { _load(); }
