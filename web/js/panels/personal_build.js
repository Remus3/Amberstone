// Personal best-build card (Overlay App E personal-WR build override, local-data
// half; docs/COMPETITOR_LIFT_2026-06-16.md). A READ-ONLY ranked list for
// the operator's LOCKED champion: the completed items they actually WIN with
// on that champion, computed from their OWN rewind_history.db - a "your best
// build" read ALONGSIDE the DS engine recommendation, never a change to the
// DS default ranking. Items are scored by confidence-weighted win-rate LIFT
// vs the player's own baseline (core/smoothed_rates shrink) so a 2-0 item
// cannot outrank a 40-26 one.
//
// Backend wire:
//   GET /api/personal-build?champion=<champ>&mode=sr|aram|arena
//   Response (the compute_personal_build dict; NO `ok` field - gate on
//   `items`): {
//     champion, champion_id, mode, games, win_rate, baseline_win_rate,
//     confidence ("ok"|"thin"|"insufficient"|...), items:[{item_id, name,
//     games, wins, win_rate, adj_win_rate, lift, is_boots}],
//     most_common_build:[id...], source, cached, elapsed_ms
//   }
//
// The locked champion comes from cs.my_champion (numeric LCU championId)
// resolved via resolveChampNames (champ_select side). Mode comes from
// cs.queue_id, lowercased to the route's sr|aram|arena vocabulary.
//
// Discipline: pure ESM, ASCII only, sig-dedup gate on the render, no DOM
// writes outside renderPersonalBuild(). Mirrors cooldown_watch.js /
// ds_relscore.js.

const _PBW_CACHE = Object.create(null);     // cacheKey -> response JSON
const _PBW_INFLIGHT = Object.create(null);
const _PBW_TS = Object.create(null);
const _PBW_SIG = Object.create(null);
const _PBW_TTL_MS = 5 * 60 * 1000;          // matches backend TTL

// queue_id -> personal-build mode (the route's lowercase vocabulary).
// Mirrors ds_relscore.js _DSR_MODE_MAP but lowercased for /api/personal-build.
const _PBW_MODE_MAP = {
  450: "aram", 920: "aram", 2400: "aram",
  1750: "arena", 1700: "arena", 1710: "arena",
  400: "sr", 420: "sr", 430: "sr", 440: "sr",
  830: "sr", 840: "sr", 850: "sr",
};

export function pbwModeForQueue(queueId) {
  return _PBW_MODE_MAP[queueId | 0] || "sr";
}

function _cacheKey(champ, mode) {
  return [champ, mode].join("|");
}

export function fetchPersonalBuild(champ, mode, onLand) {
  if (!champ) return;
  const key = _cacheKey(champ, mode);
  const fresh = _PBW_CACHE[key] && _PBW_TS[key]
                && (Date.now() - _PBW_TS[key]) < _PBW_TTL_MS;
  if (fresh || _PBW_INFLIGHT[key]) return;
  _PBW_INFLIGHT[key] = true;
  const qs = new URLSearchParams({ champion: champ, mode });
  fetch("/api/personal-build?" + qs.toString(), { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      _PBW_INFLIGHT[key] = false;
      if (data) {
        _PBW_CACHE[key] = data;
        _PBW_TS[key] = Date.now();
        if (typeof onLand === "function") onLand();
      }
    })
    .catch(() => { _PBW_INFLIGHT[key] = false; });
}

export function getCachedPersonalBuild(champ, mode) {
  return _PBW_CACHE[_cacheKey(champ, mode)] || null;
}

export function getPersonalBuildCacheCount() {
  return Object.keys(_PBW_CACHE).length;
}

function _items(payload) {
  return payload && Array.isArray(payload.items) ? payload.items : [];
}

function _signature(payload) {
  const items = _items(payload);
  if (!payload || !items.length) {
    return payload && payload.confidence ? `_${payload.confidence}` : "_empty";
  }
  const champ = payload.champion || "";
  return champ + "#" + items
    .map((it) => `${it.item_id}:${Math.round((+it.lift || 0) * 100)}`)
    .join("|");
}

// HTML-escape backend item names / champ slug before innerHTML
// interpolation (defense-in-depth at the render boundary).
function _esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function _clampPct(p) {
  const n = +p || 0;
  if (n < 0) return 0;
  if (n > 100) return 100;
  return n;
}

// Signed whole-percentage-point lift label: "+9" / "-4" / "0".
function _liftLabel(lift) {
  const pp = Math.round((+lift || 0) * 100);
  return pp > 0 ? `+${pp}` : String(pp);
}

function _rowHtml(it) {
  const wr = _clampPct((+it.adj_win_rate || 0) * 100);
  // Sign drives the bar + lift color. A lift that rounds to 0pp is neutral
  // (muted), NOT red - a red "0" reads as a contradiction.
  const pp = Math.round((+it.lift || 0) * 100);
  const sign = pp > 0 ? "pos" : pp < 0 ? "neg" : "zero";
  const games = +it.games || 0;
  return (
    `<div class="pbw-row">`
    + `<span class="pbw-item">${_esc(it.name || it.item_id || "")}</span>`
    + `<span class="pbw-bar"><span class="pbw-bar-fill" data-sign="${sign}"`
    + ` style="width:${wr}%"></span></span>`
    + `<span class="pbw-lift" data-sign="${sign}">${_liftLabel(it.lift)}</span>`
    + `<span class="pbw-games">${games}g</span>`
    + `</div>`
  );
}

// Render the personal best-build card into the provided element. payload is
// the backend response (may be null on cold-load). Hidden until the locked
// champion has a non-empty, above-threshold item list.
export function renderPersonalBuild(blockEl, payload) {
  if (!blockEl) return;
  const sigKey = blockEl.id || "_pbw_default";
  const sig = _signature(payload);
  if (_PBW_SIG[sigKey] === sig) return;
  _PBW_SIG[sigKey] = sig;

  const items = _items(payload);
  if (!payload || !items.length) {
    blockEl.hidden = true;
    return;
  }
  blockEl.hidden = false;

  const champ = _esc(payload.champion || "");
  const games = +payload.games || 0;
  const baseline = payload.baseline_win_rate != null
    ? Math.round(payload.baseline_win_rate * 100) : null;
  const thin = payload.confidence === "thin";

  const head = (
    `<div class="pbw-head">`
    + `<span class="pbw-head-title">Your best build</span>`
    + `<span class="pbw-head-sub">${champ}: items you win with`
    + (baseline != null ? ` (baseline ${baseline}% / ${games}g)` : "")
    + `</span>`
    + `</div>`
  );
  const note = thin
    ? `<div class="pbw-thin">thin sample - directional only</div>` : "";
  const rows = items.map(_rowHtml).join("");

  blockEl.innerHTML = head + note + `<div class="pbw-rows">${rows}</div>`;
}

// Reset helper for tests (clears in-memory cache + sig stamps).
export function _resetPersonalBuild() {
  for (const k of Object.keys(_PBW_CACHE))    delete _PBW_CACHE[k];
  for (const k of Object.keys(_PBW_INFLIGHT)) delete _PBW_INFLIGHT[k];
  for (const k of Object.keys(_PBW_TS))       delete _PBW_TS[k];
  for (const k of Object.keys(_PBW_SIG))      delete _PBW_SIG[k];
}

export const __test = {
  _cacheKey,
  _signature,
  _liftLabel,
  _clampPct,
  pbwModeForQueue,
  _PBW_TTL_MS,
};
