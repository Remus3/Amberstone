"""Item 299 (ENGINE 1.111.0) - scaling / power-curve scorer tests.

The tenth scored axis alongside DPS / burst / EHP / ability-DPS /
healing-throughput / offensive CC-output (item 294) / mobility (item 297) /
sustain (item 298): a champion's power TRAJECTORY across the game, reduced to an
early / mid / late power triple plus a signed ``scaling_slope`` (late - early).
Proves (a) the per-kind ramp + online gate + conditional discount math on
synthetic entries (registry-independent), (b) hand-verified champion values at
pinned inputs (a ramping hypercarry and a decaying early bully), (c) the
kind -> weight tiers + the ramp table, (d) the score/slope identities, (e) the
LATE-online gate (no early/mid contribution), (f) registry invariants + roster
coverage, (g) the additive /scaling route registers alongside (does not replace)
the existing routes, (h) the ENGINE pin.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.scaling import (
    _SCALING_CONDITIONAL_PROB,
    _SCALING_KIND_WEIGHT,
    _SCALING_REGISTRY,
    _SCALING_STAGE_RAMP,
    _STAGE_INDEX,
    ScalingEntry,
    ScalingResult,
    _stage_contribution,
    compute_scaling,
)


class StageContributionMathTests(unittest.TestCase):
    def test_infinite_stack_ramp_unconditional(self):
        # INFINITE_STACK weight 1.0, ramp (0.3, 0.65, 1.0), magnitude 1.0.
        e = ScalingEntry("P", "INFINITE_STACK", "EARLY", magnitude=1.0)
        self.assertAlmostEqual(_stage_contribution(e, 0), 0.30, places=4)
        self.assertAlmostEqual(_stage_contribution(e, 1), 0.65, places=4)
        self.assertAlmostEqual(_stage_contribution(e, 2), 1.00, places=4)

    def test_conditional_halves_contribution(self):
        e = ScalingEntry("P", "INFINITE_STACK", "EARLY", magnitude=1.0, conditional=True)
        self.assertAlmostEqual(_stage_contribution(e, 0), 0.15, places=4)
        self.assertAlmostEqual(_stage_contribution(e, 2), 0.50, places=4)

    def test_online_gate_blocks_earlier_stages(self):
        # A LATE-online mechanism contributes nothing to early (0) or mid (1).
        e = ScalingEntry("R", "FORM_SPIKE", "LATE", magnitude=1.0)
        self.assertEqual(_stage_contribution(e, 0), 0.0)
        self.assertEqual(_stage_contribution(e, 1), 0.0)
        self.assertAlmostEqual(_stage_contribution(e, 2), 0.8, places=4)

    def test_early_frontload_decays(self):
        # EARLY_FRONTLOAD weight 0.4, ramp (1.0, 0.55, 0.25), magnitude 0.9.
        e = ScalingEntry("BASE", "EARLY_FRONTLOAD", "EARLY", magnitude=0.9)
        self.assertAlmostEqual(_stage_contribution(e, 0), 0.36, places=4)
        self.assertAlmostEqual(_stage_contribution(e, 1), 0.198, places=4)
        self.assertAlmostEqual(_stage_contribution(e, 2), 0.09, places=4)

    def test_unknown_kind_is_zero(self):
        e = ScalingEntry("Q", "NONSENSE", "EARLY", magnitude=1.0)
        self.assertEqual(_stage_contribution(e, 0), 0.0)


class HandVerifiedChampionTests(unittest.TestCase):
    def test_veigar_infinite_stack_curve(self):
        # Veigar: a single P INFINITE_STACK (magnitude 1.0) - the canonical
        # ramping hypercarry. early 0.30 -> mid 0.65 -> late 1.00, slope +0.70.
        r = compute_scaling("Veigar")
        self.assertAlmostEqual(r.early_power, 0.30, places=3)
        self.assertAlmostEqual(r.mid_power, 0.65, places=3)
        self.assertAlmostEqual(r.late_power, 1.00, places=3)
        self.assertAlmostEqual(r.scaling_score, 1.00, places=3)
        self.assertAlmostEqual(r.scaling_slope, 0.70, places=3)

    def test_renekton_frontload_negative_slope(self):
        # Renekton: a single EARLY_FRONTLOAD (magnitude 0.9) - the canonical
        # decaying lane bully. early 0.36 -> late 0.09, NEGATIVE slope.
        r = compute_scaling("Renekton")
        self.assertAlmostEqual(r.early_power, 0.36, places=3)
        self.assertAlmostEqual(r.late_power, 0.09, places=3)
        self.assertLess(r.scaling_slope, 0.0)

    def test_late_online_carry_has_no_early_power(self):
        # Vayne is classified RATIO_HYPERSCALE online LATE -> zero early/mid.
        r = compute_scaling("Vayne")
        self.assertEqual(r.early_power, 0.0)
        self.assertEqual(r.mid_power, 0.0)
        self.assertGreater(r.late_power, 0.0)


class DirectionalTests(unittest.TestCase):
    def test_hypercarries_scale_up(self):
        for champ in ("Nasus", "Kayle", "Karthus", "AurelionSol", "Veigar"):
            self.assertGreater(
                compute_scaling(champ).scaling_slope, 0.3, champ
            )

    def test_early_bullies_fall_off(self):
        for champ in ("Renekton", "Draven", "Pantheon", "LeeSin"):
            self.assertLess(compute_scaling(champ).scaling_slope, 0.0, champ)


class IdentityTests(unittest.TestCase):
    def test_score_is_late_power(self):
        for champ in ("Nasus", "Renekton", "Veigar", "Garen"):
            r = compute_scaling(champ)
            self.assertEqual(r.scaling_score, r.late_power)

    def test_slope_is_late_minus_early(self):
        for champ in ("Nasus", "Renekton", "Veigar", "Malphite"):
            r = compute_scaling(champ)
            self.assertAlmostEqual(
                r.scaling_slope, r.late_power - r.early_power, places=6
            )


class WeightAndRampTierTests(unittest.TestCase):
    def test_kind_weights(self):
        self.assertEqual(_SCALING_KIND_WEIGHT["INFINITE_STACK"], 1.0)
        self.assertEqual(_SCALING_KIND_WEIGHT["FORM_SPIKE"], 0.8)
        self.assertEqual(_SCALING_KIND_WEIGHT["RATIO_HYPERSCALE"], 0.8)
        self.assertEqual(_SCALING_KIND_WEIGHT["ITEM_RELIANT"], 0.5)
        self.assertEqual(_SCALING_KIND_WEIGHT["EARLY_FRONTLOAD"], 0.4)

    def test_ramp_shapes(self):
        self.assertEqual(_SCALING_STAGE_RAMP["FORM_SPIKE"], (1.0, 1.0, 1.0))
        # ramping kinds end at 1.0 late; frontload decays below its early value.
        for kind in ("INFINITE_STACK", "RATIO_HYPERSCALE", "ITEM_RELIANT"):
            self.assertEqual(_SCALING_STAGE_RAMP[kind][2], 1.0)
        front = _SCALING_STAGE_RAMP["EARLY_FRONTLOAD"]
        self.assertEqual(front[0], 1.0)
        self.assertLess(front[2], front[0])

    def test_conditional_midpoint(self):
        self.assertEqual(_SCALING_CONDITIONAL_PROB, 0.5)

    def test_stage_index(self):
        self.assertEqual(_STAGE_INDEX, {"EARLY": 0, "MID": 1, "LATE": 2})


class EmptyAndShapeTests(unittest.TestCase):
    def test_blank_champion(self):
        r = compute_scaling("")
        self.assertIsInstance(r, ScalingResult)
        self.assertEqual(r.scaling_score, 0.0)
        self.assertEqual(r.scaling_slope, 0.0)
        self.assertEqual(r.sources, ())

    def test_unknown_champion(self):
        r = compute_scaling("NotAChampion")
        self.assertEqual(r.scaling_score, 0.0)
        self.assertEqual(r.sources, ())

    def test_to_dict_shape(self):
        d = compute_scaling("Nasus").to_dict()
        for key in (
            "champion", "mode", "early_power", "mid_power", "late_power",
            "scaling_score", "scaling_slope", "sources",
        ):
            self.assertIn(key, d)
        self.assertTrue(d["sources"])
        for s in d["sources"]:
            for key in (
                "source_key", "kind", "online_stage", "kind_weight",
                "magnitude", "conditional", "early", "mid", "late",
            ):
                self.assertIn(key, s)

    def test_mode_passthrough(self):
        self.assertEqual(compute_scaling("Nasus", mode="ARAM").mode, "ARAM")


class RegistryInvariantTests(unittest.TestCase):
    def test_all_kinds_have_weights(self):
        for champ, entries in _SCALING_REGISTRY.items():
            for e in entries:
                self.assertIn(e.kind, _SCALING_KIND_WEIGHT, f"{champ} {e.source}")

    def test_all_sources_canonical(self):
        for champ, entries in _SCALING_REGISTRY.items():
            for e in entries:
                self.assertIn(e.source, ("P", "Q", "W", "E", "R", "BASE"))

    def test_all_stages_valid(self):
        for champ, entries in _SCALING_REGISTRY.items():
            for e in entries:
                self.assertIn(e.online_stage, ("EARLY", "MID", "LATE"))

    def test_magnitudes_in_range(self):
        for champ, entries in _SCALING_REGISTRY.items():
            for e in entries:
                self.assertTrue(0.0 < e.magnitude <= 1.0, f"{champ} {e.source}")

    def test_one_entry_per_champion_source(self):
        for champ, entries in _SCALING_REGISTRY.items():
            slots = [e.source for e in entries]
            self.assertEqual(len(slots), len(set(slots)), champ)

    def test_roster_coverage(self):
        # 10-channel roster fan-out: 258 entries / 171 champions (full roster).
        # Re-running tools/ds_scaling_build.py against a fresh scan updates these.
        self.assertEqual(len(_SCALING_REGISTRY), 171)
        total = sum(len(v) for v in _SCALING_REGISTRY.values())
        self.assertEqual(total, 258)


class RouteAndVersionTests(unittest.TestCase):
    def test_scaling_route_registered_additively(self):
        from agents.daemon_slayer import server
        self.assertIn("/scaling", server._POST_ROUTES)
        self.assertIn("/scaling", server._GET_DISPATCH_ROUTES)
        # Additive: every existing route is still present (none replaced).
        for path in (
            "/sustain", "/mobility", "/cc-output", "/ehp", "/rank-tank",
            "/hybrid", "/burst", "/hps", "/ability-dps", "/v2/matchup",
        ):
            self.assertIn(path, server._POST_ROUTES)

    def test_engine_version(self):
        self.assertEqual(ENGINE_VERSION, "1.209.0")


if __name__ == "__main__":
    unittest.main()
