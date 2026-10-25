"""
tft/tft_pbe_engine.py

Challenger-level TFT coaching engine - Double Up focus (the PBE coach's twin
of tft/tft_coach_engine.py, reached only through coaches/tft_pbe_coach.py).
Analyses live game state and produces structured advice for all coaching panels.
Writes structured JSON to data/tft_pbe_coaching_data.json for the overlay.
The system prompt is built per resolved set by tft/tft_prompt.py (RM-845);
Realm of the Gods round labels apply only when the resolved set's meta
records that mechanic.
"""

import json
import logging
import re
import threading
import time
from pathlib import Path

import anthropic

from core import anthropic_key
from core.polled_json import atomic_write_text

logger = logging.getLogger("rc.tft.pbe")

# RM-845: this engine carried its own 9821-char hand-written Set 17 system
# prompt (patch 17.3 notes, god boon lists, a ranked meta comp list - tier
# claims no ingested data backed). It is retired: the system block is now
# tft/tft_prompt.py's per-set build, byte-identical to the live engine's, so
# the PBE coach can no longer drift onto a stale set on its own.


def _system_prompt() -> str:
    """The resolved set's system prompt (tft/tft_prompt.py; never raises)."""
    from tft import tft_prompt
    return tft_prompt.build_system_prompt()


def _set_has_gods() -> bool:
    """True only when the resolved set's meta records Realm of the Gods."""
    try:
        from tft import tft_prompt
        return tft_prompt.set_has_gods()
    except Exception:  # noqa: BLE001
        return False


def _round_labels(stage, rnd) -> dict:
    """RM-858: the round fields of the resolved set's schedule
    (tft/tft_state_reader.py round_schedule, RM-855) plus "gods_schedule",
    True only on the Set 17 Realm of the Gods schedule. {} when the schedule
    cannot be built, which labels every round PVP (never raises)."""
    try:
        from tft import tft_state_reader
        sched = tft_state_reader.round_schedule()
        out = sched.fields(stage, rnd)
        out["gods_schedule"] = sched.label == tft_state_reader.SCHEDULE_GODS
        return out
    except Exception:  # noqa: BLE001
        return {}


FIELD_MAP = {
    "action":    "action",
    "board":     "board",
    "econ":      "econ",
    "rolldown":  "rolldown",
    "items":     "items",
    "god":       "god",
    # RM-845: the shared prompt labels the pick field per set ("God pick",
    # "Carousel" or "Pick"); every label lands in this engine's "god" key.
    "god pick":  "god",
    "carousel":  "god",
    "pick":      "god",
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

    # Determine round type. RM-858: the labels come from the resolved set's
    # round schedule (RM-855 round_schedule): the Set 17 Realm of the Gods
    # tables in tft/tft_pbe_data.py only for Set 17 with that mechanic, and no
    # god, boon or PvE label for any other set (Set 18, an unknown set). The
    # PvE branch used to apply the Set 17 PvE table to every set.
    from tft.tft_pbe_data import BOON_ROUND
    gods = _set_has_gods()  # the reminder line below, not a round label
    rf = _round_labels(stage, rnd)
    if rf.get("is_god_round"):
        round_type = "REALM OF THE GODS"
    elif rf.get("gods_schedule") and (stage, rnd) == BOON_ROUND:
        round_type = "GOD BOON"
    elif rf.get("is_pve"):
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
    ]
    if gods:
        lines.append("- God choices should complement partner's god selection")
    lines += [
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
    except Exception:  # noqa: BLE001
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

        # ENV-APIKEY (s112): the ONE shared lookup (env first VALID, then the
        # repo-root key file), replacing a private `env or _read_key_file()`.
        api_key = anthropic_key.read_anthropic_key()
        self._client = anthropic.Anthropic(api_key=api_key, base_url="https://api.anthropic.com") if api_key else None

        cfg_path = Path(__file__).parent.parent / "config" / "coach_settings.json"
        self._model      = "claude-haiku-4-5-20251001"
        self._debounce_s = 15.0
        self._timeout    = 20
        self._max_tokens = 700
        if cfg_path.exists():
            try:
                self._apply_config(json.loads(cfg_path.read_text(encoding="utf-8")))
            except (OSError, ValueError) as exc:
                # ValueError covers json.JSONDecodeError and the
                # UnicodeDecodeError raised by a non-UTF-8 settings file.
                # Fail soft on the DEFAULTS, but never silently: this used to
                # be a bare `except Exception: pass`, so an unreadable or
                # malformed coach_settings.json was indistinguishable from an
                # absent one.
                logger.warning("coach_settings.json unusable (%s) - using defaults", exc)

        logger.info("TftPbeCoachEngine ready (model=%s debounce=%.0fs)",
                    self._model, self._debounce_s)

    def _apply_config(self, cfg: dict) -> None:
        """Adopt coach_settings.json values, rejecting anything unusable.

        RM-286 (lane 8): these were adopted verbatim, so a string
        `debounce_seconds` made `(now - self._last_call) < self._debounce_s`
        at submit() raise TypeError into the TFT PBE poll loop, and a
        non-positive `max_tokens` or `timeout` is refused by the API on every
        call. A bad config value now degrades to the default, loudly.

        Mirrors tft/tft_coach_engine.py `_apply_config` (the live twin, fixed
        in cycle 30) - keep the two contracts identical.
        """
        if not isinstance(cfg, dict):
            logger.warning("coach_settings.json is not an object, using defaults")
            return

        def _num(key, current, *, minimum, maximum, cast):
            if key not in cfg:
                return current
            val = cfg[key]
            # bool first: bool subclasses int, so `True` would pass isinstance
            # and silently configure a 1-second timeout.
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                logger.warning("coach_settings.%s must be a number, got %r - keeping %r",
                               key, val, current)
                return current
            if not (minimum <= val <= maximum):
                logger.warning("coach_settings.%s out of range [%s, %s], got %r - keeping %r",
                               key, minimum, maximum, val, current)
                return current
            return cast(val)

        model = cfg.get("model", self._model)
        if isinstance(model, str) and model.strip():
            self._model = model
        elif "model" in cfg:
            logger.warning("coach_settings.model must be a non-empty string, got %r - keeping %r",
                           model, self._model)

        self._debounce_s = _num("debounce_seconds", self._debounce_s,
                                minimum=0, maximum=3600, cast=float)
        self._timeout    = _num("timeout", self._timeout,
                                minimum=1, maximum=600, cast=float)
        self._max_tokens = _num("max_tokens", self._max_tokens,
                                minimum=1, maximum=8192, cast=int)

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
        except Exception as exc:  # noqa: BLE001
            # HARD RULE: never surface a raw API/exception string in a
            # user-facing panel. risk is rendered by tft_pbe_coach
            # (coaches/tft_pbe_coach.py renders the risk field), so the raw
            # str(exc) - which can carry a credit/balance/400/rate-limit body -
            # must stay in the log only. Degrade to a friendly message.
            # Mirrors tft_coach_engine._run_safe (sibling, already fixed).
            logger.error("TFT PBE coach error: %s", exc)
            self._write_status("Coaching paused - retrying")
        finally:
            self._lock.release()

    def _run(self, state: dict):
        # Spend-gate: TFT Anthropic calls off via Settings kill-switch.
        try:
            from core.cost_tracker import get_tracker as _gt
            if _gt().gate_disabled("tft"):
                return
        except Exception:  # noqa: BLE001
            pass
        t0     = time.time()
        prompt = _build_prompt(state)
        if self._debug:
            logger.debug("TFT PBE prompt:\n%s", prompt)

        response = self._client.messages.create(
            model      = self._model,
            max_tokens = self._max_tokens,
            # RM-286: without this the call inherits the SDK default (600s)
            # while _run_safe holds self._lock, so every later submit logs
            # "busy - skipping" for as long as it hangs.
            timeout    = self._timeout,
            system     = [{"type": "text", "text": _system_prompt(),
                           "cache_control": {"type": "ephemeral"}}],
            messages   = [{"role": "user", "content": prompt}],
        )
        # AUDIT 2026-05-23 (cost-trace gap C): feed cost_tracker. POLLING
        # cadence (per game tick).
        try:
            from core.cost_tracker import record_anthropic_response
            record_anthropic_response(response, model=self._model, purpose="tft_pbe")
        except Exception as exc:  # noqa: BLE001
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
            atomic_write_text(self._data_file, json.dumps(output, indent=2))
            logger.debug("TFT PBE coaching data written (%d fields)", len(fields))
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to write TFT PBE coaching data: %s", exc)

    def _write_status(self, msg: str):
        # 2026-04-27 audit: atomic-write per CLAUDE.md hard rule - overlay
        # polls this file, raw write_text could expose mid-write content.
        try:
            payload = json.dumps({"mode": "tft_pbe", "action": "ERROR", "risk": msg}, indent=2)
            atomic_write_text(self._data_file, payload)
        except Exception as exc:  # noqa: BLE001
            # RM-316: was a bare `pass`, so a failure to say "coaching paused"
            # left the previous round's advice on screen with no record why.
            # Stays fail-soft: this runs inside _run_safe's handler.
            logger.warning("Failed to write TFT PBE status %r: %s", msg, exc)
