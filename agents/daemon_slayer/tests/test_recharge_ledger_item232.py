"""Tests for agents/daemon_slayer/recharge_ledger.py (item 232).

Data probed against 16.11.1 snapshots before pinning:

CDragon (slot-keyed, authoritative):
  Vi E: max=[2,2,2,2,2,2,2], recharge=[12.0,12.0,11.0,10.0,9.0,8.0,8.0]
    rank=None -> idx=6 -> recharge_s=8.0, max_charges=2
    rank=0    -> idx=0 -> recharge_s=12.0, max_charges=2

Wiki fallback (name-keyed, no cdragon ammo on any slot):
  Vel'Koz E (slot): no cdragon ammo
  ability_recharge('Vel'Koz', 'Void Rift') -> [19.0,18.0,17.0,16.0,15.0]
    rank=None -> idx=4 -> recharge_s=15.0, max_charges=1.0 (wiki has no max)

Non-charge: Aatrox Q, no ammo, no ability_name -> source="none", 0 casts.
"""
import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.recharge_ledger import (
    RechargeLedger,
    _clamp_rank,
    compute_recharge_ledger,
)


class ClampRankTests(unittest.TestCase):
    """Unit tests for _clamp_rank helper."""

    def test_none_clamps_to_last(self):
        self.assertEqual(_clamp_rank(None, 7), 6)

    def test_negative_clamps_to_last(self):
        self.assertEqual(_clamp_rank(-1, 5), 4)

    def test_zero_is_first(self):
        self.assertEqual(_clamp_rank(0, 7), 0)

    def test_mid_rank(self):
        self.assertEqual(_clamp_rank(3, 7), 3)

    def test_exact_last(self):
        self.assertEqual(_clamp_rank(6, 7), 6)

    def test_overflow_clamps_to_last(self):
        self.assertEqual(_clamp_rank(99, 7), 6)

    def test_length_zero_returns_zero(self):
        self.assertEqual(_clamp_rank(None, 0), 0)


class CdragonSourceTests(unittest.TestCase):
    """Grounded tests using Vi E (authoritative cdragon ammo)."""

    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()

    def _ledger(self, window_s, rank=None):
        return compute_recharge_ledger(
            self.snap, "Vi", "E", window_s, rank=rank
        )

    def test_source_is_cdragon(self):
        lg = self._ledger(30)
        self.assertEqual(lg.source, "cdragon")

    def test_max_rank_recharge_s(self):
        # rank=None -> idx=6 -> recharge=[...8.0]
        lg = self._ledger(30)
        self.assertAlmostEqual(lg.recharge_s, 8.0, places=3)

    def test_max_rank_max_charges(self):
        # max=[2]*7 -> 2.0
        lg = self._ledger(30)
        self.assertAlmostEqual(lg.max_charges, 2.0, places=2)

    def test_charges_at_start_equals_max(self):
        lg = self._ledger(30)
        self.assertAlmostEqual(lg.charges_at_start, lg.max_charges, places=2)

    def test_window_30_exact_total(self):
        # recharge_s=8.0, max=2, window=30
        # recharges_in_window = int(30 // 8) = 3
        # total = 2 + 3 = 5
        lg = self._ledger(30)
        self.assertEqual(lg.recharges_in_window, 3)
        self.assertAlmostEqual(lg.total_casts_available, 5.0, places=2)

    def test_champion_and_slot_fields(self):
        lg = self._ledger(10)
        self.assertEqual(lg.champion, "Vi")
        self.assertEqual(lg.slot, "E")

    def test_rank0_gives_different_recharge(self):
        # rank=0 -> idx=0 -> recharge=[12.0,...] which differs from rank=None (8.0)
        lg_max = self._ledger(30)
        lg_r0 = self._ledger(30, rank=0)
        self.assertAlmostEqual(lg_r0.recharge_s, 12.0, places=3)
        self.assertNotAlmostEqual(lg_r0.recharge_s, lg_max.recharge_s, places=1)

    def test_rank0_window30_total(self):
        # recharge_s=12.0, max=2, window=30
        # recharges = int(30 // 12) = 2
        # total = 2 + 2 = 4
        lg = self._ledger(30, rank=0)
        self.assertEqual(lg.recharges_in_window, 2)
        self.assertAlmostEqual(lg.total_casts_available, 4.0, places=2)


class WindowMonotonicityTests(unittest.TestCase):
    """total_casts_available is non-decreasing as window grows."""

    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()

    def test_monotonic_windows(self):
        windows = [0, 10, 30, 60, 120]
        totals = [
            compute_recharge_ledger(self.snap, "Vi", "E", w).total_casts_available
            for w in windows
        ]
        for i in range(1, len(totals)):
            self.assertGreaterEqual(
                totals[i],
                totals[i - 1],
                msg=f"total decreased from window {windows[i-1]} to {windows[i]}",
            )

    def test_window_0_equals_max_charges(self):
        lg = compute_recharge_ledger(self.snap, "Vi", "E", 0)
        self.assertAlmostEqual(lg.total_casts_available, lg.max_charges, places=2)

    def test_window_120_exact(self):
        # recharge_s=8.0, max=2, window=120
        # recharges = int(120//8) = 15
        # total = 2 + 15 = 17
        lg = compute_recharge_ledger(self.snap, "Vi", "E", 120)
        self.assertEqual(lg.recharges_in_window, 15)
        self.assertAlmostEqual(lg.total_casts_available, 17.0, places=2)

    def test_window_10(self):
        # recharge_s=8.0, max=2, window=10
        # recharges = int(10//8) = 1
        # total = 2 + 1 = 3
        lg = compute_recharge_ledger(self.snap, "Vi", "E", 10)
        self.assertEqual(lg.recharges_in_window, 1)
        self.assertAlmostEqual(lg.total_casts_available, 3.0, places=2)

    def test_window_60(self):
        # recharge_s=8.0, max=2, window=60
        # recharges = int(60//8) = 7
        # total = 2 + 7 = 9
        lg = compute_recharge_ledger(self.snap, "Vi", "E", 60)
        self.assertEqual(lg.recharges_in_window, 7)
        self.assertAlmostEqual(lg.total_casts_available, 9.0, places=2)


class WikiFallbackTests(unittest.TestCase):
    """Grounded tests using Vel'Koz E (wiki-only, no cdragon ammo for slot E)."""

    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()

    def test_source_is_wiki_when_no_cdragon(self):
        # Vel'Koz slot E has no cdragon ammo; wiki has 'Void Rift' recharge_ranks
        lg = compute_recharge_ledger(
            self.snap, "Vel'Koz", "E", 30, ability_name="Void Rift"
        )
        self.assertEqual(lg.source, "wiki")

    def test_wiki_max_charges_is_one(self):
        lg = compute_recharge_ledger(
            self.snap, "Vel'Koz", "E", 30, ability_name="Void Rift"
        )
        self.assertAlmostEqual(lg.max_charges, 1.0, places=2)

    def test_wiki_max_rank_recharge_s(self):
        # recharge_ranks=[19,18,17,16,15] -> idx=4 -> 15.0
        lg = compute_recharge_ledger(
            self.snap, "Vel'Koz", "E", 30, ability_name="Void Rift"
        )
        self.assertAlmostEqual(lg.recharge_s, 15.0, places=3)

    def test_wiki_window30_total(self):
        # recharge_s=15.0, max=1, window=30
        # recharges = int(30//15) = 2
        # total = 1 + 2 = 3
        lg = compute_recharge_ledger(
            self.snap, "Vel'Koz", "E", 30, ability_name="Void Rift"
        )
        self.assertEqual(lg.recharges_in_window, 2)
        self.assertAlmostEqual(lg.total_casts_available, 3.0, places=2)

    def test_wiki_rank0_recharge_s(self):
        # rank=0 -> idx=0 -> recharge_ranks[0]=19.0
        lg = compute_recharge_ledger(
            self.snap, "Vel'Koz", "E", 30, rank=0, ability_name="Void Rift"
        )
        self.assertAlmostEqual(lg.recharge_s, 19.0, places=3)

    def test_no_ability_name_falls_through_to_none(self):
        # Without ability_name, slot E has no cdragon ammo -> source="none"
        lg = compute_recharge_ledger(self.snap, "Vel'Koz", "E", 30)
        self.assertEqual(lg.source, "none")
        self.assertAlmostEqual(lg.total_casts_available, 0.0, places=2)


class NonChargeTests(unittest.TestCase):
    """Abilities with no ammo data at all return source='none'."""

    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()

    def test_aatrox_q_is_none_source(self):
        lg = compute_recharge_ledger(self.snap, "Aatrox", "Q", 30)
        self.assertEqual(lg.source, "none")

    def test_aatrox_q_total_casts_zero(self):
        lg = compute_recharge_ledger(self.snap, "Aatrox", "Q", 30)
        self.assertAlmostEqual(lg.total_casts_available, 0.0, places=2)

    def test_none_ledger_max_charges_zero(self):
        lg = compute_recharge_ledger(self.snap, "Aatrox", "Q", 30)
        self.assertAlmostEqual(lg.max_charges, 0.0, places=2)

    def test_none_ledger_recharges_zero(self):
        lg = compute_recharge_ledger(self.snap, "Aatrox", "Q", 30)
        self.assertEqual(lg.recharges_in_window, 0)

    def test_none_recharge_s_zero(self):
        lg = compute_recharge_ledger(self.snap, "Aatrox", "Q", 30)
        self.assertAlmostEqual(lg.recharge_s, 0.0, places=3)


class FailSoftTests(unittest.TestCase):
    """Edge cases and fail-soft behavior."""

    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()

    def test_unknown_champ_no_raise(self):
        lg = compute_recharge_ledger(self.snap, "NotAChampion", "E", 30)
        self.assertEqual(lg.source, "none")
        self.assertAlmostEqual(lg.total_casts_available, 0.0, places=2)

    def test_unknown_champ_field_values(self):
        lg = compute_recharge_ledger(self.snap, "NotAChampion", "E", 30)
        self.assertEqual(lg.champion, "NotAChampion")
        self.assertEqual(lg.slot, "E")
        self.assertAlmostEqual(lg.window_s, 30.0, places=3)

    def test_negative_window_treated_as_zero(self):
        lg = compute_recharge_ledger(self.snap, "Vi", "E", -5)
        self.assertGreaterEqual(lg.window_s, 0.0)
        self.assertGreaterEqual(lg.total_casts_available, 0.0)

    def test_window_zero_no_recharges(self):
        lg = compute_recharge_ledger(self.snap, "Vi", "E", 0)
        self.assertEqual(lg.recharges_in_window, 0)

    def test_result_is_frozen_dataclass(self):
        lg = compute_recharge_ledger(self.snap, "Vi", "E", 30)
        self.assertIsInstance(lg, RechargeLedger)
        with self.assertRaises((AttributeError, TypeError)):
            lg.source = "mutated"  # type: ignore[misc]


class AsciiHygieneTests(unittest.TestCase):
    """No non-ASCII bytes in the new source files."""

    def _check_file(self, path):
        import pathlib
        content = pathlib.Path(path).read_bytes()
        bad = [i for i, b in enumerate(content) if b > 127]
        self.assertEqual(
            bad,
            [],
            msg=f"{path}: non-ASCII bytes at offsets {bad[:5]}",
        )

    def test_recharge_ledger_ascii(self):
        import pathlib
        here = pathlib.Path(__file__).parent.parent
        self._check_file(here / "recharge_ledger.py")

    def test_test_file_ascii(self):
        self._check_file(__file__)


if __name__ == "__main__":
    unittest.main()
