"""R35 - live percent-DR consumer for mitigation_multipliers (snapshot fold).

R19 shipped the forward-marker accessor
``DataSnapshot.spell_damage_reduction_pct(champ_id, slot)`` returning the
per-rank PERCENT damage-reduction magnitude from the ``champion_abilities.json``
defensive ``modifier`` blocks, with NO consumer. R35 wires that accessor into
``mitigation_multipliers``: when a ``snapshot`` is passed AND
``apply_passive_mitigation`` is True, each (champ, slot) percent-DR block folds
into the matching EHP-denominator multiplier exactly like a hand-authored
``PassiveMitigationEntry`` - amortized by ``_ACTIVE_DR_PROB`` and read at
``_ASSUMED_ABILITY_RANK`` (per-rank, clamped to the tuple bounds).

DEFAULT-OFF is byte-identical: ``apply_passive_mitigation=False`` returns
(1,1,1) before the snapshot is ever consulted, and the legacy 3-arg call
(``snapshot`` defaults None) is unchanged - the percent registry only adds the
hand-authored entries, as item 261 pinned.

The axis classification follows the LIVE data, not the directive's literal
3-key map: 16.13.1 carries five distinct labels - ``Damage Reduction``,
Braum's lowercased ``Damage reduction``, ``Magic Damage Reduction``,
``Physical Damage Reduction``, and MasterYi's ``Modified Damage Reduction`` -
so a case-insensitive substring test (``physical`` -> PHYS, ``magic`` -> MAG,
else ANY) is required; an exact map would miss Braum and MasterYi.
"""
from __future__ import annotations

import unittest

import agents.daemon_slayer as daemon_slayer
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import compute_ehp
from agents.daemon_slayer._passive_mitigation_overrides import (
    _ACTIVE_DR_PROB,
    _ASSUMED_ABILITY_RANK,
    _HAND_AUTHORED_DR_CHAMPS,
    _PASSIVE_MITIGATION_OVERRIDES,
    mitigation_multipliers,
)

SNAP = DataSnapshot.load()
_IDX = _ASSUMED_ABILITY_RANK - 1  # per-rank read index (rank 4 -> index 3)


def _mult(pct: float) -> float:
    """The denominator multiplier a snapshot percent-DR term contributes."""
    return 1.0 - (pct / 100.0) * _ACTIVE_DR_PROB


class SnapshotMitigationConsumerTests(unittest.TestCase):
    def test_default_off_is_byte_identical(self):
        # apply_passive_mitigation=False short-circuits before the snapshot is
        # consulted - identity even for a champ with a percent-DR block.
        self.assertEqual(
            mitigation_multipliers("Galio", 11, False, SNAP), (1.0, 1.0, 1.0)
        )

    def test_legacy_three_arg_call_unchanged(self):
        # snapshot defaults None: Galio (not hand-authored) gets nothing, exactly
        # like the item-261 pin for the 3-arg signature.
        self.assertEqual(mitigation_multipliers("Galio", 11, True), (1.0, 1.0, 1.0))

    def test_galio_split_phys_and_magic(self):
        mp, mm, mt = mitigation_multipliers("Galio", 11, True, SNAP)
        # Magic Damage Reduction (25,30,35,40,45)[3]=40 -> MAG axis.
        # Physical Damage Reduction (12.5,15,17.5,20,22.5)[3]=20 -> PHYS axis.
        self.assertAlmostEqual(mp, _mult(20.0))
        self.assertAlmostEqual(mm, _mult(40.0))
        self.assertAlmostEqual(mt, 1.0)
        self.assertLess(mp, 1.0)
        self.assertLess(mm, 1.0)

    def test_garen_generic_label_is_all_axes(self):
        mp, mm, mt = mitigation_multipliers("Garen", 11, True, SNAP)
        # Damage Reduction (25,29,33,37,41)[3]=37 -> ANY -> all three axes.
        exp = _mult(37.0)
        self.assertAlmostEqual(mp, exp)
        self.assertAlmostEqual(mm, exp)
        self.assertAlmostEqual(mt, exp)

    def test_masteryi_modified_label_classifies_any(self):
        mp, mm, mt = mitigation_multipliers("MasterYi", 11, True, SNAP)
        # "Modified Damage Reduction" (45,47.5,50,52.5,55)[3]=52.5 -> no
        # physical/magic token -> ANY (all axes), proving substring classify.
        exp = _mult(52.5)
        self.assertAlmostEqual(mp, exp)
        self.assertAlmostEqual(mm, exp)
        self.assertAlmostEqual(mt, exp)

    def test_braum_lowercase_label_classifies_any(self):
        mp, mm, mt = mitigation_multipliers("Braum", 11, True, SNAP)
        # Braum's lowercased "Damage reduction" (35,40,45,50,55)[3]=50 -> ANY.
        exp = _mult(50.0)
        self.assertAlmostEqual(mp, exp)
        self.assertAlmostEqual(mm, exp)
        self.assertAlmostEqual(mt, exp)

    def test_alistar_rank_index_clamps_to_three_rank_tuple(self):
        # Alistar R has only 3 ranks (55,65,75); _ASSUMED_ABILITY_RANK=4 ->
        # index 3 clamps to the last (75.0), never an IndexError.
        mp, mm, mt = mitigation_multipliers("Alistar", 11, True, SNAP)
        exp = _mult(75.0)
        self.assertAlmostEqual(mp, exp)
        self.assertAlmostEqual(mm, exp)
        self.assertAlmostEqual(mt, exp)

    def test_untabled_champ_is_identity(self):
        # Ashe has no defensive percent-DR block -> identity.
        self.assertEqual(
            mitigation_multipliers("Ashe", 11, True, SNAP), (1.0, 1.0, 1.0)
        )

    def test_no_double_count_guard_set_excludes_snapshot_champs(self):
        # The guard skips the snapshot fold for any champ already hand-authored,
        # so a future champ landing in BOTH registries is never counted twice.
        # Today the two sets are disjoint - assert that invariant holds.
        snap_champs = set(SNAP._build_damage_reduction_pct_map().keys())
        self.assertTrue(_HAND_AUTHORED_DR_CHAMPS.isdisjoint(snap_champs))
        self.assertEqual(
            _HAND_AUTHORED_DR_CHAMPS,
            {c for (c, _k, _f) in _PASSIVE_MITIGATION_OVERRIDES},
        )

    def test_hand_authored_champ_unaffected_by_snapshot(self):
        # A hand-authored champ (Kassadin, 10% magic) returns the same result
        # whether or not a snapshot is supplied - the guard never lets the
        # snapshot path alter a curated entry.
        without = mitigation_multipliers("Kassadin", 11, True)
        withsnap = mitigation_multipliers("Kassadin", 11, True, SNAP)
        self.assertEqual(without, withsnap)

    def test_compute_ehp_wiring_raises_galio_resist_ehp(self):
        # End-to-end through ehp.py: the opt-in flag now folds Galio's split DR
        # into the magical + physical EHP denominators -> both rise.
        off = compute_ehp(SNAP, "Galio", 11, apply_passive_mitigation=False)
        on = compute_ehp(SNAP, "Galio", 11, apply_passive_mitigation=True)
        self.assertGreater(on.magical_ehp, off.magical_ehp)
        self.assertGreater(on.physical_ehp, off.physical_ehp)
        # true_ehp untouched (Galio carries no true-DR term).
        self.assertAlmostEqual(on.true_ehp, off.true_ehp)

    def test_compute_ehp_default_off_byte_identical(self):
        # The default compute_ehp path (apply_passive_mitigation=False) is
        # byte-identical for a percent-DR champ - live DS output unchanged.
        base = compute_ehp(SNAP, "Galio", 11)
        explicit_off = compute_ehp(SNAP, "Galio", 11, apply_passive_mitigation=False)
        self.assertEqual(base.magical_ehp, explicit_off.magical_ehp)
        self.assertEqual(base.physical_ehp, explicit_off.physical_ehp)

    def test_engine_version_bumped(self):
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.196.0")


if __name__ == "__main__":
    unittest.main()
