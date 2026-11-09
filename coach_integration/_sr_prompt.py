# arch: SR prompt building - system prompt, helpers, WaveTracker | section=coaching | frozen=no
"""SR-specific prompt assembly: system prompt, data loaders, _build_user_prompt, WaveTracker."""

import json
import math
import numbers
import threading
import time
import logging
from collections import deque
from pathlib import Path

from core.cc_blended_ehp_context import cc_blended_ehp_impact_line
from core.cc_conditional_impact_context import (
    cc_conditional_impact_line,
)
from core.death_patterns_loader import personal_context_block
from core.enemy_cc_threat_context import enemy_cc_threat_line
from core.mode_capabilities import has_capability

logger = logging.getLogger("coach")

# Points to project root (parent of this package dir).
_CI_APP_DIR = Path(__file__).parent.parent

# Written by core/vision_tracker; consumed by _vision_tracker_locs.
# Module-level so tests can monkeypatch it (audit cycle 10).
_VISION_STATE_PATH = _CI_APP_DIR / "data" / "vision_state.json"

# WaveTracker override clock; module-level so tests can drive it.
_clock = time.monotonic


# -- Input shaping (S144-T-591) -------------------------------------------------
# The game_reader state dict, the vision tracker file and the three meta_build
# JSON files are all read here without a schema. These helpers are the trust
# boundary: a value of the wrong type reads as ABSENT (the caller's default),
# never as a raise that loses the whole coach tick and never as raw text.


def _finite(value: object, default=None):
    """``value`` if it is a finite real number, else ``default``.

    bool is refused (``True`` is not a level), as is an int too large for a
    float. The original object is returned, so an int still renders "62" and
    a float "8.1" - the prompt text for valid input is unchanged.
    """
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        return default
    try:
        ok = math.isfinite(value)
    except (OverflowError, TypeError, ValueError):
        return default
    return value if ok else default


def _text(value: object) -> str:
    """``value`` if it is a str, else "" (a dict or None never renders)."""
    return value if isinstance(value, str) else ""


def _str_seq(value: object) -> list:
    """A list / tuple as a list, a bare str as ONE entry, anything else []."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


def _load_meta(name: str) -> dict:
    """Parse ``data/meta_build/<name>``; {} when absent, unreadable or not a mapping."""
    p = _CI_APP_DIR / "data" / "meta_build" / name
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, RecursionError) as exc:
        # Was a silent swallow: a corrupt file read exactly like a missing
        # champion. Log the exception TYPE only (no payload bytes).
        logger.debug("sr meta_build %s unreadable: %s", name, type(exc).__name__)
        return {}
    return data if isinstance(data, dict) else {}


def _meta_entry(name: str, champion: object) -> dict:
    """The mapping stored under ``champion`` in ``name``, else {}."""
    if not isinstance(champion, str) or not champion:
        return {}
    entry = _load_meta(name).get(champion)
    return entry if isinstance(entry, dict) else {}


def _load_sr_rune_rec(champion: str) -> str:
    """Load SR rune recommendation string for a champion."""
    rec = _meta_entry("rune_recommendations_sr.json", champion)
    if not rec:
        return ""
    ks   = _text(rec.get("keystone"))
    pri  = _text(rec.get("primary_tree"))
    sec  = _text(rec.get("secondary_tree"))
    note = _text(rec.get("coaching_note"))
    result = f"{ks} | {pri} / {sec}"
    if note:
        result += f" - {note}"
    return result


# -- Summoner's Rift system prompt ---------------------------------------------

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

OUTPUT FORMAT - follow exactly, no preamble. Every field has a hard word cap.
Emit each field as a plain 'Label: value' line, one field per line. NEVER format the output as a markdown table, and never use pipe '|' columns or dash '---' separator rows - they render as raw pipes in the overlay. Plain 'Label: value' lines only.
Choices is REQUIRED and is the PRIMARY actionable surface (the operator picks one via Alt+1/2/3 hotkey). Do NOT emit Immediate/Next prose - those slots have been retired in favour of the Choices array. Every field below MUST be present.
Action: <1-3 WORDS ALL-CAPS macro priority - e.g. PUSH BOT LANE / BASE LOW HP / FREEZE WAVE / FIGHT NOW / GIVE SPACE / DEFEND TOWER / CRASH AND RESET / TAKE DRAKE / TAKE BARON / END GAME>
Wave: <state + <=6 word reason>
Objective: <take/setup/skip/rotate-NOW + [T] timing, max 10 words>
Fight rule: <specific condition using [A]/[E] tags + exact mechanic, max 12 words>
Reset / item: <item name + exact gold check, max 8 words>
Risk: <specific threat using [E] tag + mechanic to watch, max 12 words>
Choices: <REQUIRED compact single-line JSON array of 2-3 micro-decisions the player faces RIGHT NOW. Schema: [{{"key":"A","label":"<3-5 word option>","expected_outcome":"<one sentence what likely happens>","confidence":"low" or "mid" or "high","source_tag":"<3-10 char descriptor>"}}, ...]. Keys are A/B/C in order. Use confidence honestly: "high" only for textbook plays; "mid" for situational reads; "low" for high-uncertainty calls. Set source_tag to a short descriptor like "lane-state", "rotate-ward", "team-fight", "wave-tempo", "objective-call". Return [] ONLY if no decision is on the clock (e.g. dead waiting respawn, in fountain shopping); the default expectation is 2-3 choices reflecting the live tactical fork. Output MUST be a single line of valid JSON (no markdown, no line breaks inside the array).>
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
Emit each field as a plain 'Label: value' line, one per line. NEVER use a markdown table or pipe '|' / dash '---' separator rows - they render as raw pipes in the overlay.
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
    entry = _meta_entry("sr_champion_builds.json", champion)
    if not entry:
        return ""
    start  = _text(entry.get("start"))
    # A bare-string full_build used to be joined per CHARACTER; only a list
    # of item names is a build path, and a non-str element is skipped.
    fb_raw = entry.get("full_build")
    fb     = [x for x in fb_raw if isinstance(x, str) and x] if isinstance(fb_raw, list) else []
    note   = _text(entry.get("build_note"))
    recall = _text(entry.get("recall_timing"))
    vt     = _text(entry.get("vs_tanks"))
    vh     = _text(entry.get("vs_healing"))
    build_str = " -> ".join(fb)
    result = ""
    if start:    result += f"Start: {start}. "
    if build_str: result += f"Build: {build_str}. "
    if note:     result += note
    if recall:   result += f" | {recall}"
    if vt:       result += f" | vs tanks: {vt}"
    if vh:       result += f" | vs healing: {vh}"
    return result[:400]


def _load_lane_matchup_note(enemy_adc: str) -> str:
    """Load ADC lane matchup note for the enemy ADC/marksman from matchup_weights."""
    if not isinstance(enemy_adc, str) or not enemy_adc:
        return ""
    mm = _load_meta("matchup_weights.json").get("adc_lane_matchups")
    entry = mm.get(enemy_adc) if isinstance(mm, dict) else None
    if not entry or not isinstance(entry, dict):
        return ""
    # One wrong-typed field used to raise and lose the whole note.
    diff     = _finite(entry.get("difficulty"), 0)
    style    = _text(entry.get("lane_style"))
    note     = _text(entry.get("priority_note"))[:120]
    mechanic = _text(entry.get("key_mechanic"))[:100]
    result   = f"{enemy_adc} [diff {diff}/5, {style}]: {note}"
    if mechanic:
        result += f" | Key: {mechanic}"
    return result[:280]


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
        p = _VISION_STATE_PATH
        if not p.exists():
            return ""
        if (time.time() - p.stat().st_mtime) > 10:
            return ""
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return ""
    # S144-T-591: the shape checks used to sit OUTSIDE the try, so a list
    # root, a list "enemies" or one non-dict entry raised AttributeError
    # and killed the whole SR prompt build for the tick.
    enemies = d.get("enemies") if isinstance(d, dict) else None
    if not isinstance(enemies, dict) or not enemies:
        return ""
    visible, mia, dead = [], [], []
    for name, e in enemies.items():
        if not isinstance(e, dict):
            continue
        zone = e.get("last_seen_zone") or "?"
        if e.get("is_dead"):
            # Audit cycle 10: math.isfinite guard - json.loads accepts
            # NaN/Infinity literals and int(NaN) raised ValueError here,
            # killing the whole SR prompt build for the tick. S144-T-591:
            # a bool (True read "1s") or a negative timer is not a timer.
            r = _finite(e.get("respawn_in_s"))
            dead.append(f"{name} ({int(r)}s)" if r is not None and r >= 0 else name)
            continue
        if e.get("visible"):
            visible.append(f"{name} [{zone}]")
        else:
            # bool and NaN are "untracked", not "seen 1 s ago" / "long gone".
            ago = _finite(e.get("missing_for_s"))
            if ago is not None:
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
    # S144-T-591: a non-dict state reads as an empty one, and every numeric
    # slot goes through _finite - a None / str / NaN / bool value used to
    # raise out of the comparisons below (losing the tick) or be
    # interpolated RAW, which let a string carry a newline and a role marker
    # past the sanitizer on ten fields. Junk reads exactly like a missing key.
    if not isinstance(gs, dict):
        gs = {}
    game_time  = _ps_clean(gs.get("game_time", "0:00"), max_len=12)
    game_s     = _finite(gs.get("game_seconds"), 0)
    phase      = "early" if game_s < 600 else "mid" if game_s < 1500 else "late"
    hp_pct     = _finite(gs.get("hp_pct"), 100)
    mp_pct     = _finite(gs.get("mana_pct"), 100)
    hp_abs     = _finite(gs.get("hp_abs"), 0)
    hp_max     = _finite(gs.get("hp_max"), 1000)
    gold       = _finite(gs.get("gold"), 0)
    cs         = _finite(gs.get("cs"), 0)
    cs_pm      = _finite(gs.get("cs_per_min"), 0)
    level      = _finite(gs.get("level"), 1)
    kda        = _ps_clean(gs.get("kda", "0/0/0"), max_len=24)
    items      = ", ".join(_ps_iter(_str_seq(gs.get("items")))) or "none"
    summ_d     = _ps_clean(gs.get("summoner_d", "?"), max_len=24)
    summ_f     = _ps_clean(gs.get("summoner_f", "?"), max_len=24)
    # RM-361: sanitise the wire comps ONCE and reuse the cleaned lists on
    # every branch below. Both keys used to be cleaned here and then re-read
    # RAW further down, so a single wire field had two renderings - one
    # sanitised and one not - and only the sanitised one was obvious.
    # S144-T-591: None raised and a bare str was split per character.
    ally_list  = _ps_iter(_str_seq(gs.get("ally_comp")))
    enemy_list = _ps_iter(_str_seq(gs.get("enemy_comp")))
    allies     = ", ".join(ally_list) or "unknown"
    enemies    = ", ".join(enemy_list) or "unknown"
    # Prefer vision_tracker output (position-freeze detection - more
    # accurate fog-of-war model than game_reader's (0,0) heuristic).
    # Falls through to game_reader's enemy_locs when tracker is cold/stale.
    enemy_locs = _ps_clean(_vision_tracker_locs() or gs.get("enemy_locs", "unknown"))
    objectives = _ps_clean(gs.get("objectives", "none"))
    walk_drake = _finite(gs.get("walk_time_drake"))
    walk_baron = _finite(gs.get("walk_time_baron"))
    camp_hint  = _ps_clean(gs.get("camp_hint", ""))
    ally_status = _ps_clean(gs.get("ally_status_str", allies))
    dead_info  = _ps_clean(gs.get("dead_respawn_str", ""))
    next_spike = _ps_clean(gs.get("next_item_str", ""))
    ally_kills = _finite(gs.get("ally_kills_total"), 0)
    enemy_kills = _finite(gs.get("enemy_kills_total"), 0)
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
    elif level >= 5:
        lines.append(f"Note: Lane quest boots NOT yet completed (level {level})")

    # RM-361: ally_list / enemy_list are the sanitised lists built above -
    # do NOT re-read gs here.

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
    # Aggregate enemy CC -> blended-EHP impact (item 137 carry a coach
    # consumer of agents.daemon_slayer.ehp.compute_ehp cc_blended_ehp
    # math model). Empty string when no enemy carries CC - zero bloat.
    _cc_blended_line = cc_blended_ehp_impact_line(enemy_list, game_mode)
    if _cc_blended_line:
        lines.append(_cc_blended_line)
    # Aggregate enemy CONDITIONAL CC -> blended-EHP impact (item 143
    # follow-up; first coach-prompt consumer of the cc_conditional
    # registry shipped item 141 Slice B `7233568`). Empty string when
    # no enemy carries a registered conditional CC entry (the common
    # case at 23/172 champs at ENGINE 1.39.0).
    _cc_conditional_line = cc_conditional_impact_line(
        enemy_list, game_mode
    )
    if _cc_conditional_line:
        lines.append(_cc_conditional_line)
    if enemy_lane:
        lines.append(f"Enemy bot lane (your lane opponents): {enemy_lane}")
    elif enemy_list:
        lines.append(f"Note: enemies are {', '.join(enemy_list)} - do NOT use their names as allies")
    # S144-T-591: was interpolated RAW (RM-361 residual). The note embeds
    # the enemy champion name the caller took off the wire.
    lane_matchup_note = _ps_clean(_text(gs.get("_lane_matchup_note")), max_len=300)
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
            f"Wave: {_ps_clean(_text(wave_state), max_len=32) or 'unknown'}",
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
        # Spec-W ward-gate: never emit ward prompting in a mode without
        # wards (fail-CLOSED outside SR/CLASSIC).
        if ward_hint and has_capability(game_mode, "has_wards"):
            lines.append(f"Ward priority: {ward_hint}")

    # S144-T-591: a non-str comp_context raised AttributeError on
    # .splitlines(); a list / tuple is read as its lines, anything else skipped.
    comp_raw = gs.get("comp_context")
    comp_lines = comp_raw.splitlines() if isinstance(comp_raw, str) else (
        [x for x in comp_raw if isinstance(x, str)] if isinstance(comp_raw, (list, tuple)) else [])
    comp_ctx = _ps_iter(comp_lines)
    if comp_ctx:
        lines.append("")
        lines.append("COMPOSITION ANALYSIS:")
        # RM-361: clean each line rather than the whole blob. comp_context
        # is legitimately multi-line (composition_advisor.comp_context_str
        # joins up to eight lines), so a whole-string clean would flatten
        # the block onto one line and truncate it at DEFAULT_MAX_LEN. Per
        # line keeps the layout and still neutralises role markers. Note
        # the splitlines() above is why the whole-string newline token never
        # applied to this field - see the residual noted in the RM-361 test.
        for cl in comp_ctx:
            lines.append(f"  {cl}")

    return "\n".join(lines)


# -- Wave state inference from CS delta ----------------------------------------


class WaveTracker:
    """Infer the wave state from the CS rate over the last ~15 game seconds.

    S144-T-591: a None / NaN / bool / str sample used to be STORED, so the
    next tick raised TypeError (or read a NaN rate as "neutral"); it is now
    refused and reads "unknown". A game clock that goes BACKWARDS (replay
    rewind, a reconnect re-basing game time) left samples from the future
    in the window, so every tick read "unknown" until 20 fresh samples had
    pushed them out; the window is now reset when the clock goes back by
    more than ``_REWIND_S``. A smaller step back is kept as before: the two
    production callers (the coach thread, coach_integration/_coach.py
    ``_convert``, and the app loop, app/_game_lifecycle.py) share one
    tracker and can read one game second out of order. Those two threads
    also used to iterate the deque while the other appended to it
    ("deque mutated during iteration"); ``_lock`` now serialises them. The
    override clock is monotonic (a wall-clock step no longer stretches or
    cancels it) and a non-finite duration or a non-text state is refused -
    an infinite duration used to pin the override forever.
    """

    # Upper bound on one override; the only caller asks for 30 s.
    _MAX_OVERRIDE_S = 600.0
    # A step back in game time larger than this is a rewind, not jitter.
    _REWIND_S = 5.0

    def __init__(self):
        self._samples = deque(maxlen=20)
        self._override = None
        self._override_until = 0.0
        self._lock = threading.Lock()

    def set_override(self, state: str, duration_s: float = 30.0) -> None:
        dur = _finite(duration_s)
        # A negative duration needs no branch: it lands in the past and never holds.
        if not isinstance(state, str) or not state or dur is None:
            return
        with self._lock:
            self._override = state
            self._override_until = _clock() + min(float(dur), self._MAX_OVERRIDE_S)

    def update(self, cs: int, game_seconds: float) -> str:
        with self._lock:
            return self._update_locked(cs, game_seconds)

    def _update_locked(self, cs, game_seconds) -> str:
        if self._override and _clock() < self._override_until:
            return self._override

        cs = _finite(cs)
        game_seconds = _finite(game_seconds)
        if cs is None or game_seconds is None:
            return "unknown"
        if self._samples and game_seconds < self._samples[-1]["t"] - self._REWIND_S:
            self._samples.clear()

        self._samples.append({"cs": cs, "t": game_seconds})

        old = None
        for s in self._samples:
            if game_seconds - s["t"] <= 15 and old is None:
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


# -- Main integration class -----------------------------------------------------
