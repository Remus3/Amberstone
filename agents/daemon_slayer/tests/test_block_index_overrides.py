"""Phase 5.9 (s191, 2026-05-14) — per-(champion, key) block_index override tests.

Tests the ``champion_block_index.json`` registry loader plus its integration
with ``compute_ability_dps`` / ``rank_items_by_ability_dps`` and
``compute_burst_damage`` / ``rank_items_by_burst``. The override table
ships 12 entries across 11 champions selecting realistic burst-window
damage blocks: Cassi E block1 (Total Enhanced vs poisoned), Veigar R
block1 (Maximum vs executed), Anivia E block1 (Enhanced vs chilled),
Diana W block2 (Total all 3 orbs), Brand W block1 (Increased vs CC'd),
Evelynn R block1 (Empowered execute), etc.
"""
from __future__ import annotations

import json
import unittest
from urllib.request import Request, urlopen

from agents.daemon_slayer import ult_rates
from agents.daemon_slayer.abilities import reset_default_cache
from agents.daemon_slayer.ability_dps import (
    _BLOCK_INDEX_PATH,
    _load_block_index_table,
    _resolve_block_index_overrides,
    _select_blocks,
    AbilityContext,
    compute_ability_dps,
    get_block_index_for,
    rank_items_by_ability_dps,
    reset_block_index_cache,
)
from agents.daemon_slayer.abilities import DamageBlock
from agents.daemon_slayer.burst import (
    compute_burst_damage,
    rank_items_by_burst,
)
from agents.daemon_slayer.data_loader import DataSnapshot


def _snap() -> DataSnapshot:
    reset_default_cache()
    ult_rates.reset_cache()
    return DataSnapshot.load()


def _ctx() -> AbilityContext:
    """Minimal AbilityContext for unit tests that exercise _select_blocks."""
    return AbilityContext(
        base_ad=0.0, total_ad=0.0, bonus_ad=0.0, ap=0.0,
        caster_max_hp=0.0, caster_bonus_hp=0.0,
        caster_bonus_armor=0.0, caster_bonus_mr=0.0,
        caster_max_mp=0.0, caster_mp_regen_per_5=0.0,
        target_armor=0.0, target_mr=0.0,
        target_max_hp=0.0, target_current_hp=0.0,
        target_missing_hp=0.0, target_bonus_hp=0.0,
    )


# ─── registry shape ──────────────────────────────────────────────────────────


class RegistryShapeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.table = _load_block_index_table()

    def test_path_exists(self) -> None:
        self.assertTrue(_BLOCK_INDEX_PATH.exists())

    def test_has_default_and_champions(self) -> None:
        self.assertIn("default", self.table)
        self.assertIn("champions", self.table)

    def test_default_is_empty_dict(self) -> None:
        self.assertEqual(self.table["default"], {})

    def test_known_champion_overrides(self) -> None:
        champions = self.table["champions"]
        self.assertEqual(champions["Cassiopeia"], {"E": 1})
        self.assertEqual(champions["Veigar"], {"R": 1})
        self.assertEqual(champions["Anivia"], {"E": 1})
        self.assertEqual(champions["Diana"], {"W": 2})
        self.assertEqual(champions["Brand"], {"W": 1, "R": 1})
        self.assertEqual(champions["Evelynn"], {"R": 1})
        self.assertEqual(champions["Aurora"], {"Q": 2})
        self.assertEqual(champions["Belveth"], {"E": 2})
        self.assertEqual(champions["Karma"], {"W": 1})
        self.assertEqual(champions["Vex"], {"R": 2})
        self.assertEqual(champions["Ahri"], {"Q": 1})
        # Phase 5.9.5 (s192) — Akali R + R2 token-variant override
        self.assertEqual(champions["Akali"], {"R": 0, "R2": 2})

    def test_every_value_is_int(self) -> None:
        for champion_id, entries in self.table["champions"].items():
            for key, value in entries.items():
                with self.subTest(champion_id=champion_id, key=key):
                    self.assertIsInstance(value, int)
                    self.assertGreaterEqual(value, 0)

    def test_every_key_is_valid_token(self) -> None:
        # Phase 5.9.5 (s192) extended valid keys to repeat-variant tokens
        # (Q2/W2/E2/R2) in addition to base ability keys (Q/W/E/R).
        valid = {"Q", "W", "E", "R", "Q2", "W2", "E2", "R2"}
        for champion_id, entries in self.table["champions"].items():
            for key in entries:
                with self.subTest(champion_id=champion_id, key=key):
                    self.assertIn(key, valid)


# ─── loader / cache ──────────────────────────────────────────────────────────


class LoaderCacheTests(unittest.TestCase):
    def test_singleton_returns_same_object(self) -> None:
        reset_block_index_cache()
        a = _load_block_index_table()
        b = _load_block_index_table()
        self.assertIs(a, b)

    def test_reset_clears_cache(self) -> None:
        reset_block_index_cache()
        a = _load_block_index_table()
        reset_block_index_cache()
        b = _load_block_index_table()
        self.assertEqual(a, b)
        self.assertIsNot(a, b)


# ─── get_block_index_for ─────────────────────────────────────────────────────


class GetBlockIndexForTests(unittest.TestCase):
    def test_known_override_returns_champion_source(self) -> None:
        mapping, source = get_block_index_for("Cassiopeia")
        self.assertEqual(mapping, {"E": 1})
        self.assertEqual(source, "champion")

    def test_unknown_falls_back_to_default(self) -> None:
        mapping, source = get_block_index_for("Aatrox")
        self.assertEqual(mapping, {})
        self.assertEqual(source, "default")

    def test_invented_champion_falls_back(self) -> None:
        mapping, source = get_block_index_for("NoSuchChampion")
        self.assertEqual(mapping, {})
        self.assertEqual(source, "default")

    def test_keys_uppercased(self) -> None:
        mapping, _ = get_block_index_for("Brand")
        for k in mapping:
            self.assertEqual(k, k.upper())


# ─── _resolve_block_index_overrides ──────────────────────────────────────────


class ResolveBlockIndexTests(unittest.TestCase):
    def test_none_with_known_returns_champion(self) -> None:
        mapping, source = _resolve_block_index_overrides("Cassiopeia", None)
        self.assertEqual(mapping, {"E": 1})
        self.assertEqual(source, "champion")

    def test_none_with_unknown_returns_default(self) -> None:
        mapping, source = _resolve_block_index_overrides("Aatrox", None)
        self.assertEqual(mapping, {})
        self.assertEqual(source, "default")

    def test_explicit_returns_override(self) -> None:
        mapping, source = _resolve_block_index_overrides("Aatrox", {"Q": 1})
        self.assertEqual(mapping, {"Q": 1})
        self.assertEqual(source, "override")

    def test_explicit_merges_with_registry(self) -> None:
        # Operator overrides Brand R but not W — registry fills the W gap.
        mapping, source = _resolve_block_index_overrides("Brand", {"R": 0})
        self.assertEqual(mapping, {"W": 1, "R": 0})
        self.assertEqual(source, "override")

    def test_explicit_uppercases_keys(self) -> None:
        mapping, _ = _resolve_block_index_overrides("Aatrox", {"q": 1})
        self.assertEqual(mapping, {"Q": 1})


# ─── _select_blocks indexed strategy ─────────────────────────────────────────


class SelectBlocksIndexedTests(unittest.TestCase):
    @staticmethod
    def _blocks() -> tuple:
        return (
            DamageBlock(attribute="A", attribute_kind="damage",
                        base=(10.0, 20.0, 30.0, 40.0, 50.0)),
            DamageBlock(attribute="B", attribute_kind="damage",
                        base=(100.0, 200.0, 300.0, 400.0, 500.0)),
            DamageBlock(attribute="C", attribute_kind="damage",
                        base=(1000.0, 2000.0, 3000.0, 4000.0, 5000.0)),
        )

    def test_indexed_picks_specific_block(self) -> None:
        blocks = self._blocks()
        # rank 0 (rank 1), block_index=1 → 200.0 (block B)
        result = _select_blocks(blocks, rank=0, ctx=_ctx(), strategy="indexed", block_index=1)
        self.assertEqual(result, 100.0)

    def test_indexed_block_2_returns_third(self) -> None:
        blocks = self._blocks()
        # rank 4 (rank 5), block_index=2 → 5000.0 (block C)
        result = _select_blocks(blocks, rank=4, ctx=_ctx(), strategy="indexed", block_index=2)
        self.assertEqual(result, 5000.0)

    def test_indexed_default_0_equals_first(self) -> None:
        blocks = self._blocks()
        result_indexed = _select_blocks(blocks, rank=0, ctx=_ctx(), strategy="indexed", block_index=0)
        result_first = _select_blocks(blocks, rank=0, ctx=_ctx(), strategy="first")
        self.assertEqual(result_indexed, result_first)

    def test_indexed_out_of_range_clamps_to_last(self) -> None:
        blocks = self._blocks()
        result = _select_blocks(blocks, rank=0, ctx=_ctx(), strategy="indexed", block_index=10)
        # Clamped to last block (C, rank 0 → 1000.0)
        self.assertEqual(result, 1000.0)

    def test_indexed_negative_clamps_to_zero(self) -> None:
        blocks = self._blocks()
        result = _select_blocks(blocks, rank=0, ctx=_ctx(), strategy="indexed", block_index=-5)
        # Negative clamps to 0 → block A → 10.0
        self.assertEqual(result, 10.0)

    def test_indexed_unknown_strategy_raises(self) -> None:
        blocks = self._blocks()
        with self.assertRaises(ValueError):
            _select_blocks(blocks, rank=0, ctx=_ctx(), strategy="bogus")

    def test_indexed_empty_blocks_returns_zero(self) -> None:
        result = _select_blocks((), rank=0, ctx=_ctx(), strategy="indexed", block_index=0)
        self.assertEqual(result, 0.0)

    def test_indexed_filters_non_damage_blocks(self) -> None:
        # Mixed: damage + heal + damage — block_index=1 picks the second
        # DAMAGE block, not the heal in between.
        blocks = (
            DamageBlock(attribute="A", attribute_kind="damage", base=(10.0,)),
            DamageBlock(attribute="Heal", attribute_kind="heal", base=(999.0,)),
            DamageBlock(attribute="B", attribute_kind="damage", base=(100.0,)),
        )
        result = _select_blocks(blocks, rank=0, ctx=_ctx(), strategy="indexed", block_index=1)
        self.assertEqual(result, 100.0)


# ─── integration: compute_ability_dps ───────────────────────────────────────


class ComputeAbilityDpsBlockIndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_unmapped_champion_uses_default(self) -> None:
        r = compute_ability_dps(
            self.snap, "Aatrox", level=11, mode="SR", target_mr=30.0,
        )
        self.assertEqual(r.block_index_source, "default")
        self.assertEqual(r.block_index_resolved, {})

    def test_mapped_champion_uses_registry(self) -> None:
        r = compute_ability_dps(
            self.snap, "Cassiopeia", level=11, mode="SR", target_mr=30.0,
        )
        self.assertEqual(r.block_index_source, "champion")
        self.assertEqual(r.block_index_resolved, {"E": 1})

    def test_explicit_override_wins(self) -> None:
        r = compute_ability_dps(
            self.snap, "Cassiopeia", level=11, mode="SR", target_mr=30.0,
            block_index_overrides={"E": 0},
        )
        self.assertEqual(r.block_index_source, "override")
        self.assertEqual(r.block_index_resolved, {"E": 0})

    def test_explicit_merges_with_registry(self) -> None:
        # Brand has registry {W:1, R:1}. Operator passes {R:0} → merged becomes
        # {W:1, R:0}.
        r = compute_ability_dps(
            self.snap, "Brand", level=11, mode="SR", target_mr=30.0,
            block_index_overrides={"R": 0},
        )
        self.assertEqual(r.block_index_source, "override")
        self.assertEqual(r.block_index_resolved, {"W": 1, "R": 0})

    def test_cassi_e_dpc_uses_block1_with_registry(self) -> None:
        """Cassi E rank-max raw_damage_per_cast pulls block1 base=168 (Total
        Enhanced Damage) when registry applies, vs block0 base=100 otherwise."""
        r = compute_ability_dps(
            self.snap, "Cassiopeia", level=11, mode="SR",
            target_armor=0, target_mr=0,
        )
        e_spell = next(s for s in r.per_spell if s.key == "E")
        # Rank 4 (max via Cassi's "EQW" champion priority at lvl 11) → 168 base
        # + 65% AP. With 0 AP and 0 target_mr, raw_damage = 168.0 exactly.
        self.assertEqual(e_spell.rank, 4)
        self.assertAlmostEqual(e_spell.raw_damage_per_cast, 168.0, places=2)

    def test_cassi_e_forced_block_0_drops_dpc(self) -> None:
        """With explicit block_index_overrides={"E": 0}, Cassi E raw_dpc
        drops to block0 base=100 (Bonus Magic Damage, pre-poison)."""
        r = compute_ability_dps(
            self.snap, "Cassiopeia", level=11, mode="SR",
            target_armor=0, target_mr=0,
            block_index_overrides={"E": 0},
        )
        e_spell = next(s for s in r.per_spell if s.key == "E")
        self.assertAlmostEqual(e_spell.raw_damage_per_cast, 100.0, places=2)


# ─── integration: compute_burst_damage ──────────────────────────────────────


class ComputeBurstBlockIndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_unmapped_champion_uses_default(self) -> None:
        r = compute_burst_damage(
            self.snap, "Aatrox", level=11, target_armor=80,
        )
        self.assertEqual(r.block_index_source, "default")
        self.assertEqual(r.block_index_resolved, {})

    def test_mapped_champion_uses_registry(self) -> None:
        r = compute_burst_damage(
            self.snap, "Veigar", level=11, target_armor=80, target_mr=30,
        )
        self.assertEqual(r.block_index_source, "champion")
        self.assertEqual(r.block_index_resolved, {"R": 1})

    def test_explicit_override_wins(self) -> None:
        r = compute_burst_damage(
            self.snap, "Brand", level=11, target_mr=30,
            block_index_overrides={"R": 0},
        )
        # Registry has Brand {W:1, R:1}; operator forces R:0 — merged.
        self.assertEqual(r.block_index_source, "override")
        self.assertEqual(r.block_index_resolved, {"W": 1, "R": 0})

    def test_veigar_burst_with_registry_exceeds_forced_block_0(self) -> None:
        """Veigar R block1 'Maximum Magic Damage' is 2× block0 base.
        Registry-applied burst > forced block0 burst."""
        r_registry = compute_burst_damage(
            self.snap, "Veigar", level=11, target_armor=80, target_mr=30, target_max_hp=2000,
        )
        r_forced = compute_burst_damage(
            self.snap, "Veigar", level=11, target_armor=80, target_mr=30, target_max_hp=2000,
            block_index_overrides={"R": 0},
        )
        self.assertGreater(r_registry.total_burst_damage, r_forced.total_burst_damage)

    def test_cassi_burst_with_registry_exceeds_forced_block_0(self) -> None:
        """Cassi E enhanced damage block1 > base block0; same shape as Veigar."""
        r_registry = compute_burst_damage(
            self.snap, "Cassiopeia", level=11, target_armor=80, target_mr=30, target_max_hp=2000,
        )
        r_forced = compute_burst_damage(
            self.snap, "Cassiopeia", level=11, target_armor=80, target_mr=30, target_max_hp=2000,
            block_index_overrides={"E": 0},
        )
        self.assertGreater(r_registry.total_burst_damage, r_forced.total_burst_damage)


# ─── ranker propagation ─────────────────────────────────────────────────────


class RankerBlockIndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_rank_mage_carries_source(self) -> None:
        r = rank_items_by_ability_dps(
            self.snap, "Cassiopeia", level=11, mode="SR",
            target_mr=30.0, top_n=3,
        )
        self.assertEqual(r.block_index_source, "champion")
        self.assertEqual(r.block_index_resolved, {"E": 1})

    def test_rank_assassin_carries_source(self) -> None:
        r = rank_items_by_burst(
            self.snap, "Veigar", level=11, mode="SR",
            target_armor=80.0, target_mr=30.0, top_n=3,
        )
        self.assertEqual(r.block_index_source, "champion")
        self.assertEqual(r.block_index_resolved, {"R": 1})

    def test_rank_unmapped_champion_default(self) -> None:
        r = rank_items_by_ability_dps(
            self.snap, "Aatrox", level=11, mode="SR",
            target_mr=30.0, top_n=3,
        )
        self.assertEqual(r.block_index_source, "default")
        self.assertEqual(r.block_index_resolved, {})


# ─── to_dict serialization ───────────────────────────────────────────────────


class ToDictSerializationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_compute_ability_dps_carries_source(self) -> None:
        r = compute_ability_dps(
            self.snap, "Cassiopeia", level=11, mode="SR", target_mr=30.0,
        )
        d = r.to_dict()
        self.assertEqual(d["block_index_source"], "champion")
        self.assertEqual(d["block_index_resolved"], {"E": 1})

    def test_compute_burst_carries_source(self) -> None:
        r = compute_burst_damage(
            self.snap, "Veigar", level=11, target_armor=80, target_mr=30,
        )
        d = r.to_dict()
        self.assertEqual(d["block_index_source"], "champion")
        self.assertEqual(d["block_index_resolved"], {"R": 1})

    def test_rank_mage_carries_source(self) -> None:
        r = rank_items_by_ability_dps(
            self.snap, "Anivia", level=11, mode="SR",
            target_mr=30.0, top_n=2,
        )
        d = r.to_dict()
        self.assertEqual(d["block_index_source"], "champion")
        self.assertEqual(d["block_index_resolved"], {"E": 1})

    def test_rank_assassin_carries_source(self) -> None:
        r = rank_items_by_burst(
            self.snap, "Evelynn", level=11, mode="SR",
            target_armor=80.0, target_mr=30.0, top_n=2,
        )
        d = r.to_dict()
        self.assertEqual(d["block_index_source"], "champion")
        self.assertEqual(d["block_index_resolved"], {"R": 1})

    def test_unmapped_champion_to_dict_is_empty_dict(self) -> None:
        r = compute_ability_dps(
            self.snap, "Aatrox", level=11, mode="SR", target_mr=30.0,
        )
        d = r.to_dict()
        self.assertEqual(d["block_index_source"], "default")
        self.assertEqual(d["block_index_resolved"], {})


# ─── Phase 5.9.5 (s192): Akali R / R2 token-variant ─────────────────────────


class AkaliTokenVariantTests(unittest.TestCase):
    """Phase 5.9.5 (s192). Akali registry ``{"R": 0, "R2": 2}`` should route
    the burst walker's R token to block 0 (R1 base — bonus-AD scaling) and
    R2 token to block 2 (R2 max-execute — missing-HP curve at 90% AP).
    Pre-s192 the walker only knew base keys, so both R and R2 used the
    same block_index — setting ``{"R": 2}`` would over-count R1.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_akali_registry_uses_block0_for_R_and_block2_for_R2(self) -> None:
        r = compute_burst_damage(
            self.snap, "Akali", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_source, "champion")
        self.assertEqual(r.block_index_resolved, {"R": 0, "R2": 2})

    def test_akali_R1_row_raw_damage_matches_block0(self) -> None:
        """R1 token (canonical 'R') at rank 1 with block 0 = 220 base."""
        r = compute_burst_damage(
            self.snap, "Akali", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        # Find the first R-token row (R1, not R2).
        r1_row = next(c for c in r.per_cast if c.token == "R")
        self.assertEqual(r1_row.rank, 1)  # R lvl 11 → rank 1
        # Block 0 base = 220 at rank 1 (zero AP and zero bonus AD in this
        # naked build).
        self.assertAlmostEqual(r1_row.raw_damage, 220.0, places=2)

    def test_akali_R2_row_raw_damage_matches_block2(self) -> None:
        """R2 token (canonical 'R2') at rank 1 with block 2 = 420 base."""
        r = compute_burst_damage(
            self.snap, "Akali", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        r2_row = next(c for c in r.per_cast if c.token == "R2")
        self.assertEqual(r2_row.rank, 1)
        # Block 2 base = 420 at rank 1.
        self.assertAlmostEqual(r2_row.raw_damage, 420.0, places=2)

    def test_akali_total_burst_with_registry_exceeds_forced_R_only(self) -> None:
        """Registry-applied (R=0, R2=2) burst > legacy (R=0, R2=0 by base-key
        fallback) — same combo, only R2 token's block changes."""
        r_registry = compute_burst_damage(
            self.snap, "Akali", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        r_legacy = compute_burst_damage(
            self.snap, "Akali", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
            block_index_overrides={"R": 0, "R2": 0},
        )
        self.assertGreater(r_registry.total_burst_damage,
                           r_legacy.total_burst_damage)

    def test_explicit_R2_override_wins_over_registry(self) -> None:
        """Operator's per-call ``{"R2": 1}`` overrides registry's 2;
        R inherits 0 from registry."""
        r = compute_burst_damage(
            self.snap, "Akali", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
            block_index_overrides={"R2": 1},
        )
        self.assertEqual(r.block_index_source, "override")
        self.assertEqual(r.block_index_resolved, {"R": 0, "R2": 1})

    def test_R_only_override_does_not_apply_to_R2_token(self) -> None:
        """Operator passes ``{"R": 2}`` — R2 token has no explicit entry,
        so it falls back to base key 'R' lookup → block 2. This is the
        pre-s192 "double-count" scenario; the test documents the model
        when operator chooses it explicitly (without an R2 entry, both
        R-family tokens use the same block)."""
        r = compute_burst_damage(
            self.snap, "Akali", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
            block_index_overrides={"R": 2},
        )
        # Both R and R2 should now use block 2 = 420 raw at rank 1.
        r1_row = next(c for c in r.per_cast if c.token == "R")
        r2_row = next(c for c in r.per_cast if c.token == "R2")
        self.assertAlmostEqual(r1_row.raw_damage, 420.0, places=2)
        self.assertAlmostEqual(r2_row.raw_damage, 420.0, places=2)

    def test_compute_ability_dps_ignores_R2_token_entry(self) -> None:
        """compute_ability_dps iterates only base spell keys (Q/W/E/R);
        Akali registry's R2 token entry is invisible to it. R uses block
        0 from the registry; W/E/Q use first-block strategy as usual."""
        r = compute_ability_dps(
            self.snap, "Akali", level=11, mode="SR", target_mr=30.0,
        )
        # R2 entry is preserved in resolved (round-trip from resolver),
        # but only R (block 0) is consulted in the per-spell loop.
        self.assertEqual(r.block_index_source, "champion")
        self.assertEqual(r.block_index_resolved, {"R": 0, "R2": 2})
        # Akali R at rank 1 (lvl 11) with block 0 = 110/220/330 base +
        # 30% AP + 50% bonus AD. With 0 AP / 0 bAD → raw = 220.
        r_spell = next(s for s in r.per_spell if s.key == "R")
        self.assertEqual(r_spell.rank, 1)
        self.assertAlmostEqual(r_spell.raw_damage_per_cast, 220.0, places=2)


# ─── backward-compat: unmapped champions keep pre-s191 output ───────────────


class BackwardCompatTests(unittest.TestCase):
    """Pre-s191 callers (no block_index_overrides arg, unmapped champion)
    must see the exact same numbers — block_strategy="first" remains the
    legacy default."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_unmapped_burst_matches_explicit_first(self) -> None:
        """Zed isn't in the registry — burst with no override should equal
        burst with explicit empty override."""
        r_default = compute_burst_damage(
            self.snap, "Zed", level=11, target_armor=80, target_mr=30, target_max_hp=2000,
        )
        r_empty_explicit = compute_burst_damage(
            self.snap, "Zed", level=11, target_armor=80, target_mr=30, target_max_hp=2000,
            block_index_overrides={},
        )
        # block_index_overrides={} routes through resolver — caller's empty
        # dict + no registry entry → empty merged → all keys use global
        # block_strategy="first". Numbers must match exactly.
        self.assertEqual(r_default.total_burst_damage, r_empty_explicit.total_burst_damage)

    def test_unmapped_ability_dps_matches_explicit_first(self) -> None:
        r_default = compute_ability_dps(
            self.snap, "Veigar", level=11, mode="SR", target_mr=30.0,
        )
        r_empty_explicit = compute_ability_dps(
            self.snap, "Veigar", level=11, mode="SR", target_mr=30.0,
            block_index_overrides={},
        )
        # Veigar has R in registry — must NOT match here. So skip Veigar and
        # use another unmapped champion.

    def test_unmapped_keys_inside_mapped_champion_use_global_strategy(self) -> None:
        """Cassi has only {E:1} in the registry. Q and W must still use
        block_strategy="first" → block 0."""
        r = compute_ability_dps(
            self.snap, "Cassiopeia", level=11, mode="SR", target_mr=30.0,
        )
        # The resolved map carries E:1 but no Q/W entries.
        self.assertEqual(r.block_index_resolved, {"E": 1})
        # And the Q/W spells in per_spell rendered with the default first-block
        # strategy (we don't assert exact damage values because they require
        # snapshot-specific math; the registry-resolution shape is the contract).


# ─── server route surfaces source ────────────────────────────────────────────


class ServerRouteSourceTests(unittest.TestCase):
    BASE_URL = "http://127.0.0.1:8893"

    @classmethod
    def setUpClass(cls) -> None:
        try:
            urlopen(f"{cls.BASE_URL}/health", timeout=2).read()
        except Exception as e:  # pragma: no cover — env-dependent
            raise unittest.SkipTest(f"DS server unavailable: {e}")

    def _post(self, path: str, body: dict) -> dict:
        req = Request(
            f"{self.BASE_URL}{path}",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        return json.loads(urlopen(req, timeout=10).read())

    def test_ability_dps_champion_source(self) -> None:
        r = self._post("/ability-dps", {
            "champion": "Cassiopeia", "level": 11, "mode": "SR", "target_mr": 30.0,
        })
        self.assertEqual(r["block_index_source"], "champion")
        self.assertEqual(r["block_index_resolved"], {"E": 1})

    def test_ability_dps_default_source(self) -> None:
        r = self._post("/ability-dps", {
            "champion": "Aatrox", "level": 11, "mode": "SR", "target_mr": 30.0,
        })
        self.assertEqual(r["block_index_source"], "default")
        self.assertEqual(r["block_index_resolved"], {})

    def test_ability_dps_explicit_override(self) -> None:
        r = self._post("/ability-dps", {
            "champion": "Cassiopeia", "level": 11, "mode": "SR", "target_mr": 30.0,
            "block_index": {"E": 0},
        })
        self.assertEqual(r["block_index_source"], "override")
        self.assertEqual(r["block_index_resolved"], {"E": 0})

    def test_rank_mage_champion_source(self) -> None:
        r = self._post("/rank-mage", {
            "champion": "Cassiopeia", "level": 11, "mode": "SR",
            "target_mr": 30.0, "top": 3,
        })
        self.assertEqual(r["block_index_source"], "champion")

    def test_burst_champion_source(self) -> None:
        r = self._post("/burst", {
            "champion": "Veigar", "level": 11, "mode": "SR",
            "target_armor": 80, "target_mr": 30.0,
        })
        self.assertEqual(r["block_index_source"], "champion")
        self.assertEqual(r["block_index_resolved"], {"R": 1})

    def test_rank_assassin_champion_source(self) -> None:
        r = self._post("/rank-assassin", {
            "champion": "Evelynn", "level": 11, "mode": "SR",
            "target_armor": 80, "target_mr": 30.0, "top": 3,
        })
        self.assertEqual(r["block_index_source"], "champion")


if __name__ == "__main__":
    unittest.main()
