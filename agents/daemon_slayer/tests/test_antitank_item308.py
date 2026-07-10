"""Item 308 (ENGINE 1.118.0) - anti-tank / %HP-damage + resist-shred scorer tests.

The sixteenth scored axis alongside DPS / burst / EHP / ability-DPS /
healing-throughput / offensive CC-output (item 294) / mobility (item 297) /
sustain (item 298) / scaling (item 299) / wave-clear (item 300) / effective
threat-range (item 301) / zone-control (item 302) / objective-damage (item 303) /
ally-amplification (item 304): how well a champion's OWN KIT melts a high-HP /
high-resist target (the %max-HP / %current-HP damage and the armor/MR shred /
%pen it brings), reduced to a single kind-weighted, cadence-scaled
``antitank_score`` plus a ``top_kind`` label and a ``shreds_resist`` flag. Proves
(a) the kind-weight * cadence-mult * magnitude * conditional math on synthetic
entries (registry-independent), (b) hand-verified champion values at pinned
inputs (a %max-HP carry, a dual-mechanism resist-stealer, a %current-HP bruiser,
a %pen juggernaut), (c) the kind -> weight + cadence -> mult tiers, (d) the
top_kind / shreds_resist identities, (e) the SELECTIVE contract (a flat-damage
champion scores 0.0), (f) the dual-kind-per-slot allowance, (g) registry
invariants + coverage, (h) the additive /anti-tank route registers alongside
(does not replace) the existing routes, (i) the ENGINE pin.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.antitank import (
    _ANTITANK_CADENCE_MULT,
    _ANTITANK_CONDITIONAL_PROB,
    _ANTITANK_KIND_WEIGHT,
    _ANTITANK_REGISTRY,
    AntiTankEntry,
    AntiTankResult,
    _mechanism_value,
    compute_antitank,
)


class MechanismValueMathTests(unittest.TestCase):
    def test_maxhp_sustained_unconditional(self):
        # MAX_HP weight 1.0, SUSTAINED mult 1.0, magnitude 1.0 -> 1.0.
        e = AntiTankEntry("W", "MAX_HP", "SUSTAINED", magnitude=1.0)
        self.assertAlmostEqual(_mechanism_value(e), 1.0, places=4)

    def test_shred_periodic(self):
        # SHRED weight 0.85, PERIODIC mult 0.8, magnitude 0.5 -> 0.34.
        e = AntiTankEntry("E", "SHRED", "PERIODIC", magnitude=0.5)
        self.assertAlmostEqual(_mechanism_value(e), 0.34, places=4)

    def test_currenthp_burst(self):
        # CURRENT_HP weight 0.75, BURST mult 0.65, magnitude 0.6 -> 0.2925.
        e = AntiTankEntry("R", "CURRENT_HP", "BURST", magnitude=0.6)
        self.assertAlmostEqual(_mechanism_value(e), 0.2925, places=4)

    def test_percentpen_sustained_lowest_kind(self):
        # PERCENT_PEN weight 0.65, SUSTAINED mult 1.0, magnitude 1.0 -> 0.65.
        e = AntiTankEntry("E", "PERCENT_PEN", "SUSTAINED", magnitude=1.0)
        self.assertAlmostEqual(_mechanism_value(e), 0.65, places=4)

    def test_conditional_halves_value(self):
        e = AntiTankEntry("W", "MAX_HP", "SUSTAINED", magnitude=1.0, conditional=True)
        self.assertAlmostEqual(_mechanism_value(e), 0.5, places=4)

    def test_unknown_kind_or_cadence_is_zero(self):
        self.assertEqual(
            _mechanism_value(AntiTankEntry("Q", "NOPE", "SUSTAINED", magnitude=1.0)),
            0.0,
        )
        self.assertEqual(
            _mechanism_value(AntiTankEntry("Q", "MAX_HP", "ALWAYS", magnitude=1.0)),
            0.0,
        )


class HandVerifiedChampionTests(unittest.TestCase):
    # Pinned exact values; re-running tools/ds_antitank_build.py against a fresh
    # scan updates them.
    def test_vayne_pure_maxhp(self):
        # Vayne W MAX_HP SUSTAINED 0.95 -> 0.95; top MAX_HP, no shred.
        r = compute_antitank("Vayne")
        self.assertAlmostEqual(r.antitank_score, 0.95, places=4)
        self.assertEqual(r.top_kind, "MAX_HP")
        self.assertFalse(r.shreds_resist)

    def test_trundle_dual_mechanism(self):
        # Trundle R MAX_HP BURST 0.8 (0.52) + R SHRED BURST 0.85 (0.469625)
        # -> 0.989625; top MAX_HP, shreds True (the resist-steal row).
        r = compute_antitank("Trundle")
        self.assertAlmostEqual(r.antitank_score, 0.989625, places=5)
        self.assertEqual(r.top_kind, "MAX_HP")
        self.assertTrue(r.shreds_resist)
        kinds = {(s.source_key, s.kind) for s in r.sources}
        self.assertIn(("R", "MAX_HP"), kinds)
        self.assertIn(("R", "SHRED"), kinds)

    def test_drmundo_current_hp(self):
        # Dr. Mundo Q CURRENT_HP PERIODIC 0.7 -> 0.75*0.8*0.7 = 0.42; no shred.
        r = compute_antitank("DrMundo")
        self.assertAlmostEqual(r.antitank_score, 0.42, places=4)
        self.assertEqual(r.top_kind, "CURRENT_HP")
        self.assertFalse(r.shreds_resist)

    def test_mordekaiser_percent_pen_tops(self):
        # Morde E PERCENT_PEN SUSTAINED 0.7 (0.455) edges P MAX_HP cond (0.425)
        # + R SHRED BURST cond (0.138125) -> 1.018125; top PERCENT_PEN, shred True.
        r = compute_antitank("Mordekaiser")
        self.assertAlmostEqual(r.antitank_score, 1.018125, places=5)
        self.assertEqual(r.top_kind, "PERCENT_PEN")
        self.assertTrue(r.shreds_resist)


class DirectionalTests(unittest.TestCase):
    def test_antitank_champs_score_high(self):
        for champ in ("Rumble", "KSante", "Sion", "Vi", "Trundle", "Vayne",
                      "KogMaw", "Fiora", "Ornn"):
            self.assertGreater(compute_antitank(champ).antitank_score, 0.6, champ)

    def test_flat_damage_champs_score_zero(self):
        # The axis is SELECTIVE: a champion whose damage ignores enemy health and
        # resists is absent from the registry.
        for champ in ("MasterYi", "Annie", "Talon", "Katarina", "Lux",
                      "Soraka", "Veigar", "Akali", "Lulu", "Janna"):
            self.assertEqual(compute_antitank(champ).antitank_score, 0.0, champ)

    def test_shred_champs_flag_true(self):
        for champ in ("Trundle", "Vi", "Sion", "Yorick", "KogMaw", "Rumble",
                      "Rell", "KSante", "Mordekaiser", "Briar", "Corki", "Nasus"):
            self.assertTrue(compute_antitank(champ).shreds_resist, champ)

    def test_pure_hp_champs_do_not_flag_shred(self):
        for champ in ("Vayne", "Fiora", "Gwen", "DrMundo", "Lillia", "Aatrox",
                      "Camille"):
            self.assertFalse(compute_antitank(champ).shreds_resist, champ)


class IdentityTests(unittest.TestCase):
    def test_top_kind_is_strongest_mechanism(self):
        for champ in ("Rumble", "Trundle", "Mordekaiser", "KSante", "Vayne"):
            r = compute_antitank(champ)
            best = max(r.sources, key=lambda s: s.value)
            self.assertEqual(r.top_kind, best.kind, champ)

    def test_shreds_resist_tracks_kinds(self):
        # Every champion with a SHRED or PERCENT_PEN mechanism is flagged.
        for champ, entries in _ANTITANK_REGISTRY.items():
            has_shred = any(
                e.kind in ("SHRED", "PERCENT_PEN") for e in entries
            )
            self.assertEqual(
                compute_antitank(champ).shreds_resist, has_shred, champ
            )

    def test_score_is_sum_of_source_values(self):
        for champ in ("Rumble", "Trundle", "Sion", "Vi"):
            r = compute_antitank(champ)
            self.assertAlmostEqual(
                r.antitank_score, sum(s.value for s in r.sources), places=6
            )


class WeightAndCadenceTierTests(unittest.TestCase):
    def test_kind_weights(self):
        self.assertEqual(_ANTITANK_KIND_WEIGHT["MAX_HP"], 1.0)
        self.assertEqual(_ANTITANK_KIND_WEIGHT["SHRED"], 0.85)
        self.assertEqual(_ANTITANK_KIND_WEIGHT["CURRENT_HP"], 0.75)
        self.assertEqual(_ANTITANK_KIND_WEIGHT["PERCENT_PEN"], 0.65)
        vals = [
            _ANTITANK_KIND_WEIGHT[k]
            for k in ("MAX_HP", "SHRED", "CURRENT_HP", "PERCENT_PEN")
        ]
        self.assertEqual(vals, sorted(vals, reverse=True))

    def test_cadence_mults(self):
        self.assertEqual(_ANTITANK_CADENCE_MULT["SUSTAINED"], 1.0)
        self.assertEqual(_ANTITANK_CADENCE_MULT["PERIODIC"], 0.8)
        self.assertEqual(_ANTITANK_CADENCE_MULT["BURST"], 0.65)
        vals = [_ANTITANK_CADENCE_MULT[c] for c in ("SUSTAINED", "PERIODIC", "BURST")]
        self.assertEqual(vals, sorted(vals, reverse=True))

    def test_conditional_midpoint(self):
        self.assertEqual(_ANTITANK_CONDITIONAL_PROB, 0.5)


class EmptyAndShapeTests(unittest.TestCase):
    def test_blank_champion(self):
        r = compute_antitank("")
        self.assertIsInstance(r, AntiTankResult)
        self.assertEqual(r.antitank_score, 0.0)
        self.assertEqual(r.top_kind, "")
        self.assertFalse(r.shreds_resist)
        self.assertEqual(r.sources, ())

    def test_unknown_champion(self):
        r = compute_antitank("NotAChampion")
        self.assertEqual(r.antitank_score, 0.0)
        self.assertEqual(r.sources, ())

    def test_to_dict_shape(self):
        d = compute_antitank("Trundle").to_dict()
        for key in (
            "champion", "mode", "antitank_score", "top_kind",
            "shreds_resist", "sources",
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
        self.assertEqual(compute_antitank("Vayne", mode="ARAM").mode, "ARAM")


class RegistryInvariantTests(unittest.TestCase):
    def test_all_kinds_have_weights(self):
        for champ, entries in _ANTITANK_REGISTRY.items():
            for e in entries:
                self.assertIn(e.kind, _ANTITANK_KIND_WEIGHT, f"{champ} {e.source}")

    def test_all_cadences_valid(self):
        for champ, entries in _ANTITANK_REGISTRY.items():
            for e in entries:
                self.assertIn(e.cadence, _ANTITANK_CADENCE_MULT, f"{champ} {e.source}")

    def test_all_sources_canonical(self):
        for champ, entries in _ANTITANK_REGISTRY.items():
            for e in entries:
                self.assertIn(e.source, ("P", "Q", "W", "E", "R", "BASE"))

    def test_magnitudes_in_range(self):
        for champ, entries in _ANTITANK_REGISTRY.items():
            for e in entries:
                self.assertTrue(0.0 < e.magnitude <= 1.0, f"{champ} {e.source}")

    def test_source_kind_unique_per_champion(self):
        # A slot may carry two KINDS (Trundle R, Vi W), but not the same
        # (source, kind) twice - that would be a classify/critic overlap.
        for champ, entries in _ANTITANK_REGISTRY.items():
            pairs = [(e.source, e.kind) for e in entries]
            self.assertEqual(len(pairs), len(set(pairs)), champ)

    def test_roster_coverage(self):
        # Roster fan-out (selective axis): 102 entries / 78 champions; 29 of them
        # bring a SHRED or PERCENT_PEN mechanism (the shreds_resist set), 5 of
        # which are kit-intrinsic PERCENT_PEN. Re-running
        # tools/ds_antitank_build.py against a fresh scan updates these.
        self.assertEqual(len(_ANTITANK_REGISTRY), 78)
        total = sum(len(v) for v in _ANTITANK_REGISTRY.values())
        self.assertEqual(total, 102)
        shred_champs = sum(
            1 for c in _ANTITANK_REGISTRY if compute_antitank(c).shreds_resist
        )
        self.assertEqual(shred_champs, 29)
        pen_count = sum(
            1 for v in _ANTITANK_REGISTRY.values()
            for e in v if e.kind == "PERCENT_PEN"
        )
        self.assertEqual(pen_count, 5)


class RouteAndVersionTests(unittest.TestCase):
    def test_antitank_route_registered_additively(self):
        from agents.daemon_slayer import server
        self.assertIn("/anti-tank", server._POST_ROUTES)
        self.assertIn("/anti-tank", server._GET_DISPATCH_ROUTES)
        # Additive: every existing route is still present (none replaced).
        for path in (
            "/ally-amp", "/objective-damage", "/zone-control", "/threat-range",
            "/waveclear", "/scaling", "/sustain", "/mobility", "/cc-output",
            "/ehp", "/rank-tank", "/hybrid", "/burst", "/hps", "/ability-dps",
            "/v2/matchup",
        ):
            self.assertIn(path, server._POST_ROUTES)

    def test_engine_version(self):
        self.assertEqual(ENGINE_VERSION, "1.189.0")


if __name__ == "__main__":
    unittest.main()
