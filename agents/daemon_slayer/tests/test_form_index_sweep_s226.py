"""Phase 5.9.26 (s226, 2026-05-16) - first form_index coverage sweep
since s205. Iteration 4 of the self-paced DS loop.

`tools/ds_form_index_prefilter.py` ran ground-truth A/B (forced form 0
vs each later form) over all 16 multi-DAMAGE-form (champion, key) pairs
NOT yet in `champion_form_index.json`. Three clean ADDs - each the
canonical operator-commit form the engine was wrongly defaulting away
from:

  Swain R=1   - form 0 'Demonic Ascension' is the 7.5-17.5 drain-channel
                per-tick; form 1 'Demonflare' is the 150-350 + 50% AP
                recast nuke (Swain's ult payoff). Same shape as the
                existing AurelionSol R=1. Live A/B 12.5→250 (20×).
  Briar W=1   - form 0 'Blood Frenzy' has ZERO damage blocks (it is the
                AS/MS frenzy-buff cast); form 1 'Snack Attack' is the
                entire W damage incl. the s224-migrated 9% missing-HP.
  Evelynn E=1 - form 1 'Empowered Whiplash' is Eve's canonical
                Demon-Shade-opened combo E (1.33× form 0 base, 4% vs 3%
                target max HP). Composes orthogonally with Evelynn's
                s204 block_index {R:1,Q:5}.

Skips (documented in the registry _meta rationale): Heimerdinger W/E
(R-gated upgraded form - conditional bucket), Gnar Q/E + RekSai Q
(contextual transforms, form 0 is the dominant-uptime default),
Skarner Q (form 1 Upheaval is boulder-resource-gated).

ENGINE_VERSION 0.97.0 → 0.98.0 pinned.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import ult_rates
from agents.daemon_slayer.abilities import load_default, reset_default_cache
from agents.daemon_slayer.ability_dps import (
    compute_ability_dps,
    get_block_index_for,
    get_form_index_for,
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


class FormIndexRegistryShapeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        reset_form_index_cache()

    def test_three_new_entries(self) -> None:
        self.assertEqual(get_form_index_for("Swain")[0].get("R"), 1)
        self.assertEqual(get_form_index_for("Briar")[0].get("W"), 1)
        self.assertEqual(get_form_index_for("Evelynn")[0].get("E"), 1)
        for c in ("Swain", "Briar", "Evelynn"):
            self.assertEqual(get_form_index_for(c)[1], "champion")

    def test_prior_form_index_entries_unchanged(self) -> None:
        self.assertEqual(get_form_index_for("AurelionSol")[0].get("R"), 1)
        self.assertEqual(get_form_index_for("Nidalee")[0],
                         {"Q": 1, "W": 1, "E": 1})
        self.assertEqual(get_form_index_for("Hwei")[0],
                         {"Q": 1, "W": 3, "E": 1})
        self.assertEqual(get_form_index_for("Riven")[0].get("R"), 1)


class FormIndexABTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def _spell(self, champ, key, *, form=None, hp=0.5):
        kw = {} if form is None else {"form_index_overrides": {key: form}}
        out = compute_ability_dps(
            self.snap, champ, level=11, item_ids=[], mode="SR",
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
            target_current_hp_pct=hp, **kw,
        )
        return next(p for p in out.per_spell if p.key == key)

    def test_swain_R_registry_is_demonflare(self) -> None:
        reg = self._spell("Swain", "R")
        f0 = self._spell("Swain", "R", form=0)
        f1 = self._spell("Swain", "R", form=1)
        self.assertGreater(reg.raw_damage_per_cast,
                           f0.raw_damage_per_cast * 5)
        self.assertAlmostEqual(reg.raw_damage_per_cast,
                               f1.raw_damage_per_cast, places=6)

    def test_briar_W_form0_is_the_buff_cast(self) -> None:
        """Form 0 'Blood Frenzy' is the AS/MS frenzy-buff cast - its lone
        damage-kind block carries NO parsed scaling (base None), so it
        is not the real W damage. Form 1 'Snack Attack' is. The registry
        must route to form 1 and strictly beat form 0."""
        reset_default_cache()
        ab = load_default()
        f0 = ab.champions["Briar"]["W"][0]
        f0_dmg = f0.damage_blocks_only()
        self.assertEqual(len(f0_dmg), 1)            # the null 'Physical Damage'
        self.assertIsNone(f0_dmg[0].base)           # no parsed scaling
        self.assertEqual(f0_dmg[0].target_missing_hp_pct, None)
        # form 1 carries the real damage incl. s224-migrated missing-HP
        f1 = ab.champions["Briar"]["W"][1].damage_blocks_only()
        self.assertTrue(f1 and f1[0].target_missing_hp_pct)
        reg = self._spell("Briar", "W")
        s_f1 = self._spell("Briar", "W", form=1)
        s_f0 = self._spell("Briar", "W", form=0)
        self.assertAlmostEqual(reg.raw_damage_per_cast,
                               s_f1.raw_damage_per_cast, places=6)
        self.assertGreater(reg.raw_damage_per_cast,
                           s_f0.raw_damage_per_cast)

    def test_evelynn_E_registry_is_empowered(self) -> None:
        reg = self._spell("Evelynn", "E")
        f0 = self._spell("Evelynn", "E", form=0)
        f1 = self._spell("Evelynn", "E", form=1)
        self.assertGreater(f1.raw_damage_per_cast, f0.raw_damage_per_cast)
        self.assertAlmostEqual(reg.raw_damage_per_cast,
                               f1.raw_damage_per_cast, places=6)

    def test_evelynn_form_and_block_index_compose(self) -> None:
        """Evelynn carries BOTH a form_index (E=1, s226) and a
        block_index ({R:1,Q:5}, s204). They are orthogonal registries -
        assert both still resolve for Evelynn."""
        fi, _ = get_form_index_for("Evelynn")
        bi, _ = get_block_index_for("Evelynn")
        self.assertEqual(fi.get("E"), 1)
        # s228 converted Evelynn Q to a target_no_setup conditional;
        # s231 Phase 5.9.31 converted R to a target_full_hp execute
        # conditional. form_index (E=1) and block_index (Q+R both
        # conditional dicts) still compose orthogonally - the point of
        # this test.
        self.assertEqual(bi.get("R"), {"default": 1, "target_full_hp": 0})
        self.assertEqual(bi.get("Q"), {"default": 5, "target_no_setup": 0})


class BackwardCompatS226Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        reset_block_index_cache()
        reset_form_index_cache()

    def test_s225_varus_block_index_intact(self) -> None:
        self.assertEqual(get_block_index_for("Varus")[0], {"Q": 1, "W": 2})

    def test_s224_belveth_block_index_intact(self) -> None:
        self.assertEqual(get_block_index_for("Belveth")[0], {"E": 2, "R": 1})

    def test_form_index_champion_count(self) -> None:
        import json
        from pathlib import Path
        reg = json.loads(
            Path("agents/daemon_slayer/champion_form_index.json")
            .read_text(encoding="utf-8")
        )
        self.assertEqual(len(reg["champions"]), 12)  # 9 prior + 3 s226
        self.assertEqual(reg["champions"]["Swain"], {"R": 1})
        self.assertEqual(reg["champions"]["Briar"], {"W": 1})
        self.assertEqual(reg["champions"]["Evelynn"], {"E": 1})


class EngineVersionS226Tests(unittest.TestCase):
    def test_engine_version(self) -> None:
        from agents import daemon_slayer
        # s231 (Phase 5.9.31) bumped to 1.3.0; pin tracks current.
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.14.0")


if __name__ == "__main__":
    unittest.main()
