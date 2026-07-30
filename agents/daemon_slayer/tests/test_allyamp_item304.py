"""Item 304 (ENGINE 1.118.0) - ally-amplification / buff-throughput scorer tests.

The fifteenth scored axis alongside DPS / burst / EHP / ability-DPS /
healing-throughput / offensive CC-output (item 294) / mobility (item 297) /
sustain (item 298) / scaling (item 299) / wave-clear (item 300) / effective
threat-range (item 301) / zone-control (item 302) / objective-damage (item 303):
how much COMBAT VALUE a champion grants to her ALLIES (the shields, heals,
steroids, hard-saves, and haste she pumps OUTWARD into her team), reduced to a
single kind-weighted, reach-scaled ``allyamp_score`` plus a ``top_kind`` label
and a ``saves_ally`` flag. Proves (a) the kind-weight * scope-mult * magnitude *
conditional math on synthetic entries (registry-independent), (b) hand-verified
champion values at pinned inputs (a hard-save enchanter, a team healer, a
shield-bot), (c) the kind -> weight + scope -> mult tiers, (d) the top_kind /
saves_ally identities, (e) the SPARSE contract (a selfish carry / assassin scores
0.0), (f) registry invariants + coverage, (g) the additive /ally-amp route
registers alongside (does not replace) the existing routes, (h) the ENGINE pin.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.allyamp import (
    _ALLYAMP_CONDITIONAL_PROB,
    _ALLYAMP_KIND_WEIGHT,
    _ALLYAMP_REGISTRY,
    _ALLYAMP_SCOPE_MULT,
    AllyAmpEntry,
    AllyAmpResult,
    _mechanism_value,
    compute_allyamp,
)


class MechanismValueMathTests(unittest.TestCase):
    def test_protect_team_unconditional(self):
        # PROTECT weight 1.0, TEAM mult 1.0, magnitude 1.0 -> 1.0.
        e = AllyAmpEntry("R", "PROTECT", "TEAM", magnitude=1.0)
        self.assertAlmostEqual(_mechanism_value(e), 1.0, places=4)

    def test_shield_single(self):
        # SHIELD weight 0.85, SINGLE mult 0.65, magnitude 0.6 -> 0.3315.
        e = AllyAmpEntry("E", "SHIELD", "SINGLE", magnitude=0.6)
        self.assertAlmostEqual(_mechanism_value(e), 0.3315, places=4)

    def test_heal_duo(self):
        # HEAL weight 0.75, DUO mult 0.8, magnitude 0.5 -> 0.3.
        e = AllyAmpEntry("W", "HEAL", "DUO", magnitude=0.5)
        self.assertAlmostEqual(_mechanism_value(e), 0.3, places=4)

    def test_haste_team_lowest_kind(self):
        # HASTE weight 0.45, TEAM mult 1.0, magnitude 0.5 -> 0.225.
        e = AllyAmpEntry("E", "HASTE", "TEAM", magnitude=0.5)
        self.assertAlmostEqual(_mechanism_value(e), 0.225, places=4)

    def test_conditional_halves_value(self):
        e = AllyAmpEntry("R", "PROTECT", "TEAM", magnitude=1.0, conditional=True)
        self.assertAlmostEqual(_mechanism_value(e), 0.5, places=4)

    def test_unknown_kind_or_scope_is_zero(self):
        self.assertEqual(
            _mechanism_value(AllyAmpEntry("Q", "NOPE", "TEAM", magnitude=1.0)),
            0.0,
        )
        self.assertEqual(
            _mechanism_value(AllyAmpEntry("Q", "PROTECT", "EVERYONE", magnitude=1.0)),
            0.0,
        )


class HandVerifiedChampionTests(unittest.TestCase):
    # Pinned exact values; re-running tools/ds_allyamp_build.py against a fresh
    # scan updates them.
    def test_taric_tops_roster_hard_save(self):
        # Taric: Q HEAL TEAM 0.55 (0.4125) + W SHIELD SINGLE 0.6 (0.3315)
        # + R PROTECT TEAM 0.92 cond (0.46) -> 1.204; top PROTECT (R), saves True.
        r = compute_allyamp("Taric")
        self.assertAlmostEqual(r.allyamp_score, 1.204, places=3)
        self.assertEqual(r.top_kind, "PROTECT")
        self.assertTrue(r.saves_ally)
        rr = next(s for s in r.sources if s.source_key == "R")
        self.assertAlmostEqual(rr.value, 0.46, places=4)
        q = next(s for s in r.sources if s.source_key == "Q")
        self.assertAlmostEqual(q.value, 0.4125, places=4)

    def test_milio_team_healer(self):
        # Milio P STEROID TEAM 0.4 (0.24) + W HEAL TEAM 0.55 (0.4125)
        # + E SHIELD SINGLE 0.55 (0.3039) + R HASTE TEAM 0.8 cond (0.18)
        # -> 1.1364; top HEAL (W edges out E), no PROTECT.
        r = compute_allyamp("Milio")
        self.assertAlmostEqual(r.allyamp_score, 1.1364, places=4)
        self.assertEqual(r.top_kind, "HEAL")
        self.assertFalse(r.saves_ally)

    def test_janna_shield_bot(self):
        # Janna P HASTE TEAM 0.35 (0.1575) + E SHIELD SINGLE 0.65 (0.3591)
        # + R HEAL TEAM 0.8 cond (0.3) -> 0.8166; top SHIELD, no PROTECT.
        r = compute_allyamp("Janna")
        self.assertAlmostEqual(r.allyamp_score, 0.8166, places=4)
        self.assertEqual(r.top_kind, "SHIELD")
        self.assertFalse(r.saves_ally)


class DirectionalTests(unittest.TestCase):
    def test_enchanters_score_high(self):
        for champ in ("Taric", "Milio", "Nami", "Janna", "Senna", "Lulu"):
            self.assertGreater(compute_allyamp(champ).allyamp_score, 0.6, champ)

    def test_selfish_champs_score_zero(self):
        # The axis is SPARSE: a champion who grants nothing to allies is absent.
        for champ in ("MasterYi", "Zed", "Talon", "Tryndamere", "Vayne",
                      "Darius", "Katarina"):
            self.assertEqual(compute_allyamp(champ).allyamp_score, 0.0, champ)

    def test_hard_save_champs_flag_true(self):
        for champ in ("Taric", "Kayle", "Zilean", "Kindred", "TahmKench",
                      "Shen", "Bard", "Akshan"):
            self.assertTrue(compute_allyamp(champ).saves_ally, champ)


class IdentityTests(unittest.TestCase):
    def test_top_kind_is_strongest_mechanism(self):
        for champ in ("Taric", "Milio", "Janna", "Lulu"):
            r = compute_allyamp(champ)
            best = max(r.sources, key=lambda s: s.value)
            self.assertEqual(r.top_kind, best.kind, champ)

    def test_saves_ally_tracks_kinds(self):
        # Every champion with a PROTECT mechanism is flagged; one without is not.
        for champ, entries in _ALLYAMP_REGISTRY.items():
            has_protect = any(e.kind == "PROTECT" for e in entries)
            self.assertEqual(
                compute_allyamp(champ).saves_ally, has_protect, champ
            )

    def test_score_is_sum_of_source_values(self):
        for champ in ("Taric", "Milio", "Nami", "Sona"):
            r = compute_allyamp(champ)
            self.assertAlmostEqual(
                r.allyamp_score, sum(s.value for s in r.sources), places=6
            )


class WeightAndScopeTierTests(unittest.TestCase):
    def test_kind_weights(self):
        self.assertEqual(_ALLYAMP_KIND_WEIGHT["PROTECT"], 1.0)
        self.assertEqual(_ALLYAMP_KIND_WEIGHT["SHIELD"], 0.85)
        self.assertEqual(_ALLYAMP_KIND_WEIGHT["HEAL"], 0.75)
        self.assertEqual(_ALLYAMP_KIND_WEIGHT["STEROID"], 0.6)
        self.assertEqual(_ALLYAMP_KIND_WEIGHT["HASTE"], 0.45)
        # Monotonic decreasing value tiers.
        vals = [
            _ALLYAMP_KIND_WEIGHT[k]
            for k in ("PROTECT", "SHIELD", "HEAL", "STEROID", "HASTE")
        ]
        self.assertEqual(vals, sorted(vals, reverse=True))

    def test_scope_mults(self):
        self.assertEqual(_ALLYAMP_SCOPE_MULT["TEAM"], 1.0)
        self.assertEqual(_ALLYAMP_SCOPE_MULT["DUO"], 0.8)
        self.assertEqual(_ALLYAMP_SCOPE_MULT["SINGLE"], 0.65)
        vals = [_ALLYAMP_SCOPE_MULT[s] for s in ("TEAM", "DUO", "SINGLE")]
        self.assertEqual(vals, sorted(vals, reverse=True))

    def test_conditional_midpoint(self):
        self.assertEqual(_ALLYAMP_CONDITIONAL_PROB, 0.5)


class EmptyAndShapeTests(unittest.TestCase):
    def test_blank_champion(self):
        r = compute_allyamp("")
        self.assertIsInstance(r, AllyAmpResult)
        self.assertEqual(r.allyamp_score, 0.0)
        self.assertEqual(r.top_kind, "")
        self.assertFalse(r.saves_ally)
        self.assertEqual(r.sources, ())

    def test_unknown_champion(self):
        r = compute_allyamp("NotAChampion")
        self.assertEqual(r.allyamp_score, 0.0)
        self.assertEqual(r.sources, ())

    def test_to_dict_shape(self):
        d = compute_allyamp("Taric").to_dict()
        for key in (
            "champion", "mode", "allyamp_score", "top_kind",
            "saves_ally", "sources",
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
        self.assertEqual(compute_allyamp("Taric", mode="ARAM").mode, "ARAM")


class RegistryInvariantTests(unittest.TestCase):
    def test_all_kinds_have_weights(self):
        for champ, entries in _ALLYAMP_REGISTRY.items():
            for e in entries:
                self.assertIn(e.kind, _ALLYAMP_KIND_WEIGHT, f"{champ} {e.source}")

    def test_all_scopes_valid(self):
        for champ, entries in _ALLYAMP_REGISTRY.items():
            for e in entries:
                self.assertIn(e.scope, _ALLYAMP_SCOPE_MULT, f"{champ} {e.source}")

    def test_all_sources_canonical(self):
        for champ, entries in _ALLYAMP_REGISTRY.items():
            for e in entries:
                self.assertIn(e.source, ("P", "Q", "W", "E", "R", "BASE"))

    def test_magnitudes_in_range(self):
        for champ, entries in _ALLYAMP_REGISTRY.items():
            for e in entries:
                self.assertTrue(0.0 < e.magnitude <= 1.0, f"{champ} {e.source}")

    def test_one_entry_per_champion_source(self):
        for champ, entries in _ALLYAMP_REGISTRY.items():
            slots = [e.source for e in entries]
            self.assertEqual(len(slots), len(set(slots)), champ)

    def test_roster_coverage(self):
        # 10-channel roster fan-out (sparse axis): 74 entries / 43 champions,
        # 8 PROTECT mechanisms (one per hard-save champion). Re-running
        # tools/ds_allyamp_build.py against a fresh scan updates these.
        self.assertEqual(len(_ALLYAMP_REGISTRY), 43)
        total = sum(len(v) for v in _ALLYAMP_REGISTRY.values())
        self.assertEqual(total, 74)
        protect_count = sum(
            1 for v in _ALLYAMP_REGISTRY.values()
            for e in v if e.kind == "PROTECT"
        )
        self.assertEqual(protect_count, 8)
        protect_champs = sum(
            1 for c in _ALLYAMP_REGISTRY if compute_allyamp(c).saves_ally
        )
        self.assertEqual(protect_champs, 8)


class RouteAndVersionTests(unittest.TestCase):
    def test_allyamp_route_registered_additively(self):
        from agents.daemon_slayer import server
        self.assertIn("/ally-amp", server._POST_ROUTES)
        self.assertIn("/ally-amp", server._GET_DISPATCH_ROUTES)
        # Additive: every existing route is still present (none replaced).
        for path in (
            "/objective-damage", "/zone-control", "/threat-range", "/waveclear",
            "/scaling", "/sustain", "/mobility", "/cc-output", "/ehp",
            "/rank-tank", "/hybrid", "/burst", "/hps", "/ability-dps",
            "/v2/matchup",
        ):
            self.assertIn(path, server._POST_ROUTES)

    def test_engine_version(self):
        self.assertEqual(ENGINE_VERSION, "1.266.0")


if __name__ == "__main__":
    unittest.main()
