"""R156: Jack Of All Trades 8316 - the distinct-item-stat census.

R155 recorded 8316 as a MEASURED FUTURE in the ``_rune_offense_grants``
DELIBERATE EXCLUSIONS block: a real, exactly-quantified Adaptive Force grant
whose stack count is a census of DISTINCT STAT TYPES across the resolved build,
with no such per-build decomposition available. That decomposition does exist -
``stats.aggregate_item_stats`` already maps every DDragon item stat key onto a
canonical ``{axis}_{flat|pct}`` slot, and ``engine.py:318-320`` is the exact
shape a resolved build uses to produce it. This slice builds the census on top
of that and credits the rune.

DDragon 16.14.1 longDesc, verbatim (tags stripped): "For each different stat
gained from items, gain one Jack stack. Each stack grants you 1 Ability
Haste.<br><br>Gain 10 or 25 bonus Adaptive Force at 5 and 10 stacks,
respectively."

Four ways to get this wrong, each pinned below:

  * A RAMP INSTEAD OF A STEP. "10 or 25 ... at 5 and 10 stacks, respectively"
    is two discrete tiers, not a per-stack accrual. Nothing is granted below 5
    stacks, and 7 stacks pays exactly what 5 stacks pays.
  * SUMMING THE TIERS. The higher tier REPLACES the lower one (25 total at 10
    stacks, not 10 + 25 = 35). "10 or 25" is a disjunction in the feed's own
    words.
  * DOUBLE-COUNTING AN AXIS. Movement speed reaches the census through TWO
    DDragon keys (``FlatMovementSpeedMod`` + ``PercentMovementSpeedMod``) and
    lands in two canonical slots (``ms_flat`` + ``ms_pct``). It is ONE different
    stat, so it must contribute ONE stack.
  * CREDITING THE ABILITY HASTE HALF. "Each stack grants you 1 Ability Haste"
    is real but Ability Haste as a DS axis was MEASURED INERT and is settled.
    Only the Adaptive Force half is credited here, and only the adaptive
    columns move - the R155 attack-speed column stays at zero.

OFFLINE ONLY: no live :8860, no network.
"""
from __future__ import annotations

import unittest
from unittest import mock

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer._rune_offense_grants import (
    _ADAPTIVE_FORCE_AD_PER_AF,
    _JACK_AF_AT_HIGH_TIER,
    _JACK_AF_AT_LOW_TIER,
    _JACK_HIGH_TIER_STACKS,
    _JACK_LOW_TIER_STACKS,
    _JACK_MAX_STACKS,
    _RUNE_OFFENSE_GRANTS,
    jack_of_all_trades_grant,
    jack_of_all_trades_stacks,
    rune_offense_grants,
)
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps
from agents.daemon_slayer.stats import aggregate_item_stats

JACK_OF_ALL_TRADES = "8316"
LEGEND_ALACRITY = "9104"
GATHERING_STORM = "8236"
ABSOLUTE_FOCUS = "8233"
CONQUEROR = "8010"

# A real six-item AD build whose census is exactly 5 distinct axes (ad, as,
# crit, lifesteal, ms) - the feed's LOW tier. An empty ``item_ids`` is a known
# probe artifact in this repo and is never used as a fixture here.
_AD_SIX = ["3031", "3094", "3006", "3072", "3036", "3046"]
# Two items only: ad, as, crit, ms = 4 axes, one short of the low tier. The
# negative control that proves the gate is the CENSUS and not a dead lane.
_AD_TWO = ["3031", "3094"]

_SNAP = None


def _snap() -> DataSnapshot:
    global _SNAP
    if _SNAP is None:
        _SNAP = DataSnapshot.load()
    return _SNAP


def _blocks(item_ids) -> list:
    return [_snap().item(i).get("stats", {}) for i in item_ids]


class JackStepFunctionTests(unittest.TestCase):
    """Two discrete tiers, the higher REPLACING the lower - never a ramp."""

    def test_below_the_low_tier_is_zero(self) -> None:
        for stacks in (0, 1, 2, 3, 4):
            with self.subTest(stacks=stacks):
                self.assertEqual(jack_of_all_trades_grant(stacks), (0.0, 0.0))

    def test_the_low_tier_pays_ten_adaptive_force(self) -> None:
        ad, ap = jack_of_all_trades_grant(5)
        self.assertAlmostEqual(ap, 10.0, places=12)
        self.assertAlmostEqual(ad, 6.0, places=12)

    def test_the_high_tier_pays_twenty_five_adaptive_force(self) -> None:
        ad, ap = jack_of_all_trades_grant(10)
        self.assertAlmostEqual(ap, 25.0, places=12)
        self.assertAlmostEqual(ad, 15.0, places=12)

    def test_the_tiers_are_not_summed(self) -> None:
        # "10 or 25" is a disjunction: the high tier is 25 total, not 35.
        _ad, ap = jack_of_all_trades_grant(10)
        self.assertAlmostEqual(
            ap, _JACK_AF_AT_HIGH_TIER, places=12,
        )
        self.assertNotAlmostEqual(
            ap, _JACK_AF_AT_LOW_TIER + _JACK_AF_AT_HIGH_TIER, places=6,
        )

    def test_it_is_flat_inside_a_tier_not_a_ramp(self) -> None:
        low = jack_of_all_trades_grant(5)
        for stacks in (6, 7, 8, 9):
            with self.subTest(stacks=stacks):
                self.assertEqual(jack_of_all_trades_grant(stacks), low)

    def test_the_conversion_is_the_registry_adaptive_force_ratio(self) -> None:
        for stacks, af in (
            (_JACK_LOW_TIER_STACKS, _JACK_AF_AT_LOW_TIER),
            (_JACK_HIGH_TIER_STACKS, _JACK_AF_AT_HIGH_TIER),
        ):
            with self.subTest(stacks=stacks):
                ad, ap = jack_of_all_trades_grant(stacks)
                self.assertAlmostEqual(ap, af, places=12)
                self.assertAlmostEqual(
                    ad, _ADAPTIVE_FORCE_AD_PER_AF * af, places=12
                )

    def test_it_clamps_above_the_feed_cap(self) -> None:
        self.assertEqual(
            jack_of_all_trades_grant(99), jack_of_all_trades_grant(10)
        )

    def test_it_clamps_below_zero(self) -> None:
        self.assertEqual(jack_of_all_trades_grant(-5), (0.0, 0.0))

    def test_a_junk_stack_count_is_fail_soft(self) -> None:
        """The junk values are the test - only the subTest LABEL is repr'd.

        MEASURED 2026-07-26: a bare object() passed as a subTest kwarg fails
        under `pytest -n` and only under `-n`. pytest 9 puts the raw kwargs in
        the report and emits one for every subtest, and execnet serializes only
        builtins, so subTest.__exit__ raises DumpError and fails the PARENT
        test. Serially there is no channel and the same matrix passes. Three
        sibling instances in tests/ were mislabelled "xdist shared-state" for
        months on that asymmetry; this is the fourth, found by enumerating the
        defect class rather than by hitting it.
        """
        for junk in ("many", None, object()):
            with self.subTest(junk=repr(junk)):
                self.assertEqual(jack_of_all_trades_grant(junk), (0.0, 0.0))


class JackCensusTests(unittest.TestCase):
    """The stack count is the engine's OWN distinct-axis census."""

    def test_the_six_item_ad_build_censuses_five_axes(self) -> None:
        totals = aggregate_item_stats(_blocks(_AD_SIX))
        axes = {slot.rsplit("_", 1)[0] for slot in totals}
        self.assertEqual(axes, {"ad", "as", "crit", "lifesteal", "ms"})
        self.assertAlmostEqual(
            jack_of_all_trades_stacks(_blocks(_AD_SIX)), 5.0, places=12
        )

    def test_the_two_item_build_is_one_stack_short_of_the_tier(self) -> None:
        self.assertAlmostEqual(
            jack_of_all_trades_stacks(_blocks(_AD_TWO)), 4.0, places=12
        )
        self.assertEqual(jack_of_all_trades_grant(4), (0.0, 0.0))

    def test_a_flat_and_pct_pair_on_one_axis_counts_once(self) -> None:
        # Movement speed arrives through two DDragon keys and two canonical
        # slots, but it is ONE different stat.
        pair = [{"FlatMovementSpeedMod": 45.0}, {"PercentMovementSpeedMod": 0.07}]
        self.assertEqual(len(aggregate_item_stats(pair)), 2)
        self.assertAlmostEqual(jack_of_all_trades_stacks(pair), 1.0, places=12)

    def test_an_unmapped_ddragon_key_contributes_no_stack(self) -> None:
        self.assertAlmostEqual(
            jack_of_all_trades_stacks([{"NotAStatKeyAtAll": 100.0}]),
            0.0,
            places=12,
        )

    def test_a_zero_valued_axis_contributes_no_stack(self) -> None:
        self.assertAlmostEqual(
            jack_of_all_trades_stacks(
                [{"FlatArmorMod": 0.0, "FlatPhysicalDamageMod": 40.0}]
            ),
            1.0,
            places=12,
        )

    def test_the_census_clamps_at_the_feed_cap(self) -> None:
        every_axis = [
            {
                "FlatHPPoolMod": 100.0,
                "FlatMPPoolMod": 100.0,
                "FlatHPRegenMod": 1.0,
                "FlatMPRegenMod": 1.0,
                "FlatArmorMod": 10.0,
                "FlatSpellBlockMod": 10.0,
                "FlatPhysicalDamageMod": 10.0,
                "FlatMagicDamageMod": 10.0,
                "FlatCritChanceMod": 0.2,
                "FlatMovementSpeedMod": 45.0,
                "PercentAttackSpeedMod": 0.2,
                "PercentLifeStealMod": 0.1,
                "PercentSpellVampMod": 0.1,
            }
        ]
        self.assertGreater(len(aggregate_item_stats(every_axis)), 10)
        self.assertAlmostEqual(
            jack_of_all_trades_stacks(every_axis), _JACK_MAX_STACKS, places=12
        )

    def test_an_empty_build_censuses_zero(self) -> None:
        self.assertAlmostEqual(jack_of_all_trades_stacks([]), 0.0, places=12)

    def test_junk_input_is_fail_soft(self) -> None:
        for junk in (None, 7, "3031", [None, "x", 5]):
            with self.subTest(junk=junk):
                self.assertAlmostEqual(
                    jack_of_all_trades_stacks(junk), 0.0, places=12
                )


class RegistryEntryTests(unittest.TestCase):
    """8316 is now a seeded entry, not a documented exclusion."""

    def test_the_registry_carries_jack_with_its_own_family(self) -> None:
        self.assertIn(JACK_OF_ALL_TRADES, _RUNE_OFFENSE_GRANTS)
        entry = _RUNE_OFFENSE_GRANTS[JACK_OF_ALL_TRADES]
        self.assertEqual(entry.name, "Jack Of All Trades")
        self.assertEqual(entry.tree, "Inspiration")
        self.assertTrue(entry.note)
        families = [e.family for e in _RUNE_OFFENSE_GRANTS.values()]
        self.assertTrue(all(families), "an empty family disables the dedup guard")
        self.assertEqual(len(families), len(set(families)))

    def test_no_supplied_census_means_no_grant(self) -> None:
        # Every pre-R156 caller passes no census, and must stay byte-identical.
        self.assertEqual(
            rune_offense_grants(
                [JACK_OF_ALL_TRADES], level=18, bonus_ad=250.0, ap=0.0
            ),
            (0.0, 0.0, 0.0),
        )

    def test_an_ad_build_takes_the_ad_column(self) -> None:
        ad, ap, as_frac = rune_offense_grants(
            [JACK_OF_ALL_TRADES],
            level=18, bonus_ad=250.0, ap=0.0, jack_stacks=10,
        )
        self.assertAlmostEqual(ad, 15.0, places=12)
        self.assertAlmostEqual(ap, 0.0, places=12)
        self.assertAlmostEqual(as_frac, 0.0, places=12)

    def test_an_ap_build_takes_the_ap_column(self) -> None:
        ad, ap, as_frac = rune_offense_grants(
            [JACK_OF_ALL_TRADES],
            level=18, bonus_ad=0.0, ap=600.0, jack_stacks=10,
        )
        self.assertAlmostEqual(ad, 0.0, places=12)
        self.assertAlmostEqual(ap, 25.0, places=12)
        self.assertAlmostEqual(as_frac, 0.0, places=12)

    def test_it_contributes_zero_to_the_attack_speed_column(self) -> None:
        for stacks in (0, 5, 10, 99):
            with self.subTest(stacks=stacks):
                _ad, _ap, as_frac = rune_offense_grants(
                    [JACK_OF_ALL_TRADES],
                    level=18, bonus_ad=250.0, ap=0.0, jack_stacks=stacks,
                )
                self.assertAlmostEqual(as_frac, 0.0, places=12)

    def test_the_low_tier_reaches_the_registry(self) -> None:
        ad, _ap, _as = rune_offense_grants(
            [JACK_OF_ALL_TRADES],
            level=18, bonus_ad=250.0, ap=0.0, jack_stacks=5,
        )
        self.assertAlmostEqual(ad, 6.0, places=12)

    def test_a_sub_tier_census_reaches_the_registry_as_zero(self) -> None:
        self.assertEqual(
            rune_offense_grants(
                [JACK_OF_ALL_TRADES],
                level=18, bonus_ad=250.0, ap=0.0, jack_stacks=4,
            ),
            (0.0, 0.0, 0.0),
        )

    def test_a_supplied_census_is_clamped_at_the_cap(self) -> None:
        self.assertEqual(
            rune_offense_grants(
                [JACK_OF_ALL_TRADES],
                level=18, bonus_ad=250.0, ap=0.0, jack_stacks=99,
            ),
            rune_offense_grants(
                [JACK_OF_ALL_TRADES],
                level=18, bonus_ad=250.0, ap=0.0,
                jack_stacks=_JACK_MAX_STACKS,
            ),
        )

    def test_a_duplicated_id_cannot_double_credit(self) -> None:
        once = rune_offense_grants(
            [JACK_OF_ALL_TRADES],
            level=18, bonus_ad=250.0, ap=0.0, jack_stacks=10,
        )
        many = rune_offense_grants(
            [JACK_OF_ALL_TRADES, JACK_OF_ALL_TRADES, 8316],
            level=18, bonus_ad=250.0, ap=0.0, jack_stacks=10,
        )
        self.assertEqual(once, many)

    def test_the_census_knob_does_not_disturb_the_other_entries(self) -> None:
        for rid in (GATHERING_STORM, ABSOLUTE_FOCUS, CONQUEROR, LEGEND_ALACRITY):
            with self.subTest(rune=rid):
                self.assertEqual(
                    rune_offense_grants(
                        [rid], level=18, bonus_ad=250.0, ap=0.0, game_minute=60.0
                    ),
                    rune_offense_grants(
                        [rid], level=18, bonus_ad=250.0, ap=0.0,
                        game_minute=60.0, jack_stacks=10,
                    ),
                )

    def test_jack_does_not_disturb_the_attack_speed_entry(self) -> None:
        both = rune_offense_grants(
            [LEGEND_ALACRITY, JACK_OF_ALL_TRADES],
            level=18, bonus_ad=250.0, ap=0.0, jack_stacks=10,
        )
        self.assertAlmostEqual(both[0], 15.0, places=12)
        self.assertAlmostEqual(both[2], 0.18, places=12)


class SeamDefaultOffTests(unittest.TestCase):
    """DEFAULT-OFF must be byte-identical even with 8316 in ``rune_ids``."""

    def _dps(self, items=None, **kw):
        return compute_dps(
            _snap(), champion_id="Caitlyn", level=18,
            item_ids=list(items or _AD_SIX), mode="SR", target_armor=80.0, **kw,
        )

    def test_absent_equals_explicit_off_with_jack_supplied(self) -> None:
        absent = self._dps()
        off = self._dps(
            apply_rune_offense_grants=False, rune_ids=[JACK_OF_ALL_TRADES]
        )
        self.assertAlmostEqual(absent.weighted_dps, off.weighted_dps, places=12)
        self.assertGreater(absent.weighted_dps, 0.0, "fixture is not exercising")


class SeamOnMovesDpsTests(unittest.TestCase):
    """Non-vacuous: with the flag ON the census-driven grant must land."""

    def _dps(self, items=None, **kw):
        return compute_dps(
            _snap(), champion_id="Caitlyn", level=18,
            item_ids=list(items or _AD_SIX), mode="SR", target_armor=80.0, **kw,
        )

    def test_jack_raises_weighted_dps_on_a_five_axis_build(self) -> None:
        off = self._dps(apply_rune_offense_grants=True, rune_ids=[])
        on = self._dps(
            apply_rune_offense_grants=True, rune_ids=[JACK_OF_ALL_TRADES]
        )
        self.assertGreater(
            on.weighted_dps, off.weighted_dps,
            "the census credited nothing - the lane is inert",
        )

    def test_a_four_axis_build_is_inert_even_when_on(self) -> None:
        # The negative control: the gate is the CENSUS, not the flag.
        off = compute_dps(
            _snap(), champion_id="Caitlyn", level=18, item_ids=_AD_TWO,
            mode="SR", target_armor=80.0,
            apply_rune_offense_grants=True, rune_ids=[],
        )
        on = compute_dps(
            _snap(), champion_id="Caitlyn", level=18, item_ids=_AD_TWO,
            mode="SR", target_armor=80.0,
            apply_rune_offense_grants=True, rune_ids=[JACK_OF_ALL_TRADES],
        )
        self.assertAlmostEqual(on.weighted_dps, off.weighted_dps, places=12)
        self.assertGreater(off.weighted_dps, 0.0, "fixture is not exercising")

    def test_the_credited_magnitude_is_the_low_tier_ad_not_the_high_one(self) -> None:
        # Decides the magnitude numerically rather than by sign: a 5-axis build
        # must credit 6.0 AD (10 Adaptive Force x 0.6) and NOT the high tier's
        # 15.0, so the ON result matches a forced (6.0, 0, 0) grant exactly and
        # differs from a forced (15.0, 0, 0) one.
        expected_ad = _ADAPTIVE_FORCE_AD_PER_AF * _JACK_AF_AT_LOW_TIER
        self.assertAlmostEqual(expected_ad, 6.0, places=12)
        self.assertAlmostEqual(
            jack_of_all_trades_stacks(_blocks(_AD_SIX)),
            _JACK_LOW_TIER_STACKS,
            places=12,
        )
        on = self._dps(
            apply_rune_offense_grants=True, rune_ids=[JACK_OF_ALL_TRADES]
        )
        with mock.patch(
            "agents.daemon_slayer.dps.rune_offense_grants",
            return_value=(expected_ad, 0.0, 0.0),
        ):
            forced_low = self._dps(
                apply_rune_offense_grants=True, rune_ids=[JACK_OF_ALL_TRADES]
            )
        with mock.patch(
            "agents.daemon_slayer.dps.rune_offense_grants",
            return_value=(_ADAPTIVE_FORCE_AD_PER_AF * _JACK_AF_AT_HIGH_TIER,
                          0.0, 0.0),
        ):
            forced_high = self._dps(
                apply_rune_offense_grants=True, rune_ids=[JACK_OF_ALL_TRADES]
            )
        self.assertAlmostEqual(on.weighted_dps, forced_low.weighted_dps, places=9)
        self.assertGreater(forced_high.weighted_dps, on.weighted_dps)


class EngineVersionTests(unittest.TestCase):
    def test_engine_version_pin(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.272.0")


if __name__ == "__main__":
    unittest.main()
