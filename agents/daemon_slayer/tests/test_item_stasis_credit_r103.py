"""Item cast-triggered STASIS credit to the EHP numerator (Zhonya 3157 / Seeker 2420).

RED-first coverage for the NEW default-OFF ``assume_item_stasis`` seam on
``compute_ehp``. Today the item stasis actives earn ZERO EHP: the
``_passive_survival_window_overrides.py`` registry is champion-keyed (keyed by
``(champion_id, ability_key, form_index)``), so an ITEM can never match its
``survival_window_multiplier`` - the exact structural gap the ``_item_revive``
registry fills for the champion revive. Zhonya's Hourglass (3157) / Seeker's
Armguard (2420) / Wooglet's Witchcap (228002) grant a 2.5s Time Stop / Stasis
that renders the wielder untargetable + invulnerable (an all-damage void), which
- like the champion survival window - is an EHP-NUMERATOR avoided-fight fraction.

This module is the item-side lane of that champion survival window: a NEW
``_item_survival_window`` registry (item_id -> window_s = 2.5, mirroring
``_item_revive``) plus a default-OFF ``assume_item_stasis`` seam that folds the
summed item stasis window into ``common_revive``.

Contract:
  * OFF (default) -> ``item_stasis_mult`` collapses to 1.0 -> blended_ehp is
    BYTE-IDENTICAL to the pre-seam value (and to an explicit ``False`` run).
  * ON -> blended_ehp STRICTLY RISES for a stasis build by exactly the amortized
    avoided-fight fraction ``min(2.5/6.0, 1.0) * 0.35``; this credit RAISES the
    primary EHP number (a numerator term, NOT a sustain-only credit like omnivamp).
  * The credit is a fraction-of-fight avoided (NO resist curve, NO HP pool), so it
    composes multiplicatively with any champion survival window / revive.
  * A non-stasis build (Bloodthirster 3072) with the flag ON does NOT leak credit.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import compute_ehp
from agents.daemon_slayer._item_survival_window import (
    _ITEM_SURVIVAL_WINDOW,
    _ITEM_STASIS_PROB,
    item_survival_window_fraction,
)

# The reference fight window (ehp._FIGHT_WINDOW_S) the seam passes in.
_FW = 6.0
# The exact per-item amortized avoided-fight fraction for a 2.5s window.
_UNIT = min(2.5 / _FW, 1.0) * 0.35


class _SnapBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()


# ---------------- registry unit ----------------


class ItemStasisRegistryTests(unittest.TestCase):
    def test_zhonya_fraction_formula(self) -> None:
        # Summed additive numerator fraction = min(window_s/fw, 1.0) *
        # _ITEM_STASIS_PROB for the 2.5s window.
        self.assertAlmostEqual(
            item_survival_window_fraction(["3157"], fight_window_s=_FW),
            min(2.5 / _FW, 1.0) * 0.35,
            places=9,
        )

    def test_seeker_same_nominal(self) -> None:
        self.assertAlmostEqual(
            item_survival_window_fraction(["2420"], fight_window_s=_FW),
            min(2.5 / _FW, 1.0) * 0.35,
            places=9,
        )

    def test_wooglet_same_nominal(self) -> None:
        self.assertAlmostEqual(
            item_survival_window_fraction(["228002"], fight_window_s=_FW),
            min(2.5 / _FW, 1.0) * 0.35,
            places=9,
        )

    def test_arena_mirror_same_nominal(self) -> None:
        self.assertAlmostEqual(
            item_survival_window_fraction(["223157"], fight_window_s=_FW),
            min(2.5 / _FW, 1.0) * 0.35,
            places=9,
        )

    def test_unknown_item_id_yields_zero(self) -> None:
        self.assertEqual(
            item_survival_window_fraction(["9999"], fight_window_s=_FW), 0.0
        )

    def test_empty_build_yields_zero(self) -> None:
        self.assertEqual(item_survival_window_fraction([], fight_window_s=_FW), 0.0)

    def test_non_positive_fight_window_falls_back_to_reference(self) -> None:
        # fw <= 0 guard -> default 6.0; ["3157"] then yields the same unit fraction.
        self.assertAlmostEqual(
            item_survival_window_fraction(["3157"], fight_window_s=0.0),
            min(2.5 / 6.0, 1.0) * 0.35,
            places=9,
        )

    def test_registered_windows_are_all_2p5(self) -> None:
        for iid in ("3157", "223157", "2420", "228002"):
            self.assertAlmostEqual(_ITEM_SURVIVAL_WINDOW[iid], 2.5, places=9)

    def test_prob_midpoint_is_the_ult_midpoint(self) -> None:
        self.assertAlmostEqual(_ITEM_STASIS_PROB, 0.35, places=9)

    def test_dropped_mirror_ids_not_registered(self) -> None:
        # 323157 (Zhonya ARAM), 222420 / 322420 (Seeker Arena/ARAM) are NOT in the
        # DS item index -> intentionally dropped.
        self.assertNotIn("323157", _ITEM_SURVIVAL_WINDOW)
        self.assertNotIn("222420", _ITEM_SURVIVAL_WINDOW)
        self.assertNotIn("322420", _ITEM_SURVIVAL_WINDOW)


# ---------------- OFF byte-identical ----------------


class StasisOffByteIdenticalTests(_SnapBase):
    def test_flag_absent_equals_explicit_false(self) -> None:
        absent = compute_ehp(self.snap, "Lux", level=13, item_ids=["3157"])
        explicit_off = compute_ehp(
            self.snap, "Lux", level=13, item_ids=["3157"], assume_item_stasis=False
        )
        self.assertEqual(absent.blended_ehp, explicit_off.blended_ehp)

    def test_off_leaves_all_per_type_ehp_identical(self) -> None:
        # A champion with NO champion survival window (Lux) - the only credit that
        # could move is the item seam, and OFF it must not.
        absent = compute_ehp(self.snap, "Lux", level=13, item_ids=["3157"])
        explicit_off = compute_ehp(
            self.snap, "Lux", level=13, item_ids=["3157"], assume_item_stasis=False
        )
        self.assertEqual(absent.physical_ehp, explicit_off.physical_ehp)
        self.assertEqual(absent.magical_ehp, explicit_off.magical_ehp)
        self.assertEqual(absent.true_ehp, explicit_off.true_ehp)


# ---------------- ON credit (EHP numerator) ----------------


class StasisOnCreditTests(_SnapBase):
    def _pair(self, champ: str = "Lux", items=("3157",)):
        off = compute_ehp(self.snap, champ, level=13, item_ids=list(items))
        on = compute_ehp(
            self.snap, champ, level=13, item_ids=list(items), assume_item_stasis=True
        )
        return off, on

    def test_on_strictly_raises_blended_ehp(self) -> None:
        off, on = self._pair()
        self.assertGreater(on.blended_ehp, off.blended_ehp)

    def test_on_ratio_matches_fraction_formula(self) -> None:
        # The item stasis folds uniformly into common_revive, so blended scales by
        # exactly (1 + fraction).
        off, on = self._pair()
        expected = 1.0 + item_survival_window_fraction(["3157"], fight_window_s=_FW)
        self.assertAlmostEqual(on.blended_ehp / off.blended_ehp, expected, places=6)

    def test_on_rise_is_within_the_prob_capped_bound(self) -> None:
        off, on = self._pair()
        rise = on.blended_ehp / off.blended_ehp - 1.0
        self.assertGreater(rise, 0.0)
        self.assertLessEqual(rise, _UNIT + 1e-9)


# ---------------- multiplicative compose (champion window independent) ----------------


class StasisMultiplicativeComposeTests(_SnapBase):
    def test_champion_with_survival_window_composes_cleanly(self) -> None:
        # Lissandra HAS a champion survival window (R self-stasis), but we DO NOT
        # toggle apply_survival_window here - only assume_item_stasis. So the
        # champion window is identical on both sides and the on/off ratio isolates
        # the item fraction exactly (proves multiplicative composition).
        off = compute_ehp(self.snap, "Lissandra", level=13, item_ids=["3157"])
        on = compute_ehp(
            self.snap, "Lissandra", level=13, item_ids=["3157"], assume_item_stasis=True
        )
        expected = 1.0 + item_survival_window_fraction(["3157"], fight_window_s=_FW)
        self.assertAlmostEqual(on.blended_ehp / off.blended_ehp, expected, places=6)


# ---------------- isolation (no leak) ----------------


class StasisIsolationTests(_SnapBase):
    def test_non_stasis_build_with_flag_on_is_byte_identical(self) -> None:
        # Bloodthirster (3072) is not in the stasis registry; arming the seam must
        # not leak any stasis credit onto it.
        off = compute_ehp(self.snap, "Aatrox", level=13, item_ids=["3072"])
        on = compute_ehp(
            self.snap, "Aatrox", level=13, item_ids=["3072"], assume_item_stasis=True
        )
        self.assertEqual(on.blended_ehp, off.blended_ehp)


if __name__ == "__main__":
    unittest.main()
