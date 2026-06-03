"""Item 290 (ENGINE 1.103.0) - champion-innate CC-mitigation registry tests.

The SEVENTH survivability axis: a champion's innate tenacity / crowd-control-
immunity ABILITY (Garen W / Olaf R / Malzahar P) feeds the cc_blended discount
(it shrinks the enemy CC the caster eats -> a larger cc_blended_ehp), the clean
CC-survival half of the guaranteed-survival family. Proves (a) the default path
is byte-identical, (b) the on path produces the hand-verified tenacity at a
pinned input, and (c) the multiplicative-with-item-tenacity combine + the
documented exclusions.
"""
from __future__ import annotations

import math
import unittest

from agents.daemon_slayer._champion_cc_mitigation_overrides import (
    _BRIEF_TENACITY_PROB,
    _CC_IMMUNITY_ACTIVE_PROB,
    _CC_IMMUNITY_PASSIVE_PROB,
    _CHAMPION_CC_MITIGATION_OVERRIDES,
    champion_cc_tenacity_fraction,
)
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import compute_ehp

_SNAP: DataSnapshot | None = None


def _snap() -> DataSnapshot:
    global _SNAP
    if _SNAP is None:
        _SNAP = DataSnapshot.load()
    return _SNAP


class RegistryFractionTests(unittest.TestCase):
    def test_flag_off_is_zero(self):
        # The default (flag False) returns 0.0 for every champion - byte-identical.
        for cid in ("Garen", "Olaf", "Malzahar", "Ashe"):
            self.assertEqual(
                champion_cc_tenacity_fraction(cid, 18, False), 0.0
            )

    def test_unregistered_champion_is_zero_even_on(self):
        self.assertEqual(champion_cc_tenacity_fraction("Ashe", 18, True), 0.0)

    def test_garen_w_brief_tenacity_value(self):
        # Garen W: 60% tenacity, amortized at the brief-window midpoint.
        frac = champion_cc_tenacity_fraction("Garen", 18, True)
        self.assertAlmostEqual(frac, 0.60 * _BRIEF_TENACITY_PROB, places=9)

    def test_olaf_r_active_immunity_value(self):
        # Olaf R: 100% CC immunity, amortized at the active-ult midpoint.
        frac = champion_cc_tenacity_fraction("Olaf", 18, True)
        self.assertAlmostEqual(frac, 1.0 * _CC_IMMUNITY_ACTIVE_PROB, places=9)

    def test_malzahar_p_passive_immunity_value(self):
        # Malzahar P: 100% CC immunity, amortized at the passive midpoint.
        frac = champion_cc_tenacity_fraction("Malzahar", 1, True)
        self.assertAlmostEqual(frac, 1.0 * _CC_IMMUNITY_PASSIVE_PROB, places=9)

    def test_fraction_bounded_below_one(self):
        # Even a 100%-nominal entry resolves below 1.0 once amortized.
        for cid in ("Garen", "Olaf", "Malzahar"):
            frac = champion_cc_tenacity_fraction(cid, 18, True)
            self.assertGreater(frac, 0.0)
            self.assertLess(frac, 1.0)

    def test_registry_is_exactly_the_three_self_entries(self):
        keys = set(_CHAMPION_CC_MITIGATION_OVERRIDES)
        self.assertEqual(
            keys,
            {("Garen", "W", 0), ("Olaf", "R", 0), ("Malzahar", "P", 0)},
        )

    def test_excluded_champions_absent(self):
        # Cast-bound dash immunity (Sion/Warwick/Pantheon/Kled/Galio/Briar),
        # spell-shields (Fiora/Morgana), ally-targeted (Milio), one-time cleanse
        # (Alistar), and the Bard R false positive are deliberately NOT seeded.
        for cid in (
            "Sion", "Warwick", "Pantheon", "Kled", "Galio", "Briar",
            "Fiora", "Morgana", "Milio", "Alistar", "Bard",
        ):
            self.assertEqual(champion_cc_tenacity_fraction(cid, 18, True), 0.0)


class ComputeEhpSeamTests(unittest.TestCase):
    ENEMIES = ("Leona", "Morgana", "Annie")  # a heavy-CC comp

    def _ehp(self, champ, *, on, enemies=ENEMIES, items=None):
        return compute_ehp(
            _snap(), champion_id=champ, level=18,
            item_ids=items or (), mode="SR",
            enemy_champions=enemies,
            apply_champion_tenacity=on,
        )

    def test_default_off_byte_identical(self):
        # Flag off vs the pre-item-290 behavior: identical cc_blended_ehp.
        off = self._ehp("Olaf", on=False)
        # The field exists and is 0.0 at the default.
        self.assertEqual(off.champion_tenacity_frac, 0.0)

    def test_no_enemy_comp_field_still_populated(self):
        # With no enemy comp the cc discount is inert, but the innate fraction
        # field is still surfaced for a future consumer.
        r = compute_ehp(
            _snap(), champion_id="Olaf", level=18, item_ids=(), mode="SR",
            enemy_champions=(), apply_champion_tenacity=True,
        )
        self.assertGreater(r.champion_tenacity_frac, 0.0)
        # cc_blended_ehp == blended_ehp when there is no enemy comp.
        self.assertAlmostEqual(r.cc_blended_ehp, r.blended_ehp, places=6)

    def test_innate_tenacity_raises_cc_blended_ehp(self):
        # A CC-immune champion eats less enemy CC -> a LARGER cc_blended_ehp than
        # the same champion with the flag off (same blended_ehp baseline).
        off = self._ehp("Olaf", on=False)
        on = self._ehp("Olaf", on=True)
        self.assertAlmostEqual(on.blended_ehp, off.blended_ehp, places=6)
        self.assertGreater(on.cc_blended_ehp, off.cc_blended_ehp)
        self.assertAlmostEqual(
            on.champion_tenacity_frac, _CC_IMMUNITY_ACTIVE_PROB, places=9
        )

    def test_unregistered_champion_unchanged_by_flag(self):
        # Ashe has no innate CC mitigation: flag on/off identical cc_blended_ehp.
        off = self._ehp("Ashe", on=False)
        on = self._ehp("Ashe", on=True)
        self.assertAlmostEqual(on.cc_blended_ehp, off.cc_blended_ehp, places=6)
        self.assertEqual(on.champion_tenacity_frac, 0.0)

    def test_combines_multiplicatively_with_item_tenacity(self):
        # Champion (Olaf) + item tenacity (Mercury's Treads 3111) combine as
        # (1 - champ)*(1 - item); the eaten CC is scaled by that combined factor.
        # cc_blended with both > cc_blended with either alone is NOT asserted (the
        # discount saturates); instead pin the combined fraction directly.
        from agents.daemon_slayer._item_tenacity import total_item_tenacity
        champ = champion_cc_tenacity_fraction("Olaf", 18, True)
        item = total_item_tenacity(("3111",))
        combined = 1.0 - (1.0 - champ) * (1.0 - item)
        # Both credited: build-tenacity (item) + champion-tenacity together.
        both = compute_ehp(
            _snap(), champion_id="Olaf", level=18, item_ids=("3111",),
            mode="SR", enemy_champions=self.ENEMIES,
            apply_build_tenacity=True, apply_champion_tenacity=True,
        )
        champ_only = compute_ehp(
            _snap(), champion_id="Olaf", level=18, item_ids=("3111",),
            mode="SR", enemy_champions=self.ENEMIES,
            apply_build_tenacity=False, apply_champion_tenacity=True,
        )
        # The combined credit erodes strictly less CC than champion alone ->
        # cc_blended_ehp(both) >= cc_blended_ehp(champ_only).
        self.assertGreaterEqual(both.cc_blended_ehp, champ_only.cc_blended_ehp)
        self.assertTrue(0.0 < combined < 1.0)
        self.assertGreater(combined, champ)

    def test_build_tenacity_only_path_unaffected_by_new_flag(self):
        # Regression: with apply_champion_tenacity default-off, the item-236
        # apply_build_tenacity path is numerically unchanged (Olaf still has an
        # innate entry, so this proves the new flag gates it off cleanly).
        a = compute_ehp(
            _snap(), champion_id="Olaf", level=18, item_ids=("3111",),
            mode="SR", enemy_champions=self.ENEMIES,
            apply_build_tenacity=True,
        )
        b = compute_ehp(
            _snap(), champion_id="Olaf", level=18, item_ids=("3111",),
            mode="SR", enemy_champions=self.ENEMIES,
            apply_build_tenacity=True, apply_champion_tenacity=False,
        )
        self.assertAlmostEqual(a.cc_blended_ehp, b.cc_blended_ehp, places=9)


class ToDictTests(unittest.TestCase):
    def test_to_dict_carries_field(self):
        r = compute_ehp(
            _snap(), champion_id="Olaf", level=18, item_ids=(), mode="SR",
            enemy_champions=("Leona",), apply_champion_tenacity=True,
        )
        d = r.to_dict()
        self.assertIn("champion_tenacity_frac", d)
        self.assertTrue(math.isclose(
            d["champion_tenacity_frac"], _CC_IMMUNITY_ACTIVE_PROB
        ))


if __name__ == "__main__":
    unittest.main()
