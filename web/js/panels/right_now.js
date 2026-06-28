// Right Now panel - immediate coaching actions, game-sense, stats, digest.
import { el, safe, fmtList, classifyAction, isArenaPayload, logLine, _formatRelativeAge } from '../lib/helpers.js';
import { state } from '../lib/state.js';
import { selectPrimary, shouldPulse, signalFromState } from '../lib/overlay_priority.js';
import { isFightCue, makeCombatLatch } from '../lib/combat_mode.js';
import { condenseKvRows } from '../lib/condense.js';

// RC2 P3.3 SHADOW: the previous S0 cue across renders, for shouldPulse's
// cross-detection. Module scope so it survives between renderRightNow calls.
let _s0PrevCue = "none";

// QA9: combat-mode declutter latch. Module scope so the hysteresis hold
// survives between renders (the overlay sheds non-urgent panes while a fight
// holds; overlay.css gates the shed on body[data-shell="overlay"][data-fight]).
const _combatLatch = makeCombatLatch({});

const RN = {
  root: el("right-now"),
  action: el("rn-action"),
  immediate: el("rn-immediate"),
  risk: el("rn-risk"),
  fight: el("rn-fight-rule"),
  reset: el("rn-reset"),
  staleness: document.querySelector('.staleness[data-for="right-now"]'),
};

// ── Panel renderers ─────────────────────────────────────────────────

// One-time bind: click the action headline to copy to clipboard.
if (RN.action && !RN.action.dataset.bound) {
  RN.action.style.cursor = "copy";
  RN.action.title = "click to copy the coach's call";
  RN.action.addEventListener("click", () => {
    const text = RN.action.dataset.raw || RN.action.textContent || "";
    if (!text || text === "-") return;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(() => {
        RN.action.classList.add("copied");
        setTimeout(() => RN.action.classList.remove("copied"), 900);
        // Tiny "COPIED" bubble over the action for explicit feedback.
        const bubble = document.createElement("span");
        bubble.className = "copied-bubble";
        bubble.textContent = "COPIED";
        RN.action.appendChild(bubble);
        requestAnimationFrame(() => bubble.classList.add("show"));
        setTimeout(() => bubble.remove(), 900);
      }).catch(() => {});
    }
  });
  RN.action.dataset.bound = "1";
}

function renderWhatWent(p) {
  if (!p) return;
  const goodList = el("ww-good");
  const badList  = el("ww-bad");
  if (!goodList || !badList) return;
  const good = Array.isArray(p.what_went_good)
    ? p.what_went_good.filter(Boolean)
    : (safe(p.what_went_good) ? [safe(p.what_went_good)] : []);
  const bad = Array.isArray(p.what_went_bad)
    ? p.what_went_bad.filter(Boolean)
    : (safe(p.what_went_bad) ? [safe(p.what_went_bad)] : []);
  const fill = (ul, items) => {
    ul.innerHTML = "";
    if (!items.length) {
      const li = document.createElement("li");
      li.className = "ww-empty";
      li.textContent = "-";
      ul.appendChild(li);
      return;
    }
    for (const t of items) {
      const li = document.createElement("li");
      li.textContent = t;
      ul.appendChild(li);
    }
  };
  fill(goodList, good);
  fill(badList, bad);
}

// ── Digest icon + popout ──────────────────────────────────────────
// Queue #5: cross-session digest warning icon in the header. Replaces
// the in-panel trend surfaces that were removed. Click opens a modal-
// style popout with cold-streak / slump / trend data.
function renderDigest(p) {
  if (!p) return;
  const icon = el("digest-icon");
  const label = el("digest-label");
  if (!icon || !label) return;
  // Severity: "alert" > "warn" > neutral.  Coach emits p.digest_state
  // ∈ {none, ok, warn, alert}; icon class reflects it.
  const state = (safe(p.digest_state) || "none").toLowerCase();
  icon.classList.remove("warn", "alert");
  if (state === "alert") icon.classList.add("alert");
  else if (state === "warn") icon.classList.add("warn");
  // Label: short glyph + optional count ("⟳", "⟳ 3L", "⟳ SLUMP")
  const tag = safe(p.digest_label) || (state === "none" ? "-" : state.toUpperCase());
  label.textContent = tag;
  icon.title = safe(p.digest_tooltip) || "cross-session digest";
  // Populate popout fields from the same payload.
  const setd = (id, v) => { const e = el(id); if (e) e.textContent = safe(v) || "-"; };
  setd("dig-state",      p.digest_state_long);
  setd("dig-streak",     p.digest_streak);
  setd("dig-recent",     p.digest_recent);
  setd("dig-kda-trend",  p.digest_kda_trend);
  setd("dig-tod",        p.digest_time_of_day);
  setd("dig-fatigue",    p.digest_fatigue);
  setd("dig-advice",     p.digest_advice);
}
(function bindDigestIcon() {
  const icon = el("digest-icon");
  const pop = el("digest-popout");
  const close = el("digest-popout-close");
  if (!icon || !pop) return;
  // 2026-04-25: populate "TOP INSIGHTS" list from /api/digest each open.
  // Cache for 60 s so reopening within a minute doesn't re-fetch.
  const _DIG = { fetchedAt: 0, items: null };
  function renderInsights(arr) {
    const ul = el("dig-insights");
    const cnt = el("dig-insights-count");
    if (!ul) return;
    ul.innerHTML = "";
    if (!arr || !arr.length) {
      ul.innerHTML = '<li class="dim">no insights yet</li>';
      if (cnt) cnt.textContent = "0";
      return;
    }
    // Sort by severity desc, take top 5.
    const top = arr.slice().sort((a, b) =>
      (b.severity || 0) - (a.severity || 0)).slice(0, 5);
    top.forEach(ins => {
      const sev = (ins.severity || 0);
      const tone = sev >= 0.7 ? "alert" : sev >= 0.4 ? "warn" : "ok";
      const li = document.createElement("li");
      li.className = "ins-row tone-" + tone;
      const tag = document.createElement("span");
      tag.className = "ins-tag";
      tag.textContent = (ins.type || "?").replace(/_/g, " ");
      const msg = document.createElement("span");
      msg.className = "ins-msg";
      msg.textContent = ins.message || "(no message)";
      li.appendChild(tag);
      li.appendChild(msg);
      ul.appendChild(li);
    });
    if (cnt) cnt.textContent = arr.length;
  }
  function refreshInsights(force) {
    const now = Date.now();
    if (!force && _DIG.items && (now - _DIG.fetchedAt) < 60000) {
      renderInsights(_DIG.items);
      return;
    }
    fetch("/api/digest", { cache: "no-store" })
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        _DIG.fetchedAt = now;
        _DIG.items = (data && data.insights) || [];
        renderInsights(_DIG.items);
      })
      .catch(() => renderInsights([]));
  }
  const open = () => { pop.classList.remove("hidden"); refreshInsights(false); };
  const hide = () => pop.classList.add("hidden");
  icon.addEventListener("click", open);
  icon.addEventListener("keydown", e => {
    if (e.key === "Enter" || e.key === " ") { open(); e.preventDefault(); }
  });
  if (close) close.addEventListener("click", hide);
  pop.addEventListener("click", e => { if (e.target === pop) hide(); });
  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && !pop.classList.contains("hidden")) hide();
  });
})();

// ── GAME SENSE panel renderer ─────────────────────────────────────
// Client/aftergame mode populates the 3-row Game Sense block with the
// Early/Mid/Late phase descriptors emitted by the coach. Vocabulary is
// the 12 approved words (see coaches docs). Each word is valence-
// colored so the trio reads as a quick strengths/weaknesses read.
const GAME_SENSE_VALENCE = {
  // Negative (coral)
  chaotic: "v-bad", tilted: "v-bad", drowning: "v-bad",
  scattered: "v-bad",
  // Warning (gold)
  hesitant: "v-warn", reactive: "v-warn",
  // Neutral (text)
  steady: "v-ok",
  // Positive (mint/good)
  composed: "v-good", patient: "v-good", opportunistic: "v-good",
  dominant: "v-good", "on point": "v-good",
};
function _valenceClass(word) {
  if (!word) return "";
  return GAME_SENSE_VALENCE[word.toLowerCase().trim()] || "v-ok";
}
function renderGameSense(p) {
  if (!p) return;
  const gsBlock = el("game-sense-block");
  if (!gsBlock) return;
  // Only show when we actually have game-sense data (post-game state).
  const e = safe(p.game_sense_early);
  const m = safe(p.game_sense_mid);
  const l = safe(p.game_sense_late);
  const hasAny = [e, m, l].some(v => v && v !== "-");
  gsBlock.style.display = hasAny ? "" : "none";
  if (!hasAny) return;
  const triples = [
    ["gs-early", "gs-early-blurb", e, p.game_sense_early_blurb],
    ["gs-mid",   "gs-mid-blurb",   m, p.game_sense_mid_blurb],
    ["gs-late",  "gs-late-blurb",  l, p.game_sense_late_blurb],
  ];
  for (const [wordId, blurbId, word, blurb] of triples) {
    const wEl = el(wordId);
    const bEl = el(blurbId);
    if (wEl) {
      wEl.textContent = (word || "-").toUpperCase();
      wEl.className = "game-sense-word " + _valenceClass(word);
    }
    if (bEl) bEl.textContent = safe(blurb) || "";
  }
  // Trend line - last N matches aggregate. Coach-emitted string.
  const trendEl = el("gs-trend");
  if (trendEl) {
    const trend = safe(p.game_sense_trend);
    trendEl.textContent = trend || "no trend data yet";
    trendEl.style.display = trend ? "" : "none";
  }
}

// ── STATS panel renderer ─────────────────────────────────────────
// Populates the in-game STATS view (replaces Adaptation for in-game
// modes). Each field reads a specific payload key; when the coach hasn't
// emitted that field yet, the placeholder "-" stays. Coach-side work
// to populate these from live-client + Riot API is a separate pass.
//
// Level breakdown math (Lane/Jungle and Jungle Camp rows):
// Both rows compute independently from p.xp_to_next and don't influence
// each other - they show parallel paths to the next level (take lane
// minions OR jungle camps, not a mix).
//
// Lane minion XP (mid-game approximation, patch-independent enough):
//   melee 70, caster 40, siege/cannon 110
//   wave composition: 3 melee + 3 caster (cannon every 3rd wave)
// Algorithm: greedy melees first (higher XP per kill), then casters.
// If melee+caster inside one wave can't reach xp_to_next, switch to
// "Need Full Wave: N" count.
//
// Jungle camp XP average: ~130 per camp (blue 135, red 135, gromp 115,
// raptors 155, wolves 110, krugs 127). ceil(xp_needed / 130) for count.
function _levelBreakdowns(xpNeeded) {
  if (xpNeeded == null || xpNeeded <= 0) {
    return { lane: "at level", jungle: "at level" };
  }
  const MELEE = 70, CASTER = 40;
  const WAVE_MELEE = 3, WAVE_CASTER = 3;
  const WAVE_XP_NO_CANNON = WAVE_MELEE * MELEE + WAVE_CASTER * CASTER; // 330
  let xp = xpNeeded, melee = 0, caster = 0;
  while (xp > 0 && melee < WAVE_MELEE) { melee++; xp -= MELEE; }
  while (xp > 0 && caster < WAVE_CASTER) { caster++; xp -= CASTER; }
  const lane = xp <= 0
    ? `Melee: ${melee} | Caster: ${caster}`
    : `Need Full Wave: ${Math.ceil(xpNeeded / WAVE_XP_NO_CANNON)}`;
  const CAMP_XP = 130;
  const camps = Math.ceil(xpNeeded / CAMP_XP);
  return { lane, jungle: String(camps) };
}
// Post-population pass: most STATS rows have no live producer yet and
// render the "-" placeholder, painting a wall of empty rows mid-game.
// After setv() has filled every row, hide any .stats-row whose value is
// an empty sentinel, then collapse a group whose rows are ALL hidden so
// no orphan section header (e.g. "LANING PHASE") shows. Scoped strictly
// to .stats-group rows - never touches .stats-row elsewhere (ward-heat,
// etc.). Idempotent: only toggles display, no innerHTML rewrites, so a
// row reappears the tick its value latches (e.g. CS @ 10 at 10:00).
const _STAT_EMPTY = new Set(["", "-", "- / -"]);
function _hideEmptyStatRows() {
  // Pass 1 - per-row toggle, scoped strictly to STATS-group rows.
  const rows = document.querySelectorAll(".stats-group .stats-row");
  rows.forEach(row => {
    const valEl = row.querySelector(".stats-val");
    const val = valEl ? (valEl.textContent || "").trim() : "";
    if (_STAT_EMPTY.has(val)) {
      row.style.display = "none";
    } else {
      row.style.display = "";
    }
  });
  // Pass 2 - collapse a group whose rows are ALL hidden so its section
  // title does not float alone; otherwise restore the title.
  const groups = document.querySelectorAll(".stats-group");
  groups.forEach(group => {
    const groupRows = group.querySelectorAll(".stats-row");
    let anyVisible = false;
    groupRows.forEach(row => {
      if (row.style.display !== "none") anyVisible = true;
    });
    const title = group.querySelector(".stats-group-title");
    if (title) title.style.display = anyVisible ? "" : "none";
  });
}
function renderStats(p) {
  if (!p) return;
  const $ = id => el(id);
  const setv = (id, v) => { const e = $(id); if (e) e.textContent = v == null || v === "" ? "-" : v; };
  // LANING PHASE
  // Level row: "Ln - need X xp"
  if (p.level != null && p.xp_to_next != null) {
    setv("st-level", `L${p.level} - need ${p.xp_to_next} xp`);
  } else if (p.level != null) {
    setv("st-level", `L${p.level}`);
  } else {
    setv("st-level", "-");
  }
  // Two independent breakdowns below Level - lane minions vs jungle camps.
  // Neither influences the other; both re-derive from the same xp_to_next.
  const brk = _levelBreakdowns(p.xp_to_next);
  setv("st-level-lane",   brk.lane);
  setv("st-level-jungle", brk.jungle);
  setv("st-cannon",       p.cannon_cs_summary);
  // Spike hit + Next spike collapsed (2026-04-24) - power-spike status
  // now carries the next-item spike hint appended after the level-hit
  // summary so one row covers both views.
  {
    const sh = safe(p.powerspike_status) || "";
    const ns = safe(p.next_spike) || "";
    let v = sh;
    if (ns && ns !== "-") v = sh ? `${sh} · ${ns}` : ns;
    setv("st-spike-status", v || "-");
  }
  setv("st-cs-at-10",     p.cs_at_10);
  setv("st-csd-15",       p.csd_at_15);
  setv("st-gd-15",        p.gd_at_15);
  setv("st-wave-now",     p.wave_state_now);
  setv("st-back-gold",    p.back_gold_summary);
  setv("st-enemy-side",   p.enemy_side_pct);
  setv("st-build-dev",    p.build_deviation);
  setv("st-waves",        p.wave_control);
  setv("st-trades",       p.trade_winrate);
  setv("st-roams",        p.roams_summary);
  setv("st-freezes",      p.wave_freezes);
  setv("st-jungle-path",  p.jungle_pathing);
  setv("st-lane-prio",    p.lane_prio);
  setv("st-enemy-mastery",p.enemy_laner_mastery);
  setv("st-first-recall", p.first_recall_timing);
  // COMBAT
  setv("st-kp",           p.kill_participation_pct);
  setv("st-dmg-share",    p.damage_share_summary);
  setv("st-dmg-taken",    p.damage_taken_summary);
  setv("st-cc",           p.cc_score_summary);
  setv("st-heal",         p.heal_shield_summary);
  setv("st-peel",         p.peel_on_carry);
  // Alive/Dead collapsed - two lines worth of info ("28s dead" +
  // "98% alive") on one row so the reader sees the death cost and
  // life ratio together.
  {
    const td = safe(p.time_dead_summary) || "";
    const ta = safe(p.time_alive_pct) || "";
    let v = td;
    if (ta && ta !== "-") v = td ? `${td} · alive ${ta}` : `alive ${ta}`;
    setv("st-time-dead", v || "-");
  }
  setv("st-skillshot",    p.skillshot_summary);
  setv("st-combo-hit",    p.combo_hit_rate);
  setv("st-engage",       p.engage_count);
  setv("st-ult-eff",      p.ult_efficiency);
  setv("st-tf-outcomes",  p.teamfight_outcomes);
  setv("st-dive",         p.dive_outcomes);
  setv("st-flash-disc",   p.flash_discipline);
  setv("st-solo-death",   p.solo_death_rate);
  setv("st-top-threat",   p.top_enemy_threat);
  setv("st-comp-id",      p.team_comp_id);
  setv("st-carry-idx",    p.carry_index);
  setv("st-aa-mix",       p.auto_attack_mix);
  setv("st-wasted-clicks",p.wasted_clicks);
  setv("st-apm",          p.apm);
  setv("st-reaction",     p.reaction_time);
  setv("st-cancel-windows",p.cancel_windows);
  setv("st-anim-cancels", p.animation_cancels);
  setv("st-fight-window", p.fight_windows);
  setv("st-wall-deaths",  p.wall_collision_deaths);
  setv("st-death-heat",   p.death_locations);
  setv("st-death-pattern",p.death_pattern);
  setv("st-winc",         p.wincon_ability_up);
  setv("st-ally-summs",   p.ally_summs_up);
  setv("st-flank",        p.flank_success);
  // MAP PRESENCE
  setv("st-vision",       p.vision_summary);
  setv("st-trinket",      p.trinket_uptime);
  setv("st-pink-uptime",  p.pink_ward_uptime);
  setv("st-vision-denied",p.vision_denied);
  setv("st-obj-setup",    p.objective_setup);
  setv("st-obj-dance",    p.objective_dance);
  setv("st-baron-prep",   p.baron_prep);
  setv("st-scuttle",      p.scuttle_control);
  setv("st-jg-track",     p.jungler_tracking);
  setv("st-split-push",   p.split_push_pressure);
  // IDENTITY
  setv("st-mastery",      p.mastery_summary);
  setv("st-runes",        p.runes_chosen);
  setv("st-spike-map",    p.power_spike_map);
  // Matchup row collapsed (2026-04-24 reorganize) - both history and
  // counter warning surface on the same line so the eye sees "this
  // opponent, here's the record + threat" in one glance.
  const mh = safe(p.matchup_history) || "";
  const cw = safe(p.counter_warning) || "";
  let matchup = mh;
  if (cw && cw !== "-") matchup = mh ? `${mh} · ${cw}` : cw;
  setv("st-matchup", matchup || "-");
  setv("st-champ-key",    p.champ_key_metric);
  setv("st-keystone",     p.keystone_procs);
  setv("st-rune-adapt",   p.rune_adapt_hint);
  // RANK / SESSION
  setv("st-rank",         p.current_rank_lp);
  setv("st-lp-forecast",  p.lp_forecast);
  // Session row collapsed - LP delta + session duration on one line.
  {
    const sd = safe(p.lp_session_delta) || "";
    const dur = safe(p.session_duration) || "";
    let v = sd;
    if (dur && dur !== "-") v = sd ? `${sd} · ${dur}` : dur;
    setv("st-session-delta", v || "-");
  }
  setv("st-gold-diff-trend", p.team_gold_diff_trend);
  setv("st-promo",        p.promo_status);
  setv("st-goal",         p.rank_goal_progress);
  setv("st-break",        p.break_recommendation);
  setv("st-lobby-mmr",    p.lobby_mmr);
  setv("st-benchmark",    p.rank_benchmark);
  setv("st-improve",      p.improvement_target);
  setv("st-chat-tone",    p.chat_tone);
  // Perf row collapsed - strength (+) and weakness (−) of the game
  // in one line, sign-prefixed so the eye reads both as a unit.
  {
    const sg = safe(p.strength_of_game) || "";
    const wg = safe(p.weakness_of_game) || "";
    const parts = [];
    if (sg && sg !== "-") parts.push(`+ ${sg}`);
    if (wg && wg !== "-") parts.push(`− ${wg}`);
    setv("st-strength", parts.join("   ") || "-");
  }
  setv("st-adjust",       p.adjustment_rate);
  setv("st-tilt",         p.tilt_meter);
  setv("st-comeback",     p.comeback_odds);
  setv("st-comp-align",   p.comp_alignment);
  setv("st-wincon-phase", p.wincon_phase);
  setv("st-session-compare",p.session_to_session_delta);
  setv("st-game-eta",     p.game_close_eta);
  setv("st-comp-synergy", p.comp_synergy);
  setv("st-self-judge",   p.self_judgement);
  setv("st-coach-use",    p.coach_interventions);
  // Final pass - collapse the dash-wall of producerless rows.
  _hideEmptyStatRows();
}

function renderRightNow(p) {
  const arena = isArenaPayload(p);
  let rawAction = safe(p.action);
  // DEAD state: the coral `DEAD Ns` pill in the header is the authoritative
  // countdown. When the coach echoes "DEAD - 18s" as the action headline,
  // rewrite so the big text carries the 1-line next-action (headline) and
  // the sub-headline carries the 1-line why/threat - matching the live-
  // game pattern (action = what to do, immediate = detail). Both kept to
  // 1 sentence so the panel reads without duplication.
  let overriddenImmediate = null;
  if (p.is_dead && /^\s*[⚠✓►•⚡⛔🚨✳▶◉→⛔]?\s*DEAD\b/i.test(rawAction)) {
    const immStr = safe(p.immediate) || "";
    const sentences = immStr.split(/(?<=[.!?])\s+/).map(s => s.trim()).filter(Boolean);
    if (sentences.length >= 2) {
      // Convention: last sentence = actionable next-step; earlier = why.
      rawAction = sentences[sentences.length - 1].replace(/\.$/, "");
      overriddenImmediate = sentences.slice(0, -1).join(" ");
    } else if (sentences.length === 1) {
      rawAction = sentences[0].replace(/\.$/, "");
      overriddenImmediate = safe(p.next) || "";
    } else if (safe(p.next)) {
      rawAction = safe(p.next);
    }
  }
  const hasAction = !!rawAction;
  const klass = hasAction ? classifyAction(rawAction) : "empty";
  // RC2 P3.3 (spec sections 4+5 / acceptance A2+A5): compute the S0
  // single-winner arbitration + the pulse-rationing decision, STAMP them on
  // the panel root (data-s0-cue / data-s0-tier / data-s0-pulse), and now
  // AUTHORITATIVELY gate the live change-pulse on the decision. Operator-
  // approved 2026-06-22 (LIVE flip; was shadow-only). The decision rations
  // motion to the EMERGENCY tier + a one-shot URGENT cross (spike/choices),
  // so benign 'good' / re-emit headline changes no longer pulse. Conservative
  // by construction: _s0Pulse is a strict subset of the old isFreshAction
  // pulse set, so this only ever SUPPRESSES a pulse that fires today, never
  // adds one. overlay_pulse.js consumes the same data-s0-pulse stamp.
  // Best-effort: a decision throw must never break the live render (and on a
  // throw _s0Pulse stays false -> the .action pulse simply stays silent, the
  // safe direction).
  let _s0Pulse = false;
  try {
    const _sig = signalFromState(p, klass);
    const _sel = selectPrimary(_sig);
    _s0Pulse = shouldPulse(_s0PrevCue, _sel);
    if (RN.root) {
      RN.root.dataset.s0Cue = _sel.cue;
      RN.root.dataset.s0Tier = _sel.tier;
      RN.root.dataset.s0Pulse = _s0Pulse ? "1" : "0";
    }
    // QA9: stamp the combat-mode flag off the SAME S0 arbitration (so the
    // declutter and the pop-out can never disagree about "is this a fight"),
    // through the hysteresis latch so a brief mid-fight headline change does
    // not strobe the panes. Body-level + inert on the dashboard (overlay.css
    // gates the actual shed on body[data-shell="overlay"][data-fight="1"]).
    if (document.body) {
      if (_combatLatch.update(isFightCue(_sel))) {
        document.body.dataset.fight = "1";
      } else {
        delete document.body.dataset.fight;
      }
    }
    _s0PrevCue = _sel.cue;
  } catch (_e) { /* shadow only - never disturb the live render */ }
  // Detect content change for fresh-state flash - only pulse when the
  // headline actually changes, not on every re-emit of the same text.
  const prevAction = RN.action.dataset.raw || "";
  const isFreshAction = hasAction && rawAction !== prevAction;
  if (isFreshAction) {
    RN.root.classList.remove("rn-fresh");
    void RN.root.offsetWidth;
    RN.root.classList.add("rn-fresh");
    setTimeout(() => RN.root.classList.remove("rn-fresh"), 1200);
  }
  RN.action.dataset.raw = rawAction;
  RN.action.className = "action action-" + klass;
  // 2026-05-20 UI polish: per-band pulse on the .action element itself
  // when the headline text changes. classifyAction() bands map to the
  // tokens.css coach-pulse-{good,warn,bad} keyframes. "empty" stays
  // silent (no headline -> nothing to pulse). The pulse class is
  // dropped 800ms later so a stable headline does not retain it.
  //
  // RC2 P3.3 LIVE flip (operator-approved 2026-06-22, A5 motion rationing):
  // gate the pulse on the S0 decision (_s0Pulse) IN ADDITION to a fresh
  // headline. The decision only allows motion for the EMERGENCY tier
  // (incl. the lethal cue, which carries the lethal_incoming passthrough)
  // and a one-shot URGENT cross (spike/choices). A benign 'good' band and a
  // sustained-same-cue re-emit no longer add rn-pulse-good/warn/bad. This is
  // STRICTLY a subset of the old isFreshAction condition (suppress-only,
  // never a new pulse).
  if (isFreshAction && _s0Pulse) {
    const pulseMap = { urgent: "rn-pulse-bad",
                       fight:  "rn-pulse-warn",
                       good:   "rn-pulse-good" };
    const pulseClass = pulseMap[klass];
    if (pulseClass) {
      RN.action.classList.remove("rn-pulse-good", "rn-pulse-warn", "rn-pulse-bad");
      void RN.action.offsetWidth;
      RN.action.classList.add(pulseClass);
      setTimeout(() => RN.action.classList.remove(pulseClass), 800);
    }
  }
  // Priority glyph prefix - a quick shape-read for peripheral vision.
  // Skip the glyph when we have no action text to avoid a lonely "►".
  // Also skip if the fixture/coach already starts the string with a
  // matching glyph, to avoid double "⚠ ⚠ DEFEAT".
  const glyph = klass === "urgent" ? "⚠ "
              : klass === "good"   ? "✓ "
              :                      "► ";
  const alreadyGlyphed = hasAction && /^[⚠✓►•⚡⛔🚨✳▶◉→]/.test(rawAction);
  // Fixed-height .action slot with CSS line-clamp (see .action in
  // dashboard.css). No fitText shrinking - font stays at the CSS-defined
  // 48-56px, long content ellipsizes at line 2. Short content sits at
  // the top of the fixed 130px box; the box itself never changes size
  // so subsequent rows stay pinned across fixtures.
  RN.action.textContent = hasAction
    ? (alreadyGlyphed ? rawAction : glyph + rawAction)
    : "-";
  // 2026-05-25 (item 189): the LLM coaches no longer emit Immediate/Next
  // prose - the Choices array (Alt+1/2/3 hotkey-selectable chips rendered
  // by web/js/panels/coach_choices.js into #rn-choices) is the primary
  // actionable surface now. If choices are non-empty, hide #rn-immediate
  // entirely so the chips occupy the slot below #rn-action. If choices
  // are empty (no decision on the clock, dead waiting respawn, mid-base,
  // or pre-game-pregame) fall through to whatever prose the coach still
  // emits (pregame for arena, plain p.immediate for replay-cached data).
  const hasChoices = Array.isArray(p.choices) && p.choices.length > 0;
  RN.immediate.hidden = hasChoices;
  if (hasChoices) {
    RN.immediate.classList.remove("is-pregame");
    RN.immediate.textContent = "";
  } else if (arena) {
    // Arena: in pregame (no round yet / no round_strategy), surface the
    // full pregame card as the immediate content. Once the live coach
    // starts writing round_strategy, swap to that.
    const liveStrategy = safe(p.round_strategy);
    const hasLiveRound = (typeof p.round === "number" && p.round > 0) || !!liveStrategy;
    const imm = hasLiveRound
      ? (liveStrategy || safe(p.immediate) || "-")
      : (safe(p.pregame) || safe(p.immediate) || "-");
    RN.immediate.classList.toggle("is-pregame", !hasLiveRound && !!safe(p.pregame));
    RN.immediate.textContent = imm;
  } else {
    RN.immediate.classList.remove("is-pregame");
    // DEAD-state rewrite (see top of function) replaces p.immediate with a
    // single-sentence "why" so headline and sub don't duplicate each other.
    const immText = overriddenImmediate !== null
      ? overriddenImmediate
      : (safe(p.immediate) || safe(p.pregame) || "-");
    RN.immediate.textContent = immText;
  }
  RN.risk.textContent   = safe(p.risk) || "-";
  RN.fight.textContent  = safe(p.fight_rule) || "-";
  // Reset item: if the text has a "(Ng)" price tag, color-code by
  // whether the current gold clears it. "Dark Seal + boots (950g)".
  if (RN.reset) {
    const resetTxt = safe(p.reset_item) || "-";
    const mg = /\((\d+)\s*g\)/.exec(resetTxt);
    RN.reset.textContent = resetTxt;
    RN.reset.classList.remove("can-afford", "short-gold");
    if (mg && typeof p.gold === "number") {
      const need = +mg[1];
      RN.reset.classList.add(p.gold >= need ? "can-afford" : "short-gold");
    }
  }
  // Arena has no SR-style reset. Repurpose the slot for target priority
  // (who to focus) since that's the single highest-value per-fight datum.
  if (arena) {
    const tgt = safe(p.target_priority);
    RN.reset.textContent = tgt || safe(p.anvil_advice) || "-";
    RN.reset.parentElement.firstElementChild.textContent = "Target";
  } else {
    RN.reset.textContent = safe(p.reset_item) || "-";
    RN.reset.parentElement.firstElementChild.textContent = "Base";
  }
  // RC2 P3.6 dashboard condensation: collapse the supporting KV rows
  // (Watch / Fight / Base) that paint the "-" no-data sentinel in
  // client / pregame / ARAM states so the glance lands on populated rows.
  // Idempotent; overlay-inert (those .kv rows are display:none !important in
  // the ?overlay=1 shell, so this only reshapes the dashboard surface).
  condenseKvRows(RN.root);
  state.lastTouch.right_now = Date.now() / 1000;
}

export { RN, renderRightNow, renderWhatWent, renderDigest, renderGameSense, renderStats };
