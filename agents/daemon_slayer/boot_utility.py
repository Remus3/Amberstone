"""Comp-conditioned per-boot utility scorer (DEFAULT-OFF assume_boot_utility seam).

Pure + self-contained: no engine imports, no I/O. Consumed by
core.build_order._select_boots only on the ON path; OFF stays byte-identical.

Model (two clean cases):
  * OFFENSIVE archetypes (marksman/mage/assassin/enchanter/...) have a kit boot
    prior (Berserker's / Sorcerer's / Ionian) worth ``_KIT``. A defensive boot
    only overrides it when the enemy comp is lopsided enough to beat the prior
    by ``_SWITCH_MARGIN`` - so a carry keeps its DPS boot in a balanced comp and
    takes Mercury's only into heavy AP + CC.
  * DEFENSIVE archetypes (tank/ehp/bruiser/hybrid) have NO kit prior; their boot
    is chosen among the defensive boots by enemy DAMAGE TYPE - Steelcaps vs AD,
    Mercury's vs AP - with a small incumbency (``_INCUMBENT_DEF``) so a neutral
    comp holds the archetype default (Steelcaps).

Each boot carries a NORMALIZED utility vector; the comp supplies per-axis
weights; the boot's score is the dot product (plus the defensive incumbency).
All weights + the margin are conservative operator-tunable starters (the seam is
DEFAULT-OFF pending a live flip), in the spirit of hybrid.py
_MS_UTILITY_DPS_FRACTION. See docs/specs/2026-07-09-boot-utility-scorer-design.md.

Boot ids are 16.13.1 DDragon tier-2 forms (Arena 22-prefix mirror is applied by
the caller AFTER selection). Symbiotic Soles 3010 is rune-granted (not
shop-buyable) so it is scored but NOT in SELECTABLE_TIER2.
"""
from __future__ import annotations

import math
from typing import Iterable

# Tier-2 boot ids.
BERSERKERS = "3006"   # attack speed
SWIFTNESS = "3009"    # move speed + slow-resist
SYMBIOTIC = "3010"    # move speed (rune-granted; scored, not selectable)
SORCERERS = "3020"    # magic pen
STEELCAPS = "3047"    # armor + R80 AA-damage-reduction
MERCURYS = "3111"     # magic resist + 30% tenacity
IONIAN = "3158"       # ability haste + summoner haste

# Directly-purchasable tier-2 boots the ON path may select (excludes the
# rune-only Symbiotic 3010 so the scorer never recommends an unbuyable boot).
SELECTABLE_TIER2: tuple[str, ...] = (
    BERSERKERS, SWIFTNESS, SORCERERS, STEELCAPS, MERCURYS, IONIAN,
)

# Defensive boots: their value comes from the enemy damage type, and the one
# that is a champ's archetype default earns the incumbency stickiness below.
_DEFENSIVE_BOOTS: frozenset[str] = frozenset({STEELCAPS, MERCURYS})

# Per-boot normalized utility vector, seeded from the 16.13.1 stat profile
# (cross-checked vs _item_tenacity.py, _item_ability_haste.py, and the R80
# AA-damage-reduction registry).
BOOT_UTILITY_PROFILE: dict[str, dict[str, float]] = {
    BERSERKERS: {"as_dps": 1.0},
    SWIFTNESS:  {"move_speed": 1.0},
    SYMBIOTIC:  {"move_speed": 0.7},
    SORCERERS:  {"magic_pen": 1.0},
    STEELCAPS:  {"armor_survival": 1.0},
    MERCURYS:   {"mr_survival": 1.0, "tenacity": 1.0},
    IONIAN:     {"ability_haste": 1.0},
}

# OFFENSIVE archetypes only -> their kit boot axis. Defensive archetypes
# (tank/ehp/bruiser/hybrid) are intentionally ABSENT so they carry no offensive
# prior; their boot is chosen among the defensive boots by enemy damage type.
_ARCHETYPE_AXIS: dict[str, str] = {
    "carry": "as_dps", "marksman": "as_dps", "adc": "as_dps", "dps": "as_dps",
    "mage": "magic_pen", "burst": "magic_pen",
    "assassin": "ability_haste", "enchanter": "ability_haste",
    "hps": "ability_haste", "ability": "ability_haste", "support": "ability_haste",
}

# Tunable starters. The seam is DEFAULT-OFF, so the bar to override a champ's
# kit boot is deliberately high.
_KIT = 1.0             # an offensive champ's own kit boot value (the prior)
_DEF = 1.0             # enemy AD/AP share -> armor/MR survival value
_TEN = 0.5             # tenacity value, scaled by the CC proxy
_MS = 0.35             # standing move-speed value (needs a poke/kite signal to win - v1 follow-up)
_INCUMBENT_DEF = 0.3   # stickiness for a DEFENSIVE archetype's default boot (holds a neutral comp)
# A challenger must beat the archetype default by this RELATIVE margin to win.
_SWITCH_MARGIN = 0.15


def _unit_share(value: float) -> float:
    """A share / proxy as a float clamped to [0,1] (s144 S144-T-683 F2).

    An in-range value comes back as exactly ``float(value)``, so every caller
    that already passed a fraction is byte-identical. Out of range is clamped
    (a percent such as 70 reads as 1.0, not 70x the kit prior; +inf -> 1.0,
    -inf -> 0.0) and nan reads as 0.0 - no signal - instead of making every
    weight nan. A non-numeric value still raises from ``float()``.
    """
    x = float(value)
    if math.isnan(x):
        return 0.0
    return max(0.0, min(1.0, x))


def comp_weights(
    archetype: str,
    enemy_ad_share: float,
    enemy_ap_share: float,
    cc_proxy: float,
) -> dict[str, float]:
    """Per-axis weights for a comp. Shares and cc_proxy are fractions in [0,1];
    out-of-range or nan values are clamped by :func:`_unit_share`.

    A blank / None / whitespace archetype reads as ``"carry"``, matching
    ``core.build_order._select_boots``; a non-string archetype is a TypeError.
    """
    if archetype is not None and not isinstance(archetype, str):
        raise TypeError(
            f"comp_weights: archetype must be a str or None, got {type(archetype).__name__}"
        )
    weights: dict[str, float] = {
        "armor_survival": _DEF * _unit_share(enemy_ad_share),
        "mr_survival": _DEF * _unit_share(enemy_ap_share),
        "tenacity": _TEN * _unit_share(cc_proxy),
        "move_speed": _MS,
    }
    arch = (archetype or "").strip().lower() or "carry"
    kit_axis = _ARCHETYPE_AXIS.get(arch)
    if kit_axis:
        weights[kit_axis] = weights.get(kit_axis, 0.0) + _KIT
    return weights


def score_boot(boot_id: str, weights: dict[str, float]) -> float:
    """Dot product of the boot's utility vector with the comp weights. 0.0 if unknown.

    Walks the BOOT's own axes (s144 S144-T-683 F1): walking the weights made a
    non-finite weight on an axis the boot does not carry poison it anyway
    (0.0 * inf is nan). A non-finite weight on the boot's own axis contributes
    0.0. For finite weights the nonzero terms are summed in the same order, so
    the score is byte-identical.
    """
    profile = BOOT_UTILITY_PROFILE.get(str(boot_id), {})
    total = 0.0
    for axis, utility in profile.items():
        w = weights.get(axis, 0.0)
        if not math.isfinite(w):
            continue
        total += utility * w
    return total


def _require_pool_like(value: object, name: str) -> None:
    """A bare str / bytes is iterated per CHARACTER - refuse it by name (F5)."""
    if isinstance(value, (str, bytes, bytearray)):
        raise TypeError(
            f"{name} must be an iterable of ids / names, not a bare {type(value).__name__}"
        )


def select_boot(
    pool: Iterable[str],
    weights: dict[str, float],
    default_id: str,
    switch_margin: float = _SWITCH_MARGIN,
) -> str:
    """Argmax boot over pool, but the challenger must beat the archetype default
    by switch_margin. A DEFENSIVE archetype's default boot earns an incumbency
    bonus so a neutral comp holds it. Fail-soft: an empty pool returns default_id.

    ``switch_margin`` must be finite and >= 0 (ValueError otherwise); ``pool``
    must not be a bare string (TypeError). The bar is the default's score plus
    ``|default| * switch_margin``, so a NEGATIVE default score keeps its
    hysteresis (s144 S144-T-683 F4); for a non-negative default the comparison
    is the original ``default * (1 + margin)`` expression, byte-identical.
    """
    _require_pool_like(pool, "select_boot: pool")
    margin = float(switch_margin)
    if not math.isfinite(margin) or margin < 0.0:
        raise ValueError(
            f"select_boot: switch_margin must be finite and >= 0, got {switch_margin!r}"
        )
    ids = [str(b) for b in pool]
    did = str(default_id)
    if not ids:
        return did

    def _eff(boot_id: str) -> float:
        s = score_boot(boot_id, weights)
        if boot_id == did and boot_id in _DEFENSIVE_BOOTS:
            s += _INCUMBENT_DEF
        return s

    default_score = _eff(did)
    if default_score >= 0.0:
        bar = default_score * (1.0 + margin)
    else:
        bar = default_score - default_score * margin
    challenger = max(ids, key=_eff)
    if challenger != did and _eff(challenger) > bar:
        return challenger
    return did


# --- v2 CC input (A-39) ----------------------------------------------------
# The comp-MEAN ``cc_output.total_lockdown_score`` that saturates the tenacity
# axis at 1.0. Measured over the whole 161-champion cc_output registry at ENGINE
# 1.246.0: median 1.400, p75 2.100, p90 2.790, max 7.125 (Mordekaiser). 3.0 sits
# just above p90, so only a genuinely lockdown-stacked comp saturates while a
# median comp lands near 0.47. Operator-tunable, same spirit as _KIT / _TEN.
_CC_LOCKDOWN_REF = 3.0


def comp_cc_signal(
    enemy_champions: Iterable[str] | None,
    mode: str = "SR",
    lockdown_ref: float | None = None,
) -> float | None:
    """Real per-champion enemy-CC signal in [0,1], or ``None`` when unavailable.

    Replaces the v1 AP-share ``cc_proxy``: reads each enemy champion's
    hand-weighted lockdown score from :func:`cc_output.compute_cc_output` and
    returns the comp MEAN divided by ``lockdown_ref``, clamped to [0,1]. The
    kind weights already price a 1.5s suppression above a 1.5s slow, so an
    AD-dominant hard-CC frontline is credited correctly - the exact case the
    AP-share proxy under-credits.

    Returns ``None`` (never 0.0) when there is nothing to read - a blank / empty
    roster, or ``cc_output`` being unimportable - so the caller can fall back to
    the v1 proxy and stay byte-identical. ``cc_output`` is imported LAZILY to
    keep this module's import graph pure, matching how ``core.build_order``
    lazy-imports this module on its ON path only.

    A champion absent from the cc_output registry (12 of 173 at 1.246.0)
    contributes 0.0 rather than raising, which under-credits rather than
    over-credits. ``mode`` is accepted and forwarded for parity with the other
    scorers but is provably inert today (``cc_output.compute_cc_output``
    docstring: offensive output is target-independent).

    ``lockdown_ref`` defaults to None and is resolved to the module-level
    ``_CC_LOCKDOWN_REF`` at CALL time, not bound at def time, so the knob stays
    genuinely operator-tunable (and monkeypatchable) at runtime.

    Input hardening (s144 S144-T-683): a bare str / bytes roster is a TypeError
    (it used to be read per CHARACTER, so ``"Leona"`` returned 0.0 - "no CC" -
    and overrode the v1 fallback); a non-finite or non-positive ref returns
    None (a nan ref used to SATURATE to 1.0 through ``min(1.0, nan)``); a
    non-finite or negative per-champion score contributes 0.0 like an
    unregistered name, so one corrupt row cannot saturate the comp.
    """
    _require_pool_like(enemy_champions, "comp_cc_signal: enemy_champions")
    if not enemy_champions:
        return None
    names = [str(c).strip() for c in enemy_champions if str(c).strip()]
    if not names:
        return None
    ref = float(_CC_LOCKDOWN_REF if lockdown_ref is None else lockdown_ref)
    if not math.isfinite(ref) or ref <= 0.0:
        return None
    try:
        from agents.daemon_slayer.cc_output import compute_cc_output
    except Exception:  # noqa: BLE001 - fail-soft to the v1 proxy
        return None
    total = 0.0
    for name in names:
        try:
            score = float(compute_cc_output(name, mode).total_lockdown_score)
        except Exception:  # noqa: BLE001 - one bad name must not sink the comp
            continue
        if not math.isfinite(score) or score < 0.0:
            continue
        total += score
    return max(0.0, min(1.0, (total / float(len(names))) / ref))
