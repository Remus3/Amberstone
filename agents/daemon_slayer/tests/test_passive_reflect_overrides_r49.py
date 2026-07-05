"""R49 (2026-06-30) - Rammus-style on-being-hit reflect damage seam.

Characterization tests for ``_passive_reflect_overrides`` (the registry) + the
``dps.compute_dps`` / ``burst.compute_burst_damage`` ``assume_passive_reflect``
seam, plus the ``caster_mr`` (full magic resistance) scaling-target schema lift
that the reflect math needed (the documented blocker in
``_passive_damage_overrides`` item 513: "no caster total-MR _SCALING_TARGETS
field").

Ground truth = data/daemon_slayer/16.13.1/champion_abilities.json Rammus W
"Defensive Ball Curl" effects_descriptions, verified 2026-06-30 verbatim:
  "dealt 15 (+ 10% total armor) (+ 10% total magic resistance) magic damage."
parse_status == "no_damage" (the reflect lives in effects text, not a damage
block) - exactly the effects-text-only class this seam handles.

The reflect is a REACTIVE on-being-hit magic return (not an empowered AA), so
it amortizes by the assumed incoming attack rate (1 / ``reflect_cadence_s``)
into per-second DPS, and is mitigated by the duel target's magic resistance.
The seam is DEFAULT-OFF (byte-identical); the live default-ON flip is
operator-gated (docs/LIVE_GAME_GATED_SYNC.md).

Does NOT pin ENGINE_VERSION beyond the post-bump assertion (orchestrator owns
the bump).
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer._passive_reflect_overrides import (
    _ASSUMED_REFLECT_BURST_WINDOW_S,
    _PASSIVE_REFLECT_OVERRIDES,
    PassiveReflectEntry,
    reflect_entry,
    reflect_per_proc,
)
from agents.daemon_slayer._registries import _SCALING_TARGETS
from agents.daemon_slayer.ability_dps import AbilityContext
from agents.daemon_slayer.burst import compute_burst_damage
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps

_ITEMS = ["3047"]  # Plated Steelcaps - armor boots, a clean Rammus build.


class EngineVersion(unittest.TestCase):
    def test_engine_version_bumped(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.181.0")


class CasterMrScalingTarget(unittest.TestCase):
    """The full-MR scaling target the reflect math needed (symmetric with the
    pre-existing full-armor ``caster_armor`` target)."""

    def test_caster_mr_pct_mapped(self) -> None:
        mapping = dict(_SCALING_TARGETS)
        self.assertEqual(mapping.get("caster_mr_pct"), "caster_mr")

    def test_ability_context_carries_full_mr(self) -> None:
        ctx = AbilityContext.from_build(
            stats={"armor": 120.0, "mr": 90.0},
            base_stats={"armor": 20.0, "mr": 30.0},
            target_armor=0.0,
            target_mr=0.0,
            target_max_hp=0.0,
            target_bonus_hp=0.0,
        )
        self.assertEqual(ctx.caster_mr, 90.0)        # FULL mr (base + bonus)
        self.assertEqual(ctx.caster_bonus_mr, 60.0)  # above-base, unchanged
        self.assertEqual(ctx.caster_armor, 120.0)    # full armor still credited


class RegistryGroundTruth(unittest.TestCase):
    def test_rammus_w_pins(self) -> None:
        e = reflect_entry("Rammus")
        self.assertIsNotNone(e)
        self.assertIsInstance(e, PassiveReflectEntry)
        self.assertEqual(e.base[0], 15.0)
        self.assertAlmostEqual(e.caster_armor_pct, 10.0)
        self.assertAlmostEqual(e.caster_mr_pct, 10.0)
        self.assertEqual(e.damage_type, "MAGIC")
        self.assertGreater(e.reflect_cadence_s, 0.0)

    def test_registry_key_shape(self) -> None:
        self.assertIn(("Rammus", "W", 0), _PASSIVE_REFLECT_OVERRIDES)

    def test_unregistered_is_none(self) -> None:
        self.assertIsNone(reflect_entry("Garen"))
        self.assertIsNone(reflect_entry("Caitlyn"))

    def test_per_proc_formula(self) -> None:
        e = reflect_entry("Rammus")
        # 15 + 10% of 200 armor + 10% of 100 MR = 15 + 20 + 10 = 45.
        self.assertAlmostEqual(
            reflect_per_proc(e, caster_total_armor=200.0, caster_total_mr=100.0),
            45.0,
        )
        # flat-only at zero resists (the no-build lower bound).
        self.assertAlmostEqual(
            reflect_per_proc(e, caster_total_armor=0.0, caster_total_mr=0.0),
            15.0,
        )

    def test_per_proc_monotonic_in_caster_resists(self) -> None:
        e = reflect_entry("Rammus")
        lo = reflect_per_proc(e, caster_total_armor=50.0, caster_total_mr=30.0)
        hi = reflect_per_proc(e, caster_total_armor=150.0, caster_total_mr=120.0)
        self.assertGreater(hi, lo)

    def test_burst_window_positive(self) -> None:
        self.assertGreater(_ASSUMED_REFLECT_BURST_WINDOW_S, 0.0)


class ComputeDpsSeam(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_default_off_byte_identical(self) -> None:
        for cid in ("Rammus", "Caitlyn"):
            base = compute_dps(self.snap, cid, level=11, item_ids=_ITEMS,
                               target_armor=60, target_mr=40)
            off = compute_dps(self.snap, cid, level=11, item_ids=_ITEMS,
                              target_armor=60, target_mr=40,
                              assume_passive_reflect=False)
            self.assertEqual(base.weighted_dps, off.weighted_dps, msg=cid)
            self.assertEqual(base.phase_dps, off.phase_dps, msg=cid)
            self.assertFalse(
                any("reflect" in n.lower() for n in off.notes), msg=cid
            )

    def test_rammus_reflect_raises_dps(self) -> None:
        off = compute_dps(self.snap, "Rammus", level=11, item_ids=_ITEMS,
                          target_armor=60, target_mr=40)
        on = compute_dps(self.snap, "Rammus", level=11, item_ids=_ITEMS,
                         target_armor=60, target_mr=40,
                         assume_passive_reflect=True)
        self.assertGreater(on.weighted_dps, off.weighted_dps)
        self.assertTrue(any("reflect" in n.lower() for n in on.notes))

    def test_unregistered_champ_byte_identical_even_on(self) -> None:
        off = compute_dps(self.snap, "Caitlyn", level=11, item_ids=_ITEMS,
                          target_armor=60, target_mr=40)
        on = compute_dps(self.snap, "Caitlyn", level=11, item_ids=_ITEMS,
                         target_armor=60, target_mr=40,
                         assume_passive_reflect=True)
        self.assertEqual(off.weighted_dps, on.weighted_dps)
        self.assertEqual(off.phase_dps, on.phase_dps)

    def test_higher_target_mr_lowers_reflect_credit(self) -> None:
        # The reflect is MAGIC -> mitigated by the duel target's MR. A tankier
        # (higher-MR) attacker takes less reflect, so the seam DELTA shrinks.
        off_lo = compute_dps(self.snap, "Rammus", level=11, item_ids=_ITEMS,
                             target_armor=60, target_mr=20)
        on_lo = compute_dps(self.snap, "Rammus", level=11, item_ids=_ITEMS,
                            target_armor=60, target_mr=20,
                            assume_passive_reflect=True)
        off_hi = compute_dps(self.snap, "Rammus", level=11, item_ids=_ITEMS,
                             target_armor=60, target_mr=200)
        on_hi = compute_dps(self.snap, "Rammus", level=11, item_ids=_ITEMS,
                            target_armor=60, target_mr=200,
                            assume_passive_reflect=True)
        delta_lo = on_lo.weighted_dps - off_lo.weighted_dps
        delta_hi = on_hi.weighted_dps - off_hi.weighted_dps
        self.assertGreater(delta_lo, delta_hi)


class ComputeBurstSeam(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_default_off_byte_identical(self) -> None:
        for cid in ("Rammus", "Caitlyn"):
            base = compute_burst_damage(self.snap, cid, level=11, item_ids=_ITEMS,
                                        target_armor=60, target_mr=40)
            off = compute_burst_damage(self.snap, cid, level=11, item_ids=_ITEMS,
                                       target_armor=60, target_mr=40,
                                       assume_passive_reflect=False)
            self.assertEqual(
                base.total_burst_damage, off.total_burst_damage, msg=cid
            )

    def test_rammus_reflect_raises_burst(self) -> None:
        off = compute_burst_damage(self.snap, "Rammus", level=11, item_ids=_ITEMS,
                                   target_armor=60, target_mr=40)
        on = compute_burst_damage(self.snap, "Rammus", level=11, item_ids=_ITEMS,
                                  target_armor=60, target_mr=40,
                                  assume_passive_reflect=True)
        self.assertGreater(on.total_burst_damage, off.total_burst_damage)

    def test_unregistered_champ_byte_identical_even_on(self) -> None:
        off = compute_burst_damage(self.snap, "Caitlyn", level=11, item_ids=_ITEMS,
                                   target_armor=60, target_mr=40)
        on = compute_burst_damage(self.snap, "Caitlyn", level=11, item_ids=_ITEMS,
                                  target_armor=60, target_mr=40,
                                  assume_passive_reflect=True)
        self.assertEqual(off.total_burst_damage, on.total_burst_damage)


if __name__ == "__main__":
    unittest.main()
