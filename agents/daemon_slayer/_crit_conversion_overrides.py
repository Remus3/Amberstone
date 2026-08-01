"""2026-07-25 (A-12 / RM-46) - per-champion CRIT CONVERSION registry.

A small class of champions do NOT crit the way the engine's universal auto-attack
model assumes. ``dps.py`` resolves every champion's basic attack as::

    ad * (1 + crit * crit_bonus)
    crit_bonus = DEFAULT_CRIT_BONUS (0.75) + total_crit_damage_bonus(items)

Ashe is the canonical (currently only) counter-example. Her innate ``Frost Shot``
CONVERTS critical strike chance into flat bonus physical damage and removes the
critical strike itself, so BOTH halves of the universal model are wrong for her:

  * the conversion factor is 0.75 + 0.40 = 1.15, not 0.75 - the engine returns
    1.75x AD at c=1.00 where the correct value is 2.15x, a 22.9 pct
    UNDER-valuation of her crit (2.15 / 1.75 = 1.2286);
  * "Critical strikes do not deal any additional damage" makes every item
    crit-damage bonus (Infinity Edge +0.30) INERT on her, so the conversion
    factor REPLACES the item sum instead of adding to it.

Net effect of modelling this: her crit items ALL rise (1.15 > 0.75); what the
model correctly does is demote Infinity Edge RELATIVE to pure crit-chance items,
because IE's crit-damage half stops paying her.

CONSUMER: ``dps.compute_dps(apply_crit_conversion=True)`` - DEFAULT-OFF. With the
flag omitted (the default) NOTHING in this module is imported or read and every
champion, Ashe included, is byte-identical to the pre-seam engine. The live
default-ON flip stays validation-gated (do-not-flip-blind), same posture as the
sibling ``apply_melee_aa_gate`` / ``assume_passive_as_stacks`` seams; the shipped
build tables are additionally unreachable today because ``rank.py`` has no
crit-conversion parameter and the table generator drives ``:8860``.

WHY AN EXPLICIT DICT, not a parsed rule: the DDragon innate prose that carries
the numbers ("(75% + 40%) critical strike chance") is free text that is rewritten
most patches, and no structured Meraki / DDragon field encodes "this champion
cannot critically strike". A text rule would silently mis-key any champion whose
passive merely MENTIONS crit (Yasuo's doubled crit chance, Jhin's AS/crit -> AD
lock, Senna's crit-to-range conversion) - each of those is a DIFFERENT mechanic
with its own registry (``_passive_as_lock_overrides`` holds Jhin). Entries here
are hand-authored from the verbatim cited fragment, one champion at a time.

``crit_denied_item_ids`` is the third term of the row. DDragon's Ashe passive
notes state verbatim: "Runaan's Hurricane's will not deal additional damage on
critical strikes." Any proc riding a denied item is therefore resolved against a
crit_chance=0.0 context, so a crit-scaling on-hit rider can never be credited the
converted crit. Runaan's own ``Wind's Fury`` proc is a flat ``2 x 55% total AD``
with no crit term (``_effects_data.py:184-202``), so the shipped 3085 / 223085
entry measures as a REGRESSION GUARD rather than a numeric demotion today - it
pins the invariant that a future re-model of the bolts cannot quietly hand Ashe
the Frost bonus twice. The mechanism itself is live and is proven to bite in
``tests/test_crit_conversion_ashe_rm46.py`` against Essence Reaver, whose proc
does read ``CallContext.crit_chance``.

GROUND TRUTH: ``data/daemon_slayer/16.14.1/champion_abilities.json`` -> data ->
Ashe -> P (patch 16.14.1), verbatim:
  effects_descriptions[0]: "Innate: Ashe's basic attacks deal bonus physical
    damage equal to (75% + 40%) critical strike chance. Critical strikes do not
    deal any additional damage."
  notes: "Ashe's critical strikes are still considered critical strike damage and
    thus will be reduced by Randuin's Omen's Resilience.\n Runaan's Hurricane's
    will not deal additional damage on critical strikes. ..."
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# 75% + 40% from the verbatim innate line above. Named so the test can pin the
# literal without re-deriving it from the entry.
_ASHE_FROST_SHOT_FACTOR = 1.15


@dataclass(frozen=True)
class CritConversionEntry:
    """One champion's crit-conversion override.

    crit_bonus: the multiplier applied to resolved crit chance in the auto-attack
      term ``ad * (1 + crit * crit_bonus)``. For a conversion champion this is
      the innate's flat bonus-damage ratio, NOT a critical strike multiplier.
    replaces_item_crit_damage: when True (the conversion case) the value above
      REPLACES ``DEFAULT_CRIT_BONUS + total_crit_damage_bonus(items)``, so an
      item crit-damage bonus contributes nothing. When False it is ADDED to the
      item sum instead - reserved for a future champion whose innate stacks with
      real critical strikes; no entry uses it today.
    crit_denied_item_ids: item ids whose on-hit procs must be resolved with
      crit_chance=0.0 for this champion (see the module note).
    """

    champion_id: str
    crit_bonus: float
    note: str
    replaces_item_crit_damage: bool = True
    crit_denied_item_ids: frozenset[str] = field(default_factory=frozenset)


_CRIT_CONVERSION: dict[str, CritConversionEntry] = {
    "Ashe": CritConversionEntry(
        champion_id="Ashe",
        crit_bonus=_ASHE_FROST_SHOT_FACTOR,
        replaces_item_crit_damage=True,
        # SR 3085 plus the Arena mirror 223085 (same Wind's Fury proc,
        # _effects_data.py:4272-4285).
        crit_denied_item_ids=frozenset({"3085", "223085"}),
        note=(
            "Frost Shot (P): basic attacks deal bonus physical damage equal to "
            "(75% + 40%) critical strike chance; critical strikes do not deal "
            "any additional damage. Runaan's Hurricane bolts are denied the "
            "conversion per the same passive's notes."
        ),
    ),
}


def crit_conversion_entry(champion_id: str) -> Optional[CritConversionEntry]:
    """Return the champion's crit-conversion entry, or None when unregistered.

    None is the overwhelmingly common answer (172 of 173 champions), and every
    consumer must treat it as "use the universal crit model unchanged".
    """
    return _CRIT_CONVERSION.get(champion_id)


def resolve_crit_bonus(
    champion_id: str, engine_crit_bonus: float
) -> tuple[float, Optional[CritConversionEntry]]:
    """Resolve the auto-attack crit factor for a champion.

    ``engine_crit_bonus`` is the universal value the caller already computed
    (``DEFAULT_CRIT_BONUS + total_crit_damage_bonus(item_effects)``). Returns it
    unchanged with a None entry for any unregistered champion, so the caller's
    default path stays a single dict lookup.
    """
    entry = _CRIT_CONVERSION.get(champion_id)
    if entry is None:
        return engine_crit_bonus, None
    if entry.replaces_item_crit_damage:
        return entry.crit_bonus, entry
    return engine_crit_bonus + entry.crit_bonus, entry
