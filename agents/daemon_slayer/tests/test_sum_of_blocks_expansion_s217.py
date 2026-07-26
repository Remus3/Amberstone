"""Phase 5.9.22 (s217, 2026-05-15) - second sum-of-blocks data batch.

Closes the s215 carry-forward queue by reframing the two remaining
candidates under the operator-commits-to-canonical-burst model.

Two entries:

  * Taliyah.E  = [0, 2]   - NEW key. Block 0 Magic Damage (initial
                            shard-impact pass-through) + block 2 Total
                            Maximum Detonation Damage (aggregate of
                            multiple stone detonations when target
                            steps through Unraveled Earth). Operator
                            commits to landing the spell on target +
                            target moving through resulting terrain.
                            Closes s215's 'Taliyah E likely no-op' note
                            which missed that block 0 IS an additional
                            damage source separate from the detonation
                            aggregate.

  * DrMundo.W = [1, 2]    - LIFT from s193's single-int {W: 1}. Block 1
                            Total Magic Damage (full 4-second Heart
                            Zapper drain channel) + block 2 Magic
                            Damage (recast detonation burst). Operator
                            commits to letting Heart Zapper run + manual
                            recast at end. Same in-batch lift pattern
                            as s215's Thresh.E lift {E: 2} -> {E: [1, 2]}.

Mirrors the s215 test structure: registry shape assertions + arithmetic
parity (sum == sum of forced singletons) + strict-greater guards vs
forced block 0 / single-block A/B. ENGINE_VERSION 0.93.0 -> 0.94.0 pinned.
Backward-compat: prior s207 + s215 sum-of-blocks entries unchanged.

All 2 entries verified per-rank against the Meraki 16.10.1 snapshot
during s217 implementation:
  * Taliyah E rank 5: block 0 240+60%AP, block 2 262.5+75%AP - sum 502.5
                      raw base (+109% over forced block 0 alone)
  * DrMundo W rank 5: block 1 320 base, block 2 80 base - sum 400 raw
                      base (+25% over forced block 1 alone)
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


# --- Registry shape - 2 new/lifted entries -----------------------------------


class Phase599_22RegistrySeedTests(unittest.TestCase):
    """The 2 entries are present with expected shapes.

    Taliyah gains a new E key (Q=2 preserved from s201). DrMundo's
    existing W=1 entry is lifted to the list form [1, 2].
    """

    @classmethod
    def setUpClass(cls) -> None:
        reset_block_index_cache()

    def test_taliyah_E_is_impact_plus_max_detonation(self) -> None:
        m, src = get_block_index_for("Taliyah")
        self.assertEqual(src, "champion")
        self.assertEqual(m.get("E"), [0, 2])

    def test_taliyah_Q_preserved_from_s201(self) -> None:
        """Taliyah Q=2 from s201 (Threaded Volley 5-stone Worked Ground
        commit) must be unchanged after the E addition."""
        m, _ = get_block_index_for("Taliyah")
        self.assertEqual(m.get("Q"), 2)

    def test_drmundo_W_lifted_from_int_to_list(self) -> None:
        m, src = get_block_index_for("DrMundo")
        self.assertEqual(src, "champion")
        v = m.get("W")
        self.assertIsInstance(v, list)
        self.assertEqual(v, [1, 2])


# --- Arithmetic parity - sum == sum of forced singletons ---------------------


class Phase599_22AbilityDpsTests(unittest.TestCase):
    """Sum-of-blocks entries deliver canonical full-burst totals.

    Pattern mirrors ``test_sum_of_blocks_expansion_s215``: fetch the
    per-spell row with the registry active, then fetch the same row
    with a forced single block_index for each component, and assert
    arithmetic parity. Both deltas are strictly positive (no clamping).
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

    # --- Taliyah E [0, 2] ---------------------------------------------------

    def test_taliyah_E_sum_exceeds_block_0_alone(self) -> None:
        """Sum strictly exceeds block 0 (initial impact) alone - block 2
        adds the Total Maximum Detonation aggregate which carries 75% AP
        and a larger base at every rank."""
        s_sum = self._spell("Taliyah", "E")
        s_forced = self._spell_forced("Taliyah", "E", 0)
        self.assertGreater(s_sum.raw_damage_per_cast, s_forced.raw_damage_per_cast)

    def test_taliyah_E_sum_exceeds_block_2_alone(self) -> None:
        """Sum strictly exceeds block 2 (max detonation) alone - block 0
        adds the initial pass-through impact damage."""
        s_sum = self._spell("Taliyah", "E")
        s_forced = self._spell_forced("Taliyah", "E", 2)
        self.assertGreater(s_sum.raw_damage_per_cast, s_forced.raw_damage_per_cast)

    def test_taliyah_E_sum_matches_explicit_arithmetic(self) -> None:
        s_sum = self._spell("Taliyah", "E")
        s_b0 = self._spell_forced("Taliyah", "E", 0)
        s_b2 = self._spell_forced("Taliyah", "E", 2)
        self.assertAlmostEqual(
            s_sum.raw_damage_per_cast,
            s_b0.raw_damage_per_cast + s_b2.raw_damage_per_cast,
            places=4,
        )

    # --- DrMundo W [1, 2] ---------------------------------------------------

    def test_drmundo_W_sum_exceeds_block_1_alone(self) -> None:
        """Sum strictly exceeds block 1 (full channel) alone - block 2
        adds the recast detonation burst (20-80 base damage)."""
        s_sum = self._spell("DrMundo", "W")
        s_forced = self._spell_forced("DrMundo", "W", 1)
        self.assertGreater(s_sum.raw_damage_per_cast, s_forced.raw_damage_per_cast)

    def test_drmundo_W_sum_exceeds_block_2_alone(self) -> None:
        """Sum strictly exceeds block 2 (recast detonation) alone - the
        full-channel total carries the bulk of the damage at higher ranks."""
        s_sum = self._spell("DrMundo", "W")
        s_forced = self._spell_forced("DrMundo", "W", 2)
        self.assertGreater(s_sum.raw_damage_per_cast, s_forced.raw_damage_per_cast)

    def test_drmundo_W_sum_matches_explicit_arithmetic(self) -> None:
        s_sum = self._spell("DrMundo", "W")
        s_b1 = self._spell_forced("DrMundo", "W", 1)
        s_b2 = self._spell_forced("DrMundo", "W", 2)
        self.assertAlmostEqual(
            s_sum.raw_damage_per_cast,
            s_b1.raw_damage_per_cast + s_b2.raw_damage_per_cast,
            places=4,
        )


# --- Backward-compat - s207 + s215 sum-of-blocks entries preserved -----------


class Phase599_22BackwardCompatTests(unittest.TestCase):
    """All prior sum-of-blocks entries (s207 seed + s215 batch) still
    resolve identically post-s217."""

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

    def test_thresh_E_unchanged_from_s215(self) -> None:
        m, _ = get_block_index_for("Thresh")
        self.assertEqual(m.get("E"), [1, 2])

    def test_sona_Q_unchanged_from_s215(self) -> None:
        m, _ = get_block_index_for("Sona")
        self.assertEqual(m.get("Q"), [0, 1])

    def test_kalista_E_unchanged_from_s215(self) -> None:
        m, _ = get_block_index_for("Kalista")
        self.assertEqual(m.get("E"), [0, 1, 1, 1, 1])

    def test_malzahar_R_unchanged_from_s215(self) -> None:
        m, _ = get_block_index_for("Malzahar")
        self.assertEqual(m.get("R"), [0, 2])

    def test_unmapped_champion_still_returns_empty(self) -> None:
        m, src = get_block_index_for("Annie")
        self.assertEqual(m, {})
        self.assertEqual(src, "default")


# --- ENGINE_VERSION pin ------------------------------------------------------


class Phase599_22EngineVersionTests(unittest.TestCase):
    def test_engine_version_bumped(self) -> None:
        from agents import daemon_slayer
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.255.0")


if __name__ == "__main__":
    unittest.main()
