"""
coach_integration.py
Bridge between LoLOverlay's game_reader and the auto-coaching engine.
"""

import os
import json
import time
import logging
import threading
import anthropic
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
        "Spikes: BotRK (1-item), Kraken+PD (anti-tank). "
        "Macro: force 2v2s, avoid extended poke. "
        "Exploit: E to a tagged enemy ignores terrain — use through walls."
    ),
    "Miss Fortune": (
        "Miss Fortune. Mechanics: E (rain) slows first, then ult for guaranteed full channel; "
        "ult angle = perpendicular to enemy team, from behind cover; Strut MS — don't take hits. "
        "Spikes: Lethality first (poke dominance), Kraken (anti-tank). "
        "Macro: group for objectives, punish in MF ult-angle windows. "
        "Exploit: Q bounce target = minion standing directly behind enemy ADC."
    ),
}
GENERIC_PROFILE = (
    "ADC. Priorities: safe uptime, wave tempo, item spikes, objective windows. "
    "Never die without purpose. Always know where the next wave crashes."
)

# ── Summoner's Rift system prompt ─────────────────────────────────────────────

SR_SYSTEM_PROMPT = """\
You are coaching a challenger-level ADC in Summoner's Rift. Skip all basics. \
Give decision-quality, specific advice only.

CHAMPION: {profile}

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

OUTPUT FORMAT — follow exactly, no preamble:
Action: <1-3 WORDS ALL-CAPS macro priority — e.g. PUSH BOT LANE / BASE LOW HP / FREEZE WAVE / FIGHT NOW / GIVE SPACE / DEFEND TOWER / CRASH AND RESET / TAKE DRAKE / TAKE BARON / END GAME>
Immediate: <concise 3-5s action, use [A]/[E] name tags, max 15 words>
Next: <15-30s plan, use [A]/[E] tags and [T] for all timings, max 20 words>
Wave: <state + <=6 word reason>
Objective: <take/setup/skip/rotate-NOW + [T] timing>
Fight rule: <specific condition using [A]/[E] tags + exact mechanic>
Reset / item: <item name + exact gold check>
Risk: <specific threat using [E] tag + mechanic to watch>
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

def _build_user_prompt(gs: dict, wave_state: str) -> str:
    """Build a rich context prompt from the full game_reader state dict."""
    game_time  = gs.get("game_time", "0:00")
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
    kda        = gs.get("kda", "0/0/0")
    items      = ", ".join(gs.get("items", [])) or "none"
    summ_d     = gs.get("summoner_d", "?")
    summ_f     = gs.get("summoner_f", "?")
    allies     = ", ".join(gs.get("ally_comp", [])) or "unknown"
    enemies    = ", ".join(gs.get("enemy_comp", [])) or "unknown"
    enemy_locs = gs.get("enemy_locs", "unknown")
    objectives = gs.get("objectives", "none")
    walk_drake = gs.get("walk_time_drake")
    walk_baron = gs.get("walk_time_baron")
    camp_hint  = gs.get("camp_hint", "")
    ally_status = gs.get("ally_status_str", allies)
    dead_info  = gs.get("dead_respawn_str", "")
    next_spike = gs.get("next_item_str", "")
    ally_kills = gs.get("ally_kills_total", 0)
    enemy_kills = gs.get("enemy_kills_total", 0)
    kill_diff   = ally_kills - enemy_kills
    kill_str    = (f"+{kill_diff}" if kill_diff > 0 else str(kill_diff)) + f" ({ally_kills}v{enemy_kills})"

    # New fields
    gank_threat   = gs.get("gank_threat", "")
    friendly_jg   = gs.get("friendly_jg", "")
    position_note = gs.get("position_note", "")
    ward_hint     = gs.get("ward_hint", "")
    enemy_lane    = gs.get("enemy_lane_str", "")
    game_mode     = gs.get("game_mode", "CLASSIC")
    is_aram       = "ARAM" in game_mode

    walk_str = ""
    if not is_aram:
        if walk_drake is not None:
            walk_str += f"  Walk→drake: ~{walk_drake}s"
        if walk_baron is not None:
            walk_str += f"  Walk→baron: ~{walk_baron}s"

    lines = [
        f"=== {game_time} | {phase} | kills {kill_str} ===",
        f"HP: {hp_pct}% ({hp_abs}/{hp_max})  Mana: {mp_pct}%  Gold: {gold}g",
        f"CS: {cs} ({cs_pm}/min)  Lv: {level}  KDA: {kda}",
        f"Items: {items}",
    ]
    if next_spike:
        lines.append(f"Next spike: {next_spike}")

    # Lane quest boots note (invisible slot — not in items array)
    quest_boots = gs.get("quest_boots_owned", False)
    if quest_boots:
        lines.append("Note: Lane quest boots owned (invisible slot — skip boots in item path)")
    elif gs.get("level", 1) >= 5 and not quest_boots:
        lines.append(f"Note: Lane quest boots NOT yet completed (level {gs.get('level',1)})")
    # Build explicit ally/enemy section with lane role labels
    ally_list  = gs.get("ally_comp",  [])
    enemy_list = gs.get("enemy_comp", [])

    # Determine the lane partner (bot-lane support or jungler depending on role)
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
        f"REMINDER: [A]=ally (green), [E]=enemy (red) — do NOT swap.",
        f"Enemy locations: {enemy_locs}",
    ]
    # Explicitly label enemy lane opponents to prevent ally/enemy confusion
    if enemy_lane:
        lines.append(f"Enemy bot lane (your lane opponents): {enemy_lane}")
    elif enemy_list:
        # If no specific lane data, at minimum list enemy names clearly
        lines.append(f"Note: enemies are {', '.join(enemy_list)} — do NOT use their names as allies")

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

    # ARAM-specific item guidance
    if is_aram:
        try:
            aram_ctx = aram_item_context(
                gs.get("enemy_comp", []),
                gs.get("ally_comp",  []),
                gs.get("champion",   ""),
            )
            if aram_ctx:
                lines.append("")
                for cl in aram_ctx.splitlines():
                    lines.append(f"  {cl}")
        except Exception:
            pass

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

        # Find sample ~15s ago
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

        # Coach config
        self._debounce_s = 3.0
        self._timeout_s  = 20
        # Haiku is used by default for live coaching — ~2-3s latency vs ~10s for Sonnet.
        # Override to claude-sonnet-4-6 in config/coach_settings.json for deeper analysis.
        self._model = "claude-haiku-4-5-20251001"
        self._patch = "current"

        # Load config if present
        cfg_path = Path(__file__).parent / "config" / "coach_settings.json"
        if cfg_path.exists():
            try:
                cfg = json.loads(cfg_path.read_text())
                self._debounce_s = cfg.get("debounce_seconds", self._debounce_s)
                self._timeout_s  = cfg.get("timeout_seconds",  self._timeout_s)
                self._model      = cfg.get("model",            self._model)
            except Exception:
                pass

        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            logger.warning("ANTHROPIC_API_KEY not set — auto-coaching disabled")
        self._client = anthropic.Anthropic(api_key=api_key) if api_key else None

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

    # ── Public API called from overlay ──────────────────────────────────────

    def submit_state(self, game_state: dict):
        """Called from _apply_auto_fields every 2s. Non-blocking."""
        if not self._client:
            return
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
        """
        Reset all per-game state. Called by the overlay on game start and
        game end so stale wave tracking, triggers, and state don't bleed
        between matches.  Also writes a blank coaching_data.json so stale
        advice from the previous game is not visible at the start of the next.
        """
        self._last_submitted_state = {}
        self._last_state = {}
        self._last_coach_time = 0.0
        self._pending = False
        self._wave = WaveTracker()
        # Phase 6 Step 2 Fix 7: clear visible artifact so stale advice
        # from the previous game does not show at new game start.
        try:
            blank = self._default_data()
            blank["mode"] = "game"
            tmp = self.data_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(blank, indent=2), encoding="utf-8")
            tmp.replace(self.data_file)
        except Exception:
            pass
        logger.info("Coach state reset for new game")

    def set_wave_override(self, state: str):
        self._wave.set_override(state, duration_s=30)
        logger.info("Wave override: %s (30s)", state)

    # ── Internal ─────────────────────────────────────────────────────────────

    def _should_coach(self, state: dict) -> bool:
        now = time.time()

        # Kill window: bypass normal debounce when enemies just died
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

        # Cache check
        cached = self._cache.get(coach_state)
        if cached:
            latency = round((time.time() - t0) * 1000)
            logger.debug("Cache hit in %dms", latency)
            self._write_fields(cached, cache_hit=True)
            return

        if not self._client:
            return

        # Build prompt — detect game mode and select appropriate system prompt
        champion   = coach_state.get("champion", "")
        # Prefer detailed SR profiles for primary pool, fall back to champion_profiles.py
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
                    profile  = (
                        f"{champion} ({role}, {dmg} damage). "
                        f"{mechanic} "
                        + (f"Spikes: {spikes}. " if spikes else "")
                        + (f"ARAM: {aram_tip}" if aram_tip else "")
                    )
                else:
                    profile = GENERIC_PROFILE
            except Exception:
                profile = GENERIC_PROFILE
        game_mode  = game_state.get("game_mode", "CLASSIC")
        is_aram    = "ARAM" in game_mode

        if is_aram:
            # ARAM Mayhem uses a separate coaching frame
            system = ARAM_SYSTEM_PROMPT.format(
                profile     = profile,
                mayhem_tag  = " Mayhem" if game_mode == "ARAM" else "",
                augment_line= "\n   (State your augments in chat for augment-specific advice)",
            )
        else:
            system = SR_SYSTEM_PROMPT.format(profile=profile)

        user = _build_user_prompt(game_state, coach_state.get("wave_state", "unknown"))

        if self.debug:
            logger.debug("User prompt:\n%s", user)

        # API call with timeout
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=500,          # increased — richer output for challenger coaching
                timeout=self._timeout_s,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            raw = response.content[0].text
        except anthropic.APITimeoutError:
            logger.warning("Claude API timeout after %ds — will retry at next trigger", self._timeout_s)
            # Reset timer so the next poll triggers a retry after the debounce period
            self._last_coach_time = time.time() - self._debounce_s + 2.0
            self._write_status_field("Timeout — retrying next trigger")
            return
        except anthropic.APIConnectionError:
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
        """Convert game_reader dict → coach cache key format."""
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
        }

    def _parse_response(self, text: str) -> dict:
        """Parse coaching response into field dict for coaching_data.json.
        Handles both 'Field:' and '**Field:**' (markdown bold) formats."""
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
            # Strip markdown bold markers: **Field:** → Field:
            s_clean = s.lstrip("*").rstrip("*")
            # Also handle **Field:** where bold wraps just the label
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
        """Atomically update coaching_data.json with new coaching fields.
        
        Fields are stored WITH [A]/[E]/[T] tags intact — the overlay's
        rich-text renderer strips them and applies colors.
        Action field is stripped to plain ALLCAPS keywords.

        update_ts: if True (default), write last_coaching_ts.json after a
          successful coaching payload write.  Set to False for status/error
          placeholder writes so those do not advance the coaching timestamp.
        """
        fields = self._parse_response(raw_response)
        if not fields:
            logger.warning("No fields parsed from response (first 200 chars): %r",
                           raw_response[:200])
            return

        # Clean up Action field — strip any tags, keep all-caps
        if "action" in fields:
            import re as _re
            plain = _re.sub(r'\[/?[AET]\]', '', fields["action"]).strip()
            fields["action"] = plain.upper()

        retries = 3
        for attempt in range(retries):
            try:
                if self.data_file.exists():
                    current = json.loads(self.data_file.read_text(encoding="utf-8"))
                else:
                    current = self._default_data()

                current.update(fields)
                current["mode"] = "game"  # ensure game mode when coaching arrives

                # Append to log
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
                # Phase 2 Step 1 / 1.1 / Phase 3 Step 1:
                # Write per-mode coaching timestamp for MetricsCache.
                # update_ts=False for status/error/timeout writes (no advance).
                # update_ts=True (default) for successful coaching payload writes.
                if update_ts:
                    try:
                        from core.coaching_timestamps import write_coaching_ts as _wts
                        _wts("sr")  # SR path owns this integration module
                    except Exception:
                        pass  # non-fatal
                return
            except Exception as e:
                if attempt < retries - 1:
                    time.sleep(0.05)
                else:
                    logger.error("Failed to write coaching_data.json: %s", e)

    def _write_status_field(self, status: str):
        """Write a status message to the immediate field only.
        update_ts=False: status/error writes must not advance last_coaching_ts.
        """
        self._write_fields(f"Immediate: {status}", update_ts=False)

    def _default_data(self) -> dict:
        return {
            "mode": "game",
            "action": "",
            "immediate": "", "next": "", "fight_rule": "",
            "wave": "", "objective": "", "reset_item": "",
            "risk": "", "map": "", "log": [], "pregame": "",
        }
