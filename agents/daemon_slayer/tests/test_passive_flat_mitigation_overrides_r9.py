"""R9 - effects-text-only PER-INSTANCE FLAT-AMOUNT damage-reduction tests.

The MISSING SIBLING of the percent ``_passive_mitigation_overrides`` registry:
that one EXCLUDED the flat-amount-per-instance class (Fizz P, Amumu E, Leona W).
R9 adds exactly that class, folded into the EHP NUMERATOR like ``ext_flat_hp``.
``assume_passive_flat_mitigation`` defaults False -> byte-identical to ENGINE
1.147.0.

Seeded 3 (Fizz P flat 4 ANY innate, Amumu E rank [5,7,9,11,13] PHYS passive,
Leona W rank [8,12,16,20,24] ANY active amortized at 0.3). Each caps at 50% of
the instance (cap_frac 0.5, non-binding at representative instance sizes).
"""
from __future__ import annotations

import dataclasses
import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import compute_ehp
from agents.daemon_slayer._passive_flat_mitigation_overrides import (
    ANY,
    MAG,
    PHYS,
    TRUE,
    PassiveFlatMitigationEntry,
    _ASSUMED_ABILITY_RANK,
    _ASSUMED_FLAT_DR_INSTANCES,
    _PASSIVE_FLAT_MITIGATION_OVERRIDES,
    _value_at_level,
    flat_mitigation_hp,
)

_SNAP = DataSnapshot.load()

# An unregistered champion (no flat-DR entry) used for the no-spurious-effect +
# byte-identical-OFF-and-ON checks.
_UNREG = "Garen"


def _ehp(cid, lvl=11, items=(), **kw):
    return compute_ehp(_SNAP, champion_id=cid, level=lvl, item_ids=items, mode="SR", **kw)


class RegistryShapeTests(unittest.TestCase):
    def test_exactly_three_seeds(self):
        self.assertEqual(len(_PASSIVE_FLAT_MITIGATION_OVERRIDES), 3)

    def test_keys_are_the_seeded_set(self):
        self.assertEqual(
            set(_PASSIVE_FLAT_MITIGATION_OVERRIDES),
            {
                ("Fizz", "P", 0),
                ("Amumu", "E", 0),
                ("Leona", "W", 0),
            },
        )

    def test_every_term_type_is_valid(self):
        valid = {PHYS, MAG, TRUE, ANY}
        for entry in _PASSIVE_FLAT_MITIGATION_OVERRIDES.values():
            self.assertTrue(entry.terms)
            for (_flat, dtype) in entry.terms:
                self.assertIn(dtype, valid)

    def test_conditional_probability_in_unit_range(self):
        for entry in _PASSIVE_FLAT_MITIGATION_OVERRIDES.values():
            self.assertGreaterEqual(entry.conditional_probability, 0.0)
            self.assertLessEqual(entry.conditional_probability, 1.0)

    def test_cap_frac_in_open_unit_range(self):
        for entry in _PASSIVE_FLAT_MITIGATION_OVERRIDES.values():
            self.assertGreater(entry.cap_frac, 0.0)
            self.assertLessEqual(entry.cap_frac, 1.0)

    def test_every_entry_has_a_nonempty_note(self):
        for entry in _PASSIVE_FLAT_MITIGATION_OVERRIDES.values():
            self.assertTrue(entry.note.strip())

    def test_entry_is_frozen(self):
        entry = _PASSIVE_FLAT_MITIGATION_OVERRIDES[("Fizz", "P", 0)]
        with self.assertRaises(dataclasses.FrozenInstanceError):
            entry.terms = ()  # type: ignore[misc]


class CharacterizationTests(unittest.TestCase):
    """Each seed's flat value + axis + cap match the verbatim cited effects text."""

    def test_fizz_p_flat_four_any_cap_half(self):
        entry = _PASSIVE_FLAT_MITIGATION_OVERRIDES[("Fizz", "P", 0)]
        self.assertEqual(entry.terms, ((4.0, ANY),))
        self.assertEqual(entry.cap_frac, 0.5)
        self.assertEqual(entry.conditional_probability, 1.0)
        self.assertFalse(entry.rank_scaled)

    def test_amumu_e_rank_block_physical_cap_half(self):
        entry = _PASSIVE_FLAT_MITIGATION_OVERRIDES[("Amumu", "E", 0)]
        self.assertEqual(entry.terms, (((5.0, 7.0, 9.0, 11.0, 13.0), PHYS),))
        self.assertEqual(entry.cap_frac, 0.5)
        self.assertEqual(entry.conditional_probability, 1.0)
        self.assertTrue(entry.rank_scaled)

    def test_leona_w_rank_block_any_active_amortized(self):
        entry = _PASSIVE_FLAT_MITIGATION_OVERRIDES[("Leona", "W", 0)]
        self.assertEqual(entry.terms, (((8.0, 12.0, 16.0, 20.0, 24.0), ANY),))
        self.assertEqual(entry.cap_frac, 0.5)
        self.assertEqual(entry.conditional_probability, 0.3)
        self.assertTrue(entry.rank_scaled)

    def test_value_at_level_reads_assumed_ability_rank(self):
        # Amumu's per-rank [5,7,9,11,13] read at the assumed rank (index rank-1).
        block = (5.0, 7.0, 9.0, 11.0, 13.0)
        expected = block[_ASSUMED_ABILITY_RANK - 1]
        self.assertEqual(_value_at_level(block, 11, True), expected)

    def test_value_at_level_flat_is_passthrough(self):
        self.assertEqual(_value_at_level(4.0, 18, False), 4.0)


class FlatMitigationHpTests(unittest.TestCase):
    def test_off_returns_all_zero(self):
        self.assertEqual(flat_mitigation_hp("Amumu", 11, False), (0.0, 0.0, 0.0))
        self.assertEqual(flat_mitigation_hp("Fizz", 11, False), (0.0, 0.0, 0.0))

    def test_unregistered_champ_returns_zero_even_on(self):
        self.assertEqual(flat_mitigation_hp(_UNREG, 11, True), (0.0, 0.0, 0.0))

    def test_amumu_positive_physical_zero_other_axes(self):
        phys, mag, true = flat_mitigation_hp("Amumu", 11, True)
        self.assertGreater(phys, 0.0)
        self.assertEqual(mag, 0.0)
        self.assertEqual(true, 0.0)
        # exact prevented-HP arithmetic: instances * flat(rank) * prob.
        flat = (5.0, 7.0, 9.0, 11.0, 13.0)[_ASSUMED_ABILITY_RANK - 1]
        self.assertAlmostEqual(phys, _ASSUMED_FLAT_DR_INSTANCES * flat * 1.0)

    def test_fizz_any_axis_all_three_positive_and_equal(self):
        phys, mag, true = flat_mitigation_hp("Fizz", 11, True)
        self.assertGreater(phys, 0.0)
        self.assertEqual(phys, mag)
        self.assertEqual(phys, true)
        self.assertAlmostEqual(phys, _ASSUMED_FLAT_DR_INSTANCES * 4.0 * 1.0)

    def test_leona_any_axis_amortized_by_prob(self):
        phys, mag, true = flat_mitigation_hp("Leona", 11, True)
        self.assertGreater(phys, 0.0)
        self.assertEqual(phys, mag)
        self.assertEqual(phys, true)
        flat = (8.0, 12.0, 16.0, 20.0, 24.0)[_ASSUMED_ABILITY_RANK - 1]
        self.assertAlmostEqual(phys, _ASSUMED_FLAT_DR_INSTANCES * flat * 0.3)


class EhpByteIdenticalTests(unittest.TestCase):
    def test_default_equals_explicit_false_registered_champ(self):
        a = _ehp("Amumu")
        b = _ehp("Amumu", assume_passive_flat_mitigation=False)
        self.assertEqual(a.blended_ehp, b.blended_ehp)
        self.assertEqual(a.physical_ehp, b.physical_ehp)
        self.assertEqual(a.magical_ehp, b.magical_ehp)
        self.assertEqual(a.true_ehp, b.true_ehp)

    def test_unregistered_champ_identical_on_vs_off(self):
        off = _ehp(_UNREG)
        on = _ehp(_UNREG, assume_passive_flat_mitigation=True)
        self.assertEqual(off.blended_ehp, on.blended_ehp)
        self.assertEqual(off.physical_ehp, on.physical_ehp)
        self.assertEqual(off.true_ehp, on.true_ehp)

    def test_registered_champ_blended_strictly_greater_on(self):
        off = _ehp("Amumu")
        on = _ehp("Amumu", assume_passive_flat_mitigation=True)
        self.assertGreater(on.blended_ehp, off.blended_ehp)
        # Amumu's flat DR is PHYSICAL-only, so physical EHP rises and true EHP
        # (no flat-DR axis) is unchanged.
        self.assertGreater(on.physical_ehp, off.physical_ehp)
        self.assertEqual(on.true_ehp, off.true_ehp)

    def test_fizz_any_axis_raises_all_three(self):
        off = _ehp("Fizz")
        on = _ehp("Fizz", assume_passive_flat_mitigation=True)
        self.assertGreater(on.physical_ehp, off.physical_ehp)
        self.assertGreater(on.magical_ehp, off.magical_ehp)
        self.assertGreater(on.true_ehp, off.true_ehp)


class EnginePinTests(unittest.TestCase):
    def test_engine_version(self):
        self.assertEqual(ENGINE_VERSION, "1.231.0")


if __name__ == "__main__":
    unittest.main()
