"""s170 (2026-05-11) — DS enemy-stats heuristic for coach DS calls.

Before s170, all 4 coaches (`coach_integration/_coach.py` for SR,
`coaches/aram_coach.py`, `coaches/arena_coach.py`, `coaches/brawl_coach.py`)
hardcoded ``target_armor=80.0`` in their `daemon_slayer_client.rank_for`
call. That meant DS picks never reacted to game time or mode: a level-1
laning recommendation got the same target as a level-18 late-game one,
and ARAM/Arena/Brawl reused the SR mid-game anchor regardless of how
those modes' item economies actually progressed.

This module computes per-mode, level-aware aggregate enemy stats. Level
drives the curve (better than time because mid-game shutdowns / early
ganks shift the level lead independently of the clock). Each coach's
existing `_estimate_target_bonus_hp` item-aware estimator is preserved
via the `bonus_hp_override` kwarg — when items are visible (mid/late
SR or ARAM), the item-derived number is more accurate than the curve.

This is Tier 1: heuristic only. Tier 2 (later, scoped in ROADMAP) will
add FlatArmorMod/FlatSpellBlockMod caches to `core/daemon_slayer_resolver`
mirroring the existing FlatHPPoolMod cache, then per-coach
`_estimate_target_armor` / `_estimate_target_mr` helpers that walk
`state["enemies"][].items` the same way `_estimate_target_bonus_hp` does.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass(frozen=True)
class EnemyStats:
    """Aggregate enemy stats for a DS `rank_for` call.

    Field names mirror the DS server's `target_*` kwargs so coaches can
    `**stats.as_kwargs()`-style spread when the call ergonomics improve.
    """
    armor:    float
    mr:       float
    max_hp:   float
    bonus_hp: float


# Per-mode anchors. Each tuple is (armor_base, armor_per_level,
# mr_base, mr_per_level, hp_base, hp_per_level). Values calibrated to
# League's typical aggregate enemy stat lines at the mode's typical
# pace, NOT theoretical maximums — DS uses these as "good enough"
# rerank targets, not as a damage-prediction ground truth.
#
# SR: classic 5v5, gradual scaling. Armor anchors at lvl 11 → 95
# (matches the prior ``target_armor=80`` ballpark and the SR draft
# preset table at coaches/sr_draft_profile.py:71).
# ARAM: faster gold + healing reduction. Items come ~30% faster.
# Arena: 2v2v2v2, rounds compress build time. Higher armor at peak.
# Brawl: similar to SR but compressed teamfights.
_MODE_ANCHORS: dict[str, tuple[float, float, float, float, float, float]] = {
    "sr":    (40.0, 5.0,  30.0, 3.0,  1000.0, 110.0),
    "aram":  (50.0, 6.0,  35.0, 4.0,  1100.0, 120.0),
    "arena": (40.0, 8.0,  30.0, 6.0,  1100.0, 150.0),
    "brawl": (45.0, 5.0,  30.0, 3.5,  1100.0, 110.0),
}

# Caps prevent the heuristic from running away at very high levels or
# very long games. Drawn from real late-game enemy stat lines.
_ARMOR_CAP   = 220.0
_MR_CAP      = 160.0
_MAX_HP_CAP  = 4500.0
_BONUS_HP_FLOOR = 0.0
_BONUS_HP_CAP   = 3500.0

# Champion base HP averages ~600 (varies 540 Karthus → 690 Mundo).
# ``bonus_hp = max_hp - base_hp`` is the engine-relevant signal because
# items like Giant Slayer / Bork scale by bonus HP, not max.
_CHAMP_BASE_HP_AVG = 600.0


def _estimate_level_from_game_time(game_seconds: float) -> float:
    """Rough level estimate from game clock when no level signal exists.

    Standard SR XP curve: ~1 level per 90s of game time, plus a head
    start at minute 0 (everyone is level 1, not 0). Capped at 18 (max
    champion level). Used as a fallback only — when ``level`` is
    supplied explicitly we always prefer that.
    """
    if game_seconds <= 0:
        return 1.0
    est = 1.0 + (game_seconds / 90.0)
    if est > 18.0:
        return 18.0
    return est


def _normalize_mode(mode: str | None) -> str:
    m = (mode or "sr").lower().strip()
    if m in _MODE_ANCHORS:
        return m
    # Common aliases. The DS server accepts "SR" / "ARAM" / etc.
    # uppercased; the resolver and these anchors are lowercased.
    if m in ("classic", "summoners_rift", "summoners-rift"):
        return "sr"
    if m in ("aram_mayhem", "howling_abyss"):
        return "aram"
    if m in ("cherry", "2v2v2v2"):
        return "arena"
    return "sr"


def compute_enemy_stats(
    mode: str | None,
    game_seconds: float = 0.0,
    level: Optional[float] = None,
    *,
    bonus_hp_override: Optional[float] = None,
    enemy_levels: Optional[Iterable[float]] = None,
) -> EnemyStats:
    """Compute aggregate enemy stats for a DS `rank_for` call.

    Args:
        mode: ``"sr"`` / ``"aram"`` / ``"arena"`` / ``"brawl"`` or any
            uppercased / alias variant (auto-normalized).
        game_seconds: Game clock in seconds. Used as a fallback when
            ``level`` and ``enemy_levels`` are both None.
        level: Operator's current champion level. When supplied alongside
            no ``enemy_levels``, assumed roughly equal to average enemy
            level (true in laning, ±1 mid-game; off by 2-3 in stomps).
        bonus_hp_override: When set, replaces the heuristic-derived
            bonus_hp. Coaches' existing `_estimate_target_bonus_hp`
            (item-aware, walks enemy item displayNames) is more accurate
            when enemy items are visible — pass that result through here.
        enemy_levels: Per-enemy levels when known (e.g. parsed from
            Live Client `enemy_details`). When supplied, averaged into
            the effective level used for the curve. Overrides ``level``.

    Returns:
        EnemyStats with armor / mr / max_hp / bonus_hp filled. Always
        non-negative; caps applied to prevent runaway values.
    """
    mode_key = _normalize_mode(mode)
    armor_base, armor_per_lv, mr_base, mr_per_lv, hp_base, hp_per_lv = (
        _MODE_ANCHORS[mode_key]
    )

    if enemy_levels is not None:
        levels_list = [float(lv) for lv in enemy_levels if lv]
        if levels_list:
            avg_level = sum(levels_list) / len(levels_list)
        else:
            avg_level = float(level) if level is not None else _estimate_level_from_game_time(game_seconds)
    elif level is not None:
        avg_level = float(level)
    else:
        avg_level = _estimate_level_from_game_time(game_seconds)

    # Clamp to valid champion-level range.
    if avg_level < 1.0:
        avg_level = 1.0
    if avg_level > 18.0:
        avg_level = 18.0

    armor   = armor_base + armor_per_lv * avg_level
    mr      = mr_base + mr_per_lv * avg_level
    max_hp  = hp_base + hp_per_lv * avg_level

    # Apply caps.
    if armor > _ARMOR_CAP:
        armor = _ARMOR_CAP
    if mr > _MR_CAP:
        mr = _MR_CAP
    if max_hp > _MAX_HP_CAP:
        max_hp = _MAX_HP_CAP

    if bonus_hp_override is not None and bonus_hp_override > 0:
        bonus_hp = float(bonus_hp_override)
    else:
        bonus_hp = max_hp - _CHAMP_BASE_HP_AVG
    if bonus_hp < _BONUS_HP_FLOOR:
        bonus_hp = _BONUS_HP_FLOOR
    if bonus_hp > _BONUS_HP_CAP:
        bonus_hp = _BONUS_HP_CAP

    return EnemyStats(
        armor=round(armor, 1),
        mr=round(mr, 1),
        max_hp=round(max_hp, 1),
        bonus_hp=round(bonus_hp, 1),
    )
