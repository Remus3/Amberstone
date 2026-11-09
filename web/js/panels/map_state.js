// Map State panel - zone pill, game clock, spell CDs, gold diff,
// objective countdowns.
import { el, safe, fmtList, _formatRelativeAge } from '../lib/helpers.js';
import { state } from '../lib/state.js';
import { CHAMPS, SPELLS, ITEM_COSTS, _resolveChampId, _resolveSpell } from '../lib/items_index.js';
import { teamItemValueDiff } from '../lib/item_value.js';

// State slots initialised here (map_state owns the clock + spell tracking).
state.gameClock = { startedAt: 0, anchorS: 0, raw: "" };
state.spellCds = {};

const MM = {
  root: el("minimap"),
  staleness: document.querySelector('.staleness[data-for="minimap"]'),
  dragon: el("mm-dragon"),
  baron: el("mm-baron"),
  herald: el("mm-herald"),
};

function _updateGameClock(p) {
  const s = (typeof p.game_time_s === "number") ? p.game_time_s : null;
  if (s != null) {
    state.gameClock.startedAt = Date.now();
    state.gameClock.anchorS = s;
    state.gameClock.raw = p.game_time || "";
    _applyGamePhase(s);
  } else if (p.game_time) {
    state.gameClock.raw = p.game_time;
  }
}
// Three phases mapped to body[data-phase] so CSS can tint subtly:
//   early  < 15:00   (calm blue)
//   mid    15-25:00  (engaged gold)
//   late   25:00+    (urgent coral)
// Read by the header tint (web/css/panels/base.css) and the stage-gated
// STATS groups (web/css/panels/map_state.css). S144-U-254: the match-phase
// strip and its marker that this also drove are retired - they sat in the
// #minimap panel, which renders in no view (S144-U-246).
let _lastPhase = null;
function _applyGamePhase(gtS) {
  const phase = gtS < 900 ? "early" : gtS < 1500 ? "mid" : "late";
  if (phase !== _lastPhase) {
    _lastPhase = phase;
    document.body.dataset.phase = phase;
  }
}
function _currentGameTimeS() {
  if (!state.gameClock.startedAt) return null;
  return state.gameClock.anchorS + (Date.now() - state.gameClock.startedAt) / 1000;
}
function _fmtMMSS(s) {
  s = Math.max(0, Math.round(s));
  const m = Math.floor(s / 60), ss = s % 60;
  return `${m}:${ss.toString().padStart(2, "0")}`;
}
// Extract "spawns MM:SS" or "next MM:SS" or "in N:SS" from objective text
// so we can surface a live countdown chip alongside the narrative state.
function _extractSpawnTime(text) {
  if (!text) return null;
  const m = String(text).match(/\b(?:spawns?|next|in)\s+(\d{1,2}):(\d{2})\b/i);
  if (!m) return null;
  return parseInt(m[1], 10) * 60 + parseInt(m[2], 10);
}

// Tick every second - pull current cd from state.spellCds and update
// each header self-spell cell's display.
function _tickSpellCooldowns() {
  if (document.hidden) return;
  document.querySelectorAll(".self-spell[data-cd-key]").forEach(cell => {
    const key = cell.dataset.cdKey;
    const rem = _currentSpellCd(key);
    const label = cell.querySelector(".cd-label");
    if (rem > 0) {
      cell.classList.add("on-cd");
      if (label) label.textContent = rem >= 60 ? Math.round(rem/60) + "m" : rem;
      cell.title = (cell.title.split(" - ")[0]) + ` - ${rem}s`;
    } else {
      // If the cell was on cooldown last tick, briefly flash "ready".
      if (cell.classList.contains("on-cd")) {
        cell.classList.add("cd-ready-flash");
        setTimeout(() => cell.classList.remove("cd-ready-flash"), 1100);
      }
      cell.classList.remove("on-cd");
      if (label) label.textContent = "";
    }
  });
}
setInterval(_tickSpellCooldowns, 1000);

// Default spawn-cycle durations per objective (seconds) used as the
// progress-bar denominator. Not scientific - Riot timings shift - but
// gives a glanceable "how close are we" feel.
const _OBJ_CYCLE = {
  dragon: 300,  // 5:00 between drakes
  baron:  360,  // 6:00 respawn after take
  herald: 360,
  atakhan: 300,
};
function _kindOf(elm) {
  if (!elm || !elm.id) return null;
  if (elm.id === "mm-dragon")  return "dragon";
  if (elm.id === "mm-baron")   return "baron";
  if (elm.id === "mm-herald")  return "herald";
  if (elm.id === "mm-atakhan") return "atakhan";
  return null;
}
// Zone of Influence (ZOI) pressure at your own position - drives the header
// zone pill and body[data-zone]. S144-U-258 retired the minimap canvas stack
// this math also painted (it rendered in no view), so only the one-point
// read below is left.
//
// Net pressure = sum ally_pressure - sum enemy_pressure, plus a weak
// diagonal baseline. Each champion contributes a compact-support "bubble"
// of influence - 1 at the champ, falling smoothly to exactly 0 at radius R:
//   d^2 = (dist / RADIUS)^2
//   contribution = (1 - d^2)^2   when d < R,   else 0
// Same-team champs in proximity stack (sum); the opposing team subtracts.
// Re-runs on every state envelope.
const ZOI = (() => {
  const q = new URLSearchParams(location.search);
  const pf = (k, d) => {
    const v = parseFloat(q.get(k));
    return isNaN(v) ? d : v;
  };
  return {
    // Each champion influences within ~0.35 of map width. Tunable.
    radius: pf("zoi-R", 0.32),
    // Deadband around net=0 reads as the DMZ on the zone pill.
    deadband: pf("zoi-DB", 0.10),
    // Baseline diagonal bias - top-left to bottom-right split (SR map).
    // Blue base is bot-left, red base is top-right. Champion pressure
    // warps this default. Keep weak so ganks + split-push still read.
    baselineStrength: pf("zoi-BL", 0.55),
  };
})();
// Phase-aware radius - early game champs are lane-contained, late game
// they rotate freely. Called with game_time_s from the state envelope.
function _zoiRadius(gtS) {
  if (typeof gtS !== "number") return ZOI.radius;
  if (gtS < 600)  return 0.22;   // <10:00 - tight lanes
  if (gtS < 1200) return 0.28;   // 10-20 - grouping phase
  if (gtS < 1800) return 0.34;   // 20-30 - rotations
  return 0.40;                    // 30+ - pure teamfight / split
}
// Compact-support influence bubble. d2 is (dist/R)^2 - already normalized
// by the caller. Outside the bubble (d2 >= 1) the champion contributes
// nothing, so the DMZ forms naturally in gaps and is pushed/pulled by
// wherever bubbles actually reach.
function _bubbleKernel(d2) {
  if (d2 >= 1) return 0;
  const t = 1 - d2;
  return t * t;
}

// S144-U-244: no position for you (dead, missing from the allies, or no
// positions at all) resets the header zone pill to its "-" placeholder and
// drops body[data-zone]. Adding .hidden alone kept the last call ("DEEP
// ENEMY") on the static pill and in its aria-live region, and the
// no-positions return kept the pill lit and the red zone tint on.
function _clearZone() {
  delete document.body.dataset.zone;
  const zonePill = el("zone-pill"), zoneLabel = el("zone-label");
  if (zonePill) zonePill.className = "zone-pill hidden";
  if (zoneLabel) zoneLabel.textContent = "-";
  // S144-U-245: the ?debug=1 readout explains the pill, so it goes with it.
  const dbg = el("zoi-debug");
  if (dbg) {
    dbg.classList.add("hidden");
    dbg.textContent = "";
  }
}

// S144-U-258: the name is kept for its callers and pins, but this no longer
// paints anything. The minimap canvas stack it drew into rendered in no view
// and is retired; what is left is the header zone pill (via _updateZone),
// computed at once even in a hidden tab - a few champions' worth of math,
// with no paint to defer behind document.hidden any more.
// Guard: tests/snapshot_panels/test_minimap_canvas_stack_retired.py.
function renderMinimapCanvases(p) {
  if (!p.positions || (!p.positions.allies && !p.positions.enemies)) {
    _clearZone();
    return;
  }
  const myTeam = (p.my_team || "blue").toLowerCase();
  document.body.dataset.myteam = myTeam;

  // Drop positions for dead champions - they're not exerting pressure.
  // *_respawns keys -> remaining seconds; >0 = dead, skip contribution.
  const deadE = new Set(Object.entries(p.enemy_respawns || {})
      .filter(([, s]) => typeof s === "number" && s > 0)
      .map(([n]) => n));
  const deadA = new Set(Object.entries(p.ally_respawns || {})
      .filter(([, s]) => typeof s === "number" && s > 0)
      .map(([n]) => n));
  const allies = Object.fromEntries(
    Object.entries(p.positions.allies || {}).filter(([n]) => !deadA.has(n)));
  const enemies = Object.fromEntries(
    Object.entries(p.positions.enemies || {}).filter(([n]) => !deadE.has(n)));

  const selfKey = _champKey(p.champion);
  let selfPos = null;
  for (const name of Object.keys(allies)) {
    if (allies[name] && _champKey(name) === selfKey) selfPos = allies[name];
  }
  _updateZone(p, allies, enemies, myTeam, selfKey, selfPos);
}

function _champKey(name) {
  return String(name || "").toLowerCase().replace(/[^a-z0-9]/g, "");
}

// Pressure at your own position drives the header zone pill (and
// body[data-zone]); no position resets both (S144-U-244).
function _updateZone(p, allies, enemies, myTeam, selfKey, selfPos) {
  if (!selfPos) {
    _clearZone();
    return;
  }
  const myIsRed = myTeam === "red";
  const baselineSign = myIsRed ? -1 : 1;
  let netAtSelf = (selfPos.y - selfPos.x) * ZOI.baselineStrength * baselineSign;
  const _R = _zoiRadius(p.game_time_s);
  for (const key of Object.keys(allies)) {
    const q = allies[key]; if (!q || _champKey(key) === selfKey) continue;
    const dx = selfPos.x - q.x, dy = selfPos.y - q.y;
    const d2 = (dx*dx + dy*dy) / (_R * _R);
    netAtSelf += _bubbleKernel(d2);
  }
  for (const key of Object.keys(enemies)) {
    const q = enemies[key]; if (!q) continue;
    const dx = selfPos.x - q.x, dy = selfPos.y - q.y;
    const d2 = (dx*dx + dy*dy) / (_R * _R);
    netAtSelf -= _bubbleKernel(d2);
  }
  // ?debug=1 - show ZOI pressure readouts under the Active Match map.
  if (/[?&]debug=1/.test(location.search)) {
    const dbg = el("zoi-debug");
    if (dbg) {
      dbg.classList.remove("hidden");
      dbg.textContent =
        `R=${_zoiRadius(p.game_time_s).toFixed(2)} \u00B7 baseline ${ZOI.baselineStrength}` +
        ` \u00B7 deadband ${ZOI.deadband} \u00B7 self-pressure ${netAtSelf.toFixed(2)}`;
    }
  }
  const zonePill = el("zone-pill"), zoneLabel = el("zone-label");
  if (zonePill && zoneLabel) {
    zonePill.classList.remove("hidden");
    if (netAtSelf < -ZOI.deadband) {
      // Deep-enemy-territory escalation: < -3*DB is the "you are
      // clearly deeper than just adjacent to enemy influence" bar.
      // Empirically: sr_gank_scenario (3 enemies stacked, 1 isolated ally)
      // clears the bar; teamfight (5v5) does NOT.
      const deep = netAtSelf < -ZOI.deadband * 3;
      zoneLabel.textContent = deep ? "\u26D4 DEEP ENEMY" : "\u26A0 ENEMY ZONE";
      zonePill.className = "zone-pill zone-enemy" + (deep ? " zone-deep" : "");
      document.body.dataset.zone = deep ? "deep" : "enemy";
    } else if (netAtSelf > ZOI.deadband) {
      zoneLabel.textContent = "\u2713 SAFE";
      zonePill.className = "zone-pill zone-safe";
      document.body.dataset.zone = "safe";
    } else {
      zoneLabel.textContent = "- DMZ";
      zonePill.className = "zone-pill zone-dmz";
      document.body.dataset.zone = "dmz";
    }
  }
}

function renderItemValueDiff(p) {
  const wrap = el("gold-diff");
  const fill = el("gold-diff-fill");
  const lbl = el("gold-diff-val");
  if (!wrap || !fill || !lbl) return;
  // R117 F1: the dormant team_gold_diff bar can never be fed live - enemy gold
  // is activePlayer-only over the Live Client API - so repurpose it as the
  // item-value differential, the one economy lens computable from the public
  // allPlayers[].items roster. Honest user-facing label is "item value".
  const lc = (state.latest && state.latest.liveclient) || (p && p.liveclient) || null;
  // S144-U-255: the bar now renders (Active Match MAP pane), so gate it to the
  // two-team modes. Arena pits your duo against every other duo and TFT has no
  // League items, so an ally-vs-rest sum there is not a team lead.
  const mode = document.body.dataset.mode || "";
  const diff = (mode === "arena" || mode === "tft") ? null : teamItemValueDiff(lc, ITEM_COSTS);
  if (diff == null) {
    wrap.classList.add("hidden");
    return;
  }
  wrap.classList.remove("hidden");
  // Clamp to +/-10k for the fill bar scale.
  const clamp = Math.max(-10000, Math.min(10000, diff));
  const pct = Math.abs(clamp) / 10000;
  // Left edge is 50% (center). Fill extends right (ahead) or left (behind).
  if (clamp >= 0) {
    fill.style.left = "50%";
    fill.style.right = `${50 - pct * 50}%`;
    fill.classList.remove("behind");
    fill.classList.add("ahead");
  } else {
    fill.style.right = "50%";
    fill.style.left = `${50 - pct * 50}%`;
    fill.classList.remove("ahead");
    fill.classList.add("behind");
  }
  const signed = clamp >= 0 ? `+${clamp.toLocaleString()}` : clamp.toLocaleString();
  lbl.textContent = signed;
  lbl.className = clamp >= 0 ? "gd-ahead" : "gd-behind";
}

function _tickObjectiveCountdowns() {
  const nowS = _currentGameTimeS();
  for (const elm of [MM.dragon, MM.baron, MM.herald]) {
    if (!elm) continue;
    const raw = elm.dataset.raw || "-";
    if (nowS == null) { elm.textContent = raw; continue; }
    const target = _extractSpawnTime(raw);
    // Find (or lazy-create) the tick progress bar on the containing .kv row.
    const row = elm.closest(".kv");
    let bar = row && row.querySelector(".obj-bar");
    if (row && !bar) {
      bar = document.createElement("i");
      bar.className = "obj-bar";
      row.appendChild(bar);
    }
    if (target == null) {
      elm.textContent = raw;
      if (bar) bar.style.setProperty("--pct", "0%");
      continue;
    }
    const remaining = target - nowS;
    const cycle = _OBJ_CYCLE[_kindOf(elm)] || 300;
    // Ratio of progress toward spawn (0 = just went down, 1 = up now).
    const progress = Math.max(0, Math.min(1, 1 - (remaining / cycle)));
    if (bar) bar.style.setProperty("--pct", (progress * 100).toFixed(1) + "%");
    if (remaining <= 0) {
      elm.textContent = raw.replace(/\b(?:spawns?|next|in)\s+\d{1,2}:\d{2}\b/i, "UP NOW");
      elm.classList.add("obj-up");
      if (bar) bar.classList.add("full");
    } else {
      elm.textContent = raw.replace(
        /\b(?:spawns?|next|in)\s+\d{1,2}:\d{2}\b/i,
        `in ${_fmtMMSS(remaining)}`
      );
      elm.classList.toggle("obj-soon", remaining < 45);
      elm.classList.remove("obj-up");
      if (bar) bar.classList.remove("full");
    }
  }
}
// Tick every 1s - objective countdowns are the primary live pulse.
// Skip work entirely when the tab is hidden (iPad battery / CPU).
setInterval(() => {
  if (document.hidden) return;
  _tickObjectiveCountdowns();
}, 1000);

function renderMinimap(p) {
  _updateGameClock(p);
  // Coaching-JSON fields surface objective state when the coach has
  // computed it. When absent, keep the placeholder. Fields queried:
  //   p.dragon_state / p.dragon_stack / p.soul - if the coach computed them
  //   p.baron_alive / p.baron_timer
  //   p.herald_alive / p.atakhan_state
  //   p.game_time / p.game_time_s
  // Store the raw state text in data-raw so the countdown tick can
  // re-render from it without a fresh state envelope.
  // Strip "(Cloud taken 12:04)" / "(Chemtech taken 8:30)" style parentheticals
  // - the kill count + next-spawn line already convey the important bits;
  // the parenthetical just eats horizontal space.
  const _cleanObj = s => String(s || "-")
    .replace(/\s*\([^)]*taken[^)]*\)\s*/gi, " ")
    .replace(/  +/g, " ")
    .trim() || "-";
  for (const [elm, val] of [
    [MM.dragon,  _cleanObj(p.dragon_state  || p.dragon)],
    [MM.baron,   _cleanObj(p.baron_state   || p.baron)],
    [MM.herald,  _cleanObj(p.herald_state  || p.herald)],
  ]) {
    if (elm) elm.dataset.raw = val;
  }
  _tickObjectiveCountdowns();
  // Keep self-spell CDs current - feeds the header summoner-spell pill.
  _snapshotSpells(p.ally_spells);
  _tickSpellCooldowns();
  renderItemValueDiff(p);
  renderMinimapCanvases(p);
  // S144-U-261: the tower / team score / game time chips left this panel
  // 2026-04-23 (header row 2 carries those signals); their MM slots, the
  // guarded writes here and in the 1 s tick, and their item_build.css
  // icon tints are retired with them.
  // Guard: tests/snapshot_panels/test_minimap_dead_chip_writes_retired.py.

  // S144-U-256: the MAP STATE heartbeat line under the minimap image is
  // retired. It sat in #minimap, which renders in no view, yet every
  // envelope rewrote it and restarted its heart through a forced reflow,
  // and the first one started a 1 s age timer for the page's life.
  // Guard: tests/snapshot_panels/test_minimap_state_line_retired.py.
  state.lastTouch.minimap = Date.now() / 1000;
}

// Lightweight ephemeral burst above the KDA pill - kill/assist/death
// surfaces briefly then fades. One-shot DOM elements so overlaps

// Live spell-cooldown state. Each key is champion|spell, value is
// {remaining: seconds, anchor: Date.now()}. On state re-emit we
// snapshot, on tick we recompute visible remaining time.
state.spellCds = {};
function _spellKey(champ, spell) {
  return (champ || "") + "|" + (spell || "");
}
function _snapshotSpells(spellsMap) {
  // Merge fresh spell cooldowns from the state payload.
  // Only overwrite when the incoming timer is meaningfully different
  // to avoid resetting a smooth tick on every 3s re-emit.
  const now = Date.now();
  for (const champ of Object.keys(spellsMap || {})) {
    const slots = spellsMap[champ] || [];
    slots.forEach(s => {
      if (typeof s !== "object" || !s.spell) return;
      const key = _spellKey(champ, s.spell);
      const incoming = typeof s.cd_remaining_s === "number" ? s.cd_remaining_s : 0;
      const prev = state.spellCds[key];
      if (!prev || Math.abs(prev.remaining - _currentSpellCd(key)) > 2) {
        state.spellCds[key] = { remaining: incoming, anchor: now };
      }
    });
  }
}
function _currentSpellCd(key) {
  const rec = state.spellCds[key];
  if (!rec) return 0;
  const elapsed = (Date.now() - rec.anchor) / 1000;
  return Math.max(0, Math.round(rec.remaining - elapsed));
}


export {
  MM,
  renderMinimap,
  _tickSpellCooldowns, _tickObjectiveCountdowns,
  _updateGameClock, _applyGamePhase,
  _snapshotSpells, _fmtMMSS,
  // RM-1211: main.js calls both; unexported, each call threw a ReferenceError.
  _spellKey, renderMinimapCanvases,
  // S144-U-255: test seam for the relocated item-value bar.
  renderItemValueDiff,
};
