"""DS V2 S3 - rune_procs wired into burst + combo behind optional ``runes``.

The wire is PURE ADDITIVE: when ``runes`` is None/empty/unknown-only the
burst + combo totals are BYTE-IDENTICAL to the no-runes path. When a real
rune id is supplied the rune layer contributes either a flat on-proc burst
piece (Electrocute / Dark Harvest / ...) or a keystone amp (Press the
Attack x1.08), and Conqueror (adaptive stat stack, not a damage amp) is
EXCLUDED from the damage total.

Rune layer (``agents/daemon_slayer/rune_procs.py``):
  * 8005 Press the Attack - ``stacking_amp`` (1.08 amp) + a 40-160 burst piece.
  * 8112 Electrocute       - ``on_proc_burst`` 70-240 by level + 0.10 bAD + 0.05 AP.
  * 8010 Conqueror         - ``adaptive`` per-stack force (NOT a damage total).
  * 99999                  - unknown id -> 0.0 contribution / amp pass-through.

NO ENGINE_VERSION assertions here (the orchestrator owns the bump).
"""

from __future__ import annotations

import pathlib
import unittest

from agents.daemon_slayer import combo as cb
from agents.daemon_slayer.burst import compute_burst_damage
from agents.daemon_slayer.data_loader import DataSnapshot


# One shared snapshot for the whole module (load is fast but reused anyway).
_SNAP = DataSnapshot.load()

# Targets used across tests (vs a typical bruiser-ish profile so AA + abilities
# both land non-zero damage).
_TGT = dict(target_armor=80.0, target_mr=60.0, target_max_hp=2000.0, target_bonus_hp=600.0)


def _burst(champ: str, *, runes=None, level: int = 11, items=None):
    return compute_burst_damage(
        _SNAP,
        champ,
        level,
        item_ids=list(items or []),
        mode="SR",
        runes=runes,
        **_TGT,
    )


class BurstByteIdenticalTests(unittest.TestCase):
    """runes None / [] / unknown-only -> byte-identical to no-runes path."""

    def test_none_equals_omitted_lux(self):
        a = compute_burst_damage(_SNAP, "Lux", 11, item_ids=[], mode="SR", **_TGT)
        b = _burst("Lux", runes=None)
        self.assertEqual(a.total_burst_damage, b.total_burst_damage)
        self.assertEqual(b.rune_proc_damage, 0.0)

    def test_none_equals_omitted_caitlyn(self):
        a = compute_burst_damage(_SNAP, "Caitlyn", 11, item_ids=[], mode="SR", **_TGT)
        b = _burst("Caitlyn", runes=None)
        self.assertEqual(a.total_burst_damage, b.total_burst_damage)
        self.assertEqual(b.rune_proc_damage, 0.0)

    def test_empty_list_equals_none(self):
        none = _burst("Lux", runes=None)
        empty = _burst("Lux", runes=[])
        self.assertEqual(none.total_burst_damage, empty.total_burst_damage)
        self.assertEqual(empty.rune_proc_damage, 0.0)

    def test_unknown_rune_id_byte_identical(self):
        base = _burst("Lux", runes=None)
        unknown = _burst("Lux", runes=[99999])
        self.assertEqual(base.total_burst_damage, unknown.total_burst_damage)
        self.assertEqual(unknown.rune_proc_damage, 0.0)


class BurstElectrocuteTests(unittest.TestCase):
    """8112 Electrocute is on_proc_burst: total rises by exactly the proc damage."""

    def test_electrocute_adds_proc_no_amp(self):
        base = _burst("Lux", runes=None)
        elec = _burst("Lux", runes=[8112])
        self.assertGreater(elec.rune_proc_damage, 0.0)
        # on_proc_burst -> no amp on the ability+AA base; total == base + proc.
        self.assertAlmostEqual(
            elec.total_burst_damage,
            base.total_burst_damage + elec.rune_proc_damage,
            places=4,
        )

    def test_electrocute_proc_field_surfaced_in_to_dict(self):
        elec = _burst("Lux", runes=[8112])
        d = elec.to_dict()
        self.assertIn("rune_proc_damage", d)
        self.assertEqual(d["rune_proc_damage"], elec.rune_proc_damage)


class BurstPressTheAttackTests(unittest.TestCase):
    """8005 Press the Attack: 1.08 amp on base + a 40-160 burst piece."""

    def test_pta_raises_total_and_has_proc(self):
        base = _burst("Caitlyn", runes=None)
        pta = _burst("Caitlyn", runes=[8005])
        self.assertGreater(pta.total_burst_damage, base.total_burst_damage)
        self.assertGreater(pta.rune_proc_damage, 0.0)

    def test_pta_total_equals_amped_base_plus_proc(self):
        base = _burst("Caitlyn", runes=None)
        pta = _burst("Caitlyn", runes=[8005])
        # amp 1.08 on the ability+AA base, then add the burst piece.
        expected = base.total_burst_damage * 1.08 + pta.rune_proc_damage
        self.assertAlmostEqual(pta.total_burst_damage, expected, places=3)


class BurstConquerorExcludedTests(unittest.TestCase):
    """8010 Conqueror is adaptive (a stat stack) - excluded from the damage total."""

    def test_conqueror_does_not_change_total(self):
        base = _burst("Caitlyn", runes=None)
        conq = _burst("Caitlyn", runes=[8010])
        self.assertEqual(conq.rune_proc_damage, 0.0)
        self.assertEqual(conq.total_burst_damage, base.total_burst_damage)


class ComboWireTests(unittest.TestCase):
    """compute_combo threads ``runes`` into the burst walker, surfaces in total."""

    _SEQ = ("Q", "AA", "W", "E", "R")

    def _combo(self, *, runes=None):
        return cb.compute_combo(
            "Lux", 11, item_ids=[], sequence=self._SEQ,
            target_armor=80.0, target_mr=60.0,
            target_max_hp=2000.0, target_bonus_hp=600.0,
            mode="SR", snapshot=_SNAP, runes=runes,
        )

    def test_combo_none_byte_identical_to_omitted(self):
        omitted = cb.compute_combo(
            "Lux", 11, item_ids=[], sequence=self._SEQ,
            target_armor=80.0, target_mr=60.0,
            target_max_hp=2000.0, target_bonus_hp=600.0,
            mode="SR", snapshot=_SNAP,
        )
        none = self._combo(runes=None)
        self.assertEqual(omitted.total_mitigated, none.total_mitigated)
        self.assertEqual(omitted.total_raw, none.total_raw)

    def test_combo_empty_list_equals_none(self):
        self.assertEqual(
            self._combo(runes=None).total_mitigated,
            self._combo(runes=[]).total_mitigated,
        )

    def test_combo_electrocute_raises_total(self):
        none = self._combo(runes=None)
        elec = self._combo(runes=[8112])
        self.assertGreater(elec.total_mitigated, none.total_mitigated)

    def test_combo_unknown_rune_byte_identical(self):
        none = self._combo(runes=None)
        unknown = self._combo(runes=[99999])
        self.assertEqual(none.total_mitigated, unknown.total_mitigated)


class AsciiHygieneTests(unittest.TestCase):
    def test_module_is_ascii(self):
        p = pathlib.Path(__file__)
        raw = p.read_bytes()
        non_ascii = [(i, b) for i, b in enumerate(raw) if b > 0x7F]
        self.assertEqual(non_ascii, [], f"non-ASCII bytes at {non_ascii[:5]}")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
