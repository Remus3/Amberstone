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
 * Each Quick Review item is {text, why} — `why` becomes the data-tt-html
 * tooltip on hover so the analysis stays explainable.
 *
 * Champion deep-link: clicking the champion name stashes the champion to
 * sessionStorage.rc-history-focus-champion and routes to view-history
 * (mirrors the s218 Home Tonight's Pick "Jinx" name behavior).
 *
 * Deep Review button: stashes the match id to
 * sessionStorage.rc-review-focus-match and routes to view-review (placeholder
 * for the future deep-analysis page).
 */

// CHAMPS.byId is async-hydrated from /data/champions_index.json by
// the items_index.js loader. Until that fetch resolves, byId is {} —
// the team-comp row renderer falls back to a numeric id label so it
// stays informative rather than blank. ITEMS.version drives item
// icon paths so we stay current with the patch.
import { CHAMPS, ITEMS } from '../lib/items_index.js';

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
  // Unpinned s219 v3: local mirror was bumped to 16.10.1 (cloned from
  // 16.8.1 since item icons rarely change between minor patches; new
  // items in 16.10.1 fall back to the live CDN via onerror).
  return (ITEMS && ITEMS.version) || "16.10.1";
}

// onerror chain: try local at current ITEMS.version first; on 404 fall
// back to the official DDragon CDN at the same version. Mirrors the
// active_match.js cdnRetry pattern. Important because the local
// /data/ddragon/<ver>/img/item/ mirror sometimes lags the live patch
// (e.g. ITEMS.version=16.10.1 but on-disk dir is 16.8.1).
function _onErrCdnFallback(ver, kind, id) {
  // kind = "item" | "spell" — only used to build the CDN url
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
  return `<img class="${cls}" src="${localUrl}" alt="" ${safeTitle} loading="lazy" onerror="${onErr}">`;
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

// s219 v4: rank-tier comparison sample averages, per game mode.
// Hand-curated placeholder data — backend aggregates by tier from
// rewind_history.db are a future settings page follow-up. Keys are
// the dropdown values; values are { mode: {cs, kda, duration_s, kp} }
// expressing what an "average <tier>" looks like in that mode.
const _RANK_TIER_AVERAGES = {
  iron:        { ARAM:{cs:35,kda:1.6,duration_s:1080,kp:55}, SR:{cs:140,kda:1.7,duration_s:1800,kp:50} },
  bronze:      { ARAM:{cs:42,kda:1.9,duration_s:1080,kp:58}, SR:{cs:165,kda:2.0,duration_s:1830,kp:53} },
  silver:      { ARAM:{cs:48,kda:2.1,duration_s:1080,kp:60}, SR:{cs:185,kda:2.2,duration_s:1860,kp:55} },
  gold:        { ARAM:{cs:55,kda:2.4,duration_s:1080,kp:62}, SR:{cs:205,kda:2.5,duration_s:1890,kp:58} },
  platinum:    { ARAM:{cs:62,kda:2.7,duration_s:1080,kp:64}, SR:{cs:225,kda:2.8,duration_s:1920,kp:60} },
  emerald:     { ARAM:{cs:68,kda:3.0,duration_s:1080,kp:66}, SR:{cs:240,kda:3.1,duration_s:1920,kp:62} },
  diamond:     { ARAM:{cs:75,kda:3.3,duration_s:1080,kp:68}, SR:{cs:260,kda:3.4,duration_s:1950,kp:64} },
  master:      { ARAM:{cs:80,kda:3.6,duration_s:1080,kp:70}, SR:{cs:280,kda:3.7,duration_s:1980,kp:66} },
  grandmaster: { ARAM:{cs:85,kda:3.9,duration_s:1080,kp:72}, SR:{cs:300,kda:4.0,duration_s:2010,kp:68} },
  challenger:  { ARAM:{cs:90,kda:4.2,duration_s:1080,kp:74}, SR:{cs:320,kda:4.3,duration_s:2040,kp:70} },
};
const _RANK_LS_KEY = "rc-pgr-rank-tier";

/** One-time DOM wiring — click handlers, etc. Idempotent. */
export function wireLastMatchOnce() {
  if (_wired) return;
  _wired = true;

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
      if (mid) {
        try { sessionStorage.setItem("rc-review-focus-match", mid); } catch (_) {}
      }
      try { location.hash = "#review"; } catch (_) {}
      if (typeof window._viewSaveManual === "function") window._viewSaveManual("review");
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
}

/** Fetch latest match + render into DOM. Safe to call repeatedly. */
export function fetchAndRenderLastMatch() {
  fetch("/api/last-match", { headers: { "Accept": "application/json" } })
    .then((r) => r.json())
    .then((data) => renderLastMatch(data))
    .catch((err) => {
      // Surface in console; leave any pre-existing rendered state in place.
      try { console.warn("[last-match] fetch failed:", err); } catch (_) {}
    });
}

function renderLastMatch(data) {
  if (!data || !data.found) {
    _setEmptyState(data && data.error);
    return;
  }
  const m = data.match || {};
  const qr = data.quick_review || {};
  const enriched = m.enriched || null;

  _setHero(m, enriched);
  _setStatsGrid(m);
  // s219 v3: _setDsPicks + _setEnrichedBuild dropped — operator removed
  // the BUILD section entirely. Final inventory + summoner spells now
  // live in the Team Composition card (operator's own row); DS picks
  // belong on champ-select + active-match, not post-game.
  _setTeamComp(enriched);
  _setQuickReview(qr);
  _setReviewButton(m);
  _setMeta(m, data.history_count, enriched);

  // s219 v4: cache the current match's mode for the rank-compare
  // panel + re-render with the saved tier choice.
  _lastMatchMode = m.mode || "";
  let savedTier = "";
  try { savedTier = localStorage.getItem(_RANK_LS_KEY) || ""; } catch (_) {}
  _renderRankCompare(savedTier);
}

// Cache so the dropdown can re-render without refetching /api/last-match.
let _lastMatchMode = "";

function _renderRankCompare(tier) {
  const root = document.getElementById("lm-rank-compare-values");
  if (!root) return;
  if (!tier) {
    root.innerHTML = '<span class="lm-rank-pending">pick a tier to compare</span>';
    return;
  }
  const tierData = _RANK_TIER_AVERAGES[tier];
  if (!tierData) {
    root.innerHTML = `<span class="lm-rank-pending">no data for ${_escHtml(tier)}</span>`;
    return;
  }
  // Look up the current match's mode (defaults to SR if mode missing/unknown).
  const mode = (_lastMatchMode || "").toUpperCase();
  const modeKey = mode in tierData ? mode : (mode === "ARAM" || mode === "KIWI" ? "ARAM" : "SR");
  const avg = tierData[modeKey] || tierData.SR;
  if (!avg) {
    root.innerHTML = `<span class="lm-rank-pending">no data for ${_escHtml(tier)} / ${_escHtml(mode)}</span>`;
    return;
  }
  // 3 cells: avg CS / avg KDA / avg duration. Compact.
  const cells = [
    { label: "CS",  value: String(avg.cs) },
    { label: "KDA", value: avg.kda.toFixed(1) },
    { label: "DUR", value: _fmtDuration(avg.duration_s) },
  ];
  root.innerHTML = cells.map((c) => `
    <div class="lm-rank-cell">
      <span class="lm-rank-cell-label">${_escHtml(c.label)}</span>
      <span class="lm-rank-cell-value">${_escHtml(c.value)}</span>
    </div>
  `).join("");
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
  const parts = [m.mode || "—", _fmtAgo(m.timestamp)];
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
  if (modeTag) modeTag.textContent = m.mode || "—";
  if (kdaText) kdaText.textContent = m.kda_str || "—/—/—";
  if (kdaRatio) {
    const r = m.kda_ratio;
    kdaRatio.textContent = (typeof r === "number") ? `${r.toFixed(2)} KDA` : "—";
  }
  const g = (m.grade || "—").toUpperCase().trim();
  if (grade) {
    grade.textContent = g || "—";
    grade.dataset.grade = (g && g !== "—") ? g : "";
  }
  if (heroBox) {
    heroBox.dataset.grade = (g && g !== "—") ? g : "";
  }
  // W/L badge — only shown when LCU enrichment is in. Arena (CHERRY)
  // has 4 sub-teams and `win` semantics differ; suppress there until
  // we model subteam_placement.
  if (result) {
    const queueId = enriched && enriched.queue_id;
    const isArenaSubteamMode = (queueId === 1700 || queueId === 1710);
    if (enriched && enriched.win != null && !isArenaSubteamMode) {
      const won = !!enriched.win;
      result.textContent = won ? "VICTORY" : "DEFEAT";
      result.dataset.result = won ? "win" : "loss";
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
  const ally  = (enriched.roster || []).filter((r) => r.team_id === myTeamId);
  const enemy = (enriched.roster || []).filter((r) => r.team_id !== myTeamId);
  allyList.innerHTML  = ally.map((r)  => _renderTcRow(r)).join("") || `<li class="lm-tc-empty">—</li>`;
  enemyList.innerHTML = enemy.map((r) => _renderTcRow(r)).join("") || `<li class="lm-tc-empty">—</li>`;

  // Win/loss tag per team using enriched.teams (more reliable than per-row win)
  const teamWin = {};
  (enriched.teams || []).forEach((t) => { teamWin[t.team_id] = !!t.win; });
  const myWin = teamWin[myTeamId];
  if (myWin != null && allyResult) {
    allyResult.textContent = myWin ? "VICTORY" : "DEFEAT";
    allyResult.dataset.result = myWin ? "win" : "loss";
  } else if (allyResult) {
    allyResult.textContent = "—"; allyResult.dataset.result = "";
  }
  const enemyTeamId = enemy.length ? enemy[0].team_id : null;
  const enemyWin = enemyTeamId != null ? teamWin[enemyTeamId] : null;
  if (enemyWin != null && enemyResult) {
    enemyResult.textContent = enemyWin ? "VICTORY" : "DEFEAT";
    enemyResult.dataset.result = enemyWin ? "win" : "loss";
  } else if (enemyResult) {
    enemyResult.textContent = "—"; enemyResult.dataset.result = "";
  }
}

function _renderTcRow(r) {
  // Resolve championId → name via CHAMPS.byId (async-hydrated by items_index.js)
  const slug = (CHAMPS && CHAMPS.byId && CHAMPS.byId[String(r.champion_id)]) || "";
  const portrait = slug ? `/icons/champions/${slug}.png` : "";
  const name = _escHtml(r.game_name || "—");
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
    const tag = _summonerImgTag(sid, "lm-tc-summ");
    return tag || `<div class="lm-tc-summ lm-tc-summ-empty"></div>`;
  }).join("");
  return `<li class="lm-tc-row${meRow}" data-team="${r.team_id}">
    <img class="lm-tc-portrait" src="${portrait}" alt="${slug || ''}" loading="lazy" onerror="this.style.visibility='hidden'">
    <div class="lm-tc-name">${name}${tag}</div>
    <span class="lm-tc-lvl" title="champion level">L${r.champ_level || 0}</span>
    <span class="lm-tc-kda" title="kills / deaths / assists">${kda}</span>
    <span class="lm-tc-cs" title="creep score">${r.cs || 0} CS</span>
    <div class="lm-tc-summs">${summHtml}</div>
    <div class="lm-tc-items">${itemsHtml}</div>
  </li>`;
}

function _setStatsGrid(m) {
  const cs = document.getElementById("lm-cs");
  const cspm = document.getElementById("lm-cs-per-min");
  const gold = document.getElementById("lm-gold");
  const gpm = document.getElementById("lm-gold-per-min");
  const kp = document.getElementById("lm-kp");
  const dur = document.getElementById("lm-duration");
  const when = document.getElementById("lm-when");

  if (cs) cs.textContent = (m.cs != null && m.cs > 0) ? String(m.cs) : "—";
  if (cspm) cspm.textContent = (typeof m.cs_per_min === "number")
    ? `${m.cs_per_min.toFixed(1)} CS/min` : "—";
  if (gold) gold.textContent = (m.gold != null && m.gold > 0)
    ? _fmtGold(m.gold) : "—";
  if (gpm) gpm.textContent = (typeof m.gold_per_min === "number" && m.gold_per_min > 0)
    ? `${Math.round(m.gold_per_min)} / min` : "—";
  if (kp) kp.textContent = (typeof m.kp_pct === "number") ? `${Math.round(m.kp_pct)}%` : "—";
  if (dur) dur.textContent = _fmtDuration(m.duration_s);
  if (when) when.textContent = _fmtAgo(m.timestamp);
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
      ? `no match data — ${errMsg}`
      : "no matches captured yet";
  }
  const champEl = document.getElementById("lm-champion-name");
  if (champEl) { champEl.textContent = "—"; champEl.dataset.champion = ""; }
  ["lm-mode-tag","lm-kda-text","lm-kda-ratio","lm-grade-badge",
   "lm-cs","lm-cs-per-min","lm-gold","lm-gold-per-min",
   "lm-kp","lm-duration","lm-when"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.textContent = "—";
  });
  const result = document.getElementById("lm-result-badge");
  if (result) { result.hidden = true; result.dataset.result = ""; }
  const dsRoot = document.getElementById("lm-ds-picks");
  if (dsRoot) dsRoot.innerHTML = '<span class="lm-empty">no match yet</span>';
  const actual = document.getElementById("lm-actual-build");
  if (actual) actual.hidden = true;
  const tcTable = document.getElementById("lm-tc-table");
  if (tcTable) tcTable.hidden = true;
  ["lm-build-pending","lm-tc-pending"].forEach((id) => {
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
  if (t <= 0) return "—";
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
  if (!timestamp) return "—";
  // match_history.db uses "YYYY-MM-DD HH:MM:SS" local time
  const t = Date.parse(String(timestamp).replace(" ", "T"));
  if (isNaN(t)) return "—";
  const delta = (Date.now() - t) / 1000;
  if (delta < 60) return "just now";
  if (delta < 3600) return `${Math.floor(delta / 60)}m ago`;
  if (delta < 86400) return `${Math.floor(delta / 3600)}h ago`;
  const days = Math.floor(delta / 86400);
  return `${days}d ago`;
}

function _resolveChampKey(name) {
  // Mirror of main.js _resolveChampId — try the window-level resolver
  // if available, else best-effort capitalize+strip-spaces.
  if (typeof window._resolveChampId === "function") {
    try { return window._resolveChampId(name) || ""; } catch (_) {}
  }
  if (!name) return "";
  return String(name).replace(/[^A-Za-z]/g, "");
}

function _scorerUnit(scorer) {
  // Mirror of scorer_units.js scorerUnit — kept local to avoid an
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
