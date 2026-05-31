"""2026-05-30 (DS scraper-review slice) - modifier-block taxonomy tests.

Pins ``modifier_blocks.classify_modifier_kind`` + ``summarize_modifiers``
against the live 16.11.1 snapshot. Closes the DS-review finding that
"modifiers aren't being considered" - they are now classified + queryable
(without corrupting any DPS number, which is correct: the 180 modifier
blocks are a heterogeneous bag, not one clean damage multiplier).

Roster snapshot at 16.11.1: 180 modifier blocks ->
  pve_only 125 / target_shred 17 / defensive_self 17 / damage_amp_self 15
  / other 6.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from agents.daemon_slayer.abilities import load_default
from agents.daemon_slayer.modifier_blocks import (
    MODIFIER_KINDS,
    ModifierSummary,
    classify_modifier_kind,
    summarize_modifiers,
)

_AB = load_default()


class ClassifyModifierKindTests(unittest.TestCase):
    def test_pve_minion(self):
        self.assertEqual(classify_modifier_kind("Minion Damage"), "pve_only")

    def test_pve_monster(self):
        self.assertEqual(classify_modifier_kind("Maximum Monster Damage"), "pve_only")

    def test_pve_non_champion(self):
        self.assertEqual(classify_modifier_kind("Non-Champion Damage"), "pve_only")

    def test_pve_wins_over_reduction(self):
        # "Monster Damage Reduction" is PvE, not a defensive self-buff.
        self.assertEqual(classify_modifier_kind("Reduced Monster Damage"), "pve_only")

    def test_target_shred_armor(self):
        self.assertEqual(classify_modifier_kind("Armor Reduction"), "target_shred")

    def test_target_shred_mr(self):
        self.assertEqual(
            classify_modifier_kind("Magic Resistance Reduction"), "target_shred"
        )

    def test_target_shred_resistances(self):
        self.assertEqual(
            classify_modifier_kind("Resistances Reduction"), "target_shred"
        )

    def test_target_shred_ad(self):
        self.assertEqual(
            classify_modifier_kind("Attack Damage Reduction"), "target_shred"
        )

    def test_defensive_damage_reduction(self):
        self.assertEqual(
            classify_modifier_kind("Damage Reduction"), "defensive_self"
        )

    def test_defensive_bonus_mr(self):
        self.assertEqual(
            classify_modifier_kind("Bonus Magic Resistance"), "defensive_self"
        )

    def test_amp_headshot(self):
        self.assertEqual(
            classify_modifier_kind("Headshot Damage Increase"), "damage_amp_self"
        )

    def test_amp_crit(self):
        self.assertEqual(classify_modifier_kind("Critical damage"), "damage_amp_self")

    def test_amp_damage_increase(self):
        self.assertEqual(classify_modifier_kind("Damage Increase"), "damage_amp_self")

    def test_other_size(self):
        self.assertEqual(classify_modifier_kind("Size Increase"), "other")

    def test_empty(self):
        self.assertEqual(classify_modifier_kind(""), "other")

    def test_every_result_is_known_kind(self):
        for att in ["Minion Damage", "Armor Reduction", "Damage Reduction",
                    "Headshot Damage Increase", "Size Increase", "whatever"]:
            self.assertIn(classify_modifier_kind(att), MODIFIER_KINDS)


class SummarizeModifiersTests(unittest.TestCase):
    def test_roster_totals(self):
        s = summarize_modifiers(_AB)
        self.assertIsInstance(s, ModifierSummary)
        # Live 16.11.1 count - pins the bag is heterogeneous (a blanket
        # "apply every modifier as a multiplier" would be wrong).
        self.assertEqual(s.total, 180)
        self.assertEqual(set(s.by_kind.keys()), set(MODIFIER_KINDS))
        self.assertEqual(sum(s.by_kind.values()), s.total)

    def test_pve_is_the_bulk(self):
        s = summarize_modifiers(_AB)
        # The dominant class is PvE-only (correctly excluded from champ DPS).
        self.assertGreater(s.by_kind["pve_only"], s.total // 2)

    def test_shred_examples_present(self):
        s = summarize_modifiers(_AB)
        self.assertGreater(s.by_kind["target_shred"], 0)
        joined = " ".join(s.target_shred_examples)
        self.assertIn("Nasus.E", joined)  # canonical armor shred

    def test_amp_examples_present(self):
        s = summarize_modifiers(_AB)
        self.assertGreater(s.by_kind["damage_amp_self"], 0)
        joined = " ".join(s.damage_amp_examples)
        self.assertIn("Caitlyn.W", joined)  # the chat's named case

    def test_to_dict_shape(self):
        s = summarize_modifiers(_AB)
        d = s.to_dict()
        self.assertEqual(d["total"], 180)
        self.assertIn("by_kind", d)
        self.assertIn("target_shred_examples", d)
        import json
        json.dumps(d)


class AsciiHygieneTests(unittest.TestCase):
    def test_module_is_ascii(self):
        for rel in ("modifier_blocks.py",
                    "tests/test_modifier_blocks_2026_05_30.py"):
            p = Path(__file__).resolve().parents[1] / rel
            data = p.read_bytes()
            non_ascii = [(i, b) for i, b in enumerate(data) if b > 0x7F]
            self.assertEqual(non_ascii, [], f"{rel} non-ASCII: {non_ascii[:5]}")


if __name__ == "__main__":
    unittest.main()
