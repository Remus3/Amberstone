"""RM-177 - Heal-and-Shield-Power composes ADDITIVELY, matching real League.

Until ENGINE 1.275.2 ``hps.py`` compounded every ``heal_shield_amp_pct`` as a
product while ``_hsp_amp.sum_wielder_hsp_pct`` summed the same field off the
same catalog. Two engines, one stat, opposite models - and two green tests
asserting each. The product convention over-credited superlinearly in HSP-item
count, so the error was largest on exactly the finished enchanter build the
scorer exists to rank (about 10 pct at six items).

The split shipped here is NOT "additive everywhere". ``heal_shield_amp_pct`` is
an overloaded field: rows flagged ``ally_chain_only`` (Moonstone Renewer 6617,
the only one at patch 16.15.1) carry an ally-CHAIN ratio rather than the printed
HSP stat, which is why ``_hsp_amp`` already skips them for the wielder. A chain
ratio genuinely multiplies the amped throughput, so it stays a product ON TOP of
the additive HSP term.

The load-bearing consequence, and the reason this file asserts equality rather
than a hand-computed float: for any build with no chain row, ``hps.py`` and
``_hsp_amp.py`` must now agree EXACTLY. That equality is the contract; the
individual numbers are downstream of it.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer._hsp_amp import sum_wielder_hsp_pct
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.hps import compute_hps, load_default_formulas

MOONSTONE = "6617"
REDEMPTION = "3107"
MIKAEL = "3222"
ARDENT = "3504"
STAFF = "6616"
IDOL = "3114"
CIRCLET = "2526"

CHAIN_FREE_BUILDS = (
    [REDEMPTION, MIKAEL],
    [REDEMPTION, MIKAEL, ARDENT, STAFF],
    [REDEMPTION, MIKAEL, ARDENT, STAFF, IDOL, CIRCLET],
)


class CrossEngineAgreementTests(unittest.TestCase):
    """The contract: one stat, one composition model, two call sites."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_chain_free_amp_equals_one_plus_additive_sum(self) -> None:
        for build in CHAIN_FREE_BUILDS:
            with self.subTest(n=len(build)):
                r = compute_hps(self.snap, "Soraka", level=13, item_ids=build)
                self.assertAlmostEqual(
                    r.amp_multiplier, 1.0 + sum_wielder_hsp_pct(build), places=9
                )

    def test_chain_row_stays_multiplicative_on_top(self) -> None:
        build = [MOONSTONE, REDEMPTION, ARDENT]
        r = compute_hps(self.snap, "Soraka", level=13, item_ids=build)
        # 6617 is skipped by sum_wielder_hsp_pct, so the additive term covers
        # only the printed-HSP rows and the chain ratio multiplies it.
        self.assertAlmostEqual(
            r.amp_multiplier,
            1.30 * (1.0 + sum_wielder_hsp_pct(build)),
            places=9,
        )
        self.assertAlmostEqual(r.amp_multiplier, 1.30 * 1.20, places=9)


class UnchangedCasesTests(unittest.TestCase):
    """Everything the flip must NOT move - the exclusion half of the contract."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_no_hsp_item_is_identity(self) -> None:
        r = compute_hps(self.snap, "Soraka", level=13, item_ids=["3020"])
        self.assertAlmostEqual(r.amp_multiplier, 1.0, places=9)

    def test_single_hsp_item_is_unchanged_by_the_split(self) -> None:
        # With one term, a sum and a product are the same number - so these
        # rows pin that the flip did not perturb the one-item case.
        for iid, pct in ((REDEMPTION, 0.10), (MIKAEL, 0.12), (ARDENT, 0.10)):
            with self.subTest(item=iid):
                r = compute_hps(self.snap, "Soraka", level=13, item_ids=[iid])
                self.assertAlmostEqual(r.amp_multiplier, 1.0 + pct, places=9)

    def test_moonstone_alone_is_unchanged(self) -> None:
        r = compute_hps(self.snap, "Soraka", level=13, item_ids=[MOONSTONE])
        self.assertAlmostEqual(r.amp_multiplier, 1.30, places=9)

    def test_mode_mirror_magnitudes_are_not_normalized(self) -> None:
        # Arena Redemption is 12 pct against SR's 10 - stripping the mirror
        # prefix would silently serve the SR line to an Arena build.
        sr = compute_hps(self.snap, "Soraka", level=13, item_ids=[REDEMPTION])
        arena = compute_hps(self.snap, "Soraka", level=13, item_ids=["223107"])
        self.assertAlmostEqual(sr.amp_multiplier, 1.10, places=9)
        self.assertAlmostEqual(arena.amp_multiplier, 1.12, places=9)


class DirectionAndShapeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_additive_never_exceeds_the_old_product(self) -> None:
        """Every multi-item build must move DOWN or stay equal, never up."""
        formulas = load_default_formulas()
        for build in CHAIN_FREE_BUILDS:
            with self.subTest(n=len(build)):
                product = 1.0
                for iid in build:
                    product *= 1.0 + formulas.get_formula(iid).heal_shield_amp_pct
                r = compute_hps(self.snap, "Soraka", level=13, item_ids=build)
                self.assertLessEqual(r.amp_multiplier, product + 1e-12)
                if len(build) > 1:
                    self.assertLess(r.amp_multiplier, product)

    def test_amp_is_monotone_non_decreasing_in_hsp_items(self) -> None:
        ladder = [REDEMPTION, MIKAEL, ARDENT, STAFF, IDOL, CIRCLET]
        prev = 1.0
        for n in range(len(ladder) + 1):
            r = compute_hps(self.snap, "Soraka", level=13, item_ids=ladder[:n])
            self.assertGreaterEqual(r.amp_multiplier, prev - 1e-12)
            prev = r.amp_multiplier

    def test_throughput_scales_with_the_amp_it_reports(self) -> None:
        build = [REDEMPTION, MIKAEL, ARDENT, STAFF]
        r = compute_hps(self.snap, "Soraka", level=13, item_ids=build)
        self.assertAlmostEqual(
            r.healing_hps, r.healing_hps_raw * r.amp_multiplier, places=6
        )


class ReferenceLaneIsUnmovedTests(unittest.TestCase):
    """`_hsp_amp` is the model being converged ON - it must not itself move."""

    def test_sum_is_still_plain_addition(self) -> None:
        self.assertAlmostEqual(
            sum_wielder_hsp_pct([REDEMPTION, MIKAEL]), 0.22, places=9
        )

    def test_chain_row_still_skipped_for_the_wielder(self) -> None:
        self.assertAlmostEqual(sum_wielder_hsp_pct([MOONSTONE]), 0.0, places=9)


if __name__ == "__main__":
    unittest.main()
