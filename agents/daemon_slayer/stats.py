"""Stat scaling rules + DDragon item-stat mapping for Daemon Slayer.

Two extension points are deliberate:

* ``CHAMPION_SCALING_RULES`` - per-stat rule list. Adding a stat means adding
  one ``ScalingRule`` entry; engine.py iterates the list, no engine edit needed.
* ``ITEM_STAT_KEY_MAP`` - DDragon stat key → ``(canonical_key, kind)``.
  ``kind`` is ``"flat"`` or ``"pct"``. Items whose stats live only in description
  text (passive effects, on-hit, conversions) are deliberately absent - that's
  the Phase 4 conditional-effects layer.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

LEVEL_MIN = 1
LEVEL_MAX = 18


# ----- per-level scaling formulas ---------------------------------------------

def growth_multiplier(level: int) -> float:
    """Riot champion stat-growth coefficient for a given level.

    ``(n - 1) * (0.7025 + 0.0175 * (n - 1))`` - the canonical
    Riot/League-wiki per-level growth multiplier. It equals the naive
    linear ``(n - 1)`` ONLY at level 1 (multiplier 0) and level 18
    (multiplier exactly 17.0); for every level 2..17 it is strictly
    lower. The pre-fix engine used the linear multiplier and therefore
    over-stated every per-level base stat between the two endpoints.
    """
    return (level - 1) * (0.7025 + 0.0175 * (level - 1))


def scaled(base: float, perlevel: float, level: int) -> float:
    """Per-level base-stat scaling - current League math.

    Applies to hp/mp/hpregen/mpregen/armor/mr/ad (and crit, whose
    ``critperlevel`` is 0 for every champion, so it stays flat).
    """
    return base + perlevel * growth_multiplier(level)


def attack_speed_scaling(base_as: float, perlevel_pct: float, level: int) -> float:
    """Attack speed: ``base × (1 + perlevel% × (level-1))``.

    DDragon ``attackspeedperlevel`` is expressed as a percentage (e.g. ``2.5``
    means +2.5% bonus AS per level). Item AS bonuses stack into the same
    bonus_pct sum; the engine applies the item portion alongside this.
    """
    return base_as * (1 + (perlevel_pct / 100.0) * (level - 1))


@dataclass(frozen=True)
class ScalingRule:
    canonical_key: str           # engine-side stat name (lowercase, short)
    base_field: str              # DDragon ``stats`` key for base value
    perlevel_field: str          # DDragon ``stats`` key for per-level value
    formula: Callable[[float, float, int], float]
    # AS needs special downstream handling (item bonuses stack into bonus_pct,
    # not on top of the leveled value). Engine inspects this flag.
    multiplicative_item_pct: bool = False


CHAMPION_SCALING_RULES: tuple[ScalingRule, ...] = (
    ScalingRule("hp",       "hp",            "hpperlevel",            scaled),
    ScalingRule("mp",       "mp",            "mpperlevel",            scaled),
    ScalingRule("hpregen",  "hpregen",       "hpregenperlevel",       scaled),
    ScalingRule("mpregen",  "mpregen",       "mpregenperlevel",       scaled),
    ScalingRule("armor",    "armor",         "armorperlevel",         scaled),
    ScalingRule("mr",       "spellblock",    "spellblockperlevel",    scaled),
    ScalingRule("ad",       "attackdamage",  "attackdamageperlevel",  scaled),
    ScalingRule("crit",     "crit",          "critperlevel",          scaled),
    ScalingRule(
        "as",
        "attackspeed",
        "attackspeedperlevel",
        attack_speed_scaling,
        multiplicative_item_pct=True,
    ),
)

# Stats that are read straight from the champion record without per-level math.
PASSTHROUGH_STAT_FIELDS: dict[str, str] = {
    # canonical_key: ddragon_field
    "ms":          "movespeed",
    "attackrange": "attackrange",
}


# ----- DDragon item stat mapping ----------------------------------------------

# (canonical_key, kind) - kind is "flat" or "pct".
# Pct values from DDragon are unit-fraction (0.07 == +7%), NOT percentage points.
ITEM_STAT_KEY_MAP: dict[str, tuple[str, str]] = {
    "FlatHPPoolMod":          ("hp",        "flat"),
    "FlatMPPoolMod":          ("mp",        "flat"),
    "FlatHPRegenMod":         ("hpregen",   "flat"),
    "FlatMPRegenMod":         ("mpregen",   "flat"),
    "FlatArmorMod":           ("armor",     "flat"),
    "FlatSpellBlockMod":      ("mr",        "flat"),
    "FlatPhysicalDamageMod":  ("ad",        "flat"),
    "FlatMagicDamageMod":     ("ap",        "flat"),
    "FlatCritChanceMod":      ("crit",      "flat"),
    "FlatMovementSpeedMod":   ("ms",        "flat"),
    "PercentMovementSpeedMod":("ms",        "pct"),
    "PercentAttackSpeedMod":  ("as",        "pct"),
    "PercentLifeStealMod":    ("lifesteal", "pct"),
    "PercentSpellVampMod":    ("spellvamp", "pct"),
    "FlatHPRegenModPerLevel": ("hpregen",   "flat"),  # rare; folded as flat
}

# Canonical keys we always surface in the resolved stat dict, even when zero.
# Listed in display order for the CLI table.
RESOLVED_STAT_ORDER: tuple[str, ...] = (
    "hp", "mp", "hpregen", "mpregen",
    "armor", "mr",
    "ad", "ap",
    "as", "crit", "lifesteal", "spellvamp",
    "ms", "attackrange",
)


def clamp_level(level: int) -> int:
    if not isinstance(level, int):
        raise TypeError(f"level must be int, got {type(level).__name__}")
    if level < LEVEL_MIN or level > LEVEL_MAX:
        raise ValueError(f"level out of range [{LEVEL_MIN}, {LEVEL_MAX}]: {level}")
    return level


def aggregate_item_stats(item_stat_blocks: list[dict]) -> dict[str, float]:
    """Sum DDragon item stat blocks into canonical ``{key_kind: total}`` form.

    Returns keys like ``"ad_flat"``, ``"as_pct"``, ``"hp_flat"``. Unknown
    DDragon keys are silently skipped - that's the Phase 4 conditional layer's
    job, not the stat aggregator's.
    """
    totals: dict[str, float] = {}
    for block in item_stat_blocks:
        if not block:
            continue
        for ddragon_key, value in block.items():
            mapped = ITEM_STAT_KEY_MAP.get(ddragon_key)
            if mapped is None:
                continue
            canonical, kind = mapped
            slot = f"{canonical}_{kind}"
            totals[slot] = totals.get(slot, 0.0) + float(value)
    return totals
