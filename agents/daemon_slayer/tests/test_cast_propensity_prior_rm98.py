"""RM-98 - cast-rate propensity prior (DEFAULT-OFF seam).

Pins the adjudicated recommendation in
``docs/specs/SPEC_rm98_cast_rate_time_base.md:135-147``: the measured
whole-game cast rate is DEMOTED from a DPS multiplier to a dimensionless
cast-propensity PRIOR, and the combat-basis rate is rebuilt on the
cooldown-inverse (correct-units) availability rate modulated by that prior.

Three contracts:

* (a) flag OFF is byte-identical to today's scores - every branch, both the
  scalar scorer and the ranker.
* (b) flag ON moves the ability term in the PREDICTED direction (up, by the
  reference-normalisation factor, for every spell whose propensity sits
  below the full-availability reference).
* (c) the Aatrox-W-style low-propensity signal SURVIVES. RM-39 flagged this
  as must-not-discard (``SPEC:144-147``): Infernal Chains is genuinely cast
  less often than available, and a pure cooldown-inverse model throws that
  away by handing every spell a prior of 1.0.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer.ability_dps import compute_ability_dps
from agents.daemon_slayer.cast_propensity import (
    FULL_AVAILABILITY_PROPENSITY,
    cast_propensity,
    cast_propensity_prior,
    combat_basis_casts_per_sec,
    propensity_adjusted_dps_delta,
    theoretical_casts_per_sec,
)
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.hybrid import compute_hybrid, rank_items_by_hybrid

# Two AD bruisers (the RM-39 AD-axis branch), one AP mage (the ability branch),
# one AD bruiser whose W is the low-propensity signal the prior must keep.
_AD_CHAMPS = ("Renekton", "Riven", "Aatrox")
_AP_CHAMPS = ("Veigar",)


class PropensityMathTests(unittest.TestCase):
    """Pure-function contracts - no snapshot needed."""

    def test_theoretical_is_cooldown_inverse(self) -> None:
        self.assertAlmostEqual(theoretical_casts_per_sec(4.0), 0.25)
        self.assertEqual(theoretical_casts_per_sec(0.0), 0.0)
        self.assertEqual(theoretical_casts_per_sec(-1.0), 0.0)

    def test_propensity_is_measured_over_theoretical(self) -> None:
        # SPEC:16-18 - Veigar Q, 4s cooldown, measured 0.098 casts/sec.
        self.assertAlmostEqual(cast_propensity(4.0, 0.098), 0.392, places=3)
        # Degenerate cooldown -> no theoretical -> no propensity.
        self.assertEqual(cast_propensity(0.0, 0.098), 0.0)

    def test_prior_is_propensity_over_reference_clamped_to_one(self) -> None:
        ref = FULL_AVAILABILITY_PROPENSITY
        # A spell sitting exactly at the reference realises full availability.
        cd = 4.0
        measured_at_ref = ref * theoretical_casts_per_sec(cd)
        self.assertAlmostEqual(cast_propensity_prior(cd, measured_at_ref), 1.0)
        # Half the reference -> half the availability.
        self.assertAlmostEqual(cast_propensity_prior(cd, measured_at_ref / 2.0), 0.5)
        # Above the reference clamps - a prior is a fraction of availability
        # and cannot exceed 1.0.
        self.assertAlmostEqual(cast_propensity_prior(cd, measured_at_ref * 9.0), 1.0)

    def test_combat_basis_rate_is_availability_times_prior(self) -> None:
        cd = 4.0
        measured = 0.098
        prior = cast_propensity_prior(cd, measured)
        self.assertAlmostEqual(
            combat_basis_casts_per_sec(cd, measured),
            theoretical_casts_per_sec(cd) * prior,
        )
        # The uncapped transform is a LIFT, never a cut.
        self.assertGreater(combat_basis_casts_per_sec(cd, measured), measured)

    def test_measured_rate_is_a_hard_floor(self) -> None:
        """The lower-bound proof: combat time is a subset of game time.

        Binds on the propensity-above-1.0 rows the ``1 / cooldown``
        availability model undercounts (Riven Q Broken Wings: 3 casts per
        13s cooldown, measured 0.19941 vs availability 0.07692).
        """
        cd, measured = 13.0, 0.19941
        self.assertGreater(cast_propensity(cd, measured), 1.0)
        self.assertEqual(combat_basis_casts_per_sec(cd, measured), measured)

    def test_transform_is_monotone_non_decreasing(self) -> None:
        for cd in (0.25, 1.0, 4.0, 13.0, 60.0, 130.0):
            for measured in (0.001, 0.005, 0.02, 0.098, 0.2, 0.5):
                with self.subTest(cd=cd, measured=measured):
                    self.assertGreaterEqual(
                        combat_basis_casts_per_sec(cd, measured), measured
                    )

    def test_zero_measured_stays_zero(self) -> None:
        self.assertEqual(combat_basis_casts_per_sec(4.0, 0.0), 0.0)
        self.assertEqual(combat_basis_casts_per_sec(0.0, 0.5), 0.5)


class PerSpellRowTests(unittest.TestCase):
    """The row-level transform the hybrid seam is built on."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def _rows(self, champion_id: str):
        return compute_ability_dps(
            self.snap, champion_id=champion_id, level=13, item_ids=(), mode="SR"
        ).per_spell

    def test_delta_is_zero_for_empty_rows(self) -> None:
        self.assertEqual(propensity_adjusted_dps_delta(()), 0.0)

    def test_non_measured_rows_are_untouched(self) -> None:
        # A row whose cast rate came from the 1/cooldown fallback is ALREADY on
        # a combat basis (SPEC:109-112 names the mixed-basis sum as the defect);
        # re-basing it would double-apply. Only "measured" rows move.
        rows = [r for r in self._rows("Aatrox")]
        fallback = [r for r in rows if r.casts_per_sec_source != "measured"]
        if fallback:
            self.assertEqual(propensity_adjusted_dps_delta(fallback), 0.0)

    def test_aatrox_w_low_propensity_signal_survives(self) -> None:
        """(c) - the must-not-discard signal, SPEC:144-147."""
        rows = {r.key: r for r in self._rows("Aatrox")}
        w, q = rows["W"], rows["Q"]
        self.assertEqual(w.casts_per_sec_source, "measured")
        self.assertEqual(q.casts_per_sec_source, "measured")
        w_prior = cast_propensity_prior(w.cooldown, w.casts_per_sec)
        q_prior = cast_propensity_prior(q.cooldown, q.casts_per_sec)
        # A pure cooldown-inverse model gives BOTH 1.0 and discards the signal.
        self.assertLess(w_prior, 1.0)
        # Infernal Chains is cast markedly less often than Darkin Blade.
        self.assertLess(w_prior, q_prior)
        self.assertLess(w_prior, 0.6)

    def test_delta_respects_damage_type_filter(self) -> None:
        rows = self._rows("Aatrox")
        all_delta = propensity_adjusted_dps_delta(rows)
        magic_only = propensity_adjusted_dps_delta(
            rows, credited_damage_types=frozenset({"MAGIC"})
        )
        self.assertGreater(all_delta, 0.0)
        self.assertLess(magic_only, all_delta)


class HybridFlagOffByteIdenticalTests(unittest.TestCase):
    """(a) - DEFAULT-OFF must not move a single float."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_scalar_scorer_default_matches_explicit_false(self) -> None:
        for champ in _AD_CHAMPS + _AP_CHAMPS:
            for ad_axis in (False, True):
                with self.subTest(champ=champ, ad_axis=ad_axis):
                    base = compute_hybrid(
                        self.snap, champion_id=champ, level=13,
                        item_ids=("3078",), mode="SR",
                        apply_ad_axis_ability_damage=ad_axis,
                    )
                    off = compute_hybrid(
                        self.snap, champion_id=champ, level=13,
                        item_ids=("3078",), mode="SR",
                        apply_ad_axis_ability_damage=ad_axis,
                        apply_cast_rate_propensity_prior=False,
                    )
                    self.assertEqual(base.dps, off.dps)
                    self.assertEqual(base.hybrid_score, off.hybrid_score)

    def test_ranker_default_matches_explicit_false(self) -> None:
        for champ in ("Renekton", "Veigar"):
            with self.subTest(champ=champ):
                base = rank_items_by_hybrid(
                    self.snap, champion_id=champ, level=13, mode="SR", top_n=8,
                    apply_ad_axis_ability_damage=True,
                )
                off = rank_items_by_hybrid(
                    self.snap, champion_id=champ, level=13, mode="SR", top_n=8,
                    apply_ad_axis_ability_damage=True,
                    apply_cast_rate_propensity_prior=False,
                )
                self.assertEqual(
                    [i.item_id for i in base.ranked], [i.item_id for i in off.ranked]
                )
                self.assertEqual(
                    [i.new_dps for i in base.ranked], [i.new_dps for i in off.ranked]
                )
                self.assertEqual(base.baseline_dps, off.baseline_dps)


class HybridFlagOnDirectionTests(unittest.TestCase):
    """(b) - ON moves the ability term in the predicted direction."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_ap_branch_ability_term_rises(self) -> None:
        for champ in _AP_CHAMPS:
            with self.subTest(champ=champ):
                off = compute_hybrid(
                    self.snap, champion_id=champ, level=13,
                    item_ids=("3078",), mode="SR",
                )
                on = compute_hybrid(
                    self.snap, champion_id=champ, level=13,
                    item_ids=("3078",), mode="SR",
                    apply_cast_rate_propensity_prior=True,
                )
                self.assertGreater(on.dps, off.dps)
                self.assertGreater(on.hybrid_score, off.hybrid_score)

    def test_ad_branch_moves_only_when_ad_axis_term_is_on(self) -> None:
        # With the AD-axis ability term OFF the AD branch is auto-attack-only,
        # so the prior has nothing to modulate - byte-identical.
        for champ in _AD_CHAMPS:
            with self.subTest(champ=champ):
                off = compute_hybrid(
                    self.snap, champion_id=champ, level=13,
                    item_ids=("3078",), mode="SR",
                )
                on_prior_only = compute_hybrid(
                    self.snap, champion_id=champ, level=13,
                    item_ids=("3078",), mode="SR",
                    apply_cast_rate_propensity_prior=True,
                )
                self.assertEqual(off.dps, on_prior_only.dps)
                # Both seams ON: the ability half rises.
                both_off = compute_hybrid(
                    self.snap, champion_id=champ, level=13,
                    item_ids=("3078",), mode="SR",
                    apply_ad_axis_ability_damage=True,
                )
                both_on = compute_hybrid(
                    self.snap, champion_id=champ, level=13,
                    item_ids=("3078",), mode="SR",
                    apply_ad_axis_ability_damage=True,
                    apply_cast_rate_propensity_prior=True,
                )
                self.assertGreater(both_on.dps, both_off.dps)

    def test_ranker_on_path_executes(self) -> None:
        off = rank_items_by_hybrid(
            self.snap, champion_id="Renekton", level=13, mode="SR", top_n=10,
            apply_ad_axis_ability_damage=True,
        )
        on = rank_items_by_hybrid(
            self.snap, champion_id="Renekton", level=13, mode="SR", top_n=10,
            apply_ad_axis_ability_damage=True,
            apply_cast_rate_propensity_prior=True,
        )
        self.assertGreater(on.baseline_dps, off.baseline_dps)
        self.assertNotEqual(
            [i.new_dps for i in off.ranked], [i.new_dps for i in on.ranked]
        )
        by_id = {i.item_id: i.new_dps for i in off.ranked}
        moved = 0
        for row in on.ranked:
            if row.item_id in by_id:
                # Monotone non-decreasing per the floor contract.
                self.assertGreaterEqual(row.new_dps, by_id[row.item_id])
                if row.new_dps > by_id[row.item_id]:
                    moved += 1
        self.assertGreater(moved, 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
