"""RM-87 / row A-18: champion RESIST -> DAMAGE coupling registry (DEFAULT-OFF).

WHY THIS REGISTRY EXISTS
------------------------
Row A-18 was filed as "resists pay twice while the objective counts them once",
i.e. a DOUBLE-COUNT in the tank objective. That is REFUTED by source: ``ehp.py``
accumulates each resist EXACTLY ONCE into ``eff_armor`` / ``eff_mr``
(``ehp.py:1926-1927``), divides by it exactly once in the three per-type
numerators (``ehp.py:1984-1986``), and blends exactly once
(``ehp.py:2095-2099``). No term is counted twice anywhere.

The real defect is the INVERSE - a single-count UNDER-credit. ``ehp.py`` imports
no abilities module and reads zero ``damage_blocks``, so a champion whose OWN KIT
converts its resists into damage gets that second, genuinely-real payment
credited NOWHERE. The tank route therefore over-ranks a pure-HP roller
(Warmog's / Heartsteel) against a resist roller (Thornmail / Frozen Heart /
Kaenic Rookern) for exactly the champions built to punish that trade.

WHAT AN ENTRY MEANS
-------------------
``armor_pct`` / ``mr_pct`` are the NOMINAL percent of the champion's armor / MR
its kit re-spends as damage. ``pct_base`` says which pool the percent reads:

  * ``"total"`` - total armor / total MR (base per-level + items).
  * ``"bonus"`` - bonus armor / bonus MR only (total minus the champion's base
    block), which is the smaller pool, so a given item's resists are a LARGER
    relative addition. The consumer picks the matching baseline basis, so the
    distinction is load-bearing, not decorative.

``conditional_probability`` amortizes cadence exactly like its sibling
registries (``_champion_cc_mitigation_overrides._CC_IMMUNITY_ACTIVE_PROB``,
``_passive_resist_overrides._ACTIVE_RESIST_PROB``): a permanent stat conversion
is 1.0, a cooldown-gated ability is a fight-share midpoint, a periodic empowered
basic attack is lower still.

The consumer (``ehp.rank_items_by_ehp``) folds these into the RANKING KEY ONLY,
following the ``_conv_key`` precedent - no row value is ever mutated - and the
whole lane is inert unless BOTH ``apply_resist_damage_coupling=True`` AND
``resist_coupling_strength > 0.0``, so the default path is byte-identical.

PROVENANCE - every seeded entry is cited, nothing is authored from memory
------------------------------------------------------------------------
On-disk source is ``data/daemon_slayer/16.14.1/champion_abilities.json`` (the
active patch, ENGINE 1.246.0). A machine sweep of every champion's
``damage_blocks`` for a resist-scaling field returned exactly six rows
(KSante Q, Malphite W, Malphite E, Ornn E, Taric E) plus the ``no_damage``
effects-text forms read verbatim below. In-repo source is
``_passive_damage_overrides.py`` where two of these are already modelled.

DOCUMENTED REJECTS - deliberately NOT seeded
--------------------------------------------
  * ``KSante`` - K'Sante P "All Out Bonus" is an existing documented reject at
    ``_passive_damage_overrides.py:839-843``: it is BILINEAR (caster bonus
    resist * target max HP, a product, not a linear resist term) AND gated on
    the R-empowered All Out state, so seeding it always-on over-models. The
    sweep did also surface K'Sante Q "Ntofo Strikes" (bonus_armor_pct 40 /
    bonus_mr_pct 40, PHYSICAL) as a clean linear form, but K'Sante is held out
    of this seed pass in full per that same reject scope - promoting Q is an
    operator call, not a side effect of this slice.
  * ``Rammus`` W "Defensive Ball Curl" (15 + 10 percent total armor + 10 percent
    total MR reflect) - already rejected at
    ``_passive_damage_overrides.py:844-849`` as a reactive on-being-hit reflect,
    the wrong cadence for a conversion term. Rammus is seeded on his P only.
  * ``Skarner`` - carries NO resist-scaling ability text or damage block at
    16.14.1. Nothing to source, so nothing is seeded.
  * ``Poppy`` - her only resist passive (W "Stubborn to a Fault") increases her
    own total armor and total MR by 12 percent. That is resist -> RESIST
    amplification, which the EHP denominator ALREADY captures; it is not a
    resist -> damage conversion. Poppy is the seam's negative control.

Also deliberately NOT summed within a seeded champion: a second, weaker
resist-scaling source on the same kit (Malphite W's 15 percent on top of E's 40,
Taric P's 15 percent bonus armor on top of E's 50). Summing peer abilities with
different cadences is how a conversion credit turns into a double-count, which
is the exact failure mode this row was mis-filed as. Each champion is seeded on
its single DOMINANT clean-linear source.
"""
from __future__ import annotations

from dataclasses import dataclass

# Cadence amortization midpoints. Documented + conservative, operator-tunable,
# and parallel to the sibling registries' midpoints.
_PERMANENT_CONVERSION_PROB = 1.0   # a permanent stat conversion (Rammus P bonus AD)
_ON_HIT_INNATE_PROB = 1.0          # an every-basic-attack innate rider (Rell P)
_ABILITY_CAST_PROB = 0.5           # a cooldown-gated damage ability in the rotation
_PERIODIC_EMPOWER_PROB = 0.4       # an internally-gated periodic empowered attack


@dataclass(frozen=True)
class ResistDamageCouplingEntry:
    """One champion's kit-level resist -> damage conversion.

    ``armor_pct`` / ``mr_pct`` are NOMINAL percents of the pool named by
    ``pct_base`` (``"total"`` or ``"bonus"``). ``conditional_probability``
    amortizes cadence; a permanent stat conversion is 1.0.
    """

    armor_pct: float = 0.0
    mr_pct: float = 0.0
    pct_base: str = "total"
    conditional_probability: float = 1.0
    attribute: str = ""
    note: str = ""


# champion_id (canonical DDragon id) -> ResistDamageCouplingEntry.
_CHAMPION_RESIST_DAMAGE_COUPLING: dict[str, ResistDamageCouplingEntry] = {
    # champion_abilities.json 16.14.1, Rammus P "Spiked Shell",
    # effects_descriptions[0] verbatim: "Innate: Rammus gains bonus attack damage
    # equal to the sum of 15% total armor and 15% total magic resistance."
    # A PERMANENT stat conversion (damage_blocks is empty, parse_status
    # "no_damage" - the whole payment is invisible to every scorer), hence 1.0.
    "Rammus": ResistDamageCouplingEntry(
        armor_pct=15.0,
        mr_pct=15.0,
        pct_base="total",
        conditional_probability=_PERMANENT_CONVERSION_PROB,
        attribute="Spiked Shell",
        note="Innate: bonus AD equal to 15% total armor + 15% total MR (permanent stat conversion; W reflect deliberately excluded, see module docstring)",
    ),
    # champion_abilities.json 16.14.1, Ornn E "Searing Charge",
    # damage_blocks[0]: attribute "Physical Damage", damage_type PHYSICAL,
    # bonus_armor_pct [40.0]*5, bonus_mr_pct [40.0]*5 (flat across ranks).
    # A 12-14s cooldown damage ability -> the in-rotation fight-share midpoint.
    "Ornn": ResistDamageCouplingEntry(
        armor_pct=40.0,
        mr_pct=40.0,
        pct_base="bonus",
        conditional_probability=_ABILITY_CAST_PROB,
        attribute="Searing Charge",
        note="E: 40% bonus armor + 40% bonus MR as PHYSICAL damage (flat all ranks); amortized at the ability-cast midpoint",
    ),
    # champion_abilities.json 16.14.1, Rell P "Break the Mold",
    # effects_descriptions verbatim: "Innate: Rell's basic attacks deal bonus
    # magic damage on-hit equal to the sum of 5% of her total armor and 5% of her
    # total magic resistance." An every-basic-attack innate -> 1.0. The same
    # passive's resist SHRED and her self resist-steal are separate axes
    # (target vulnerability / self resist grant), not this conversion.
    "Rell": ResistDamageCouplingEntry(
        armor_pct=5.0,
        mr_pct=5.0,
        pct_base="total",
        conditional_probability=_ON_HIT_INNATE_PROB,
        attribute="Break the Mold",
        note="Innate: on-hit bonus MAGIC equal to 5% total armor + 5% total MR (every basic attack); the resist shred + self resist-steal are separate axes",
    ),
    # champion_abilities.json 16.14.1, Malphite E "Ground Slam",
    # damage_blocks[0]: attribute "Magic Damage", damage_type MAGIC,
    # caster_armor_pct [40.0]*5 - caster_armor_pct is TOTAL armor. Cooldown
    # ability -> the cast midpoint. W "Thunderclap" (caster_armor_pct 15) is a
    # peer source deliberately NOT summed (see module docstring).
    "Malphite": ResistDamageCouplingEntry(
        armor_pct=40.0,
        mr_pct=0.0,
        pct_base="total",
        conditional_probability=_ABILITY_CAST_PROB,
        attribute="Ground Slam",
        note="E: 40% TOTAL armor as MAGIC damage (flat all ranks); amortized at the ability-cast midpoint; W's 15% peer source not summed",
    ),
    # champion_abilities.json 16.14.1, Taric E "Dazzle", damage_blocks[0]:
    # attribute "Magic Damage", damage_type MAGIC, bonus_armor_pct [50.0]*5.
    # The already-modelled Taric P Bravado rider (bonus_armor_pct=15.0 at
    # _passive_damage_overrides.py:852-861) is the WEAKER peer source and is
    # deliberately not summed - it is post-cast 2-basic-attack gated and is
    # metadata-only in the scorers.
    "Taric": ResistDamageCouplingEntry(
        armor_pct=50.0,
        mr_pct=0.0,
        pct_base="bonus",
        conditional_probability=_ABILITY_CAST_PROB,
        attribute="Dazzle",
        note="E: 50% bonus armor as MAGIC damage (flat all ranks); amortized at the ability-cast midpoint; P Bravado's 15% peer source not summed",
    ),
    # _passive_damage_overrides.py:867-874, Galio P "Colossal Smash":
    # bonus_mr_pct=60.0, damage_type MAGIC, cadence "on_hit" - and that entry's
    # own note records it is NOT on the AA-routed allowlist because the gate is
    # PERIODIC, not every-attack, so it stays metadata-only / inert in every
    # scorer. Amortized at the periodic-empower midpoint.
    "Galio": ResistDamageCouplingEntry(
        armor_pct=0.0,
        mr_pct=60.0,
        pct_base="bonus",
        conditional_probability=_PERIODIC_EMPOWER_PROB,
        attribute="Colossal Smash",
        note="P: 60% bonus MR on the periodic empowered basic attack (MAGIC); metadata-only in the damage scorers; amortized at the periodic-empower midpoint",
    ),
}


def resist_damage_coupling(champion_id: str) -> ResistDamageCouplingEntry | None:
    """Return the champion's resist -> damage coupling entry, or None.

    Fail-soft by design (the sibling-registry contract): an unknown / empty /
    unseeded champion id returns None, which collapses the consumer's credit to
    an exact no-op.
    """
    if not champion_id:
        return None
    return _CHAMPION_RESIST_DAMAGE_COUPLING.get(str(champion_id))


def coupled_resist_points(
    entry: ResistDamageCouplingEntry,
    armor: float,
    mr: float,
) -> float:
    """NOMINAL resist points the kit re-spends as damage, given a resist pair.

    Linear and probability-FREE on purpose: ``conditional_probability`` is
    applied ONCE by the caller, to the final normalized credit, so it can never
    be double-applied.

    The caller normalizes this by the champion's RAW baseline resist pool
    (``basis_armor + basis_mr``, percent-FREE) rather than by this same function
    evaluated on the baseline. That choice is load-bearing: dividing
    percent-weighted points by percent-weighted points cancels the percents
    exactly, which would make a 5-percent converter (Rell) and a 40-percent
    converter (Ornn) receive an IDENTICAL credit. Against the raw pool the credit
    reads literally as "the fraction of my already-counted resist pool that pays
    a second time", and scales with the conversion magnitude as it must.

    Negative resist inputs floor at zero - a resist LOSS must never manufacture
    a negative conversion credit (the same guard shape as ``_conv_key``'s
    non-positive early return).
    """
    a = max(0.0, float(armor))
    m = max(0.0, float(mr))
    return (entry.armor_pct / 100.0) * a + (entry.mr_pct / 100.0) * m


__all__ = [
    "ResistDamageCouplingEntry",
    "_CHAMPION_RESIST_DAMAGE_COUPLING",
    "resist_damage_coupling",
    "coupled_resist_points",
    "_PERMANENT_CONVERSION_PROB",
    "_ON_HIT_INNATE_PROB",
    "_ABILITY_CAST_PROB",
    "_PERIODIC_EMPOWER_PROB",
]
