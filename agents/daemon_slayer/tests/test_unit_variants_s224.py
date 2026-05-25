"""Phase 5.9.24 (s224, 2026-05-16) - unmapped-key pass on COVERED
champions: Bel'Veth R entry + _UNIT_TO_FIELD health-variant completion.

The s223 5-way scan proved the *uncovered-champion* block_index space
saturated. s224 worked the orthogonal space - ability KEYS on already-
covered champions not yet in the registry - via a pre-filter over all
125 covered champs. It surfaced:

  PART 1 (block_index) - Bel'Veth R=1. "Endless Banquet" block 1 is the
  canonical recast nuke (150-250 + 100% AP + 25% missing-HP); the engine
  defaulted to block 0 (6-10 per-takedown true dmg, ~25x under). This
  CORRECTS s223's over-conservative "no entry, already parsed" call -
  field-parsed ≠ engine-block-selected. Bel'Veth → {E:2, R:1}.

  PART 2 (parser, s223-sibling) - `_UNIT_TO_FIELD` was missing a family
  of Meraki text-drift health-unit variants (double-space, "the
  target's", caster pronoun/name forms). 8 keys added; a deterministic
  audit-gated migration promoted exactly 32 modifiers across 13
  champions (Ambessa Q · Braum Q · Briar W · Fiddlesticks Q · Gnar E ·
  Gwen Q·R · Maokai Q · Sejuani W · Skarner E · TahmKench R · Trundle R ·
  Varus W · Zac Q) whose %HP component was silently dropped - Trundle R
  and Fiddlesticks Q evaluated to 0 entirely pre-s224.

ENGINE_VERSION 0.95.0 → 0.96.0 pinned.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import ult_rates
from agents.daemon_slayer.abilities import load_default, reset_default_cache
from agents.daemon_slayer.ability_dps import (
    compute_ability_dps,
    get_block_index_for,
    reset_block_index_cache,
    reset_form_index_cache,
)
from agents.daemon_slayer.data_loader import DataSnapshot
from tools.daemon_slayer_abilities_extract import (
    _UNIT_TO_FIELD,
    _canonicalize_unit,
)


def _snap() -> DataSnapshot:
    reset_default_cache()
    reset_block_index_cache()
    reset_form_index_cache()
    ult_rates.reset_cache()
    return DataSnapshot.load()


# ─── PART 2a - _UNIT_TO_FIELD variant additions ──────────────────────────────


class UnitTableVariantTests(unittest.TestCase):
    def test_target_health_textdrift_variants(self) -> None:
        self.assertEqual(_UNIT_TO_FIELD["%  of target's current health"],
                         "target_current_hp_pct")
        self.assertEqual(_UNIT_TO_FIELD["% of the target's maximum health"],
                         "target_max_hp_pct")
        self.assertEqual(_UNIT_TO_FIELD["%  of the target's maximum health"],
                         "target_max_hp_pct")
        self.assertEqual(_UNIT_TO_FIELD["% of the target's missing health"],
                         "target_missing_hp_pct")

    def test_caster_max_health_pronoun_and_name_forms(self) -> None:
        for u in ("% of his maximum health", "% of her maximum health",
                  "% of Braum's maximum health", "% of Zac's maximum health"):
            self.assertEqual(_UNIT_TO_FIELD[u], "caster_max_hp_pct")

    def test_nested_paren_plus_the_target_composes(self) -> None:
        """s223's _canonicalize_unit + s224's "the target's" key compose:
        a nested-conditional "the target's" unit still resolves."""
        canon = _canonicalize_unit(
            "% (+ 2% per 100 AP) of the target's maximum health"
        )
        self.assertEqual(_UNIT_TO_FIELD.get(canon), "target_max_hp_pct")

    def test_existing_keys_untouched(self) -> None:
        """Pure additions - the pre-s224 keys keep their mapping."""
        self.assertEqual(_UNIT_TO_FIELD["% AD"], "total_ad_pct")
        self.assertEqual(_UNIT_TO_FIELD["% of target's missing health"],
                         "target_missing_hp_pct")
        self.assertEqual(_UNIT_TO_FIELD["% maximum health"],
                         "caster_max_hp_pct")


# ─── PART 2b - migration applied to the live snapshot ────────────────────────


class SnapshotMigrationS224Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        reset_default_cache()
        cls.ab = load_default()

    def _b(self, champ, key, form_idx, blk):
        return self.ab.champions[champ][key][form_idx].damage_blocks[blk]

    def test_target_max_hp_textdrift_promoted(self) -> None:
        self.assertEqual(self._b("Gwen", "Q", 0, 7).target_max_hp_pct[0], 6.0)
        self.assertEqual(self._b("Gwen", "R", 0, 4).target_max_hp_pct[0], 9.0)
        self.assertEqual(self._b("Varus", "W", 0, 4).target_max_hp_pct[0], 13.5)
        self.assertEqual(self._b("Maokai", "Q", 0, 0).target_max_hp_pct[0], 2.0)
        self.assertEqual(self._b("Ambessa", "Q", 0, 1).target_max_hp_pct[0], 2.0)

    def test_trundle_R_recovered_from_zero(self) -> None:
        """Trundle R 'Subjugate' was all-None (evaluated 0) pre-s224 -
        the double-space "the target's" maximum-health drain now types."""
        b = self._b("Trundle", "R", 0, 0)
        self.assertIsNotNone(b.target_max_hp_pct)
        self.assertEqual(b.target_max_hp_pct[0], 20.0)

    def test_fiddle_Q_current_hp_recovered(self) -> None:
        self.assertEqual(
            self._b("Fiddlesticks", "Q", 0, 1).target_current_hp_pct[0], 4.0)
        self.assertEqual(
            self._b("Fiddlesticks", "Q", 0, 4).target_current_hp_pct[0], 8.0)

    def test_caster_max_hp_forms_promoted(self) -> None:
        self.assertEqual(self._b("Sejuani", "W", 0, 2).caster_max_hp_pct[0], 12.0)
        self.assertEqual(self._b("Zac", "Q", 0, 1).caster_max_hp_pct[0], 6.0)
        self.assertEqual(self._b("Braum", "Q", 0, 0).caster_max_hp_pct[0], 2.5)
        self.assertEqual(self._b("Skarner", "E", 0, 0).caster_max_hp_pct[0], 6.0)

    def test_briar_W_missing_hp_the_target_form(self) -> None:
        self.assertEqual(
            self._b("Briar", "W", 1, 0).target_missing_hp_pct[0], 9.0)

    def test_promoted_blocks_drop_resolved_unparsed(self) -> None:
        """Trundle R block 0 had exactly the one max-HP unparsed mod."""
        b = self._b("Trundle", "R", 0, 0)
        for m in b.unparsed_modifiers:
            us = m.get("units") or []
            self.assertFalse(
                any("of the target's maximum health" in (u or "") for u in us),
                "Trundle R still carries the unresolved max-HP unit",
            )


# ─── PART 1 - Bel'Veth R entry + A/B ─────────────────────────────────────────


class BelvethREntryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        reset_block_index_cache()
        cls.snap = _snap()

    def test_registry_shape(self) -> None:
        m, src = get_block_index_for("Belveth")
        self.assertEqual(src, "champion")
        self.assertEqual(m.get("E"), 2)   # s174-era preserved
        self.assertEqual(m.get("R"), 1)   # s224 new

    def _r(self, *, forced=None):
        kw = {} if forced is None else {"block_index_overrides": {"R": forced}}
        out = compute_ability_dps(
            self.snap, "Belveth", level=11, item_ids=[], mode="SR",
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0, **kw,
        )
        return next(p for p in out.per_spell if p.key == "R")

    def test_registry_picks_recast_nuke_over_block0(self) -> None:
        """Registry (block 1, the True Damage recast) ≫ forced block 0
        (the trivial 6-10 per-takedown bonus)."""
        reg = self._r()
        b0 = self._r(forced=0)
        self.assertGreater(reg.raw_damage_per_cast,
                           b0.raw_damage_per_cast * 5)

    def test_registry_equals_forced_block1(self) -> None:
        self.assertAlmostEqual(self._r().raw_damage_per_cast,
                               self._r(forced=1).raw_damage_per_cast,
                               places=6)


# ─── Backward-compat - s223 + prior entries intact ───────────────────────────


class BackwardCompatS224Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        reset_block_index_cache()

    def test_s223_kindred_E_unchanged(self) -> None:
        # s228 Phase 5.9.28 converted Kindred E to a conditional dict;
        # default=1 preserves the s223 block-1 execute routing in Part 1.
        self.assertEqual(
            get_block_index_for("Kindred")[0].get("E"),
            {"default": 1, "target_full_hp": 0},
        )

    def test_s223_promotions_still_typed(self) -> None:
        """s223's nested-paren promotions survive the s224 migration."""
        reset_default_cache()
        ab = load_default()
        kE = ab.champions["Kindred"]["E"][0].damage_blocks[1]
        self.assertEqual(kE.target_missing_hp_pct[0], 7.5)
        cE = ab.champions["Chogath"]["E"][0].damage_blocks[1]
        self.assertEqual(cE.target_max_hp_pct[0], 7.5)

    def test_prior_block_index_entries_stable(self) -> None:
        self.assertEqual(get_block_index_for("Gwen")[0].get("Q"), 6)
        self.assertEqual(get_block_index_for("Gwen")[0].get("R"), 4)
        self.assertEqual(get_block_index_for("Varus")[0].get("Q"), 1)
        self.assertEqual(get_block_index_for("Zac")[0].get("Q"), 1)
        self.assertEqual(get_block_index_for("Thresh")[0].get("E"), [1, 2])

    def test_champion_count_unchanged(self) -> None:
        """s224 added a KEY to an already-covered champ (Bel'Veth) - the
        champion count stays 125 (s223's number)."""
        import json
        from pathlib import Path
        reg = json.loads(
            Path("agents/daemon_slayer/champion_block_index.json")
            .read_text(encoding="utf-8")
        )
        self.assertEqual(len(reg["champions"]), 125)
        self.assertEqual(reg["champions"]["Belveth"], {"E": 2, "R": 1})


class EngineVersionS224Tests(unittest.TestCase):
    def test_engine_version(self) -> None:
        from agents import daemon_slayer
        # s231 (Phase 5.9.31) bumped to 1.3.0; pin tracks current.
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.58.0")


if __name__ == "__main__":
    unittest.main()
