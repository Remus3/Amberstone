"""core.champion_info_overrides - curated DDragon info for zeroed champs.

DDragon serves an all-zero info block for Akshan/Rell/Seraphine/Vex and
attack=0 for the AD assassin Qiyana (verified upstream, not a local bug). The
overlay restores the correct AD/AP polarity, filling ONLY the fields DDragon
left zero so a future real value is respected.
"""
from __future__ import annotations

import unittest

from core import champion_info_overrides as cio


class MergedInfoTests(unittest.TestCase):
    def test_all_zero_champ_gets_full_override(self):
        # Seraphine (AP): 0/0 -> magic dominant.
        m = cio.merged_info("Seraphine", {"attack": 0, "magic": 0, "defense": 0})
        self.assertGreater(m["magic"], m["attack"], "Seraphine must read AP")

    def test_partial_zero_fills_missing_side_keeps_real(self):
        # Qiyana (AD assassin): DDragon attack=0, magic=4. Fill attack only;
        # keep the real magic=4. Result must lean AD (attack >= magic).
        m = cio.merged_info("Qiyana", {"attack": 0, "magic": 4, "defense": 2})
        self.assertEqual(m["magic"], 4, "real DDragon magic preserved")
        self.assertGreaterEqual(m["attack"], m["magic"], "Qiyana must read AD")

    def test_non_zero_ddragon_value_not_clobbered(self):
        # If DDragon later populates a real attack, the override must NOT win.
        m = cio.merged_info("Seraphine", {"attack": 5, "magic": 8})
        self.assertEqual(m["attack"], 5, "real DDragon attack preserved over override")

    def test_unlisted_champ_passthrough(self):
        raw = {"attack": 7, "magic": 6}
        self.assertEqual(cio.merged_info("Ezreal", raw), raw)

    def test_non_dict_raw_is_safe(self):
        self.assertEqual(cio.merged_info("Seraphine", None).get("magic"), 8)

    def test_does_not_mutate_input(self):
        raw = {"attack": 0, "magic": 0}
        cio.merged_info("Vex", raw)
        self.assertEqual(raw, {"attack": 0, "magic": 0}, "input dict untouched")

    def test_ad_overrides_lean_ad(self):
        for name in ("Akshan", "Qiyana"):
            m = cio.merged_info(name, {"attack": 0, "magic": 0})
            self.assertGreaterEqual(m["attack"], m["magic"], f"{name} must read AD")

    def test_ap_overrides_lean_ap(self):
        for name in ("Seraphine", "Rell", "Vex"):
            m = cio.merged_info(name, {"attack": 0, "magic": 0})
            self.assertGreater(m["magic"], m["attack"], f"{name} must read AP")


if __name__ == "__main__":
    unittest.main()
