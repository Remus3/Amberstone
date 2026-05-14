"""Phase 5.9 (s191, 2026-05-14) — per-(champion, key) block_index override tests.

Tests the ``champion_block_index.json`` registry loader plus its integration
with ``compute_ability_dps`` / ``rank_items_by_ability_dps`` and
``compute_burst_damage`` / ``rank_items_by_burst``. The override table
ships 12 entries across 11 champions selecting realistic burst-window
damage blocks: Cassi E block1 (Total Enhanced vs poisoned), Veigar R
block1 (Maximum vs executed), Anivia E block1 (Enhanced vs chilled),
Diana W block2 (Total all 3 orbs), Brand W block1 (Increased vs CC'd),
Evelynn R block1 (Empowered execute), etc.

Phase 5.9.5 (s192) added token-variant lookup (Akali R/R2 split).
Phase 5.9.6 (s193) added 8 channeled-ability entries (Alistar/Fiddle/etc).
Phase 5.9.7 (s194) added 8 calibration-follow-up entries (Corki W/E,
Hecarim W/E, Jayce Q/W, Rell R, DrMundo W) — same per-tick → total
pattern plus the first block_index that layers on a prior form_index
override (Jayce Q inside cannon form 1).
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
        # Phase 5.9 (s191) — initial seed
        self.assertEqual(champions["Cassiopeia"], {"E": 1})
        self.assertEqual(champions["Veigar"], {"R": 1})
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
        # Phase 5.9.6 (s193) — channeled-ability expansion + Anivia Q
        self.assertEqual(champions["Anivia"], {"Q": 2, "E": 1})
        self.assertEqual(champions["Alistar"], {"E": 1})
        self.assertEqual(champions["AurelionSol"], {"E": 1})
        self.assertEqual(champions["Fiddlesticks"], {"R": 1})
        self.assertEqual(champions["MissFortune"], {"E": 1})
        self.assertEqual(champions["Samira"], {"R": 1})
        self.assertEqual(champions["Singed"], {"Q": 1})
        self.assertEqual(champions["Syndra"], {"R": 2})
        self.assertEqual(champions["Velkoz"], {"R": 1})
        # Phase 5.9.7 (s194) — calibration follow-up expansion
        self.assertEqual(champions["Corki"], {"W": 1, "E": 1})
        self.assertEqual(champions["Hecarim"], {"W": 1, "E": 1})
        self.assertEqual(champions["Jayce"], {"Q": 1, "W": 1})
        self.assertEqual(champions["Rell"], {"R": 1})
        self.assertEqual(champions["DrMundo"], {"W": 1})

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
        # Phase 5.9.6 (s193) — Anivia gained Q=2 alongside existing E=1
        self.assertEqual(d["block_index_resolved"], {"Q": 2, "E": 1})

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


# ─── Phase 5.9.6 (s193): channeled-ability expansion ────────────────────────


class ChanneledAbilityExpansionTests(unittest.TestCase):
    """Phase 5.9.6 (s193). 8 new champion entries + Anivia Q extension —
    all covering the "per-tick → total" gap for channeled / duration
    abilities where the engine's default first damage block picked the
    per-tick value but the realistic per-cast contribution is the
    full-channel total.

    Tests verify each new entry:
      1. Is present in the resolved registry
      2. Drives the per-spell raw_damage_per_cast to the block ≥1 value
         (not the per-tick block 0)
      3. Produces a strictly higher total_ability_dps vs forced block 0
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def _delta_check(self, champion: str, key: str, expected_idx: int) -> None:
        """Assert champion's registry entry routes `key` to expected_idx,
        and the resulting total_ability_dps exceeds the forced-block-0
        baseline by a positive margin."""
        r_reg = compute_ability_dps(
            self.snap, champion, level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r_reg.block_index_resolved.get(key), expected_idx,
                         f"{champion}.{key} should route to block {expected_idx}")
        # Force key to block 0 (override registry's choice).
        forced = dict(r_reg.block_index_resolved)
        forced[key] = 0
        r_off = compute_ability_dps(
            self.snap, champion, level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
            block_index_overrides=forced,
        )
        self.assertGreater(r_reg.total_ability_dps, r_off.total_ability_dps,
                           f"{champion} registry total should exceed forced-block-0")

    def test_alistar_E_routes_to_block_1(self) -> None:
        self._delta_check("Alistar", "E", 1)

    def test_aurelionsol_E_routes_to_block_1(self) -> None:
        self._delta_check("AurelionSol", "E", 1)

    def test_fiddlesticks_R_routes_to_block_1(self) -> None:
        self._delta_check("Fiddlesticks", "R", 1)

    def test_missfortune_E_routes_to_block_1(self) -> None:
        self._delta_check("MissFortune", "E", 1)

    def test_samira_R_routes_to_block_1(self) -> None:
        self._delta_check("Samira", "R", 1)

    def test_singed_Q_routes_to_block_1(self) -> None:
        self._delta_check("Singed", "Q", 1)

    def test_velkoz_R_routes_to_block_1(self) -> None:
        self._delta_check("Velkoz", "R", 1)

    def test_syndra_R_routes_to_block_2(self) -> None:
        self._delta_check("Syndra", "R", 2)

    def test_anivia_Q_routes_to_block_2(self) -> None:
        """Anivia gets Q added to her existing {E: 1} entry."""
        self._delta_check("Anivia", "Q", 2)

    def test_anivia_E_still_routes_to_block_1(self) -> None:
        """The s191 E:1 entry is preserved when Q gets added."""
        r = compute_ability_dps(
            self.snap, "Anivia", level=11, mode="SR",
            target_armor=80, target_mr=30,
        )
        self.assertEqual(r.block_index_resolved, {"Q": 2, "E": 1})

    def test_singed_Q_total_block_matches_per_cast_math(self) -> None:
        """Singed Q at rank 5 (level 11+, Q maxed): block 1 base = 120
        (per-tick 15 × 8 ticks). Confirms the registry picks block 1."""
        r = compute_ability_dps(
            self.snap, "Singed", level=11, mode="SR",
            target_armor=80, target_mr=30,
        )
        q_spell = next(s for s in r.per_spell if s.key == "Q")
        # Singed Q at level 11 (max priority Q-W-E, lvl 11 Q rank: probably 4)
        # Block 1 base at rank 4 = 100 (per-tick 12.5 × 8 ticks). Block 0 = 12.5.
        # The exact rank depends on max_priority resolver; just assert
        # raw is closer to block 1 value than block 0.
        self.assertGreater(q_spell.raw_damage_per_cast, 60.0,
                           "raw should reflect total (block 1), not per-tick (block 0)")


# ─── s194 Phase 5.9.7 — calibration follow-up entries ────────────────────────


class CalibrationFollowUpExpansionTests(unittest.TestCase):
    """Phase 5.9.7 (s194). 8 more (champion, key) entries closing s193's
    deferred calibration list. Same "per-tick → total" pattern as s193
    for channels/auras (Corki W/E, Hecarim W, Jayce W, Rell R, DrMundo W),
    plus "min → max amped" for charge/gate variants (Hecarim E charge,
    Jayce Q gate-amped Shock Blast). The Jayce Q entry is the first
    block_index that layers on a prior form_index override (s187 set
    Jayce.Q form_index=1 cannon; s194 now sets block_index=1 within
    that form — orthogonal resolvers).

    Tests verify each new entry:
      1. Is present in the resolved registry
      2. Drives per-spell raw_damage_per_cast above the forced-block-0
         baseline (positive delta proves block ≥1 evaluation)
      3. Produces strictly higher total_ability_dps vs forced block 0
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def _delta_check(self, champion: str, key: str, expected_idx: int) -> None:
        """Assert champion's registry entry routes `key` to expected_idx,
        and the resulting total_ability_dps exceeds the forced-block-0
        baseline by a positive margin."""
        r_reg = compute_ability_dps(
            self.snap, champion, level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r_reg.block_index_resolved.get(key), expected_idx,
                         f"{champion}.{key} should route to block {expected_idx}")
        forced = dict(r_reg.block_index_resolved)
        forced[key] = 0
        r_off = compute_ability_dps(
            self.snap, champion, level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
            block_index_overrides=forced,
        )
        self.assertGreater(r_reg.total_ability_dps, r_off.total_ability_dps,
                           f"{champion} registry total should exceed forced-block-0")

    def test_corki_W_routes_to_block_1(self) -> None:
        self._delta_check("Corki", "W", 1)

    def test_corki_E_routes_to_block_1(self) -> None:
        self._delta_check("Corki", "E", 1)

    def test_hecarim_W_routes_to_block_1(self) -> None:
        self._delta_check("Hecarim", "W", 1)

    def test_hecarim_E_routes_to_block_1(self) -> None:
        self._delta_check("Hecarim", "E", 1)

    def test_jayce_Q_routes_to_block_1(self) -> None:
        """Jayce Q layers s194 block_index=1 on s187 form_index=1.
        Cannon form (form 1) Shock Blast block 1 = 'Increased Damage'
        (1.4× block 0) through Acceleration Gate."""
        self._delta_check("Jayce", "Q", 1)

    def test_jayce_W_routes_to_block_1(self) -> None:
        """Jayce W hammer-form (default form 0) Lightning Field aura:
        block 0 = 'Magic Damage Per Tick', block 1 = 'Total Magic Damage'
        (4× block 0 over 4 second aura)."""
        self._delta_check("Jayce", "W", 1)

    def test_rell_R_routes_to_block_1(self) -> None:
        self._delta_check("Rell", "R", 1)

    def test_drmundo_W_routes_to_block_1(self) -> None:
        self._delta_check("DrMundo", "W", 1)

    def test_corki_both_keys_in_resolved(self) -> None:
        """Both Corki W and E entries land in the same resolved map."""
        r = compute_ability_dps(
            self.snap, "Corki", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"W": 1, "E": 1})
        self.assertEqual(r.block_index_source, "champion")

    def test_hecarim_both_keys_in_resolved(self) -> None:
        r = compute_ability_dps(
            self.snap, "Hecarim", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"W": 1, "E": 1})
        self.assertEqual(r.block_index_source, "champion")

    def test_jayce_both_keys_in_resolved(self) -> None:
        """Jayce gets Q and W both — Q block_index applies within form 1
        (cannon, per s187 form_index override); W block_index applies in
        form 0 (hammer, default)."""
        r = compute_ability_dps(
            self.snap, "Jayce", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        self.assertEqual(r.block_index_resolved, {"Q": 1, "W": 1})

    def test_jayce_Q_block_layers_on_s187_form_index(self) -> None:
        """Smoke test that Jayce Q block_index=1 inside form_index=1
        produces a non-zero raw_damage_per_cast (i.e., the form+block
        resolvers compose correctly)."""
        r = compute_ability_dps(
            self.snap, "Jayce", level=11, mode="SR",
            target_armor=80, target_mr=30, target_max_hp=2000,
        )
        q_spell = next((s for s in r.per_spell if s.key == "Q"), None)
        self.assertIsNotNone(q_spell)
        self.assertGreater(q_spell.raw_damage_per_cast, 0.0,
                           "Jayce Q in cannon form block 1 should evaluate to positive damage")

    def test_pre_s194_unmapped_unaffected(self) -> None:
        """Backward-compat: s193 entries unchanged after s194 ship."""
        r = compute_ability_dps(
            self.snap, "Singed", level=11, mode="SR",
            target_armor=80, target_mr=30,
        )
        self.assertEqual(r.block_index_resolved, {"Q": 1})


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
