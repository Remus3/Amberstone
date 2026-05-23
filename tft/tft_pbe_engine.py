"""
tft/tft_pbe_engine.py

Challenger-level TFT Set 17: Space Gods coaching engine - Double Up focus.
Analyses live game state and produces structured advice for all coaching panels.
Writes structured JSON to data/tft_pbe_coaching_data.json for the overlay.
Last updated: patch 17.3 (2026-05-13).
"""

import json
import logging
import re
import threading
import time
from pathlib import Path

import anthropic

logger = logging.getLogger("rc.tft.pbe")

TFT_PBE_SYSTEM_PROMPT = """\
You are a Challenger-rank TFT Set 17: Space Gods coach specialising in Double Up.
Maximum information density, zero padding.

SET 17 CRITICAL CHANGES - DO NOT USE SET 16 KNOWLEDGE:
- CAROUSEL IS GONE. Replaced by "Realm of the Gods" at stages 2-4, 3-4, 4-4.
- At God rounds, players pick offerings from 2 random Gods (+ Pengu placement reward).
- Aligning with one God 2+ times on stages 2-4 grants a God Boon at stage 4-7.
- PvE rounds remain at end of each stage (wolves, raptors, herald, baron).

PATCH 17.3 CHANGES (2026-05-13):
- MORGANA is now 4-cost (Magic Tank). Redeemer (Conduit + Space Groove) is EASIER to execute.
- ANIMA (6): loot now after EVERY combat, not just wins. Anima is more consistent - loss-streak not required to cash out.
- STARGAZER REWORKED: now grants HP regeneration + stacking stats. Fountain mechanic removed. Yasuo hex synergy retained.
- MARAUDER NERFED: Omnivamp reduced all tiers (20→18%, 40→35%, 60→55%). No longer a top tank trait.
- APEX PRIMORDIAN GUTTED: AS 0.9→0.6, armor/MR 150→60, grid damage 400→100. Primordian comps are DEAD.
- AP LATE GAME BUFFED: Aurelion Sol, Karma, LeBlanc, Sona all received damage buffs. AP carries stronger.
- EDGE OF NIGHT: healing 30%→20%. Less sustain for carry items.
- SPACE GROOVE EMBLEM: 4-second cooldown added. Less spammable.
- HORIZON FOCUS: removed from game entirely. Don't suggest it.
- ENCOUNTERS (17.3): Double Duplicators now gives Tiny (not Lesser); appears at 3-5 not 3-3.
  Reroll Start NERFED: 5 free rerolls at 2-1 (was 8). Hyper-roll openers less explosive.
- New augments available: Concentration, Loot Singularity, New Recruit, Timestream, Tour of the Galaxy.
- Cosmic Restart rerolls cut (11→8). Jeweled Lotus, May the Fours Be With You nerfed.

PATCH 17.2 MECHANICS (STILL ACTIVE):
ENCOUNTERS: An Encounter modifies early-game conditions for all players.
  Common encounters: Golden Gala (econ gold), Prismatic Party (loot), 2-cost/3-cost Start,
  Artifact Anvil (all players get Artifact Anvil at 3-3 - flex item builds),
  Cheaper Levels (-2 XP cost - enables fast leveling comps).
  KEY: Adapt comp direction to the active encounter. Artifact Anvil → flex carries.

GOD BLESSINGS (17.2 new): When aligned with a God 2+ times, choose between 2-3 Blessings:
  Ahri: Gold every turn / Divine Investment (max interest +1) / Chest of Greed (split gold pool)
  Kayle: Divine Refund (2g + component copy) / Craftsmanship (Reforgers) / Anvil Transformation
  Evelynn: Finalist Gambit (3g + 30g bonus for top-4 finish)
  Soraka: Soraka's Embrace (shield first ally that died last round each combat)
  Thresh: Mini Recombobulate (1-2 costs → higher cost) / Pandora's Seat (bench transforms each round)
  Varus: Ephemeral Rerolls (free reroll if shop empty) / Starcrossed Upgrade (next buy 2-starred) / Super Parting Gift
  KEY: Kayle Craftsmanship = best item value. Ahri Divine Investment = hard econ lead. Evelynn Finalist only if top-4 likely.

THE 9 GODS AND THEIR BOONS:
- Ahri (Opulence): 2 gold + 2 XP + 2 rerolls per round. Best for fast leveling.
- Aurelion Sol (Wonders): Choose trial quests for rewards. High skill cap.
- Ekko (Time): Anomaly item with role-based bonuses. Slow scaling.
- Evelynn (Temptation): +10% Durability but lose extra HP on loss. Risk/reward.
- Kayle (Order): Upgrade random completed item to Radiant. Pure item value.
- Soraka (Stars): +2 HP per missing tactician HP, +1 HP/round. Loss-streak insurance.
- Thresh (Pacts): Roll die after combat for random rewards. High variance.
- Varus (Love): +10 HP per total star level, +4% 5-cost odds. Fast-9 enabler.
- Yasuo (Abyss): Hex power +50% or 12g. Strong with Stargazer.

DOUBLE UP SPECIFIC RULES:
- You play WITH a partner. Combined boards determine win/loss.
- Send units to partner: 3rd copy they need for 3-star first, then off-comp 2-stars.
- Coordinate comps: ONE player frontline/tank heavy, ONE player carry focused.
- God alignment is PER PLAYER. Coordinate: one takes econ god, other takes item god.
- Partner coordination: "Send [unit] to partner" is valid advice.
- Win condition is your COMBINED boards. Partner's board matters as much as yours.

SET 17 TRAITS (key ones, 17.2 balance applied):
- Anima (2/4/6): Loss-streak trait. Tech per loss buffed (17.2). Anima Weapons at 100 Tech. 17.3: (6) gives loot after EVERY combat (was wins only) - significantly more consistent.
- Dark Star (2/4/6/9): Black holes execute below 10% HP. Jhin carry. Emblem AD/AP nerfed 25→18%.
- Mecha (2/4/6): Transform to Ultimate Form (+60% HP, 2 slots). (6) +1 team size.
- Meeple (3/5/7/10): Meeps empower abilities. (7) Cloning Slot. Gold per clone NERFED (1c:3→2g, 5c:5→2g).
- N.O.V.A. (2/3/5): Power surges. (5) Striker selector. Splash or vertical.
- Primordian (2/4/6): Swarmlings. (3+) free champ each round.
- Space Groove (2/4/6): Groove = AS + HP regen. (6) stacking AD/AP. Emblem reworked (no mana, +200 HP).
- Stargazer (2/4/6): REWORKED 17.3: HP regen + stacking stats per combat. Fountain removed. Yasuo hex synergy retained. Mountain HP buff kept.
- Replicator (2/4): Abilities fire twice at reduced effectiveness. Nami/Sona.
- Conduit (2/4): +20% mana from all sources. Mana regen.
- Timebreaker (2/3/4): REWORKED 17.2. (2) +15% AS team. (3) Free rerolls on loss. (4) +50% AS for Timebreakers.
- Voyager (2/4/6): Tanks get Shield, others get Damage Amp. Emblem omnivamp nerfed 18→10%.
- Marauder (2/4/6): Omnivamp + AD. NERFED 17.3: 20→18%, 40→35%, 60→55%. No longer top tank trait.

KEY CARRIES:
- Jhin (5g Dark Star): Primary AD carry, execute synergy, best with IE/LW/BT.
- Bard (5g Meeple): AP carry, UFO ability, abduction mechanic.
- Fiora (5g): Wins every 1v1 duel, heals 15% player damage. Stack AD.
- Sona (5g): AP carry, BUFFED 17.3. Conduit + Space Groove payoff.
- Lissandra (4g): AP carry, Frozen Tomb AoE, Replicator double-cast.
- Morgana (4g Magic Tank): Reclassed 17.3 from 5g. More accessible frontline for Redeemer/Conduit comps.
- Aurelion Sol (4g): AP damage carry, BUFFED 17.3. Wonders quest god synergy.
- Karma (4g): AP carry, BUFFED 17.3. Stargazer + Invoker.
- LeBlanc (3g Anima): Loss-streak carry, Anima Weapons payoff. Buffed 17.3.
- Jinx (3g): Switcheroo rockets, Space Groove + Gunslinger.
- Nami (2g): Replicator double-heal, sustain carry for Conduit comps.
- Corki/Rammus (3g/4g): Mecha carries, transform for power spike.

META S-TIER COMPS (17.3 - May 2026):
1. Meeple - Bard/Veigar carry, Cloning Slot at (7). Vertical still strong.
2. AP Vanguards - Lissandra carry, Vanguard 4 + Replicator 2. STRONGER in 17.3 (AP buffs).
3. Dark Star Jhin - Vertical Dark Star 6-9, execute carry. Consistent S tier.
4. Redeemer - Sona/Morgana carry, Conduit 4 + Space Groove. Morgana now 4g = more accessible.
5. Conduit Reroll - 3-star Nami, Conduit 4 + Replicator 2.
6. N.O.V.A. - Caitlyn/Akali carry, (5) Striker selector. Akali buffed.
7. Mecha - Corki/Rammus, transform units, (6) for +1 team size.
A TIER: Anima (LeBlanc, buffed 17.3 - every-combat loot) · Stargazer (Karma, reworked HP regen) · Rogue Reroll (Akali) · Space Opera (Jinx).
AVOID 17.3: Primordian comps (Apex Primordian gutted). Master Yi (omnivamp 15→10%). Marauder vertical (omnivamp nerfed).
17.3 NOTE: Timebreaker still viable flex AS trait. Anima now S-tier candidate with loot-every-combat buff.

DATA AVAILABILITY NOTE:
Stage/round (estimated from time), player level, items, win/loss record, and alive
player count are available. Gold and board units are NOT available from the API.
Never say specific gold amounts. Base econ advice on stage and level timing only.

BOARD ORIENTATION - CRITICAL:
- Row 4 = FRONTLINE (closest to enemy, engage first) - tanks/bruisers go here
- Row 1 = BACKLINE (closest to bench, safest) - ranged carries go here
- Row 2-3 = mid-board (supports, flex, melee carries)
- Col 1 = left, Col 7 = right

PLACEMENT RULES:
- Ranged carry (Jhin, Caitlyn, Jinx): Row 1 col 6-7
- Tanks/engage (Nasus, Poppy, Cho'Gath): Row 4 col 1-3
- Supports/enchanters (Nami, Sona): Row 2, adjacent to carry
- Mecha transformed: row 3-4 center (they take 2 slots)
- Anti-dive: move carry to col 1 if enemy has right-side engage

FEASIBILITY RULES:
- If round is GOD SELECTION (Realm of the Gods): advise which god offering AND any Blessing choice
- If round is PVE or ENCOUNTER: rolling OK but no PvP tips; flag encounter impact on comp direction
- NEVER suggest carousel picks - carousel does not exist in Set 17
- NEVER suggest Horizon Focus - removed from game in 17.3
- NEVER recommend Primordian vertical as a comp - Apex Primordian gutted in 17.3
- NEVER ask for more data - always coach with what you have
- NEVER use placeholder/blank/N/A in any field

CORE RULES:
1. Level 7 = 3-cost spike | Level 8 = 4-cost carries | Level 9 = 5-cost (stage 5+)
2. Board strength beats econ on loss streak (unless running Anima deliberately)
3. Items define comp - name real components
4. Mecha transforms consume 2 team slots - plan board space
5. In Double Up: always consider what to send partner

OUTPUT FORMAT - STRICT:
- Output ONLY the 9 fields below, nothing else
- NO markdown, NO bold, NO bullets, NO reasoning
- Each field: ONE concise line, max 20 words
- Action: 1-3 WORDS ALL-CAPS with spaces
- Board: ALWAYS include both FRONT and BACK
- NEVER use "placeholder", "blank", or "N/A"
- If rolldown is not applicable (god round), write "-"

Action: <1-3 WORDS ALL-CAPS>
Board: <FRONT: [tanks row 4] | BACK: [carry row 1, support row 2]>
Econ: <stage/level timing - no gold amounts>
Rolldown: <when/level trigger - "-" if god round>
Items: <real component names + holder>
God: <which god offering to pick and why, or current boon status>
Placement: <positioning note; for Double Up: which unit to send partner>
Upgrade: <pivot trigger - only levels feasible this stage>
Risk: <single specific threat>
"""

FIELD_MAP = {
    "action":    "action",
    "board":     "board",
    "econ":      "econ",
    "rolldown":  "rolldown",
    "items":     "items",
    "god":       "god",
    "placement": "placement",
    "upgrade":   "upgrade",
    "risk":      "risk",
}


def _build_prompt(state: dict) -> str:
    level     = state.get("level", 1)
    stage     = state.get("stage", 1)
    rnd       = state.get("round", 1)
    streak    = state.get("streak", 0)
    event     = state.get("round_event", "pvp")
    tempo     = state.get("tempo_note", "")
    kills     = state.get("kills", 0)
    deaths    = state.get("deaths", 0)
    alive     = state.get("alive_others", 7)
    dead      = state.get("dead_others", 0)
    items_str = state.get("items_str", "none")

    streak_str = (f"WIN+{streak}" if streak > 0
                  else f"LOSS{streak}" if streak < 0 else "NEUTRAL")

    # Determine round type
    from tft.tft_pbe_data import GOD_ROUNDS, PVE_ROUNDS, BOON_ROUND
    round_key = (stage, rnd)
    if round_key in GOD_ROUNDS:
        round_type = "REALM OF THE GODS"
    elif round_key == BOON_ROUND:
        round_type = "GOD BOON"
    elif round_key in PVE_ROUNDS:
        round_type = "PVE"
    else:
        round_type = "PVP"

    max_level_for_stage = {1: 3, 2: 4, 3: 5, 4: 7, 5: 8, 6: 9, 7: 9}.get(stage, 9)

    lines = [
        f"=== Stage {stage}-{rnd} | Level {level} | Round type: {round_type} ===",
        "MODE: DOUBLE UP (playing with partner)",
        f"Game time: {int(state.get('game_time_s', 0)//60)}:{int(state.get('game_time_s', 0)%60):02d}",
        f"Streak: {streak_str}  Rounds won/lost: {kills}/{deaths}",
        f"Players alive: {alive+1} of {state.get('total_players', 8)} ({dead} eliminated)",
        f"Board size: {level} units | Grid: Row 4=FRONTLINE, Row 1=BACKLINE, Col 1=left Col 7=right",
        f"Max feasible level this stage: {max_level_for_stage}",
    ]

    if round_type == "REALM OF THE GODS":
        lines.append("GOD SELECTION ROUND: Advise which god offering to pick based on comp direction and partner coordination.")
        lines.append("Do NOT suggest carousel picks or rolling - this is a god selection round.")
    elif round_type == "GOD BOON":
        lines.append("GOD BOON ROUND: Aligned god offers powerful armory. Evaluate options based on current board.")
    elif round_type == "PVE":
        lines.append("PVE ROUND: No opponent to position against - focus on econ/leveling decisions and partner coordination.")

    if tempo:
        lines.append(f"Milestone: {tempo}")

    # Always inject Double Up context
    lines += [
        "",
        "DOUBLE UP REMINDERS:",
        "- Coordinate with partner: one builds frontline, one builds carry",
        "- Send overflow units that fit partner's comp",
        "- God choices should complement partner's god selection",
        "- Combined board strength determines outcomes",
    ]

    # Load live comp data for targeted advice
    try:
        import json as _json
        from pathlib import Path as _Path
        _live = _json.loads((_Path(__file__).parent.parent / "data" / "tft_pbe_live_data.json").read_text())
        _comp = _live.get("comp", "") or ""
        if _comp:
            lines.append(f"Current comp: {_comp}")
    except Exception:
        pass

    lines += [
        "",
        f"Your items/augments: {items_str}",
    ]

    from tft.tft_pbe_data import TIER_ODDS
    next_lvl = level + 1
    if next_lvl <= 10:
        odds_now  = TIER_ODDS.get(level, {})
        odds_next = TIER_ODDS.get(next_lvl, {})
        lines += [
            "",
            f"Roll odds at Lv{level}: " +
                "  ".join(f"{c}c={v:.0%}" for c, v in odds_now.items() if v > 0),
            f"Roll odds at Lv{next_lvl}: " +
                "  ".join(f"{c}c={v:.0%}" for c, v in odds_next.items() if v > 0),
        ]

    return "\n".join(lines)


def _parse_response(text: str) -> dict:
    fields      = {}
    current_key = None
    current_val = []

    text = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', text)

    for line in text.strip().splitlines():
        s = line.strip()
        if not s:
            continue
        matched = False
        for prefix, key in FIELD_MAP.items():
            if s.lower().startswith(prefix + ":"):
                if current_key:
                    fields[current_key] = " ".join(current_val).strip()
                current_key = key
                current_val = [s[len(prefix)+1:].strip()]
                matched = True
                break
        if not matched and current_key:
            current_val.append(s)

    if current_key:
        fields[current_key] = " ".join(current_val).strip()

    _CUTOFF = ("---", "**context", "**reasoning", "context:",
               "reasoning:", "note:", "explanation:")
    _BANNED = ("placeholder", "<placeholder>", "[placeholder]",
               "blank", "n/a", "<none>", "[none]")
    for key, val in list(fields.items()):
        if not val:
            continue
        val = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', val)
        lower = val.lower()
        if lower.strip() in _BANNED:
            fields[key] = ""
            continue
        for marker in _CUTOFF:
            idx = lower.find(marker)
            if idx > 10:
                val = val[:idx].rstrip(" .-")
        if key != "items" and len(val) > 150:
            val = val[:147].rstrip() + "..."
        fields[key] = val.strip()

    if "action" in fields:
        fields["action"] = re.sub(r'[^A-Z0-9 /]', '',
                                   fields["action"].upper()).strip()

    return fields


class TftPbeCoachEngine:
    def __init__(self, data_file: Path, debug: bool = False) -> None:
        self._data_file   = data_file
        self._debug       = debug
        self._lock        = threading.Lock()
        self._last_call   = 0.0
        self._last_round  = (0, 0)
        self._last_fields: dict = {}

        api_key = (
            __import__("os").environ.get("ANTHROPIC_API_KEY", "") or
            self._read_key_file()
        )
        self._client = anthropic.Anthropic(api_key=api_key) if api_key else None

        cfg_path = Path(__file__).parent.parent / "config" / "coach_settings.json"
        self._model      = "claude-haiku-4-5-20251001"
        self._debounce_s = 15.0
        self._timeout    = 20
        self._max_tokens = 700
        if cfg_path.exists():
            try:
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                self._model      = cfg.get("model",            self._model)
                self._debounce_s = cfg.get("debounce_seconds", self._debounce_s)
                self._timeout    = cfg.get("timeout",          self._timeout)
                self._max_tokens = cfg.get("max_tokens",       self._max_tokens)
            except Exception:
                pass

        logger.info("TftPbeCoachEngine ready (model=%s debounce=%.0fs)",
                    self._model, self._debounce_s)

    def _read_key_file(self) -> str:
        for p in [Path(__file__).parent.parent / "API-Key-Claude.txt"]:
            if p.exists():
                k = p.read_text(encoding="utf-8").strip()
                if k.startswith("sk-ant-"):
                    return k
        return ""

    def submit(self, state: dict) -> None:
        if not self._client:
            return
        now       = time.time()
        sr        = (state.get("stage", 0), state.get("round", 0))
        hp        = state.get("health", 100)
        new_round = sr != self._last_round
        urgent    = hp <= 30

        if new_round or urgent:
            pass
        elif (now - self._last_call) < self._debounce_s:
            return

        self._last_round = sr
        self._last_call  = now
        threading.Thread(target=self._run_safe, args=(state,),
                         daemon=True, name="TftPbeCoach").start()

    def reset_state(self) -> None:
        self._last_round  = (0, 0)
        self._last_call   = 0.0
        self._last_fields = {}

    def shutdown(self) -> None:
        logger.info("TftPbeCoachEngine shutdown")

    def _run_safe(self, state: dict):
        if not self._lock.acquire(blocking=False):
            logger.debug("TFT PBE coach busy - skipping")
            return
        try:
            self._run(state)
        except Exception as exc:
            logger.error("TFT PBE coach error: %s", exc)
            self._write_status(f"Coach error: {str(exc)[:60]}")
        finally:
            self._lock.release()

    def _run(self, state: dict):
        t0     = time.time()
        prompt = _build_prompt(state)
        if self._debug:
            logger.debug("TFT PBE prompt:\n%s", prompt)

        response = self._client.messages.create(
            model      = self._model,
            max_tokens = self._max_tokens,
            system     = TFT_PBE_SYSTEM_PROMPT,
            messages   = [{"role": "user", "content": prompt}],
        )
        # AUDIT 2026-05-23 (cost-trace gap C): feed cost_tracker. POLLING
        # cadence (per game tick).
        try:
            from core.cost_tracker import record_anthropic_response
            record_anthropic_response(response, model=self._model, purpose="tft_pbe")
        except Exception as exc:
            logger.debug("cost_tracker record: %s", exc)
        latency = int((time.time() - t0) * 1000)
        raw     = response.content[0].text
        logger.info("TFT PBE coach response in %dms", latency)
        if self._debug:
            logger.debug("TFT PBE response:\n%s", raw)
        self._write_fields(raw, state)

    def _write_fields(self, raw: str, state: dict):
        fields = _parse_response(raw)
        if not fields:
            logger.warning("TFT PBE: no fields parsed from response")
            return

        _WATCH = ("action", "board", "econ", "rolldown", "items",
                  "god", "placement", "upgrade", "risk")
        if self._last_fields:
            changed = any(fields.get(k) != self._last_fields.get(k) for k in _WATCH)
            if not changed:
                logger.debug("TFT PBE: advice unchanged, skipping overlay write")
                return
        self._last_fields = dict(fields)

        output = {
            "mode":         "tft_pbe",
            "game_time_s":  state.get("game_time_s",  0),
            "stage":        state.get("stage",         1),
            "round":        state.get("round",         1),
            "level":        state.get("level",         1),
            "gold":         state.get("gold",          0),
            "health":       state.get("health",        100),
            "stage_round":  state.get("stage_round",   ""),
            "kills":        state.get("kills",         0),
            "deaths":       state.get("deaths",        0),
            "alive_others": state.get("alive_others",  7),
            "items_str":    state.get("items_str",     ""),
            "action":       fields.get("action",       ""),
            "board":        fields.get("board",        ""),
            "econ":         fields.get("econ",         ""),
            "rolldown":     fields.get("rolldown",     ""),
            "items":        fields.get("items",        ""),
            "god":          fields.get("god",          ""),
            "placement":    fields.get("placement",    ""),
            "upgrade":      fields.get("upgrade",      ""),
            "risk":         fields.get("risk",         ""),
        }

        try:
            tmp = self._data_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(output, indent=2), encoding="utf-8")
            tmp.replace(self._data_file)
            logger.debug("TFT PBE coaching data written (%d fields)", len(fields))
        except Exception as exc:
            logger.error("Failed to write TFT PBE coaching data: %s", exc)

    def _write_status(self, msg: str):
        # 2026-04-27 audit: atomic-write per CLAUDE.md hard rule - overlay
        # polls this file, raw write_text could expose mid-write content.
        try:
            payload = json.dumps({"mode": "tft_pbe", "action": "ERROR", "risk": msg}, indent=2)
            tmp = self._data_file.with_suffix(".tmp")
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(self._data_file)
        except Exception:
            pass
