"""2026-05-30 (DS scraper-review slice) - champion ability heal/shield scorer tests.

Pins ``ability_hps.compute_ability_hps`` against ground-truth values probed
directly from the live 16.11.1 abilities snapshot. Closes the DS-review
finding that champion-spell heal/shield blocks (96 heal + 56 shield at
16.11.1) were extracted but never consumed.

Root finding the parser fixes: heal/shield blocks store their numbers ONLY
in ``raw_modifiers`` (flat + ``% AP`` / ``% bonus AD`` / ``% max health``),
never in the typed scaling fields the damage evaluator reads - so the
damage-block ``_evaluate_block`` returns 0 for every heal/shield block.
``_eval_heal_shield_block`` parses raw_modifiers directly.

Per-cast values are deterministic block math (base + AP/AD/HP scaling at
rank); per-second folds in measured cast rate so is asserted structurally.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from agents.daemon_slayer.ability_hps import (
    AbilityHpsResult,
    _eval_heal_shield_block,
    _is_meta_heal_shield,
    compute_ability_hps,
)
from agents.daemon_slayer.data_loader import DataSnapshot

_SNAP = DataSnapshot.load()


class AbilityHpsGroundTruthTests(unittest.TestCase):
    """Pin per-spell heal/shield per-cast at lvl 11 itemless SR (ap=0).

    Values are the rank-resolved base term of each champion's heal/shield
    raw_modifiers (Q>W>E max order; R at 6/11/16).
    """

    def test_soraka_w_heal_per_cast(self):
        r = compute_ability_hps(_SNAP, "Soraka", 11, mode="SR")
        w = next(s for s in r.spells if s.key == "W")
        self.assertAlmostEqual(w.heal_per_cast, 130.0, places=1)  # [90,110,130,..] r2
        self.assertEqual(w.shield_per_cast, 0.0)
        self.assertGreater(r.total_heal_per_sec, 0.0)
        self.assertEqual(r.total_shield_per_sec, 0.0)

    def test_nami_w_heal_per_cast(self):
        r = compute_ability_hps(_SNAP, "Nami", 11, mode="SR")
        w = next(s for s in r.spells if s.key == "W")
        self.assertAlmostEqual(w.heal_per_cast, 105.0, places=1)  # [55,80,105,..] r2

    def test_janna_e_shield_per_cast(self):
        r = compute_ability_hps(_SNAP, "Janna", 11, mode="SR")
        e = next(s for s in r.spells if s.key == "E")
        self.assertAlmostEqual(e.shield_per_cast, 80.0, places=1)  # [80,120,..] r0
        self.assertEqual(e.heal_per_cast, 0.0)
        self.assertGreater(r.total_shield_per_sec, 0.0)

    def test_lulu_e_shield_per_cast(self):
        r = compute_ability_hps(_SNAP, "Lulu", 11, mode="SR")
        e = next(s for s in r.spells if s.key == "E")
        self.assertAlmostEqual(e.shield_per_cast, 80.0, places=1)  # [80,120,..] r0

    def test_sona_w_dual_heal_and_shield(self):
        # Sona W carries BOTH a Heal block and a Shield Strength block.
        r = compute_ability_hps(_SNAP, "Sona", 11, mode="SR")
        w = next(s for s in r.spells if s.key == "W")
        self.assertAlmostEqual(w.heal_per_cast, 60.0, places=1)    # [30,45,60,..] r2
        self.assertAlmostEqual(w.shield_per_cast, 65.0, places=1)  # [25,45,65,..] r2
        self.assertGreater(r.total_heal_per_sec, 0.0)
        self.assertGreater(r.total_shield_per_sec, 0.0)


class AbilityHpsScalingTests(unittest.TestCase):
    def test_ap_raises_heal(self):
        base = compute_ability_hps(_SNAP, "Soraka", 11, mode="SR")
        with_ap = compute_ability_hps(_SNAP, "Soraka", 11, item_ids=["3089"], mode="SR")
        bw = next(s for s in base.spells if s.key == "W")
        aw = next(s for s in with_ap.spells if s.key == "W")
        # Soraka W = 130 base + 50% AP at the engine-resolved (amped) AP.
        self.assertAlmostEqual(bw.heal_per_cast, 130.0, places=1)
        self.assertAlmostEqual(
            aw.heal_per_cast, 130.0 + 0.50 * with_ap.ap, places=1,
        )
        self.assertGreater(aw.heal_per_cast, bw.heal_per_cast)
        self.assertGreater(with_ap.ap, base.ap)

    def test_ap_raises_shield(self):
        base = compute_ability_hps(_SNAP, "Janna", 11, mode="SR")
        with_ap = compute_ability_hps(_SNAP, "Janna", 11, item_ids=["3089"], mode="SR")
        be = next(s for s in base.spells if s.key == "E")
        ae = next(s for s in with_ap.spells if s.key == "E")
        # Janna E = 80 base + 55% AP at the engine-resolved (amped) AP.
        self.assertAlmostEqual(
            ae.shield_per_cast, 80.0 + 0.55 * with_ap.ap, places=1,
        )
        self.assertGreater(ae.shield_per_cast, be.shield_per_cast)


class AbilityHpsMetaBlockTests(unittest.TestCase):
    """Meta blocks (cost reductions / multipliers / HP grants) are skipped."""

    def test_meta_attribute_detection(self):
        self.assertTrue(_is_meta_heal_shield("Reduced Health Cost"))
        self.assertTrue(_is_meta_heal_shield("Healing Percentage"))
        self.assertTrue(_is_meta_heal_shield("Increased Base Health"))
        self.assertTrue(_is_meta_heal_shield("Heal and Shield Power"))
        self.assertFalse(_is_meta_heal_shield("Heal"))
        self.assertFalse(_is_meta_heal_shield("Shield Strength"))

    def test_soraka_w_cost_reduction_not_counted_as_heal(self):
        # Soraka W has a "Reduced Health Cost" block also tagged heal; it
        # must NOT inflate the heal amount (would add the % max-health cost).
        r = compute_ability_hps(_SNAP, "Soraka", 11, mode="SR")
        w = next(s for s in r.spells if s.key == "W")
        self.assertAlmostEqual(w.heal_per_cast, 130.0, places=1)


class AbilityHpsUnresolvedUnitTests(unittest.TestCase):
    def test_target_max_health_shield_is_lower_bound(self):
        # Taric W = "% of target's maximum health" - a target-relative unit
        # we cannot resolve at rest. The block contributes 0 and is flagged.
        from agents.daemon_slayer.abilities import DamageBlock
        b = DamageBlock(
            attribute="Shield Strength", attribute_kind="shield",
            raw_modifiers=({"values": [10, 12, 14, 16, 18],
                            "units": ["% of target's maximum health"] * 5},),
        )

        class _Ctx:
            ap = 0.0
        amt, unres = _eval_heal_shield_block(b, 2, _Ctx())
        self.assertEqual(amt, 0.0)
        self.assertTrue(unres)


class AbilityHpsNoHealChampionTests(unittest.TestCase):
    def test_caitlyn_zero(self):
        r = compute_ability_hps(_SNAP, "Caitlyn", 11, mode="SR")
        self.assertEqual(r.total_ability_hps, 0.0)
        self.assertEqual(r.spells, ())
        self.assertTrue(any("no active-ability heal/shield" in n for n in r.notes))

    def test_total_is_sum_of_components(self):
        r = compute_ability_hps(_SNAP, "Sona", 11, mode="SR")
        self.assertAlmostEqual(
            r.total_ability_hps,
            r.total_heal_per_sec + r.total_shield_per_sec,
            places=6,
        )


class AbilityHpsModeMultiplierTests(unittest.TestCase):
    def test_sr_mults_are_unity(self):
        r = compute_ability_hps(_SNAP, "Soraka", 11, mode="SR")
        self.assertEqual(r.heal_mult, 1.0)
        self.assertEqual(r.shield_mult, 1.0)

    def test_aram_mult_folds_into_per_sec_not_per_cast(self):
        sr = compute_ability_hps(_SNAP, "Soraka", 11, mode="SR")
        aram = compute_ability_hps(_SNAP, "Soraka", 11, mode="ARAM")
        sw = next(s for s in sr.spells if s.key == "W")
        aw = next(s for s in aram.spells if s.key == "W")
        # per-cast is mode-independent (block math); the mult lands per-sec.
        self.assertAlmostEqual(sw.heal_per_cast, aw.heal_per_cast, places=4)


class AbilityHpsBlockStrategyTests(unittest.TestCase):
    def test_invalid_strategy_raises(self):
        with self.assertRaises(ValueError):
            compute_ability_hps(_SNAP, "Soraka", 11, block_strategy="nonsense")

    def test_sum_ge_first(self):
        first = compute_ability_hps(_SNAP, "Soraka", 11, block_strategy="first")
        summed = compute_ability_hps(_SNAP, "Soraka", 11, block_strategy="sum")
        self.assertGreaterEqual(summed.total_ability_hps, first.total_ability_hps)


class AbilityHpsContractTests(unittest.TestCase):
    def test_to_dict_roundtrips(self):
        r = compute_ability_hps(_SNAP, "Soraka", 11, mode="SR")
        d = r.to_dict()
        self.assertEqual(d["champion_id"], "Soraka")
        self.assertIn("total_ability_hps", d)
        self.assertIsInstance(d["spells"], list)
        json.dumps(d)  # must be JSON-serializable

    def test_format_table_runs(self):
        r = compute_ability_hps(_SNAP, "Soraka", 11, mode="SR")
        txt = r.format_table()
        self.assertIn("ABILITY HPS", txt)
        self.assertIn("Soraka", txt)

    def test_returns_result_type(self):
        r = compute_ability_hps(_SNAP, "Lulu", 11, mode="SR")
        self.assertIsInstance(r, AbilityHpsResult)

    def test_level_18_resolves(self):
        r = compute_ability_hps(_SNAP, "Soraka", 18, mode="SR")
        self.assertEqual(r.level, 18)
        self.assertGreater(r.total_ability_hps, 0.0)


class AbilityHpsRosterCoverageTests(unittest.TestCase):
    """At least the known enchanter set must surface non-zero throughput."""

    def test_enchanter_set_nonzero(self):
        for c in ["Soraka", "Nami", "Janna", "Lulu", "Sona", "Seraphine",
                  "Yuumi", "Diana", "Garen"]:
            r = compute_ability_hps(_SNAP, c, 11, mode="SR")
            self.assertGreater(
                r.total_ability_hps, 0.0,
                f"{c} should have non-zero ability heal/shield",
            )


class AsciiHygieneTests(unittest.TestCase):
    def test_module_is_ascii(self):
        for rel in ("ability_hps.py", "tests/test_ability_hps_2026_05_30.py"):
            p = Path(__file__).resolve().parents[1] / rel
            data = p.read_bytes()
            non_ascii = [(i, b) for i, b in enumerate(data) if b > 0x7F]
            self.assertEqual(non_ascii, [], f"{rel} has non-ASCII bytes: {non_ascii[:5]}")


if __name__ == "__main__":
    unittest.main()
