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

import logging
import math
import numbers
import os
from dataclasses import dataclass
from typing import Iterable, Optional

logger = logging.getLogger(__name__)


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
# preset table `_FALLBACK_PRESETS` in coaches/sr_draft_profile.py).
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


def _finite_number(value: object) -> Optional[float]:
    """Return ``value`` as a finite float, or None for anything else.

    One reader for every numeric input (level, clock, enemy levels, the
    bonus_hp override, the comp factor counts). A real number or a numeric
    string is accepted (the pre-hardening ``float(level)`` accepted ``"11"``);
    a bool, NaN, inf, an int too large for a float and any other type is
    junk. Never raises.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, numbers.Real):
        try:
            out = float(value)
        except (OverflowError, ValueError):
            return None
    elif isinstance(value, str):
        try:
            out = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    return out if math.isfinite(out) else None


def _comp_names(enemy_champions: object) -> list[str]:
    """Materialize the enemy comp ONCE as stripped champion names.

    A one-shot iterable (a generator) is read a single time here, so the tank
    count, the no-comp guard and the AD/AP split all see the same comp. A bare
    string is one name, never its letters. Non-str entries and blanks are
    dropped; a non-iterable comp reads as empty. The ``"?"`` placeholder live
    callers write for a missing ``championName`` is kept here and simply never
    resolves (``_resolved_count``), like any other unknown name.
    """
    if enemy_champions is None:
        return []
    if isinstance(enemy_champions, str):
        items: list = [enemy_champions]
    else:
        try:
            items = list(enemy_champions)  # type: ignore[call-overload]
        except TypeError:
            return []
    names: list[str] = []
    for champ in items:
        if not isinstance(champ, str):
            continue
        safe = champ.strip()
        if safe:
            names.append(safe)
    return names


def _comp_factors(names: list[str]) -> Optional[dict]:
    """``core.aram_comp_verdict.compute_factors`` over ``names``, or None.

    Best-effort: the DDragon-backed lookup failing (import, data, a non-dict
    result) is "no comp info", logged at debug, never raised into the coach.
    """
    if not names:
        return None
    try:
        from core.aram_comp_verdict import compute_factors
        factors = compute_factors(list(names))
    except Exception as exc:  # noqa: BLE001 - comp lookup is best-effort
        logger.debug("enemy_stats: compute_factors failed: %r", exc)
        return None
    return factors if isinstance(factors, dict) else None


def _count_tanky(names: list[str]) -> int:
    """Count enemy tank/bruiser archetypes via the shared archetype registry.

    Reuses ``core.archetype_picks.get_archetype_for`` (the same classifier
    core.ds_antitank_hint uses). Fail-soft per champion: a lookup miss or
    error is treated as non-tanky and never raises.
    """
    if not names:
        return 0
    try:
        from core.archetype_picks import get_archetype_for
    except Exception as exc:  # noqa: BLE001 - registry import is best-effort
        logger.debug("enemy_stats: archetype registry import failed: %r", exc)
        return 0
    count = 0
    for champ in names:
        try:
            info = get_archetype_for(champ)
        except Exception as exc:  # noqa: BLE001 - one bad id never breaks the count
            logger.debug("enemy_stats: archetype lookup %r failed: %r", champ, exc)
            continue
        primary = info.get("primary", "") if isinstance(info, dict) else ""
        if primary in _TANKY_ARCHETYPES:
            count += 1
    return count


def _resolved_count(factors: Optional[dict]) -> int:
    """How many comp names DDragon resolved (``compute_factors``'s ``n``)."""
    if factors is None:
        return 0
    n = _finite_number(factors.get("n"))
    return int(n) if n is not None and n > 0 else 0


def _comp_hp_scale(
    names: list[str],
    resolved: int,
    comp_hp_lean: Optional[bool],
) -> tuple[float, int]:
    """Return ``(hp_scale, tanky_count)`` for the comp-conditioned seam.

    ``comp_hp_lean`` overrides the env gate when not None (tests pass it
    explicitly). OFF -> ``(1.0, tanky_count)`` so max_hp is byte-identical to
    the flat curve.

    NO-COMP-INFO GUARD: an absent / empty / all-blank comp is "no data", which
    is NOT the same as "an all-squishy comp". A known all-squishy comp (>=1
    champion DDragon resolves, 0 tanks) earns the intended 0.90 discount, but a
    no-info call must stay neutral (1.0). Without this guard the seam computed
    ``1 + STEP*(0 - 1) = 0.90`` whenever it ran with no comp, so flipping
    ``RC_COMP_HP_LEAN`` ON would silently de-rate every champ-select / preview
    route (routes_state ds-preview Path 3, ds-knobs, ds-relscore, ds-statcheck
    all call ``compute_enemy_stats(mode, level)`` with no comp) by 10%. Keeping
    no-info at the flat curve is the safety contract that lets the operator
    flip the seam ON without shifting any comp-blind ranking. "No info" also
    covers a comp of only ``"?"`` placeholders or only names DDragon cannot
    resolve (``resolved == 0``): before the s144 true-audit both read as a
    known all-squishy comp and earned the blind discount.
    """
    on = comp_hp_lean if comp_hp_lean is not None else _env_comp_hp_lean()
    tanky_count = _count_tanky(names)
    if not on:
        return 1.0, tanky_count
    if resolved <= 0:
        # No classifiable comp -> neutral flat curve, never a blind discount.
        return 1.0, 0
    scale = 1.0 + _COMP_HP_STEP * (tanky_count - 1)
    scale = max(_COMP_HP_SCALE_LO, min(_COMP_HP_SCALE_HI, scale))
    return round(scale, 4), tanky_count


def _ad_ap_share(factors: Optional[dict]) -> tuple[float, float]:
    """Enemy (ad_share, ap_share) from the comp factors; hybrids split evenly.

    No comp, an all-unknown comp, or a junk / negative count -> 0.5 / 0.5, so
    the pair is always a split in [0, 1] that sums to 1.
    """
    if factors is None:
        return 0.5, 0.5
    counts = []
    for key in ("ad_count", "ap_count", "hybrid_count"):
        raw = factors.get(key, 0)
        val = _finite_number(0 if raw is None else raw)
        if val is None or val < 0:
            return 0.5, 0.5
        counts.append(val)
    ad_n, ap_n, hybrid_n = counts
    ad = ad_n + 0.5 * hybrid_n
    ap = ap_n + 0.5 * hybrid_n
    tot = ad + ap
    if tot <= 0:
        return 0.5, 0.5
    return ad / tot, ap / tot


def _estimate_level_from_game_time(game_seconds: object) -> float:
    """Rough level estimate from game clock when no level signal exists.

    Standard SR XP curve: ~1 level per 90s of game time, plus a head
    start at minute 0 (everyone is level 1, not 0). Capped at 18 (max
    champion level). Used as a fallback only - when ``level`` is
    supplied explicitly we always prefer that. A junk clock (None, NaN,
    inf, a non-number) reads as level 1, never NaN and never a raise.
    """
    secs = _finite_number(game_seconds)
    if secs is None or secs <= 0:
        return 1.0
    est = 1.0 + (secs / 90.0)
    if est > 18.0:
        return 18.0
    return est


def _enemy_level_list(enemy_levels: object) -> list[float]:
    """Usable per-enemy levels: finite numbers > 0, each clamped to [1, 18].

    Zero is the Live Client placeholder and is dropped (pre-hardening
    behaviour); so are negatives, NaN / inf, bools and non-numbers. A str,
    bytes or a non-iterable reads as no levels.
    """
    if enemy_levels is None or isinstance(enemy_levels, (str, bytes)):
        return []
    try:
        items = list(enemy_levels)  # type: ignore[call-overload]
    except TypeError:
        return []
    out: list[float] = []
    for raw in items:
        lv = _finite_number(raw)
        if lv is None or lv <= 0:
            continue
        out.append(max(1.0, min(lv, 18.0)))
    return out


def _normalize_mode(mode: object) -> str:
    if not isinstance(mode, str):
        return "sr"
    m = mode.lower().strip()
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
            uppercased / alias variant (auto-normalized). A non-str reads
            as ``"sr"``.
        game_seconds: Game clock in seconds. Used as a fallback when
            ``level`` and ``enemy_levels`` are both None (or junk).
        level: Operator's current champion level. When supplied alongside
            no ``enemy_levels``, assumed roughly equal to average enemy
            level (true in laning, +/-1 mid-game; off by 2-3 in stomps).
        bonus_hp_override: When set, replaces the heuristic-derived
            bonus_hp. Coaches' existing `_estimate_target_bonus_hp`
            (item-aware, walks enemy item displayNames) is more accurate
            when enemy items are visible - pass that result through here.
            Zero, negative or junk falls back to the heuristic.
        enemy_levels: Per-enemy levels when known (e.g. parsed from
            Live Client `enemy_details`). When supplied, averaged into
            the effective level used for the curve. Overrides ``level``.
        enemy_champions: Enemy champion names. Feeds the AD/AP split and
            the default-OFF comp max-HP seam. Read once (a generator is
            fine); a bare string is one name; non-str entries and blanks
            are ignored, and an unresolvable name (incl. the ``"?"``
            placeholder) counts as no comp info.
        comp_hp_lean: Overrides the ``RC_COMP_HP_LEAN`` env gate when not
            None.

    Returns:
        EnemyStats with armor / mr / max_hp / bonus_hp filled. Always
        finite and non-negative; caps applied to prevent runaway values.
        Junk input never raises: each junk field falls back to the next
        signal (enemy levels -> level -> clock -> level 1).
    """
    mode_key = _normalize_mode(mode)
    armor_base, armor_per_lv, mr_base, mr_per_lv, hp_base, hp_per_lv = (
        _MODE_ANCHORS[mode_key]
    )

    levels_list = _enemy_level_list(enemy_levels)
    if levels_list:
        avg_level = sum(levels_list) / len(levels_list)
    else:
        own_level = _finite_number(level)
        if own_level is not None:
            avg_level = own_level
        else:
            avg_level = _estimate_level_from_game_time(game_seconds)

    # Clamp to valid champion-level range.
    avg_level = max(avg_level, 1.0)
    avg_level = min(avg_level, 18.0)

    armor   = armor_base + armor_per_lv * avg_level
    mr      = mr_base + mr_per_lv * avg_level
    max_hp  = hp_base + hp_per_lv * avg_level

    # The comp is materialized once and the DDragon factors computed once,
    # so the tank count, the no-info guard and the AD/AP split agree.
    names = _comp_names(enemy_champions)
    factors = _comp_factors(names)

    # DSV5 comp-conditioned max-HP (default-OFF seam). hp_scale == 1.0 leaves
    # max_hp byte-identical to the flat curve; a tank-heavy comp scales it up
    # so DSV1's ability-burn / %max-HP valuation tilts toward DoT vs tanks.
    hp_scale, tanky_count = _comp_hp_scale(
        names, _resolved_count(factors), comp_hp_lean,
    )
    max_hp *= hp_scale

    # Apply caps.
    armor = min(armor, _ARMOR_CAP)
    mr = min(mr, _MR_CAP)
    max_hp = min(max_hp, _MAX_HP_CAP)

    override = _finite_number(bonus_hp_override)
    if override is not None and override > 0:
        bonus_hp = override
    else:
        bonus_hp = max_hp - _CHAMP_BASE_HP_AVG
    bonus_hp = max(bonus_hp, _BONUS_HP_FLOOR)
    bonus_hp = min(bonus_hp, _BONUS_HP_CAP)

    # Enemy damage-type split from the comp (the EHP-side signal). DDragon
    # info.attack/info.magic leans via core.aram_comp_verdict.compute_factors;
    # hybrids split evenly. No comp / unresolved / all-unknown -> 0.5/0.5.
    ad_share, ap_share = _ad_ap_share(factors)

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
