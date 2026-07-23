"""G2-12 (2026-07-20) - ranged-exposure amortization on the R49/R68 reflect seam.

The R49 champion reflect (Rammus W Defensive Ball Curl) and the R68 item Thorns
lane (Thornmail 3075 + mirrors 223075/323075, Bramble Vest 3076) share one
``assume_passive_reflect`` seam whose per-second credit is
``per_proc / reflect_cadence_s`` at a 1.0s cadence - i.e. "the carrier is being
auto-attacked once every second for the whole fight".

That is the MELEE-tank case the mechanic targets. A LIVE measurement (Caitlyn
L14, real build ['2501','3032','3031','3075','6695'] vs armor 60 / MR 40 /
2200 HP) showed the seam crediting +8.96% of a 650-range ADC's TOTAL damage
output, which the operator ruled too high. The fix is an exposure factor:
melee 1.0 (byte-identical), ranged ``_REFLECT_RANGED_EXPOSURE``.

These tests pin:
  (a) the constant's shape + the helper's melee/ranged branch,
  (b) DEFAULT-OFF byte-identity is preserved (the seam is still opt-in),
  (c) a RANGED carrier's credit is scaled by exactly the exposure factor,
  (d) a MELEE carrier's credit is UNCHANGED (factor 1.0),
  (e) the burst consumer mirrors the DPS consumer,
  (f) the emitted note names the exposure arm.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer._passive_reflect_overrides import (
    _REFLECT_RANGED_EXPOSURE,
    reflect_exposure_factor,
)
from agents.daemon_slayer.burst import compute_burst_damage
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps

# The operator's real live Practice-Tool build (Overlord's Bloodmail,
# Berserker's Greaves, Kraken Slayer, Thornmail, Serpent's Fang).
_LIVE_BUILD = ["2501", "3032", "3031", "3075", "6695"]
_NO_THORN_BUILD = ["3032", "3031", "6695"]
_LEVEL = 14
_TARGET = dict(target_armor=60.0, target_mr=40.0, target_max_hp=2200.0)


class ExposureConstant(unittest.TestCase):
    """(a) constant shape + helper branch."""

    def test_ranged_exposure_is_a_fraction_below_one(self) -> None:
        self.assertGreater(_REFLECT_RANGED_EXPOSURE, 0.0)
        self.assertLess(_REFLECT_RANGED_EXPOSURE, 1.0)

    def test_melee_is_unscaled(self) -> None:
        self.assertEqual(reflect_exposure_factor(True), 1.0)

    def test_ranged_uses_the_constant(self) -> None:
        self.assertEqual(
            reflect_exposure_factor(False), _REFLECT_RANGED_EXPOSURE
        )


class DpsSeam(unittest.TestCase):
    """(b)(c)(d)(f) DPS consumer."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_default_off_still_byte_identical(self) -> None:
        base = compute_dps(self.snap, "Caitlyn", level=_LEVEL,
                           item_ids=_LIVE_BUILD, **_TARGET)
        off = compute_dps(self.snap, "Caitlyn", level=_LEVEL,
                          item_ids=_LIVE_BUILD,
                          assume_passive_reflect=False, **_TARGET)
        self.assertEqual(base.weighted_dps, off.weighted_dps)
        self.assertEqual(base.phase_dps, off.phase_dps)

    def test_ranged_carrier_credit_is_scaled_by_the_exposure_factor(
        self,
    ) -> None:
        """The measured live case: the credit must be the unscaled reflect
        stream times _REFLECT_RANGED_EXPOSURE, not the unscaled stream."""
        off = compute_dps(self.snap, "Caitlyn", level=_LEVEL,
                          item_ids=_LIVE_BUILD, **_TARGET)
        on = compute_dps(self.snap, "Caitlyn", level=_LEVEL,
                         item_ids=_LIVE_BUILD,
                         assume_passive_reflect=True, **_TARGET)
        credit = on.weighted_dps - off.weighted_dps
        self.assertGreater(credit, 0.0)
        # Unscaled reference: per-proc 20 + 10% of Thornmail's 75 bonus armor
        # = 27.5 magic, mitigated by the target's 40 MR (100/140), at the 1.0s
        # cadence. RED before the fix (credit was the full 19.64).
        unscaled = 27.5 * (100.0 / 140.0) / 1.0
        self.assertAlmostEqual(
            credit, unscaled * _REFLECT_RANGED_EXPOSURE, places=6
        )

    def test_ranged_credit_is_a_small_share_of_total_output(self) -> None:
        """Operator ruling: a ranged ADC's Thornmail must not read as ~a tenth
        of her damage. Pin the share strictly below 5%."""
        off = compute_dps(self.snap, "Caitlyn", level=_LEVEL,
                          item_ids=_LIVE_BUILD, **_TARGET)
        on = compute_dps(self.snap, "Caitlyn", level=_LEVEL,
                         item_ids=_LIVE_BUILD,
                         assume_passive_reflect=True, **_TARGET)
        share = (on.weighted_dps - off.weighted_dps) / off.weighted_dps
        self.assertLess(share, 0.05)

    def test_melee_carrier_credit_is_unchanged(self) -> None:
        """A melee thorn carrier keeps the full 1.0s-cadence credit - the fix
        scales the RANGED arm only."""
        off = compute_dps(self.snap, "Malphite", level=_LEVEL,
                          item_ids=_LIVE_BUILD, **_TARGET)
        on = compute_dps(self.snap, "Malphite", level=_LEVEL,
                         item_ids=_LIVE_BUILD,
                         assume_passive_reflect=True, **_TARGET)
        credit = on.weighted_dps - off.weighted_dps
        unscaled = 27.5 * (100.0 / 140.0) / 1.0
        self.assertAlmostEqual(credit, unscaled, places=6)

    def test_champion_stream_melee_rammus_unchanged(self) -> None:
        """Rammus is melee, so the R49 champion stream is byte-identical to
        the pre-G2-12 behavior (guards against a blanket cadence nerf)."""
        off = compute_dps(self.snap, "Rammus", level=_LEVEL,
                          item_ids=_NO_THORN_BUILD, **_TARGET)
        on = compute_dps(self.snap, "Rammus", level=_LEVEL,
                         item_ids=_NO_THORN_BUILD,
                         assume_passive_reflect=True, **_TARGET)
        armor = on.stats.get("armor", 0.0)
        mr = on.stats.get("mr", 0.0)
        unscaled = (15.0 + 0.10 * armor + 0.10 * mr) * (100.0 / 140.0) / 1.0
        self.assertAlmostEqual(
            on.weighted_dps - off.weighted_dps, unscaled, places=6
        )

    def test_note_names_the_exposure_arm(self) -> None:
        on = compute_dps(self.snap, "Caitlyn", level=_LEVEL,
                         item_ids=_LIVE_BUILD,
                         assume_passive_reflect=True, **_TARGET)
        thorn_notes = [
            n for n in on.notes
            if "assume_passive_reflect" in n and "Thorn" in n
        ]
        self.assertEqual(len(thorn_notes), 1)
        self.assertIn("ranged exposure", thorn_notes[0])

    def test_no_thorn_build_still_byte_identical_with_flag_on(self) -> None:
        off = compute_dps(self.snap, "Caitlyn", level=_LEVEL,
                          item_ids=_NO_THORN_BUILD, **_TARGET)
        on = compute_dps(self.snap, "Caitlyn", level=_LEVEL,
                         item_ids=_NO_THORN_BUILD,
                         assume_passive_reflect=True, **_TARGET)
        self.assertEqual(off.weighted_dps, on.weighted_dps)


class BurstSeam(unittest.TestCase):
    """(e) burst consumer mirrors the DPS consumer."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_ranged_burst_credit_is_scaled(self) -> None:
        off = compute_burst_damage(self.snap, "Caitlyn", level=_LEVEL,
                                   item_ids=_LIVE_BUILD, **_TARGET)
        on = compute_burst_damage(self.snap, "Caitlyn", level=_LEVEL,
                                  item_ids=_LIVE_BUILD,
                                  assume_passive_reflect=True, **_TARGET)
        credit = on.total_burst_damage - off.total_burst_damage
        self.assertGreater(credit, 0.0)
        # 3.0s window / 1.0s cadence = 3 procs, MR-mitigated.
        unscaled = 27.5 * (100.0 / 140.0) * 3.0
        self.assertAlmostEqual(
            credit, unscaled * _REFLECT_RANGED_EXPOSURE, places=6
        )

    def test_melee_burst_credit_is_unchanged(self) -> None:
        off = compute_burst_damage(self.snap, "Malphite", level=_LEVEL,
                                   item_ids=_LIVE_BUILD, **_TARGET)
        on = compute_burst_damage(self.snap, "Malphite", level=_LEVEL,
                                  item_ids=_LIVE_BUILD,
                                  assume_passive_reflect=True, **_TARGET)
        credit = on.total_burst_damage - off.total_burst_damage
        unscaled = 27.5 * (100.0 / 140.0) * 3.0
        self.assertAlmostEqual(credit, unscaled, places=6)

    def test_burst_default_off_byte_identical(self) -> None:
        base = compute_burst_damage(self.snap, "Caitlyn", level=_LEVEL,
                                    item_ids=_LIVE_BUILD, **_TARGET)
        off = compute_burst_damage(self.snap, "Caitlyn", level=_LEVEL,
                                   item_ids=_LIVE_BUILD,
                                   assume_passive_reflect=False, **_TARGET)
        self.assertEqual(base.total_burst_damage, off.total_burst_damage)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
