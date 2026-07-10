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


def comp_weights(
    archetype: str,
    enemy_ad_share: float,
    enemy_ap_share: float,
    cc_proxy: float,
) -> dict[str, float]:
    """Per-axis weights for a comp. cc_proxy in [0,1] is the caller's CC estimate."""
    weights: dict[str, float] = {
        "armor_survival": _DEF * float(enemy_ad_share),
        "mr_survival": _DEF * float(enemy_ap_share),
        "tenacity": _TEN * float(cc_proxy),
        "move_speed": _MS,
    }
    kit_axis = _ARCHETYPE_AXIS.get((archetype or "carry").strip().lower())
    if kit_axis:
        weights[kit_axis] = weights.get(kit_axis, 0.0) + _KIT
    return weights


def score_boot(boot_id: str, weights: dict[str, float]) -> float:
    """Dot product of the boot's utility vector with the comp weights. 0.0 if unknown."""
    profile = BOOT_UTILITY_PROFILE.get(str(boot_id), {})
    return sum(profile.get(axis, 0.0) * w for axis, w in weights.items())


def select_boot(
    pool: Iterable[str],
    weights: dict[str, float],
    default_id: str,
    switch_margin: float = _SWITCH_MARGIN,
) -> str:
    """Argmax boot over pool, but the challenger must beat the archetype default
    by switch_margin. A DEFENSIVE archetype's default boot earns an incumbency
    bonus so a neutral comp holds it. Fail-soft: an empty pool returns default_id.
    """
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
    challenger = max(ids, key=_eff)
    if challenger != did and _eff(challenger) > default_score * (1.0 + switch_margin):
        return challenger
    return did
