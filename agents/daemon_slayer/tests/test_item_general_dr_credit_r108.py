"""Item-side GENERAL %DR ("Blessing" / "Safeguard") credit to ALL THREE EHP
denominators (R108, ENGINE 1.201.0).

RED-first coverage for the NEW default-OFF ``assume_item_general_dr`` seam on
``compute_ehp``. Today an item's UNTARGETED "reduce all incoming champion damage
by X%" passive earns ZERO EHP: the engine folds only the item's flat stats
(HP/AP/mana/AH). Celestial Opposition 3869 "Blessing of the Mountain" (35% melee
/ 25% ranged, Meraki 16.13.1) and Crown of the Shattered Queen 664644 "Safeguard"
(40%, DDragon items.json 16.13.1) reduce ALL incoming champion damage - physical,
magical AND TRUE - but earn nothing. A live probe (Braum L13 + Celestial vs the
same build without it) confirmed the ONLY stat delta is the item's +200 flat HP
and true_ehp rose by EXACTLY that +200 (pure HP through the true denominator), so
the 25-35% general DR is absent from every EHP denominator.

This is a genuinely NEW axis - an ITEM-keyed UNTARGETED all-damage-type %DR -
distinct from the champion-only R35 percent-mitigation (``mit_phys/mag/true``,
champion_id-keyed so an item can never match it) AND from the three item-keyed DR
lanes that are all damage-TYPE-specific and PHYSICAL-ONLY: R77 crit-DR
(``item_crit_dr_mult``), R80 basic-attack-DR (``item_aa_dr_mult``), R86 enemy-AS-
slow (``item_enemy_as_slow_mult``). The distinguishing evidence is TRUE damage:
because general DR reduces true damage too, the fold multiplies into the true
denominator - which no R77/R80/R86 fold touches.

Contract:
  * OFF (default) -> item_general_dr_mult == 1.0 -> physical/magical/true/blended/
    cc_blended/sustain EHP BYTE-IDENTICAL to the pre-seam value (and an explicit
    ``False`` run).
  * ON + a carrier -> item_general_dr_mult == 1 - max_dr * _GENERAL_DR_UPTIME
    (MAX over the equipped registered items, resolved by wielder range), and
    physical/magical/TRUE/blended EHP all STRICTLY RISE.
  * AMORTIZED-MIDPOINT (uptime-gated), NOT EXACT - the DR magnitude is
    deterministic but uptime is conditional (linger-after-hit then long CD).
  * A non-carrier build with the flag ON does NOT leak credit (mult 1.0,
    byte-identical) and never aliases the champion mit_* percent-DR value.
"""
from __future__ import annotations

import math
import unittest

from agents.daemon_slayer._item_general_dr import (
    _GENERAL_DR_UPTIME,
    _ITEM_GENERAL_DR,
    item_general_dr_multiplier,
)
from agents.daemon_slayer.ehp import compute_ehp
from agents.daemon_slayer.data_loader import DataSnapshot

_SNAP: DataSnapshot | None = None


def _snap() -> DataSnapshot:
    global _SNAP
    if _SNAP is None:
        _SNAP = DataSnapshot.load()
    return _SNAP


def _mult(dr: float) -> float:
    return 1.0 - dr * _GENERAL_DR_UPTIME


# ---------------- registry unit ----------------


class ItemGeneralDrRegistryTests(unittest.TestCase):
    def test_off_is_identity(self) -> None:
        self.assertEqual(
            item_general_dr_multiplier(["3869"], True, assume_item_general_dr=False),
            1.0,
        )

    def test_celestial_melee_uses_35(self) -> None:
        self.assertAlmostEqual(
            item_general_dr_multiplier(["3869"], True, assume_item_general_dr=True),
            _mult(0.35), places=9,
        )

    def test_celestial_ranged_uses_25(self) -> None:
        self.assertAlmostEqual(
            item_general_dr_multiplier(["3869"], False, assume_item_general_dr=True),
            _mult(0.25), places=9,
        )

    def test_crown_sr_is_40_range_agnostic(self) -> None:
        self.assertAlmostEqual(
            item_general_dr_multiplier(["664644"], True, assume_item_general_dr=True),
            _mult(0.40), places=9,
        )
        self.assertAlmostEqual(
            item_general_dr_multiplier(["664644"], False, assume_item_general_dr=True),
            _mult(0.40), places=9,
        )

    def test_two_carriers_take_the_max_not_the_product(self) -> None:
        # UNIQUE "reduce incoming damage" effects over a shared pool -> the STRONGEST
        # applies, never the product (a synthetic Celestial + Crown build cannot
        # double-count). Melee: max(0.35, 0.40) = 0.40.
        self.assertAlmostEqual(
            item_general_dr_multiplier(["3869", "664644"], True, assume_item_general_dr=True),
            _mult(0.40), places=9,
        )

    def test_unknown_item_is_identity(self) -> None:
        self.assertEqual(
            item_general_dr_multiplier(["9999"], True, assume_item_general_dr=True), 1.0
        )

    def test_empty_build_is_identity(self) -> None:
        self.assertEqual(
            item_general_dr_multiplier([], True, assume_item_general_dr=True), 1.0
        )

    def test_registered_ids_are_exactly_the_two_sr(self) -> None:
        self.assertEqual(set(_ITEM_GENERAL_DR), {"3869", "664644"})

    def test_mult_is_below_one_when_armed(self) -> None:
        self.assertLess(
            item_general_dr_multiplier(["3869"], True, assume_item_general_dr=True), 1.0
        )


# ---------------- OFF byte-identical ----------------


class ItemGeneralDrOffByteIdenticalTests(unittest.TestCase):
    def _ehp(self, *, on, champ="Braum", items=("3869", "3082"), level=13):
        return compute_ehp(
            _snap(), champion_id=champ, level=level, item_ids=list(items),
            mode="SR", assume_item_general_dr=on,
        )

    def test_flag_absent_equals_explicit_false(self) -> None:
        absent = compute_ehp(
            _snap(), champion_id="Braum", level=13,
            item_ids=["3869", "3082"], mode="SR",
        )
        off = self._ehp(on=False)
        for field in (
            "physical_ehp", "magical_ehp", "true_ehp", "blended_ehp",
            "cc_blended_ehp", "effective_ehp_with_sustain",
        ):
            self.assertAlmostEqual(
                getattr(absent, field), getattr(off, field), places=9, msg=field
            )

    def test_off_mult_is_identity(self) -> None:
        self.assertEqual(self._ehp(on=False).item_general_dr_mult, 1.0)


# ---------------- ON credit (ALL THREE denominators incl TRUE) ----------------


class ItemGeneralDrOnCreditTests(unittest.TestCase):
    def _ehp(self, *, on, champ="Braum", items=("3869", "3082"), level=13):
        return compute_ehp(
            _snap(), champion_id=champ, level=level, item_ids=list(items),
            mode="SR", assume_item_general_dr=on,
        )

    def test_on_mult_equals_max_dr_uptime(self) -> None:
        # Braum is melee -> Celestial 35%.
        on = self._ehp(on=True)
        self.assertAlmostEqual(on.item_general_dr_mult, _mult(0.35), places=9)

    def test_true_ehp_strictly_rises(self) -> None:
        # THE distinguishing assertion: general DR reaches the TRUE denominator,
        # which R77 crit-DR / R80 AA-DR / R86 AS-slow (all physical-only) never do.
        off = self._ehp(on=False)
        on = self._ehp(on=True)
        self.assertGreater(on.true_ehp, off.true_ehp)

    def test_physical_and_magical_ehp_rise(self) -> None:
        off = self._ehp(on=False)
        on = self._ehp(on=True)
        self.assertGreater(on.physical_ehp, off.physical_ehp)
        self.assertGreater(on.magical_ehp, off.magical_ehp)
        self.assertGreater(on.blended_ehp, off.blended_ehp)

    def test_crown_sr_also_credits(self) -> None:
        on = compute_ehp(
            _snap(), champion_id="Syndra", level=13, item_ids=["664644"], mode="SR",
            assume_item_general_dr=True,
        )
        self.assertAlmostEqual(on.item_general_dr_mult, _mult(0.40), places=9)
        self.assertLess(on.item_general_dr_mult, 1.0)


# ---------------- melee vs ranged split ----------------


class ItemGeneralDrRangeSplitTests(unittest.TestCase):
    def test_melee_and_ranged_wielder_differ_for_celestial(self) -> None:
        melee = compute_ehp(
            _snap(), champion_id="Braum", level=13, item_ids=["3869"], mode="SR",
            assume_item_general_dr=True,
        )
        ranged = compute_ehp(
            _snap(), champion_id="Caitlyn", level=13, item_ids=["3869"], mode="SR",
            assume_item_general_dr=True,
        )
        self.assertAlmostEqual(melee.item_general_dr_mult, _mult(0.35), places=9)
        self.assertAlmostEqual(ranged.item_general_dr_mult, _mult(0.25), places=9)
        self.assertNotAlmostEqual(
            melee.item_general_dr_mult, ranged.item_general_dr_mult, places=6
        )


# ---------------- isolation (no leak) ----------------


class ItemGeneralDrIsolationTests(unittest.TestCase):
    def test_non_carrier_build_flag_on_is_byte_identical(self) -> None:
        # Sunfire (3068) + Thornmail (3075) carry no general-DR passive. Arming the
        # seam must not leak any DR: the mult stays 1.0 and every EHP is unchanged.
        off = compute_ehp(
            _snap(), champion_id="Garen", level=13, item_ids=["3068", "3075"],
            mode="SR",
        )
        on = compute_ehp(
            _snap(), champion_id="Garen", level=13, item_ids=["3068", "3075"],
            mode="SR", assume_item_general_dr=True,
        )
        self.assertEqual(on.item_general_dr_mult, 1.0)
        for field in ("physical_ehp", "magical_ehp", "true_ehp", "blended_ehp"):
            self.assertAlmostEqual(
                getattr(on, field), getattr(off, field), places=9, msg=field
            )

    def test_champion_mit_is_never_aliased(self) -> None:
        # The item-keyed seam is applied ALONGSIDE the champion percent-DR value,
        # never folded into it - passive_mitigation_* stays the pure champion value.
        on = compute_ehp(
            _snap(), champion_id="Braum", level=13, item_ids=["3869"], mode="SR",
            assume_item_general_dr=True,
        ).to_dict()
        self.assertEqual(on["passive_mitigation_phys"], 1.0)
        self.assertEqual(on["passive_mitigation_mag"], 1.0)
        self.assertEqual(on["passive_mitigation_true"], 1.0)


# ---------------- to_dict ----------------


class ItemGeneralDrToDictTests(unittest.TestCase):
    def test_to_dict_carries_field(self) -> None:
        r = compute_ehp(
            _snap(), champion_id="Braum", level=13, item_ids=["3869"], mode="SR",
            assume_item_general_dr=True,
        )
        d = r.to_dict()
        self.assertIn("item_general_dr_mult", d)
        self.assertTrue(math.isclose(d["item_general_dr_mult"], r.item_general_dr_mult))
        self.assertLess(d["item_general_dr_mult"], 1.0)


if __name__ == "__main__":
    unittest.main()
