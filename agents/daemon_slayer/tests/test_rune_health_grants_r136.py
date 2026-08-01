"""R136-S1: characterization tests for the SELF-side rune max-HP / heal registry.

OFFLINE ONLY - no network, no live :8860, no game. Every assertion is an
INVARIANT (monotonicity, ranged-vs-melee ordering, zero-when-off, the 120-absorb
threshold binding point, additivity) or an EXACT reproduction of a verbatim
DDragon 16.14.1 coefficient. No cross-item / cross-champion comparison
assertions (data-fragile, banned by repo policy).

The single most load-bearing guard here is
``GraspCoefficientAntiDriftTests`` - it imports the ENEMY-side
``enemy_runes.ENEMY_RUNE_THREATS[8437]`` and asserts the self-side constants
equal it term for term. ``_rune_health_grants`` deliberately does NOT import
``enemy_runes`` (that would be a production import cycle), so a restated
constant could silently drift from its twin. This TEST is the join: it lives
outside the production import graph, so it can hold both sides at once and go
RED the moment either is edited alone.
"""
from __future__ import annotations

import math
import unittest

from agents.daemon_slayer._rune_health_grants import (
    _GRASP_PERM_HP_PER_PROC,
    _GRASP_HEAL_PCT_MAX_HP,
    _GRASP_PROCS_BY_LEVEL,
    _GRASP_PROCS_PER_FIGHT,
    _GRASP_RANGED_FACTOR,
    _OVERGROWTH_ABSORBED_BY_LEVEL,
    _OVERGROWTH_ABSORBS_PER_BLOCK,
    _OVERGROWTH_HP_PER_BLOCK,
    _OVERGROWTH_THRESHOLD_ABSORBS,
    _OVERGROWTH_THRESHOLD_PCT_MAX_HP,
    _RUNE_HEALTH_GRANTS,
    RuneHealthEntry,
    grasp_heal_hp,
    grasp_permanent_hp,
    overgrowth_hp_for_absorbed,
    rune_health_grants,
    stacks_at_level,
)
from agents.daemon_slayer.enemy_runes import ENEMY_RUNE_THREATS

_GRASP = "8437"
_OVERGROWTH = "8451"
_BOTH = [_GRASP, _OVERGROWTH]
_LEVELS = tuple(range(1, 19))
_MAX_HP = 3000.0


def _perm(rune_ids, level, max_hp=_MAX_HP, is_ranged=False):
    """Permanent-HP half of an opted-IN call (the EHP-numerator pool add)."""
    return rune_health_grants(
        rune_ids, level=level, max_hp=max_hp, is_ranged=is_ranged,
        apply_rune_health_grants=True,
    )[0]


def _heal(rune_ids, level, max_hp=_MAX_HP, is_ranged=False):
    """Heal half of an opted-IN call (the pre-amp raw heal)."""
    return rune_health_grants(
        rune_ids, level=level, max_hp=max_hp, is_ranged=is_ranged,
        apply_rune_health_grants=True,
    )[1]


class DefaultOffInertnessTests(unittest.TestCase):
    """The seam is DEFAULT-OFF: a caller that does not opt in gets exactly 0.0."""

    def test_omitting_the_flag_yields_zero(self) -> None:
        # No apply_rune_health_grants kwarg at all - the shape a pre-R136 caller
        # (or a forgetful new one) uses. Must be inert even with a full page.
        for level in _LEVELS:
            with self.subTest(level=level):
                self.assertEqual(
                    rune_health_grants(_BOTH, level=level, max_hp=_MAX_HP),
                    (0.0, 0.0),
                )

    def test_explicit_false_yields_zero(self) -> None:
        for is_ranged in (False, True):
            with self.subTest(is_ranged=is_ranged):
                self.assertEqual(
                    rune_health_grants(
                        _BOTH, level=18, max_hp=_MAX_HP, is_ranged=is_ranged,
                        apply_rune_health_grants=False,
                    ),
                    (0.0, 0.0),
                )

    def test_flag_default_is_false(self) -> None:
        import inspect
        params = inspect.signature(rune_health_grants).parameters
        self.assertIs(params["apply_rune_health_grants"].default, False)

    def test_opted_in_is_actually_non_zero(self) -> None:
        # Guards the guard: if the ON path were also 0.0 every other test here
        # would pass vacuously.
        perm, heal = rune_health_grants(
            _BOTH, level=18, max_hp=_MAX_HP, apply_rune_health_grants=True,
        )
        self.assertGreater(perm, 0.0)
        self.assertGreater(heal, 0.0)


class AllowlistTests(unittest.TestCase):
    """The registry is a deliberate two-id allowlist, not a tree-wide sweep."""

    def test_registry_holds_exactly_grasp_and_overgrowth(self) -> None:
        self.assertEqual(set(_RUNE_HEALTH_GRANTS), {_GRASP, _OVERGROWTH})

    def test_every_entry_is_a_rune_health_entry(self) -> None:
        for rid, entry in _RUNE_HEALTH_GRANTS.items():
            with self.subTest(rune_id=rid):
                self.assertIsInstance(entry, RuneHealthEntry)
                self.assertTrue(entry.note, "every entry must cite its longDesc")
                self.assertTrue(entry.family, "every entry needs a dedup family")

    def test_unregistered_runes_contribute_nothing(self) -> None:
        # A full offensive page: Press the Attack / Conqueror / Electrocute /
        # Aftershock / Second Wind. None grants self max-HP or self-heal on this
        # axis, so an opted-IN call must still return zero.
        for rid in ("8005", "8010", "8112", "8439", "8444", "9923"):
            with self.subTest(rune_id=rid):
                self.assertEqual(
                    rune_health_grants(
                        [rid], level=18, max_hp=_MAX_HP,
                        apply_rune_health_grants=True,
                    ),
                    (0.0, 0.0),
                )

    def test_empty_page_is_zero(self) -> None:
        self.assertEqual(
            rune_health_grants(
                [], level=18, max_hp=_MAX_HP, apply_rune_health_grants=True,
            ),
            (0.0, 0.0),
        )

    def test_int_and_string_ids_are_equivalent(self) -> None:
        # The engine keys ids as strings throughout; ints are coerced on lookup.
        as_str = rune_health_grants(
            _BOTH, level=13, max_hp=_MAX_HP, apply_rune_health_grants=True,
        )
        as_int = rune_health_grants(
            [8437, 8451], level=13, max_hp=_MAX_HP, apply_rune_health_grants=True,
        )
        self.assertEqual(as_str, as_int)

    def test_duplicate_ids_do_not_double_credit(self) -> None:
        once = rune_health_grants(
            _BOTH, level=13, max_hp=_MAX_HP, apply_rune_health_grants=True,
        )
        twice = rune_health_grants(
            _BOTH + _BOTH, level=13, max_hp=_MAX_HP,
            apply_rune_health_grants=True,
        )
        self.assertEqual(once, twice)


class GraspCoefficientAntiDriftTests(unittest.TestCase):
    """The self side and the ENEMY side must carry identical Grasp magnitudes.

    ``_rune_health_grants`` cannot import ``enemy_runes`` (production cycle), so
    it restates the constants. This test is the only place both are in scope at
    once - it is what makes the restatement safe.
    """

    def setUp(self) -> None:
        self.threat = ENEMY_RUNE_THREATS[8437]

    def test_heal_fraction_matches_enemy_side(self) -> None:
        self.assertEqual(_GRASP_HEAL_PCT_MAX_HP, self.threat.poke_heal_pct)

    def test_permanent_hp_matches_enemy_side(self) -> None:
        self.assertEqual(_GRASP_PERM_HP_PER_PROC, self.threat.perm_hp)

    def test_ranged_factor_matches_enemy_side(self) -> None:
        self.assertEqual(_GRASP_RANGED_FACTOR, self.threat.ranged_factor)

    def test_literal_ddragon_values(self) -> None:
        # Verbatim 16.14.1 longDesc: "Heal you for 1.3% of your max health",
        # "Permanently increase your health by 5", "Ranged Champions: ... 40%
        # effective". Pinned literally so a coordinated edit of BOTH registries
        # still trips a test.
        self.assertEqual(_GRASP_HEAL_PCT_MAX_HP, 0.013)
        self.assertEqual(_GRASP_PERM_HP_PER_PROC, 5.0)
        self.assertEqual(_GRASP_RANGED_FACTOR, 0.40)

    def test_overgrowth_literal_ddragon_values(self) -> None:
        # Verbatim: "permanently gaining 3 maximum health for every 8" and
        # "When you've absorbed 120 ... gain an additional 3.5% maximum health".
        self.assertEqual(_OVERGROWTH_HP_PER_BLOCK, 3.0)
        self.assertEqual(_OVERGROWTH_ABSORBS_PER_BLOCK, 8.0)
        self.assertEqual(_OVERGROWTH_THRESHOLD_ABSORBS, 120.0)
        self.assertEqual(_OVERGROWTH_THRESHOLD_PCT_MAX_HP, 3.5)


class StackProxyCurveTests(unittest.TestCase):
    """Both proxies follow the _passive_health_overrides curve convention."""

    def test_curves_are_18_entry(self) -> None:
        for name, curve in (
            ("grasp", _GRASP_PROCS_BY_LEVEL),
            ("overgrowth", _OVERGROWTH_ABSORBED_BY_LEVEL),
        ):
            with self.subTest(curve=name):
                self.assertEqual(len(curve), 18)

    def test_curves_are_monotonic_non_decreasing(self) -> None:
        for name, curve in (
            ("grasp", _GRASP_PROCS_BY_LEVEL),
            ("overgrowth", _OVERGROWTH_ABSORBED_BY_LEVEL),
        ):
            for i in range(1, len(curve)):
                with self.subTest(curve=name, level=i + 1):
                    self.assertGreaterEqual(curve[i], curve[i - 1])

    def test_curves_are_non_negative(self) -> None:
        for name, curve in (
            ("grasp", _GRASP_PROCS_BY_LEVEL),
            ("overgrowth", _OVERGROWTH_ABSORBED_BY_LEVEL),
        ):
            for i, v in enumerate(curve):
                with self.subTest(curve=name, level=i + 1):
                    self.assertGreaterEqual(v, 0.0)

    def test_overgrowth_curve_reaches_the_120_threshold(self) -> None:
        # A curve that never reaches 120 would make the threshold dead code and
        # every threshold test below vacuous.
        self.assertGreaterEqual(
            _OVERGROWTH_ABSORBED_BY_LEVEL[-1], _OVERGROWTH_THRESHOLD_ABSORBS,
        )

    def test_stacks_at_level_clamps_out_of_range(self) -> None:
        curve = _GRASP_PROCS_BY_LEVEL
        self.assertEqual(stacks_at_level(curve, 0), curve[0])
        self.assertEqual(stacks_at_level(curve, -5), curve[0])
        self.assertEqual(stacks_at_level(curve, 1), curve[0])
        self.assertEqual(stacks_at_level(curve, 18), curve[-1])
        self.assertEqual(stacks_at_level(curve, 25), curve[-1])

    def test_stacks_at_level_empty_curve_is_zero(self) -> None:
        self.assertEqual(stacks_at_level((), 10), 0.0)

    def test_out_of_range_levels_do_not_raise(self) -> None:
        for level in (-3, 0, 19, 40):
            with self.subTest(level=level):
                perm, heal = rune_health_grants(
                    _BOTH, level=level, max_hp=_MAX_HP,
                    apply_rune_health_grants=True,
                )
                self.assertGreaterEqual(perm, 0.0)
                self.assertGreaterEqual(heal, 0.0)


class OvergrowthThresholdTests(unittest.TestCase):
    """The 3.5% is a DISCRETE threshold at 120 absorbed - never smeared."""

    def test_no_percent_term_below_the_threshold(self) -> None:
        # At 119 absorbed the grant is PURE block HP: floor(119/8) * 3 = 42.
        self.assertAlmostEqual(
            overgrowth_hp_for_absorbed(119.0, _MAX_HP), 42.0, places=9,
        )

    def test_percent_term_pays_at_exactly_120(self) -> None:
        # At 120: floor(120/8) * 3 = 45, PLUS 3.5% of max HP.
        self.assertAlmostEqual(
            overgrowth_hp_for_absorbed(120.0, _MAX_HP),
            45.0 + 0.035 * _MAX_HP,
            places=9,
        )

    def test_the_119_to_120_step_carries_the_whole_percent_term(self) -> None:
        step = (
            overgrowth_hp_for_absorbed(120.0, _MAX_HP)
            - overgrowth_hp_for_absorbed(119.0, _MAX_HP)
        )
        # One block step (+3) plus the entire 3.5% threshold, in ONE jump.
        self.assertAlmostEqual(step, 3.0 + 0.035 * _MAX_HP, places=9)

    def test_threshold_is_not_smeared_linearly(self) -> None:
        # 112 and 119 sit in the SAME block (floor 14) and BOTH below 120, so a
        # correctly-discrete threshold makes them exactly equal. A linear smear
        # of the 3.5% across 0..120 absorbs would make 119 strictly larger.
        self.assertAlmostEqual(
            overgrowth_hp_for_absorbed(112.0, _MAX_HP),
            overgrowth_hp_for_absorbed(119.0, _MAX_HP),
            places=9,
        )

    def test_block_term_quantizes_by_8(self) -> None:
        # "3 maximum health for every 8" is a discrete block, not 0.375 each.
        for absorbed in (0.0, 1.0, 7.0):
            with self.subTest(absorbed=absorbed):
                self.assertAlmostEqual(
                    overgrowth_hp_for_absorbed(absorbed, _MAX_HP), 0.0, places=9,
                )
        self.assertAlmostEqual(
            overgrowth_hp_for_absorbed(8.0, _MAX_HP), 3.0, places=9,
        )
        self.assertAlmostEqual(
            overgrowth_hp_for_absorbed(15.0, _MAX_HP), 3.0, places=9,
        )
        self.assertAlmostEqual(
            overgrowth_hp_for_absorbed(16.0, _MAX_HP), 6.0, places=9,
        )

    def test_only_the_percent_term_scales_with_max_hp(self) -> None:
        # Below the threshold max_hp is irrelevant; above it the delta is
        # exactly 3.5% of the max-HP delta.
        self.assertAlmostEqual(
            overgrowth_hp_for_absorbed(100.0, 1000.0),
            overgrowth_hp_for_absorbed(100.0, 4000.0),
            places=9,
        )
        delta = (
            overgrowth_hp_for_absorbed(200.0, 4000.0)
            - overgrowth_hp_for_absorbed(200.0, 1000.0)
        )
        self.assertAlmostEqual(delta, 0.035 * 3000.0, places=9)

    def test_negative_and_zero_inputs_are_safe(self) -> None:
        self.assertAlmostEqual(
            overgrowth_hp_for_absorbed(-10.0, _MAX_HP), 0.0, places=9,
        )
        self.assertAlmostEqual(
            overgrowth_hp_for_absorbed(200.0, -100.0), 75.0, places=9,
        )


class RangedFactorTests(unittest.TestCase):
    """Grasp takes the 0.40 ranged factor; Overgrowth does NOT."""

    def test_ranged_grasp_is_strictly_below_melee(self) -> None:
        for level in _LEVELS:
            with self.subTest(level=level):
                melee_perm = _perm([_GRASP], level)
                ranged_perm = _perm([_GRASP], level, is_ranged=True)
                self.assertLess(ranged_perm, melee_perm)

    def test_ranged_grasp_permanent_hp_is_exactly_40_percent(self) -> None:
        for level in _LEVELS:
            with self.subTest(level=level):
                melee = _perm([_GRASP], level)
                ranged = _perm([_GRASP], level, is_ranged=True)
                self.assertAlmostEqual(ranged, melee * 0.40, places=9)

    def test_ranged_grasp_heal_is_exactly_40_percent(self) -> None:
        melee = _heal([_GRASP], 18)
        ranged = _heal([_GRASP], 18, is_ranged=True)
        self.assertLess(ranged, melee)
        self.assertAlmostEqual(ranged, melee * 0.40, places=9)

    def test_overgrowth_has_no_ranged_penalty(self) -> None:
        # The 16.14.1 Overgrowth longDesc carries NO <rules> ranged clause. A
        # blanket "apply ranged_factor to every rune" bug is caught here.
        for level in _LEVELS:
            with self.subTest(level=level):
                self.assertAlmostEqual(
                    _perm([_OVERGROWTH], level, is_ranged=True),
                    _perm([_OVERGROWTH], level),
                    places=9,
                )

    def test_combined_page_is_reduced_but_not_by_40_percent(self) -> None:
        # The discriminating case: a ranged champion on BOTH runes loses only
        # the Grasp share. Reading exactly 0.40 of melee would mean the factor
        # was wrongly applied to Overgrowth too.
        melee = _perm(_BOTH, 18)
        ranged = _perm(_BOTH, 18, is_ranged=True)
        self.assertLess(ranged, melee)
        self.assertGreater(ranged, melee * 0.40)

    def test_helper_level_ranged_ordering(self) -> None:
        self.assertAlmostEqual(
            grasp_permanent_hp(10.0, is_ranged=True),
            grasp_permanent_hp(10.0) * 0.40,
            places=9,
        )
        self.assertAlmostEqual(
            grasp_heal_hp(2.0, _MAX_HP, is_ranged=True),
            grasp_heal_hp(2.0, _MAX_HP) * 0.40,
            places=9,
        )


class MonotonicityAndAdditivityTests(unittest.TestCase):
    """Structural invariants that survive any future curve re-tune."""

    def test_permanent_hp_is_monotonic_in_level(self) -> None:
        for rune_set in ([_GRASP], [_OVERGROWTH], _BOTH):
            for is_ranged in (False, True):
                prev = -1.0
                for level in _LEVELS:
                    cur = _perm(rune_set, level, is_ranged=is_ranged)
                    with self.subTest(
                        runes=tuple(rune_set), ranged=is_ranged, level=level,
                    ):
                        self.assertGreaterEqual(cur, prev)
                    prev = cur

    def test_permanent_hp_strictly_grows_from_level_1_to_18(self) -> None:
        for rune_set in ([_GRASP], [_OVERGROWTH], _BOTH):
            with self.subTest(runes=tuple(rune_set)):
                self.assertGreater(
                    _perm(rune_set, 18), _perm(rune_set, 1),
                )

    def test_page_is_additive_across_runes(self) -> None:
        for level in _LEVELS:
            with self.subTest(level=level):
                self.assertAlmostEqual(
                    _perm(_BOTH, level),
                    _perm([_GRASP], level) + _perm([_OVERGROWTH], level),
                    places=9,
                )

    def test_overgrowth_grants_no_heal(self) -> None:
        # Its longDesc has no healing clause - only permanent max HP.
        for level in _LEVELS:
            with self.subTest(level=level):
                self.assertEqual(_heal([_OVERGROWTH], level), 0.0)

    def test_grasp_heal_scales_linearly_with_max_hp(self) -> None:
        # The heal is a pure fraction of max HP, so doubling the pool doubles it.
        single = _heal([_GRASP], 18, max_hp=2000.0)
        double = _heal([_GRASP], 18, max_hp=4000.0)
        self.assertAlmostEqual(double, single * 2.0, places=9)

    def test_grasp_heal_is_level_independent(self) -> None:
        # The per-fight proc count is a fight-window assumption, not a level
        # curve - unlike the cumulative permanent-HP proxy.
        base = _heal([_GRASP], 1)
        for level in _LEVELS:
            with self.subTest(level=level):
                self.assertAlmostEqual(_heal([_GRASP], level), base, places=9)

    def test_grasp_heal_equals_the_documented_formula(self) -> None:
        self.assertAlmostEqual(
            _heal([_GRASP], 18),
            _GRASP_PROCS_PER_FIGHT * _GRASP_HEAL_PCT_MAX_HP * _MAX_HP,
            places=9,
        )

    def test_zero_max_hp_yields_zero_heal(self) -> None:
        self.assertAlmostEqual(_heal([_GRASP], 18, max_hp=0.0), 0.0, places=9)

    def test_all_outputs_are_finite_floats(self) -> None:
        for level in _LEVELS:
            for is_ranged in (False, True):
                perm, heal = rune_health_grants(
                    _BOTH, level=level, max_hp=_MAX_HP, is_ranged=is_ranged,
                    apply_rune_health_grants=True,
                )
                with self.subTest(level=level, ranged=is_ranged):
                    self.assertIsInstance(perm, float)
                    self.assertIsInstance(heal, float)
                    self.assertTrue(math.isfinite(perm))
                    self.assertTrue(math.isfinite(heal))


class GraspPermanentHpFormulaTests(unittest.TestCase):
    """Permanent HP reproduces procs * 5 * ranged_factor at every level."""

    def test_matches_curve_times_per_proc_value(self) -> None:
        for level in _LEVELS:
            expected = (
                stacks_at_level(_GRASP_PROCS_BY_LEVEL, level)
                * _GRASP_PERM_HP_PER_PROC
            )
            with self.subTest(level=level):
                self.assertAlmostEqual(
                    _perm([_GRASP], level), expected, places=9,
                )

    def test_overgrowth_matches_curve_driven_helper(self) -> None:
        for level in _LEVELS:
            absorbed = stacks_at_level(_OVERGROWTH_ABSORBED_BY_LEVEL, level)
            with self.subTest(level=level, absorbed=absorbed):
                self.assertAlmostEqual(
                    _perm([_OVERGROWTH], level),
                    overgrowth_hp_for_absorbed(absorbed, _MAX_HP),
                    places=9,
                )


if __name__ == "__main__":
    unittest.main()
