"""
coaches/arena_coach.py  — v2  (ARCH-002 BaseCoach inheritance)

Arena (2v2v2v2) full coaching engine.
Inherits lifecycle from coaches.BaseCoach.
Self-polls Riot API every 1.5s.
Vision fires every 12s (Sonnet): augment choices, item anvil, round phase.
Writes: data/arena_coaching_data.json

ARCH-002 (full) — 2026-04-18
Also fixes: _parse_fields called without keys (silent TypeError → no coaching output)
"""

import os
import sys
import json
import logging
from pathlib import Path

from coaches._base_coach import (
    BaseCoach,
    load_json,
    safe_write,
    parse_field,
    parse_fields,
    read_api_key,
    fmt_abilities,
)

logger = logging.getLogger("rc.coaches.arena")

_APP_DIR = Path(__file__).parent.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

# ── System prompt ─────────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """\
You are a Challenger-level Arena 2v2v2v2 coach. Rotating opponents, no waves, HP carries between rounds.

CHAMPION: {profile}
Champion build guide: {arena_meta}
{adaptation_hint}
═══ ARENA PRIORITY DECISION TREE ═══
Opponent HP > 70%: standard fight — do NOT overcommit; trade efficiently and kite
Opponent HP 40-70%: all-in when your burst combo is up + escape ready
Opponent HP < 40%: play safe — they will desperate all-in; kite and poke to close
Your HP < 25%: NEVER all-in; kite, disengage, survive to next camp phase
Your HP > 70%: aggressive — you can afford to make plays and take risks

═══ ROUND FIGHT RULES ═══
Your pair: stay within 300 units of your partner. Peel for each other.
Engage when: BOTH abilities are off cooldown + carry is isolated + escape path clear
Disengage when: you or partner HP < 20% OR enemy pair has both CC abilities ready
Target priority: 1) [E] carry (lowest HP, highest threat), 2) [E] CC holder, 3) tank last
Augment active: use EVERY fight — never save for "perfect" moment
Kiting: orbwalk every single auto. Never stand still during fights.
Anvil phase: ALWAYS take. Complete carry item first, then defensive stat stick.

═══ CAMP PHASE ═══
Always: buy components, upgrade if 2 copies available, heal at campfire
Priority spend: carry item completion > defensive component > sell weakest unit
Augment select at camp: pick damage amp or reset-on-kill for carry; HP/resist for tank

═══ AUGMENT SELECTION FRAMEWORK ═══
1. Does it combo with your kit? (e.g. dash → Sudden Impact; CC → Glacial Augment)
2. Does it scale with your items? (AD items → Conqueror; AP → Luden's)
3. Is it reliable in 2v2? (avoid conditional augments requiring 5+ enemies)
Best for carries: Cut Down, Sudden Impact, Eyeball Collection, Absolute Focus
Best for tanks: Bone Plating, Grasp, Shield Bash, Unflinching

NAME TAGS: [A]Ally[/A]  [E]Enemy[/E]  [T]timing[/T]

OUTPUT FORMAT — exactly 7 fields, NO markdown:
Action: <1-3 WORDS ALL-CAPS — e.g. ALL IN / KITE BACK / BUY ITEMS / FOCUS CARRY / CAMP PHASE>
Round strategy: <opponent HP + your HP + correct approach, use [E] tag, max 20 words>
Fight rule: <exact engage condition with [E] carry + specific ability window, max 20 words>
Augment advice: <if augment select: take X — why. Else: play your current augment this way>
Anvil advice: <if anvil open: take X to complete Y. Else: next component to build>
Target priority: <kill [E]name[/E] first — why — then who>
Risk: <[E]ability[/E] to dodge + when it's up>
"""

_USER_TEMPLATE = """\
=== Arena Round {round} ===
Your champion: {champion}
Partner: {partner}
HP: {hp_pct}%  Gold: {gold}g  Level: {level}  KDA: {kda}
Items: {items}

Your rank: #{rank} of {alive} teams remaining
Next opponent: {next_opp}

Team health rankings:
{team_rankings}

Active augments: {augments}
My abilities: {my_abilities}
{vision_context}
"""

_AUGMENT_SELECT_PROMPT = """\
You are a Challenger Arena coach. Choose the best augment.

Current state:
Champion: {champion}  Partner: {partner}
Items: {items}  HP: {hp_pct}%  Round: {round}

AUGMENT CHOICES:
{choices}

NO markdown. Output exactly:
Take: <augment name>
Why: <one sentence — why it works for this champion + round>
Gameplan: <how to fight differently because of this augment>
"""

_OUTPUT_KEYS = [
    "action", "round strategy", "fight rule",
    "augment advice", "anvil advice", "target priority", "risk",
]


# ══════════════════════════════════════════════════════════════════════════════
# Coach class
# ══════════════════════════════════════════════════════════════════════════════


def _load_arena_build_note(champion: str) -> str:
    """Load champion build note from aram_champion_builds.json for Arena.
    Arena uses the same item shop as SR. ARAM builds are valid but notes
    should be read in Arena context: no health packs, heal at camp, shorter fights.
    """
    try:
        p = _APP_DIR / "data" / "meta_build" / "aram_champion_builds.json"
        if not p.exists():
            return ""
        data = json.loads(p.read_text(encoding="utf-8"))
        entry = data.get(champion)
        if not entry or isinstance(entry, str):
            return ""
        tier = entry.get("aram_tier", "")
        note = entry.get("build_note", "")
        fb   = entry.get("full_build", [])
        vt   = entry.get("vs_tanks", "")
        vh   = entry.get("vs_healing", "")
        build_str = ", ".join(fb) if fb else ""
        # Arena framing: carry item first, no health packs context
        result = f"{tier} tier — {note}" if tier and note else note or tier
        if build_str:
            result += f" | Full build: {build_str}"
        if vt:
            result += f" | vs tanks: {vt}"
        if vh:
            result += f" | vs healing: {vh}"
        return result[:350]
    except Exception:
        return ""


class Coach(BaseCoach):
    """Arena 2v2v2v2 coach. Inherits full lifecycle from BaseCoach."""

    GAME_MODES     = ("ARENA", "CHERRY")
    _MODE_NAME     = "arena"
    _DATA_FILENAME = "arena_coaching_data.json"

    # Tunable overrides — Arena is faster-paced, shorter debounce
    _VISION_INTERVAL   = 12.0
    _DEBOUNCE_S        = 4.0
    _FAST_PATH_MIN_S   = 1.5
    _HP_DROP_THRESHOLD = 10.0

    # ── BaseCoach hooks ───────────────────────────────────────────────────────

    def _init_extra(self) -> None:
        """Arena-specific state: stateful round counter."""
        self._last_round         = 0
        self._event_round_count  = 0
        self._last_event_count   = 0

    def _reset_extra(self) -> None:
        self._last_round        = 0
        self._event_round_count = 0
        self._last_event_count  = 0

    def _on_state_received(self, state: dict) -> None:
        """Inject approximate round number from stateful event-delta tracker."""
        state["round"] = self._update_round_from_events(state)

    def _fast_path_trigger(self, state: dict, prev: dict) -> bool:
        new_round = (
            self._event_round_count != self._last_round
            and self._event_round_count > 0
        )
        hp_drop = (
            prev.get("hp_pct", 100) - state.get("hp_pct", 100)
        ) >= self._HP_DROP_THRESHOLD
        if new_round:
            self._last_round = self._event_round_count  # advance tracker
        return new_round or hp_drop

    # ── BaseCoach abstract implementations ────────────────────────────────────

    def _blank_artifact_data(self) -> dict:
        return {
            "mode": "arena", "action": "", "round_strategy": "",
            "fight_rule": "", "augment_advice": "", "anvil_advice": "",
            "target_priority": "", "risk": "", "teams": [],
            "round": 0, "rank": "?", "alive_teams": 8, "hp_pct": 100,
        }

    def _parse_raw_state(self, raw: dict) -> dict:
        return _parse_arena_state(raw)

    # ── Round tracker ─────────────────────────────────────────────────────────

    def _update_round_from_events(self, state: dict) -> str:
        """
        Stateful round tracker — increments only when cumulative combat-event
        count grows. Returns labeled "~N" (approximate) string.
        API has no native Arena round counter.
        """
        new_count = state.get("_raw_event_count", 0)
        if new_count > self._last_event_count:
            self._event_round_count = min(self._event_round_count + 1, 30)
            self._last_event_count  = new_count
        return f"~{max(self._event_round_count, 1)}"

    # ── Vision ────────────────────────────────────────────────────────────────

    def _run_vision(self) -> None:
        try:
            from core.feature_policy import is_allowed as _fp_ok
            if not _fp_ok("arena", "live_coaching"):
                return
        except Exception:
            pass
        try:
            reader = ArenaVisionReader(self._api_key)
            state  = reader.read()
            if not state:
                return
            self._vision_state = state
            if state.get("augment_select") and state.get("augment_choices"):
                self._handle_augment_select(state)
                return
            if state.get("anvil_choices"):
                self._handle_anvil(state)
        except Exception as exc:
            logger.debug("Arena vision run: %s", exc)

    # ── Coach ─────────────────────────────────────────────────────────────────

    def _run_coach(self, state: dict) -> None:
        try:
            from core.feature_policy import is_allowed as _fp_ok, write_disabled_placeholder as _fp_wr
            if not _fp_ok("arena", "live_coaching"):
                _fp_wr("arena")
                return
        except Exception:
            pass
        if not self._client:
            return
        try:
            from coach_integration import CHAMPION_PROFILES, GENERIC_PROFILE
            champ   = state.get("champion", "Unknown")
            profile = CHAMPION_PROFILES.get(champ, GENERIC_PROFILE)
            arena_meta = _load_arena_build_note(champ)
            _hint = ""
            if os.environ.get("RC_COACH_ADAPTATION") == "1":
                try:
                    from coaches.adaptation_hint import format_hint_line as _fhl
                    _hint = _fhl(champ, "arena", None)
                except Exception:
                    pass
            system  = _SYSTEM_PROMPT.format(profile=profile, arena_meta=arena_meta, adaptation_hint=_hint)

            teams = state.get("teams", [])
            rankings = "\n".join(
                f"  {'[YOU]' if t.get('is_you') else '     '} "
                f"{t.get('name', '?')[:12]:12}  {t.get('hp_pct', 100):3d}%"
                + (" [NEXT OPP]" if t.get("is_next_opponent") else "")
                + (" [DEAD]"     if t.get("is_dead")           else "")
                for t in sorted(teams, key=lambda x: -x.get("hp_pct", 0))
            ) or "  Team data loading..."

            partner  = next((t.get("name", "?") for t in teams if t.get("is_partner")),  "Unknown")
            next_opp = next((t.get("name", "?") for t in teams if t.get("is_next_opponent")), "Unknown")
            augments = ", ".join(state.get("augments", [])) or "none"

            vs = self._vision_state
            vision_ctx = ""
            if vs.get("camp_phase"):
                vision_ctx = "CAMP PHASE ACTIVE — buy/upgrade items and heal now."
            elif vs.get("anvil_choices"):
                vision_ctx = f"ITEM ANVIL available: {', '.join(vs.get('anvil_choices', []))}"

            user = _USER_TEMPLATE.format(
                round         = state.get("round", 0),
                champion      = champ,
                partner       = partner,
                hp_pct        = state.get("hp_pct",  100),
                gold          = state.get("gold",    0),
                level         = state.get("level",   1),
                kda           = state.get("kda",     "0/0/0"),
                items         = ", ".join(state.get("items", [])) or "none",
                rank          = state.get("rank",    "?"),
                alive         = state.get("alive_teams", 8),
                next_opp      = next_opp,
                team_rankings = rankings,
                augments      = augments,
                my_abilities  = fmt_abilities(state.get("my_abilities", {})),
                vision_context = vision_ctx,
            )

            import time as _time_a
            _t0 = _time_a.perf_counter()
            # AUDIT 2026-04-29 (gap E): cache_control: ephemeral on the
            # system prompt — system prompt is reused every tick.
            resp = self._client.messages.create(
                model="claude-haiku-4-5-20251001", max_tokens=650,
                system=[{"type": "text", "text": system,
                         "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user}],
                timeout=20,
            )
            # AUDIT 2026-04-29 (gap A): cost + trace telemetry.
            self._record_coach_call(resp, system=system, user=user,
                                    t0_perf=_t0,
                                    model="claude-haiku-4-5-20251001",
                                    purpose="arena_coach")
            raw    = resp.content[0].text
            # ARCH-002 bug fix: pass keys argument (was missing — caused silent TypeError)
            fields = parse_fields(raw, _OUTPUT_KEYS)
            if not fields:
                logger.warning("Arena: no fields parsed")
                return

            current = load_json(self._out)
            current.update({
                "action":          fields.get("action",          "").upper(),
                "round_strategy":  fields.get("round strategy",  ""),
                "fight_rule":      fields.get("fight rule",       ""),
                "augment_advice":  fields.get("augment advice",  ""),
                "anvil_advice":    fields.get("anvil advice",    ""),
                "target_priority": fields.get("target priority", ""),
                "risk":            fields.get("risk",            ""),
                "teams":           teams,
                "round":           state.get("round",        0),
                "rank":            state.get("rank",         "?"),
                "alive_teams":     state.get("alive_teams",  8),
                "hp_pct":          state.get("hp_pct",       100),
                "wins":            state.get("wins",         0),
                "losses":          state.get("losses",       0),
                "game_time_s":     state.get("game_seconds", 0),
                "camp_phase":      vs.get("camp_phase",      False),
                # (audit cycle 4) Mirror ARAM coach: write champion +
                # ally_spells to the artifact so the dashboard's header
                # champion-pill flips immediately at champ-pop instead of
                # waiting for the /api/locked-champion fallback poll.
                "champion":        champ,
                "ally_spells":     {champ: [{"spell": state.get("summoner_d", ""), "cd_s": 0},
                                            {"spell": state.get("summoner_f", ""), "cd_s": 0}]}
                                  if champ and (state.get("summoner_d") or state.get("summoner_f")) else {},
            })
            safe_write(self._out, current)
            logger.debug("Arena coaching written (%d fields)", len(fields))
            try:
                from core.coaching_timestamps import write_coaching_ts as _wts
                _wts("arena")
            except Exception:
                pass
        except Exception as exc:
            logger.error("Arena coach: %s", exc)

    def _handle_augment_select(self, vision_state: dict) -> None:
        if not self._client:
            return
        gs      = self._last_state
        choices = vision_state.get("augment_choices", [])
        champ   = gs.get("champion", "Unknown")
        teams   = gs.get("teams", [])
        partner = next((t.get("name", "?") for t in teams if t.get("is_partner")), "?")
        prompt  = _AUGMENT_SELECT_PROMPT.format(
            champion = champ,
            partner  = partner,
            items    = ", ".join(gs.get("items", [])) or "none",
            hp_pct   = gs.get("hp_pct", 100),
            round    = gs.get("round",  0),
            choices  = "\n".join(f"- {c}" for c in choices),
        )
        try:
            import time as _time_b
            _t0b = _time_b.perf_counter()
            resp = self._client.messages.create(
                model="claude-haiku-4-5-20251001", max_tokens=250,
                messages=[{"role": "user", "content": prompt}], timeout=15,
            )
            self._record_coach_call(resp, system="", user=prompt,
                                    t0_perf=_t0b,
                                    model="claude-haiku-4-5-20251001",
                                    purpose="arena_aug_select")
            raw     = resp.content[0].text
            current = load_json(self._out)
            current.update({
                "augment_select":  True,
                "aug_take":        parse_field(raw, "Take"),
                "aug_why":         parse_field(raw, "Why"),
                "aug_plan":        parse_field(raw, "Gameplan"),
                "augment_choices": choices,
            })
            safe_write(self._out, current)
        except Exception as exc:
            logger.error("Arena augment select: %s", exc)

    def _handle_anvil(self, vision_state: dict) -> None:
        choices = vision_state.get("anvil_choices", [])
        if not choices or not self._client:
            return
        gs = self._last_state
        prompt = (
            f"Arena item anvil. Champion: {gs.get('champion','?')}. "
            f"Current items: {', '.join(gs.get('items', []) or ['none'])}. "
            f"Anvil choices: {', '.join(choices)}. "
            f"HP: {gs.get('hp_pct', 100)}%. Round: {gs.get('round', 0)}. "
            "NO markdown. Output: Take: <item>\nWhy: <one line reason>"
        )
        try:
            import time as _time_c
            _t0c = _time_c.perf_counter()
            resp = self._client.messages.create(
                model="claude-haiku-4-5-20251001", max_tokens=100,
                messages=[{"role": "user", "content": prompt}], timeout=10,
            )
            self._record_coach_call(resp, system="", user=prompt,
                                    t0_perf=_t0c,
                                    model="claude-haiku-4-5-20251001",
                                    purpose="arena_anvil")
            raw     = resp.content[0].text
            current = load_json(self._out)
            current["anvil_advice"] = f"Take: {parse_field(raw, 'Take')} — {parse_field(raw, 'Why')}"
            safe_write(self._out, current)
        except Exception as exc:
            logger.error("Arena anvil: %s", exc)


# ── Vision reader ─────────────────────────────────────────────────────────────

class ArenaVisionReader:
    PROMPT = """\
Analyze this Arena (2v2v2v2) League of Legends screenshot.
Return ONLY valid JSON:
{
  "augment_select": false,
  "augment_choices": [],
  "anvil_choices": [],
  "camp_phase": false,
  "round_number": 1
}
Rules:
- augment_select: true if large augment card selection panel visible
- augment_choices: list of augment names if selection visible
- anvil_choices: list of item names if item anvil visible
- camp_phase: true if in the between-round camp phase (not in combat arena)
- Return ONLY the JSON
"""

    def __init__(self, api_key: str):
        import anthropic
        from modes.shared_vision import GameVisionReader
        r = GameVisionReader.__new__(GameVisionReader)
        r._client = anthropic.Anthropic(api_key=api_key)
        r._model  = "claude-sonnet-4-6"
        r._last   = {}
        r.PROMPT  = self.PROMPT
        self._reader = r

    def read(self):
        return self._reader.read()


# ── Arena game state parser ───────────────────────────────────────────────────

def _parse_arena_state(raw: dict) -> dict:
    ap     = raw.get("activePlayer", {})
    gd     = raw.get("gameData", {})
    all_p  = [p for p in (raw.get("allPlayers", []) or []) if isinstance(p, dict)]
    events = (raw.get("events", {}) or {}).get("Events", [])

    game_time = float(gd.get("gameTime", 0))
    game_mode = gd.get("gameMode", "ARENA")

    stats  = ap.get("championStats", {}) or {}
    hp     = int(stats.get("currentHealth", 0))
    hp_max = int(stats.get("maxHealth", 1))
    hp_pct = int(100 * hp / max(hp_max, 1))

    my_name = (ap.get("summonerName") or ap.get("riotIdGameName") or "").split("#")[0]
    me = None
    for p in all_p:
        pn = (p.get("summonerName") or "").split("#")[0]
        if pn == my_name or p.get("championName") == ap.get("championName"):
            me = p
            break

    sc      = (me or {}).get("scores", {}) or {}
    items   = [
        it.get("displayName", "")
        for it in ((me or {}).get("items") or [])
        if isinstance(it, dict) and it.get("displayName")
    ]

    alive        = sum(1 for p in all_p if not p.get("isDead"))
    my_team_id   = (me or {}).get("team", "ORDER") if me else "ORDER"
    teams = [
        {
            "name":             p.get("championName", f"Player{i}"),
            "hp_pct":           100 if not p.get("isDead") else 0,
            "is_you":           p is me,
            "is_partner":       p.get("team") == my_team_id and p is not me,
            "is_dead":          p.get("isDead", False),
            "is_next_opponent": False,
        }
        for i, p in enumerate(all_p)
    ]

    # Rank: only emit numeric rank when vision data provides real HP variance
    rank_str   = "?"
    hp_values  = [t["hp_pct"] for t in teams if not t["is_dead"]]
    if any(v not in (0, 100) for v in hp_values) and teams:
        for idx, t in enumerate(sorted(teams, key=lambda t: -t["hp_pct"])):
            if t["is_you"]:
                rank_str = f"~{idx + 1}"
                break

    combat_events = [
        ev for ev in events
        if isinstance(ev, dict) and ev.get("EventName") in (
            "TurretKilled", "ChampionKill", "FirstBlood"
        )
    ]

    return {
        "game_mode":        game_mode,
        "game_seconds":     game_time,
        "champion":         (me or ap).get("championName", "Unknown"),
        "hp_pct":           hp_pct,
        "gold":             int(ap.get("currentGold", 0)),
        "level":            ap.get("level", 1),
        "kda":              f"{sc.get('kills',0)}/{sc.get('deaths',0)}/{sc.get('assists',0)}",
        "items":            items,
        "wins":             sc.get("kills", 0),
        "losses":           sc.get("deaths", 0),
        "alive_teams":      (alive + 1) // 2,
        "rank":             rank_str,
        "round":            None,  # set by Coach._on_state_received
        "teams":            teams,
        "augments":         [],
        "_raw_event_count": len(combat_events),
    }
