"""Item 261 - effects-text-only DAMAGE-REDUCTION (mitigation) registry tests.

The survivability-triad sibling of the effects-text HEAL (items 250-254) +
SHIELD (item 260) registries, but for the EHP DENOMINATOR: a flat-% damage
reduction folds multiplicatively into compute_ehp's physical/magical/true EHP.
``apply_passive_mitigation`` defaults False -> byte-identical to ENGINE 1.90.0.

Seeded 5 (1 permanent + 4 active): Kassadin P (10% magic), Nilah W (25% magic),
KSante W (30% all), Briar E (35% all), Irelia W (phys 40:70 + magic 20:35
level-scaled). The 4 actives amortize by conditional_probability=0.3.
"""
from __future__ import annotations

import unittest

import agents.daemon_slayer as daemon_slayer
from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import compute_ehp, rank_items_by_ehp
from agents.daemon_slayer._passive_damage_overrides import _lerp_per_level
from agents.daemon_slayer._passive_mitigation_overrides import (
    ANY,
    MAG,
    PHYS,
    TRUE,
    PassiveMitigationEntry,
    _ACTIVE_DR_PROB,
    _PASSIVE_MITIGATION_OVERRIDES,
    _value_at_level,
    mitigation_multipliers,
)

_SNAP = DataSnapshot.load()


def _ehp(cid, lvl=11, items=(), **kw):
    return compute_ehp(_SNAP, champion_id=cid, level=lvl, item_ids=items, mode="SR", **kw)


class RegistryShapeTests(unittest.TestCase):
    def test_exactly_five_seeds(self):
        self.assertEqual(len(_PASSIVE_MITIGATION_OVERRIDES), 5)

    def test_keys_are_the_seeded_set(self):
        self.assertEqual(
            set(_PASSIVE_MITIGATION_OVERRIDES),
            {
                ("Kassadin", "P", 0),
                ("Nilah", "W", 0),
                ("KSante", "W", 0),
                ("Briar", "E", 0),
                ("Irelia", "W", 0),
            },
        )

    def test_every_term_type_is_valid(self):
        valid = {PHYS, MAG, TRUE, ANY}
        for entry in _PASSIVE_MITIGATION_OVERRIDES.values():
            for (_pct, dtype) in entry.terms:
                self.assertIn(dtype, valid)

    def test_probability_in_unit_interval(self):
        for entry in _PASSIVE_MITIGATION_OVERRIDES.values():
            self.assertGreaterEqual(entry.conditional_probability, 0.0)
            self.assertLessEqual(entry.conditional_probability, 1.0)

    def test_every_entry_has_a_note(self):
        for entry in _PASSIVE_MITIGATION_OVERRIDES.values():
            self.assertTrue(entry.note.strip())

    def test_kassadin_is_permanent_prob_one(self):
        self.assertEqual(
            _PASSIVE_MITIGATION_OVERRIDES[("Kassadin", "P", 0)].conditional_probability,
            1.0,
        )

    def test_actives_use_the_amortized_midpoint(self):
        for key in (("Nilah", "W", 0), ("KSante", "W", 0), ("Briar", "E", 0), ("Irelia", "W", 0)):
            self.assertEqual(
                _PASSIVE_MITIGATION_OVERRIDES[key].conditional_probability,
                _ACTIVE_DR_PROB,
            )

    def test_only_irelia_is_level_scaled(self):
        for key, entry in _PASSIVE_MITIGATION_OVERRIDES.items():
            self.assertEqual(entry.level_scaled, key == ("Irelia", "W", 0))


class ValueAtLevelTests(unittest.TestCase):
    def test_flat_pct_returns_itself(self):
        self.assertEqual(_value_at_level(10.0, 11, False), 10.0)

    def test_level_scaled_indexes_by_level(self):
        pl = _lerp_per_level(40.0, 70.0)
        self.assertEqual(_value_at_level(pl, 1, True), pl[0])
        self.assertEqual(_value_at_level(pl, 11, True), pl[10])
        self.assertEqual(_value_at_level(pl, 18, True), pl[17])

    def test_level_clamps_above_eighteen(self):
        pl = _lerp_per_level(40.0, 70.0)
        self.assertEqual(_value_at_level(pl, 99, True), pl[-1])

    def test_level_clamps_below_one(self):
        pl = _lerp_per_level(40.0, 70.0)
        self.assertEqual(_value_at_level(pl, 0, True), pl[0])


class MitigationMultipliersTests(unittest.TestCase):
    def test_flag_off_returns_identity_for_a_seed(self):
        self.assertEqual(mitigation_multipliers("Kassadin", 11, False), (1.0, 1.0, 1.0))

    def test_flag_off_returns_identity_for_non_seed(self):
        self.assertEqual(mitigation_multipliers("Garen", 11, False), (1.0, 1.0, 1.0))

    def test_unregistered_champ_is_identity_even_flag_on(self):
        self.assertEqual(mitigation_multipliers("Garen", 11, True), (1.0, 1.0, 1.0))

    def test_kassadin_magic_only(self):
        mp, mm, mt = mitigation_multipliers("Kassadin", 11, True)
        self.assertAlmostEqual(mp, 1.0)
        self.assertAlmostEqual(mm, 0.90)  # 1 - 0.10 * 1.0
        self.assertAlmostEqual(mt, 1.0)

    def test_nilah_magic_active_amortized(self):
        mp, mm, mt = mitigation_multipliers("Nilah", 11, True)
        self.assertAlmostEqual(mp, 1.0)
        self.assertAlmostEqual(mm, 1.0 - 0.25 * _ACTIVE_DR_PROB)  # 0.925
        self.assertAlmostEqual(mt, 1.0)

    def test_ksante_any_all_three(self):
        mp, mm, mt = mitigation_multipliers("KSante", 11, True)
        exp = 1.0 - 0.30 * _ACTIVE_DR_PROB  # 0.91
        self.assertAlmostEqual(mp, exp)
        self.assertAlmostEqual(mm, exp)
        self.assertAlmostEqual(mt, exp)

    def test_briar_any_all_three(self):
        mp, mm, mt = mitigation_multipliers("Briar", 11, True)
        exp = 1.0 - 0.35 * _ACTIVE_DR_PROB  # 0.895
        self.assertAlmostEqual(mp, exp)
        self.assertAlmostEqual(mm, exp)
        self.assertAlmostEqual(mt, exp)

    def test_irelia_level_scaled_split(self):
        pl = _lerp_per_level(40.0, 70.0)
        ml = _lerp_per_level(20.0, 35.0)
        for lvl in (1, 11, 18):
            mp, mm, mt = mitigation_multipliers("Irelia", lvl, True)
            self.assertAlmostEqual(mp, 1.0 - pl[lvl - 1] / 100.0 * _ACTIVE_DR_PROB)
            self.assertAlmostEqual(mm, 1.0 - ml[lvl - 1] / 100.0 * _ACTIVE_DR_PROB)
            self.assertAlmostEqual(mt, 1.0)

    def test_all_multipliers_in_unit_interval(self):
        for cid in ("Kassadin", "Nilah", "KSante", "Briar", "Irelia"):
            for lvl in (1, 6, 11, 18):
                for m in mitigation_multipliers(cid, lvl, True):
                    self.assertGreater(m, 0.0)
                    self.assertLessEqual(m, 1.0)


class ComputeEhpByteIdenticalTests(unittest.TestCase):
    def test_default_flag_off_is_default_param(self):
        # compute_ehp default path must not require the flag.
        r = _ehp("Kassadin")
        self.assertEqual(r.passive_mitigation_mag, 1.0)

    def test_every_seed_flag_off_byte_identical(self):
        for cid in ("Kassadin", "Nilah", "KSante", "Briar", "Irelia"):
            off = _ehp(cid)
            on_default = _ehp(cid, apply_passive_mitigation=False)
            self.assertEqual(off.blended_ehp, on_default.blended_ehp)
            self.assertEqual(off.physical_ehp, on_default.physical_ehp)
            self.assertEqual(off.magical_ehp, on_default.magical_ehp)

    def test_non_dr_champ_flag_on_byte_identical(self):
        # R35: Garen moved OUT of this set - its W carries a snapshot percent-DR
        # block now consumed via compute_ehp, so the flag is no longer a no-op
        # for it. Ashe / Caitlyn / Lux carry no DR in either registry.
        for cid in ("Ashe", "Caitlyn", "Lux"):
            off = _ehp(cid)
            on = _ehp(cid, apply_passive_mitigation=True)
            self.assertEqual(off.blended_ehp, on.blended_ehp)
            self.assertEqual(off.physical_ehp, on.physical_ehp)
            self.assertEqual(off.magical_ehp, on.magical_ehp)
            self.assertEqual(on.passive_mitigation_phys, 1.0)
            self.assertEqual(on.passive_mitigation_mag, 1.0)


class ComputeEhpFlagOnTests(unittest.TestCase):
    def test_kassadin_magical_ehp_grows_exactly(self):
        off = _ehp("Kassadin")
        on = _ehp("Kassadin", apply_passive_mitigation=True)
        # 10% magic DR -> magical EHP / (1 - 0.10) = x1.1111...
        self.assertAlmostEqual(on.magical_ehp, off.magical_ehp / 0.90, places=3)
        # physical + true unchanged (magic-only DR)
        self.assertEqual(on.physical_ehp, off.physical_ehp)
        self.assertEqual(on.true_ehp, off.true_ehp)
        self.assertAlmostEqual(on.passive_mitigation_mag, 0.90)

    def test_dr_strictly_increases_ehp(self):
        # a damage reduction can only raise EHP (smaller divisor).
        for cid in ("Kassadin", "Nilah", "KSante", "Briar", "Irelia"):
            off = _ehp(cid)
            on = _ehp(cid, apply_passive_mitigation=True)
            self.assertGreater(on.blended_ehp, off.blended_ehp)

    def test_ksante_all_three_axes_grow(self):
        off = _ehp("KSante")
        on = _ehp("KSante", apply_passive_mitigation=True)
        self.assertGreater(on.physical_ehp, off.physical_ehp)
        self.assertGreater(on.magical_ehp, off.magical_ehp)
        self.assertGreater(on.true_ehp, off.true_ehp)

    def test_nilah_only_magic_axis_grows(self):
        off = _ehp("Nilah")
        on = _ehp("Nilah", apply_passive_mitigation=True)
        self.assertEqual(on.physical_ehp, off.physical_ehp)
        self.assertGreater(on.magical_ehp, off.magical_ehp)
        self.assertEqual(on.true_ehp, off.true_ehp)

    def test_irelia_phys_and_magic_grow_true_unchanged(self):
        off = _ehp("Irelia")
        on = _ehp("Irelia", apply_passive_mitigation=True)
        self.assertGreater(on.physical_ehp, off.physical_ehp)
        self.assertGreater(on.magical_ehp, off.magical_ehp)
        self.assertEqual(on.true_ehp, off.true_ehp)

    def test_note_emitted_only_when_applied(self):
        on = _ehp("Kassadin", apply_passive_mitigation=True)
        self.assertTrue(any("passive_mitigation" in n for n in on.notes))
        off = _ehp("Kassadin")
        self.assertFalse(any("passive_mitigation" in n for n in off.notes))

    def test_to_dict_carries_fields(self):
        d = _ehp("Kassadin", apply_passive_mitigation=True).to_dict()
        self.assertIn("passive_mitigation_phys", d)
        self.assertIn("passive_mitigation_mag", d)
        self.assertIn("passive_mitigation_true", d)
        self.assertAlmostEqual(d["passive_mitigation_mag"], 0.90)


class RankItemsByEhpTests(unittest.TestCase):
    def test_default_off_byte_identical(self):
        off = rank_items_by_ehp(_SNAP, "Kassadin", 11, mode="SR", top_n=10)
        on_default = rank_items_by_ehp(
            _SNAP, "Kassadin", 11, mode="SR", top_n=10, apply_passive_mitigation=False
        )
        self.assertEqual(
            [(r.item_id, r.delta_ehp) for r in off.ranked],
            [(r.item_id, r.delta_ehp) for r in on_default.ranked],
        )

    def test_flag_on_grows_baseline_for_dr_champ(self):
        off = rank_items_by_ehp(_SNAP, "Kassadin", 11, mode="SR", top_n=5)
        on = rank_items_by_ehp(
            _SNAP, "Kassadin", 11, mode="SR", top_n=5, apply_passive_mitigation=True
        )
        # Kassadin's magic DR raises baseline EHP so each item's delta grows too.
        self.assertGreater(on.baseline_ehp, off.baseline_ehp)

    def test_flag_on_non_dr_champ_byte_identical(self):
        # R35: Ashe (no DR in either registry) replaces Garen here - Garen's W
        # now folds a snapshot percent-DR block, so it is no longer DR-free.
        off = rank_items_by_ehp(_SNAP, "Ashe", 11, mode="SR", top_n=8)
        on = rank_items_by_ehp(
            _SNAP, "Ashe", 11, mode="SR", top_n=8, apply_passive_mitigation=True
        )
        self.assertEqual(off.baseline_ehp, on.baseline_ehp)
        self.assertEqual(
            [(r.item_id, r.delta_ehp) for r in off.ranked],
            [(r.item_id, r.delta_ehp) for r in on.ranked],
        )


class EngineAndHygieneTests(unittest.TestCase):
    def test_engine_version(self):
        self.assertEqual(ENGINE_VERSION, "1.267.0")
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.267.0")

    def test_module_ascii(self):
        import agents.daemon_slayer._passive_mitigation_overrides as m

        for path in (m.__file__, __file__):
            with open(path, "rb") as fh:
                fh.read().decode("ascii")

    def test_entry_dataclass_constructs(self):
        e = PassiveMitigationEntry(terms=((10.0, MAG),))
        self.assertEqual(e.conditional_probability, 1.0)
        self.assertFalse(e.level_scaled)


if __name__ == "__main__":
    unittest.main()
