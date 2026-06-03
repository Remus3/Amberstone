# Tests for core/heal_threat.py - the deterministic anti-heal / Grievous-Wounds
# nudge (aggregator-A-style heal-threat tracker; Haiku-elimination, competitor #2).
#
# Covers: the curated-champion + sustain-item fire logic, ally-anti-heal
# suppression, display-name normalization, int|str item-id coercion, mode
# gating, fail-soft on garbage, callout shape, and ASCII hygiene.
from __future__ import annotations

import unittest
from pathlib import Path

import core.heal_threat as ht

_ROOT = Path(__file__).resolve().parent.parent


class FireLogicTests(unittest.TestCase):
    def test_single_sustain_champ_fires(self) -> None:
        out = ht.heal_threat_callout(["Soraka", "Ezreal"], [], [], "sr")
        self.assertIsNotNone(out)
        self.assertEqual(out["kind"], "heal_threat")
        self.assertEqual(out["tag"], "heal_threat")
        self.assertIsNone(out["eta_s"])  # standing advisory -> no ETA chip
        self.assertIn("Soraka", out["line"])
        self.assertIn("anti-heal", out["line"])

    def test_ally_grievous_item_suppresses(self) -> None:
        # Ally owns Morellonomicon (3165) -> threat already answered.
        out = ht.heal_threat_callout(["Soraka", "Aatrox"], [], ["3165"], "sr")
        self.assertIsNone(out)

    def test_ally_thornmail_onhit_grievous_suppresses(self) -> None:
        # Thornmail (3075) applies Grievous on-hit; counts as anti-heal.
        out = ht.heal_threat_callout(["Vladimir"], [], ["3047", "3075"], "sr")
        self.assertIsNone(out)

    def test_one_heal_item_below_threshold(self) -> None:
        # A lone Bloodthirster (3072) on a non-curated roster does NOT fire.
        out = ht.heal_threat_callout(["Ezreal", "Lux"], ["3072"], [], "sr")
        self.assertIsNone(out)

    def test_two_heal_items_fire_without_curated_champ(self) -> None:
        # Two sustain items (Bloodthirster + Ravenous Hydra) clear the item bar.
        out = ht.heal_threat_callout(["Ezreal", "Jax"], ["3072", "3074"], [], "sr")
        self.assertIsNotNone(out)
        self.assertIn("2 heal items", out["line"])

    def test_enemy_grievous_does_not_suppress(self) -> None:
        # A Grievous item on the ENEMY is irrelevant; only ally items suppress.
        out = ht.heal_threat_callout(["Soraka"], ["3165"], [], "sr")
        self.assertIsNotNone(out)

    def test_two_champs_listed_with_overflow_marker(self) -> None:
        out = ht.heal_threat_callout(
            ["Soraka", "Aatrox", "Warwick"], [], [], "sr")
        self.assertIsNotNone(out)
        # Up to two names shown + "+1" for the third curated champ.
        self.assertIn("Soraka", out["line"])
        self.assertIn("Aatrox", out["line"])
        self.assertIn("+1", out["line"])


class NormalizationTests(unittest.TestCase):
    def test_display_name_with_punctuation_matches(self) -> None:
        # Live Client reports "Dr. Mundo" (display name), not "DrMundo".
        out = ht.heal_threat_callout(["Dr. Mundo"], [], [], "sr")
        self.assertIsNotNone(out)
        self.assertIn("Dr. Mundo", out["line"])

    def test_int_item_ids_coerced(self) -> None:
        # itemID can arrive as an int; ally int 3165 must still suppress.
        out = ht.heal_threat_callout(["Soraka"], [], [3165], "sr")
        self.assertIsNone(out)

    def test_int_enemy_heal_items_counted(self) -> None:
        out = ht.heal_threat_callout(["Jax"], [3072, 3074], [], "sr")
        self.assertIsNotNone(out)

    def test_duplicate_normalized_champ_collapsed(self) -> None:
        # Defensive: two entries normalizing alike count once (no "+1").
        out = ht.heal_threat_callout(["Soraka", "soraka"], [], [], "sr")
        self.assertIsNotNone(out)
        self.assertNotIn("+1", out["line"])


class ModeGateTests(unittest.TestCase):
    def test_arena_returns_none(self) -> None:
        self.assertIsNone(ht.heal_threat_callout(["Soraka"], [], [], "arena"))

    def test_tft_returns_none(self) -> None:
        self.assertIsNone(ht.heal_threat_callout(["Soraka"], [], [], "tft"))

    def test_aram_fires(self) -> None:
        self.assertIsNotNone(ht.heal_threat_callout(["Soraka"], [], [], "aram"))

    def test_client_and_game_fire(self) -> None:
        self.assertIsNotNone(ht.heal_threat_callout(["Soraka"], [], [], "client"))
        self.assertIsNotNone(ht.heal_threat_callout(["Soraka"], [], [], "game"))


class FailSoftTests(unittest.TestCase):
    def test_all_none_inputs(self) -> None:
        self.assertIsNone(ht.heal_threat_callout(None, None, None, "sr"))

    def test_non_list_inputs(self) -> None:
        self.assertIsNone(ht.heal_threat_callout("Soraka", "3072", "3165", "sr"))

    def test_garbage_entries_skipped(self) -> None:
        # None/empty/bad entries in the lists are dropped, no raise.
        out = ht.heal_threat_callout(
            ["Soraka", None, 42, ""], [None, "", True], [None], "sr")
        self.assertIsNotNone(out)
        self.assertIn("Soraka", out["line"])

    def test_bool_item_ids_ignored(self) -> None:
        # True/False must not be treated as item ids (isinstance int trap).
        out = ht.heal_threat_callout(["Jax"], [True, False], [True], "sr")
        self.assertIsNone(out)  # no real heal items, no real ally grievous

    def test_no_enemy_no_fire(self) -> None:
        self.assertIsNone(ht.heal_threat_callout([], [], [], "sr"))


class CalloutShapeTests(unittest.TestCase):
    def test_line_is_ascii_and_bounded(self) -> None:
        out = ht.heal_threat_callout(
            ["Soraka", "Aatrox", "Warwick", "Vladimir"], ["3072", "3074"], [], "sr")
        self.assertIsNotNone(out)
        line = out["line"]
        self.assertTrue(line.isascii(), "callout line must be ASCII (no em-dash)")
        self.assertLessEqual(len(line), 120, "line fits the panel slice")

    def test_keys_match_callout_contract(self) -> None:
        out = ht.heal_threat_callout(["Soraka"], [], [], "sr")
        self.assertEqual(set(out.keys()), {"tag", "line", "eta_s", "kind"})


class AsciiHygieneTests(unittest.TestCase):
    def _assert_ascii(self, rel: str) -> None:
        raw = (_ROOT / rel).read_bytes()
        nonascii = [b for b in raw if b > 0x7F]
        self.assertEqual(nonascii, [], f"{rel} has {len(nonascii)} non-ASCII bytes")

    def test_module_ascii(self) -> None:
        self._assert_ascii("core/heal_threat.py")

    def test_test_file_ascii(self) -> None:
        self._assert_ascii("tests/test_heal_threat.py")


if __name__ == "__main__":
    unittest.main()
