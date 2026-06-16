"""DSV3 (1.126.0) - burst-archetype squishy-target armor seam.

P6-G5 residual 3: the lethality-vs-sustained-AD tradeoff in the burst
ranker. ``rank_items_by_burst`` defaults ``target_armor=0.0``; against zero
armor ``effective_target_armor`` floors its penetration tail at zero, so
lethality (flat armor pen) contributes NOTHING to a ranked item's delta and
an equal-cost raw-AD item out-ranks a lethality item. A burst assassin's real
target is a squishy carry WITH armor, against which flat pen bites.

``assume_squishy_target`` is an opt-in seam (DSV1/DSV2 precedent): default
False -> byte-identical to today's armor=0 ranking. When True and the caller
did not pin a positive ``target_armor``, the ranker substitutes a
representative squishy-carry armor so lethality flows through
``effective_target_armor`` and out-values raw AD.

Assertions are computed-quantity / difference-of-differences (not fragile
absolute cross-item comparisons): the seam SHIFTS value toward the lethality
item relative to a pure-AD item, which is the math the directive asks for.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import ult_rates
from agents.daemon_slayer.abilities import reset_default_cache
from agents.daemon_slayer.burst import (
    _assumed_squishy_target_armor,
    rank_items_by_burst,
)
from agents.daemon_slayer.data_loader import DataSnapshot

# Youmuu's Ghostblade - 18 lethality + AD (effects.py lethality=18.0).
_LETHALITY_ITEM = "3142"
# Bloodthirster - raw AD, zero lethality / armor pen (verified ITEM_EFFECTS).
_RAW_AD_ITEM = "3072"
_CHAMP = "Zed"  # AD assassin: lethality flows through every ability.
_LEVEL = 11


def _snap() -> DataSnapshot:
    reset_default_cache()
    ult_rates.reset_cache()
    return DataSnapshot.load()


def _delta(snap: DataSnapshot, item_id: str, **kw) -> float:
    """Marginal burst-damage gain of adding ``item_id`` to an empty build."""
    res = rank_items_by_burst(
        snap, champion_id=_CHAMP, level=_LEVEL, only_item_ids=[item_id], **kw
    )
    assert res.ranked, f"no ranked rows for {item_id}"
    return res.ranked[0].delta_burst


class AssumedSquishyArmorCurveTests(unittest.TestCase):
    def test_positive_and_monotonic(self) -> None:
        a1 = _assumed_squishy_target_armor(1)
        a11 = _assumed_squishy_target_armor(11)
        a18 = _assumed_squishy_target_armor(18)
        self.assertGreater(a1, 0.0)
        self.assertLess(a1, a11)
        self.assertLess(a11, a18)

    def test_formula_anchor_points(self) -> None:
        # 22 base + 4.5 per level above 1 - a mage/ADC armor curve.
        self.assertAlmostEqual(_assumed_squishy_target_armor(1), 22.0)
        self.assertAlmostEqual(_assumed_squishy_target_armor(11), 67.0)
        self.assertAlmostEqual(_assumed_squishy_target_armor(18), 98.5)

    def test_level_out_of_range_raises(self) -> None:
        # Mirrors the engine's clamp_level contract (validates, not clamps);
        # the ranker only ever calls this post-validation.
        with self.assertRaises(ValueError):
            _assumed_squishy_target_armor(0)
        with self.assertRaises(ValueError):
            _assumed_squishy_target_armor(99)


class SquishySeamRankingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_default_off_byte_identical(self) -> None:
        # Default (flag absent) == explicit OFF == today's armor=0 ranking.
        default = _delta(self.snap, _LETHALITY_ITEM)
        off = _delta(self.snap, _LETHALITY_ITEM, assume_squishy_target=False)
        self.assertEqual(default, off)

    def test_seam_sets_assumed_armor(self) -> None:
        on = rank_items_by_burst(
            self.snap, champion_id=_CHAMP, level=_LEVEL,
            only_item_ids=[_LETHALITY_ITEM], assume_squishy_target=True,
        )
        off = rank_items_by_burst(
            self.snap, champion_id=_CHAMP, level=_LEVEL,
            only_item_ids=[_LETHALITY_ITEM], assume_squishy_target=False,
        )
        self.assertAlmostEqual(
            on.target_armor, _assumed_squishy_target_armor(_LEVEL)
        )
        self.assertEqual(off.target_armor, 0.0)

    def test_lethality_outvalues_raw_ad_under_seam(self) -> None:
        # Difference-of-differences: turning the seam ON shifts marginal burst
        # value TOWARD the lethality item relative to the raw-AD item, because
        # only the lethality item penetrates the assumed squishy armor.
        off_leth = _delta(self.snap, _LETHALITY_ITEM, assume_squishy_target=False)
        off_ad = _delta(self.snap, _RAW_AD_ITEM, assume_squishy_target=False)
        on_leth = _delta(self.snap, _LETHALITY_ITEM, assume_squishy_target=True)
        on_ad = _delta(self.snap, _RAW_AD_ITEM, assume_squishy_target=True)
        self.assertGreater((on_leth - on_ad), (off_leth - off_ad))

    def test_explicit_target_armor_not_overridden(self) -> None:
        # A caller-pinned positive target_armor is respected; the seam is a
        # no-op (it only fills in an absent / zero target).
        on = _delta(
            self.snap, _LETHALITY_ITEM, target_armor=80.0,
            assume_squishy_target=True,
        )
        off = _delta(
            self.snap, _LETHALITY_ITEM, target_armor=80.0,
            assume_squishy_target=False,
        )
        self.assertEqual(on, off)


if __name__ == "__main__":
    unittest.main()
