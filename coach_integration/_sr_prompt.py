# arch: SR prompt building - system prompt, helpers, WaveTracker | section=coaching | frozen=no
"""SR-specific prompt assembly: system prompt, data loaders, _build_user_prompt, WaveTracker."""

import json
import time
import logging
from collections import deque
from pathlib import Path

from core.death_patterns_loader import personal_context_block
from core.enemy_cc_threat_context import enemy_cc_threat_line

logger = logging.getLogger("coach")

# Points to project root (parent of this package dir).
_CI_APP_DIR = Path(__file__).parent.parent

def _load_sr_rune_rec(champion: str) -> str:
    """Load SR rune recommendation string for a champion."""
    try:
        p = _CI_APP_DIR / "data" / "meta_build" / "rune_recommendations_sr.json"
        if not p.exists():
            return ""
        data = json.loads(p.read_text(encoding="utf-8"))
        rec = data.get(champion)
        if not rec or not isinstance(rec, dict):
            return ""
        ks   = rec.get("keystone", "")
        pri  = rec.get("primary_tree", "")
        sec  = rec.get("secondary_tree", "")
        note = rec.get("coaching_note", "")
        result = f"{ks} | {pri} / {sec}"
        if note:
            result += f" - {note}"
        return result
    except Exception:
        return ""


# ── Summoner's Rift system prompt ─────────────────────────────────────────────

SR_SYSTEM_PROMPT = """\
You are coaching a challenger-level ADC in Summoner's Rift. Skip all basics. \
Give decision-quality, specific advice only.

CHAMPION: {profile}
Recommended runes: {sr_rune_rec}
Item build path: {sr_build_note}
{adaptation_hint}

\u2550\u2550\u2550 ABSOLUTE PRIORITY ORDER \u2550\u2550\u2550
1. HP floor \u2014 never fight below 35% unless sieging inhibitor/nexus
2. Wave tempo \u2014 know where the next wave goes BEFORE any macro move
3. Dead-enemy window \u2014 respawn timers define your action window exactly
4. Objective rotation \u2014 arrive before spawn, or crash wave first if you can't
5. Camp efficiency \u2014 take camps only when on the path, <20s off route

\u2550\u2550\u2550 LANE TRADE RULES \u2550\u2550\u2550
Trade favorable when you have \u22652 of: HP advantage >15%, level even or ahead, \
item spike active, support CC available, enemy key ability on CD.
All-in condition: all of the above PLUS their escape is on CD.
Hard-reset (disengage immediately): HP below 40%, support dead, jungler MIA >30s.
Poke reset window: after landing your key ability, reset position before their retaliation.
Power difference: if enemy hit item spike you haven't hit yet \u2014 play passive until you match.

\u2550\u2550\u2550 WAVE \u2192 OBJECTIVE \u2550\u2550\u2550
\u2022 3+ enemies dead 45s+ \u2192 force EVERYTHING: wave\u2192camps\u2192objective\u2192structure
\u2022 2 dead 30s+ \u2192 crash wave, take path camps, contest objective
\u2022 1 jungler/mid dead \u2192 rotate if you arrive before their respawn
\u2022 No deaths, objective <90s \u2192 hold/thin wave, position at 60s mark
\u2022 Floating wave mid-lane \u2192 NEVER rotate; crash it first

\u2550\u2550\u2550 GANK THREAT & POSITIONING \u2550\u2550\u2550
High gank threat (MIA >30s or jg-bot sighting): hug wave, play toward own side, \
do not push past safe boundary until threat resolved.
Overextended: if you are past enemy T1 without ward, recall or wave is your only exit.
Support distance: if support is >8s walk away, reduce trade aggression by 50%.
Poke angle: stand behind your own minion line to trade safely; \
deny the enemy's best angle with side-step positioning.
Gank enable: when your jungler is nearby, step up in lane to bait enemy forward, \
then let jungler close the angle.

\u2550\u2550\u2550 JUNGLE CAMPS ON PATH \u2550\u2550\u2550
Camp gold: krugs ~160g, raptors ~145g, red buff ~100g, blue buff ~80g.
Rule: take if \u226420s off path to next objective AND objective spawn >40s away.
Never take a camp if it delays your arrival past objective spawn time.

\u2550\u2550\u2550 WARD TIMING (PRIORITY ORDER) \u2550\u2550\u2550
1. 1:30 \u2014 river tri-brush ward before scuttle at 3:15
2. 4:45 \u2014 drake pit entrance before 5:00 spawn
3. Every recall \u2014 buy one control ward, place river/pixel bush
4. After crashing wave \u2014 ward the river bush before crossing
5. Baron window (20min+) \u2014 ward baron pit mouth at 19:30

\u2550\u2550\u2550 BASE TIMING \u2550\u2550\u2550
Recall after wave crashes under enemy tower \u2014 never abandon a floating wave.
Recall minimum: 700g OR item component toward next spike.
At 50% HP with wave crashed \u2192 base, no exceptions.

\u2550\u2550\u2550 ENDING / SIDE WAVES \u2550\u2550\u2550
Before baron: crash ALL 3 waves to prevent backdoor retaliation.
After baron: ADC takes bot/mid push lane \u2014 NOT baron lane (that's for the tank).
Inhibitor down: clear bot wave every 20-25s to perpetuate super-minion pressure.
Nexus turrets exposed: STOP everything, group, end \u2014 no exceptions.
Backdoor enemy racing you: end faster on your side unless you have TP.


NAME TAGS - mandatory in every field:
  Ally champions: [A]Name[/A]   Enemy champions: [E]Name[/E]   Timings: [T]value[/T]
  Apply to the exact champion name only. e.g. [A]Hecarim[/A] ganks, [E]Caitlyn[/E] at [T]4:45[/T]

ALLY vs ENEMY RULE - CRITICAL: never swap these tags.
  YOUR ALLIES (same team, listed under YOUR ALLIES below) - ALWAYS use [A]Name[/A].
  ENEMIES (opposing team, listed under ENEMY TEAM below) - ALWAYS use [E]Name[/E].
  If you are uncertain which team a champion is on, do NOT tag them rather than risk a swap.
  A wrong tag inverts the color on screen and directly misleads the player - this is a hard error.

OUTPUT FORMAT - follow exactly, no preamble. Every field has a hard word cap:
Action: <1-3 WORDS ALL-CAPS macro priority - e.g. PUSH BOT LANE / BASE LOW HP / FREEZE WAVE / FIGHT NOW / GIVE SPACE / DEFEND TOWER / CRASH AND RESET / TAKE DRAKE / TAKE BARON / END GAME>
Immediate: <concise 3-5s action, use [A]/[E] name tags, max 12 words>
Next: <15-30s plan, use [A]/[E] tags and [T] for all timings, max 16 words>
Wave: <state + <=6 word reason>
Objective: <take/setup/skip/rotate-NOW + [T] timing, max 10 words>
Fight rule: <specific condition using [A]/[E] tags + exact mechanic, max 12 words>
Reset / item: <item name + exact gold check, max 8 words>
Risk: <specific threat using [E] tag + mechanic to watch, max 12 words>
Choices: <OPTIONAL compact single-line JSON array of 2-3 micro-decisions the player faces RIGHT NOW. Schema: [{"key":"A","label":"<3-5 word option>","expected_outcome":"<one sentence what likely happens>","confidence":"low" or "mid" or "high","source_tag":"<3-10 char descriptor>"}, ...]. Keys are A/B/C in order. Use confidence honestly: "high" only for textbook plays; "mid" for situational reads; "low" for high-uncertainty calls. Set source_tag to a short descriptor like "lane-state", "rotate-ward", "team-fight", "wave-tempo", "objective-call". Return [] if no clean binary decision is on the clock. Do NOT inflate; an empty array is better than padded choices. Output MUST be a single line of valid JSON (no markdown, no line breaks inside the array).>
""" + personal_context_block()
# \u2500\u2500 ARAM / ARAM Mayhem system prompt \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

ARAM_SYSTEM_PROMPT = """\
You are coaching a challenger-level player in ARAM{mayhem_tag}. \
No wave management. No jungle. Pure team combat on a single lane.

CHAMPION: {profile}

\u2550\u2550\u2550 ARAM PRIORITY ORDER \u2550\u2550\u2550
1. HP \u2014 never go below 30% in poke phase; death = huge gold advantage for enemies
2. Ability timing \u2014 know your full combo and CD before committing
3. Augment usage \u2014 factor your augment bonuses into every decision{augment_line}
4. Position \u2014 stay at max effective range unless all-in conditions met
5. Item efficiency \u2014 ARAM buffs items faster; itemize for constant combat, not spikes

\u2550\u2550\u2550 TRADE PHASES \u2550\u2550\u2550
POKE PHASE (both teams >50% HP): Stay max range. Trade single abilities. \
Retreat to fountain at <40% HP \u2014 ARAM death loss is massive.
SKIRMISH PHASE (1-2 enemies low): Identify kill targets. Commit if your tank is ahead.
ALL-IN CONDITION: Tank engaged + key enemy burst/CC on CD + you have >20% HP \
advantage on your target + escape route is clear.
HARD DISENGAGE: Two or more enemies targeting you, tank dead, or your escape ability on CD.

\u2550\u2550\u2550 ARAM OBJECTIVE TIMING \u2550\u2550\u2550
Turrets \u2014 push ONLY with a numbers advantage after winning a fight.
Inhibitor \u2014 push when 3+ enemies dead with 30s+ respawn.
Do NOT solo-push: ARAM turrets deal extreme damage.
After winning a fight: clear the wave, then rotate all for turret \u2014 do not split.

\u2550\u2550\u2550 ABILITY PRIORITY \u2550\u2550\u2550
Poke phase: lowest-CD poke abilities only \u2014 save burst for all-in.
All-in: lead with CC, follow with burst, auto-attack to finish.
Re-engage: only after at least one key ability is back up.

\u2550\u2550\u2550 ITEM / FOUNTAIN TIMING \u2550\u2550\u2550
Fountain if: HP <30% OR mana <20% OR next item is affordable.
ARAM: you can back freely \u2014 never stay at 20% trying to "get one more hit."
Item priority on ARAM: health/sustain earlier than SR; fights are continuous.
Augments (Mayhem): use augment effects in combo.


NAME TAGS: [A]AllyName[/A]  [E]EnemyName[/E]  [T]timing[/T] - use in all fields.

OUTPUT FORMAT - follow exactly, no preamble:
Action: <1-3 WORDS ALL-CAPS - e.g. ALL IN NOW / FALL BACK / POKE ONLY / GROUP MID / FOUNTAIN NOW / PUSH TURRET>
Immediate: <fight action right now, use [A]/[E] name tags>
Next: <15-30s plan, use [A]/[E] and [T] for timings>
Wave: N/A - ARAM auto-push
Objective: <push/hold/setup/group + [T] timing>
Fight rule: <all-in condition using [A]/[E] tags + exact mechanics>
Reset / item: <fountain timing + next item>
Risk: <specific kill threat using [E] tag + ability to respect>
"""


def _load_sr_build_note(champion: str) -> str:
    """Load SR-specific build note and item path for a champion."""
    try:
        p = _CI_APP_DIR / "data" / "meta_build" / "sr_champion_builds.json"
        if not p.exists():
            return ""
        data = json.loads(p.read_text(encoding="utf-8"))
        entry = data.get(champion)
        if not entry or isinstance(entry, str):
            return ""
        start  = entry.get("start", "")
        fb     = entry.get("full_build", [])
        note   = entry.get("build_note", "")
        recall = entry.get("recall_timing", "")
        vt     = entry.get("vs_tanks", "")
        vh     = entry.get("vs_healing", "")
        build_str = " → ".join(fb) if fb else ""
        result = ""
        if start:    result += f"Start: {start}. "
        if build_str: result += f"Build: {build_str}. "
        if note:     result += note
        if recall:   result += f" | {recall}"
        if vt:       result += f" | vs tanks: {vt}"
        if vh:       result += f" | vs healing: {vh}"
        return result[:400]
    except Exception:
        return ""



def _load_lane_matchup_note(enemy_adc: str) -> str:
    """Load ADC lane matchup note for the enemy ADC/marksman from matchup_weights."""
    try:
        p = _CI_APP_DIR / "data" / "meta_build" / "matchup_weights.json"
        if not p.exists():
            return ""
        data = json.loads(p.read_text(encoding="utf-8"))
        mm = data.get("adc_lane_matchups", {})
        entry = mm.get(enemy_adc)
        if not entry:
            return ""
        diff     = entry.get("difficulty", 0)
        style    = entry.get("lane_style", "")
        note     = entry.get("priority_note", "")[:120]
        mechanic = entry.get("key_mechanic", "")[:100]
        result   = f"{enemy_adc} [diff {diff}/5, {style}]: {note}"
        if mechanic:
            result += f" | Key: {mechanic}"
        return result[:280]
    except Exception:
        return ""


def _vision_tracker_locs() -> str:
    """Read data/vision_state.json (written by core/vision_tracker) and
    return a coach-prompt-ready enemy-locations string. Returns "" if
    the tracker file is missing, stale (>10s), or empty.

    Format mirrors game_reader._derive_enemy_locations so coaches see a
    familiar shape: visible champs first, MIA after, dead at the end.
    The tracker's position-freeze detection is more accurate than the
    legacy (0,0)-based heuristic, especially right after a champion
    enters fog of war (where the legacy reader has a 0-position blind
    spot for ~1s).
    """
    try:
        from pathlib import Path as _P
        p = _P(__file__).parent.parent / "data" / "vision_state.json"
        if not p.exists():
            return ""
        if (time.time() - p.stat().st_mtime) > 10:
            return ""
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return ""
    enemies = d.get("enemies") or {}
    if not enemies:
        return ""
    visible, mia, dead = [], [], []
    for name, e in enemies.items():
        zone = e.get("last_seen_zone") or "?"
        if e.get("is_dead"):
            r = e.get("respawn_in_s")
            dead.append(f"{name} ({int(r)}s)" if isinstance(r, (int, float)) else name)
            continue
        if e.get("visible"):
            visible.append(f"{name} [{zone}]")
        else:
            ago = e.get("missing_for_s")
            if isinstance(ago, (int, float)):
                if ago < 8:
                    visible.append(f"{name} [{zone}]")
                elif ago < 45:
                    mia.append(f"{name} MIA {int(ago)}s ({zone})")
                else:
                    mia.append(f"{name} MIA ({zone} last seen)")
            else:
                mia.append(f"{name} untracked")
    parts = visible + mia
    if dead:
        parts.append(f"Dead: {', '.join(dead)}")
    return "\n".join(parts)


def _build_user_prompt(gs: dict, wave_state: str) -> str:
    """Build a rich context prompt from the full game_reader state dict."""
    # AUDIT 2026-04-28 (deferred-low-value): defense-in-depth sanitizer
    # for external-string fields. LCU + DDragon are trusted today; the
    # cleaner is a hedge against a future MITM / mirror swap that could
    # smuggle injection text through champion/item/summoner names.
    from core.prompt_sanitize import clean as _ps_clean, clean_iter as _ps_iter
    game_time  = _ps_clean(gs.get("game_time", "0:00"), max_len=12)
    game_s     = gs.get("game_seconds", 0)
    phase      = "early" if game_s < 600 else "mid" if game_s < 1500 else "late"
    hp_pct     = gs.get("hp_pct", 100)
    mp_pct     = gs.get("mana_pct", 100)
    hp_abs     = gs.get("hp_abs", 0)
    hp_max     = gs.get("hp_max", 1000)
    gold       = gs.get("gold", 0)
    cs         = gs.get("cs", 0)
    cs_pm      = gs.get("cs_per_min", 0)
    level      = gs.get("level", 1)
    kda        = _ps_clean(gs.get("kda", "0/0/0"), max_len=24)
    items      = ", ".join(_ps_iter(gs.get("items", []))) or "none"
    summ_d     = _ps_clean(gs.get("summoner_d", "?"), max_len=24)
    summ_f     = _ps_clean(gs.get("summoner_f", "?"), max_len=24)
    allies     = ", ".join(_ps_iter(gs.get("ally_comp", []))) or "unknown"
    enemies    = ", ".join(_ps_iter(gs.get("enemy_comp", []))) or "unknown"
    # Prefer vision_tracker output (position-freeze detection - more
    # accurate fog-of-war model than game_reader's (0,0) heuristic).
    # Falls through to game_reader's enemy_locs when tracker is cold/stale.
    enemy_locs = _ps_clean(_vision_tracker_locs() or gs.get("enemy_locs", "unknown"))
    objectives = _ps_clean(gs.get("objectives", "none"))
    walk_drake = gs.get("walk_time_drake")
    walk_baron = gs.get("walk_time_baron")
    camp_hint  = _ps_clean(gs.get("camp_hint", ""))
    ally_status = _ps_clean(gs.get("ally_status_str", allies))
    dead_info  = _ps_clean(gs.get("dead_respawn_str", ""))
    next_spike = _ps_clean(gs.get("next_item_str", ""))
    ally_kills = gs.get("ally_kills_total", 0)
    enemy_kills = gs.get("enemy_kills_total", 0)
    kill_diff   = ally_kills - enemy_kills
    kill_str    = (f"+{kill_diff}" if kill_diff > 0 else str(kill_diff)) + f" ({ally_kills}v{enemy_kills})"

    gank_threat   = _ps_clean(gs.get("gank_threat", ""))
    friendly_jg   = _ps_clean(gs.get("friendly_jg", ""))
    position_note = _ps_clean(gs.get("position_note", ""))
    ward_hint     = _ps_clean(gs.get("ward_hint", ""))
    enemy_lane    = _ps_clean(gs.get("enemy_lane_str", ""))
    game_mode     = _ps_clean(gs.get("game_mode", "CLASSIC"), max_len=32)
    is_aram       = "ARAM" in game_mode

    walk_str = ""
    if not is_aram:
        if walk_drake is not None:
            walk_str += f"  Walk\u2192drake: ~{walk_drake}s"
        if walk_baron is not None:
            walk_str += f"  Walk\u2192baron: ~{walk_baron}s"

    lines = [
        f"=== {game_time} | {phase} | kills {kill_str} ===",
        f"HP: {hp_pct}% ({hp_abs}/{hp_max})  Mana: {mp_pct}%  Gold: {gold}g",
        f"CS: {cs} ({cs_pm}/min)  Lv: {level}  KDA: {kda}",
        f"Items: {items}",
    ]
    if next_spike:
        lines.append(f"Next spike: {next_spike}")

    quest_boots = gs.get("quest_boots_owned", False)
    if quest_boots:
        lines.append("Note: Lane quest boots owned (invisible slot - skip boots in item path)")
    elif gs.get("level", 1) >= 5 and not quest_boots:
        lines.append(f"Note: Lane quest boots NOT yet completed (level {gs.get('level',1)})")

    ally_list  = gs.get("ally_comp",  [])
    enemy_list = gs.get("enemy_comp", [])

    lane_partner = ""
    for a_info in (gs.get("ally_status_str", "") or "").split(","):
        a_info = a_info.strip()
        if a_info:
            lane_partner = a_info.split()[0] if a_info else ""
            break

    lines += [
        f"Summoners: D={summ_d}  F={summ_f}",
        "",
        f"YOUR ALLIES (same team - use [A] tags): {ally_status}",
        f"ENEMY TEAM (opponents - use [E] tags): {enemies}",
        "REMINDER: [A]=ally (green), [E]=enemy (red) - do NOT swap.",
        f"Enemy locations: {enemy_locs}",
    ]
    if dead_info:  # enemy respawn timers - critical for macro decisions
        lines.append(f"Enemy respawns: {dead_info}")
    # Enemy per-spell CC threat surface (item 136 carry h consumer of
    # agents.daemon_slayer.cc_pressure). Empty string when no enemy
    # carries a registered first-order CC spell - no line bloat.
    _cc_line = enemy_cc_threat_line(enemy_list, game_mode)
    if _cc_line:
        lines.append(_cc_line)
    if enemy_lane:
        lines.append(f"Enemy bot lane (your lane opponents): {enemy_lane}")
    elif enemy_list:
        lines.append(f"Note: enemies are {', '.join(enemy_list)} - do NOT use their names as allies")
    lane_matchup_note = gs.get("_lane_matchup_note", "")
    if lane_matchup_note:
        lines.append(f"Lane matchup vs {lane_matchup_note}")

    lines.append("")
    if is_aram:
        lines.append("Mode: ARAM - no wave management, pure team combat")
        lines += [
            f"Objectives: {objectives}",
        ]
    else:
        lines += [
            f"Wave: {wave_state}",
            f"Objectives: {objectives}{walk_str}",
        ]
        if camp_hint:
            lines.append(f"Camp opportunity: {camp_hint}")
        if gank_threat:
            lines.append(f"Enemy jg threat: {gank_threat}")
        if friendly_jg:
            lines.append(f"Friendly jungler: {friendly_jg}")
        if position_note:
            lines.append(f"Position alert: {position_note}")
        if ward_hint:
            lines.append(f"Ward priority: {ward_hint}")

    comp_ctx = gs.get("comp_context", "")
    if comp_ctx:
        lines.append("")
        lines.append("COMPOSITION ANALYSIS:")
        for cl in comp_ctx.splitlines():
            lines.append(f"  {cl}")

    return "\n".join(lines)


# ── Wave state inference from CS delta ────────────────────────────────────────


class WaveTracker:
    def __init__(self):
        self._samples = deque(maxlen=20)
        self._override = None
        self._override_until = 0.0

    def set_override(self, state: str, duration_s: float = 30.0):
        self._override = state
        self._override_until = time.time() + duration_s

    def update(self, cs: int, game_seconds: float) -> str:
        if time.time() < self._override_until and self._override:
            return self._override

        self._samples.append({"cs": cs, "t": game_seconds})

        old = None
        for s in self._samples:
            if game_seconds - s["t"] <= 15:
                if old is None:
                    old = s

        if old is None:
            return "unknown"

        dt = game_seconds - old["t"]
        if dt < 2:
            return "unknown"

        rate = (cs - old["cs"]) / dt

        if rate > 2.5:   return "hard_shove"
        if rate > 1.2:   return "slowpush"
        if rate < 0.3:   return "freeze_or_hold"
        return "neutral"


# ── Main integration class ─────────────────────────────────────────────────────


