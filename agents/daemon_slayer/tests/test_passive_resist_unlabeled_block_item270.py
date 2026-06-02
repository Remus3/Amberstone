"""Item 270 - unlabeled MULTI-STAT / MULTI-SERIES block RESIST-STAT grants.

Closes the last seedable resist-grant EXCLUSION class from items 264/267/268: a
parsed Meraki block bundles several stats or two value series with no per-stat
label, so item 264 deferred the four as "value cannot be confidently attributed".
HAND attribution resolves the FLAT BASE cleanly:

  - Singed R Insanity Potion: ONE shared series [25,60,95] = AP == armor == MR.
  - Braum W / Leona W / Jax R: a TWO-series block where series[0] VARIES by
    ability rank (the flat base) and series[1] is a rank-CONSTANT percent
    coefficient -> the flat base is seeded (rank_scaled), the percent + the
    AP/MS/regen/per-instance-DR/per-hit sub-terms are documented omissions.

No new schema field - the existing flat-add ``rank_scaled`` machinery (item 267)
handles all four. ``apply_passive_resist`` defaults False -> byte-identical.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import compute_ehp
from agents.daemon_slayer._passive_resist_overrides import (
    _ACTIVE_RESIST_PROB,
    _PASSIVE_RESIST_OVERRIDES,
    resist_grants,
)

_NEW = ("Singed", "Braum", "Leona", "Jax")
_P = _ACTIVE_RESIST_PROB  # 0.3


class RegistryShapeTests(unittest.TestCase):
    def test_total_entries_grew_to_twenty(self):
        self.assertGreaterEqual(len(_PASSIVE_RESIST_OVERRIDES), 20)

    def test_four_new_champs_present_rank_scaled_flat(self):
        by_cid = {k[0]: v for k, v in _PASSIVE_RESIST_OVERRIDES.items()}
        for c in _NEW:
            self.assertIn(c, by_cid, c)
            e = by_cid[c]
            self.assertTrue(e.rank_scaled, f"{c} should be rank_scaled")
            self.assertFalse(e.level_scaled, f"{c} not level_scaled")
            # flat-add only: no percent-of-resist half (omitted per-champ)
            self.assertEqual(e.armor_pct, 0.0, c)
            self.assertEqual(e.mr_pct, 0.0, c)
            self.assertIsInstance(e.armor, tuple, c)
            self.assertTrue(e.note.strip(), c)

    def test_keys_use_expected_slots(self):
        want = {("Singed", "R", 0), ("Braum", "W", 0), ("Leona", "W", 0), ("Jax", "R", 0)}
        self.assertTrue(want <= set(_PASSIVE_RESIST_OVERRIDES))


class SingedSharedSeriesTests(unittest.TestCase):
    """Singed R: one shared [25,60,95] series == armor == MR, R-rank scaled,
    active-amortized; AP/MS/regen omitted."""

    def test_singed_r_unlearned_below_six(self):
        self.assertEqual(resist_grants("Singed", 5, True), (0.0, 0.0))

    def test_singed_r_rank_scaled_armor_eq_mr(self):
        for lvl, base in ((6, 25.0), (11, 60.0), (16, 95.0), (18, 95.0)):
            a, m = resist_grants("Singed", lvl, True)
            self.assertAlmostEqual(a, base * _P, places=6, msg=f"lvl{lvl}")
            self.assertAlmostEqual(m, a, places=9, msg=f"lvl{lvl} mr==armor")


class TwoSeriesFlatBaseTests(unittest.TestCase):
    """Braum/Leona W + Jax R: series[0] flat base by rank, percent series omitted."""

    def test_braum_w_armor_eq_mr_by_rank(self):
        # W rank 0/2/4 at L5/11/16 -> base 20/30/40, * 0.3
        for lvl, base in ((5, 20.0), (11, 30.0), (16, 40.0)):
            a, m = resist_grants("Braum", lvl, True)
            self.assertAlmostEqual(a, base * _P, places=6, msg=f"lvl{lvl}")
            self.assertAlmostEqual(m, a, places=9, msg=f"lvl{lvl} mr==armor")

    def test_leona_w_armor_eq_mr_by_rank(self):
        for lvl, base in ((11, 35.0), (16, 50.0)):
            a, m = resist_grants("Leona", lvl, True)
            self.assertAlmostEqual(a, base * _P, places=6, msg=f"lvl{lvl}")
            self.assertAlmostEqual(m, a, places=9, msg=f"lvl{lvl} mr==armor")

    def test_jax_r_armor_and_mr_differ(self):
        # armor [25,50,75] vs MR [15,30,45] by R rank 0/1/2 at L6/11/16, * 0.3
        for lvl, ba, bm in ((6, 25.0, 15.0), (11, 50.0, 30.0), (16, 75.0, 45.0)):
            a, m = resist_grants("Jax", lvl, True)
            self.assertAlmostEqual(a, ba * _P, places=6, msg=f"lvl{lvl} armor")
            self.assertAlmostEqual(m, bm * _P, places=6, msg=f"lvl{lvl} mr")

    def test_jax_r_unlearned_below_six(self):
        self.assertEqual(resist_grants("Jax", 5, True), (0.0, 0.0))


class DefaultOffByteIdenticalTests(unittest.TestCase):
    """apply_passive_resist=False -> 0/0 for every new champ at every level."""

    def test_all_new_champs_zero_when_flag_off(self):
        for c in _NEW:
            for lvl in (1, 6, 11, 16, 18):
                self.assertEqual(resist_grants(c, lvl, False), (0.0, 0.0), f"{c} L{lvl}")


class EhpIntegrationTests(unittest.TestCase):
    """Flag-OFF EHP byte-identical; flag-ON raises EHP for a seeded champ."""

    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()

    def _ehp(self, champ, level, apply):
        return compute_ehp(
            self.snap, champ, level, item_ids=[],
            apply_passive_resist=apply,
        )

    def test_singed_flag_off_byte_identical(self):
        off = self._ehp("Singed", 16, False)
        # baseline EHP has no passive-resist addend
        self.assertEqual(off.passive_resist_armor, 0.0)
        self.assertEqual(off.passive_resist_mr, 0.0)

    def test_singed_flag_on_raises_ehp(self):
        off = self._ehp("Singed", 16, False)
        on = self._ehp("Singed", 16, True)
        self.assertGreater(on.passive_resist_armor, 0.0)
        self.assertAlmostEqual(on.passive_resist_armor, 95.0 * _P, places=4)
        self.assertAlmostEqual(on.passive_resist_mr, 95.0 * _P, places=4)
        # reported armor/mr stay the resolved build stats (grant surfaced separately)
        self.assertAlmostEqual(on.armor, off.armor, places=6)
        self.assertGreater(on.blended_ehp, off.blended_ehp)

    def test_unseeded_champ_flag_on_byte_identical(self):
        # Caitlyn has no resist grant -> flag-on must not change EHP
        off = self._ehp("Caitlyn", 16, False)
        on = self._ehp("Caitlyn", 16, True)
        self.assertEqual(on.passive_resist_armor, 0.0)
        self.assertAlmostEqual(on.blended_ehp, off.blended_ehp, places=6)


class EngineVersionTests(unittest.TestCase):
    def test_engine_at_least_197(self):
        major, minor, *_ = (int(x) for x in ENGINE_VERSION.split("."))
        self.assertGreaterEqual((major, minor), (1, 97))


class AsciiHygieneTests(unittest.TestCase):
    def test_module_and_test_ascii(self):
        import agents.daemon_slayer._passive_resist_overrides as mod
        for path in (mod.__file__, __file__):
            with open(path, "rb") as fh:
                fh.read().decode("ascii")  # raises on any non-ASCII byte


if __name__ == "__main__":
    unittest.main()
