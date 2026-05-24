"""Phase 5.9.21 (s215, 2026-05-15) - sum-of-blocks data batch.

First pure-data batch consuming the s207 sum-of-blocks schema lift.
Adds 4 new (champion, key) entries from s207's queued candidate list:

  * Thresh.E    = [1, 2]               - Maximum Bonus Magic (full Souls)
                                          + canonical Magic Damage
  * Sona.Q      = [0, 1]               - active Magic Damage
                                          + Power Chord empowered AA
  * Kalista.E   = [0, 1, 1, 1, 1]      - base Rend + 4× additional stacks
  * Malzahar.R  = [0, 2]               - Total Magic channel
                                          + Total Max-HP% bonus

Mirrors the s207 test structure: registry shape assertions + arithmetic
parity (sum == sum of forced singletons) + strict-greater guards vs
forced block 0/single-block A/B. ENGINE_VERSION 0.92.0 → 0.93.0
pinned. Backward-compat: prior s207 seed entries (Camille/Malphite/
Heimerdinger/Katarina) unchanged and still preserved.

All 4 entries verified per-rank against the Meraki 16.10.1 snapshot
during s215 implementation:
  * Thresh E rank 1: block 1 0+0.9×tAD ≈ 63 (at ~70 tAD), block 2 75+70%AP
  * Sona   Q rank 5: block 0 190+40%AP, block 1 30 (Sona's AP unparsed)
  * Kalista E rank 2: block 0 15+70%tAD+20%AP, block 1 14+25%tAD+20%AP
  * Malzahar R rank 2: block 0 200+80%AP, block 2 15% target max HP
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


def _snap() -> DataSnapshot:
    reset_default_cache()
    reset_block_index_cache()
    reset_form_index_cache()
    ult_rates.reset_cache()
    return DataSnapshot.load()


# ─── Registry shape - 4 new entries ──────────────────────────────────────────


class Phase599_21RegistrySeedTests(unittest.TestCase):
    """The 4 new (champion, key) entries are present with expected values.

    Thresh extends from s203 single-int {E: 2} to sum {E: [1, 2]}; the
    other three are wholly new champions in the registry.
    """

    @classmethod
    def setUpClass(cls) -> None:
        reset_block_index_cache()

    def test_thresh_E_is_max_souls_plus_canonical_magic(self) -> None:
        m, src = get_block_index_for("Thresh")
        self.assertEqual(src, "champion")
        # s215 lifts s203's {E: 2} → {E: [1, 2]}.
        self.assertEqual(m.get("E"), [1, 2])

    def test_sona_Q_is_active_plus_power_chord(self) -> None:
        m, src = get_block_index_for("Sona")
        self.assertEqual(src, "champion")
        self.assertEqual(m.get("Q"), [0, 1])

    def test_kalista_E_is_base_plus_four_stacks(self) -> None:
        m, src = get_block_index_for("Kalista")
        self.assertEqual(src, "champion")
        # [0, 1, 1, 1, 1] = base Rend + 4 additional stacks (5 total).
        self.assertEqual(m.get("E"), [0, 1, 1, 1, 1])

    def test_malzahar_R_is_total_plus_maxhp(self) -> None:
        m, src = get_block_index_for("Malzahar")
        self.assertEqual(src, "champion")
        self.assertEqual(m.get("R"), [0, 2])


# ─── Arithmetic parity - sum == sum of forced singletons ─────────────────────


class Phase599_21AbilityDpsTests(unittest.TestCase):
    """Sum-of-blocks entries deliver canonical single-target totals.

    Pattern mirrors ``test_sum_of_blocks.AbilityDpsSumOfBlocksTests``:
    fetch the per-spell row with the registry active, then fetch the
    same row with a forced single block_index for each component, and
    assert the sum matches arithmetic. Bool clamping behavior pre-s207
    is preserved for non-list entries.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def _spell(self, champion: str, key: str, *, level: int = 11):
        out = compute_ability_dps(
            self.snap, champion, level=level, item_ids=[],
            mode="SR", target_armor=80.0, target_mr=30.0,
            target_max_hp=2000.0,
        )
        return next((s for s in out.per_spell if s.key == key), None)

    def _spell_forced(self, champion: str, key: str, forced_block: int, *, level: int = 11):
        out = compute_ability_dps(
            self.snap, champion, level=level, item_ids=[],
            mode="SR", target_armor=80.0, target_mr=30.0,
            target_max_hp=2000.0,
            block_index_overrides={key: forced_block},
        )
        return next((s for s in out.per_spell if s.key == key), None)

    # ─── Thresh E [1, 2] ─────────────────────────────────────────────────────

    def test_thresh_E_sum_exceeds_block_2_alone(self) -> None:
        s_sum = self._spell("Thresh", "E")
        s_forced = self._spell_forced("Thresh", "E", 2)
        # Sum must exceed canonical Magic Damage alone; the +tAD scaling
        # from block 1 (max-Souls) adds genuine damage at lvl 11.
        self.assertGreater(s_sum.raw_damage_per_cast, s_forced.raw_damage_per_cast)

    def test_thresh_E_sum_matches_explicit_arithmetic(self) -> None:
        s_sum = self._spell("Thresh", "E")
        s_b1 = self._spell_forced("Thresh", "E", 1)
        s_b2 = self._spell_forced("Thresh", "E", 2)
        self.assertAlmostEqual(
            s_sum.raw_damage_per_cast,
            s_b1.raw_damage_per_cast + s_b2.raw_damage_per_cast,
            places=4,
        )

    # ─── Sona Q [0, 1] ───────────────────────────────────────────────────────

    def test_sona_Q_sum_exceeds_block_0_alone(self) -> None:
        s_sum = self._spell("Sona", "Q")
        s_forced = self._spell_forced("Sona", "Q", 0)
        # Power Chord block adds a small flat bonus (10/15/20/25/30 base);
        # sum must strictly exceed active-cast block alone.
        self.assertGreater(s_sum.raw_damage_per_cast, s_forced.raw_damage_per_cast)

    def test_sona_Q_sum_matches_explicit_arithmetic(self) -> None:
        s_sum = self._spell("Sona", "Q")
        s_b0 = self._spell_forced("Sona", "Q", 0)
        s_b1 = self._spell_forced("Sona", "Q", 1)
        self.assertAlmostEqual(
            s_sum.raw_damage_per_cast,
            s_b0.raw_damage_per_cast + s_b1.raw_damage_per_cast,
            places=4,
        )

    # ─── Kalista E [0, 1, 1, 1, 1] ───────────────────────────────────────────

    def test_kalista_E_sum_is_base_plus_4x_additional(self) -> None:
        """The 5-element list expresses base Rend + 4 additional stacks
        (5 total stacks). Arithmetic must equal block 0 + 4× block 1."""
        s_sum = self._spell("Kalista", "E")
        s_b0 = self._spell_forced("Kalista", "E", 0)
        s_b1 = self._spell_forced("Kalista", "E", 1)
        expected = s_b0.raw_damage_per_cast + 4 * s_b1.raw_damage_per_cast
        self.assertAlmostEqual(s_sum.raw_damage_per_cast, expected, places=4)

    def test_kalista_E_sum_strictly_exceeds_block_0_alone(self) -> None:
        s_sum = self._spell("Kalista", "E")
        s_b0 = self._spell_forced("Kalista", "E", 0)
        # 5-stack Rend must be strictly more than 0-stack base.
        self.assertGreater(s_sum.raw_damage_per_cast, s_b0.raw_damage_per_cast)

    # ─── Malzahar R [0, 2] ───────────────────────────────────────────────────

    def test_malzahar_R_sum_exceeds_block_0_alone(self) -> None:
        s_sum = self._spell("Malzahar", "R")
        s_forced = self._spell_forced("Malzahar", "R", 0)
        # Block 2 carries the 10/15/20% target max HP bonus - on a
        # 2000-HP target at rank 2 that's +300 damage on top of block 0.
        self.assertGreater(s_sum.raw_damage_per_cast, s_forced.raw_damage_per_cast)

    def test_malzahar_R_sum_matches_explicit_arithmetic(self) -> None:
        s_sum = self._spell("Malzahar", "R")
        s_b0 = self._spell_forced("Malzahar", "R", 0)
        s_b2 = self._spell_forced("Malzahar", "R", 2)
        self.assertAlmostEqual(
            s_sum.raw_damage_per_cast,
            s_b0.raw_damage_per_cast + s_b2.raw_damage_per_cast,
            places=4,
        )


# ─── Backward-compat - s207 seed entries preserved ───────────────────────────


class Phase599_21BackwardCompatTests(unittest.TestCase):
    """The s207 seed entries (Camille/Malphite/Heimerdinger/Katarina)
    still resolve identically post-s215; the s193 Thresh.E single-int
    entry has been intentionally lifted to a list (other s203 entries
    unchanged)."""

    @classmethod
    def setUpClass(cls) -> None:
        reset_block_index_cache()

    def test_camille_W_unchanged_from_s207(self) -> None:
        m, _ = get_block_index_for("Camille")
        self.assertEqual(m.get("W"), [0, 1])

    def test_malphite_W_unchanged_from_s207(self) -> None:
        m, _ = get_block_index_for("Malphite")
        self.assertEqual(m.get("W"), [2, 3])

    def test_heimerdinger_W_unchanged_from_s207(self) -> None:
        m, _ = get_block_index_for("Heimerdinger")
        self.assertEqual(m.get("W"), [0, 1, 1, 1, 1])

    def test_katarina_R_unchanged_from_s207(self) -> None:
        m, _ = get_block_index_for("Katarina")
        self.assertEqual(m.get("R"), [1, 3])

    def test_thresh_E_lifted_from_s203_int_to_list(self) -> None:
        """s203 originally set {E: 2}. s215 extends to {E: [1, 2]} to
        add the max-Souls Maximum Bonus Magic tier. Single-int → list
        behavior is the first such lift since s207's seed; pin it."""
        m, _ = get_block_index_for("Thresh")
        v = m.get("E")
        self.assertIsInstance(v, list)
        self.assertEqual(v, [1, 2])

    def test_unmapped_champion_still_returns_empty(self) -> None:
        # Annie is not in the block_index registry (uses default 0 for
        # all keys - her abilities are single-block per Meraki snapshot
        # so no override needed).
        m, src = get_block_index_for("Annie")
        self.assertEqual(m, {})
        self.assertEqual(src, "default")


# ─── ENGINE_VERSION pin ──────────────────────────────────────────────────────


class Phase599_21EngineVersionTests(unittest.TestCase):
    def test_engine_version_bumped(self) -> None:
        from agents import daemon_slayer
        # s231 (Phase 5.9.31) bumped to 1.3.0; pin tracks current.
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.49.0")


if __name__ == "__main__":
    unittest.main()
