"""Engine Agent A - compute_hps R5 missing-HP heal-amp passthrough.

Proves ``hps.compute_hps`` (and the ranker ``hps.rank_items_by_hps`` that
forwards into it) thread the R5 seam args
``assume_missing_hp_heal_amp`` / ``caster_missing_hp_pct`` straight into the
champion-ability heal scorer ``ability_hps.compute_ability_hps``:

  * DEFAULT-OFF (assume_missing_hp_heal_amp=False, caster_missing_hp_pct=0.0)
    is byte-identical to today - the comeback heal-amp is never applied.
  * ON with a positive ``caster_missing_hp_pct`` for a champ in the
    missing-HP heal-amp registry DIVERGES (a larger heal throughput, hence a
    larger ``total_throughput``).

Confirmed API surface before scaffolding:
  * compute_hps(snapshot, champion_id, level, ..., assume_missing_hp_heal_amp,
    caster_missing_hp_pct) -> HpsResult with .total_throughput
    - hps.py (compute_hps def + HpsResult.total_throughput).
  * rank_items_by_hps(..., assume_missing_hp_heal_amp, caster_missing_hp_pct)
    -> HpsRankResult with .ranked[*].new_hps - hps.py.
  * compute_ability_hps accepts caster_missing_hp_pct +
    assume_missing_hp_heal_amp - ability_hps.py:689-690.
  * _MISSING_HP_HEAL_AMP registry = MasterYi W / Lissandra R / Sylas W /
    Briar P - ability_hps.py:455-458. MasterYi / Sylas have a non-trivial
    self-heal throughput that the amp scales (live-probed).

No ENGINE_VERSION assertion here (version bump is a separate agent).
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.hps import compute_hps, rank_items_by_hps

_SNAP = DataSnapshot.load()


class ComputeHpsMissingHpAmpTests(unittest.TestCase):
    """compute_hps threads R5 into the ability-heal scorer."""

    def test_default_off_byte_identical(self):
        # Omitting the keys equals explicitly passing the off/zero defaults.
        omit = compute_hps(_SNAP, champion_id="MasterYi", level=11, mode="SR")
        explicit_off = compute_hps(
            _SNAP, champion_id="MasterYi", level=11, mode="SR",
            assume_missing_hp_heal_amp=False, caster_missing_hp_pct=0.0,
        )
        self.assertEqual(
            omit.total_throughput, explicit_off.total_throughput
        )

    def test_flag_on_but_full_hp_byte_identical(self):
        # ON with caster_missing_hp_pct == 0.0 (full HP) is still factor 1.0,
        # so the throughput is unchanged from the default-off baseline.
        off = compute_hps(_SNAP, champion_id="MasterYi", level=11, mode="SR")
        on_full = compute_hps(
            _SNAP, champion_id="MasterYi", level=11, mode="SR",
            assume_missing_hp_heal_amp=True, caster_missing_hp_pct=0.0,
        )
        self.assertEqual(off.total_throughput, on_full.total_throughput)

    def test_amp_on_diverges_masteryi(self):
        off = compute_hps(_SNAP, champion_id="MasterYi", level=11, mode="SR")
        on = compute_hps(
            _SNAP, champion_id="MasterYi", level=11, mode="SR",
            assume_missing_hp_heal_amp=True, caster_missing_hp_pct=0.5,
        )
        self.assertGreater(on.total_throughput, off.total_throughput)

    def test_amp_on_diverges_sylas(self):
        off = compute_hps(_SNAP, champion_id="Sylas", level=11, mode="SR")
        on = compute_hps(
            _SNAP, champion_id="Sylas", level=11, mode="SR",
            assume_missing_hp_heal_amp=True, caster_missing_hp_pct=0.5,
        )
        self.assertGreater(on.total_throughput, off.total_throughput)

    def test_unregistered_champ_no_op(self):
        # A champ NOT in _MISSING_HP_HEAL_AMP is byte-identical even with the
        # seam fully engaged - the amp factor stays 1.0.
        off = compute_hps(_SNAP, champion_id="Soraka", level=11, mode="SR")
        on = compute_hps(
            _SNAP, champion_id="Soraka", level=11, mode="SR",
            assume_missing_hp_heal_amp=True, caster_missing_hp_pct=0.5,
        )
        self.assertEqual(off.total_throughput, on.total_throughput)


class RankItemsByHpsMissingHpAmpTests(unittest.TestCase):
    """rank_items_by_hps forwards R5 into BOTH baseline + candidate compute_hps."""

    def test_default_off_byte_identical(self):
        omit = rank_items_by_hps(
            _SNAP, champion_id="MasterYi", level=11, mode="SR",
            enchanter_only=False, top_n=40,
        )
        explicit_off = rank_items_by_hps(
            _SNAP, champion_id="MasterYi", level=11, mode="SR",
            enchanter_only=False, top_n=40,
            assume_missing_hp_heal_amp=False, caster_missing_hp_pct=0.0,
        )
        self.assertEqual(
            [(r.item_name, r.new_hps) for r in omit.ranked],
            [(r.item_name, r.new_hps) for r in explicit_off.ranked],
        )

    def test_amp_on_lifts_new_hps(self):
        off = rank_items_by_hps(
            _SNAP, champion_id="MasterYi", level=11, mode="SR",
            enchanter_only=False, top_n=40,
        )
        on = rank_items_by_hps(
            _SNAP, champion_id="MasterYi", level=11, mode="SR",
            enchanter_only=False, top_n=40,
            assume_missing_hp_heal_amp=True, caster_missing_hp_pct=0.5,
        )
        off_by_name = {r.item_name: r.new_hps for r in off.ranked}
        on_by_name = {r.item_name: r.new_hps for r in on.ranked}
        shared = set(off_by_name) & set(on_by_name)
        self.assertTrue(shared)
        # The missing-HP amp lifts MasterYi's ability-heal throughput, so every
        # shared candidate's new_hps is strictly larger under the seam.
        self.assertTrue(
            all(on_by_name[n] > off_by_name[n] for n in shared)
        )


if __name__ == "__main__":
    unittest.main()
