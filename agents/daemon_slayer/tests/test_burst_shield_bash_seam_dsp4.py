"""DSP4 burst/combo seam - score_completion_runes default-OFF byte-identical.

Shield Bash 8401 is registered in RUNE_PROCS but tagged in COMPLETION_RUNE_IDS,
so the burst + combo scorers SKIP it unless ``score_completion_runes=True``.
Default False keeps every existing rune set byte-identical to the pre-DSP4
engine (do-not-flip-blind; the live default-ON flip is operator-gated in
docs/LIVE_GAME_GATED_SYNC.md). When ON, Shield Bash contributes its
on_proc_burst floor (5-30 by level + 2.5% bonus HP), and a non-completion rune
(Electrocute 8112) is unaffected by the flag.

NO ENGINE_VERSION assertions here (the orchestrator owns the bump).
"""

from __future__ import annotations

import pathlib
import unittest

from agents.daemon_slayer import combo as cb
from agents.daemon_slayer.burst import compute_burst_damage
from agents.daemon_slayer.data_loader import DataSnapshot

_SNAP = DataSnapshot.load()
_TGT = dict(
    target_armor=80.0, target_mr=60.0, target_max_hp=2000.0, target_bonus_hp=600.0
)


def _burst(champ, *, runes=None, completion=False, level=11):
    return compute_burst_damage(
        _SNAP, champ, level, item_ids=[], mode="SR",
        runes=runes, score_completion_runes=completion, **_TGT,
    )


class BurstSeamDefaultOffTests(unittest.TestCase):
    def test_shield_bash_off_byte_identical(self):
        # Leona (Resolve, melee tank) - a natural Shield Bash carrier.
        base = _burst("Leona", runes=None)
        off = _burst("Leona", runes=[8401], completion=False)
        self.assertEqual(base.total_burst_damage, off.total_burst_damage)
        self.assertEqual(off.rune_proc_damage, 0.0)

    def test_default_kwarg_is_off(self):
        # Omitting score_completion_runes == passing False.
        omitted = compute_burst_damage(
            _SNAP, "Leona", 11, item_ids=[], mode="SR", runes=[8401], **_TGT
        )
        base = _burst("Leona", runes=None)
        self.assertEqual(omitted.total_burst_damage, base.total_burst_damage)
        self.assertEqual(omitted.rune_proc_damage, 0.0)


class BurstSeamOnTests(unittest.TestCase):
    def test_shield_bash_on_adds_floor(self):
        base = _burst("Leona", runes=None)
        on = _burst("Leona", runes=[8401], completion=True)
        # on_proc_burst (no amp): total rises by exactly the Shield Bash floor.
        self.assertGreater(on.rune_proc_damage, 0.0)
        self.assertAlmostEqual(
            on.total_burst_damage,
            base.total_burst_damage + on.rune_proc_damage, places=4,
        )

    def test_non_completion_rune_unaffected_by_flag(self):
        # Electrocute 8112 is NOT a completion rune -> consumed regardless.
        off = _burst("Leona", runes=[8112], completion=False)
        on = _burst("Leona", runes=[8112], completion=True)
        self.assertEqual(off.total_burst_damage, on.total_burst_damage)
        self.assertGreater(off.rune_proc_damage, 0.0)


class ComboSeamTests(unittest.TestCase):
    _SEQ = ("Q", "AA", "W", "E", "R")

    def _combo(self, *, runes=None, completion=False):
        return cb.compute_combo(
            "Leona", 11, item_ids=[], sequence=self._SEQ,
            target_armor=80.0, target_mr=60.0,
            target_max_hp=2000.0, target_bonus_hp=600.0,
            mode="SR", snapshot=_SNAP, runes=runes,
            score_completion_runes=completion,
        )

    def test_combo_shield_bash_off_byte_identical(self):
        base = self._combo(runes=None)
        off = self._combo(runes=[8401], completion=False)
        self.assertEqual(base.total_mitigated, off.total_mitigated)

    def test_combo_shield_bash_on_raises_total(self):
        off = self._combo(runes=[8401], completion=False)
        on = self._combo(runes=[8401], completion=True)
        self.assertGreater(on.total_mitigated, off.total_mitigated)


class AsciiHygieneTests(unittest.TestCase):
    def test_module_ascii(self):
        raw = pathlib.Path(__file__).read_bytes()
        self.assertEqual([b for b in raw if b > 0x7F], [])


if __name__ == "__main__":
    unittest.main()
