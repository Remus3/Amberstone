"""R142-S1 characterization tests for the RUNE-side SELF-HEAL registry.

OFFLINE ONLY - no DS :8860 call, no network, no live game state. Every number
here is either an EXACT DDragon 16.14.1 magnitude or an engine constant this
file pins against its source module, so a drift on either side goes RED.
"""

from __future__ import annotations

import unittest

from agents.daemon_slayer._rune_self_heal import (
    SECOND_WIND_MISSING_HP_PCT,
    SECOND_WIND_HEAL_DURATION_S,
    _MISSING_HP_SHARE_FOR_HEALS,
    _FIGHT_WINDOW_S,
    _SECOND_WIND_WINDOW_UPTIME,
    second_wind_heal,
    sum_rune_self_heal,
)


class MagnitudeTests(unittest.TestCase):
    """The 4%-of-missing-health magnitude is EXACT DDragon, not a midpoint."""

    def test_ddragon_magnitude_is_four_percent(self):
        self.assertEqual(SECOND_WIND_MISSING_HP_PCT, 0.04)

    def test_ddragon_duration_is_ten_seconds(self):
        self.assertEqual(SECOND_WIND_HEAL_DURATION_S, 10.0)

    def test_hand_computed_value_at_a_known_pair(self):
        # 4% of missing health, missing = 50% of a 3000 pool:
        #   0.04 * 3000 * 0.5 = 60.0 raw, realized over 10s.
        # The engine models a 6s fight window, so 6/10 of the heal-over-time
        # lands inside it: 60.0 * 0.6 = 36.0.
        self.assertAlmostEqual(
            second_wind_heal(max_health=3000.0, missing_hp_share=0.5), 36.0
        )

    def test_registry_path_matches_the_direct_helper(self):
        direct = second_wind_heal(max_health=2400.0, missing_hp_share=0.5)
        via_page = sum_rune_self_heal(["8444"], max_health=2400.0)
        self.assertAlmostEqual(via_page, direct)

    def test_scales_linearly_in_the_health_pool(self):
        one = sum_rune_self_heal(["8444"], max_health=1500.0)
        two = sum_rune_self_heal(["8444"], max_health=3000.0)
        self.assertAlmostEqual(two, one * 2.0)

    def test_scales_linearly_in_the_missing_share(self):
        quarter = second_wind_heal(max_health=3000.0, missing_hp_share=0.25)
        half = second_wind_heal(max_health=3000.0, missing_hp_share=0.5)
        self.assertAlmostEqual(half, quarter * 2.0)

    def test_full_health_target_heals_nothing(self):
        # Zero missing health is zero heal - the rune has no flat component.
        self.assertEqual(
            second_wind_heal(max_health=3000.0, missing_hp_share=0.0), 0.0
        )

    def test_integer_rune_id_is_coerced(self):
        self.assertAlmostEqual(
            sum_rune_self_heal([8444], max_health=3000.0),
            sum_rune_self_heal(["8444"], max_health=3000.0),
        )


class ConventionPinTests(unittest.TestCase):
    """The missing-health convention is REUSED from ehp.py, never re-invented."""

    def test_missing_hp_share_equals_the_ehp_module_constant(self):
        from agents.daemon_slayer.ehp import (
            _MISSING_HP_SHARE_FOR_HEALS as ehp_share,
        )

        self.assertEqual(_MISSING_HP_SHARE_FOR_HEALS, ehp_share)

    def test_fight_window_equals_the_ehp_module_constant(self):
        from agents.daemon_slayer.ehp import _FIGHT_WINDOW_S as ehp_window

        self.assertEqual(_FIGHT_WINDOW_S, ehp_window)

    def test_window_uptime_is_derived_not_hand_typed(self):
        self.assertAlmostEqual(
            _SECOND_WIND_WINDOW_UPTIME,
            min(1.0, _FIGHT_WINDOW_S / SECOND_WIND_HEAL_DURATION_S),
        )

    def test_uptime_is_a_proper_fraction(self):
        self.assertGreater(_SECOND_WIND_WINDOW_UPTIME, 0.0)
        self.assertLessEqual(_SECOND_WIND_WINDOW_UPTIME, 1.0)

    def test_default_missing_share_is_the_engine_convention(self):
        explicit = second_wind_heal(
            max_health=3000.0, missing_hp_share=_MISSING_HP_SHARE_FOR_HEALS
        )
        defaulted = sum_rune_self_heal(["8444"], max_health=3000.0)
        self.assertAlmostEqual(defaulted, explicit)


class AllowlistTests(unittest.TestCase):
    """Exactly one id is seeded; every sibling_lane rune routes away."""

    def test_full_offensive_rune_page_returns_zero(self):
        # Precision keystone page: Press the Attack, Presence of Mind,
        # Legend Alacrity, Cut Down, plus a Domination secondary.
        page = ["8005", "8009", "9104", "8014", "8143", "8135"]
        self.assertEqual(sum_rune_self_heal(page, max_health=3000.0), 0.0)

    def test_sibling_lane_resolve_runes_return_zero(self):
        # 8439/8429/8242 -> _rune_resist_grants, 8437/8451 ->
        # _rune_health_grants, 8453 -> _rune_hsp_amp, 8473 -> flat mitigation,
        # 8463 DATA-BLOCKED, 8465 shield lane. None belong here.
        for rid in ("8439", "8429", "8242", "8437", "8451", "8453", "8473",
                    "8463", "8465", "8446"):
            with self.subTest(rune_id=rid):
                self.assertEqual(sum_rune_self_heal([rid], max_health=3000.0), 0.0)

    def test_second_wind_survives_inside_a_mixed_page(self):
        page = ["8437", "8444", "8453", "8005"]
        self.assertAlmostEqual(
            sum_rune_self_heal(page, max_health=3000.0),
            sum_rune_self_heal(["8444"], max_health=3000.0),
        )

    def test_duplicate_id_credited_once(self):
        once = sum_rune_self_heal(["8444"], max_health=3000.0)
        thrice = sum_rune_self_heal(["8444", "8444", 8444], max_health=3000.0)
        self.assertAlmostEqual(thrice, once)


class FailSoftTests(unittest.TestCase):
    """Empty / None / garbage input returns 0.0 - never raises."""

    def test_none_rune_list(self):
        self.assertEqual(sum_rune_self_heal(None, max_health=3000.0), 0.0)

    def test_empty_rune_list(self):
        self.assertEqual(sum_rune_self_heal([], max_health=3000.0), 0.0)

    def test_non_iterable_rune_list(self):
        self.assertEqual(sum_rune_self_heal(1234, max_health=3000.0), 0.0)

    def test_none_entries_inside_the_list(self):
        self.assertAlmostEqual(
            sum_rune_self_heal([None, "8444", None], max_health=3000.0),
            sum_rune_self_heal(["8444"], max_health=3000.0),
        )

    def test_garbage_entries_do_not_raise(self):
        self.assertEqual(
            sum_rune_self_heal(["", "abc", {}, ()], max_health=3000.0), 0.0
        )

    def test_none_max_health(self):
        self.assertEqual(sum_rune_self_heal(["8444"], max_health=None), 0.0)

    def test_negative_max_health_clamps_to_zero(self):
        self.assertEqual(sum_rune_self_heal(["8444"], max_health=-500.0), 0.0)

    def test_negative_missing_share_clamps_to_zero(self):
        self.assertEqual(
            second_wind_heal(max_health=3000.0, missing_hp_share=-0.5), 0.0
        )

    def test_missing_share_above_one_is_clamped(self):
        # Missing health can never exceed the pool.
        self.assertAlmostEqual(
            second_wind_heal(max_health=3000.0, missing_hp_share=4.0),
            second_wind_heal(max_health=3000.0, missing_hp_share=1.0),
        )

    def test_non_numeric_max_health(self):
        self.assertEqual(sum_rune_self_heal(["8444"], max_health="lots"), 0.0)


if __name__ == "__main__":
    unittest.main()
