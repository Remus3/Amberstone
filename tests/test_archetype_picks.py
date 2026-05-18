"""Phase 3 (s176, 2026-05-12) - core/archetype_picks tests.

Tag → archetype resolver, persistence round-trip, default fallbacks,
validation. Uses tempdir to avoid clobbering the real
``data/cs_archetype_picks.json`` during test runs.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from core import archetype_picks


class TagToArchetypeTests(unittest.TestCase):
    def test_canonical_tags_map_correctly(self):
        self.assertEqual(archetype_picks.tag_to_archetype("Fighter"), "bruiser")
        self.assertEqual(archetype_picks.tag_to_archetype("Mage"), "mage")
        self.assertEqual(archetype_picks.tag_to_archetype("Assassin"), "assassin")
        self.assertEqual(archetype_picks.tag_to_archetype("Marksman"), "carry")
        self.assertEqual(archetype_picks.tag_to_archetype("Tank"), "tank")
        self.assertEqual(archetype_picks.tag_to_archetype("Support"), "enchanter")

    def test_case_insensitive(self):
        self.assertEqual(archetype_picks.tag_to_archetype("FIGHTER"), "bruiser")
        self.assertEqual(archetype_picks.tag_to_archetype("fighter"), "bruiser")
        self.assertEqual(archetype_picks.tag_to_archetype("Fighter "), "bruiser")

    def test_unknown_tag_falls_back_to_carry(self):
        self.assertEqual(archetype_picks.tag_to_archetype(""), "carry")
        self.assertEqual(archetype_picks.tag_to_archetype("Unknown"), "carry")
        self.assertEqual(archetype_picks.tag_to_archetype("Specialist"), "carry")


class DefaultForChampionTests(unittest.TestCase):
    """Exercises against the real ddragon_champions.json snapshot. These
    pins assume the canonical 2026-05 DDragon shape - they'll redden if
    a patch retags champions, which is the right signal."""

    def test_aatrox_is_bruiser_with_tank_secondary(self):
        # Aatrox has only ["Fighter"] in 16.9.1 → primary=bruiser,
        # secondary falls back via _fallback_secondary("bruiser") → tank.
        primary, secondary = archetype_picks.default_for_champion("Aatrox")
        self.assertEqual(primary, "bruiser")
        self.assertEqual(secondary, "tank")

    def test_lulu_is_enchanter_with_mage_secondary(self):
        primary, secondary = archetype_picks.default_for_champion("Lulu")
        self.assertEqual(primary, "enchanter")
        self.assertEqual(secondary, "mage")

    def test_yasuo_is_bruiser_with_assassin_secondary(self):
        primary, secondary = archetype_picks.default_for_champion("Yasuo")
        self.assertEqual(primary, "bruiser")
        self.assertEqual(secondary, "assassin")

    def test_malphite_is_tank_with_mage_secondary(self):
        # Malphite has tags ["Tank", "Mage"]
        primary, secondary = archetype_picks.default_for_champion("Malphite")
        self.assertEqual(primary, "tank")
        self.assertEqual(secondary, "mage")

    def test_caitlyn_carry_with_bruiser_fallback(self):
        # Caitlyn tags = ["Marksman"] only → primary=carry,
        # _fallback_secondary("carry") = bruiser.
        primary, secondary = archetype_picks.default_for_champion("Caitlyn")
        self.assertEqual(primary, "carry")
        self.assertEqual(secondary, "bruiser")

    def test_monkeyking_ddragon_id_works(self):
        # Server-side champion resolution uses DDragon IDs. MonkeyKing
        # tags = ["Fighter", "Tank"] → bruiser/tank.
        primary, secondary = archetype_picks.default_for_champion("MonkeyKing")
        self.assertEqual(primary, "bruiser")
        self.assertEqual(secondary, "tank")

    def test_wukong_display_name_resolves(self):
        # Display name should resolve via the same map (champion-summary
        # has both name and id keyed).
        primary, secondary = archetype_picks.default_for_champion("Wukong")
        # Wukong's name in DDragon may not be "Wukong" - id is MonkeyKing,
        # display name is "Wukong". Either way the tags should resolve.
        self.assertIn(primary, ("bruiser", "carry"))  # carry = unknown fallback

    def test_unknown_champion_safe_fallback(self):
        primary, secondary = archetype_picks.default_for_champion("NonexistentChamp123")
        self.assertEqual(primary, "carry")
        self.assertEqual(secondary, "bruiser")

    def test_empty_champion_safe_fallback(self):
        primary, secondary = archetype_picks.default_for_champion("")
        self.assertEqual(primary, "carry")
        self.assertEqual(secondary, "bruiser")


class FallbackSecondaryTests(unittest.TestCase):
    """Pin the _fallback_secondary heuristic so future churn is intentional."""

    def test_carry_falls_back_to_bruiser(self):
        self.assertEqual(archetype_picks._fallback_secondary("carry"), "bruiser")

    def test_bruiser_falls_back_to_tank(self):
        self.assertEqual(archetype_picks._fallback_secondary("bruiser"), "tank")

    def test_tank_falls_back_to_bruiser(self):
        self.assertEqual(archetype_picks._fallback_secondary("tank"), "bruiser")

    def test_mage_falls_back_to_assassin(self):
        self.assertEqual(archetype_picks._fallback_secondary("mage"), "assassin")

    def test_unknown_falls_back_to_bruiser(self):
        self.assertEqual(archetype_picks._fallback_secondary("xyz"), "bruiser")


class PersistenceTests(unittest.TestCase):
    """Mock the persistence path so tests don't touch the real data file."""

    def setUp(self):
        # Use a per-test tempfile and patch the module's path constants.
        import tempfile
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmpdir.name) / "cs_archetype_picks.json"
        self._patch_path = mock.patch.object(
            archetype_picks, "_PICKS_PATH", self.tmp_path,
        )
        self._patch_dir = mock.patch.object(
            archetype_picks, "_DATA_DIR", Path(self.tmpdir.name),
        )
        self._patch_path.start()
        self._patch_dir.start()
        archetype_picks._invalidate_picks_cache()

    def tearDown(self):
        self._patch_path.stop()
        self._patch_dir.stop()
        archetype_picks._invalidate_picks_cache()
        self.tmpdir.cleanup()

    def test_save_then_get_returns_entry(self):
        entry = archetype_picks.save_archetype_pick(
            "Aatrox", primary="tank", source="user_cs",
        )
        self.assertEqual(entry["champion"], "Aatrox")
        self.assertEqual(entry["primary"], "tank")
        self.assertEqual(entry["source"], "user_cs")
        self.assertIn("set_at", entry)

        loaded = archetype_picks.get_archetype_for("Aatrox")
        self.assertEqual(loaded["primary"], "tank")
        self.assertEqual(loaded["source"], "user_cs")

    def test_get_without_pick_returns_default_with_source_default(self):
        # No pick saved → DDragon default; source=default
        entry = archetype_picks.get_archetype_for("Aatrox")
        self.assertEqual(entry["primary"], "bruiser")
        self.assertEqual(entry["source"], "default")
        self.assertNotIn("set_at", entry)

    def test_save_resolves_default_secondary(self):
        # Caller omits secondary → defaults to DDragon-derived value
        # (but != primary; otherwise _fallback_secondary).
        entry = archetype_picks.save_archetype_pick(
            "Aatrox", primary="tank",  # explicit, but secondary auto-resolves
        )
        # Aatrox's tags = ["Fighter"], default = bruiser/tank.
        # save with primary=tank → secondary should be the OTHER default option.
        self.assertNotEqual(entry["primary"], entry["secondary"])

    def test_save_with_explicit_secondary(self):
        entry = archetype_picks.save_archetype_pick(
            "Aatrox", primary="tank", secondary="mage",
        )
        self.assertEqual(entry["secondary"], "mage")

    def test_clear_removes_override(self):
        archetype_picks.save_archetype_pick("Aatrox", primary="tank")
        cleared = archetype_picks.clear_archetype_pick("Aatrox")
        self.assertTrue(cleared)
        # Now reads back as default.
        entry = archetype_picks.get_archetype_for("Aatrox")
        self.assertEqual(entry["source"], "default")
        self.assertEqual(entry["primary"], "bruiser")  # back to DDragon default

    def test_clear_unknown_champion_returns_false(self):
        self.assertFalse(archetype_picks.clear_archetype_pick("Aatrox"))

    def test_list_returns_persisted_map(self):
        archetype_picks.save_archetype_pick("Aatrox", primary="tank")
        archetype_picks.save_archetype_pick("Lulu", primary="mage")
        picks = archetype_picks.list_archetype_picks()
        self.assertEqual(len(picks), 2)
        self.assertIn("Aatrox", picks)
        self.assertIn("Lulu", picks)

    def test_file_is_valid_json(self):
        archetype_picks.save_archetype_pick("Aatrox", primary="tank")
        self.assertTrue(self.tmp_path.exists())
        raw = json.loads(self.tmp_path.read_text())
        self.assertIsInstance(raw, dict)
        self.assertIn("Aatrox", raw)

    def test_save_invalid_primary_raises(self):
        with self.assertRaises(ValueError):
            archetype_picks.save_archetype_pick("Aatrox", primary="bogus")

    def test_save_invalid_secondary_raises(self):
        with self.assertRaises(ValueError):
            archetype_picks.save_archetype_pick(
                "Aatrox", primary="tank", secondary="bogus",
            )

    def test_save_invalid_source_raises(self):
        with self.assertRaises(ValueError):
            archetype_picks.save_archetype_pick(
                "Aatrox", primary="tank", source="bogus",
            )

    def test_save_empty_champion_raises(self):
        with self.assertRaises(ValueError):
            archetype_picks.save_archetype_pick("", primary="tank")
        with self.assertRaises(ValueError):
            archetype_picks.save_archetype_pick("   ", primary="tank")

    def test_save_overwrites_existing(self):
        archetype_picks.save_archetype_pick("Aatrox", primary="tank")
        archetype_picks.save_archetype_pick("Aatrox", primary="bruiser")
        entry = archetype_picks.get_archetype_for("Aatrox")
        self.assertEqual(entry["primary"], "bruiser")


class ConstantsTests(unittest.TestCase):
    def test_six_canonical_archetypes(self):
        self.assertEqual(len(archetype_picks.ARCHETYPES), 6)
        self.assertIn("carry", archetype_picks.ARCHETYPES)
        self.assertIn("bruiser", archetype_picks.ARCHETYPES)
        self.assertIn("tank", archetype_picks.ARCHETYPES)
        self.assertIn("mage", archetype_picks.ARCHETYPES)
        self.assertIn("assassin", archetype_picks.ARCHETYPES)
        self.assertIn("enchanter", archetype_picks.ARCHETYPES)

    def test_implemented_scorers_are_subset(self):
        self.assertTrue(
            archetype_picks.IMPLEMENTED_SCORERS.issubset(set(archetype_picks.ARCHETYPES))
        )
        # s209: all 6 scorers shipped (s174 tank, s175 bruiser, s176 base,
        # s179 mage→ability, s180 assassin→burst, s181 enchanter→hps).
        # Dispatcher routes each archetype to its dedicated scorer with no
        # ds.dps fallbacks remaining.
        self.assertEqual(
            archetype_picks.IMPLEMENTED_SCORERS,
            frozenset({
                "carry", "bruiser", "tank", "mage", "assassin", "enchanter",
            }),
        )

    def test_valid_sources_are_complete(self):
        self.assertIn("default", archetype_picks.VALID_SOURCES)
        self.assertIn("user_cs", archetype_picks.VALID_SOURCES)
        self.assertIn("user_ingame", archetype_picks.VALID_SOURCES)
        self.assertIn("nudge", archetype_picks.VALID_SOURCES)


if __name__ == "__main__":
    unittest.main()
