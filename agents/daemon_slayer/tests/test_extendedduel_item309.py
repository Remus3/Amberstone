"""Item 309 (ENGINE 1.118.0) - extended-dueling / 1v1 sustained-fight scorer tests.

The seventeenth scored axis alongside DPS / burst / EHP / ability-DPS /
healing-throughput / offensive CC-output (item 294) / mobility (item 297) /
sustain (item 298) / scaling (item 299) / wave-clear (item 300) / effective
threat-range (item 301) / zone-control (item 302) / objective-damage (item 303) /
ally-amplification (item 304) / anti-tank (item 308): how well a champion's OWN
KIT wins a PROLONGED 1v1 duel past the burst window (the RAMP / RESET / DUELHEAL /
ENDURE attrition tools it brings), reduced to a single kind-weighted,
cadence-scaled ``duel_score`` plus a ``top_kind`` label and a ``ramps`` flag.
Proves (a) the kind-weight * cadence-mult * magnitude * conditional math on
synthetic entries (registry-independent), (b) hand-verified champion values at
pinned inputs (a single-mechanism RESET, a single-mechanism RAMP, a dual-kind
ramper, a multi-tool duelist), (c) the kind -> weight + cadence -> mult tiers,
(d) the top_kind / ramps identities, (e) the SELECTIVE contract (a burst /
artillery / utility champion scores 0.0), (f) the dual-kind-per-slot allowance,
(g) registry invariants + coverage, (h) the additive /extended-duel route
registers alongside (does not replace) the existing routes, (i) the ENGINE pin.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.extendedduel import (
    _EXTENDEDDUEL_CADENCE_MULT,
    _EXTENDEDDUEL_CONDITIONAL_PROB,
    _EXTENDEDDUEL_KIND_WEIGHT,
    _EXTENDEDDUEL_REGISTRY,
    ExtendedDuelEntry,
    ExtendedDuelResult,
    _mechanism_value,
    compute_extendedduel,
)


class MechanismValueMathTests(unittest.TestCase):
    def test_ramp_sustained_unconditional(self):
        # RAMP weight 1.0, SUSTAINED mult 1.0, magnitude 1.0 -> 1.0.
        e = ExtendedDuelEntry("E", "RAMP", "SUSTAINED", magnitude=1.0)
        self.assertAlmostEqual(_mechanism_value(e), 1.0, places=4)

    def test_reset_periodic(self):
        # RESET weight 0.85, PERIODIC mult 0.8, magnitude 0.5 -> 0.34.
        e = ExtendedDuelEntry("Q", "RESET", "PERIODIC", magnitude=0.5)
        self.assertAlmostEqual(_mechanism_value(e), 0.34, places=4)

    def test_duelheal_burst(self):
        # DUELHEAL weight 0.75, BURST mult 0.65, magnitude 0.6 -> 0.2925.
        e = ExtendedDuelEntry("W", "DUELHEAL", "BURST", magnitude=0.6)
        self.assertAlmostEqual(_mechanism_value(e), 0.2925, places=4)

    def test_endure_sustained_lowest_kind(self):
        # ENDURE weight 0.6, SUSTAINED mult 1.0, magnitude 1.0 -> 0.6.
        e = ExtendedDuelEntry("P", "ENDURE", "SUSTAINED", magnitude=1.0)
        self.assertAlmostEqual(_mechanism_value(e), 0.6, places=4)

    def test_conditional_halves_value(self):
        e = ExtendedDuelEntry("R", "RAMP", "SUSTAINED", magnitude=1.0, conditional=True)
        self.assertAlmostEqual(_mechanism_value(e), 0.5, places=4)

    def test_unknown_kind_or_cadence_is_zero(self):
        self.assertEqual(
            _mechanism_value(ExtendedDuelEntry("Q", "NOPE", "SUSTAINED", magnitude=1.0)),
            0.0,
        )
        self.assertEqual(
            _mechanism_value(ExtendedDuelEntry("Q", "RAMP", "ALWAYS", magnitude=1.0)),
            0.0,
        )


class HandVerifiedChampionTests(unittest.TestCase):
    # Pinned exact values; re-running tools/ds_extendedduel_build.py against a
    # fresh scan updates them.
    def test_kalista_single_ramp(self):
        # Kalista RAMP SUSTAINED 0.65 -> 0.65; top RAMP, ramps True.
        r = compute_extendedduel("Kalista")
        self.assertAlmostEqual(r.duel_score, 0.65, places=4)
        self.assertEqual(r.top_kind, "RAMP")
        self.assertTrue(r.ramps)

    def test_cassiopeia_single_reset(self):
        # Cassiopeia RESET PERIODIC 0.9 -> 0.85*0.8*0.9 = 0.612; top RESET,
        # ramps False (no RAMP mechanism).
        r = compute_extendedduel("Cassiopeia")
        self.assertAlmostEqual(r.duel_score, 0.612, places=4)
        self.assertEqual(r.top_kind, "RESET")
        self.assertFalse(r.ramps)

    def test_nasus_dual_kind_on_ult(self):
        # Nasus Q RAMP SUSTAINED 0.95 (0.95) + R DUELHEAL SUSTAINED cond 0.8 (0.3)
        # + R RAMP SUSTAINED cond 0.7 (0.35) -> 1.6; top RAMP, ramps True. The R
        # slot carries two kinds (the dual-kind-per-slot allowance).
        r = compute_extendedduel("Nasus")
        self.assertAlmostEqual(r.duel_score, 1.6, places=4)
        self.assertEqual(r.top_kind, "RAMP")
        self.assertTrue(r.ramps)
        kinds = {(s.source_key, s.kind) for s in r.sources}
        self.assertIn(("R", "RAMP"), kinds)
        self.assertIn(("R", "DUELHEAL"), kinds)

    def test_garen_multi_tool(self):
        # Garen Q RESET PERIODIC 0.55 (0.374) + W ENDURE SUSTAINED 0.35 (0.21)
        # + E RAMP SUSTAINED 0.6 (0.6) -> 1.184; top RAMP, ramps True.
        r = compute_extendedduel("Garen")
        self.assertAlmostEqual(r.duel_score, 1.184, places=4)
        self.assertEqual(r.top_kind, "RAMP")
        self.assertTrue(r.ramps)


class DirectionalTests(unittest.TestCase):
    def test_duelists_score_high(self):
        for champ in ("Jax", "MasterYi", "Tryndamere", "Aatrox", "Vladimir",
                      "Warwick", "Nasus", "Yone", "Fiora", "Katarina",
                      "Renekton"):
            self.assertGreater(compute_extendedduel(champ).duel_score, 1.0, champ)

    def test_non_duelists_score_zero(self):
        # The axis is SELECTIVE: a burst / artillery / utility champion with no
        # attrition tools is absent from the registry.
        for champ in ("Leblanc", "Veigar", "Lux", "Xerath", "Janna", "Ziggs",
                      "Zoe", "Sona", "Milio"):
            self.assertEqual(compute_extendedduel(champ).duel_score, 0.0, champ)

    def test_ramping_duelists_flag_true(self):
        for champ in ("MasterYi", "Tryndamere", "Jax", "Aatrox", "Nasus",
                      "Vladimir", "Warwick", "Yone", "Renekton", "Garen",
                      "Kalista"):
            self.assertTrue(compute_extendedduel(champ).ramps, champ)

    def test_reset_duelists_without_ramp_do_not_flag(self):
        for champ in ("Cassiopeia", "Fiora", "Katarina"):
            self.assertFalse(compute_extendedduel(champ).ramps, champ)


class IdentityTests(unittest.TestCase):
    def test_top_kind_is_strongest_mechanism(self):
        for champ in ("MasterYi", "Tryndamere", "Nasus", "Garen", "Kalista"):
            r = compute_extendedduel(champ)
            best = max(r.sources, key=lambda s: s.value)
            self.assertEqual(r.top_kind, best.kind, champ)

    def test_ramps_tracks_kinds(self):
        # Every champion with a RAMP mechanism is flagged.
        for champ, entries in _EXTENDEDDUEL_REGISTRY.items():
            has_ramp = any(e.kind == "RAMP" for e in entries)
            self.assertEqual(
                compute_extendedduel(champ).ramps, has_ramp, champ
            )

    def test_score_is_sum_of_source_values(self):
        for champ in ("MasterYi", "Tryndamere", "Nasus", "Garen"):
            r = compute_extendedduel(champ)
            self.assertAlmostEqual(
                r.duel_score, sum(s.value for s in r.sources), places=6
            )


class WeightAndCadenceTierTests(unittest.TestCase):
    def test_kind_weights(self):
        self.assertEqual(_EXTENDEDDUEL_KIND_WEIGHT["RAMP"], 1.0)
        self.assertEqual(_EXTENDEDDUEL_KIND_WEIGHT["RESET"], 0.85)
        self.assertEqual(_EXTENDEDDUEL_KIND_WEIGHT["DUELHEAL"], 0.75)
        self.assertEqual(_EXTENDEDDUEL_KIND_WEIGHT["ENDURE"], 0.6)
        vals = [
            _EXTENDEDDUEL_KIND_WEIGHT[k]
            for k in ("RAMP", "RESET", "DUELHEAL", "ENDURE")
        ]
        self.assertEqual(vals, sorted(vals, reverse=True))

    def test_cadence_mults(self):
        self.assertEqual(_EXTENDEDDUEL_CADENCE_MULT["SUSTAINED"], 1.0)
        self.assertEqual(_EXTENDEDDUEL_CADENCE_MULT["PERIODIC"], 0.8)
        self.assertEqual(_EXTENDEDDUEL_CADENCE_MULT["BURST"], 0.65)
        vals = [
            _EXTENDEDDUEL_CADENCE_MULT[c]
            for c in ("SUSTAINED", "PERIODIC", "BURST")
        ]
        self.assertEqual(vals, sorted(vals, reverse=True))

    def test_conditional_midpoint(self):
        self.assertEqual(_EXTENDEDDUEL_CONDITIONAL_PROB, 0.5)


class EmptyAndShapeTests(unittest.TestCase):
    def test_blank_champion(self):
        r = compute_extendedduel("")
        self.assertIsInstance(r, ExtendedDuelResult)
        self.assertEqual(r.duel_score, 0.0)
        self.assertEqual(r.top_kind, "")
        self.assertFalse(r.ramps)
        self.assertEqual(r.sources, ())

    def test_unknown_champion(self):
        r = compute_extendedduel("NotAChampion")
        self.assertEqual(r.duel_score, 0.0)
        self.assertEqual(r.sources, ())

    def test_to_dict_shape(self):
        d = compute_extendedduel("Nasus").to_dict()
        for key in (
            "champion", "mode", "duel_score", "top_kind", "ramps", "sources",
        ):
            self.assertIn(key, d)
        self.assertTrue(d["sources"])
        for s in d["sources"]:
            for key in (
                "source_key", "kind", "cadence", "kind_weight",
                "cadence_mult", "magnitude", "conditional", "value",
            ):
                self.assertIn(key, s)

    def test_mode_passthrough(self):
        self.assertEqual(compute_extendedduel("Jax", mode="ARAM").mode, "ARAM")


class RegistryInvariantTests(unittest.TestCase):
    def test_all_kinds_have_weights(self):
        for champ, entries in _EXTENDEDDUEL_REGISTRY.items():
            for e in entries:
                self.assertIn(e.kind, _EXTENDEDDUEL_KIND_WEIGHT, f"{champ} {e.source}")

    def test_all_cadences_valid(self):
        for champ, entries in _EXTENDEDDUEL_REGISTRY.items():
            for e in entries:
                self.assertIn(
                    e.cadence, _EXTENDEDDUEL_CADENCE_MULT, f"{champ} {e.source}"
                )

    def test_all_sources_canonical(self):
        for champ, entries in _EXTENDEDDUEL_REGISTRY.items():
            for e in entries:
                self.assertIn(e.source, ("P", "Q", "W", "E", "R", "BASE"))

    def test_magnitudes_in_range(self):
        for champ, entries in _EXTENDEDDUEL_REGISTRY.items():
            for e in entries:
                self.assertTrue(0.0 < e.magnitude <= 1.0, f"{champ} {e.source}")

    def test_source_kind_unique_per_champion(self):
        # A slot may carry two KINDS (Nasus R = RAMP + DUELHEAL), but not the same
        # (source, kind) twice - that would be a classify/critic overlap.
        for champ, entries in _EXTENDEDDUEL_REGISTRY.items():
            pairs = [(e.source, e.kind) for e in entries]
            self.assertEqual(len(pairs), len(set(pairs)), champ)

    def test_roster_coverage(self):
        # Roster fan-out (selective but broad axis - most fighters / skirmishers
        # carry an attrition tool): 283 entries / 111 champions; 63 of them bring a
        # RAMP mechanism (the ramps set), 81 rows are conditional. Re-running
        # tools/ds_extendedduel_build.py against a fresh scan updates these.
        self.assertEqual(len(_EXTENDEDDUEL_REGISTRY), 111)
        total = sum(len(v) for v in _EXTENDEDDUEL_REGISTRY.values())
        self.assertEqual(total, 283)
        ramp_champs = sum(
            1 for c in _EXTENDEDDUEL_REGISTRY if compute_extendedduel(c).ramps
        )
        self.assertEqual(ramp_champs, 63)
        conditional = sum(
            1 for v in _EXTENDEDDUEL_REGISTRY.values()
            for e in v if e.conditional
        )
        self.assertEqual(conditional, 81)


class RouteAndVersionTests(unittest.TestCase):
    def test_extendedduel_route_registered_additively(self):
        from agents.daemon_slayer import server
        self.assertIn("/extended-duel", server._POST_ROUTES)
        self.assertIn("/extended-duel", server._GET_DISPATCH_ROUTES)
        # Additive: every existing route is still present (none replaced).
        for path in (
            "/anti-tank", "/ally-amp", "/objective-damage", "/zone-control",
            "/threat-range", "/waveclear", "/scaling", "/sustain", "/mobility",
            "/cc-output", "/ehp", "/rank-tank", "/hybrid", "/burst", "/hps",
            "/ability-dps", "/v2/matchup",
        ):
            self.assertIn(path, server._POST_ROUTES)

    def test_engine_version(self):
        self.assertEqual(ENGINE_VERSION, "1.276.0")


if __name__ == "__main__":
    unittest.main()
