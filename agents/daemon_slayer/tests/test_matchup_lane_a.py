"""Lane A 1v1 matchup engine - property-style invariants (DS Lane A, 2026-06-02).

Prefers property invariants (mirror symmetry, monotonicity, advantage direction)
over exact-value pins so the suite stays robust to patch-data drift. The 2-3
concrete champions are resolved against the live snapshot once and pinned to
exist; everything else asserts a computed quantity's shape or direction.
"""

from __future__ import annotations

import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.matchup import (
    MatchupResult,
    _ALL_IN_KILL_THRESHOLD,
    _EVEN_BAND,
    _TRADE_MARGIN,
    compute_matchup,
)

# Concrete champions verified to load from the live snapshot (one bruiser, one
# tanky-fighter, one mage - distinct defence + burst shapes). A full AP 6-item
# build for the item-advantage test.
_BRUISER = "Aatrox"
_FIGHTER = "Garen"
_MAGE = "Ahri"
_VERDICTS = {"all_in", "back_off", "trade", "even"}
_AP_SIX = ("3157", "3089", "3135", "3165", "3116", "4645")


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def _mk(self, *args, **kwargs) -> MatchupResult:
        return compute_matchup(self.snap, *args, **kwargs)


class SnapshotChampsExistTests(_Base):
    def test_fixture_champions_load(self) -> None:
        # If any of the 3 pinned champ ids drifted out of the snapshot the
        # whole suite is meaningless - assert they resolve up front.
        for champ in (_BRUISER, _FIGHTER, _MAGE):
            r = self._mk(champ, champ, 11, 11)
            self.assertEqual(r.champ_a, r.champ_b)
            self.assertGreater(r.a_hp_eff, 0.0)


class MirrorEvenTests(_Base):
    def test_same_champ_same_state_is_even(self) -> None:
        for champ in (_BRUISER, _FIGHTER, _MAGE):
            with self.subTest(champ=champ):
                r = self._mk(champ, champ, 11, 11)
                self.assertAlmostEqual(r.net_swing, 0.0, delta=1e-9)
                self.assertEqual(r.verdict, "even")
                # mirror trade is symmetric in both directions of damage too
                self.assertAlmostEqual(r.dmg_a_to_b, r.dmg_b_to_a, delta=1e-9)
                self.assertAlmostEqual(r.pct_a_removed, r.pct_b_removed, delta=1e-9)


class SymmetryTests(_Base):
    def test_swap_negates_net_swing(self) -> None:
        # Swap champ + level + items; net_swing(A,B) == -net_swing(B,A).
        ab = self._mk(
            _BRUISER, _FIGHTER, 11, 4,
            item_ids_a=list(_AP_SIX[:2]), item_ids_b=[],
        )
        ba = self._mk(
            _FIGHTER, _BRUISER, 4, 11,
            item_ids_a=[], item_ids_b=list(_AP_SIX[:2]),
        )
        self.assertAlmostEqual(ab.net_swing, -ba.net_swing, delta=1e-6)
        # damage A->B in the first call equals damage B->A in the swapped call
        self.assertAlmostEqual(ab.dmg_a_to_b, ba.dmg_b_to_a, delta=1e-6)
        self.assertAlmostEqual(ab.dmg_b_to_a, ba.dmg_a_to_b, delta=1e-6)

    def test_symmetry_holds_for_mage_pairing(self) -> None:
        ab = self._mk(_MAGE, _FIGHTER, 9, 13)
        ba = self._mk(_FIGHTER, _MAGE, 13, 9)
        self.assertAlmostEqual(ab.net_swing, -ba.net_swing, delta=1e-6)


class LevelAdvantageTests(_Base):
    def test_higher_level_favored(self) -> None:
        # Same champ + items, A at 11 vs B at 4 -> A favored, firmly enough to
        # be a trade or all_in (never back_off / even).
        for champ in (_BRUISER, _MAGE):
            with self.subTest(champ=champ):
                r = self._mk(champ, champ, 11, 4)
                self.assertGreater(r.net_swing, 0.0)
                self.assertIn(r.verdict, {"trade", "all_in"})


class ItemAdvantageTests(_Base):
    def test_full_build_beats_itemless(self) -> None:
        # Same champ + level, A on a full 6-item build vs B itemless -> A
        # favored.
        r = self._mk(_MAGE, _MAGE, 11, 11, item_ids_a=list(_AP_SIX), item_ids_b=[])
        self.assertGreater(r.net_swing, 0.0)
        self.assertGreater(r.dmg_a_to_b, r.dmg_b_to_a)


class MonotonicTests(_Base):
    def test_net_swing_non_decreasing_in_level_a(self) -> None:
        # B fixed at 9; A rising 6 -> 9 -> 12 -> 15 yields a non-decreasing
        # net_swing (more A levels never hurts A's trade).
        prev = None
        for level_a in (6, 9, 12, 15):
            with self.subTest(level_a=level_a):
                r = self._mk(_BRUISER, _FIGHTER, level_a, 9)
                if prev is not None:
                    self.assertGreaterEqual(r.net_swing + 1e-9, prev)
                prev = r.net_swing


class ToDictTests(_Base):
    def test_to_dict_round_trips_all_fields(self) -> None:
        r = self._mk(_BRUISER, _FIGHTER, 11, 11)
        d = r.to_dict()
        for key in (
            "champ_a", "champ_b", "level_a", "level_b", "dmg_a_to_b",
            "dmg_b_to_a", "a_hp_eff", "b_hp_eff", "pct_a_removed",
            "pct_b_removed", "net_swing", "verdict", "a_can_full_combo",
            "b_can_full_combo", "a_casts_allowed", "b_casts_allowed", "notes",
        ):
            self.assertIn(key, d)
        self.assertIsInstance(d["notes"], list)
        self.assertIn(d["verdict"], _VERDICTS)

    def test_verdict_always_one_of_four(self) -> None:
        for la, lb in ((1, 18), (18, 1), (11, 11), (6, 9)):
            with self.subTest(la=la, lb=lb):
                r = self._mk(_BRUISER, _MAGE, la, lb)
                self.assertIn(r.verdict, _VERDICTS)


class BoundedScalarTests(_Base):
    def test_removal_fractions_bounded(self) -> None:
        r = self._mk(_MAGE, _MAGE, 11, 11, item_ids_a=list(_AP_SIX), item_ids_b=[])
        self.assertGreaterEqual(r.pct_a_removed, 0.0)
        self.assertLessEqual(r.pct_a_removed, 1.0)
        self.assertGreaterEqual(r.pct_b_removed, 0.0)
        self.assertLessEqual(r.pct_b_removed, 1.0)
        self.assertGreaterEqual(r.net_swing, -1.0)
        self.assertLessEqual(r.net_swing, 1.0)

    def test_hp_pct_shrinks_effective_pool(self) -> None:
        # A target sitting at 50% HP has half the effective pool, so the same
        # combo removes a larger fraction (or kills outright).
        full = self._mk(_BRUISER, _FIGHTER, 11, 11)
        half = self._mk(_BRUISER, _FIGHTER, 11, 11, hp_b_pct=0.5)
        self.assertAlmostEqual(half.b_hp_eff, full.b_hp_eff * 0.5, delta=1.0)
        self.assertGreaterEqual(half.pct_b_removed, full.pct_b_removed)


class ThresholdConstantsTests(_Base):
    def test_threshold_constants_are_sane(self) -> None:
        self.assertEqual(_ALL_IN_KILL_THRESHOLD, 1.0)
        self.assertEqual(_TRADE_MARGIN, 0.10)
        self.assertEqual(_EVEN_BAND, 0.05)


class EngineVersionPinTests(_Base):
    def test_engine_version(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.278.1")


if __name__ == "__main__":
    unittest.main()
