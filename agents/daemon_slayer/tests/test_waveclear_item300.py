"""Item 300 (ENGINE 1.112.0) - wave-clear / AoE-shove scorer tests.

The eleventh scored axis alongside DPS / burst / EHP / ability-DPS /
healing-throughput / offensive CC-output (item 294) / mobility (item 297) /
sustain (item 298) / scaling (item 299): how fast and how safely a champion
clears a minion wave and shoves a lane, reduced to a single range-weighted
``waveclear_score`` plus a ``top_kind`` label and a ``ranged_shove`` flag.
Proves (a) the kind-weight * range-mult * magnitude * conditional math on
synthetic entries (registry-independent), (b) hand-verified champion values at
pinned inputs (a top ranged FULL_AOE shover and a no-AoE last-hitter), (c) the
kind -> weight + range -> mult tiers, (d) the top_kind / ranged_shove identities,
(e) the GLOBAL range bonus, (f) registry invariants + roster coverage, (g) the
additive /waveclear route registers alongside (does not replace) the existing
routes, (h) the ENGINE pin.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.waveclear import (
    _WAVECLEAR_CONDITIONAL_PROB,
    _WAVECLEAR_KIND_WEIGHT,
    _WAVECLEAR_RANGE_MULT,
    _WAVECLEAR_REGISTRY,
    WaveclearEntry,
    WaveclearResult,
    _mechanism_value,
    compute_waveclear,
)


class MechanismValueMathTests(unittest.TestCase):
    def test_full_aoe_ranged_unconditional(self):
        # FULL_AOE weight 1.0, RANGED mult 1.0, magnitude 0.9 -> 0.9.
        e = WaveclearEntry("Q", "FULL_AOE", "RANGED", magnitude=0.9)
        self.assertAlmostEqual(_mechanism_value(e), 0.9, places=4)

    def test_global_band_bonus(self):
        # GLOBAL mult 1.1 lifts a full-magnitude FULL_AOE above 1.0.
        e = WaveclearEntry("Q", "FULL_AOE", "GLOBAL", magnitude=1.0)
        self.assertAlmostEqual(_mechanism_value(e), 1.1, places=4)

    def test_melee_band_penalty(self):
        # AOE_DOT weight 0.85, MELEE mult 0.7, magnitude 0.5 -> 0.2975.
        e = WaveclearEntry("W", "AOE_DOT", "MELEE", magnitude=0.5)
        self.assertAlmostEqual(_mechanism_value(e), 0.2975, places=4)

    def test_conditional_halves_value(self):
        e = WaveclearEntry("R", "FULL_AOE", "RANGED", magnitude=0.8, conditional=True)
        self.assertAlmostEqual(_mechanism_value(e), 0.4, places=4)

    def test_unknown_kind_or_band_is_zero(self):
        self.assertEqual(
            _mechanism_value(WaveclearEntry("Q", "NONSENSE", "RANGED", magnitude=1.0)),
            0.0,
        )
        self.assertEqual(
            _mechanism_value(WaveclearEntry("Q", "FULL_AOE", "NOWHERE", magnitude=1.0)),
            0.0,
        )


class HandVerifiedChampionTests(unittest.TestCase):
    # Pinned exact values; re-running tools/ds_waveclear_build.py against a fresh
    # scan updates them.
    def test_zilean_single_full_aoe(self):
        # Zilean: one Q FULL_AOE RANGED (magnitude 0.85) -> 1.0 * 1.0 * 0.85.
        r = compute_waveclear("Zilean")
        self.assertAlmostEqual(r.waveclear_score, 0.85, places=4)
        self.assertEqual(r.top_kind, "FULL_AOE")
        self.assertTrue(r.ranged_shove)

    def test_ziggs_global_q_plus_kit(self):
        # Ziggs: Q FULL_AOE GLOBAL 0.9 (=0.99) + W MULTI_HIT RANGED 0.4 (=0.24)
        # + E AOE_DOT RANGED 0.7 (=0.595) -> 1.825, top FULL_AOE.
        r = compute_waveclear("Ziggs")
        self.assertAlmostEqual(r.waveclear_score, 1.825, places=3)
        self.assertEqual(r.top_kind, "FULL_AOE")
        q = next(s for s in r.sources if s.source_key == "Q")
        self.assertEqual(q.range_band, "GLOBAL")
        self.assertAlmostEqual(q.value, 0.99, places=4)

    def test_no_aoe_last_hitter_scores_low(self):
        # Vayne has no wave-clear AoE -> a tiny single-target score.
        r = compute_waveclear("Vayne")
        self.assertLess(r.waveclear_score, 0.2)


class DirectionalTests(unittest.TestCase):
    def test_dedicated_shovers_score_high(self):
        for champ in ("Zyra", "Ziggs", "Heimerdinger", "AurelionSol", "Brand"):
            self.assertGreater(
                compute_waveclear(champ).waveclear_score, 1.0, champ
            )

    def test_single_target_champs_score_low(self):
        for champ in ("Vayne", "Yuumi", "Warwick", "Braum", "Blitzcrank"):
            self.assertLess(
                compute_waveclear(champ).waveclear_score, 0.3, champ
            )


class IdentityTests(unittest.TestCase):
    def test_top_kind_is_strongest_mechanism(self):
        for champ in ("Ziggs", "Zyra", "Zed"):
            r = compute_waveclear(champ)
            best = max(r.sources, key=lambda s: s.value)
            self.assertEqual(r.top_kind, best.kind, champ)

    def test_ranged_shove_flag_tracks_bands(self):
        # Ziggs has a GLOBAL/RANGED clear -> ranged_shove True.
        self.assertTrue(compute_waveclear("Ziggs").ranged_shove)
        # A purely MELEE-band clearer is not a ranged shover.
        for champ, entries in _WAVECLEAR_REGISTRY.items():
            if entries and all(e.range_band == "MELEE" for e in entries):
                self.assertFalse(compute_waveclear(champ).ranged_shove, champ)
                break

    def test_score_is_sum_of_source_values(self):
        for champ in ("Ziggs", "Zyra", "Brand"):
            r = compute_waveclear(champ)
            self.assertAlmostEqual(
                r.waveclear_score, sum(s.value for s in r.sources), places=6
            )


class WeightAndRangeTierTests(unittest.TestCase):
    def test_kind_weights(self):
        self.assertEqual(_WAVECLEAR_KIND_WEIGHT["FULL_AOE"], 1.0)
        self.assertEqual(_WAVECLEAR_KIND_WEIGHT["AOE_DOT"], 0.85)
        self.assertEqual(_WAVECLEAR_KIND_WEIGHT["MULTI_HIT"], 0.6)
        self.assertEqual(_WAVECLEAR_KIND_WEIGHT["CLEAVE_AA"], 0.5)
        self.assertEqual(_WAVECLEAR_KIND_WEIGHT["SINGLE_TARGET"], 0.25)

    def test_range_mults(self):
        self.assertEqual(_WAVECLEAR_RANGE_MULT["GLOBAL"], 1.1)
        self.assertEqual(_WAVECLEAR_RANGE_MULT["RANGED"], 1.0)
        self.assertEqual(_WAVECLEAR_RANGE_MULT["MELEE"], 0.7)
        # GLOBAL rewards, MELEE penalises relative to the RANGED baseline.
        self.assertGreater(_WAVECLEAR_RANGE_MULT["GLOBAL"], _WAVECLEAR_RANGE_MULT["RANGED"])
        self.assertLess(_WAVECLEAR_RANGE_MULT["MELEE"], _WAVECLEAR_RANGE_MULT["RANGED"])

    def test_conditional_midpoint(self):
        self.assertEqual(_WAVECLEAR_CONDITIONAL_PROB, 0.5)


class EmptyAndShapeTests(unittest.TestCase):
    def test_blank_champion(self):
        r = compute_waveclear("")
        self.assertIsInstance(r, WaveclearResult)
        self.assertEqual(r.waveclear_score, 0.0)
        self.assertEqual(r.top_kind, "")
        self.assertFalse(r.ranged_shove)
        self.assertEqual(r.sources, ())

    def test_unknown_champion(self):
        r = compute_waveclear("NotAChampion")
        self.assertEqual(r.waveclear_score, 0.0)
        self.assertEqual(r.sources, ())

    def test_to_dict_shape(self):
        d = compute_waveclear("Ziggs").to_dict()
        for key in (
            "champion", "mode", "waveclear_score", "top_kind", "ranged_shove",
            "sources",
        ):
            self.assertIn(key, d)
        self.assertTrue(d["sources"])
        for s in d["sources"]:
            for key in (
                "source_key", "kind", "range_band", "kind_weight", "range_mult",
                "magnitude", "conditional", "value",
            ):
                self.assertIn(key, s)

    def test_mode_passthrough(self):
        self.assertEqual(compute_waveclear("Ziggs", mode="ARAM").mode, "ARAM")


class RegistryInvariantTests(unittest.TestCase):
    def test_all_kinds_have_weights(self):
        for champ, entries in _WAVECLEAR_REGISTRY.items():
            for e in entries:
                self.assertIn(e.kind, _WAVECLEAR_KIND_WEIGHT, f"{champ} {e.source}")

    def test_all_bands_valid(self):
        for champ, entries in _WAVECLEAR_REGISTRY.items():
            for e in entries:
                self.assertIn(e.range_band, _WAVECLEAR_RANGE_MULT, f"{champ} {e.source}")

    def test_all_sources_canonical(self):
        for champ, entries in _WAVECLEAR_REGISTRY.items():
            for e in entries:
                self.assertIn(e.source, ("P", "Q", "W", "E", "R", "BASE"))

    def test_magnitudes_in_range(self):
        for champ, entries in _WAVECLEAR_REGISTRY.items():
            for e in entries:
                self.assertTrue(0.0 < e.magnitude <= 1.0, f"{champ} {e.source}")

    def test_one_entry_per_champion_source(self):
        for champ, entries in _WAVECLEAR_REGISTRY.items():
            slots = [e.source for e in entries]
            self.assertEqual(len(slots), len(set(slots)), champ)

    def test_roster_coverage(self):
        # 10-channel roster fan-out: 376 entries / 171 champions (full roster),
        # 4 GLOBAL-band mechanisms. Re-running tools/ds_waveclear_build.py against
        # a fresh scan updates these.
        self.assertEqual(len(_WAVECLEAR_REGISTRY), 171)
        total = sum(len(v) for v in _WAVECLEAR_REGISTRY.values())
        self.assertEqual(total, 376)
        global_count = sum(
            1 for v in _WAVECLEAR_REGISTRY.values()
            for e in v if e.range_band == "GLOBAL"
        )
        self.assertEqual(global_count, 4)


class RouteAndVersionTests(unittest.TestCase):
    def test_waveclear_route_registered_additively(self):
        from agents.daemon_slayer import server
        self.assertIn("/waveclear", server._POST_ROUTES)
        self.assertIn("/waveclear", server._GET_DISPATCH_ROUTES)
        # Additive: every existing route is still present (none replaced).
        for path in (
            "/scaling", "/sustain", "/mobility", "/cc-output", "/ehp",
            "/rank-tank", "/hybrid", "/burst", "/hps", "/ability-dps",
            "/v2/matchup",
        ):
            self.assertIn(path, server._POST_ROUTES)

    def test_engine_version(self):
        self.assertEqual(ENGINE_VERSION, "1.255.0")


if __name__ == "__main__":
    unittest.main()
