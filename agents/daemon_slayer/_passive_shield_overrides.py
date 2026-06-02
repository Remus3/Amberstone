"""2026-06-01 (GAP 2) - effects-text-only SHIELD registry.

Sibling of ``_passive_heal_overrides.py`` (items 250-254) but for self/ally
SHIELDS the Meraki ``leveling`` -> ``damage_blocks`` pipeline could not
structure. The roster scan (all 171 champs, forms with NO
``attribute_kind == "shield"`` block whose effects_descriptions carry a
shield/absorb verb) found a class of P/W/E/Q forms whose shield magnitude lives
only in the stripped ``effects_descriptions`` text (Malphite Granite Shield,
Blitzcrank Mana Barrier, Vi Blast Shield, Shen Ki Barrier, Rakan Fey Feathers,
...).

Why a NEW registry (not the heal one): the heal registry's gate is "no existing
HEAL block" + ``to_heal_block`` hardcodes ``attribute_kind="heal"``. Shields ride
the SAME consumer (``ability_hps._eval_heal_shield_block`` is kind-agnostic;
``compute_ability_hps`` already sums ``_select_kind_blocks(form, "shield", ...)``
into ``total_shield_per_sec`` - the 56 snapshot shield blocks are already scored).
This registry adds only the MISSING half: a synthetic ``attribute_kind="shield"``
block for the effects-text-only shields, injected by
``abilities.AbilitiesSnapshot.load(apply_passive_shield=True)`` when the form has
NO existing shield block (so a snapshot shield is never double-counted). ZERO
consumer change - the shields surface in ``total_shield_per_sec`` exactly like the
snapshot shields.

Why HAND-AUTHORED, not parsed: identical reasoning to the heal/damage registries
- a text-parser mis-extracts the endpoints and re-breaks on each patch prose
rewrite. Each entry's terms come from the verbatim ``effects_descriptions``
fragment cited in its ``note``; a patch re-extract re-verifies the cited text.

DEFAULT BEHAVIOR IS BYTE-IDENTICAL: ``apply_passive_shield`` defaults False; with
it OFF no synthetic block is appended and the full DS suite is unchanged.
``load_default`` never sets it. The shields use the EXISTING ``_HEAL_UNIT_TO_CTX``
linear units (flat / % maximum health / % ap / % bonus health) plus ONE additive
unit ``% maximum mana`` -> ``caster_max_mp`` (the ctx attr already exists; no
snapshot heal/shield block uses a mana unit, so the addition is byte-identical on
the default path) for Blitzcrank Mana Barrier. No bilinear / per-charge term is
needed (no effects-text shield is an AP*HP product or a per-stocked-charge sum).

UNLIKE the bilinear heal seeds, every seeded shield scales on a CASTER stat
(max HP / max mana / bonus HP / AP / flat-per-level) that resolves NON-ZERO at the
default ``resolve_target_relative=False`` - so ``apply_passive_shield=True``
surfaces them without an HP assumption (like the linear caster-stat heal seeds).
No seeded shield is target-relative (a shield protects the CASTER, not scaled off
an enemy), so ``resolve_target_relative`` does not change any of them.

CONDITIONAL GATES NOT MODELED (the shield magnitude is gate-independent - the
Evelynn-P / Kayn-form precedent in the heal registry): Blitzcrank P (at 30% HP),
Camille P / Vi P (periodic internal cooldown), Volibear E (only if Volibear is
within the strike), Yasuo P (Flow-consume at full Flow + on taking damage). The
shield value is exact; routing the trigger to a live clock is a future job.

cadence field MEANING (metadata only - does NOT change the injected block):
  - "per_cast"  - a cooldown-bearing spell (Volibear E / Skarner W / Viktor Q /
                  Shen P after each ability) -> shield_per_sec is computed.
  - "per_fight" - a passive-P proc on an event with no fixed cadence (Malphite /
                  Camille / Vi / Rakan / Yasuo / Blitzcrank). A P-slot has no
                  cooldown so compute_ability_hps gives casts_per_sec 0 ->
                  shield_per_sec is honestly 0 (the per-cast shield is surfaced).

How it injects: ``to_shield_block(entry)`` builds a synthetic
``DamageBlock(attribute_kind="shield", raw_modifiers=(...linear...))``. A linear
``value`` that is a tuple becomes a per-rank ``values`` list (a P-slot per-level
lerp indexed at ``rank == level-1``; a SPELL-slot "based on level" shield sets
``level_scaled=True`` so the 18-element tuple is read at level not the spell rank
- Viktor Q). A flat float is a 1-element list (clamped at every rank). Keyed
``(champion_id, key, form_index)`` - same shape as ``_passive_heal_overrides``.

EXHAUSTED scan (all 171 champs, shield-verb forms with no shield block - 38
matches): the seedable SELF/ALLY-shield set is exactly these 10. Documented
EXCLUSIONS (scanned, deliberately NOT seeded - with the reason class):
  - SPELL SHIELD (a one-shot hostile-effect block, not a damage-absorb amount):
    Nocturne W Shroud of Darkness, Sivir E Spell Shield.
  - DAMAGE-STORED / grey-health / Grit conversion (a bespoke stored-damage
    barrier, not a flat/stat magnitude - same boundary as the heal registry's
    vamp class): Sett W (Grit), Mordekaiser W Indestructible (stored damage),
    Tahm Kench E grey health.
  - RE-GRANT of an existing structured shield (the magnitude is another spell's
    block - double-count): Galio R (resets/grants Galio W's Shield of Durand),
    Yuumi R (heal-overflow converted to an ally shield).
  - SHIELD-STRIP (destroys ENEMY shields, not a grant): Blitzcrank R, Rell Q.
  - shield-verb matched but NO self/ally shield-magnitude grant (weapon-flavor /
    damage-reduction / ability name / vamp / amp / damage passive): Akshan P,
    Ambessa W, Aphelios P (Severum vamp), Braum Q/E/R ("his shield" = weapon),
    Leona Q ("her shield" empower) / W (flat damage reduction), Malphite W
    (references the P shield), Mel P (damage store), Nilah P (shield-amp) /
    Q (vamp) / R, Pantheon W (ability name "Shield Vault") / E (directional
    invuln), Poppy P (buckler = damage passive), Renekton W (empowered-AA stun),
    Yone W (cleave), Yuumi W (untargetable empower).
"""
from __future__ import annotations

from dataclasses import dataclass

from ._passive_damage_overrides import _lerp_per_level, _per_100

# Import the engine DamageBlock lazily in to_shield_block (abilities.py imports
# this module after defining DamageBlock; a top-level import would be circular).


@dataclass(frozen=True)
class PassiveShieldEntry:
    """One hand-authored effects-text-only SHIELD formula.

    ``linear_terms`` is a tuple of ``(value, unit)`` pairs: ``value`` is a flat
    pct/amount (or a per-level/per-rank tuple) and ``unit`` is a heal/shield unit
    string (``""`` flat, ``"% maximum health"`` / ``"% ap"`` / ``"% bonus
    health"`` / ``"% maximum mana"`` from ``_HEAL_UNIT_TO_CTX``). Each becomes one
    ``raw_modifiers`` entry on the synthetic shield block, resolved by the EXISTING
    ``_eval_heal_shield_block`` unit machinery. Every seeded shield is caster-stat
    scaled (resolves at the default ctx; not target-relative).

    ``bilinear_terms`` is the optional item-248 ``(factor, ctx_attr_a,
    ctx_attr_b)`` product field (no current shield uses it; kept for parity with
    the heal entry + future-proofing the eval, which reads it for free).

    ``level_scaled`` (default False) - set True for a SPELL-slot (Q/W/E/R) shield
    whose magnitude scales "based on level" so the per-rank ``values`` list is
    read at champion level (``level-1``) not the spell rank (Viktor Q). P-slot
    shields already see ``rank == level-1`` so they leave it False.
    """

    linear_terms: tuple[tuple[float | tuple[float, ...], str], ...]
    cadence: str
    note: str
    attribute: str = "Passive Shield"
    bilinear_terms: tuple[tuple[float, str, str], ...] = ()
    level_scaled: bool = False


# (champion_id, key, form_index) -> PassiveShieldEntry.
# Seeded 2026-06-01 against verbatim effects_descriptions at patch 16.11.1.
_PASSIVE_SHIELD_OVERRIDES: dict[tuple[str, str, int], PassiveShieldEntry] = {
    # Malphite P Granite Shield: "Malphite grants himself a shield equal to 10%
    # of his maximum health. The shield lasts until it is broken, and refreshes
    # after a few seconds of not taking damage." flat 10% caster max HP, constant
    # across the game (a passive). per_fight (out-of-combat refresh).
    ("Malphite", "P", 0): PassiveShieldEntry(
        linear_terms=((10.0, "% maximum health"),),
        cadence="per_fight",
        note="Granite Shield: shield 10% of caster max HP (passive, refreshes out of combat); constant magnitude",
        attribute="Granite Shield",
    ),
    # Camille P Adaptive Defenses: "Periodically, Camille's next basic attack
    # on-hit against an enemy champion grants her a shield equal to 20% of her
    # maximum health, lasting for 2 seconds". flat 20% caster max HP. per_fight
    # (periodic on-hit-vs-champ; the internal-CD gate is not modeled - magnitude
    # is gate-independent).
    ("Camille", "P", 0): PassiveShieldEntry(
        linear_terms=((20.0, "% maximum health"),),
        cadence="per_fight",
        note="Adaptive Defenses: shield 20% of caster max HP on the periodic on-hit vs a champion; internal-CD gate not modeled (magnitude gate-independent)",
        attribute="Adaptive Defenses",
    ),
    # Vi P Blast Shield: "Periodically, Vi's next ability hit grants her a shield
    # equal to 12% of her maximum health for 3 seconds". flat 12% caster max HP.
    # per_fight (periodic on ability hit).
    ("Vi", "P", 0): PassiveShieldEntry(
        linear_terms=((12.0, "% maximum health"),),
        cadence="per_fight",
        note="Blast Shield: shield 12% of caster max HP on the periodic ability hit; internal-CD gate not modeled (magnitude gate-independent)",
        attribute="Blast Shield",
    ),
    # Rakan P Fey Feathers: "Periodically, Rakan grants himself a shield for
    # 30 : 225 (based on level) (+ 95% AP) that lasts until broken." flat
    # per-level lerp + 95% AP. P-slot (rank == level-1). per_fight (periodic,
    # restores out of combat).
    ("Rakan", "P", 0): PassiveShieldEntry(
        linear_terms=((_lerp_per_level(30.0, 225.0), ""), (95.0, "% ap")),
        cadence="per_fight",
        note="Fey Feathers: shield 30 : 225 (based on level) (+ 95% AP), periodic; restores out of combat",
        attribute="Fey Feathers",
    ),
    # Shen P Ki Barrier: "After completing an ability's effects, Shen grants
    # himself a shield for 47 : 120 (based on level) (+ 13% bonus health) for 2.5
    # seconds". flat per-level lerp + 13% bonus HP. P-slot. per_cast (after each
    # ability - has an internal cooldown reduced by affecting champs).
    ("Shen", "P", 0): PassiveShieldEntry(
        linear_terms=((_lerp_per_level(47.0, 120.0), ""), (13.0, "% bonus health")),
        cadence="per_cast",
        note="Ki Barrier: shield 47 : 120 (based on level) (+ 13% bonus health) after completing an ability",
        attribute="Ki Barrier",
    ),
    # Yasuo P Way of the Wanderer (Resolve): at full Flow + on taking champion/
    # monster damage, "Yasuo consumes all Flow to grant himself a shield for
    # 125 : 600 (based on level) that lasts for 1 second". flat per-level lerp.
    # P-slot. per_fight (Flow-consume gate not modeled - magnitude gate-
    # independent; the Intent crit-conversion half of the passive is not a shield).
    ("Yasuo", "P", 0): PassiveShieldEntry(
        linear_terms=((_lerp_per_level(125.0, 600.0), ""),),
        cadence="per_fight",
        note="Way of the Wanderer (Resolve): shield 125 : 600 (based on level) on the full-Flow consume when taking damage; Flow gate not modeled (magnitude gate-independent)",
        attribute="Way of the Wanderer",
    ),
    # Blitzcrank P Mana Barrier: "Periodically, when damaged to 30% maximum
    # health, Blitzcrank generates a shield equal to 35% of maximum mana, lasting
    # for up to 10 seconds." 35% caster MAX MANA. per_fight (HP-threshold gate
    # not modeled - magnitude gate-independent). Uses the additive
    # "% maximum mana" -> caster_max_mp unit (the sole mana-scaled shield; the
    # ctx attr already exists, no snapshot block uses a mana unit -> byte-
    # identical on the default path).
    ("Blitzcrank", "P", 0): PassiveShieldEntry(
        linear_terms=((35.0, "% maximum mana"),),
        cadence="per_fight",
        note="Mana Barrier: shield 35% of caster max MANA at 30% HP; HP-threshold gate not modeled (magnitude gate-independent); sole mana-scaled shield (% maximum mana -> caster_max_mp)",
        attribute="Mana Barrier",
    ),
    # ---- SPELL-slot effects-text shields (no shield block; the form carries a
    # damage block, so the no-existing-shield-block gate admits the synthetic
    # shield without touching the damage blocks - compute_ability_dps unaffected).
    # ----
    # Skarner W Seismic Bastion: "Skarner slams his claws into the ground,
    # shielding himself equal to 8% of his maximum health for 2.5 seconds". flat
    # 8% caster max HP, constant across W ranks. per_cast (W has a cooldown).
    ("Skarner", "W", 0): PassiveShieldEntry(
        linear_terms=((8.0, "% maximum health"),),
        cadence="per_cast",
        note="Seismic Bastion: shield 8% of caster max HP on W cast (constant across ranks)",
        attribute="Seismic Bastion",
    ),
    # Volibear E Sky Splitter: "If Volibear is within the strike, he gains a
    # shield equal to 14% of his maximum health (+ 75% AP) for 3 seconds". flat
    # 14% caster max HP + 75% AP, constant across E ranks. per_cast (E cooldown).
    # The within-strike gate is not modeled (magnitude gate-independent).
    ("Volibear", "E", 0): PassiveShieldEntry(
        linear_terms=((14.0, "% maximum health"), (75.0, "% ap")),
        cadence="per_cast",
        note="Sky Splitter: shield 14% of caster max HP (+ 75% AP) if Volibear is within the strike; within-strike gate not modeled (magnitude gate-independent); constant across ranks",
        attribute="Sky Splitter",
    ),
    # Viktor Q Siphon Power: "He also grants himself a shield for 40 : 115 (based
    # on level) (+ 18% AP) for 2.5 seconds". flat per-level lerp + 18% AP. SPELL
    # slot scaling BY LEVEL (not Q rank) -> level_scaled=True. per_cast. The
    # Turbocharge AUGMENT increase (to 64 : 184 + 32% AP) is OMITTED (augment-
    # gated, not the base shield).
    ("Viktor", "Q", 0): PassiveShieldEntry(
        linear_terms=((_lerp_per_level(40.0, 115.0), ""), (18.0, "% ap")),
        cadence="per_cast",
        note="Siphon Power: shield 40 : 115 (based on level) (+ 18% AP) on Q cast; SPELL-slot level-scaled (level_scaled indexes by level not Q rank); Turbocharge augment increase omitted",
        attribute="Siphon Power",
        level_scaled=True,
    ),
}

# Re-export _per_100 so a future bilinear (AP*HP) shield can author with it
# (parity with the heal registry); currently no seeded shield uses it.
__all__ = ["PassiveShieldEntry", "_PASSIVE_SHIELD_OVERRIDES", "to_shield_block", "_per_100"]


def to_shield_block(entry: PassiveShieldEntry):
    """Build a synthetic ``DamageBlock(attribute_kind="shield", ...)`` from a
    ``PassiveShieldEntry``.

    The block carries the LINEAR terms in ``raw_modifiers`` (the ``{values,
    units}`` shape ``_eval_heal_shield_block`` parses) and any ``bilinear_terms``
    (the item-248 field; no current shield uses it). A linear ``value`` that is a
    tuple is emitted as a per-rank ``values`` list; a flat float is a 1-element
    list (``_value_at_rank`` clamps it to that value at every rank).

    Imported lazily to avoid the abilities.py circular import.
    """
    from .abilities import DamageBlock

    def _values_list(v: float | tuple[float, ...]) -> list[float]:
        if isinstance(v, (tuple, list)):
            return [float(x) for x in v] or [0.0]
        return [float(v)]

    raw_modifiers = tuple(
        {"values": _values_list(value), "units": [str(unit)]}
        for (value, unit) in entry.linear_terms
    )
    bilinear_terms = tuple(
        (float(factor), str(attr_a), str(attr_b))
        for (factor, attr_a, attr_b) in entry.bilinear_terms
    )
    return DamageBlock(
        attribute=entry.attribute,
        attribute_kind="shield",
        raw_modifiers=raw_modifiers,
        bilinear_terms=bilinear_terms,
        level_scaled=entry.level_scaled,
    )
