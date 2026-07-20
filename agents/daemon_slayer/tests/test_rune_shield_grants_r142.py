"""R142-S2: characterization tests for the SELF-side rune SHIELD registry.

OFFLINE ONLY - no network, no live :8893, no game state. Every assertion is
either an INVARIANT (monotonicity, clamping, additivity, zero-when-off,
fail-soft) or an EXACT reproduction of a verbatim DDragon 16.14.1 coefficient.
No cross-item / cross-champion comparison assertions (data-fragile, banned by
repo policy).

The most load-bearing guard here is ``AbilityPowerOmissionRegressionTests``. The
"+20% of your ability power" term of Guardian is DELIBERATELY omitted because
``ehp.py`` carries no wielder ability-power value at the call site (R136 measured
finding). A future well-meaning edit that adds AP scaling without first
introducing an AP convention at the EHP seam must fail LOUDLY rather than
silently invent a value - these tests are that tripwire.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer._rune_shield_grants import (
    _GUARDIAN_BONUS_HP_PCT,
    _GUARDIAN_COOLDOWN_AT_LEVEL_1,
    _GUARDIAN_COOLDOWN_AT_LEVEL_18,
    _GUARDIAN_SHIELD_AT_LEVEL_1,
    _GUARDIAN_SHIELD_AT_LEVEL_18,
    _GUARDIAN_SHIELD_DURATION_S,
    _RUNE_SHIELD_GRANTS,
    _RUNE_GUARDIAN_SHIELD_PROB,
    RuneShieldEntry,
    guardian_cooldown,
    guardian_self_shield,
    guardian_shield_base,
    rune_shield_grants,
)

GUARDIAN = "8465"

# A page carrying Guardian plus non-shield Resolve companions.
RESOLVE_PAGE = (GUARDIAN, "8429", "8451", "8453")
# A fully offensive page - Precision / Domination keystones and minors. None of
# these grant the wielder a shield, so the registry must return exactly 0.0.
OFFENSIVE_PAGE = ("8005", "9111", "9104", "8014", "8112", "8143", "8138", "8135")


def _kw(level=11, total_hp=2400.0, base_hp=1400.0):
    """Default keyword bundle for the public seam - one place to tune."""
    return {"level": level, "total_hp": total_hp, "base_hp": base_hp}


class DDragonMagnitudeTests(unittest.TestCase):
    """The magnitudes must be EXACT DDragon 16.14.1, never rounded or re-derived."""

    def test_shield_endpoints_match_longdesc(self):
        self.assertEqual(_GUARDIAN_SHIELD_AT_LEVEL_1, 40.0)
        self.assertEqual(_GUARDIAN_SHIELD_AT_LEVEL_18, 150.0)

    def test_cooldown_endpoints_match_longdesc(self):
        self.assertEqual(_GUARDIAN_COOLDOWN_AT_LEVEL_1, 75.0)
        self.assertEqual(_GUARDIAN_COOLDOWN_AT_LEVEL_18, 40.0)

    def test_shield_duration_matches_longdesc(self):
        # "both of you gain a shield for 1.5s" - the numerator of the raw duty
        # cycle the amortization midpoint deliberately overrides.
        self.assertEqual(_GUARDIAN_SHIELD_DURATION_S, 1.5)

    def test_raw_duty_cycle_is_far_below_the_adopted_midpoint(self):
        # Reproduces the docstring's argument rather than trusting the prose:
        # 1.5s on a 75-40s cooldown is ~0.02-0.0375, well under 0.2. The midpoint
        # is an engagement-synchronization uplift, not a duty cycle.
        for lv in (1, 18):
            raw = _GUARDIAN_SHIELD_DURATION_S / guardian_cooldown(lv)
            self.assertLess(raw, 0.05)
            self.assertLess(raw, _RUNE_GUARDIAN_SHIELD_PROB)

    def test_bonus_health_coefficient_is_six_percent(self):
        # "6% of your bonus health" stored as a percent (6.0 == 6%), the
        # _rune_resist_grants field convention (75.0 == 75%).
        self.assertEqual(_GUARDIAN_BONUS_HP_PCT, 6.0)

    def test_registry_is_a_single_id_allowlist(self):
        self.assertEqual(set(_RUNE_SHIELD_GRANTS), {GUARDIAN})
        self.assertIsInstance(_RUNE_SHIELD_GRANTS[GUARDIAN], RuneShieldEntry)

    def test_entry_carries_a_family_tag(self):
        self.assertTrue(_RUNE_SHIELD_GRANTS[GUARDIAN].family)


class LevelInterpolationTests(unittest.TestCase):
    """The standard Riot linear level-1-to-18 walk across 17 level-ups."""

    def test_shield_base_endpoints_are_exact(self):
        self.assertAlmostEqual(guardian_shield_base(1), 40.0)
        self.assertAlmostEqual(guardian_shield_base(18), 150.0)

    def test_shield_base_midpoint_computed_by_hand(self):
        # level 10 -> 40 + (150 - 40) * (10 - 1) / 17 = 40 + 110 * 9 / 17.
        self.assertAlmostEqual(guardian_shield_base(10), 40.0 + 110.0 * 9.0 / 17.0)

    def test_shield_base_is_strictly_increasing_in_level(self):
        vals = [guardian_shield_base(lv) for lv in range(1, 19)]
        for lo, hi in zip(vals, vals[1:]):
            self.assertLess(lo, hi)

    def test_shield_base_clamps_out_of_range_levels(self):
        self.assertAlmostEqual(guardian_shield_base(0), guardian_shield_base(1))
        self.assertAlmostEqual(guardian_shield_base(-5), guardian_shield_base(1))
        self.assertAlmostEqual(guardian_shield_base(99), guardian_shield_base(18))

    def test_cooldown_walks_downward_across_the_same_span(self):
        self.assertAlmostEqual(guardian_cooldown(1), 75.0)
        self.assertAlmostEqual(guardian_cooldown(18), 40.0)
        self.assertAlmostEqual(guardian_cooldown(10), 75.0 - 35.0 * 9.0 / 17.0)

    def test_cooldown_is_strictly_decreasing_in_level(self):
        vals = [guardian_cooldown(lv) for lv in range(1, 19)]
        for lo, hi in zip(vals, vals[1:]):
            self.assertGreater(lo, hi)


class BonusHealthTermTests(unittest.TestCase):
    """The 6%-of-BONUS-health term, including the zero and below-base cases."""

    def test_zero_bonus_health_yields_the_level_base_only(self):
        self.assertAlmostEqual(
            guardian_self_shield(level=1, total_hp=600.0, base_hp=600.0), 40.0
        )
        self.assertAlmostEqual(
            guardian_self_shield(level=18, total_hp=2200.0, base_hp=2200.0), 150.0
        )

    def test_bonus_health_term_is_six_percent_of_the_delta(self):
        got = guardian_self_shield(level=18, total_hp=3200.0, base_hp=2200.0)
        self.assertAlmostEqual(got, 150.0 + 0.06 * 1000.0)

    def test_below_base_health_never_yields_a_negative_contribution(self):
        # A below-base build must clamp the bonus term at zero, not subtract -
        # the _rune_resist_grants max(0.0, total - base) contract.
        below = guardian_self_shield(level=18, total_hp=1500.0, base_hp=2200.0)
        flat = guardian_self_shield(level=18, total_hp=2200.0, base_hp=2200.0)
        self.assertAlmostEqual(below, flat)
        self.assertGreaterEqual(below, 0.0)

    def test_shield_is_monotonic_non_decreasing_in_bonus_health(self):
        prev = -1.0
        for total in (1400.0, 1800.0, 2400.0, 3000.0, 4000.0):
            cur = guardian_self_shield(level=11, total_hp=total, base_hp=1400.0)
            self.assertGreaterEqual(cur, prev)
            prev = cur

    def test_shield_is_never_negative_for_degenerate_pools(self):
        self.assertGreaterEqual(
            guardian_self_shield(level=1, total_hp=-100.0, base_hp=-50.0), 0.0
        )


class AmortizationTests(unittest.TestCase):
    """The firing midpoint is the ONLY assumption - magnitude stays exact."""

    def test_probability_sits_in_the_open_unit_interval(self):
        self.assertGreater(_RUNE_GUARDIAN_SHIELD_PROB, 0.0)
        self.assertLess(_RUNE_GUARDIAN_SHIELD_PROB, 1.0)

    def test_probability_is_at_or_below_the_active_resist_sibling(self):
        # Guardian's cooldown (75-40s) is 2x to 3.75x Aftershock's 20s, so it may
        # never be priced ABOVE the 0.3 sibling midpoint.
        self.assertLessEqual(_RUNE_GUARDIAN_SHIELD_PROB, 0.3)

    def test_seam_output_is_the_exact_magnitude_times_the_midpoint(self):
        kw = _kw()
        exact = guardian_self_shield(**kw)
        got = rune_shield_grants(
            [GUARDIAN], apply_rune_shield_grants=True, **kw
        )
        self.assertAlmostEqual(got, exact * _RUNE_GUARDIAN_SHIELD_PROB)

    def test_seam_output_is_strictly_less_than_the_raw_shield(self):
        kw = _kw()
        got = rune_shield_grants([GUARDIAN], apply_rune_shield_grants=True, **kw)
        self.assertLess(got, guardian_self_shield(**kw))
        self.assertGreater(got, 0.0)


class SeamContractTests(unittest.TestCase):
    """Default-OFF, allowlist, dedup, and the returned-type contract."""

    def test_default_is_off_and_returns_zero(self):
        self.assertEqual(rune_shield_grants([GUARDIAN], **_kw()), 0.0)
        self.assertEqual(rune_shield_grants(RESOLVE_PAGE, **_kw()), 0.0)

    def test_returns_a_bare_float(self):
        got = rune_shield_grants([GUARDIAN], apply_rune_shield_grants=True, **_kw())
        self.assertIsInstance(got, float)

    def test_full_offensive_page_returns_zero(self):
        self.assertEqual(
            rune_shield_grants(
                OFFENSIVE_PAGE, apply_rune_shield_grants=True, **_kw()
            ),
            0.0,
        )

    def test_duplicate_id_is_credited_at_most_once(self):
        kw = _kw()
        once = rune_shield_grants([GUARDIAN], apply_rune_shield_grants=True, **kw)
        thrice = rune_shield_grants(
            [GUARDIAN, GUARDIAN, GUARDIAN], apply_rune_shield_grants=True, **kw
        )
        self.assertAlmostEqual(once, thrice)

    def test_integer_ids_are_coerced(self):
        kw = _kw()
        self.assertAlmostEqual(
            rune_shield_grants([8465], apply_rune_shield_grants=True, **kw),
            rune_shield_grants([GUARDIAN], apply_rune_shield_grants=True, **kw),
        )

    def test_non_shield_resolve_companions_add_nothing(self):
        kw = _kw()
        self.assertAlmostEqual(
            rune_shield_grants(RESOLVE_PAGE, apply_rune_shield_grants=True, **kw),
            rune_shield_grants([GUARDIAN], apply_rune_shield_grants=True, **kw),
        )

    def test_font_of_life_and_second_wind_are_routed_away(self):
        # 8463 is DATA-BLOCKED (@BaseHeal@); 8444 is a HEAL owned by a sibling
        # slice. Neither may leak into this SHIELD registry.
        self.assertNotIn("8463", _RUNE_SHIELD_GRANTS)
        self.assertNotIn("8444", _RUNE_SHIELD_GRANTS)
        self.assertEqual(
            rune_shield_grants(
                ["8463", "8444"], apply_rune_shield_grants=True, **_kw()
            ),
            0.0,
        )


class FailSoftTests(unittest.TestCase):
    """Empty / None / garbage input returns 0.0 rather than raising."""

    def test_empty_iterable(self):
        self.assertEqual(
            rune_shield_grants([], apply_rune_shield_grants=True, **_kw()), 0.0
        )
        self.assertEqual(
            rune_shield_grants((), apply_rune_shield_grants=True, **_kw()), 0.0
        )

    def test_none_rune_list(self):
        self.assertEqual(
            rune_shield_grants(None, apply_rune_shield_grants=True, **_kw()), 0.0
        )

    def test_non_iterable_rune_list(self):
        for junk in (42, 3.5, object()):
            self.assertEqual(
                rune_shield_grants(junk, apply_rune_shield_grants=True, **_kw()),
                0.0,
            )

    def test_garbage_entries_inside_a_valid_iterable(self):
        got = rune_shield_grants(
            [None, "", "not-a-rune", {}, [], GUARDIAN],
            apply_rune_shield_grants=True,
            **_kw(),
        )
        self.assertAlmostEqual(
            got,
            rune_shield_grants([GUARDIAN], apply_rune_shield_grants=True, **_kw()),
        )

    def test_garbage_only_page_returns_zero(self):
        self.assertEqual(
            rune_shield_grants(
                [None, "xyz", object()], apply_rune_shield_grants=True, **_kw()
            ),
            0.0,
        )

    def test_non_numeric_pool_arguments_fail_soft(self):
        self.assertEqual(
            rune_shield_grants(
                [GUARDIAN],
                apply_rune_shield_grants=True,
                level="eleven",
                total_hp=None,
                base_hp="x",
            ),
            0.0,
        )


class AbilityPowerOmissionRegressionTests(unittest.TestCase):
    """The AP half of Guardian is a DELIBERATE, LOUD omission - keep it that way.

    ``ehp.py`` has ZERO wielder ability-power references, so there is no AP value
    at the EHP call site to read. Omitting the "+20% of your ability power" term
    makes the credit an intentional UNDERCOUNT (the correct, conservative
    direction). If a future edit adds AP scaling before an AP convention exists
    at the seam, these tests go RED.
    """

    def test_public_seam_rejects_an_ap_keyword(self):
        with self.assertRaises(TypeError):
            rune_shield_grants(
                [GUARDIAN],
                apply_rune_shield_grants=True,
                ability_power=500.0,
                **_kw(),
            )

    def test_magnitude_helper_rejects_an_ap_keyword(self):
        with self.assertRaises(TypeError):
            guardian_self_shield(
                level=18, total_hp=2200.0, base_hp=2200.0, ability_power=500.0
            )

    def test_no_ap_field_exists_on_the_entry_dataclass(self):
        fields = set(vars(_RUNE_SHIELD_GRANTS[GUARDIAN]))
        for banned in ("ability_power", "ap", "ap_ratio", "ap_pct", "shield_ap_pct"):
            self.assertNotIn(banned, fields)

    def test_level_18_zero_bonus_health_shield_is_exactly_the_flat_term(self):
        # If a 20%-AP term were silently folded in with some assumed AP value,
        # this would exceed 150.0.
        self.assertAlmostEqual(
            guardian_self_shield(level=18, total_hp=2200.0, base_hp=2200.0), 150.0
        )


if __name__ == "__main__":
    unittest.main()
