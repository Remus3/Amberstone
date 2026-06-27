"""Item 302 (ENGINE 1.118.0) - zone-control / area-denial scorer tests.

The thirteenth scored axis alongside DPS / burst / EHP / ability-DPS /
healing-throughput / offensive CC-output (item 294) / mobility (item 297) /
sustain (item 298) / scaling (item 299) / wave-clear (item 300) / effective
threat-range (item 301): how much a champion can make a piece of GROUND
dangerous, impassable, or contested for a duration, reduced to a single
denial-weighted ``zonecontrol_score`` plus a ``top_kind`` label and a
``controls_terrain`` flag. Proves (a) the kind-weight * persistence-mult *
magnitude * conditional math on synthetic entries (registry-independent),
(b) hand-verified champion values at pinned inputs (a top zone mage, a wall
controller, a single-summon holder), (c) the kind -> weight + persistence ->
mult tiers, (d) the top_kind / controls_terrain identities, (e) the SPARSE
contract (a pure target-focused champion scores 0.0), (f) registry invariants +
coverage, (g) the additive /zone-control route registers alongside (does not
replace) the existing routes, (h) the ENGINE pin.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.zonecontrol import (
    _ZONECONTROL_CONDITIONAL_PROB,
    _ZONECONTROL_KIND_WEIGHT,
    _ZONECONTROL_PERSISTENCE_MULT,
    _ZONECONTROL_REGISTRY,
    ZoneControlEntry,
    ZoneControlResult,
    _mechanism_value,
    compute_zonecontrol,
)


class MechanismValueMathTests(unittest.TestCase):
    def test_terrain_sustained_unconditional(self):
        # TERRAIN weight 1.0, SUSTAINED mult 1.0, magnitude 1.0 -> 1.0.
        e = ZoneControlEntry("R", "TERRAIN", "SUSTAINED", magnitude=1.0)
        self.assertAlmostEqual(_mechanism_value(e), 1.0, places=4)

    def test_field_timed(self):
        # FIELD weight 0.85, TIMED mult 0.8, magnitude 0.5 -> 0.34.
        e = ZoneControlEntry("W", "FIELD", "TIMED", magnitude=0.5)
        self.assertAlmostEqual(_mechanism_value(e), 0.34, places=4)

    def test_displace_brief_penalty(self):
        # DISPLACE weight 0.45, BRIEF mult 0.55, magnitude 0.5 -> 0.12375.
        e = ZoneControlEntry("R", "DISPLACE", "BRIEF", magnitude=0.5)
        self.assertAlmostEqual(_mechanism_value(e), 0.12375, places=5)

    def test_conditional_halves_value(self):
        e = ZoneControlEntry("R", "TERRAIN", "SUSTAINED", magnitude=1.0, conditional=True)
        self.assertAlmostEqual(_mechanism_value(e), 0.5, places=4)

    def test_unknown_kind_or_persistence_is_zero(self):
        self.assertEqual(
            _mechanism_value(ZoneControlEntry("Q", "NOWHERE", "TIMED", magnitude=1.0)),
            0.0,
        )
        self.assertEqual(
            _mechanism_value(ZoneControlEntry("Q", "TERRAIN", "FOREVER", magnitude=1.0)),
            0.0,
        )


class HandVerifiedChampionTests(unittest.TestCase):
    # Pinned exact values; re-running tools/ds_zonecontrol_build.py against a
    # fresh scan updates them.
    def test_anivia_tops_roster(self):
        # Anivia: W TERRAIN TIMED 0.82 (0.656) + R FIELD SUSTAINED 0.78 (0.663)
        # -> 1.319; top FIELD (R edges out W), controls_terrain True (W wall).
        r = compute_zonecontrol("Anivia")
        self.assertAlmostEqual(r.zonecontrol_score, 1.319, places=3)
        self.assertEqual(r.top_kind, "FIELD")
        self.assertTrue(r.controls_terrain)
        w = next(s for s in r.sources if s.source_key == "W")
        self.assertAlmostEqual(w.value, 0.656, places=4)
        rr = next(s for s in r.sources if s.source_key == "R")
        self.assertAlmostEqual(rr.value, 0.663, places=4)

    def test_taliyah_terrain_controller(self):
        # Taliyah R TERRAIN SUSTAINED 0.92 (cond) is her strongest -> top TERRAIN.
        r = compute_zonecontrol("Taliyah")
        self.assertAlmostEqual(r.zonecontrol_score, 0.797, places=3)
        self.assertEqual(r.top_kind, "TERRAIN")
        self.assertTrue(r.controls_terrain)
        rr = next(s for s in r.sources if s.source_key == "R")
        self.assertAlmostEqual(rr.value, 0.46, places=4)

    def test_heimerdinger_single_summon(self):
        # Heimerdinger Q SUMMON SUSTAINED 0.85 -> 0.51, top SUMMON, no terrain.
        r = compute_zonecontrol("Heimerdinger")
        self.assertAlmostEqual(r.zonecontrol_score, 0.51, places=4)
        self.assertEqual(r.top_kind, "SUMMON")
        self.assertFalse(r.controls_terrain)


class DirectionalTests(unittest.TestCase):
    def test_zone_controllers_score_high(self):
        for champ in ("Anivia", "Illaoi", "Viktor", "Karthus", "Taliyah"):
            self.assertGreater(
                compute_zonecontrol(champ).zonecontrol_score, 0.6, champ
            )

    def test_target_focused_champs_score_zero(self):
        # The axis is SPARSE: a champion with no area-denial is absent and 0.0.
        for champ in ("MasterYi", "Zed", "Talon", "Tryndamere", "Vayne"):
            self.assertEqual(compute_zonecontrol(champ).zonecontrol_score, 0.0, champ)

    def test_terrain_champs_flag_true(self):
        for champ in ("Anivia", "Taliyah", "Yorick", "Azir", "Yasuo", "Veigar"):
            self.assertTrue(compute_zonecontrol(champ).controls_terrain, champ)


class IdentityTests(unittest.TestCase):
    def test_top_kind_is_strongest_mechanism(self):
        for champ in ("Anivia", "Taliyah", "Gangplank"):
            r = compute_zonecontrol(champ)
            best = max(r.sources, key=lambda s: s.value)
            self.assertEqual(r.top_kind, best.kind, champ)

    def test_controls_terrain_tracks_kinds(self):
        # Every champion with a TERRAIN mechanism is flagged; one without is not.
        for champ, entries in _ZONECONTROL_REGISTRY.items():
            has_terrain = any(e.kind == "TERRAIN" for e in entries)
            self.assertEqual(
                compute_zonecontrol(champ).controls_terrain, has_terrain, champ
            )

    def test_score_is_sum_of_source_values(self):
        for champ in ("Anivia", "Taliyah", "Gangplank", "Zyra"):
            r = compute_zonecontrol(champ)
            self.assertAlmostEqual(
                r.zonecontrol_score, sum(s.value for s in r.sources), places=6
            )


class WeightAndPersistenceTierTests(unittest.TestCase):
    def test_kind_weights(self):
        self.assertEqual(_ZONECONTROL_KIND_WEIGHT["TERRAIN"], 1.0)
        self.assertEqual(_ZONECONTROL_KIND_WEIGHT["FIELD"], 0.85)
        self.assertEqual(_ZONECONTROL_KIND_WEIGHT["TRAP"], 0.7)
        self.assertEqual(_ZONECONTROL_KIND_WEIGHT["SUMMON"], 0.6)
        self.assertEqual(_ZONECONTROL_KIND_WEIGHT["DISPLACE"], 0.45)
        # Monotonic decreasing denial tiers.
        vals = [
            _ZONECONTROL_KIND_WEIGHT[k]
            for k in ("TERRAIN", "FIELD", "TRAP", "SUMMON", "DISPLACE")
        ]
        self.assertEqual(vals, sorted(vals, reverse=True))

    def test_persistence_mults(self):
        self.assertEqual(_ZONECONTROL_PERSISTENCE_MULT["SUSTAINED"], 1.0)
        self.assertEqual(_ZONECONTROL_PERSISTENCE_MULT["TIMED"], 0.8)
        self.assertEqual(_ZONECONTROL_PERSISTENCE_MULT["BRIEF"], 0.55)
        vals = [
            _ZONECONTROL_PERSISTENCE_MULT[p]
            for p in ("SUSTAINED", "TIMED", "BRIEF")
        ]
        self.assertEqual(vals, sorted(vals, reverse=True))

    def test_conditional_midpoint(self):
        self.assertEqual(_ZONECONTROL_CONDITIONAL_PROB, 0.5)


class EmptyAndShapeTests(unittest.TestCase):
    def test_blank_champion(self):
        r = compute_zonecontrol("")
        self.assertIsInstance(r, ZoneControlResult)
        self.assertEqual(r.zonecontrol_score, 0.0)
        self.assertEqual(r.top_kind, "")
        self.assertFalse(r.controls_terrain)
        self.assertEqual(r.sources, ())

    def test_unknown_champion(self):
        r = compute_zonecontrol("NotAChampion")
        self.assertEqual(r.zonecontrol_score, 0.0)
        self.assertEqual(r.sources, ())

    def test_to_dict_shape(self):
        d = compute_zonecontrol("Anivia").to_dict()
        for key in (
            "champion", "mode", "zonecontrol_score", "top_kind",
            "controls_terrain", "sources",
        ):
            self.assertIn(key, d)
        self.assertTrue(d["sources"])
        for s in d["sources"]:
            for key in (
                "source_key", "kind", "persistence", "kind_weight",
                "persistence_mult", "magnitude", "conditional", "value",
            ):
                self.assertIn(key, s)

    def test_mode_passthrough(self):
        self.assertEqual(compute_zonecontrol("Anivia", mode="ARAM").mode, "ARAM")


class RegistryInvariantTests(unittest.TestCase):
    def test_all_kinds_have_weights(self):
        for champ, entries in _ZONECONTROL_REGISTRY.items():
            for e in entries:
                self.assertIn(e.kind, _ZONECONTROL_KIND_WEIGHT, f"{champ} {e.source}")

    def test_all_persistence_valid(self):
        for champ, entries in _ZONECONTROL_REGISTRY.items():
            for e in entries:
                self.assertIn(
                    e.persistence, _ZONECONTROL_PERSISTENCE_MULT, f"{champ} {e.source}"
                )

    def test_all_sources_canonical(self):
        for champ, entries in _ZONECONTROL_REGISTRY.items():
            for e in entries:
                self.assertIn(e.source, ("P", "Q", "W", "E", "R", "BASE"))

    def test_magnitudes_in_range(self):
        for champ, entries in _ZONECONTROL_REGISTRY.items():
            for e in entries:
                self.assertTrue(0.0 < e.magnitude <= 1.0, f"{champ} {e.source}")

    def test_one_entry_per_champion_source(self):
        for champ, entries in _ZONECONTROL_REGISTRY.items():
            slots = [e.source for e in entries]
            self.assertEqual(len(slots), len(set(slots)), champ)

    def test_roster_coverage(self):
        # 10-channel roster fan-out (sparse axis): 98 entries / 83 champions,
        # 11 TERRAIN mechanisms (one per terrain champion). Re-running
        # tools/ds_zonecontrol_build.py against a fresh scan updates these.
        self.assertEqual(len(_ZONECONTROL_REGISTRY), 83)
        total = sum(len(v) for v in _ZONECONTROL_REGISTRY.values())
        self.assertEqual(total, 98)
        terrain_count = sum(
            1 for v in _ZONECONTROL_REGISTRY.values()
            for e in v if e.kind == "TERRAIN"
        )
        self.assertEqual(terrain_count, 11)
        terrain_champs = sum(
            1 for c in _ZONECONTROL_REGISTRY
            if compute_zonecontrol(c).controls_terrain
        )
        self.assertEqual(terrain_champs, 11)


class RouteAndVersionTests(unittest.TestCase):
    def test_zonecontrol_route_registered_additively(self):
        from agents.daemon_slayer import server
        self.assertIn("/zone-control", server._POST_ROUTES)
        self.assertIn("/zone-control", server._GET_DISPATCH_ROUTES)
        # Additive: every existing route is still present (none replaced).
        for path in (
            "/threat-range", "/waveclear", "/scaling", "/sustain", "/mobility",
            "/cc-output", "/ehp", "/rank-tank", "/hybrid", "/burst", "/hps",
            "/ability-dps", "/v2/matchup",
        ):
            self.assertIn(path, server._POST_ROUTES)

    def test_engine_version(self):
        self.assertEqual(ENGINE_VERSION, "1.153.0")


if __name__ == "__main__":
    unittest.main()
