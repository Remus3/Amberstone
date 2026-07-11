"""Item death-triggered REVIVE credit to the EHP numerator (Guardian Angel 3026).

RED-first coverage for the NEW default-OFF ``assume_item_revive`` seam on
``compute_ehp``. Today Guardian Angel earns ZERO EHP: ``_effects_data.py`` marks
it ``defensive_only`` with a "no DPS contribution" note (no EHP field), and
``_passive_revive_overrides.py`` EXPLICITLY excludes item revives from the
champion revive registry (that registry is champion-keyed, so an item can never
match ``revive_multiplier``). GA's Rebirth revives the wielder for 50% of BASE
health after lethal damage (Meraki items_meraki.json:15505, 300s cooldown),
which - like the champion revive - is an EHP-NUMERATOR second life.

This module is the item-side lane of that champion revive: a NEW ``_item_revive``
registry (item_id -> revived fraction of BASE HP, mirroring ``_item_omnivamp``)
plus a default-OFF ``assume_item_revive`` seam that folds the summed item revive
into ``common_revive`` (through NORMAL resists - GA has no egg, unlike Anivia).

Contract:
  * OFF (default) -> ``item_revive_mult`` collapses to 1.0 -> blended_ehp is
    BYTE-IDENTICAL to the pre-seam value (and to an explicit ``False`` run).
  * ON -> blended_ehp STRICTLY RISES for a GA build by exactly the amortized
    base->max-converted fraction ``0.5 * (base_hp/total_hp) * 0.4``; this credit
    RAISES the primary EHP number (it is a numerator term, NOT a sustain-only
    credit like omnivamp).
  * The fraction is BASE-hp scaled, not max-hp: adding bonus HP dilutes the
    credit strictly below the ``0.5 * 0.4`` a max-hp revive would give.
  * A non-GA build (Bloodthirster 3072) with the flag ON does NOT leak credit.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import compute_ehp
from agents.daemon_slayer._item_revive import (
    _ITEM_REVIVE,
    _ITEM_REVIVE_PROB,
    item_revive_max_hp_fraction,
)


class _SnapBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()


# ---------------- registry unit ----------------


class ItemReviveRegistryTests(unittest.TestCase):
    def test_ga_base_fraction_formula(self) -> None:
        # Summed additive numerator fraction = base_frac * (base_hp/total_hp) *
        # _ITEM_REVIVE_PROB for a chosen base_hp < total_hp.
        base_hp, total_hp = 1000.0, 2000.0
        self.assertAlmostEqual(
            item_revive_max_hp_fraction(["3026"], base_hp=base_hp, total_hp=total_hp),
            0.50 * (base_hp / total_hp) * 0.4,
            places=9,
        )

    def test_arena_mirror_same_nominal(self) -> None:
        base_hp, total_hp = 1200.0, 3000.0
        self.assertAlmostEqual(
            item_revive_max_hp_fraction(["223026"], base_hp=base_hp, total_hp=total_hp),
            0.50 * (base_hp / total_hp) * 0.4,
            places=9,
        )

    def test_unknown_item_id_yields_zero(self) -> None:
        self.assertEqual(
            item_revive_max_hp_fraction(["9999"], base_hp=1000.0, total_hp=2000.0), 0.0
        )

    def test_empty_build_yields_zero(self) -> None:
        self.assertEqual(
            item_revive_max_hp_fraction([], base_hp=1000.0, total_hp=2000.0), 0.0
        )

    def test_total_hp_zero_guard(self) -> None:
        self.assertEqual(
            item_revive_max_hp_fraction(["3026"], base_hp=1000.0, total_hp=0.0), 0.0
        )

    def test_registered_fractions_are_half_base(self) -> None:
        self.assertAlmostEqual(_ITEM_REVIVE["3026"], 0.50, places=9)
        self.assertAlmostEqual(_ITEM_REVIVE["223026"], 0.50, places=9)

    def test_prob_midpoint_is_conservative(self) -> None:
        self.assertAlmostEqual(_ITEM_REVIVE_PROB, 0.4, places=9)

    def test_aram_mirror_id_is_not_registered(self) -> None:
        # 323026 is NOT in the DS item index -> intentionally dropped.
        self.assertNotIn("323026", _ITEM_REVIVE)


# ---------------- OFF byte-identical ----------------


class ReviveOffByteIdenticalTests(_SnapBase):
    def test_flag_absent_equals_explicit_false(self) -> None:
        absent = compute_ehp(self.snap, "Garen", level=13, item_ids=["3026"])
        explicit_off = compute_ehp(
            self.snap, "Garen", level=13, item_ids=["3026"], assume_item_revive=False
        )
        self.assertEqual(absent.blended_ehp, explicit_off.blended_ehp)

    def test_off_leaves_all_per_type_ehp_identical(self) -> None:
        absent = compute_ehp(self.snap, "Garen", level=13, item_ids=["3026"])
        explicit_off = compute_ehp(
            self.snap, "Garen", level=13, item_ids=["3026"], assume_item_revive=False
        )
        self.assertEqual(absent.physical_ehp, explicit_off.physical_ehp)
        self.assertEqual(absent.magical_ehp, explicit_off.magical_ehp)
        self.assertEqual(absent.true_ehp, explicit_off.true_ehp)


# ---------------- ON credit (EHP numerator) ----------------


class ReviveOnCreditTests(_SnapBase):
    def _pair(self, champ: str = "Garen", items=("3026",)):
        off = compute_ehp(self.snap, champ, level=13, item_ids=list(items))
        on = compute_ehp(
            self.snap, champ, level=13, item_ids=list(items), assume_item_revive=True
        )
        return off, on

    def test_on_strictly_raises_blended_ehp(self) -> None:
        off, on = self._pair()
        self.assertGreater(on.blended_ehp, off.blended_ehp)

    def test_on_ratio_matches_base_hp_formula(self) -> None:
        # The item revive folds uniformly into common_revive, so blended scales by
        # exactly (1 + fraction). base_hp = the champion's base HP at level (a
        # no-item run's total HP; GA grants no HP so it equals the engine's
        # base.get("hp")); total_hp = the GA build's max HP.
        off, on = self._pair()
        base_hp = compute_ehp(self.snap, "Garen", level=13, item_ids=[]).stats["hp"]
        total_hp = off.stats["hp"]
        expected = 1.0 + item_revive_max_hp_fraction(
            ["3026"], base_hp=base_hp, total_hp=total_hp
        )
        self.assertAlmostEqual(on.blended_ehp / off.blended_ehp, expected, places=6)

    def test_on_rise_is_within_the_prob_capped_bound(self) -> None:
        # For a GA-only build base_hp == total_hp (GA adds no HP) -> rise == the
        # 0.5*0.4 midpoint; assert a positive rise no greater than that bound.
        off, on = self._pair()
        rise = on.blended_ehp / off.blended_ehp - 1.0
        self.assertGreater(rise, 0.0)
        self.assertLessEqual(rise, 0.50 * 0.4 + 1e-9)


# ---------------- base-hp vs max-hp discriminator ----------------


class ReviveBaseVsMaxDiscriminatorTests(_SnapBase):
    def test_bonus_hp_dilutes_credit_below_max_based(self) -> None:
        # GA + Warmog (3083, +1000 HP): base_hp < total_hp, so a BASE-hp revive
        # credits a fraction STRICTLY below the 0.5*0.4 a MAX-hp revive would give.
        items = ["3026", "3083"]
        off = compute_ehp(self.snap, "Garen", level=13, item_ids=items)
        on = compute_ehp(
            self.snap, "Garen", level=13, item_ids=items, assume_item_revive=True
        )
        rise = on.blended_ehp / off.blended_ehp - 1.0
        self.assertGreater(rise, 0.0)
        self.assertLess(rise, 0.50 * 0.4)


# ---------------- isolation (no leak) ----------------


class ReviveIsolationTests(_SnapBase):
    def test_non_ga_build_with_flag_on_is_byte_identical(self) -> None:
        # Bloodthirster (3072) is not in the revive registry; arming the seam must
        # not leak any revive credit onto it.
        off = compute_ehp(self.snap, "Aatrox", level=13, item_ids=["3072"])
        on = compute_ehp(
            self.snap, "Aatrox", level=13, item_ids=["3072"], assume_item_revive=True
        )
        self.assertEqual(on.blended_ehp, off.blended_ehp)


if __name__ == "__main__":
    unittest.main()
