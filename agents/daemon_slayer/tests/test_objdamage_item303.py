"""Item 303 (ENGINE 1.118.0) - objective / structure-damage scorer tests.

The fourteenth scored axis alongside DPS / burst / EHP / ability-DPS /
healing-throughput / offensive CC-output (item 294) / mobility (item 297) /
sustain (item 298) / scaling (item 299) / wave-clear (item 300) / effective
threat-range (item 301) / zone-control (item 302): how much pressure a champion
puts on the map's OBJECTIVES (turrets / structures and epic monsters), reduced
to a single kind-weighted, scope-scaled ``objdamage_score`` plus a ``top_kind``
label and a ``pressures_structures`` flag. Proves (a) the kind-weight *
scope-mult * magnitude * conditional math on synthetic entries
(registry-independent), (b) hand-verified champion values at pinned inputs (a
hyper-carry, a percent-HP on-hit monster-shredder, a tower-bonus mage, a
summon-DPS turret holder, an enchanter floor), (c) the kind -> weight + scope ->
mult tiers, (d) the top_kind / pressures_structures identities, (e) the
FULL-roster contract (every champion carries at least one row), (f) registry
invariants + coverage, (g) the additive /objective-damage route registers
alongside (does not replace) the existing routes, (h) the ENGINE pin.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.objdamage import (
    _OBJDAMAGE_CONDITIONAL_PROB,
    _OBJDAMAGE_KIND_WEIGHT,
    _OBJDAMAGE_REGISTRY,
    _OBJDAMAGE_SCOPE_MULT,
    ObjDamageEntry,
    ObjDamageResult,
    _mechanism_value,
    compute_objdamage,
)


class MechanismValueMathTests(unittest.TestCase):
    def test_structure_bonus_both_unconditional(self):
        # STRUCTURE_BONUS weight 1.0, BOTH mult 1.0, magnitude 1.0 -> 1.0.
        e = ObjDamageEntry("P", "STRUCTURE_BONUS", "BOTH", magnitude=1.0)
        self.assertAlmostEqual(_mechanism_value(e), 1.0, places=4)

    def test_monster_bonus_monster(self):
        # MONSTER_BONUS weight 0.9, MONSTER mult 0.85, magnitude 0.5 -> 0.3825.
        e = ObjDamageEntry("W", "MONSTER_BONUS", "MONSTER", magnitude=0.5)
        self.assertAlmostEqual(_mechanism_value(e), 0.3825, places=4)

    def test_burst_secure_both(self):
        # BURST_SECURE weight 0.45, BOTH mult 1.0, magnitude 0.5 -> 0.225.
        e = ObjDamageEntry("R", "BURST_SECURE", "BOTH", magnitude=0.5)
        self.assertAlmostEqual(_mechanism_value(e), 0.225, places=4)

    def test_conditional_halves_value(self):
        e = ObjDamageEntry("R", "STRUCTURE_BONUS", "BOTH", magnitude=1.0, conditional=True)
        self.assertAlmostEqual(_mechanism_value(e), 0.5, places=4)

    def test_unknown_kind_or_scope_is_zero(self):
        self.assertEqual(
            _mechanism_value(ObjDamageEntry("Q", "NOWHERE", "BOTH", magnitude=1.0)),
            0.0,
        )
        self.assertEqual(
            _mechanism_value(ObjDamageEntry("Q", "SUSTAINED_DPS", "NEVER", magnitude=1.0)),
            0.0,
        )


class HandVerifiedChampionTests(unittest.TestCase):
    # Pinned exact values; re-running tools/ds_objdamage_build.py against a
    # fresh scan updates them.
    def test_kogmaw_on_hit_shredder_tops_roster(self):
        # KogMaw: W MONSTER_BONUS MONSTER 0.88 (0.6732) + BASE SUSTAINED_DPS
        # BOTH 0.85 (0.595) -> 1.2682; top MONSTER_BONUS, pressures structures.
        r = compute_objdamage("KogMaw")
        self.assertAlmostEqual(r.objdamage_score, 1.2682, places=3)
        self.assertEqual(r.top_kind, "MONSTER_BONUS")
        self.assertTrue(r.pressures_structures)
        w = next(s for s in r.sources if s.source_key == "W")
        self.assertAlmostEqual(w.value, 0.6732, places=4)

    def test_aphelios_pure_sustained_dps(self):
        # Aphelios: BASE SUSTAINED_DPS BOTH 0.88 -> 0.616, top SUSTAINED_DPS.
        r = compute_objdamage("Aphelios")
        self.assertAlmostEqual(r.objdamage_score, 0.616, places=4)
        self.assertEqual(r.top_kind, "SUSTAINED_DPS")
        self.assertTrue(r.pressures_structures)

    def test_ziggs_tower_bonus(self):
        # Ziggs Short Fuse is a STRUCTURE_BONUS - his strongest objective tool.
        r = compute_objdamage("Ziggs")
        self.assertAlmostEqual(r.objdamage_score, 0.891, places=3)
        self.assertEqual(r.top_kind, "STRUCTURE_BONUS")
        self.assertTrue(r.pressures_structures)

    def test_heimerdinger_summon_dps(self):
        # Heimerdinger W SUMMON_DPS BOTH 0.85 (0.4675) > BASE -> top SUMMON_DPS.
        r = compute_objdamage("Heimerdinger")
        self.assertAlmostEqual(r.objdamage_score, 0.7335, places=4)
        self.assertEqual(r.top_kind, "SUMMON_DPS")

    def test_enchanter_floor(self):
        # A pure enchanter / support sits at the SUSTAINED_DPS BASE floor.
        for champ in ("Soraka", "Yuumi", "Braum"):
            r = compute_objdamage(champ)
            self.assertAlmostEqual(r.objdamage_score, 0.105, places=4, msg=champ)
            self.assertEqual(r.top_kind, "SUSTAINED_DPS", champ)


class DirectionalTests(unittest.TestCase):
    def test_objective_carries_score_high(self):
        for champ in ("KogMaw", "Belveth", "Vayne", "Varus", "Kindred"):
            self.assertGreater(compute_objdamage(champ).objdamage_score, 1.0, champ)

    def test_enchanters_score_low(self):
        for champ in ("Soraka", "Yuumi", "Janna", "Braum", "Milio"):
            self.assertLess(compute_objdamage(champ).objdamage_score, 0.2, champ)

    def test_carries_beat_enchanters(self):
        carry = compute_objdamage("KogMaw").objdamage_score
        ench = compute_objdamage("Soraka").objdamage_score
        self.assertGreater(carry, ench)


class IdentityTests(unittest.TestCase):
    def test_top_kind_is_strongest_mechanism(self):
        for champ in ("KogMaw", "Ziggs", "Heimerdinger", "Belveth"):
            r = compute_objdamage(champ)
            best = max(r.sources, key=lambda s: s.value)
            self.assertEqual(r.top_kind, best.kind, champ)

    def test_pressures_structures_tracks_scope(self):
        # The flag is True iff any mechanism with scope BOTH or STRUCTURE
        # contributes (a MONSTER-only tool does not damage towers).
        for champ, entries in _OBJDAMAGE_REGISTRY.items():
            hits = any(e.scope in ("BOTH", "STRUCTURE") for e in entries)
            self.assertEqual(
                compute_objdamage(champ).pressures_structures, hits, champ
            )

    def test_score_is_sum_of_source_values(self):
        for champ in ("KogMaw", "Ziggs", "Yorick", "Belveth"):
            r = compute_objdamage(champ)
            self.assertAlmostEqual(
                r.objdamage_score, sum(s.value for s in r.sources), places=6
            )


class WeightAndScopeTierTests(unittest.TestCase):
    def test_kind_weights(self):
        self.assertEqual(_OBJDAMAGE_KIND_WEIGHT["STRUCTURE_BONUS"], 1.0)
        self.assertEqual(_OBJDAMAGE_KIND_WEIGHT["MONSTER_BONUS"], 0.9)
        self.assertEqual(_OBJDAMAGE_KIND_WEIGHT["SUSTAINED_DPS"], 0.7)
        self.assertEqual(_OBJDAMAGE_KIND_WEIGHT["SUMMON_DPS"], 0.55)
        self.assertEqual(_OBJDAMAGE_KIND_WEIGHT["BURST_SECURE"], 0.45)
        vals = [
            _OBJDAMAGE_KIND_WEIGHT[k]
            for k in ("STRUCTURE_BONUS", "MONSTER_BONUS", "SUSTAINED_DPS",
                      "SUMMON_DPS", "BURST_SECURE")
        ]
        self.assertEqual(vals, sorted(vals, reverse=True))

    def test_scope_mults(self):
        self.assertEqual(_OBJDAMAGE_SCOPE_MULT["BOTH"], 1.0)
        self.assertEqual(_OBJDAMAGE_SCOPE_MULT["MONSTER"], 0.85)
        self.assertEqual(_OBJDAMAGE_SCOPE_MULT["STRUCTURE"], 0.85)
        self.assertGreaterEqual(_OBJDAMAGE_SCOPE_MULT["BOTH"], _OBJDAMAGE_SCOPE_MULT["MONSTER"])

    def test_conditional_midpoint(self):
        self.assertEqual(_OBJDAMAGE_CONDITIONAL_PROB, 0.5)


class EmptyAndShapeTests(unittest.TestCase):
    def test_blank_champion(self):
        r = compute_objdamage("")
        self.assertIsInstance(r, ObjDamageResult)
        self.assertEqual(r.objdamage_score, 0.0)
        self.assertEqual(r.top_kind, "")
        self.assertFalse(r.pressures_structures)
        self.assertEqual(r.sources, ())

    def test_unknown_champion(self):
        r = compute_objdamage("NotAChampion")
        self.assertEqual(r.objdamage_score, 0.0)
        self.assertEqual(r.sources, ())

    def test_to_dict_shape(self):
        d = compute_objdamage("KogMaw").to_dict()
        for key in (
            "champion", "mode", "objdamage_score", "top_kind",
            "pressures_structures", "sources",
        ):
            self.assertIn(key, d)
        self.assertTrue(d["sources"])
        for s in d["sources"]:
            for key in (
                "source_key", "kind", "scope", "kind_weight",
                "scope_mult", "magnitude", "conditional", "value",
            ):
                self.assertIn(key, s)

    def test_mode_passthrough(self):
        self.assertEqual(compute_objdamage("KogMaw", mode="ARAM").mode, "ARAM")


class RegistryInvariantTests(unittest.TestCase):
    def test_all_kinds_have_weights(self):
        for champ, entries in _OBJDAMAGE_REGISTRY.items():
            for e in entries:
                self.assertIn(e.kind, _OBJDAMAGE_KIND_WEIGHT, f"{champ} {e.source}")

    def test_all_scopes_valid(self):
        for champ, entries in _OBJDAMAGE_REGISTRY.items():
            for e in entries:
                self.assertIn(e.scope, _OBJDAMAGE_SCOPE_MULT, f"{champ} {e.source}")

    def test_all_sources_canonical(self):
        for champ, entries in _OBJDAMAGE_REGISTRY.items():
            for e in entries:
                self.assertIn(e.source, ("P", "Q", "W", "E", "R", "BASE"))

    def test_magnitudes_in_range(self):
        for champ, entries in _OBJDAMAGE_REGISTRY.items():
            for e in entries:
                self.assertTrue(0.0 < e.magnitude <= 1.0, f"{champ} {e.source}")

    def test_one_entry_per_champion_source(self):
        for champ, entries in _OBJDAMAGE_REGISTRY.items():
            slots = [e.source for e in entries]
            self.assertEqual(len(slots), len(set(slots)), champ)

    def test_roster_coverage(self):
        # 10-channel roster fan-out (full roster): 285 entries / 171 champions,
        # 4 STRUCTURE_BONUS mechanisms (Tristana / Volibear / Yunara / Ziggs),
        # 66 conditional. Re-running tools/ds_objdamage_build.py against a fresh
        # scan updates these.
        self.assertEqual(len(_OBJDAMAGE_REGISTRY), 171)
        total = sum(len(v) for v in _OBJDAMAGE_REGISTRY.values())
        self.assertEqual(total, 285)
        structure_bonus = sum(
            1 for v in _OBJDAMAGE_REGISTRY.values()
            for e in v if e.kind == "STRUCTURE_BONUS"
        )
        self.assertEqual(structure_bonus, 4)
        conditional = sum(
            1 for v in _OBJDAMAGE_REGISTRY.values() for e in v if e.conditional
        )
        self.assertEqual(conditional, 66)

    def test_every_champion_has_a_row(self):
        # Full-roster contract: every champion carries at least one mechanism.
        for champ, entries in _OBJDAMAGE_REGISTRY.items():
            self.assertGreater(len(entries), 0, champ)


class RouteAndVersionTests(unittest.TestCase):
    def test_objdamage_route_registered_additively(self):
        from agents.daemon_slayer import server
        self.assertIn("/objective-damage", server._POST_ROUTES)
        self.assertIn("/objective-damage", server._GET_DISPATCH_ROUTES)
        # Additive: every existing route is still present (none replaced).
        for path in (
            "/zone-control", "/threat-range", "/waveclear", "/scaling",
            "/sustain", "/mobility", "/cc-output", "/ehp", "/rank-tank",
            "/hybrid", "/burst", "/hps", "/ability-dps", "/v2/matchup",
        ):
            self.assertIn(path, server._POST_ROUTES)

    def test_engine_version(self):
        self.assertEqual(ENGINE_VERSION, "1.159.0")


if __name__ == "__main__":
    unittest.main()
