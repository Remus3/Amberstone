"""RM-91 T1: champion HEALTH -> DAMAGE coupling registry (DEFAULT-OFF).

WHY THIS REGISTRY EXISTS
------------------------
``ehp.py`` imports no abilities module and reads zero ``damage_blocks``. For a
tank that is usually fine - health and resists ARE the tank objective. But a
champion whose OWN KIT spends its health as damage gets a SECOND, genuinely-real
payment out of the same purchase, and that payment is credited NOWHERE: Shen E
"Shadow Dash" deals 11 percent of his bonus health as physical damage, Sejuani W
"Winter's Wrath" deals 12 percent of her maximum health as physical damage. The
tank route therefore prices a health item on the DENOMINATOR axis only and
under-ranks it for exactly the champions built to spend it.

This is the HEALTH-axis TWIN of the shipped RESIST-axis lever
(``_resist_damage_coupling`` / RM-87). The two registries are DISJOINT - zero
champion overlap at 16.14.1 - and they ride SEPARATE flags on purpose. Merging
them into one flag would arm a health credit on Rammus (who converts resists,
not health) and a resist credit on Shen (who converts health, not resists).

WHAT AN ENTRY MEANS
-------------------
``max_hp_pct`` / ``bonus_hp_pct`` are the NOMINAL percent of the champion's
maximum / bonus health its kit re-spends as damage. ``pct_base`` names the pool
the percent reads, and it always matches whichever of the two columns is
non-zero:

  * ``"total"`` - total maximum health (base per-level block + items), the
    ``caster_max_hp_pct`` field in ``champion_abilities.json``.
  * ``"bonus"`` - bonus health only (maximum minus the champion's own base
    block), the ``caster_bonus_hp_pct`` field. That is the SMALLER pool, so a
    given item's health is a LARGER relative addition. The consumer picks the
    matching baseline basis, so the distinction is load-bearing.

``conditional_probability`` amortizes cadence exactly like its sibling
registries (``_resist_damage_coupling``,
``_champion_cc_mitigation_overrides._CC_IMMUNITY_ACTIVE_PROB``,
``_passive_resist_overrides._ACTIVE_RESIST_PROB``).

The consumer (``ehp.rank_items_by_ehp``) folds these into the RANKING KEY ONLY,
following the ``_conv_key`` / ``_coupling_key`` precedent - no row value is ever
mutated - and the whole lane is inert unless BOTH
``apply_health_damage_coupling=True`` AND ``health_coupling_strength > 0.0``, so
the default path is byte-identical.

PROVENANCE - every seeded entry is cited, nothing is authored from memory
------------------------------------------------------------------------
On-disk source is ``data/daemon_slayer/16.14.1/champion_abilities.json`` (the
active patch). A machine sweep of every champion's ``damage_blocks`` for a
``caster_max_hp_pct`` / ``caster_bonus_hp_pct`` field returned exactly FOURTEEN
champions. Three are excluded by ARCHETYPE ROUTE (see DOCUMENTED REJECTS), which
leaves the ELEVEN tank-primary champions seeded below. Primary role is read from
``champions.json`` ``tags[0]``.

*** THE DOUBLE-COUNT TRAP ***
Most of these kits emit SEVERAL blocks that are sub-components of ONE ability:
Sejuani W is 4.0 + 8.0 with a "Total Physical Damage" 12.0 that IS their sum;
Skarner Q is 3.0 per hit with a "Total Bonus Physical Damage" 9.0; Zac Q is 3.0
with a "Total Magic Damage" 6.0. The rule, inherited verbatim from the RM-87
module docstring: seed ONE value per champion, prefer the genuine TOTAL where one
exists, NEVER sum a sub-component with the Total that contains it, and NEVER sum
peer abilities with different cadences. Each entry below records which value was
taken and which was discarded.

DOCUMENTED REJECTS - deliberately NOT seeded
--------------------------------------------
  * ``Gnar`` (``champions.json`` tags ``["Fighter", "Tank"]``) and ``Volibear``
    (tags ``["Fighter", "Tank"]``) are FIGHTER-primary, so they route to
    ``ds.hybrid``, which already prices a caster-health ability term via the
    shipped DEFAULT-OFF ``apply_ad_axis_ability_damage`` (RM-39/RM-43). Gnar E
    "Hop" / "Crunch" (``caster_max_hp_pct`` 6.0, PHYSICAL) and Volibear W
    "Frenzied Maul" (``caster_bonus_hp_pct`` 6.0, PHYSICAL) are both on the
    PHYSICAL axis that term credits. Wiring either here double-counts.
  * ``Vladimir`` (tags ``["Mage", "Fighter"]``) is MAGE-primary, so he routes to
    ``ds.ability``, which evaluates his ``damage_blocks`` directly - W "Sanguine
    Pool" (Total Magic ``caster_bonus_hp_pct`` 15.0) and E "Tides of Blood"
    (``caster_max_hp_pct`` 1.5 minimum / 6.0 maximum) are already read there.
    Wiring him here double-counts.
  * ``Sett`` - REFUTED against the data, not from memory. His only health-scaling
    blocks are Q "Knuckle Down" ``target_max_hp_pct`` [1.0]*5 and "Total Bonus
    Physical Damage" ``target_max_hp_pct`` [2.0]*5, plus R "The Show Stopper"
    ``target_bonus_hp_pct`` [40.0, 50.0, 60.0] and "Reduced Damage"
    ``target_bonus_hp_pct`` [10.0, 12.5, 15.0]. Every one is ``target_*`` - the
    TARGET's health, an enemy-vulnerability axis that is already modelled - and
    none of it makes Sett's OWN health offensive. He carries NO ``caster_*_hp_pct``
    block at all.
  * ``Sion`` - same refutation, same evidence class: his only health-scaling block
    is W "Soul Furnace" ``target_max_hp_pct`` [14.0]*5. No ``caster_*_hp_pct``
    block anywhere in his kit at 16.14.1.
  * ``Poppy`` - the seam's negative control. Q "Hammer Shock" carries
    ``target_max_hp_pct`` [9.0]*5 and "Total Physical Damage"
    ``target_max_hp_pct`` [18.0]*5, again the TARGET's health. ``Leona`` is the
    second negative control and carries no health-scaling block of any kind.
"""
from __future__ import annotations

from dataclasses import dataclass

# Cadence amortization midpoints, reused verbatim from the RM-87 sibling so the
# two levers are calibrated on one scale. Documented + conservative, and
# operator-tunable.
_PERMANENT_CONVERSION_PROB = 1.0   # a permanent stat conversion
_ON_HIT_INNATE_PROB = 1.0          # an every-basic-attack innate rider
_ABILITY_CAST_PROB = 0.5           # a cooldown-gated damage ability in the rotation
_PERIODIC_EMPOWER_PROB = 0.4       # an internally-gated periodic empowered attack
# The 0.4 tier again, under the name this registry actually needs it for: a cast
# gated on something BEYOND its own cooldown - an ult form window (K'Sante R All
# Out) or an 80-second ultimate that is simply not available every fight
# (Cho'Gath R Feast). Same midpoint, different reason, named so the reason is
# visible at the call site instead of hiding behind "periodic empower".
_GATED_CAST_PROB = _PERIODIC_EMPOWER_PROB


@dataclass(frozen=True)
class HealthDamageCouplingEntry:
    """One champion's kit-level health -> damage conversion.

    ``max_hp_pct`` / ``bonus_hp_pct`` are NOMINAL percents of the pool named by
    ``pct_base`` (``"total"`` or ``"bonus"``). Exactly one of the two is non-zero
    on every seeded entry, and ``pct_base`` names that same pool, so the credit's
    numerator and its normalizing denominator always read the same health pool.
    ``conditional_probability`` amortizes cadence.
    """

    max_hp_pct: float = 0.0
    bonus_hp_pct: float = 0.0
    pct_base: str = "total"
    conditional_probability: float = 1.0
    attribute: str = ""
    note: str = ""


# champion_id (canonical DDragon id) -> HealthDamageCouplingEntry.
# Exactly 11 tank-primary champions. Machine-guarded by
# tests/test_health_damage_coupling_rm91.py::RegistryPopulationTests.
_CHAMPION_HEALTH_DAMAGE_COUPLING: dict[str, HealthDamageCouplingEntry] = {
    # champion_abilities.json 16.14.1, Braum Q "Winter's Bite", damage_blocks[0]:
    # attribute "Magic Damage", caster_max_hp_pct [2.5]*5. The ONLY caster-health
    # block in his kit - no sub-component, nothing discarded. Cooldown 8.0 -> 6.0
    # seconds, an in-rotation damage cast.
    "Braum": HealthDamageCouplingEntry(
        max_hp_pct=2.5,
        pct_base="total",
        conditional_probability=_ABILITY_CAST_PROB,
        attribute="Winter's Bite",
        note="Q: 2.5% TOTAL max health as MAGIC damage (flat all ranks); sole caster-health block, nothing discarded; ability-cast midpoint (8.0-6.0s cooldown)",
    ),
    # champion_abilities.json 16.14.1, Chogath R "Feast", damage_blocks[0]:
    # attribute "Champion True Damage", caster_bonus_hp_pct [10.0]*3.
    # TAKEN 10.0. DISCARDED: "Non-Champion True Damage" (a modifier block, not a
    # caster-health term), "Bonus Health Per Stack" (a heal block - the ability
    # GRANTS health, which the EHP denominator already captures, and folding a
    # grant into a damage conversion would be the double-count this module
    # exists to avoid). Cadence: an 80/70/60-second ultimate is not available
    # every fight, so it takes the gated tier rather than the cast tier.
    "Chogath": HealthDamageCouplingEntry(
        bonus_hp_pct=10.0,
        pct_base="bonus",
        conditional_probability=_GATED_CAST_PROB,
        attribute="Feast",
        note="R: 10% BONUS health as TRUE damage to champions; the non-champion modifier + the Bonus-Health-Per-Stack heal block are discarded; gated tier (80/70/60s ultimate)",
    ),
    # champion_abilities.json 16.14.1, DrMundo E "Blunt Force Trauma".
    # TAKEN the "Minimum Bonus Physical Damage" caster_bonus_hp_pct [7.0]*5 - the
    # GUARANTEED floor of the block.
    # DISCARDED, all three for stated reasons:
    #   * "Maximum Bonus Physical Damage" caster_bonus_hp_pct [9.8]*5 - the SAME
    #     block at the other end of its missing-health ramp ("increased by
    #     0% : 40% based on Dr. Mundo's missing health"), NOT an additional
    #     payment. Summing 7.0 + 9.8 would count one hit twice.
    #   * "Bonus Attack Damage" caster_max_hp_pct [2.0..2.8] - a STAT grant on a
    #     DIFFERENT basis (max, not bonus), and a permanent passive rather than
    #     this active. Different basis + different cadence = never summed.
    #   * W "Heart Zapper" caster_bonus_hp_pct [7.0]*5 - a PEER ability on a
    #     17.0-15.0s cooldown against E's 9.0-6.0s. E is the shorter-cooldown,
    #     larger-ceiling source, so E is the dominant one and W is dropped whole.
    "DrMundo": HealthDamageCouplingEntry(
        bonus_hp_pct=7.0,
        pct_base="bonus",
        conditional_probability=_ABILITY_CAST_PROB,
        attribute="Blunt Force Trauma",
        note="E: 7% BONUS health as PHYSICAL damage (the guaranteed minimum; the 9.8% maximum is the same block's missing-health ramp, the 2.0-2.8% bonus-AD passive is a different basis, and W Heart Zapper's 7% is a longer-cooldown peer - all discarded)",
    ),
    # champion_abilities.json 16.14.1, KSante R "All Out".
    # TAKEN 5.0. "Strike Physical Damage" and "Total Physical Damage" both read
    # caster_bonus_hp_pct [5.0]*3 - the Total CONTAINS the Strike, so they are one
    # payment stated twice and 5.0 is the answer either way. DISCARDED: the
    # unscaled "Physical Damage" block (no caster-health term) and "Bonus Attack
    # Speed" (a duration block).
    # Cadence: the gated tier and NEVER 1.0. All Out is a 120/100/80-second
    # ultimate that opens a 15-second form window; treating it as permanent would
    # credit a health item for a conversion that is off for most of the game.
    "KSante": HealthDamageCouplingEntry(
        bonus_hp_pct=5.0,
        pct_base="bonus",
        conditional_probability=_GATED_CAST_PROB,
        attribute="All Out",
        note="R: 5% BONUS health as PHYSICAL damage (Strike and Total state the same 5%, not two payments); gated tier - the 120/100/80s ult opens a 15s All Out form, so it is explicitly NOT a permanent conversion",
    ),
    # champion_abilities.json 16.14.1, Maokai E "Sapling Toss".
    # TAKEN the UNCONDITIONAL "Magic Damage" caster_bonus_hp_pct [5.0]*5.
    # DISCARDED:
    #   * "Total Enhanced Damage" caster_bonus_hp_pct [10.0]*5 - the BRUSH-placed
    #     variant ("A Sapling placed in brush ... deals double damage ... over 3
    #     bursts"). It is not a Total that contains the 5.0; it is a conditional
    #     DOUBLE of it, so seeding it would price every sapling as a brush
    #     sapling. The conservative unconditional value is taken instead.
    #   * "Enhanced Damage Per Tick" caster_bonus_hp_pct [3.33]*5 - a
    #     sub-component of that 10.0 (three bursts), never summed with it.
    "Maokai": HealthDamageCouplingEntry(
        bonus_hp_pct=5.0,
        pct_base="bonus",
        conditional_probability=_ABILITY_CAST_PROB,
        attribute="Sapling Toss",
        note="E: 5% BONUS health as MAGIC damage, the UNCONDITIONAL sapling; the 10% Total Enhanced is the brush-placed double (a conditional variant, not a containing total) and the 3.33% per tick is its sub-component - both discarded",
    ),
    # champion_abilities.json 16.14.1, Nunu Q "Consume", the "Champion Magic
    # Damage" block: caster_bonus_hp_pct [5.0]*5. The only caster-health block in
    # the ability - the sibling blocks are non-champion modifiers and heal blocks.
    # Cooldown 12.0 -> 8.0 seconds, an in-rotation damage cast.
    "Nunu": HealthDamageCouplingEntry(
        bonus_hp_pct=5.0,
        pct_base="bonus",
        conditional_probability=_ABILITY_CAST_PROB,
        attribute="Consume",
        note="Q: 5% BONUS health as MAGIC damage to champions; the non-champion true-damage modifier + the four heal blocks are not caster-health damage and are discarded; ability-cast midpoint (12.0-8.0s cooldown)",
    ),
    # champion_abilities.json 16.14.1, Sejuani W "Winter's Wrath".
    # TAKEN the "Total Physical Damage" caster_max_hp_pct [12.0]*5.
    # DISCARDED: the two "Physical Damage" blocks at caster_max_hp_pct [4.0]*5
    # (the cone) and [8.0]*5 (the line). They are the Total's two SUB-COMPONENTS
    # and 4 + 8 == 12 exactly; summing any of them with the Total would count the
    # whole ability twice over. This is the textbook case the trap describes.
    "Sejuani": HealthDamageCouplingEntry(
        max_hp_pct=12.0,
        pct_base="total",
        conditional_probability=_ABILITY_CAST_PROB,
        attribute="Winter's Wrath",
        note="W: 12% TOTAL max health as PHYSICAL damage, the genuine Total; its 4% cone + 8% line sub-components sum to exactly that and are discarded, never added to it",
    ),
    # champion_abilities.json 16.14.1, Shen E "Shadow Dash", damage_blocks[0]:
    # attribute "Physical Damage", caster_bonus_hp_pct [11.0]*5. The only
    # caster-health block in his kit and the LARGEST bonus-health converter in
    # this registry - nothing discarded. Cooldown 18.0 -> 10.0 seconds.
    "Shen": HealthDamageCouplingEntry(
        bonus_hp_pct=11.0,
        pct_base="bonus",
        conditional_probability=_ABILITY_CAST_PROB,
        attribute="Shadow Dash",
        note="E: 11% BONUS health as PHYSICAL damage (flat all ranks); sole caster-health block, nothing discarded; ability-cast midpoint (18.0-10.0s cooldown)",
    ),
    # champion_abilities.json 16.14.1, Skarner Q "Shattered Earth" (form_index 0).
    # TAKEN the "Total Bonus Physical Damage" caster_bonus_hp_pct [9.0]*5.
    # DISCARDED:
    #   * "Bonus Physical Damage per Hit" caster_bonus_hp_pct [3.0]*5 - the
    #     SUB-COMPONENT (the ability empowers "up to three" attacks, 3 x 3 == 9).
    #   * Q "Upheaval" (form_index 1) caster_bonus_hp_pct [3.0]*5 - the alternate
    #     ENDING of the same Q ("Skarner ends Shattered Earth by throwing his
    #     boulder ... applying the same damage ... as the final attack would"). It
    #     REPLACES the final attack rather than adding to it, so adding it to the
    #     9.0 would count that attack twice.
    #   * E "Ixtal's Impact" caster_max_hp_pct [6.0]*5 - a PEER ability on a
    #     22.0-18.0s cooldown AND on the other basis (max, not bonus). Summing
    #     across two different health pools is doubly wrong, so it is dropped
    #     whole; Q is the dominant, shorter-cooldown source.
    "Skarner": HealthDamageCouplingEntry(
        bonus_hp_pct=9.0,
        pct_base="bonus",
        conditional_probability=_ABILITY_CAST_PROB,
        attribute="Shattered Earth",
        note="Q: 9% BONUS health as PHYSICAL damage, the genuine Total of three empowered hits; the 3% per-hit sub-component, the 3% Upheaval recast that REPLACES the final hit, and the peer 6% max-health E are all discarded",
    ),
    # champion_abilities.json 16.14.1, TahmKench Q "Tongue Lash", the "Magic
    # Damage" block: caster_bonus_hp_pct [4.0]*5. The sibling "Heal" block is a
    # self-heal, a survivability axis the EHP scorer already owns, not a second
    # damage payment. Cooldown 7.0 -> 5.0 seconds.
    "TahmKench": HealthDamageCouplingEntry(
        bonus_hp_pct=4.0,
        pct_base="bonus",
        conditional_probability=_ABILITY_CAST_PROB,
        attribute="Tongue Lash",
        note="Q: 4% BONUS health as MAGIC damage (flat all ranks); the sibling Heal block is a survivability axis, not a damage payment, and is discarded; ability-cast midpoint (7.0-5.0s cooldown)",
    ),
    # champion_abilities.json 16.14.1, Zac Q "Stretching Strikes".
    # TAKEN the "Total Magic Damage" caster_max_hp_pct [6.0]*5.
    # DISCARDED: the "Magic Damage" caster_max_hp_pct [3.0]*5 initial strike - the
    # SUB-COMPONENT. The ability lands twice ("Zac's next basic attack is replaced
    # by a second Stretching Strike"), so 3 + 3 == the stated 6 and the two must
    # never be added together.
    "Zac": HealthDamageCouplingEntry(
        max_hp_pct=6.0,
        pct_base="total",
        conditional_probability=_ABILITY_CAST_PROB,
        attribute="Stretching Strikes",
        note="Q: 6% TOTAL max health as MAGIC damage, the genuine Total of the cast plus the replaced-attack second strike; the 3% single-strike sub-component is discarded",
    ),
}


def health_damage_coupling(champion_id: str) -> HealthDamageCouplingEntry | None:
    """Return the champion's health -> damage coupling entry, or None.

    Fail-soft by design (the sibling-registry contract): an unknown / empty /
    unseeded champion id returns None, which collapses the consumer's credit to
    an exact no-op.
    """
    if not champion_id:
        return None
    return _CHAMPION_HEALTH_DAMAGE_COUPLING.get(str(champion_id))


def coupled_health_points(
    entry: HealthDamageCouplingEntry,
    delta_max_hp: float,
    delta_bonus_hp: float,
) -> float:
    """NOMINAL health points the kit re-spends as damage, given a health delta.

    Linear and probability-FREE on purpose: ``conditional_probability`` is
    applied ONCE by the caller, to the final normalized credit, so it can never
    be double-applied.

    The caller normalizes this by the champion's RAW baseline health pool on the
    basis the entry names, percent-FREE. That choice is load-bearing: dividing
    percent-weighted points by percent-weighted points cancels the percents
    exactly, which would hand a 2.5-percent converter (Braum) and an 11-percent
    converter (Shen) an IDENTICAL credit. Against the raw pool the credit reads
    literally as "the fraction of my already-counted health pool that pays a
    second time", and scales with the conversion magnitude as it must.

    Negative health inputs floor at zero - a health LOSS must never manufacture
    a negative conversion credit (the same guard shape as ``_conv_key``'s
    non-positive early return).
    """
    m = max(0.0, float(delta_max_hp))
    b = max(0.0, float(delta_bonus_hp))
    return (entry.max_hp_pct / 100.0) * m + (entry.bonus_hp_pct / 100.0) * b


__all__ = [
    "HealthDamageCouplingEntry",
    "_CHAMPION_HEALTH_DAMAGE_COUPLING",
    "health_damage_coupling",
    "coupled_health_points",
    "_PERMANENT_CONVERSION_PROB",
    "_ON_HIT_INNATE_PROB",
    "_ABILITY_CAST_PROB",
    "_PERIODIC_EMPOWER_PROB",
    "_GATED_CAST_PROB",
]
