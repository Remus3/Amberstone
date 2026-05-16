"""Regression tests for the _ITEM_CLASS_PEERS expansion in
``coaches/aram_coach.py``.

Covers two peer classes salvaged from PR #3:
  - Boots (all boot types are peers — only one pair fits the slot)
  - Spellblade passive (Trinity Force / Lich Bane / Divine Sunderer /
    Essence Reaver — passive does not stack; only the last-triggered
    proc applies, so a second Spellblade item is a dead slot)

Each test verifies that ``_dedup_build_vs_owned`` strips a class-peer
item from the build path when a peer is already owned, and does NOT
strip unrelated items.
"""
import sys
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from coaches.aram_coach import _dedup_build_vs_owned


class BootsPeerTests(unittest.TestCase):
    """Coach must never recommend a second boot pair after boots are owned."""

    def test_berserkers_owned_strips_ionian(self) -> None:
        result = _dedup_build_vs_owned(
            "Ionian Boots of Lucidity → Shadowflame",
            "Berserker's Greaves, Kraken Slayer",
        )
        self.assertNotIn("Ionian", result)
        self.assertIn("Shadowflame", result)

    def test_sorcerers_owned_strips_mercury_treads(self) -> None:
        result = _dedup_build_vs_owned(
            "Mercury's Treads → Rabadon's Deathcap",
            "Sorcerer's Shoes, Luden's Companion",
        )
        self.assertNotIn("Mercury's Treads", result)
        self.assertIn("Rabadon", result)

    def test_steelcaps_owned_strips_ionian(self) -> None:
        result = _dedup_build_vs_owned(
            "Ionian Boots of Lucidity → Trinity Force",
            "Plated Steelcaps, Sunfire Aegis",
        )
        self.assertNotIn("Ionian", result)
        self.assertIn("Trinity Force", result)

    def test_symbiotic_owned_strips_swiftness(self) -> None:
        result = _dedup_build_vs_owned(
            "Boots of Swiftness → Heartsteel",
            "Symbiotic Soles, Warmog's Armor",
        )
        self.assertNotIn("Swiftness", result)

    def test_boots_do_not_suppress_non_boot_items(self) -> None:
        result = _dedup_build_vs_owned(
            "Shadowflame → Rabadon's Deathcap",
            "Sorcerer's Shoes, Luden's Companion",
        )
        self.assertIn("Shadowflame", result)
        self.assertIn("Rabadon", result)

    def test_no_boots_owned_no_suppression(self) -> None:
        result = _dedup_build_vs_owned(
            "Ionian Boots of Lucidity → Shadowflame",
            "Luden's Companion, Shadowflame",
        )
        self.assertIn("Ionian", result)


class SpellbladePeerTests(unittest.TestCase):
    """Trinity / Lich Bane / Divine Sunderer / Essence Reaver — non-stacking passive."""

    def test_trinity_owned_strips_lich_bane(self) -> None:
        result = _dedup_build_vs_owned(
            "Lich Bane → Shadowflame",
            "Trinity Force, Plated Steelcaps",
        )
        self.assertNotIn("Lich Bane", result)
        self.assertIn("Shadowflame", result)

    def test_lich_bane_owned_strips_divine_sunderer(self) -> None:
        result = _dedup_build_vs_owned(
            "Divine Sunderer → Sterak's Gage",
            "Lich Bane, Shadowflame",
        )
        self.assertNotIn("Divine Sunderer", result)
        self.assertIn("Sterak", result)

    def test_sunderer_owned_strips_essence_reaver(self) -> None:
        result = _dedup_build_vs_owned(
            "Essence Reaver → Infinity Edge",
            "Divine Sunderer, Black Cleaver",
        )
        self.assertNotIn("Essence Reaver", result)
        self.assertIn("Infinity Edge", result)

    def test_essence_reaver_owned_strips_trinity(self) -> None:
        result = _dedup_build_vs_owned(
            "Trinity Force → Infinity Edge",
            "Essence Reaver, Kraken Slayer",
        )
        self.assertNotIn("Trinity Force", result)
        self.assertIn("Infinity Edge", result)

    def test_spellblade_does_not_suppress_non_spellblade_ad(self) -> None:
        result = _dedup_build_vs_owned(
            "Black Cleaver → Sterak's Gage",
            "Trinity Force, Plated Steelcaps",
        )
        self.assertIn("Black Cleaver", result)
        self.assertIn("Sterak", result)


if __name__ == "__main__":
    unittest.main()
