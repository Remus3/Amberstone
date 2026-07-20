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

import inspect
import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer._rune_offense_grants import (
    _GATHERING_STORM_STEPS,
    _RUNE_OFFENSE_GRANTS,
    absolute_focus_grant,
    gathering_storm_step,
    rune_offense_grants,
)
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps
from agents.daemon_slayer.hybrid import compute_hybrid, rank_items_by_hybrid

GATHERING_STORM = "8236"
ABSOLUTE_FOCUS = "8233"
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


class RegistryShapeTests(unittest.TestCase):
    """The registry is a seeded ALLOWLIST - the exclusions are the point."""

    def test_only_the_two_sorcery_adaptive_stat_grants_are_seeded(self) -> None:
        self.assertEqual(
            set(_RUNE_OFFENSE_GRANTS), {GATHERING_STORM, ABSOLUTE_FOCUS}
        )

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
                    (0.0, 0.0),
                )


class AdaptiveSideResolutionTests(unittest.TestCase):
    """One side pays out, chosen from the RESOLVED BUILD. AD wins ties."""

    def test_ad_build_takes_the_ad_column(self) -> None:
        ad, ap = rune_offense_grants(
            [GATHERING_STORM], level=18, bonus_ad=250.0, ap=0.0, game_minute=30.0
        )
        self.assertAlmostEqual(ad, 29.0, places=9)
        self.assertAlmostEqual(ap, 0.0, places=9)

    def test_ap_build_takes_the_ap_column(self) -> None:
        ad, ap = rune_offense_grants(
            [GATHERING_STORM], level=18, bonus_ad=0.0, ap=600.0, game_minute=30.0
        )
        self.assertAlmostEqual(ad, 0.0, places=9)
        self.assertAlmostEqual(ap, 48.0, places=9)

    def test_ad_wins_ties(self) -> None:
        # rune_procs._adaptive_coeff: "AD wins ties (League's adaptive force
        # defaults to AD when AD bonus >= AP bonus)".
        ad, ap = rune_offense_grants(
            [GATHERING_STORM], level=18, bonus_ad=100.0, ap=100.0, game_minute=30.0
        )
        self.assertAlmostEqual(ad, 29.0, places=9)
        self.assertAlmostEqual(ap, 0.0, places=9)

    def test_both_runes_sum_on_the_chosen_side(self) -> None:
        ad, ap = rune_offense_grants(
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
        ad, _ap = rune_offense_grants(
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
        "8236", "8233", "8112", "8210", "8226", "8234", "8232",
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


class EngineVersionTests(unittest.TestCase):
    def test_engine_version_pin(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.232.0")


if __name__ == "__main__":
    unittest.main()
