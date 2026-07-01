// Champ Select panel - full-page view rendered during ChampSelect
// phase: pick&ban + build chooser + SR Draft Theatre + analyzer.
// _ib* functions live in item_build.js (avoid circular dep).
import { el, safe, fmtList, isArenaPayload, escHtml } from '../lib/helpers.js';
import { state } from '../lib/state.js';
import { ITEMS, CHAMPS, _normItemName, _resolveItemId, _resolveChampId } from '../lib/items_index.js';
import { sumImg, sumName } from '../lib/summoner_spells.js';
import { itemTooltipHtml, keystoneTooltipHtml, preloadLolDescriptions } from '../lib/lol_descriptions.js';
import { championTags, preloadChampionTags } from '../lib/champion_tags.js';
import {
  _ibPushItems, _ibFetchAndRender, _ibSetStatus,
  _ibRenderRows, _ibMarkSelectedRow, _ibSaveChoice,
} from './item_build.js';
import { buildOrderCardHtml } from './build_order.js';
import { dedupFetch } from '../lib/dedup_fetch.js';
import {
  fetchBanSuggest, getCachedBanSuggest, getBanSuggestCacheCount,
  renderBanSuggestModeChip, renderBanSuggestList,
} from './ban_suggest_toggle.js';
import {
  fetchCcBlendedEhpThreat, getCachedCcBlendedEhpThreat,
  getCcBlendedEhpThreatCacheCount,
  renderCcBlendedEhpThreat, resolveChampNames,
} from './cc_blended_ehp_threat.js';
import {
  fetchCcConditionalPressure, getCachedCcConditionalPressure,
  getCcConditionalPressureCacheCount,
  renderCcConditionalPressure,
} from './cc_conditional_pressure.js';
import {
  fetchCooldownWatch, getCachedCooldownWatch,
  getCooldownWatchCacheCount, renderCooldownWatch,
} from './cooldown_watch.js';
// 2026-06-25: personal best-build card (Overlay App E personal-WR build override,
// local-data half). Reads the operator's OWN locked champion + surfaces the
// items they win with from rewind_history.db. Backend routes_personal_build.
import {
  fetchPersonalBuild, getCachedPersonalBuild,
  getPersonalBuildCacheCount, renderPersonalBuild, pbwModeForQueue,
} from './personal_build.js';
// CS1 (2026-06-08): ally CC-pairing card. Delimited new block - CS3 will
// also touch champ_select.js; keep CS1 imports + wiring grouped here.
import {
  fetchCcPairing, getCachedCcPairing,
  getCcPairingCacheCount, renderCcPairing,
} from './cc_pairing.js';
// CS3 (2026-06-08): the DPS-scaling sweep, 1v1 fight-model matchup,
// action-queue combo timeline, and relative-item-power panels were MOVED to
// the Active Match view (web/js/panels/active_match.js) - they now read the
// LIVE champion mid-game instead of the locked champ-select pick. Their
// imports + render invocations left this file with the move. The profile,
// engine-knobs, and stat-check panels STAY on champ-select.
import {
  renderDsProfileForChampSelect, getDsProfileCacheCount, setDsProfileScheduler,
} from './ds_profile.js';
import {
  renderDsSkillOrderForChampSelect, setDsSkillOrderScheduler,
} from './ds_skill_order.js';
import { showPlayerGpi } from './player_gpi.js';
import { renderDsKnobs, getDsKnobsCacheCount } from './ds_knobs.js';
import { renderDsStatcheck, getDsStatcheckCacheCount } from './ds_statcheck.js';

// -- LCU command helper (used by champ-select + build chooser) ------
function lcuCmd(cmdObj) {
  // Endpoint expects FLAT shape: {cmd: "name", ...args} - not wrapped.
  return fetch("/api/lcu-cmd", {
    method: "POST", cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cmdObj),
  }).then((r) => (r && r.ok ? r.json() : null)).catch(() => null);
}

// Poll /api/lcu-cmd-result for the agent's response to a queued LCU
// command (the POST itself returns immediately with just the queue id).
// Calls onResult({ok, err}) once the agent reports back, or once after
// ~3s of pending if the agent is unreachable. Used by the lobby Find
// Match / Cancel / Change-queue buttons so non-leader 400s and other
// LCU errors surface as a status line instead of vanishing silently.
function lcuPollResult(id, onResult) {
  if (!id) { onResult && onResult({ ok: false, err: "no_queue_id" }); return; }
  let tries = 0;
  const tick = () => {
    tries += 1;
    fetch("/api/lcu-cmd-result?id=" + id, { cache: "no-store" })
      .then((r) => r.json().then((j) => ({ status: r.status, body: j })))
      .then(({ status, body }) => {
        if (status === 200 && body && body.result) {
          onResult && onResult(body.result);
        } else if (tries < 6) {
          setTimeout(tick, 500);
        } else {
          onResult && onResult({ ok: false, err: "timeout" });
        }
      })
      .catch(() => {
        if (tries < 6) setTimeout(tick, 500);
        else onResult && onResult({ ok: false, err: "fetch_failed" });
      });
  };
  setTimeout(tick, 300);  // give agent one poll cycle to drain
}

function _csChampImg(cid) {
  if (!cid) return "";
  const nm = CHAMPS.byId[String(cid)];
  if (!nm) return "";
  return `/data/ddragon/${CHAMPS.version}/img/champion/${nm}.png`;
}
function _csChampName(cid) {
  return (cid && CHAMPS.byId[String(cid)]) || "";
}

// 2026-04-25: Cold-start champ-select coaching. When LCU phase is
// ChampSelect and we have a locked-in champion + enemy team, surface
// the user's historical adaptation data BEFORE the game starts.
// Resolves championId integers to names via the CHAMPS byId index.
const _CS_LIVE = { lastKey: "", inflight: false, lastFetch: 0, lastResult: null };

function handleChampSelect(lcu) {
  // s162: cache the LCU snapshot on state.latest so view-lobby's
  // _lobbyViewRefresh (which reads state.latest.lcu) sees the same data
  // as the new champ-select view. Pre-fix the lobby sub-page rendered
  // empty in production because no upstream path ever assigned
  // state.latest.lcu.
  state.latest.lcu = lcu || null;
  // s162 bug fix (2026-05-10): renderLobbyPanel / renderHomePanel /
  // _viewResolveAndApply / _maybeRefreshLobbyView USED to be called
  // here, but they're defined in main.js's module scope and were never
  // imported into champ_select.js - every call threw ReferenceError
  // silently caught by the SSE try/catch, so post-refresh the lobby
  // view never re-rendered with newly-arrived lcu data. Orchestration
  // now lives in main.js's handleLcuEnvelope wrapper.
  if (!lcu || lcu.phase !== "ChampSelect") return;
  const cs = lcu.champ_select || {};
  if (!cs.my_champion || cs.my_champion <= 0) return;
  if (!CHAMPS.ready) return;  // wait for champion-name resolver
  const myName = CHAMPS.byId[String(cs.my_champion)];
  if (!myName) return;
  const allies = (cs.my_team || [])
    .map((p) => CHAMPS.byId[String(p && p.championId)])
    .filter(Boolean);
  const enemies = (cs.their_team || [])
    .map((p) => CHAMPS.byId[String(p && p.championId)])
    .filter(Boolean);
  const bench = (cs.bench || [])
    .map((id) => CHAMPS.byId[String(id)])
    .filter(Boolean);
  // Map queue_id to adaptation mode. ARAM-family = 450 (Classic) /
  // 920 (Poro King) / 2400 (Mayhem); Arena = 1750 live (1700/1710 legacy).
  const modeMap = {
    450: "aram", 920: "aram", 2400: "aram",   // ARAM Classic / Poro King / Mayhem
    1750: "arena", 1700: "arena", 1710: "arena",    // Arena live + legacy aliases
    400: "sr_draft", 420: "sr_ranked", 430: "sr_ranked", 440: "sr_ranked",
    830: "sr_ranked", 840: "sr_ranked", 850: "sr_ranked",   // co-op vs AI
  };
  const adaptMode = modeMap[cs.queue_id] || "aram";
  fetchAdaptation(myName, adaptMode === "sr_draft" ? "sr" : adaptMode, enemies);

  // Live Haiku coaching - debounced + key-deduped so we only fire when
  // the actual pick state changes (champion or team comp), not on every
  // 2 s state poll. ~1 Haiku call per ~10 s of active drafting.
  const liveKey = [
    myName, cs.queue_id, allies.join("|"), enemies.join("|"), bench.join("|"),
  ].join("/");
  const now = Date.now();
  if (liveKey === _CS_LIVE.lastKey) return;
  if (now - _CS_LIVE.lastFetch < 6000) return;   // 6 s minimum spacing
  if (_CS_LIVE.inflight) return;
  _CS_LIVE.lastKey = liveKey;
  _CS_LIVE.lastFetch = now;
  _CS_LIVE.inflight = true;
  fetch("/api/champ-select-coach", {
    method: "POST", cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      is_aram: !!cs.is_aram,
      queue_id: cs.queue_id,
      my_champion: myName,
      my_team: allies,
      their_team: enemies,
      bench: bench,
    }),
  })
    .then((r) => r.ok ? r.json() : null)
    .then((data) => {
      _CS_LIVE.inflight = false;
      if (!data || !data.ok) return;
      _CS_LIVE.lastResult = data;
      renderChampSelectCoach(data);
    })
    .catch(() => { _CS_LIVE.inflight = false; });
}

// Light renderer - drops the Haiku output into the Right Now action +
// immediate slots while in champ-select. Keeps the existing in-game
// UI surface; switches content when phase=ChampSelect.
function renderChampSelectCoach(data) {
  if (!RN.action || !RN.immediate) return;
  const head = data.advice || "(no advice)";
  RN.action.innerHTML = "> " + head;
  const lines = [];
  if (data.summoners) lines.push("Summoners: " + data.summoners);
  if (data.swap)      lines.push("Swap: " + data.swap);
  if (data.watchout)  lines.push("Watch: " + data.watchout);
  _rnImmediate.textContent = lines.join("  *  ");
}

// -- Champ Select VIEW (s164 - Phase 3 step 3 scaffold) -------------
// Top-level <section id="view-champ-select"> page rendered while
// lcu.phase === "ChampSelect". Auto-promoted by main.js's view router.

function _csvSetText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text || "";
}

// LCU command helper for the trade/swap clicks below.
function _csvFireCmd(cmd) {
  return fetch("/api/lcu-cmd", {
    method: "POST", cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cmd),
  }).then((r) => (r && r.ok ? r.json() : null)).catch(() => null);
}
function _csvOnLaneSwap(cellId) {
  if (cellId == null) return;
  _csvFireCmd({ cmd: "request_position_swap", cell_id: cellId });
}
function _csvOnChampTrade(cellId) {
  if (cellId == null) return;
  _csvFireCmd({ cmd: "trade_request", cell_id: cellId });
}
function _csvOnPickOrderSwap(cellId) {
  if (cellId == null) return;
  _csvFireCmd({ cmd: "request_pick_order_swap", cell_id: cellId });
}
// Quick-select handlers for Pick & Ban panel icons. Tracks the active
// selection client-side so the colored border stays on the picked
// icon across re-renders, and a "locked" flag so subsequent clicks
// can't re-target a different ban/pick once the first has been sent.
// s212 v6: dropped the banLocked / pickLocked gates. Pre-s212v6 the
// first click committed and disabled the other 2 cells in the row,
// modeling "one-time intent". Operator's new flow: every click fires
// `set_ban_intent` / `set_pick_intent` to LCU; the agent itself
// decides whether to accept the change. Dashboard tracks only the
// latest clicked id for `.is-selected` highlight purposes.
const _csvSelection = { ban: 0, pick: 0 };
function _csvOnBanSelect(championId) {
  if (!championId) return;
  _csvSelection.ban = championId;
  _csvFireCmd({ cmd: "set_ban_intent", championId: championId });
}
function _csvOnPickSelect(championId) {
  if (!championId) return;
  _csvSelection.pick = championId;
  _csvFireCmd({ cmd: "set_pick_intent", championId: championId });
}
// 1 -> "1st", 2 -> "2nd", 3 -> "3rd", 4 -> "4th", etc.
function _csvOrdinal(n) {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}
// Full role names used in the trade popup AND in the ally/enemy
// position pip. Operator wanted them spelled out rather than the
// 3-letter abbreviations the panel previously showed.
const _CSV_SHORT_ROLE = {
  TOP: "TOP", JUNGLE: "JG", MIDDLE: "MID",
  BOTTOM: "ADC", UTILITY: "SUP",
};
function _csvShortRole(pos) {
  return _CSV_SHORT_ROLE[pos] || pos || "-";
}
// Singleton popup that appears when the operator clicks an ally's
// summoner name. Structure: a SWAP / TRADE header row above three
// equal-width choice buttons:
//   1) <CHAMPION NAME>  -> champion trade
//   2) <Nth Pick>       -> pick-order swap (only when showPickOrder)
//   3) <ROLE LABEL>     -> lane swap (uses ally's actual short role)
// Positioned so the MIDDLE button's center sits on the username's
// center (when middle is hidden, falls back to the champion button).
function _csvShowTradeChoice(cellId, anchorEl, opts) {
  const champName    = (opts && opts.champName)    || "Champion";
  const pickOrderLbl = (opts && opts.pickOrderLbl) || "";
  const roleLbl      = (opts && opts.roleLbl)      || "-";
  const showPickOrd  = !!(opts && opts.showPickOrder);

  let popup = document.getElementById("csv-trade-popup");
  if (!popup) {
    popup = document.createElement("div");
    popup.id = "csv-trade-popup";
    popup.className = "csv-trade-popup";
    popup.innerHTML =
      '<div class="csv-trade-header">SWAP / TRADE</div>' +
      '<div class="csv-trade-buttons">' +
        '<button type="button" class="csv-trade-choice" data-action="champion"></button>' +
        '<button type="button" class="csv-trade-choice" data-action="pick-order"></button>' +
        '<button type="button" class="csv-trade-choice" data-action="role"></button>' +
      '</div>';
    // Append to <html> instead of <body> - body has zoom:1.33 (see
    // base.css), and any position:fixed descendant of a zoomed element
    // has its top/left values scaled by that zoom, which was offsetting
    // the popup ~33% below where the click landed. The popup gets a
    // matching zoom in CSS so its visual size still matches the rest
    // of the dashboard.
    document.documentElement.appendChild(popup);
    document.addEventListener("click", (ev) => {
      if (!popup.classList.contains("is-open")) return;
      if (popup.contains(ev.target)) return;
      popup.classList.remove("is-open");
    });
    popup.addEventListener("click", (ev) => {
      const btn = ev.target.closest(".csv-trade-choice");
      if (!btn) return;
      const cid = parseInt(popup.dataset.cellId, 10);
      const action = btn.dataset.action;
      popup.classList.remove("is-open");
      if (action === "role")       _csvOnLaneSwap(cid);
      else if (action === "champion") _csvOnChampTrade(cid);
      else if (action === "pick-order") _csvOnPickOrderSwap(cid);
    });
  }
  const champBtn = popup.querySelector('[data-action="champion"]');
  if (champBtn) champBtn.textContent = champName.toUpperCase();
  const pickBtn  = popup.querySelector('[data-action="pick-order"]');
  if (pickBtn) {
    pickBtn.textContent = pickOrderLbl;
    pickBtn.style.display = showPickOrd ? "" : "none";
  }
  const roleBtn  = popup.querySelector('[data-action="role"]');
  if (roleBtn) roleBtn.textContent = roleLbl.toUpperCase();
  popup.dataset.cellId = String(cellId);
  // Render-then-measure: show the popup with visibility:hidden so we
  // can read its actual rendered width via getBoundingClientRect, then
  // compute final left so the popup is horizontally centered on the
  // ALLIES panel and its top edge sits just under the clicked username.
  // Avoids the transform-based positioning that was producing the
  // wrong offset on lower rows.
  popup.style.visibility = "hidden";
  popup.style.left = "0px";
  popup.style.top  = "0px";
  popup.style.transform = "";
  popup.classList.add("is-open");
  const popupRect = popup.getBoundingClientRect();
  const userRect  = anchorEl.getBoundingClientRect();
  const panel = anchorEl.closest(".csv-card-allies");
  const panelRect = panel ? panel.getBoundingClientRect() : userRect;
  const targetLeft = panelRect.left + panelRect.width / 2 - popupRect.width / 2;
  const targetTop  = userRect.bottom + 2;  // 2px breathing room
  popup.style.left = Math.round(targetLeft) + "px";
  popup.style.top  = Math.round(targetTop) + "px";
  popup.style.visibility = "visible";
}

// Module-level cache: { type: "ban"|"pick", cellSet: Set<cellId> } -
// derived from cs.active_round and consulted by _csvRenderTeam to
// apply the pulsating border class to cells whose cellId is in the
// active round. Reset on each renderChampSelectView call.
let _csvActiveRound = null;

// Mode classifier for the champ-select view. SR draft is the historical
// default; ARAM (450/920/2400), Arena (1750 live, 1700/1710 legacy) get
// distinct central + enemies layouts because the LCU surface they
// expose differs structurally - ARAM has a bench but no roles/bans,
// Arena has 6 teams of 3 + augments and no enemy-team field. s214 v2:
// Brawl mode retired from the live League rotation; brawl branches
// dropped from this classifier. 2026-05-24 (#89): Arena live queue
// flipped 1700 -> 1750 (verified via /lol-game-queues/v1/queues
// catalog); 1700/1710 retained as legacy aliases for historical match
// data still in rewind_history.db.
function _csvDetectMode(cs) {
  if (!cs) return "sr";
  const q = (cs.queue_id | 0);
  if (q === 1700 || q === 1710 || q === 1750) return "arena";
  if (cs.is_aram || q === 450 || q === 920 || q === 2400) return "aram";
  return "sr";
}

// s209: queue_id -> human label for the CS sub-line. Mirrors the agent's
// `_LOBBY_QUEUE_NAMES` map in tools/lcu_agent.py:220 - the agent
// forwards `queue_name` on the lobby envelope but not the champ-select
// envelope, so the dashboard needs its own local mapping. Unknown IDs
// fall through to "queue <N>" for visibility.
const _CSV_QUEUE_NAMES = {
  400:  "Normal Draft",
  420:  "Ranked Solo/Duo",
  430:  "Normal Blind",
  440:  "Ranked Flex",
  450:  "ARAM",
  480:  "Swiftplay",
  490:  "Quickplay",
  700:  "Clash",
  900:  "URF",
  920:  "Poro King",
  1020: "One for All",
  1300: "Nexus Blitz",
  1400: "Ultimate Spellbook",
  1700: "Arena",
  1710: "Arena",
  1750: "Arena",  // Live Arena 3x6 (CHERRY mapId 30) - 2026-05-24 #89.
  2400: "ARAM Mayhem",
};
function _csvQueueLabel(queueId) {
  const q = queueId | 0;
  return _CSV_QUEUE_NAMES[q] || (q ? "queue " + q : "");
}

// s209: rune-tree icon paths. Files live at data/icons/runes/<slug>.png
// and ride the numeric-prefix convention DDragon ships them with. The
// "Whimsy" file is Riot's Arena-tier rebrand of the Inspiration tree -
// it's the only Inspiration art the icon set carries.
const _CSV_RUNE_TREE_FILES = {
  Precision:   "7201_Precision",
  Domination:  "7200_Domination",
  Sorcery:     "7202_Sorcery",
  Resolve:     "7204_Resolve",
  Inspiration: "7203_Whimsy",
};
function _csvTreeIcon(treeName) {
  const slug = _CSV_RUNE_TREE_FILES[String(treeName || "").trim()];
  return slug ? `/icons/runes/${slug}.png` : "";
}
// Keystone slug overrides for keystones whose icon filename doesn't
// match the TitleCase-no-spaces derivation. Riot has shipped a couple
// of mid-rebrand assets with "Temp" / "Veteran" prefixes that haven't
// been renamed back. Keep this map small - add entries only when a
// concrete file mismatch is observed.
const _CSV_KEYSTONE_SLUG_OVERRIDES = {
  "Lethal Tempo": "LethalTempoTemp",
  "Aftershock":   "VeteranAftershock",
};
// Keystone slug - TitleCase each word + strip spaces. ("Press the Attack"
// -> "PressTheAttack", "Grasp of the Undying" -> "GraspOfTheUndying").
// Matches the file naming convention in data/icons/runes/.
function _csvKeystoneIcon(keystoneName) {
  const raw = String(keystoneName || "").trim();
  if (!raw) return "";
  if (_CSV_KEYSTONE_SLUG_OVERRIDES[raw]) {
    return `/icons/runes/${_CSV_KEYSTONE_SLUG_OVERRIDES[raw]}.png`;
  }
  const slug = raw
    .split(/\s+/)
    .map((w) => w ? w[0].toUpperCase() + w.slice(1).toLowerCase() : "")
    .join("")
    .replace(/[^A-Za-z0-9]/g, "");
  return slug ? `/icons/runes/${slug}.png` : "";
}

// s209: LCU's `cs.phase` is shouty-snake-case ("BAN_PICK", "FINALIZATION",
// "GAME_STARTING"). Convert to Title Case with spaces for the sub-line.
// Unknown phases fall through as-is so anything new lands legibly.
const _CSV_PHASE_LABELS = {
  PLANNING:      "Planning",
  BAN_PICK:      "Ban & Pick",
  FINALIZATION: "Finalizing",
  GAME_STARTING: "Starting",
};
function _csvHumanPhase(phase) {
  if (!phase) return "";
  const upper = String(phase).toUpperCase();
  if (_CSV_PHASE_LABELS[upper]) return _CSV_PHASE_LABELS[upper];
  return upper.replace(/_/g, " ").toLowerCase()
              .replace(/\b\w/g, (c) => c.toUpperCase());
}

// Renders a team cell list. Backward-compatible 5-positional signature
// - the 6th `opts` arg adds mode-aware behavior: `cellCount` (default
// 5), `showGuess` (default true for enemy lists), and `allowRolePip`
// (default true). ARAM passes `showGuess: false` since roles are
// random and the (guess) annotation is meaningless; Arena uses a
// dedicated 2-cell ally renderer instead.
// Personal-vs threat tag cache. Keyed by champId; values are
// {ts, payload|null|"pending"}. TTL matches the backend cache (60s)
// so repeat renders inside a single champ-select tick are free.
const _csvThreatCache = new Map();
const _CSV_THREAT_TTL_MS = 60 * 1000;
const _CSV_THREAT_DAYS = 30;

function _csvThreatBandCls(band) {
  // Defensive: trust the backend but coerce unknowns to "unknown" so
  // an unexpected value doesn't strip the placeholder styling.
  if (band === "red" || band === "amber" || band === "green") return band;
  return "unknown";
}

function _csvThreatTagApply(el, payload, champNm) {
  if (!el || !payload || !payload.ok) {
    if (el) {
      el.className = "csv-team-cell-threat csv-team-cell-threat--unknown";
      el.textContent = "n/a";
      el.title = "no data for " + (champNm || "this champion");
    }
    return;
  }
  const band = _csvThreatBandCls(payload.threat_band);
  el.className = "csv-team-cell-threat csv-team-cell-threat--" + band;
  const n = payload.sample_n | 0;
  if (n <= 0) {
    el.textContent = "0g";
    el.title = "no games vs " + (payload.champ_name || champNm)
             + " in last " + (payload.days | 0) + "d";
    return;
  }
  // "5-2 (71%)" - explicit W-L is more readable than just a percentage
  // when the sample is small (the band already encodes WR colour).
  el.textContent = (payload.wins | 0) + "-" + (payload.losses | 0)
                 + " (" + (payload.wr_pct | 0) + "%)";
  el.title = "personal record vs " + (payload.champ_name || champNm)
           + " - last " + (payload.days | 0) + "d ("
           + (payload.wins | 0) + "W " + (payload.losses | 0) + "L)";
}

function _csvThreatTagFetch(champId, champNm, el) {
  if (!champId || champId <= 0 || !el) return;
  const cached = _csvThreatCache.get(champId);
  const now = Date.now();
  if (cached && cached.payload && (now - cached.ts) < _CSV_THREAT_TTL_MS) {
    _csvThreatTagApply(el, cached.payload, champNm);
    return;
  }
  if (cached && cached.payload === "pending") {
    // Already in flight - leave placeholder text; the in-flight resolver
    // will paint this DOM node too because it stamps every live element
    // with the matching data-champ-id.
    return;
  }
  _csvThreatCache.set(champId, { ts: now, payload: "pending" });
  const url = "/api/personal-vs?champ_id=" + (champId | 0)
            + "&days=" + _CSV_THREAT_DAYS;
  fetch(url, { credentials: "same-origin", cache: "no-store" })
    .then((r) => r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status)))
    .then((data) => {
      _csvThreatCache.set(champId, { ts: Date.now(), payload: data });
      // Paint every live element for this champion. _csvRenderTeam may
      // have re-rendered the cell since the fetch fired, so query by
      // data-champ-id rather than holding a stale reference.
      document
        .querySelectorAll(".csv-team-cell-threat[data-champ-id='" + (champId | 0) + "']")
        .forEach((node) => _csvThreatTagApply(node, data, champNm));
    })
    .catch(() => {
      _csvThreatCache.set(champId, { ts: Date.now(), payload: null });
      document
        .querySelectorAll(".csv-team-cell-threat[data-champ-id='" + (champId | 0) + "']")
        .forEach((node) => _csvThreatTagApply(node, null, champNm));
    });
}

function _csvRenderTeam(listId, team, myCid, timerEndMs, showPickOrder, opts) {
  const list = document.getElementById(listId);
  if (!list) return;
  list.innerHTML = "";
  const cellCount   = (opts && opts.cellCount) || 5;
  const isEnemyList = (listId === "csv-enemies-list");
  const showGuess   = !opts || opts.showGuess !== false;
  const allowRole   = !opts || opts.allowRolePip !== false;
  const arr = (team || []).slice(0, cellCount);
  while (arr.length < cellCount) arr.push(null);
  arr.forEach((p, idx) => {
    const cid = (p && p.championId) | 0;
    const isMe = !!(myCid && cid === myCid);
    const champNm = _csChampName(cid) || (cid ? "cid:" + cid : "-");
    const summ = (p && p.summonerName) || "";
    const pos = (p && p.assignedPosition) || "";
    const stateCls = !cid ? "empty" : ((p && p.completed) ? "locked" : "hovering");
    const url = _csChampImg(cid);

    // s213 v2: lock icon ([lock]) removed per operator. The cell's overall
    // outline already encodes lock state (green border for locked,
    // amber for hovering) so the per-cell padlock was redundant.
    // s214: countdown timer also removed for allies + enemies - same
    // signal already lives in the global champ-select header timer +
    // the active-round border indicator. Per-cell timer added too
    // much visual noise without a unique payload.
    const lockHtml = "";

    // Hoist peer-cell identity ABOVE the li.className use - referencing
    // peerCellId before its const declaration would throw a TDZ
    // ReferenceError and crash the whole forEach (no cells rendered).
    const isAllyOther = (listId === "csv-allies-list") && !isMe && cid;
    const peerCellId = (p && typeof p.cellId === "number") ? p.cellId : null;

    const li = document.createElement("li");
    let activeCls = "";
    if (_csvActiveRound && _csvActiveRound.cellSet
        && peerCellId != null && _csvActiveRound.cellSet.has(peerCellId)) {
      activeCls = (_csvActiveRound.type === "ban") ? " is-banning" : " is-picking";
    }
    li.className = "csv-team-cell " + stateCls + (isMe ? " me" : "") + activeCls;
    li.dataset.cid = String(cid || 0);

    // Operator 2026-05-31 (part 4): on the SR Enemies panel, reserve a
    // fixed-width leading slot for the operator's lifetime win-rate vs
    // this enemy (filled by _csvInjectEnemyWinRates once the personal-
    // record fetch lands). First child so every enemy icon stays aligned.
    if (isEnemyList && opts && opts.withWinRate) {
      const wrSlot = document.createElement("span");
      wrSlot.className = "csv-enemy-wr-slot";
      li.appendChild(wrSlot);
    }

    const icon = document.createElement("div");
    icon.className = "csv-team-cell-icon";
    icon.innerHTML = url
      ? `<img src="${url}" alt="" onerror="this.style.display='none'">`
      : "";
    // Per operator: champion-icon and pos-pip no longer initiate
    // trades directly - the only click target for trades is the
    // summoner name (which opens the SWAP / TRADE popup).
    li.appendChild(icon);

    // Champ name col is plain text again - lock/timer moved out.
    const nm = document.createElement("div");
    nm.className = "csv-team-cell-nm";
    nm.textContent = champNm;
    li.appendChild(nm);

    // Summoner col leads with the lock/timer (left-aligned at the col
    // start, which the JS aligner positions at "A of Allies"), then
    // the summoner name sits immediately to its right.
    const sm = document.createElement("div");
    sm.className = "csv-team-cell-summ";
    // summ is an LCU summoner display name (other-player-controlled) -
      // escape before it lands in innerHTML so a crafted name can't inject
      // markup (XSS). Escaping is a no-op for normal ASCII names.
      sm.innerHTML = lockHtml +
      `<span class="csv-team-cell-summ-text">${summ ? escHtml(summ.slice(0, 22)) : ""}</span>`;
    if (isAllyOther && peerCellId != null) {
      const summText = sm.querySelector(".csv-team-cell-summ-text");
      if (summText) {
        summText.classList.add("is-clickable");
        summText.addEventListener("click", (ev) => {
          ev.stopPropagation();
          _csvShowTradeChoice(peerCellId, summText, {
            champName: champNm,
            pickOrderLbl: _csvOrdinal(idx + 1) + " Pick",
            roleLbl: _csvShortRole(pos),
            showPickOrder: !!showPickOrder,
          });
        });
      }
    }
    li.appendChild(sm);

    if (pos && allowRole) {
      const posEl = document.createElement("span");
      posEl.className = "csv-team-cell-pos";
      posEl.textContent = _csvShortRole(pos);
      // Pos pip is now display-only - trades go through the popup.
      li.appendChild(posEl);
    }
    // s213 v2: enemy cells now carry a 2-piece comp identifier + role
    // confidence instead of the bare "(guess)" tag. Pulls tags from
    // /api/dictionary/champion-tags (DDragon info + curated CC/burst
    // sets). Confidence is derived from LCU state: 100% if locked,
    // 85% if assignedPosition is present but not committed, 50% if
    // LCU hasn't classified the cell yet. Renders BEFORE the role pip
    // in the cell so the visual reading order is: champ -> tags -> role.
    if (isEnemyList && cid && showGuess) {
      const champTags = championTags(champNm);
      if (champTags && Array.isArray(champTags.tags) && champTags.tags.length) {
        const tagsEl = document.createElement("span");
        tagsEl.className = "csv-team-cell-tags";
        tagsEl.innerHTML = champTags.tags.slice(0, 2)
          .map((t) => `<span class="csv-team-cell-tag csv-team-cell-tag--${t.toLowerCase()}">${t}</span>`)
          .join("");
        li.appendChild(tagsEl);
      }
      // Operator 2026-05-31: confidence pill removed (#1); the per-enemy
      // win-rate is the leading .csv-enemy-wr-slot (via
      // _csvInjectEnemyWinRates, #2), so the inline threat pill is dropped
      // too. Tags above stay.
    }
    list.appendChild(li);
  });
}

export function renderChampSelectView(lcu) {
  // Section may not exist yet on older cached HTML - bail out cleanly.
  const section = document.getElementById("view-champ-select");
  const grid = section && section.querySelector(".csv-grid");
  if (!grid) return;
  // s213: warm the DDragon item + rune description caches on first
  // mount so the first hover already has tooltip content ready.
  // Idempotent - subsequent calls are no-ops once cache is ready.
  preloadLolDescriptions();
  // s213 v2: warm champion-tags cache for the enemies-panel 2-piece
  // identifier + confidence pill.
  preloadChampionTags();
  if (!lcu || lcu.phase !== "ChampSelect") {
    _csvSetText("csv-sub", "waiting for champ-select...");
    return;
  }
  _csvCacheLcuIfChampSelect(lcu);
  if (!CHAMPS.ready) return;  // names not loaded yet - wait next tick

  const cs = lcu.champ_select || {};
  const mode = _csvDetectMode(cs);
  const myCid = (cs.my_champion | 0);
  const myName = _csChampName(myCid) || "-";
  const locked = !!cs.my_completed;

  // s209 v2: idempotent render gate. The state envelope re-fires every
  // 2s in live, and the sim FakeSocket tick re-fires every 3s - each
  // tick triggers a full renderChampSelectView which rebuilds three
  // panels worth of innerHTML. The operator saw the build chooser
  // flicker every ~3s on cold load. Skip the render when nothing
  // observable has changed since the last tick.
  const sig = _csvComputeSig(cs, mode, myCid, myName);
  if (section.dataset.csvSig === sig) return;
  section.dataset.csvSig = sig;

  // Stamp the section with data-cs-mode so CSS can branch (hide
  // pickban panel for non-SR, swap enemies/allies layout for Arena,
  // adjust grid template, etc).
  section.dataset.csMode = mode;

  // Sub-line: mode + queue + inner phase + timer.
  // s209: humanize the LCU phase enum ("BAN_PICK" -> "Ban & Pick",
  // "FINALIZATION" -> "Finalization", etc.). Raw shouty-snake-case
  // looked like a debug log line in the live sub-line.
  const bits = [];
  const modeLabel = { sr: "SR DRAFT", aram: "ARAM", arena: "ARENA" }[mode] || "";
  if (modeLabel) bits.push(modeLabel);
  if (cs.queue_id) bits.push(_csvQueueLabel(cs.queue_id));
  if (cs.phase) bits.push(_csvHumanPhase(cs.phase));
  if (cs.timer && cs.timer.remaining_ms != null) {
    bits.push(Math.max(0, Math.round(cs.timer.remaining_ms / 1000)) + "s");
  }
  _csvSetText("csv-sub", bits.join(" . ") || "-");

  // Cache absolute timer end timestamp on the cs object so re-renders
  // (every 2s state envelope) don't reset the countdown - important
  // for sim mode where the lcu envelope only fires once.
  let timerEndMs = 0;
  if (cs.timer && typeof cs.timer.remaining_ms === "number") {
    if (!cs.timer._end) cs.timer._end = Date.now() + cs.timer.remaining_ms;
    timerEndMs = cs.timer._end;
  }
  // Pick-order swap button shows only on modes where pick order is
  // structural (SR draft queues). ARAM/Arena don't have a meaningful
  // pick order - operator wanted the middle button hidden.
  const showPickOrder = !!cs.sr_draft;
  // Compute active-round set (cells currently banning or picking) so
  // _csvRenderTeam can stamp the pulsing border class on them.
  if (cs.active_round && Array.isArray(cs.active_round.cell_ids)) {
    _csvActiveRound = {
      type: cs.active_round.type === "ban" ? "ban" : "pick",
      cellSet: new Set(cs.active_round.cell_ids),
    };
  } else {
    _csvActiveRound = null;
  }

  // Allies render - Arena renders 3 cells (me + 2 teammates; s234/#89:
  // Arena is now 6 teams of 3, was 8x2); SR/ARAM render 5. ARAM also
  // suppresses the (guess) tag and role pip since there are no role
  // assignments to display.
  const allyOpts = (mode === "arena")
    ? { cellCount: 3, showGuess: false, allowRolePip: false }
    : (mode === "aram")
      ? { cellCount: 5, showGuess: false, allowRolePip: false }
      : { cellCount: 5, showGuess: true,  allowRolePip: true };
  _csvRenderTeam("csv-allies-list", cs.my_team, myCid, timerEndMs, showPickOrder, allyOpts);

  // Enemies render - Arena stacks the 5 other sub-teams vertically
  // (s234/#89: 6 teams of 3 total). SR keeps the 5-cell list with
  // (guess); ARAM renders 5 cells but suppresses (guess) + role pip.
  if (mode === "arena") {
    _csvRenderEnemiesArena(cs, timerEndMs);
  } else {
    const enemyOpts = (mode === "sr")
      ? { cellCount: 5, showGuess: true,  allowRolePip: true, withWinRate: true }
      : { cellCount: 5, showGuess: false, allowRolePip: false };
    _csvRenderTeam("csv-enemies-list", cs.their_team, myCid, timerEndMs, showPickOrder, enemyOpts);
  }

  _csvSetupTimerTick();
  _csvRenderCentralPane(cs, mode, myCid, myName, locked);
  // s210: render the new Suggestions panel (row 2 right). Has its own
  // fetch path for ban-suggestions; pick-order + DS items pull from
  // local state. SR-only - the panel is hidden on ARAM/Arena via CSS
  // (no bans, no pick order, no DS-engine concept of "next").
  if (mode === "sr") {
    _csvRenderSuggestions(cs, myCid, myName, mode);
  } else {
    _csvRenderSuggestionsNonSr(cs);
  }

  // Pick & Ban panel - SR-only. Other modes hide it via CSS rule
  // [data-cs-mode] but we skip the render entirely to save work and
  // keep the body empty (it's display:none anyway).
  if (mode === "sr") {
    _csvRenderPickBan(cs, myCid);
  } else {
    const body = document.getElementById("csv-pickban-body");
    if (body) body.innerHTML = "";
  }
  // _csvAlignAllies() disabled - JS measurement kept returning wrong
  // values; champname col width is hardcoded in CSS instead.
}

// ARAM/Arena ASSESSMENT card (R30, 2026-06-24 in-game review). The full
// SR _csvRenderSuggestions does draft-only work (ban suggestions, pick
// order, DS profile/knobs) that has no meaning without a draft, so non-SR
// modes get this lean subset instead of an empty card. counter-picks stays
// SR-DRAFT-only (you can't counter-draft in ARAM/Arena), but the team-
// damage lean (own roster AD/AP balance) and watch-their-cooldowns (enemy
// hard-CC timers) read off ANY roster - so they fill the right column with
// real pre-game intel. Both renderers self-fetch + self-hide off cs, so
// this is a thin dispatch. The bans / DS-items / pick-order sub-sections
// are display:none in non-SR (CSS); clear any stale "non-SR mode" stub.
function _csvRenderSuggestionsNonSr(cs) {
  const cp = document.getElementById("csv-sugg-counter-picks");
  if (cp) { cp.hidden = true; cp.innerHTML = ""; }
  _csvRenderTeamDamage(cs);
  _csvRenderCooldownWatch(cs);
  ["csv-sugg-bans-grid", "csv-sugg-items-body", "csv-sugg-pickorder-body"]
    .forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.innerHTML = "";
    });
}

// Renders the center column (My Pick + mode-specific extras). Rebuilds
// the .csv-card-mypick body each call so we can vary header + content
// per mode without leaving stale elements behind. SR/ARAM get a build
// chooser variant list; Arena gets the duo header + augments.
function _csvRenderCentralPane(cs, mode, myCid, myName, locked) {
  const card = document.querySelector("#view-champ-select .csv-card-mypick");
  if (!card) return;
  const head = card.querySelector(".csv-card-head");
  const body = card.querySelector(".csv-card-body");
  if (!head || !body) return;

  // R30 (2026-06-24): Arena no longer early-returns here. The DS archetype
  // picker (left column) + build chooser + ordered build all key off the
  // locked/hovered champion, so Arena flows through the shared setup below
  // and renders its duo+augments pane PLUS those builds at the body
  // assembly. Pre-R30 the early-return left the Arena left column stuck on
  // "waiting for champion pick..." and offered no build, despite the
  // fixture carrying my_champion + build_variants.

  head.textContent = "My Pick";
  const iconCls = myCid ? (locked ? "locked" : "hovering") : "empty";
  const iconUrl = _csChampImg(myCid);
  const iconHtml = (myCid && iconUrl)
    ? `<img src="${iconUrl}" alt="${myName}" onerror="this.style.display='none'">`
    : "?";
  const stateCls = myCid ? (locked ? "locked" : "hovering") : "";
  const stateTxt = locked ? "OK LOCKED" : (myCid ? "... HOVERING" : "no pick yet");

  // s171: lock button - shown only when a champion is hovered but not
  // yet locked. Click fires the LCU lock_pick command and surfaces the
  // result inline via lcuPollResult, mirroring the legacy overlay's
  // #cs-lock-btn (champ_select.js:818). Hidden after lock since there's
  // nothing left to do; LCU re-emits `my_completed=true` and the next
  // render re-renders without the button.
  const lockBtnHtml = (myCid && !locked)
    ? `<button class="csv-lock-btn" id="csv-lock-btn" data-cid="${myCid}">LOCK IN ${myName.toUpperCase()}</button>`
    : "";

  let extraHtml = "";
  if (mode === "aram") {
    // Trigger the deterministic comp-verdict fetch on every ARAM render;
    // it no-ops when already cached / inflight and re-fires the render via
    // _csvScheduleRender once the verdict lands (folded into the sig).
    _csvFetchCompVerdict(cs);
    extraHtml = _csvBenchHtml(cs);
  }
  // Phase 3 (s176): trigger an async fetch for the persisted pick so the
  // picker re-renders with overridden state once the server replies.
  // No-op if already cached / inflight. Renders synchronously below.
  if (myName) _csvFetchArchetype(myName);
  const archetypeHtml = _csvArchetypePickerHtml(myName);
  // Operator (2026-05-23 round 2): Allies panel re-used as the DS
  // Build Archetype slot. Render the picker into #csv-archetype-target
  // + wire its click handlers; the My Pick body below no longer
  // interpolates archetypeHtml.
  const archTarget = document.getElementById("csv-archetype-target");
  if (archTarget) {
    archTarget.innerHTML = archetypeHtml
      || '<div class="csv-empty">waiting for champion pick...</div>';
    _csvWireArchetypePicker(archTarget);
  }
  const variants = _csvBuildVariantsFor(myCid, myName, mode, cs);
  // Operator (2026-05-23) item 164: push ALL build variants to the LCU
  // client so the in-game item-shop "Recommended Items" dropdown carries
  // RC's curated builds during the match (not just at champ-select). The
  // agent's apply_item_sets_batch (lcu_agent.py L1031+) accepts a
  // list of sets + replaces by-uid (does NOT wipe other RC- sets), so
  // 4 variant sets coexist in the dropdown. Debounced via last-push key
  // so we only re-push when the variant set actually changes.
  _csvMaybePushBuildsToLCU(myName, mode, variants);
  // Operator (2026-05-23): summoner spell strip. Selection mirrors the
  // current default variant's summoners (first row); click pushes to
  // LCU via the set_summoner_spell agent route (slot 1 = D, slot 2 = F).
  // First click in a render cycle assigns D, next click assigns F, then
  // wraps. Mode-keyed list (SR vs ARAM) so Mark / Snowball (id 32) lands
  // in the ARAM strip.
  const _activeVariant = variants && variants[0];
  const _activeSpells = (_activeVariant && Array.isArray(_activeVariant.summoners))
    ? _activeVariant.summoners : (mode === "aram" ? [4, 32] : [4, 7]);
  _csvSpellPair[0] = _activeSpells[0] | 0;
  _csvSpellPair[1] = _activeSpells[1] | 0;
  const summSpellHtml = _csvSummSpellStripHtml(_csvSpellPair, mode);
  const buildsTitle = mode === "aram" ? "ARAM build chooser"
                    : mode === "arena" ? "Arena build chooser"
                    : "SR build chooser";
  // Item 240 part-3 (3d): header control on the chooser title - one
  // small [PUSH] button + 3 inline checkboxes (Runes / Spells / Build),
  // right-aligned to the title. Checkbox states are GLOBAL + persisted;
  // default first-run all-unchecked (opt-in). The state is read live so
  // the boxes render checked on a re-render after the operator marked
  // them in a prior champ-select.
  const _pushFlags = _csvGetPushFlags();
  const _pushCtrlHtml = `
      <div class="csv-builds-push-ctrl">
        <button type="button" class="csv-builds-push-btn" id="csv-builds-push-btn"
                title="Push all checked categories to the client now">PUSH</button>
        ${_CSV_PUSH_CATS.map((cat) => {
          const label = cat.charAt(0).toUpperCase() + cat.slice(1);
          return `<label class="csv-builds-push-cat">
            <input type="checkbox" class="csv-builds-push-cb" data-push-cat="${cat}"${_pushFlags[cat] ? " checked" : ""}>
            <span>${label}</span>
          </label>`;
        }).join("")}
      </div>`;
  const _savedSel = _csvSavedSelection(myName);
  const buildsHtml = `
    <div class="csv-builds" data-champion="${myName || ""}" data-mode="${mode || "sr"}">
      <div class="csv-builds-head">
        <div class="csv-builds-title">${buildsTitle}</div>
        ${_pushCtrlHtml}
      </div>
      <div class="csv-builds-body" id="csv-builds-body">
        ${_csvBuildVariantRowsHtml(variants, _savedSel.variantKey, _savedSel.runeKey)}
      </div>
    </div>`;
  // Build Order (2026-05-17, plan S6b option B): contextual DS-backed
  // ordered build with the engine-enforced unique-passive no-double
  // rule. Sits under the build chooser in the mode-agnostic My Pick
  // card (matters in ARAM/Arena too - unlike the SR-only Suggestions
  // panel). The async fetch is cache-keyed (one engine round per
  // champ+mode+arch per session) and its re-render piggybacks on
  // _csvScheduleRender, exactly like the DS-builds fetch.
  const _boArch = (_csvResolveArchetype(myName) || {}).key || "";
  // item 213 (2026-05-28): resolve the LIVE enemy comp (numeric LCU
  // championIds -> DDragon slugs) so the DS-vs-enemy-comp build re-ranks
  // + re-fetches whenever an enemy locks / swaps. resolveChampNames is
  // the same helper the CC cards use; empty during early CS (the build
  // plans vs the zero-baseline until enemies lock).
  const _boEnemyIds = cs
    ? ((cs.their_team || []).map((p) => (p && (p.championId | 0)) || 0)
        .filter((x) => x > 0))
    : [];
  const _boEnemyNames = resolveChampNames(_boEnemyIds);
  const boHtml = buildOrderCardHtml(myName, _csvDsModeFor(mode), _boArch, {
    ver: (ITEMS && ITEMS.version) || "latest",
    scheduleRender: _csvScheduleRender,
    enemies: _boEnemyNames,
  });

  // R30 (2026-06-24): Arena pane = duo + augments, then the shared build
  // chooser + ordered build (the archetype picker already rendered into the
  // left column above). Returns before the SR/ARAM single-portrait body.
  if (mode === "arena") {
    head.textContent = "My Duo + Augments";
    body.className = "csv-card-body";
    body.innerHTML = _csvArenaPaneHtml(cs, myCid, myName) + buildsHtml + boHtml;
    _csvWireArenaAugments(body, cs);
    _csvWireBuildVariants(body);
    return;
  }

  // s214 v2: LOCKED state sits to the LEFT of the champion icon now
  // (per operator follow-up). Pre-s214v2 it was centered below; pre-
  // s214 it was inline-right inside .csv-mypick-text. New layout:
  //   [LOCKED state] [icon] [name]
  // The state column is fixed-width so the icon stays in roughly the
  // same X position whether locked / hovering / empty.
  body.className = "csv-card-body csv-mypick";
  body.innerHTML = `
    <div class="csv-mypick-portrait-row">
      <div class="csv-mypick-state ${stateCls}" id="csv-mypick-state">${stateTxt}</div>
      <div class="csv-mypick-icon ${iconCls}" id="csv-mypick-icon">${iconHtml}</div>
      <div class="csv-mypick-text">
        <div class="csv-mypick-name" id="csv-mypick-name">${myName}</div>
      </div>
    </div>
    ${lockBtnHtml}
    ${extraHtml}
    ${summSpellHtml}
    ${buildsHtml}
    ${boHtml}
    <div class="csv-sugg-section cc-blended-ehp-threat" id="csv-sugg-cc-blended-ehp-threat" data-cc-tier="warn" hidden></div>
    <div class="csv-sugg-section cc-conditional-pressure" id="csv-sugg-cc-conditional-pressure" data-cc-cond-tier="warn" hidden></div>
    <div class="csv-sugg-section capability-gap" id="csv-sugg-capability-gap" hidden></div>`;
  // Wire click handlers on the summoner-spell strip (idempotent - body
  // innerHTML rebuild on each render attaches fresh handlers). Click N=1
  // fills the D slot, click N=2 fills the F slot, then wraps. Skips
  // when the clicked spell would duplicate the other slot.
  body.querySelectorAll(".csv-summspell-cell").forEach((cell) => {
    cell.addEventListener("click", () => {
      const sid = parseInt(cell.dataset.spellId, 10) | 0;
      if (!sid) return;
      const otherIdx = _csvNextSpellSlot === 1 ? 1 : 0;
      if (sid === _csvSpellPair[otherIdx]) return;
      const usedSlot = _csvNextSpellSlot;
      _csvSpellPair[usedSlot - 1] = sid;
      _csvNextSpellSlot = usedSlot === 1 ? 2 : 1;
      _csvRefreshSpellBadges(body);
      try { lcuCmd({ cmd: "set_summoner_spell", slot: usedSlot, spellId: sid }); } catch (_) {}
    });
  });

  // Wire bench cells to fire bench_swap on click. Only ARAM renders
  // the bench block; the wiring is idempotent under re-render since
  // we replace innerHTML and re-attach each tick.
  if (mode === "aram") _csvWireBench(body);
  _csvWireBuildVariants(body);
  _csvWireLockButton(body);
  // Operator (2026-05-23 round 2): archetype picker wired against
  // #csv-archetype-target (Allies grid-area), not the My Pick body.
}

// s210: Suggestions panel renderer (row 2 right).
//   Row 1 (header)         -> static "Suggestions" from .csv-card-head
//   Row 2 (bans grid)      -> 4 cards, top globally-banned, filtered by
//                            already-banned from either team
//   Row 3 (pick order)     -> static lane-based advisory for the operator's
//                            assigned role (jungle picks 2nd-last, ADC
//                            picks last, etc.). Future: dynamic based on
//                            counter-pick implications.
//   Row 4 (DS items)       -> DS engine top-6 for the operator's champion;
//                            mirrors what the build chooser used to show
//                            as the "DS engine top picks" pseudo-row.
// RC2 E4: ban-phase-complete detector. True once the draft has moved off
// the ban rounds into picks/finalization, so the banned-champions display
// can collapse out of the operator's pick-window eyeline.
//
// LCU ground truth (tools/lcu_agent.py): cs.phase = sess.timer.phase
// (PLANNING -> BAN_PICK -> FINALIZATION); cs.active_round.type is "ban"
// while a ban round is on the clock and flips to "pick" once picks begin
// (lcu_agent.py:491 _active_round). So ban phase is DONE when the
// active round is a pick round, OR the phase has advanced past BAN_PICK /
// PLANNING (e.g. FINALIZATION). No-bans draft modes (Blind 430 / Quickplay
// 490) never enter a ban round, so they read as complete the moment picks
// start - correct: there is no ban display to keep open.
function _csvBanPhaseComplete(cs) {
  if (!cs) return false;
  if (cs.active_round && cs.active_round.type === "pick") return true;
  if (cs.phase && cs.phase !== "BAN_PICK" && cs.phase !== "PLANNING") return true;
  return false;
}

function _csvRenderSuggestions(cs, myCid, myName, mode) {
  // ---- Row 2: bans block ----
  // Phase-aware: during the ban phase show 4 suggested bans for the
  // operator to commit; once active_round.type === "pick" (bans
  // committed, picks underway) switch to a 2-row 5-cell grid showing
  // ally bans (top) + enemy bans (bottom).
  // s214: title row dropped - `.csv-sugg-row-label` no longer in the
  // DOM. The grid alone communicates state via the ALLY / ENEMY side
  // labels in the banned-list rows + the icon strip in suggestion mode.
  const bansGrid = document.getElementById("csv-sugg-bans-grid");
  if (bansGrid) {
    const allyBans  = (cs.bans && Array.isArray(cs.bans.my_team)) ? cs.bans.my_team : [];
    const enemyBans = (cs.bans && Array.isArray(cs.bans.their_team)) ? cs.bans.their_team : [];
    // RC2 E4: ban-phase-complete is the single detection helper now, so the
    // collapse decision below shares the exact same condition.
    const isPickPhase = _csvBanPhaseComplete(cs);
    if (isPickPhase && (allyBans.length || enemyBans.length)) {
      bansGrid.classList.add("is-banned-grid");
      bansGrid.classList.remove("is-suggestions-grid");
      // RC2 E4 (operator-reported): once the ban phase is DONE the banned
      // list no longer needs full vertical space during the pick window.
      // Collapse it to a compact summary line via the is-collapsed class
      // (CSS shrinks the 2x5 icon grid to a single quiet count line); a
      // click on the header toggles it back open if the operator wants
      // the full grid. State persists across re-renders via _csvBansOpen.
      bansGrid.classList.add("is-collapsed");
      if (_csvBansOpen) bansGrid.classList.remove("is-collapsed");
      bansGrid.innerHTML = _csvBannedCollapseHeader(allyBans, enemyBans)
                         + _csvBannedListRow(allyBans, "ALLY")
                         + _csvBannedListRow(enemyBans, "ENEMY");
      const hdr = bansGrid.querySelector(".csv-sugg-banned-toggle");
      if (hdr) {
        hdr.addEventListener("click", () => {
          _csvBansOpen = !_csvBansOpen;
          bansGrid.classList.toggle("is-collapsed", !_csvBansOpen);
          const caret = hdr.querySelector(".csv-sugg-banned-caret");
          if (caret) caret.textContent = _csvBansOpen ? "[-]" : "[+]";
        });
      }
    } else {
      bansGrid.classList.add("is-suggestions-grid");
      bansGrid.classList.remove("is-banned-grid");
      bansGrid.classList.remove("is-collapsed");
      // Collect already-banned ids so the suggestion fetch can skip them.
      const banned = new Set();
      allyBans.forEach((id) => banned.add(id | 0));
      enemyBans.forEach((id) => banned.add(id | 0));
      const excludedIds = Array.from(banned).filter((x) => x > 0);
      _csvFetchBanSuggestions(excludedIds);
      const cached = _CSV_BANSUGG_CACHE[_csvBanSuggKey(excludedIds)];
      if (cached && Array.isArray(cached.suggestions) && cached.suggestions.length) {
        bansGrid.innerHTML = cached.suggestions.map((s) => {
          const isBanned = banned.has(s.champId);
          // OQ9 (QA26 remainder): why-banned sub-label. `rank` is the
          // champion's 1-based position in the meta top_bans list
          // (routes_ban_suggestions.py, additive field) - honest "it's
          // a top global ban" signal. Older cached payloads without
          // rank render name-only as before.
          const rank = s.rank | 0;
          const reasonHtml = rank > 0
            ? `<div class="csv-sugg-ban-reason">meta ban #${rank}</div>` : "";
          const whyTitle = rank > 0
            ? `Suggest ban: ${s.name} - global top ban #${rank} (patch ${cached.patch || "?"})`
            : `Suggest ban: ${s.name}`;
          return `
            <div class="csv-sugg-ban-card${isBanned ? " is-banned" : ""}"
                 data-champ-id="${s.champId}"
                 title="${isBanned ? `${s.name} already banned` : whyTitle}">
              <div class="csv-sugg-ban-icon">
                <img src="${s.icon}" alt="${s.name}" onerror="this.style.display='none'">
              </div>
              <div class="csv-sugg-ban-name">${s.name}</div>
              ${reasonHtml}
            </div>`;
        }).join("");
        bansGrid.querySelectorAll(".csv-sugg-ban-card:not(.is-banned)").forEach((card) => {
          card.addEventListener("click", () => {
            const cid = parseInt(card.dataset.champId, 10) | 0;
            if (cid > 0) lcuCmd({ cmd: "set_ban_intent", championId: cid });
          });
        });
      } else {
        bansGrid.innerHTML = '<div class="csv-sugg-empty">loading global top bans...</div>';
      }
      // 2026-05-20 (item 109 carry-forward): HURTS-THEM / HELPS-US
      // toggle. Renders the dual-score ban-suggest backend ship
      // 6e7b7e5 inline above the legacy global-top-bans grid. Uses
      // the same global-top-bans candidate pool (cached) - dual-
      // scores each candidate vs the operator's current ally + enemy
      // roster, then renders a sortable list. The mode chip is
      // visible the moment the cached candidate list lands.
      _csvRenderBanSuggestToggle(cs, cached);
    }
  }
  // RC2 E4 (P2): live counter-picks vs the enemy comp. Glanceable
  // "pick into this comp" list for the operator's open slot, driven by
  // the existing counters index via /api/champ-select/counter-picks.
  _csvRenderCounterPicks(cs);
  // LIFT 1b (2026-06-22): ally team AD/AP damage-lean meter. Glanceable
  // physical-vs-magic bar for the operator's own team, summed from DDragon
  // info.attack/info.magic via /api/champ-select/team-damage-mix.
  _csvRenderTeamDamage(cs);
  // 2026-05-22 (item 139 carry (a)): FIRST dashboard UI consumer of
  // cc_blended_ehp. Renders the ally-vs-enemy CC-blended EHP balance
  // chip beside the legacy bans grid so the operator can see at a
  // glance whether enemy CC threatens to erode their team faster
  // than ally CC erodes the enemy team.
  _csvRenderCcBlendedEhpThreat(cs);
  // 2026-05-22 (item 144): FIRST dashboard UI consumer of cc_conditional
  // (5th overall consumer of the cc_conditional ecosystem). Sibling
  // chip to cc-blended-ehp-threat; surfaces the probability-weighted
  // CONDITIONAL CC seconds totals so the operator can see at a glance
  // whether enemy conditional CC threatens to land more lockdown than
  // ally conditional CC will land on enemies.
  _csvRenderCcConditionalPressure(cs);
  // 2026-05-30 (item 218 / competitor lift #5): matchup cooldown-watch.
  // Per enemy champion, the single highest-threat hard-CC ability + its
  // max-rank base cooldown ("watch their hook - 16s"). Joins the CC threat
  // registries to per-rank ability cooldowns from champion_abilities.json.
  _csvRenderCooldownWatch(cs);
  // 2026-06-26 (item 633): L4 Phase-D capability-gap surface. For the
  // operator's OWN locked champion vs the live enemy roster, the single
  // highest-severity capability DEFICIT (anti-tank / anti-heal / anti-poke)
  // from core.ds_capability_gap, surfaced behind the backend default-OFF
  // RC_CAPGAP_SURFACE flag - the chip stays hidden until the flag is ON
  // (the route returns capability_gap=null otherwise), so this is inert by
  // default. Mirrors the my-champion + enemy-roster resolution of
  // _csvRenderPersonalBuild + _csvRenderCooldownWatch.
  _csvRenderCapabilityGap(cs);
  // 2026-06-25: personal best-build card. For the operator's OWN locked
  // champion (cs.my_champion), the completed items they win with from their
  // rewind_history.db - a "your best build" read alongside the DS engine
  // recommendation. Hidden until a champion locks. Read-only.
  _csvRenderPersonalBuild(cs);
  // CS1 (2026-06-08): ally CC-pairing card. Surfaces, for the operator's
  // OWN roster, which conditional CC entries a TEAMMATE can set up + the
  // plausible enablers. Read-only join over the existing cc_conditional
  // registry. Delimited CS1 block (CS3 will also touch this file).
  _csvRenderCcPairing(cs);
  // CS3 (2026-06-08): ds-sweep / ds-matchup / ds-combo / ds-relscore render
  // calls moved to active_match.js (they read the live champion mid-game).
  // ds-profile / ds-knobs / ds-statcheck stay on champ-select for the pick.
  setDsProfileScheduler(_csvScheduleRender);
  renderDsProfileForChampSelect(cs);
  setDsSkillOrderScheduler(_csvScheduleRender);
  renderDsSkillOrderForChampSelect(cs);
  // GPI radar is history-based (not champ-select-state-driven) so it ignores cs;
  // the server + client caches make the per-tick re-show idempotent + cheap.
  showPlayerGpi("sr");
  { const _dskBlock = document.getElementById("csv-ds-knobs");
    if (_dskBlock) renderDsKnobs(_dskBlock, cs); }
  { const _dssBlock = document.getElementById("csv-ds-statcheck");
    if (_dssBlock) renderDsStatcheck(_dssBlock, cs); }
  // ---- Row 3: pick-order tips (no header label per s213 v3) ----
  // Static advisory keyed on operator's assigned role. 3 tips per role
  // - the third row is the "consider" / strategic depth tip beyond
  // basic "pick after / pick first" logic.
  const pickOrderBody = document.getElementById("csv-sugg-pickorder-body");
  if (pickOrderBody) {
    const role = _csvResolveRole(cs);
    const tips = (_CSV_PICKORDER_TIPS[role] || _CSV_PICKORDER_TIPS.DEFAULT).slice();
    // s214: swap row 3 for a comp-aware tip once at least one ally lock
    // or enemy commit is visible. Static role tip is preserved as the
    // fallback when comp data is too thin to derive signal.
    const compTip = _csvCompAwareTip(cs, role);
    if (compTip) tips[2] = compTip;
    pickOrderBody.innerHTML = tips.map((tip, idx) => `
      <div class="csv-sugg-pickorder-cell">
        <span class="csv-sugg-pickorder-idx">${idx + 1}</span>
        <span>${tip}</span>
      </div>`).join("");
  }
  // s211: DS engine item output row removed - the Experimental build
  // chooser row now carries DS top picks in a richer rune+spell+item
  // layout, making the duplicate strip here visual noise.
}

// s213 v3: helper - render a single-row 5-cell banned-list strip for
// the Suggestions panel's post-ban-phase view. Banned ids come from
// LCU's cs.bans.my_team / cs.bans.their_team arrays. Pads to 5 cells
// with placeholder slots when fewer than 5 bans are committed (Riot
// draft modes vary: 3 bans/side classic, 5 bans/side ranked).
function _csvBannedListRow(banIds, sideLabel) {
  const cells = [];
  for (let i = 0; i < 5; i++) {
    const cid = banIds[i] | 0;
    if (cid > 0) {
      const champ = (CHAMPS && CHAMPS.byId && CHAMPS.byId[String(cid)]) || `cid:${cid}`;
      const img = _csChampImg(cid);
      cells.push(`
        <div class="csv-sugg-ban-card is-banned" data-champ-id="${cid}" title="${champ} banned">
          <div class="csv-sugg-ban-icon">
            ${img ? `<img src="${img}" alt="${champ}" onerror="this.style.display='none'">` : ""}
          </div>
          <div class="csv-sugg-ban-name">${champ}</div>
        </div>`);
    } else {
      cells.push(`
        <div class="csv-sugg-ban-card is-empty">
          <div class="csv-sugg-ban-icon"></div>
          <div class="csv-sugg-ban-name">-</div>
        </div>`);
    }
  }
  return `<div class="csv-sugg-banned-row"
               data-side="${sideLabel.toLowerCase()}">
            <span class="csv-sugg-banned-side">${sideLabel}</span>
            <div class="csv-sugg-banned-cells">${cells.join("")}</div>
          </div>`;
}

// RC2 E4: collapse-state for the post-ban-phase banned-champions display.
// Default collapsed (false) so the pick window isn't dominated by a 2x5
// icon grid the operator has already seen during bans; the header toggle
// re-opens it. Module-level so it survives the per-tick innerHTML rebuild.
let _csvBansOpen = false;

// RC2 E4: compact header for the collapsed banned display. Shows a count
// ("BANS - 8 banned") + a [+]/[-] caret; the whole strip is the click
// target that toggles _csvBansOpen. When expanded (is-collapsed removed)
// the 2x5 grid below it shows; when collapsed only this line is visible.
function _csvBannedCollapseHeader(allyBans, enemyBans) {
  const n = ((allyBans || []).filter((x) => (x | 0) > 0).length)
          + ((enemyBans || []).filter((x) => (x | 0) > 0).length);
  const caret = _csvBansOpen ? "[-]" : "[+]";
  return `<div class="csv-sugg-banned-toggle" role="button" tabindex="0"
               title="Show / hide the full banned-champions grid">
            <span class="csv-sugg-banned-toggle-label">BANS</span>
            <span class="csv-sugg-banned-toggle-count">${n} banned</span>
            <span class="csv-sugg-banned-caret">${caret}</span>
          </div>`;
}

// RC2 E4 (P2): live counter-picks vs the enemy comp. The single-decision
// "pick into this comp" prompt that wins the short pick window. Resolves
// the live enemy ids off the session, excludes everything already on the
// board (ally picks + ally/enemy bans + the operator's own hover), fetches
// the aggregated counters from /api/champ-select/counter-picks, and renders
// a glanceable top-5 list.
const _CSV_COUNTER_CACHE = {};   // {key: {data, fetchedAt}}
const _CSV_COUNTER_INFLIGHT = {};
const _CSV_COUNTER_TTL_MS = 30_000;

function _csvFetchCounterPicks(role, enemyIds, excludeIds, onLoad) {
  const e = (enemyIds || []).filter((x) => (x | 0) > 0).slice().sort((a, b) => a - b);
  const x = (excludeIds || []).filter((v) => (v | 0) > 0).slice().sort((a, b) => a - b);
  if (!e.length) return null;
  const key = [role || "-", `e:${e.join(",")}`, `x:${x.join(",")}`].join("|");
  const now = Date.now();
  const cached = _CSV_COUNTER_CACHE[key];
  if (cached && (now - cached.fetchedAt) < _CSV_COUNTER_TTL_MS) return cached.data;
  if (_CSV_COUNTER_INFLIGHT[key]) return cached ? cached.data : null;
  _CSV_COUNTER_INFLIGHT[key] = true;
  let url = "/api/champ-select/counter-picks?top=5"
          + `&enemies=${encodeURIComponent(e.join(","))}`;
  if (role && role !== "-") url += `&role=${encodeURIComponent(role)}`;
  if (x.length) url += `&exclude=${encodeURIComponent(x.join(","))}`;
  fetch(url)
    .then((r) => r.ok ? r.json() : null)
    .then((j) => {
      _CSV_COUNTER_INFLIGHT[key] = false;
      if (j && j.ok) {
        _CSV_COUNTER_CACHE[key] = { data: j, fetchedAt: Date.now() };
        if (typeof onLoad === "function") onLoad();
      }
    })
    .catch(() => { _CSV_COUNTER_INFLIGHT[key] = false; });
  return cached ? cached.data : null;
}

// Indirection so the render path can be driven by a stubbed fetch in the
// snapshot harness (see the ui_mock test hook at the bottom of the file).
// In production this is always the real _csvFetchCounterPicks.
let _csvCounterFetch = _csvFetchCounterPicks;

// LIFT 1b (2026-06-22): ally team AD/AP damage-lean fetch. Mirrors the
// counter-picks fetch (30s TTL cache keyed on the SORTED ally ids, in-flight
// guard, synchronous cached-return). Drives /api/champ-select/team-damage-mix.
const _CSV_TDMG_CACHE = {};   // {key: {data, fetchedAt}}
const _CSV_TDMG_INFLIGHT = {};
const _CSV_TDMG_TTL_MS = 30_000;

function _csvFetchTeamDamage(teamIds, onLoad) {
  const t = (teamIds || []).filter((x) => (x | 0) > 0).slice().sort((a, b) => a - b);
  if (!t.length) return null;
  const key = `t:${t.join(",")}`;
  const now = Date.now();
  const cached = _CSV_TDMG_CACHE[key];
  if (cached && (now - cached.fetchedAt) < _CSV_TDMG_TTL_MS) return cached.data;
  if (_CSV_TDMG_INFLIGHT[key]) return cached ? cached.data : null;
  _CSV_TDMG_INFLIGHT[key] = true;
  const url = "/api/champ-select/team-damage-mix?team_ids="
            + encodeURIComponent(t.join(","));
  fetch(url)
    .then((r) => r.ok ? r.json() : null)
    .then((j) => {
      _CSV_TDMG_INFLIGHT[key] = false;
      if (j && j.ok) {
        _CSV_TDMG_CACHE[key] = { data: j, fetchedAt: Date.now() };
        if (typeof onLoad === "function") onLoad();
      }
    })
    .catch(() => { _CSV_TDMG_INFLIGHT[key] = false; });
  return cached ? cached.data : null;
}

// Same indirection pattern as _csvCounterFetch so the snapshot harness can
// swap in a stubbed fetch (see the ui_mock test hook at the bottom).
let _csvTeamDamageFetch = _csvFetchTeamDamage;

function _csvRenderTeamDamage(cs) {
  const box = document.getElementById("csv-sugg-team-damage");
  if (!box) return;
  // The operator's OWN team (ally locked picks + the operator's hover).
  const allyIds = (cs && cs.my_team || [])
    .map((p) => (p && (p.championId | 0)) || 0)
    .filter((x) => x > 0);
  if (!allyIds.length) {
    box.hidden = true;
    box.innerHTML = "";
    return;
  }
  box.hidden = false;
  const data = _csvTeamDamageFetch(allyIds, _csvScheduleRender);
  if (!data || !data.ok || (data.n_champs | 0) <= 0) {
    // Quiet placeholder while the first fetch lands (or zero known champs).
    box.innerHTML = `<div class="csv-tdmg-head">TEAM DAMAGE LEAN</div>`
                  + `<div class="csv-sugg-empty">reading team damage profile...</div>`;
    return;
  }
  const adPct = data.physical_pct | 0;
  const apPct = data.magical_pct | 0;
  // Dual-color bar: AD (warm) segment on the left, AP (cyan) on the right.
  // The text label below carries the meaning (glyphs, not color alone).
  box.innerHTML =
      `<div class="csv-tdmg-head">TEAM DAMAGE LEAN</div>`
    + `<div class="csv-tdmg-bar" role="img"`
    + ` aria-label="AD ${adPct} percent, AP ${apPct} percent">`
    + `<div class="csv-tdmg-seg-ad" style="width:${adPct}%"></div>`
    + `<div class="csv-tdmg-seg-ap" style="width:${apPct}%"></div>`
    + `</div>`
    + `<div class="csv-tdmg-label">`
    + `<span class="csv-tdmg-ad">AD <b>${adPct}%</b></span>`
    + `<span class="csv-tdmg-sep"> . </span>`
    + `<span class="csv-tdmg-ap">AP <b>${apPct}%</b></span>`
    + `</div>`;
}

function _csvRenderCounterPicks(cs) {
  const box = document.getElementById("csv-sugg-counter-picks");
  if (!box) return;
  // Live enemy comp (numeric LCU championIds) off the session, same
  // resolution the build-order card uses (champ_select.js enemy ids).
  const enemyIds = (cs && cs.their_team || [])
    .map((p) => (p && (p.championId | 0)) || 0)
    .filter((x) => x > 0);
  if (!enemyIds.length) {
    box.hidden = true;
    box.innerHTML = "";
    return;
  }
  // Exclude everything already off the table: ally locked picks, the
  // operator's own hover, and both sides' bans - so we never recommend a
  // champ that can't be picked.
  const excl = new Set();
  (cs.my_team || []).forEach((p) => { if (p && (p.championId | 0) > 0) excl.add(p.championId | 0); });
  ((cs.bans && cs.bans.my_team) || []).forEach((id) => excl.add(id | 0));
  ((cs.bans && cs.bans.their_team) || []).forEach((id) => excl.add(id | 0));
  const excludeIds = Array.from(excl).filter((x) => x > 0);
  const role = _csvResolveRole(cs);
  const data = _csvCounterFetch(role, enemyIds, excludeIds, _csvScheduleRender);
  const counters = (data && Array.isArray(data.counters)) ? data.counters : [];
  if (!counters.length) {
    // Keep the panel visible with a quiet placeholder while the first
    // fetch lands (or when the enemy comp has no known counters yet).
    box.hidden = false;
    box.innerHTML = `<div class="csv-counter-head">PICK INTO THIS COMP</div>`
                  + `<div class="csv-sugg-empty">no counter data for this comp yet</div>`;
    return;
  }
  box.hidden = false;
  // LIFT 1a (2026-06-22): elevate counters[0] into a single large HERO
  // card (the dominant decision element) and demote counters[1..4] to a
  // compact secondary list. Every clickable entry - hero + each secondary
  // row - still hovers on the operator's pick action via set_pick_intent.
  const top = counters[0] || null;
  const rest = counters.slice(1, 5);

  let heroHtml = "";
  if (top) {
    const hid = top.champId | 0;
    const himg = _csChampImg(hid);
    const hname = String(top.name || (hid ? "cid:" + hid : "?"));
    const hnote = String(top.note || "");
    const hClick = hid > 0;
    heroHtml = `
      <div class="csv-counter-hero${hClick ? " is-clickable" : ""}"
           data-champ-id="${hid}"
           title="Hover ${hname} - ${hnote}">
        <div class="csv-counter-hero-icon">
          ${himg ? `<img src="${himg}" alt="${hname}" onerror="this.style.display='none'">` : ""}
        </div>
        <div class="csv-counter-hero-text">
          <span class="csv-counter-hero-tag">BEST PICK</span>
          <span class="csv-counter-hero-name">${hname}</span>
          <span class="csv-counter-hero-note">${hnote}</span>
        </div>
      </div>`;
  }

  const rows = rest.map((c) => {
    const cid = c.champId | 0;
    const img = _csChampImg(cid);
    const name = String(c.name || (cid ? "cid:" + cid : "?"));
    const note = String(c.note || "");
    const isClickable = cid > 0;
    return `
      <div class="csv-counter-pick${isClickable ? " is-clickable" : ""}"
           data-champ-id="${cid}"
           title="Hover ${name} - ${note}">
        <div class="csv-counter-icon">
          ${img ? `<img src="${img}" alt="${name}" onerror="this.style.display='none'">` : ""}
        </div>
        <div class="csv-counter-text">
          <span class="csv-counter-name">${name}</span>
          <span class="csv-counter-note">${note}</span>
        </div>
      </div>`;
  }).join("");
  const secondaryHtml = rows
    ? `<div class="csv-counter-secondary">${rows}</div>`
    : "";
  box.innerHTML = `<div class="csv-counter-head">PICK INTO THIS COMP</div>`
                + heroHtml
                + secondaryHtml;
  // Click any counter (hero OR secondary row) -> hover it on the
  // operator's pick action (same set_pick_intent path the Pick & Ban
  // cells use). Skips empty ids.
  box.querySelectorAll(".csv-counter-hero.is-clickable, .csv-counter-pick.is-clickable").forEach((el) => {
    el.addEventListener("click", () => {
      const cid = parseInt(el.dataset.champId, 10) | 0;
      if (cid > 0) { try { lcuCmd({ cmd: "set_pick_intent", championId: cid }); } catch (_) {} }
    });
  });
}

// s211: variant key -> badge CSS class. Each known variant gets a
// distinct hue so the operator can read the row identity at a glance
// without a separate trailing tag. Unknown variant keys fall through
// to a neutral grey pill.
// item 213 (2026-05-28): the synthetic "experimental" row was removed
// from every champion + mode; its amber badge branch is gone with it.
function _csvVariantBadgeClass(v) {
  const key = (v.key || "").toLowerCase();
  if (key.startsWith("userbuild_")) return "csv-build-badge csv-build-badge-user";
  if (key === "on-hit" || key === "onhit")  return "csv-build-badge csv-build-badge-onhit";
  if (key === "crit")                       return "csv-build-badge csv-build-badge-crit";
  if (key === "ap-burst" || key === "ap")   return "csv-build-badge csv-build-badge-ap";
  if (key === "tank" || key === "bruiser")  return "csv-build-badge csv-build-badge-tank";
  if (key === "lethality" || key.includes("lethality")
      || key === "lethality-poke")          return "csv-build-badge csv-build-badge-lethality";
  if (key === "adc-crit")                   return "csv-build-badge csv-build-badge-crit";
  if (key.startsWith("support") || key === "enchanter")
                                            return "csv-build-badge csv-build-badge-support";
  return "csv-build-badge csv-build-badge-default";
}

// item 213 (2026-05-28): the auto-build chooser row was removed, so
// its per-archetype default rune table + lookup helper are gone too.

// s210: pick-order advisory blurbs per role. Short tips, ordered from
// "what to do first" to "what to do at lock-in". s214: row 3 is now
// dynamically swapped for a comp-aware tip when ally + enemy comps
// have enough locks to read - see _csvCompAwareTip below. Rows 1+2
// stay static so the operator always sees the role's "pick order"
// constants regardless of comp readability.
const _CSV_PICKORDER_TIPS = {
  TOP: [
    "Counterpick - wait for enemy top lock",
    "Then commit to your matchup pick",
    "Watch enemy jungler - a gank-heavy comp punishes weak-early lane picks",
  ],
  JNG: [
    "Pick early - clear path matters more than counter",
    "Avoid blind-picking weak-early junglers",
    "Match enemy team's tempo - vs poke comp pick gank, vs engage pick disengage",
  ],
  MID: [
    "Flex picks have leverage - hover late",
    "Lock when enemy team comp is readable",
    "Save assassins for after enemy ADC + sup lock so you confirm dive targets",
  ],
  BOT: [
    "Pick after support locks - synergy > counter",
    "Lethality vs squishy comps, crit vs draft",
    "Hard-CC enemy support? Hover Cleanse before lock-in",
  ],
  SUP: [
    "Lock support pick first - your ADC counts on it",
    "Engage vs poke comp; peel vs assassin comp",
    "Vision-heavy supports (Bard, Senna) scale with map awareness - pair carefully",
  ],
  DEFAULT: [
    "Watch enemy hovers before locking",
    "Comfort > counterpick if matchup is unclear",
    "Hover your pick to telegraph intent - see if enemy adapts before you commit",
  ],
};

// s214: derive a comp-aware tip from the locked allies + enemies tag
// distribution. Returns null when neither side has any locks (early
// CS) so the caller falls through to the static row-3 tip. Uses the
// championTags cache (DDragon Fighter/Mage/Marksman/Tank/Support/
// Assassin classifications) - same source the enemy-row tag chips
// + adaptive-summoner classifier read from.
function _csvCompAwareTip(cs, role) {
  if (!cs || !championTags) return null;
  const tagOf = (cid) => {
    if (!cid) return [];
    const t = championTags(cid);
    return Array.isArray(t) ? t : [];
  };
  const allyIds = (cs.my_team || [])
    .filter((p) => p && p.completed && p.championId)
    .map((p) => p.championId | 0);
  const enemyIds = (cs.their_team || [])
    .filter((p) => p && p.championId)
    .map((p) => p.championId | 0);
  // Need at least 1 locked ally + 1 enemy commit for the tip to have
  // signal. Pre-lock state: caller fall-through to static tip.
  if (!allyIds.length && !enemyIds.length) return null;
  const tagCount = (ids) => {
    const c = { Fighter: 0, Mage: 0, Marksman: 0, Tank: 0, Support: 0, Assassin: 0 };
    ids.forEach((cid) => tagOf(cid).forEach((t) => { if (c[t] != null) c[t] += 1; }));
    return c;
  };
  const ally = tagCount(allyIds);
  const enemy = tagCount(enemyIds);

  // Damage-profile read: enemy AD = Fighter+Marksman+Assassin (Tank
  // partial); enemy AP = Mage. When one side is heavily skewed the
  // tip surfaces a defensive item or summoner spell suggestion.
  const enemyAD = enemy.Fighter + enemy.Marksman + enemy.Assassin;
  const enemyAP = enemy.Mage;
  const enemyCC = enemy.Tank + enemy.Support;  // proxy - full CC scoring lives in adaptive-summoner classifier
  const allyHasFrontline = (ally.Tank + ally.Fighter) >= 1;
  const allyHasCarry = (ally.Marksman + ally.Mage + ally.Assassin) >= 1;

  // Role-conditional tip selection - surface the highest-priority
  // observation for the operator's chosen role.
  if (role === "BOT") {
    if (enemyCC >= 3) return "Enemy has 3+ CC threats - hover Cleanse before lock-in";
    if (enemyAD > enemyAP + 1) return "Enemy comp leans AD - Plated Steelcaps / Tabis path opens up";
    if (enemyAP > enemyAD) return "Enemy comp leans AP - Mercury's + Maw of Malmortius";
    if (!allyHasFrontline) return "No locked frontline yet - wait or shift to a self-peeling ADC";
  } else if (role === "SUP") {
    if (!allyHasCarry) return "Carry slots still open - hover engage to telegraph aggression";
    if (enemyAD >= 3) return "Heavy AD enemy comp - Knight's Vow / Locket of Iron Solari shine";
    if (enemy.Assassin >= 1) return "Enemy has assassin pressure - peel-first supports beat engage here";
  } else if (role === "TOP") {
    if (enemy.Marksman + enemy.Mage >= 3) return "Enemy heavy on ranged damage - tank + MR rush";
    if (enemyAD >= 3) return "Heavy AD top side - armor first (Plated / Randuin's / Sunfire)";
    if (!allyHasCarry) return "Allies lack scaling carry - consider a self-scaling top (Nasus / Kayle)";
  } else if (role === "JNG") {
    if (enemy.Tank >= 2) return "Enemy fields 2+ tanks - bring %-HP or true-damage jungler";
    if (enemyCC >= 3) return "CC-heavy enemy comp - duelist > engage jungler";
    if (!allyHasFrontline) return "Allies lack frontline - pick an engage/tank jungler";
  } else if (role === "MID") {
    if (enemy.Assassin >= 1) return "Enemy assassin commits to dive - bring Zhonya's window";
    if (enemyAP >= 2) return "Enemy double-AP - Mercury's first; Maw of Malmortius if you're AD";
    if (!allyHasCarry) return "No locked carry yet - flex pick keeps options open";
  } else if (role === "ARAM" || role === "MAYHEM") {
    if (enemyCC >= 3) return "ARAM CC bomb risk - Mercury's + Cleanse if any ranged carry locks";
    if (enemyAP > enemyAD + 1) return "Enemy ARAM is AP-heavy - Force of Nature / Spirit Visage";
    if (enemyAD > enemyAP + 1) return "Enemy ARAM is AD-heavy - Plated / Randuin's path";
  }
  // Generic fall-through when nothing above triggered (mixed comp).
  if (allyHasFrontline && allyHasCarry) {
    return "Comp shaping up balanced - comfort > counterpick from here";
  }
  return null;
}

// s171: lock button click handler - same shape as the legacy overlay's
// #cs-lock-btn. Disables the button on click to prevent double-fire,
// stamps the state line with the agent's response, then re-enables on
// timeout so a real failure can be retried.
function _csvWireLockButton(scope) {
  const btn = scope.querySelector("#csv-lock-btn");
  if (!btn) return;
  btn.addEventListener("click", () => {
    btn.disabled = true;
    const cid = (btn.dataset.cid | 0);
    if (!(cid > 0)) { btn.disabled = false; return; }
    lcuCmd({ cmd: "lock_pick", championId: cid }).then((resp) => {
      const id = resp && resp.id;
      if (!id) { btn.disabled = false; return; }
      lcuPollResult(id, (result) => {
        const stateEl = document.getElementById("csv-mypick-state");
        if (stateEl) {
          if (result && result.ok) {
            stateEl.textContent = result.note === "already locked"
              ? "OK ALREADY LOCKED" : "OK LOCK SENT";
            stateEl.classList.remove("hovering");
            stateEl.classList.add("locked");
          } else {
            const err = (result && result.err) || "no response";
            stateEl.textContent = "X Lock failed: " + err;
          }
        }
      });
    });
    setTimeout(() => { btn.disabled = false; }, 1500);
  });
}

// HTML for the ARAM bench strip (up to 10 horizontal champion cells).
// Click fires lcu bench_swap which bypasses the 5s client-side cooldown.
function _csvBenchHtml(cs) {
  const bench = (cs && Array.isArray(cs.bench)) ? cs.bench.slice(0, 10) : [];
  // Deterministic comp-verdict banner sits at the top of the bench strip
  // in both the empty and populated branches (it can recommend a STAY or
  // a VARIANT swap even when the bench is empty).
  const verdictHtml = _csvCompVerdictHtml();
  if (!bench.length) {
    return `
      <div class="csv-bench">
        ${verdictHtml}
        <div class="csv-bench-title">Bench</div>
        <div class="csv-bench-empty">no bench champs yet - wait for a teammate to reroll</div>
      </div>`;
  }
  // When the verdict recommends a swap, highlight the matching bench cell
  // (case-insensitive alnum-normalized name match against swap_to).
  const verdict = _CSV_COMPVERDICT.data;
  const swapTarget = (verdict && verdict.ok && verdict.recommendation === "swap")
    ? _csvNormChampName(verdict.swap_to) : "";
  const ver = CHAMPS.version || "latest";
  const cells = bench.map((cid) => {
    const nm = _csChampName(cid) || ("cid:" + cid);
    const img = (cid && CHAMPS.byId[String(cid)])
      ? `<img src="/data/ddragon/${ver}/img/champion/${CHAMPS.byId[String(cid)]}.png" alt="${nm}" onerror="this.style.display='none'">`
      : "?";
    const isSwap = swapTarget && _csvNormChampName(nm) === swapTarget;
    const swapCls = isSwap ? " is-verdict-swap" : "";
    return `
      <div class="csv-bench-cell is-clickable${swapCls}" data-bench-id="${cid}" data-bench-name="${nm}" title="Swap to ${nm}">
        <div class="csv-bench-cell-icon">${img}</div>
      </div>`;
  }).join("");
  return `
    <div class="csv-bench">
      ${verdictHtml}
      <div class="csv-bench-title">Bench . click to swap</div>
      <div class="csv-bench-row">${cells}</div>
    </div>`;
}

function _csvWireBench(scope) {
  scope.querySelectorAll(".csv-bench-cell.is-clickable").forEach((cell) => {
    cell.addEventListener("click", () => {
      const cid = parseInt(cell.dataset.benchId, 10);
      if (!cid) return;
      lcuCmd({ cmd: "bench_swap", championId: cid });
      // Visual feedback - pulse the cell so the operator sees the click
      // registered before the LCU agent confirms via state push.
      cell.classList.add("is-pending");
      setTimeout(() => cell.classList.remove("is-pending"), 500);
    });
  });
}

// Placeholder build variants. Phase B replaces this with real loadout
// data from /api/loadout/list keyed on champion + mode.
// s209 v2 fix: cs.bans comes through as `{my_team: [ids], their_team: [ids]}`
// from the LCU agent (a dict), not the array shape my first sig assumed.
// Old code did `(cs.bans || []).map(...)` which threw `.map is not a
// function` and aborted renderChampSelectView entirely (page stayed on
// the scaffold "waiting for champ-select data" text). Tolerant decode:
// arrays of {championId} (legacy shape), {my_team, their_team} arrays of
// ids (LCU agent shape), or missing -> empty string.
function _csvBansSig(bans) {
  if (!bans) return "";
  if (Array.isArray(bans)) {
    return bans.map((b) => (b && b.championId) | 0).join(",");
  }
  if (typeof bans === "object") {
    const a = Array.isArray(bans.my_team)    ? bans.my_team.join(",")    : "";
    const b = Array.isArray(bans.their_team) ? bans.their_team.join(",") : "";
    return `${a}|${b}`;
  }
  return "";
}

// s209 v2: idempotent render sig. Captures everything renderChampSelectView
// reads to draw the three panels (allies / center / enemies + pickban).
// Timer remaining_ms is deliberately excluded - _csvSetupTimerTick owns
// the countdown text and updates it independently of the innerHTML
// rebuild. DS / user-variant / archetype caches are folded in as a
// 1-or-0 presence stamp so the render fires once when each cache lands.
function _csvComputeSig(cs, mode, myCid, myName) {
  const teamSig = (t) => (t || []).map((p) => {
    if (!p) return "_";
    return `${p.cellId|0}:${p.championId|0}:${p.championPickIntent|0}`;
  }).join(",");
  // s214: DS cache key folds in the archetype primary alongside mode,
  // so the sig changes when operator flips archetype mid-CS and the
  // build chooser re-renders with fresh items.
  const archForKey = (_CSV_ARCH_CACHE[myName] && _CSV_ARCH_CACHE[myName].primary)
    || _csvSavedArchetype(myName) || "";
  const dsKey   = _CSV_DS_CACHE[_csvDsCacheKey(myName, _csvDsModeFor(mode), archForKey)] ? "1" : "0";
  const userKey = _CSV_USER_CACHE[`${myName}|${mode || "sr"}`] !== undefined ? "1" : "0";
  // s211 v4: include the archetype's primary + source in the sig so a
  // mid-session swap (operator clicks Bruiser -> Tank, or clicks AUTO
  // to revert to DDragon-tag default) actually re-renders the picker.
  // Pre-s211v4 the sig was presence-only ("1" once cached, never
  // changing) which meant the "overridden" pill + AUTO button state
  // stayed frozen on the first cached value until a full reload.
  const archCached = _CSV_ARCH_CACHE[myName];
  const archKey = archCached
    ? `1:${archCached.primary || ""}:${archCached.source || ""}`
    : "0::";
  // s209 v2: include adaptive-summoners cache state so the render fires
  // once when the recommendation lands per enemy roster. Just count the
  // cached keys for this champion - granular enough to detect "new
  // recommendation arrived" without hashing the whole cache.
  const adaptCount = Object.keys(_CSV_ADAPT_CACHE)
    .filter((k) => k.startsWith(`${myName}|`)).length;
  // s210: ban-suggestions cache state - count keys so the Suggestions
  // panel re-renders when the global top-bans fetch lands.
  const banSuggCount = Object.keys(_CSV_BANSUGG_CACHE).length;
  // 2026-05-20 (item 109 carry-forward): ban-suggest dual-score cache
  // state - same pattern, count keys so the HURTS-THEM / HELPS-US
  // toggle re-renders when the /api/ban-suggest fetch lands.
  const banSuggDualCount = getBanSuggestCacheCount();
  // 2026-05-22 (item 139 carry (a)): cc-blended-ehp threat cache state
  // - same pattern, count keys so the threat chip re-renders when
  // /api/cc-blended-ehp-threat lands.
  const ccBlendedCount = getCcBlendedEhpThreatCacheCount();
  const ccCondCount = getCcConditionalPressureCacheCount();
  // CS1 (2026-06-08): ally CC-pairing cache state - count keys so the
  // pairing card re-renders when /api/cc-pairing lands.
  const ccPairCount = getCcPairingCacheCount();
  const cdwCount = getCooldownWatchCacheCount();
  // 2026-06-25: personal best-build cache state - count keys so the card
  // re-renders when /api/personal-build lands.
  const pbwCount = getPersonalBuildCacheCount();
  // CS3 (2026-06-08): ds-sweep / ds-combo / ds-relscore cache counts dropped
  // from the champ-select sig - those panels render on active-match now. The
  // profile / knobs / statcheck counts stay (they still render here).
  const dspCount = getDsProfileCacheCount();
  const dskCount = getDsKnobsCacheCount();
  const dssCount = getDsStatcheckCacheCount();
  // RC2 E4: counter-picks cache state - count keys so the "pick into this
  // comp" list re-renders when /api/champ-select/counter-picks lands.
  const counterCount = Object.keys(_CSV_COUNTER_CACHE).length;
  // ARAM comp-verdict presence stamp - flips 0->1 when the verdict fetch
  // lands so the idempotent render gate re-fires and the bench banner
  // (plus the is-verdict-swap cell highlight) draws.
  const verdictKey = _CSV_COMPVERDICT.data ? "1" : "0";
  return [
    cs.phase || "",
    myCid | 0,
    cs.my_completed ? "1" : "0",
    teamSig(cs.my_team),
    teamSig(cs.their_team),
    _csvBansSig(cs.bans),
    cs.active_round
      ? `${cs.active_round.type}|${(cs.active_round.cell_ids || []).join(",")}`
      : "",
    cs.queue_id | 0,
    mode,
    `ds:${dsKey}|usr:${userKey}|arch:${archKey}|adapt:${adaptCount}|bsugg:${banSuggCount}|bsdual:${banSuggDualCount}|ccbe:${ccBlendedCount}|ccp:${ccCondCount}|ccpair:${ccPairCount}|cdw:${cdwCount}|pbw:${pbwCount}|dsk:${dskCount}|dss:${dssCount}|dsp:${dspCount}|cnt:${counterCount}`,
    verdictKey,
  ].join("|");
}

// s209 v2: coalesce post-fetch re-renders into a single rAF tick.
// _csvFetchDsBuilds / _csvFetchUserVariants / _csvFetchArchetype each
// fire their own .then() re-render, and on a cold-cache champion they
// can all land within the same frame - back-to-back synchronous
// renderChampSelectView() calls rebuild innerHTML three times in a
// row, which the operator sees as flicker in the build chooser. This
// helper queues one rAF, runs at most once per frame, and re-reads
// state.latest.lcu at fire time (in case the LCU envelope changed
// between the fetch landing and the frame rendering).
let _csvScheduledRenderRaf = 0;
// UI scale v2.1 page #8 audit (2026-05-23): cache the last lcu that
// rendered as a valid ChampSelect surface. _csvScheduleRender's rAF
// re-fire normally pulls state.latest.lcu, but under mock mode the
// live state has no ChampSelect phase - bailing out at the
// renderChampSelectView phase-gate would skip the cache-driven
// re-render (build chooser, threat chips, etc.). The cache lets the
// rAF restore the mock lcu so post-fetch re-renders complete.
let _csvLastRenderedLcu = null;
function _csvCacheLcuIfChampSelect(lcu) {
  if (lcu && lcu.phase === "ChampSelect") _csvLastRenderedLcu = lcu;
}
function _csvScheduleRender() {
  if (_csvScheduledRenderRaf) return;
  _csvScheduledRenderRaf = requestAnimationFrame(() => {
    _csvScheduledRenderRaf = 0;
    const isMock = !!(document && document.body && document.body.dataset.uiMock === "1");
    const liveLcu = (state.latest && state.latest.lcu) || null;
    const lcu = (isMock && (!liveLcu || liveLcu.phase !== "ChampSelect"))
      ? _csvLastRenderedLcu
      : liveLcu;
    if (lcu) {
      // s213: bump the section sig so the idempotent gate at the top
      // of renderChampSelectView doesn't bail. The sig already
      // captures DS/user/arch/adapt/bsugg cache state, but not the
      // lol-descriptions cache - events that fire `_csvScheduleRender`
      // (DS land, adaptive land, ban-sugg land, lol-desc land) need
      // to defeat the sig either by changing one of its inputs OR by
      // clearing the stamp explicitly. Clearing is safer than coupling
      // every fire site to the sig schema.
      const sec = document.getElementById("view-champ-select");
      if (sec) sec.dataset.csvSig = "";
      renderChampSelectView(lcu);
    }
  });
}

// s213: re-render champ-select once the DDragon item/rune description
// cache lands so item + keystone elements pick up `data-tt-html`.
document.addEventListener("rc:lol-descriptions-ready", () => {
  _csvScheduleRender();
});
// s213 v2: same for champion-tags - enemy cells get the 2-piece tag +
// confidence pill once the cache resolves.
document.addEventListener("rc:champion-tags-ready", () => {
  _csvScheduleRender();
});
// Operator 2026-05-31 (part 2): the Build Order card no longer collapses
// (always-on horizontal render), so the rc:build-order-toggle listener +
// its dispatch in build_order.js were removed.
// item 213 (2026-05-28): delegated handler for the DS-vs-enemy-comp
// "save + push to client" button (rendered by build_order.js). Pushes
// the finalized ordered build to the League client as an item set via
// the EXISTING apply_item_sets_batch LCU contract (item 164/178). The
// set_uid is distinct (RC-<champ>-<mode>-dsenemycomp) so it coexists
// with the build-chooser rows' sets - replace-by-uid leaves them all in
// the in-game item-shop dropdown. Items are already in buy order from
// the engine (boots + core early, situational later); we preserve that
// order in the pushed block.
let _BO_PUSH_INFLIGHT = false;
document.addEventListener("click", (ev) => {
  const btn = ev.target && ev.target.closest && ev.target.closest("[data-bo-push]");
  if (!btn) return;
  ev.stopPropagation();
  if (_BO_PUSH_INFLIGHT) return;
  const champ = btn.dataset.boChamp || "";
  const mode  = (btn.dataset.boMode || "SR").toLowerCase();
  const itemsRaw = btn.dataset.boItems || "";
  const itemIds = itemsRaw.split(",").map((x) => String(x).trim()).filter(Boolean);
  if (!champ || !itemIds.length) return;
  _BO_PUSH_INFLIGHT = true;
  const sets = [{
    set_uid:     `RC-${champ}-${mode}-dsenemycomp`,
    title:       `RC DS vs Enemy Comp: ${champ}`.slice(0, 50),
    champion_id: 0,
    blocks: [{
      type: "DS vs Enemy Comp (buy order)",
      items: itemIds.slice(0, 6).map((iid) => ({ id: String(iid), count: 1 })),
    }],
  }];
  try { lcuCmd({ cmd: "apply_item_sets_batch", sets }); } catch (_) {}
  // Brief visual ack on the button, then clear the in-flight guard.
  const prior = btn.textContent;
  btn.textContent = "pushed";
  btn.classList.add("is-pushed");
  setTimeout(() => {
    btn.textContent = prior;
    btn.classList.remove("is-pushed");
    _BO_PUSH_INFLIGHT = false;
  }, 1500);
});

// s171: DS engine cache for the new champ-select view's build chooser.
// Keyed by `${champion}|${dsMode}` - drafts don't change build order so
// caching across the whole champ-select session is safe. Cleared on
// CHAMPS.ready transition (handled implicitly - page reload clears).
const _CSV_DS_CACHE    = Object.create(null);
const _CSV_DS_INFLIGHT = Object.create(null);

// s171.8: parallel cache for user-curated variants from /api/loadout/list.
// User variants are persisted to disk via loadout_resolver, so different
// modes for the same champion can carry different variant sets.
const _CSV_USER_CACHE    = Object.create(null);
const _CSV_USER_INFLIGHT = Object.create(null);

// s209 v2: adaptive-summoners cache (per champion + enemy-roster sig
// + base summoner pair). Refetches when enemies lock new champs.
const _CSV_ADAPT_CACHE    = Object.create(null);
const _CSV_ADAPT_INFLIGHT = Object.create(null);

// s210: ban-suggestions cache keyed on already-banned-set sig. Top-4
// globally-banned champions filtered against already-banned. Refetches
// when bans change so the panel stays in sync with the draft.
const _CSV_BANSUGG_CACHE    = Object.create(null);
const _CSV_BANSUGG_INFLIGHT = Object.create(null);

// Deterministic ARAM comp-verdict cache. Single-slot (the verdict is a
// function of my pick + my-team comp + the current bench), not a per-key
// map - the whole champ-select carries one live verdict at a time. Keyed
// by `${my_champion}|<my-team ids>|<bench ids>` so a teammate reroll or a
// fresh bench refetches. Backed by POST /api/aram-comp-verdict (the
// parallel backend slice); mock mode reads the aram_comp_verdict key from
// the champ_select_aram.json fixture.
const _CSV_COMPVERDICT = { key: "", data: null, inflight: false };

function _csvCompVerdictKey(cs) {
  if (!cs) return "";
  const teamIds = (cs.my_team || [])
    .map((p) => (p && p.championId) | 0).join(",");
  const benchIds = (Array.isArray(cs.bench) ? cs.bench : [])
    .map((c) => c | 0).join(",");
  return `${cs.my_champion | 0}|${teamIds}|${benchIds}`;
}

// Trigger an async fetch for the deterministic ARAM comp-verdict. No-op
// when already cached for this key or a request is inflight. The render
// re-fires via _csvScheduleRender once the verdict lands (its presence is
// folded into _csvComputeSig). Mock mode short-circuits the live POST and
// reads the fixture, mirroring _csvFetchUserVariants.
function _csvFetchCompVerdict(cs) {
  if (!cs) return;
  const key = _csvCompVerdictKey(cs);
  if (key === _CSV_COMPVERDICT.key && _CSV_COMPVERDICT.data) return;
  if (_CSV_COMPVERDICT.inflight) return;
  const isMock = !!(document && document.body
    && document.body.dataset.uiMock === "1");
  if (isMock) {
    _CSV_COMPVERDICT.inflight = true;
    fetch("/data/ui_mock/champ_select_aram.json", { cache: "no-store" })
      .then((r) => (r && r.ok ? r.json() : null))
      .then((json) => {
        _CSV_COMPVERDICT.inflight = false;
        _CSV_COMPVERDICT.data = (json && json.aram_comp_verdict) || null;
        _CSV_COMPVERDICT.key = key;
        if (_CSV_COMPVERDICT.data) _csvScheduleRender();
      })
      .catch(() => { _CSV_COMPVERDICT.inflight = false; });
    return;
  }
  // Live path: resolve championIds -> display names the engine expects.
  const myName = _csChampName(cs.my_champion);
  const team = (cs.my_team || [])
    .map((p) => _csChampName(p && p.championId)).filter(Boolean);
  const enemies = (cs.their_team || [])
    .map((p) => _csChampName(p && p.championId)).filter(Boolean);
  const bench = (Array.isArray(cs.bench) ? cs.bench : [])
    .map((c) => _csChampName(c)).filter(Boolean);
  // The deterministic engine needs >=3 known allies to score a comp.
  if (team.length < 3) return;
  _CSV_COMPVERDICT.inflight = true;
  fetch("/api/aram-comp-verdict", {
    method: "POST", cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      my_champion: myName, my_team: team,
      their_team: enemies, bench: bench,
    }),
  })
    .then((r) => (r && r.ok ? r.json() : null))
    .then((json) => {
      _CSV_COMPVERDICT.inflight = false;
      if (json && json.ok) {
        _CSV_COMPVERDICT.data = json;
        _CSV_COMPVERDICT.key = key;
        _csvScheduleRender();
      }
    })
    .catch(() => { _CSV_COMPVERDICT.inflight = false; });
}

// Normalise a champion name for case-insensitive alnum-only comparison
// (so "Miss Fortune" matches "MissFortune", "Dr. Mundo" vs "DrMundo").
function _csvNormChampName(s) {
  return String(s || "").toLowerCase().replace(/[^a-z0-9]/g, "");
}

// Build the comp-verdict banner. Empty string when there's no verdict or
// the engine declined (ok=false). Server strings are trusted (no HTML
// injection surface - they're our own engine output).
function _csvCompVerdictHtml() {
  const data = _CSV_COMPVERDICT.data;
  if (!data || !data.ok) return "";
  const rec = data.recommendation || "stay";
  let recTxt = "STAY";
  if (rec === "swap") recTxt = `SWAP -> ${data.swap_to || "?"}`;
  else if (rec === "variant") recTxt = `VARIANT -> ${data.variant_to || "?"}`;
  const conf = data.confidence || "low";
  return `
    <div class="csv-bench-verdict csv-bench-verdict--${rec}">
      <span class="csv-bench-verdict-label">COMP VERDICT</span>
      <span class="csv-bench-verdict-rec">${recTxt}</span>
      <span class="csv-bench-verdict-conf csv-bench-verdict-conf--${conf}">${conf}</span>
      <span class="csv-bench-verdict-reason">${data.reason || ""}</span>
    </div>`;
}

function _csvBanSuggKey(excludedIds) {
  return (excludedIds || []).slice().sort((a, b) => a - b).join(",");
}

function _csvFetchBanSuggestions(excludedIds) {
  const key = _csvBanSuggKey(excludedIds);
  if (_CSV_BANSUGG_CACHE[key] || _CSV_BANSUGG_INFLIGHT[key]) return;
  _CSV_BANSUGG_INFLIGHT[key] = true;
  const url = `/api/champ-select/ban-suggestions?exclude=${encodeURIComponent(key)}&top=4`;
  fetch(url, { cache: "no-store" })
    .then((r) => r.ok ? r.json() : null)
    .then((data) => {
      _CSV_BANSUGG_INFLIGHT[key] = false;
      if (data && data.ok) {
        _CSV_BANSUGG_CACHE[key] = data;
        _csvScheduleRender();
      }
    })
    .catch(() => { _CSV_BANSUGG_INFLIGHT[key] = false; });
}

// 2026-05-20 (item 109 carry-forward (a)): HURTS-THEM / HELPS-US toggle
// wire. Uses the cached global-top-bans list (`bansCached.suggestions`,
// already filtered against already-banned ids) as the candidate pool,
// then calls /api/ban-suggest to enrich each candidate with the dual
// HURTS-THEM / HELPS-US ratings against the operator's current ally +
// enemy roster. The mode chip + sortable list mount inside the
// #csv-sugg-bs-toggle block (declared in web/index.html).
function _csvRenderBanSuggestToggle(cs, bansCached) {
  const block = document.getElementById("csv-sugg-bs-toggle");
  if (!block) return;
  // Need at least one ally locked + a candidate pool to score.
  const allyIds = (cs.my_team || [])
    .map((p) => (p && (p.championId | 0)) || 0)
    .filter((x) => x > 0);
  if (!allyIds.length) { block.hidden = true; return; }
  const candidatesMeta = (bansCached && Array.isArray(bansCached.suggestions))
    ? bansCached.suggestions : [];
  if (!candidatesMeta.length) { block.hidden = true; return; }
  block.hidden = false;
  const enemyIds = (cs.their_team || [])
    .map((p) => (p && (p.championId | 0)) || 0)
    .filter((x) => x > 0);
  const candidateIds = candidatesMeta
    .map((m) => (m && (m.champId | 0)) || 0)
    .filter((x) => x > 0);
  const queue = (cs.queue_id | 0) || null;

  fetchBanSuggest(allyIds, enemyIds, candidateIds, queue, _csvScheduleRender);

  const chipEl = document.getElementById("csv-sugg-bs-mode");
  const listEl = document.getElementById("csv-sugg-bs-list");
  if (chipEl) {
    renderBanSuggestModeChip(chipEl, () => _csvScheduleRender());
  }
  if (listEl) {
    const payload = getCachedBanSuggest(allyIds, enemyIds, candidateIds, queue);
    renderBanSuggestList(listEl, payload, candidatesMeta);
  }
}

// 2026-05-22 (item 139 carry (a)): FIRST dashboard UI consumer of
// cc_blended_ehp. Calls /api/cc-blended-ehp-threat with the operator's
// current ally + enemy rosters, then renders the threat-balance chip
// inside the #csv-sugg-cc-blended-ehp-threat block. The mode parameter
// is derived from cs.queue_id (ARAM/Mayhem are the modes whose
// aramTenacity actually moves the cc_pressure value; SR computes
// cleanly at identity tenacity). Chip is hidden until at least one
// ally + one enemy is committed so it doesn't render premature noise.
function _csvRenderCcBlendedEhpThreat(cs) {
  const block = document.getElementById("csv-sugg-cc-blended-ehp-threat");
  if (!block) return;
  const allyNumericIds = (cs.my_team || [])
    .map((p) => (p && (p.championId | 0)) || 0)
    .filter((x) => x > 0);
  const enemyNumericIds = (cs.their_team || [])
    .map((p) => (p && (p.championId | 0)) || 0)
    .filter((x) => x > 0);
  if (!allyNumericIds.length || !enemyNumericIds.length) {
    block.hidden = true;
    return;
  }
  const allyNames = resolveChampNames(allyNumericIds);
  const enemyNames = resolveChampNames(enemyNumericIds);
  if (!allyNames.length || !enemyNames.length) {
    // CHAMPS index not yet loaded - keep hidden, will resolve on the
    // next render tick after the rc:champs-ready event fires.
    block.hidden = true;
    return;
  }
  // Map queue_id to mode. ARAM (450), KIWI/Mayhem (2400), Arena
  // (1750 live, 1700/1710 legacy) all benefit from the chip; SR (420
  // ranked / 400 normal) computes cleanly at identity tenacity. The
  // backend accepts any of these and defaults to ARAM if absent.
  let mode = "ARAM";
  const q = cs.queue_id | 0;
  if (q === 2400) mode = "KIWI";
  else if (q === 1700 || q === 1710 || q === 1750) mode = "ARENA";
  else if (q === 420 || q === 400 || q === 430 || q === 700) mode = "SR";
  else if (q === 450 || q === 920) mode = "ARAM";

  fetchCcBlendedEhpThreat(allyNames, enemyNames, mode, _csvScheduleRender);
  const payload = getCachedCcBlendedEhpThreat(allyNames, enemyNames, mode);
  renderCcBlendedEhpThreat(block, payload);
}

// 2026-05-22 (item 144): FIRST dashboard UI consumer of cc_conditional
// (5th overall ecosystem consumer). Calls /api/cc-conditional-pressure
// with the operator's current ally + enemy rosters, then renders the
// conditional-CC threat-balance chip inside the
// #csv-sugg-cc-conditional-pressure block. Mirrors the
// _csvRenderCcBlendedEhpThreat structure exactly so the two chips
// stay behaviourally coherent. Chip is hidden until at least one
// ally + one enemy is committed so it doesn't render premature
// noise.
function _csvRenderCcConditionalPressure(cs) {
  const block = document.getElementById("csv-sugg-cc-conditional-pressure");
  if (!block) return;
  const allyNumericIds = (cs.my_team || [])
    .map((p) => (p && (p.championId | 0)) || 0)
    .filter((x) => x > 0);
  const enemyNumericIds = (cs.their_team || [])
    .map((p) => (p && (p.championId | 0)) || 0)
    .filter((x) => x > 0);
  if (!allyNumericIds.length || !enemyNumericIds.length) {
    block.hidden = true;
    return;
  }
  const allyNames = resolveChampNames(allyNumericIds);
  const enemyNames = resolveChampNames(enemyNumericIds);
  if (!allyNames.length || !enemyNames.length) {
    // CHAMPS index not yet loaded - keep hidden, will resolve on the
    // next render tick after the rc:champs-ready event fires.
    block.hidden = true;
    return;
  }
  // Map queue_id to mode (same mapping as _csvRenderCcBlendedEhpThreat).
  let mode = "ARAM";
  const q = cs.queue_id | 0;
  if (q === 2400) mode = "KIWI";
  else if (q === 1700 || q === 1710 || q === 1750) mode = "ARENA";
  else if (q === 420 || q === 400 || q === 430 || q === 700) mode = "SR";
  else if (q === 450 || q === 920) mode = "ARAM";

  fetchCcConditionalPressure(allyNames, enemyNames, mode, _csvScheduleRender);
  const payload = getCachedCcConditionalPressure(allyNames, enemyNames, mode);
  renderCcConditionalPressure(block, payload);
}

// 2026-05-30 (item 218 / competitor lift #5): matchup cooldown-watch.
// ENEMY-only surface (no ally side) - per enemy champion, the single
// highest-threat hard-CC ability + its max-rank base cooldown. Calls
// /api/cooldown-watch with the enemy roster, renders the card list inside
// the #csv-sugg-cooldown-watch block. Hidden until at least one enemy is
// committed. Mode-agnostic (the route + engine take no mode param - the
// cooldown is intrinsic to the ability).
function _csvRenderCooldownWatch(cs) {
  const block = document.getElementById("csv-sugg-cooldown-watch");
  if (!block) return;
  const enemyNumericIds = (cs.their_team || [])
    .map((p) => (p && (p.championId | 0)) || 0)
    .filter((x) => x > 0);
  if (!enemyNumericIds.length) {
    block.hidden = true;
    return;
  }
  const enemyNames = resolveChampNames(enemyNumericIds);
  if (!enemyNames.length) {
    // CHAMPS index not yet loaded - keep hidden, resolves next tick.
    block.hidden = true;
    return;
  }
  fetchCooldownWatch(enemyNames, _csvScheduleRender);
  const payload = getCachedCooldownWatch(enemyNames);
  renderCooldownWatch(block, payload);
}

// 2026-06-26 (item 633): L4 Phase-D capability-gap chip. Self-contained
// fetch/cache/render: the verdict rides on the EXISTING /api/ds-preview
// response (new `capability_gap` field, default-OFF RC_CAPGAP_SURFACE) so
// no new endpoint is added. Keyed by my-champion + enemy roster + mode so a
// pick/ban swap re-fetches. The cache stores `false` for a resolved
// no-gap (or flag-off) response so we do not refetch the same key forever.
const _CSV_CAPGAP_CACHE = {};
const _CSV_CAPGAP_INFLIGHT = {};

function _csvCapgapKey(myChamp, enemyNames, mode) {
  return `${myChamp}|${(enemyNames || []).join(",")}|${mode}`;
}

function _csvFetchCapabilityGap(myChamp, enemyNames, mode, cb) {
  if (!myChamp || !(enemyNames && enemyNames.length) || !mode) return;
  const key = _csvCapgapKey(myChamp, enemyNames, mode);
  if (key in _CSV_CAPGAP_CACHE || _CSV_CAPGAP_INFLIGHT[key]) return;
  _CSV_CAPGAP_INFLIGHT[key] = true;
  // UI mock short-circuit (mirrors _csvFetchUserVariants): under
  // ?ui_mock=1 the chip seeds from the fixture's capability_gap block so
  // the champ-select page renders the chip deterministically for the
  // visual-audit ritual (the live /api/ds-preview path is default-OFF).
  const isMock = !!(document && document.body && document.body.dataset.uiMock === "1");
  if (isMock) {
    fetch("/data/ui_mock/champ_select_sr.json", { cache: "no-store" })
      .then((r) => (r && r.ok ? r.json() : null))
      .then((data) => {
        _CSV_CAPGAP_INFLIGHT[key] = false;
        _CSV_CAPGAP_CACHE[key] = (data && data.capability_gap) || false;
        if (_CSV_CAPGAP_CACHE[key]) { try { cb && cb(); } catch (_) {} }
      })
      .catch(() => { _CSV_CAPGAP_INFLIGHT[key] = false; _CSV_CAPGAP_CACHE[key] = false; });
    return;
  }
  fetch("/api/ds-preview", {
    method: "POST", cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      champion: myChamp, enemies: enemyNames, mode, level: 6, items: [],
    }),
  })
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      _CSV_CAPGAP_INFLIGHT[key] = false;
      // null (flag OFF / no gap) -> store `false` so the `in` guard above
      // treats the key as resolved and we stop refetching it.
      _CSV_CAPGAP_CACHE[key] = (data && data.capability_gap) || false;
      if (_CSV_CAPGAP_CACHE[key]) { try { cb && cb(); } catch (_) {} }
    })
    .catch(() => { _CSV_CAPGAP_INFLIGHT[key] = false; });
}

function _csvGetCachedCapabilityGap(myChamp, enemyNames, mode) {
  const v = _CSV_CAPGAP_CACHE[_csvCapgapKey(myChamp, enemyNames, mode)];
  return v || null;  // `false`/undefined -> null (render hides the chip)
}

// Axis -> operator-facing label. The backend axis keys are itemization-
// direct; the labels name the COUNTER the operator should buy/play toward.
const _CSV_CAPGAP_AXIS_LABEL = {
  anti_tank: "Anti-tank",
  sustain:   "Anti-heal",
  poke:      "Anti-poke",
};

function _csvRenderCapabilityGapBlock(block, payload) {
  if (!payload || !payload.applies) { block.hidden = true; return; }
  const axis = String(payload.top_gap || "");
  const axisLabel = _CSV_CAPGAP_AXIS_LABEL[axis]
    || (axis ? axis.replace(/_/g, " ") : "Gap");
  const verdict = String(payload.verdict || "");
  block.dataset.capgapAxis = axis || "none";
  block.hidden = false;
  block.innerHTML = `
    <div class="capability-gap-head">
      <span class="capability-gap-badge">GAP</span>
      <span class="capability-gap-axis">${escHtml(axisLabel)}</span>
    </div>
    <div class="capability-gap-verdict">${escHtml(verdict)}</div>`;
}

function _csvRenderCapabilityGap(cs) {
  const block = document.getElementById("csv-sugg-capability-gap");
  if (!block) return;
  const myId = (cs.my_champion | 0);
  const enemyNumericIds = (cs.their_team || [])
    .map((p) => (p && (p.championId | 0)) || 0)
    .filter((x) => x > 0);
  if (myId <= 0 || !enemyNumericIds.length) { block.hidden = true; return; }
  const myNames = resolveChampNames([myId]);
  const myChamp = myNames.length ? myNames[0] : "";
  const enemyNames = resolveChampNames(enemyNumericIds);
  if (!myChamp || !enemyNames.length) {
    // CHAMPS index not yet loaded - keep hidden, resolves next tick.
    block.hidden = true;
    return;
  }
  // Map queue_id to mode (same vocabulary as the sibling chips). Default SR.
  let mode = "SR";
  const q = cs.queue_id | 0;
  if (q === 2400) mode = "KIWI";
  else if (q === 1700 || q === 1710 || q === 1750) mode = "ARENA";
  else if (q === 450 || q === 920) mode = "ARAM";
  _csvFetchCapabilityGap(myChamp, enemyNames, mode, _csvScheduleRender);
  const payload = _csvGetCachedCapabilityGap(myChamp, enemyNames, mode);
  _csvRenderCapabilityGapBlock(block, payload);
}

// 2026-06-25: personal best-build card. Reads the operator's OWN locked
// champion (cs.my_champion -> resolveChampNames) and renders, per completed
// item they win with on it, the win-rate lift vs their own baseline inside the
// #csv-personal-build block. Mode comes from cs.queue_id (the route's
// lowercase sr|aram|arena vocabulary). Mirrors _csvRenderCooldownWatch but on
// the operator's own-pick side. Hidden until a champion is locked + the
// personal sample clears the backend threshold. Read-only.
function _csvRenderPersonalBuild(cs) {
  const block = document.getElementById("csv-personal-build");
  if (!block) return;
  const myId = (cs.my_champion | 0);
  if (myId <= 0) {
    block.hidden = true;
    return;
  }
  const names = resolveChampNames([myId]);
  const champ = names.length ? names[0] : "";
  if (!champ) {
    // CHAMPS index not yet loaded - keep hidden, resolves next tick.
    block.hidden = true;
    return;
  }
  const mode = pbwModeForQueue(cs.queue_id);
  fetchPersonalBuild(champ, mode, _csvScheduleRender);
  const payload = getCachedPersonalBuild(champ, mode);
  renderPersonalBuild(block, payload);
}

// CS1 (2026-06-08): ally CC-pairing card. Reads the operator's OWN roster
// (cs.my_team) and renders, per conditional CC entry whose condition a
// TEAMMATE can set up, the entry + plausible enabler teammates inside the
// #csv-sugg-cc-pairing block. Mirrors the _csvRenderCooldownWatch shape
// but on the ALLY side (the cooldown-watch card is the enemy-threat twin).
// Mode-agnostic (the route + engine take no mode param - the pairing fact
// is intrinsic to the abilities). Hidden until at least one ally with an
// ally-enablable conditional CC entry is committed. Delimited CS1 block;
// CS3 will also touch champ_select.js.
function _csvRenderCcPairing(cs) {
  const block = document.getElementById("csv-sugg-cc-pairing");
  if (!block) return;
  const allyNumericIds = (cs.my_team || [])
    .map((p) => (p && (p.championId | 0)) || 0)
    .filter((x) => x > 0);
  if (!allyNumericIds.length) {
    block.hidden = true;
    return;
  }
  const allyNames = resolveChampNames(allyNumericIds);
  if (!allyNames.length) {
    // CHAMPS index not yet loaded - keep hidden, resolves next tick.
    block.hidden = true;
    return;
  }
  fetchCcPairing(allyNames, _csvScheduleRender);
  const payload = getCachedCcPairing(allyNames);
  renderCcPairing(block, payload);
}

// CS3 (2026-06-08): the action-queue combo host wrapper moved to
// active_match.js - the combo timeline reads the live champion mid-game now,
// not the locked champ-select pick.

function _csvAdaptKey(champion, enemyIds, baseSummoners, role) {
  return [
    champion || "",
    (enemyIds || []).join(","),
    (baseSummoners || []).join(","),
    role || "",
  ].join("|");
}

function _csvFetchAdaptiveSummoners(champion, enemyIds, baseSummoners, role) {
  if (!champion) return;
  const key = _csvAdaptKey(champion, enemyIds, baseSummoners, role);
  if (_CSV_ADAPT_CACHE[key] || _CSV_ADAPT_INFLIGHT[key]) return;
  _CSV_ADAPT_INFLIGHT[key] = true;
  const url = `/api/champ-select/adaptive-summoners`
            + `?champion=${encodeURIComponent(champion)}`
            + `&enemy_ids=${encodeURIComponent((enemyIds || []).join(","))}`
            + `&base=${encodeURIComponent((baseSummoners || []).join(","))}`
            + `&role=${encodeURIComponent(role || "")}`;
  fetch(url, { cache: "no-store" })
    .then((r) => r.ok ? r.json() : null)
    .then((data) => {
      _CSV_ADAPT_INFLIGHT[key] = false;
      if (data && data.ok) {
        _CSV_ADAPT_CACHE[key] = data;
        _csvScheduleRender();
      }
    })
    .catch(() => { _CSV_ADAPT_INFLIGHT[key] = false; });
}

// s171.8: shared storage key with item_build.js (_ibStorageKey). Picking
// a variant here in champ-select pre-selects the same row in the in-game
// build chooser without a separate plumbing layer.
function _csvStorageKey(champion) { return "rc-ingame-build-" + (champion || ""); }
function _csvSavedChoice(champion) {
  try { return localStorage.getItem(_csvStorageKey(champion)) || ""; }
  catch (_) { return ""; }
}
function _csvSaveChoice(champion, variantKey) {
  try { localStorage.setItem(_csvStorageKey(champion), variantKey); }
  catch (_) {}
}

// Item 240 part-3 (3c, 2026-06-01): the SR build chooser now persists
// BOTH a build choice AND a rune choice per champion so the operator
// is not re-choosing the rune every champ-select. The build choice
// stays in `rc-ingame-build-<champ>` (a plain variant/path string)
// because item_build.js's _ibSavedChoice reads that exact key to pre-
// select the in-game item-shop row - changing its FORMAT would break
// that cross-panel pre-select. The rune choice lives in a SEPARATE
// sibling key `rc-cs-rune-<champ>` so the {variantKey, runeKey} pair
// is reconstructable while existing variant-only entries keep working
// untouched (back-compat: a champ with no rune key just returns "").
function _csvRuneStorageKey(champion) { return "rc-cs-rune-" + (champion || ""); }
function _csvSavedRuneChoice(champion) {
  try { return localStorage.getItem(_csvRuneStorageKey(champion)) || ""; }
  catch (_) { return ""; }
}
function _csvSaveRuneChoice(champion, runeKey) {
  try { localStorage.setItem(_csvRuneStorageKey(champion), runeKey); }
  catch (_) {}
}
// Convenience accessor returning the persisted {variantKey, runeKey}
// pair. variantKey may be the legacy plain form or the item-178
// "<variant>:<path-key>" colon form; both are preserved verbatim.
function _csvSavedSelection(champion) {
  return {
    variantKey: _csvSavedChoice(champion),
    runeKey:    _csvSavedRuneChoice(champion),
  };
}

// Item 240 part-3 (3d, 2026-06-01): per-category auto-push checkbox
// state for the SR-build-chooser header control. GLOBAL (not per-
// champion) so the operator's "always push my runes" intent rides
// across champ-selects. DEFAULT first-run = ALL UNCHECKED (opt-in -
// nothing auto-pushes until the operator marks a category). Stored as
// a 3-key JSON blob; missing/corrupt -> all-off.
const _CSV_PUSH_CATS = ["runes", "spells", "build"];
function _csvPushFlagsStorageKey() { return "rc-cs-push-flags"; }
function _csvGetPushFlags() {
  const off = { runes: false, spells: false, build: false };
  try {
    const raw = localStorage.getItem(_csvPushFlagsStorageKey());
    if (!raw) return off;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return off;
    return {
      runes:  !!parsed.runes,
      spells: !!parsed.spells,
      build:  !!parsed.build,
    };
  } catch (_) { return off; }
}
function _csvSetPushFlag(cat, on) {
  if (_CSV_PUSH_CATS.indexOf(cat) < 0) return;
  const flags = _csvGetPushFlags();
  flags[cat] = !!on;
  try { localStorage.setItem(_csvPushFlagsStorageKey(), JSON.stringify(flags)); }
  catch (_) {}
}

// --- Phase 3 (s176, 2026-05-12) - archetype scorer picker ---------------
//
// Six canonical archetypes; carry/bruiser/tank have real scorers today
// (ds.dps / ds.hybrid / ds.ehp), the rest are placeholders for Phases
// 4-6. Order matches core/archetype_picks.ARCHETYPES so the UI is stable
// across language changes and re-renders. Implemented set tracked
// separately so we can gray-out the unimplemented ones without removing
// them - operator sees the full taxonomy.
// s209: all 6 scorers shipped - flipped `implemented: false -> true` for
// mage/assassin/enchanter and pointed to their dedicated scorers
// (ability DPS / burst / HPS) per Phases 4-6 (s179/s180/s181). Pre-s209
// the dispatcher routed these to ds.dps as a placeholder; that fallback
// path is gone. Source of truth for unit suffixes is web/js/lib/scorer_units.js.
const _CSV_ARCHETYPES = [
  { key: "carry",     label: "Carry",     implemented: true, scorer: "DPS" },
  { key: "bruiser",   label: "Bruiser",   implemented: true, scorer: "Hybrid" },
  { key: "tank",      label: "Tank",      implemented: true, scorer: "EHP" },
  { key: "mage",      label: "Mage",      implemented: true, scorer: "Ability DPS" },
  { key: "assassin",  label: "Assassin",  implemented: true, scorer: "Burst" },
  { key: "enchanter", label: "Enchanter", implemented: true, scorer: "HPS" },
];

function _csvArchetypeStorageKey(champion) { return "rc-cs-archetype-" + (champion || ""); }
function _csvSavedArchetype(champion) {
  try { return localStorage.getItem(_csvArchetypeStorageKey(champion)) || ""; }
  catch (_) { return ""; }
}
function _csvSaveArchetype(champion, key) {
  try { localStorage.setItem(_csvArchetypeStorageKey(champion), key); }
  catch (_) {}
}

// Per-champion cached pick from /api/cs-archetype-pick. Map keyed by
// champion display name. Fetched once per champion change; the picker
// re-renders when the fetch lands. Same pattern as _CSV_DS_CACHE.
const _CSV_ARCH_CACHE = Object.create(null);
const _CSV_ARCH_INFLIGHT = Object.create(null);

function _csvFetchArchetype(champion) {
  if (!champion) return;
  if (_CSV_ARCH_CACHE[champion] || _CSV_ARCH_INFLIGHT[champion]) return;
  _CSV_ARCH_INFLIGHT[champion] = true;
  fetch("/api/cs-archetype-pick?champion=" + encodeURIComponent(champion), {
    cache: "no-store",
  })
    .then((r) => r.ok ? r.json() : null)
    .then((data) => {
      _CSV_ARCH_INFLIGHT[champion] = false;
      if (data && data.ok && data.pick) {
        _CSV_ARCH_CACHE[champion] = data.pick;
        // s209 v2: rAF-coalesced - see _csvScheduleRender.
        _csvScheduleRender();
      }
    })
    .catch(() => { _CSV_ARCH_INFLIGHT[champion] = false; });
}

// Resolve which archetype to highlight. Priority: localStorage (instant)
// -> cached fetch (server-side override) -> "" (no selection yet, picker
// shows nothing pre-selected and the row is dim).
function _csvResolveArchetype(champion) {
  if (!champion) return { key: "", source: "" };
  const local = _csvSavedArchetype(champion);
  if (local && _CSV_ARCHETYPES.some((a) => a.key === local)) {
    return { key: local, source: "local" };
  }
  const fetched = _CSV_ARCH_CACHE[champion];
  if (fetched && fetched.primary) {
    return { key: fetched.primary, source: fetched.source || "default" };
  }
  return { key: "", source: "" };
}

// Operator (2026-05-23) item 164: push all 4 build variants to LCU so
// they live in the in-game item-shop "Recommended Items" dropdown. The
// agent (apply_item_sets_batch, lcu_agent.py L1031+) replaces
// each variant by-uid, leaving other RC- sets intact. Debounced via a
// last-push key so re-renders during the same champ-select session
// don't re-PUT the same payload. NOOP in mock mode (LCU agent returns
// "no summoner" - swallowed).
const _CSV_LAST_PUSH_KEY = { value: "" };
function _csvMaybePushBuildsToLCU(champion, mode, variants) {
  if (!champion || !Array.isArray(variants) || !variants.length) return;
  // Item 178 (2026-05-24): flatten collapsed variants into their
  // build_paths so the in-game item-shop dropdown carries one set per
  // build path (not one set per champion). Pre-item-178 a collapsed
  // variant would push only the primary path's items because the
  // variant-level item_ids field is populated from path[0]; this
  // missed paths 2..N. Each path's set carries a distinct set_uid so
  // apply_item_sets_batch's replace-by-uid leaves them coexisting.
  const pushUnits = [];
  for (const v of variants) {
    if (!v || v.key === "empty") continue;
    const paths = Array.isArray(v.build_paths) ? v.build_paths : [];
    if (paths.length) {
      for (const p of paths) {
        if (p && Array.isArray(p.item_ids) && p.item_ids.length) {
          pushUnits.push({
            uidKey: `${v.key}-${p.key || "path"}`,
            label:  `${v.label || v.key} - ${p.label || p.key || "Variant"}`,
            item_ids: (p.item_ids || []).slice(0, 6).map((x) => String(x)),
          });
        }
      }
    } else if (Array.isArray(v.item_ids) && v.item_ids.length) {
      // Legacy single-variant entry (ARAM/Arena/experimental).
      pushUnits.push({
        uidKey: v.key || "default",
        label:  v.label || v.key || "Build",
        item_ids: (v.item_ids || []).slice(0, 6).map((x) => String(x)),
      });
    }
  }
  if (!pushUnits.length) return;
  const itemSig = pushUnits.map((u) =>
    `${u.uidKey}:${u.item_ids.join(",")}`).join("|");
  const key = `${champion}|${mode || "sr"}|${itemSig}`;
  if (_CSV_LAST_PUSH_KEY.value === key) return;
  _CSV_LAST_PUSH_KEY.value = key;
  // Cap at 4 sets to match the historical apply_item_sets_batch
  // budget (item 164); the in-game dropdown holds more but the
  // operator picked 4 as the sweet spot for the recommended-items
  // surface.
  const sets = pushUnits.slice(0, 4).map((u, i) => ({
    set_uid:     `RC-${champion}-${mode || "sr"}-${u.uidKey}`,
    title:       `RC ${i + 1}: ${u.label}`.slice(0, 50),
    champion_id: 0,
    blocks: [{
      type: u.label,
      items: u.item_ids.map((iid) => ({ id: String(iid), count: 1 })),
    }],
  }));
  if (!sets.length) return;
  // Item 188 Slice B (2026-05-25): PRE-PUSH wipe of stale RC- sets
  // that don't match the current {champion, mode}. Without this, each
  // champ-select swap or mode-switch leaves the prior 4 RC- sets behind
  // (replace-by-uid only overwrites matching uids), so a session
  // cycling 2-3 champions across SR/ARAM/Arena accumulates 20+ stale
  // entries in the in-game item-shop dropdown. The wipe handler keeps
  // operator's own custom (non-RC-) sets + this scope's RC- sets so
  // the apply_item_sets_batch right below is idempotent.
  try {
    lcuCmd({
      cmd: "delete_stale_rc_item_sets",
      active_champion: champion,
      active_mode: mode || "sr",
    });
  } catch (_) {}
  try { lcuCmd({ cmd: "apply_item_sets_batch", sets }); } catch (_) {}
}

// Item 240 part-3 (3e, 2026-06-01): resolve the currently-active build
// card for this champion+mode so the per-category push helpers know
// which variant/path to push. Reads the persisted selection (sticky)
// and falls back to the first variant / its primary path. Returns
// {variant, composedKey, summoners} where composedKey is the
// "<variant>:<path-key>" colon form when the variant carries
// build_paths (so the resolver overlays the active path's items/runes),
// else the bare variant key.
function _csvActiveBuildSelection(champion, mode, variants) {
  if (!Array.isArray(variants) || !variants.length) return null;
  const saved = _csvSavedChoice(champion);
  const savedVariant = saved ? saved.split(":")[0] : "";
  let v = variants.find((x) => x && x.key === savedVariant) || variants[0];
  if (!v || !v.key || v.key === "empty") return null;
  const paths = Array.isArray(v.build_paths) ? v.build_paths : [];
  let composedKey = v.key;
  if (paths.length) {
    let pathKey = "";
    if (saved && saved.startsWith(v.key + ":")) {
      pathKey = saved.slice(v.key.length + 1);
    }
    if (!pathKey) {
      const primaryPath = paths.find((p) => p && p._is_primary);
      pathKey = (primaryPath && primaryPath.key) || (paths[0] && paths[0].key) || "";
    }
    if (pathKey) composedKey = `${v.key}:${pathKey}`;
  }
  const summoners = Array.isArray(v.summoners) ? v.summoners.slice(0, 2) : [];
  return { variant: v, composedKey, summoners };
}

// Item 240 part-3 (3e): push a SINGLE category to the LCU for the
// currently-active build card. The header-control checkbox auto-push
// (uncheck->check + subsequent in-category selection changes while
// checked) and the manual [PUSH] button both funnel through here.
//   - "build"  -> apply_item_sets_batch route (push_items only) via the
//                 colon-form variant key so the resolver overlays the
//                 active path's item set.
//   - "runes"  -> apply route (push_runes only); colon-form picks the
//                 active card's per-path keystone/primary/secondary.
//   - "spells" -> set_summoner_spell x2 (D + F) from the active
//                 variant's summoner pair (matches the strip's verb).
function _csvPushCategory(champion, mode, cat, variants) {
  if (!champion || _CSV_PUSH_CATS.indexOf(cat) < 0) return;
  const sel = _csvActiveBuildSelection(champion, mode, variants);
  if (!sel) return;
  if (cat === "build") {
    _csvApplyLoadout(champion, sel.composedKey, mode, null, null, null,
      { push_runes: false, push_items: true, push_summoners: false });
  } else if (cat === "runes") {
    // 3b: the rune selection is INDEPENDENT of the active build card.
    // If the operator has a sticky rune choice that matches a DIFFERENT
    // build path's keystone, push THAT path's composed key so the
    // resolver overlays the selected rune (not the active card's rune).
    // Falls back to the active card's composed key when no sticky rune
    // (or it matches the active card already).
    const savedRuneKey = _csvSavedRuneChoice(champion);
    let runeComposedKey = sel.composedKey;
    let overrideRunes = null;
    if (savedRuneKey) {
      const paths = Array.isArray(sel.variant.build_paths)
        ? sel.variant.build_paths : [];
      const runePath = paths.find((p) =>
        p && String((p.keystone) || sel.variant.keystone || "") === savedRuneKey);
      if (runePath && runePath.key) {
        runeComposedKey = `${sel.variant.key}:${runePath.key}`;
      } else if (savedRuneKey === String(sel.variant.auto_keystone || "")
                 && sel.variant.auto_primary && sel.variant.auto_secondary) {
        // The auto-applied keystone (rune_recommendations) is NOT one of the
        // build-path cards, so the path lookup above misses it. Push it
        // explicitly via override_runes so the written page matches the
        // selected (recommended) rune instead of silently falling back to the
        // active card's keystone.
        overrideRunes = {
          keystone:  String(sel.variant.auto_keystone),
          primary:   String(sel.variant.auto_primary),
          secondary: String(sel.variant.auto_secondary),
        };
      }
    }
    _csvApplyLoadout(champion, runeComposedKey, mode, null, overrideRunes, null,
      { push_runes: true, push_items: false, push_summoners: false });
  } else if (cat === "spells") {
    const pair = sel.summoners;
    const d = pair[0] | 0;
    const f = pair[1] | 0;
    if (d) { try { lcuCmd({ cmd: "set_summoner_spell", slot: 1, spellId: d }); } catch (_) {} }
    if (f && f !== d) { try { lcuCmd({ cmd: "set_summoner_spell", slot: 2, spellId: f }); } catch (_) {} }
  }
}

// Item 240 part-3 (3e): push ALL currently-checked categories now (the
// [PUSH] button's manual force-push). Reads the global push flags + the
// active selection; a no-op when no category is checked.
function _csvPushCheckedCategories(champion, mode, variants) {
  const flags = _csvGetPushFlags();
  _CSV_PUSH_CATS.forEach((cat) => {
    if (flags[cat]) _csvPushCategory(champion, mode, cat, variants);
  });
}

// Operator (2026-05-23): summoner spell strip. Mode-keyed list - SR
// carries 9 SR-legal spells, ARAM swaps out Smite + Teleport for Mark
// (Snowball, id 32) + Clarity (id 13). Selected cell ids come from
// _csvSpellPair (module-level [d, f]); click rotates slot D -> F -> D
// and pushes via set_summoner_spell. Recommended usage % is a rough
// mock - wiring the operator's match-history pivot is a follow-up.
const _CSV_SUMM_STRIP_SR = [
  { id: 4,  name: "Flash",    pct: 95 },
  { id: 7,  name: "Heal",     pct: 60 },
  { id: 14, name: "Ignite",   pct: 20 },
  { id: 12, name: "Teleport", pct:  6 },
  { id: 1,  name: "Cleanse",  pct: 12 },
  { id: 21, name: "Barrier",  pct:  8 },
  { id: 3,  name: "Exhaust",  pct:  4 },
  { id: 6,  name: "Ghost",    pct:  2 },
  { id: 11, name: "Smite",    pct:  0 },
];
const _CSV_SUMM_STRIP_ARAM = [
  { id: 4,  name: "Flash",    pct: 95 },
  { id: 32, name: "Mark",     pct: 88 },
  { id: 7,  name: "Heal",     pct: 35 },
  { id: 1,  name: "Cleanse",  pct: 20 },
  { id: 21, name: "Barrier",  pct: 18 },
  { id: 3,  name: "Exhaust",  pct: 12 },
  { id: 14, name: "Ignite",   pct: 10 },
  { id: 13, name: "Clarity",  pct:  6 },
  { id: 6,  name: "Ghost",    pct:  4 },
];
// Module-level state - tracks current D / F pair + next-click slot
// pointer. Reset to [0, 0] / slot=1 between champion-pick rerenders.
let _csvSpellPair = [0, 0];
let _csvNextSpellSlot = 1;
function _csvSummSpellListFor(mode) {
  return (mode === "aram") ? _CSV_SUMM_STRIP_ARAM : _CSV_SUMM_STRIP_SR;
}
function _csvSpellSlotLabel(spellId) {
  if (spellId && spellId === _csvSpellPair[0]) return "D";
  if (spellId && spellId === _csvSpellPair[1]) return "F";
  return "";
}
function _csvSummSpellStripHtml(currentSpells, mode) {
  const list = _csvSummSpellListFor(mode);
  const selected = new Set((currentSpells || []).map((s) => s | 0));
  const cells = list.map((sp) => {
    const isSel = selected.has(sp.id);
    const slotLbl = _csvSpellSlotLabel(sp.id);
    const url = sumImg(sp.id);
    const icon = url
      ? `<img class="csv-summspell-icon" src="${url}" alt="${sp.name}" onerror="this.style.display='none'">`
      : `<span class="csv-summspell-icon" aria-hidden="true">?</span>`;
    const badge = slotLbl
      ? `<span class="csv-summspell-slot">${slotLbl}</span>`
      : "";
    return `
      <button type="button" class="csv-summspell-cell${isSel ? " is-selected" : ""}"
              data-spell-id="${sp.id}" data-spell-name="${sp.name}"
              title="${sp.name} - ${sp.pct}% recommended usage">
        ${icon}${badge}
        <div class="csv-summspell-pct">${sp.pct}%</div>
      </button>`;
  }).join("");
  return `<div class="csv-summspell-strip" id="csv-summspell-strip">${cells}</div>`;
}
function _csvRefreshSpellBadges(scope) {
  if (!scope) return;
  scope.querySelectorAll(".csv-summspell-cell").forEach((cell) => {
    const sid = parseInt(cell.dataset.spellId, 10) | 0;
    const slotLbl = _csvSpellSlotLabel(sid);
    const isSel = !!slotLbl;
    cell.classList.toggle("is-selected", isSel);
    let badge = cell.querySelector(".csv-summspell-slot");
    if (slotLbl) {
      if (!badge) {
        badge = document.createElement("span");
        badge.className = "csv-summspell-slot";
        const iconEl = cell.querySelector(".csv-summspell-icon");
        if (iconEl && iconEl.nextSibling) {
          cell.insertBefore(badge, iconEl.nextSibling);
        } else {
          cell.appendChild(badge);
        }
      }
      badge.textContent = slotLbl;
    } else if (badge) {
      badge.remove();
    }
  });
}

function _csvArchetypePickerHtml(champion) {
  if (!champion) return "";
  const resolved = _csvResolveArchetype(champion);
  const buttons = _CSV_ARCHETYPES.map((a) => {
    const cls = ["csv-arch-btn"];
    if (a.key === resolved.key) cls.push("active");
    if (!a.implemented) cls.push("placeholder");
    return `<button class="${cls.join(" ")}" data-arch="${a.key}"`
         + ` title="${a.label} -> ds.${a.scorer.toLowerCase().split(" ")[0]}">`
         + `<span class="csv-arch-label">${a.label}</span>`
         + `<span class="csv-arch-scorer">${a.scorer}</span>`
         + `</button>`;
  }).join("");
  // s212 v3: dropped the "overridden" / "auto" source pill - duplicate
  // of the AUTO button's active state (green-active = auto, grey =
  // overridden). The AUTO button alone carries both signals: when
  // green it's the active mode; when grey-clickable it means "click
  // to revert from override". Audit must-fix #2 closed.
  const isAuto = (resolved.source === "default" || resolved.source === "");
  const autoBtn = `<button class="csv-arch-auto${isAuto ? " is-active" : ""}"
                           data-champion="${champion}"
                           title="${isAuto ? 'currently auto-derived from DDragon tags' : 'click to revert to DDragon-tag default'}">AUTO</button>`;
  // Operator (2026-05-25 item 200 Slice D): the DS-top-picks preview
  // row that lived under the 6 archetype buttons (item 168) is removed.
  // The freed vertical space is filled by the PICK sub-panel moved up
  // from Pick & Ban into the same top-left card. See `csv-picks-target`
  // mount in web/index.html + _csvRenderPickBan split below.
  return `
    <div class="csv-archetype-picker" data-champion="${champion}">
      <div class="csv-archetype-title">
        <span>Daemon Slayer build archetype</span>
        ${autoBtn}
      </div>
      <div class="csv-archetype-buttons">${buttons}</div>
    </div>`;
}

function _csvWireArchetypePicker(scope) {
  const wrap = scope.querySelector(".csv-archetype-picker");
  if (!wrap) return;
  const champion = wrap.dataset.champion || "";
  if (!champion) return;
  wrap.querySelectorAll(".csv-arch-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const arch = btn.dataset.arch || "";
      if (!arch) return;
      // Save locally for instant subsequent renders, then POST to
      // persist server-side. Match the existing build-chooser pattern.
      _csvSaveArchetype(champion, arch);
      // Optimistic update of the cached pick so the next render shows
      // the active state without waiting for the POST round-trip.
      _CSV_ARCH_CACHE[champion] = Object.assign(
        {}, _CSV_ARCH_CACHE[champion] || {},
        { primary: arch, source: "user_cs", champion },
      );
      // s214: invalidate any cached DS entries for OTHER archetypes
      // on this champion so the experimental row's items refresh with
      // the new scorer. The DS cache key is `${champion}|${dsMode}|${arch}`
      // so we drop every entry whose champion+dsMode matches but arch
      // does not. Net effect: clicking Tank -> Bruiser drops the cached
      // Tank ranking and triggers a fresh `/api/ds-preview` POST with
      // `archetype: "bruiser"` next render.
      Object.keys(_CSV_DS_CACHE).forEach((k) => {
        if (k.startsWith(`${champion}|`) && !k.endsWith(`|${arch}`)) {
          delete _CSV_DS_CACHE[k];
        }
      });
      Object.keys(_CSV_DS_INFLIGHT).forEach((k) => {
        if (k.startsWith(`${champion}|`) && !k.endsWith(`|${arch}`)) {
          delete _CSV_DS_INFLIGHT[k];
        }
      });
      fetch("/api/cs-archetype-pick", {
        method: "POST", cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ champion, primary: arch, source: "user_cs" }),
      })
        .then((r) => r.ok ? r.json() : null)
        .then((data) => {
          if (data && data.ok && data.pick) {
            _CSV_ARCH_CACHE[champion] = data.pick;
          }
        })
        .catch(() => { /* localStorage already saved; next reload retries */ });
      // Update DOM directly so the operator sees the click respond
      // before the next render tick.
      wrap.querySelectorAll(".csv-arch-btn").forEach((b) => {
        b.classList.toggle("active", b.dataset.arch === arch);
      });
      _csvScheduleRender();
    });
  });
  // s211: AUTO button -> revert to DDragon-tag default. Clears the
  // local override, POSTs `{clear: true}` to drop the server-side
  // record, and re-fetches so the picker re-renders with source="default".
  const autoBtn = wrap.querySelector(".csv-arch-auto");
  if (autoBtn) {
    autoBtn.addEventListener("click", () => {
      if (autoBtn.classList.contains("is-active")) return;  // already on AUTO
      try { localStorage.removeItem(_csvArchetypeStorageKey(champion)); } catch (_) {}
      // s214: drop the user-archetype DS cache so the experimental row
      // re-fetches with the about-to-be-resolved default archetype.
      // We don't know which archetype the server will default to yet,
      // so blow away everything for this champion + dsMode pair.
      Object.keys(_CSV_DS_CACHE).forEach((k) => {
        if (k.startsWith(`${champion}|`)) delete _CSV_DS_CACHE[k];
      });
      Object.keys(_CSV_DS_INFLIGHT).forEach((k) => {
        if (k.startsWith(`${champion}|`)) delete _CSV_DS_INFLIGHT[k];
      });
      // Drop server-side; the endpoint accepts `{champion, clear: true}`.
      fetch("/api/cs-archetype-pick", {
        method: "POST", cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ champion, clear: true }),
      })
        .then((r) => r.ok ? r.json() : null)
        .then((data) => {
          // Clear our cache so the next fetch reloads the default.
          delete _CSV_ARCH_CACHE[champion];
          delete _CSV_ARCH_INFLIGHT[champion];
          if (data && data.ok && data.pick) {
            _CSV_ARCH_CACHE[champion] = data.pick;
          }
          _csvScheduleRender();
        })
        .catch(() => {
          delete _CSV_ARCH_CACHE[champion];
          _csvScheduleRender();
        });
    });
  }
}

// Convert the view's adapt-mode to the DS engine's mode label.
function _csvDsModeFor(mode) {
  if (mode === "aram")  return "ARAM";
  if (mode === "arena") return "ARENA";
  return "SR";
}

// s214: cache key extended to include the active archetype so a
// mid-CS swap (Tank -> Bruiser via the archetype picker) invalidates
// the experimental row's items and re-fetches with the new scorer.
// Pre-s214 the experimental row served stale ds.dps rankings for the
// full champ-select session regardless of archetype clicks. Helper
// returns the key + archetype string so callers can pass it through
// to /api/ds-preview (the s184 backend dispatcher already routes
// `archetype` -> rank_for_primary_archetype).
function _csvDsCacheKey(champion, dsMode, archetype) {
  const a = archetype || "";
  return `${champion}|${dsMode}|${a}`;
}

// Fire the DS engine for this champion + mode + archetype. Non-blocking
// - the next renderChampSelectView tick (~1Hz from the LCU state push)
// picks up the cached result. ``level=6`` matches the legacy overlay's
// preview level so the rankings match between views.
function _csvFetchDsBuilds(champion, dsMode, archetype) {
  if (!champion || !dsMode) return;
  const key = _csvDsCacheKey(champion, dsMode, archetype);
  if (_CSV_DS_CACHE[key] || _CSV_DS_INFLIGHT[key]) return;
  _CSV_DS_INFLIGHT[key] = true;
  const body = { champion, mode: dsMode, level: 6, items: [] };
  if (archetype) body.archetype = archetype;
  fetch("/api/ds-preview", {
    method: "POST", cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
    .then((r) => r.ok ? r.json() : null)
    .then((data) => {
      _CSV_DS_INFLIGHT[key] = false;
      if (data && data.ok && Array.isArray(data.ranked) && data.ranked.length) {
        _CSV_DS_CACHE[key] = data.ranked;
        // s209: trigger a CS re-render so the build chooser picks up
        // the fresh cache. s209 v2: routed through _csvScheduleRender so
        // simultaneous fetches don't trigger N back-to-back innerHTML
        // rebuilds (the visible build-chooser flicker on cold load).
        _csvScheduleRender();
      }
    })
    .catch(() => { _CSV_DS_INFLIGHT[key] = false; });
}

// s171.8: fetch user-curated variants (loadout_resolver). Mode label is
// the lower-case form ("sr"/"aram"/"arena") matching the legacy
// chooser's contract - `/api/loadout/list` normalises internally.
// s214 v2: "brawl" dropped from the mode set (mode retired from rotation).
function _csvFetchUserVariants(champion, mode) {
  if (!champion || !mode) return;
  const key = `${champion}|${mode}`;
  if (_CSV_USER_CACHE[key] !== undefined || _CSV_USER_INFLIGHT[key]) return;
  _CSV_USER_INFLIGHT[key] = true;
  // UI scale v2.1 page #8 audit (2026-05-23): when body.dataset.uiMock
  // === "1", short-circuit the live POST and seed the cache from the
  // mock fixture so the build chooser renders the operator-curated
  // variants alongside the rest of the mocked champ-select state.
  const isMock = !!(document && document.body && document.body.dataset.uiMock === "1");
  if (isMock) {
    fetch("/data/ui_mock/champ_select_sr.json", { cache: "no-store" })
      .then((r) => (r && r.ok ? r.json() : null))
      .then((data) => {
        _CSV_USER_INFLIGHT[key] = false;
        const bv = (data && data.build_variants) || {};
        _CSV_USER_CACHE[key] = Array.isArray(bv[key]) ? bv[key] : [];
        if (_CSV_USER_CACHE[key].length) _csvScheduleRender();
      })
      .catch(() => { _CSV_USER_INFLIGHT[key] = false; _CSV_USER_CACHE[key] = []; });
    return;
  }
  // item 186: dedupFetch coalesces with item_build.js's parallel POSTs
  // for the same (champion, mode) tuple within the 100ms render-storm
  // grace window.
  dedupFetch("/api/loadout/list", {
    method: "POST", cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ champion, mode }),
  })
    .then((r) => r.ok ? r.json() : null)
    .then((data) => {
      _CSV_USER_INFLIGHT[key] = false;
      // Mark "empty" with [] (truthy in lookup) so we don't refetch
      // forever for champions/modes with no user variants saved.
      const variants = (data && Array.isArray(data.variants))
        ? data.variants : [];
      _CSV_USER_CACHE[key] = variants;
      // s209 v2: rAF-coalesced - see _csvScheduleRender.
      if (variants.length) _csvScheduleRender();
    })
    .catch(() => {
      _CSV_USER_INFLIGHT[key] = false;
      _CSV_USER_CACHE[key] = [];
    });
}

// Build chooser variants for the central pane. s171: returns DS-engine-
// ranked items when available (cached per champion+mode), otherwise a
// "computing..." placeholder. Mode-specific keystone hints distinguish
// the 3 rows visually - same items in each row for now (Phase B-2 will
// produce per-keystone variants once the loadout resolver is wired).
function _csvBuildVariantsFor(cid, name, mode, cs) {
  if (!cid || !name) {
    return [{ key: "empty", label: "no champion yet - hover or lock to see builds",
              keystone: "-", item_ids: [], is_default: true }];
  }
  const dsMode = _csvDsModeFor(mode);
  // s214: include the resolved archetype primary in the DS cache key so
  // a mid-CS archetype swap (operator clicks Tank -> Bruiser) re-fetches
  // with the new scorer. Empty archetype string defaults to ds.dps (the
  // dispatcher's `fell_back=True` path for unimplemented archetypes pre-
  // s182 - preserves behavior for callers that don't pass archetype).
  const archResolved = _csvResolveArchetype(name);
  const archKey = (archResolved && archResolved.key) || "";
  // s211 v2 fix: default to empty array when cache is cold - pre-fix
  // `ranked.slice(0, 6)` below threw "Cannot read properties of
  // undefined (reading 'slice')" and aborted the whole render.
  const ranked = _CSV_DS_CACHE[_csvDsCacheKey(name, dsMode, archKey)] || [];
  // Always trigger the user-variant fetch + DS fetch in parallel. s210
  // dropped the DS pseudo-row from the build chooser - DS engine output
  // now renders in the Suggestions panel - but we still need DS data
  // for the experimental row's item set (DS top picks under the hood)
  // and for `/api/champ-select/adaptive-summoners` enemy classification.
  _csvFetchUserVariants(name, mode || "sr");
  if (!ranked.length) {
    _csvFetchDsBuilds(name, dsMode, archKey);
  }
  // s209 v2: pull enemy ids + role for the adaptive-summoner pipeline.
  // Empty enemy_ids during early CS is fine - the recommendation will
  // be the base pair (no swap) until enemies lock.
  const enemyIds = cs
    ? ((cs.their_team || []).map((p) => (p && p.championId) | 0).filter((x) => x > 0))
    : [];
  const role = cs ? _csvResolveRole(cs) : "";
  const userVariants = _CSV_USER_CACHE[`${name}|${mode || "sr"}`] || [];
  // User-variant rows carry their own keystone / primary / secondary /
  // summoners / item_ids from the loadout file. s209 preserves all four
  // fields through the mapper so the row renderer can show the full
  // rune + spell strip; pre-s209 the mapper dropped primary/secondary/
  // summoners and the strip rendered only the keystone caption.
  const userRows = userVariants.map((v) => {
    const baseSumm = Array.isArray(v.summoners) ? v.summoners : [];
    // s209 v2: fetch adaptive summoners keyed on (variant base summoners,
    // enemy roster, role). When the recommendation lands, the rendered
    // row swaps to it + stamps swap metadata for the visual cue. The
    // variant's stored base is preserved on the row so a future "revert
    // to stored" toggle has a value to fall back to.
    _csvFetchAdaptiveSummoners(name, enemyIds, baseSumm, role);
    const adapt = _CSV_ADAPT_CACHE[_csvAdaptKey(name, enemyIds, baseSumm, role)];
    const summoners = (adapt && Array.isArray(adapt.summoners))
      ? adapt.summoners
      : baseSumm;
    // Item 178 (2026-05-24): collapsed SR variant carries build_paths[]
    // (one per source variant in the operator's prior config). When
    // present, the row renders as ONE champion entry with N labeled
    // build-path rows stacked vertically inside. Each path's items +
    // (optional) runes / summoners override the variant-level fields
    // on click. backend route serves the resolved item_ids per path
    // so the frontend doesn't have to re-call ddragon resolution.
    const buildPaths = Array.isArray(v.build_paths) ? v.build_paths : [];
    return {
      key:        v.key,
      label:      v.label || v.key,
      keystone:   v.keystone  || "user variant",
      primary:    v.primary   || "",
      secondary:  v.secondary || "",
      summoners,
      summoners_base: baseSumm,
      adapt:      adapt || null,   // {swapped, swap_from, swap_to, reason}
      item_ids:   v.item_ids  || [],
      reasons:    {},
      is_default: false,
      is_user:    true,
      collapsed:  !!v._collapsed,
      build_paths: buildPaths,
    };
  });
  // item 213 (2026-05-28): the synthetic "experimental" auto-build row
  // was removed from every champion + mode per operator request. The
  // chooser now shows only the operator's curated + user-build rows.
  // DS engine output still surfaces via the DS Build Archetype preview
  // (Pick & Ban panel) + the DS vs Enemy Comp card (build_order.js).
  return userRows;
}

// Item 178 (2026-05-24): render a single build-path row inside a
// collapsed variant. Each path renders as a labeled pill + 6 item
// icons stacked horizontally. Click selects the path (highlight +
// persist) and fires the LCU push via _csvApplyLoadout with the
// `<variant>:<path-key>` form so the backend resolver overlays the
// path's items / runes / summoners on the variant.
function _csvBuildPathRowHtml(variantKey, path, isActive, ver) {
  const items = (path.item_ids || []).slice(0, 6).map((iid) => {
    const lolHtml = itemTooltipHtml(iid);
    const ttAttr = lolHtml ? ` data-tt-html="${lolHtml.replace(/"/g, "&quot;")}"` : "";
    return `
      <div class="csv-build-path-item"${ttAttr}>
        <img src="/data/ddragon/${ver}/img/item/${iid}.png"
             onerror="if(!this.dataset.cdn){this.dataset.cdn=1;this.src='https://ddragon.leagueoflegends.com/cdn/${ver}/img/item/${iid}.png'}else{this.style.display='none'}"
             alt="">
      </div>`;
  }).join("") || '<div class="csv-empty">-</div>';
  const label = path.label || path.key || "Variant";
  const archAttr = path._archetype ? ` data-arch="${path._archetype}"` : "";
  const primaryAttr = path._is_primary ? ' data-primary="1"' : "";
  // Item 240 part-3 (3b): carry the card's keystone so a path-row click
  // can re-point the rune panel's amber (recommended) marker to it. The
  // path's keystone falls back to the variant-level keystone (resolver
  // does the same), supplied by the caller as `path.keystone`.
  const ksAttr = path.keystone ? ` data-card-keystone="${path.keystone}"` : "";
  return `
    <div class="csv-build-path-row${isActive ? " is-active" : ""}"
         data-variant="${variantKey}"
         data-path-key="${path.key || ""}"${archAttr}${primaryAttr}${ksAttr}>
      <div class="csv-build-path-label" title="${label}">${label}</div>
      <div class="csv-build-path-items">${items}</div>
    </div>`;
}

// Item 240 part-3 (3a/3b, 2026-06-01): the nested RUNE panel that sits
// to the RIGHT of the build-path cards inside a collapsed SR variant.
// Each build path carries its own keystone (per-path runes overlay the
// variant-level runes - see loadout_resolver.list_variants); we render
// one rune option per DISTINCT keystone across the paths. Borders:
//   - GREEN  (.is-selected)    = the operator's sticky rune selection.
//   - AMBER  (.is-recommended) = the rune RECOMMENDED for the currently-
//                                active build card, shown ONLY when it
//                                differs from the sticky selection. When
//                                the operator is already on the
//                                recommended rune it is just green (no
//                                second color) - the is-recommended
//                                class is withheld in that case.
// Changing the active build card re-points the amber (recommended)
// marker but does NOT change the sticky selection (3b): the panel's
// click handler is the only thing that moves green.
function _csvRunePanelHtml(variant, recommendedRuneKey, savedRuneKey) {
  const paths = Array.isArray(variant.build_paths) ? variant.build_paths : [];
  // Collect distinct (keystone) rune options, preserving first-seen
  // order. Each option records the keystone name + its tree pair so the
  // click can persist + (later) push the right page. Skip empties.
  const seen = Object.create(null);
  const opts = [];
  paths.forEach((p) => {
    const ks = String((p && p.keystone) || variant.keystone || "").trim();
    if (!ks || seen[ks]) return;
    seen[ks] = true;
    opts.push({
      key:       ks,
      keystone:  ks,
      primary:   String((p && p.primary)   || variant.primary   || ""),
      secondary: String((p && p.secondary) || variant.secondary || ""),
    });
  });
  // Fall back to the variant-level keystone when no path carried one
  // (defensive - a collapsed variant always has at least the variant
  // keystone).
  if (!opts.length && variant.keystone) {
    opts.push({
      key:       String(variant.keystone),
      keystone:  String(variant.keystone),
      primary:   String(variant.primary || ""),
      secondary: String(variant.secondary || ""),
    });
  }
  // Ensure the AUTO-APPLIED keystone (the one lcu_rune_writer actually pushes,
  // from rune_recommendations - see loadout_resolver auto_keystone) is always
  // a visible option so it can carry the recommended marker even when it is
  // not one of the build-card keystones (Caitlyn: auto=Arcane Comet, cards=
  // PTA/Fleet/Lethal Tempo). This is what makes the panel match what the game
  // actually receives.
  const autoKs = String(variant.auto_keystone || "").trim();
  if (autoKs && !seen[autoKs]) {
    seen[autoKs] = true;
    opts.unshift({
      key:       autoKs,
      keystone:  autoKs,
      primary:   String(variant.auto_primary || ""),
      secondary: String(variant.auto_secondary || ""),
    });
  }
  if (!opts.length) {
    return '<div class="csv-rune-panel"><div class="csv-empty">no rune options</div></div>';
  }
  // Whichever option matches the saved rune key is GREEN. The
  // recommended option is AMBER only when it is NOT the saved one.
  const onRecommended = !!savedRuneKey && savedRuneKey === recommendedRuneKey;
  const rows = opts.map((o) => {
    const isSelected    = !!savedRuneKey && o.key === savedRuneKey;
    const isRecommended = o.key === recommendedRuneKey && !onRecommended && !isSelected;
    const icon = _csvKeystoneIcon(o.keystone);
    const ksHtml = keystoneTooltipHtml(o.keystone);
    const ttAttr = ksHtml
      ? ` data-tt-html="${ksHtml.replace(/"/g, "&quot;")}"`
      : (o.keystone ? ` title="${o.keystone}"` : "");
    const cls = "csv-rune-opt"
      + (isSelected ? " is-selected" : "")
      + (isRecommended ? " is-recommended" : "");
    return `
      <div class="${cls}" data-rune-key="${o.keystone}"
           data-rune-primary="${o.primary}" data-rune-secondary="${o.secondary}"${ttAttr}>
        ${icon ? `<img class="csv-rune-opt-icon" src="${icon}" onerror="this.style.display='none'" alt="">` : '<span class="csv-rune-opt-icon"></span>'}
        <span class="csv-rune-opt-name">${o.keystone}</span>
      </div>`;
  }).join("");
  return `
    <div class="csv-rune-panel">
      <div class="csv-rune-panel-title">Runes</div>
      <div class="csv-rune-opt-list">${rows}</div>
    </div>`;
}

function _csvBuildVariantRowsHtml(variants, savedChoice, savedRuneKey) {
  if (!variants || !variants.length) {
    return '<div class="csv-empty">no build variants for this champion / mode yet</div>';
  }
  const ver = (ITEMS && ITEMS.version) || "latest";
  // s171.8: pre-select the saved choice if present; else default to
  // the first row (DS engine top picks). Matches what the in-game
  // chooser does via _ibSavedChoice on the same localStorage key.
  // Item 178: saved choice can be either "<variant>" (legacy) or
  // "<variant>:<path-key>" (multi-path). Strip the path-key suffix
  // when looking up the variant idx.
  let selectedIdx = 0;
  if (savedChoice) {
    const savedVariant = savedChoice.split(":")[0];
    const found = variants.findIndex((v) => v && v.key === savedVariant);
    if (found >= 0) selectedIdx = found;
  }
  return variants.map((v, idx) => {
    const reasons = v.reasons || {};
    const items = (v.item_ids || []).slice(0, 6).map((iid) => {
      // s213: rich item tooltip from DDragon item description. Falls
      // back to scorer reason (e.g., "+18 dps") when DDragon load
      // hasn't completed yet OR when the item id isn't in the cache.
      // app-wide tooltip reads `data-tt-html` first, `title` second.
      const lolHtml = itemTooltipHtml(iid);
      const reasonAttr = reasons[iid] ? ` title="${reasons[iid]}"` : "";
      const ttAttr = lolHtml ? ` data-tt-html="${lolHtml.replace(/"/g, "&quot;")}"` : "";
      return `
      <div class="csv-build-item"${ttAttr}${reasonAttr}>
        <img src="/data/ddragon/${ver}/img/item/${iid}.png"
             onerror="if(!this.dataset.cdn){this.dataset.cdn=1;this.src='https://ddragon.leagueoflegends.com/cdn/${ver}/img/item/${iid}.png'}else{this.style.display='none'}"
             alt="">
      </div>`;
    }).join("") || '<div class="csv-empty">-</div>';
    const cb = `<div class="csv-build-checkbox"></div>`;
    // s211: variant badge replaces the row tag. Each row's label is
    // rendered as a colored pill in the same visual style as the
    // pre-s211 [experimental] tag. The color is keyed off the variant
    // key so On-Hit / Crit / Experimental each get a distinct hue.
    // No separate trailing tag - the badge IS the label.
    const tag = '';
    const badgeClass = _csvVariantBadgeClass(v);

    // s211 v3: rune line 2 is just the KEYSTONE - icon on the left,
    // keystone name spelled out as text on the right. The primary tree
    // icon (round tree-shield symbol) was dropped per operator request;
    // the keystone art IS already in the primary tree visually, so
    // showing both was redundant. Tree info still rides through the
    // apply payload - just visually elided.
    // s213: keystone gets a rich tooltip from DDragon runesReforged
    // (name + tree + short description). Falls back silently to bare
    // `title` until the JSON loads on first hover.
    const keystoneIcon = _csvKeystoneIcon(v.keystone);
    const ksHtml = keystoneTooltipHtml(v.keystone);
    // s214: rich tooltip lives ONLY on the wrapper so hovering either
    // the icon OR the spelled-out keystone name fires the same
    // DDragon-backed tooltip. Pre-s214 the img carried a bare `title`
    // (browser native tooltip) which intercepted hover and gave a
    // different/weaker UX than the wrapper's app-tooltip. Removing
    // `title` from the child lets the wrapper's data-tt-html win.
    // Fallback `title` on the wrapper for the brief window before the
    // DDragon descriptions cache resolves.
    const ksFallbackTitle = v.keystone ? ` title="${v.keystone}"` : "";
    const ksTtAttr = ksHtml ? ` data-tt-html="${ksHtml.replace(/"/g, "&quot;")}"` : ksFallbackTitle;
    const runeMainHtml = (keystoneIcon || v.keystone)
      ? `<div class="csv-build-rune-main"${ksTtAttr}>
           ${keystoneIcon ? `<img class="csv-build-rune-keystone" src="${keystoneIcon}" onerror="this.style.display='none'" alt="">` : ""}
           ${v.keystone   ? `<span class="csv-build-rune-tree-name">${v.keystone}</span>` : ""}
         </div>`
      : "";
    // s209 v2: render summoners + an adaptive-swap badge when the row's
    // adaptive recommendation differs from the variant's stored pair.
    // The displayed summoners are already overridden by the recommendation
    // (see _csvBuildVariantsFor); the badge surfaces *why* the swap fired
    // (CC threat / burst threat / etc.) so the operator can sanity-check.
    const summoners = Array.isArray(v.summoners) ? v.summoners.slice(0, 2) : [];
    const adapt = v.adapt || null;
    const swappedSecondary = adapt && adapt.swapped;
    const spellTooltip = (sid, isSecondary) => {
      const nm = sumName(sid) || `spell ${sid}`;
      if (isSecondary && swappedSecondary && adapt) {
        return `${nm} (swapped from ${adapt.swap_from || "?"} . ${adapt.reason || ""})`;
      }
      return nm;
    };
    const spellsHtml = summoners.length
      ? `<span class="csv-build-spells">${summoners.map((sid, idx) => {
          const isSecondary = idx === 1;
          const url = sumImg(sid);
          const tip = spellTooltip(sid, isSecondary);
          const cls = "csv-build-spell" + (isSecondary && swappedSecondary ? " is-swapped" : "");
          return url
            ? `<img class="${cls}" src="${url}" title="${tip}" onerror="this.style.display='none'">`
            : `<span class="${cls} empty" title="${tip}">?</span>`;
        }).join("")}</span>`
      : "";
    // s211: runes-text caption removed - rune main + sub icons replace
    // it visually, and the redundant "Keystone . Primary / Secondary"
    // line was eating row height. Hovering the icons still shows the
    // tree names via title attrs.
    const runesText = "";

    // s209 v2: stash the adaptive override on the row dataset so the
    // click handler can read it without going through the cache twice.
    // Empty when no swap applied (click uses variant's stored summoners).
    const summOverride = swappedSecondary && Array.isArray(v.summoners)
      ? v.summoners.join(",")
      : "";
    const summAttr = summOverride ? ` data-override-summoners="${summOverride}"` : "";
    // item 213 (2026-05-28): the experimental row + its data-exp-*
    // override attributes were removed; expAttrs is now always empty.
    const expAttrs = "";
    // Item 178 (2026-05-24): collapsed SR variant renders ONE champion
    // entry with N labeled build-path rows stacked vertically inside
    // (instead of N separate selectable variant rows). Each path is
    // clickable - selection persists as "<variant>:<path-key>" so the
    // legacy single-variant savedChoice format still pre-selects the
    // variant idx on next render. Non-collapsed variants (ARAM/Arena/
    // experimental) render the legacy single-row layout below.
    const buildPaths = Array.isArray(v.build_paths) ? v.build_paths : [];
    if (buildPaths.length) {
      // Pick the active path: saved choice's :path-key suffix if it
      // belongs to this variant; else the first path flagged as primary;
      // else path[0].
      let activePathKey = "";
      if (savedChoice && savedChoice.startsWith(v.key + ":")) {
        activePathKey = savedChoice.slice(v.key.length + 1);
      }
      if (!activePathKey) {
        const primaryPath = buildPaths.find((p) => p && p._is_primary);
        activePathKey = (primaryPath && primaryPath.key) || buildPaths[0].key || "";
      }
      const pathRowsHtml = buildPaths.map((p) =>
        _csvBuildPathRowHtml(v.key, p, p.key === activePathKey, ver)
      ).join("");
      // Item 240 part-3 (3a/3b): the recommended rune is the keystone of
      // the currently-active build card; the nested rune panel renders
      // to the RIGHT of the cards. The active path's keystone falls back
      // to the variant-level keystone (build_paths may not carry per-path
      // runes - the resolver does the same fallback).
      const activePath = buildPaths.find((p) => p && p.key === activePathKey)
        || buildPaths.find((p) => p && p._is_primary)
        || buildPaths[0] || {};
      // The recommended (amber) rune mirrors what the auto-writer actually
      // applies (v.auto_keystone, from rune_recommendations) so the panel
      // matches the game. Falls back to the active build-card keystone when
      // no auto rec exists for this champion/mode.
      const recommendedRuneKey =
        String(v.auto_keystone || activePath.keystone || v.keystone || "");
      const runePanelHtml = _csvRunePanelHtml(v, recommendedRuneKey, savedRuneKey);
      return `
        <div class="csv-build-row csv-build-row-collapsed${idx === selectedIdx ? " selected" : ""}"
             data-variant="${v.key}"
             data-active-path="${activePathKey}">
          <div class="csv-build-collapsed-head">
            <div class="csv-build-collapsed-title">${v.label}</div>
          </div>
          <div class="csv-build-collapsed-cols">
            <div class="csv-build-path-list">${pathRowsHtml}</div>
            ${runePanelHtml}
          </div>
        </div>`;
    }

    // s211: 4-column row - checkbox / meta (3 stacked rows: badge, main
    // tree, sub tree) / summoners (stacked vertically) / items (larger).
    // Label rendered as a colored pill via csv-build-badge so the row
    // identity reads at a glance without a trailing tag.
    // s211 v2: 2-row card - badge label on row 1, rune main (keystone
    // + primary icon + primary tree name) on row 2. Subtree row dropped;
    // freed vertical room rolls into the larger icon sizes.
    return `
      <div class="csv-build-row${idx === selectedIdx ? " selected" : ""}" data-variant="${v.key}"${summAttr}${expAttrs}>
        ${cb}
        <div class="csv-build-meta">
          <div class="${badgeClass}">${v.label}</div>
          ${runeMainHtml}
        </div>
        ${spellsHtml}
        <div class="csv-build-items">${items}</div>
      </div>`;
  }).join("");
}

// s209: in-flight guard on the loadout-apply call so a rapid double-click
// doesn't fire two LCU pushes back-to-back. Keyed per
// (champion, variant, mode) - cleared when the response lands.
const _CSV_APPLY_INFLIGHT = Object.create(null);

function _csvApplyLoadout(champion, variantKey, mode, overrideSummoners, overrideRunes, overrideItems, pushFlags) {
  if (!champion || !variantKey) return;
  // Empty/pending pseudo-rows aren't backed by anything pushable.
  if (variantKey === "empty" || variantKey === "ds-pending") return;
  // Item 240 part-3 (3e): optional per-category gate. Default (omitted)
  // pushes all three so the legacy click + the userbuild path are
  // unchanged. The header-control auto-push wires pass a single-category
  // {push_runes|push_items|push_summoners} so a checked "Build" box pushes
  // ONLY the item set (and the colon-form variant key makes the resolver
  // overlay the right path), not the runes/spells.
  const pf = pushFlags || {};
  const wantRunes = (pf.push_runes !== undefined) ? !!pf.push_runes : true;
  const wantItems = (pf.push_items !== undefined) ? !!pf.push_items : true;
  const wantSumm  = (pf.push_summoners !== undefined) ? !!pf.push_summoners : true;
  const key = `${champion}|${variantKey}|${mode || "sr"}|${(overrideSummoners||[]).join(",")}|${wantRunes ? 1 : 0}${wantItems ? 1 : 0}${wantSumm ? 1 : 0}`;
  if (_CSV_APPLY_INFLIGHT[key]) return;
  _CSV_APPLY_INFLIGHT[key] = true;
  const body = {
    champion, variant: variantKey, mode: mode || "sr",
    push_runes:     wantRunes,
    push_items:     wantItems,
    push_summoners: wantSumm,
  };
  if (Array.isArray(overrideSummoners) && overrideSummoners.length === 2) {
    body.override_summoners = overrideSummoners.map((x) => x | 0);
  }
  // s210 v2: experimental row passes a complete override package
  // (keystone+trees + DS engine item ids). Backend bypasses the variant
  // resolver and builds rune_cmd/item_cmd/summ_cmd inline.
  if (overrideRunes
      && overrideRunes.keystone && overrideRunes.primary && overrideRunes.secondary) {
    body.override_runes = {
      keystone:  overrideRunes.keystone,
      primary:   overrideRunes.primary,
      secondary: overrideRunes.secondary,
    };
  }
  if (Array.isArray(overrideItems) && overrideItems.length) {
    body.override_items = overrideItems.map((x) => String(x));
  }
  fetch("/api/loadout/apply", {
    method: "POST", cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
    .then((r) => (r && r.ok ? r.json() : null))
    .catch(() => null)
    .finally(() => { _CSV_APPLY_INFLIGHT[key] = false; });
}

function _csvWireBuildVariants(scope) {
  // s171.8: read champion + mode from the wrapper's data-* so the click
  // handler can persist the selection AND fire the loadout push. Falls
  // back to no-save if absent (defensive - keeps the visual toggle
  // working in unit-test fixtures).
  const wrap = scope.querySelector(".csv-builds");
  const champion = wrap ? (wrap.dataset.champion || "") : "";
  const mode     = wrap ? (wrap.dataset.mode || "sr") : "sr";

  // Item 240 part-3 (3a/3b): re-point the rune panel's AMBER
  // (recommended) marker to the keystone of the now-active build card,
  // WITHOUT moving the GREEN (selected) marker. Reads the active card's
  // keystone from its rune option's sibling cards. Called on a path-row
  // click so the recommended rune tracks the active card live (3b).
  function _repointRecommendedRune(scopeRoot, recommendedRuneKey) {
    const savedRuneKey = _csvSavedRuneChoice(champion);
    const onRecommended = !!savedRuneKey && savedRuneKey === recommendedRuneKey;
    scopeRoot.querySelectorAll(".csv-rune-opt").forEach((opt) => {
      const k = opt.dataset.runeKey || "";
      const isSelected = !!savedRuneKey && k === savedRuneKey;
      const isRec = k === recommendedRuneKey && !onRecommended && !isSelected;
      opt.classList.toggle("is-recommended", isRec);
      // Keep green authoritative on the selected option.
      opt.classList.toggle("is-selected", isSelected);
    });
  }

  // Item 178 (2026-05-24): wire path-row clicks inside collapsed variants
  // BEFORE the legacy single-variant click handler so a nested click is
  // handled by the inner row (and stopPropagation prevents the outer
  // selection toggle). Each path click persists `<variant>:<path-key>`.
  // Item 240 part-3 (3e): the BUILD push now fires automatically ONLY
  // when the "Build" header checkbox is checked (opt-in); the selection
  // always persists regardless. The rune panel's recommended marker
  // re-points to the new card's keystone (3b).
  const pathRows = scope.querySelectorAll(".csv-build-path-row");
  pathRows.forEach((prow) => {
    prow.addEventListener("click", (ev) => {
      ev.stopPropagation();
      const variantKey = prow.dataset.variant || "";
      const pathKey    = prow.dataset.pathKey || "";
      if (!champion || !variantKey || !pathKey) return;
      // Single-active-path within this collapsed variant.
      const siblings = prow.parentNode
        ? prow.parentNode.querySelectorAll(".csv-build-path-row")
        : [];
      siblings.forEach((s) => s.classList.toggle("is-active", s === prow));
      const outer = prow.closest(".csv-build-row-collapsed");
      if (outer) outer.dataset.activePath = pathKey;
      const composed = `${variantKey}:${pathKey}`;
      _csvSaveChoice(champion, composed);
      // 3b: re-point the recommended rune (amber) to this card's
      // keystone - the active card's keystone falls back to the
      // variant-level keystone (data-rune-key on the matching opt).
      const recKey = prow.dataset.cardKeystone || "";
      const collapsedRoot = outer || scope;
      if (recKey) _repointRecommendedRune(collapsedRoot, recKey);
      // 3e: auto-push BUILD only when its category box is checked. When
      // unchecked the selection persists but fires NO push.
      const flags = _csvGetPushFlags();
      if (flags.build) {
        _csvApplyLoadout(champion, composed, mode, null, null, null,
          { push_runes: false, push_items: true, push_summoners: false });
      }
    });
  });

  // Item 240 part-3 (3b/3e): rune-option clicks inside the nested rune
  // panel move the GREEN (selected/sticky) marker + persist the rune
  // choice per champion. When the "Runes" box is checked the click also
  // auto-pushes the rune page (3e). Selecting the option that was amber
  // (recommended) clears the amber (you are now ON the recommended rune
  // -> just green per 3b).
  const runeOpts = scope.querySelectorAll(".csv-rune-opt");
  runeOpts.forEach((opt) => {
    opt.addEventListener("click", (ev) => {
      ev.stopPropagation();
      const runeKey = opt.dataset.runeKey || "";
      if (!champion || !runeKey) return;
      _csvSaveRuneChoice(champion, runeKey);
      const panel = opt.closest(".csv-rune-panel") || scope;
      panel.querySelectorAll(".csv-rune-opt").forEach((o) => {
        const isSel = (o.dataset.runeKey || "") === runeKey;
        o.classList.toggle("is-selected", isSel);
        // Clear amber on the now-selected option (3b: on the
        // recommended rune -> green only, no second color).
        if (isSel) o.classList.remove("is-recommended");
      });
      // 3e: auto-push RUNES only when its category box is checked. The
      // active build card's composed key drives the resolver overlay so
      // the pushed page matches the operator's rune selection's card.
      const flags = _csvGetPushFlags();
      if (flags.runes) {
        // cid=1: _csvBuildVariantsFor uses cid ONLY as a "champion is
        // picked" guard (the body resolves variants by name+mode from
        // the warm cache); 0 would hit the empty-placeholder early return.
        const variants = _csvBuildVariantsFor(1, champion, mode, null);
        _csvPushCategory(champion, mode, "runes", variants);
      }
    });
  });

  // Item 240 part-3 (3d/3e): header control - the [PUSH] button + the 3
  // category checkboxes. A checkbox going unchecked -> checked persists
  // the flag AND immediately pushes that category (3e). Unchecking
  // persists the flag + fires NO push. The [PUSH] button force-pushes
  // every currently-checked category now.
  const pushBtn = scope.querySelector("#csv-builds-push-btn");
  if (pushBtn) {
    pushBtn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      if (!champion) return;
      const variants = _csvBuildVariantsFor(0, champion, mode, null);
      _csvPushCheckedCategories(champion, mode, variants);
    });
  }
  scope.querySelectorAll(".csv-builds-push-cb").forEach((cb) => {
    cb.addEventListener("change", (ev) => {
      ev.stopPropagation();
      const cat = cb.dataset.pushCat || "";
      if (_CSV_PUSH_CATS.indexOf(cat) < 0) return;
      const on = !!cb.checked;
      _csvSetPushFlag(cat, on);
      // Unchecked -> checked: push that category now. Checked -> unchecked:
      // no push (stops auto-pushing going forward).
      if (on && champion) {
        // cid=1: _csvBuildVariantsFor uses cid ONLY as a "champion is
        // picked" guard (the body resolves variants by name+mode from
        // the warm cache); 0 would hit the empty-placeholder early return.
        const variants = _csvBuildVariantsFor(1, champion, mode, null);
        _csvPushCategory(champion, mode, cat, variants);
      }
    });
  });

  // Legacy single-variant rows - click selects the variant (non-
  // collapsed shape; ARAM / Arena / experimental).
  const rows = scope.querySelectorAll(".csv-build-row");
  rows.forEach((row) => {
    row.addEventListener("click", () => {
      // Collapsed rows have their own per-path click wiring above; the
      // outer click should not toggle a single "selected" state on the
      // collapsed entry (only one entry per champ; the row is implicitly
      // selected).
      if (row.classList.contains("csv-build-row-collapsed")) return;
      rows.forEach((r) => r.classList.toggle("selected", r === row));
      const variantKey = row.dataset.variant;
      if (champion && variantKey
          && variantKey !== "empty"
          && variantKey !== "ds-pending") {
        _csvSaveChoice(champion, variantKey);
        // s209: fire the actual LCU push - runes + items + summoners.
        // Curated rows pass override_summoners only (when adaptive
        // swapped). item 213 (2026-05-28): experimental override_runes
        // + override_items were removed with the experimental row.
        const summRaw = row.dataset.overrideSummoners || "";
        const overrideSummoners = summRaw
          ? summRaw.split(",").map((x) => x | 0)
          : null;
        _csvApplyLoadout(champion, variantKey, mode,
                         overrideSummoners, null, null);
      }
    });
  });
}

// Arena central pane: team header (me + up to 2 teammates; s234/#89:
// Arena is 6 teams of 3, was 8x2) + 3 augment slots (silver/gold/
// prismatic) + the current-round augment options.
function _csvArenaPaneHtml(cs, myCid, myName) {
  const teams = (cs && Array.isArray(cs.arena_teams)) ? cs.arena_teams : [];
  const myTeam = teams.find((t) => t && t.is_me) || (cs.my_team ? { cells: cs.my_team } : null);
  const cells = (myTeam && Array.isArray(myTeam.cells)) ? myTeam.cells : (cs.my_team || []);
  const me = cells.find((c) => (c && c.championId) === myCid) || cells[0] || null;
  // s234 (#89): Arena sub-teams are 3 players -> render me + up to 2
  // teammates (was a single "partner" when Arena was 8x2).
  const partners = cells.filter((c) => c && c !== me).slice(0, 2);
  while (partners.length < 2) partners.push(null);
  const ver = CHAMPS.version || "latest";
  const cellHtml = (c, isMe) => {
    if (!c || !c.championId) {
      return `<div class="csv-duo-cell is-empty">
        <div class="csv-duo-cell-icon">?</div>
        <div class="csv-duo-cell-tag">${isMe ? "ME" : "ALLY"}</div>
        <div class="csv-duo-cell-name">waiting...</div>
      </div>`;
    }
    const nm = _csChampName(c.championId) || ("cid:" + c.championId);
    const img = CHAMPS.byId[String(c.championId)]
      ? `<img src="/data/ddragon/${ver}/img/champion/${CHAMPS.byId[String(c.championId)]}.png" alt="${nm}" onerror="this.style.display='none'">`
      : "?";
    const lockCls = c.completed ? "locked" : "hovering";
    return `<div class="csv-duo-cell ${lockCls}${isMe ? " is-me" : ""}">
      <div class="csv-duo-cell-icon">${img}</div>
      <div class="csv-duo-cell-tag">${isMe ? "ME" : "ALLY"}</div>
      <div class="csv-duo-cell-name">${nm}</div>
      <div class="csv-duo-cell-summ">${escHtml((c.summonerName || "").slice(0, 22)) || "-"}</div>
    </div>`;
  };

  const aug = cs.augments || {};
  const slots = Array.isArray(aug.my_slots) ? aug.my_slots : [];
  const curTier = aug.current_round || "silver";
  const slotHtml = ["silver", "gold", "prismatic"].map((tier) => {
    const s = slots.find((x) => x && x.tier === tier);
    const filled = !!(s && s.id);
    const isActive = tier === curTier;
    return `<div class="csv-augment-slot ${tier}${filled ? " filled" : ""}${isActive ? " is-active" : ""}">
      <div class="csv-augment-slot-grade">${tier.toUpperCase()}</div>
      <div class="csv-augment-slot-name">${filled ? s.name : (isActive ? "PICKING..." : "-")}</div>
    </div>`;
  }).join("");

  const options = Array.isArray(aug.options) ? aug.options : [];
  const optionsHtml = options.length
    ? options.map((o) => `
        <div class="csv-augment-option is-clickable ${o.tier || ""}" data-augment-id="${o.id}" data-augment-name="${o.name}">
          <div class="csv-augment-option-name">${o.name}</div>
          <div class="csv-augment-option-blurb">${o.blurb || ""}</div>
        </div>`).join("")
    : '<div class="csv-empty">no augment options yet</div>';

  return `
    <div class="csv-duo-row">
      ${cellHtml(me, true)}
      ${partners.map((p) => cellHtml(p, false)).join("")}
    </div>
    <div class="csv-augments">
      <div class="csv-augments-title">My augments</div>
      <div class="csv-augment-slots">${slotHtml}</div>
    </div>
    <div class="csv-augment-options">
      <div class="csv-augments-title">${curTier.toUpperCase()} round . pick one</div>
      ${optionsHtml}
    </div>`;
}

function _csvWireArenaAugments(scope, cs) {
  scope.querySelectorAll(".csv-augment-option.is-clickable").forEach((cell) => {
    cell.addEventListener("click", () => {
      const id = parseInt(cell.dataset.augmentId, 10);
      if (!id) return;
      // Mark selected (visual only - LCU push is Phase B once we have
      // the right LCU verb / payload schema for arena augments).
      scope.querySelectorAll(".csv-augment-option").forEach((c) =>
        c.classList.toggle("is-selected", c === cell));
      lcuCmd({ cmd: "set_augment_intent", augment_id: id });
    });
  });
}

// Arena enemies: the 5 other sub-team cards stacked vertically inside
// the enemies column (s234/#89: Arena is 6 teams of 3, was 8x2). Each
// sub-team shows its 3 champion cells side-by-side.
function _csvRenderEnemiesArena(cs, timerEndMs) {
  const list = document.getElementById("csv-enemies-list");
  if (!list) return;
  list.innerHTML = "";
  const teams = (cs && Array.isArray(cs.arena_teams)) ? cs.arena_teams : [];
  const others = teams.filter((t) => t && !t.is_me).slice(0, 5);
  while (others.length < 5) others.push(null);
  const ver = CHAMPS.version || "latest";
  others.forEach((t, idx) => {
    const li = document.createElement("li");
    li.className = "csv-arena-team";
    const label = (t && t.label) || `TEAM ${idx + 2}`;
    const cells = (t && Array.isArray(t.cells)) ? t.cells.slice(0, 3) : [];
    while (cells.length < 3) cells.push(null);
    const cellsHtml = cells.map((c) => {
      if (!c || !c.championId) {
        return `<div class="csv-arena-cell is-empty">
          <div class="csv-arena-cell-icon">?</div>
          <div class="csv-arena-cell-name">-</div>
        </div>`;
      }
      const nm = _csChampName(c.championId) || ("cid:" + c.championId);
      const img = CHAMPS.byId[String(c.championId)]
        ? `<img src="/data/ddragon/${ver}/img/champion/${CHAMPS.byId[String(c.championId)]}.png" alt="${nm}" onerror="this.style.display='none'">`
        : "?";
      // s214: per-cell timer removed for Arena teams too - same
      // rationale as SR/ARAM. Lock glyph kept for arena since the
      // sub-team card visual is denser and the cell's own outline
      // doesn't carry the lock signal as cleanly. `timerEndMs` arg
      // retained on the function for ABI continuity with SR's caller
      // signature, but no longer rendered.
      const lockHtml = c.completed ? '<span class="csv-arena-cell-lock">[lock]</span>' : "";
      const stateCls = c.completed ? "locked" : "hovering";
      return `<div class="csv-arena-cell ${stateCls}">
        <div class="csv-arena-cell-icon">${img}</div>
        <div class="csv-arena-cell-mark">${lockHtml}</div>
        <div class="csv-arena-cell-name">${nm}</div>
      </div>`;
    }).join("");
    li.innerHTML = `
      <div class="csv-arena-team-head">${label}</div>
      <div class="csv-arena-team-row">${cellsHtml}</div>`;
    list.appendChild(li);
  });
}

// s214: per-cell countdown ticker retired alongside the per-cell timers
// in SR/ARAM/Arena (operator: too much visual noise; the global header
// timer + active-round border indicator already convey "round ticking
// down"). Kept as a no-op so existing callers don't error.
function _csvSetupTimerTick() { /* no-op since s214 */ }

// Align summoner-name column with the "A" of the centered "Allies"
// header.
//
// Strategy: canvas measureText() - DOM-based measurement (Range API,
// inline span, cloned head off-screen) all gave wrong values across
// attempts (returning end-of-text or end-of-line positions, likely
// browser-specific quirks). Canvas is text-only, no layout quirks.
// We manually apply text-transform and letter-spacing since canvas
// doesn't honor those CSS properties on its own.
const _csvCanvas =
  (typeof document !== "undefined") ? document.createElement("canvas") : null;
function _csvMeasureText(text, cs) {
  if (!_csvCanvas) return 0;
  const ctx = _csvCanvas.getContext("2d");
  // Apply CSS text-transform manually (canvas ignores it).
  const tt = cs.textTransform;
  let s = text;
  if (tt === "uppercase") s = s.toUpperCase();
  else if (tt === "lowercase") s = s.toLowerCase();
  else if (tt === "capitalize") {
    s = s.replace(/\b\w/g, (c) => c.toUpperCase());
  }
  ctx.font = (cs.fontStyle || "") + " " + (cs.fontWeight || "400") + " " +
             cs.fontSize + " " + cs.fontFamily;
  let w = ctx.measureText(s).width;
  // Letter-spacing adds (n-1) gaps; canvas doesn't apply it.
  const ls = parseFloat(cs.letterSpacing) || 0;
  if (ls && s.length > 1) w += ls * (s.length - 1);
  return w;
}

function _csvAlignAllies() {
  const card = document.querySelector(".csv-card-allies");
  const head = card && card.querySelector(".csv-card-head");
  if (!card || !head) return;
  const headRect = head.getBoundingClientRect();
  if (!headRect.width) return;
  const text = (head.textContent || "").trim();
  if (!text) return;
  const cs = getComputedStyle(head);
  const textWidth = _csvMeasureText(text, cs);
  if (!textWidth) return;
  const padL = parseFloat(cs.paddingLeft) || 0;
  const padR = parseFloat(cs.paddingRight) || 0;
  const innerW = headRect.width - padL - padR;
  const aLeftAbs = headRect.left + padL + (innerW - textWidth) / 2;
  const cardRect = card.getBoundingClientRect();
  const aFromCardLeft = aLeftAbs - cardRect.left;
  // Summ col left from card outer edge:
  //   card border (1) + card padding-left (10) + cell border (1)
  //   + cell padding-left (6) + icon-col (36) + gap (8)
  //   + champname-col + gap (8) = 70 + col
  const champnameCol = Math.max(60, Math.round(aFromCardLeft - 70));
  card.style.setProperty("--csv-champname-col", champnameCol + "px");
}

// -- Pick & Ban Recommendations (s164 scaffold) ---------------------
// Layout: role chip + 3 pick-rows (performance / mastery / meta) each
// with [icon+name | reason | 3 ban suggestions] + mood toggle.
// Real data wiring (perf scoring from rewind_history.db, mastery from
// LCU, counter matrix, 500ms blocker poll, mode-conditional behavior)
// is Phase B. This stub uses hardcoded placeholders so the operator
// can review the visual scaffold before backend integration.

const _ROLE_FROM_LCU = {
  TOP: "TOP", JUNGLE: "JNG", MIDDLE: "MID",
  BOTTOM: "BOT", UTILITY: "SUP",
};

function _csvResolveRole(cs) {
  // Mode-specific labels for non-SR queues. s234 (#89 follow-up): ARAM
  // Mayhem is queue 2400 (KIWI), not 920 - 920 is Legend of the Poro
  // King (ARAM-family). Real Mayhem games were falling through to the
  // SR position logic and never showing the MAYHEM badge.
  if (cs.queue_id === 1700 || cs.queue_id === 1710 || cs.queue_id === 1750) return "ARENA";
  if (cs.queue_id === 450 || cs.queue_id === 920) return "ARAM";
  if (cs.queue_id === 2400) return "MAYHEM";
  // SR: read assignedPosition from my local cell.
  const myCell = cs.local_cell;
  const me = (cs.my_team || []).find((p) => p && p.cellId === myCell);
  const pos = (me && me.assignedPosition) || "";
  return _ROLE_FROM_LCU[pos.toUpperCase()] || "-";
}

// Placeholder pick/ban data per role. Phase B replaces this with
// computed values from rewind_history.db + counter matrix + LCU mastery.
const _PB_PLACEHOLDERS = {
  BOT: {
    performance: {
      champId: 51, champName: "Caitlyn",
      reason: "62% WR . 14 BOT games . early lane-bully matchups favor you",
      bans: [
        { champId: 119, name: "Draven",  pct: 78 },
        { champId: 236, name: "Lucian",  pct: 64 },
        { champId: 555, name: "Pyke",    pct: 71 },
      ],
    },
    mastery: {
      champId: 67, champName: "Vayne",
      reason: "M8 . 388k pts . 47 ranked games . highest mastery on role",
      bans: [
        { champId: 51,  name: "Caitlyn", pct: 81 },
        { champId: 81,  name: "Ezreal",  pct: 58 },
        { champId: 53,  name: "Overlay App E",   pct: 76 },
      ],
    },
    meta: {
      champId: 145, champName: "Kai'Sa",
      reason: "S+ tier ADC this patch . 53% global WR . scales well vs comp",
      bans: [
        { champId: 15,  name: "Sivir",   pct: 72 },
        { champId: 222, name: "Jinx",    pct: 61 },
        { champId: 89,  name: "Leona",   pct: 69 },
      ],
    },
  },
  // Other roles inherit BOT placeholders until backend lands.
};

function _pbPlaceholdersFor(role) {
  return _PB_PLACEHOLDERS[role] || _PB_PLACEHOLDERS.BOT;
}

function _csvMoodGet() {
  try { return sessionStorage.getItem("csv-mood") || "comfort"; }
  catch (_) { return "comfort"; }
}
function _csvMoodSet(v) {
  try { sessionStorage.setItem("csv-mood", v); } catch (_) {}
}
// s211: mood-keyed row title for the Pick & Ban PERFORMANCE row.
// Mirrors the mood-button labels so the operator can correlate the
// active button with the row above it.
const _CSV_MOOD_LABELS = {
  comfort: "Performance",
  limit:   "Limit Test",
  new:     "Something New",
  synergy: "Comp Synergy",
};

// s170 item #4: live pick&ban recommendations from
// /api/champ-select/pickban-recs. Cached per (role, queue_id) and
// refreshed at most every 60s - operator history isn't changing
// during a single champ-select session, so this is just an in-memory
// dedupe to keep the panel responsive.
const _CSV_PB_CACHE = {};   // {`${role}|${queue}`: {data, fetchedAt}}
const _CSV_PB_INFLIGHT = {};
const _CSV_PB_TTL_MS = 60_000;

function _csvFetchPickBanRecs(role, queueId, mood, opts, onLoad) {
  // Role here is the dashboard form ("BOT"/"JNG"/etc.) - the endpoint
  // accepts both forms via its _ROLE_ALIASES map. s209: mood is
  // included in the cache key + query string so each toggle change
  // surfaces a distinct rec without invalidating others. s214: opts
  // adds {exclude:[ids], allies:[ids], top:N} for cascade-filtered
  // multi-row queries on LIMIT/NEW/SYNERGY moods. The full opts payload
  // folds into the cache key so a re-fetch with different excludes
  // doesn't return stale top-N from the prior call.
  //
  // Item 168 (2026-05-24): opts.enemies + opts.my_summoners flow to
  // the backend for the cleanse-advisory composer. Both are included
  // in the cache key so the advisory shifts as enemies lock + the
  // operator switches summoner pairs.
  if (!role || role === "-") return null;
  const m = mood || "comfort";
  const o = opts || {};
  const exclude  = Array.isArray(o.exclude)      ? o.exclude.slice().sort((a, b) => a - b)      : [];
  const allies   = Array.isArray(o.allies)       ? o.allies.slice().sort((a, b) => a - b)       : [];
  const enemies  = Array.isArray(o.enemies)      ? o.enemies.slice().sort((a, b) => a - b)      : [];
  const mySumms  = Array.isArray(o.my_summoners) ? o.my_summoners.slice().sort((a, b) => a - b) : [];
  const top      = Math.max(1, Math.min(5, o.top | 0 || 1));
  const cacheKey = [
    role, queueId || 0, m, top,
    `e:${exclude.join(",")}`, `a:${allies.join(",")}`,
    `n:${enemies.join(",")}`, `s:${mySumms.join(",")}`,
  ].join("|");
  const now = Date.now();
  const cached = _CSV_PB_CACHE[cacheKey];
  if (cached && (now - cached.fetchedAt) < _CSV_PB_TTL_MS) {
    return cached.data;
  }
  if (_CSV_PB_INFLIGHT[cacheKey]) return cached ? cached.data : null;
  _CSV_PB_INFLIGHT[cacheKey] = true;
  let url = `/api/champ-select/pickban-recs?role=${encodeURIComponent(role)}`
          + (queueId ? `&queue=${queueId}` : "")
          + `&mood=${encodeURIComponent(m)}`
          + `&top=${top}`;
  if (exclude.length) url += `&exclude=${encodeURIComponent(exclude.join(","))}`;
  if (allies.length)  url += `&allies=${encodeURIComponent(allies.join(","))}`;
  if (enemies.length) url += `&enemies=${encodeURIComponent(enemies.join(","))}`;
  if (mySumms.length) url += `&my_summoners=${encodeURIComponent(mySumms.join(","))}`;
  fetch(url)
    .then((r) => r.ok ? r.json() : null)
    .then((j) => {
      _CSV_PB_INFLIGHT[cacheKey] = false;
      if (j && j.ok) {
        _CSV_PB_CACHE[cacheKey] = { data: j, fetchedAt: Date.now() };
        if (typeof onLoad === "function") onLoad();
      }
    })
    .catch(() => { _CSV_PB_INFLIGHT[cacheKey] = false; });
  return cached ? cached.data : null;
}

// s239 (AUTONOMOUS_AUDIT opportunity #2): the per-user CONTEXTUAL read.
// /api/champ-select/personal-record reports the operator's actual
// lifetime record against the champions ALREADY on the board in this
// draft - distinct from the mood recs above (which RECOMMEND picks).
// This is the headline differentiator: "your WR with/against", a
// per-user signal no cohort-averaged SaaS can produce. Same 60s
// in-memory dedupe pattern as _csvFetchPickBanRecs (operator history
// doesn't change mid-champ-select). No queue param by design - the
// lifetime read spans all SR queues (A7), so a normal-draft lobby
// still counts the operator's ranked Vayne games.
const _CSV_PR_CACHE = {};
const _CSV_PR_INFLIGHT = {};
const _CSV_PR_TTL_MS = 60_000;

function _csvFetchPersonalRecord(role, champId, allyIds, enemyIds, onLoad) {
  const a = (allyIds || []).slice().sort((x, y) => x - y);
  const e = (enemyIds || []).slice().sort((x, y) => x - y);
  const c = champId | 0;
  // Nothing on the board yet - no champ hovered + no locks.
  if (!c && !a.length && !e.length) return null;
  const cacheKey = [
    role || "-", c, `a:${a.join(",")}`, `e:${e.join(",")}`,
  ].join("|");
  const now = Date.now();
  const cached = _CSV_PR_CACHE[cacheKey];
  if (cached && (now - cached.fetchedAt) < _CSV_PR_TTL_MS) return cached.data;
  if (_CSV_PR_INFLIGHT[cacheKey]) return cached ? cached.data : null;
  _CSV_PR_INFLIGHT[cacheKey] = true;
  let url = "/api/champ-select/personal-record?v=1";
  if (role && role !== "-") url += `&role=${encodeURIComponent(role)}`;
  if (c) url += `&champ=${c}`;
  if (a.length) url += `&allies=${encodeURIComponent(a.join(","))}`;
  if (e.length) url += `&enemies=${encodeURIComponent(e.join(","))}`;
  fetch(url)
    .then((r) => r.ok ? r.json() : null)
    .then((j) => {
      _CSV_PR_INFLIGHT[cacheKey] = false;
      if (j && j.ok) {
        _CSV_PR_CACHE[cacheKey] = { data: j, fetchedAt: Date.now() };
        if (typeof onLoad === "function") onLoad();
      }
    })
    .catch(() => { _CSV_PR_INFLIGHT[cacheKey] = false; });
  return cached ? cached.data : null;
}

// WR -> tint class. Uniform semantics for both rows: high operator WR is
// green, low is red. Reads correctly both ways - high "with ally" =
// good synergy; low "vs enemy" = they beat you = ban-worthy red.
function _csvPrTint(wr) {
  return wr >= 55 ? "is-good" : (wr >= 45 ? "is-mid" : "is-bad");
}

function _csvPrChip(name, wr, games) {
  // Legacy text-chip - kept for backwards-compat. The Assessment-panel
  // VS row now uses _csvPrChipIcon below.
  const nm = String(name || "?");
  if (!games) {
    return `<span class="csv-pr-chip is-new">${nm}<em>first time</em></span>`;
  }
  return `<span class="csv-pr-chip ${_csvPrTint(wr)}">`
       + `${nm}<b>${wr}%</b></span>`;
}

// Operator (2026-05-23 round 3): chip variant that renders the champion
// portrait icon (instead of the text name) with the WR % below. Used in
// the Assessment panel's VS row so the operator scans by face, not by
// reading champ names. champId is the LCU integer (DDragon-keyed name
// via CHAMPS.byId).
function _csvPrChipIcon(champId, wr, games) {
  const cid = (champId | 0);
  const url = _csChampImg(cid);
  const name = _csChampName(cid) || (cid ? "cid:" + cid : "?");
  if (!games) {
    return `<span class="csv-pr-chip-icon is-new" title="${name} - first time">`
         + (url ? `<img class="csv-pr-chip-icon-img" src="${url}" alt="${name}" onerror="this.style.display='none'">` : "")
         + `<span class="csv-pr-chip-icon-pct">--</span></span>`;
  }
  return `<span class="csv-pr-chip-icon ${_csvPrTint(wr)}" title="${name} ${wr}% (${games}g)">`
       + (url ? `<img class="csv-pr-chip-icon-img" src="${url}" alt="${name}" onerror="this.style.display='none'">` : "")
       + `<span class="csv-pr-chip-icon-pct">${wr}%</span></span>`;
}

// Build the foregrounded "YOUR RECORD" headline. Always renders the
// titled block (foregrounding = a named, present headline, not
// conditional filler) - falls to a muted hint when the board is empty.
function _csvRenderPersonalRecordBlock(pr, selfCid) {
  let inner = "";
  if (pr && pr.champ) {
    const c = pr.champ;
    const sub = `${c.wins}-${c.games - c.wins} (${c.games}g)`;
    let roleBit = "";
    if (c.role && c.role_games) {
      roleBit = ` <span class="csv-pr-champ-role">`
              + `${_csvShortRole(c.role)} ${c.role_wr_pct}%`
              + ` (${c.role_games}g)</span>`;
    }
    inner += `<div class="csv-pr-champ">`
           + `<span class="csv-pr-champ-name">${String(c.champName || "?").toUpperCase()}</span>`
           + `<span class="csv-pr-champ-wr ${_csvPrTint(c.wr_pct)}">${c.wr_pct}%</span>`
           + `<span class="csv-pr-champ-sub">${sub}</span>${roleBit}</div>`;
  } else if (selfCid) {
    const nm = String(_csChampName(selfCid) || "?").toUpperCase();
    inner += `<div class="csv-pr-champ is-new">`
           + `<span class="csv-pr-champ-name">${nm}</span>`
           + `<em>no games on record</em></div>`;
  }
  // Operator (2026-05-23 round 3): WITH row dropped entirely; VS row
  // kept but each chip is now an icon (champion portrait) with WR %
  // below - not a text name. Operator scans by face, not by name.
  const enemies = (pr && Array.isArray(pr.vs_enemies)) ? pr.vs_enemies : [];
  if (enemies.length) {
    inner += `<div class="csv-pr-row csv-pr-row-vs"><span class="csv-pr-tag">VS</span>`
           + enemies.map((x) => _csvPrChipIcon(x.champId, x.wr_pct, x.games)).join("")
           + `</div>`;
  }
  if (!inner) {
    inner = `<div class="csv-pr-hint">your lifetime record vs this draft `
          + `appears here as champs lock in</div>`;
  }
  return `<div class="csv-pr">`
       + `<div class="csv-pr-title">YOUR RECORD</div>${inner}</div>`;
}

// Operator 2026-05-31 (part 4): inject the operator's lifetime win-rate
// vs each enemy into the Enemies panel (left of the icon), replacing the
// removed YOUR RECORD VS-chip row. Idempotent - clears prior fills first.
// prData.vs_enemies = [{champId, wr_pct, games}].
function _csvInjectEnemyWinRates(prData) {
  const list = document.getElementById("csv-enemies-list");
  if (!list) return;
  list.querySelectorAll(".csv-enemy-wr-slot").forEach((el) => {
    el.textContent = "";
    el.className = "csv-enemy-wr-slot";
    el.removeAttribute("title");
  });
  const vs = (prData && Array.isArray(prData.vs_enemies)) ? prData.vs_enemies : [];
  if (!vs.length) return;
  const byId = Object.create(null);
  vs.forEach((x) => { if (x && x.champId) byId[x.champId | 0] = x; });
  list.querySelectorAll("li.csv-team-cell[data-cid]").forEach((li) => {
    const cid = parseInt(li.dataset.cid, 10) | 0;
    const rec = cid ? byId[cid] : null;
    const slot = li.querySelector(".csv-enemy-wr-slot");
    if (!rec || !slot) return;
    const tint = (rec.wr_pct != null) ? _csvPrTint(rec.wr_pct) : "is-new";
    slot.textContent = (rec.wr_pct != null) ? rec.wr_pct + "%" : "--";
    slot.className = "csv-enemy-wr-slot " + tint;
    slot.title = `your record vs ${_csChampName(cid) || cid}: `
               + `${rec.wr_pct}% (${rec.games || 0}g)`;
  });
}

function _csvMergePickBanData(role, liveRecs, placeholder) {
  // Layer live performance over placeholder mastery/meta. When the
  // live performance row is missing (operator has no SR history at
  // this role), keep the placeholder so the panel doesn't go blank.
  const out = {
    performance: placeholder.performance,
    mastery:     placeholder.mastery,
    meta:        placeholder.meta,
  };
  if (liveRecs && liveRecs.performance) {
    const p = liveRecs.performance;
    out.performance = {
      champId:   p.champId,
      champName: p.champName,
      reason:    p.reason,
      bans:      (liveRecs.performance_bans || placeholder.performance.bans).map((b) => ({
        champId: b.champId,
        name:    b.name,
        pct:     b.pct,
      })),
    };
    // Backfill bans from placeholder if live returned fewer than 3.
    while (out.performance.bans.length < 3 && placeholder.performance.bans[out.performance.bans.length]) {
      out.performance.bans.push(placeholder.performance.bans[out.performance.bans.length]);
    }
  }
  return out;
}

// item 213 (2026-05-28): the duo-synergy fetcher + its render helper +
// the ally-bot-sup-state extractor were removed when the bottom panel
// was reoriented to a live ally-picks-by-role mirror (the ally-roles
// renderer below). The /api/duo-synergy route + its mock fixture stay
// for any future re-use; nothing in champ-select calls them now.
// The champ-name-from-id helper is retained - the ally-roles panel
// uses it.

// Champion-name lookup from numeric id via CHAMPS.byId. Used to map
// the operator's allies (LCU returns championId numbers) into the
// string names the backend route expects.
function _csvChampNameFromId(cid) {
  if (!cid) return "";
  const slug = CHAMPS.byId[String(cid | 0)];
  if (!slug) return "";
  return String(slug);
}



// item 213 (2026-05-28): ROLE_ORDER for the ally-picks-by-role panel.
// Canonical SR lane order top -> bottom of the visual list.
const _CSV_ROLE_ORDER = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"];
const _CSV_ROLE_SHORT = {
  TOP: "TOP", JUNGLE: "JG", MIDDLE: "MID", BOTTOM: "ADC", UTILITY: "SUP",
};

// item 213 (2026-05-28): bottom/support panel redesigned to mirror the
// LIVE ally roster - one row per assigned lane showing which ally is on
// that role + the champion they LOCKED (solid) or are HOVERING (dimmed),
// or an empty "picking..." state. Replaces the prior 101.qq.com duo-
// synergy suggestion grid (disconnected from the actual draft). Reads
// cs.my_team cells: assignedPosition + (completed ? championId : pick
// intent) + cellId vs cs.local_cell to flag the operator's own row.
function _csvRenderAllyRolesHtml(cs, champImg) {
  const team = (cs && Array.isArray(cs.my_team)) ? cs.my_team : [];
  if (!team.length) {
    return '<div class="csv-allyroles-empty">waiting for ally picks...</div>';
  }
  // Index cells by assigned position so we render in canonical lane
  // order regardless of the raw cell ordering.
  const byPos = Object.create(null);
  const unassigned = [];
  for (const p of team) {
    if (!p) continue;
    const pos = String(p.assignedPosition || "").toUpperCase();
    if (pos && _CSV_ROLE_SHORT[pos]) byPos[pos] = p;
    else unassigned.push(p);
  }
  const localCell = cs.local_cell;
  const rowFor = (pos, cell) => {
    const isMe = cell && cell.cellId != null && cell.cellId === localCell;
    const lockedId = (cell && cell.completed && cell.championId)
      ? (cell.championId | 0) : 0;
    const hoverId = (cell && (cell.championPickIntent | 0)) || 0;
    const showId = lockedId || hoverId;
    let stateCls = "is-empty";
    let stateTxt = "picking...";
    if (lockedId) { stateCls = "is-locked"; stateTxt = "LOCKED"; }
    else if (hoverId) { stateCls = "is-hover"; stateTxt = "hovering"; }
    const champName = showId ? (_csvChampNameFromId(showId) || "?") : "-";
    const meCls = isMe ? " is-me" : "";
    return `
      <div class="csv-allyroles-row ${stateCls}${meCls}">
        <span class="csv-allyroles-role">${_CSV_ROLE_SHORT[pos] || pos}</span>
        <div class="csv-allyroles-icon">${showId ? champImg(showId) : '<span class="csv-allyroles-icon-empty">?</span>'}</div>
        <span class="csv-allyroles-name">${champName}</span>
        <span class="csv-allyroles-state">${isMe ? "YOU" : stateTxt}</span>
      </div>`;
  };
  let rows = "";
  let rendered = 0;
  for (const pos of _CSV_ROLE_ORDER) {
    if (byPos[pos]) { rows += rowFor(pos, byPos[pos]); rendered += 1; }
  }
  // ARAM / blind / unassigned-position queues: no assignedPosition, so
  // fall back to one row per cell (no lane label).
  if (rendered === 0) {
    rows = team.map((cell, i) =>
      rowFor("#" + (i + 1), cell)).join("");
  } else {
    // Append any extra unassigned cells below the lane rows.
    rows += unassigned.map((cell, i) =>
      rowFor("#" + (i + 1), cell)).join("");
  }
  return `<div class="csv-allyroles-grid">${rows}</div>`;
}

// OQ9 (QA26 remainder): short why-banned label for a P&B ban cell.
// Derived ONLY from fields already in the pickban-recs payload:
// pct = operator's loss rate vs this champion in-role (routes_pickban.py
// _query_loss_matchups), losses/encounters = the sample behind it.
// Returns "" when there is nothing honest to say (placeholder cell or
// no qualifying loss rate) - the cell then renders name-only as before.
function _csvBanReasonLabel(b) {
  if (!b || !(b.champId > 0)) return "";
  const pct = b.pct | 0;
  if (pct <= 0) return "";
  const enc = b.encounters | 0;
  const los = b.losses | 0;
  const sample = (enc > 0) ? ` (${los}/${enc})` : "";
  return `beats you ${pct}%${sample}`;
}

function _csvRenderPickBan(cs, myCid) {
  const body = document.getElementById("csv-pickban-body");
  if (!body) return;
  if (!cs) {
    body.innerHTML = '<div class="csv-empty">waiting for champ-select data...</div>';
    return;
  }
  const role = _csvResolveRole(cs);
  const ver = CHAMPS.version || "latest";
  const ph = _pbPlaceholdersFor(role);
  const mood = _csvMoodGet();
  const perfLabel = _CSV_MOOD_LABELS[mood] || "Performance";

  // s214: build the cascade exclude-set - every champion already
  // committed in the draft is off-limits as a recommendation. Source
  // ids:
  //   - bans (ally + enemy) from cs.bans
  //   - picks (ally + enemy) from cs.my_team[].championId,
  //     cs.their_team[].championId (BOTH intent + locked)
  //   - the operator's own current pick intent (don't recommend
  //     yourself a champ you're already hovering)
  // Plus the row-cascade: as we render rows 1..N for LIMIT/NEW/SYNERGY,
  // each row's pick id is added to the exclude-set for the next row's
  // backend call so we never duplicate within the panel.
  const collectIds = (arr) => (arr || []).map((p) => {
    if (typeof p === "number") return p | 0;
    return (p && (p.championId | 0)) || 0;
  }).filter((x) => x > 0);
  const baseExclude = new Set();
  if (cs.bans) {
    collectIds(cs.bans.my_team).forEach((x) => baseExclude.add(x));
    collectIds(cs.bans.their_team).forEach((x) => baseExclude.add(x));
  }
  collectIds(cs.my_team).forEach((x) => baseExclude.add(x));
  collectIds(cs.their_team).forEach((x) => baseExclude.add(x));
  // Also exclude championPickIntent (hover state, not yet locked).
  (cs.my_team || []).concat(cs.their_team || []).forEach((p) => {
    const intent = p && p.championPickIntent;
    if (intent && intent > 0) baseExclude.add(intent | 0);
  });

  // Item 168: operator's locked-in summoner-spell pair for the cleanse
  // advisory. Pull from the operator's own my_team cell. Default to
  // empty array if the cell isn't resolvable yet.
  const myCell = (cs.my_team || []).find(
    (p) => p && p.cellId === cs.local_cell);
  const mySumms = myCell
    ? [myCell.spell1Id, myCell.spell2Id].filter((x) => x > 0)
    : [];

  // Ally ids (LOCKED only - hovers don't count toward team-comp synergy
  // because they can swap) for the SYNERGY mood backend query.
  const allyIds = (cs.my_team || [])
    .filter((p) => p && p.completed && p.championId)
    .map((p) => p.championId | 0)
    .filter((x) => x > 0);

  // s239: per-user CONTEXTUAL read. enemyIds mirrors allyIds (locked
  // only). selfCid = operator's own champ, falling back to the operator
  // cell's championId / hover intent so the headline populates the
  // moment they hover - when it's most useful during the draft.
  const enemyIds = (cs.their_team || [])
    .filter((p) => p && p.completed && p.championId)
    .map((p) => p.championId | 0)
    .filter((x) => x > 0);
  let selfCid = myCid | 0;
  if (!selfCid) {
    const meRow = (cs.my_team || []).find(
      (p) => p && p.cellId === cs.local_cell);
    if (meRow) selfCid = (meRow.championId | 0) || (meRow.championPickIntent | 0);
  }
  const prData = _csvFetchPersonalRecord(
    role, selfCid, allyIds, enemyIds,
    () => _csvRenderPickBan(cs, myCid),
  );
  // Operator 2026-05-31 (part 4): YOUR RECORD block removed. The per-
  // enemy lifetime win-rate now renders in the Enemies panel (left of
  // each icon) via _csvInjectEnemyWinRates; the prData fetch above still
  // drives it. Hide the now-removed Assessment container if still present.
  const yrTarget = document.getElementById("csv-sugg-your-record");
  if (yrTarget) { yrTarget.innerHTML = ""; yrTarget.hidden = true; }
  _csvInjectEnemyWinRates(prData);

  // -- Item 168 (2026-05-24): 3-stacked-sub-panel layout ------------
  // Top    : 4 picks (3 role-matching from comfort + 1 last_in_queue).
  // Middle : 4 bans  (3 from performance_bans + 1 struggle_ban).
  // Bottom : dynamic explanation (per-pick reasons + cleanse advisory).
  // Mood toggle stays in the bottom strip alongside the advisory; it
  // re-orders the 3 role-matching picks. The 4th pick (last_in_queue)
  // is mood-invariant by design.
  const opts168 = {
    exclude: Array.from(baseExclude),
    top: 3,
    enemies: enemyIds,
    my_summoners: mySumms,
  };
  if (mood === "synergy") opts168.allies = allyIds;
  const liveRecs = _csvFetchPickBanRecs(
    role, cs.queue_id, mood, opts168,
    () => _csvRenderPickBan(cs, myCid),
  );
  const liveRoleMatch = (liveRecs && Array.isArray(liveRecs.performance_picks))
    ? liveRecs.performance_picks : [];
  const fallbackPicks = [ph.performance, ph.mastery, ph.meta];
  // 3 role-matching picks: backend top-3 from current mood, padded with
  // placeholders so the row keeps its 4-cell geometry on a thin DB.
  const roleMatchPicks = [0, 1, 2].map((i) => {
    const p = liveRoleMatch[i];
    if (p) {
      return {
        champId:   p.champId,
        champName: p.champName,
        reason:    p.reason,
        sourceKey: i === 0 ? "performance" : (i === 1 ? "mastery" : "meta"),
      };
    }
    const fb = fallbackPicks[i] || {};
    return {
      champId:   fb.champId   || 0,
      champName: fb.champName || "-",
      reason:    `[no ${mood} data]`,
      sourceKey: i === 0 ? "performance" : (i === 1 ? "mastery" : "meta"),
    };
  });
  // 4th pick: last-in-queue (mood-invariant). When backend can't resolve
  // it (no history in this queue), surface an em-dash placeholder cell.
  const lastInQueue = liveRecs && liveRecs.last_in_queue;
  const fourthPick = lastInQueue
    ? {
        champId:   lastInQueue.champId,
        champName: lastInQueue.champName,
        reason:    lastInQueue.reason,
        sourceKey: "last",
      }
    : {
        champId:   0,
        champName: "-",
        reason:    "no recent history in this queue",
        sourceKey: "last",
      };
  const allPicks = [...roleMatchPicks, fourthPick];

  // 3 counter bans + 1 struggle ban.
  const liveBans = (liveRecs && Array.isArray(liveRecs.performance_bans))
    ? liveRecs.performance_bans : [];
  // OQ9 (QA26 remainder): carry encounters + losses through - the
  // backend has always returned them per ban row (routes_pickban.py
  // _query_loss_matchups) but the pre-OQ9 mapping dropped both, leaving
  // the why-banned label with nothing to show. Placeholder rows have no
  // sample so they default 0 (label formatter omits the sample part).
  const counterBans = [0, 1, 2].map((i) => {
    const b = liveBans[i];
    if (b) {
      return {
        champId:    b.champId,
        name:       b.name,
        pct:        b.pct,
        encounters: b.encounters | 0,
        losses:     b.losses | 0,
        sourceKey:  "counter",
      };
    }
    // Use placeholder ban data when backend can't supply 3.
    const fbBan = (ph.performance.bans || [])[i] || {};
    return {
      champId:    fbBan.champId || 0,
      name:       fbBan.name    || "-",
      pct:        fbBan.pct     || 0,
      encounters: 0,
      losses:     0,
      sourceKey:  "counter",
    };
  });
  const struggle = liveRecs && liveRecs.struggle_ban;
  const fourthBan = struggle
    ? {
        champId:    struggle.champId,
        name:       struggle.name,
        pct:        struggle.pct,
        encounters: struggle.encounters | 0,
        losses:     struggle.losses | 0,
        sourceKey:  "struggle",
      }
    : {
        champId:    0,
        name:       "-",
        pct:        0,
        encounters: 0,
        losses:     0,
        sourceKey:  "struggle",
      };
  const allBans = [...counterBans, fourthBan];

  // Dynamic explanation: per-pick reason lines + cleanse advisory.
  // Operator wants "lite + quickly readable" so cap to 3 short lines
  // (1 per displayed source plus the advisory). The cleanse line lands
  // first when present since it's the most actionable real-time signal.
  const explanationLines = [];
  const advisory = liveRecs && liveRecs.cleanse_advisory;
  if (advisory) {
    explanationLines.push({ cls: "csv-pb-expl-cc", text: advisory });
  }
  allPicks.forEach((p) => {
    if (!p.champId) return;
    const tag = p.sourceKey === "last" ? "last in queue"
              : (p.sourceKey === "performance" ? perfLabel.toLowerCase()
                 : p.sourceKey);
    explanationLines.push({
      cls: `csv-pb-expl-pick is-${p.sourceKey}`,
      text: `${p.champName}: ${p.reason} (${tag})`,
    });
  });

  // s214: pick-click safety - only disable when an actual BAN round is
  // active so the operator can't accidentally fire `set_pick_intent`
  // during a ban (the trap the original gate addressed). Pre-s214 the
  // gate was `cs.phase === "FINALIZATION" || cs.my_completed === true`,
  // which under-enabled clicks during pick rounds (the operator
  // couldn't set pick intent until either the round was over OR they
  // had locked, which is itself a "click to lock" decision).
  //
  // Per-queue confirmation that the active_round resolver covers all
  // SR draft variants the operator cares about:
  //   400 Normal Draft  - one simultaneous ban round, then alt picks
  //   420 Ranked Solo   - same ban shape, alt picks
  //   430 Normal Blind  - no bans, alt picks only
  //   440 Ranked Flex   - same as 420
  //   490 Quickplay     - no bans, alt picks
  // ARAM (450/920/2400) + Arena (1700/1710/1750) don't show the P&B panel
  // (CSS hides it via data-cs-mode), so this gate is SR-only in practice.
  // s214 v2: Brawl branch retired from this list (mode removed).
  const inActiveBanRound = !!(cs.active_round
                              && cs.active_round.type === "ban");
  const pickClickEnabled = !inActiveBanRound;

  const champImg = (cid) =>
    cid && CHAMPS.byId[String(cid)]
      ? `<img src="/data/ddragon/${ver}/img/champion/${CHAMPS.byId[String(cid)]}.png" onerror="this.style.display='none'" alt="">`
      : "?";

  // Item 168: 3-stacked-sub-panel render.
  // Sub-panel 1: 4-pick horizontal grid.
  const pickCells = allPicks.map((p) => {
    const isClickable = pickClickEnabled && p.champId > 0;
    const isSel = isClickable && (_csvSelection.pick === p.champId);
    const cls = "csv-pb168-cell csv-pb168-pick is-" + p.sourceKey
              + (isClickable ? " is-clickable" : "")
              + (isSel ? " is-selected" : "");
    const dataAttr = isClickable
      ? ` data-pick-id="${p.champId}" data-pick-name="${p.champName}"` : "";
    const tag = p.sourceKey === "last" ? "LAST"
              : (p.sourceKey === "performance" ? "TOP"
                 : (p.sourceKey === "mastery" ? "#2" : "#3"));
    return `
      <div class="${cls}"${dataAttr} title="${p.champName} - ${p.reason}">
        <span class="csv-pb168-tag">${tag}</span>
        <div class="csv-pb168-icon">${champImg(p.champId)}</div>
        <div class="csv-pb168-name">${p.champName}</div>
      </div>`;
  }).join("");
  // Sub-panel 2: 4-ban horizontal grid.
  const banCells = allBans.map((b) => {
    const isClickable = b.champId > 0;
    const isSel = isClickable && (_csvSelection.ban === b.champId);
    const cls = "csv-pb168-cell csv-pb168-ban is-" + b.sourceKey
              + (isClickable ? " is-clickable" : "")
              + (isSel ? " is-selected" : "");
    const dataAttr = isClickable
      ? ` data-ban-id="${b.champId}" data-ban-name="${b.name}"` : "";
    // Operator 2026-05-31 (#6): champion name centered (no CTR/COUNTER
    // tag, no %); the struggle ban keeps a centered STRUGGLE label.
    const struggleLabel = b.sourceKey === "struggle"
      ? `<div class="csv-pb168-struggle">STRUGGLE</div>` : "";
    // OQ9 (QA26 remainder): short why-banned sub-label under the name -
    // dim prose ("beats you 67% (4/6)"), NOT the loud % tag operator #6
    // removed. Empty for placeholder cells; title carries the same why.
    const reason = _csvBanReasonLabel(b);
    const reasonHtml = reason
      ? `<div class="csv-pb168-reason">${reason}</div>` : "";
    const cellTitle = reason ? `${b.name} - ${reason}` : b.name;
    return `
      <div class="${cls}"${dataAttr} title="${cellTitle}">
        ${struggleLabel}
        <div class="csv-pb168-icon">${champImg(b.champId)}</div>
        <div class="csv-pb168-name">${b.name}</div>
        ${reasonHtml}
      </div>`;
  }).join("");
  // Sub-panel 3: item 213 (2026-05-28) - ally-picks-by-role panel.
  // Replaces the prior 101.qq.com duo-synergy SUGGESTION grid (which
  // was disconnected from the actual draft) with a LIVE mirror of the
  // ally roster: one row per assigned lane showing which ally is on
  // that role + the champion they locked / are hovering. Reads
  // cs.my_team directly - no backend fetch needed, so it updates every
  // champ-select tick as allies lock in.
  const allyRolesHtml = _csvRenderAllyRolesHtml(cs, champImg);
  // Operator (2026-05-25 item 200 Slice D): PICK sub-panel renders into
  // the top-left card (#csv-picks-target inside .csv-card-allies). BAN +
  // DUO SYNERGY stay in #csv-pickban-body (row-2 pickban) with all the
  // freed vertical space. Pick + ban cells keep the .csv-pb168-pick /
  // .csv-pb168-ban classes; the click wiring below scopes to document
  // so it finds picks in their new location.
  const picksHtml = `
    <div class="csv-pb168-section csv-pb168-picks">
      <div class="csv-pb168-head">PICK</div>
      <div class="csv-pb168-row">${pickCells}</div>
    </div>`;
  // RC2 E4 (operator-reported): the BAN recommendation sub-panel is only
  // actionable while bans are open. Once the ban phase is DONE
  // (_csvBanPhaseComplete) it can no longer be acted on, so collapse it
  // out of the pick-window eyeline - the CSS .is-collapsed rule hides the
  // 4-cell ban row and leaves a one-line "BAN - locked" header, freeing
  // the vertical space for PICK + ALLY PICKS BY ROLE during picks.
  const bansCollapsed = _csvBanPhaseComplete(cs);
  const banSectCls = "csv-pb168-section csv-pb168-bans"
                   + (bansCollapsed ? " is-collapsed" : "");
  const banHeadTxt = bansCollapsed ? "BAN - phase over" : "BAN";
  const html = `
    <div class="${banSectCls}">
      <div class="csv-pb168-head">${banHeadTxt}</div>
      <div class="csv-pb168-row">${banCells}</div>
    </div>
    <div class="csv-pb168-section csv-pb168-expl">
      <div class="csv-pb168-head">ALLY PICKS BY ROLE</div>
      <div class="csv-pb168-expl-body">${allyRolesHtml}</div>
    </div>`;

  body.innerHTML = html;
  const picksTarget = document.getElementById("csv-picks-target");
  if (picksTarget) picksTarget.innerHTML = picksHtml;

  // Wire mood toggle. s209: re-render the panel after persisting so the
  // performance row reflects the new mood (comfort / limit / new /
  // synergy). The fetch helper caches per (role, queue, mood) so a
  // toggle back to a previously-loaded mood is instant.
  body.querySelectorAll(".csv-pb-mood-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const m = btn.dataset.mood;
      if (!m) return;
      _csvMoodSet(m);
      body.querySelectorAll(".csv-pb-mood-btn").forEach((b) =>
        b.classList.toggle("is-active", b.dataset.mood === m));
      _csvRenderPickBan(cs, myCid);
    });
  });
  // Item 168: ban + pick click wiring on the new .csv-pb168-* cells.
  // Every click fires `set_ban_intent` / `set_pick_intent` to LCU; the
  // most-recent click gets `.is-selected` while siblings stay
  // clickable so the operator can re-target.
  body.querySelectorAll(".csv-pb168-ban.is-clickable").forEach((cell) => {
    cell.addEventListener("click", () => {
      const cid = parseInt(cell.dataset.banId, 10);
      body.querySelectorAll(".csv-pb168-ban").forEach((el) => {
        el.classList.toggle("is-selected", el === cell);
      });
      _csvOnBanSelect(cid);
    });
  });
  // Item 200 Slice D: picks render into #csv-picks-target (top-left
  // card) not body (#csv-pickban-body). Scope pick-click wiring to the
  // picks target so it attaches to the moved cells.
  const picksScope = document.getElementById("csv-picks-target") || body;
  picksScope.querySelectorAll(".csv-pb168-pick.is-clickable").forEach((cell) => {
    cell.addEventListener("click", () => {
      const cid = parseInt(cell.dataset.pickId, 10);
      picksScope.querySelectorAll(".csv-pb168-pick").forEach((el) => {
        el.classList.toggle("is-selected", el === cell);
      });
      _csvOnPickSelect(cid);
    });
  });
}

// LIFT 1a (2026-06-22): test-only hooks. This module is an ES module, so
// its functions are not reachable from the global scope; the snapshot
// harness (tests/snapshot_panels/test_champ_select_view.py) needs to stub
// the counter-picks fetch and invoke the renderer deterministically. Gated
// on the ?ui_mock=1 query flag read straight from location.search - NOT on
// body.dataset.uiMock, which main.js sets only AFTER this module (imported
// at the top of main.js) has already evaluated. So these globals never
// exist in the live dashboard (no ?ui_mock=1), only under the mock harness.
// The renderer reads the live _csvCounterFetch indirection (see its call
// site), so a test can override window._csvFetchCounterPicks before render.
try {
  if (typeof window !== "undefined" && typeof location !== "undefined"
      && /[?&]ui_mock=1(?:&|$)/.test(location.search || "")) {
    window._csvFetchCounterPicks = _csvCounterFetch;
    window._csvRenderCounterPicks = function (cs) {
      const ov = window._csvFetchCounterPicks;
      const prev = _csvCounterFetch;
      if (typeof ov === "function" && ov !== prev) _csvCounterFetch = ov;
      try { return _csvRenderCounterPicks(cs); }
      finally { _csvCounterFetch = prev; }
    };
    // LIFT 1b: same swap-during-render pattern for the team-damage meter,
    // reading the _csvTeamDamageFetch indirection at the renderer call site.
    window._csvFetchTeamDamage = _csvTeamDamageFetch;
    window._csvRenderTeamDamage = function (cs) {
      const ov = window._csvFetchTeamDamage;
      const prev = _csvTeamDamageFetch;
      if (typeof ov === "function" && ov !== prev) _csvTeamDamageFetch = ov;
      try { return _csvRenderTeamDamage(cs); }
      finally { _csvTeamDamageFetch = prev; }
    };
  }
} catch (_) { /* non-browser / no window - skip the test hook */ }

export { handleChampSelect, renderChampSelectCoach };
