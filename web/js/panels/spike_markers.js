// Live power-spike markers strip (competitor lift #4,
// docs/COMPETITOR_LIFT_2026-05-30.md). Mounts on the ACTIVE-MATCH surface
// (not champ-select). Renders the operator's discrete power spikes as a
// horizontal threshold strip:
//   - level spikes 6 / 11 / 16 (R unlock + ranks 2/3)
//   - item-completion spikes 1 / 2 / 3 finished legendaries
// Each marker is one of: CROSSED (filled - operator is at/past it), NEXT
// (highlighted - the nearest not-yet-crossed spike), or FUTURE (muted).
//
// OWED (live-game-only): a live-clock CURSOR line positioned at the live
// game_time. This v1 renders the discrete markers + the "next spike"
// highlight keyed to the operator's live level + finished-item count. The
// cursor is wired when a real in-game session proves the visual (the
// active_match panel feeds ctx.liveclient with gameData.gameTime).
//
// Backend wire:
//   GET /api/spike-markers?champion=<id>&level=<n>&items=<id,id>&mode=SR
//   Response: {
//     ok, champion, level, markers:[{kind, threshold, label, crossed,
//                  next, dps_at?}], next:{...}|null, count, elapsed_ms,
//                  cached
//   }
//
// The active_match render call supplies the operator's live champion id
// (DDragon slug), level, owned item ids, and mode. Discipline: pure ESM,
// ASCII only, sig-dedup gate, no DOM writes outside renderSpikeMarkers().
// Mirrors the cooldown_watch.js / spike_curve.js patterns.

const _SPM_CACHE = Object.create(null);     // cacheKey -> response JSON
const _SPM_INFLIGHT = Object.create(null);
const _SPM_TS = Object.create(null);
const _SPM_SIG = Object.create(null);       // mount-id -> last-rendered sig
const _SPM_TTL_MS = 5 * 60 * 1000;          // matches backend TTL

function _cacheKey(champion, level, itemCount, mode) {
  return [
    String(champion || ""),
    +level || 0,
    +itemCount || 0,
    String(mode || "SR").toUpperCase(),
  ].join("|");
}

// Fetch + memoize the operator's spike markers. champion is a DDragon
// slug; level is the live champion level; itemIds is the owned-item-id
// list (threaded to the DS curve for dps_at); itemCount is the finished-
// legendary count (optional - backend proxies from itemIds when absent).
// Returns nothing; caller re-renders on the next tick once the cache
// lands. ``onLand`` optional re-render callback.
export function fetchSpikeMarkers(champion, level, itemIds, mode, itemCount, onLand) {
  if (!champion) return;
  const key = _cacheKey(champion, level, itemCount, mode);
  const fresh = _SPM_CACHE[key] && _SPM_TS[key]
                && (Date.now() - _SPM_TS[key]) < _SPM_TTL_MS;
  if (fresh || _SPM_INFLIGHT[key]) return;
  _SPM_INFLIGHT[key] = true;
  const params = {
    champion: String(champion),
    level: String(+level || 1),
    mode: String(mode || "SR").toUpperCase(),
  };
  if (Array.isArray(itemIds) && itemIds.length) {
    params.items = itemIds.join(",");
  }
  if (itemCount != null && +itemCount >= 0) {
    params.item_count = String(+itemCount);
  }
  const qs = new URLSearchParams(params);
  fetch("/api/spike-markers?" + qs.toString(), { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      _SPM_INFLIGHT[key] = false;
      if (data) {
        _SPM_CACHE[key] = data;
        _SPM_TS[key] = Date.now();
        if (typeof onLand === "function") onLand();
      }
    })
    .catch(() => { _SPM_INFLIGHT[key] = false; });
}

export function getCachedSpikeMarkers(champion, level, itemCount, mode) {
  return _SPM_CACHE[_cacheKey(champion, level, itemCount, mode)] || null;
}

export function getSpikeMarkersCacheCount() {
  return Object.keys(_SPM_CACHE).length;
}

function _signature(payload) {
  if (!payload || !payload.ok) {
    return payload && payload.reason ? `_${payload.reason}` : "_empty";
  }
  const markers = Array.isArray(payload.markers) ? payload.markers : [];
  return markers
    .map((m) => `${m.kind}${m.threshold}:${m.crossed ? 1 : 0}${m.next ? "n" : ""}`)
    .join("|") || "_nomarkers";
}

// HTML-escape backend label text before innerHTML interpolation
// (defense-in-depth; the DS spike generator emits ASCII labels today but
// escape so a future table change can never inject markup here).
function _esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// State word for one marker: crossed | next | future.
function _state(m) {
  if (m.crossed) return "crossed";
  if (m.next) return "next";
  return "future";
}

// Short cell glyph for a level marker (the threshold number) or item
// marker (a filled / hollow pip count surrogate - we show the number).
// Coerced numeric so a non-finite threshold renders "" not "NaN".
function _cellLabel(m) {
  const n = Number(m.threshold);
  return Number.isFinite(n) ? `${n}` : "";
}

// Render the spike-markers strip into the provided element. payload is
// the backend response (may be null on cold-load). Idempotent - sig-dedup
// skips the DOM write when nothing changed.
export function renderSpikeMarkers(blockEl, payload) {
  if (!blockEl) return;
  const sigKey = blockEl.id || "_spm_default";
  const sig = _signature(payload);
  // Dedup, but only if the DOM still reflects the stamped sig. The outer
  // active_match.js hide path clears mount.innerHTML behind our back (the
  // sig stays stamped), so a re-show with identical data must still repaint
  // an externally-emptied mount instead of early-returning into a blank strip.
  if (_SPM_SIG[sigKey] === sig && blockEl.innerHTML !== "") return;
  _SPM_SIG[sigKey] = sig;

  if (!payload || !payload.ok) {
    blockEl.hidden = true;
    blockEl.innerHTML = "";
    return;
  }
  const markers = Array.isArray(payload.markers) ? payload.markers : [];
  if (!markers.length) {
    blockEl.hidden = true;
    blockEl.innerHTML = "";
    return;
  }
  blockEl.hidden = false;

  const levelMarks = markers.filter((m) => m.kind === "level");
  const itemMarks = markers.filter((m) => m.kind === "item");
  const next = payload.next || null;

  const cell = (m) => {
    const st = _state(m);
    const dpsN = Number(m.dps_at);
    const dps = (m.dps_at != null && Number.isFinite(dpsN))
      ? `<span class="spm-dps">${Math.round(dpsN)}</span>` : "";
    const lbl = _esc(m.label || "");
    return (
      `<div class="spm-cell" data-spm-state="${st}" title="${lbl}">`
      + `<span class="spm-mark">${_cellLabel(m)}</span>`
      + `<span class="spm-lbl">${lbl}</span>`
      + dps
      + `</div>`
    );
  };

  const levelRow = levelMarks.length
    ? (`<div class="spm-row">`
       + `<span class="spm-row-tag">LVL</span>`
       + `<div class="spm-track">${levelMarks.map(cell).join("")}</div>`
       + `</div>`)
    : "";
  const itemRow = itemMarks.length
    ? (`<div class="spm-row">`
       + `<span class="spm-row-tag">ITEMS</span>`
       + `<div class="spm-track">${itemMarks.map(cell).join("")}</div>`
       + `</div>`)
    : "";

  let nextLine = "";
  if (next) {
    const kindWord = next.kind === "level" ? "level" : "item";
    const nextThr = Number(next.threshold);
    const thrStr = Number.isFinite(nextThr) ? `${nextThr}` : "";
    const what = next.kind === "level"
      ? `level ${thrStr} (${_esc(next.label)})`
      : `${_esc(next.label)}`;
    nextLine = (
      `<div class="spm-next">NEXT SPIKE: ${what} - ${kindWord} threshold</div>`
    );
  } else {
    nextLine = `<div class="spm-next spm-next-done">all spikes online</div>`;
  }

  // OWED: the live-clock cursor line would render here, positioned by
  // payload.level + game_time against a minute axis. v1 omits it (live-
  // game-only visual). The discrete strip below is the headless half.
  blockEl.innerHTML = (
    `<div class="spm-head">`
    + `<span class="spm-head-title">Power spikes</span>`
    + `<span class="spm-head-sub">filled = online, ring = next</span>`
    + `</div>`
    + levelRow
    + itemRow
    + nextLine
  );
}

// Reset helper for tests (clears in-memory cache + sig stamps).
export function _resetSpikeMarkers() {
  for (const k of Object.keys(_SPM_CACHE))    delete _SPM_CACHE[k];
  for (const k of Object.keys(_SPM_INFLIGHT)) delete _SPM_INFLIGHT[k];
  for (const k of Object.keys(_SPM_TS))       delete _SPM_TS[k];
  for (const k of Object.keys(_SPM_SIG))      delete _SPM_SIG[k];
}

export const __test = {
  _cacheKey,
  _signature,
  _state,
  _cellLabel,
  _SPM_TTL_MS,
};
