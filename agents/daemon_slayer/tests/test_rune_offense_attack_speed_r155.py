"""R155: Legend: Alacrity 9104 - the rune ATTACK SPEED column.

The R145 ``_rune_offense_grants`` registry credited a rune-granted ADAPTIVE
stat (AD or AP, one side chosen by the resolved build). Legend: Alacrity grants
neither: it grants ATTACK SPEED, unconditionally, to an AD build and an AP build
alike. So the registry gains a THIRD column and 9104 becomes its first
occupant. 9104 was credited NOWHERE in the engine before this slice - not in
``rune_procs.RUNE_PROCS``, not in ``enemy_runes``, not in any ``_rune_*``
registry.

Three ways to get this wrong, each pinned below:

  * UNITS. ``stats["as"]`` is FINAL attacks/sec (``engine.py:196`` resolves it
    as ``base_as * (1 + bonus)``), and the rune's number is a bonus-AS FRACTION.
    The fold must be ``innate_base_as * fraction``; adding the raw fraction
    over-credits by ``1 / base_as``. Same unit bug the R42 cond_as and R7
    passive_as guards exist for, and the same colinear-calibration proof shape.
  * ADAPTIVE BLEED. The registry's other three entries pay ONE side by
    ``prefer_ad``. Attack speed has no sides, so the third column must bypass
    that branch entirely and must never move the AD/AP columns.
  * ATTACK-SPEED-LOCK CHAMPIONS. ``engine.py:439`` zeroes ``as_pct`` for a
    champion carrying an ``as_lock_entry`` with ``locks_as`` (Jhin's Whisper).
    A rune AS fold in ``dps.py`` happens DOWNSTREAM of that zeroing, so without
    a gate it would hand an AS-locked champion attack speed they cannot have.

OFFLINE ONLY: no live :8893, no network.
"""
from __future__ import annotations

import unittest
from unittest import mock

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer._passive_as_lock_overrides import as_lock_entry
from agents.daemon_slayer._rune_offense_grants import (
    _ASSUMED_LEGEND_STACKS,
    _LEGEND_ALACRITY_AS_PER_STACK,
    _LEGEND_ALACRITY_BASE_AS,
    _LEGEND_MAX_STACKS,
    _RUNE_OFFENSE_GRANTS,
    legend_alacrity_grant,
    rune_offense_grants,
)
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps

LEGEND_ALACRITY = "9104"
# Read and rejected in the same feed slot - see the module docstring exclusions.
LEGEND_HASTE = "9105"
LEGEND_BLOODLINE = "9103"
# Seeded in R156, but adaptive - it never touches the attack-speed column, and
# with no census supplied it grants nothing at all. Kept in this file's fixtures
# as a control that the third column stays its own lane.
JACK_OF_ALL_TRADES = "8316"
# The three R145 adaptive entries, used to prove the columns stay independent.
GATHERING_STORM = "8236"
ABSOLUTE_FOCUS = "8233"
CONQUEROR = "8010"

# A real, non-empty build. An empty ``item_ids`` is a known probe artifact in
# this repo and is never used as a fixture here.
_ITEMS = ["3031", "3094"]        # Infinity Edge + Rapid Firecannon
_DAGGER = "1042"                 # pure +AS, the colinear calibration point

_SNAP = None


def _snap() -> DataSnapshot:
    global _SNAP
    if _SNAP is None:
        _SNAP = DataSnapshot.load()
    return _SNAP


def _base_as(champion_id: str) -> float:
    return float(
        (_snap().champion(champion_id).get("stats") or {}).get("attackspeed", 0.0)
    )


class LegendAlacrityMagnitudeTests(unittest.TestCase):
    """The feed's own arithmetic: 3% base plus 1.5% per stack, max 10 stacks."""

    def test_zero_stacks_is_the_base_grant_alone(self) -> None:
        self.assertAlmostEqual(legend_alacrity_grant(0), 0.03, places=12)

    def test_max_stacks_is_the_feed_cap_value(self) -> None:
        self.assertAlmostEqual(legend_alacrity_grant(10), 0.18, places=12)

    def test_the_constants_reproduce_the_endpoints(self) -> None:
        self.assertAlmostEqual(_LEGEND_ALACRITY_BASE_AS, 0.03, places=12)
        self.assertAlmostEqual(_LEGEND_ALACRITY_AS_PER_STACK, 0.015, places=12)
        self.assertAlmostEqual(_LEGEND_MAX_STACKS, 10.0, places=12)
        self.assertAlmostEqual(
            _LEGEND_ALACRITY_BASE_AS
            + _LEGEND_MAX_STACKS * _LEGEND_ALACRITY_AS_PER_STACK,
            0.18,
            places=12,
        )

    def test_it_is_linear_between_the_endpoints(self) -> None:
        for stacks in range(0, 11):
            with self.subTest(stacks=stacks):
                self.assertAlmostEqual(
                    legend_alacrity_grant(stacks),
                    0.03 + 0.015 * stacks,
                    places=12,
                )

    def test_it_clamps_above_the_feed_cap(self) -> None:
        self.assertAlmostEqual(
            legend_alacrity_grant(99), legend_alacrity_grant(10), places=12
        )

    def test_it_clamps_below_zero(self) -> None:
        self.assertAlmostEqual(
            legend_alacrity_grant(-5), legend_alacrity_grant(0), places=12
        )

    def test_the_default_stack_count_is_the_explicit_knob(self) -> None:
        # A KNOB, not a constant - same doctrine as _ASSUMED_CONQUEROR_STACKS.
        self.assertAlmostEqual(_ASSUMED_LEGEND_STACKS, 10.0, places=12)
        self.assertAlmostEqual(
            legend_alacrity_grant(None),
            legend_alacrity_grant(_ASSUMED_LEGEND_STACKS),
            places=12,
        )

    def test_a_junk_stack_count_falls_back_to_the_default(self) -> None:
        self.assertAlmostEqual(
            legend_alacrity_grant("many"), legend_alacrity_grant(None), places=12
        )


class ThirdColumnTests(unittest.TestCase):
    """``rune_offense_grants`` returns ``(ad, ap, attack_speed_fraction)``."""

    def test_the_return_is_three_columns(self) -> None:
        out = rune_offense_grants(
            [LEGEND_ALACRITY], level=18, bonus_ad=250.0, ap=0.0
        )
        self.assertEqual(len(out), 3)

    def test_alacrity_pays_only_the_attack_speed_column(self) -> None:
        ad, ap, as_frac = rune_offense_grants(
            [LEGEND_ALACRITY], level=18, bonus_ad=250.0, ap=0.0
        )
        self.assertAlmostEqual(ad, 0.0, places=12)
        self.assertAlmostEqual(ap, 0.0, places=12)
        self.assertAlmostEqual(as_frac, 0.18, places=12)

    def test_it_is_not_adaptive_ad_and_ap_builds_get_the_same_grant(self) -> None:
        # The whole point of the third column: prefer_ad must not reach it.
        ad_build = rune_offense_grants(
            [LEGEND_ALACRITY], level=18, bonus_ad=250.0, ap=0.0
        )
        ap_build = rune_offense_grants(
            [LEGEND_ALACRITY], level=18, bonus_ad=0.0, ap=600.0
        )
        tie_build = rune_offense_grants(
            [LEGEND_ALACRITY], level=18, bonus_ad=100.0, ap=100.0
        )
        self.assertEqual(ad_build, ap_build)
        self.assertEqual(ad_build, tie_build)
        self.assertAlmostEqual(ad_build[2], 0.18, places=12)

    def test_the_adaptive_entries_pay_no_attack_speed(self) -> None:
        for rid in (GATHERING_STORM, ABSOLUTE_FOCUS, CONQUEROR):
            with self.subTest(rune=rid):
                _ad, _ap, as_frac = rune_offense_grants(
                    [rid], level=18, bonus_ad=250.0, ap=0.0, game_minute=60.0
                )
                self.assertAlmostEqual(as_frac, 0.0, places=12)

    def test_alacrity_does_not_disturb_the_adaptive_columns(self) -> None:
        without = rune_offense_grants(
            [GATHERING_STORM, CONQUEROR],
            level=18, bonus_ad=250.0, ap=0.0, game_minute=30.0,
        )
        with_alacrity = rune_offense_grants(
            [GATHERING_STORM, CONQUEROR, LEGEND_ALACRITY],
            level=18, bonus_ad=250.0, ap=0.0, game_minute=30.0,
        )
        self.assertAlmostEqual(with_alacrity[0], without[0], places=12)
        self.assertAlmostEqual(with_alacrity[1], without[1], places=12)
        self.assertAlmostEqual(with_alacrity[2], 0.18, places=12)
        self.assertGreater(without[0], 0.0, "fixture is not exercising")

    def test_a_duplicated_id_cannot_double_credit_attack_speed(self) -> None:
        once = rune_offense_grants(
            [LEGEND_ALACRITY], level=18, bonus_ad=250.0, ap=0.0
        )
        many = rune_offense_grants(
            [LEGEND_ALACRITY, LEGEND_ALACRITY, 9104],
            level=18, bonus_ad=250.0, ap=0.0,
        )
        self.assertEqual(once, many)

    def test_the_per_call_stack_override_reaches_the_registry(self) -> None:
        zero = rune_offense_grants(
            [LEGEND_ALACRITY], level=18, bonus_ad=250.0, ap=0.0, legend_stacks=0
        )
        self.assertAlmostEqual(zero[2], 0.03, places=12)

    def test_the_stack_knob_does_not_disturb_the_other_entries(self) -> None:
        for rid in (GATHERING_STORM, ABSOLUTE_FOCUS, CONQUEROR):
            with self.subTest(rune=rid):
                self.assertEqual(
                    rune_offense_grants(
                        [rid], level=18, bonus_ad=250.0, ap=0.0, game_minute=60.0
                    ),
                    rune_offense_grants(
                        [rid], level=18, bonus_ad=250.0, ap=0.0,
                        game_minute=60.0, legend_stacks=0,
                    ),
                )

    def test_the_registry_carries_alacrity_with_its_own_family(self) -> None:
        self.assertIn(LEGEND_ALACRITY, _RUNE_OFFENSE_GRANTS)
        entry = _RUNE_OFFENSE_GRANTS[LEGEND_ALACRITY]
        self.assertEqual(entry.name, "Legend: Alacrity")
        self.assertEqual(entry.tree, "Precision")
        families = [e.family for e in _RUNE_OFFENSE_GRANTS.values()]
        self.assertTrue(all(families), "an empty family disables the dedup guard")
        self.assertEqual(len(families), len(set(families)))

    def test_the_documented_legend_exclusions_contribute_nothing(self) -> None:
        # 9105 is ability haste (MEASURED INERT as a DS axis, settled); 9103 is
        # life steal + max health (the sustain / EHP lane). Both are permanent
        # exclusions, not pending work.
        for rid in (LEGEND_HASTE, LEGEND_BLOODLINE):
            with self.subTest(rune=rid):
                self.assertNotIn(rid, _RUNE_OFFENSE_GRANTS)
                self.assertEqual(
                    rune_offense_grants(
                        [rid], level=18, bonus_ad=250.0, ap=0.0
                    ),
                    (0.0, 0.0, 0.0),
                )

    def test_the_jack_exclusion_was_lifted_in_r156(self) -> None:
        # R155 recorded 8316 as a MEASURED FUTURE blocked on a distinct
        # item-stat census. R156 built that census, so the rune is seeded - but
        # it stays inert to THIS lane: it is adaptive, so its attack-speed
        # column is zero, and with no census supplied it grants nothing at all.
        self.assertIn(JACK_OF_ALL_TRADES, _RUNE_OFFENSE_GRANTS)
        self.assertEqual(
            rune_offense_grants(
                [JACK_OF_ALL_TRADES], level=18, bonus_ad=250.0, ap=0.0
            ),
            (0.0, 0.0, 0.0),
        )
        _ad, _ap, as_frac = rune_offense_grants(
            [JACK_OF_ALL_TRADES],
            level=18, bonus_ad=250.0, ap=0.0, jack_stacks=10,
        )
        self.assertAlmostEqual(as_frac, 0.0, places=12)


class SeamDefaultOffTests(unittest.TestCase):
    """DEFAULT-OFF must be byte-identical even with 9104 in ``rune_ids``."""

    def _dps(self, **kw):
        return compute_dps(
            _snap(), champion_id="Caitlyn", level=11,
            item_ids=_ITEMS, mode="SR", target_armor=80.0, **kw,
        )

    def test_absent_equals_explicit_off_with_alacrity_supplied(self) -> None:
        absent = self._dps()
        off = self._dps(
            apply_rune_offense_grants=False, rune_ids=[LEGEND_ALACRITY]
        )
        self.assertAlmostEqual(absent.weighted_dps, off.weighted_dps, places=12)
        self.assertAlmostEqual(absent.stats["as"], off.stats["as"], places=12)
        self.assertGreater(absent.weighted_dps, 0.0, "fixture is not exercising")

    def test_off_is_identical_for_a_full_precision_page(self) -> None:
        page = [CONQUEROR, LEGEND_ALACRITY, LEGEND_HASTE, LEGEND_BLOODLINE]
        absent = self._dps()
        off = self._dps(apply_rune_offense_grants=False, rune_ids=page)
        self.assertAlmostEqual(absent.weighted_dps, off.weighted_dps, places=12)


class SeamOnMovesDpsTests(unittest.TestCase):
    """Non-vacuous: with the flag ON the AS grant must actually land."""

    def _dps(self, items=None, **kw):
        return compute_dps(
            _snap(), champion_id="Caitlyn", level=11,
            item_ids=list(items or _ITEMS), mode="SR", target_armor=80.0, **kw,
        )

    def test_alacrity_raises_weighted_dps(self) -> None:
        off = self._dps(apply_rune_offense_grants=True, rune_ids=[])
        on = self._dps(
            apply_rune_offense_grants=True, rune_ids=[LEGEND_ALACRITY]
        )
        self.assertGreater(
            on.weighted_dps, off.weighted_dps,
            "the attack-speed column credited nothing - the lane is inert",
        )

    def test_the_fold_uses_base_as_scaled_fraction_not_the_raw_fraction(self) -> None:
        # weighted_dps is affine in rotation AS (see the R42 cond_as guard), so
        # a pure-AS calibration item gives the slope and the fold's magnitude is
        # decidable numerically rather than by sign alone.
        off = self._dps(apply_rune_offense_grants=True, rune_ids=[])
        cal = self._dps(
            items=_ITEMS + [_DAGGER],
            apply_rune_offense_grants=True, rune_ids=[],
        )
        on = self._dps(
            apply_rune_offense_grants=True, rune_ids=[LEGEND_ALACRITY]
        )
        a0 = off.stats["as"]
        a_cal = cal.stats["as"]
        base_as = _base_as("Caitlyn")
        frac = legend_alacrity_grant(None)
        # Preconditions - fail loudly if the fixture stops exercising the path.
        self.assertGreater(base_as, 0.0)
        self.assertLess(base_as, 1.0, "base AS < 1 so the unit bug is large")
        self.assertGreater(a_cal, a0, "Dagger did not raise AS")
        self.assertLess(a0 + base_as * frac, 2.5, "fixture must stay under cap")
        c1 = (cal.weighted_dps - off.weighted_dps) / (a_cal - a0)
        predicted_correct = off.weighted_dps + c1 * (base_as * frac)
        predicted_wrong = off.weighted_dps + c1 * frac
        self.assertAlmostEqual(
            on.weighted_dps, predicted_correct,
            delta=abs(predicted_correct) * 0.005,
        )
        self.assertLess(
            abs(on.weighted_dps - predicted_correct),
            abs(on.weighted_dps - predicted_wrong),
            "the fold added the raw fraction instead of base_as * fraction",
        )

    def test_the_two_and_a_half_attack_speed_cap_is_re_clamped(self) -> None:
        # Two absurd AS fractions both clamp to the same 2.5 ceiling, so the
        # rotation DPS must be identical between them and strictly above the
        # real-magnitude grant.
        real = self._dps(
            apply_rune_offense_grants=True, rune_ids=[LEGEND_ALACRITY]
        )
        with mock.patch(
            "agents.daemon_slayer.dps.rune_offense_grants",
            return_value=(0.0, 0.0, 50.0),
        ):
            huge = self._dps(
                apply_rune_offense_grants=True, rune_ids=[LEGEND_ALACRITY]
            )
        with mock.patch(
            "agents.daemon_slayer.dps.rune_offense_grants",
            return_value=(0.0, 0.0, 100.0),
        ):
            huger = self._dps(
                apply_rune_offense_grants=True, rune_ids=[LEGEND_ALACRITY]
            )
        self.assertAlmostEqual(huge.weighted_dps, huger.weighted_dps, places=9)
        self.assertGreater(huge.weighted_dps, real.weighted_dps)

    def test_a_page_without_alacrity_is_inert_even_when_on(self) -> None:
        off = self._dps(apply_rune_offense_grants=True, rune_ids=[])
        on = self._dps(
            apply_rune_offense_grants=True,
            rune_ids=[LEGEND_HASTE, LEGEND_BLOODLINE, JACK_OF_ALL_TRADES],
        )
        self.assertAlmostEqual(on.weighted_dps, off.weighted_dps, places=12)


class AttackSpeedLockGateTests(unittest.TestCase):
    """An AS-locked champion must receive ZERO rune attack speed.

    ``engine.py:439`` zeroes ``item_totals["as_pct"]`` for a locked champion
    (Jhin's Whisper converts would-be attack speed into AD). The ``dps.py`` rune
    fold runs AFTER that zeroing, so it must re-check the lock. Granting zero is
    a deliberately CONSERVATIVE recorded limitation: the ``ad_per_bonus_as``
    conversion is NOT applied here, because the override table was authored
    against item attack speed and applying it to a rune would be inventing a
    magnitude.
    """

    _LOCKED = "Jhin"
    _ITEMS = ["3031", "3094"]

    def test_the_override_table_really_locks_the_fixture_champion(self) -> None:
        entry = as_lock_entry(self._LOCKED)
        self.assertIsNotNone(entry, "fixture champion is no longer AS-locked")
        self.assertTrue(entry.locks_as)

    def test_a_locked_champion_gets_no_rune_attack_speed(self) -> None:
        def _dps(**kw):
            return compute_dps(
                _snap(), champion_id=self._LOCKED, level=11,
                item_ids=self._ITEMS, mode="SR", target_armor=80.0, **kw,
            )

        off = _dps(apply_rune_offense_grants=True, rune_ids=[])
        on = _dps(apply_rune_offense_grants=True, rune_ids=[LEGEND_ALACRITY])
        self.assertAlmostEqual(on.weighted_dps, off.weighted_dps, places=12)
        self.assertGreater(off.weighted_dps, 0.0, "fixture is not exercising")

    def test_an_unlocked_champion_of_the_same_class_does_move(self) -> None:
        # The negative control: the gate must be the LOCK, not a dead lane.
        self.assertIsNone(as_lock_entry("Caitlyn"))

        def _dps(**kw):
            return compute_dps(
                _snap(), champion_id="Caitlyn", level=11,
                item_ids=self._ITEMS, mode="SR", target_armor=80.0, **kw,
            )

        off = _dps(apply_rune_offense_grants=True, rune_ids=[])
        on = _dps(apply_rune_offense_grants=True, rune_ids=[LEGEND_ALACRITY])
        self.assertGreater(on.weighted_dps, off.weighted_dps)


class EngineVersionTests(unittest.TestCase):
    def test_engine_version_pin(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.257.0")


if __name__ == "__main__":
    unittest.main()
