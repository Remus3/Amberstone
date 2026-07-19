"""Item 294 (ENGINE 1.106.0) - offensive CC-output (lockdown) scorer tests.

The seventh scored axis and the mirror of the survivability CC axes (item 290
champion CC-mitigation / item 292 spell-shield): how much crowd control a
champion APPLIES to enemies, weighted by CC kind into a single lockdown score.
Proves (a) hand-verified lockdown values at pinned inputs, (b) the conditional
availability-midpoint discount, (c) the kind -> weight tiers, (d) registry
invariants + roster coverage, (e) the additive /cc-output route registers
alongside (does not replace) the existing routes, (f) the ENGINE pin.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.cc_output import (
    _CC_KIND_WEIGHT,
    _CC_OUTPUT_CONDITIONAL_PROB,
    _CC_OUTPUT_REGISTRY,
    CcOutputResult,
    compute_cc_output,
)


class HandVerifiedScoreTests(unittest.TestCase):
    def test_leona(self):
        # Q STUN 1.25 (x1.0) + E ROOT 0.5 (x0.6) + R STUN 1.5 (x1.0) = 3.05.
        r = compute_cc_output("Leona")
        self.assertAlmostEqual(
            r.lockdown_score, 1.25 + 0.5 * 0.6 + 1.5, places=4
        )
        self.assertAlmostEqual(r.lockdown_score, 3.05, places=4)
        self.assertEqual(r.conditional_lockdown_score, 0.0)
        self.assertAlmostEqual(r.total_cc_seconds, 3.25, places=4)

    def test_amumu(self):
        # Q STUN 1.4 + R STUN 2.0, both x1.0 = 3.4.
        r = compute_cc_output("Amumu")
        self.assertAlmostEqual(r.total_lockdown_score, 3.4, places=4)

    def test_malzahar_silence_plus_suppression(self):
        # Q SILENCE 2.0 (x0.6=1.2) + R SUPPRESSION 2.5 (x1.0=2.5) = 3.7.
        r = compute_cc_output("Malzahar")
        self.assertAlmostEqual(r.lockdown_score, 3.7, places=4)

    def test_lux_root_plus_slow(self):
        # Q ROOT 3.0 (x0.6=1.8) + E SLOW 1.0 (x0.2=0.2) = 2.0.
        r = compute_cc_output("Lux")
        self.assertAlmostEqual(r.lockdown_score, 2.0, places=4)

    def test_missfortune_slow_only(self):
        # E SLOW 2.0 (x0.2) = 0.4.
        r = compute_cc_output("MissFortune")
        self.assertAlmostEqual(r.lockdown_score, 0.4, places=4)


class ConditionalDiscountTests(unittest.TestCase):
    def test_annie_all_conditional(self):
        # Annie Q/W/R all conditional STUN (Pyromania-stack gated):
        # (1.75 + 1.75 + 1.5) * 1.0 * 0.5 = 2.5; unconditional lockdown 0.0.
        r = compute_cc_output("Annie")
        self.assertEqual(r.lockdown_score, 0.0)
        self.assertEqual(r.total_cc_seconds, 0.0)
        self.assertAlmostEqual(r.conditional_lockdown_score, 2.5, places=4)
        self.assertAlmostEqual(r.total_lockdown_score, 2.5, places=4)

    def test_conditional_midpoint(self):
        self.assertEqual(_CC_OUTPUT_CONDITIONAL_PROB, 0.5)


class WeightTierTests(unittest.TestCase):
    def test_hard_disable_tier(self):
        for k in (
            "SUPPRESSION", "STUN", "AIRBORNE", "CHARM", "FEAR",
            "TAUNT", "SLEEP", "STASIS", "POLYMORPH",
        ):
            self.assertEqual(_CC_KIND_WEIGHT[k], 1.0)

    def test_restrict_tier(self):
        for k in ("ROOT", "SILENCE", "GROUND", "DISARM", "BLIND"):
            self.assertEqual(_CC_KIND_WEIGHT[k], 0.6)

    def test_displacement_tier(self):
        for k in ("KNOCKBACK", "PULL"):
            self.assertEqual(_CC_KIND_WEIGHT[k], 0.5)

    def test_soft_tier(self):
        for k in ("SLOW", "NEARSIGHT", "CRIPPLE"):
            self.assertEqual(_CC_KIND_WEIGHT[k], 0.2)


class EmptyAndShapeTests(unittest.TestCase):
    def test_blank_champion(self):
        r = compute_cc_output("")
        self.assertIsInstance(r, CcOutputResult)
        self.assertEqual(r.total_lockdown_score, 0.0)
        self.assertEqual(r.spells, ())

    def test_unregistered_champion(self):
        # MasterYi has no first-order CC -> absent from registry -> all-zero.
        r = compute_cc_output("MasterYi")
        self.assertEqual(r.total_lockdown_score, 0.0)
        self.assertEqual(r.spells, ())

    def test_to_dict_shape(self):
        d = compute_cc_output("Leona").to_dict()
        for key in (
            "champion", "mode", "lockdown_score",
            "conditional_lockdown_score", "total_lockdown_score",
            "total_cc_seconds", "spells",
        ):
            self.assertIn(key, d)
        self.assertTrue(d["spells"])
        for s in d["spells"]:
            for key in (
                "spell_key", "cc_kind", "duration_s", "kind_weight",
                "conditional", "weighted_seconds",
            ):
                self.assertIn(key, s)

    def test_mode_passthrough(self):
        r = compute_cc_output("Leona", mode="ARAM")
        self.assertEqual(r.mode, "ARAM")


class RegistryInvariantTests(unittest.TestCase):
    def test_all_kinds_have_weights(self):
        for champ, entries in _CC_OUTPUT_REGISTRY.items():
            for e in entries:
                self.assertIn(
                    e.cc_kind, _CC_KIND_WEIGHT, f"{champ} {e.spell} {e.cc_kind}"
                )

    def test_all_durations_positive(self):
        for champ, entries in _CC_OUTPUT_REGISTRY.items():
            for e in entries:
                self.assertGreater(e.duration_s, 0.0, f"{champ} {e.spell}")

    def test_all_spells_canonical(self):
        for champ, entries in _CC_OUTPUT_REGISTRY.items():
            for e in entries:
                self.assertIn(e.spell, ("P", "Q", "W", "E", "R"))

    def test_roster_coverage(self):
        # 12-agent roster fan-out: 315 entries / 161 champions. Re-running
        # tools/ds_cc_output_build.py against a fresh scan updates these pins.
        self.assertEqual(len(_CC_OUTPUT_REGISTRY), 161)
        total = sum(len(v) for v in _CC_OUTPUT_REGISTRY.values())
        self.assertEqual(total, 315)


class RouteAndVersionTests(unittest.TestCase):
    def test_cc_output_route_registered_additively(self):
        from agents.daemon_slayer import server
        self.assertIn("/cc-output", server._POST_ROUTES)
        # Additive: every existing route is still present (none replaced).
        for path in (
            "/ehp", "/rank-tank", "/hybrid", "/rank-bruiser", "/burst",
            "/hps", "/ability-dps", "/v2/matchup",
        ):
            self.assertIn(path, server._POST_ROUTES)

    def test_engine_version(self):
        self.assertEqual(ENGINE_VERSION, "1.220.0")


if __name__ == "__main__":
    unittest.main()
