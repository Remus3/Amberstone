"""R145 Slice A: the OFFENSE-side rune adaptive stat-grant lane.

Sorcery's two adaptive STAT grants - Gathering Storm 8236 and Absolute Focus
8233 - were registered in ``rune_procs.py`` with ``proc_type="adaptive"``, and
every consumer of that registry skips exactly that proc_type
(``burst.py:1034``). The force was computed and discarded: no DPS / hybrid / rank
path credited a single point of the up-to-101 AD or 168 AP those runes grant.

This module pins the new ``_rune_offense_grants`` registry, the DEFAULT-OFF
``apply_rune_offense_grants`` seam, and the byte-identity contract.

OFFLINE ONLY: no live :8893, no network.
"""
from __future__ import annotations

import ast
import inspect
import pathlib
import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer._effects_data import ITEM_EFFECTS
from agents.daemon_slayer._rune_offense_grants import (
    _ABSOLUTE_FOCUS_AD_AT_LEVEL_1,
    _ABSOLUTE_FOCUS_AD_AT_LEVEL_18,
    _ABSOLUTE_FOCUS_AP_AT_LEVEL_1,
    _ABSOLUTE_FOCUS_AP_AT_LEVEL_18,
    _ADAPTIVE_FORCE_AD_PER_AF,
    _ASSUMED_CONQUEROR_STACKS,
    _CONQUEROR_MAX_STACKS,
    _GATHERING_STORM_STEPS,
    _RUNE_OFFENSE_GRANTS,
    absolute_focus_grant,
    conqueror_grant,
    gathering_storm_step,
    rune_offense_grants,
)
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps
from agents.daemon_slayer.hybrid import compute_hybrid, rank_items_by_hybrid

GATHERING_STORM = "8236"
ABSOLUTE_FOCUS = "8233"
CONQUEROR = "8010"
# R155: the registry's non-adaptive attack-speed entry. Named here only so the
# allowlist assertion below stays exact; its behaviour is pinned in
# test_rune_offense_attack_speed_r155.py.
LEGEND_ALACRITY = "9104"
# R156: the registry's census-driven adaptive entry, named here for the same
# reason; its behaviour is pinned in
# test_rune_offense_jack_of_all_trades_r156.py.
JACK_OF_ALL_TRADES = "8316"
# Not in the registry by DESIGN (documented exclusions): proc damage, ability
# haste, mana, move speed.
ELECTROCUTE = "8112"
TRANSCENDENCE = "8210"
MANAFLOW_BAND = "8226"
CELERITY = "8234"
WATERWALKING = "8232"

_SNAP = None


def _snap() -> DataSnapshot:
    global _SNAP
    if _SNAP is None:
        _SNAP = DataSnapshot.load()
    return _SNAP


class GatheringStormStepTableTests(unittest.TestCase):
    """The step table is DDragon 16.14.1 verbatim - every row is pinned."""

    def test_every_milestone_row_matches_the_feed(self) -> None:
        # Verbatim longDesc: "10 min: + 8 AP or 5 AD  20 min: + 24 AP or 14 AD
        # 30 min: + 48 AP or 29 AD  40 min: + 80 AP or 48 AD  50 min: + 120 AP or
        # 72 AD  60 min: + 168 AP or 101 AD".
        expected = {
            10.0: (5.0, 8.0),
            20.0: (14.0, 24.0),
            30.0: (29.0, 48.0),
            40.0: (48.0, 80.0),
            50.0: (72.0, 120.0),
            60.0: (101.0, 168.0),
        }
        self.assertEqual(len(_GATHERING_STORM_STEPS), len(expected))
        for minute, (ad, ap) in expected.items():
            with self.subTest(minute=minute):
                self.assertEqual(gathering_storm_step(minute), (ad, ap))

    def test_below_the_first_milestone_is_zero(self) -> None:
        # "Every 10 min gain" - the first stack lands AT 10 minutes.
        for minute in (0.0, 5.0, 9.99):
            with self.subTest(minute=minute):
                self.assertEqual(gathering_storm_step(minute), (0.0, 0.0))

    def test_it_is_a_step_not_a_ramp(self) -> None:
        # The load-bearing divergence from rune_procs._gathering_storm, which
        # interpolates 5.0 * t/600 and prices 30 min at 15 AD where the feed
        # says 29 AD. Anywhere strictly inside a decade the value must equal the
        # decade's OPENING row, not something between two rows.
        self.assertEqual(gathering_storm_step(19.9), (5.0, 8.0))
        self.assertEqual(gathering_storm_step(29.9), (14.0, 24.0))
        # And it must NOT be the linear reading at the classic mid-game clock.
        ad_at_30, _ap = gathering_storm_step(30.0)
        self.assertEqual(ad_at_30, 29.0)
        self.assertNotAlmostEqual(ad_at_30, 5.0 * (1800.0 / 600.0), places=6)

    def test_past_sixty_minutes_clamps_rather_than_extrapolating(self) -> None:
        # The feed ends in "etc..." with no stated 70-minute magnitude -
        # DATA-BLOCKED, so the value is clamped, never invented.
        last = (101.0, 168.0)
        for minute in (60.0, 75.0, 120.0, 999.0):
            with self.subTest(minute=minute):
                self.assertEqual(gathering_storm_step(minute), last)


class AbsoluteFocusGrantTests(unittest.TestCase):
    """Verbatim: "up to 18 Attack Damage or 30 Ability Power (based on level)"."""

    def test_level_one_endpoint_matches_the_feed(self) -> None:
        # "Grants 1.8 Attack Damage or 3 Ability Power at level 1."
        ad, ap = absolute_focus_grant(1, 1.0)
        self.assertAlmostEqual(ad, 1.8, places=9)
        self.assertAlmostEqual(ap, 3.0, places=9)

    def test_level_eighteen_endpoint_matches_the_feed(self) -> None:
        ad, ap = absolute_focus_grant(18, 1.0)
        self.assertAlmostEqual(ad, 18.0, places=9)
        self.assertAlmostEqual(ap, 30.0, places=9)

    def test_the_seventy_percent_health_gate_is_strict(self) -> None:
        # "While above 70% health" - strict, matching rune_procs._absolute_focus
        # which returns 0.0 at caster_hp_pct <= 0.70.
        self.assertEqual(absolute_focus_grant(18, 0.70), (0.0, 0.0))
        self.assertEqual(absolute_focus_grant(18, 0.5), (0.0, 0.0))
        self.assertNotEqual(absolute_focus_grant(18, 0.701), (0.0, 0.0))


class AdaptiveForceConversionTests(unittest.TestCase):
    """1 Adaptive Force is 1 AP or 0.6 AD - pinned by the registry's OWN rows.

    Conqueror's feed states a raw Adaptive Force scalar and no per-column split,
    so its entry has to convert. The conversion ratio is not taken on faith: the
    two entries whose feeds DO enumerate both columns exhibit it in their stated
    data, and that is asserted here as a property so the constant cannot drift.
    """

    # Read from the module's own constants, never hand-copied, so the property
    # is pinned against the registry data itself.
    _EXACT_ROWS = (
        ("AbsoluteFocus L1", _ABSOLUTE_FOCUS_AD_AT_LEVEL_1, _ABSOLUTE_FOCUS_AP_AT_LEVEL_1),
        ("AbsoluteFocus L18", _ABSOLUTE_FOCUS_AD_AT_LEVEL_18, _ABSOLUTE_FOCUS_AP_AT_LEVEL_18),
    )
    _ROUNDED_ROWS = tuple(
        (f"GatheringStorm {int(minute)}min", ad, ap)
        for minute, ad, ap in _GATHERING_STORM_STEPS
    )

    def test_the_ratio_is_exact_where_the_feed_states_full_precision(self) -> None:
        # Absolute Focus publishes 1.8/3.0 and 18/30 - unrounded, so 0.6 * AP
        # reproduces the AD column exactly.
        for label, ad, ap in self._EXACT_ROWS:
            with self.subTest(row=label):
                self.assertAlmostEqual(_ADAPTIVE_FORCE_AD_PER_AF * ap, ad, places=9)

    def test_the_ratio_holds_to_feed_rounding_on_every_integer_row(self) -> None:
        # Gathering Storm publishes integers (5/8, 14/24, ...), so the ratio
        # shows up as the product rounded to the nearest whole number.
        for label, ad, ap in self._ROUNDED_ROWS:
            with self.subTest(row=label):
                self.assertEqual(round(_ADAPTIVE_FORCE_AD_PER_AF * ap), ad)
                self.assertLessEqual(abs(_ADAPTIVE_FORCE_AD_PER_AF * ap - ad), 0.5)

    def test_no_stated_row_supports_a_one_to_one_af_to_ad_reading(self) -> None:
        # The guard on the error this conversion exists to prevent: if AD were
        # the raw Adaptive Force, AD would equal AP on every row. It never does.
        for label, ad, ap in self._EXACT_ROWS + self._ROUNDED_ROWS:
            with self.subTest(row=label):
                self.assertNotAlmostEqual(ad, ap, places=3)

    def test_the_constant_is_the_documented_zero_point_six(self) -> None:
        self.assertEqual(_ADAPTIVE_FORCE_AD_PER_AF, 0.6)


class ConquerorGrantTests(unittest.TestCase):
    """Verbatim: "1.8-4 Adaptive Force per stack. Stacks up to 12 times."."""

    # 12 stacks * 1.8 AF = 21.6 AF at L1; * 4.0 = 48.0 AF at L18. AF pays the AP
    # column 1:1 and the AD column at 0.6.
    _AF_L1 = 21.6
    _AF_L18 = 48.0

    def test_default_stack_magnitude_at_level_one(self) -> None:
        ad, ap = conqueror_grant(1)
        self.assertAlmostEqual(ap, self._AF_L1, places=9)
        self.assertAlmostEqual(ad, 12.96, places=9)

    def test_default_stack_magnitude_at_level_eighteen(self) -> None:
        ad, ap = conqueror_grant(18)
        self.assertAlmostEqual(ap, self._AF_L18, places=9)
        self.assertAlmostEqual(ad, 28.8, places=9)

    def test_the_ad_column_is_the_converted_af_never_the_raw_scalar(self) -> None:
        # The specific error this entry exists to avoid: reading the raw Adaptive
        # Force onto AD would over-credit it by 1/0.6 = 1.667x.
        for level in range(1, 19):
            with self.subTest(level=level):
                ad, ap = conqueror_grant(level)
                self.assertAlmostEqual(ad, _ADAPTIVE_FORCE_AD_PER_AF * ap, places=9)
                self.assertLess(ad, ap)

    def test_the_raw_per_stack_adaptive_force_is_the_feed_walk(self) -> None:
        # 1.8 at L1 to 4.0 at L18, recovered by dividing out the stack count.
        for level, expected in ((1, 1.8), (18, 4.0)):
            with self.subTest(level=level):
                _ad, ap = conqueror_grant(level, _CONQUEROR_MAX_STACKS)
                self.assertAlmostEqual(ap / _CONQUEROR_MAX_STACKS, expected, places=9)

    def test_it_is_monotone_nondecreasing_in_level(self) -> None:
        values = [conqueror_grant(lvl)[1] for lvl in range(1, 19)]
        self.assertEqual(values, sorted(values))
        self.assertLess(values[0], values[-1])

    def test_out_of_range_levels_clamp_rather_than_extrapolate(self) -> None:
        self.assertEqual(conqueror_grant(0), conqueror_grant(1))
        self.assertEqual(conqueror_grant(99), conqueror_grant(18))


class ConquerorStackKnobTests(unittest.TestCase):
    """The stack count is an explicit knob, not a hardcoded 12.

    ``rune_procs.py:212`` assigns the live stack count to the CALLER ("the caller
    multiplies by the live stack count (max 12)"). The default is the feed's cap
    because the modeled fight is fully committed, but max-stacks is the
    anti-conservative reading on the SELF side, so it must stay overridable.
    """

    def test_the_feed_cap_and_the_assumed_default_are_both_twelve(self) -> None:
        # "Stacks up to 12 times."
        self.assertEqual(_CONQUEROR_MAX_STACKS, 12.0)
        self.assertEqual(_ASSUMED_CONQUEROR_STACKS, 12.0)

    def test_the_default_is_the_assumed_constant_not_a_literal(self) -> None:
        self.assertEqual(
            conqueror_grant(18), conqueror_grant(18, _ASSUMED_CONQUEROR_STACKS)
        )

    def test_the_grant_is_linear_in_the_stack_count(self) -> None:
        one = conqueror_grant(18, 1)[1]
        for stacks in range(0, 13):
            with self.subTest(stacks=stacks):
                self.assertAlmostEqual(
                    conqueror_grant(18, stacks)[1], one * stacks, places=9
                )

    def test_zero_stacks_grants_nothing(self) -> None:
        self.assertEqual(conqueror_grant(18, 0), (0.0, 0.0))

    def test_the_stack_count_clamps_to_the_feed_range(self) -> None:
        self.assertEqual(conqueror_grant(18, 99), conqueror_grant(18, 12))
        self.assertEqual(conqueror_grant(18, -5), conqueror_grant(18, 0))

    def test_a_junk_stack_count_falls_back_to_the_default(self) -> None:
        self.assertEqual(conqueror_grant(18, "many"), conqueror_grant(18))

    def test_the_knob_reaches_the_registry_through_the_public_entry_point(self) -> None:
        full = rune_offense_grants(
            [CONQUEROR], level=18, bonus_ad=250.0, ap=0.0
        )
        half = rune_offense_grants(
            [CONQUEROR], level=18, bonus_ad=250.0, ap=0.0, conqueror_stacks=6
        )
        self.assertAlmostEqual(half[0], full[0] / 2.0, places=9)
        self.assertGreater(full[0], 0.0)

    def test_the_knob_does_not_disturb_the_other_entries(self) -> None:
        # conqueror_stacks is Conqueror's gate alone - the Sorcery pair must be
        # untouched by it.
        for rid in (GATHERING_STORM, ABSOLUTE_FOCUS):
            with self.subTest(rune=rid):
                self.assertEqual(
                    rune_offense_grants(
                        [rid], level=18, bonus_ad=250.0, ap=0.0, game_minute=60.0
                    ),
                    rune_offense_grants(
                        [rid], level=18, bonus_ad=250.0, ap=0.0, game_minute=60.0,
                        conqueror_stacks=1,
                    ),
                )


class RegistryShapeTests(unittest.TestCase):
    """The registry is a seeded ALLOWLIST - the exclusions are the point."""

    def test_exactly_the_seeded_adaptive_stat_grants_are_present(self) -> None:
        # R155 added the non-adaptive attack-speed entry 9104 Legend: Alacrity
        # and R156 the census-driven adaptive entry 8316 Jack Of All Trades;
        # their own registry / column assertions live in
        # test_rune_offense_attack_speed_r155.py and
        # test_rune_offense_jack_of_all_trades_r156.py.
        self.assertEqual(
            set(_RUNE_OFFENSE_GRANTS),
            {
                GATHERING_STORM,
                ABSOLUTE_FOCUS,
                CONQUEROR,
                LEGEND_ALACRITY,
                JACK_OF_ALL_TRADES,
            },
        )

    def test_every_entry_declares_a_tree_and_a_unique_family(self) -> None:
        families = [e.family for e in _RUNE_OFFENSE_GRANTS.values()]
        self.assertTrue(all(families), "an empty family disables the dedup guard")
        self.assertEqual(len(families), len(set(families)))
        self.assertEqual(_RUNE_OFFENSE_GRANTS[CONQUEROR].tree, "Precision")

    def test_documented_exclusions_contribute_nothing(self) -> None:
        # Proc damage (already in rune_procs), ability haste (measured inert),
        # mana (a different axis), move speed (not an offensive stat), and the
        # uptime-blocked river rune.
        for rid in (
            ELECTROCUTE, TRANSCENDENCE, MANAFLOW_BAND, CELERITY, WATERWALKING,
        ):
            with self.subTest(rune=rid):
                self.assertEqual(
                    rune_offense_grants(
                        [rid], level=18, bonus_ad=200.0, ap=0.0, game_minute=60.0
                    ),
                    (0.0, 0.0, 0.0),
                )


class AdaptiveSideResolutionTests(unittest.TestCase):
    """One side pays out, chosen from the RESOLVED BUILD. AD wins ties."""

    def test_ad_build_takes_the_ad_column(self) -> None:
        ad, ap, _as = rune_offense_grants(
            [GATHERING_STORM], level=18, bonus_ad=250.0, ap=0.0, game_minute=30.0
        )
        self.assertAlmostEqual(ad, 29.0, places=9)
        self.assertAlmostEqual(ap, 0.0, places=9)

    def test_ap_build_takes_the_ap_column(self) -> None:
        ad, ap, _as = rune_offense_grants(
            [GATHERING_STORM], level=18, bonus_ad=0.0, ap=600.0, game_minute=30.0
        )
        self.assertAlmostEqual(ad, 0.0, places=9)
        self.assertAlmostEqual(ap, 48.0, places=9)

    def test_ad_wins_ties(self) -> None:
        # rune_procs._adaptive_coeff: "AD wins ties (League's adaptive force
        # defaults to AD when AD bonus >= AP bonus)".
        ad, ap, _as = rune_offense_grants(
            [GATHERING_STORM], level=18, bonus_ad=100.0, ap=100.0, game_minute=30.0
        )
        self.assertAlmostEqual(ad, 29.0, places=9)
        self.assertAlmostEqual(ap, 0.0, places=9)

    def test_both_runes_sum_on_the_chosen_side(self) -> None:
        ad, ap, _as = rune_offense_grants(
            [GATHERING_STORM, ABSOLUTE_FOCUS],
            level=18, bonus_ad=250.0, ap=0.0, game_minute=30.0,
        )
        self.assertAlmostEqual(ad, 29.0 + 18.0, places=9)
        self.assertAlmostEqual(ap, 0.0, places=9)

    def test_a_duplicated_id_cannot_double_credit(self) -> None:
        once = rune_offense_grants(
            [GATHERING_STORM], level=18, bonus_ad=250.0, ap=0.0, game_minute=60.0
        )
        twice = rune_offense_grants(
            [GATHERING_STORM, GATHERING_STORM, 8236],
            level=18, bonus_ad=250.0, ap=0.0, game_minute=60.0,
        )
        self.assertEqual(once, twice)
        self.assertAlmostEqual(once[0], 101.0, places=9)

    def test_integer_ids_are_coerced(self) -> None:
        self.assertEqual(
            rune_offense_grants(
                [8236], level=18, bonus_ad=250.0, ap=0.0, game_minute=30.0
            ),
            rune_offense_grants(
                ["8236"], level=18, bonus_ad=250.0, ap=0.0, game_minute=30.0
            ),
        )

    def test_default_game_minute_is_the_explicit_tunable_constant(self) -> None:
        # _ASSUMED_GAME_MINUTE is 15.0, which sits in the 10-minute decade.
        ad, _ap, _as = rune_offense_grants(
            [GATHERING_STORM], level=18, bonus_ad=250.0, ap=0.0
        )
        self.assertAlmostEqual(ad, 5.0, places=9)


class SeamDefaultOffTests(unittest.TestCase):
    """The seam is DEFAULT-OFF on every entry point that carries it."""

    _ENTRY_POINTS = (compute_dps, compute_hybrid, rank_items_by_hybrid)

    def test_flag_exists_and_defaults_false(self) -> None:
        for fn in self._ENTRY_POINTS:
            with self.subTest(fn=fn.__name__):
                params = inspect.signature(fn).parameters
                self.assertIn("apply_rune_offense_grants", params)
                self.assertIs(params["apply_rune_offense_grants"].default, False)

    def test_flag_rides_the_existing_rune_ids_transport(self) -> None:
        for fn in self._ENTRY_POINTS:
            with self.subTest(fn=fn.__name__):
                params = inspect.signature(fn).parameters
                self.assertIn("rune_ids", params)
                self.assertEqual(tuple(params["rune_ids"].default), ())


class ByteIdentityTests(unittest.TestCase):
    """With the flag OFF, a full rune page must not move a single number."""

    _RUNE_PAGE = [
        "8236", "8233", "8010", "8112", "8210", "8226", "8234", "8232",
    ]

    def test_compute_dps_absent_equals_explicit_off(self) -> None:
        absent = compute_dps(
            _snap(), champion_id="Jinx", level=13,
            item_ids=["3031", "3094"], mode="SR", target_armor=100.0,
        )
        off = compute_dps(
            _snap(), champion_id="Jinx", level=13,
            item_ids=["3031", "3094"], mode="SR", target_armor=100.0,
            apply_rune_offense_grants=False, rune_ids=self._RUNE_PAGE,
        )
        self.assertAlmostEqual(absent.weighted_dps, off.weighted_dps, places=12)
        self.assertGreater(absent.weighted_dps, 0.0, "fixture is not exercising")

    def test_compute_hybrid_absent_equals_explicit_off(self) -> None:
        absent = compute_hybrid(
            _snap(), champion_id="Jinx", level=13,
            item_ids=["3031", "3094"], mode="SR",
            target_armor=100.0, target_mr=100.0,
        )
        off = compute_hybrid(
            _snap(), champion_id="Jinx", level=13,
            item_ids=["3031", "3094"], mode="SR",
            target_armor=100.0, target_mr=100.0,
            apply_rune_offense_grants=False, rune_ids=self._RUNE_PAGE,
        )
        self.assertAlmostEqual(absent.hybrid_score, off.hybrid_score, places=12)
        self.assertAlmostEqual(absent.dps, off.dps, places=12)

    def test_rank_items_by_hybrid_absent_equals_explicit_off(self) -> None:
        def _ranked(**kw):
            res = rank_items_by_hybrid(
                _snap(), champion_id="Jinx", level=13,
                current_item_ids=["3031"], mode="SR", top_n=10, **kw,
            )
            return [(r.item_id, round(r.gold, 6)) for r in res.ranked]

        absent = _ranked()
        off = _ranked(apply_rune_offense_grants=False, rune_ids=self._RUNE_PAGE)
        self.assertEqual(absent, off)
        self.assertTrue(absent, "ranker returned no rows - fixture is not exercising")


class SeamOnRaisesDamageTests(unittest.TestCase):
    """Non-vacuous: with the flag ON the credited AD/AP must actually land."""

    def test_gathering_storm_raises_dps_for_an_ad_carry(self) -> None:
        base = compute_dps(
            _snap(), champion_id="Jinx", level=18,
            item_ids=["3031", "3094"], mode="SR", target_armor=100.0,
        )
        on = compute_dps(
            _snap(), champion_id="Jinx", level=18,
            item_ids=["3031", "3094"], mode="SR", target_armor=100.0,
            apply_rune_offense_grants=True, rune_ids=["8236", "8233"],
        )
        self.assertGreater(
            on.weighted_dps, base.weighted_dps,
            "the offense-grant seam credited no adaptive AD - the lane is inert",
        )

    def test_a_rune_page_without_a_seeded_id_is_inert_even_when_on(self) -> None:
        base = compute_dps(
            _snap(), champion_id="Jinx", level=18,
            item_ids=["3031", "3094"], mode="SR", target_armor=100.0,
        )
        on = compute_dps(
            _snap(), champion_id="Jinx", level=18,
            item_ids=["3031", "3094"], mode="SR", target_armor=100.0,
            apply_rune_offense_grants=True,
            rune_ids=[ELECTROCUTE, TRANSCENDENCE, MANAFLOW_BAND],
        )
        self.assertAlmostEqual(on.weighted_dps, base.weighted_dps, places=12)

    def test_hybrid_seam_on_raises_dps(self) -> None:
        base = compute_hybrid(
            _snap(), champion_id="Jinx", level=18,
            item_ids=["3031", "3094"], mode="SR",
            target_armor=100.0, target_mr=100.0,
        )
        on = compute_hybrid(
            _snap(), champion_id="Jinx", level=18,
            item_ids=["3031", "3094"], mode="SR",
            target_armor=100.0, target_mr=100.0,
            apply_rune_offense_grants=True, rune_ids=["8236", "8233"],
        )
        self.assertGreater(on.dps, base.dps)


class DivergenceFromRuneProcsIsDeliberateAndOneSidedTests(unittest.TestCase):
    """Two readings of Gathering Storm exist. Exactly ONE of them is reachable.

    ``rune_procs._gathering_storm`` reads the rune as a LINEAR ramp
    (``5.0 * t / 600``); this lane reads it as the feed's discrete STEP table.
    That is a real disagreement and it is pinned here rather than left implicit,
    because two live readings of one rune WOULD be a defect class.

    It is not two LIVE readings. ``rune_procs`` registers 8236 with
    ``proc_type="adaptive"`` and every consumer of that registry skips exactly
    that proc_type (``burst.py:1034``), so the linear value is computed and
    discarded on every path - it has never reached a score. This lane is the only
    reachable reading. R145 deliberately did NOT edit ``rune_procs`` for that
    reason: changing a shipped constant on the already-shipped burst path is not
    something a DEFAULT-OFF slice gets to do as a side effect.

    This test therefore pins BOTH facts, so neither can drift silently: the two
    readings differ, AND the rune_procs one is unreachable. If a future slice
    makes the burst consumer stop skipping "adaptive", this test goes RED and
    forces the reconciliation to be an explicit, evidenced decision.
    """

    def test_the_two_readings_genuinely_disagree_at_thirty_minutes(self) -> None:
        from agents.daemon_slayer.rune_procs import _gathering_storm

        linear = _gathering_storm(ad=250.0, ap=0.0, game_time_s=1800.0)
        step_ad, _step_ap = gathering_storm_step(30.0)
        # The feed's 30-minute row is 29 AD. The linear ramp yields 15.
        self.assertAlmostEqual(linear, 15.0, places=6)
        self.assertAlmostEqual(step_ad, 29.0, places=6)
        self.assertNotAlmostEqual(linear, step_ad, places=3)

    def test_the_rune_procs_reading_is_unreachable(self) -> None:
        # The guard on the claim above: 8236 is proc_type "adaptive", and that is
        # precisely what the burst consumer skips.
        from agents.daemon_slayer.rune_procs import RUNE_PROCS

        self.assertEqual(RUNE_PROCS[8236].proc_type, "adaptive")
        self.assertEqual(RUNE_PROCS[8233].proc_type, "adaptive")


class ConquerorAdaptiveSideResolutionTests(unittest.TestCase):
    """Conqueror pays ONE side, chosen from the RESOLVED BUILD. AD wins ties."""

    # 12 stacks at level 18: 48.0 Adaptive Force -> 48.0 AP or 28.8 AD.
    _AD_L18 = 28.8
    _AP_L18 = 48.0

    def test_ad_build_takes_the_ad_column(self) -> None:
        ad, ap, _as = rune_offense_grants(
            [CONQUEROR], level=18, bonus_ad=250.0, ap=0.0
        )
        self.assertAlmostEqual(ad, self._AD_L18, places=9)
        self.assertAlmostEqual(ap, 0.0, places=9)

    def test_ap_build_takes_the_ap_column(self) -> None:
        ad, ap, _as = rune_offense_grants(
            [CONQUEROR], level=18, bonus_ad=0.0, ap=600.0
        )
        self.assertAlmostEqual(ad, 0.0, places=9)
        self.assertAlmostEqual(ap, self._AP_L18, places=9)

    def test_ad_wins_ties(self) -> None:
        ad, ap, _as = rune_offense_grants(
            [CONQUEROR], level=18, bonus_ad=100.0, ap=100.0
        )
        self.assertAlmostEqual(ad, self._AD_L18, places=9)
        self.assertAlmostEqual(ap, 0.0, places=9)

    def test_exactly_one_side_is_ever_nonzero(self) -> None:
        for build_ad, build_ap, expected in (
            (250.0, 0.0, self._AD_L18),
            (0.0, 600.0, self._AP_L18),
            (100.0, 100.0, self._AD_L18),
        ):
            with self.subTest(bonus_ad=build_ad, ap=build_ap):
                ad, ap, _as = rune_offense_grants(
                    [CONQUEROR], level=18, bonus_ad=build_ad, ap=build_ap
                )
                self.assertEqual(min(ad, ap), 0.0)
                self.assertAlmostEqual(max(ad, ap), expected, places=9)

    def test_a_duplicated_id_cannot_double_credit(self) -> None:
        once = rune_offense_grants(
            [CONQUEROR], level=18, bonus_ad=250.0, ap=0.0
        )
        many = rune_offense_grants(
            [CONQUEROR, CONQUEROR, 8010, "8010"],
            level=18, bonus_ad=250.0, ap=0.0,
        )
        self.assertEqual(once, many)
        self.assertAlmostEqual(once[0], self._AD_L18, places=9)

    def test_it_is_game_clock_and_caster_health_independent(self) -> None:
        # Conqueror's gate is stack count, not the clock or caster HP - so unlike
        # its two registry siblings it must not move with either input.
        baseline = rune_offense_grants(
            [CONQUEROR], level=18, bonus_ad=250.0, ap=0.0
        )
        for minute, hp_pct in ((0.0, 1.0), (60.0, 1.0), (15.0, 0.05)):
            with self.subTest(game_minute=minute, caster_hp_pct=hp_pct):
                self.assertEqual(
                    rune_offense_grants(
                        [CONQUEROR], level=18, bonus_ad=250.0, ap=0.0,
                        game_minute=minute, caster_hp_pct=hp_pct,
                    ),
                    baseline,
                )

    def test_it_sums_with_the_other_families_on_the_chosen_side(self) -> None:
        ad, ap, _as = rune_offense_grants(
            [CONQUEROR, GATHERING_STORM, ABSOLUTE_FOCUS],
            level=18, bonus_ad=250.0, ap=0.0, game_minute=30.0,
        )
        self.assertAlmostEqual(ad, self._AD_L18 + 29.0 + 18.0, places=9)
        self.assertAlmostEqual(ap, 0.0, places=9)


class ConquerorSeamTests(unittest.TestCase):
    """DEFAULT-OFF inertness, then a non-vacuous ON check."""

    _ITEMS = ["3031", "3094"]

    def _dps(self, **kw):
        return compute_dps(
            _snap(), champion_id="Jinx", level=18,
            item_ids=self._ITEMS, mode="SR", target_armor=100.0, **kw,
        )

    def test_flag_off_with_conqueror_is_byte_identical_to_no_rune_ids(self) -> None:
        absent = self._dps()
        off = self._dps(apply_rune_offense_grants=False, rune_ids=[CONQUEROR])
        self.assertAlmostEqual(absent.weighted_dps, off.weighted_dps, places=12)
        self.assertGreater(absent.weighted_dps, 0.0, "fixture is not exercising")

    def test_flag_on_with_conqueror_raises_dps(self) -> None:
        base = self._dps()
        on = self._dps(apply_rune_offense_grants=True, rune_ids=[CONQUEROR])
        self.assertGreater(
            on.weighted_dps, base.weighted_dps,
            "Conqueror credited no adaptive AD - the entry is inert",
        )


class RuneItemIdKeyspaceCollisionTests(unittest.TestCase):
    """8010 is Conqueror in the RUNE keyspace and Bloodletter's Curse in the ITEM one.

    The two keyspaces are disjoint by transport, not by value: this registry is
    reachable only through ``rune_ids``, and ``item_ids`` never touches it. That
    is asserted here rather than assumed, because the shared literal is exactly
    the kind of collision a future refactor could merge by accident.
    """

    # Every rune key that is ALSO a live item key. 8010 is the first and, as of
    # this slice, only one. Pinned as an exact set so a future entry that
    # collides with the item keyspace goes RED and has to be looked at, while the
    # one known collision stays documented rather than silently tolerated.
    _KNOWN_KEYSPACE_OVERLAP = {"8010"}

    def test_the_collision_is_real_and_pinned(self) -> None:
        self.assertIn("8010", _RUNE_OFFENSE_GRANTS)
        self.assertEqual(_RUNE_OFFENSE_GRANTS["8010"].name, "Conqueror")
        self.assertIn("8010", ITEM_EFFECTS)
        self.assertEqual(ITEM_EFFECTS["8010"].name, "Bloodletter's Curse")

    def test_no_undocumented_rune_key_collides_with_the_item_keyspace(self) -> None:
        overlap = set(_RUNE_OFFENSE_GRANTS) & set(ITEM_EFFECTS)
        self.assertEqual(
            overlap,
            self._KNOWN_KEYSPACE_OVERLAP,
            "a rune id now collides with an item id undocumented - confirm the "
            "rune_ids transport still keeps the two keyspaces apart",
        )

    def test_the_item_8010_cannot_reach_the_rune_registry(self) -> None:
        # Buying Bloodletter's Curse must not silently grant Conqueror's force,
        # even with the seam explicitly ON and no runes supplied at all.
        def _dps(**kw):
            return compute_dps(
                _snap(), champion_id="Jinx", level=18,
                item_ids=["3031", "8010"], mode="SR", target_armor=100.0, **kw,
            )

        off = _dps()
        on_no_runes = _dps(apply_rune_offense_grants=True, rune_ids=[])
        self.assertAlmostEqual(off.weighted_dps, on_no_runes.weighted_dps, places=12)
        self.assertGreater(off.weighted_dps, 0.0, "fixture is not exercising")

    def test_the_rune_8010_is_not_reduced_to_an_item_lookup(self) -> None:
        # The converse direction: an item id that is NOT a rune contributes
        # nothing, so the registry is keyed on runes and never falls back to
        # items. 3031 Infinity Edge is an item id with no rune counterpart.
        self.assertNotIn("3031", _RUNE_OFFENSE_GRANTS)
        self.assertEqual(
            rune_offense_grants(["3031"], level=18, bonus_ad=250.0, ap=0.0),
            (0.0, 0.0, 0.0),
        )
        self.assertNotEqual(
            rune_offense_grants([CONQUEROR], level=18, bonus_ad=250.0, ap=0.0),
            (0.0, 0.0, 0.0),
        )

    def test_every_call_site_feeds_the_registry_rune_ids_never_item_ids(self) -> None:
        # Source-level guard: the transport separation is the whole defense, so
        # it is checked structurally rather than only behaviourally.
        pkg = pathlib.Path(inspect.getsourcefile(compute_dps)).parent
        call_sites = 0
        for path in sorted(pkg.glob("*.py")):
            src = path.read_text(encoding="utf-8")
            if "rune_offense_grants(" not in src:
                continue
            for node in ast.walk(ast.parse(src)):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if not isinstance(func, ast.Name) or func.id != "rune_offense_grants":
                    continue
                call_sites += 1
                first = ast.get_source_segment(src, node.args[0]) if node.args else ""
                kwargs = {kw.arg for kw in node.keywords}
                with self.subTest(file=path.name, line=node.lineno):
                    self.assertIn("rune_ids", first or "")
                    self.assertNotIn("item_ids", first or "")
                    self.assertNotIn("item_ids", kwargs)
        self.assertGreater(call_sites, 0, "found no call site to guard")


class EngineVersionTests(unittest.TestCase):
    def test_engine_version_pin(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.257.0")


if __name__ == "__main__":
    unittest.main()
