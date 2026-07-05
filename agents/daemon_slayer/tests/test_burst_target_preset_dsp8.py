"""DSP8 (1.134.0) - enemy-comp target-preset seam for the burst ranker.

Generalizes the DSV3 ``assume_squishy_target`` armor assumption (a single
binary squishy-carry armor curve) into four named enemy-comp presets -
``squishy`` / ``bruiser`` / ``tank`` / ``high_cc`` - each a representative
``(armor, MR)`` defensive profile the burst ranker substitutes for an
absent / zero target when ``target_preset`` is set.

Contract (mirrors the DSV1/2/3/4 + DSP4/5/6/7 seam convention):

* DEFAULT-OFF: ``target_preset=None`` is byte-identical to the DSV3 engine
  (no resist substitution unless ``assume_squishy_target`` is also set).
* BACK-COMPAT: ``assume_squishy_target=True`` is UNCHANGED - it still
  substitutes ARMOR only (no MR), exactly as DSV3 shipped. The richer
  ``target_preset="squishy"`` adds the representative MR the binary seam
  omitted, and the squishy preset's armor curve is identical to
  ``_assumed_squishy_target_armor`` so the two agree on armor.
* PRESETS substitute BOTH armor and MR, only when the caller did not pin a
  positive ``target_armor`` / ``target_mr`` respectively.

Assertions are formula anchor points (pin the curves this slice authors,
DSV3 ``test_formula_anchor_points`` precedent) plus monotonic /
computed-quantity checks (higher armor mitigates physical burst); NOT
fragile absolute cross-item comparisons.
"""
from __future__ import annotations

import unittest

from agents import daemon_slayer
from agents.daemon_slayer import ult_rates
from agents.daemon_slayer.abilities import reset_default_cache
from agents.daemon_slayer.burst import (
    _TARGET_PRESETS,
    _assumed_squishy_target_armor,
    _assumed_target_resists,
    rank_items_by_burst,
)
from agents.daemon_slayer.data_loader import DataSnapshot

# Youmuu's Ghostblade - 18 lethality + AD (effects.py lethality=18.0).
_LETHALITY_ITEM = "3142"
_CHAMP = "Zed"  # AD assassin: physical burst, so armor (not MR) mitigates.
_LEVEL = 11

# Anchor profiles at _LEVEL (L11) - the curves this slice authors.
# (armor, MR). squishy armor reuses the DSV3 curve (22 + 4.5/lvl -> 67@11).
_EXPECTED_L11 = {
    "squishy": (67.0, 35.0),
    "bruiser": (90.0, 55.0),
    "tank": (180.0, 110.0),
    "high_cc": (75.0, 70.0),
}


def _snap() -> DataSnapshot:
    reset_default_cache()
    ult_rates.reset_cache()
    return DataSnapshot.load()


class PresetResistCurveTests(unittest.TestCase):
    """Pure-formula tests - no snapshot load."""

    def test_all_four_presets_registered(self) -> None:
        self.assertEqual(
            set(_TARGET_PRESETS), {"squishy", "bruiser", "tank", "high_cc"}
        )

    def test_squishy_armor_matches_dsv3_curve(self) -> None:
        # The squishy preset's armor MUST equal the DSV3 standalone curve at
        # every level, so assume_squishy_target=True and target_preset="squishy"
        # never disagree on armor.
        for lvl in (1, 11, 18):
            self.assertAlmostEqual(
                _assumed_target_resists("squishy", lvl)[0],
                _assumed_squishy_target_armor(lvl),
            )

    def test_anchor_points_l11(self) -> None:
        for preset, (exp_armor, exp_mr) in _EXPECTED_L11.items():
            armor, mr = _assumed_target_resists(preset, _LEVEL)
            self.assertAlmostEqual(armor, exp_armor, msg=f"{preset} armor")
            self.assertAlmostEqual(mr, exp_mr, msg=f"{preset} mr")

    def test_monotonic_in_level(self) -> None:
        for preset in _TARGET_PRESETS:
            a1, m1 = _assumed_target_resists(preset, 1)
            a11, m11 = _assumed_target_resists(preset, 11)
            a18, m18 = _assumed_target_resists(preset, 18)
            self.assertLess(a1, a11, msg=f"{preset} armor 1<11")
            self.assertLess(a11, a18, msg=f"{preset} armor 11<18")
            self.assertLessEqual(m1, m11, msg=f"{preset} mr 1<=11")
            self.assertLessEqual(m11, m18, msg=f"{preset} mr 11<=18")
            self.assertGreater(a1, 0.0, msg=f"{preset} armor positive")

    def test_tank_is_tankiest_both_axes(self) -> None:
        tank_a, tank_m = _assumed_target_resists("tank", _LEVEL)
        for preset in ("squishy", "bruiser", "high_cc"):
            a, m = _assumed_target_resists(preset, _LEVEL)
            self.assertGreater(tank_a, a, msg=f"tank armor > {preset}")
            self.assertGreater(tank_m, m, msg=f"tank mr > {preset}")

    def test_squishy_is_squishiest_both_axes(self) -> None:
        sq_a, sq_m = _assumed_target_resists("squishy", _LEVEL)
        for preset in ("bruiser", "tank", "high_cc"):
            a, m = _assumed_target_resists(preset, _LEVEL)
            self.assertLess(sq_a, a, msg=f"squishy armor < {preset}")
            self.assertLess(sq_m, m, msg=f"squishy mr < {preset}")

    def test_unknown_preset_raises(self) -> None:
        with self.assertRaises(ValueError):
            _assumed_target_resists("bogus", _LEVEL)

    def test_level_out_of_range_raises(self) -> None:
        # Mirrors the DSV3 _assumed_squishy_target_armor clamp_level contract
        # (validates, not clamps); the ranker only calls this post-validation.
        with self.assertRaises(ValueError):
            _assumed_target_resists("tank", 0)
        with self.assertRaises(ValueError):
            _assumed_target_resists("tank", 99)


class TargetPresetSeamRankingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def _rank(self, **kw):
        return rank_items_by_burst(
            self.snap, champion_id=_CHAMP, level=_LEVEL,
            only_item_ids=[_LETHALITY_ITEM], **kw,
        )

    def test_default_off_is_zero_target(self) -> None:
        # No preset, no assume_squishy_target -> byte-identical DSV3 OFF:
        # the ranker leaves target_armor / target_mr at the caller's 0.
        res = self._rank()
        self.assertEqual(res.target_armor, 0.0)
        self.assertEqual(res.target_mr, 0.0)

    def test_assume_squishy_target_backcompat_mr_zero(self) -> None:
        # DSV3 back-compat: the binary seam substitutes ARMOR only; MR stays 0.
        res = self._rank(assume_squishy_target=True)
        self.assertAlmostEqual(
            res.target_armor, _assumed_squishy_target_armor(_LEVEL)
        )
        self.assertEqual(res.target_mr, 0.0)

    def test_squishy_preset_sets_armor_and_mr(self) -> None:
        # The richer preset path substitutes BOTH; armor agrees with DSV3.
        res = self._rank(target_preset="squishy")
        exp_armor, exp_mr = _EXPECTED_L11["squishy"]
        self.assertAlmostEqual(res.target_armor, exp_armor)
        self.assertAlmostEqual(res.target_mr, exp_mr)

    def test_each_preset_substitutes_its_profile(self) -> None:
        for preset, (exp_armor, exp_mr) in _EXPECTED_L11.items():
            res = self._rank(target_preset=preset)
            self.assertAlmostEqual(
                res.target_armor, exp_armor, msg=f"{preset} armor"
            )
            self.assertAlmostEqual(res.target_mr, exp_mr, msg=f"{preset} mr")

    def test_explicit_targets_not_overridden(self) -> None:
        # Caller-pinned positive resists win; the preset only fills absent ones.
        res = self._rank(target_preset="tank", target_armor=80.0, target_mr=60.0)
        self.assertEqual(res.target_armor, 80.0)
        self.assertEqual(res.target_mr, 60.0)

    def test_tank_mitigates_physical_more_than_squishy(self) -> None:
        # Computed-quantity / monotonic-mitigation: Zed's burst is physical, so
        # the tank preset (180 armor) yields strictly LESS baseline burst than
        # the squishy preset (67 armor). Exercises the end-to-end armor
        # substitution through the ranker, not a fragile absolute value.
        tank = self._rank(target_preset="tank")
        squishy = self._rank(target_preset="squishy")
        self.assertGreater(squishy.baseline_burst, tank.baseline_burst)

    def test_unknown_preset_raises_in_ranker(self) -> None:
        with self.assertRaises(ValueError):
            self._rank(target_preset="bogus")


class EngineVersionCurrentTests(unittest.TestCase):
    def test_engine_version(self) -> None:
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.181.0")


if __name__ == "__main__":
    unittest.main()
