"""Unit tests for core/cc_threat.py - the C6 tenacity counter-hint source.

compute_cc_score maps an enemy champion roster to a 0..10 CC-load float that
feeds the situational EnemyProfile.cc_score (the C6 tenacity counter-hint fires
at >= CC_CUT (5.0)). Flat per-champ x2.5 over a curated hard-CC roster, clamped
at 10.0. Correct-by-construction + fail-soft, mirroring core/heal_threat.py.

ASCII only - use " - " for a clause break (repo hard rule).
"""
from __future__ import annotations

import unittest
from pathlib import Path

import core.cc_threat as cc

_ROOT = Path(__file__).resolve().parent.parent


class CcScoreTests(unittest.TestCase):
    """compute_cc_score: matched curated hard-CC champs x2.5, clamp 10.0."""

    def test_two_hard_cc_champs_score_five(self) -> None:
        # Leona + Malphite are curated hard-CC -> 2 * 2.5 = 5.0 (fires at >=).
        self.assertEqual(cc.compute_cc_score(["Leona", "Malphite"]), 5.0)

    def test_one_hard_cc_champ_below_cut(self) -> None:
        # 1 curated champ (Leona); Master Yi + Tryndamere are off-roster -> 2.5.
        self.assertEqual(
            cc.compute_cc_score(["Leona", "Master Yi", "Tryndamere"]), 2.5)

    def test_score_clamps_at_ten(self) -> None:
        # 5 curated champs = 12.5 raw, clamped to 10.0.
        self.assertEqual(
            cc.compute_cc_score(
                ["Leona", "Malphite", "Amumu", "Sejuani", "Morgana"]), 10.0)

    def test_off_roster_comp_scores_zero(self) -> None:
        self.assertEqual(
            cc.compute_cc_score(["Master Yi", "Tryndamere", "Katarina"]), 0.0)

    def test_normalization_matches_punctuation_and_spacing(self) -> None:
        # "Cho'Gath" -> chogath, "Jarvan IV" -> jarvaniv, both curated -> 5.0.
        self.assertEqual(cc.compute_cc_score(["Cho'Gath", "Jarvan IV"]), 5.0)

    def test_dedups_on_normalized_key(self) -> None:
        # Two entries normalizing alike collapse to one distinct match -> 2.5.
        self.assertEqual(cc.compute_cc_score(["Cho'Gath", "chogath"]), 2.5)

    def test_failsoft_none(self) -> None:
        self.assertEqual(cc.compute_cc_score(None), 0.0)

    def test_failsoft_non_list(self) -> None:
        self.assertEqual(cc.compute_cc_score("Leona"), 0.0)

    def test_failsoft_empty(self) -> None:
        self.assertEqual(cc.compute_cc_score([]), 0.0)


class AsciiHygieneTests(unittest.TestCase):
    def _assert_ascii(self, rel: str) -> None:
        raw = (_ROOT / rel).read_bytes()
        nonascii = [b for b in raw if b > 0x7F]
        self.assertEqual(nonascii, [], f"{rel} has {len(nonascii)} non-ASCII bytes")

    def test_module_ascii(self) -> None:
        self._assert_ascii("core/cc_threat.py")

    def test_test_file_ascii(self) -> None:
        self._assert_ascii("tests/test_cc_threat.py")


if __name__ == "__main__":
    unittest.main()
