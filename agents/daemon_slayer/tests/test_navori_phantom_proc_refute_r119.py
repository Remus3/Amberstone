"""R119 adversarial Meraki-vs-registry refute - Navori Flickerblade (6675).

Ground truth: data/daemon_slayer/16.13.1/items_meraki.json item 6675 lists a
SINGLE passive - Transcendence ("Basic attacks reduce the remaining cooldowns
of your basic abilities by 15%") - and zero on-hit damage. "Bring It Down" is
Kraken Slayer's (6672) proc alone.

The SR base 6675 entry phantom-credited a 120->168 physical every-3rd-attack
"Bring It Down" proc (a 6672-vs-6675 key-collision artifact). Its own Arena
mirror 226675 was already corrected to utility-only, and the 226672 comment
already documents "Navori 6675's passive is Transcendence CDR, it has no Bring
It Down proc". This guard pins the SR base entry to that same truth so the
phantom over-credit for crit-ability carries (Yasuo / Yone / Zeri / Xayah)
cannot regress.
"""

import unittest

from agents.daemon_slayer.effects import ITEM_EFFECTS


class NavoriPhantomProcRefuteR119Tests(unittest.TestCase):
    def test_navori_6675_has_no_periodic_proc(self) -> None:
        # Meraki 16.13.1: Transcendence only, no on-hit damage.
        self.assertEqual(ITEM_EFFECTS["6675"].periodics, ())

    def test_navori_6675_no_bring_it_down(self) -> None:
        names = {p.name for p in ITEM_EFFECTS["6675"].periodics}
        self.assertNotIn("Bring It Down", names)

    def test_navori_sr_and_arena_mirror_consistent(self) -> None:
        # 6675 (SR) and 226675 (Arena) are both utility-only (no DPS proc).
        self.assertEqual(ITEM_EFFECTS["6675"].periodics, ())
        self.assertEqual(ITEM_EFFECTS["226675"].periodics, ())

    def test_kraken_6672_still_has_bring_it_down(self) -> None:
        # Surgical guard: the legitimate proc on Kraken Slayer is untouched.
        names = {p.name for p in ITEM_EFFECTS["6672"].periodics}
        self.assertIn("Bring It Down", names)


if __name__ == "__main__":
    unittest.main()
