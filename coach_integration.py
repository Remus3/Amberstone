# arch: Haiku coaching dispatch + budget + cache (god module) | section=coaching | frozen=no
"""
coach_integration.py
Bridge between LoLOverlay's game_reader and the auto-coaching engine.
"""

import os
import json
import time
import logging
import threading
try:
    import anthropic
    _APITimeoutError = anthropic.APITimeoutError
    _APIConnectionError = anthropic.APIConnectionError
except ImportError:
    anthropic = None  # type: ignore[assignment]
    _APITimeoutError = Exception
    _APIConnectionError = Exception
from collections import deque
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("coach")

# Role-expanded profiles (mid/support/APC/Vayne top)
try:
    from role_profiles import get_role_profile, aram_item_context, ARAM_ITEM_RULES
    HAS_ROLE_PROFILES = True
except Exception:
    HAS_ROLE_PROFILES = False
    def get_role_profile(champ, role="bot"): return ""
    def aram_item_context(e, a, c): return ""
    ARAM_ITEM_RULES = ""

# ── Champion profiles — challenger-level specifics ─────────────────────────────

CHAMPION_PROFILES = {
    "Jinx": (
        "Jinx. Mechanics: flip Pow-Pow→Fishbones at objectives/grouped fights; "
        "passive reset = free second kill — always find the follow-up target. "
        "Spikes: Yun Tal (1 item), Runaan's (2-item AoE), IE (3-item crit cap). "
        "Positioning: absolute max range, front-to-back always. "
        "Ult: pick/cleanup at 30%+ HP targets; never the primary damage tool in fights. "
        "Exploit: super-long ult range confirms at 20%+ HP threshold."
    ),
    "Vayne": (
        "Vayne. Mechanics: Q before every auto for bonus damage; 3-stack Silver Bolts "
        "priority on tanks; Condemn wall-stun = 1.5s — know every wall near lane. "
        "Final Hour invis = reposition tool, not just a DPS cooldown. "
        "Spikes: BotRK (1-item), PD+BotRK (2-item sustained), IE (damage cap). "
        "Macro: play for late, avoid 5v5 before 3 items. "
        "Exploit: BotRK+3-stack = solo-kills any tank post-2-items."
    ),
    "Tristana": (
        "Tristana. Mechanics: stack E on tower for plates, on enemies for trade dmg; "
        "E reset from kills — commit only in reset windows; W (jump) = escape, not engage when behind. "
        "Spikes: Yun Tal (all-in burst), Stormrazor+IE (guaranteed proc combo). "
        "Macro: crash waves fast, abuse plate gold pre-14min, tower tempo control. "
        "Exploit: kill a tower in 2 waves at level 7+ with E stacked."
    ),
    "Caitlyn": (
        "Caitlyn. Mechanics: Headshot combos from trap hits and net shots; "
        "trap bushes pre-6 for zone deny; E (net) is also primary escape — never burn offensively with dive risk. "
        "Spikes: Hexoptics C44 (lane domination), IE (crit-cap finisher). "
        "Macro: zone with traps 30s before objective spawns; shove for plate gold. "
        "Exploit: Q bounce off minion standing behind enemy ADC."
    ),
    "Nilah": (
        "Nilah. Mechanics: all-in ONLY on confirmed CC chain; E (flip) = engage AND escape — "
        "never burn without CC locked. W reduces healing — priority vs sustain enemies. "
        "Passive shares assists — value grouped play over split dueling. "
        "Spikes: BotRK (1-item), Bloodthirster (sustain), Phantom Dancer (crit + MS). "
        "Macro: force 2v2s, avoid extended poke. "
        "Exploit: E to a tagged enemy ignores terrain — use through walls."
    ),
    "Miss Fortune": (
        "Miss Fortune. Mechanics: E (rain) slows first, then ult for guaranteed full channel; "
        "ult angle = perpendicular to enemy team, from behind cover; Strut MS — don't take hits. "
        "Spikes: Lethality first (poke dominance), Lord Dominik's (vs tanks). "
        "Macro: group for objectives, punish in MF ult-angle windows. "
        "Exploit: Q bounce target = minion standing directly behind enemy ADC."
    ),
    "Lucian": (
        "Lucian. Mechanics: Trinity Force Spellblade procs on every Q — Q fires Spellblade "
        "AND Lightslinger simultaneously (3 hits per ability cycle). "
        "E (Relentless Pursuit) is the repositioning tool — keep it for engage AND escape. "
        "Never use RFC — he gaps-close and bursts, does not siege. "
        "Spikes: Trinity Force (Spellblade burst), Essence Reaver (mana + CDR), Navori (E refresh). "
        "Macro: dash in on isolated carry, burst, dash out before peel arrives. "
        "Exploit: Q activates Spellblade AND Lightslinger: Q-proc + empowered auto + second auto."
    ),
    "Ezreal": (
        "Ezreal. Mechanics: Q (Mystic Shot) reduces all CDs by 1.5s — spam every wave for haste. "
        "Trinity Force Spellblade on Q for bonus damage. Manamune stacks via Q spam. "
        "Arcane Shift (E) is your ONLY escape — never burn offensively without backup. "
        "Spikes: Trinity Force + Manamune fully stacked (Muramana), Serylda's Grudge (armor pen). "
        "Macro: stay mid-to-long range, Q poke every wave, ult across map at grouped enemies. "
        "Exploit: Q applies on-hit effects including Muramana — every Q is a ranged attack."
    ),
    "Jhin": (
        "Jhin. Mechanics: 4 shots then reload — plan your 4th shot as the crit execute. "
        "W (Deadly Flourish) roots enemies recently hit by minions/allies — set up in trades. "
        "RFC headshot at max range crits for 30%+ HP on squishies. "
        "Spikes: Hexoptics C44 (25% crit + 55 AD), RFC (max-range headshot), IE (crit cap). "
        "Macro: position behind ally frontline, use W roots from fog of war, R to finish. "
        "Exploit: Reload window forces him to reposition — abuse his reload with all-in timing."
    ),
    "Ashe": (
        "Ashe. Mechanics: every auto is a slow (Frost Shot) — perma-slow kites any enemy. "
        "Ranger's Focus (Q) at 4+ stacks: cone of arrows that AOE slows. "
        "Crystal Arrow (R) is global — throw at fight start, always on CD. "
        "Spikes: RFC (max-range frost shot), The Collector (25% crit), IE (75% crit cap). "
        "Macro: stay at absolute max range, perma-slow tanks for team, R to initiate from range. "
        "Exploit: RFC headshot crits from 850+ range without closing distance."
    ),
    "Draven": (
        "Draven. Mechanics: catch BOTH Spinning Axes on every throw for permanent double-proc. "
        "League of Draven stacks: every kill multiplies R damage — use R to finish grouped low-HP enemies. "
        "Stand (E) blocks and returns any projectile. "
        "Spikes: The Collector (early execute), Bloodthirster (sustain + crit), Navori (25% crit). "
        "Macro: dominate early kills for stack generation, convert stack gold on R reset. "
        "Exploit: Stand (E) can block Lux R, Caitlyn R, any targeted projectile for free trade."
    ),
    "Xayah": (
        "Xayah. Mechanics: autos plant feathers, E (Bladecaller) pulls them back rooting caught enemies. "
        "Fire Q (Double Daggers) before E for maximum feathers. "
        "R (Featherstorm) INVINCIBLE during channel — dodge any burst or CC with R timing. "
        "Spikes: Yun Tal (AS), RFC (25% crit), The Collector (50% crit before IE). "
        "Macro: plant feathers with autos in extended trades, E-root for kills, R to dodge burst. "
        "Exploit: time R to dodge Malphite ult, Lux R, or any burst window."
    ),
    "Zeri": (
        "Zeri. Mechanics: Q (Burst Fire) passes through terrain — chip enemies through minion walls. "
        "E (Spark Surge) wall-hop for repositioning or escape. "
        "R (Lightning Crash) overcharges: every kill extends duration — snowball through grouped fights. "
        "Spikes: Kraken Slayer (on-hit), Navori (25% crit), Runaan (AoE on-hit spread). "
        "Macro: wall-hop for unexpected angles, Q poke through minions, R into 2+ enemies. "
        "Exploit: empowered Q auto after ability crits at 60%+ crit for burst window."
    ),
    "Samira": (
        "Samira. Mechanics: Style rank D→S requires alternating melee/ranged combos and using ally CC. "
        "R (Inferno Trigger) only unlocks at S rank — time it after building rank in a fight. "
        "Daredevil Impulse passive dashes through/over enemies on autos. "
        "Spikes: The Collector (25% crit), Navori (25% crit), ISB (75% before IE). "
        "Macro: build rank on multiple enemies before R, never R single isolated target. "
        "Exploit: weave through grouped enemies with passive dashes to hit all 5 with R spin."
    ),
    "Sivir": (
        "Sivir. Mechanics: Ricochet (W) bounces autos for AOE — activate before every teamfight. "
        "Spell Shield (E) blocks one incoming ability — save for hard CC or burst finisher. "
        "R gives entire team movement speed — use for disengage or initiation. "
        "Spikes: Navori (25% crit, reduces Q/W CD on crit), RFC (25% crit), IE (75% cap). "
        "Macro: crash waves fast with Q/W, R to move team between objectives. "
        "Exploit: E Spell Shield on Malphite R or Amumu R negates engage entirely."
    ),
    "Varus": (
        "Varus. Mechanics: W (Blighted Quiver) passive — 3 stacks of blight on target, "
        "then E root detonates stacks for bonus % max HP damage. "
        "R (Chain of Corruption) root jumps between enemies — throw into grouped cluster. "
        "Spikes: Kraken Slayer (vs tanks), Phantom Dancer (20% crit + ghost), The Collector (crit + execute). "
        "Macro: Q long-range poke to apply blight stacks, E to root + detonate, R on grouped. "
        "Exploit: apply 3 blight stacks with W-passive autos before using any ability for max detonation."
    ),
    "Kalista": (
        "Kalista. Mechanics: every auto hops to a new position — never stand still, always move. "
        "Rend (E) pulls ALL spears from ALL targets simultaneously — detonate when 4+ stacked. "
        "Fate's Call (R) throws your support at enemies for a targeted knockup. "
        "Spikes: Kraken Slayer (on-hit spread via Runaan), Navori (25% crit), Runaan (AoE spear stack). "
        "Macro: stack spears on 3+ enemies simultaneously with Runaan, E to AOE rend the group. "
        "Exploit: R is your support's initiation tool — coordinate the throw for gap-close into their team."
    ),
}
GENERIC_PROFILE = (
    "ADC. Priorities: safe uptime, wave tempo, item spikes, objective windows. "
    "Never die without purpose. Always know where the next wave crashes."
)


# ── Game Sense vocabulary ─────────────────────────────────────────────────
# Approved 12-word vocabulary for the aftergame GAME SENSE panel. Early / Mid /
# Late game phases each receive one descriptor drawn from this list. The
# dashboard renders these in the adaptation panel (client mode) and persists
# them to match_metrics with metric_key ∈ {game_sense_early, _mid, _late}
# under milestone_tag='game_end'. Valence colors in the UI map accordingly.
GAME_SENSE_VOCAB: dict[str, dict[str, str]] = {
    # Negative (coral)
    "Chaotic":      {"valence": "bad",  "hint": "Scattered, reactive, losing every skirmish."},
    "Tilted":       {"valence": "bad",  "hint": "Emotional play, forcing engagements."},
    "Drowning":     {"valence": "bad",  "hint": "Tempo-starved, falling behind objective-to-objective."},
    "Scattered":    {"valence": "bad",  "hint": "Missing obvious play windows."},
    # Warning (gold)
    "Hesitant":     {"valence": "warn", "hint": "Winning the duel, losing the map."},
    "Reactive":     {"valence": "warn", "hint": "Responding, never initiating."},
    # Neutral
    "Steady":       {"valence": "ok",   "hint": "No mistakes, no standout plays."},
    # Positive (mint)
    "Composed":     {"valence": "good", "hint": "Traceable decisions, no panic."},
    "Patient":      {"valence": "good", "hint": "Waited for the right window."},
    "Opportunistic":{"valence": "good", "hint": "Capitalized on enemy mistakes."},
    "Dominant":     {"valence": "good", "hint": "Dictated tempo, enemy reacted to you."},
    "On Point":     {"valence": "good", "hint": "Read plays before they committed."},
}


# ── SR rune recommendations ───────────────────────────────────────────────────
_CI_APP_DIR = Path(__file__).parent

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
            result += f" — {note}"
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


NAME TAGS — mandatory in every field:
  Ally champions: [A]Name[/A]   Enemy champions: [E]Name[/E]   Timings: [T]value[/T]
  Apply to the exact champion name only. e.g. [A]Hecarim[/A] ganks, [E]Caitlyn[/E] at [T]4:45[/T]

ALLY vs ENEMY RULE — CRITICAL: never swap these tags.
  YOUR ALLIES (same team, listed under YOUR ALLIES below) — ALWAYS use [A]Name[/A].
  ENEMIES (opposing team, listed under ENEMY TEAM below) — ALWAYS use [E]Name[/E].
  If you are uncertain which team a champion is on, do NOT tag them rather than risk a swap.
  A wrong tag inverts the color on screen and directly misleads the player — this is a hard error.

OUTPUT FORMAT — follow exactly, no preamble. Every field has a hard word cap:
Action: <1-3 WORDS ALL-CAPS macro priority — e.g. PUSH BOT LANE / BASE LOW HP / FREEZE WAVE / FIGHT NOW / GIVE SPACE / DEFEND TOWER / CRASH AND RESET / TAKE DRAKE / TAKE BARON / END GAME>
Immediate: <concise 3-5s action, use [A]/[E] name tags, max 12 words>
Next: <15-30s plan, use [A]/[E] tags and [T] for all timings, max 16 words>
Wave: <state + <=6 word reason>
Objective: <take/setup/skip/rotate-NOW + [T] timing, max 10 words>
Fight rule: <specific condition using [A]/[E] tags + exact mechanic, max 12 words>
Reset / item: <item name + exact gold check, max 8 words>
Risk: <specific threat using [E] tag + mechanic to watch, max 12 words>
"""
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


NAME TAGS: [A]AllyName[/A]  [E]EnemyName[/E]  [T]timing[/T] — use in all fields.

OUTPUT FORMAT — follow exactly, no preamble:
Action: <1-3 WORDS ALL-CAPS — e.g. ALL IN NOW / FALL BACK / POKE ONLY / GROUP MID / FOUNTAIN NOW / PUSH TURRET>
Immediate: <fight action right now, use [A]/[E] name tags>
Next: <15-30s plan, use [A]/[E] and [T] for timings>
Wave: N/A — ARAM auto-push
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
        p = _P(__file__).parent / "data" / "vision_state.json"
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
    # Prefer vision_tracker output (position-freeze detection — more
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
        lines.append("Note: Lane quest boots owned (invisible slot — skip boots in item path)")
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
        f"YOUR ALLIES (same team — use [A] tags): {ally_status}",
        f"ENEMY TEAM (opponents — use [E] tags): {enemies}",
        "REMINDER: [A]=ally (green), [E]=enemy (red) — do NOT swap.",
        f"Enemy locations: {enemy_locs}",
    ]
    if dead_info:  # enemy respawn timers — critical for macro decisions
        lines.append(f"Enemy respawns: {dead_info}")
    if enemy_lane:
        lines.append(f"Enemy bot lane (your lane opponents): {enemy_lane}")
    elif enemy_list:
        lines.append(f"Note: enemies are {', '.join(enemy_list)} — do NOT use their names as allies")
    lane_matchup_note = gs.get("_lane_matchup_note", "")
    if lane_matchup_note:
        lines.append(f"Lane matchup vs {lane_matchup_note}")

    lines.append("")
    if is_aram:
        lines.append("Mode: ARAM — no wave management, pure team combat")
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

class CoachIntegration:
    def __init__(self, data_file: Path, debug: bool = False):
        self.data_file = Path(data_file)
        self.debug = debug

        self._debounce_s = 3.0
        self._timeout_s  = 20
        self._model = "claude-haiku-4-5-20251001"
        self._patch = "current"

        cfg_path = Path(__file__).parent / "config" / "coach_settings.json"
        if cfg_path.exists():
            try:
                cfg = json.loads(cfg_path.read_text())
                self._debounce_s = cfg.get("debounce_seconds", self._debounce_s)
                self._timeout_s  = cfg.get("timeout_seconds",  self._timeout_s)
                self._model      = cfg.get("model",            self._model)
            except Exception as _e:  # QUAL-002
                logger.debug("coach_settings reload: %s", _e)

        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            logger.warning("ANTHROPIC_API_KEY not set — auto-coaching disabled")
        self._client = anthropic.Anthropic(api_key=api_key) if (api_key and anthropic) else None

        db_path = Path(__file__).parent / "data" / "decisions.db"
        from modules.cache_engine import CacheEngine
        self._cache = CacheEngine(db_path)

        self._wave = WaveTracker()
        self._lock = threading.Lock()
        self._last_coach_time = 0.0
        self._last_state: dict = {}
        self._last_submitted_state: dict = {}
        self._pending = False

        logger.info("CoachIntegration ready (api_key=%s)", "set" if api_key else "MISSING")

    def submit_state(self, game_state: dict):
        """Called from _apply_auto_fields every 2s. Non-blocking."""
        if not self._client:
            return
        # AUDIT 2026-04-28 (2.2): per-mode kill switch.
        try:
            from core.cost_tracker import get_tracker as _gt
            if _gt().coach_disabled("sr"):
                return
        except Exception:
            pass
        if not self._should_coach(game_state):
            return
        self._last_submitted_state = game_state
        self._last_coach_time = time.time()
        t = threading.Thread(target=self._run_safe, args=(game_state,),
                             daemon=True, name="CoachCall")
        t.start()

    def request_now(self, game_state: dict):
        """Force immediate coaching call — from context menu."""
        if not self._client or not game_state:
            return
        self._last_coach_time = time.time()
        t = threading.Thread(target=self._run_safe, args=(game_state,),
                             daemon=True, name="CoachForced")
        t.start()

    def flag_last_bad(self):
        if self._last_state:
            self._cache.flag_bad(self._last_state)
            logger.info("Bad advice flagged for %s", self._last_state.get("champion"))

    def reset_state(self):
        self._last_submitted_state = {}
        self._last_state = {}
        self._last_coach_time = 0.0
        self._pending = False
        self._wave = WaveTracker()
        try:
            blank = self._default_data()
            blank["mode"] = "game"
            tmp = self.data_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(blank, indent=2), encoding="utf-8")
            tmp.replace(self.data_file)
        except Exception as _e:  # QUAL-002
            import logging as _lg; _lg.getLogger(__name__).debug("blank artifact write: %s", _e)
        logger.info("Coach state reset for new game")

    def set_wave_override(self, state: str):
        self._wave.set_override(state, duration_s=30)
        logger.info("Wave override: %s (30s)", state)

    def _state_signature(self, coach_state: dict) -> str:
        """AUDIT 2026-04-28 (5.7): compact stable hash of the coach-relevant
        state fields. If this is identical to the last call's signature,
        the previous coach response is still correct and we can skip a
        round-trip. Keep the field set narrow: drift in irrelevant fields
        (e.g., minor timer ticks) shouldn't force a new call."""
        try:
            import hashlib
            keys = (
                "champion", "wave_state", "hp_bucket", "mana_bucket",
                "gold_bucket", "level", "kda", "objective_window",
                "dead_count", "kill_window",
            )
            parts = []
            for k in keys:
                v = coach_state.get(k)
                # Bucket continuous values to absorb noise.
                # _convert outputs my_hp_pct (0.0-1.0), my_gold, my_level —
                # fix key names to match; hp_pct was the old wrong fallback.
                if k == "hp_bucket" and v is None:
                    v = int(coach_state.get("my_hp_pct", 0) * 10)
                if k == "mana_bucket" and v is None:
                    v = int(coach_state.get("my_mana_pct", 0) * 10)
                if k == "gold_bucket" and v is None:
                    v = int(coach_state.get("my_gold", 0) // 300)
                if k == "level" and v is None:
                    v = coach_state.get("my_level")
                if k == "objective_window" and v is None:
                    ot = coach_state.get("objective_timers") or {}
                    v = 1 if any(
                        isinstance(t, (int, float)) and 0 <= float(t) < 90
                        for obj, t in ot.items() if obj in ("dragon", "baron")
                    ) else 0
                parts.append(f"{k}={v}")
            return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()
        except Exception:
            return ""

    def _should_coach(self, state: dict) -> bool:
        now = time.time()

        dead_count = state.get("dead_count", 0)
        last_dead  = self._last_submitted_state.get("dead_count", 0)
        new_kills  = dead_count > last_dead
        kill_window = state.get("kill_window", False)

        if (kill_window or new_kills) and now - self._last_coach_time > 2.0:
            return True

        if now - self._last_coach_time < self._debounce_s:
            return False

        last = self._last_submitted_state
        if not last:
            return True

        hp_delta     = abs(state.get("hp_pct", 50) - last.get("hp_pct", 50))
        gold_changed = (state.get("gold", 0) // 300) != (last.get("gold", 0) // 300)

        cur_obj  = state.get("obj_timers_dict", {})
        last_obj = last.get("obj_timers_dict", {})
        obj_trigger = any(
            cur_obj.get(k) is not None and cur_obj.get(k, 9999) < 90
            and last_obj.get(k, 9999) >= 90
            for k in ("dragon", "baron")
        )

        return hp_delta >= 10 or gold_changed or obj_trigger

    def _run_safe(self, game_state: dict):
        if not self._lock.acquire(blocking=False):
            logger.debug("Coach already running, skipping")
            return
        try:
            self._run(game_state)
        except Exception as e:
            logger.error("Coach error: %s", e)
            self._write_status_field(f"Coach error: {str(e)[:60]}")
        finally:
            self._lock.release()

    def _run(self, game_state: dict):
        t0 = time.time()
        coach_state = self._convert(game_state)
        self._last_state = coach_state
        # Stash the raw game_state too — _write_fields needs unprefixed
        # live stats (kda / cs / level / gold / game_time_s) to populate
        # the dashboard top-bar pills, which read from coaching_data.json
        # via the WS /push channel (raw file content, no liveclient
        # overlay). _last_state has these prefixed (my_cs, my_level…).
        self._last_gs = game_state

        cached = self._cache.get(coach_state)
        if cached:
            latency = round((time.time() - t0) * 1000)
            logger.debug("Cache hit in %dms", latency)
            self._write_fields(cached, cache_hit=True)
            return

        if not self._client:
            return

        champion   = coach_state.get("champion", "")
        profile = CHAMPION_PROFILES.get(champion)
        if not profile and HAS_ROLE_PROFILES:
            role = game_state.get("role", "bot")
            profile = get_role_profile(champion, role)
        if not profile:
            try:
                from champion_profiles import CHAMPIONS as _ALL_CHAMPS
                cp = _ALL_CHAMPS.get(champion, {})
                if cp:
                    role    = cp.get("role", "unknown")
                    dmg     = cp.get("dmg", "ad")
                    mechanic = cp.get("mechanic", "")
                    aram_tip = cp.get("aram", "")
                    spikes   = ", ".join(cp.get("spikes", [])) if cp.get("spikes") else ""
                    # SR context: omit aram_tip (ARAM-specific, not useful in SR)
                    profile  = (
                        f"{champion} ({role}, {dmg} damage). "
                        f"{mechanic} "
                        + (f"Item spikes: {spikes}." if spikes else "")
                    )
                else:
                    profile = GENERIC_PROFILE
            except Exception:
                profile = GENERIC_PROFILE
        game_mode  = game_state.get("game_mode", "CLASSIC")
        # SrAramWorker only submits CLASSIC/RANKED — always SR path.
        # ARAM/KIWI/Arena/Brawl coaching is owned by dedicated mode coaches.
        sr_rune_rec  = _load_sr_rune_rec(champion)
        sr_build_note = _load_sr_build_note(champion)
        # Audit round-9: env-gated adaptation hint. Default off; empty-safe.
        _adapt_hint = ""
        import os as _os
        if _os.environ.get("RC_COACH_ADAPTATION") == "1":
            try:
                from coaches.adaptation_hint import format_hint_line as _fhl
                _adapt_hint = _fhl(champion, "sr_ranked",
                                   game_state.get("enemy_comp") or [])
            except Exception:
                _adapt_hint = ""
        system = SR_SYSTEM_PROMPT.format(
            profile=profile,
            sr_rune_rec=sr_rune_rec or "use meta keystone for this champion",
            sr_build_note=sr_build_note or "use standard ADC build for this champion",
            adaptation_hint=_adapt_hint,
        )

        # Inject lane matchup note (adc_lane_matchups data)
        _enemy_adc = (game_state.get("enemy_comp") or [""])[0]
        game_state["_lane_matchup_note"] = _load_lane_matchup_note(_enemy_adc)
        user = _build_user_prompt(game_state, coach_state.get("wave_state", "unknown"))

        _ds_rows = None
        _ds_picks_str = "unavailable"
        try:
            from core import daemon_slayer_client as _ds_client
            from core.daemon_slayer_resolver import resolve_many as _ds_resolve_many
            _owned_ids = _ds_resolve_many(game_state.get("items", []), mode="sr")
            _ds_rows = _ds_client.rank_for(
                champion=champion,
                level=int(game_state.get("level", 1)) or 1,
                item_ids=_owned_ids,
                mode="SR",
                target_armor=80.0,
                top=5,
            )
            if _ds_rows:
                _ds_picks_str = " > ".join(
                    f"{r.item_name}(+{r.delta_dps:.0f}dps,{r.gold}g)"
                    for r in _ds_rows
                )
            elif _ds_rows == []:
                _ds_picks_str = "none"
        except Exception as _ds_exc:
            logger.debug("SR daemon_slayer pre-call: %s", _ds_exc)
        self._last_ds_rows = _ds_rows
        if _ds_rows:
            try:
                from core.ds_calibration import log_ds_run as _ds_log
                _ds_log(champion=champion, mode="SR", level=int(game_state.get("level", 1)) or 1,
                        owned_items=list(_owned_ids),
                        game_id=str(game_state.get("game_id") or ""),
                        ds_picks=[{"item_id": r.item_id, "item_name": r.item_name,
                                   "delta_dps": round(r.delta_dps, 2), "gold": r.gold}
                                  for r in _ds_rows])
            except Exception:
                pass
        if _ds_picks_str != "unavailable":
            user += f"\nDS top items (DPS ranked, own-items-accounted): {_ds_picks_str}"

        if self.debug:
            logger.debug("User prompt:\n%s", user)

        # AUDIT 2026-04-28 (5.7): if the coach-relevant slice of state is
        # byte-identical to the last submitted slice, the previous response
        # is already correct — skip the API call entirely.
        sig = self._state_signature(coach_state)
        if sig and sig == getattr(self, "_last_sig", None):
            logger.debug("Coach skip: state signature unchanged (%s)", sig[:16])
            return
        # AUDIT 2026-04-28 (5.4): hard daily spend cap.
        try:
            from core.cost_tracker import get_tracker as _gt
            if not _gt().allow_call():
                logger.warning("Coach call blocked: daily budget exceeded")
                self._write_status_field("daily budget — paused until midnight")
                return
        except Exception:
            pass
        try:
            # AUDIT 2026-04-28 (5.3): mark the system prompt with
            # cache_control=ephemeral so subsequent ticks with the same
            # prefix replay at ~10% of the input-token cost. system param
            # accepts a list of content blocks for fine-grained caching.
            response = self._client.messages.create(
                model=self._model,
                max_tokens=500,
                timeout=self._timeout_s,
                system=[{
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": user}],
            )
            raw = response.content[0].text
            # AUDIT 2026-04-28 (5.8 + 2.5): record token telemetry +
            # persistent coach trace for the "why did the coach say that?"
            # dashboard tab. usage may include cache_*_input_tokens
            # depending on SDK version; fall back to plain input_tokens.
            _tin = _tout = _cr = _cw = 0
            try:
                u = getattr(response, "usage", None)
                if u is not None:
                    _tin  = getattr(u, "input_tokens", 0) or 0
                    _tout = getattr(u, "output_tokens", 0) or 0
                    _cr   = getattr(u, "cache_read_input_tokens", 0) or 0
                    _cw   = getattr(u, "cache_creation_input_tokens", 0) or 0
            except Exception:
                pass
            try:
                from core.cost_tracker import get_tracker as _gt
                _gt().record_call(
                    model=self._model,
                    input_tokens=_tin, output_tokens=_tout,
                    cache_read=_cr, cache_write=_cw,
                    purpose="sr_coach",
                )
            except Exception as _exc:
                logger.debug("cost_tracker record_call: %s", _exc)
            try:
                from core.coach_trace import append as _trace_append
                _trace_append(
                    mode="sr",
                    model=self._model,
                    system_prompt=system,
                    user_prompt=user,
                    response=raw,
                    latency_ms=int((time.time() - t0) * 1000),
                    tokens_in=_tin, tokens_out=_tout,
                    cache_read=_cr, cache_write=_cw,
                )
            except Exception as _exc:
                logger.debug("coach_trace append: %s", _exc)
            self._last_sig = sig
        except _APITimeoutError:
            logger.warning("Claude API timeout after %ds — will retry at next trigger", self._timeout_s)
            self._last_coach_time = time.time() - self._debounce_s + 2.0
            self._write_status_field("Timeout — retrying next trigger")
            return
        except _APIConnectionError:
            logger.error("Claude API unreachable")
            self._write_status_field("API unreachable")
            return
        except Exception as e:
            logger.error("Claude error: %s", e)
            self._write_status_field(str(e)[:60])
            return

        latency = round((time.time() - t0) * 1000)
        logger.info("Coach response in %dms (model=%s)", latency, self._model)
        self._cache.set(coach_state, raw)
        self._write_fields(raw, cache_hit=False)

    def _convert(self, gs: dict) -> dict:
        hp_pct = gs.get("hp_pct", 100) / 100.0
        mp_pct = gs.get("mana_pct", 100) / 100.0
        game_s = gs.get("game_seconds", 0)

        wave = self._wave.update(gs.get("cs", 0), game_s)

        enemy_comp = gs.get("enemy_comp", [])
        return {
            "champion":         gs.get("champion", ""),
            "game_time_s":      game_s,
            "my_hp_pct":        hp_pct,
            "my_mana_pct":      mp_pct,
            "my_gold":          gs.get("gold", 0),
            "my_items":         gs.get("items", []),
            "my_level":         gs.get("level", 1),
            "my_cs":            gs.get("cs", 0),
            "wave_state":       wave,
            "ally_comp":        gs.get("ally_comp", []),
            "enemy_comp":       enemy_comp,
            "lane_matchup":     {
                "enemy_adc": enemy_comp[0] if enemy_comp else "unknown",
                "enemy_sup": enemy_comp[1] if len(enemy_comp) > 1 else "unknown",
            },
            "nearby_enemies":   [],
            "objective_timers": gs.get("obj_timers_dict", {}),
            "patch_version":    self._patch,
            "kda":              gs.get("kda", ""),
            "dead_count":       gs.get("dead_count", 0),
            "kill_window":      gs.get("kill_window", False),
        }

    def _parse_response(self, text: str) -> dict:
        field_map = {
            "action":       "action",
            "immediate":    "immediate",
            "next":         "next",
            "wave":         "wave",
            "objective":    "objective",
            "fight rule":   "fight_rule",
            "reset / item": "reset_item",
            "risk":         "risk",
        }
        fields = {}
        current_key = None
        current_val = []
        for line in text.strip().splitlines():
            s = line.strip()
            if not s:
                continue
            s_clean = s.lstrip("*").rstrip("*")
            import re as _re
            s_clean = _re.sub(r'^\*{1,2}(.*?)\*{1,2}(:)', r'\1\2', s_clean)
            matched = False
            for prefix, key in field_map.items():
                if s_clean.lower().startswith(prefix + ":"):
                    if current_key:
                        fields[current_key] = " ".join(current_val).strip()
                    current_key = key
                    current_val = [s_clean[len(prefix)+1:].strip()]
                    matched = True
                    break
            if not matched and current_key:
                current_val.append(s)
        if current_key:
            fields[current_key] = " ".join(current_val).strip()
        return fields

    def _write_fields(self, raw_response: str, cache_hit: bool = False,
                       update_ts: bool = True):
        fields = self._parse_response(raw_response)
        if not fields:
            logger.warning("No fields parsed from response (first 200 chars): %r",
                           raw_response[:200])
            return

        if "action" in fields:
            import re as _re
            plain = _re.sub(r'\[/?[AET]\]', '', fields["action"]).strip()
            fields["action"] = plain.upper()

        # (audit cycle 10) Mirror ARAM/Arena/Brawl pattern: surface
        # champion + ally_spells from _last_state so the dashboard
        # header pill flips immediately on SR games instead of relying
        # on the slower /api/locked-champion fallback.
        ls = getattr(self, "_last_state", None) or {}
        _champ = ls.get("champion") or ""
        if _champ:
            fields.setdefault("champion", _champ)
            _sd = ls.get("summoner_d") or ""
            _sf = ls.get("summoner_f") or ""
            if _sd or _sf:
                fields.setdefault("ally_spells", {
                    _champ: [{"spell": _sd, "cd_s": 0},
                             {"spell": _sf, "cd_s": 0}],
                })

        # 2026-05-02 (s31): force-overwrite ally_comp/enemy_comp from the
        # coach's current input. Claude's response shape doesn't include
        # comps, so the read-merge-write cycle below preserves whatever
        # was in coaching_data.json from a prior game. Without this, the
        # dashboard's RIGHT NOW / target / fight-rule panels reference the
        # PREVIOUS match's enemy comp for the first ~5 minutes of every
        # new game (until the coach engine eventually surfaces fresh
        # advice that names the actual current opponents). Use direct
        # assignment (not setdefault) — these MUST trump whatever's on
        # disk every tick.
        for _k in ("ally_comp", "enemy_comp"):
            _v = ls.get(_k)
            if _v is not None:
                fields[_k] = _v

        # Mirror live game stats from the raw gs so the dashboard top-bar
        # pills (CS / level / gold / KDA / game time) populate. Coaching
        # JSON is what file_ingest broadcasts to the WS /push channel —
        # without these keys, the pills hide via the dashboard JS's
        # `if (typeof p.cs === "number")` guards. /api/state already does
        # this via state-builder's liveclient overlay, but the WS push
        # path reads the file content directly.
        gs = getattr(self, "_last_gs", None) or {}
        for _k in ("kda", "cs", "level", "gold",
                   "game_time", "game_time_s",
                   "hp", "hp_max", "hp_pct",
                   "items", "owned_items", "enemy_team"):
            _v = gs.get(_k)
            if _v is not None:
                fields[_k] = _v

        # NOTE-003: hold the shared coaching_data_lock around the entire
        # read-modify-write cycle so the dashboard's _set_pregame /
        # /api/command refresh handlers can't clobber our update with their
        # own stale read. The lock is process-local and lives in
        # core.coaching_data_lock.
        from core.coaching_data_lock import coaching_data_lock
        retries = 3
        for attempt in range(retries):
            try:
                with coaching_data_lock():
                    if self.data_file.exists():
                        current = json.loads(self.data_file.read_text(encoding="utf-8"))
                        # 2026-04-27 audit: a partially-flushed file or a bad
                        # external write could leave non-dict JSON here, and
                        # current.update(...) would crash on TypeError. Treat
                        # it like a fresh start rather than propagating.
                        if not isinstance(current, dict):
                            logger.warning("coaching_data.json was %s, resetting", type(current).__name__)
                            current = self._default_data()
                    else:
                        current = self._default_data()

                    current.update(fields)
                    if "action" not in fields:
                        current["action"] = ""
                    current["mode"] = "game"

                    _pending_ds = getattr(self, "_last_ds_rows", None)
                    if _pending_ds is not None:
                        current["daemon_slayer_picks"] = [
                            {"id": r.item_id, "name": r.item_name,
                             "delta_dps": round(r.delta_dps, 2), "gold": r.gold}
                            for r in _pending_ds
                        ] if _pending_ds else []

                    imm = fields.get("immediate", "")
                    if imm:
                        log = current.get("log", [])
                        if isinstance(log, str):
                            log = [log]
                        ts = datetime.now().strftime("%H:%M")
                        suffix = " [C]" if cache_hit else ""
                        log.append(f"[{ts}] {imm[:60]}{suffix}")
                        current["log"] = log[-12:]

                    tmp = self.data_file.with_suffix(".tmp")
                    tmp.write_text(json.dumps(current, indent=2), encoding="utf-8")
                    tmp.replace(self.data_file)
                logger.debug("Wrote %d fields (cache=%s)", len(fields), cache_hit)
                if update_ts:
                    try:
                        from core.coaching_timestamps import write_coaching_ts as _wts
                        _wts("sr")
                    except Exception:
                        pass  # non-fatal
                return
            except Exception as e:
                if attempt < retries - 1:
                    time.sleep(0.05)
                else:
                    logger.error("Failed to write coaching_data.json: %s", e)

    def _write_status_field(self, status: str):
        self._write_fields(f"Immediate: {status}", update_ts=False)

    def _default_data(self) -> dict:
        return {
            "mode": "game",
            "action": "",
            "immediate": "", "next": "", "fight_rule": "",
            "wave": "", "objective": "", "reset_item": "",
            "risk": "", "map": "", "log": [], "pregame": "",
        }
