"""R59 (2026-07-02) - target-side Lifeline shield seam.

Characterization tests for ``_lifeline_target_shield`` (the shared magnitude
helper) + the ``burst.compute_burst_damage`` / ``dps.compute_dps``
``assume_lifeline_shield`` seam.

Ground truth = the Phase-1.5 ``ItemShield`` magnitudes already extracted from
Meraki into ``_effects_data.ITEM_EFFECTS`` for the three ``unique_passive_key
="lifeline"`` items (verified vs data/daemon_slayer/16.13.1/items_meraki.json):

  * Immortal Shieldbow 6673 - ANY shield, flat 400 (<=L9) lerp-> 700 (>=L18),
    ranged x0.80. No wielder-stat dependency -> the canonical representative a
    modeled target is assumed to hold (exact magnitude, zero extra assumptions).
  * Sterak's Gage 3053 - ANY shield, 60% of the target's bonus HP.
  * Maw of Malmortius 3156 - MAGICAL shield, flat 200 + 150% bonus AD, ranged
    x0.75.

The seam is DEFAULT-OFF (byte-identical): assume_lifeline_shield=False leaves
total_burst / weighted_dps untouched. When True, burst subtracts the target's
one-shot Lifeline shield from the burst actually delivered (floored at 0), and
dps surfaces the magnitude WITHOUT corrupting the steady-state rate (a
one-trigger shield does not map to a per-second rate). Live default-ON flip is
operator-gated (docs/LIVE_GAME_GATED_SYNC.md).
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.burst import compute_burst_damage
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps
from agents.daemon_slayer._lifeline_target_shield import (
    ASSUME_LIFELINE_TARGET_ITEM_ID,
    LIFELINE_ITEM_IDS,
    target_lifeline_shield,
)

_ITEMS = ["3153", "3006"]  # Blade of the Ruined King + Berserker's - clean ADC.


class EngineVersion(unittest.TestCase):
    def test_engine_version_bumped(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.275.2")


class HelperGroundTruth(unittest.TestCase):
    """Meraki-exact magnitudes via the shared ItemShield.resolve_magnitude."""

    def test_default_item_is_shieldbow(self) -> None:
        self.assertEqual(ASSUME_LIFELINE_TARGET_ITEM_ID, "6673")

    def test_lifeline_family_ids(self) -> None:
        self.assertEqual(set(LIFELINE_ITEM_IDS), {"6673", "3053", "3156"})

    def test_shieldbow_flat_below_lerp(self) -> None:
        # <= L9 clamps to flat 400.
        self.assertAlmostEqual(target_lifeline_shield(level=9), 400.0)
        self.assertAlmostEqual(target_lifeline_shield(level=1), 400.0)

    def test_shieldbow_flat_at_lerp_high(self) -> None:
        # >= L18 clamps to level_lerp_high_value 700.
        self.assertAlmostEqual(target_lifeline_shield(level=18), 700.0)

    def test_shieldbow_lerp_midpoint(self) -> None:
        # L11: 400 + (700-400) * (11-9)/(18-9) = 400 + 300 * 2/9 = 466.666...
        self.assertAlmostEqual(target_lifeline_shield(level=11), 400.0 + 300.0 * 2 / 9)

    def test_shieldbow_ranged_modifier(self) -> None:
        self.assertAlmostEqual(
            target_lifeline_shield(level=18, target_is_ranged=True), 560.0
        )

    def test_sterak_bonus_hp_scaling(self) -> None:
        self.assertAlmostEqual(
            target_lifeline_shield(level=11, item_id="3053", target_bonus_hp=1000.0),
            600.0,
        )
        # No bonus HP -> no shield.
        self.assertAlmostEqual(
            target_lifeline_shield(level=11, item_id="3053", target_bonus_hp=0.0),
            0.0,
        )

    def test_maw_flat_plus_bonus_ad(self) -> None:
        self.assertAlmostEqual(
            target_lifeline_shield(level=11, item_id="3156", target_bonus_ad=0.0),
            200.0,
        )
        self.assertAlmostEqual(
            target_lifeline_shield(level=11, item_id="3156", target_bonus_ad=100.0),
            350.0,
        )

    def test_maw_ranged_modifier(self) -> None:
        # (200 + 1.5*100) * 0.75 = 262.5
        self.assertAlmostEqual(
            target_lifeline_shield(
                level=11, item_id="3156", target_bonus_ad=100.0, target_is_ranged=True
            ),
            262.5,
        )

    def test_unknown_item_zero(self) -> None:
        self.assertAlmostEqual(target_lifeline_shield(level=11, item_id="9999"), 0.0)


class ComputeBurstSeam(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_default_off_byte_identical(self) -> None:
        for cid in ("Caitlyn", "Syndra"):
            base = compute_burst_damage(
                self.snap, cid, level=16, item_ids=_ITEMS, target_armor=60, target_mr=40
            )
            off = compute_burst_damage(
                self.snap, cid, level=16, item_ids=_ITEMS, target_armor=60,
                target_mr=40, assume_lifeline_shield=False,
            )
            self.assertEqual(base.total_burst_damage, off.total_burst_damage, msg=cid)
            self.assertEqual(off.target_lifeline_shield_absorbed, 0.0, msg=cid)
            self.assertFalse(
                any("lifeline" in n.lower() for n in off.notes), msg=cid
            )

    def test_seam_on_subtracts_shield(self) -> None:
        off = compute_burst_damage(
            self.snap, "Syndra", level=16, item_ids=_ITEMS, target_armor=60, target_mr=40
        )
        on = compute_burst_damage(
            self.snap, "Syndra", level=16, item_ids=_ITEMS, target_armor=60,
            target_mr=40, assume_lifeline_shield=True,
        )
        expected = target_lifeline_shield(level=16)
        self.assertGreater(expected, 0.0)
        absorbed = min(expected, off.total_burst_damage)
        self.assertAlmostEqual(on.target_lifeline_shield_absorbed, absorbed)
        self.assertAlmostEqual(
            on.total_burst_damage, max(0.0, off.total_burst_damage - expected)
        )
        self.assertTrue(any("lifeline" in n.lower() for n in on.notes))

    def test_seam_never_negative(self) -> None:
        # Trivial burst (level 1, no items) < shield -> floored, not negative.
        on = compute_burst_damage(
            self.snap, "Syndra", level=1, item_ids=[], target_armor=0, target_mr=0,
            assume_lifeline_shield=True,
        )
        self.assertGreaterEqual(on.total_burst_damage, 0.0)


class ComputeDpsSeam(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_default_off_byte_identical(self) -> None:
        base = compute_dps(
            self.snap, "Caitlyn", level=16, item_ids=_ITEMS, target_armor=60, target_mr=40
        )
        off = compute_dps(
            self.snap, "Caitlyn", level=16, item_ids=_ITEMS, target_armor=60,
            target_mr=40, assume_lifeline_shield=False,
        )
        self.assertEqual(base.weighted_dps, off.weighted_dps)
        self.assertEqual(base.phase_dps, off.phase_dps)
        self.assertEqual(off.target_lifeline_shield, 0.0)

    def test_seam_on_surfaces_shield_rate_unchanged(self) -> None:
        off = compute_dps(
            self.snap, "Caitlyn", level=16, item_ids=_ITEMS, target_armor=60, target_mr=40
        )
        on = compute_dps(
            self.snap, "Caitlyn", level=16, item_ids=_ITEMS, target_armor=60,
            target_mr=40, assume_lifeline_shield=True,
        )
        # Rate is intentionally NOT corrupted by a one-shot shield.
        self.assertEqual(on.weighted_dps, off.weighted_dps)
        self.assertEqual(on.phase_dps, off.phase_dps)
        # ... but the magnitude is surfaced for burst-window consumers.
        self.assertAlmostEqual(on.target_lifeline_shield, target_lifeline_shield(level=16))
        self.assertTrue(any("lifeline" in n.lower() for n in on.notes))


if __name__ == "__main__":
    unittest.main()
