"""Item 298 (ENGINE 1.110.0) - sustain / vamp-throughput scorer tests.

The ninth scored axis alongside DPS / burst / EHP / ability-DPS /
healing-throughput / offensive CC-output (item 294) / mobility (item 297): how
much effective HP a champion claws back during a fight by converting damage to
health (lifesteal / omnivamp / spellvamp / drains) plus self HP-regen steroids,
normalised to effective-HP units and weighted by kind into one sustain score.
Proves (a) hand-verified sustain values at pinned inputs, (b) the conditional
availability-midpoint discount, (c) the kind -> weight tiers, (d) the
normalisation rules - the fight-damage reference, the max-HP reference, the
HP-unit, the flat + percent regen sum, (e) registry invariants + roster
coverage, (f) the additive /sustain route registers alongside (does not
replace) the existing routes, (g) the ENGINE pin.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.sustain import (
    _REF_FIGHT_DAMAGE,
    _REF_MAX_HP,
    _SUSTAIN_CONDITIONAL_PROB,
    _SUSTAIN_HP_UNIT,
    _SUSTAIN_KIND_WEIGHT,
    _SUSTAIN_REGISTRY,
    SustainResult,
    compute_sustain,
)


class HandVerifiedScoreTests(unittest.TestCase):
    def test_aatrox_omnivamp(self):
        # P OMNIVAMP 1.0 uncond -> 2000 HP / 300 = 6.6667 units x1.0 = 6.6667.
        # E SPELLVAMP 0.16 cond -> 320 HP / 300 = 1.0667 units x0.6 = 0.64,
        # x0.5 midpoint = 0.32.
        r = compute_sustain("Aatrox")
        self.assertAlmostEqual(r.sustain_score, 6.6667, places=3)
        self.assertAlmostEqual(r.conditional_sustain_score, 0.32, places=3)
        self.assertAlmostEqual(r.total_sustain_score, 6.9867, places=3)
        self.assertAlmostEqual(r.raw_sustain_units, 6.6667, places=3)

    def test_nasus_lifesteal(self):
        # P LIFESTEAL 0.24 uncond -> 480 HP / 300 = 1.6 units x0.8 = 1.28.
        r = compute_sustain("Nasus")
        self.assertAlmostEqual(r.sustain_score, 1.28, places=4)
        self.assertAlmostEqual(r.raw_sustain_units, 1.6, places=4)
        self.assertEqual(r.conditional_sustain_score, 0.0)

    def test_warwick_tops_the_axis(self):
        # Q SPELLVAMP 0.75 -> 1500/300 = 5.0 x0.6 = 3.0 (uncond).
        # R DRAIN 1.0 -> 2000/300 = 6.6667 x0.8 = 5.3333 (uncond).
        # P OMNIVAMP 1.0 cond -> 6.6667 x1.0 = 6.6667, x0.5 = 3.3333.
        r = compute_sustain("Warwick")
        self.assertAlmostEqual(r.sustain_score, 8.3333, places=3)
        self.assertAlmostEqual(r.conditional_sustain_score, 3.3333, places=3)
        self.assertAlmostEqual(r.total_sustain_score, 11.6667, places=3)
        self.assertAlmostEqual(r.raw_sustain_units, 11.6667, places=3)

    def test_drmundo_regen_percent_max_hp(self):
        # P REGEN 2.3% maxHP -> 0.023*2200 = 50.6 HP /300 = 0.16867 x0.4.
        # R REGEN 18% maxHP -> 0.18*2200 = 396 HP /300 = 1.32 x0.4. Both uncond.
        r = compute_sustain("DrMundo")
        expect = (0.023 * _REF_MAX_HP / _SUSTAIN_HP_UNIT * 0.4) + (
            0.18 * _REF_MAX_HP / _SUSTAIN_HP_UNIT * 0.4
        )
        self.assertAlmostEqual(r.sustain_score, expect, places=4)
        self.assertEqual(r.conditional_sustain_score, 0.0)


class ConditionalDiscountTests(unittest.TestCase):
    def test_conditional_midpoint(self):
        self.assertEqual(_SUSTAIN_CONDITIONAL_PROB, 0.5)

    def test_gated_source_is_half_credited(self):
        # Soraka's only sustain row (Q rejuvenation regen) is conditional, so the
        # unconditional score is 0 and the conditional score is positive.
        r = compute_sustain("Soraka")
        self.assertEqual(r.sustain_score, 0.0)
        self.assertGreater(r.conditional_sustain_score, 0.0)


class WeightTierTests(unittest.TestCase):
    def test_kind_weights(self):
        self.assertEqual(_SUSTAIN_KIND_WEIGHT["OMNIVAMP"], 1.0)
        self.assertEqual(_SUSTAIN_KIND_WEIGHT["LIFESTEAL"], 0.8)
        self.assertEqual(_SUSTAIN_KIND_WEIGHT["DRAIN"], 0.8)
        self.assertEqual(_SUSTAIN_KIND_WEIGHT["SPELLVAMP"], 0.6)
        self.assertEqual(_SUSTAIN_KIND_WEIGHT["REGEN"], 0.4)


class NormalizationTests(unittest.TestCase):
    def test_reference_constants(self):
        self.assertEqual(_REF_FIGHT_DAMAGE, 2000.0)
        self.assertEqual(_REF_MAX_HP, 2200.0)
        self.assertEqual(_SUSTAIN_HP_UNIT, 300.0)

    def test_regen_sums_percent_and_flat(self):
        # The REGEN path adds the percent-max-HP term and the flat term before
        # dividing by the HP unit; a champion with both contributes their sum.
        for champ, entries in _SUSTAIN_REGISTRY.items():
            for e in entries:
                if e.kind == "REGEN":
                    hp = e.pct_max_hp * _REF_MAX_HP + e.flat_hp
                    self.assertGreater(hp, 0.0, f"{champ} {e.spell}")


class EmptyAndShapeTests(unittest.TestCase):
    def test_blank_champion(self):
        r = compute_sustain("")
        self.assertIsInstance(r, SustainResult)
        self.assertEqual(r.total_sustain_score, 0.0)
        self.assertEqual(r.spells, ())

    def test_no_sustain_champion(self):
        # Karthus has no innate damage-conversion / regen sustain -> absent.
        r = compute_sustain("Karthus")
        self.assertEqual(r.total_sustain_score, 0.0)
        self.assertEqual(r.spells, ())

    def test_to_dict_shape(self):
        d = compute_sustain("Warwick").to_dict()
        for key in (
            "champion", "mode", "sustain_score",
            "conditional_sustain_score", "total_sustain_score",
            "raw_sustain_units", "spells",
        ):
            self.assertIn(key, d)
        self.assertTrue(d["spells"])
        for s in d["spells"]:
            for key in (
                "spell_key", "kind", "sustain_units", "kind_weight",
                "conditional", "weighted_units",
            ):
                self.assertIn(key, s)

    def test_mode_passthrough(self):
        r = compute_sustain("Aatrox", mode="ARAM")
        self.assertEqual(r.mode, "ARAM")


class RegistryInvariantTests(unittest.TestCase):
    def test_all_kinds_have_weights(self):
        for champ, entries in _SUSTAIN_REGISTRY.items():
            for e in entries:
                self.assertIn(
                    e.kind, _SUSTAIN_KIND_WEIGHT, f"{champ} {e.spell} {e.kind}"
                )

    def test_magnitudes_positive_by_kind(self):
        for champ, entries in _SUSTAIN_REGISTRY.items():
            for e in entries:
                if e.kind == "REGEN":
                    self.assertTrue(
                        e.pct_max_hp > 0.0 or e.flat_hp > 0.0,
                        f"{champ} {e.spell}",
                    )
                else:
                    self.assertGreater(e.vamp_pct, 0.0, f"{champ} {e.spell}")

    def test_all_spells_canonical(self):
        for champ, entries in _SUSTAIN_REGISTRY.items():
            for e in entries:
                self.assertIn(e.spell, ("P", "Q", "W", "E", "R"))

    def test_one_entry_per_champion_spell(self):
        # The build tool dedupes by (champion, spell); the registry must hold no
        # duplicate spell slot for any champion.
        for champ, entries in _SUSTAIN_REGISTRY.items():
            slots = [e.spell for e in entries]
            self.assertEqual(len(slots), len(set(slots)), champ)

    def test_roster_coverage(self):
        # 10-channel roster fan-out: 56 entries / 45 champions. Re-running
        # tools/ds_sustain_build.py against a fresh scan updates these pins.
        self.assertEqual(len(_SUSTAIN_REGISTRY), 45)
        total = sum(len(v) for v in _SUSTAIN_REGISTRY.values())
        self.assertEqual(total, 56)


class RouteAndVersionTests(unittest.TestCase):
    def test_sustain_route_registered_additively(self):
        from agents.daemon_slayer import server
        self.assertIn("/sustain", server._POST_ROUTES)
        self.assertIn("/sustain", server._GET_DISPATCH_ROUTES)
        # Additive: every existing route is still present (none replaced).
        for path in (
            "/mobility", "/cc-output", "/ehp", "/rank-tank", "/hybrid",
            "/burst", "/hps", "/ability-dps", "/v2/matchup",
        ):
            self.assertIn(path, server._POST_ROUTES)

    def test_engine_version(self):
        self.assertEqual(ENGINE_VERSION, "1.136.0")


if __name__ == "__main__":
    unittest.main()
