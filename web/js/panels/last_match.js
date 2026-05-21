/* s219: Last Match panel.
 *
 * Renders the post-game review for the most-recent non-TFT match
 * captured in data/match_history.db. Wired into main.js via
 * applyView("last-match") → wireLastMatchOnce() + fetchAndRenderLastMatch().
 *
 * Data shape from /api/last-match (see dashboard/builders._build_last_match):
 *   {
 *     found, match: {id, mode, champion, grade, kda_str, kda_ratio,
 *                    duration_s, kills/deaths/assists, cs, cs_per_min,
 *                    gold, gold_per_min, kp_pct, ds_picks: [...]},
 *     history_count, quick_review: {right, wrong_team, my_chronic}
 *   }
 * Each Quick Review item is {text, why} - `why` becomes the data-tt-html
 * tooltip on hover so the analysis stays explainable.
 *
 * Champion deep-link: clicking the champion name stashes the champion to
 * sessionStorage.rc-history-focus-champion and routes to view-history
 * (mirrors the s218 Home Tonight's Pick "Jinx" name behavior).
 *
 * Deep Review button: stashes the match id to
 * sessionStorage.rc-replay-focus-match and routes to view-replay so
 * the Replay page auto-selects this match. The Replay view itself
 * is the s220 S5 "deep review" target (per-frame scrubber + event
 * ribbon over Match-V5 timeline).
 */

// CHAMPS.byId is async-hydrated from /data/champions_index.json by
// the items_index.js loader. Until that fetch resolves, byId is {} -
// the team-comp row renderer falls back to a numeric id label so it
// stays informative rather than blank. ITEMS.version drives item
// icon paths so we stay current with the patch.
import { CHAMPS, ITEMS } from '../lib/items_index.js';
// Item C (s220): rich DDragon item tooltips via the shared app-wide
// data-tt-html plumbing - same lib champ_select.js uses (s213).
import { itemTooltipHtml, preloadLolDescriptions } from '../lib/lol_descriptions.js';
// s220 PGR S2: phases-that-mattered (WPA decomposition of the timeline).
import { fetchAndRenderPhases, clearPhases } from './post_game_phases.js';

// Numeric summoner-spell id → DDragon filename. Covers SR + ARAM common
// set; Arena (CHERRY) spell ids are not in this map and fall back to a
// blank slot. Source: DDragon summoner.json. Extend if a new spell ships.
const SUMMONER_SPELL_BY_ID = {
  1:  "SummonerBoost",           // Cleanse
  3:  "SummonerExhaust",
  4:  "SummonerFlash",
  6:  "SummonerHaste",           // Ghost
  7:  "SummonerHeal",
  11: "SummonerSmite",
  12: "SummonerTeleport",
  13: "SummonerMana",            // Clarity
  14: "SummonerDot",             // Ignite
  21: "SummonerBarrier",
  30: "SummonerPoroRecall",
  31: "SummonerPoroThrow",
  32: "SummonerSnowball",        // legacy ARAM Mark
  39: "SummonerSnowURFSnowball_Mark", // current ARAM Mark
  54: "Summoner_UltBookPlaceholder",
  55: "SummonerSmiteSweep",      // ult-book smite
};

function _ddragonVersion() {
  // Unpinned s219 v3: local mirror auto-refreshes via tools/ddragon_mirror_refresh.py
  // (item 101, RC-DDragonMirrorRefresh daily); ITEMS.version drives all asset
  // URLs. Hardcoded fallback only fires before items_index.json loads.
  return (ITEMS && ITEMS.version) || "16.10.1";
}

// onerror chain: try local at current ITEMS.version first; on 404 fall
// back to the official DDragon CDN at the same version. Mirrors the
// active_match.js cdnRetry pattern. Stays in place as a safety net for
// the gap between a new patch on DDragon and the next RC-DDragonMirrorRefresh
// run (daily 03:30).
function _onErrCdnFallback(ver, kind, id) {
  // kind = "item" | "spell" - only used to build the CDN url
  const cdnUrl = `https://ddragon.leagueoflegends.com/cdn/${ver}/img/${kind}/${id}.png`;
  return (
    `if(this.dataset.cdn){this.style.visibility='hidden';}` +
    `else{this.dataset.cdn='1';this.src='${cdnUrl}';}`
  );
}

function _itemIconUrl(iid) {
  return iid ? `/data/ddragon/${_ddragonVersion()}/img/item/${iid}.png` : "";
}
function _itemImgTag(iid, cls = "", title = "") {
  if (!iid) return "";
  const ver = _ddragonVersion();
  const localUrl = `/data/ddragon/${ver}/img/item/${iid}.png`;
  const onErr = _onErrCdnFallback(ver, "item", `${iid}.png`);
  const safeTitle = title ? `title="${String(title).replace(/"/g, "&quot;")}"` : "";
  // Item C (s220): rich DDragon tooltip via the app-wide data-tt-html
  // plumbing (mirrors champ_select.js). itemTooltipHtml() returns ""
  // until /api/dictionary/items lands; the rc:lol-descriptions-ready
  // listener triggers a re-render so icons pick up the attr next paint.
  const lolHtml = itemTooltipHtml(iid);
  const ttAttr = lolHtml ? ` data-tt-html="${lolHtml.replace(/"/g, "&quot;")}"` : "";
  return `<img class="${cls}" src="${localUrl}" alt="" ${safeTitle}${ttAttr} loading="lazy" onerror="${onErr}">`;
}

function _summonerIconUrl(sid) {
  const key = SUMMONER_SPELL_BY_ID[sid];
  return key ? `/data/ddragon/${_ddragonVersion()}/img/spell/${key}.png` : "";
}
function _summonerImgTag(sid, cls = "") {
  const key = SUMMONER_SPELL_BY_ID[sid];
  if (!key) return "";
  const ver = _ddragonVersion();
  const localUrl = `/data/ddragon/${ver}/img/spell/${key}.png`;
  const onErr = _onErrCdnFallback(ver, "spell", `${key}.png`);
  return `<img class="${cls}" src="${localUrl}" alt="spell ${sid}" loading="lazy" onerror="${onErr}">`;
}

let _wired = false;
// Item C (s220): cached so the rc:lol-descriptions-ready listener can
// re-render once the DDragon item-description fetch resolves.
let _lastData = null;

// s-PGR-S2 (#9 augments): id -> {name, icon_url, rarity} from
// /api/dictionary/augments (the patch-versioned cherry_augments
// snapshot). Async like CHAMPS.byId - empty until the fetch lands;
// _loadAugments() re-renders once so the roster picks up icons. Only
// ARAM Mayhem (KIWI) / Arena (CHERRY) rosters carry non-zero ids;
// SR roster augments are all 0 so nothing renders + the grid stays
// the pre-S2 8-column layout (byte-identical).
let _AUGMENTS = {};
let _augLoaded = false;

function _loadAugments() {
  if (_augLoaded) return;
  fetch("/api/dictionary/augments", { headers: { "Accept": "application/json" } })
    .then((r) => (r.ok ? r.json() : null))
    .then((d) => {
      _AUGMENTS = (d && d.augments) || {};
      _augLoaded = true;
      if (_lastData) renderLastMatch(_lastData);
    })
    .catch(() => { _augLoaded = true; });  // give up quietly; rows just omit augments
}

function _augRarityShort(rarity) {
  // cherry rarity is kBronze/kSilver/kGold/kPrismatic/kEventChoice.
  const r = String(rarity || "").replace(/^k/, "");
  return r === "EventChoice" ? "Event" : r;
}

// Per-player augment icon strip. Filters the trailing 0s the LCU
// pads playerAugment{1..6} with; skips ids missing from the dict
// (Mayhem-only ids occasionally absent from the Arena cherry set) so
// an unknown id degrades to nothing rather than a broken image.
function _augIconsHtml(augArr) {
  if (!_augLoaded || !Array.isArray(augArr)) return "";
  const ids = augArr.filter((x) => Number(x) > 0);
  if (!ids.length) return "";
  const cells = ids.map((id) => {
    const info = _AUGMENTS[String(id)];
    if (!info || !info.icon_url) return "";
    const rar = _augRarityShort(info.rarity);
    const nm = info.name || `augment ${id}`;
    const title = rar ? `${nm} (${rar})` : nm;
    return `<img class="lm-tc-aug" src="${info.icon_url}" alt=""` +
      ` title="${_escHtml(title)}" data-rarity="${_escHtml(rar.toLowerCase())}"` +
      ` loading="lazy" onerror="this.style.display='none'">`;
  }).join("");
  return cells;
}

// s219 v6: rank-tier comparison sample averages per game mode.
// Hand-curated placeholder data - backend aggregates from
// rewind_history.db are a future settings page follow-up. Keys are
// the dropdown values; values are {mode: {cs, cs_per_min, kda, kp,
// damage, tanked, vision, healing}} expressing what an "average
// <tier>" looks like in that mode. ARAM values are smaller because
// the mode runs ~12min average vs SR's ~30min.
const _RANK_TIER_AVERAGES = {
  iron:        { ARAM:{cs:35, cs_per_min:2.9, kda:1.6, kp:55, damage:11000, tanked:18000, vision:0, healing:1500},
                 SR:  {cs:140,cs_per_min:4.7, kda:1.7, kp:50, damage:14000, tanked:21000, vision:18,healing:2500} },
  bronze:      { ARAM:{cs:42, cs_per_min:3.5, kda:1.9, kp:58, damage:13000, tanked:21000, vision:0, healing:1800},
                 SR:  {cs:165,cs_per_min:5.5, kda:2.0, kp:53, damage:16500, tanked:23000, vision:21,healing:2800} },
  silver:      { ARAM:{cs:48, cs_per_min:4.0, kda:2.1, kp:60, damage:15000, tanked:23000, vision:0, healing:2100},
                 SR:  {cs:185,cs_per_min:6.2, kda:2.2, kp:55, damage:18500, tanked:25000, vision:24,healing:3000} },
  gold:        { ARAM:{cs:55, cs_per_min:4.6, kda:2.4, kp:62, damage:17500, tanked:25000, vision:0, healing:2400},
                 SR:  {cs:205,cs_per_min:6.8, kda:2.5, kp:58, damage:21000, tanked:27000, vision:27,healing:3300} },
  platinum:    { ARAM:{cs:62, cs_per_min:5.2, kda:2.7, kp:64, damage:20000, tanked:27000, vision:0, healing:2700},
                 SR:  {cs:225,cs_per_min:7.5, kda:2.8, kp:60, damage:23500, tanked:29000, vision:30,healing:3600} },
  emerald:     { ARAM:{cs:68, cs_per_min:5.7, kda:3.0, kp:66, damage:22500, tanked:29000, vision:0, healing:2900},
                 SR:  {cs:240,cs_per_min:8.0, kda:3.1, kp:62, damage:25500, tanked:30500, vision:33,healing:3800} },
  diamond:     { ARAM:{cs:75, cs_per_min:6.2, kda:3.3, kp:68, damage:25000, tanked:31000, vision:0, healing:3200},
                 SR:  {cs:260,cs_per_min:8.7, kda:3.4, kp:64, damage:28000, tanked:32000, vision:36,healing:4100} },
  master:      { ARAM:{cs:80, cs_per_min:6.7, kda:3.6, kp:70, damage:27500, tanked:33000, vision:0, healing:3500},
                 SR:  {cs:280,cs_per_min:9.3, kda:3.7, kp:66, damage:30500, tanked:33500, vision:39,healing:4400} },
  grandmaster: { ARAM:{cs:85, cs_per_min:7.1, kda:3.9, kp:72, damage:30000, tanked:35000, vision:0, healing:3800},
                 SR:  {cs:300,cs_per_min:10.0,kda:4.0, kp:68, damage:33000, tanked:35000, vision:42,healing:4700} },
  challenger:  { ARAM:{cs:90, cs_per_min:7.5, kda:4.2, kp:74, damage:32500, tanked:37000, vision:0, healing:4100},
                 SR:  {cs:320,cs_per_min:10.7,kda:4.3, kp:70, damage:36000, tanked:37000, vision:45,healing:5000} },
};
const _RANK_LS_KEY = "rc-pgr-rank-tier";

/** One-time DOM wiring - click handlers, etc. Idempotent. */
export function wireLastMatchOnce() {
  if (_wired) return;
  _wired = true;

  // Item C (s220): warm the DDragon item/rune description cache on
  // first mount so the first Comp-tab render already has tooltips.
  // Idempotent - no-op once the cache is ready.
  preloadLolDescriptions();
  // s-PGR-S2 (#9): warm the augment id->icon dict so the first roster
  // render already shows augment icons (ARAM Mayhem / Arena).
  _loadAugments();

  const champEl = document.getElementById("lm-champion-name");
  if (champEl) {
    const goHistory = () => {
      const champ = champEl.dataset.champion || "";
      if (!champ) return;
      try { sessionStorage.setItem("rc-history-focus-champion", champ); } catch (_) {}
      try { location.hash = "#history"; } catch (_) {}
      if (typeof window._viewSaveManual === "function") window._viewSaveManual("history");
      if (typeof window._viewResolveAndApply === "function") window._viewResolveAndApply();
    };
    champEl.addEventListener("click", goHistory);
    champEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); goHistory(); }
    });
  }

  const reviewBtn = document.getElementById("lm-go-to-review");
  if (reviewBtn) {
    reviewBtn.addEventListener("click", () => {
      const mid = reviewBtn.dataset.matchId || "";
      // s220 S5: stash + route to the existing Replay view (VIEW_IDS
      // contains "replay", not "review" - the pre-S5 wire targeted
      // a never-built "review" id and silently fell back to home).
      if (mid) {
        try { sessionStorage.setItem("rc-replay-focus-match", mid); } catch (_) {}
      }
      try { location.hash = "#replay"; } catch (_) {}
      if (typeof window._viewSaveManual === "function") window._viewSaveManual("replay");
      if (typeof window._viewResolveAndApply === "function") window._viewResolveAndApply();
    });
  }

  // Rank-tier comparison dropdown: restore from localStorage + persist
  // on change. The values displayed depend on the current match's
  // mode, so we re-render via the panel's cached last match data.
  const rankSel = document.getElementById("lm-rank-select");
  if (rankSel) {
    try {
      const saved = localStorage.getItem(_RANK_LS_KEY) || "";
      if (saved) rankSel.value = saved;
    } catch (_) {}
    rankSel.addEventListener("change", () => {
      try { localStorage.setItem(_RANK_LS_KEY, rankSel.value); } catch (_) {}
      _renderRankCompare(rankSel.value);
    });
  }

  // s220 PGR S4: Tab nav (Build / Graph / AI Analysis + Review-nav).
  // Defaults to Build on first render; persists active tab to
  // localStorage so the operator's last choice survives a reload.
  // Legacy values (pre-S4: comp / chart / timeline / insights) migrate
  // via _migrateLegacyTab below.
  const tabsRoot = document.getElementById("lm-tabbed-section");
  if (tabsRoot) {
    try {
      const saved = localStorage.getItem(_TAB_LS_KEY);
      // s220 PGR S4: tabs reframed 4 -> 3 (build / graph / ai-analysis).
      // Map legacy values so an operator who last viewed "timeline"
      // lands on the new panel that hosts those visuals (graph) rather
      // than blanking out. "review" is a nav tab (-> deep-review page),
      // never a persistable panel.
      const migrated = _migrateLegacyTab(saved);
      if (migrated && _VALID_TABS.includes(migrated)) {
        _activateTab(migrated);
        if (migrated !== saved) {
          try { localStorage.setItem(_TAB_LS_KEY, migrated); } catch (_) {}
        }
      }
    } catch (_) {}
    tabsRoot.querySelectorAll(".lm-tab[data-tab]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const which = btn.dataset.tab || "";
        _activateTab(which);
        try { localStorage.setItem(_TAB_LS_KEY, which); } catch (_) {}
      });
    });
  }
}

const _TAB_LS_KEY = "rc-pgr-tab";
// s220 PGR S4: canonical tab ids. Update _migrateLegacyTab in lock-step
// when adding a new tab or splitting an existing one.
const _VALID_TABS = ["build", "graph", "ai-analysis"];

// s220 PGR S4: legacy localStorage migration. Pre-S4 saved values were
// comp / chart / timeline / insights. The S4 reframe folds Chart +
// Timeline into Graph and Insights + Timeline-WPA into AI Analysis.
function _migrateLegacyTab(saved) {
  if (!saved) return null;
  switch (saved) {
    case "comp":     return "build";
    case "chart":    return "graph";
    case "timeline": return "graph";         // visuals half landed in Graph
    case "insights": return "ai-analysis";
    default:         return saved;            // already a new id or unknown
  }
}

function _activateTab(which) {
  const tabsRoot = document.getElementById("lm-tabbed-section");
  if (!tabsRoot) return;
  tabsRoot.querySelectorAll(".lm-tab[data-tab]").forEach((t) => {
    t.classList.toggle("is-active", t.dataset.tab === which);
  });
  tabsRoot.querySelectorAll(".lm-tab-panel[data-tab-panel]").forEach((p) => {
    const match = p.dataset.tabPanel === which;
    p.classList.toggle("is-active", match);
    if (match) p.removeAttribute("hidden");
    else p.setAttribute("hidden", "");
  });
}

/** Fetch latest match + render into DOM. Safe to call repeatedly. */
export function fetchAndRenderLastMatch() {
  // s220: baseline window is operator-configurable from Settings
  // (shared localStorage key rc-pgr-baseline). Clamp client-side too;
  // the server re-clamps defensively.
  let _b = 20;
  try { _b = parseInt(localStorage.getItem("rc-pgr-baseline") || "20", 10); } catch (_) {}
  if (isNaN(_b)) _b = 20;
  _b = Math.max(5, Math.min(50, _b));
  fetch(`/api/last-match?baseline=${_b}`, { headers: { "Accept": "application/json" } })
    .then((r) => r.json())
    .then((data) => renderLastMatch(data))
    .catch((err) => {
      // Surface in console; leave any pre-existing rendered state in place.
      try { console.warn("[last-match] fetch failed:", err); } catch (_) {}
    });
}

function renderLastMatch(data) {
  _lastData = data;
  if (!data || !data.found) {
    _setEmptyState(data && data.error);
    return;
  }
  const m = data.match || {};
  const qr = data.quick_review || {};
  const enriched = m.enriched || null;

  _setHero(m, enriched);
  _setStatsGrid(m, enriched);
  // s219 v3: _setDsPicks + _setEnrichedBuild dropped - operator removed
  // the BUILD section entirely. Final inventory + summoner spells now
  // live in the Team Composition card (operator's own row); DS picks
  // belong on champ-select + active-match, not post-game.
  _setTeamComp(enriched);
  // s220 PGR S3: aggregator-G-style operator 0-100 match-score block in the
  // hero. Runs after _setTeamComp so the roster + scores are computed;
  // _setHeroScore reuses _rosterScores so the number is consistent
  // with the per-row chip + MVP card.
  _setHeroScore(m, enriched);
  // Item 131 Slice A: per-role grade chip - fetches the operator's
  // S+/S/A/B/C/D grade for this match from /api/post-game-rubric
  // (sibling to _rosterScores; role-aware vs lobby-relative).
  _setHeroRoleGrade(m);
  _setChart(enriched);
  _setTimeline(enriched);
  _setPhases(m, enriched);
  _setQuickReview(qr);
  _setReviewButton(m);
  _setMeta(m, data.history_count, enriched);

  // s219 v4: cache the current match's mode for the rank-compare
  // panel + re-render with the saved tier choice.
  _lastMatchMode = m.mode || "";
  let savedTier = "";
  try { savedTier = localStorage.getItem(_RANK_LS_KEY) || ""; } catch (_) {}
  // s220: Settings is the canonical home for this knob (shared key).
  // Keep the inline dropdown in lock-step on every render so a change
  // made in Settings reflects here without a hard reload.
  const _rs = document.getElementById("lm-rank-select");
  if (_rs && _rs.value !== savedTier) _rs.value = savedTier;
  _renderRankCompare(savedTier);
}

// Cache so the dropdown can re-render without refetching /api/last-match.
let _lastMatchMode = "";

function _renderRankCompare(tier) {
  // s219 v6: 8 individual cells (4 row 1 + 4 row 2 minus the selector
  // in col 1 row 1). Populates by ID rather than rewriting the whole
  // container, so the HTML structure + grid placement stays stable.
  const cells = {
    "lm-rank-kda":    "",
    "lm-rank-vision": "",
    "lm-rank-cs":     "",
    "lm-rank-tank":   "",
    "lm-rank-kp":     "",
    "lm-rank-damage": "",
    "lm-rank-cspm":   "",
    "lm-rank-heal":   "",
  };
  const set = (vals) => {
    Object.keys(cells).forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.textContent = vals[id] != null ? vals[id] : "-";
    });
  };

  if (!tier) { set({}); return; }
  const tierData = _RANK_TIER_AVERAGES[tier];
  if (!tierData) { set({}); return; }
  const mode = (_lastMatchMode || "").toUpperCase();
  const modeKey = mode in tierData
    ? mode
    : (mode === "ARAM" || mode === "KIWI" ? "ARAM" : "SR");
  const avg = tierData[modeKey] || tierData.SR;
  if (!avg) { set({}); return; }
  set({
    "lm-rank-kda":    avg.kda.toFixed(1),
    "lm-rank-vision": String(avg.vision),
    "lm-rank-cs":     String(avg.cs),
    "lm-rank-tank":   _fmtThousands(avg.tanked),
    "lm-rank-kp":     `${avg.kp}%`,
    "lm-rank-damage": _fmtThousands(avg.damage),
    "lm-rank-cspm":   avg.cs_per_min.toFixed(1),
    "lm-rank-heal":   _fmtThousands(avg.healing),
  });
}

function _setMeta(m, historyCount, _enriched) {
  // s219 v4: trimmed to mode · "X ago" · baseline-count. Duration
  // already lives in the hero stats inline; the "LCU detail ingested"
  // debug callout was operator-noise. The N in "baseline · N prior
  // games" will become operator-configurable from the Settings page
  // (window currently fixed at 20 via _build_last_match's LIMIT 20
  // SQL clause; once Settings ships a knob it'll propagate here).
  const meta = document.getElementById("lm-meta");
  if (!meta) return;
  const parts = [m.mode || "-", _fmtAgo(m.timestamp)];
  if (typeof historyCount === "number" && historyCount > 0) {
    parts.push(`baseline · ${historyCount} prior games`);
  }
  meta.textContent = parts.filter(Boolean).join(" · ");
}

function _setHero(m, enriched) {
  const portrait = document.getElementById("lm-portrait");
  const champEl = document.getElementById("lm-champion-name");
  const modeTag = document.getElementById("lm-mode-tag");
  const kdaText = document.getElementById("lm-kda-text");
  const kdaRatio = document.getElementById("lm-kda-ratio");
  const grade = document.getElementById("lm-grade-badge");
  const result = document.getElementById("lm-result-badge");
  const heroBox = document.querySelector(".lm-hero");

  const champion = m.champion || "?";
  const champKey = _resolveChampKey(champion);
  if (portrait) {
    portrait.src = champKey ? `/icons/champions/${champKey}.png` : "";
    portrait.alt = champion;
  }
  if (champEl) {
    champEl.textContent = champion;
    champEl.dataset.champion = champion;
  }
  if (modeTag) modeTag.textContent = m.mode || "-";
  if (kdaText) kdaText.textContent = m.kda_str || "-/-/-";
  if (kdaRatio) {
    const r = m.kda_ratio;
    kdaRatio.textContent = (typeof r === "number") ? `${r.toFixed(2)} KDA` : "-";
  }
  const g = (m.grade || "-").toUpperCase().trim();
  if (grade) {
    grade.textContent = g || "-";
    grade.dataset.grade = (g && g !== "-") ? g : "";
  }
  if (heroBox) {
    heroBox.dataset.grade = (g && g !== "-") ? g : "";
  }
  // W/L badge - only shown when LCU enrichment is in. Arena (CHERRY)
  // has 4 sub-teams and `win` semantics differ; suppress there until
  // we model subteam_placement.
  if (result) {
    const queueId = enriched && enriched.queue_id;
    const isArenaSubteamMode = (queueId === 1700 || queueId === 1710);
    if (enriched && enriched.win != null && !isArenaSubteamMode) {
      const won = !!enriched.win;
      let label = won ? "VICTORY" : "DEFEAT";
      // s220 surrender tag: distinguish an FF'd result from a
      // played-out one; early surrender = remake. data-surrender lets
      // CSS refine the badge in the later UI-audit pass without
      // coupling now (the text suffix already works standalone).
      if (enriched.ended_in_early_surrender) label += " (REMAKE)";
      else if (enriched.ended_in_surrender) label += " (FF)";
      result.textContent = label;
      result.dataset.result = won ? "win" : "loss";
      result.dataset.surrender = enriched.ended_in_early_surrender ? "early"
        : (enriched.ended_in_surrender ? "yes" : "");
      result.hidden = false;
    } else if (enriched && isArenaSubteamMode) {
      // Surface the sub-team placement as a numeric pill if available
      result.textContent = "ARENA";
      result.dataset.result = "neutral";
      result.hidden = false;
    } else {
      result.hidden = true;
      result.dataset.result = "";
    }
  }
}

function _setEnrichedBuild(enriched) {
  const wrap = document.getElementById("lm-actual-build");
  const inv = document.getElementById("lm-inventory");
  const summ = document.getElementById("lm-summoners");
  const pending = document.getElementById("lm-build-pending");
  if (!wrap || !inv || !summ) return;
  if (!enriched || !enriched.items) {
    wrap.hidden = true;
    if (pending) pending.hidden = false;
    return;
  }
  wrap.hidden = false;
  if (pending) pending.hidden = true;
  // Inventory: 7 slots (item0-item6). item6 is the trinket. Empty (0) → faded slot.
  inv.innerHTML = (enriched.items || []).map((iid, idx) => {
    const isTrinket = idx === 6;
    const cls = isTrinket ? "lm-item lm-item-trinket" : "lm-item";
    if (!iid) {
      return `<div class="${cls} lm-item-empty" aria-label="empty slot"></div>`;
    }
    return `<div class="${cls}" title="item ${iid}">${_itemImgTag(iid)}</div>`;
  }).join("");
  // Summoner spells: spell1Id + spell2Id (D + F)
  const sp1 = enriched.spell1_id, sp2 = enriched.spell2_id;
  summ.innerHTML = [sp1, sp2].map((sid) => {
    const tag = _summonerImgTag(sid);
    if (!tag) return `<div class="lm-summ lm-summ-empty" title="spell ${sid || ''}"></div>`;
    return `<div class="lm-summ" title="spell ${sid}">${tag}</div>`;
  }).join("");
}

function _setTeamComp(enriched) {
  const table = document.getElementById("lm-tc-table");
  const allyList = document.getElementById("lm-tc-ally-list");
  const enemyList = document.getElementById("lm-tc-enemy-list");
  const allyResult = document.getElementById("lm-tc-ally-result");
  const enemyResult = document.getElementById("lm-tc-enemy-result");
  const pending = document.getElementById("lm-tc-pending");
  if (!table || !allyList || !enemyList) return;
  if (!enriched || !enriched.roster || !enriched.roster.length) {
    table.hidden = true;
    if (pending) pending.hidden = false;
    return;
  }
  table.hidden = false;
  if (pending) pending.hidden = true;

  const myTeamId = enriched.team_id;
  const roster = enriched.roster || [];
  const ally  = roster.filter((r) => r.team_id === myTeamId);
  const enemy = roster.filter((r) => r.team_id !== myTeamId);

  // s-PGR-S2 (#9): only widen the row grid to an augments column when
  // the dict is loaded AND someone actually has augments (Mayhem /
  // Arena). SR rosters (all-0 augments) keep the pre-S2 8-col layout
  // exactly - data-aug drives the CSS grid-template + the cell emit.
  const hasAug = _augLoaded
    && roster.some((r) => Array.isArray(r.augments) && r.augments.some((x) => Number(x) > 0));
  table.dataset.aug = hasAug ? "1" : "";

  // Win/loss per team (enriched.teams is more reliable than per-row win).
  const teamWin = {};
  (enriched.teams || []).forEach((t) => { teamWin[t.team_id] = !!t.win; });

  // s220: per-player overall score → per-SIDE rank (1..N within each
  // team). The best on each side shows MVP (that side won) / SVP (lost);
  // the rest show #2..#N. Ranking is per-side, not lobby-wide, so the
  // visible numbers stay contiguous (no gaps where the badge slots are).
  const scores = _rosterScores(roster);
  const rankSide = (list, won) => {
    const sorted = [...list].sort((a, b) =>
      (scores[b.participant_id] || 0) - (scores[a.participant_id] || 0));
    const meta = {};
    sorted.forEach((r, i) => {
      const sc = scores[r.participant_id] || 0;
      meta[r.participant_id] = (i === 0)
        ? { badge: won ? "MVP" : "SVP", rank: 1, score: sc }
        : { badge: "", rank: i + 1, score: sc };
    });
    // s220 PGR S3: surface the top entry so _renderMvpCard can paint
    // a dedicated MVP/SVP card above the roster list (aggregator G pattern).
    return { meta, top: sorted[0] || null };
  };
  const enemyTid  = enemy.length ? enemy[0].team_id : null;
  const allySide  = rankSide(ally,  !!teamWin[myTeamId]);
  const enemySide = rankSide(enemy, enemyTid != null ? !!teamWin[enemyTid] : false);
  const allyMeta  = allySide.meta;
  const enemyMeta = enemySide.meta;
  const metaFor = (r) =>
    ((r.team_id === myTeamId ? allyMeta : enemyMeta)[r.participant_id])
    || { badge: "", rank: 0, score: 0 };
  allyList.innerHTML  = ally.map((r)  => _renderTcRow(r, metaFor(r), hasAug)).join("")  || `<li class="lm-tc-empty">-</li>`;
  enemyList.innerHTML = enemy.map((r) => _renderTcRow(r, metaFor(r), hasAug)).join("") || `<li class="lm-tc-empty">-</li>`;
  // s220 PGR S3: per-side MVP / SVP card above each roster.
  _renderMvpCard("lm-tc-ally-mvp",  allySide.top,
    allySide.top  ? allyMeta[allySide.top.participant_id]   : null);
  _renderMvpCard("lm-tc-enemy-mvp", enemySide.top,
    enemySide.top ? enemyMeta[enemySide.top.participant_id] : null);

  const myWin = teamWin[myTeamId];
  if (myWin != null && allyResult) {
    allyResult.textContent = myWin ? "VICTORY" : "DEFEAT";
    allyResult.dataset.result = myWin ? "win" : "loss";
  } else if (allyResult) {
    allyResult.textContent = "-"; allyResult.dataset.result = "";
  }
  const enemyTeamId = enemy.length ? enemy[0].team_id : null;
  const enemyWin = enemyTeamId != null ? teamWin[enemyTeamId] : null;
  if (enemyWin != null && enemyResult) {
    enemyResult.textContent = enemyWin ? "VICTORY" : "DEFEAT";
    enemyResult.dataset.result = enemyWin ? "win" : "loss";
  } else if (enemyResult) {
    enemyResult.textContent = "-"; enemyResult.dataset.result = "";
  }
}

function _renderTcRow(r, sm, showAug) {
  // Resolve championId → name via CHAMPS.byId (async-hydrated by items_index.js)
  const slug = (CHAMPS && CHAMPS.byId && CHAMPS.byId[String(r.champion_id)]) || "";
  const portrait = slug ? `/icons/champions/${slug}.png` : "";
  const name = _escHtml(r.game_name || "-");
  const tag = r.tag_line ? `<span class="lm-tc-tag">#${_escHtml(r.tag_line)}</span>` : "";
  const meRow = r.is_me ? " lm-tc-row-me" : "";
  const kda = `${r.kills}/${r.deaths}/${r.assists}`;
  const itemsHtml = (r.items || []).map((iid, idx) => {
    const cls = idx === 6 ? "lm-tc-item lm-tc-item-trinket" : "lm-tc-item";
    if (!iid) return `<div class="${cls} lm-tc-item-empty"></div>`;
    return _itemImgTag(iid, cls);
  }).join("");
  const sp1 = r.summoner1, sp2 = r.summoner2;
  const summHtml = [sp1, sp2].map((sid) => {
    const t = _summonerImgTag(sid, "lm-tc-summ");
    return t || `<div class="lm-tc-summ lm-tc-summ-empty"></div>`;
  }).join("");
  // s220: score / MVP-SVP cell, left of level. The single best player
  // per side shows MVP (won) / SVP (lost); everyone else shows their
  // lobby rank. Underlying score + factors live in the hover tooltip.
  // s220 PGR S3: cell stacks the badge/rank text + the numeric 0-100
  // score, so each row shows its score directly instead of hiding it
  // inside the tooltip (aggregator G pattern).
  const m = sm || { badge: "", rank: 0, score: 0 };
  const sVal = (typeof m.score === "number") ? m.score.toFixed(1) : "0.0";
  const sNum = (typeof m.score === "number") ? Math.round(m.score) : 0;
  const scoreCell = m.badge
    ? `<div class="lm-tc-score" data-kind="${m.badge.toLowerCase()}" data-tt="${m.badge === "MVP" ? "MVP - best on the winning side" : "SVP - best on the losing side"} (overall score ${sVal}/100)">
         <span class="lm-tc-score-badge">${m.badge}</span>
         <span class="lm-tc-score-value">${sNum}</span>
       </div>`
    : `<div class="lm-tc-score" data-kind="rank" data-tt="Lobby rank by overall score ${sVal}/100 - blend of KDA, damage, gold, CS, vision, tanked">
         <span class="lm-tc-score-badge">#${m.rank || "-"}</span>
         <span class="lm-tc-score-value">${sNum}</span>
       </div>`;
  // s-PGR-S2 (#9): augment strip between summoners + CS, emitted only
  // when the table is in augment mode (showAug) so the grid column
  // count stays uniform across every row + both panels. Empty <div>
  // for a player with no augments keeps alignment.
  const augCell = showAug
    ? `<div class="lm-tc-augs">${_augIconsHtml(r.augments)}</div>`
    : "";
  // s220 (#H): champ level shows just the number (no "L" prefix).
  // s220 (#F): summoner spells now sit before CS (swapped).
  return `<li class="lm-tc-row${meRow}" data-team="${r.team_id}">
    <img class="lm-tc-portrait" src="${portrait}" alt="${slug || ''}" loading="lazy" onerror="this.style.visibility='hidden'">
    <div class="lm-tc-name">${name}${tag}</div>
    ${scoreCell}
    <span class="lm-tc-lvl" title="champion level">${r.champ_level || 0}</span>
    <span class="lm-tc-kda" title="kills / deaths / assists">${kda}</span>
    <div class="lm-tc-summs">${summHtml}</div>
    ${augCell}
    <span class="lm-tc-cs" title="creep score">${r.cs || 0} CS</span>
    <div class="lm-tc-items">${itemsHtml}</div>
  </li>`;
}

// s220 PGR S3: score-tier mapping for the hero 0-100 score. Thresholds
// chosen so a typical OK match lands "OK" + a real carry game lands
// "Excellent" - calibrated against the existing _rosterScores 100-point
// scale. data-tier attribute drives the color in last_match.css.
function _scoreTier(score) {
  const n = Number(score) || 0;
  if (n >= 80) return { label: "Excellent", key: "excellent" };
  if (n >= 65) return { label: "Good",      key: "good" };
  if (n >= 50) return { label: "OK",        key: "ok" };
  return            { label: "Bad",       key: "bad" };
}

// s220 PGR S3: paint the operator's 0-100 match score in the hero.
// Source: _rosterScores - same heuristic as the per-row chip + MVP
// card so the three numbers are mutually consistent. Hidden when
// LCU enrichment is absent (no roster -> no score).
function _setHeroScore(m, enriched) {
  const wrap    = document.getElementById("lm-hero-score");
  const valueEl = document.getElementById("lm-hero-score-value");
  const tierEl  = document.getElementById("lm-hero-score-tier");
  if (!wrap || !valueEl || !tierEl) return;
  const roster = enriched && enriched.roster;
  if (!roster || !roster.length) {
    wrap.hidden = true; wrap.dataset.tier = "";
    valueEl.textContent = "-"; tierEl.textContent = "-";
    return;
  }
  const me = roster.find((r) => r && r.is_me);
  if (!me) {
    wrap.hidden = true; wrap.dataset.tier = "";
    valueEl.textContent = "-"; tierEl.textContent = "-";
    return;
  }
  const scores = _rosterScores(roster);
  const sc = scores[me.participant_id] || 0;
  const tier = _scoreTier(sc);
  valueEl.textContent = String(Math.round(sc));
  tierEl.textContent  = tier.label;
  wrap.dataset.tier   = tier.key;
  wrap.hidden = false;
}

// Item 131 Slice A wire: per-role grading rubric chip. Fetches
// /api/post-game-rubric for the operator's row in this match, paints
// the S+/S/A/B/C/D grade alongside the role label. The grade is
// role-aware (sourced from core/post_game_rubric.py); the existing
// _setHeroScore is lobby-relative. The two compose visually.
function _setHeroRoleGrade(m) {
  const wrap    = document.getElementById("lm-hero-role-grade");
  const roleEl  = document.getElementById("lm-hero-role-grade-role");
  const valueEl = document.getElementById("lm-hero-role-grade-value");
  const tierEl  = document.getElementById("lm-hero-role-grade-tier");
  if (!wrap || !roleEl || !valueEl || !tierEl) return;
  const matchId = (m && m.id) || "";
  if (!matchId) {
    wrap.hidden = true; wrap.dataset.tier = "";
    roleEl.textContent = "-"; valueEl.textContent = "-"; tierEl.textContent = "-";
    return;
  }
  const url = `/api/post-game-rubric?match_id=${encodeURIComponent(matchId)}`;
  fetch(url, { headers: { "Accept": "application/json" } })
    .then((r) => r.json())
    .then((data) => {
      if (!data || !data.ok) {
        wrap.hidden = true; wrap.dataset.tier = "";
        return;
      }
      const score = Math.round(Number(data.total_score) || 0);
      const grade = String(data.percentile_grade || "-");
      const role  = String(data.role || "-");
      roleEl.textContent  = role;
      valueEl.textContent = String(score);
      tierEl.textContent  = grade;
      wrap.dataset.tier   = grade;
      wrap.hidden = false;
    })
    .catch((err) => {
      try { console.warn("[post-game-rubric] fetch failed:", err); } catch (_) {}
      wrap.hidden = true; wrap.dataset.tier = "";
    });
}

// s220 PGR S3: render a aggregator-G-style MVP / SVP card above one team's
// roster list. `top` is the highest-scoring row on that side; `sm` is
// its meta (badge/rank/score) from rankSide. data-kind drives the
// visual flavor (mvp -> gold-tinted, svp -> accent-tinted). Hidden
// when there is no top entry or no badge (defensive).
function _renderMvpCard(cardId, top, sm) {
  const card = document.getElementById(cardId);
  if (!card) return;
  if (!top || !sm || !sm.badge) {
    card.hidden = true; card.dataset.kind = ""; card.innerHTML = "";
    return;
  }
  const slug = (CHAMPS && CHAMPS.byId && CHAMPS.byId[String(top.champion_id)]) || "";
  const portrait = slug ? `/icons/champions/${slug}.png` : "";
  const score = Math.round(Number(sm.score) || 0);
  const name  = _escHtml(top.game_name || "-");
  const kind  = sm.badge.toLowerCase();
  const tier  = _scoreTier(score);
  card.innerHTML = `
    <img class="lm-tc-mvp-portrait" src="${portrait}" alt="" loading="lazy"
         onerror="this.style.visibility='hidden'" />
    <svg class="lm-tc-mvp-crown" viewBox="0 0 24 16" aria-hidden="true">
      <path d="M2 14 L4 4 L8 9 L12 2 L16 9 L20 4 L22 14 Z"></path>
    </svg>
    <div class="lm-tc-mvp-meta">
      <span class="lm-tc-mvp-badge">${sm.badge}</span>
      <span class="lm-tc-mvp-name">${name}</span>
    </div>
    <div class="lm-tc-mvp-score" data-tier="${tier.key}">
      <span class="lm-tc-mvp-score-value">${score}</span>
      <span class="lm-tc-mvp-score-tier">${tier.label}</span>
    </div>
  `;
  card.hidden = false;
  card.dataset.kind = kind;
}

// s220: per-player overall score → { participant_id: score } map.
// _setTeamComp turns this into a per-side 1..N rank + MVP/SVP badge.
// Transparent heuristic (surfaced in each row's hover tooltip): a
// weighted blend of KDA, damage to champs, gold, CS, vision, and
// damage tanked, each normalized to the lobby max so it's comparable
// across roles + modes. Not Riot's MVP formula (proprietary) - a
// defensible proxy from the roster fields we already ship.
function _rosterScores(roster) {
  const rows = roster || [];
  if (!rows.length) return {};
  const maxOf = (sel) => {
    let mx = 1;
    for (const r of rows) { const v = Number(sel(r)) || 0; if (v > mx) mx = v; }
    return mx;
  };
  const mDmg  = maxOf((r) => r.damage_to_champs);
  const mGold = maxOf((r) => r.gold);
  const mCs   = maxOf((r) => r.cs);
  const mVis  = maxOf((r) => r.vision_score);
  const mTank = maxOf((r) => r.damage_taken);
  const scored = rows.map((r) => {
    const k = +r.kills || 0, d = +r.deaths || 0, a = +r.assists || 0;
    const kdaN = Math.min(((k + a) / Math.max(d, 1)) / 6, 1);
    const score = 100 * (
      0.30 * kdaN +
      0.28 * ((+r.damage_to_champs || 0) / mDmg) +
      0.16 * ((+r.gold || 0) / mGold) +
      0.12 * ((+r.cs || 0) / mCs) +
      0.08 * ((+r.vision_score || 0) / mVis) +
      0.06 * ((+r.damage_taken || 0) / mTank)
    );
    return { pid: r.participant_id, score };
  });
  const out = {};
  scored.forEach((e) => { out[e.pid] = e.score; });
  return out;
}

function _setStatsGrid(m, enriched) {
  // s219 v6: section 2 of hero - 2 rows × 4 cols. Row 1: Vision / CS /
  // Tanked. Row 2: KP% / Damage / CS/min / Heal+Shield.
  const cs       = document.getElementById("lm-cs");
  const cspm     = document.getElementById("lm-cs-per-min");
  const kp       = document.getElementById("lm-kp");
  const vision   = document.getElementById("lm-vision");
  const tankDmg  = document.getElementById("lm-tank-dmg");
  const damage   = document.getElementById("lm-damage");
  const healing  = document.getElementById("lm-healing");

  if (cs)   cs.textContent   = (m.cs != null && m.cs > 0) ? String(m.cs) : "-";
  if (cspm) cspm.textContent = (typeof m.cs_per_min === "number")
                                ? m.cs_per_min.toFixed(1) : "-";
  if (kp)   kp.textContent   = (typeof m.kp_pct === "number")
                                ? `${Math.round(m.kp_pct)}%` : "-";

  // Enriched-only stats - Vision / Damage / Tanked / Heal+Shield.
  const e   = enriched || {};
  const dmg = e.damage  || {};
  const sup = e.support || {};
  const vs  = e.vision  || {};

  if (vision)  vision.textContent  = (vs.score != null) ? String(vs.score) : "-";
  if (tankDmg) tankDmg.textContent = (dmg.taken)
                                      ? _fmtThousands(dmg.taken) : "-";
  if (damage)  damage.textContent  = (dmg.dealt_to_champs)
                                      ? _fmtThousands(dmg.dealt_to_champs) : "-";
  if (healing) {
    const hs = sup.heal_plus_shield || 0;
    healing.textContent = hs > 0 ? _fmtThousands(hs) : "-";
  }
}

function _setDsPicks(picks) {
  const root = document.getElementById("lm-ds-picks");
  if (!root) return;
  if (!picks || !picks.length) {
    root.innerHTML = '<span class="lm-empty">no DS data captured for this match</span>';
    return;
  }
  const html = picks.slice(0, 5).map((p) => {
    const name = String(p.name || "?");
    const id = String(p.id || "");
    const delta = (typeof p.delta === "number") ? p.delta
                 : (typeof p.delta_dps === "number") ? p.delta_dps : null;
    const scorer = p.scorer || "dps";
    const unit = _scorerUnit(scorer);
    const deltaTxt = (delta != null) ? `+${Math.round(delta)}${unit}` : "";
    const safeName = _escHtml(name);
    return `<div class="lm-build-item" title="${safeName} (${scorer})">
      ${id ? _itemImgTag(id, "", safeName) : ""}
      <span class="lm-build-item-name">${safeName}</span>
      <span class="lm-build-item-delta">${deltaTxt}</span>
    </div>`;
  }).join("");
  root.innerHTML = html;
}

// s219 v5: Chart tab - team-aggregate ally vs enemy bars.
// Derived from enriched.roster (per-player KDA/damage/gold/vision)
// + enriched.teams (tower/dragon/baron/inhibitor kills). Each row is
// a pair of bars normalized to the larger value so the visual diff
// reads instantly. SR-only metrics (Dragons / Barons) suppressed on
// other modes; conversely tower kills + vision show in all 5v5 modes.
function _setChart(enriched) {
  const wrap = document.getElementById("lm-chart-wrap");
  const list = document.getElementById("lm-chart-list");
  const pending = document.getElementById("lm-chart-pending");
  if (!wrap || !list) return;
  if (!enriched || !enriched.roster || !enriched.roster.length) {
    wrap.hidden = true;
    if (pending) pending.hidden = false;
    return;
  }
  wrap.hidden = false;
  if (pending) pending.hidden = true;

  const myTid = enriched.team_id;
  const ally  = (enriched.roster || []).filter((r) => r.team_id === myTid);
  const enemy = (enriched.roster || []).filter((r) => r.team_id !== myTid);
  const teams = enriched.teams || [];
  const myTeam = teams.find((t) => t.team_id === myTid) || {};
  const enemyTeam = teams.find((t) => t.team_id !== myTid) || {};

  const sum = (arr, fn) => arr.reduce((a, r) => a + (Number(fn(r)) || 0), 0);

  // Build rows. Suppress mode-irrelevant rows.
  const queueId = enriched.queue_id || 0;
  const gameMode = (enriched.game_mode || "").toUpperCase();
  const isAram   = queueId === 450 || queueId === 2400 || gameMode === "ARAM" || gameMode === "KIWI";
  const isArena  = queueId === 1700 || queueId === 1710 || gameMode === "CHERRY";
  const isSr     = !isAram && !isArena;

  const rows = [
    { label: "Kills",   ally: sum(ally, r => r.kills),   enemy: sum(enemy, r => r.kills) },
    { label: "Deaths",  ally: sum(ally, r => r.deaths),  enemy: sum(enemy, r => r.deaths) },
    { label: "Assists", ally: sum(ally, r => r.assists), enemy: sum(enemy, r => r.assists) },
    { label: "Damage",  ally: sum(ally, r => r.damage_to_champs), enemy: sum(enemy, r => r.damage_to_champs), fmt: _fmtThousands },
    { label: "Damage Tkn", ally: sum(ally, r => r.damage_taken), enemy: sum(enemy, r => r.damage_taken), fmt: _fmtThousands },
    { label: "Gold",    ally: sum(ally, r => r.gold), enemy: sum(enemy, r => r.gold), fmt: _fmtThousands },
    { label: "Vision",  ally: sum(ally, r => r.vision_score), enemy: sum(enemy, r => r.vision_score) },
  ];
  if (myTeam.tower_kills != null || enemyTeam.tower_kills != null) {
    rows.push({ label: "Towers", ally: myTeam.tower_kills || 0, enemy: enemyTeam.tower_kills || 0 });
  }
  if (isSr) {
    rows.push({ label: "Dragons", ally: myTeam.dragon_kills || 0, enemy: enemyTeam.dragon_kills || 0 });
    rows.push({ label: "Barons",  ally: myTeam.baron_kills  || 0, enemy: enemyTeam.baron_kills  || 0 });
    rows.push({ label: "Heralds", ally: myTeam.rift_herald_kills || 0, enemy: enemyTeam.rift_herald_kills || 0 });
  }

  list.innerHTML = rows.map((r) => {
    const max = Math.max(r.ally, r.enemy, 1);
    const allyPct  = Math.round((r.ally  / max) * 100);
    const enemyPct = Math.round((r.enemy / max) * 100);
    const fmtFn = r.fmt || ((v) => String(v));
    return `<li class="lm-chart-row">
      <div class="lm-chart-label">${_escHtml(r.label)}</div>
      <div class="lm-chart-bar lm-chart-bar-ally">
        <span class="lm-chart-bar-fill" style="width:${allyPct}%"></span>
        <span class="lm-chart-bar-value">${_escHtml(fmtFn(r.ally))}</span>
      </div>
      <div class="lm-chart-vs">vs</div>
      <div class="lm-chart-bar lm-chart-bar-enemy">
        <span class="lm-chart-bar-fill" style="width:${enemyPct}%"></span>
        <span class="lm-chart-bar-value">${_escHtml(fmtFn(r.enemy))}</span>
      </div>
    </li>`;
  }).join("");
}

function _fmtThousands(n) {
  const v = Number(n) || 0;
  if (v >= 1000) return `${(v / 1000).toFixed(1)}k`;
  return String(v);
}

// s220 Item E (phase 1): Timeline tab - per-minute gold/XP/CS
// differential sparklines + an objective-event ribbon. Diffs are
// ally − enemy (positive = operator's team ahead). Data comes from
// enriched.timeline (dashboard.builders._enrich_timeline_from_lcu);
// absent until a game completes post-agent-redeploy → placeholder.
function _setTimeline(enriched) {
  const wrap    = document.getElementById("lm-tl-wrap");
  const charts  = document.getElementById("lm-tl-charts");
  const ribbon  = document.getElementById("lm-tl-ribbon");
  const pending = document.getElementById("lm-tl-pending");
  if (!wrap || !charts || !ribbon) return;
  const tl = enriched && enriched.timeline;
  const series = tl && tl.series;
  if (!tl || !series || !Array.isArray(series.gold) || series.gold.length < 2) {
    wrap.hidden = true;
    if (pending) pending.hidden = false;
    return;
  }
  wrap.hidden = false;
  if (pending) pending.hidden = true;

  const fin = tl.final || {};
  const specs = [
    { key: "gold", label: "GOLD", thousands: true  },
    { key: "xp",   label: "XP",   thousands: true  },
    { key: "cs",   label: "CS",   thousands: false },
  ];
  charts.innerHTML = specs.map((sp) => {
    const data = series[sp.key] || [];
    const finalV = (typeof fin[sp.key] === "number")
      ? fin[sp.key] : (data[data.length - 1] || 0);
    const lead = finalV > 0 ? "ally" : (finalV < 0 ? "enemy" : "even");
    return `<div class="lm-tl-chart" data-lead="${lead}">
      <div class="lm-tl-chart-top">
        <span class="lm-tl-chart-label">${sp.label} DIFF</span>
        <span class="lm-tl-chart-final">${_escHtml(_fmtSigned(finalV, sp.thousands))}</span>
      </div>
      ${_tlSparkline(data)}
    </div>`;
  }).join("");

  const evs = Array.isArray(tl.events) ? tl.events : [];
  if (!evs.length) {
    ribbon.innerHTML = `<li class="lm-tl-ev-empty">no objective events recorded</li>`;
  } else {
    ribbon.innerHTML = evs.map((e) => {
      const team  = (e && e.team) || "neutral";
      const clock = _escHtml(String(e && e.clock || ""));
      const label = _escHtml(String(e && e.label || ""));
      const side  = team === "ally" ? "Ally"
                  : (team === "enemy" ? "Enemy" : "");
      return `<li class="lm-tl-ev" data-team="${team}">
        <span class="lm-tl-ev-clock">${clock}</span>
        <span class="lm-tl-ev-label">${label}</span>
        <span class="lm-tl-ev-side">${side}</span>
      </li>`;
    }).join("");
  }
}

// Inline SVG sparkline with a zero baseline. preserveAspectRatio=none
// so it stretches to the card width; stroke/area use currentColor so
// the parent .lm-tl-chart[data-lead] rule tints the whole thing by who
// ended ahead. vector-effect keeps the 2px stroke crisp despite the
// non-uniform scale.
function _tlSparkline(data) {
  const n = (data && data.length) || 0;
  const W = 100, H = 40, PAD = 3;
  if (n < 2) {
    return `<svg class="lm-tl-spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true"></svg>`;
  }
  let maxAbs = 1;
  for (const v of data) {
    const a = Math.abs(Number(v) || 0);
    if (a > maxAbs) maxAbs = a;
  }
  const half = (H / 2) - PAD;
  const xAt = (i) => ((i / (n - 1)) * W);
  const yAt = (v) => (H / 2) - ((Number(v) || 0) / maxAbs) * half;
  let line = "";
  for (let i = 0; i < n; i++) {
    line += (i === 0 ? "M" : "L") + xAt(i).toFixed(2) + " " + yAt(data[i]).toFixed(2) + " ";
  }
  const midY = (H / 2).toFixed(2);
  const area = `${line}L${W} ${midY} L0 ${midY} Z`;
  return `<svg class="lm-tl-spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
    <line class="lm-tl-spark-zero" x1="0" y1="${midY}" x2="${W}" y2="${midY}"></line>
    <path class="lm-tl-spark-area" d="${area}"></path>
    <path class="lm-tl-spark-line" d="${line.trim()}"></path>
  </svg>`;
}

function _fmtSigned(v, thousands) {
  const n = Number(v) || 0;
  const sign = n > 0 ? "+" : (n < 0 ? "-" : "");
  const abs = Math.abs(n);
  const body = thousands ? _fmtThousands(abs) : String(Math.round(abs));
  return `${sign}${body}`;
}

function _setPhases(m, enriched) {
  // s220 PGR S2: trigger the WPA fetch for this match. The match id
  // comes from /api/last-match (m.id). operator's side may live on
  // m.tracked_side or enriched.tracked_side - check both.
  const matchId = (m && m.id) || (enriched && enriched.match_id) || "";
  let operatorTeam = 0;
  if (m && (m.tracked_side === 100 || m.tracked_side === 200)) {
    operatorTeam = m.tracked_side;
  } else if (enriched && (enriched.tracked_side === 100 || enriched.tracked_side === 200)) {
    operatorTeam = enriched.tracked_side;
  }
  // Skip non-SR modes - the WPA model is trained on SR timelines.
  const mode = (m && m.mode) || "";
  if (mode && !/CLASSIC|SR|RANKED|DRAFT|NORMAL/i.test(mode)) {
    clearPhases();
    return;
  }
  fetchAndRenderPhases(matchId, operatorTeam);
}

function _setQuickReview(qr) {
  _renderQrColumn("lm-qr-right", qr.right);
  _renderQrColumn("lm-qr-wrong", qr.wrong_team);
  _renderQrColumn("lm-qr-chronic", qr.my_chronic);
}

function _renderQrColumn(elementId, items) {
  const ul = document.getElementById(elementId);
  if (!ul) return;
  if (!items || !items.length) {
    ul.innerHTML = '<li class="lm-qr-empty">no signal</li>';
    return;
  }
  const html = items.map((it) => {
    const text = String(it && it.text || "");
    const why  = String(it && it.why  || "");
    const safeText = _escHtml(text);
    const safeWhy  = _escHtml(why);
    return `<li data-tt-html="${safeWhy.replace(/"/g, "&quot;")}">${safeText}</li>`;
  }).join("");
  ul.innerHTML = html;
}

function _setReviewButton(m) {
  const btn = document.getElementById("lm-go-to-review");
  if (!btn) return;
  btn.dataset.matchId = String(m.id || "");
  btn.disabled = !m.id;
}

function _setEmptyState(errMsg) {
  const heroBox = document.querySelector(".lm-hero");
  if (heroBox) heroBox.dataset.grade = "";
  const meta = document.getElementById("lm-meta");
  if (meta) {
    meta.textContent = errMsg
      ? `no match data - ${errMsg}`
      : "no matches captured yet";
  }
  const champEl = document.getElementById("lm-champion-name");
  if (champEl) { champEl.textContent = "-"; champEl.dataset.champion = ""; }
  ["lm-mode-tag","lm-kda-text","lm-kda-ratio","lm-grade-badge",
   "lm-cs","lm-cs-per-min","lm-kp",
   "lm-vision","lm-tank-dmg","lm-damage","lm-healing",
   "lm-rank-kda","lm-rank-vision","lm-rank-cs","lm-rank-tank",
   "lm-rank-kp","lm-rank-damage","lm-rank-cspm","lm-rank-heal"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.textContent = "-";
  });
  const result = document.getElementById("lm-result-badge");
  if (result) { result.hidden = true; result.dataset.result = ""; }
  // s220 PGR S3: clear the hero match-score block + the MVP/SVP cards.
  const heroScore = document.getElementById("lm-hero-score");
  if (heroScore) { heroScore.hidden = true; heroScore.dataset.tier = ""; }
  const heroScoreVal  = document.getElementById("lm-hero-score-value");
  const heroScoreTier = document.getElementById("lm-hero-score-tier");
  if (heroScoreVal)  heroScoreVal.textContent  = "-";
  if (heroScoreTier) heroScoreTier.textContent = "-";
  // Item 131 Slice A: clear the per-role grade chip.
  const heroRole = document.getElementById("lm-hero-role-grade");
  if (heroRole) { heroRole.hidden = true; heroRole.dataset.tier = ""; }
  ["lm-hero-role-grade-role", "lm-hero-role-grade-value",
   "lm-hero-role-grade-tier"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.textContent = "-";
  });
  ["lm-tc-ally-mvp", "lm-tc-enemy-mvp"].forEach((id) => {
    const c = document.getElementById(id);
    if (c) { c.hidden = true; c.dataset.kind = ""; c.innerHTML = ""; }
  });
  const dsRoot = document.getElementById("lm-ds-picks");
  if (dsRoot) dsRoot.innerHTML = '<span class="lm-empty">no match yet</span>';
  const actual = document.getElementById("lm-actual-build");
  if (actual) actual.hidden = true;
  const tcTable = document.getElementById("lm-tc-table");
  if (tcTable) { tcTable.hidden = true; tcTable.dataset.aug = ""; }
  const chartWrap = document.getElementById("lm-chart-wrap");
  if (chartWrap) chartWrap.hidden = true;
  const tlWrap = document.getElementById("lm-tl-wrap");
  if (tlWrap) tlWrap.hidden = true;
  ["lm-tc-pending","lm-chart-pending","lm-tl-pending"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.hidden = false;
  });
  ["lm-qr-right","lm-qr-wrong","lm-qr-chronic"].forEach((id) => {
    const ul = document.getElementById(id);
    if (ul) ul.innerHTML = '<li class="lm-qr-empty">no signal yet</li>';
  });
}

/* ── helpers ───────────────────────────────────────────────────────── */

function _fmtDuration(s) {
  const t = Number(s) || 0;
  if (t <= 0) return "-";
  const mm = Math.floor(t / 60);
  const ss = Math.floor(t % 60);
  return `${mm}:${ss.toString().padStart(2, "0")}`;
}

function _fmtGold(g) {
  const n = Number(g) || 0;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

function _fmtAgo(timestamp) {
  if (!timestamp) return "-";
  // match_history.db uses "YYYY-MM-DD HH:MM:SS" local time
  const t = Date.parse(String(timestamp).replace(" ", "T"));
  if (isNaN(t)) return "-";
  const delta = (Date.now() - t) / 1000;
  if (delta < 60) return "just now";
  if (delta < 3600) return `${Math.floor(delta / 60)}m ago`;
  if (delta < 86400) return `${Math.floor(delta / 3600)}h ago`;
  const days = Math.floor(delta / 86400);
  return `${days}d ago`;
}

function _resolveChampKey(name) {
  // Mirror of main.js _resolveChampId - try the window-level resolver
  // if available, else best-effort capitalize+strip-spaces.
  if (typeof window._resolveChampId === "function") {
    try { return window._resolveChampId(name) || ""; } catch (_) {}
  }
  if (!name) return "";
  return String(name).replace(/[^A-Za-z]/g, "");
}

function _scorerUnit(scorer) {
  // Mirror of scorer_units.js scorerUnit - kept local to avoid an
  // import cycle on the rare chance that file moves.
  switch ((scorer || "").toLowerCase()) {
    case "ehp":     return "ehp";
    case "hybrid":  return "%";
    case "ability": return "adps";
    case "burst":   return "burst";
    case "hps":     return "hps";
    case "dps":
    default:        return "dps";
  }
}

function _escHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// Item C (s220): re-render once the DDragon item-description cache
// lands so Comp-tab item icons pick up their data-tt-html rich
// tooltip (itemTooltipHtml returns "" until the fetch resolves).
// Module scope mirrors champ_select.js's rc:lol-descriptions-ready
// handler - fires at most twice (items + runes), idempotent renders.
document.addEventListener("rc:lol-descriptions-ready", () => {
  if (_lastData) renderLastMatch(_lastData);
});
