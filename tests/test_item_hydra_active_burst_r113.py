"""R113 RC-suite regression guard - Tiamat-tree TOTAL-AD physical burst seam.

Companion to ``agents/daemon_slayer/tests/test_item_hydra_active_burst_r113.py``
(the DS-dir suite). This is the RC top-level ``tests/`` guard so the CI
``pytest tests/`` run also covers the R113 total-AD physical burst seam -
``effects.total_physical_burst_damage`` + the ``burst.compute_burst_damage``
wiring - not only the DS-dir suite. The R113 feat commit (ef6cea88) shipped the
seam and the DS-dir test but no RC-suite guard, so a diff-window audit of the
finalize commit saw the effects.py / burst.py total-AD logic with no test
beside it in the RC suite. This closes that gap.

Seam recap (Meraki 16.13.1): the four Tiamat-tree actives deal plain
"X% AD physical" = TOTAL AD via the END-appended field
``ItemEffect.physical_burst_total_ad_ratio``:

- Tiamat 3077 "Crescent": 75% AD -> 0.75 (SR only, no Arena mirror).
- Ravenous 3074 / Profane 6698 / Stridebreaker 6631: 80% AD -> 0.80
  (+ Arena mirrors 223074 / 226698 / 226631).

The burst consumer folds ``physical_burst_total_ad_ratio *
(ctx.base_ad + ctx.bonus_ad)`` into the physical burst window - armor-mitigated
(PHYSICAL routing) x mode_mult, NO amp layer - under the SAME default-OFF
``assume_physical_burst`` flag. Goredrinker 226630 stays on the BASE-AD path
(``physical_burst_base_ad_ratio=1.75``, total-AD field 0.0). Titanic 3748 is
EXCLUDED (its active is a %max-HP empowered basic attack, a different mechanic).

This is a characterization / regression guard for already-shipped R113
behavior: each assertion fails if the total-AD seam is reverted (field zeroed,
or the consumer drops the ``ctx.base_ad + ctx.bonus_ad`` third arg back to a
2-arg base-AD-only call).
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer.ability_dps import _mitigation_factor
from agents.daemon_slayer.burst import compute_burst_damage
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.effects import (
    ITEM_EFFECTS,
    collect_effects,
    total_physical_burst_damage,
)
from agents.daemon_slayer.engine import build_champion

# The four base Tiamat-tree carriers + the three Arena mirrors that exist.
_TIAMAT = "3077"          # 75% AD, SR only (no Arena mirror)
_RAVENOUS_SR = "3074"
_PROFANE_SR = "6698"
_STRIDE_SR = "6631"
_HYDRA_080_IDS = (
    "3074", "223074",     # Ravenous Hydra + Arena mirror
    "6698", "226698",     # Profane Hydra + Arena mirror
    "6631", "226631",     # Stridebreaker + Arena mirror
)

# Base-AD path (unchanged by R113) + the excluded max-HP mechanic.
_GOREDRINKER = "226630"   # 175% BASE AD -> physical_burst_base_ad_ratio 1.75
_TITANIC_SR = "3748"      # %max-HP active, must stay off the AD field

_MELEE = "Darius"
_HYDRA_BUILD = ["3047", _RAVENOUS_SR]  # Plated Steelcaps + Ravenous Hydra


class RegistryPins(unittest.TestCase):
    """The four Tiamat-tree carriers ride the TOTAL-AD field; Goredrinker
    rides BASE-AD; Titanic is excluded (directive step 4)."""

    def test_tiamat_is_075(self) -> None:
        self.assertAlmostEqual(
            ITEM_EFFECTS[_TIAMAT].physical_burst_total_ad_ratio, 0.75
        )

    def test_hydra_tree_is_080(self) -> None:
        for iid in _HYDRA_080_IDS:
            self.assertAlmostEqual(
                ITEM_EFFECTS[iid].physical_burst_total_ad_ratio,
                0.80,
                msg=iid,
            )

    def test_carriers_carry_no_base_ad_term(self) -> None:
        # The Hydra tree rides the TOTAL-AD field ONLY, never the base-AD pair.
        for iid in (_TIAMAT, *_HYDRA_080_IDS):
            self.assertEqual(
                ITEM_EFFECTS[iid].physical_burst_base_ad_ratio, 0.0, msg=iid
            )
            self.assertEqual(
                ITEM_EFFECTS[iid].physical_burst_base, 0.0, msg=iid
            )

    def test_goredrinker_stays_base_ad(self) -> None:
        eff = ITEM_EFFECTS[_GOREDRINKER]
        self.assertAlmostEqual(eff.physical_burst_base_ad_ratio, 1.75)
        self.assertEqual(eff.physical_burst_total_ad_ratio, 0.0)

    def test_titanic_excluded_from_total_ad_field(self) -> None:
        self.assertEqual(
            ITEM_EFFECTS[_TITANIC_SR].physical_burst_total_ad_ratio, 0.0
        )


class HelperMath(unittest.TestCase):
    """``effects.total_physical_burst_damage`` total-AD path (directive step
    2). 2-arg callers stay inert; the 3-arg total-AD term is credited."""

    def test_profane_three_arg_total_ad(self) -> None:
        # 0 + 0.0 * base_ad + 0.80 * 250 = 200.0.
        effs = collect_effects([_PROFANE_SR])
        self.assertAlmostEqual(
            total_physical_burst_damage(effs, 110.0, 250.0), 200.0
        )

    def test_two_arg_call_is_inert(self) -> None:
        # The 2-arg call (compute_ability_dps inert path) folds the new term
        # against caster_total_ad=0.0, so the Hydra active contributes 0.0.
        effs = collect_effects([_PROFANE_SR])
        self.assertEqual(total_physical_burst_damage(effs, 110.0), 0.0)

    def test_goredrinker_base_ad_unchanged_by_total_arg(self) -> None:
        # Goredrinker rides base-AD: 1.75 * 110 = 192.5, identical 2-arg vs
        # 3-arg (the new total-AD arg does not touch the base-AD path).
        effs = collect_effects([_GOREDRINKER])
        self.assertAlmostEqual(
            total_physical_burst_damage(effs, 110.0, 250.0), 192.5
        )
        self.assertAlmostEqual(
            total_physical_burst_damage(effs, 110.0), 192.5
        )

    def test_non_carrier_returns_zero(self) -> None:
        effs = collect_effects(["3047"])  # boots, no burst field
        self.assertEqual(
            total_physical_burst_damage(effs, 999.0, 999.0), 0.0
        )


class ComputeBurstWiring(unittest.TestCase):
    """``burst.compute_burst_damage`` folds ``ratio * (ctx.base_ad +
    ctx.bonus_ad)`` under ``assume_physical_burst`` (directive step 3)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def _delta(self, *, mode: str = "SR", armor: float = 0.0) -> float:
        common = dict(
            item_ids=_HYDRA_BUILD,
            mode=mode,
            target_armor=armor,
            target_max_hp=2000,
        )
        off = compute_burst_damage(
            self.snap, _MELEE, 11, assume_physical_burst=False, **common
        )
        on = compute_burst_damage(
            self.snap, _MELEE, 11, assume_physical_burst=True, **common
        )
        return on.total_burst_damage - off.total_burst_damage

    def test_default_off_is_byte_identical(self) -> None:
        common = dict(
            item_ids=_HYDRA_BUILD,
            mode="SR",
            target_armor=60,
            target_max_hp=2000,
        )
        base = compute_burst_damage(self.snap, _MELEE, 11, **common)
        off = compute_burst_damage(
            self.snap, _MELEE, 11, assume_physical_burst=False, **common
        )
        self.assertEqual(base.total_burst_damage, off.total_burst_damage)

    def test_on_credits_080_of_total_ad(self) -> None:
        # At armor 0 (PHYSICAL factor 1.0) and SR (mode_mult 1.0), no amp and
        # no armor pen on the build, the delta is exactly 0.80 * TOTAL AD -
        # this is what proves the consumer passes ctx.base_ad + ctx.bonus_ad
        # (TOTAL AD) and NOT base AD alone.
        resolved = build_champion(
            self.snap, _MELEE, 11, item_ids=_HYDRA_BUILD, mode="SR"
        )
        total_ad = float(resolved.stats["ad"])
        base_ad = float(resolved.base_stats["ad"])
        self.assertGreater(total_ad, base_ad)  # Ravenous adds bonus AD
        self.assertAlmostEqual(self._delta(), 0.80 * total_ad, places=2)

    def test_physical_burst_is_armor_sensitive(self) -> None:
        # PHYSICAL burst MUST route through armor: raising armor shrinks the
        # delta by the engine's own PHYSICAL mitigation ratio.
        d0 = self._delta(armor=0.0)
        d100 = self._delta(armor=100.0)
        self.assertGreater(d0, 0.0)
        self.assertLess(d100, d0)
        expected_ratio = (
            _mitigation_factor("PHYSICAL", 100.0, 0.0)
            / _mitigation_factor("PHYSICAL", 0.0, 0.0)
        )
        self.assertAlmostEqual(d100, d0 * expected_ratio, places=2)


if __name__ == "__main__":
    unittest.main()
