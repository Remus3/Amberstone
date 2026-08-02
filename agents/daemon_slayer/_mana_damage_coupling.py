"""RM-118: champion MANA -> DAMAGE coupling registry (DEFAULT-OFF).

WHY THIS REGISTRY EXISTS
------------------------
``ehp.py`` imports no abilities module and reads zero ``damage_blocks``. For a
tank that is usually fine - health and resists ARE the tank objective. But a
champion whose OWN KIT spends its MANA as damage gets a SECOND, genuinely-real
payment out of the same purchase, and that payment is credited NOWHERE:
Blitzcrank R "Static Field" deals 2 percent of his maximum mana as magic damage
on every detonation. The tank route therefore prices a mana item (Winter's
Approach 3119 / Fimbulwinter 3121) on the HEALTH axis alone and under-ranks it
for exactly the champion built to spend the mana half.

This is the MANA-axis TWIN of the shipped RESIST-axis lever
(``_resist_damage_coupling`` / RM-87) and the HEALTH-axis lever
(``_health_damage_coupling`` / RM-91 T1). All three registries are DISJOINT -
zero champion overlap at 16.15.1 - and they ride SEPARATE flags on purpose.
Merging them into one flag would arm a mana credit on Rammus (who converts
resists, not mana) and a resist credit on Blitzcrank (who converts mana, not
resists).

WHAT AN ENTRY MEANS
-------------------
``max_mp_pct`` / ``bonus_mp_pct`` are the NOMINAL percent of the champion's
maximum / bonus mana its kit re-spends as damage. ``pct_base`` names the pool
the percent reads, and it always matches whichever of the two columns is
non-zero:

  * ``"total"`` - total maximum mana (base per-level block + items), the
    ``caster_max_mp_pct`` field in ``champion_abilities.json``.
  * ``"bonus"`` - bonus mana only (maximum minus the champion's own base
    block), the ``caster_bonus_mp_pct`` field. That is the SMALLER pool, so a
    given item's mana is a LARGER relative addition. The consumer picks the
    matching baseline basis, so the distinction is load-bearing.

``conditional_probability`` amortizes cadence exactly like its sibling
registries (``_resist_damage_coupling``, ``_health_damage_coupling``,
``_champion_cc_mitigation_overrides._CC_IMMUNITY_ACTIVE_PROB``,
``_passive_resist_overrides._ACTIVE_RESIST_PROB``).

The consumer (``ehp.rank_items_by_ehp``) folds these into the RANKING KEY ONLY,
following the ``_conv_key`` / ``_coupling_key`` / ``_health_key`` precedent - no
row value is ever mutated - and the whole lane is inert unless BOTH
``apply_mana_damage_coupling=True`` AND ``mana_coupling_strength > 0.0``, so the
default path is byte-identical.

PROVENANCE - every seeded entry is cited, nothing is authored from memory
------------------------------------------------------------------------
On-disk source is ``data/daemon_slayer/16.15.1/champion_abilities.json`` (the
active patch). A machine sweep of every champion's ``damage_blocks`` for a
``caster_max_mp_pct`` / ``caster_bonus_mp_pct`` field returned exactly EIGHT
blocks across THREE champions and nothing else:

  * ``caster_max_mp_pct`` - Blitzcrank ``R/0/damage_blocks/0`` [2.0, 2.0, 2.0];
    Kassadin ``R/0/damage_blocks/{0,1,2,3}`` [2.0], [1.0], [4.0], [6.0].
  * ``caster_bonus_mp_pct`` - Ryze ``Q/0``, ``W/0``, ``E/0``, each 5 ranks flat
    at 2.0, 4.0, 2.0.

The sibling ``caster_mr_pct`` field is wired in the schema but carries ZERO
blocks at 16.15.1, so there is nothing on that axis to seed.

Of those three champions exactly ONE is seeded. The other two are excluded by
ARCHETYPE ROUTE, below.

DOCUMENTED REJECTS - deliberately NOT seeded
--------------------------------------------
  * ``Kassadin`` (``champions.json`` tags ``["Assassin", "Mage"]``) is
    ASSASSIN-primary, so he routes to ``ds.burst``, not to this tank route. That
    scorer consumes ``AbilityContext``, which ALREADY carries ``caster_max_mp``
    and ``caster_bonus_mp`` derived at ``ability_dps.py:299-300``, so his R
    mana term is already priced where he is actually scored. Wiring him here
    double-counts. His four blocks are additionally a textbook instance of the
    sub-component trap - "Bonus Damage Per Stack" 1.0 and "Maximum Bonus Damage"
    4.0 are components of the "Maximum Magic Damage" 6.0 that contains them -
    so even a legitimate seed could never sum them.
  * ``Ryze`` (tags ``["Mage"]``) is MAGE-primary, so he routes to
    ``ds.ability``, which evaluates his ``damage_blocks`` directly off the same
    ``AbilityContext`` mana fields. His Q / W / E bonus-mana terms are already
    read there. Wiring him here double-counts. He is also three PEER abilities
    with three different cadences, which the sibling registries' standing rule
    forbids summing.

Blitzcrank is the only member of the census that is Tank-primary
(``champions.json`` tags ``["Tank", "Support"]``), which is what routes him to
``/rank-tank`` and this scorer, and he genuinely buys mana (Winter's Approach /
Fimbulwinter), so the uncredited payment is real rather than hypothetical.
"""
from __future__ import annotations

from dataclasses import dataclass

# Cadence amortization midpoints, reused verbatim from the RM-87 / RM-91
# siblings so all three levers are calibrated on one scale. Documented +
# conservative, and operator-tunable.
_PERMANENT_CONVERSION_PROB = 1.0   # a permanent stat conversion
_ABILITY_CAST_PROB = 0.5           # a cooldown-gated damage ability in the rotation
# NEW tier for this registry, and it sits deliberately BELOW the 0.5 in-rotation
# ability midpoint. ``_ABILITY_CAST_PROB`` was calibrated on a 12-14 second
# damage ability (Ornn E "Searing Charge"); Blitzcrank R "Static Field" is on a
# 60/40/20 second cooldown per champion_abilities.json 16.15.1, i.e. 3-5x that
# cadence at the ranks a mana item is actually being bought at. Crediting an
# ultimate at the basic-ability rate would over-model it, so the ultimate takes
# its own lower midpoint. Conservative and operator-tunable.
_ULTIMATE_CAST_PROB = 0.35


@dataclass(frozen=True)
class ManaDamageCouplingEntry:
    """One champion's kit-level mana -> damage conversion.

    ``max_mp_pct`` / ``bonus_mp_pct`` are NOMINAL percents of the pool named by
    ``pct_base`` (``"total"`` or ``"bonus"``). Exactly one of the two is non-zero
    on every seeded entry, and ``pct_base`` names that same pool, so the credit's
    numerator and its normalizing denominator always read the same mana pool.
    ``conditional_probability`` amortizes cadence.
    """

    max_mp_pct: float = 0.0
    bonus_mp_pct: float = 0.0
    pct_base: str = "total"
    conditional_probability: float = 1.0
    attribute: str = ""
    note: str = ""


# champion_id (canonical DDragon id) -> ManaDamageCouplingEntry.
# Exactly ONE champion. Machine-guarded by
# tests/test_mana_damage_coupling_rm118.py::RegistryPopulationTests.
_CHAMPION_MANA_DAMAGE_COUPLING: dict[str, ManaDamageCouplingEntry] = {
    # champion_abilities.json 16.15.1, Blitzcrank R "Static Field",
    # damage_blocks[0] (path Blitzcrank/R/0/damage_blocks/0): attribute
    # "Magic Damage", damage_type MAGIC, caster_max_mp_pct [2.0, 2.0, 2.0] -
    # flat across all 3 ranks. caster_max_mp_pct reads TOTAL mana, hence
    # pct_base "total". The ONLY mana-scaling block in his kit - no
    # sub-component and no peer ability, so nothing is discarded.
    "Blitzcrank": ManaDamageCouplingEntry(
        max_mp_pct=2.0,
        bonus_mp_pct=0.0,
        pct_base="total",
        conditional_probability=_ULTIMATE_CAST_PROB,
        attribute="Static Field",
        note="R: 2% TOTAL max mana as MAGIC damage (flat all 3 ranks); sole mana-scaling block in the kit, nothing discarded; amortized at the ultimate-cast midpoint (60/40/20s cooldown)",
    ),
}


def mana_damage_coupling(champion_id: str) -> ManaDamageCouplingEntry | None:
    """Return the champion's mana -> damage coupling entry, or None.

    Fail-soft by design (the sibling-registry contract): an unknown / empty /
    unseeded champion id returns None, which collapses the consumer's credit to
    an exact no-op.
    """
    if not champion_id:
        return None
    return _CHAMPION_MANA_DAMAGE_COUPLING.get(str(champion_id))


def coupled_mana_points(
    entry: ManaDamageCouplingEntry,
    max_mp: float,
    bonus_mp: float,
) -> float:
    """NOMINAL mana points the kit re-spends as damage, given a mana pair.

    Linear and probability-FREE on purpose: ``conditional_probability`` is
    applied ONCE by the caller, to the final normalized credit, so it can never
    be double-applied.

    The caller normalizes this by the champion's RAW baseline mana pool on the
    basis the entry names, percent-FREE. That choice is load-bearing: dividing
    percent-weighted points by percent-weighted points cancels the percents
    exactly, which would hand a 2-percent converter and a 6-percent converter an
    IDENTICAL credit. Against the raw pool the credit reads literally as "the
    fraction of my mana pool that pays a second time", and scales with the
    conversion magnitude as it must.

    Negative mana inputs floor at zero - a mana LOSS must never manufacture a
    negative conversion credit (the same guard shape as ``_conv_key``'s
    non-positive early return).
    """
    m = max(0.0, float(max_mp))
    b = max(0.0, float(bonus_mp))
    return (entry.max_mp_pct / 100.0) * m + (entry.bonus_mp_pct / 100.0) * b


__all__ = [
    "ManaDamageCouplingEntry",
    "_CHAMPION_MANA_DAMAGE_COUPLING",
    "mana_damage_coupling",
    "coupled_mana_points",
    "_PERMANENT_CONVERSION_PROB",
    "_ABILITY_CAST_PROB",
    "_ULTIMATE_CAST_PROB",
]
