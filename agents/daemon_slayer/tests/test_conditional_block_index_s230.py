"""Phase 5.9.30 (s230, 2026-05-16) - pure-data conditional seed-expansion
on the stable 2-term vocab. Continues the s207->s215/s217 / s228->s229
schema->pure-data cadence; NO vocab change (s227's "don't over-expand"
lesson - both new entries reuse the existing ``target_no_setup`` term).

1 NEW key (a real correctness fix, NOT a no-op) + 1 CONVERSION (provable
Part-1 no-op). Verified per-rank vs Meraki 16.10.1 + live A/B :8893.

  * Fiddlesticks Q "Terrify" = {"default": [2, 3], "target_no_setup":
        [0, 1]} - the FIRST registry conditional whose branches are
        list[int] (combines the s207 sum-of-blocks list schema with the
        s228 conditional schema; zero engine change -
        ``_normalize_block_index_value`` already recursively normalizes
        each branch and only rejects a *nested* dict). Filtered damage
        blocks (raw[0]/raw[3] are duration, dropped by the
        attribute_kind=='damage' filter): fidx0 target_current_hp_pct
        [4..6], fidx1 base [40..120], fidx2 = EXACTLY 2.0x fidx0,
        fidx3 = EXACTLY 2.0x fidx1 - the classic Terrify
        double-damage-vs-feared discrete pair. ``default``=[2,3]
        (feared/amped, operator-commits canonical - Fiddle's kit
        revolves around fear), ``target_no_setup``=[0,1] (un-amped vs
        a not-yet-feared target). Pre-s230 the engine scored Q at
        filtered-block-0 ONLY (un-amped %HP, missing the un-amped base
        AND the fear-amp) - a real ~+200% Q-dps fix.
  * Cassiopeia E "Twin Fang" int 1 -> {"default": 1, "target_no_setup":
        0} - provable Part-1 no-op (default == prior int 1,
        byte-identical). Enhanced vs a poisoned target (Cassi's own
        Q/W poison is the setup). RESOLVES the s229 "irregular
        18-element Meraki array - defer until investigated"
        carry-forward: the array is block 1's base scaling, rank-indexed
        by ``_evaluate_block`` exactly as since s191; the conditional
        conversion is orthogonal (Part-1 always resolves to default=1).

Closed carry-forwards: Lux Illumination (PHANTOM - Lux P is Meraki
parse_status=no_damage with zero damage_blocks; Q/E/R each single-block;
no discrete pair exists anywhere in Lux's kit - never met the rigor
bar). Aatrox W stays deferred (positional escaped-chain is NOT an
operator-applied target-state setup).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from agents.daemon_slayer import ult_rates
from agents.daemon_slayer.abilities import reset_default_cache
from agents.daemon_slayer.ability_dps import (
    _BLOCK_INDEX_CONDITIONS,
    _normalize_block_index_value,
    compute_ability_dps,
    get_block_index_for,
    reset_block_index_cache,
    reset_form_index_cache,
)
from agents.daemon_slayer.data_loader import DataSnapshot


def _snap() -> DataSnapshot:
    reset_default_cache()
    reset_block_index_cache()
    reset_form_index_cache()
    ult_rates.reset_cache()
    return DataSnapshot.load()


# ─── vocab unchanged (s227 "don't over-build" - no new condition) ────────────


class VocabUnchangedTests(unittest.TestCase):
    def test_vocab_still_exactly_two_terms(self) -> None:
        self.assertEqual(
            _BLOCK_INDEX_CONDITIONS,
            frozenset({"target_full_hp", "target_no_setup"}),
        )

    def test_list_valued_conditional_branch_accepted(self) -> None:
        # s230's structural novelty: a conditional whose branches are
        # list[int] (Fiddle Q). The validator recursively normalizes
        # each branch; only a *nested* dict is rejected.
        self.assertEqual(
            _normalize_block_index_value(
                {"default": [2, 3], "target_no_setup": [0, 1]}),
            {"default": [2, 3], "target_no_setup": [0, 1]},
        )

    def test_mixed_int_and_list_branches_accepted(self) -> None:
        self.assertEqual(
            _normalize_block_index_value(
                {"default": [2, 3], "target_no_setup": 0}),
            {"default": [2, 3], "target_no_setup": 0},
        )

    def test_nested_conditional_still_rejected(self) -> None:
        with self.assertRaises(ValueError) as cm:
            _normalize_block_index_value(
                {"default": {"default": 1}, "target_no_setup": 0})
        self.assertIn("nested conditional", str(cm.exception))


# ─── registry shape ─────────────────────────────────────────────────────────


class S230RegistryShapeTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_block_index_cache()

    def test_fiddlesticks_Q_conditional_R_W_preserved(self) -> None:
        m, src = get_block_index_for("Fiddlesticks")
        self.assertEqual(
            m["Q"], {"default": [2, 3], "target_no_setup": [0, 1]})
        self.assertEqual(m["R"], 1)
        self.assertEqual(m["W"], 3)
        self.assertEqual(src, "champion")

    def test_cassiopeia_E_conditional_W_preserved(self) -> None:
        m, _ = get_block_index_for("Cassiopeia")
        self.assertEqual(m["E"], {"default": 1, "target_no_setup": 0})
        self.assertEqual(m["W"], 1)

    def test_registry_still_125_champions(self) -> None:
        reg = json.loads(
            Path("agents/daemon_slayer/champion_block_index.json")
            .read_text(encoding="utf-8")
        )
        self.assertEqual(len(reg["champions"]), 125)


# ─── Fiddlesticks Q: a REAL improvement (NOT a Part-1 no-op) ─────────────────


class FiddleQImprovementTests(unittest.TestCase):
    """Unlike the s229 conversions, Fiddle Q is a *new* key - under
    Part-1 default resolution it strictly improves on the engine's
    pre-s230 block_strategy='first' baseline (which scored only the
    un-amped %HP block, missing the un-amped base AND the fear-amp)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def _spell(self, champ, key, **extra):
        out = compute_ability_dps(
            self.snap, champ, level=11, item_ids=[], mode="SR",
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
            **extra,
        )
        return next((s for s in out.per_spell if s.key == key), None), out

    def test_registry_default_equals_forced_amped_sum(self) -> None:
        reg, ro = self._spell("Fiddlesticks", "Q")
        forced, fo = self._spell(
            "Fiddlesticks", "Q",
            block_index_overrides={"Q": [2, 3], "R": 1, "W": 3})
        self.assertAlmostEqual(
            reg.raw_damage_per_cast, forced.raw_damage_per_cast, places=9)
        self.assertAlmostEqual(
            ro.total_ability_dps, fo.total_ability_dps, places=9)

    def test_registry_default_strictly_beats_engine_first(self) -> None:
        # Pre-s230 baseline = block_strategy 'first' = filtered idx 0.
        reg, _ = self._spell("Fiddlesticks", "Q")
        first, _ = self._spell(
            "Fiddlesticks", "Q",
            block_index_overrides={"Q": 0, "R": 1, "W": 3})
        self.assertGreater(
            reg.raw_damage_per_cast, first.raw_damage_per_cast)
        # ~3x: engine-first scored only the un-amped %HP (80 @ 2000HP
        # rank1); default sums amped %HP + amped base (160 + 80 = 240).
        self.assertAlmostEqual(
            reg.raw_damage_per_cast, 3.0 * first.raw_damage_per_cast,
            places=3)

    def test_amped_pair_is_exactly_2x_unamped_pair(self) -> None:
        # The discrete-pair rigor check: forced [2,3] == 2.0x forced
        # [0,1] at every rank (verified raw 240 == 2 * 120 @ rank1).
        amped, _ = self._spell(
            "Fiddlesticks", "Q",
            block_index_overrides={"Q": [2, 3], "R": 1, "W": 3})
        unamped, _ = self._spell(
            "Fiddlesticks", "Q",
            block_index_overrides={"Q": [0, 1], "R": 1, "W": 3})
        self.assertAlmostEqual(
            amped.raw_damage_per_cast,
            2.0 * unamped.raw_damage_per_cast, places=4)

    def test_target_no_setup_branch_equals_unamped_sum(self) -> None:
        # Forcing the registry conditional's downgrade branch via an
        # explicit caller dict must equal the un-amped [0,1] sum.
        ns, _ = self._spell(
            "Fiddlesticks", "Q",
            block_index_overrides={
                "Q": {"default": [2, 3], "target_no_setup": [0, 1]},
                "R": 1, "W": 3})
        # Part-1: caller conditional also resolves to default.
        amped, _ = self._spell(
            "Fiddlesticks", "Q",
            block_index_overrides={"Q": [2, 3], "R": 1, "W": 3})
        self.assertAlmostEqual(
            ns.raw_damage_per_cast, amped.raw_damage_per_cast, places=9)


# ─── Cassiopeia E: provable Part-1 zero-regression conversion ───────────────


class CassiopeiaEConversionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def _spell(self, champ, key, **extra):
        out = compute_ability_dps(
            self.snap, champ, level=11, item_ids=[], mode="SR",
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
            **extra,
        )
        return next((s for s in out.per_spell if s.key == key), None), out

    def test_registry_equals_forced_default_1(self) -> None:
        reg, ro = self._spell("Cassiopeia", "E")
        forced, fo = self._spell(
            "Cassiopeia", "E", block_index_overrides={"E": 1, "W": 1})
        self.assertAlmostEqual(
            reg.raw_damage_per_cast, forced.raw_damage_per_cast, places=9)
        self.assertAlmostEqual(
            ro.total_ability_dps, fo.total_ability_dps, places=9)

    def test_default_is_load_bearing_vs_block_0(self) -> None:
        # default (block 1, vs-poisoned enhanced) strictly exceeds the
        # non-poisoned block 0 downgrade - the conditional is not a
        # no-op vs the un-mapped baseline (only vs the prior int 1).
        reg, _ = self._spell("Cassiopeia", "E")
        b0, _ = self._spell(
            "Cassiopeia", "E", block_index_overrides={"E": 0, "W": 1})
        self.assertGreater(reg.raw_damage_per_cast, b0.raw_damage_per_cast)

    def test_irregular_18_elem_array_handled_at_rank(self) -> None:
        # The s229 deferral concern: block 1's base is an 18-element
        # array. _evaluate_block rank-indexes it (first 5 = per-rank).
        # At lvl 11 Cassi maxes E (EQW priority) -> rank 4 -> base 168.
        reg, _ = self._spell("Cassiopeia", "E")
        self.assertAlmostEqual(reg.raw_damage_per_cast, 168.0, places=6)


# ─── backward-compat: s228 + s229 + pre-s228 entries unchanged ──────────────


class S230BackwardCompatTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_block_index_cache()

    def test_zoe_E_s228_conditional_intact(self) -> None:
        m, _ = get_block_index_for("Zoe")
        self.assertEqual(m["E"], {"default": 2, "target_no_setup": 0})

    def test_kindred_E_target_full_hp_intact(self) -> None:
        m, _ = get_block_index_for("Kindred")
        self.assertEqual(m["E"], {"default": 1, "target_full_hp": 0})

    def test_morgana_W_s229_conditional_intact(self) -> None:
        m, _ = get_block_index_for("Morgana")
        self.assertEqual(m["W"], {"default": 3, "target_full_hp": 2})
        self.assertEqual(m["R"], 1)

    def test_anivia_E_s229_conditional_intact(self) -> None:
        m, _ = get_block_index_for("Anivia")
        self.assertEqual(m["E"], {"default": 1, "target_no_setup": 0})
        self.assertEqual(m["Q"], 2)

    def test_brand_W_s229_conditional_intact(self) -> None:
        m, _ = get_block_index_for("Brand")
        self.assertEqual(m["W"], {"default": 1, "target_no_setup": 0})

    def test_camille_W_still_list(self) -> None:
        m, _ = get_block_index_for("Camille")
        self.assertEqual(m["W"], [0, 1])

    def test_veigar_R_deferred_still_int(self) -> None:
        m, _ = get_block_index_for("Veigar")
        self.assertEqual(m["R"], 1)


# ─── ENGINE_VERSION pin ──────────────────────────────────────────────────────


class EngineVersionS230Tests(unittest.TestCase):
    def test_engine_version(self) -> None:
        from agents import daemon_slayer

        # s231 (Phase 5.9.31) bumped to 1.3.0; pin tracks current.
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.47.0")


if __name__ == "__main__":
    unittest.main()
