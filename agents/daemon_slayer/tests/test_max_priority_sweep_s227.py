"""Phase 5.9.27 (s227, 2026-05-16) - max_priority coverage audit.
Iteration 5 of the self-paced DS loop.

`tools/ds_max_priority_prefilter.py` A/B'd all 6 (Q,W,E) max orderings
vs the Q-W-E default for every champion. The numeric level-11 optimum
is NOT the real in-game max order for most (it flags Azir W-first,
contradicting universal Q-max), so max_priority is a play-pattern
registry, NOT a numeric-sweepable pure-data batch. After filtering to
ds.ability/ds.burst-archetype champions AND cross-checking established
meta, exactly 3 had a universally-known non-default order the registry
genuinely missed:

  Brand        W-E-Q  (Pillar of Flame - Brand's primary dmg+waveclear;
                       maxed W-first for years. The original s185 _meta
                       wrongly listed Brand as 'default is fine' - fixed)
  Talon        W-Q-E  (Rake - canonical Talon max-first)
  Fiddlesticks W-E-Q  (Bountiful Harvest drain - standard jungle max)

Live A/B (lvl 11): Brand +18.7%, Fiddlesticks +16.4%, Talon +12.0%.

The sibling combo_sequence registry was assessed in the same iteration
and found ADEQUATE for its stated reset/shadow/chain-cast purpose: the
assassin-archetype champs genuinely NOT in it (Shaco/Ekko - Fizz +
Katarina ARE curated) have no such mechanic the default Q-W-E-AA-R-AA
misses - a valid negative result, no additions.

ENGINE_VERSION 0.98.0 -> 0.99.0 pinned.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from agents.daemon_slayer import ult_rates
from agents.daemon_slayer.abilities import reset_default_cache
from agents.daemon_slayer.ability_dps import (
    compute_ability_dps,
    get_block_index_for,
    get_form_index_for,
    get_max_priority_for,
    reset_block_index_cache,
    reset_form_index_cache,
    reset_max_priority_cache,
)
from agents.daemon_slayer.data_loader import DataSnapshot


def _snap() -> DataSnapshot:
    reset_default_cache()
    reset_block_index_cache()
    reset_form_index_cache()
    reset_max_priority_cache()
    ult_rates.reset_cache()
    return DataSnapshot.load()


class MaxPriorityRegistryShapeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        reset_max_priority_cache()

    def test_three_new_entries(self) -> None:
        self.assertEqual(list(get_max_priority_for("Brand")[0]),
                         ["W", "E", "Q"])
        self.assertEqual(list(get_max_priority_for("Talon")[0]),
                         ["W", "Q", "E"])
        self.assertEqual(list(get_max_priority_for("Fiddlesticks")[0]),
                         ["W", "E", "Q"])
        for c in ("Brand", "Talon", "Fiddlesticks"):
            self.assertEqual(get_max_priority_for(c)[1], "champion")

    def test_prior_entries_unchanged(self) -> None:
        self.assertEqual(list(get_max_priority_for("Cassiopeia")[0]),
                         ["E", "Q", "W"])
        self.assertEqual(list(get_max_priority_for("Karthus")[0]),
                         ["Q", "E", "W"])
        self.assertEqual(list(get_max_priority_for("Leblanc")[0]),
                         ["W", "Q", "E"])

    def test_registry_count(self) -> None:
        reg = json.loads(
            Path("agents/daemon_slayer/champion_max_priority.json")
            .read_text(encoding="utf-8")
        )
        self.assertEqual(len(reg["champions"]), 15)  # 12 prior + 3 s227

    def test_over_flag_finding_azir_not_shipped(self) -> None:
        """The pre-filter flagged Azir W-first, but real Azir maxes Q
        universally - assert we did NOT auto-ship the numeric optimum
        (the documented over-flag guard)."""
        m, src = get_max_priority_for("Azir")
        self.assertEqual(src, "default")


class MaxPriorityABTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def _total(self, champ, order):
        out = compute_ability_dps(
            self.snap, champ, level=11, item_ids=[], mode="SR",
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
            max_priority=order,
        )
        return sum(s.dps for s in out.per_spell), \
            {s.key: s.rank for s in out.per_spell}

    def test_brand_w_first_beats_default(self) -> None:
        d, dr = self._total("Brand", ["Q", "W", "E"])
        o, orr = self._total("Brand", ["W", "E", "Q"])
        self.assertGreater(o, d * 1.10)
        self.assertGreater(orr["W"], dr["W"])  # W ranked higher

    def test_talon_w_first_beats_default(self) -> None:
        d, _ = self._total("Talon", ["Q", "W", "E"])
        o, orr = self._total("Talon", ["W", "Q", "E"])
        self.assertGreater(o, d * 1.08)
        self.assertEqual(orr["W"], 4)  # W maxed at lvl 11

    def test_fiddlesticks_w_first_is_the_meta_curated_registry_entry(
        self,
    ) -> None:
        # s227 SHIPPED Fiddlesticks ["W","E","Q"] on REAL-META grounds
        # (Bountiful Harvest drain is the standard jungle max) - the
        # lvl-11 numeric A/B was only the *discovery* method, not the
        # durable property. s230 Phase 5.9.30 added a Fiddle Q
        # block_index entry (Terrify double-vs-feared, +200% Q-dps);
        # because Q was under-counted at s227, the numeric lvl-11 A/B
        # now FAVORS Q-first (ratio ~0.85, no longer >1.10). This is
        # precisely the s227 hand-off's stated lesson - max_priority is
        # a meta-curated registry, NOT numeric-sweepable; a correctness
        # fix elsewhere must not silently revert a real-meta decision.
        # Guard the DECISION (registry entry + resolution), not the
        # now-stale inequality.
        order, src = get_max_priority_for("Fiddlesticks")
        self.assertEqual(tuple(order), ("W", "E", "Q"))
        self.assertEqual(src, "champion")
        # Registry resolution still works (no explicit arg == explicit
        # W-E-Q list): the meta order is what the engine actually uses.
        reg = compute_ability_dps(
            self.snap, "Fiddlesticks", level=11, item_ids=[], mode="SR",
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
        )
        explicit = compute_ability_dps(
            self.snap, "Fiddlesticks", level=11, item_ids=[], mode="SR",
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
            max_priority=["W", "E", "Q"],
        )
        self.assertAlmostEqual(
            sum(s.dps for s in reg.per_spell),
            sum(s.dps for s in explicit.per_spell), places=6)

    def test_registry_default_resolution_uses_override(self) -> None:
        """With no explicit max_priority arg the engine must pick up the
        registry entry - Brand scored via the registry == Brand scored
        with the explicit W-E-Q list."""
        reg = compute_ability_dps(
            self.snap, "Brand", level=11, item_ids=[], mode="SR",
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
        )
        explicit = compute_ability_dps(
            self.snap, "Brand", level=11, item_ids=[], mode="SR",
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
            max_priority=["W", "E", "Q"],
        )
        self.assertAlmostEqual(sum(s.dps for s in reg.per_spell),
                               sum(s.dps for s in explicit.per_spell),
                               places=6)


class CombosAdequateNegativeResultTests(unittest.TestCase):
    """s227 assessed combo_sequence and found it adequate - the
    unmapped assassins have no reset/chain mechanic the default misses.
    Pin that they stay unmapped (a guard against a future unjustified
    numeric expansion)."""

    def test_unmapped_assassins_stay_out_of_combo_sequence(self) -> None:
        reg = json.loads(
            Path("agents/daemon_slayer/champion_combo_sequences.json")
            .read_text(encoding="utf-8")
        )["champions"]
        # Shaco / Ekko are assassin-archetype but have NO reset/shadow/
        # chain mechanic the default Q-W-E-AA-R-AA misses -> correctly
        # absent (s227 negative result). Fizz/Katarina ARE curated (15).
        for champ in ("Shaco", "Ekko"):
            self.assertNotIn(champ, reg)
        self.assertEqual(len(reg), 15)
        self.assertEqual(reg["Zed"], ["Q", "W", "E", "R", "Q2", "AA"])
        self.assertIn("Fizz", reg)  # curated s186, not an s227 omission


class BackwardCompatS227Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        reset_block_index_cache()
        reset_form_index_cache()
        reset_max_priority_cache()

    def test_s226_form_index_intact(self) -> None:
        self.assertEqual(get_form_index_for("Swain")[0].get("R"), 1)
        self.assertEqual(get_form_index_for("Evelynn")[0].get("E"), 1)

    def test_s225_s224_block_index_intact(self) -> None:
        self.assertEqual(get_block_index_for("Varus")[0], {"Q": 1, "W": 2})
        self.assertEqual(get_block_index_for("Belveth")[0], {"E": 2, "R": 1})

    def test_fiddlesticks_carries_all_three_registries(self) -> None:
        """Fiddlesticks now exercises max_priority (W-E-Q, s227) +
        block_index ({R:1,W:3}, s193/s199) - orthogonal registries."""
        self.assertEqual(list(get_max_priority_for("Fiddlesticks")[0]),
                         ["W", "E", "Q"])
        bi, _ = get_block_index_for("Fiddlesticks")
        self.assertEqual(bi.get("R"), 1)
        self.assertEqual(bi.get("W"), 3)


class EngineVersionS227Tests(unittest.TestCase):
    def test_engine_version(self) -> None:
        from agents import daemon_slayer
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.207.0")


if __name__ == "__main__":
    unittest.main()
