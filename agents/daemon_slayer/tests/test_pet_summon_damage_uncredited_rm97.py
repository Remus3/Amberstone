"""RM-97 CHARACTERIZATION PIN - persistent pet / summon damage is UNCREDITED.

This file is a CHARACTERIZATION test of a KNOWN GAP, not a correctness test.
It pins the CURRENT Daemon Slayer behavior so the gap cannot close silently.

The gap (RM-97, SPEC-ONLY - no engine change has ever shipped for it): the
ability-damage lane has no PERSISTENT-ENTITY uptime model. A pet, plant,
turret, ghoul, or voidling that stands on the map and auto-attacks for a
duration contributes ZERO to ``compute_ability_dps`` because Meraki ships no
per-tick damage row for it - the pet-bearing form simply carries no
``attribute_kind == "damage"`` block at all. For Zyra that silently drops the
majority of her real damage output (the plants), and the same shape holds for
Heimerdinger turrets, Ivern's Daisy, and Yorick's ghouls + Maiden.

The gap is specifically about SUSTAINED PET UPTIME, NOT about summons in
general. Where Meraki DOES ship a one-shot number attached to the summoning
cast - Annie R's initial Tibbers impact, Malzahar W's voidling-spawn magic
damage, Elise W's spiderling explosion - the engine credits it normally. The
``CREDITED_SUMMON_BURST_FORMS`` table below pins exactly that, so a future
reader cannot mis-read this file as "no summon ever scores".

CONTRAST - the NON-damage axes already model summons explicitly, which is what
makes the damage-lane silence a gap rather than a deliberate roster-wide
policy:

* ``agents/daemon_slayer/objdamage.py`` lines 79-83 / 92 - ``SUMMON_DPS``
  weight 0.55, prose naming "Heimerdinger turrets / Yorick ghouls + Maiden /
  Malzahar voidlings / Annie Tibbers / Elise spiders / Zyra plants /
  Ivern Daisy".
* ``agents/daemon_slayer/zonecontrol.py`` lines 73-77 - ``SUMMON`` weight
  0.60, naming the same population.

WHAT A RED HERE MEANS: a pet-damage lane LANDED. This file is expected to go
red the day the engine starts crediting persistent-entity damage. Do NOT
"fix" it by loosening an assertion - update the pin deliberately, in the same
slice that ships the lane, and re-state what the new behavior is.

OBSERVED-NOT-ASSUMED note on the "P" spell key: ``ability_dps.SPELL_KEYS`` is
``("Q", "W", "E", "R")`` (``agents/daemon_slayer/ability_dps.py:209``), so the
passive row is ABSENT from ``result.per_spell`` rather than present-and-zero.
This file pins the ABSENCE, because absence is what was measured. Zyra's
passive (Garden of Thorns - the plant seeds) therefore never even reaches the
block filter.

Engine seams pinned:

* ``agents/daemon_slayer/abilities.py:274`` ``AbilityForm.damage_blocks_only``
  - the ``attribute_kind == "damage"`` filter.
* ``agents/daemon_slayer/ability_dps.py:459`` ``_select_blocks`` - re-applies
  the same filter and returns ``0.0`` when nothing survives it.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import ult_rates
from agents.daemon_slayer.abilities import AbilitiesSnapshot, reset_default_cache
from agents.daemon_slayer.ability_dps import SPELL_KEYS, compute_ability_dps
from agents.daemon_slayer.data_loader import DataSnapshot

# --- the filed RM-97 population ----------------------------------------------
# (champion_id, spell_key, form_index, form_name)
#
# Every row is a form whose ENTIRE gameplay payload is a persistent autonomous
# entity. Each carries ZERO attribute_kind == "damage" blocks today.
PET_BEARING_FORMS_ZERO_DAMAGE = (
    ("Zyra", "P", 0, "Garden of Thorns"),          # the plants: most of her damage
    ("Zyra", "W", 0, "Rampant Growth"),            # seeds / plant spawn
    ("Heimerdinger", "Q", 0, "H-28G Evolution Turret"),
    ("Heimerdinger", "Q", 1, "H-28Q Apex Turret"),  # R-upgraded turret form
    ("Ivern", "R", 0, "Daisy!"),
    ("Yorick", "P", 0, "Shepherd of Souls"),       # Mist Walker ghouls
    ("Yorick", "R", 0, "Eulogy of the Isles"),     # the Maiden of the Mist
)

# --- the contrast population -------------------------------------------------
# Summon casts that DO carry exactly one damage block, because Meraki ships a
# one-shot number for the summoning event itself. The persistent entity that
# each of these spawns is still uncredited - only the burst is scored.
# (champion_id, spell_key, form_index, form_name, damage_block_attribute)
CREDITED_SUMMON_BURST_FORMS = (
    ("Malzahar", "W", 0, "Void Swarm", "Magic Damage"),
    ("Annie", "R", 0, "Summon: Tibbers", "Initial Magic Damage"),
    ("Elise", "W", 0, "Volatile Spiderling", "Magic Damage"),
)

# Zyra engine-pin fixture. Level 11 puts Q at max rank, W at rank 2, E at
# rank 0 and R at rank 1 - every slot is unlocked, so a zero can only come
# from the block filter, never from a locked ability.
_ZYRA_LEVEL = 11
_ZYRA_TARGET_ARMOR = 30.0
_ZYRA_TARGET_MR = 30.0


class _Rm97Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        reset_default_cache()
        ult_rates.reset_cache()
        cls.abilities = AbilitiesSnapshot.load()
        cls.snap = DataSnapshot.load()


class PetBearingFormsCarryNoDamageBlocksTests(_Rm97Base):
    """Data-shape pin - the filed RM-97 forms carry zero damage blocks."""

    def test_named_form_resolves_at_expected_index(self) -> None:
        # Pin the NAME too: if Riot renames or re-orders a form, this fails
        # loudly rather than silently pinning a different ability.
        for cid, key, form_index, form_name in PET_BEARING_FORMS_ZERO_DAMAGE:
            with self.subTest(champion=cid, key=key, form=form_name):
                form = self.abilities.get_ability(cid, key, form_index)
                self.assertEqual(form.name, form_name)

    def test_zero_damage_kind_blocks(self) -> None:
        for cid, key, form_index, form_name in PET_BEARING_FORMS_ZERO_DAMAGE:
            with self.subTest(champion=cid, key=key, form=form_name):
                form = self.abilities.get_ability(cid, key, form_index)
                self.assertEqual(
                    form.damage_blocks_only(),
                    (),
                    f"{cid} {key} '{form_name}' gained a damage block - a "
                    f"pet-damage lane may have landed (RM-97). Update this "
                    f"pin deliberately.",
                )

    def test_no_damage_kind_block_survives_the_kind_filter(self) -> None:
        # Independent of damage_blocks_only(): assert directly on the raw
        # attribute_kind values so the pin does not depend on that one helper.
        for cid, key, form_index, form_name in PET_BEARING_FORMS_ZERO_DAMAGE:
            with self.subTest(champion=cid, key=key, form=form_name):
                form = self.abilities.get_ability(cid, key, form_index)
                kinds = [b.attribute_kind for b in form.damage_blocks]
                self.assertNotIn("damage", kinds)


class YorickUltCountBlockIsNotDamageTests(_Rm97Base):
    """Near-miss pin - Yorick R block 0 is a COUNT, correctly kind 'other'.

    This is the one row in the population that is not simply empty. Yorick R
    ships exactly one block, "Mist Walkers", whose values are a UNIT COUNT
    (how many ghouls the Maiden raises), not a damage number. It sits at
    index 0, which is precisely where ``_select_blocks``'s ``"first"``
    strategy reads. If the ``attribute_kind == "damage"`` filter were ever
    removed or widened, this count would be evaluated as raw damage.
    """

    def test_yorick_r_has_exactly_one_block_and_it_is_other(self) -> None:
        form = self.abilities.get_ability("Yorick", "R", 0)
        self.assertEqual(form.name, "Eulogy of the Isles")
        self.assertEqual(len(form.damage_blocks), 1)
        block = form.damage_blocks[0]
        self.assertEqual(block.attribute, "Mist Walkers")
        self.assertEqual(block.attribute_kind, "other")

    def test_yorick_r_count_block_is_excluded_from_damage(self) -> None:
        form = self.abilities.get_ability("Yorick", "R", 0)
        self.assertEqual(form.damage_blocks_only(), ())


class CreditedSummonBurstTests(_Rm97Base):
    """Contrast pin - summon CASTS with a one-shot number DO score.

    Records that the gap is "no PERSISTENT-ENTITY uptime model", NOT "no
    summon ever scores".
    """

    def test_each_credited_form_has_exactly_one_damage_block(self) -> None:
        for cid, key, form_index, form_name, attr in CREDITED_SUMMON_BURST_FORMS:
            with self.subTest(champion=cid, key=key, form=form_name):
                form = self.abilities.get_ability(cid, key, form_index)
                self.assertEqual(form.name, form_name)
                damage = form.damage_blocks_only()
                self.assertEqual(len(damage), 1)
                self.assertEqual(damage[0].attribute, attr)
                self.assertEqual(damage[0].attribute_kind, "damage")

    def test_malzahar_w_non_damage_siblings_are_not_credited(self) -> None:
        # Void Swarm ships three blocks; only the middle one is damage. The
        # voidling DURATION (the pet-uptime signal RM-97 would need) and the
        # minion-damage MODIFIER are both filtered out.
        form = self.abilities.get_ability("Malzahar", "W", 0)
        kinds = {b.attribute: b.attribute_kind for b in form.damage_blocks}
        self.assertEqual(kinds.get("Voidling Duration"), "duration")
        self.assertEqual(kinds.get("Minion Damage"), "modifier")
        self.assertEqual(kinds.get("Magic Damage"), "damage")

    def test_annie_r_summon_burst_credited_but_tibbers_autos_are_not(self) -> None:
        # Annie R's only damage block is the INITIAL impact. Tibbers' own
        # persistent auto-attacks and his burn aura have no block at all.
        form = self.abilities.get_ability("Annie", "R", 0)
        damage = form.damage_blocks_only()
        self.assertEqual(len(damage), 1)
        self.assertEqual(damage[0].attribute, "Initial Magic Damage")


class ZyraAbilityDpsEnginePinTests(_Rm97Base):
    """Engine pin - the real ``compute_ability_dps`` scores Zyra's pets at 0.

    Measured values at level 11 / SR / 30 armor / 30 MR, no items:

        P -> ABSENT from per_spell (SPELL_KEYS excludes "P")
        W -> 0.0
        Q -> 9.147609147609147
        E -> 1.2968849332485697
        R -> 1.0865999671969822

    Only the ZEROS and the ABSENCE are asserted exactly; Q/E/R are asserted
    as strictly positive rather than pinned to their literal magnitudes, so
    an unrelated base-damage or cast-rate retune does not falsely red this
    file. The point of the pin is the shape, not the numbers.
    """

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.result = compute_ability_dps(
            cls.snap,
            "Zyra",
            _ZYRA_LEVEL,
            mode="SR",
            target_armor=_ZYRA_TARGET_ARMOR,
            target_mr=_ZYRA_TARGET_MR,
        )

    def test_passive_row_is_absent_not_zero(self) -> None:
        # OBSERVED behavior: ability_dps.SPELL_KEYS == ("Q", "W", "E", "R").
        # Zyra's plant-seeding passive never gets a per_spell row at all.
        self.assertEqual(SPELL_KEYS, ("Q", "W", "E", "R"))
        keys = tuple(s.key for s in self.result.per_spell)
        self.assertEqual(keys, ("Q", "W", "E", "R"))
        self.assertNotIn("P", keys)

    def test_w_rampant_growth_scores_exactly_zero(self) -> None:
        w = next(s for s in self.result.per_spell if s.key == "W")
        # W is unlocked at this level - the zero is the block filter, not a
        # locked ability.
        self.assertGreaterEqual(w.rank, 0)
        self.assertEqual(w.dps, 0.0)

    def test_q_e_r_all_score_positive(self) -> None:
        for key in ("Q", "E", "R"):
            with self.subTest(key=key):
                row = next(s for s in self.result.per_spell if s.key == key)
                self.assertGreaterEqual(row.rank, 0)
                self.assertGreater(row.dps, 0.0)

    def test_total_equals_the_three_non_pet_rows(self) -> None:
        # The pet lane contributes literally nothing to the total: summing the
        # three scoring rows reproduces it exactly.
        non_pet = sum(s.dps for s in self.result.per_spell if s.key != "W")
        self.assertAlmostEqual(self.result.total_ability_dps, non_pet, places=9)
        self.assertGreater(self.result.total_ability_dps, 0.0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
