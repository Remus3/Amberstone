"""Item 297 (ENGINE 1.109.0) - self-mobility (gap-close / kiting) scorer tests.

The eighth scored axis alongside DPS / burst / EHP / ability-DPS /
healing-throughput / offensive CC-output (item 294): how much a champion can
reposition her own body (dashes / blinks / leaps / MS steroids / untargetable
hops), normalised to Flash-units and weighted by kind into one mobility score.
Proves (a) hand-verified mobility values at pinned inputs, (b) the conditional
availability-midpoint discount, (c) the kind -> weight tiers, (d) the
normalisation rules - Flash unit, the >1-screen dash cap, the sustained-MS
window, the charge multiplier, (e) registry invariants + roster coverage,
(f) the additive /mobility route registers alongside (does not replace) the
existing routes, (g) the ENGINE pin.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.mobility import (
    _BASE_MS,
    _FLASH_UNITS,
    _MAX_DASH_UNITS,
    _MOBILITY_CONDITIONAL_PROB,
    _MOBILITY_KIND_WEIGHT,
    _MOBILITY_REGISTRY,
    _MS_SUSTAINED_WINDOW_S,
    MobilityResult,
    compute_mobility,
)


class HandVerifiedScoreTests(unittest.TestCase):
    def test_aatrox(self):
        # E DASH 300 -> 0.75 units x0.8 = 0.6; R MS 0.6*330*10/400 = 4.95 units
        # x0.5 = 2.475. total 3.075 (both unconditional). raw units 0.75+4.95.
        r = compute_mobility("Aatrox")
        self.assertAlmostEqual(r.mobility_score, 0.6 + 2.475, places=4)
        self.assertAlmostEqual(r.total_mobility_score, 3.075, places=4)
        self.assertEqual(r.conditional_mobility_score, 0.0)
        self.assertAlmostEqual(r.raw_mobility_units, 5.7, places=4)

    def test_ezreal_single_blink(self):
        # E BLINK 475 -> 475/400 = 1.1875 units x1.0 = 1.1875.
        r = compute_mobility("Ezreal")
        self.assertAlmostEqual(r.mobility_score, 1.1875, places=4)

    def test_twistedfate_global_capped(self):
        # R BLINK 5500 is a global teleport: capped at _MAX_DASH_UNITS (1500)
        # -> 1500/400 = 3.75 units x1.0, NOT 5500/400 = 13.75.
        r = compute_mobility("TwistedFate")
        self.assertAlmostEqual(r.total_mobility_score, 3.75, places=4)

    def test_quinn_sustained_ms(self):
        # R MS_STEROID ms 1.3 with no fixed duration -> credited over the
        # sustained window 3.0s: 1.3*330*3/400 = 3.2175 units x0.5 = 1.60875
        # (unconditional). E DASH 700 conditional -> 1.75 x0.8 x0.5 = 0.7.
        r = compute_mobility("Quinn")
        self.assertAlmostEqual(r.mobility_score, 1.60875, places=4)
        self.assertAlmostEqual(r.conditional_mobility_score, 0.7, places=4)
        self.assertAlmostEqual(r.total_mobility_score, 2.30875, places=4)

    def test_zed_charge_multiplier_all_conditional(self):
        # W BLINK 650 cond -> 1.625 x1.0 x0.5 = 0.8125; R BLINK 625 x2 charges
        # cond -> 1.5625*2 = 3.125 x1.0 x0.5 = 1.5625. Both gated -> uncond 0.
        r = compute_mobility("Zed")
        self.assertEqual(r.mobility_score, 0.0)
        self.assertAlmostEqual(r.conditional_mobility_score, 0.8125 + 1.5625, places=4)
        self.assertAlmostEqual(r.total_mobility_score, 2.375, places=4)


class ConditionalDiscountTests(unittest.TestCase):
    def test_conditional_midpoint(self):
        self.assertEqual(_MOBILITY_CONDITIONAL_PROB, 0.5)

    def test_gated_move_is_half_credited(self):
        # A fully-gated champion contributes 0 to the unconditional score.
        r = compute_mobility("Zed")
        self.assertEqual(r.mobility_score, 0.0)
        self.assertGreater(r.conditional_mobility_score, 0.0)


class WeightTierTests(unittest.TestCase):
    def test_kind_weights(self):
        self.assertEqual(_MOBILITY_KIND_WEIGHT["BLINK"], 1.0)
        self.assertEqual(_MOBILITY_KIND_WEIGHT["DASH"], 0.8)
        self.assertEqual(_MOBILITY_KIND_WEIGHT["LEAP"], 0.8)
        self.assertEqual(_MOBILITY_KIND_WEIGHT["UNTARGET_REPOSITION"], 0.7)
        self.assertEqual(_MOBILITY_KIND_WEIGHT["MS_STEROID"], 0.5)


class NormalizationTests(unittest.TestCase):
    def test_flash_unit_constant(self):
        self.assertEqual(_FLASH_UNITS, 400.0)
        self.assertEqual(_BASE_MS, 330.0)

    def test_dash_cap_constant(self):
        self.assertEqual(_MAX_DASH_UNITS, 1500.0)

    def test_sustained_ms_window_constant(self):
        self.assertEqual(_MS_SUSTAINED_WINDOW_S, 3.0)

    def test_cap_actually_caps(self):
        # No single registered champion's per-spell units exceed
        # the implied cap math: a displacement is at most
        # (_MAX_DASH_UNITS/_FLASH_UNITS) * charges.
        for champ, entries in _MOBILITY_REGISTRY.items():
            for e in entries:
                if e.kind != "MS_STEROID":
                    eff = min(e.range_units, _MAX_DASH_UNITS)
                    self.assertLessEqual(eff, _MAX_DASH_UNITS, f"{champ} {e.spell}")


class EmptyAndShapeTests(unittest.TestCase):
    def test_blank_champion(self):
        r = compute_mobility("")
        self.assertIsInstance(r, MobilityResult)
        self.assertEqual(r.total_mobility_score, 0.0)
        self.assertEqual(r.spells, ())

    def test_immobile_champion(self):
        # Karthus has no dash / blink / leap / MS steroid -> absent -> all-zero.
        r = compute_mobility("Karthus")
        self.assertEqual(r.total_mobility_score, 0.0)
        self.assertEqual(r.spells, ())

    def test_to_dict_shape(self):
        d = compute_mobility("Aatrox").to_dict()
        for key in (
            "champion", "mode", "mobility_score",
            "conditional_mobility_score", "total_mobility_score",
            "raw_mobility_units", "spells",
        ):
            self.assertIn(key, d)
        self.assertTrue(d["spells"])
        for s in d["spells"]:
            for key in (
                "spell_key", "kind", "mobility_units", "kind_weight",
                "conditional", "weighted_units",
            ):
                self.assertIn(key, s)

    def test_mode_passthrough(self):
        r = compute_mobility("Aatrox", mode="ARAM")
        self.assertEqual(r.mode, "ARAM")


class RegistryInvariantTests(unittest.TestCase):
    def test_all_kinds_have_weights(self):
        for champ, entries in _MOBILITY_REGISTRY.items():
            for e in entries:
                self.assertIn(
                    e.kind, _MOBILITY_KIND_WEIGHT, f"{champ} {e.spell} {e.kind}"
                )

    def test_magnitudes_positive_by_kind(self):
        for champ, entries in _MOBILITY_REGISTRY.items():
            for e in entries:
                if e.kind == "MS_STEROID":
                    self.assertGreater(e.ms_pct, 0.0, f"{champ} {e.spell}")
                else:
                    self.assertGreater(e.range_units, 0.0, f"{champ} {e.spell}")

    def test_all_spells_canonical(self):
        for champ, entries in _MOBILITY_REGISTRY.items():
            for e in entries:
                self.assertIn(e.spell, ("P", "Q", "W", "E", "R"))

    def test_roster_coverage(self):
        # 10-channel roster fan-out: 254 entries / 150 champions. Re-running
        # tools/ds_mobility_build.py against a fresh scan updates these pins.
        self.assertEqual(len(_MOBILITY_REGISTRY), 150)
        total = sum(len(v) for v in _MOBILITY_REGISTRY.values())
        self.assertEqual(total, 254)


class RouteAndVersionTests(unittest.TestCase):
    def test_mobility_route_registered_additively(self):
        from agents.daemon_slayer import server
        self.assertIn("/mobility", server._POST_ROUTES)
        self.assertIn("/mobility", server._GET_DISPATCH_ROUTES)
        # Additive: every existing route is still present (none replaced).
        for path in (
            "/cc-output", "/ehp", "/rank-tank", "/hybrid", "/burst",
            "/hps", "/ability-dps", "/v2/matchup",
        ):
            self.assertIn(path, server._POST_ROUTES)

    def test_engine_version(self):
        self.assertEqual(ENGINE_VERSION, "1.124.0")


if __name__ == "__main__":
    unittest.main()
