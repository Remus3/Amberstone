// Active Match panel module (s159 — step 1 scaffold, s170 — step 2/3 wiring).
//
// Step 1 (s159) shipped the empty render shell wired into the main dispatcher.
// Step 2/3 (s170) adds per-tick DS rerank by POSTing to /api/ds-preview
// with the live champion + level + items + mode. The endpoint is locally
// hosted (same Legion box, same process), so round-trip is sub-100ms and
// the DS engine call lives behind the existing supervisor on :8893.
//
// Auto-promote behavior (gating in main.js _viewAutoDerive):
//   activeMatchEnabled() AND mode in {sr, aram, arena, brawl}
//     → "active-match"
// Otherwise the existing in-game default ("last-match") wins, so
// nothing changes for users who haven't opted in.

const _AM = {
  sub:        () => document.getElementById("am-sub"),
  callBody:   () => document.getElementById("am-call-body"),
  buildBody:  () => document.getElementById("am-build-body"),
  mapBody:    () => document.getElementById("am-map-body"),
};

// s170 (step 2): per-tick DS rerank cache. Keyed by a coarse "input
// fingerprint" so we don't refetch on every state envelope (~1 Hz)
// when nothing meaningful changed. Cooldown floors the refetch rate
// to once per 4s even when inputs change rapidly, so the DS engine
// doesn't get hammered during e.g. an active item-purchase spree.
const _DS_RERANK = {
  lastKey:   "",
  lastFired: 0,
  lastRows:  null,
  inFlight:  false,
};
const _DS_RERANK_COOLDOWN_MS = 4000;

function _dsRerankKey(champion, mode, level, items) {
  return `${champion}|${mode}|${level}|${(items || []).join(",")}`;
}

// Returns the most recent rank_for() result for the current inputs,
// scheduling a refetch in the background if the inputs changed or the
// cooldown has elapsed. Non-blocking — caller renders with whatever's
// already cached. The next render() call will pick up the new rows
// once the POST completes.
function _maybeRefreshDsPicks(champion, mode, level, items) {
  if (!champion || !mode) return _DS_RERANK.lastRows;
  const key = _dsRerankKey(champion, mode, level, items);
  const now = Date.now();
  const stale = (key !== _DS_RERANK.lastKey)
              || ((now - _DS_RERANK.lastFired) > _DS_RERANK_COOLDOWN_MS);
  if (!stale || _DS_RERANK.inFlight) return _DS_RERANK.lastRows;
  _DS_RERANK.inFlight  = true;
  _DS_RERANK.lastKey   = key;
  _DS_RERANK.lastFired = now;
  fetch("/api/ds-preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      champion: champion,
      mode:     mode,
      level:    level | 0,
      items:    items || [],
    }),
  }).then((r) => r.ok ? r.json() : null)
    .then((j) => {
      _DS_RERANK.inFlight = false;
      if (j && j.ok && Array.isArray(j.ranked)) {
        _DS_RERANK.lastRows = j.ranked;
      }
    })
    .catch(() => { _DS_RERANK.inFlight = false; });
  return _DS_RERANK.lastRows;
}

// Flag check used by main.js view-router. Two opt-in paths so the
// preference survives a refresh:
//   1. ?am=1 in the URL — one-shot for testing.
//   2. localStorage.activeMatch === '1' — sticky for daily use.
export function activeMatchEnabled() {
  try {
    if (typeof location !== "undefined"
        && location.search
        && location.search.includes("am=1")) {
      // Sticky-promote when the URL flag fires so the next load
      // doesn't need the query string. Operator can clear via
      // localStorage.removeItem('activeMatch').
      try { localStorage.setItem("activeMatch", "1"); } catch (_) {}
      return true;
    }
    return localStorage.getItem("activeMatch") === "1";
  } catch (_) {
    return false;
  }
}

export function renderActiveMatch(payload, ctx) {
  // ctx: { mode: state.mode, lcuPhase: lcu.phase }
  // Defensive: every getter is null-safe so a missing pane in DOM
  // (older HTML cache) doesn't crash the dispatcher chain.
  const p = payload || {};
  const mode = (ctx && ctx.mode) || "—";
  const phase = (ctx && ctx.lcuPhase) || "—";

  const sub = _AM.sub();
  if (sub) {
    const champ = p.champion || "—";
    const time = p.game_time || "—";
    sub.textContent = `${mode.toUpperCase()} · ${champ} · ${time} · phase ${phase}`;
  }

  // Step 1 placeholders — surface a few raw fields so the user can
  // confirm data is reaching the view before steps 2-4 fill in the
  // curated layout. Plain text only; no DOM scaffolding promised by
  // the final design (CALL fold, DS icons, static map) yet.
  const call = _AM.callBody();
  if (call) {
    const action = p.action || "";
    const next = p.next || "";
    const objective = p.objective || "";
    if (action || next || objective) {
      call.innerHTML = ""; // clear placeholder
      if (action)    call.appendChild(_line("ACTION",    action));
      if (objective) call.appendChild(_line("OBJECTIVE", objective));
      if (next)      call.appendChild(_line("NEXT",      next));
    }
  }

  const build = _AM.buildBody();
  if (build) {
    // s170 step 2: per-tick rerank. Coach-emitted picks
    // (state.daemon_slayer_picks, written every coach tick) are the
    // fallback; the live rerank goes through /api/ds-preview every
    // 4s when champion/mode/level/items change. Live rerank wins when
    // available because it's freshly computed against the current
    // inventory, not the coach's last snapshot.
    const champion = p.champion || "";
    const mode     = (ctx && ctx.mode) ? String(ctx.mode).toUpperCase() : "SR";
    const level    = parseInt(p.level || 0, 10) || 1;
    const owned    = Array.isArray(p.items) ? p.items : [];
    const ownedSet = new Set(owned.map((o) => String(o || "").toLowerCase()));
    const livePicks  = _maybeRefreshDsPicks(champion, mode, level, owned);
    const coachPicks = Array.isArray(p.daemon_slayer_picks) ? p.daemon_slayer_picks : [];
    const picks = (livePicks && livePicks.length) ? livePicks : coachPicks;
    build.innerHTML = "";
    if (picks.length) {
      const strip = document.createElement("div");
      strip.style.cssText = "display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px;";
      picks.slice(0, 5).forEach((r) => {
        strip.appendChild(_dsIcon(r, ownedSet));
      });
      build.appendChild(_line("DS ENGINE", ""));
      build.appendChild(strip);
    }
    if (owned.length) {
      build.appendChild(_line("OWNED", owned.join(" · ")));
    }
    if (!picks.length && !owned.length) {
      // Empty pane shouldn't be blank — surface that we're waiting.
      build.appendChild(_line("DS ENGINE", "waiting for live data…"));
    }
  }

  const map = _AM.mapBody();
  if (map) {
    // Step 1 placeholder — step 4 swaps in the static SR/ARAM/Arena
    // map image + ZOI/threat overlay layer.
    const enemyComp = Array.isArray(p.enemy_comp) ? p.enemy_comp : [];
    if (enemyComp.length) {
      map.innerHTML = "";
      map.appendChild(_line("ENEMY", enemyComp.join(" / ")));
    }
  }
}

function _line(label, value) {
  const row = document.createElement("div");
  row.style.cssText = "margin-bottom:10px;font-size:13px;line-height:1.45;";
  const lbl = document.createElement("span");
  lbl.style.cssText = "color:var(--text-faint);letter-spacing:0.12em;font-size:10px;font-weight:700;display:block;margin-bottom:2px;";
  lbl.textContent = label;
  const val = document.createElement("span");
  val.style.cssText = "color:var(--text);";
  val.textContent = value;
  row.appendChild(lbl);
  row.appendChild(val);
  return row;
}

// s170 step 2: render a single DS pick as an icon-with-overlay.
// CommunityDragon CDN hosts the per-patch item icon at a stable path;
// /api/state's `items` field uses item names so we match the OWNED
// overlay by lowercased name. The "+Ndps" overlay is the rerank delta
// from the current inventory baseline.
//
// Icon falls back to a labeled grey tile when the item_id isn't known
// (DS server occasionally returns names without ids during ARAM/Arena
// re-skin resolution).
function _dsIcon(r, ownedSet) {
  const wrap = document.createElement("div");
  wrap.style.cssText = "position:relative;width:48px;text-align:center;";
  const name = r.name || r.item_name || "?";
  const id   = r.id   || r.item_id   || 0;
  const delta = (r.delta_dps != null ? r.delta_dps : (r.deltaDps || 0));
  const owned = ownedSet && ownedSet.has(String(name).toLowerCase());
  if (id) {
    const img = document.createElement("img");
    img.src = `https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/item-icons/${id}.png`;
    img.alt = name;
    img.title = `${name} (+${(delta || 0).toFixed(0)}dps)`;
    img.style.cssText = "width:44px;height:44px;border-radius:6px;border:1px solid var(--border, #303040);display:block;margin:0 auto;";
    img.onerror = () => {
      // Fallback for items missing on the CDN (Arena re-skins occasionally).
      img.replaceWith(_dsIconFallback(name, id, delta));
    };
    wrap.appendChild(img);
  } else {
    wrap.appendChild(_dsIconFallback(name, id, delta));
  }
  if (owned) {
    const ow = document.createElement("div");
    ow.textContent = "OWNED";
    ow.style.cssText = "position:absolute;left:0;right:0;top:14px;text-align:center;font-size:9px;font-weight:700;letter-spacing:0.08em;background:rgba(0,0,0,0.7);color:#5dd47e;padding:2px 0;pointer-events:none;";
    wrap.appendChild(ow);
  }
  const dlt = document.createElement("div");
  dlt.textContent = `+${(delta || 0).toFixed(0)}`;
  dlt.style.cssText = "font-size:11px;font-weight:600;color:var(--accent, #6cf);margin-top:2px;";
  wrap.appendChild(dlt);
  return wrap;
}

function _dsIconFallback(name, id, delta) {
  const tile = document.createElement("div");
  tile.style.cssText = "width:44px;height:44px;border-radius:6px;border:1px solid var(--border, #303040);background:var(--surface-2, #1d1d28);display:flex;align-items:center;justify-content:center;font-size:9px;color:var(--text-faint);text-align:center;line-height:1.1;padding:2px;box-sizing:border-box;";
  tile.title = `${name} (+${(delta || 0).toFixed(0)}dps)`;
  tile.textContent = String(name).slice(0, 8);
  return tile;
}
