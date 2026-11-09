# arch: pydantic v2 schemas for per-mode coaching JSON payloads | section=core | frozen=no
"""Pydantic v2 models for data/{mode}_coaching_data.json.

Each model uses extra="allow" so new fields added by coaches never cause
validation failures - only declared fields are type-checked.
validate_coaching_payload() logs warnings for wrong-type (and non-finite
float) fields but never raises; coaches keep working even if the schema
drifts. An unchanged error set is logged once, not on every build.

Usage:
    from core.coaching_payload import validate_coaching_payload
    ok = validate_coaching_payload(data)   # logs warnings, returns bool
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, ValidationError

log = logging.getLogger("rc.coaching_payload")


class _Base(BaseModel):
    # s144 true-audit F2: allow_inf_nan=False. Python's json reads NaN /
    # Infinity and json.dumps writes them back bare, which the browser's
    # JSON.parse rejects; a non-finite declared float is a field error.
    model_config = ConfigDict(extra="allow", validate_default=False,
                              allow_inf_nan=False)
    mode: str = ""
    action: str = ""
    # R65-A (L9/L10): declared on the shared base so every mode payload
    # type-checks the new championStats + stat-shard ingestion keys.
    combat_stats: dict[str, Any] = {}
    stat_shards: list[Any] = []


class AramPayload(_Base):
    champion: str = ""
    immediate: str = ""
    fight_rule: str = ""
    positioning: str = ""
    reset_item: str = ""
    objective: str = ""
    risk: str = ""
    game_time: str = ""
    game_time_s: float = 0.0
    hp_pct: float = 0.0
    kda: str = ""
    ally_spells: dict[str, Any] = {}
    items_display: str = ""
    game_mode: str = ""
    mayhem: bool = False
    my_team: str = ""
    item_build: str = ""
    item_extra: str = ""
    item_build_reasons: dict[str, Any] = {}
    my_tower_hp: int = 100
    enemy_tower_hp: int = 100
    wave_pct: int = 50
    hp_packs: list[Any] = []
    augments: str = ""
    level: int = 1
    gold: int = 0


class ArenaPayload(_Base):
    champion: str = ""
    fight_rule: str = ""
    round_strategy: str = ""
    augment_advice: str = ""
    anvil_advice: str = ""
    target_priority: str = ""
    risk: str = ""
    immediate: str = ""
    teams: list[Any] = []
    round: str = ""
    rank: str = ""
    alive_teams: int = 0
    hp_pct: float = 0.0
    wins: int = 0
    losses: int = 0
    game_time_s: float = 0.0
    camp_phase: bool = False
    item_build: str = ""
    ally_spells: dict[str, Any] = {}
    pregame: str = ""
    win_pct: Optional[float] = None
    kda: str = ""
    level: int = 1
    gold: int = 0
    daemon_slayer_picks: list[Any] = []


class BrawlPayload(_Base):
    champion: str = ""
    immediate: str = ""
    fight_rule: str = ""
    wave: str = ""
    reset_item: str = ""
    objective: str = ""
    risk: str = ""
    game_time_s: float = 0.0
    hp_pct: float = 0.0
    kda: str = ""
    gold: int = 0
    game_mode: str = ""
    ally_spells: dict[str, Any] = {}
    my_nexus_hp: int = 100
    enemy_nexus_hp: int = 100
    log: list[Any] = []
    win_pct: Optional[float] = None
    daemon_slayer_picks: list[Any] = []


class TeamContextEntry(_Base):
    """One slot in the 5+5 champ-select roster enrichment.

    Populated progressively by `core/riot_api.py` fan-out (FU02).
    Empty/zero values are the soft-fail signal - the dashboard renders
    skeleton rows until each field arrives.
    """
    puuid: str = ""
    summoner_name: str = ""        # blanked for ranked-pre-loading
    team_id: int = 0               # 100=blue, 200=red
    locked_champion: str = ""
    rank: str = ""                 # e.g. "PLATINUM IV 47 LP" or ""
    mastery_on_locked: int = 0
    w_l_streak_7: list[int] = [0, 0]   # [wins, losses] last 7 games
    mains: list[str] = []          # top-3 champion names
    win_rate_recent: float = 0.0


class TeamContext(_Base):
    allies: list[TeamContextEntry] = []
    enemies: list[TeamContextEntry] = []
    refreshed_at: str = ""         # ISO-8601 timestamp
    partial: bool = True           # False once priority-2 fan-out completes
    queue_id: int = 0              # 420 ranked solo, 440 flex, 400 normal draft, etc.


class SrPayload(_Base):
    """SR + client idle mode. Live fields are overlaid by state-builder."""
    immediate: str = ""
    next: str = ""
    fight_rule: str = ""
    wave: str = ""
    objective: str = ""
    reset_item: str = ""
    risk: str = ""
    map: str = ""
    win_pct: Optional[float] = None
    log: list[Any] = []
    pregame: str = ""
    champion: str = ""
    game_time_s: float = 0.0
    hp_pct: float = 0.0
    kda: str = ""
    gold: int = 0
    level: int = 1
    cs: int = 0
    ally_spells: dict[str, Any] = {}
    ally_comp: list[Any] = []
    enemy_comp: list[Any] = []
    team_context: Optional[TeamContext] = None


class TftPayload(_Base):
    """data/tft_coaching_data.json - the shape authority for every writer.

    RM-292 (d): ``stage`` / ``round`` are INTS, as the live producer emits
    them (tft/tft_state_reader.py ``_parse``) and tft/tft_coach_engine.py
    copies them through. They were declared ``str``, so every engine
    artifact failed its own schema and each /api/state build logged two
    WARNINGs (dashboard/_state_builder.py validates on every build).

    Defaults are what the blank seeds below write, so they are
    overlay-neutral: the state builder fills a coach key from the Live
    Client only while it is None / "" / 0, and a seeded ``level`` of 1 used
    to pin the dashboard's top-bar level. Defaults never affect validation
    (``validate_default=False``).

    S136 T11: ``level`` / ``gold`` / ``health`` are null when UNKNOWN (OCR
    silent, no per-round file of this game): the live engine wrote the
    reader's level 1 / gold 0 and a health of 100, and this blank wrote
    gold 0 / health 100, all painted as fact by the TFT overlay
    (web/js/lib/overlay_tft.js). A known 0 gold stays 0.
    """
    board: str = ""
    econ: str = ""
    rolldown: str = ""
    items: str = ""
    god_pick: str = ""
    placement: str = ""
    upgrade: str = ""
    risk: str = ""
    game_time_s: float = 0.0
    stage: int = 0
    round: int = 0
    level: Optional[int] = None
    gold: Optional[int] = None
    health: Optional[int] = None


# RM-292 (d): the advice strings every TFT artifact carries. The disabled
# placeholder (core/feature_policy.py), the degraded-status write and the
# facade seed (coaches/tft_coach.py) carry ONLY these plus mode / action:
# no numeric key, because a present 0 renders as "0:00" / level 0 on the
# dashboard whenever the Live Client summary is stale, while an ABSENT key
# lets the live value through.
TFT_ADVICE_FIELDS: tuple[str, ...] = (
    "board", "econ", "rolldown", "items",
    "god_pick", "placement", "upgrade", "risk",
)

# SR-family championStats keys on the shared base; no TFT writer emits them.
_SR_FAMILY_BASE_FIELDS = frozenset({"combat_stats", "stat_shards"})


def tft_advice_payload(**overrides: Any) -> dict:
    """mode, action and the advice strings at their TftPayload defaults.

    The disabled / degraded TFT shape. A NEW dict on every call, so a
    caller's overrides can never leak into another write."""
    seed = TftPayload(mode="tft")
    data: dict = {"mode": seed.mode, "action": seed.action}
    for name in TFT_ADVICE_FIELDS:
        data[name] = getattr(seed, name)
    data.update(overrides)
    return data


def tft_blank_payload(**overrides: Any) -> dict:
    """The whole declared TftPayload shape at its defaults - the blank
    artifact the live engine writes on reset. A NEW dict on every call."""
    data = TftPayload(mode="tft").model_dump(exclude=set(_SR_FAMILY_BASE_FIELDS))
    data.update(overrides)
    return data


_MODE_TO_MODEL: dict[str, type[_Base]] = {
    "aram":   AramPayload,
    "arena":  ArenaPayload,
    "brawl":  BrawlPayload,
    "game":   SrPayload,
    "sr":     SrPayload,
    "client": SrPayload,
    "tft":    TftPayload,
}


# s144 true-audit F3: at most this many per-field WARNING lines per call,
# then ONE summary line - a payload with 30 bad team_context rows used to
# log 30 lines on every /api/state build.
_MAX_FIELD_WARNINGS = 8

# s144 true-audit F4: build_state() validates on EVERY /api/state build
# (about every 0.5 s), so one stuck bad field re-logged the same WARNING
# twice a second for as long as the file held it. The last logged error
# set is remembered; an identical one logs at DEBUG only, a changed one
# logs again, and a valid payload (or an idle / unknown-mode one) clears
# the memo so a recurrence is visible. The key is (mode, field location,
# message): a new VALUE with the same error message is a repeat on
# purpose, since messages never carry the input. Guarded by a lock: the
# dashboard serves on threads.
_repeat_lock = threading.Lock()
_last_logged: Optional[tuple] = None


def _reset_repeat_memo() -> None:
    """Forget the last logged error set (tests; a fresh log after a fix)."""
    global _last_logged
    with _repeat_lock:
        _last_logged = None


def _is_repeat(signature: tuple) -> bool:
    """True if ``signature`` was the last one logged; else remember it."""
    global _last_logged
    with _repeat_lock:
        if signature == _last_logged:
            return True
        _last_logged = signature
        return False


def _report(signature: tuple, lines: list[str]) -> None:
    """Log ``lines`` as WARNINGs (capped), or one DEBUG line on a repeat."""
    if _is_repeat(signature):
        log.debug("coaching_payload: same %d error(s) as last build",
                  len(lines))
        return
    for line in lines[:_MAX_FIELD_WARNINGS]:
        log.warning("%s", line)
    extra = len(lines) - _MAX_FIELD_WARNINGS
    if extra > 0:
        log.warning("coaching_payload: %d more error(s) not shown", extra)


def validate_coaching_payload(data: dict) -> bool:
    """Soft-validate a coaching payload dict against its mode schema.

    Never raises on any payload shape. Returns True if valid, or if the
    mode is absent / None / an unknown string (idle and lobby states).
    A non-dict payload, a non-string ``mode`` (s144 F1: a list or dict
    mode used to raise TypeError out of build_state, so /api/state served
    500) and any field error return False. Field errors log one WARNING
    each, capped at ``_MAX_FIELD_WARNINGS`` plus a summary line; the same
    error set as the previous call logs at DEBUG only (see ``_report``).
    Called in build_state() and in unit tests (Phase 5 smoke harness).
    """
    if not isinstance(data, dict):
        name = type(data).__name__
        _report(("<non-dict>", name),
                [f"coaching_payload: expected dict, got {name}"])
        return False
    mode = data.get("mode", "")
    if mode is None:
        mode = ""
    if not isinstance(mode, str):
        name = type(mode).__name__
        _report(("<mode-type>", name),
                [f"coaching_payload: mode is {name}, expected str"])
        return False
    model_cls = _MODE_TO_MODEL.get(mode)
    if model_cls is None:
        # Unknown mode is not a hard error - idle/lobby states may omit mode.
        # Clears the memo too, so a bad field that comes back next game
        # warns again instead of once per process.
        _reset_repeat_memo()
        return True
    try:
        model_cls.model_validate(data)
    except ValidationError as exc:
        errors = [(".".join(str(x) for x in err["loc"]), str(err["msg"]))
                  for err in exc.errors()]
        _report((mode, tuple(errors)),
                [f"coaching_payload [{mode}] {loc}: {msg}"
                 for loc, msg in errors])
        return False
    _reset_repeat_memo()
    return True
