"""Regression (mid-game fix 2026-06-16): enemy AD/AP damage-type share is
derived from the enemy comp and threaded through the DS dispatch.

Before this, ``compute_enemy_stats`` had no enemy-champion input, so the
bruiser/tank EHP-side scorer always saw the rank_*_for 50/50 default. DS
therefore never recommended comp-appropriate resists (e.g. Wit's End vs an
AP-heavy comp). Jarvan IV ARAM vs Rumble/Lux/Maokai (ad_count 0 / ap_count 4)
surfaced pure-DPS items because the AP signal never reached the scorer.
"""
from __future__ import annotations

import unittest

from coach_integration.enemy_stats import EnemyStats, compute_enemy_stats


class TestEnemyAdApShare(unittest.TestCase):
    def test_defaults_to_even_split_without_comp(self):
        s = compute_enemy_stats("aram", level=12)
        self.assertEqual(s.ad_share, 0.5)
        self.assertEqual(s.ap_share, 0.5)

    def test_dataclass_has_share_fields_with_defaults(self):
        # Fields appended at the END with defaults - no positional break.
        s = EnemyStats(armor=1.0, mr=1.0, max_hp=1.0, bonus_hp=1.0)
        self.assertEqual(s.ad_share, 0.5)
        self.assertEqual(s.ap_share, 0.5)

    def test_ap_heavy_comp_skews_ap(self):
        # The live Jarvan game comp - AP-heavy (Rumble/Lux/Maokai/TF).
        s = compute_enemy_stats(
            "aram", level=12,
            enemy_champions=["Rumble", "Blitzcrank", "Maokai", "Lux", "Twisted Fate"],
        )
        self.assertGreater(s.ap_share, s.ad_share)
        self.assertGreater(s.ap_share, 0.7)
        self.assertAlmostEqual(s.ad_share + s.ap_share, 1.0, places=2)

    def test_ad_heavy_comp_skews_ad(self):
        s = compute_enemy_stats(
            "sr", level=12,
            enemy_champions=["Zed", "Jinx", "Tryndamere", "Darius", "Garen"],
        )
        self.assertGreater(s.ad_share, s.ap_share)
        self.assertAlmostEqual(s.ad_share + s.ap_share, 1.0, places=2)

    def test_unresolvable_comp_falls_back_even(self):
        s = compute_enemy_stats("aram", level=12, enemy_champions=["NotAChamp", "Zzz"])
        self.assertEqual(s.ad_share, 0.5)
        self.assertEqual(s.ap_share, 0.5)

    def test_empty_comp_falls_back_even(self):
        s = compute_enemy_stats("aram", level=12, enemy_champions=[])
        self.assertEqual(s.ad_share, 0.5)
        self.assertEqual(s.ap_share, 0.5)


class TestDispatchThreadsShares(unittest.TestCase):
    def test_dispatch_forwards_enemy_shares_to_engine(self):
        # dispatch_for_coach must forward enemy_ad_share/enemy_ap_share so the
        # bruiser/tank EHP-side scorer reacts to the comp.
        import coach_integration.archetype_dispatch as adisp
        from core import daemon_slayer_client as dsc

        captured: dict = {}

        def _fake_rank(**kwargs):
            captured.update(kwargs)
            return {"ok": True, "scorer": "hybrid", "archetype": "bruiser",
                    "ranked": [], "fell_back": False}

        orig = dsc.rank_for_primary_archetype
        dsc.rank_for_primary_archetype = _fake_rank
        try:
            es = EnemyStats(armor=100.0, mr=50.0, max_hp=2000.0, bonus_hp=1400.0,
                            ad_share=0.1, ap_share=0.9)
            adisp.dispatch_for_coach(
                champion="JarvanIV", mode_engine="ARAM", level=12,
                item_ids=["6631"], enemy_stats=es,
            )
        finally:
            dsc.rank_for_primary_archetype = orig

        self.assertAlmostEqual(captured.get("enemy_ad_share"), 0.1, places=3)
        self.assertAlmostEqual(captured.get("enemy_ap_share"), 0.9, places=3)


if __name__ == "__main__":
    unittest.main()
