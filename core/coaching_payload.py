# arch: pydantic v2 schemas for per-mode coaching JSON payloads | section=core | frozen=no
"""Pydantic v2 models for data/{mode}_coaching_data.json.

Each model uses extra="allow" so new fields added by coaches never cause
validation failures — only declared fields are type-checked.
validate_coaching_payload() logs warnings for wrong-type fields but never
raises; coaches keep working even if the schema drifts.

Usage:
    from core.coaching_payload import validate_coaching_payload
    ok = validate_coaching_payload(data)   # logs warnings, returns bool
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, ValidationError

log = logging.getLogger("rc.coaching_payload")


class _Base(BaseModel):
    model_config = ConfigDict(extra="allow", validate_default=False)
    mode: str = ""
    action: str = ""


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


class TftPayload(_Base):
    board: str = ""
    econ: str = ""
    rolldown: str = ""
    items: str = ""
    god_pick: str = ""
    placement: str = ""
    upgrade: str = ""
    risk: str = ""
    game_time_s: float = 0.0
    stage: str = ""
    round: str = ""
    level: int = 1
    gold: int = 0
    health: int = 100


_MODE_TO_MODEL: dict[str, type[_Base]] = {
    "aram":   AramPayload,
    "arena":  ArenaPayload,
    "brawl":  BrawlPayload,
    "game":   SrPayload,
    "sr":     SrPayload,
    "client": SrPayload,
    "tft":    TftPayload,
}


def validate_coaching_payload(data: dict) -> bool:
    """Soft-validate a coaching payload dict against its mode schema.

    Logs a WARNING per field error; never raises. Returns True if valid.
    Called in build_state() and in unit tests (Phase 5 smoke harness).
    """
    if not isinstance(data, dict):
        log.warning("coaching_payload: expected dict, got %s", type(data).__name__)
        return False
    mode = data.get("mode", "")
    model_cls = _MODE_TO_MODEL.get(mode)
    if model_cls is None:
        # Unknown mode is not a hard error — idle/lobby states may omit mode.
        return True
    try:
        model_cls.model_validate(data)
        return True
    except ValidationError as exc:
        for err in exc.errors():
            loc = ".".join(str(x) for x in err["loc"])
            log.warning("coaching_payload [%s] %s: %s", mode, loc, err["msg"])
        return False
