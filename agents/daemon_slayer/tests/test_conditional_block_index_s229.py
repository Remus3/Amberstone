"""Phase 5.9.29 (s229, 2026-05-16) - pure-data conditional seed-expansion
+ vocab generalization (operator pivot from literal B-2).

Operator pivoted: literal B-2 (per-tick HP/CC threaded into the item-
ranking call) was found to be a mis-feature - it would flicker build
recommendations on a combat-moment signal, and the operator-commits
default (Part 1) is the *correct* model for item-build ranking. So the
schema's value is already delivered; continue option B's spirit via the
proven s207->s215/s217 schema->pure-data pattern instead.

VOCAB GENERALIZED: ``_BLOCK_INDEX_CONDITIONS`` condition key
``target_no_cc`` -> ``target_no_setup``. s228 scoped the non-HP condition
to its CC-family flagships (Zoe sleep / Evelynn charm). The expansion
candidates (Anivia E vs *Chilled*, Brand W vs *ablaze*) share the
identical modeling semantic regardless of debuff *type* - the operator's
own ability applied an amp-enabling target state; ``"default"`` is the
committed/canonical amped block, the condition key is the un-amped
downgrade when that state is absent. 5+ concrete uses -> the honest
general term (vocab stays 2 entries, NOT over-built per s227's lesson).
The 2 s228 entries (Zoe E / Evelynn Q) were migrated; the engine
validator now rejects the old ``target_no_cc`` key (a stale one fails
loudly).

3 CONVERSIONS of already-shipped unconditional entries - all provably
Part-1 no-op (``"default"`` branch == the prior int, byte-identical),
verified per-rank vs Meraki 16.10.1:
  * Morgana W = {"default": 3, "target_full_hp": 2}  - Tormented Shadow
        block 3 'Maximum Total' = exactly 2.7x block 2 'Minimum Total'
        (the <50%-max-HP amp; both full-duration channel totals so the
        downgrade is same-shape). s195's "vs rooted" framing was
        imprecise: the amp is HP-threshold; the Q-root is the operator's
        setup to hold the target in the zone.
  * Anivia E  = {"default": 1, "target_no_setup": 0} - Frostbite block 1
        'Enhanced' = exactly 2.0x block 0 'Magic Damage' vs a Chilled
        target (Anivia's own Q/passive chill - same setup model as Zoe).
  * Brand W   = {"default": 1, "target_no_setup": 0} - Pillar of Flame
        block 1 'Increased' = exactly 1.25x block 0 vs an ablaze target
        (Brand's own Blaze passive).

Deferred (registry _meta): Veigar R (clean target_full_hp execute but
the canonical stable-int test fixture - converting cascades fixture
repoints), Bel'Veth R (continuous in-block missing-HP, not a discrete
block pair), Cho'Gath R (single block), Cassiopeia E (irregular Meraki
array), Brand R / Aatrox W.
"""
from __future__ import annotations

import unittest

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


# --- vocab generalization ----------------------------------------------------


class VocabGeneralizationTests(unittest.TestCase):
    def test_vocab_is_target_full_hp_and_target_no_setup(self) -> None:
        self.assertEqual(
            _BLOCK_INDEX_CONDITIONS,
            frozenset({"target_full_hp", "target_no_setup"}),
        )

    def test_old_target_no_cc_key_now_rejected(self) -> None:
        # The s228 term was renamed; a stale 'target_no_cc' anywhere must
        # fail loudly (registry-typo guard), not silently no-op.
        with self.assertRaises(ValueError) as cm:
            _normalize_block_index_value({"default": 1, "target_no_cc": 0})
        self.assertIn("unknown block_index condition", str(cm.exception))

    def test_target_no_setup_accepted(self) -> None:
        self.assertEqual(
            _normalize_block_index_value({"default": 1, "target_no_setup": 0}),
            {"default": 1, "target_no_setup": 0},
        )


# --- s228 flagship migration (target_no_cc -> target_no_setup) ----------------


class S228MigrationTests(unittest.TestCase):
    """Zoe E + Evelynn Q (s228) migrated to the renamed key; Kindred E
    (target_full_hp) untouched by the rename."""

    def setUp(self) -> None:
        reset_block_index_cache()

    def test_zoe_E_migrated(self) -> None:
        m, _ = get_block_index_for("Zoe")
        self.assertEqual(m["E"], {"default": 2, "target_no_setup": 0})

    def test_evelynn_Q_migrated_R_preserved(self) -> None:
        # s229's durable property: Q migrated to the target_no_setup
        # key. R was a plain int 1 at s229; s231 converted it to a
        # target_full_hp execute conditional (default=1 == that int -
        # provable Part-1 no-op, so s229's intent is preserved).
        m, _ = get_block_index_for("Evelynn")
        self.assertEqual(m["Q"], {"default": 5, "target_no_setup": 0})
        self.assertEqual(m["R"], {"default": 1, "target_full_hp": 0})

    def test_kindred_E_unaffected_by_rename(self) -> None:
        m, _ = get_block_index_for("Kindred")
        self.assertEqual(m["E"], {"default": 1, "target_full_hp": 0})


# --- the 3 s229 conversions: registry shape ----------------------------------


class S229ConversionShapeTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_block_index_cache()

    def test_morgana_W_conditional_R_preserved(self) -> None:
        m, src = get_block_index_for("Morgana")
        self.assertEqual(m["W"], {"default": 3, "target_full_hp": 2})
        self.assertEqual(m["R"], 1)
        self.assertEqual(src, "champion")

    def test_anivia_E_conditional_Q_R_preserved(self) -> None:
        m, _ = get_block_index_for("Anivia")
        self.assertEqual(m["E"], {"default": 1, "target_no_setup": 0})
        self.assertEqual(m["Q"], 2)
        self.assertEqual(m["R"], 1)

    def test_brand_W_conditional_R_preserved(self) -> None:
        m, _ = get_block_index_for("Brand")
        self.assertEqual(m["W"], {"default": 1, "target_no_setup": 0})
        self.assertEqual(m["R"], 1)

    def test_registry_still_125_champions(self) -> None:
        import json
        from pathlib import Path
        reg = json.loads(
            Path("agents/daemon_slayer/champion_block_index.json")
            .read_text(encoding="utf-8")
        )
        self.assertEqual(len(reg["champions"]), 125)


# --- Part-1 zero-regression invariant (default == prior int) -----------------


class S229ZeroRegressionTests(unittest.TestCase):
    """Each conversion's registry conditional resolves byte-identical to
    the equivalent forced ``default`` int - the schema lift adds zero
    numeric change to item ranking (the whole point of the pivot)."""

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

    def test_morgana_W_registry_equals_forced_default_3(self) -> None:
        reg, ro = self._spell("Morgana", "W")
        forced, fo = self._spell(
            "Morgana", "W", block_index_overrides={"W": 3, "R": 1})
        self.assertAlmostEqual(
            reg.raw_damage_per_cast, forced.raw_damage_per_cast, places=9)
        self.assertAlmostEqual(
            ro.total_ability_dps, fo.total_ability_dps, places=9)

    def test_morgana_W_default_is_2p7x_block_2(self) -> None:
        reg, _ = self._spell("Morgana", "W")
        b2, _ = self._spell(
            "Morgana", "W", block_index_overrides={"W": 2, "R": 1})
        self.assertAlmostEqual(
            reg.raw_damage_per_cast, 2.7 * b2.raw_damage_per_cast, places=3)

    def test_anivia_E_registry_equals_forced_default_1(self) -> None:
        reg, ro = self._spell("Anivia", "E")
        forced, fo = self._spell(
            "Anivia", "E", block_index_overrides={"Q": 2, "E": 1, "R": 1})
        self.assertAlmostEqual(
            reg.raw_damage_per_cast, forced.raw_damage_per_cast, places=9)
        self.assertAlmostEqual(
            ro.total_ability_dps, fo.total_ability_dps, places=9)

    def test_anivia_E_default_is_2x_block_0(self) -> None:
        reg, _ = self._spell("Anivia", "E")
        b0, _ = self._spell(
            "Anivia", "E", block_index_overrides={"Q": 2, "E": 0, "R": 1})
        self.assertAlmostEqual(
            reg.raw_damage_per_cast, 2.0 * b0.raw_damage_per_cast, places=4)

    def test_brand_W_registry_equals_forced_default_1(self) -> None:
        reg, ro = self._spell("Brand", "W")
        forced, fo = self._spell(
            "Brand", "W", block_index_overrides={"W": 1, "R": 1})
        self.assertAlmostEqual(
            reg.raw_damage_per_cast, forced.raw_damage_per_cast, places=9)
        self.assertAlmostEqual(
            ro.total_ability_dps, fo.total_ability_dps, places=9)

    def test_brand_W_default_is_1p25x_block_0(self) -> None:
        reg, _ = self._spell("Brand", "W")
        b0, _ = self._spell(
            "Brand", "W", block_index_overrides={"W": 0, "R": 1})
        self.assertAlmostEqual(
            reg.raw_damage_per_cast, 1.25 * b0.raw_damage_per_cast, places=4)

    def test_brand_W_load_bearing(self) -> None:
        # default (block 1, +25% ablaze) strictly exceeds engine-default
        # block 0 - the conditional entry is not a no-op vs the un-mapped
        # baseline (it's a no-op only relative to the prior int entry).
        reg, _ = self._spell("Brand", "W")
        b0, _ = self._spell(
            "Brand", "W", block_index_overrides={"W": 0, "R": 1})
        self.assertGreater(reg.raw_damage_per_cast, b0.raw_damage_per_cast)


# --- backward-compat: a representative s228 + pre-s228 entry unchanged -------


class S229BackwardCompatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()
        reset_block_index_cache()

    def test_kindred_E_s228_conditional_intact(self) -> None:
        m, _ = get_block_index_for("Kindred")
        self.assertEqual(m["E"], {"default": 1, "target_full_hp": 0})

    def test_cassiopeia_E_converted_s230_part1_noop(self) -> None:
        # s229 deferred Cassi E (irregular 18-elem Meraki array). s230
        # Phase 5.9.30 resolved that carry-forward: the array is block
        # 1's base scaling, orthogonal to the conditional conversion
        # (Part-1 always resolves to default=1 == the s191 int). This
        # s229->s230 evolution guard asserts the new shape + the no-op.
        m, _ = get_block_index_for("Cassiopeia")
        self.assertEqual(m["E"], {"default": 1, "target_no_setup": 0})
        reg = next(
            s for s in compute_ability_dps(
                self.snap, "Cassiopeia", level=11, mode="SR",
                target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
            ).per_spell if s.key == "E"
        )
        forced1 = next(
            s for s in compute_ability_dps(
                self.snap, "Cassiopeia", level=11, mode="SR",
                target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
                block_index_overrides={"E": 1, "W": 1},
            ).per_spell if s.key == "E"
        )
        self.assertAlmostEqual(
            reg.raw_damage_per_cast, forced1.raw_damage_per_cast, places=9)

    def test_camille_W_still_list(self) -> None:
        m, _ = get_block_index_for("Camille")
        self.assertEqual(m["W"], [0, 1])

    def test_veigar_R_deferred_still_int(self) -> None:
        # s229 deliberately did NOT convert Veigar R (fixture cascade).
        m, _ = get_block_index_for("Veigar")
        self.assertEqual(m["R"], 1)


# --- ENGINE_VERSION pin ------------------------------------------------------


class EngineVersionS229Tests(unittest.TestCase):
    def test_engine_version(self) -> None:
        from agents import daemon_slayer

        # s231 (Phase 5.9.31) bumped to 1.3.0; pin tracks current.
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.248.0")


if __name__ == "__main__":
    unittest.main()
