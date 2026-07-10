"""DSV6 (R30): on-cast magic-burst valuation seam.

Root cause: the per-cast burst combo loop in ``compute_burst_damage`` sums only
ability casts + AA hits, so an item's on-cast magic proc (Luden's Echo,
Stormsurge Squall, Malignance Hatefog) was never credited inside a burst window.
An AP/magic build that bought these items saw zero burst value from the proc -
only its raw stats - so the offense-burst scorer under-ranked them.

DSV6 adds two END-appended ItemEffect fields (``magic_burst_base`` /
``magic_burst_ap_ratio``, the one-shot burst-window magnitude), the
``effects.total_magic_burst_damage`` helper, and an ``assume_magic_burst`` kwarg
(default False = byte-identical) on both ability scorers. ``compute_burst_damage``
folds ``sum(base + ap_ratio * ap)`` MR-mitigated (MAGIC routing) x mode_mult x
magic_amp into ``total_burst``. ``compute_ability_dps`` takes the kwarg for caller
API symmetry but is DELIBERATELY INERT (byte-identical ON or OFF): a one-shot
magnitude has no dimensionally-sound place in a per-second metric, and
``compute_dps`` already values these procs at their PeriodicProc rate, so folding
them into the ability-DPS scorer would be wrong-units and a partial double-count.

Meraki 16.13.1 magnitudes (also the PeriodicProc bonus_damage on each item):
  Luden's Echo  (6655): 75  + 5%  AP
  Stormsurge    (4646): 125 + 10% AP
  Malignance    (3118): 180 + 15% AP  (one ult-zone hit; no ult-rate factor)
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer._effects_types import ItemEffect
from agents.daemon_slayer.ability_dps import _mitigation_factor, compute_ability_dps
from agents.daemon_slayer.burst import compute_burst_damage
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.effects import (
    ITEM_EFFECTS,
    collect_effects,
    total_magic_burst_damage,
)

_LUDENS = "6655"
_STORMSURGE = "4646"
_MALIGNANCE = "3118"
_INFINITY_EDGE = "3031"  # AD crit item, carries no magic_burst field


class MagicBurstSchemaDefaults(unittest.TestCase):
    """The two new ItemEffect fields default to the inert (seam-OFF) values."""

    def test_defaults_zero(self) -> None:
        eff = ItemEffect(item_id="x", name="x")
        self.assertEqual(eff.magic_burst_base, 0.0)
        self.assertEqual(eff.magic_burst_ap_ratio, 0.0)


class MagicBurstData(unittest.TestCase):
    """Item ids pin the on-cast magic-burst magnitudes to Meraki 16.13.1."""

    def test_pins(self) -> None:
        for iid, base, ratio in (
            (_LUDENS, 75.0, 0.05),
            (_STORMSURGE, 125.0, 0.10),
            (_MALIGNANCE, 180.0, 0.15),
        ):
            eff = ITEM_EFFECTS[iid]
            self.assertAlmostEqual(eff.magic_burst_base, base, msg=iid)
            self.assertAlmostEqual(eff.magic_burst_ap_ratio, ratio, msg=iid)

    def test_burst_magnitude_matches_periodic_bonus(self) -> None:
        # The burst-window magnitude must equal the item's own PeriodicProc
        # bonus at AP=0 (both are the single-proc Meraki base) so the two
        # representations of the same proc never drift.
        for iid in (_LUDENS, _STORMSURGE):
            eff = ITEM_EFFECTS[iid]

            class _Ctx:
                ap = 0.0

            proc_at_zero = eff.periodics[0].bonus_damage(_Ctx())
            self.assertAlmostEqual(eff.magic_burst_base, proc_at_zero, msg=iid)


class MagicBurstHelper(unittest.TestCase):
    """``total_magic_burst_damage`` sums base + ap_ratio*ap across the build."""

    def test_single_item(self) -> None:
        effs = collect_effects([_LUDENS])
        # 75 + 0.05 * 200 = 85.
        self.assertAlmostEqual(total_magic_burst_damage(effs, 200.0), 85.0)

    def test_additive_across_items(self) -> None:
        effs = collect_effects([_LUDENS, _STORMSURGE])
        # (75 + 10) + (125 + 20) = 230 at AP=200.
        self.assertAlmostEqual(total_magic_burst_damage(effs, 200.0), 230.0)

    def test_malignance_one_zone(self) -> None:
        effs = collect_effects([_MALIGNANCE])
        # 180 + 0.15 * 100 = 195 (one ult-zone hit, no ult-rate factor).
        self.assertAlmostEqual(total_magic_burst_damage(effs, 100.0), 195.0)

    def test_zero_for_no_field(self) -> None:
        self.assertEqual(total_magic_burst_damage(collect_effects([]), 200.0), 0.0)
        self.assertEqual(
            total_magic_burst_damage(collect_effects([_INFINITY_EDGE]), 200.0), 0.0
        )


class ComputeBurstSeam(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_default_off_byte_identical(self) -> None:
        base = compute_burst_damage(
            self.snap, "Veigar", 11, item_ids=[_LUDENS], target_mr=60, target_max_hp=2000
        )
        off = compute_burst_damage(
            self.snap, "Veigar", 11, item_ids=[_LUDENS], target_mr=60, target_max_hp=2000,
            assume_magic_burst=False,
        )
        self.assertEqual(base.total_burst_damage, off.total_burst_damage)

    def test_seam_on_raises_burst(self) -> None:
        off = compute_burst_damage(
            self.snap, "Veigar", 11, item_ids=[_LUDENS], target_mr=0, target_max_hp=2000
        )
        on = compute_burst_damage(
            self.snap, "Veigar", 11, item_ids=[_LUDENS], target_mr=0, target_max_hp=2000,
            assume_magic_burst=True,
        )
        self.assertGreater(on.total_burst_damage, off.total_burst_damage)
        # At target_mr=0 (MAGIC factor 1.0), SR (mode_mult 1.0), no Abyssal
        # (magic_amp 1.0), the delta is at least Luden's 75 base floor.
        self.assertGreaterEqual(
            on.total_burst_damage - off.total_burst_damage, 75.0
        )

    def test_mr_routing_scales_delta(self) -> None:
        # The magic-burst delta must route through MR (not armor): mitigating
        # only MR shrinks it by exactly the engine's own MAGIC mitigation ratio.
        # Luden's is used (not Stormsurge) because it carries NO magic pen, so
        # target_mr_eff == raw target_mr and the expected ratio is clean.
        def delta(mr: float) -> float:
            off = compute_burst_damage(
                self.snap, "Veigar", 11, item_ids=[_LUDENS],
                target_mr=mr, target_max_hp=2000,
            )
            on = compute_burst_damage(
                self.snap, "Veigar", 11, item_ids=[_LUDENS],
                target_mr=mr, target_max_hp=2000, assume_magic_burst=True,
            )
            return on.total_burst_damage - off.total_burst_damage

        d0 = delta(0.0)
        d100 = delta(100.0)
        self.assertGreater(d0, 0.0)
        self.assertLess(d100, d0)
        # Expected ratio is the engine's own factor curve (not a hardcoded 0.5).
        expected_ratio = (
            _mitigation_factor("MAGIC", 0.0, 100.0)
            / _mitigation_factor("MAGIC", 0.0, 0.0)
        )
        self.assertAlmostEqual(d100, d0 * expected_ratio, places=2)

    def test_no_magic_burst_item_byte_identical_on(self) -> None:
        off = compute_burst_damage(
            self.snap, "Veigar", 11, item_ids=[_INFINITY_EDGE],
            target_mr=60, target_max_hp=2000,
        )
        on = compute_burst_damage(
            self.snap, "Veigar", 11, item_ids=[_INFINITY_EDGE],
            target_mr=60, target_max_hp=2000, assume_magic_burst=True,
        )
        self.assertAlmostEqual(
            on.total_burst_damage, off.total_burst_damage, places=4
        )


class ComputeAbilityDpsInertSeam(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_inert_byte_identical_even_with_magic_burst_item(self) -> None:
        # Luden's carries a magic_burst field, but the ability-DPS scorer is a
        # documented-inert seam: ON == OFF == base (no double-count, right-units).
        base = compute_ability_dps(
            self.snap, "Veigar", 11, item_ids=[_LUDENS], target_mr=60
        )
        off = compute_ability_dps(
            self.snap, "Veigar", 11, item_ids=[_LUDENS], target_mr=60,
            assume_magic_burst=False,
        )
        on = compute_ability_dps(
            self.snap, "Veigar", 11, item_ids=[_LUDENS], target_mr=60,
            assume_magic_burst=True,
        )
        self.assertEqual(base.total_ability_dps, off.total_ability_dps)
        self.assertEqual(off.total_ability_dps, on.total_ability_dps)


class EngineVersionPin(unittest.TestCase):
    def test_engine_version(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.185.0")


if __name__ == "__main__":
    unittest.main()
