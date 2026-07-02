"""R58 - assume_ms_utility seam: Movement Speed utility valuation for the
BRUISER (hybrid) scorer.

The seam is DEFAULT-OFF. When ON, bonus MS over the champion's base MS is
converted into an effective-DPS multiplier via ``_ms_utility_multiplier``
(each 1 pct bonus MS ~= _MS_UTILITY_DPS_FRACTION pct effective bruiser DPS,
capped at _MS_UTILITY_DPS_CAP total credit). The multiplier feeds ONLY the
hybrid_score / hybrid_delta_pct composition - the raw ``dps`` / ``delta_dps``
/ ``new_dps`` surfaces keep RAW weighted_dps semantics so there is no double
counting with stat-derived DPS (e.g. Dead Man's Plate Shipwrecker).

Ground truth anchors (verified against the live snapshot, patch 16.13.1):
  * Darius base MS 340.0 (snapshot.champions["Darius"].stats.movespeed).
  * 3742 Dead Man's Plate: PercentMovementSpeedMod 0.04.
  * 4401 Force of Nature:  PercentMovementSpeedMod 0.04.
  * pct MS is ADDITIVE across items -> 340 * (1 + 0.08) = 367.2 resolved.
  * 3083 Warmog's Armor: no MS mods at all.
  * Darius archetype weights [0.65, 0.35] (archetype_weights.json).

Symbols under test are accessed via the module object (not from-imports) so
the characterization tests still run GREEN on the pre-R58 tree while the
seam tests fail RED (TDD red-first contract).

NO ENGINE_VERSION pin here - the orchestrator owns the bump.
"""

import inspect
import unittest

from agents.daemon_slayer import burst, dps, ehp, hybrid, rank
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps
from agents.daemon_slayer.hybrid import compute_hybrid, rank_items_by_hybrid

_CHAMP = "Darius"
_LEVEL = 13
_BASE_MS = 340.0
_DMP = "3742"       # Dead Man's Plate - 4 pct MS + Shipwrecker stack proc
_FON = "4401"       # Force of Nature - 4 pct MS, zero DPS stats
_WARMOG = "3083"    # Warmog's Armor - no MS at all
_ALPHA = 0.65       # Darius alpha from archetype_weights.json
# Shared target preset for the seam tests (keeps Shipwrecker's %-max-HP
# discharge non-zero so the no-double-count test has a real raw delta_dps).
_TARGET_KW = {
    "target_armor": 80.0,
    "target_mr": 60.0,
    "target_max_hp": 2200.0,
    "target_bonus_hp": 600.0,
}


class HelperMathTests(unittest.TestCase):
    """Pure math contract of _ms_utility_multiplier + the module constants."""

    def test_zero_bonus_is_identity(self):
        self.assertEqual(hybrid._ms_utility_multiplier(340.0, 340.0), 1.0)

    def test_darius_dmp_fon_multiplier(self):
        # bonus_frac = 27.2 / 340 = 0.08; 0.08 * 0.5 = 0.04 -> x1.04
        self.assertAlmostEqual(hybrid._ms_utility_multiplier(367.2, 340.0), 1.04)

    def test_below_base_clamps_to_identity(self):
        # Slows / negative MS never PENALIZE the score through this seam.
        self.assertEqual(hybrid._ms_utility_multiplier(300.0, 340.0), 1.0)

    def test_zero_base_fail_soft(self):
        # Missing champion record / zeroed base MS -> identity, never a div-by-0.
        self.assertEqual(hybrid._ms_utility_multiplier(367.2, 0.0), 1.0)

    def test_cap_engages(self):
        # +40 pct MS -> 0.40 * 0.5 = 0.20 raw credit, capped at the ceiling.
        self.assertAlmostEqual(
            hybrid._ms_utility_multiplier(340.0 * 1.40, 340.0),
            1.0 + hybrid._MS_UTILITY_DPS_CAP,
        )

    def test_constants_are_conservative_midpoints(self):
        self.assertGreater(hybrid._MS_UTILITY_DPS_FRACTION, 0.0)
        self.assertLessEqual(hybrid._MS_UTILITY_DPS_FRACTION, 1.0)
        self.assertGreater(hybrid._MS_UTILITY_DPS_CAP, 0.0)
        self.assertLessEqual(hybrid._MS_UTILITY_DPS_CAP, 0.25)


class StatBlockCharacterizationTests(unittest.TestCase):
    """Anchor the resolved-MS inputs the seam consumes (pre-existing math)."""

    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()

    def test_darius_naked_ms_is_base(self):
        r = compute_dps(self.snap, champion_id=_CHAMP, level=_LEVEL, item_ids=[])
        self.assertEqual(r.stats["ms"], _BASE_MS)

    def test_darius_dmp_fon_resolved_ms(self):
        r = compute_dps(
            self.snap, champion_id=_CHAMP, level=_LEVEL, item_ids=[_DMP, _FON],
        )
        # Additive pct: (340 + 0) * (1 + 0.04 + 0.04) = 367.2
        self.assertAlmostEqual(r.stats["ms"], 367.2)


class ComputeHybridSeamTests(unittest.TestCase):
    """compute_hybrid seam behavior: OFF byte-identical, ON worked pins."""

    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()

    def _hybrid(self, item_ids, **kw):
        return compute_hybrid(
            self.snap, champion_id=_CHAMP, level=_LEVEL, item_ids=item_ids,
            **_TARGET_KW, **kw,
        )

    def test_off_omitted_equals_explicit_false(self):
        omitted = self._hybrid([_DMP, _FON])
        explicit = self._hybrid([_DMP, _FON], assume_ms_utility=False)
        self.assertEqual(omitted.to_dict(), explicit.to_dict())
        self.assertEqual(omitted.ms_utility_mult, 1.0)
        # OFF score recomposes exactly from the surfaced raw components.
        self.assertEqual(
            omitted.hybrid_score,
            omitted.alpha * omitted.dps + omitted.beta * omitted.ehp,
        )

    def test_on_gt_off_and_worked_pin(self):
        off = self._hybrid([_DMP, _FON])
        on = self._hybrid([_DMP, _FON], assume_ms_utility=True)
        self.assertGreater(on.hybrid_score, off.hybrid_score)
        # Worked pin: DMP+FoN = +8 pct MS -> x1.04 on the DPS axis only.
        self.assertAlmostEqual(
            on.hybrid_score,
            off.alpha * (off.dps * 1.04) + off.beta * off.ehp,
            places=6,
        )
        # HybridResult.dps stays RAW weighted_dps even when the seam is ON.
        self.assertEqual(on.dps, off.dps)

    def test_on_surfaces_mult_and_note(self):
        off = self._hybrid([_DMP, _FON])
        on = self._hybrid([_DMP, _FON], assume_ms_utility=True)
        self.assertAlmostEqual(on.ms_utility_mult, 1.04)
        self.assertTrue(any("ms utility" in n for n in on.notes))
        self.assertFalse(any("ms utility" in n for n in off.notes))

    def test_on_eq_off_for_ms_less_build(self):
        # Warmog has zero MS -> resolved == base -> identity multiplier ->
        # the ON score line is bit-for-bit the OFF score line.
        off = self._hybrid([_WARMOG])
        on = self._hybrid([_WARMOG], assume_ms_utility=True)
        self.assertEqual(on.hybrid_score, off.hybrid_score)


class RankerSeamTests(unittest.TestCase):
    """rank_items_by_hybrid seam behavior on a controlled candidate pool."""

    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()

    def _rank(self, current, only, **kw):
        return rank_items_by_hybrid(
            self.snap, champion_id=_CHAMP, level=_LEVEL,
            current_item_ids=current, only_item_ids=only,
            **_TARGET_KW, **kw,
        )

    @staticmethod
    def _row(result, item_id):
        matches = [r for r in result.ranked if r.item_id == item_id]
        assert len(matches) == 1, f"expected exactly 1 row for {item_id}"
        return matches[0]

    def test_ranker_off_byte_identical(self):
        omitted = self._rank([], [_DMP, _FON, _WARMOG])
        explicit = self._rank([], [_DMP, _FON, _WARMOG], assume_ms_utility=False)
        self.assertEqual(len(omitted.ranked), len(explicit.ranked))
        for ra, rb in zip(omitted.ranked, explicit.ranked):
            self.assertEqual(ra.item_id, rb.item_id)
            self.assertEqual(ra.delta_dps, rb.delta_dps)
            self.assertEqual(ra.delta_ehp, rb.delta_ehp)
            self.assertEqual(ra.hybrid_delta_pct, rb.hybrid_delta_pct)
            self.assertEqual(ra.hybrid_score, rb.hybrid_score)

    def test_ranker_on_fon_gains_exact_alpha_credit(self):
        # FoN adds ZERO dps stats (raw delta_dps == 0) but +4 pct MS. On a
        # naked baseline (mult 1.0) the ON-vs-OFF pct gain is exactly
        # alpha * (FRACTION * bonus_frac) = 0.65 * 0.5 * 0.04 = 0.013.
        off = self._rank([], [_DMP, _FON, _WARMOG])
        on = self._rank([], [_DMP, _FON, _WARMOG], assume_ms_utility=True)
        fon_off = self._row(off, _FON)
        fon_on = self._row(on, _FON)
        self.assertAlmostEqual(
            fon_on.hybrid_delta_pct - fon_off.hybrid_delta_pct,
            _ALPHA * 0.5 * 0.04,
        )
        # Raw delta_dps surface is untouched by the seam.
        self.assertEqual(fon_on.delta_dps, 0.0)

    def test_ranker_on_msless_candidate_unchanged(self):
        # Warmog carries no MS: identity multiplier on a naked baseline ->
        # the ON row's pct is bit-for-bit the OFF row's pct.
        off = self._rank([], [_DMP, _FON, _WARMOG])
        on = self._rank([], [_DMP, _FON, _WARMOG], assume_ms_utility=True)
        self.assertEqual(
            self._row(on, _WARMOG).hybrid_delta_pct,
            self._row(off, _WARMOG).hybrid_delta_pct,
        )

    def test_shared_ms_multiplier_cancels(self):
        # Baseline already owns FoN (+4 pct MS) and the candidate (Warmog)
        # adds none: baseline and candidate share the same x1.02 multiplier,
        # which cancels in the normalized pct -> ON pct == OFF pct.
        off = self._rank([_FON], [_WARMOG])
        on = self._rank([_FON], [_WARMOG], assume_ms_utility=True)
        self.assertAlmostEqual(
            self._row(on, _WARMOG).hybrid_delta_pct,
            self._row(off, _WARMOG).hybrid_delta_pct,
            places=9,
        )

    def test_no_double_count_shipwrecker(self):
        # DMP already earns REAL raw delta_dps from the Shipwrecker proc fold.
        # The seam must NOT touch that raw surface (no double counting): only
        # the composed pct / score / mult move, and the ON pct still rises
        # because the +4 pct MS earns its separate utility credit.
        off = self._rank([], [_DMP, _FON, _WARMOG])
        on = self._rank([], [_DMP, _FON, _WARMOG], assume_ms_utility=True)
        dmp_off = self._row(off, _DMP)
        dmp_on = self._row(on, _DMP)
        self.assertGreater(dmp_off.delta_dps, 0.0)
        self.assertEqual(dmp_on.delta_dps, dmp_off.delta_dps)
        self.assertEqual(dmp_on.delta_ehp, dmp_off.delta_ehp)
        self.assertEqual(dmp_on.new_dps, dmp_off.new_dps)
        self.assertEqual(dmp_on.new_ehp, dmp_off.new_ehp)
        self.assertAlmostEqual(dmp_on.ms_utility_mult, 1.02)
        self.assertEqual(dmp_off.ms_utility_mult, 1.0)
        self.assertNotEqual(dmp_on.hybrid_score, dmp_off.hybrid_score)
        self.assertGreater(dmp_on.hybrid_delta_pct, dmp_off.hybrid_delta_pct)


class ScopeGuardTests(unittest.TestCase):
    """The seam exists ONLY on the two bruiser entry points, END-appended."""

    def test_seam_scope_and_end_append(self):
        for fn in (compute_hybrid, rank_items_by_hybrid):
            params = inspect.signature(fn).parameters
            names = list(params)
            self.assertIn("assume_ms_utility", names, fn.__name__)
            self.assertEqual(names[-1], "assume_ms_utility", fn.__name__)
            self.assertIs(params["assume_ms_utility"].default, False, fn.__name__)
        for fn in (
            rank.rank_items,
            dps.compute_dps,
            ehp.compute_ehp,
            burst.compute_burst_damage,
        ):
            self.assertNotIn(
                "assume_ms_utility",
                inspect.signature(fn).parameters,
                fn.__name__,
            )


if __name__ == "__main__":
    unittest.main()
