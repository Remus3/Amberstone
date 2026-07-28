// Next panel - wave state, objective row, arena partner info.
import { el, safe, isArenaPayload } from '../lib/helpers.js';
import { state } from '../lib/state.js';
import { formatDsDelta } from '../lib/scorer_units.js';
import { condenseKvRows } from '../lib/condense.js';

const NX = {
  root: el("next"),
  next: el("nx-next"),
  objective: el("nx-objective"),
  positioning: el("nx-positioning"),
  wave: el("nx-wave"),
  staleness: document.querySelector('.staleness[data-for="next"]'),
};

// -- Wave state (Next panel) --------------------------------------
// SR has 3 lanes; we show all three on separate lines with the
// player's own lane marked >. Each percentage is colored AND
// suffixed with the action verb so the eye reads value + intent
// in one glance.
//
//   <= 30 %       wave-our   (icy blue)      -> FREEZE
//   30 - 65 %     wave-mid   (potion green)  -> TRADE
//   65 - 80 %     wave-warn  (gold)          -> CRASH
//   >= 80 %       wave-bad   (vibrant red)   -> DISENGAGE
//   null / -      wave-dim   (faint)         (no suffix)
function _classifyWavePct(pct) {
  if (pct == null || isNaN(pct)) return "wave-dim";
  if (pct >= 80) return "wave-bad";
  if (pct >= 65) return "wave-warn";
  if (pct <= 30) return "wave-our";
  return "wave-mid";
}
function _waveSuffix(pct) {
  if (pct == null || isNaN(pct)) return "";
  if (pct >= 80) return " → DISENGAGE";
  if (pct >= 65) return " → CRASH";
  if (pct <= 30) return " → FREEZE";
  return " → TRADE";
}
function _waveVerb(pct) {
  if (pct == null || isNaN(pct)) return "";
  if (pct >= 80) return "DISENGAGE";
  if (pct >= 65) return "CRASH";
  if (pct <= 30) return "FREEZE";
  return "TRADE";
}
function _waveLineHtml(lane, pct, isMine) {
  // (2026-04-25) Each lane wrapped in a `.wave-line` block so it
  // renders as exactly one row (white-space:nowrap) - earlier the
  // <br>-separated inline form let BOT's "50%" wrap to a 4th line
  // when the inline span sat at a sub-pixel-tight width. Marker is
  // a fixed-width slot so the lane labels TOP/MID/BOT line up by
  // column whether or not the > is present.
  const cls    = _classifyWavePct(pct);
  const pctTxt = (pct == null || isNaN(pct)) ? "-" : `${Math.round(pct)}%`;
  const verb   = _waveVerb(pct);
  // Each segment in its own fixed-width span so the four columns
  // (label / pct / arrow / verb) lock to identical X positions
  // across all rows, regardless of value length. Marker is absolutely
  // positioned in CSS so it doesn't push the lane label.
  const marker = isMine ? `<span class="wave-marker">▶</span>` : "";
  return `<span class="wave-line">${marker}` +
    `<span class="wave-label">${lane}:</span>` +
    `<span class="wave-pct ${cls}">${pctTxt}</span>` +
    `<span class="wave-arrow ${cls}">→</span>` +
    `<span class="wave-verb ${cls}">${verb}</span>` +
    `</span>`;
}
function _renderWaveState(p) {
  if (!NX.wave) return;
  const m = state.mode;
  if (m === "sr") {
    const lane = String(p.lane || p.role || "").toUpperCase();
    const isTop = lane === "TOP" || lane === "TOPLANE";
    const isMid = lane === "MID" || lane === "MIDDLE";
    const isBot = lane === "BOT" || lane === "BOTTOM" || lane === "ADC"
               || lane === "SUPPORT" || lane === "SUP" || lane === "UTILITY";
    NX.wave.innerHTML = [
      _waveLineHtml("TOP", p.wave_top, isTop),
      _waveLineHtml("MID", p.wave_mid, isMid),
      _waveLineHtml("BOT", p.wave_bot, isBot),
    ].join("");
  } else if (m === "aram" || m === "brawl") {
    // Single-lane modes: just the percentage with classification.
    const pct = p.wave_pct;
    if (pct == null) {
      NX.wave.textContent = safe(p.wave) || "-";
    } else {
      const cls = _classifyWavePct(pct);
      NX.wave.innerHTML = `<span class="wave-pct ${cls}">${Math.round(pct)}%</span>`;
    }
  } else {
    NX.wave.textContent = safe(p.wave) || "-";
  }
}

function renderNext(p) {
  const arena = isArenaPayload(p);
  const aftergame = state.mode === "client";
  if (aftergame) {
    // ADVICE layout for aftergame / client. Headline reads as the
    // coach's session take; body rows relabel to "Objective" (stays),
    // "Key Points to Review" (3 bullets), "What to Review in Clips".
    NX.next.textContent        = safe(p.advice_headline) || safe(p.next) || safe(p.action) || "-";
    NX.objective.textContent   = safe(p.objective) || safe(p.advice_objective) || "-";
    NX.positioning.textContent = safe(p.key_points_review) || safe(p.positioning) || "-";
    NX.wave.textContent        = safe(p.clips_review) || safe(p.wave) || "-";
    const rows = NX.root.querySelectorAll(".kv span:first-child");
    if (rows[0]) rows[0].textContent = "Objective";
    if (rows[1]) rows[1].textContent = "Key Points";
    if (rows[2]) rows[2].textContent = "Clips";
  } else if (state.mode === "aram" || state.mode === "brawl") {
    // ARAM/Brawl/Mayhem coach (coaches/aram_coach.py) doesn't emit
    // next/objective/positioning/wave - those rows would all show "-".
    // Map to fields the coach DOES emit so the panel actually fires.
    // 2026-04-26 user-reported regression mid-game.
    // Headline: reset_item is the "what's next" call (build, recall,
    // pack timing). If the coach left it blank, fall back to action.
    const _resetTxt = safe(p.reset_item);
    const _action = safe(p.action) || "";
    let _head = _resetTxt;
    if (!_head || _head === _action) _head = safe(p.next) || _action || "";
    NX.next.textContent = _head || "-";
    // Objective row -> item rationale (item_extra) - long-form per-item
    // build context. Truncated by CSS line-clamp.
    // (2026-05-09) DS top pick fallback: when the coach hasn't emitted
    // item_extra/objective yet, surface the engine's top recommendation
    // as a one-liner so the row carries useful build content from tick 1
    // instead of a "-". Coach text wins when present; DS only fills the
    // gap because the engine fires on every coaching cycle.
    const _objCoach = safe(p.item_extra) || safe(p.objective);
    if (_objCoach) {
      NX.objective.textContent = _objCoach;
    } else {
      const _dsTop = Array.isArray(p.daemon_slayer_picks) && p.daemon_slayer_picks[0];
      if (_dsTop && _dsTop.name) {
        const _d = formatDsDelta(_dsTop);
        NX.objective.textContent = `DS: ${_dsTop.name} ${_d}`
          + (_dsTop.gold ? ` (${_dsTop.gold}g)` : "");
      } else {
        NX.objective.textContent = "-";
      }
    }
    // Positioning row -> HP pack status (TOP / BOT availability). Coach
    // emits hp_packs as [top:bool, bot:bool].
    const hpPacks = Array.isArray(p.hp_packs) ? p.hp_packs : null;
    let hpLine = "-";
    if (hpPacks && hpPacks.length >= 2) {
      const tag = (b) => (b ? "✓" : "✗");
      hpLine = `TOP ${tag(hpPacks[0])} · BOT ${tag(hpPacks[1])}`;
    } else if (safe(p.positioning)) {
      hpLine = safe(p.positioning);
    }
    NX.positioning.textContent = hpLine;
    // Wave row -> wave_pct (int 0-100) - minion wave progress.
    const wp = p.wave_pct;
    NX.wave.textContent = (typeof wp === "number")
      ? `${wp}% to next wave` : (safe(p.wave) || "-");
    const rows = NX.root.querySelectorAll(".kv span:first-child");
    if (rows[0]) rows[0].textContent = "Build";
    if (rows[1]) rows[1].textContent = "HP Packs";
    if (rows[2]) rows[2].textContent = "Wave";
  } else if (arena) {
    // Headline: round # + rank + alive teams, since those drive every decision.
    // `round` is the coach's "~N" approximate label, or "" in the blank
    // artifact written at coach init (see coaches/arena_coach.py
    // _blank_artifact_data). Guard on truthiness, not != null, so the blank
    // falls through to the action fallback below instead of rendering a
    // dangling "Round " with no number.
    const rd = p.round ? `Round ${p.round}` : "";
    const rk = p.rank != null && p.rank !== "?" ? `#${p.rank}/${p.alive_teams || 8}` : "";
    const head = [rd, rk].filter(Boolean).join(" · ") || safe(p.action) || "-";
    NX.next.textContent = head;
    // Objective -> anvil advice (what to buy/take between rounds)
    NX.objective.textContent   = safe(p.anvil_advice) || "-";
    // Positioning -> partner name + synergy one-liner
    NX.positioning.textContent = arenaPartnerLine(p);
    // Wave -> camp-phase or next-opponent hint
    NX.wave.textContent        = arenaWaveLine(p);
    // Relabel KV keys for arena context
    const rows = NX.root.querySelectorAll(".kv span:first-child");
    if (rows[0]) rows[0].textContent = "Anvil";
    if (rows[1]) rows[1].textContent = "Partner";
    if (rows[2]) rows[2].textContent = "Camp/Opp";
  } else {
    // Fixed font, no shrink. Readability matters more than fit - the
    // coach is expected to produce concise, glanceable copy. Hard 2-line
    // cap on headline and 3-line cap on body rows is enforced by CSS
    // -webkit-line-clamp; anything longer gets ellipsized rather than
    // resized to an unreadable small font.
    // Dedup (2026-04-25): the headline used to fall back to p.action
    // when p.next was empty, which produced an exact echo of the Right
    // Now panel headline (e.g. both saying "FOUNTAIN NOW" while dead).
    // Now we only fall back to p.action if it's strictly different;
    // otherwise show "-" so the duplication is visible rather than
    // pretending two coaching slots have content.
    const _action = safe(p.action) || "";
    let _nextHead = safe(p.next);
    if (!_nextHead || _nextHead === _action) _nextHead = "";
    NX.next.textContent        = _nextHead || "-";
    NX.objective.textContent   = safe(p.objective)   || "-";
    NX.positioning.textContent = safe(p.positioning) || "-";
    // (2026-04-25) Wave state: SR shows all-three-lanes per row with a
    // > marker on the player's lane and color-coded percentages
    // matching coach-prompt thresholds. Other modes (ARAM single-lane,
    // Brawl, Arena, TFT) keep the simple "wave NN%" or fall through.
    _renderWaveState(p);
    const rows = NX.root.querySelectorAll(".kv span:first-child");
    if (rows[0]) rows[0].textContent = "Objective";
    if (rows[1]) rows[1].textContent = "Position";
    if (rows[2]) rows[2].textContent = "Waves";
  }
  // RC2 P3.6 dashboard condensation: collapse any supporting KV row left at
  // the "-" no-data sentinel (mode-dependent: SR aftergame Key Points/Clips,
  // arena pre-game partner, etc.) so the NEXT glance carries only live rows.
  // Idempotent; overlay-inert (the overlay does not mount the NEXT panel).
  condenseKvRows(NX.root);
  state.lastTouch.next = Date.now() / 1000;
}

// -- Arena helpers ---------------------------------------------------
// Partner synergy one-liners for the Caitlyn Arena build. Keyed on the
// partner champion detected from the teams payload; falls back to a
// generic line if we don't have a canned combo for this matchup.
const CAITLYN_PARTNER_COMBOS = {
  "Lux":      "Wait for Q root → headshot → R through rooted. Stay 550u behind her shield line.",
  "Orianna":  "Ball on you. Ori R pulls enemies → your trap+R. Net AWAY to drag the ball.",
  "Zoe":      "NEVER engage first. Wait for E sleep → headshot doubles damage → R finisher.",
  "Morgana":  "Q binds = free headshots. E shield blocks their CC; all-in inside her shield.",
  "Leona":    "She engages E+Q, you trap-headshot during her CC chain. Kite after the stun drops.",
  "Nami":     "Nami Q bubble = free headshot. Stay in her E AS-buff range during trades.",
  "Lulu":     "Lulu W polymorph = free headshot. Stay in her shield during all-ins.",
  "Janna":    "Janna shield bonus AD on your autos. R disengage lets you kite-reset any fight.",
  "Soraka":   "Sustain pair - poke with R + traps, she globals you at 30% HP. Avoid all-ins.",
  "Seraphine":"Triple-note stun = full burst window. Stack her shield then all-in.",
};
function arenaDetectPartner(p) {
  if (!Array.isArray(p.teams)) return "";
  const partner = p.teams.find(t => t && t.is_partner);
  if (!partner) return "";
  return String(partner.name || partner.champion || "").trim();
}
function arenaPartnerLine(p) {
  const partner = arenaDetectPartner(p);
  if (!partner) {
    // Pre-game: surface the planned partner from the pregame card header.
    const pre = safe(p.pregame);
    const m = pre.match(/PARTNER:\s*([A-Za-z][A-Za-z']+)/);
    if (m) {
      // Pregame header is all-caps ("PARTNER: LUX"); combo table is title-case.
      const name = m[1][0].toUpperCase() + m[1].slice(1).toLowerCase();
      return `${name} (planned) - ${CAITLYN_PARTNER_COMBOS[name] || "synergy loads at game start."}`;
    }
    return "-";
  }
  const combo = CAITLYN_PARTNER_COMBOS[partner] || "Stay 550-600u back. Peel for each other.";
  return `${partner} - ${combo}`;
}
function arenaWaveLine(p) {
  if (p.camp_phase) return "CAMP - buy/upgrade + heal";
  if (!Array.isArray(p.teams)) return "-";
  const nxt = p.teams.find(t => t && t.is_next_opponent);
  if (nxt) {
    const hp = nxt.hp_pct != null ? ` (${nxt.hp_pct}% HP)` : "";
    return `vs ${nxt.name || nxt.champion || "?"}${hp}`;
  }
  return "-";
}

export { NX, renderNext, arenaDetectPartner, arenaPartnerLine, arenaWaveLine };
