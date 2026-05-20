// Active Match panel module (s159 - step 1 scaffold, s170 - step 2/3 wiring,
//   s171 - step 4 map overlay).
//
// Step 1 (s159) shipped the empty render shell wired into the main dispatcher.
// Step 2/3 (s170) adds per-tick DS rerank by POSTing to /api/ds-preview.
// Step 4 (s171) ships the in-game map pane: static SR/ARAM/Arena/Brawl
//   base image + champion-dot overlay from /api/vision-state (enemies'
//   last_seen_pos / visible / missing_for_s / is_dead) + MIA badge for
//   enemies missing > 12s + gank warning band for enemy JG MIA > 20s.
//
// Auto-promote behavior (gating in main.js _viewAutoDerive):
//   activeMatchEnabled() AND mode in {sr, aram, arena, brawl}
//     -> "active-match"
// Otherwise the existing in-game default ("last-match") wins, so
// nothing changes for users who haven't opted in.

import { ITEMS } from '../lib/items_index.js';
import { scorerUnit } from '../lib/scorer_units.js';
import { renderThreatDonut } from './threat_donut.js';
import { renderCooldownLedger, attachCooldownLedgerHandlers } from './cd_ledger.js';

const _AM = {
  sub:        () => document.getElementById("am-sub"),
  callBody:   () => document.getElementById("am-call-body"),
  buildBody:  () => document.getElementById("am-build-body"),
  mapBody:    () => document.getElementById("am-map-body"),
  cdBody:     () => document.getElementById("cd-ledger-body"),
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
  lastTargetStats: null,   // s171.4: live target_armor/_mr/_hp from /api/ds-preview
  lastThreat:  null,       // s171.6: enemy team threat profile
  lastDefensive: null,     // s171.6: ranked defensive picks
  inFlight:  false,
};
const _DS_RERANK_COOLDOWN_MS = 4000;

function _dsRerankKey(champion, mode, level, items) {
  return `${champion}|${mode}|${level}|${(items || []).join(",")}`;
}

// Returns the most recent rank_for() result for the current inputs,
// scheduling a refetch in the background if the inputs changed or the
// cooldown has elapsed. Non-blocking - caller renders with whatever's
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
        _DS_RERANK.lastTargetStats = j.target_stats || null;
        _DS_RERANK.lastThreat = j.threat || null;
        _DS_RERANK.lastDefensive = Array.isArray(j.defensive) ? j.defensive : null;
      }
    })
    .catch(() => { _DS_RERANK.inFlight = false; });
  return _DS_RERANK.lastRows;
}

// s171.4: build a "vs N armor / M mr / K hp" caption so operator can
// see WHY the DS engine ranked items the way it did. Sourced from the
// /api/ds-preview response's target_stats field. Hidden when no live
// data (target_stats.source === "default-zero" or null).
function _dsTargetStatsCaption() {
  const t = _DS_RERANK.lastTargetStats;
  if (!t || t.source === "default-zero") return "";
  const a = Math.round(t.target_armor || 0);
  const m = Math.round(t.target_mr || 0);
  const hp = Math.round(t.target_max_hp || 0);
  const n = t.n_enemies | 0;
  // P1-L21: the backend's live-enemy path emits source="live-items"
  // (legacy item-only) OR "live-items+base" (P1-L4 champion-base layer
  // active - the in-game default once enemy champions resolve). Both are
  // the live itemization path; match either with a prefix test so the
  // base-layer variant doesn't fall through and render the raw literal.
  const tag = (typeof t.source === "string" && t.source.indexOf("live-items") === 0)
                ? `live - ${n} enemies`
            : t.source === "explicit-override" ? "synthetic"
            : t.source === "mode-level-curve" ? "mode curve" : t.source;
  return `vs ${a} armor - ${m} mr - ${hp} hp - ${tag}`;
}

// s171: opt-OUT (was opt-in). Active Match is the default in-game
// surface - it renders coach action/immediate/objective/next + DS
// live rerank + the static map with enemy dots. Operator opts OUT via
// ``?am=0`` or ``localStorage.activeMatch === '0'`` to fall back to
// the legacy MAP STATE / RIGHT NOW / NEXT / STATS panels in last-match.
export function activeMatchEnabled() {
  try {
    if (typeof location !== "undefined" && location.search) {
      if (location.search.includes("am=0")) {
        try { localStorage.setItem("activeMatch", "0"); } catch (_) {}
        return false;
      }
      if (location.search.includes("am=1")) {
        try { localStorage.setItem("activeMatch", "1"); } catch (_) {}
        return true;
      }
    }
    const stored = localStorage.getItem("activeMatch");
    if (stored === "0") return false;   // explicit opt-out
    return true;                         // default ON
  } catch (_) {
    return true;
  }
}

export function renderActiveMatch(payload, ctx) {
  // ctx: { mode: state.mode, lcuPhase: lcu.phase }
  // Defensive: every getter is null-safe so a missing pane in DOM
  // (older HTML cache) doesn't crash the dispatcher chain.
  const p = payload || {};
  const mode = (ctx && ctx.mode) || "-";
  const phase = (ctx && ctx.lcuPhase) || "-";

  // s171.2: freshness gate. The coach payload (state.coach.*) lives in
  // memory across games - when a game ends, the previous game's
  // immediate/action/objective/next stay populated until the next
  // game's coach tick overwrites them. Without a gate, the active-
  // match view shows stale "Recall now-Ryze respawn 47s" prompts from
  // the previous game while the operator is in champ-select for a new
  // one. Treat anything other than phase=InProgress as "between games"
  // and clear the coach panes so the operator isn't misled.
  const isLive = (phase === "InProgress");

  const sub = _AM.sub();
  if (sub) {
    if (isLive) {
      const champ = p.champion || "-";
      const time = p.game_time || "-";
      sub.textContent = `${mode.toUpperCase()} - ${champ} - ${time} - phase ${phase}`;
    } else {
      // Champ-select / loading / between games: no live coach yet.
      sub.textContent = phase
        ? `${mode.toUpperCase()} - phase ${phase} - waiting for in-game data`
        : `${mode.toUpperCase()} - waiting for in-game data`;
    }
  }

  // Step 1 placeholders - surface a few raw fields so the user can
  // confirm data is reaching the view before steps 2-4 fill in the
  // curated layout. Plain text only; no DOM scaffolding promised by
  // the final design (CALL fold, DS icons, static map) yet.
  const call = _AM.callBody();
  if (call) {
    if (!isLive) {
      // Stale-data guard: don't show previous-game prompts during
      // champ-select / loading / aftergame.
      call.innerHTML = "";
      call.appendChild(_line("RIGHT NOW",
        phase === "ChampSelect" ? "champ select - no in-game prompts yet"
        : phase === "GameStart" ? "loading screen - game starts soon"
        : "no in-game session - waiting for next game"));
      return;
    }
    const action = p.action || "";
    const immediate = p.immediate || "";
    const next = p.next || "";
    const objective = p.objective || "";
    // s171: ``immediate`` is the most actionable field - the coach's
    // RIGHT NOW prompt (e.g. "Recall now - Ryze + Yi respawn ~47s").
    // It was being dropped from the active-match render even though
    // every coach tick populates it. Now leads the panel above
    // ACTION/OBJECTIVE/NEXT so the operator sees the imminent call
    // first when they glance at the dashboard.
    if (action || immediate || next || objective) {
      call.innerHTML = "";
      if (immediate) call.appendChild(_line("RIGHT NOW", immediate));
      if (action)    call.appendChild(_line("ACTION",    action));
      if (objective) call.appendChild(_line("OBJECTIVE", objective));
      if (next)      call.appendChild(_line("NEXT",      next));
    } else {
      // Empty coach payload -> surface that we're waiting rather than
      // leave the panel blank. Operator's complaint "no coach prompts
      // because it doesn't know I'm in game" was partly this - the
      // panel rendered nothing while coach tick was lagging.
      call.innerHTML = "";
      call.appendChild(_line("RIGHT NOW", "waiting for coach tick..."));
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
      // s171.4: live target-stats caption - shows the operator what
      // armor/MR/HP profile the DS ranker is computing against, so
      // they can see when the rankings shift due to enemy itemization.
      const tgtCaption = _dsTargetStatsCaption();
      const label = tgtCaption ? `DS ENGINE - ${tgtCaption}` : "DS ENGINE";
      build.appendChild(_line(label, ""));
      build.appendChild(strip);
    }
    if (owned.length) {
      build.appendChild(_line("OWNED", owned.join(" - ")));
    }
    // s171.6: defensive-pick row. Renders only when enemy team's
    // threat score crosses the "worth recommending defense" line:
    //   burst_threat >= 5  (assassin / mage burst)
    //   OR ad_threat >= 7  (AD-heavy team)
    //   OR ap_threat >= 7  (AP-heavy team)
    // Shows up to 3 defensive picks with their reasons, plus the
    // threat summary so operator sees the "why".
    const threat = _DS_RERANK.lastThreat;
    const defensive = _DS_RERANK.lastDefensive;
    if (threat && Array.isArray(defensive) && defensive.length) {
      const bt = +threat.burst_threat || 0;
      const at = +threat.ad_threat || 0;
      const pt = +threat.ap_threat || 0;
      const surface = (bt >= 5) || (at >= 7) || (pt >= 7);
      if (surface) {
        const defLabel = `DEFENSE - ${threat.summary || "threat detected"}`;
        build.appendChild(_line(defLabel, ""));
        const defStrip = document.createElement("div");
        defStrip.style.cssText = "display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px;";
        defensive.slice(0, 3).forEach((r) => {
          defStrip.appendChild(_defIcon(r, ownedSet));
        });
        build.appendChild(defStrip);
      }
    }

    // UX-2 (2026-05-20): THREATS strip - per-enemy champion portrait +
    // inline damage-mix donut driven by /api/damage-mix. Reads from
    // ctx.liveclient.allPlayers + activePlayer.team (the active player's
    // team is excluded so we only see enemies). Skips silently when
    // liveclient is missing, when there are no enemy entries, or in
    // shared-vision modes where the operator already has full info.
    const lc = (ctx && ctx.liveclient) || null;
    if (lc && Array.isArray(lc.allPlayers) && lc.allPlayers.length) {
      const myTeam = _resolveMyTeam(lc);
      const enemies = lc.allPlayers.filter((pl) => pl && pl.team && pl.team !== myTeam);
      if (enemies.length) {
        build.appendChild(_line("THREATS", ""));
        const strip = document.createElement("div");
        strip.className = "threat-strip";
        strip.style.cssText = "display:flex;gap:10px;flex-wrap:wrap;margin-bottom:8px;align-items:center;";
        enemies.forEach((pl) => strip.appendChild(_threatRow(pl, mode, level)));
        build.appendChild(strip);
      }
    }

    if (!picks.length && !owned.length) {
      // Empty pane shouldn't be blank - surface that we're waiting.
      build.appendChild(_line("DS ENGINE", "waiting for live data..."));
    }
  }

  const map = _AM.mapBody();
  if (map) {
    // Step 4: render the mode's static base image + champion-dot
    // overlay from /api/vision-state. _renderAmMap is idempotent -
    // re-attaches the shell only on mode change, redraws the canvas
    // every tick.
    const modeLow = String((ctx && ctx.mode) || "sr").toLowerCase();
    _renderAmMap(map, modeLow, p);
  }

  // UX-3 (2026-05-20): right-rail CD ledger. Reads the
  // summoner_cooldowns array threaded via ctx (top-level /api/state
  // field; backend computes it in dashboard/_state_cooldowns.py and
  // returns null when no live game is running). Render is null-safe
  // and idempotent - sig-based dedup keeps the DOM stable across
  // sub-second tick churn. attachCooldownLedgerHandlers is idempotent
  // too (dataset.cdBound gate), safe to call every tick.
  const cdBody = _AM.cdBody();
  if (cdBody) {
    const cooldowns = (ctx && ctx.cooldowns) || null;
    renderCooldownLedger(cdBody, cooldowns, {
      liveclient: (ctx && ctx.liveclient) || null,
      version:    (ITEMS && ITEMS.version) || "16.10.1",
    });
    attachCooldownLedgerHandlers();
  }
}

// --- s171 step 4: map pane ------------------------------------------

// Static base image per mode. Falls back to /api/minimap-crop?mode=<x>
// when the static asset 404s (Arena/Brawl on builds without local
// asset prefetch).
const _AM_MAP_IMG = {
  sr:    "/data/ddragon/16.10.1/img/map/map11.png",
  aram:  "/data/ddragon/16.10.1/img/map/map12.png",
  arena: "/api/minimap-crop?mode=arena",
  brawl: "/api/minimap-crop?mode=brawl",
};
// World-coordinate map sizes. Mirror of main.js's VT_MAP_SIZE so the
// canvas projection matches the home-view overlay.
const _AM_MAP_WORLD = {
  CLASSIC:    14800,
  ARAM:       13800,
  KIWI:       13800,
  URF:        14800,
  NEXUSBLITZ: 14800,
  ULTBOOK:    14800,
};
// Shared-vision modes: Live Client emits no positions because the
// whole map is visible to both teams. Suppress the dot overlay but
// still surface the summary line (N visible / N dead).
const _AM_SHARED_VISION = new Set(["ARAM", "KIWI"]);
// MIA threshold (s) - render the badge when missing_for_s exceeds this.
const _AM_MIA_THRESHOLD = 12;
// Gank-warning threshold (s) for enemy JG missing outside their jungle.
const _AM_GANK_THRESHOLD = 20;
// Cadence: how often we re-poll /api/vision-state. 500ms matches the
// home-view's VT_INTERVAL_MS so dot positions don't lag.
const _AM_TICK_MS = 500;

const _AM_MAP = {
  attachedMode: null,    // last mode we rendered the shell for
  pollHandle:   null,    // setInterval handle
  vsCache:      null,    // last successful /api/vision-state response
};

function _renderAmMap(host, mode, payload) {
  // Allowed-mode gate. Arena/Brawl supported but rely on the live
  // minimap-crop endpoint since DDragon doesn't ship 30/33 statically.
  const knownMode = (mode in _AM_MAP_IMG) ? mode : "sr";
  if (_AM_MAP.attachedMode !== knownMode) {
    _AM_MAP.attachedMode = knownMode;
    host.innerHTML = "";
    const shell = document.createElement("div");
    shell.className = "am-map-shell";
    shell.style.cssText = "position:relative;width:100%;height:100%;display:flex;align-items:center;justify-content:center;";
    const img = document.createElement("img");
    img.id = "am-map-img";
    img.src = _AM_MAP_IMG[knownMode];
    img.alt = knownMode + " map";
    img.style.cssText = "max-width:100%;max-height:100%;object-fit:contain;display:block;";
    img.onerror = () => {
      // Fallback to live minimap-crop on local asset miss
      if (!img.dataset.fallback) {
        img.dataset.fallback = "1";
        img.src = "/api/minimap-crop?mode=" + encodeURIComponent(knownMode);
      } else {
        img.style.display = "none";
      }
    };
    shell.appendChild(img);
    const canvas = document.createElement("canvas");
    canvas.id = "am-map-overlay";
    canvas.style.cssText = "position:absolute;left:0;top:0;pointer-events:none;";
    shell.appendChild(canvas);
    const status = document.createElement("div");
    status.id = "am-map-status";
    status.style.cssText = "position:absolute;left:8px;top:8px;font-size:11px;color:#9ca3af;background:rgba(0,0,0,0.55);padding:3px 8px;border-radius:4px;letter-spacing:0.4px;text-transform:uppercase;font-weight:700;";
    status.textContent = "loading vision...";
    shell.appendChild(status);
    const ganker = document.createElement("div");
    ganker.id = "am-map-gank";
    ganker.style.cssText = "position:absolute;left:0;right:0;bottom:0;padding:6px 10px;font-size:12px;color:#fff;background:rgba(220,38,38,0.85);font-weight:700;letter-spacing:0.4px;text-transform:uppercase;display:none;text-align:center;";
    shell.appendChild(ganker);
    host.appendChild(shell);
    // Kick off the polling loop if not already running.
    _amStartMapPolling();
  }
  // Re-draw with cached vision state immediately so the user sees
  // something on the tick that triggered the render call.
  if (_AM_MAP.vsCache) _amDrawOverlay(_AM_MAP.vsCache);
}

function _amStartMapPolling() {
  if (_AM_MAP.pollHandle != null) return;
  const tick = () => {
    // Only poll while the active-match view is current - otherwise we
    // burn CPU + bandwidth on hidden surfaces.
    const view = document.body.dataset.view;
    if (view !== "active-match") return;
    fetch("/api/vision-state", { cache: "no-store" })
      .then((r) => r.ok ? r.json() : null)
      .then((vs) => {
        if (vs) {
          _AM_MAP.vsCache = vs;
          _amDrawOverlay(vs);
        }
      })
      .catch(() => { /* swallow - next tick retries */ });
  };
  tick();   // fire immediately so the first draw isn't 500ms late
  _AM_MAP.pollHandle = setInterval(tick, _AM_TICK_MS);
}

function _amDrawOverlay(vs) {
  const img    = document.getElementById("am-map-img");
  const canvas = document.getElementById("am-map-overlay");
  const status = document.getElementById("am-map-status");
  const ganker = document.getElementById("am-map-gank");
  if (!img || !canvas) return;
  if (!img.complete || !img.naturalWidth) return;
  const rect = img.getBoundingClientRect();
  const hostRect = img.parentElement.getBoundingClientRect();
  const w = Math.round(rect.width);
  const h = Math.round(rect.height);
  if (w < 4 || h < 4) return;
  canvas.style.left   = (rect.left - hostRect.left) + "px";
  canvas.style.top    = (rect.top  - hostRect.top)  + "px";
  canvas.style.width  = w + "px";
  canvas.style.height = h + "px";
  if (canvas.width  !== w) canvas.width  = w;
  if (canvas.height !== h) canvas.height = h;

  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, w, h);

  const enemies = (vs && vs.enemies) || {};
  const enemyList = Object.entries(enemies);
  const summary = (vs && vs.summary) || {};
  const gameModeUp = String((vs && vs.game_mode) || "").toUpperCase();
  const shared = _AM_SHARED_VISION.has(gameModeUp);

  // Status line - visible/missing/dead summary.
  if (status) {
    const visible = summary.visible_count | 0;
    const missing = summary.missing_count | 0;
    const dead    = summary.dead_count | 0;
    status.textContent = shared
      ? `${visible} on bridge - ${dead} dead`
      : `${visible} visible - ${missing} MIA - ${dead} dead`;
  }

  // Shared-vision (ARAM/Brawl-on-bridge): no position data, skip dots.
  if (shared) {
    if (ganker) ganker.style.display = "none";
    return;
  }

  const mapSize = _AM_MAP_WORLD[gameModeUp] || 14800;
  function project(x, z) {
    // Game origin = bottom-left, z grows up. Canvas y grows down -> flip.
    return [(x / mapSize) * w, h - (z / mapSize) * h];
  }

  // Gank warning: enemy with role-hint "JUNGLE" missing > _AM_GANK_THRESHOLD.
  // The vision_state schema doesn't carry role directly, so detect by
  // smite or by champion category. For now, surface ANY enemy missing
  // over the threshold whose last_seen_zone is "ENEMY_JUNGLE" or null
  // and whose missing_for_s exceeds the threshold.
  let gankAlert = null;

  for (const [name, e] of enemyList) {
    if (e.is_dead) continue;
    const pos = e.last_seen_pos;
    if (!pos || typeof pos.x !== "number") continue;
    const [px, py] = project(pos.x, pos.z);
    const missing = e.missing_for_s || 0;

    if (e.visible) {
      // Bright current-position dot
      ctx.beginPath();
      ctx.arc(px, py, 6, 0, Math.PI * 2);
      ctx.fillStyle = "rgba(240, 126, 139, 0.95)";
      ctx.fill();
      ctx.strokeStyle = "#fff";
      ctx.lineWidth = 1.5;
      ctx.stroke();
    } else {
      // Ghost dot fading with missing time
      const alpha = Math.max(0.25, 1.0 - missing / 30);
      ctx.beginPath();
      ctx.arc(px, py, 6, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(240, 126, 139, ${alpha})`;
      ctx.fill();
      ctx.strokeStyle = `rgba(255, 255, 255, ${alpha * 0.7})`;
      ctx.lineWidth = 1;
      ctx.stroke();
      // MIA badge
      if (missing > _AM_MIA_THRESHOLD) {
        const tag = `${name.slice(0, 6)} ${Math.round(missing)}s`;
        ctx.font = "bold 10px sans-serif";
        const txtW = ctx.measureText(tag).width;
        const bx = Math.min(w - txtW - 8, Math.max(4, px + 8));
        const by = Math.min(h - 14, Math.max(12, py - 4));
        ctx.fillStyle = "rgba(220, 38, 38, 0.85)";
        ctx.fillRect(bx - 3, by - 10, txtW + 6, 14);
        ctx.fillStyle = "#fff";
        ctx.fillText(tag, bx, by);
      }
      // Gank-watch: jungler-shaped missing pattern
      if (missing > _AM_GANK_THRESHOLD
          && (e.last_seen_zone === "ENEMY_JUNGLE"
              || e.last_seen_zone === "RIVER"
              || e.last_seen_zone === null)) {
        gankAlert = `${name} missing ${Math.round(missing)}s - ward / back off`;
      }
    }
  }

  if (ganker) {
    if (gankAlert) {
      ganker.textContent = "WARN " + gankAlert;
      ganker.style.display = "block";
    } else {
      ganker.style.display = "none";
    }
  }
}

// UX-2 (2026-05-20): liveclient team-of-active-player resolver. Mirrors
// core.enemy_aware_stats.active_player_team. The riotIdGameName form
// "Name#Tag" matches both the bare and the suffixed shapes that show
// up across summoner-name vs riotId payloads.
function _resolveMyTeam(lc) {
  if (!lc || typeof lc !== "object") return null;
  const ap = lc.activePlayer || {};
  const me = ap.summonerName || ap.riotIdGameName || "";
  if (!me) return null;
  const all = lc.allPlayers || [];
  for (const pl of all) {
    if (!pl || typeof pl !== "object") continue;
    const rid = pl.riotIdGameName || pl.summonerName || "";
    if (rid === me
        || me.startsWith(rid + "#")
        || rid === me.split("#", 1)[0]) {
      return pl.team || null;
    }
  }
  return null;
}

// UX-2 (2026-05-20): one enemy row = portrait + donut + champ name. The
// donut is appended via renderThreatDonut so the cache + fetch lifecycle
// is owned by the donut module. Item ids exclude slot >= 6 (trinket)
// since trinkets don't contribute to damage mix - matches the
// `enemy_items_from_liveclient` exclusion.
function _threatRow(pl, mode, level) {
  const row = document.createElement("div");
  row.className = "threat-row";
  row.style.cssText = "display:inline-flex;align-items:center;gap:4px;";

  const champ = pl.championName || pl.rawChampionName || "?";
  const portrait = document.createElement("img");
  portrait.className = "threat-portrait";
  portrait.alt = champ;
  portrait.title = champ;
  const ver = (ITEMS && ITEMS.version) || "16.10.1";
  // DDragon champion-square id is the championName (no spaces / apostrophes
  // for most; rawChampionName has the canonical id form when present).
  const champId = (pl.rawChampionName || champ).replace(/[^a-zA-Z0-9]/g, "");
  portrait.src = `/data/ddragon/${ver}/img/champion/${champId}.png`;
  portrait.style.cssText = "width:28px;height:28px;border-radius:50%;border:1px solid #303040;display:inline-block;vertical-align:middle;";
  portrait.onerror = () => {
    if (!portrait.dataset.cdnRetry) {
      portrait.dataset.cdnRetry = "1";
      portrait.src = `https://ddragon.leagueoflegends.com/cdn/${ver}/img/champion/${champId}.png`;
    } else {
      portrait.style.display = "none";
    }
  };
  row.appendChild(portrait);

  // Build the item-id list for /api/damage-mix. Same slot < 6 filter as
  // core.enemy_aware_stats.enemy_items_from_liveclient. Skip non-objects
  // and zero/missing item ids.
  const itemIds = [];
  const liveItems = Array.isArray(pl.items) ? pl.items : [];
  for (const it of liveItems) {
    if (!it || typeof it !== "object") continue;
    const slot = it.slot;
    if (slot != null && slot >= 6) continue;
    const iid = it.itemID || it.itemId || 0;
    if (iid) itemIds.push(String(iid));
  }

  renderThreatDonut(row, champId, itemIds, { level: level | 0 || 11, mode: String(mode || "SR").toUpperCase() });
  return row;
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

// s170 step 2 + s171 fix: render a single DS pick as an icon-with-overlay.
// Item icons live at /data/ddragon/<ver>/img/item/<id>.png on the dashboard
// (local DDragon cache) with the DDragon CDN as fallback when the local
// asset hasn't been pre-fetched. The s170 URL path
// (`perk-images/item-icons/`) was the runes/perks namespace and 404s for
// every item id, so every icon was falling through to the text tile.
// /api/state's `items` field uses item names so we match the OWNED
// overlay by lowercased name. The "+Ndps" overlay is the rerank delta
// from the current inventory baseline.
//
// Icon falls back to a labeled grey tile when the item_id isn't known
// (DS server occasionally returns names without ids during ARAM/Arena
// re-skin resolution) or both DDragon paths 404.
function _dsIcon(r, ownedSet) {
  const wrap = document.createElement("div");
  wrap.style.cssText = "position:relative;width:48px;text-align:center;";
  const name = r.name || r.item_name || "?";
  const id   = r.id   || r.item_id   || 0;
  const delta = (r.delta_dps != null ? r.delta_dps : (r.deltaDps || 0));
  const unit  = scorerUnit(r.scorer);
  const owned = ownedSet && ownedSet.has(String(name).toLowerCase());
  if (id) {
    const ver = (ITEMS && ITEMS.version) || "latest";
    const img = document.createElement("img");
    img.src = `/data/ddragon/${ver}/img/item/${id}.png`;
    img.alt = name;
    img.title = `${name} (+${(delta || 0).toFixed(0)}${unit})`;
    img.style.cssText = "width:44px;height:44px;border-radius:6px;border:1px solid var(--border, #303040);display:block;margin:0 auto;";
    img.onerror = () => {
      if (!img.dataset.cdnRetry) {
        img.dataset.cdnRetry = "1";
        img.src = `https://ddragon.leagueoflegends.com/cdn/${ver}/img/item/${id}.png`;
      } else {
        img.replaceWith(_dsIconFallback(name, id, delta));
      }
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

// s171.6: defensive pick icon - like _dsIcon but the caption is the
// item's category (lifeline / armor / mr / sustain / tenacity) +
// reason tooltip instead of a +Ndps delta. Amber border so they
// visually distinguish from the offensive DS strip.
function _defIcon(rec, ownedSet) {
  const wrap = document.createElement("div");
  wrap.style.cssText = "position:relative;width:62px;text-align:center;";
  const name = rec.name || "?";
  const id = rec.item_id || 0;
  const owned = ownedSet && ownedSet.has(String(name).toLowerCase());
  if (id) {
    const ver = (ITEMS && ITEMS.version) || "latest";
    const img = document.createElement("img");
    img.src = `/data/ddragon/${ver}/img/item/${id}.png`;
    img.alt = name;
    img.title = `${name} - ${rec.reason || rec.category || ""}`;
    img.style.cssText = "width:44px;height:44px;border-radius:6px;border:2px solid #f59e0b;display:block;margin:0 auto;";
    img.onerror = () => {
      if (!img.dataset.cdnRetry) {
        img.dataset.cdnRetry = "1";
        img.src = `https://ddragon.leagueoflegends.com/cdn/${ver}/img/item/${id}.png`;
      } else {
        img.replaceWith(_dsIconFallback(name, id, 0));
      }
    };
    wrap.appendChild(img);
  } else {
    wrap.appendChild(_dsIconFallback(name, id, 0));
  }
  if (owned) {
    const ow = document.createElement("div");
    ow.textContent = "OWNED";
    ow.style.cssText = "position:absolute;left:0;right:0;top:14px;text-align:center;font-size:9px;font-weight:700;letter-spacing:0.08em;background:rgba(0,0,0,0.7);color:#5dd47e;padding:2px 0;pointer-events:none;";
    wrap.appendChild(ow);
  }
  const cap = document.createElement("div");
  cap.textContent = rec.category || "";
  cap.style.cssText = "font-size:10px;font-weight:600;color:#f59e0b;margin-top:2px;text-transform:uppercase;letter-spacing:0.4px;";
  wrap.appendChild(cap);
  return wrap;
}

function _dsIconFallback(name, id, delta) {
  const tile = document.createElement("div");
  tile.style.cssText = "width:44px;height:44px;border-radius:6px;border:1px solid var(--border, #303040);background:var(--surface-2, #1d1d28);display:flex;align-items:center;justify-content:center;font-size:9px;color:var(--text-faint);text-align:center;line-height:1.1;padding:2px;box-sizing:border-box;";
  tile.title = `${name} (+${(delta || 0).toFixed(0)}dps)`;
  tile.textContent = String(name).slice(0, 8);
  return tile;
}
