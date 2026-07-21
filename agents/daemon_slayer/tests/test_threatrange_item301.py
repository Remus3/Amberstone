"""Item 301 (ENGINE 1.113.0) - effective threat-range scorer tests.

The twelfth scored axis alongside DPS / burst / EHP / ability-DPS /
healing-throughput / offensive CC-output (item 294) / mobility (item 297) /
sustain (item 298) / scaling (item 299) / wave-clear (item 300): how FAR OUT a
champion can deliver meaningful damage or CC, reduced to a single reach-weighted
``threatrange_score`` plus a ``top_band`` label and an ``is_artillery`` flag.
Proves (a) the band-weight * kind-mult * magnitude * conditional math on
synthetic entries (registry-independent), (b) hand-verified champion values at
pinned inputs (a top artillery poke mage and a melee-only juggernaut), (c) the
band -> weight + kind -> mult tiers, (d) the top_band / is_artillery identities,
(e) the GLOBAL band bonus, (f) registry invariants + roster coverage, (g) the
additive /threat-range route registers alongside (does not replace) the existing
routes, (h) the ENGINE pin.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.threatrange import (
    _THREATRANGE_BAND_WEIGHT,
    _THREATRANGE_CONDITIONAL_PROB,
    _THREATRANGE_KIND_MULT,
    _THREATRANGE_REGISTRY,
    ThreatRangeEntry,
    ThreatRangeResult,
    _mechanism_value,
    compute_threatrange,
)


class MechanismValueMathTests(unittest.TestCase):
    def test_artillery_burst_unconditional(self):
        # ARTILLERY weight 1.0, BURST mult 1.0, magnitude 0.8 -> 0.8.
        e = ThreatRangeEntry("Q", "ARTILLERY", "BURST", magnitude=0.8)
        self.assertAlmostEqual(_mechanism_value(e), 0.8, places=4)

    def test_global_band_bonus(self):
        # GLOBAL mult 1.1 lifts a full-magnitude CC threat above 1.0.
        e = ThreatRangeEntry("R", "GLOBAL", "CC", magnitude=1.0)
        self.assertAlmostEqual(_mechanism_value(e), 1.1, places=4)

    def test_melee_poke_penalty(self):
        # MELEE weight 0.15, POKE mult 0.7, magnitude 0.5 -> 0.0525.
        e = ThreatRangeEntry("Q", "MELEE", "POKE", magnitude=0.5)
        self.assertAlmostEqual(_mechanism_value(e), 0.0525, places=4)

    def test_conditional_halves_value(self):
        e = ThreatRangeEntry("R", "GLOBAL", "BURST", magnitude=0.8, conditional=True)
        self.assertAlmostEqual(_mechanism_value(e), 0.44, places=4)

    def test_unknown_band_or_kind_is_zero(self):
        self.assertEqual(
            _mechanism_value(ThreatRangeEntry("Q", "NOWHERE", "BURST", magnitude=1.0)),
            0.0,
        )
        self.assertEqual(
            _mechanism_value(ThreatRangeEntry("Q", "ARTILLERY", "NONSENSE", magnitude=1.0)),
            0.0,
        )


class HandVerifiedChampionTests(unittest.TestCase):
    # Pinned exact values; re-running tools/ds_threatrange_build.py against a
    # fresh scan updates them.
    def test_xerath_artillery_identity(self):
        # Xerath: Q/W ARTILLERY POKE + E ARTILLERY CC + R GLOBAL BURST (cond)
        # + BASE MEDIUM SUSTAINED -> 2.28, top ARTILLERY, artillery True.
        r = compute_threatrange("Xerath")
        self.assertAlmostEqual(r.threatrange_score, 2.28, places=2)
        self.assertEqual(r.top_band, "ARTILLERY")
        self.assertTrue(r.is_artillery)
        e = next(s for s in r.sources if s.source_key == "E")
        self.assertEqual(e.band, "ARTILLERY")
        self.assertAlmostEqual(e.value, 0.70, places=4)

    def test_garen_melee_only(self):
        # Garen has no ranged threat -> a small all-MELEE score, no artillery.
        r = compute_threatrange("Garen")
        self.assertAlmostEqual(r.threatrange_score, 0.3285, places=4)
        self.assertEqual(r.top_band, "MELEE")
        self.assertFalse(r.is_artillery)

    def test_ashe_global_ult_tops(self):
        # Ashe R GLOBAL CC (cond) is her single highest-value threat -> top GLOBAL.
        r = compute_threatrange("Ashe")
        self.assertEqual(r.top_band, "GLOBAL")
        self.assertTrue(r.is_artillery)
        rr = next(s for s in r.sources if s.source_key == "R")
        self.assertAlmostEqual(rr.value, 0.495, places=4)


class DirectionalTests(unittest.TestCase):
    def test_long_range_threats_score_high(self):
        for champ in ("Xerath", "Caitlyn", "Velkoz", "Lux", "Ziggs"):
            self.assertGreater(
                compute_threatrange(champ).threatrange_score, 1.5, champ
            )

    def test_melee_juggernauts_score_low(self):
        for champ in ("Garen", "Udyr", "MasterYi", "Olaf"):
            self.assertLess(
                compute_threatrange(champ).threatrange_score, 1.0, champ
            )

    def test_artillery_champs_flag_true(self):
        for champ in ("Xerath", "Ziggs", "Velkoz", "Caitlyn", "Lux"):
            self.assertTrue(compute_threatrange(champ).is_artillery, champ)


class IdentityTests(unittest.TestCase):
    def test_top_band_is_strongest_mechanism(self):
        for champ in ("Xerath", "Ashe", "Garen"):
            r = compute_threatrange(champ)
            best = max(r.sources, key=lambda s: s.value)
            self.assertEqual(r.top_band, best.band, champ)

    def test_is_artillery_flag_tracks_bands(self):
        # Xerath has ARTILLERY/GLOBAL threats -> is_artillery True.
        self.assertTrue(compute_threatrange("Xerath").is_artillery)
        # A purely sub-artillery champion is not flagged.
        for champ, entries in _THREATRANGE_REGISTRY.items():
            if entries and all(
                e.band not in ("ARTILLERY", "GLOBAL") for e in entries
            ):
                self.assertFalse(compute_threatrange(champ).is_artillery, champ)
                break

    def test_score_is_sum_of_source_values(self):
        for champ in ("Xerath", "Ashe", "Caitlyn"):
            r = compute_threatrange(champ)
            self.assertAlmostEqual(
                r.threatrange_score, sum(s.value for s in r.sources), places=6
            )


class WeightAndKindTierTests(unittest.TestCase):
    def test_band_weights(self):
        self.assertEqual(_THREATRANGE_BAND_WEIGHT["GLOBAL"], 1.1)
        self.assertEqual(_THREATRANGE_BAND_WEIGHT["ARTILLERY"], 1.0)
        self.assertEqual(_THREATRANGE_BAND_WEIGHT["LONG"], 0.75)
        self.assertEqual(_THREATRANGE_BAND_WEIGHT["MEDIUM"], 0.5)
        self.assertEqual(_THREATRANGE_BAND_WEIGHT["SHORT"], 0.3)
        self.assertEqual(_THREATRANGE_BAND_WEIGHT["MELEE"], 0.15)
        # Monotonic decreasing reach tiers.
        vals = [
            _THREATRANGE_BAND_WEIGHT[b]
            for b in ("GLOBAL", "ARTILLERY", "LONG", "MEDIUM", "SHORT", "MELEE")
        ]
        self.assertEqual(vals, sorted(vals, reverse=True))

    def test_kind_mults(self):
        self.assertEqual(_THREATRANGE_KIND_MULT["BURST"], 1.0)
        self.assertEqual(_THREATRANGE_KIND_MULT["CC"], 1.0)
        self.assertEqual(_THREATRANGE_KIND_MULT["SUSTAINED"], 0.9)
        self.assertEqual(_THREATRANGE_KIND_MULT["POKE"], 0.7)

    def test_conditional_midpoint(self):
        self.assertEqual(_THREATRANGE_CONDITIONAL_PROB, 0.5)


class EmptyAndShapeTests(unittest.TestCase):
    def test_blank_champion(self):
        r = compute_threatrange("")
        self.assertIsInstance(r, ThreatRangeResult)
        self.assertEqual(r.threatrange_score, 0.0)
        self.assertEqual(r.top_band, "")
        self.assertFalse(r.is_artillery)
        self.assertEqual(r.sources, ())

    def test_unknown_champion(self):
        r = compute_threatrange("NotAChampion")
        self.assertEqual(r.threatrange_score, 0.0)
        self.assertEqual(r.sources, ())

    def test_to_dict_shape(self):
        d = compute_threatrange("Xerath").to_dict()
        for key in (
            "champion", "mode", "threatrange_score", "top_band", "is_artillery",
            "sources",
        ):
            self.assertIn(key, d)
        self.assertTrue(d["sources"])
        for s in d["sources"]:
            for key in (
                "source_key", "band", "kind", "band_weight", "kind_mult",
                "magnitude", "conditional", "value",
            ):
                self.assertIn(key, s)

    def test_mode_passthrough(self):
        self.assertEqual(compute_threatrange("Xerath", mode="ARAM").mode, "ARAM")


class RegistryInvariantTests(unittest.TestCase):
    def test_all_bands_have_weights(self):
        for champ, entries in _THREATRANGE_REGISTRY.items():
            for e in entries:
                self.assertIn(e.band, _THREATRANGE_BAND_WEIGHT, f"{champ} {e.source}")

    def test_all_kinds_valid(self):
        for champ, entries in _THREATRANGE_REGISTRY.items():
            for e in entries:
                self.assertIn(e.kind, _THREATRANGE_KIND_MULT, f"{champ} {e.source}")

    def test_all_sources_canonical(self):
        for champ, entries in _THREATRANGE_REGISTRY.items():
            for e in entries:
                self.assertIn(e.source, ("P", "Q", "W", "E", "R", "BASE"))

    def test_magnitudes_in_range(self):
        for champ, entries in _THREATRANGE_REGISTRY.items():
            for e in entries:
                self.assertTrue(0.0 < e.magnitude <= 1.0, f"{champ} {e.source}")

    def test_one_entry_per_champion_source(self):
        for champ, entries in _THREATRANGE_REGISTRY.items():
            slots = [e.source for e in entries]
            self.assertEqual(len(slots), len(set(slots)), champ)

    def test_roster_coverage(self):
        # 10-channel roster fan-out: 725 entries / 171 champions (full roster),
        # 33 GLOBAL + 71 ARTILLERY mechanisms. Re-running
        # tools/ds_threatrange_build.py against a fresh scan updates these.
        self.assertEqual(len(_THREATRANGE_REGISTRY), 171)
        total = sum(len(v) for v in _THREATRANGE_REGISTRY.values())
        self.assertEqual(total, 725)
        global_count = sum(
            1 for v in _THREATRANGE_REGISTRY.values()
            for e in v if e.band == "GLOBAL"
        )
        self.assertEqual(global_count, 33)
        artillery_count = sum(
            1 for v in _THREATRANGE_REGISTRY.values()
            for e in v if e.band == "ARTILLERY"
        )
        self.assertEqual(artillery_count, 71)


class RouteAndVersionTests(unittest.TestCase):
    def test_threatrange_route_registered_additively(self):
        from agents.daemon_slayer import server
        self.assertIn("/threat-range", server._POST_ROUTES)
        self.assertIn("/threat-range", server._GET_DISPATCH_ROUTES)
        # Additive: every existing route is still present (none replaced).
        for path in (
            "/waveclear", "/scaling", "/sustain", "/mobility", "/cc-output",
            "/ehp", "/rank-tank", "/hybrid", "/burst", "/hps", "/ability-dps",
            "/v2/matchup",
        ):
            self.assertIn(path, server._POST_ROUTES)

    def test_engine_version(self):
        self.assertEqual(ENGINE_VERSION, "1.238.0")


if __name__ == "__main__":
    unittest.main()
