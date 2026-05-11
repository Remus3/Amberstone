// Loading Screen view — renders the locked champ-select state during the
// GameStart phase (between champion lock-in and InProgress). It's the
// last strategic-briefing window before the game actually starts, so
// the layout prioritises full team comp visibility + matchup info over
// any picker UI.
//
// Phase 3 step 4 (s166, 2026-05-10) — initial scaffold. Operator iterates
// the visual hierarchy + briefing content in follow-up sessions per the
// fixture ritual. Live-fire trigger: phase === "GameStart" + ?ld=1
// (or localStorage.loadingView='1' makes it sticky).
import { CHAMPS } from '../lib/items_index.js';

// ── opt-in gate ───────────────────────────────────────────────────────
//
// Mirrors champSelectViewEnabled / activeMatchEnabled. Off by default so
// existing flows (lobby → champ-select → last-match) stay intact until
// the operator opts in.
export function loadingViewEnabled() {
  try {
    const sp = new URLSearchParams(window.location.search);
    if (sp.get("ld") === "1") {
      try { localStorage.setItem("loadingView", "1"); } catch (_) {}
      return true;
    }
    if (sp.get("ld") === "0") {
      try { localStorage.removeItem("loadingView"); } catch (_) {}
      return false;
    }
    return localStorage.getItem("loadingView") === "1";
  } catch (_) {
    return false;
  }
}

// ── small helpers ─────────────────────────────────────────────────────

function _lvwChampImg(cid) {
  if (!cid) return "";
  const nm = CHAMPS.byId[String(cid)];
  if (!nm) return "";
  return `/data/ddragon/${CHAMPS.version}/img/champion/${nm}.png`;
}

function _lvwChampName(cid) {
  return (cid && CHAMPS.byId[String(cid)]) || "";
}

function _lvwDetectMode(cs) {
  if (!cs) return "sr";
  const q = cs.queue_id | 0;
  if (cs.is_brawl || q === 480) return "brawl";
  if (q === 1700 || q === 1710) return "arena";
  if (cs.is_aram || q === 450 || q === 920) return "aram";
  return "sr";
}

function _lvwMapLabelFor(mode, queueId) {
  if (mode === "arena") return "Rings of Wrath";
  if (mode === "brawl") return "The Brawl";
  if (mode === "aram") return queueId === 920 ? "Howling Abyss (Mayhem)" : "Howling Abyss";
  return "Summoner's Rift";
}

function _lvwQueueLabel(mode, queueId) {
  if (mode === "arena") return "ARENA";
  if (mode === "brawl") return "BRAWL";
  if (mode === "aram") return queueId === 920 ? "MAYHEM" : "ARAM";
  // SR draft sub-types.
  if (queueId === 420) return "RANKED SOLO/DUO";
  if (queueId === 440) return "RANKED FLEX";
  if (queueId === 400) return "NORMAL DRAFT";
  if (queueId === 430) return "NORMAL BLIND";
  return "SR";
}

// Position pip uppercase + collapsed to 3 letters (matches the lobby
// view's role normalizer — `JUNGLE`/`JG` → `JNG`, `SUPPORT`/`SUPP`/
// `UTILITY` → `SUP`). Empty positions return "" so the column collapses.
function _lvwRoleShort(role) {
  const r = String(role || "").toUpperCase();
  if (!r || r === "FILL" || r === "UNSELECTED") return "";
  if (r === "JUNGLE" || r === "JG" || r === "JGL") return "JNG";
  if (r === "BOTTOM") return "BOT";
  if (r === "UTILITY" || r === "SUPP" || r === "SUPPORT") return "SUP";
  if (r === "MIDDLE") return "MID";
  return r.slice(0, 3);
}

// Summoner-spell icon by spell id. Riot publishes the canonical map at
// /data/ddragon/<version>/data/en_US/summoner.json but we only need the
// 9 spells used in League — hardcode the slug for now and let the
// CDN/data-dragon mount serve the asset. Returns "" for unknown ids.
const _LVW_SUM_SPELLS = {
  1:  "SummonerBoost",          // Cleanse
  3:  "SummonerExhaust",
  4:  "SummonerFlash",
  6:  "SummonerHaste",          // Ghost
  7:  "SummonerHeal",
  11: "SummonerSmite",
  12: "SummonerTeleport",
  13: "SummonerMana",           // Clarity (ARAM)
  14: "SummonerDot",            // Ignite
  21: "SummonerBarrier",
  32: "SummonerSnowball",       // ARAM Mark
};
function _lvwSumImg(spellId) {
  const slug = _LVW_SUM_SPELLS[spellId | 0];
  if (!slug) return "";
  return `/data/ddragon/${CHAMPS.version}/img/spell/${slug}.png`;
}

// Pretty-printed summoner spell name for hover/tooltip. Matches the
// slug table above with minimal lookup. Returns "" when unknown.
const _LVW_SUM_NAMES = {
  1:  "Cleanse", 3:  "Exhaust", 4:  "Flash", 6:  "Ghost",
  7:  "Heal", 11: "Smite", 12: "Teleport", 13: "Clarity",
  14: "Ignite", 21: "Barrier", 32: "Mark",
};
function _lvwSumName(spellId) { return _LVW_SUM_NAMES[spellId | 0] || ""; }

// ── row + team renderers ──────────────────────────────────────────────

function _lvwCellHtml(slot, opts) {
  const cid = slot.championId || slot.cid || 0;
  const name = _lvwChampName(cid) || (cid ? "cid:" + cid : "—");
  const summ = slot.summonerName || "";
  const role = opts && opts.showRole ? _lvwRoleShort(slot.assignedPosition || "") : "";
  const img = _lvwChampImg(cid);
  const summs = slot.summoners || slot.spells || null;
  const d = summs && summs[0] ? summs[0] : 0;
  const f = summs && summs[1] ? summs[1] : 0;
  const dImg = _lvwSumImg(d);
  const fImg = _lvwSumImg(f);
  // Slot 1 (d) is the keybind-D spell; slot 2 (f) is keybind-F. Match
  // the in-game order so the operator scans left-to-right.
  const summsHtml = (d || f)
    ? `<div class="lvw-cell-sums">
         ${dImg ? `<img class="lvw-sum" src="${dImg}" alt="${_lvwSumName(d)}" title="${_lvwSumName(d)}">` : ""}
         ${fImg ? `<img class="lvw-sum" src="${fImg}" alt="${_lvwSumName(f)}" title="${_lvwSumName(f)}">` : ""}
       </div>`
    : "";
  const meClass = opts && opts.isMe ? " is-me" : "";
  return `<li class="lvw-cell${meClass}">
    <div class="lvw-cell-portrait">
      ${img ? `<img src="${img}" alt="${name}">` : `<span class="lvw-cell-placeholder">?</span>`}
    </div>
    <div class="lvw-cell-text">
      <div class="lvw-cell-champ">${name}</div>
      ${summ ? `<div class="lvw-cell-summ">${summ}</div>` : ""}
    </div>
    ${role ? `<div class="lvw-cell-role">${role}</div>` : ""}
    ${summsHtml}
  </li>`;
}

function _lvwRenderTeam(targetId, cells, opts) {
  const ul = document.getElementById(targetId);
  if (!ul) return;
  const arr = Array.isArray(cells) ? cells : [];
  if (!arr.length) {
    ul.innerHTML = `<li class="lvw-empty">no team data yet…</li>`;
    return;
  }
  ul.innerHTML = arr.map((slot) =>
    _lvwCellHtml(slot, {
      ...opts,
      isMe: opts && opts.localCell != null
            && slot.cellId === opts.localCell,
    })).join("");
}

// Arena 2v2v2v2 renderer — 4 sub-team cards stacked. The TEAM with
// is_me=true gets the indigo accent; the rest get the muted enemy tone.
function _lvwRenderArenaTeams(targetId, teams, opts) {
  const host = document.getElementById(targetId);
  if (!host) return;
  if (!Array.isArray(teams) || !teams.length) {
    host.innerHTML = `<div class="lvw-empty">no arena team data yet…</div>`;
    return;
  }
  const localCell = opts && opts.localCell != null ? opts.localCell : -1;
  host.innerHTML = teams.map((tm) => {
    const cells = Array.isArray(tm.cells) ? tm.cells : [];
    const meClass = tm.is_me ? " is-me" : "";
    return `<div class="lvw-arena-team${meClass}">
      <div class="lvw-arena-team-head">${tm.name || ("Team " + tm.id)}</div>
      <ul class="lvw-arena-team-cells">
        ${cells.map((c) => _lvwCellHtml(c, {
          showRole: false,
          isMe: c.cellId === localCell,
        })).join("")}
      </ul>
    </div>`;
  }).join("");
}

// ── main entry point ──────────────────────────────────────────────────

export function renderLoadingView(lcu) {
  const section = document.getElementById("view-loading");
  if (!section) return;
  const cs = (lcu && lcu.champ_select) || null;
  const phase = (lcu && lcu.phase) || "";
  const sub = document.getElementById("lvw-sub");

  if (!cs) {
    if (sub) sub.textContent = `waiting for champ-select data… (phase=${phase || "—"})`;
    _lvwRenderTeam("lvw-allies-list", [], {});
    _lvwRenderTeam("lvw-enemies-list", [], {});
    return;
  }

  const mode = _lvwDetectMode(cs);
  section.dataset.lvwMode = mode;
  const qid = cs.queue_id | 0;
  const map = _lvwMapLabelFor(mode, qid);
  const qlabel = _lvwQueueLabel(mode, qid);

  // Sub-line: mode label + map + phase + queue id.
  const bits = [qlabel, map];
  if (phase) bits.push(phase.toUpperCase());
  if (qid) bits.push("queue " + qid);
  if (sub) sub.textContent = bits.join(" · ");

  const showRole = (mode === "sr");
  const opts = { showRole, localCell: cs.local_cell };

  if (mode === "arena") {
    // 2v2v2v2 — render the 4 sub-team cards via the arena renderer.
    // Allies card hosts our duo; enemies card hosts the other 3 sub-teams.
    const myTeam = (Array.isArray(cs.arena_teams) ? cs.arena_teams : [])
      .find((t) => t && t.is_me);
    const enemyTeams = (Array.isArray(cs.arena_teams) ? cs.arena_teams : [])
      .filter((t) => t && !t.is_me);
    _lvwRenderTeam("lvw-allies-list",
      myTeam ? myTeam.cells : cs.my_team, opts);
    _lvwRenderArenaTeams("lvw-enemies-list", enemyTeams, opts);
  } else {
    _lvwRenderTeam("lvw-allies-list",  cs.my_team,    opts);
    _lvwRenderTeam("lvw-enemies-list", cs.their_team, opts);
  }
}
