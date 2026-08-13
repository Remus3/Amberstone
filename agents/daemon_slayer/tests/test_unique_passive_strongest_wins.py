"""RM-186: the unique-passive dedup was ORDER-DEPENDENT, so slot order alone
changed the score.

``collect_effects`` de-duplicates items sharing a non-empty
``unique_passive_key`` first-seen-wins. Sunfire Aegis (3068, Immolate 20 + 1%
bonus HP) and Hollow Radiance (6664, Immolate 15 + 1% bonus HP) are both FULL
items and legally co-ownable, so a build listing them in the other order kept
the WEAKER passive:

    collect_effects(['6664','3068']) -> ['6664']   # 15 + 1% kept
    collect_effects(['3068','6664']) -> ['3068']   # 20 + 1% kept

Operator decision: model STRONGEST-AT-CONTEXT WINS, behind a DEFAULT-OFF seam.
``caster_ctx=None`` (every existing caller) stays byte-identical first-seen-wins;
``caster_ctx=<CallContext>`` resolves each group to the member with the largest
comparable per-second RAW magnitude.

Written RED first per the repo TDD rule.
"""
from __future__ import annotations

import unittest
import unittest.mock

import agents.daemon_slayer as daemon_slayer
from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer._effects_data import ITEM_EFFECTS
from agents.daemon_slayer._effects_types import (
    CallContext,
    ItemEffect,
    MAGICAL,
    PeriodicProc,
)
from agents.daemon_slayer.dps import _periodic_proc_dps
from agents.daemon_slayer.effects import collect_effects

# Immolate family (unique_passive_key="immolate").
SUNFIRE = "3068"            # 20 + 1.0% bonus HP, MAGICAL
HOLLOW_RADIANCE = "6664"    # 15 + 1.0% bonus HP, MAGICAL
HOLLOW_ARENA = "226664"     # Arena mirror of 6664 - IDENTICAL magnitude
BAMIS = "6660"              # flat 15, MAGICAL (component tier)
VOID_IMMOLATION = "223069"  # 20 + 1.5% MAX HP, TRUE (Arena)

# Families with ZERO per-second periodics -> no comparable magnitude.
LAST_WHISPER_A = "3036"     # Lord Dominik's Regards (pen only, no procs)
LAST_WHISPER_B = "3033"     # Mortal Reminder (pen only, no procs)
LIFELINE_A = "3053"         # Sterak's Gage (shield only)
LIFELINE_B = "3156"         # Maw of Malmortius (shield only)
# hydra_cleave is every_n_ATTACKS only -> not per-second comparable.
HYDRA_RAVENOUS = "3074"
HYDRA_TITANIC = "3748"


def _tank_ctx(bonus_hp: float = 2000.0, max_hp: float = 3400.0) -> CallContext:
    """A realistic mid-game tank context (level 13, ~3400 HP / ~2000 bonus)."""
    return CallContext(
        base_ad=60.0,
        bonus_ad=0.0,
        level=13,
        caster_max_hp=max_hp,
        caster_bonus_hp=bonus_hp,
    )


class DefaultPathIsByteIdenticalTests(unittest.TestCase):
    """(a) OFF / default path is unchanged - first-seen-wins, every family."""

    # Pinned from the PRE-CHANGE engine (measured 2026-08-08), not recomputed
    # by a parallel reimplementation in the test (which would be shaped to the
    # code under test rather than to the old behaviour).
    CASES = (
        (["6664", "3068"], ["6664"]),
        (["3068", "6664"], ["3068"]),
        (["3078", "3100", "3153", "6673"], ["3078", "3153", "6673"]),
        (["3036", "3033", "3135", "3137", "3031"], ["3036", "3135", "3031"]),
        (
            ["3068", "6660", "3074", "3748", "3053", "3156", "3036"],
            ["3068", "3074", "3053", "3036"],
        ),
        (["3031", "3153", "3086"], ["3031", "3153", "3086"]),
        ([], []),
    )

    def test_default_results_unchanged(self):
        for build, expected in self.CASES:
            with self.subTest(build=build):
                self.assertEqual(
                    [e.item_id for e in collect_effects(build)], expected
                )

    def test_default_kwarg_is_explicit_none_equivalent(self):
        for build, expected in self.CASES:
            with self.subTest(build=build):
                self.assertEqual(
                    [e.item_id for e in collect_effects(build, caster_ctx=None)],
                    expected,
                )

    def test_unknown_ids_and_int_ids_still_pass_through(self):
        self.assertEqual(
            [e.item_id for e in collect_effects([3068, 999999, 6664])],
            ["3068"],
        )


class OrderIndependenceTests(unittest.TestCase):
    """(b) ON path is ORDER-INDEPENDENT and keeps the strongest member."""

    def test_immolate_pair_order_independent(self):
        ctx = _tank_ctx()
        weak_first = collect_effects([HOLLOW_RADIANCE, SUNFIRE], caster_ctx=ctx)
        strong_first = collect_effects([SUNFIRE, HOLLOW_RADIANCE], caster_ctx=ctx)
        self.assertEqual(
            [e.item_id for e in weak_first], [e.item_id for e in strong_first]
        )
        self.assertEqual([e.item_id for e in weak_first], [SUNFIRE])

    def test_sunfire_wins_at_every_non_negative_bonus_hp(self):
        """20 + 1% beats 15 + 1% at ANY non-negative bonus HP."""
        for bonus_hp in (0.0, 1.0, 500.0, 2000.0, 5000.0):
            with self.subTest(bonus_hp=bonus_hp):
                ctx = _tank_ctx(bonus_hp=bonus_hp)
                self.assertEqual(
                    [
                        e.item_id
                        for e in collect_effects(
                            [HOLLOW_RADIANCE, SUNFIRE], caster_ctx=ctx
                        )
                    ],
                    [SUNFIRE],
                )

    def test_group_keeps_the_first_members_slot(self):
        """The winner is emitted at the position the group first claimed, so a
        build with unrelated items between the pair is order-independent too."""
        ctx = _tank_ctx()
        a = collect_effects([HOLLOW_RADIANCE, "3031", SUNFIRE], caster_ctx=ctx)
        b = collect_effects([SUNFIRE, "3031", HOLLOW_RADIANCE], caster_ctx=ctx)
        self.assertEqual([e.item_id for e in a], [e.item_id for e in b])
        self.assertEqual([e.item_id for e in a], [SUNFIRE, "3031"])

    def test_non_grouped_items_keep_their_order(self):
        ctx = _tank_ctx()
        self.assertEqual(
            [
                e.item_id
                for e in collect_effects(
                    ["3031", HOLLOW_RADIANCE, "3153", SUNFIRE], caster_ctx=ctx
                )
            ],
            ["3031", SUNFIRE, "3153"],
        )


class ContextSensitiveWinnerTests(unittest.TestCase):
    """(c) The winner is context-dependent, not a static per-item ranking."""

    def test_void_immolation_beats_sunfire_at_a_tank_context(self):
        # 223069: 20 + 1.5% MAX HP -> 20 + 51 = 71/s at 3400 max HP.
        # 3068:   20 + 1.0% BONUS HP -> 20 + 20 = 40/s at 2000 bonus HP.
        ctx = _tank_ctx(bonus_hp=2000.0, max_hp=3400.0)
        self.assertEqual(
            [
                e.item_id
                for e in collect_effects([SUNFIRE, VOID_IMMOLATION], caster_ctx=ctx)
            ],
            [VOID_IMMOLATION],
        )
        self.assertEqual(
            [
                e.item_id
                for e in collect_effects([VOID_IMMOLATION, SUNFIRE], caster_ctx=ctx)
            ],
            [VOID_IMMOLATION],
        )

    def test_same_pair_flips_when_the_context_flips(self):
        """A squishy with bonus HP but (contrived) no max-HP signal ranks the
        MAGICAL Sunfire above the TRUE-damage Void Immolation."""
        ctx = _tank_ctx(bonus_hp=3000.0, max_hp=0.0)
        self.assertEqual(
            [
                e.item_id
                for e in collect_effects([VOID_IMMOLATION, SUNFIRE], caster_ctx=ctx)
            ],
            [SUNFIRE],
        )

    def test_damage_type_is_not_a_tiebreak(self):
        """(3) RAW pre-mitigation magnitude decides. Void Immolation deals TRUE
        damage - strictly better post-mitigation than Sunfire's MAGICAL - and
        still LOSES when its raw per-second number is lower. Pinning the
        documented assumption so a future 'true damage should win' change is a
        deliberate act, not a silent one."""
        ctx = _tank_ctx(bonus_hp=3000.0, max_hp=0.0)
        void_raw = ITEM_EFFECTS[VOID_IMMOLATION].periodics[0].resolve_damage(ctx)
        sunfire_raw = ITEM_EFFECTS[SUNFIRE].periodics[0].resolve_damage(ctx)
        self.assertLess(void_raw, sunfire_raw)
        self.assertEqual(ITEM_EFFECTS[VOID_IMMOLATION].periodics[0].damage_type, "true")
        self.assertEqual(
            [
                e.item_id
                for e in collect_effects([VOID_IMMOLATION, SUNFIRE], caster_ctx=ctx)
            ],
            [SUNFIRE],
        )

    def test_per_second_normalisation_not_raw_tick(self):
        """A 2s-period proc worth 60 is 30/s and must LOSE to a 1s proc worth 40.
        Pins the every_n_seconds normalisation rather than raw tick magnitude."""
        slow = ItemEffect(
            item_id="_slow",
            name="Slow Immolate",
            periodics=(
                PeriodicProc(
                    name="Immolate",
                    bonus_damage=60.0,
                    damage_type=MAGICAL,
                    every_n_seconds=2.0,
                ),
            ),
            unique_passive_key="immolate",
        )
        patched = dict(ITEM_EFFECTS)
        patched["_slow"] = slow
        with unittest.mock.patch.dict(ITEM_EFFECTS, patched, clear=True):
            ctx = _tank_ctx(bonus_hp=2000.0)
            self.assertEqual(
                [
                    e.item_id
                    for e in collect_effects(["_slow", SUNFIRE], caster_ctx=ctx)
                ],
                [SUNFIRE],
            )


class FallbackTests(unittest.TestCase):
    """(d) A group with no comparable magnitude resolves first-seen under ON."""

    def test_last_whisper_family_has_no_periodics(self):
        self.assertEqual(ITEM_EFFECTS[LAST_WHISPER_A].periodics, ())
        self.assertEqual(ITEM_EFFECTS[LAST_WHISPER_B].periodics, ())

    def test_last_whisper_family_falls_back_first_seen(self):
        ctx = _tank_ctx()
        self.assertEqual(
            [
                e.item_id
                for e in collect_effects(
                    [LAST_WHISPER_A, LAST_WHISPER_B], caster_ctx=ctx
                )
            ],
            [LAST_WHISPER_A],
        )
        self.assertEqual(
            [
                e.item_id
                for e in collect_effects(
                    [LAST_WHISPER_B, LAST_WHISPER_A], caster_ctx=ctx
                )
            ],
            [LAST_WHISPER_B],
        )

    def test_lifeline_family_falls_back_first_seen(self):
        ctx = _tank_ctx()
        self.assertEqual(
            [
                e.item_id
                for e in collect_effects([LIFELINE_B, LIFELINE_A], caster_ctx=ctx)
            ],
            [LIFELINE_B],
        )

    def test_every_n_attacks_family_falls_back_first_seen(self):
        """hydra_cleave is every_n_attacks only - not per-second comparable."""
        for e in (ITEM_EFFECTS[HYDRA_RAVENOUS], ITEM_EFFECTS[HYDRA_TITANIC]):
            for proc in e.periodics:
                self.assertGreater(proc.every_n_attacks, 0)
                self.assertEqual(proc.every_n_seconds, 0.0)
        ctx = _tank_ctx()
        self.assertEqual(
            [
                e.item_id
                for e in collect_effects(
                    [HYDRA_TITANIC, HYDRA_RAVENOUS], caster_ctx=ctx
                )
            ],
            [HYDRA_TITANIC],
        )

    def test_raising_callable_falls_back_first_seen_and_does_not_propagate(self):
        """(4) A bonus_damage callable that raises must not break collection."""

        def _boom(_ctx):
            raise RuntimeError("bad proc lambda")

        exploding = ItemEffect(
            item_id="_boom",
            name="Exploding Immolate",
            periodics=(
                PeriodicProc(
                    name="Immolate",
                    bonus_damage=_boom,
                    damage_type=MAGICAL,
                    every_n_seconds=1.0,
                ),
            ),
            unique_passive_key="immolate",
        )
        patched = dict(ITEM_EFFECTS)
        patched["_boom"] = exploding
        ctx = _tank_ctx()
        with unittest.mock.patch.dict(ITEM_EFFECTS, patched, clear=True):
            with self.assertLogs("agents.daemon_slayer.effects", level="WARNING"):
                got = collect_effects([HOLLOW_RADIANCE, "_boom"], caster_ctx=ctx)
            self.assertEqual([e.item_id for e in got], [HOLLOW_RADIANCE])
            with self.assertLogs("agents.daemon_slayer.effects", level="WARNING"):
                got = collect_effects(["_boom", HOLLOW_RADIANCE], caster_ctx=ctx)
            self.assertEqual([e.item_id for e in got], ["_boom"])


class TieBreakTests(unittest.TestCase):
    """(f) Ties keep first-seen, so the ON path stays deterministic."""

    def test_identical_magnitude_mirrors_keep_first_seen(self):
        ctx = _tank_ctx()
        sr = ITEM_EFFECTS[HOLLOW_RADIANCE].periodics[0].resolve_damage(ctx)
        arena = ITEM_EFFECTS[HOLLOW_ARENA].periodics[0].resolve_damage(ctx)
        self.assertEqual(sr, arena)
        self.assertEqual(
            [
                e.item_id
                for e in collect_effects(
                    [HOLLOW_RADIANCE, HOLLOW_ARENA], caster_ctx=ctx
                )
            ],
            [HOLLOW_RADIANCE],
        )
        self.assertEqual(
            [
                e.item_id
                for e in collect_effects(
                    [HOLLOW_ARENA, HOLLOW_RADIANCE], caster_ctx=ctx
                )
            ],
            [HOLLOW_ARENA],
        )


class NonInertnessTests(unittest.TestCase):
    """(e) The ON path moves a REAL computed number, not just the returned list.

    Proving the seam changes the collected list is not proving it changes the
    engine's arithmetic (memory: a verified change is not a measured downstream).
    """

    def test_periodic_proc_dps_differs_between_off_and_on(self):
        ctx = _tank_ctx(bonus_hp=2000.0)
        weak_order = [HOLLOW_RADIANCE, SUNFIRE]
        off = _periodic_proc_dps(
            collect_effects(weak_order),
            total_attacks=10.0,
            duration=10.0,
            target_armor_for_physical=0.0,
            target_mr=0.0,
            mode_dmg_mult=1.0,
            call_ctx=ctx,
        )
        on = _periodic_proc_dps(
            collect_effects(weak_order, caster_ctx=ctx),
            total_attacks=10.0,
            duration=10.0,
            target_armor_for_physical=0.0,
            target_mr=0.0,
            mode_dmg_mult=1.0,
            call_ctx=ctx,
        )
        # Hollow Radiance 15 + 1% x 2000 = 35 magic/s; Sunfire 20 + 1% x 2000
        # = 40 magic/s. Zero MR -> the mitigation factor is 1.0 on both.
        self.assertAlmostEqual(off, 35.0, places=6)
        self.assertAlmostEqual(on, 40.0, places=6)
        self.assertGreater(on, off)

    def test_strong_order_is_identical_off_and_on(self):
        """The seam only CORRECTS the bad order - it never inflates the good
        one, so a build already listing the stronger item first is unchanged."""
        ctx = _tank_ctx(bonus_hp=2000.0)
        strong_order = [SUNFIRE, HOLLOW_RADIANCE]
        kw = dict(
            total_attacks=10.0,
            duration=10.0,
            target_armor_for_physical=0.0,
            target_mr=0.0,
            mode_dmg_mult=1.0,
            call_ctx=ctx,
        )
        off = _periodic_proc_dps(collect_effects(strong_order), **kw)
        on = _periodic_proc_dps(
            collect_effects(strong_order, caster_ctx=ctx), **kw
        )
        self.assertAlmostEqual(off, on, places=9)
        self.assertAlmostEqual(on, 40.0, places=6)


class EngineVersionTests(unittest.TestCase):
    def test_engine_version(self):
        self.assertEqual(ENGINE_VERSION, "1.277.1")
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.277.1")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
