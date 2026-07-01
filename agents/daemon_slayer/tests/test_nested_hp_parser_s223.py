"""Phase 5.9.23 (s223, 2026-05-16) - nested missing/current/maximum-HP
parser fix + Kindred E execute entry + registry-saturation guard.

PART 1 - the extractor's ``_normalize_modifiers`` gained
``_canonicalize_unit()`` which strips Meraki's nested conditional
``(+ ...)`` parentheticals (innermost-first, so doubly-nested K'Sante
strings collapse) before the ``_UNIT_TO_FIELD`` lookup. A deterministic
zero-re-fetch in-place migration promoted exactly 22 such modifiers
across 10 champions whose entire % target-health damage component had
been silently dropped since Phase 4a.

PART 2 - one new block_index entry: Kindred E=1 ("Enhanced damage below
threshold", 7.5% missing-HP vs block 0's 5%) - the canonical
Kindred-E-as-execute case. Monotone >= block 0, strictly greater at any
sub-100% target HP, exact no-op at full HP.

PART 3 - the s191->s217 single-int/list registry is provably saturated:
the 47 not-yet-covered champions yielded zero clean candidates (residue
is single-block kits / block-0-already-max / upstream data gaps). This
file pins a few representative "stays unmapped" guards so a future
accidental entry trips a test.

ENGINE_VERSION 0.94.0 -> 0.95.0 pinned.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import ult_rates
from agents.daemon_slayer.abilities import reset_default_cache
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
    _normalize_modifiers,
)


def _snap() -> DataSnapshot:
    reset_default_cache()
    reset_block_index_cache()
    reset_form_index_cache()
    ult_rates.reset_cache()
    return DataSnapshot.load()


# --- PART 1a - _canonicalize_unit unit tests ---------------------------------


class CanonicalizeUnitTests(unittest.TestCase):
    def test_plain_unit_is_byte_identical(self) -> None:
        """No "(+" -> returned unchanged (zero perturbation of recognized
        units; the early-return is the regression guarantee)."""
        for u in ("", "% AD", "% bonus AD", "% AP",
                  "% of target's maximum health",
                  "%  of target's missing health"):
            self.assertEqual(_canonicalize_unit(u), u)

    def test_single_nested_paren_stripped(self) -> None:
        self.assertEqual(
            _canonicalize_unit("% (+ 0.5% per Mark) of target's missing health"),
            "% of target's missing health",
        )

    def test_double_nested_parens_stripped(self) -> None:
        """K'Sante W carries TWO sibling "(+ ...)" groups."""
        self.assertEqual(
            _canonicalize_unit(
                "% (+ 2% per 100 bonus armor) (+ 2% per 100 bonus "
                "magic resistance) of target's maximum health"
            ),
            "% of target's maximum health",
        )

    def test_recursively_nested_parens_stripped(self) -> None:
        """Kindred E block 1 has a paren INSIDE a paren - innermost-first
        iteration must collapse it fully."""
        self.assertEqual(
            _canonicalize_unit(
                "% (+ 2%) (+ 0.75% (+ 0.2%) per Mark) of target's "
                "missing health"
            ),
            "% of target's missing health",
        )

    def test_canonical_residues_are_known_fields(self) -> None:
        for raw, field in [
            ("% (+ 0.5% per Mark) of target's missing health",
             "target_missing_hp_pct"),
            ("% (+ 1% per mark) of target's current health",
             "target_current_hp_pct"),
            ("% (+ 0.25% per 100 AP) of target's maximum health",
             "target_max_hp_pct"),
        ]:
            self.assertEqual(_UNIT_TO_FIELD[_canonicalize_unit(raw)], field)


# --- PART 1b - _normalize_modifiers integration ------------------------------


class NormalizeModifiersNestedTests(unittest.TestCase):
    def test_nested_modifier_promotes_to_typed_field(self) -> None:
        typed, unparsed = _normalize_modifiers([
            {"values": [5, 5, 5, 5, 5],
             "units": ["% (+ 0.5% per Mark) of target's missing health"] * 5}
        ])
        self.assertEqual(typed.get("target_missing_hp_pct"),
                         [5.0, 5.0, 5.0, 5.0, 5.0])
        self.assertEqual(unparsed, [])

    def test_recognized_unit_path_unchanged(self) -> None:
        """An already-recognized unit must NOT route through the
        canonicalizer (raw-match-wins regression guard)."""
        typed, unparsed = _normalize_modifiers([
            {"values": [60.0], "units": ["% AD"]}
        ])
        self.assertEqual(typed.get("total_ad_pct"), [60.0])
        self.assertEqual(unparsed, [])

    def test_genuinely_unknown_unit_stays_unparsed(self) -> None:
        """Second-order amplifiers Meraki nests without a base health
        clause (Kayle E's "% per 100 AP") must remain unparsed."""
        typed, unparsed = _normalize_modifiers([
            {"values": [1.5], "units": ["% per 100 AP"]}
        ])
        self.assertEqual(typed, {})
        self.assertEqual(len(unparsed), 1)


# --- PART 1c - migration applied to the live 16.10.1 snapshot ----------------


class SnapshotMigrationTests(unittest.TestCase):
    """Every one of the 22 promoted modifiers must be present as a typed
    field on the live snapshot, and absent from unparsed_modifiers."""

    @classmethod
    def setUpClass(cls) -> None:
        reset_default_cache()
        from agents.daemon_slayer.abilities import load_default
        cls.ab = load_default()

    def _block(self, champ: str, key: str, form_idx: int, blk: int):
        return self.ab.champions[champ][key][form_idx].damage_blocks[blk]

    def test_kindred_E_missing_hp_now_typed(self) -> None:
        b0 = self._block("Kindred", "E", 0, 0)
        b1 = self._block("Kindred", "E", 0, 1)
        self.assertEqual(b0.target_missing_hp_pct[0], 5.0)
        self.assertEqual(b1.target_missing_hp_pct[0], 7.5)

    def test_kindred_W_current_hp_now_typed(self) -> None:
        b = self._block("Kindred", "W", 0, 0)
        self.assertEqual(b.target_current_hp_pct[0], 1.5)

    def test_chogath_E_max_hp_now_typed(self) -> None:
        self.assertEqual(self._block("Chogath", "E", 0, 0).target_max_hp_pct[0], 2.5)
        self.assertEqual(self._block("Chogath", "E", 0, 1).target_max_hp_pct[0], 7.5)

    def test_elise_Q_both_forms(self) -> None:
        self.assertEqual(self._block("Elise", "Q", 0, 0).target_current_hp_pct[0], 4.0)
        self.assertEqual(self._block("Elise", "Q", 1, 0).target_missing_hp_pct[0], 8.0)

    def test_evelynn_E_both_forms_max_hp(self) -> None:
        self.assertEqual(self._block("Evelynn", "E", 0, 0).target_max_hp_pct[0], 3.0)
        self.assertEqual(self._block("Evelynn", "E", 1, 0).target_max_hp_pct[0], 4.0)

    def test_ksante_W_double_nested_resolved(self) -> None:
        self.assertEqual(self._block("KSante", "W", 0, 0).target_max_hp_pct[0], 8.0)
        self.assertEqual(self._block("KSante", "W", 0, 4).target_max_hp_pct[0], 14.4)

    def test_sett_shen_zac_amumu_kled_max_hp(self) -> None:
        self.assertEqual(self._block("Sett", "Q", 0, 0).target_max_hp_pct[0], 1.0)
        self.assertEqual(self._block("Sett", "Q", 0, 1).target_max_hp_pct[0], 2.0)
        self.assertEqual(self._block("Shen", "Q", 0, 1).target_max_hp_pct[0], 2.0)
        self.assertEqual(self._block("Zac", "W", 0, 0).target_max_hp_pct[0], 4.0)
        self.assertEqual(self._block("Amumu", "W", 0, 0).target_max_hp_pct[0], 0.5)
        self.assertEqual(self._block("Kled", "W", 0, 0).target_max_hp_pct[0], 4.5)

    def test_promoted_blocks_drop_the_resolved_unparsed_entry(self) -> None:
        """The migration removes the now-typed modifier from
        unparsed_modifiers - Kindred E blocks each had exactly one
        unparsed mod (the missing-HP clause), so it must now be empty."""
        for blk in (0, 1):
            b = self._block("Kindred", "E", 0, blk)
            self.assertEqual(
                b.unparsed_modifiers, (),
                f"Kindred E block {blk} still has unparsed mods",
            )
            self.assertIsNotNone(b.target_missing_hp_pct)


# --- PART 2 - Kindred E registry entry + A/B ---------------------------------


class KindredEEntryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        reset_block_index_cache()
        cls.snap = _snap()

    def test_registry_shape(self) -> None:
        m, src = get_block_index_for("Kindred")
        self.assertEqual(src, "champion")
        # s228 Phase 5.9.28 converted Kindred E from int 1 to a conditional
        # dict: default=1 (the s223 execute block - operator commits to
        # E'ing low-HP targets), downgrade to 0 vs a full-HP target. Part 1
        # resolves to "default" so every other test in this class (the
        # s223 semantic guarantees) still passes unchanged.
        self.assertEqual(m.get("E"), {"default": 1, "target_full_hp": 0})

    def _e(self, *, hp_pct: float, forced: int | None = None):
        kw = {} if forced is None else {"block_index_overrides": {"E": forced}}
        out = compute_ability_dps(
            self.snap, "Kindred", level=11, item_ids=[], mode="SR",
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
            target_current_hp_pct=hp_pct, **kw,
        )
        return next(p for p in out.per_spell if p.key == "E")

    def test_full_hp_is_exact_noop(self) -> None:
        """At full HP, missing-HP term = 0 so block 1 == block 0 - the
        entry is provably harmless in the engine's default model."""
        reg = self._e(hp_pct=1.0)
        b0 = self._e(hp_pct=1.0, forced=0)
        self.assertAlmostEqual(reg.raw_damage_per_cast,
                               b0.raw_damage_per_cast, places=6)

    def test_execute_hp_registry_beats_block0(self) -> None:
        """At 40% target HP the registry (block 1, 7.5% missing-HP)
        strictly exceeds forced block 0 (5%)."""
        reg = self._e(hp_pct=0.4)
        b0 = self._e(hp_pct=0.4, forced=0)
        self.assertGreater(reg.raw_damage_per_cast, b0.raw_damage_per_cast)

    def test_registry_equals_forced_block1(self) -> None:
        reg = self._e(hp_pct=0.4)
        b1 = self._e(hp_pct=0.4, forced=1)
        self.assertAlmostEqual(reg.raw_damage_per_cast,
                               b1.raw_damage_per_cast, places=6)

    def test_monotone_in_missing_hp(self) -> None:
        """More missing HP => strictly more Kindred E damage (the parser
        fix made the missing-HP component count at all)."""
        full = self._e(hp_pct=1.0).raw_damage_per_cast
        half = self._e(hp_pct=0.5).raw_damage_per_cast
        low = self._e(hp_pct=0.2).raw_damage_per_cast
        self.assertGreater(half, full)
        self.assertGreater(low, half)


# --- PART 3 - saturation guards + backward-compat ----------------------------


class SaturationAndBackwardCompatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        reset_block_index_cache()

    def test_representative_uncovered_champions_stay_unmapped(self) -> None:
        """The s223 5-way scan proved these have no clean candidate -
        pin them so an accidental future entry trips here."""
        for champ in ("Caitlyn", "Jinx", "Zed", "Yone", "Aphelios",
                      "Mordekaiser", "Orianna", "TwistedFate"):
            m, src = get_block_index_for(champ)
            self.assertEqual(m, {}, f"{champ} unexpectedly mapped")
            self.assertEqual(src, "default")

    def test_kayle_unmapped_belveth_R_added_s224(self) -> None:
        """s223 originally left Bel'Veth R unmapped, reasoning "field
        already parsed". s224's unmapped-key pre-filter proved that
        reasoning incomplete: the engine still DEFAULTS to block 0
        (8-dmg per-takedown bonus), not the 200-dmg recast nuke (block
        1, 25% missing-HP) - so an explicit entry IS required. s224
        added Bel'Veth R=1 (kept E=2). Kayle E stays correctly unmapped:
        its only unparsed bit is a genuine second-order "% per 100 AP"
        amp (not a health-pct), so no entry is warranted."""
        self.assertEqual(get_block_index_for("Kayle")[0], {})
        bel, _ = get_block_index_for("Belveth")
        self.assertEqual(bel.get("E"), 2)   # s174-era, preserved
        self.assertEqual(bel.get("R"), 1)   # s224 correction

    def test_prior_entries_unchanged(self) -> None:
        """Migration touched several covered champions' snapshot blocks
        but their registry entries are pure JSON - must be byte-stable."""
        self.assertEqual(get_block_index_for("Chogath")[0].get("E"), 1)
        self.assertEqual(get_block_index_for("Sett")[0].get("Q"), 1)
        self.assertEqual(get_block_index_for("Shen")[0].get("Q"), 1)
        # Cassi E was int 1 through s223; s230 Phase 5.9.30 converted it
        # to a conditional (default=1 == the int - provable Part-1
        # no-op, the s223 snapshot migration is still byte-stable).
        self.assertEqual(
            get_block_index_for("Cassiopeia")[0].get("E"),
            {"default": 1, "target_no_setup": 0},
        )
        self.assertEqual(get_block_index_for("Thresh")[0].get("E"), [1, 2])

    def test_covered_count_grew_by_one(self) -> None:
        import json
        from pathlib import Path
        reg = json.loads(
            Path("agents/daemon_slayer/champion_block_index.json")
            .read_text(encoding="utf-8")
        )
        # s228 converts 3 entries in-place (Zoe E / Evelynn Q / Kindred E)
        # to conditional dicts - no new champions, count stays 125.
        self.assertEqual(len(reg["champions"]), 125)
        self.assertEqual(
            reg["champions"]["Kindred"],
            {"E": {"default": 1, "target_full_hp": 0}},
        )


class EngineVersionTests(unittest.TestCase):
    def test_engine_version_bumped(self) -> None:
        from agents import daemon_slayer
        # s231 (Phase 5.9.31) bumped to 1.3.0; pin tracks current.
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.164.0")


if __name__ == "__main__":
    unittest.main()
