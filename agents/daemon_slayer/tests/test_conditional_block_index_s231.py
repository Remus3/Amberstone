"""Phase 5.9.31 (s231, 2026-05-16) - pure-data conditional seed-
expansion, EXECUTE family. Continues the s228->s229->s230 cadence; NO
vocab change (s227 "don't over-build" - both entries reuse the existing
``target_full_hp`` term, extending the s228 Kindred E pattern).

2 CONVERSIONS of already-shipped unconditional entries - both provable
Part-1 no-op (``"default"`` branch == the prior int 1, byte-identical),
verified per-rank vs Meraki 16.10.1 + live A/B :8893.

  * Evelynn R "Last Caress" int 1 -> {"default": 1, "target_full_hp":
        0} - block 1 = EXACTLY 2.4x block 0 (the bonus-vs-sub-30%-max-HP
        execute). default = the execute block (operator-commits the
        canonical ranking assumption, s191 model - same as Kindred E
        s228); target_full_hp = block 0, the un-amped downgrade when the
        live target is above the execute threshold. Evelynn's s228
        sibling Q {default:5,target_no_setup:0} preserved.
  * KogMaw R "Living Artillery" int 1 -> {"default": 1,
        "target_full_hp": 0} - block 1 = EXACTLY 2.0x block 0 (the
        double-damage-vs-low-HP execute; base/bonus_ad/ap all 2x).

Both are TWO discrete Meraki damage blocks (a clean amped/un-amped
pair), NOT one block with a continuous missing-HP coefficient - the
precise distinction that rejected Bel'Veth R (continuous in-block 25%
missing-HP, already handled by ``_SCALING_TARGETS``).

Veigar R stays the deferred non-converted exemplar (also a clean 2.0x
execute, but the canonical stable-int test fixture - s229 _meta said
pick non-fixture executes; s231 did exactly that). Akali R/R2 NOT
touched (s192 token-variant double-count guard).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from agents.daemon_slayer import ult_rates
from agents.daemon_slayer.abilities import reset_default_cache
from agents.daemon_slayer.ability_dps import (
    _BLOCK_INDEX_CONDITIONS,
    get_block_index_for,
    reset_block_index_cache,
    reset_form_index_cache,
)
from agents.daemon_slayer.burst import compute_burst_damage
from agents.daemon_slayer.data_loader import DataSnapshot


def _snap() -> DataSnapshot:
    reset_default_cache()
    reset_block_index_cache()
    reset_form_index_cache()
    ult_rates.reset_cache()
    return DataSnapshot.load()


# --- vocab unchanged (s227 "don't over-build" - no new condition) ------------


class VocabUnchangedS231Tests(unittest.TestCase):
    def test_vocab_still_exactly_two_terms(self) -> None:
        self.assertEqual(
            _BLOCK_INDEX_CONDITIONS,
            frozenset({"target_full_hp", "target_no_setup"}),
        )


# --- registry shape ---------------------------------------------------------


class S231RegistryShapeTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_block_index_cache()

    def test_evelynn_R_conditional_Q_sibling_preserved(self) -> None:
        m, src = get_block_index_for("Evelynn")
        self.assertEqual(m["R"], {"default": 1, "target_full_hp": 0})
        # s228 sibling Q must survive the dict-merge.
        self.assertEqual(m["Q"], {"default": 5, "target_no_setup": 0})
        self.assertEqual(src, "champion")

    def test_kogmaw_R_conditional(self) -> None:
        m, _ = get_block_index_for("KogMaw")
        self.assertEqual(m["R"], {"default": 1, "target_full_hp": 0})

    def test_registry_still_125_champions(self) -> None:
        reg = json.loads(
            Path("agents/daemon_slayer/champion_block_index.json")
            .read_text(encoding="utf-8")
        )
        self.assertEqual(len(reg["champions"]), 125)


# --- Part-1 zero-regression (default == prior int 1) + load-bearing ---------


class S231ExecuteConversionTests(unittest.TestCase):
    """Each conversion's registry conditional resolves byte-identical to
    the equivalent forced ``default`` int 1 - provable Part-1 no-op. The
    execute block (default=1) strictly exceeds the full-HP downgrade
    (block 0), so the entry is load-bearing vs the un-mapped baseline."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def _burst(self, champ, **bi):
        return compute_burst_damage(
            self.snap, champ, level=11, mode="SR",
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
            **bi,
        ).total_burst_damage

    def test_evelynn_R_registry_equals_forced_default_1(self) -> None:
        reg = self._burst("Evelynn")
        forced1 = self._burst(
            "Evelynn",
            block_index_overrides={
                "R": 1, "Q": {"default": 5, "target_no_setup": 0}})
        cond = self._burst(
            "Evelynn",
            block_index_overrides={
                "R": {"default": 1, "target_full_hp": 0},
                "Q": {"default": 5, "target_no_setup": 0}})
        self.assertAlmostEqual(reg, forced1, places=6)
        self.assertAlmostEqual(reg, cond, places=6)

    def test_evelynn_R_default_is_load_bearing(self) -> None:
        reg = self._burst("Evelynn")
        forced0 = self._burst(
            "Evelynn",
            block_index_overrides={
                "R": 0, "Q": {"default": 5, "target_no_setup": 0}})
        self.assertGreater(reg, forced0)

    def test_evelynn_R_default_is_2p4x_block_0(self) -> None:
        # The discrete-pair rigor check: block 1 (default) raw == 2.4x
        # block 0 every rank (Meraki base 125->300, ap 75->180).
        out1 = compute_burst_damage(
            self.snap, "Evelynn", level=11, mode="SR",
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
            block_index_overrides={
                "R": 1, "Q": {"default": 5, "target_no_setup": 0}})
        out0 = compute_burst_damage(
            self.snap, "Evelynn", level=11, mode="SR",
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
            block_index_overrides={
                "R": 0, "Q": {"default": 5, "target_no_setup": 0}})
        r1 = next(c for c in out1.per_cast if c.ability_key == "R")
        r0 = next(c for c in out0.per_cast if c.ability_key == "R")
        self.assertAlmostEqual(r1.raw_damage, 2.4 * r0.raw_damage,
                               places=3)

    def test_kogmaw_R_registry_equals_forced_default_1(self) -> None:
        reg = self._burst("KogMaw")
        forced1 = self._burst(
            "KogMaw", block_index_overrides={"R": 1})
        cond = self._burst(
            "KogMaw",
            block_index_overrides={"R": {"default": 1,
                                         "target_full_hp": 0}})
        self.assertAlmostEqual(reg, forced1, places=6)
        self.assertAlmostEqual(reg, cond, places=6)

    def test_kogmaw_R_default_is_load_bearing(self) -> None:
        reg = self._burst("KogMaw")
        forced0 = self._burst(
            "KogMaw", block_index_overrides={"R": 0})
        self.assertGreater(reg, forced0)

    def test_kogmaw_R_default_is_2x_block_0(self) -> None:
        out1 = compute_burst_damage(
            self.snap, "KogMaw", level=11, mode="SR",
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
            block_index_overrides={"R": 1})
        out0 = compute_burst_damage(
            self.snap, "KogMaw", level=11, mode="SR",
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
            block_index_overrides={"R": 0})
        r1 = next(c for c in out1.per_cast if c.ability_key == "R")
        r0 = next(c for c in out0.per_cast if c.ability_key == "R")
        self.assertAlmostEqual(r1.raw_damage, 2.0 * r0.raw_damage,
                               places=3)


# --- backward-compat: s228/s229/s230 conditionals + deferred ints -----------


class S231BackwardCompatTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_block_index_cache()

    def test_kindred_E_s228_target_full_hp_intact(self) -> None:
        m, _ = get_block_index_for("Kindred")
        self.assertEqual(m["E"], {"default": 1, "target_full_hp": 0})

    def test_fiddlesticks_Q_s230_list_conditional_intact(self) -> None:
        m, _ = get_block_index_for("Fiddlesticks")
        self.assertEqual(
            m["Q"], {"default": [2, 3], "target_no_setup": [0, 1]})

    def test_cassiopeia_E_s230_conditional_intact(self) -> None:
        m, _ = get_block_index_for("Cassiopeia")
        self.assertEqual(m["E"], {"default": 1, "target_no_setup": 0})

    def test_veigar_R_deferred_fixture_still_int(self) -> None:
        # s229/s231 deliberately do NOT convert Veigar R (canonical
        # stable-int test fixture) - picked Evelynn/KogMaw instead.
        m, _ = get_block_index_for("Veigar")
        self.assertEqual(m["R"], 1)


# --- ENGINE_VERSION pin ------------------------------------------------------


class EngineVersionS231Tests(unittest.TestCase):
    def test_engine_version(self) -> None:
        from agents import daemon_slayer

        # s231 (Phase 5.9.31) bumped to 1.3.0; pin tracks current.
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.164.0")


if __name__ == "__main__":
    unittest.main()
