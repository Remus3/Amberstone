"""ENGINE 1.202.0 (2026-07-11): item Heal/Shield-Power (HSP) amp of the
CHAMPION-ABILITY heal/shield throughput fold in ``compute_hps``.

The item heal/shield throughput is already HSP-amped (``healing_hps =
healing_raw * amp_factor``), but the folded champion-ability throughput
(``ability_hps_total``, Soraka Q/W, Janna E, Lulu E, ...) was added RAW at the
grand-total line, so an enchanter's Ardent Censer / Staff of Flowing Water /
Redemption / Mikael HSP amplified her ITEM heals but NOT her ABILITY heals. In
League, HSP amplifies every heal/shield the wielder outputs, including abilities.

``apply_ability_hsp_amp`` defaults False -> the ability fold stays RAW ->
byte-identical to the pre-1.202.0 behavior. ON multiplies the ability fold by the
SAME ``amp_factor`` the item heals use (product convention, one wielder).
"""

import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.hps import compute_hps

# Heal-and-Shield-Power carriers: Ardent Censer / Staff of Flowing Water /
# Redemption / Moonstone / Mikael's Blessing (all carry heal_shield_amp_pct).
HSP_ITEMS = ["3504", "6620", "3107", "6616", "3222"]


class TestAbilityHspAmp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()

    def test_default_off_folds_ability_raw(self):
        """Default (flag omitted): ability_hps_total is added RAW (un-amped)."""
        r = compute_hps(self.snap, "Soraka", 13, item_ids=HSP_ITEMS, mode="SR")
        self.assertAlmostEqual(
            r.total_throughput,
            r.direct_throughput + r.ally_buff_credit + r.ability_hps_total,
            places=6,
        )
        self.assertEqual(r.ability_hps_amp_mult, 1.0)

    def test_explicit_off_equals_default(self):
        a = compute_hps(self.snap, "Soraka", 13, item_ids=HSP_ITEMS, mode="SR")
        b = compute_hps(
            self.snap, "Soraka", 13, item_ids=HSP_ITEMS, mode="SR",
            apply_ability_hsp_amp=False,
        )
        self.assertEqual(a.to_dict(), b.to_dict())

    def test_on_amps_ability_by_amp_factor(self):
        off = compute_hps(self.snap, "Soraka", 13, item_ids=HSP_ITEMS, mode="SR")
        on = compute_hps(
            self.snap, "Soraka", 13, item_ids=HSP_ITEMS, mode="SR",
            apply_ability_hsp_amp=True,
        )
        # Preconditions: HSP present + real ability heals to amp.
        self.assertGreater(off.amp_multiplier, 1.0)
        self.assertGreater(off.ability_hps_total, 0.0)
        # ON: ability fold is amped by amp_multiplier (product convention).
        self.assertAlmostEqual(
            on.total_throughput,
            on.direct_throughput + on.ally_buff_credit
            + on.ability_hps_total * on.amp_multiplier,
            places=6,
        )
        self.assertAlmostEqual(on.ability_hps_amp_mult, on.amp_multiplier, places=9)
        # ON exceeds OFF by exactly ability_hps_total * (amp - 1).
        self.assertAlmostEqual(
            on.total_throughput - off.total_throughput,
            off.ability_hps_total * (off.amp_multiplier - 1.0),
            places=6,
        )
        self.assertGreater(on.total_throughput, off.total_throughput)
        # The pre-amp ability_hps_total field itself stays pre-amp for transparency.
        self.assertAlmostEqual(on.ability_hps_total, off.ability_hps_total, places=9)

    def test_on_without_hsp_item_is_byte_identical(self):
        """ON but no HSP item (amp_factor == 1.0) -> byte-identical to OFF."""
        off = compute_hps(self.snap, "Soraka", 13, item_ids=["3157"], mode="SR")
        on = compute_hps(
            self.snap, "Soraka", 13, item_ids=["3157"], mode="SR",
            apply_ability_hsp_amp=True,
        )
        self.assertEqual(off.to_dict(), on.to_dict())
        self.assertEqual(on.ability_hps_amp_mult, 1.0)

    def test_on_without_ability_heal_champ_no_total_move(self):
        """A champ with no ability heal/shield blocks -> total unchanged by ON."""
        off = compute_hps(self.snap, "Zed", 13, item_ids=HSP_ITEMS, mode="SR")
        on = compute_hps(
            self.snap, "Zed", 13, item_ids=HSP_ITEMS, mode="SR",
            apply_ability_hsp_amp=True,
        )
        self.assertEqual(off.ability_hps_total, 0.0)
        self.assertAlmostEqual(off.total_throughput, on.total_throughput, places=9)

    def test_engine_version_bumped(self):
        self.assertEqual(ENGINE_VERSION, "1.233.0")


if __name__ == "__main__":
    unittest.main()
