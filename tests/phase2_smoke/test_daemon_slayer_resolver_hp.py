"""
tests/phase2_smoke/test_daemon_slayer_resolver_hp.py
Phase 4 batch 19 wire-in (s73) — bonus_hp_for_id / total_bonus_hp.

Pins the lazy-loaded HP table built from DDragon items.json. Uses the
real patch-current snapshot — the resolver's job IS to read it, so the
test surface is "given live DDragon, do the lookups produce the
documented numbers". HP values can drift on patch bumps; assertions
key on items whose HP has been stable for many patches (LDR=0,
Riftmaker=350, Heartsteel=900 SR / 700 ARENA).
"""
import sys
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from core import daemon_slayer_resolver as ds_res


class BonusHpForIdTests(unittest.TestCase):
    """Per-id HP lookup against the patch-current DDragon snapshot."""

    def test_unknown_id_returns_zero(self) -> None:
        # Defensive: no exception, no log noise blocking — caller treats
        # 0 as "no signal" same as a missing item.
        self.assertEqual(ds_res.bonus_hp_for_id("999999"), 0.0)

    def test_empty_string_returns_zero(self) -> None:
        self.assertEqual(ds_res.bonus_hp_for_id(""), 0.0)

    def test_ldr_has_no_hp(self) -> None:
        # LDR (3036) is a pure crit/AD/pen item — no HP component.
        # Pinning this verifies the lookup distinguishes "0 HP" from
        # "unknown id" cleanly.
        self.assertEqual(ds_res.bonus_hp_for_id("3036"), 0.0)

    def test_heartsteel_900_hp_sr(self) -> None:
        # SR Heartsteel (3084): 900 HP. Pinned across many patches.
        self.assertAlmostEqual(ds_res.bonus_hp_for_id("3084"), 900.0, places=1)

    def test_heartsteel_arena_alias_700_hp(self) -> None:
        # Arena Heartsteel (223084) carries a different HP roll. Pin
        # this so future patch refreshes catch unexpected DDragon
        # rebalances.
        self.assertAlmostEqual(ds_res.bonus_hp_for_id("223084"), 700.0, places=1)

    def test_riftmaker_350_hp(self) -> None:
        self.assertAlmostEqual(ds_res.bonus_hp_for_id("4633"), 350.0, places=1)


class TotalBonusHpTests(unittest.TestCase):
    """Aggregator behavior."""

    def test_empty_iterable_returns_zero(self) -> None:
        self.assertEqual(ds_res.total_bonus_hp([]), 0)
        self.assertEqual(ds_res.total_bonus_hp(()), 0)
        # Defensive against None.
        self.assertEqual(ds_res.total_bonus_hp(None), 0)

    def test_sums_across_known_ids(self) -> None:
        # Heartsteel (900) + Riftmaker (350) + Sunfire (350) = 1600.
        result = ds_res.total_bonus_hp(["3084", "4633", "3068"])
        self.assertAlmostEqual(result, 1600.0, places=1)

    def test_unknown_ids_silently_skipped(self) -> None:
        # Mix known + unknown: known contribution preserved, unknown 0.
        result = ds_res.total_bonus_hp(["3084", "999999", "4633"])
        self.assertAlmostEqual(result, 1250.0, places=1)

    def test_pen_only_items_contribute_zero(self) -> None:
        # LDR + Mortal Reminder are pen items with no HP. Result must
        # be 0 across the build.
        self.assertEqual(ds_res.total_bonus_hp(["3036", "3033"]), 0.0)


if __name__ == "__main__":
    unittest.main()
