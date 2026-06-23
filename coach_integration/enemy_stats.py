"""s170 (2026-05-11) - DS enemy-stats heuristic for coach DS calls.

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
via the `bonus_hp_override` kwarg - when items are visible (mid/late
SR or ARAM), the item-derived number is more accurate than the curve.

This is Tier 1: heuristic only. Tier 2 (later, scoped in ROADMAP) will
add FlatArmorMod/FlatSpellBlockMod caches to `core/daemon_slayer_resolver`
mirroring the existing FlatHPPoolMod cache, then per-coach
`_estimate_target_armor` / `_estimate_target_mr` helpers that walk
`state["enemies"][].items` the same way `_estimate_target_bonus_hp` does.
"""
from __future__ import annotations

import os
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
    # Enemy damage-type split (fractions in [0,1], summing ~1.0), derived
    # from the enemy comp when champion names are known. Feeds the
    # bruiser/tank EHP-side scorer's enemy_ad_share / enemy_ap_share so DS
    # recommends comp-appropriate resists (e.g. Wit's End vs an AP-heavy
    # comp). Default 0.5/0.5 = "no comp info" - preserves pre-2026-06-16
    # behavior for callers that pass no enemy_champions (dashboard preview
    # routes, champ-select). Appended at the END with defaults so existing
    # positional/keyword construction is unaffected.
    ad_share: float = 0.5
    ap_share: float = 0.5
    # DSV5 (P6-G5 residual: AP-DoT-vs-burst EHP-gating). Comp-conditioned
    # max-HP scaling: the flat mode/level curve is comp-BLIND, so DSV1's
    # ability-burn valuation (which scales with target_max_hp) fired at a
    # constant value regardless of the enemy comp's tankiness. A
    # rewind-WIN-anchored measurement (winning AP carries, by enemy tank
    # count) showed a clean preference flip: vs 0 tanks winners build burst
    # over DoT by -6.2pt, vs 2+ tanks they build DoT over burst by +12.0pt
    # (burst usage halves). ``hp_scale`` (default 1.0) records the applied
    # comp uplift/discount; ``tanky_count`` the tank/bruiser enemies seen.
    # Appended at the END with defaults so existing positional/keyword
    # construction is unaffected. Both inert until the default-OFF seam is
    # enabled (``comp_hp_lean`` / ``RC_COMP_HP_LEAN``).
    hp_scale: float = 1.0
    tanky_count: int = 0


# Per-mode anchors. Each tuple is (armor_base, armor_per_level,
# mr_base, mr_per_level, hp_base, hp_per_level). Values calibrated to
# League's typical aggregate enemy stat lines at the mode's typical
# pace, NOT theoretical maximums - DS uses these as "good enough"
# rerank targets, not as a damage-prediction ground truth.
#
# SR: classic 5v5, gradual scaling. Armor anchors at lvl 11 -> 95
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

# Champion base HP averages ~600 (varies 540 Karthus -> 690 Mundo).
# ``bonus_hp = max_hp - base_hp`` is the engine-relevant signal because
# items like Giant Slayer / Bork scale by bonus HP, not max.
_CHAMP_BASE_HP_AVG = 600.0

# DSV5 comp-conditioned max-HP seam (default-OFF). The flat curve above is an
# AVERAGE comp; a tank-heavy comp's median EHP is higher (-> DoT/%max-HP items
# gain) and an all-squishy comp's is lower. ``hp_scale = 1 + STEP*(tanky-1)``,
# clamped to [LO, HI]. Anchored to the rewind win-data: 1 frontline = neutral
# (the typical comp), each extra tank/bruiser +10%, all-squishy -10%. Tank set
# mirrors core.ds_antitank_hint (_TANKY_ARCHETYPES) so the RANKING tilt agrees
# with the existing anti-tank text hint (HIGH_HP_ENEMY_MIN == 2 -> scale 1.10).
_COMP_HP_STEP     = 0.10
_COMP_HP_SCALE_LO = 0.85
_COMP_HP_SCALE_HI = 1.30
_TANKY_ARCHETYPES = frozenset({"tank", "bruiser"})


def _env_comp_hp_lean() -> bool:
    """Read the ``RC_COMP_HP_LEAN`` live-flip gate (default OFF).

    The seam stays dormant (byte-identical to the pre-DSV5 flat curve) until
    the operator flips this env var. Documented in docs/LIVE_GAME_GATED_SYNC.md.
    """
    return os.environ.get("RC_COMP_HP_LEAN", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _count_tanky(enemy_champions: Optional[Iterable[str]]) -> int:
    """Count enemy tank/bruiser archetypes via the shared archetype registry.

    Reuses ``core.archetype_picks.get_archetype_for`` (the same classifier
    core.ds_antitank_hint uses). Fail-soft per champion: a blank id or a
    lookup miss is treated as non-tanky and never raises.
    """
    if not enemy_champions:
        return 0
    try:
        from core.archetype_picks import get_archetype_for
    except Exception:  # noqa: BLE001 - registry import is best-effort
        return 0
    count = 0
    for champ in enemy_champions:
        safe = (champ or "").strip()
        if not safe:
            continue
        try:
            info = get_archetype_for(safe)
            primary = info.get("primary", "") if isinstance(info, dict) else ""
            if primary in _TANKY_ARCHETYPES:
                count += 1
        except Exception:  # noqa: BLE001 - one bad id never breaks the count
            continue
    return count


def _comp_hp_scale(
    enemy_champions: Optional[Iterable[str]],
    comp_hp_lean: Optional[bool],
) -> tuple[float, int]:
    """Return ``(hp_scale, tanky_count)`` for the comp-conditioned seam.

    ``comp_hp_lean`` overrides the env gate when not None (tests pass it
    explicitly). OFF -> ``(1.0, tanky_count)`` so max_hp is byte-identical to
    the flat curve.

    NO-COMP-INFO GUARD: an absent / empty / all-blank ``enemy_champions`` is
    "no data", which is NOT the same as "an all-squishy comp". A known
    all-squishy comp (>=1 classifiable champ, 0 tanks) earns the intended 0.90
    discount, but a no-info call must stay neutral (1.0). Without this guard the
    seam computed ``1 + STEP*(0 - 1) = 0.90`` whenever it ran with no comp, so
    flipping ``RC_COMP_HP_LEAN`` ON would silently de-rate every champ-select /
    preview route (routes_state ds-preview Path 3, ds-knobs, ds-relscore,
    ds-statcheck all call ``compute_enemy_stats(mode, level)`` with no comp) by
    10%. Keeping no-info at the flat curve is the safety contract that lets the
    operator flip the seam ON without shifting any comp-blind ranking.
    """
    on = comp_hp_lean if comp_hp_lean is not None else _env_comp_hp_lean()
    tanky_count = _count_tanky(enemy_champions)
    if not on:
        return 1.0, tanky_count
    if not any((c or "").strip() for c in (enemy_champions or [])):
        # No classifiable comp -> neutral flat curve, never a blind discount.
        return 1.0, 0
    scale = 1.0 + _COMP_HP_STEP * (tanky_count - 1)
    scale = max(_COMP_HP_SCALE_LO, min(_COMP_HP_SCALE_HI, scale))
    return round(scale, 4), tanky_count


def _estimate_level_from_game_time(game_seconds: float) -> float:
    """Rough level estimate from game clock when no level signal exists.

    Standard SR XP curve: ~1 level per 90s of game time, plus a head
    start at minute 0 (everyone is level 1, not 0). Capped at 18 (max
    champion level). Used as a fallback only - when ``level`` is
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
    enemy_champions: Optional[Iterable[str]] = None,
    comp_hp_lean: Optional[bool] = None,
) -> EnemyStats:
    """Compute aggregate enemy stats for a DS `rank_for` call.

    Args:
        mode: ``"sr"`` / ``"aram"`` / ``"arena"`` / ``"brawl"`` or any
            uppercased / alias variant (auto-normalized).
        game_seconds: Game clock in seconds. Used as a fallback when
            ``level`` and ``enemy_levels`` are both None.
        level: Operator's current champion level. When supplied alongside
            no ``enemy_levels``, assumed roughly equal to average enemy
            level (true in laning, +/-1 mid-game; off by 2-3 in stomps).
        bonus_hp_override: When set, replaces the heuristic-derived
            bonus_hp. Coaches' existing `_estimate_target_bonus_hp`
            (item-aware, walks enemy item displayNames) is more accurate
            when enemy items are visible - pass that result through here.
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

    # DSV5 comp-conditioned max-HP (default-OFF seam). hp_scale == 1.0 leaves
    # max_hp byte-identical to the flat curve; a tank-heavy comp scales it up
    # so DSV1's ability-burn / %max-HP valuation tilts toward DoT vs tanks.
    hp_scale, tanky_count = _comp_hp_scale(enemy_champions, comp_hp_lean)
    max_hp *= hp_scale

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

    # Enemy damage-type split from the comp (the EHP-side signal). DDragon
    # info.attack/info.magic leans via core.aram_comp_verdict.compute_factors;
    # hybrids split evenly. No comp / unresolved / all-unknown -> 0.5/0.5.
    ad_share, ap_share = 0.5, 0.5
    if enemy_champions:
        try:
            from core.aram_comp_verdict import compute_factors
            f = compute_factors(list(enemy_champions))
            ad = float(f.get("ad_count", 0) or 0) + 0.5 * float(f.get("hybrid_count", 0) or 0)
            ap = float(f.get("ap_count", 0) or 0) + 0.5 * float(f.get("hybrid_count", 0) or 0)
            tot = ad + ap
            if tot > 0:
                ad_share = ad / tot
                ap_share = ap / tot
        except Exception:  # noqa: BLE001
            ad_share, ap_share = 0.5, 0.5

    return EnemyStats(
        armor=round(armor, 1),
        mr=round(mr, 1),
        max_hp=round(max_hp, 1),
        bonus_hp=round(bonus_hp, 1),
        ad_share=round(ad_share, 3),
        ap_share=round(ap_share, 3),
        hp_scale=hp_scale,
        tanky_count=tanky_count,
    )
