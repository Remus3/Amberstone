"""B1 melee-applicability gate (DS Tier-2 cross-eval nomination B, default-OFF).

`dps.py`/`hybrid.py` had NO attack-range gate, so Runaan's Hurricane's two
extra bolts (a RANGED-only on-hit in League) were credited on melee autos.
The `apply_melee_aa_gate` seam (default-OFF, byte-identical when off) drops a
`PeriodicProc.ranged_only` proc on a melee champion (attackrange <
`MELEE_RANGE_CEILING`). Evidence: ops/audit/ds_cross_eval/TIER2_REPORT.md (B1).

Difference-of-differences assertions (not fragile cross-item magnitudes): the
gate removes >0 DPS for a melee champ and exactly 0 for a ranged champ.
"""

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import MELEE_RANGE_CEILING, compute_dps
from agents.daemon_slayer.effects import ITEM_EFFECTS

RUNAANS = "3085"
RUNAANS_ARENA = "223085"


class TestRunaanRangedOnlyTag(unittest.TestCase):
    def test_runaans_winds_fury_tagged_ranged_only(self):
        for iid in (RUNAANS, RUNAANS_ARENA):
            eff = ITEM_EFFECTS[iid]
            fury = [p for p in eff.periodics if "Wind's Fury" in p.name]
            self.assertTrue(fury, f"{iid} must carry the Wind's Fury proc")
            for p in fury:
                self.assertTrue(p.ranged_only, f"{iid} Wind's Fury must be ranged_only")

    def test_other_procs_not_ranged_only(self):
        # Spellblade / on-hit physical procs apply on melee autos -> stay False
        for iid in ("3078", "3153", "3091"):  # Triforce, BotRK, Wit's End
            eff = ITEM_EFFECTS.get(iid)
            if eff is None:
                continue
            for p in eff.periodics:
                if "Wind's Fury" in p.name:
                    continue
                self.assertFalse(p.ranged_only, f"{iid} {p.name} must not be ranged_only")


class TestMeleeAAGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()

    def _dps(self, champ, gate, level=11):
        return compute_dps(
            self.snap, champ, level=level, item_ids=[RUNAANS],
            apply_melee_aa_gate=gate,
        ).weighted_dps

    def test_melee_ceiling_is_350(self):
        self.assertEqual(MELEE_RANGE_CEILING, 350)

    def test_default_off_byte_identical_melee(self):
        a = compute_dps(self.snap, "Briar", level=11, item_ids=[RUNAANS]).weighted_dps
        b = self._dps("Briar", False)
        self.assertEqual(a, b)

    def test_default_off_byte_identical_ranged(self):
        a = compute_dps(self.snap, "Caitlyn", level=11, item_ids=[RUNAANS]).weighted_dps
        b = self._dps("Caitlyn", False)
        self.assertEqual(a, b)

    def test_melee_champ_drops_bolt_credit_when_on(self):
        for champ in ("Briar", "XinZhao", "Nilah"):  # 125 / 175 / 225 attackrange
            self.assertGreater(self._dps(champ, False), self._dps(champ, True), champ)

    def test_ranged_champ_unaffected_by_gate(self):
        for champ in ("Caitlyn", "Senna", "Xayah"):  # 650 / 600 / 525 attackrange
            self.assertEqual(self._dps(champ, False), self._dps(champ, True), champ)

    def test_difference_of_differences(self):
        melee_delta = self._dps("XinZhao", False) - self._dps("XinZhao", True)
        ranged_delta = self._dps("Senna", False) - self._dps("Senna", True)
        self.assertGreater(melee_delta, 0.0)
        self.assertEqual(ranged_delta, 0.0)

    def test_gate_no_op_without_runaans(self):
        # a melee build WITHOUT a ranged_only proc is byte-identical on/off
        off = compute_dps(self.snap, "Briar", level=11, item_ids=["3078"],
                          apply_melee_aa_gate=False).weighted_dps
        on = compute_dps(self.snap, "Briar", level=11, item_ids=["3078"],
                         apply_melee_aa_gate=True).weighted_dps
        self.assertEqual(off, on)


if __name__ == "__main__":
    unittest.main()
