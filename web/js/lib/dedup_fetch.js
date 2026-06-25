// In-flight fetch dedup primitive (item 186).
//
// Multiple panels (coach_decisions + trigger_pill for /api/decisions;
// champ_select + item_build for /api/loadout/list) independently fire
// the same request on parallel render/poll cadences. Each fetch costs
// ~50-150ms server-side. When the requests overlap in time, this helper
// returns the in-flight promise to subsequent callers instead of
// hitting the network N times.
//
// Contract:
//   - Key includes method + URL + (for POST) a stable body identity.
//     Per item 171 trailing-space precedent, query-string variants are
//     distinct keys (the caller's URL already encodes them).
//   - The in-flight entry is evicted on settle PLUS a small grace TTL
//     so back-to-back identical fetches within the TTL still coalesce
//     (covers the typical 50-250ms render-storm window). After TTL
//     expires, fresh fetches go through normally - this is NOT a cache.
//   - Body cloning: response.clone() is used so each consumer can read
//     the body independently (.json() / .text() / .arrayBuffer()).
//   - Errors propagate to all waiters; eviction is immediate on reject
//     so the next fetch retries fresh (no stuck negative cache).
//
// Returns a Promise<Response> just like fetch(). Caller calls .ok /
// .json() / .text() on it normally.

const _inflight = new Map();

// Stable string key for a (method, url, body) tuple. For POST bodies
// that are JSON strings, the string itself is the body fingerprint.
// For ArrayBuffer / FormData / streams, we fall back to a per-call
// unique key (no dedup) so we don't crash on non-stringifiable bodies.
function _keyFor(url, init) {
  const method = (init && init.method ? init.method : "GET").toUpperCase();
  let bodyKey = "";
  if (init && init.body != null) {
    if (typeof init.body === "string") {
      bodyKey = init.body;
    } else {
      // Non-string bodies (FormData, Blob, etc.) - don't dedup.
      // Return a unique key so this fetch bypasses the helper.
      return null;
    }
  }
  return method + "|" + url + (bodyKey ? "|" + bodyKey : "");
}

// Default TTL after settle: 100ms. Covers the typical render-storm
// window where 2 panels mount + fetch within the same animation frame.
// Override per-call via init.dedupTtlMs (escape hatch for callers with
// known longer-lived coalescing windows).
const _DEFAULT_TTL_MS = 100;

export function dedupFetch(url, init) {
  const key = _keyFor(url, init);
  if (key == null) {
    // Non-stringifiable body - just pass through.
    return fetch(url, init);
  }
  const existing = _inflight.get(key);
  if (existing && existing.promise) {
    // Return a clone so each caller can read the body independently.
    return existing.promise.then((resp) => resp.clone());
  }
  const ttlMs = (init && typeof init.dedupTtlMs === "number")
    ? init.dedupTtlMs
    : _DEFAULT_TTL_MS;
  const entry = { promise: null };
  // Strip the dedupTtlMs key before passing init to real fetch (it's
  // not part of the Fetch standard and may trigger warnings).
  let fetchInit = init;
  if (init && "dedupTtlMs" in init) {
    fetchInit = Object.assign({}, init);
    delete fetchInit.dedupTtlMs;
  }
  entry.promise = fetch(url, fetchInit).then(
    (resp) => {
      // Evict after TTL so back-to-back identical fetches within the
      // grace window still coalesce. The resp held here is the master;
      // each waiter receives a clone above.
      setTimeout(() => {
        if (_inflight.get(key) === entry) _inflight.delete(key);
      }, ttlMs);
      return resp;
    },
    (err) => {
      // Immediate eviction on reject so the next call retries fresh.
      if (_inflight.get(key) === entry) _inflight.delete(key);
      throw err;
    },
  );
  _inflight.set(key, entry);
  // First caller gets the master response (no clone needed).
  return entry.promise;
}

// Test-only - module state introspection.
export function _dedupInflightSize() {
  return _inflight.size;
}

export function _dedupInflightClear() {
  _inflight.clear();
}
