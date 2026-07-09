"""HOT-01 (2026-07-09): compute_dps ``only_phase`` opt-in single-phase path.

The ranker only ever reads ``weighted_dps`` (the selected phase); computing
early+mid+late per candidate discards 2/3 of the rotation convolution.
``only_phase`` lets a caller compute JUST the selected phase. This proves:

  (a) the DEFAULT path (only_phase=None) is byte-identical - full 3-phase
      output, weighted_dps == phase_dps[selected];
  (b) only_phase=selected yields the SAME weighted_dps as the full path for
      that phase, across champions / levels / phases / modes / builds - so
      rank_items (which reads only weighted_dps + phase-independent stats)
      stays byte-identical;
  (c) a mismatched or invalid only_phase fails loudly (no silent KeyError /
      dropped candidate).
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import PHASES, _select_phase, compute_dps
from agents.daemon_slayer.rank import rank_items

# (champion_id, item_ids) fixtures - real champions with nonzero AA DPS.
_BUILDS = [
    ("Aatrox", ()),
    ("Aatrox", ("3072",)),
    ("Ashe", ("3006", "3031")),
    ("Ahri", ("3020",)),
    ("Leona", ()),
]
# Levels chosen to straddle every phase boundary (early<=6, mid<=12, late).
_LEVELS = (1, 6, 7, 12, 13, 18)
_MODES = ("SR", "ARAM")


class DefaultUnchangedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_default_output_is_full_three_phase(self) -> None:
        # only_phase=None (default) -> phase_dps carries all 3 phases and
        # weighted_dps is the selected phase's value. This is the byte-identical
        # legacy shape /dps CLI + existing tests depend on.
        for champ, items in _BUILDS:
            for level in _LEVELS:
                r = compute_dps(self.snap, champ, level=level, item_ids=items)
                self.assertEqual(set(r.phase_dps.keys()), set(PHASES),
                                 f"{champ} L{level}: phase_dps not full 3-phase")
                self.assertEqual(r.weighted_dps, r.phase_dps[r.phase],
                                 f"{champ} L{level}: weighted_dps != selected")

    def test_default_is_deterministic(self) -> None:
        # Adding the param must not perturb the default result across calls.
        a = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3072"])
        b = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3072"])
        self.assertEqual(a.weighted_dps, b.weighted_dps)
        self.assertEqual(a.phase_dps, b.phase_dps)


class OnlyPhaseParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_only_phase_matches_full_selected(self) -> None:
        # For every champ/level/mode/build, only_phase=selected must reproduce
        # the full path's selected-phase weighted_dps exactly.
        for champ, items in _BUILDS:
            for level in _LEVELS:
                for mode in _MODES:
                    full = compute_dps(
                        self.snap, champ, level=level, item_ids=items, mode=mode,
                        apply_mode_modifiers=True,
                    )
                    sel = full.phase
                    single = compute_dps(
                        self.snap, champ, level=level, item_ids=items, mode=mode,
                        apply_mode_modifiers=True, only_phase=sel,
                    )
                    self.assertEqual(
                        single.weighted_dps, full.weighted_dps,
                        f"{champ} L{level} {mode}: only_phase weighted_dps drift",
                    )
                    self.assertEqual(
                        single.weighted_dps, full.phase_dps[sel],
                        f"{champ} L{level} {mode}: only_phase != full[{sel}]",
                    )

    def test_only_phase_honors_explicit_phase_arg(self) -> None:
        # When the caller pins phase="early" explicitly, only_phase="early" must
        # match full[early] even at a level whose auto-selected phase differs.
        full = compute_dps(self.snap, "Aatrox", level=18, phase="early")
        single = compute_dps(self.snap, "Aatrox", level=18, phase="early",
                             only_phase="early")
        self.assertEqual(single.phase, "early")
        self.assertEqual(single.weighted_dps, full.weighted_dps)


class OnlyPhaseGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_only_phase_mismatch_raises(self) -> None:
        # only_phase must equal the phase the result is weighted for; a mismatch
        # would KeyError on phase_dps[selected] - guard it loudly instead.
        with self.assertRaises(ValueError):
            compute_dps(self.snap, "Aatrox", level=18, phase="late",
                        only_phase="early")

    def test_only_phase_invalid_value_raises(self) -> None:
        with self.assertRaises(ValueError):
            compute_dps(self.snap, "Aatrox", level=11, only_phase="endgame")

    def test_only_phase_none_is_default(self) -> None:
        a = compute_dps(self.snap, "Aatrox", level=11)
        b = compute_dps(self.snap, "Aatrox", level=11, only_phase=None)
        self.assertEqual(a.weighted_dps, b.weighted_dps)
        self.assertEqual(a.phase_dps, b.phase_dps)


class RankItemsStillGreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_rank_items_baseline_matches_full_compute(self) -> None:
        # rank_items now passes only_phase internally; confirm the baseline_dps
        # it reports equals a full-path compute_dps baseline (candidates are not
        # silently dropped by a spurious only_phase ValueError).
        res = rank_items(self.snap, "Ashe", level=11,
                         current_item_ids=["3006"], mode="SR", top_n=5)
        self.assertTrue(res.ranked, "rank_items returned no candidates")
        full_baseline = compute_dps(self.snap, "Ashe", level=11,
                                    item_ids=["3006"], mode="SR")
        self.assertEqual(res.baseline_dps, full_baseline.weighted_dps)

    def test_rank_items_deltas_match_full_recompute(self) -> None:
        # Each ranked row's delta must equal (full candidate weighted_dps -
        # full baseline weighted_dps) - byte-identical to the pre-HOT-01 ranker.
        current = ["3006"]
        res = rank_items(self.snap, "Ashe", level=11,
                         current_item_ids=current, mode="SR", top_n=8)
        base = compute_dps(self.snap, "Ashe", level=11,
                           item_ids=current, mode="SR").weighted_dps
        for row in res.ranked:
            full = compute_dps(self.snap, "Ashe", level=11,
                               item_ids=[*current, str(row.item_id)], mode="SR")
            self.assertAlmostEqual(
                row.delta_dps, full.weighted_dps - base, places=6,
                msg=f"delta drift for item {row.item_id}",
            )


if __name__ == "__main__":
    unittest.main()
