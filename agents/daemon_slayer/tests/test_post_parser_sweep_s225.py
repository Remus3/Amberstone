"""Phase 5.9.25 (s225, 2026-05-16) - post-parser-fix block_index sweep.

The s223 (nested-paren) + s224 (text-drift variant) parser fixes
re-parsed %HP scalings onto many blocks. Re-running the unmapped-key
pre-filter over the POST-s224 snapshot (champions whose candidate
blocks evaluated ~0 pre-migration now show real ratios) surfaced one
clean block_index ADD:

  Varus W=2 - 'Blighted Quiver'. Block 2 'Bonus Magic Damage at Max
  Stacks' is exactly 3x block 1's per-Blight-stack value (verified
  per-rank) = the canonical 3-stack detonation, Varus's standard combo
  (W-passive stacks via AAs/Q, then Q/R detonates). The engine
  defaulted to block 0 'Bonus Magic Damage' (the trivial 6-30 + 35% AP
  passive on-hit), scoring Varus W at ~7% of reality (live A/B 18->240
  raw, 13.3x). Pattern D resource-state amp - operator fully controls
  the 3-stack build (precedent: Twitch E 6-stack s198, Renekton full
  Fury s197). Block 2 (not block 4 'Maximum...at Max Stacks' = 1.5x
  block 2) because block 4 entangles Varus R's Blight amplification -
  W's contribution must be scored R-independent (R is its own
  ability_dps key). Varus -> {Q:1, W:2}.

Deliberately NOT added (documented in the registry _meta): Fiddlesticks
Q (s224's current-HP fix already made its engine-default block 0
correct; the 'Increased' block is a fear-sequence conditional ->
conditional-schema-lift bucket), Fizz W (block 0 literally 'Total'),
LeBlanc R (s197 Mimic data-gap; canonical block not unambiguous).

ENGINE_VERSION 0.96.0 -> 0.97.0 pinned.
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


def _snap() -> DataSnapshot:
    reset_default_cache()
    reset_block_index_cache()
    reset_form_index_cache()
    ult_rates.reset_cache()
    return DataSnapshot.load()


class VarusWEntryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        reset_block_index_cache()
        cls.snap = _snap()

    def test_registry_shape(self) -> None:
        m, src = get_block_index_for("Varus")
        self.assertEqual(src, "champion")
        self.assertEqual(m.get("Q"), 1)   # s195, preserved
        self.assertEqual(m.get("W"), 2)   # s225 new

    def _w(self, *, forced=None):
        kw = {} if forced is None else {"block_index_overrides": {"W": forced}}
        out = compute_ability_dps(
            self.snap, "Varus", level=11, item_ids=[], mode="SR",
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0, **kw,
        )
        return next(p for p in out.per_spell if p.key == "W")

    def test_registry_beats_passive_onhit_block0(self) -> None:
        """Registry (block 2, 3-stack detonation) >> forced block 0 (the
        18-dmg passive on-hit the engine wrongly defaulted to)."""
        reg = self._w()
        b0 = self._w(forced=0)
        self.assertGreater(reg.raw_damage_per_cast,
                           b0.raw_damage_per_cast * 5)

    def test_registry_equals_forced_block2(self) -> None:
        self.assertAlmostEqual(self._w().raw_damage_per_cast,
                               self._w(forced=2).raw_damage_per_cast,
                               places=6)

    def test_block2_is_R_independent_choice(self) -> None:
        """Block 4 ('Maximum...at Max Stacks') is strictly larger than the
        chosen block 2 - confirming we deliberately took the smaller,
        R-independent 3-stack value, not the R-amplified one."""
        b2 = self._w(forced=2).raw_damage_per_cast
        b4 = self._w(forced=4).raw_damage_per_cast
        self.assertGreater(b4, b2)

    def test_mechanic_block2_is_3x_block1_per_stack(self) -> None:
        """The 3-stack invariant: block 2 target_max_hp_pct == 3 x block
        1 per-Blight-stack at every rank. This is the proof that block 2
        is the canonical 'all 3 stacks detonate' value."""
        reset_default_cache()
        ab = load_default()
        blocks = ab.champions["Varus"]["W"][0].damage_blocks
        per_stack = blocks[1].target_max_hp_pct
        max_stacks = blocks[2].target_max_hp_pct
        self.assertIsNotNone(per_stack)
        self.assertIsNotNone(max_stacks)
        for ps, ms in zip(per_stack, max_stacks):
            self.assertAlmostEqual(ms, ps * 3.0, places=4)


class BackwardCompatS225Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        reset_block_index_cache()

    def test_s224_entries_unchanged(self) -> None:
        self.assertEqual(get_block_index_for("Belveth")[0], {"E": 2, "R": 1})
        # s228 Phase 5.9.28 converted Kindred E to a conditional dict
        # (default=1 = the s223 execute block; Part-1 resolves to default).
        self.assertEqual(
            get_block_index_for("Kindred")[0].get("E"),
            {"default": 1, "target_full_hp": 0},
        )

    def test_swept_keys_deliberately_not_added(self) -> None:
        """s225's shortlist flagged Fiddlesticks Q / Fizz W / LeBlanc R
        but deliberately did NOT map them (see module docstring /
        registry _meta Phase 5.9.25). These champions keep their PRIOR
        entries on other keys.

        Fiddlesticks Q was specifically deferred to the *conditional-
        schema bucket* ("fear-sequence conditional"). That call was
        CORRECT: s230 Phase 5.9.30 delivered it there exactly - Q is now
        a conditional ({default:[2,3] feared/amped sum,
        target_no_setup:[0,1] un-amped}, the Terrify double-vs-feared
        mechanic). Fizz W / LeBlanc R remain deliberately absent."""
        fid, _ = get_block_index_for("Fiddlesticks")
        # s225 deferred-to-conditional-bucket -> s230 delivered there.
        self.assertEqual(
            fid.get("Q"), {"default": [2, 3], "target_no_setup": [0, 1]})
        self.assertEqual(fid.get("W"), 3)       # s199, preserved
        self.assertEqual(fid.get("R"), 1)       # s193, preserved
        fizz, _ = get_block_index_for("Fizz")
        self.assertNotIn("W", fizz)             # swept, not added
        self.assertEqual(fizz.get("R"), 2)      # prior, preserved
        leb, _ = get_block_index_for("Leblanc")
        self.assertNotIn("R", leb)              # swept (s197 data-gap), not added
        self.assertEqual(leb.get("Q"), 1)       # prior, preserved
        self.assertEqual(leb.get("E"), 1)       # prior, preserved

    def test_champion_count_unchanged(self) -> None:
        """s225 added a KEY to already-covered Varus - count stays 125."""
        import json
        from pathlib import Path
        reg = json.loads(
            Path("agents/daemon_slayer/champion_block_index.json")
            .read_text(encoding="utf-8")
        )
        self.assertEqual(len(reg["champions"]), 125)
        self.assertEqual(reg["champions"]["Varus"], {"Q": 1, "W": 2})


class EngineVersionS225Tests(unittest.TestCase):
    def test_engine_version(self) -> None:
        from agents import daemon_slayer
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.195.0")


if __name__ == "__main__":
    unittest.main()
