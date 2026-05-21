"""ENGINE 1.26.0 (2026-05-21) - Stack-ramp discharge schema lift.

Closes BACKLOG "Dead Man's Plate Momentum stacks-schema" queued from
overnight 2026-05-20 iter 15-16. The family extension is the new
``PeriodicProc.stack_ramp_seconds`` field on the existing periodic-proc
schema. Dead Man's Plate (3742 + Arena mirror 223742) is the first
consumer.

Tests cover:
* SchemaConstructionTests - PeriodicProc accepts/rejects new field
* SustainedDpsRampGateTests - ramp-gated proc fires at correct rate
* BurstSkipTests - burst path skips stack-ramp-gated procs
* DeadMansPlateEncodingTests - SR 3742 + Arena 223742 wired correctly
* DeadMansPlateLiveContributionTests - end-to-end DPS contribution
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer._effects_types import (
    CallContext,
    MAGICAL,
    PHYSICAL,
    PeriodicProc,
)
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import (
    _per_attack_proc_damage,
    _periodic_proc_dps,
    compute_dps,
)
from agents.daemon_slayer.effects import ITEM_EFFECTS


class SchemaConstructionTests(unittest.TestCase):
    """The new ``stack_ramp_seconds`` field accepts valid combos and
    rejects malformed ones."""

    def test_valid_with_attacks_and_ramp(self) -> None:
        p = PeriodicProc(
            name="test",
            bonus_damage=100.0,
            damage_type=PHYSICAL,
            every_n_attacks=1,
            stack_ramp_seconds=3.57,
        )
        self.assertEqual(p.stack_ramp_seconds, 3.57)
        self.assertEqual(p.every_n_attacks, 1)

    def test_default_ramp_is_zero(self) -> None:
        p = PeriodicProc(
            name="test",
            bonus_damage=100.0,
            damage_type=PHYSICAL,
            every_n_attacks=4,
        )
        self.assertEqual(p.stack_ramp_seconds, 0.0)

    def test_rejects_negative_ramp(self) -> None:
        with self.assertRaises(ValueError) as cm:
            PeriodicProc(
                name="bad",
                bonus_damage=100.0,
                damage_type=PHYSICAL,
                every_n_attacks=1,
                stack_ramp_seconds=-1.0,
            )
        self.assertIn("stack_ramp_seconds", str(cm.exception))

    def test_rejects_ramp_with_seconds_path(self) -> None:
        # Stack-ramp only valid with every_n_attacks > 0.
        with self.assertRaises(ValueError) as cm:
            PeriodicProc(
                name="bad",
                bonus_damage=100.0,
                damage_type=PHYSICAL,
                every_n_seconds=2.0,
                stack_ramp_seconds=1.0,
            )
        self.assertIn("every_n_attacks > 0", str(cm.exception))

    def test_zero_ramp_keeps_existing_xor_semantics(self) -> None:
        # Default 0.0 ramp + every_n_seconds is the existing pattern.
        p = PeriodicProc(
            name="test",
            bonus_damage=100.0,
            damage_type=PHYSICAL,
            every_n_seconds=2.0,
        )
        self.assertEqual(p.stack_ramp_seconds, 0.0)


class SustainedDpsRampGateTests(unittest.TestCase):
    """The consumer in ``_periodic_proc_dps`` gates ramp procs to fire at
    the MAX of (ramp seconds, attack_period * every_n_attacks)."""

    def _ctx(self) -> CallContext:
        return CallContext(base_ad=100.0, bonus_ad=0.0, level=11)

    def _proc(self, ramp_s: float) -> PeriodicProc:
        return PeriodicProc(
            name="ramp_test",
            bonus_damage=100.0,
            damage_type=PHYSICAL,
            every_n_attacks=1,
            stack_ramp_seconds=ramp_s,
        )

    def _mk_effect(self, proc: PeriodicProc):
        # Minimal ItemEffect via the real schema (defaults satisfied).
        from agents.daemon_slayer._effects_types import ItemEffect
        return ItemEffect(item_id="X", name="X", periodics=(proc,))

    def test_ramp_dominates_when_longer_than_attack_period(self) -> None:
        # 10s duration, 10 attacks -> 1s attack period. 3.57s ramp >
        # 1s -> ramp wins. Expected procs = 10 / 3.57.
        e = self._mk_effect(self._proc(3.57))
        dps = _periodic_proc_dps(
            [e], total_attacks=10.0, duration=10.0,
            target_armor_for_physical=0.0, target_mr=0.0,
            mode_dmg_mult=1.0, call_ctx=self._ctx(),
        )
        # 10/3.57 = 2.801 procs; 100 dmg each; 0 armor -> factor 1.0
        # contribution = 2.801 * 100 / 10 = 28.01 DPS
        self.assertAlmostEqual(dps, (10.0 / 3.57) * 100.0 / 10.0, places=2)

    def test_attack_period_dominates_when_longer_than_ramp(self) -> None:
        # 10s duration, 2 attacks -> 5s attack period. Ramp 3.57s -> 5s
        # wins. Expected procs = 10 / 5 = 2.
        e = self._mk_effect(self._proc(3.57))
        dps = _periodic_proc_dps(
            [e], total_attacks=2.0, duration=10.0,
            target_armor_for_physical=0.0, target_mr=0.0,
            mode_dmg_mult=1.0, call_ctx=self._ctx(),
        )
        # 2 procs * 100 / 10 = 20 DPS.
        self.assertAlmostEqual(dps, 20.0, places=2)

    def test_zero_ramp_is_pre_lift_behavior(self) -> None:
        # Sanity: stack_ramp_seconds=0 -> same as legacy every_n_attacks
        # proc. 10 attacks / 1 attack-per-proc = 10 procs over 10s.
        e = self._mk_effect(self._proc(0.0))
        dps = _periodic_proc_dps(
            [e], total_attacks=10.0, duration=10.0,
            target_armor_for_physical=0.0, target_mr=0.0,
            mode_dmg_mult=1.0, call_ctx=self._ctx(),
        )
        self.assertAlmostEqual(dps, 100.0, places=2)

    def test_zero_total_attacks_yields_zero(self) -> None:
        # Engine pre-existing behavior: every_n_attacks proc with 0
        # attacks contributes 0. Stack-ramp gating preserves this.
        e = self._mk_effect(self._proc(3.57))
        dps = _periodic_proc_dps(
            [e], total_attacks=0.0, duration=10.0,
            target_armor_for_physical=0.0, target_mr=0.0,
            mode_dmg_mult=1.0, call_ctx=self._ctx(),
        )
        self.assertAlmostEqual(dps, 0.0, places=2)

    def test_armor_mitigation_applies(self) -> None:
        # 100 armor = 50% factor. 10s/3.57s ramp = 2.801 procs * 100 dmg
        # * 0.5 = 140.06 total / 10s = 14.0 DPS.
        e = self._mk_effect(self._proc(3.57))
        dps = _periodic_proc_dps(
            [e], total_attacks=10.0, duration=10.0,
            target_armor_for_physical=100.0, target_mr=0.0,
            mode_dmg_mult=1.0, call_ctx=self._ctx(),
        )
        self.assertAlmostEqual(dps, (10.0 / 3.57) * 100.0 * 0.5 / 10.0, places=2)


class BurstSkipTests(unittest.TestCase):
    """Burst-window per-attack tally skips stack-ramp-gated procs
    (typical burst is 2-3s; ramp is 3.57s for Dead Man's). This is a
    deliberate scope decision: tank items with stack-discharge passives
    don't contribute meaningfully to assassin burst, and including them
    would over-attribute by assuming stacks were pre-built."""

    def _ctx(self) -> CallContext:
        return CallContext(base_ad=100.0, bonus_ad=0.0, level=11)

    def _mk_effect(self, *procs):
        from agents.daemon_slayer._effects_types import ItemEffect
        return ItemEffect(item_id="X", name="X", periodics=tuple(procs))

    def test_burst_skips_stack_ramp_proc(self) -> None:
        ramp_proc = PeriodicProc(
            name="ramp",
            bonus_damage=100.0,
            damage_type=PHYSICAL,
            every_n_attacks=1,
            stack_ramp_seconds=3.57,
        )
        e = self._mk_effect(ramp_proc)
        per_aa = _per_attack_proc_damage(
            [e], target_armor_for_physical=0.0, target_mr=0.0,
            mode_dmg_mult=1.0, call_ctx=self._ctx(),
        )
        self.assertAlmostEqual(per_aa, 0.0, places=4)

    def test_burst_includes_non_ramp_attack_proc(self) -> None:
        # Sibling: standard every-1-attack proc DOES contribute to burst.
        normal_proc = PeriodicProc(
            name="normal",
            bonus_damage=50.0,
            damage_type=PHYSICAL,
            every_n_attacks=1,
        )
        e = self._mk_effect(normal_proc)
        per_aa = _per_attack_proc_damage(
            [e], target_armor_for_physical=0.0, target_mr=0.0,
            mode_dmg_mult=1.0, call_ctx=self._ctx(),
        )
        # 1 proc per AA * 50 dmg * factor 1.0 = 50.
        self.assertAlmostEqual(per_aa, 50.0, places=4)


class DeadMansPlateEncodingTests(unittest.TestCase):
    """Verify SR 3742 + Arena 223742 are wired with the new schema."""

    def test_sr_3742_has_shipwrecker_proc(self) -> None:
        e = ITEM_EFFECTS["3742"]
        self.assertFalse(e.defensive_only)
        self.assertEqual(len(e.periodics), 1)
        proc = e.periodics[0]
        self.assertEqual(proc.name, "Shipwrecker")
        self.assertEqual(proc.damage_type, PHYSICAL)
        self.assertEqual(proc.every_n_attacks, 1)
        self.assertAlmostEqual(proc.stack_ramp_seconds, 3.57, places=4)

    def test_sr_3742_discharge_matches_full_stack_formula(self) -> None:
        # Full-stack discharge = 40 + 1.0 * base_ad (PHYSICAL).
        proc = ITEM_EFFECTS["3742"].periodics[0]
        ctx = CallContext(base_ad=100.0, bonus_ad=0.0, level=11)
        self.assertAlmostEqual(proc.resolve_damage(ctx), 140.0, places=4)

    def test_arena_223742_mirrors_sr(self) -> None:
        e = ITEM_EFFECTS["223742"]
        self.assertFalse(e.defensive_only)
        self.assertEqual(len(e.periodics), 1)
        proc = e.periodics[0]
        self.assertEqual(proc.name, "Shipwrecker")
        self.assertEqual(proc.damage_type, PHYSICAL)
        self.assertEqual(proc.every_n_attacks, 1)
        self.assertAlmostEqual(proc.stack_ramp_seconds, 3.57, places=4)

    def test_arena_223742_discharge_matches_sr(self) -> None:
        sr_proc = ITEM_EFFECTS["3742"].periodics[0]
        ar_proc = ITEM_EFFECTS["223742"].periodics[0]
        ctx = CallContext(base_ad=125.0, bonus_ad=0.0, level=14)
        self.assertAlmostEqual(
            sr_proc.resolve_damage(ctx),
            ar_proc.resolve_damage(ctx),
            places=4,
        )


class DeadMansPlateLiveContributionTests(unittest.TestCase):
    """End-to-end: adding Dead Man's Plate to a build lifts weighted_dps
    by the expected stack-ramp-gated proc contribution."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_aatrox_l11_dead_mans_lifts_dps(self) -> None:
        # Aatrox L11 base_ad = 103.875. Full-stack discharge = 40 + 103.875
        # = 143.875 physical per proc. Target 100 armor = 50% factor.
        # Sustained model: proc rate gated by max(3.57s ramp, attack
        # period). Aatrox L11 base AS ~0.681 -> attack period ~1.47s;
        # 1.47s < 3.57s -> ramp gates. Expected DPS contribution from
        # the proc = 143.875 / 3.57 * 0.5 = 20.15.
        r0 = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=[],
            target_armor=100.0, target_mr=100.0,
        )
        r1 = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3742"],
            target_armor=100.0, target_mr=100.0,
        )
        delta = r1.weighted_dps - r0.weighted_dps
        # 143.875 / 3.57 * 0.5 = 20.15 (exact full-stack math, no
        # attack-speed effect since Dead Man's grants 0 AS).
        expected = (40.0 + 103.875) / 3.57 * 0.5
        self.assertAlmostEqual(delta, expected, places=1)

    def test_dead_mans_no_longer_defensive_only(self) -> None:
        # Schema-lift consequence: Dead Man's now contributes DPS in
        # rank tables where pre-1.26.0 it was filtered as defensive_only.
        r0 = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=[],
            target_armor=100.0, target_mr=100.0,
        )
        r1 = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3742"],
            target_armor=100.0, target_mr=100.0,
        )
        # Strict greater - the schema lift gives this item real DPS.
        self.assertGreater(r1.weighted_dps, r0.weighted_dps)


if __name__ == "__main__":
    unittest.main()
