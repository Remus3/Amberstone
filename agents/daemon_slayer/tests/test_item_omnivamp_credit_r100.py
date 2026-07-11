"""Item-passive OMNIVAMP credit to the EHP sustain axis (Riftmaker 4633).

RED-first coverage for the NEW default-OFF ``assume_max_stacks_omnivamp`` seam
on ``compute_ehp``. Today omnivamp scores ZERO because nothing feeds
``stats["omnivamp"]`` (stats.py maps lifesteal + spellvamp but not omnivamp).
Riftmaker's Void Corruption grants 10% melee / 6% ranged omnivamp AT MAXIMUM
Void Corruption stacks (Meraki items_meraki.json:44481 ``{{rd|10%|6%}}``),
credited best-case, mirroring the same full-ramp convention Riftmaker already
uses for ``damage_amp_pct=0.08``.

Contract:
  * OFF (default) -> stats["omnivamp"] stays absent -> heal_omnivamp == 0.0 and
    effective_ehp_with_sustain == blended_ehp (BYTE-IDENTICAL to pre-seam).
  * ON -> the build's summed omnivamp FRACTION is injected so heal_omnivamp > 0
    and sustain_ehp_delta > 0, WITHOUT moving blended_ehp (credit lands on the
    SUSTAIN axis only, same posture as lifesteal / spellvamp).
  * Melee 10% vs ranged 6% split resolves per champion attackrange.
  * A non-omnivamp build (Bloodthirster 3072) with the flag ON does NOT leak
    any omnivamp credit.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import compute_ehp
from agents.daemon_slayer._item_omnivamp import (
    _ITEM_OMNIVAMP,
    item_omnivamp_fraction,
)


class _SnapBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()


# ---------------- registry unit ----------------


class ItemOmnivampRegistryTests(unittest.TestCase):
    def test_riftmaker_melee_fraction_is_ten_percent(self) -> None:
        self.assertAlmostEqual(
            item_omnivamp_fraction(["4633"], is_ranged=False), 0.10, places=9
        )

    def test_riftmaker_ranged_fraction_is_six_percent(self) -> None:
        self.assertAlmostEqual(
            item_omnivamp_fraction(["4633"], is_ranged=True), 0.06, places=9
        )

    def test_ranged_branch_is_strictly_less_than_melee(self) -> None:
        self.assertLess(
            item_omnivamp_fraction(["4633"], is_ranged=True),
            item_omnivamp_fraction(["4633"], is_ranged=False),
        )

    def test_arena_mirror_carries_the_base_nominal(self) -> None:
        # 224633 exists in the DS item index (items.json:9980) - the Arena
        # mode-mirror of Riftmaker; it carries the base nominal.
        self.assertAlmostEqual(
            item_omnivamp_fraction(["224633"], is_ranged=False), 0.10, places=9
        )

    def test_unknown_item_id_yields_zero(self) -> None:
        self.assertEqual(item_omnivamp_fraction(["9999"], is_ranged=False), 0.0)
        self.assertEqual(item_omnivamp_fraction(["3072"], is_ranged=True), 0.0)

    def test_empty_build_yields_zero(self) -> None:
        self.assertEqual(item_omnivamp_fraction([], is_ranged=False), 0.0)

    def test_aram_mirror_id_is_not_registered(self) -> None:
        # 324633 is NOT in the DS item index -> intentionally dropped.
        self.assertNotIn("324633", _ITEM_OMNIVAMP)


# ---------------- OFF byte-identical ----------------


class OmnivampOffByteIdenticalTests(_SnapBase):
    def test_off_leaves_omnivamp_absent_and_heal_zero(self) -> None:
        e = compute_ehp(self.snap, "Mordekaiser", level=13, item_ids=["4633"])
        self.assertEqual(e.heal_omnivamp, 0.0)
        self.assertEqual(e.stats.get("omnivamp", 0.0), 0.0)

    def test_off_effective_equals_blended(self) -> None:
        # Mordekaiser + Riftmaker carries no lifesteal / spellvamp, so with the
        # omnivamp seam OFF the sustain-inclusive term collapses onto blended_ehp.
        e = compute_ehp(self.snap, "Mordekaiser", level=13, item_ids=["4633"])
        self.assertAlmostEqual(
            e.effective_ehp_with_sustain, e.blended_ehp, places=6
        )


# ---------------- ON credits (sustain axis only) ----------------


class OmnivampOnCreditsSustainTests(_SnapBase):
    def _pair(self):
        off = compute_ehp(self.snap, "Mordekaiser", level=13, item_ids=["4633"])
        on = compute_ehp(
            self.snap,
            "Mordekaiser",
            level=13,
            item_ids=["4633"],
            assume_max_stacks_omnivamp=True,
        )
        return off, on

    def test_on_credits_a_positive_omnivamp_heal(self) -> None:
        _, on = self._pair()
        self.assertGreater(on.heal_omnivamp, 0.0)

    def test_on_raises_the_sustain_delta(self) -> None:
        _, on = self._pair()
        self.assertGreater(on.sustain_ehp_delta, 0.0)

    def test_on_raises_effective_ehp_with_sustain(self) -> None:
        off, on = self._pair()
        self.assertGreater(
            on.effective_ehp_with_sustain, off.effective_ehp_with_sustain
        )

    def test_on_does_not_move_blended_ehp(self) -> None:
        # The credit MUST land only on the sustain axis - blended_ehp is the
        # primary EHP number and stays byte-identical to the OFF run.
        off, on = self._pair()
        self.assertEqual(on.blended_ehp, off.blended_ehp)

    def test_on_injects_the_melee_fraction_into_stats(self) -> None:
        _, on = self._pair()
        self.assertAlmostEqual(on.stats.get("omnivamp", 0.0), 0.10, places=9)


# ---------------- melee vs ranged split ----------------


class OmnivampMeleeRangedSplitTests(_SnapBase):
    def test_ranged_champ_credits_the_six_percent_branch(self) -> None:
        e = compute_ehp(
            self.snap,
            "Ezreal",
            level=13,
            item_ids=["4633"],
            assume_max_stacks_omnivamp=True,
        )
        self.assertGreater(e.heal_omnivamp, 0.0)
        self.assertAlmostEqual(e.stats.get("omnivamp", 0.0), 0.06, places=9)

    def test_ranged_injected_fraction_is_strictly_less_than_melee(self) -> None:
        ranged = compute_ehp(
            self.snap,
            "Ezreal",
            level=13,
            item_ids=["4633"],
            assume_max_stacks_omnivamp=True,
        )
        melee = compute_ehp(
            self.snap,
            "Mordekaiser",
            level=13,
            item_ids=["4633"],
            assume_max_stacks_omnivamp=True,
        )
        self.assertLess(
            ranged.stats.get("omnivamp", 0.0), melee.stats.get("omnivamp", 0.0)
        )


# ---------------- isolation (no leak) ----------------


class OmnivampIsolationTests(_SnapBase):
    def test_non_omnivamp_item_with_flag_on_yields_no_credit(self) -> None:
        # Bloodthirster (3072) grants lifesteal but no omnivamp; arming the seam
        # must not leak any omnivamp credit onto it.
        e = compute_ehp(
            self.snap,
            "Aatrox",
            level=13,
            item_ids=["3072"],
            assume_max_stacks_omnivamp=True,
        )
        self.assertEqual(e.heal_omnivamp, 0.0)
        self.assertEqual(e.stats.get("omnivamp", 0.0), 0.0)


if __name__ == "__main__":
    unittest.main()
