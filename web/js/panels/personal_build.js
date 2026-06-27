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
  const usual = (payload.most_common_build || []).join(",");
  return champ + "#" + items
    .map((it) => `${it.item_id}:${Math.round((+it.lift || 0) * 100)}`)
    .join("|") + "#u:" + usual;
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

// Set of most_common_build ids (as strings) - the operator's MOST FREQUENT
// completed build, served alongside the win-rate ranking. Surfacing the
// popular build next to the win-rate build exposes the gap between "what you
// build" and "what you win with" (the survivorship-bias read).
function _usualSet(payload) {
  const ids = payload && Array.isArray(payload.most_common_build)
    ? payload.most_common_build : [];
  return new Set(ids.map((x) => String(x)));
}

// The popular-vs-winning survivorship insight, computed PURELY from the served
// payload (no DOM): an UNDERUSED WINNER (positive lift, NOT in the usual build)
// and/or an OVERUSED LOSER (negative lift, IN the usual build). A >=1pp gate
// drops sub-rounding noise. Returns {kind, text} or null.
function _usualBuildInsight(payload) {
  const items = _items(payload);
  if (!items.length) return null;
  const usual = _usualSet(payload);
  const pp = (it) => Math.round((+it.lift || 0) * 100);
  let winner = null;   // best positive-lift item NOT in the usual build
  let loser = null;    // most-negative-lift item IN the usual build
  for (const it of items) {
    const v = pp(it);
    const inUsual = usual.has(String(it.item_id));
    if (!inUsual && v >= 1 && (!winner || v > pp(winner))) winner = it;
    if (inUsual && v <= -1 && (!loser || v < pp(loser))) loser = it;
  }
  const nm = (it) => _esc(it.name || it.item_id || "");
  if (winner && loser) {
    return { kind: "swap",
      text: `Try ${nm(winner)} (+${pp(winner)}) over your usual `
        + `${nm(loser)} (${pp(loser)})` };
  }
  if (winner) {
    return { kind: "winner",
      text: `Underused: ${nm(winner)} (+${pp(winner)}) wins but is not `
        + `your usual build` };
  }
  if (loser) {
    return { kind: "loser", text: `Usual but losing: ${nm(loser)} (${pp(loser)})` };
  }
  return null;
}

function _rowHtml(it, usual) {
  const wr = _clampPct((+it.adj_win_rate || 0) * 100);
  // Sign drives the bar + lift color. A lift that rounds to 0pp is neutral
  // (muted), NOT red - a red "0" reads as a contradiction.
  const pp = Math.round((+it.lift || 0) * 100);
  const sign = pp > 0 ? "pos" : pp < 0 ? "neg" : "zero";
  const games = +it.games || 0;
  const inUsual = !!(usual && usual.has(String(it.item_id)));
  return (
    `<div class="pbw-row" data-usual="${inUsual ? 1 : 0}">`
    + `<span class="pbw-usual-pip" title="in your usual build"></span>`
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

  // Popular-vs-winning: the operator's MOST FREQUENT completed build shown
  // next to the win-rate ranking, resolved to names via the served
  // items (falls back to the raw id when a usual item was min-sample filtered
  // out of the ranked list).
  const usual = _usualSet(payload);
  const rows = items.map((it) => _rowHtml(it, usual)).join("");
  let usualLine = "";
  if (usual.size) {
    const nameById = Object.create(null);
    for (const it of items) nameById[String(it.item_id)] = it.name || it.item_id;
    const names = (payload.most_common_build || [])
      .map((id) => _esc(nameById[String(id)] || id));
    usualLine = `<div class="pbw-usual-build">`
      + `<span class="pbw-usual-label">Usual</span> ${names.join(", ")}</div>`;
  }

  const insight = _usualBuildInsight(payload);
  const insightLine = insight
    ? `<div class="pbw-insight" data-kind="${insight.kind}">${insight.text}</div>`
    : "";

  blockEl.innerHTML = head + note + usualLine
    + `<div class="pbw-rows">${rows}</div>` + insightLine;
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
  _usualSet,
  _usualBuildInsight,
  pbwModeForQueue,
  _PBW_TTL_MS,
};
