"""Prismatic ALWAYS-ON percent-of-TOTAL resist self-amp credit (R124, ENGINE 1.212.0).

RED-first coverage for two current-patch (16.13.1 DDragon) prismatic item
passives whose ALWAYS-ON percent-of-total resist self-amplifier earns ZERO EHP
credit today - a delta==0 gap distinct from the R106 Jak'Sho / Force-of-Nature
RAMP entries already in ``_item_resist_grants``:

  * Shield of Molten Stone (Arena 443058 / SR-mirror 663058) "Immovable as the
    Earth": "Increase your armor by 20%, and gain Block Chance based on your
    Armor" (``items.json`` DDragon 16.13.1; Meraki-absent). A permanent +20% of
    TOTAL armor - always-on, no stacks / no ramp. The secondary armor-scaled
    Block Chance carries no DDragon magnitude and is NOT credited.
  * Cloak of Starry Night (Arena 443059 / SR-mirror 663059) "Limitless as the
    Stars": "Increase your Magic Resist by 20%. Reduce all damage you take from
    non-Basic Attack sources by a percentage, scaling with your Magic Resist up
    to a cap of 50%" (``items.json`` DDragon 16.13.1; Meraki-absent). A permanent
    +20% of TOTAL MR - always-on. The secondary MR-scaled non-AA damage reduction
    is a separate scaling axis with no flat magnitude and is NOT credited here.
    R133 correction: the quoted magnitudes are the map-30 443059 row only - the
    663059 mirror is retuned to HALF (10% MR, 25% DR cap), so the two rows carry
    DIFFERENT ``mr_pct`` values. Molten Stone's pair genuinely matches at 20%.

Both were ``defensive_only=True`` stubs in ``_effects_data`` (notes say "increases
total armor/MR by 20%") whose 20% never reached ``compute_ehp`` - ``build_champion``
folds only the items' FLAT static resists (Molten Stone +100/+80 armor, Starry
Night +100/+60 MR), NOT the +20% total self-amp. They join the EXISTING R106
``_item_resist_grants`` percent-of-total lane (``pct_base="total"``), but with
``conditional_probability=1.0`` (ALWAYS-ON, no ramp) - the first prob==1.0 entries,
decoupling from the 0.5 at-max-stacks ramp midpoint the Jak'Sho / FoN entries use.

Contract:
  * The registry function credits ``armor_pct``/``mr_pct`` of the RESOLVED TOTAL
    resist at prob 1.0 (EXACT, no amortization) for the registered prismatic ids.
  * Molten Stone -> armor only; Starry Night -> MR only.
  * A base + its mode mirror (443058 / 663058) share a ``family`` and are credited
    ONCE (mutually exclusive - the same item under two mode-mirror ids).
  * OFF (default ``apply_item_resist_grants``) -> BYTE-IDENTICAL, zero leak.
  * ON + Molten Stone -> only the physical (armor) EHP axis rises; magical + true
    stay byte-identical. The delta matches the resist-curve ratio the grant implies.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer._item_resist_grants import (
    _ITEM_RESIST_GRANTS,
    item_resist_grants,
)
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import compute_ehp

_SNAP: DataSnapshot | None = None


def _snap() -> DataSnapshot:
    global _SNAP
    if _SNAP is None:
        _SNAP = DataSnapshot.load()
    return _SNAP


# ---------------- registry unit (engine-free, exact always-on math) ----------------


class PrismaticResistRegistryTests(unittest.TestCase):
    _IDS = ("443058", "663058", "443059", "663059")

    def test_all_four_prismatic_ids_registered(self) -> None:
        for iid in self._IDS:
            self.assertIn(iid, _ITEM_RESIST_GRANTS, msg=iid)

    def test_prismatic_entries_are_always_on_prob_one(self) -> None:
        # Always-on innate +20% (no stacks / no ramp) -> prob 1.0, NOT the 0.5
        # at-max-stacks ramp midpoint the Jak'Sho / FoN entries carry.
        for iid in self._IDS:
            self.assertAlmostEqual(
                _ITEM_RESIST_GRANTS[iid].conditional_probability, 1.0, places=9,
                msg=iid,
            )

    def test_molten_stone_is_percent_of_total_armor_only(self) -> None:
        # +20% of TOTAL armor, exact (prob 1.0); no MR term.
        a, m = item_resist_grants(
            ["443058"], total_armor=200.0, total_mr=100.0,
            base_armor=30.0, base_mr=32.0,
        )
        self.assertAlmostEqual(a, 200.0 * 0.20, places=9)  # 40.0
        self.assertAlmostEqual(m, 0.0, places=9)

    def test_starry_night_is_percent_of_total_mr_only(self) -> None:
        # +20% of TOTAL MR, exact (prob 1.0); no armor term.
        a, m = item_resist_grants(
            ["443059"], total_armor=200.0, total_mr=100.0,
            base_armor=30.0, base_mr=32.0,
        )
        self.assertAlmostEqual(a, 0.0, places=9)
        self.assertAlmostEqual(m, 100.0 * 0.20, places=9)  # 20.0

    def test_mode_mirror_credits_same_as_arena_id(self) -> None:
        arena = item_resist_grants(
            ["443058"], total_armor=200.0, total_mr=100.0,
            base_armor=30.0, base_mr=32.0,
        )
        mirror = item_resist_grants(
            ["663058"], total_armor=200.0, total_mr=100.0,
            base_armor=30.0, base_mr=32.0,
        )
        self.assertEqual(arena, mirror)

    def test_family_dedup_arena_and_mirror_do_not_double(self) -> None:
        single = item_resist_grants(
            ["443058"], total_armor=200.0, total_mr=100.0,
            base_armor=30.0, base_mr=32.0,
        )
        both = item_resist_grants(
            ["443058", "663058"], total_armor=200.0, total_mr=100.0,
            base_armor=30.0, base_mr=32.0,
        )
        self.assertAlmostEqual(both[0], single[0], places=9)
        self.assertAlmostEqual(both[1], single[1], places=9)

    def test_molten_and_starry_are_distinct_families_and_sum(self) -> None:
        # Armor (Molten Stone) + MR (Starry Night) are different items -> sum.
        a, m = item_resist_grants(
            ["443058", "443059"], total_armor=200.0, total_mr=100.0,
            base_armor=30.0, base_mr=32.0,
        )
        self.assertAlmostEqual(a, 200.0 * 0.20, places=9)  # 40.0 armor
        self.assertAlmostEqual(m, 100.0 * 0.20, places=9)  # 20.0 MR


# ---------------- OFF byte-identical + ON credit (compute_ehp, SR-mirror id) ----------------


class PrismaticResistComputeEhpTests(unittest.TestCase):
    # The 663058 mirror carries the SR (maps.11) flag so it resolves in a
    # mode="SR" compute_ehp call (mirrors the R106 Ornn/SR harness).
    def _ehp(self, *, on, items, champ="Ornn", level=13):
        return compute_ehp(
            _snap(), champion_id=champ, level=level, item_ids=list(items),
            mode="SR", apply_item_resist_grants=on,
        )

    def test_off_is_byte_identical_and_zero(self) -> None:
        absent = compute_ehp(
            _snap(), champion_id="Ornn", level=13, item_ids=["663058"], mode="SR",
        )
        off = self._ehp(on=False, items=["663058"])
        self.assertEqual(off.item_resist_armor, 0.0)
        self.assertEqual(off.item_resist_mr, 0.0)
        for field in (
            "physical_ehp", "magical_ehp", "true_ehp", "blended_ehp",
            "cc_blended_ehp", "effective_ehp_with_sustain",
        ):
            self.assertAlmostEqual(
                getattr(absent, field), getattr(off, field), places=9, msg=field
            )

    def test_on_molten_stone_raises_only_the_physical_axis(self) -> None:
        off = self._ehp(on=False, items=["663058"])
        on = self._ehp(on=True, items=["663058"])
        self.assertGreater(on.physical_ehp, off.physical_ehp)
        self.assertAlmostEqual(on.magical_ehp, off.magical_ehp, places=9)
        self.assertAlmostEqual(on.true_ehp, off.true_ehp, places=9)
        self.assertGreater(on.item_resist_armor, 0.0)
        self.assertEqual(on.item_resist_mr, 0.0)

    def test_on_physical_delta_matches_registry_grant(self) -> None:
        # Computed-quantity assertion: the physical EHP ratio equals the armor
        # curve ratio the registry grant implies (no hardcoded magic number).
        from agents.daemon_slayer.ehp import _armor_factor
        off = self._ehp(on=False, items=["663058"])
        on = self._ehp(on=True, items=["663058"])
        granted = on.item_resist_armor
        self.assertGreater(granted, 0.0)
        expected_ratio = _armor_factor(off.armor) / _armor_factor(off.armor + granted)
        self.assertAlmostEqual(
            on.physical_ehp / off.physical_ehp, expected_ratio, places=6
        )


if __name__ == "__main__":
    unittest.main()
