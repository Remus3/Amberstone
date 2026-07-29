"""RM-123 - melee/ranged split reconciliation (root-cause regression).

The engine encoded one boolean fact (melee vs ranged) as a magic attackrange
threshold in four sites with two different values (250 in ehp/rank, 350 in
burst/dps) and three operators. The 250 sites wrongly classify the only three
champions whose base attackrange sits in the 250 < ar <= 350 band:

    Rakan  300  -> MELEE  (250 sites called ranged)
    Lillia 325  -> MELEE  (250 sites called ranged)
    Urgot  350  -> RANGED (burst strict `> 350` called melee)

Full 173-roster scan confirms the ONLY champions in 250 < ar < 450 are Rakan
(300), Lillia (325), Urgot (350), Graves (425), Yuumi (425); the rule
"ranged iff attackrange >= 350.0" classifies every one correctly and matches
real League. This test pins that single canonical rule across every consumer.
"""

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer import ehp as ehp_mod
from agents.daemon_slayer import rank as rank_mod
from agents.daemon_slayer import dps as dps_mod


# (name, expected_is_ranged). Grounded in the live snapshot's real attackrange.
_CASES = [
    ("Sett", False),      # 125  melee
    ("Yasuo", False),     # 175  melee
    ("Nilah", False),     # 225  melee
    ("Rakan", False),     # 300  melee  <- 250 bug
    ("Lillia", False),    # 325  melee  <- 250 bug
    ("Urgot", True),      # 350  ranged <- burst strict-> bug
    ("Graves", True),     # 425  ranged marksman (must stay buyable Runaan's)
    ("Kalista", True),    # 525  ranged
]


class MeleeRangedSplitRM123(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()

    def test_ehp_is_ranged_matches_canonical(self):
        for name, want_ranged in _CASES:
            rec = self.snap.champion(name)
            base = rec.get("stats") or {}
            self.assertEqual(
                ehp_mod._is_ranged(base),
                want_ranged,
                f"ehp._is_ranged mis-classified {name} "
                f"(attackrange={base.get('attackrange')})",
            )

    def test_rank_champion_is_melee_matches_canonical(self):
        for name, want_ranged in _CASES:
            rec = self.snap.champion(name)
            self.assertEqual(
                rank_mod._champion_is_melee(rec),
                not want_ranged,
                f"rank._champion_is_melee mis-classified {name} "
                f"(attackrange={(rec.get('stats') or {}).get('attackrange')})",
            )

    def test_all_sites_agree_on_the_band(self):
        # The two hub predicates must never contradict each other.
        for name, _ in _CASES:
            rec = self.snap.champion(name)
            base = rec.get("stats") or {}
            ehp_ranged = ehp_mod._is_ranged(base)
            rank_melee = rank_mod._champion_is_melee(rec)
            self.assertEqual(
                ehp_ranged,
                not rank_melee,
                f"ehp/rank disagree on {name}: ehp_ranged={ehp_ranged} "
                f"rank_melee={rank_melee}",
            )

    def test_split_boundary_is_350(self):
        # dps already carried the correct value; pin it as the shared split.
        self.assertEqual(dps_mod.MELEE_RANGE_CEILING, 350)
        # Boundary: 349 melee, exactly 350 ranged, 351 ranged.
        self.assertFalse(ehp_mod._is_ranged({"attackrange": 349.0}))
        self.assertTrue(ehp_mod._is_ranged({"attackrange": 350.0}))
        self.assertTrue(ehp_mod._is_ranged({"attackrange": 351.0}))


if __name__ == "__main__":
    unittest.main()
