"""R42 (2026-06-30) - Yun Tal conditional-AS (Flurry) base-AS fold regression.

``total_conditional_as`` returns a bonus-AS FRACTION (Yun Tal Flurry,
uptime-weighted ~0.08 = +8% bonus AS), but ``stats['as']`` is FINAL attacks
per second (engine resolves it as ``base_as * (1 + bonus_pct)``). ``compute_dps``
must fold the conditional AS in as ``base_as * fraction``, NOT add the raw
fraction to the final rotation AS - otherwise it over-credits AS by a factor of
``1 / base_as`` (the same unit bug R7 fixed for the per-stack ``passive_as``
seam, the fold sitting directly below this one in dps.py).

The Yun Tal item (3032) carries the cond_as field automatically (no flag), so
the counterfactual is built by monkeypatching ``dps.total_conditional_as`` to
0.0 - identical resolved stats, only the fold differs (the analog of R7's
``assume_passive_as_stacks`` toggle). compute_dps does not memoize, so the
patched and real calls return distinct results for the same args.

``weighted_dps`` is exactly affine in rotation AS (``total_attacks = basic +
basic_time * as``; ``base_dps = total_attacks * avg_dmg / duration``; duration
is AS-independent), so builds that differ ONLY in attack speed are colinear.
Dagger (1042) is pure +AS (no AD/crit/AP/on-hit), the AS calibration point. The
real (cond_as ON) build's DPS gain over the patched-off build must match a
``base_as * fraction`` AS delta, not a raw ``fraction`` delta.
"""
from __future__ import annotations

import unittest
from unittest import mock

from agents import daemon_slayer
from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer._effects_data import ITEM_EFFECTS
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps
from agents.daemon_slayer.effects import total_conditional_as


class EngineVersion(unittest.TestCase):
    def test_engine_version_pinned(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.198.0")
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.198.0")


class CondAsAddsBaseAsScaledFraction(unittest.TestCase):
    """Regression guard: cond_as folds as ``base_as * fraction``, not raw.

    The fold only moves ``weighted_dps`` (``raw_attack_dps`` reads the un-folded
    ``eff_as``), so the gain is read through ``weighted_dps`` exactly as the R7
    ``SeamAddsBaseAsScaledFraction`` guard does for ``passive_as``.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_cond_as_gain_matches_base_as_scaled_fraction(self) -> None:
        cid, level = "Caitlyn", 11  # marksman, base AS < 1 (bug is large), autos
        yt = ["3032"]                # Yun Tal carries cond_as
        yt_dagger = ["3032", "1042"]  # + pure-AS calibration point
        # Counterfactual: identical resolved stats, cond_as fold suppressed.
        with mock.patch(
            "agents.daemon_slayer.dps.total_conditional_as", return_value=0.0
        ):
            off = compute_dps(self.snap, cid, level=level, item_ids=yt,
                              target_armor=80)
            cal = compute_dps(self.snap, cid, level=level, item_ids=yt_dagger,
                              target_armor=80)
        # Real build: cond_as fires (must be the base_as-scaled fold).
        on = compute_dps(self.snap, cid, level=level, item_ids=yt,
                         target_armor=80)
        a0 = off.stats["as"]
        a_cal = cal.stats["as"]
        base_as = float(
            (self.snap.champion(cid).get("stats") or {}).get("attackspeed", 0.0)
        )
        cond = total_conditional_as([ITEM_EFFECTS["3032"]])
        # Preconditions (fail loudly if the fixture stops exercising the path).
        self.assertGreater(cond, 0.0)
        self.assertGreater(base_as, 0.0)
        self.assertLess(base_as, 1.0)             # base AS < 1, so the bug is large
        self.assertGreater(a_cal, a0)             # Dagger really raised AS
        self.assertNotEqual(on.weighted_dps, off.weighted_dps)  # fold did fire
        self.assertLess(a0 + base_as * cond, 2.5)  # stays under the AS hard cap
        # weighted_dps = c0 + c1*AS; c1 from the pure-AS calibration build.
        c1 = (cal.weighted_dps - off.weighted_dps) / (a_cal - a0)
        predicted_correct = off.weighted_dps + c1 * (base_as * cond)
        predicted_wrong = off.weighted_dps + c1 * cond  # the regression
        # The fix must land on the base_as-scaled prediction...
        self.assertAlmostEqual(
            on.weighted_dps, predicted_correct,
            delta=abs(predicted_correct) * 0.005,
        )
        # ...and be unambiguously NOT the raw-fraction (buggy) magnitude.
        self.assertLess(
            abs(on.weighted_dps - predicted_correct),
            abs(on.weighted_dps - predicted_wrong),
        )


if __name__ == "__main__":
    unittest.main()
