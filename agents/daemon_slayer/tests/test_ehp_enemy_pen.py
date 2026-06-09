"""T1-F3 (BACKLOG MED, docs/COMPETITOR_LIFT_2026-06-08.md lines 59-66) -
opt-in enemy-penetration effective-resist seam on the EHP scorer.

Covers the new ``_effective_resist_after_pen`` helper (pure math, no
snapshot) plus the five opt-in ``compute_ehp`` kwargs
(``enemy_lethality`` / ``enemy_armor_pen_pct`` / ``enemy_shred_pct`` /
``enemy_magic_pen_flat`` / ``enemy_magic_pen_pct``).

The DEFAULT (no pen kwargs) MUST stay byte-identical to the pre-seam
EHP math - the seam ships inert and is flipped live later. The
byte-identical guard lives in the existing ``test_ehp.py`` wide blast
radius too; this module adds the explicit no-kwargs == explicit-zero
assertion plus the ordered-pipeline coverage.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import (
    _armor_factor,
    _effective_resist_after_pen,
    compute_ehp,
)


class EffectiveResistAfterPenUnitTests(unittest.TestCase):
    """Pure-math unit tests for the helper - no snapshot needed.

    ARMOR order (spec): flat reduction -> % shred (clamp 0..0.99) ->
    general %pen (multiplicative) -> lethality (flat, subtract LAST).
    Shred is a REDUCTION (can drive the resist below zero, amplifying
    damage via ``_armor_factor``'s negative branch); %pen + flat pen
    CANNOT push the resist below zero (League's two-rule split, mirrored
    from ``effects.effective_target_armor``).
    """

    def test_no_pen_is_identity(self) -> None:
        # All-zero pen inputs leave the resist exactly unchanged.
        self.assertEqual(
            _effective_resist_after_pen(100.0, shred_pct=0.0, pen_pct=0.0, flat_pen=0.0),
            100.0,
        )

    def test_negative_resist_passthrough(self) -> None:
        # Already-negative resist: pen / shred is a no-op (mirrors the
        # effects.py two-rule contract).
        self.assertEqual(
            _effective_resist_after_pen(-30.0, shred_pct=0.5, pen_pct=0.5, flat_pen=20.0),
            -30.0,
        )

    def test_lethality_only_subtracts_flat(self) -> None:
        # 100 armor, 18 lethality (flat pen) -> 82 effective armor.
        self.assertAlmostEqual(
            _effective_resist_after_pen(100.0, shred_pct=0.0, pen_pct=0.0, flat_pen=18.0),
            82.0,
        )

    def test_pct_pen_only_multiplicative(self) -> None:
        # 100 armor, 35% pen -> 65 effective armor.
        self.assertAlmostEqual(
            _effective_resist_after_pen(100.0, shred_pct=0.0, pen_pct=0.35, flat_pen=0.0),
            65.0,
        )

    def test_shred_then_pen_then_flat_order(self) -> None:
        # 100 armor: 30% shred -> 70; 35% pen -> 45.5; 10 lethality -> 35.5.
        self.assertAlmostEqual(
            _effective_resist_after_pen(100.0, shred_pct=0.30, pen_pct=0.35, flat_pen=10.0),
            35.5,
        )

    def test_shred_can_drive_negative(self) -> None:
        # Shred is a REDUCTION: 20 armor, 99% shred -> 0.2; but a flat
        # reduction is not in the kwarg set, so to reach negative we rely
        # on shred alone never crossing zero (clamped at 0.99). Confirm
        # shred floors the keep-factor at 0.01 (never fully zero).
        out = _effective_resist_after_pen(20.0, shred_pct=2.0, pen_pct=0.0, flat_pen=0.0)
        # 2.0 clamps to 0.99 -> 20 * 0.01 = 0.2 (still positive, not negative).
        self.assertAlmostEqual(out, 0.2)

    def test_pen_cannot_go_below_zero(self) -> None:
        # 30 armor, 50 lethality -> flat pen cannot push below 0.
        self.assertEqual(
            _effective_resist_after_pen(30.0, shred_pct=0.0, pen_pct=0.0, flat_pen=50.0),
            0.0,
        )

    def test_pct_pen_noop_once_shred_crosses_zero(self) -> None:
        # If shred alone reaches <= 0, the % pen + flat pen tail is a
        # no-op (mirrors effects.effective_target_armor early-return).
        # Shred clamps at 0.99 so a single shred never crosses zero;
        # verify the floor behavior holds at the clamp boundary.
        out = _effective_resist_after_pen(1.0, shred_pct=0.99, pen_pct=0.5, flat_pen=5.0)
        # 1.0 * 0.01 = 0.01 -> %pen 0.5 -> 0.005 -> flat 5 -> floored 0.0.
        self.assertEqual(out, 0.0)


class ComputeEhpEnemyPenIntegrationTests(unittest.TestCase):
    """End-to-end: the five opt-in kwargs on compute_ehp."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_no_kwargs_byte_identical_to_explicit_zero(self) -> None:
        # The seam MUST default to the current no-pen behavior.
        base = compute_ehp(self.snap, "Aatrox", level=11)
        zero = compute_ehp(
            self.snap, "Aatrox", level=11,
            enemy_lethality=0.0,
            enemy_armor_pen_pct=0.0,
            enemy_shred_pct=0.0,
            enemy_magic_pen_flat=0.0,
            enemy_magic_pen_pct=0.0,
        )
        self.assertEqual(base.physical_ehp, zero.physical_ehp)
        self.assertEqual(base.magical_ehp, zero.magical_ehp)
        self.assertEqual(base.true_ehp, zero.true_ehp)
        self.assertEqual(base.blended_ehp, zero.blended_ehp)
        # Reported armor/MR are the RESOLVED build stats either way.
        self.assertEqual(base.armor, zero.armor)
        self.assertEqual(base.mr, zero.mr)

    def test_lethality_only_lowers_physical_ehp(self) -> None:
        base = compute_ehp(self.snap, "Aatrox", level=11, enemy_ad_share=1.0, enemy_ap_share=0.0)
        penned = compute_ehp(
            self.snap, "Aatrox", level=11, enemy_ad_share=1.0, enemy_ap_share=0.0,
            enemy_lethality=20.0,
        )
        # Less effective armor -> takes more damage -> lower physical EHP.
        self.assertLess(penned.physical_ehp, base.physical_ehp)
        # Magic side untouched by armor lethality.
        self.assertAlmostEqual(penned.magical_ehp, base.magical_ehp, places=6)

    def test_physical_ehp_matches_post_pen_closed_form(self) -> None:
        # Closed form: physical_ehp = hp / armor_factor(eff_armor) in SR
        # (mode_mult 1.0, no shields/heals/DR on a naked build).
        penned = compute_ehp(
            self.snap, "Aatrox", level=11,
            enemy_lethality=10.0, enemy_armor_pen_pct=0.35, enemy_shred_pct=0.30,
        )
        eff_armor = _effective_resist_after_pen(
            penned.armor, shred_pct=0.30, pen_pct=0.35, flat_pen=10.0
        )
        expected = penned.hp / _armor_factor(eff_armor)
        self.assertAlmostEqual(penned.physical_ehp, expected, places=4)

    def test_magic_pen_flat_lowers_magical_ehp(self) -> None:
        base = compute_ehp(self.snap, "Aatrox", level=11, enemy_ad_share=0.0, enemy_ap_share=1.0)
        penned = compute_ehp(
            self.snap, "Aatrox", level=11, enemy_ad_share=0.0, enemy_ap_share=1.0,
            enemy_magic_pen_flat=15.0,
        )
        self.assertLess(penned.magical_ehp, base.magical_ehp)
        # Physical side untouched by magic pen.
        self.assertAlmostEqual(penned.physical_ehp, base.physical_ehp, places=6)

    def test_magical_ehp_matches_post_pen_closed_form(self) -> None:
        penned = compute_ehp(
            self.snap, "Aatrox", level=11,
            enemy_magic_pen_flat=15.0, enemy_magic_pen_pct=0.40,
        )
        eff_mr = _effective_resist_after_pen(
            penned.mr, shred_pct=0.0, pen_pct=0.40, flat_pen=15.0
        )
        expected = penned.hp / _armor_factor(eff_mr)
        self.assertAlmostEqual(penned.magical_ehp, expected, places=4)

    def test_combined_order_armor_pipeline(self) -> None:
        # Verify the ARMOR pipeline applies shred -> %pen -> lethality in
        # order via the public kwargs end-to-end.
        penned = compute_ehp(
            self.snap, "Aatrox", level=11, enemy_ad_share=1.0, enemy_ap_share=0.0,
            enemy_shred_pct=0.30, enemy_armor_pen_pct=0.35, enemy_lethality=10.0,
        )
        eff_armor = _effective_resist_after_pen(
            penned.armor, shred_pct=0.30, pen_pct=0.35, flat_pen=10.0
        )
        expected_phys = penned.hp / _armor_factor(eff_armor)
        self.assertAlmostEqual(penned.physical_ehp, expected_phys, places=4)
        # blended == physical for pure-AD enemy.
        self.assertAlmostEqual(penned.blended_ehp, penned.physical_ehp, places=4)

    def test_true_ehp_unaffected_by_pen(self) -> None:
        # True damage ignores resists -> pen kwargs never touch true_ehp.
        base = compute_ehp(self.snap, "Aatrox", level=11)
        penned = compute_ehp(
            self.snap, "Aatrox", level=11,
            enemy_lethality=30.0, enemy_armor_pen_pct=0.5, enemy_shred_pct=0.5,
            enemy_magic_pen_flat=30.0, enemy_magic_pen_pct=0.5,
        )
        self.assertAlmostEqual(penned.true_ehp, base.true_ehp, places=6)


if __name__ == "__main__":
    unittest.main()
