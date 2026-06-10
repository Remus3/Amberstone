"""T1-F4 (BACKLOG LOW, docs/COMPETITOR_LIFT_2026-06-08.md lines 68-75) -
per-stat EHP gold-efficiency verdict built on the shipped T1-F3 enemy-pen
seam.

Covers the new ``ehp_gold_efficiency`` pure compute-only helper: given a
champion's current armor / MR / HP context (the same build/enemy-mix
structures ``compute_ehp`` already resolves), it returns the marginal EHP
gained per 1 gold for ARMOR vs MR vs HP so the most gold-efficient
defensive stat versus a given enemy AD/AP damage-mix is identifiable.

The helper is ADDITIVE / compute-only and wired to NO live surface (a
live flip is a gated follow-up). These tests assert on COMPUTED
quantities (marginal-EHP closed forms, the verdict ordering, gold-cost
scaling) rather than data-fragile cross-item magnitudes.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import (
    _GOLD_PER_ARMOR,
    _GOLD_PER_HP,
    _GOLD_PER_MR,
    _armor_factor,
    compute_ehp,
    ehp_gold_efficiency,
)


class GoldConstantsTests(unittest.TestCase):
    """The three 16.12-standard gold-per-stat constants exist + are sane."""

    def test_constants_match_standard_values(self) -> None:
        # 16.12 standard per-point gold cost (documented at the source in
        # ehp.py). Armor 20g, MR 18g, HP 2.67g.
        self.assertAlmostEqual(_GOLD_PER_ARMOR, 20.0)
        self.assertAlmostEqual(_GOLD_PER_MR, 18.0)
        self.assertAlmostEqual(_GOLD_PER_HP, 2.67, places=2)

    def test_constants_are_positive(self) -> None:
        for c in (_GOLD_PER_ARMOR, _GOLD_PER_MR, _GOLD_PER_HP):
            self.assertGreater(c, 0.0)


class GoldEfficiencyUnitTests(unittest.TestCase):
    """Closed-form marginal-EHP / gold checks against the resolved build."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_keys_present_and_typed(self) -> None:
        res = ehp_gold_efficiency(self.snap, "Aatrox", level=11)
        for k in (
            "armor", "mr", "hp",
            "ehp_per_gold_armor", "ehp_per_gold_mr", "ehp_per_gold_hp",
            "ehp_gain_armor", "ehp_gain_mr", "ehp_gain_hp",
            "best_stat", "best_ehp_per_gold", "second_best_stat", "gap_to_second",
            "enemy_ad_share", "enemy_ap_share",
        ):
            self.assertIn(k, res)
        self.assertIn(res["best_stat"], ("armor", "mr", "hp"))
        self.assertIn(res["second_best_stat"], ("armor", "mr", "hp"))

    def test_hp_marginal_ehp_closed_form_pure_ad(self) -> None:
        # vs a pure-AD enemy, +1 HP raises blended EHP by 1/armor_factor(armor)
        # (the HP numerator scales; the phys damage-taken factor is the only
        # active divisor). Compare the helper's ehp_gain_hp to that closed form.
        ehp = compute_ehp(self.snap, "Aatrox", level=11, enemy_ad_share=1.0, enemy_ap_share=0.0)
        res = ehp_gold_efficiency(
            self.snap, "Aatrox", level=11, enemy_ad_share=1.0, enemy_ap_share=0.0
        )
        expected_gain = 1.0 / _armor_factor(ehp.armor)
        self.assertAlmostEqual(res["ehp_gain_hp"], expected_gain, places=4)
        self.assertAlmostEqual(
            res["ehp_per_gold_hp"], expected_gain / _GOLD_PER_HP, places=6
        )

    def test_armor_marginal_ehp_closed_form_pure_ad(self) -> None:
        # vs pure AD: +1 armor moves the phys damage-taken factor, raising
        # blended EHP by hp * (1/af(armor+1) - 1/af(armor)).
        ehp = compute_ehp(self.snap, "Aatrox", level=11, enemy_ad_share=1.0, enemy_ap_share=0.0)
        res = ehp_gold_efficiency(
            self.snap, "Aatrox", level=11, enemy_ad_share=1.0, enemy_ap_share=0.0
        )
        gain = ehp.hp * (1.0 / _armor_factor(ehp.armor + 1.0) - 1.0 / _armor_factor(ehp.armor))
        self.assertAlmostEqual(res["ehp_gain_armor"], gain, places=4)

    def test_mr_irrelevant_vs_pure_ad(self) -> None:
        # vs a pure-AD enemy, +1 MR yields zero marginal EHP (no magic share).
        res = ehp_gold_efficiency(
            self.snap, "Aatrox", level=11, enemy_ad_share=1.0, enemy_ap_share=0.0
        )
        self.assertAlmostEqual(res["ehp_gain_mr"], 0.0, places=6)
        self.assertAlmostEqual(res["ehp_per_gold_mr"], 0.0, places=6)
        # MR can never be the best stat when the enemy deals no magic.
        self.assertNotEqual(res["best_stat"], "mr")

    def test_armor_irrelevant_vs_pure_ap(self) -> None:
        res = ehp_gold_efficiency(
            self.snap, "Aatrox", level=11, enemy_ad_share=0.0, enemy_ap_share=1.0
        )
        self.assertAlmostEqual(res["ehp_gain_armor"], 0.0, places=6)
        self.assertNotEqual(res["best_stat"], "armor")

    def test_verdict_picks_max_ehp_per_gold(self) -> None:
        # best_stat is the argmax over the three per-gold figures; the gap to
        # second is non-negative and matches best - second.
        res = ehp_gold_efficiency(self.snap, "Aatrox", level=11)
        per_gold = {
            "armor": res["ehp_per_gold_armor"],
            "mr": res["ehp_per_gold_mr"],
            "hp": res["ehp_per_gold_hp"],
        }
        best = max(per_gold, key=per_gold.get)
        self.assertEqual(res["best_stat"], best)
        self.assertAlmostEqual(res["best_ehp_per_gold"], per_gold[best], places=9)
        self.assertGreaterEqual(res["gap_to_second"], 0.0)
        self.assertAlmostEqual(
            res["gap_to_second"],
            per_gold[res["best_stat"]] - per_gold[res["second_best_stat"]],
            places=9,
        )

    def test_pen_kwargs_lower_armor_efficiency(self) -> None:
        # The helper rides the T1-F3 enemy-pen seam: enemy lethality/armor-pen
        # erode the tank's effective armor, so +1 armor buys LESS EHP than vs
        # the un-penned case (verifies the seam is actually threaded).
        base = ehp_gold_efficiency(
            self.snap, "Aatrox", level=11, enemy_ad_share=1.0, enemy_ap_share=0.0
        )
        penned = ehp_gold_efficiency(
            self.snap, "Aatrox", level=11, enemy_ad_share=1.0, enemy_ap_share=0.0,
            enemy_armor_pen_pct=0.40, enemy_lethality=15.0,
        )
        self.assertLess(penned["ehp_gain_armor"], base["ehp_gain_armor"])

    def test_blended_mix_default(self) -> None:
        # The default 50/50 mix surfaces non-zero armor AND mr efficiency.
        res = ehp_gold_efficiency(self.snap, "Aatrox", level=11)
        self.assertGreater(res["ehp_gain_armor"], 0.0)
        self.assertGreater(res["ehp_gain_mr"], 0.0)
        self.assertGreater(res["ehp_gain_hp"], 0.0)


class AsciiHygieneTests(unittest.TestCase):
    def test_this_test_file_is_ascii(self) -> None:
        import pathlib
        src = pathlib.Path(__file__).read_bytes()
        bad = [(i, b) for i, b in enumerate(src) if b > 0x7F]
        self.assertEqual(bad, [], f"non-ASCII: {bad[:5]}")


if __name__ == "__main__":
    unittest.main()
