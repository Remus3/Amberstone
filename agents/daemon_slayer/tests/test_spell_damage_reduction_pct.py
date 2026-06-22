"""Forward-marker accessor tests - DataSnapshot.spell_damage_reduction_pct.

Pins the per-rank PERCENT damage-reduction magnitude pulled from the
``champion_abilities.json`` defensive ``modifier`` blocks against the live
16.12.1 snapshot. The accessor is a FORWARD MARKER (no consumer), so these
tests guard the SHAPE + the exact per-rank floats, not any engine output.

The pure-% filter is the load-bearing detail: a defensive_self
"damage reduction" block can carry a flat sub-modifier (Amumu E, empty units)
or a resist-scaling sub-modifier ("% per 100 AP"); only the raw_modifier whose
``units`` are ALL the bare ``"%"`` string is a true percent reduction, so those
mixed-unit and flat cases must return None.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from agents.daemon_slayer.data_loader import DataSnapshot

SNAP = DataSnapshot.load()


class SpellDamageReductionPctTests(unittest.TestCase):
    def test_alistar_r(self):
        self.assertEqual(
            SNAP.spell_damage_reduction_pct("Alistar", "R"),
            {"Damage Reduction": (55.0, 65.0, 75.0)},
        )

    def test_belveth_e(self):
        self.assertEqual(
            SNAP.spell_damage_reduction_pct("Belveth", "E"),
            {"Damage Reduction": (35.0, 40.0, 45.0, 50.0, 55.0)},
        )

    def test_braum_e(self):
        # Note the lowercase 'reduction' in the Meraki attribute label.
        self.assertEqual(
            SNAP.spell_damage_reduction_pct("Braum", "E"),
            {"Damage reduction": (35.0, 40.0, 45.0, 50.0, 55.0)},
        )

    def test_galio_w_both_labels(self):
        self.assertEqual(
            SNAP.spell_damage_reduction_pct("Galio", "W"),
            {
                "Magic Damage Reduction": (25.0, 30.0, 35.0, 40.0, 45.0),
                "Physical Damage Reduction": (12.5, 15.0, 17.5, 20.0, 22.5),
            },
        )

    def test_garen_w(self):
        self.assertEqual(
            SNAP.spell_damage_reduction_pct("Garen", "W"),
            {"Damage Reduction": (25.0, 29.0, 33.0, 37.0, 41.0)},
        )

    def test_gragas_w(self):
        self.assertEqual(
            SNAP.spell_damage_reduction_pct("Gragas", "W"),
            {"Damage Reduction": (10.0, 12.0, 14.0, 16.0, 18.0)},
        )

    def test_masteryi_w(self):
        self.assertEqual(
            SNAP.spell_damage_reduction_pct("MasterYi", "W"),
            {"Modified Damage Reduction": (45.0, 47.5, 50.0, 52.5, 55.0)},
        )

    def test_warwick_e(self):
        self.assertEqual(
            SNAP.spell_damage_reduction_pct("Warwick", "E"),
            {"Damage Reduction": (35.0, 40.0, 45.0, 50.0, 55.0)},
        )

    def test_amumu_e_flat_is_none(self):
        # Amumu E is a FLAT reduction (empty units) - not a percent block.
        self.assertIsNone(SNAP.spell_damage_reduction_pct("Amumu", "E"))

    def test_leona_w_flat_is_none(self):
        self.assertIsNone(SNAP.spell_damage_reduction_pct("Leona", "W"))

    def test_ashe_q_no_block_is_none(self):
        self.assertIsNone(SNAP.spell_damage_reduction_pct("Ashe", "Q"))

    def test_unknown_champ_is_none(self):
        self.assertIsNone(SNAP.spell_damage_reduction_pct("Zzz", "Q"))


class SpellDamageReductionPctInvariantTests(unittest.TestCase):
    def test_every_value_is_percent_tuple(self):
        # Reach the lazily-built map by querying any known champ first.
        SNAP.spell_damage_reduction_pct("Garen", "W")
        built = SNAP._dr_pct_map
        self.assertTrue(built, "expected a non-empty damage-reduction-% map")
        for champ_id, slots in built.items():
            self.assertIsInstance(champ_id, str)
            for slot, labels in slots.items():
                self.assertIsInstance(slot, str)
                for label, ranks in labels.items():
                    self.assertIsInstance(label, str)
                    self.assertIsInstance(ranks, tuple)
                    self.assertTrue(ranks, f"{champ_id}.{slot} {label} empty tuple")
                    for p in ranks:
                        self.assertIsInstance(p, float)
                        self.assertGreater(p, 0.0)
                        self.assertLessEqual(p, 100.0)


class AsciiHygieneTests(unittest.TestCase):
    def test_test_file_is_ascii(self):
        p = Path(__file__).resolve()
        data = p.read_bytes()
        non_ascii = [(i, b) for i, b in enumerate(data) if b > 0x7F]
        self.assertEqual(non_ascii, [], f"non-ASCII bytes: {non_ascii[:5]}")


if __name__ == "__main__":
    unittest.main()
