/* HIST2: detached historical Post Game Review panel.
 *
 * A clicked match row on the Session / History page routes to the
 * #view-historical-pgr view with the row's timestamp. This panel renders
 * that specific match's PGR "as if it had just ended", from
 *   GET /api/last-match?match_ts=<YYYY-MM-DD HH:MM:SS>
 * (parameterized in dashboard/builders_last_match._build_last_match).
 *
 * CRITICAL - no clobber: this module owns an ENTIRELY SEPARATE DOM
 * subtree (every id is hpgr- prefixed) and its own module-level state.
 * It NEVER reads or writes any lm- element or the live PGR panel's
 * _lastData singleton, so opening a historical match cannot mutate or
 * clobber the live #view-last-match PGR (the operator's real most-recent
 * game). The live PGR keeps showing the latest match; this frame is a
 * read-only archive view with a BACK action.
 *
 * It reuses the lm-* CSS classes (visual identity) + the shared CHAMPS /
 * ITEMS / itemTooltipHtml libs, and a focused subset of the live PGR
 * render shape (hero identity + stats grid + ally/enemy rosters). The
 * heavy fail-soft sub-panels (career-WPA / win-prob / lane-compare) are
 * deliberately omitted - they key on the live-latest match, not an
 * arbitrary historical match_ts, and are out of scope for the archive
 * view.
 */
import { CHAMPS, ITEMS } from '../lib/items_index.js';
import { itemTooltipHtml, preloadLolDescriptions } from '../lib/lol_descriptions.js';

// Numeric summoner-spell id -> DDragon filename (SR + ARAM common set).
// Mirrors the last_match.js map; kept local to avoid an export churn.
const SUMMONER_SPELL_BY_ID = {
  1: "SummonerBoost", 3: "SummonerExhaust", 4: "SummonerFlash",
  6: "SummonerHaste", 7: "SummonerHeal", 11: "SummonerSmite",
  12: "SummonerTeleport", 13: "SummonerMana", 14: "SummonerDot",
  21: "SummonerBarrier", 30: "SummonerPoroRecall", 31: "SummonerPoroThrow",
  32: "SummonerSnowball", 39: "SummonerSnowURFSnowball_Mark",
  54: "Summoner_UltBookPlaceholder", 55: "SummonerSmiteSweep",
};

function _ddragonVersion() {
  return (ITEMS && ITEMS.version) || "16.10.1";
}

function _onErrCdnFallback(ver, kind, id) {
  const cdnUrl = `https://ddragon.leagueoflegends.com/cdn/${ver}/img/${kind}/${id}.png`;
  return (
    `if(this.dataset.cdn){this.style.visibility='hidden';}` +
    `else{this.dataset.cdn='1';this.src='${cdnUrl}';}`
  );
}

function _itemImgTag(iid, cls = "") {
  if (!iid) return "";
  const ver = _ddragonVersion();
  const localUrl = `/data/ddragon/${ver}/img/item/${iid}.png`;
  const onErr = _onErrCdnFallback(ver, "item", `${iid}.png`);
  const lolHtml = itemTooltipHtml(iid);
  const ttAttr = lolHtml ? ` data-tt-html="${lolHtml.replace(/"/g, "&quot;")}"` : "";
  return `<img class="${cls}" src="${localUrl}" alt=""${ttAttr} loading="lazy" onerror="${onErr}">`;
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
// The match_ts currently shown in the detached frame. Separate from the
// live PGR; exposed via window so main.js's view-activate hook + a stale-
// guard can read it without importing this module's internals.
let _currentTs = null;
let _lastData = null;

/** One-time DOM wiring - the BACK button + DDragon tooltip warm. Idempotent. */
export function wireHistoricalPgrOnce() {
  if (_wired) return;
  _wired = true;
  preloadLolDescriptions();
  // Expose the current-ts getter so main.js's applyView fallback can
  // re-render the same match on a bare re-activate (the stash key having
  // already been consumed). Panels may write window; main.js does not
  // export its closures, so this is the handoff surface.
  try { window._hpgrCurrentTs = historicalPgrCurrentTs; } catch (_) {}
  const back = document.getElementById("hpgr-back");
  if (back) {
    back.addEventListener("click", () => {
      // Return to History. We do NOT touch the live PGR state here - it
      // was never mutated, so the operator's most-recent game is intact.
      try { location.hash = "#history"; } catch (_) {}
      if (typeof window._viewSaveManual === "function") window._viewSaveManual("history");
      if (typeof window._viewResolveAndApply === "function") window._viewResolveAndApply();
    });
  }
}

/** The timestamp of the match currently mounted in the detached frame. */
export function historicalPgrCurrentTs() {
  return _currentTs;
}

/**
 * Fetch the historical match by timestamp + render into the detached
 * frame. `matchTs` is "YYYY-MM-DD HH:MM:SS". Safe to call repeatedly.
 */
export function renderHistoricalPgr(matchTs) {
  const ts = String(matchTs || "").trim();
  _currentTs = ts || null;
  if (!ts) { _setEmptyState("no match selected"); return; }
  let _b = 20;
  try { _b = parseInt(localStorage.getItem("rc-pgr-baseline") || "20", 10); } catch (_) {}
  if (isNaN(_b)) _b = 20;
  _b = Math.max(5, Math.min(50, _b));
  const qs = `?baseline=${_b}&match_ts=${encodeURIComponent(ts)}`;
  // In mock mode the harness intercepts /api/last-match* and returns the
  // fixture; the match_ts param rides along so the same plumbing is
  // exercised. No separate mock-url branch needed - page.route handles it.
  fetch(`/api/last-match${qs}`, { headers: { "Accept": "application/json" } })
    .then((r) => r.json())
    .then((data) => {
      // Guard against a stale async response landing after the operator
      // navigated to a different match: only paint if this ts is still
      // the selected one.
      if (_currentTs !== ts) return;
      _render(data);
    })
    .catch((err) => {
      try { console.warn("[historical-pgr] fetch failed:", err); } catch (_) {}
      _setEmptyState("fetch failed");
    });
}

function _render(data) {
  _lastData = data;
  if (!data || !data.found) {
    _setEmptyState(data && data.error);
    return;
  }
  const m = data.match || {};
  const enriched = m.enriched || null;
  _setHero(m, enriched);
  _setStatsGrid(m, enriched);
  _setHeroScore(enriched);
  _setTeamComp(enriched);
  _setMeta(m);
}

function _setMeta(m) {
  const meta = document.getElementById("hpgr-meta");
  if (!meta) return;
  const parts = [m.mode || "-", _fmtAgo(m.timestamp), "archived match"];
  meta.textContent = parts.filter(Boolean).join(" - ");
}

function _setHero(m, enriched) {
  const portrait = document.getElementById("hpgr-portrait");
  const champEl = document.getElementById("hpgr-champion-name");
  const modeTag = document.getElementById("hpgr-mode-tag");
  const kdaText = document.getElementById("hpgr-kda-text");
  const kdaRatio = document.getElementById("hpgr-kda-ratio");
  const grade = document.getElementById("hpgr-grade-badge");
  const result = document.getElementById("hpgr-result-badge");
  const heroBox = document.getElementById("hpgr-hero");

  const champion = m.champion || "?";
  const champKey = _resolveChampKey(champion);
  if (portrait) {
    portrait.src = champKey ? `/icons/champions/${champKey}.png` : "";
    portrait.alt = champion;
  }
  if (champEl) champEl.textContent = champion;
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
  if (heroBox) heroBox.dataset.grade = (g && g !== "-") ? g : "";
  if (result) {
    const queueId = enriched && enriched.queue_id;
    const isArenaSubteamMode = (queueId === 1700 || queueId === 1710 || queueId === 1750);
    if (enriched && enriched.win != null && !isArenaSubteamMode) {
      const won = !!enriched.win;
      let label = won ? "VICTORY" : "DEFEAT";
      if (enriched.ended_in_early_surrender) label += " (REMAKE)";
      else if (enriched.ended_in_surrender) label += " (FF)";
      result.textContent = label;
      result.dataset.result = won ? "win" : "loss";
      result.hidden = false;
    } else if (enriched && isArenaSubteamMode) {
      result.textContent = "ARENA";
      result.dataset.result = "neutral";
      result.hidden = false;
    } else {
      result.hidden = true;
      result.dataset.result = "";
    }
  }
}

function _setStatsGrid(m, enriched) {
  const cs       = document.getElementById("hpgr-cs");
  const cspm     = document.getElementById("hpgr-cs-per-min");
  const kp       = document.getElementById("hpgr-kp");
  const vision   = document.getElementById("hpgr-vision");
  const tankDmg  = document.getElementById("hpgr-tank-dmg");
  const damage   = document.getElementById("hpgr-damage");
  const healing  = document.getElementById("hpgr-healing");

  if (cs)   cs.textContent   = (m.cs != null && m.cs > 0) ? String(m.cs) : "-";
  if (cspm) cspm.textContent = (typeof m.cs_per_min === "number") ? m.cs_per_min.toFixed(1) : "-";
  if (kp)   kp.textContent   = (typeof m.kp_pct === "number") ? `${Math.round(m.kp_pct)}%` : "-";

  const e   = enriched || {};
  const dmg = e.damage  || {};
  const sup = e.support || {};
  const vs  = e.vision  || {};

  if (vision)  vision.textContent  = (vs.score != null) ? String(vs.score) : "-";
  if (tankDmg) tankDmg.textContent = (dmg.taken) ? _fmtThousands(dmg.taken) : "-";
  if (damage)  damage.textContent  = (dmg.dealt_to_champs) ? _fmtThousands(dmg.dealt_to_champs) : "-";
  if (healing) {
    const hs = sup.heal_plus_shield || 0;
    healing.textContent = hs > 0 ? _fmtThousands(hs) : "-";
  }
}

function _scoreTier(score) {
  const n = Number(score) || 0;
  if (n >= 80) return { label: "Excellent", key: "excellent" };
  if (n >= 65) return { label: "Good",      key: "good" };
  if (n >= 50) return { label: "OK",        key: "ok" };
  return            { label: "Bad",       key: "bad" };
}

function _setHeroScore(enriched) {
  const wrap    = document.getElementById("hpgr-hero-score");
  const valueEl = document.getElementById("hpgr-hero-score-value");
  const tierEl  = document.getElementById("hpgr-hero-score-tier");
  if (!wrap || !valueEl || !tierEl) return;
  const roster = enriched && enriched.roster;
  const me = roster && roster.find((r) => r && r.is_me);
  if (!roster || !roster.length || !me) {
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

function _setTeamComp(enriched) {
  const table = document.getElementById("hpgr-tc-table");
  const allyList = document.getElementById("hpgr-tc-ally-list");
  const enemyList = document.getElementById("hpgr-tc-enemy-list");
  const allyResult = document.getElementById("hpgr-tc-ally-result");
  const enemyResult = document.getElementById("hpgr-tc-enemy-result");
  const pending = document.getElementById("hpgr-tc-pending");
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

  const teamWin = {};
  (enriched.teams || []).forEach((t) => { teamWin[t.team_id] = !!t.win; });

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
    return meta;
  };
  const enemyTid = enemy.length ? enemy[0].team_id : null;
  const allyMeta  = rankSide(ally,  !!teamWin[myTeamId]);
  const enemyMeta = rankSide(enemy, enemyTid != null ? !!teamWin[enemyTid] : false);
  const metaFor = (r) =>
    ((r.team_id === myTeamId ? allyMeta : enemyMeta)[r.participant_id])
    || { badge: "", rank: 0, score: 0 };

  allyList.innerHTML  = ally.map((r)  => _renderTcRow(r, metaFor(r))).join("")  || `<li class="lm-tc-empty">-</li>`;
  enemyList.innerHTML = enemy.map((r) => _renderTcRow(r, metaFor(r))).join("") || `<li class="lm-tc-empty">-</li>`;

  const myWin = teamWin[myTeamId];
  if (myWin != null && allyResult) {
    allyResult.textContent = myWin ? "VICTORY" : "DEFEAT";
    allyResult.dataset.result = myWin ? "win" : "loss";
  } else if (allyResult) {
    allyResult.textContent = "-"; allyResult.dataset.result = "";
  }
  const enemyWin = enemyTid != null ? teamWin[enemyTid] : null;
  if (enemyWin != null && enemyResult) {
    enemyResult.textContent = enemyWin ? "VICTORY" : "DEFEAT";
    enemyResult.dataset.result = enemyWin ? "win" : "loss";
  } else if (enemyResult) {
    enemyResult.textContent = "-"; enemyResult.dataset.result = "";
  }
}

function _renderTcRow(r, sm) {
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
  const summHtml = [r.summoner1, r.summoner2].map((sid) => {
    const t = _summonerImgTag(sid, "lm-tc-summ");
    return t || `<div class="lm-tc-summ lm-tc-summ-empty"></div>`;
  }).join("");
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
  return `<li class="lm-tc-row${meRow}" data-team="${r.team_id}">
    <img class="lm-tc-portrait" src="${portrait}" alt="${slug || ''}" loading="lazy" onerror="this.style.visibility='hidden'">
    <div class="lm-tc-name">${name}${tag}</div>
    ${scoreCell}
    <span class="lm-tc-lvl" title="champion level">${r.champ_level || 0}</span>
    <span class="lm-tc-kda" title="kills / deaths / assists">${kda}</span>
    <div class="lm-tc-summs">${summHtml}</div>
    <span class="lm-tc-cs" title="creep score">${r.cs || 0} CS</span>
    <div class="lm-tc-items">${itemsHtml}</div>
  </li>`;
}

// Same heuristic as last_match.js _rosterScores so the historical frame's
// per-row chip + hero score stay consistent with the live PGR's scoring.
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
  const out = {};
  rows.forEach((r) => {
    const k = +r.kills || 0, d = +r.deaths || 0, a = +r.assists || 0;
    const kdaN = Math.min(((k + a) / Math.max(d, 1)) / 6, 1);
    out[r.participant_id] = 100 * (
      0.30 * kdaN +
      0.28 * ((+r.damage_to_champs || 0) / mDmg) +
      0.16 * ((+r.gold || 0) / mGold) +
      0.12 * ((+r.cs || 0) / mCs) +
      0.08 * ((+r.vision_score || 0) / mVis) +
      0.06 * ((+r.damage_taken || 0) / mTank)
    );
  });
  return out;
}

function _setEmptyState(errMsg) {
  const heroBox = document.getElementById("hpgr-hero");
  if (heroBox) heroBox.dataset.grade = "";
  const meta = document.getElementById("hpgr-meta");
  if (meta) {
    meta.textContent = errMsg
      ? `match unavailable - ${errMsg}`
      : "match not found in history";
  }
  const champEl = document.getElementById("hpgr-champion-name");
  if (champEl) champEl.textContent = "-";
  ["hpgr-mode-tag", "hpgr-kda-text", "hpgr-kda-ratio", "hpgr-grade-badge",
   "hpgr-cs", "hpgr-cs-per-min", "hpgr-kp", "hpgr-vision", "hpgr-tank-dmg",
   "hpgr-damage", "hpgr-healing"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.textContent = "-";
  });
  const result = document.getElementById("hpgr-result-badge");
  if (result) { result.hidden = true; result.dataset.result = ""; }
  const heroScore = document.getElementById("hpgr-hero-score");
  if (heroScore) { heroScore.hidden = true; heroScore.dataset.tier = ""; }
  const table = document.getElementById("hpgr-tc-table");
  if (table) table.hidden = true;
  const pending = document.getElementById("hpgr-tc-pending");
  if (pending) pending.hidden = false;
}

/* -- helpers (mirror the live PGR panel) ---------------------------- */

function _fmtThousands(n) {
  const v = Number(n) || 0;
  if (v >= 1000) return `${(v / 1000).toFixed(1)}k`;
  return String(v);
}

function _fmtAgo(timestamp) {
  if (!timestamp) return "-";
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
  if (typeof window._resolveChampId === "function") {
    try { return window._resolveChampId(name) || ""; } catch (_) {}
  }
  if (!name) return "";
  return String(name).replace(/[^A-Za-z]/g, "");
}

function _escHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// Re-render once the DDragon item-description cache lands so item icons
// pick up their rich tooltip. Mirrors last_match.js; idempotent.
document.addEventListener("rc:lol-descriptions-ready", () => {
  if (_lastData) _render(_lastData);
});
