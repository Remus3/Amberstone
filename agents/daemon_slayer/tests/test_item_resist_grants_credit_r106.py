"""Item-side conditional RESIST-GRANT credit to the EHP denominator (R106, ENGINE 1.199.0).

RED-first coverage for the NEW default-OFF ``apply_item_resist_grants`` seam on
``compute_ehp``. Today two current-patch (16.13.1 Meraki) item COMBAT passives that
RAMP to max stacks in combat earn ZERO EHP for their stacked bonus resists:

  * Jak'Sho, The Protean (6665 + Arena 226665) "Voidborn Resilience": gain a stack
    per second in combat with champions (max 5); at max, increase BONUS armor and
    BONUS magic resistance by 30% until the end of combat. A PERCENT-of-BONUS
    resist grant (the item-268 champion mode).
  * Force of Nature (4401 + Arena 224401) "Steadfast": taking magic damage from
    champions stacks (max 8); at max, gain 70 FLAT bonus magic resistance (MR only,
    no armor). A flat add (the item-264 champion mode).

The magnitudes quoted above are the SR BASE rows. R133 correction: the Arena
mirrors are RETUNED, not re-skins - 226665 grants 40% of bonus resist and 224401
grants 50 flat MR (via a differently shaped 10-stack Absorb / Dissipate passive).
Each row is pinned to its own DDragon tooltip in
``test_item_resist_mirror_magnitudes_r133.py``.

``build_champion`` folds only the items' FLAT static resists (Jak'Sho +45/+45, FoN
+55 MR), NOT the stacked ramp (live-probe R105 / LEDGER 850). The champion resist
registry ``_passive_resist_overrides.resist_grants`` is champion-keyed, so an ITEM
can never match it - the same structural gap ``_item_revive`` /
``_item_survival_window`` / ``_item_spell_shield_overrides`` / ``_item_mana_health``
fill for the other item-side survivability axes. This module is the item-side lane
of the FOURTH (resist-denominator) axis: a NEW ``_item_resist_grants`` registry plus
a default-OFF ``apply_item_resist_grants`` seam folding the amortized bonus resist
into ``eff_armor`` / ``eff_mr`` (the DENOMINATOR, next to the champion
``bonus_armor`` / ``bonus_mr``).

Contract:
  * OFF (default) -> ``item_resist_armor`` / ``item_resist_mr`` == 0.0 ->
    physical/magical/true/blended/cc_blended/sustain EHP BYTE-IDENTICAL to the
    pre-seam value (and to an explicit ``False`` run).
  * ON + a Force of Nature build -> only the MAGICAL axis rises (MR-only grant);
    physical + true EHP stay byte-identical.
  * ON + a Jak'Sho build -> BOTH physical and magical EHP rise (armor + MR grant).
  * The grant is CONDITIONAL (ramps to max stacks), so it is amortized by the
    at-max-stacks midpoint ``_ITEM_RESIST_STACK_PROB`` (0.5); the resist magnitude
    is EXACT Meraki, only the firing midpoint is the assumption.
  * A non-family build with the flag ON does NOT leak any resist.
"""
from __future__ import annotations

import math
import unittest

from agents.daemon_slayer._item_resist_grants import (
    _ITEM_RESIST_GRANTS,
    _ITEM_RESIST_STACK_PROB,
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


# ---------------- registry unit (engine-free, exact math) ----------------


class ItemResistRegistryTests(unittest.TestCase):
    def test_registered_ids_are_the_expected_set(self) -> None:
        # R106 ramping combat passives (Jak'Sho / FoN) + R124 prismatic always-on
        # percent-of-total self-amps (Molten Stone / Starry Night, base + mirror).
        self.assertEqual(
            set(_ITEM_RESIST_GRANTS),
            {
                "6665", "226665", "4401", "224401",
                "443058", "663058", "443059", "663059",
            },
        )

    def test_midpoint_is_half(self) -> None:
        self.assertAlmostEqual(_ITEM_RESIST_STACK_PROB, 0.5, places=9)

    def test_fon_is_flat_mr_only_amortized(self) -> None:
        # Steadfast +70 flat bonus MR at 8 stacks, MR ONLY, no armor.
        a, m = item_resist_grants(
            ["4401"], total_armor=100.0, total_mr=80.0,
            base_armor=30.0, base_mr=32.0,
        )
        self.assertAlmostEqual(a, 0.0, places=9)
        self.assertAlmostEqual(m, 70.0 * _ITEM_RESIST_STACK_PROB, places=9)  # 35.0

    def test_jaksho_is_percent_of_bonus_resist_amortized(self) -> None:
        # Voidborn +30% of BONUS armor + BONUS MR (bonus = total - base).
        total_armor, total_mr, base_armor, base_mr = 100.0, 80.0, 30.0, 32.0
        a, m = item_resist_grants(
            ["6665"], total_armor=total_armor, total_mr=total_mr,
            base_armor=base_armor, base_mr=base_mr,
        )
        bonus_armor = total_armor - base_armor  # 70
        bonus_mr = total_mr - base_mr  # 48
        self.assertAlmostEqual(
            a, bonus_armor * 0.30 * _ITEM_RESIST_STACK_PROB, places=9  # 10.5
        )
        self.assertAlmostEqual(
            m, bonus_mr * 0.30 * _ITEM_RESIST_STACK_PROB, places=9  # 7.2
        )

    def test_jaksho_negative_bonus_clamped_to_zero(self) -> None:
        # A champ whose total resist is below base per-level (never in practice)
        # must not yield a negative grant.
        a, m = item_resist_grants(
            ["6665"], total_armor=10.0, total_mr=10.0,
            base_armor=40.0, base_mr=40.0,
        )
        self.assertAlmostEqual(a, 0.0, places=9)
        self.assertAlmostEqual(m, 0.0, places=9)

    def test_family_dedup_base_and_arena_mirror_do_not_double(self) -> None:
        single = item_resist_grants(
            ["6665"], total_armor=100.0, total_mr=80.0,
            base_armor=30.0, base_mr=32.0,
        )
        both = item_resist_grants(
            ["6665", "226665"], total_armor=100.0, total_mr=80.0,
            base_armor=30.0, base_mr=32.0,
        )
        self.assertAlmostEqual(both[0], single[0], places=9)
        self.assertAlmostEqual(both[1], single[1], places=9)

    def test_distinct_families_sum(self) -> None:
        # Jak'Sho (percent) + FoN (flat MR) are DIFFERENT unique passives -> sum.
        ja, jm = item_resist_grants(
            ["6665"], total_armor=100.0, total_mr=80.0,
            base_armor=30.0, base_mr=32.0,
        )
        fa, fm = item_resist_grants(
            ["4401"], total_armor=100.0, total_mr=80.0,
            base_armor=30.0, base_mr=32.0,
        )
        ba, bm = item_resist_grants(
            ["6665", "4401"], total_armor=100.0, total_mr=80.0,
            base_armor=30.0, base_mr=32.0,
        )
        self.assertAlmostEqual(ba, ja + fa, places=9)
        self.assertAlmostEqual(bm, jm + fm, places=9)

    def test_unknown_and_empty_yield_zero(self) -> None:
        for ids in (["9999"], [], ["3075"]):
            a, m = item_resist_grants(
                ids, total_armor=100.0, total_mr=80.0,
                base_armor=30.0, base_mr=32.0,
            )
            self.assertEqual((a, m), (0.0, 0.0), msg=str(ids))

    def test_arena_mirrors_are_retuned_not_base_nominal_copies(self) -> None:
        # R133 correction. This assertion used to read `base == mirror`, which
        # baked the "base nominal" seeding defect into the suite: an Arena
        # mirror is a RETUNED item, not a re-skin of its base. Force of Nature
        # 224401 grants 50 flat MR at 10 stacks (base 4401: 70 at 8), and
        # Jak'Sho 226665 grants 40% of bonus resist (base 6665: 30%) in exchange
        # for lower flat statics. Exact magnitudes are pinned against each row's
        # OWN DDragon tooltip in test_item_resist_mirror_magnitudes_r133.py.
        resists = {
            "total_armor": 100.0, "total_mr": 80.0,
            "base_armor": 30.0, "base_mr": 32.0,
        }
        base_fon = item_resist_grants(["4401"], **resists)
        mirror_fon = item_resist_grants(["224401"], **resists)
        self.assertEqual(base_fon[0], mirror_fon[0])  # neither grants armor
        self.assertLess(mirror_fon[1], base_fon[1])  # 50 flat MR vs base 70

        base_jaksho = item_resist_grants(["6665"], **resists)
        mirror_jaksho = item_resist_grants(["226665"], **resists)
        self.assertGreater(mirror_jaksho[0], base_jaksho[0])  # 40% vs base 30%
        self.assertGreater(mirror_jaksho[1], base_jaksho[1])


# ---------------- OFF byte-identical ----------------


class ItemResistOffByteIdenticalTests(unittest.TestCase):
    def _ehp(self, *, on, items, champ="Ornn", level=13):
        return compute_ehp(
            _snap(), champion_id=champ, level=level, item_ids=list(items),
            mode="SR", apply_item_resist_grants=on,
        )

    def test_flag_absent_equals_explicit_false(self) -> None:
        absent = compute_ehp(
            _snap(), champion_id="Ornn", level=13, item_ids=["4401"], mode="SR",
        )
        off = self._ehp(on=False, items=["4401"])
        for field in (
            "physical_ehp", "magical_ehp", "true_ehp", "blended_ehp",
            "cc_blended_ehp", "effective_ehp_with_sustain",
        ):
            self.assertAlmostEqual(
                getattr(absent, field), getattr(off, field), places=9, msg=field
            )

    def test_off_fields_are_zero(self) -> None:
        off = self._ehp(on=False, items=["6665"])
        self.assertEqual(off.item_resist_armor, 0.0)
        self.assertEqual(off.item_resist_mr, 0.0)


# ---------------- ON credit (EHP denominator, axis-targeted) ----------------


class ItemResistOnCreditTests(unittest.TestCase):
    def _ehp(self, *, on, items, champ="Ornn", level=13):
        return compute_ehp(
            _snap(), champion_id=champ, level=level, item_ids=list(items),
            mode="SR", apply_item_resist_grants=on,
        )

    def test_fon_raises_only_the_magical_axis(self) -> None:
        off = self._ehp(on=False, items=["4401"])
        on = self._ehp(on=True, items=["4401"])
        # MR-only grant -> magical rises, physical + true byte-identical.
        self.assertGreater(on.magical_ehp, off.magical_ehp)
        self.assertAlmostEqual(on.physical_ehp, off.physical_ehp, places=9)
        self.assertAlmostEqual(on.true_ehp, off.true_ehp, places=9)
        self.assertGreater(on.item_resist_mr, 0.0)
        self.assertEqual(on.item_resist_armor, 0.0)

    def test_jaksho_raises_both_resisted_axes(self) -> None:
        off = self._ehp(on=False, items=["6665"])
        on = self._ehp(on=True, items=["6665"])
        # +30% of BONUS armor + MR -> both resisted axes rise; true unchanged.
        self.assertGreater(on.physical_ehp, off.physical_ehp)
        self.assertGreater(on.magical_ehp, off.magical_ehp)
        self.assertAlmostEqual(on.true_ehp, off.true_ehp, places=9)
        self.assertGreater(on.item_resist_armor, 0.0)
        self.assertGreater(on.item_resist_mr, 0.0)

    def test_fon_magical_delta_matches_registry_grant(self) -> None:
        # The magical EHP ratio equals the resist-curve ratio the registry grant
        # implies: _armor_factor(mr) / _armor_factor(mr + granted_mr). Uses the
        # engine's own resolved MR so this is a computed-quantity assertion, not a
        # hardcoded magic number.
        from agents.daemon_slayer.ehp import _armor_factor
        off = self._ehp(on=False, items=["4401"])
        on = self._ehp(on=True, items=["4401"])
        granted_mr = on.item_resist_mr
        self.assertGreater(granted_mr, 0.0)
        expected_ratio = _armor_factor(off.mr) / _armor_factor(off.mr + granted_mr)
        self.assertAlmostEqual(
            on.magical_ehp / off.magical_ehp, expected_ratio, places=6
        )


# ---------------- isolation (no leak) ----------------


class ItemResistIsolationTests(unittest.TestCase):
    def test_non_family_build_with_flag_on_is_byte_identical(self) -> None:
        # Thornmail (3075) is a pure-resist item with no ramping resist passive:
        # arming the seam must not leak any grant.
        off = compute_ehp(
            _snap(), champion_id="Garen", level=13, item_ids=["3075"], mode="SR",
        )
        on = compute_ehp(
            _snap(), champion_id="Garen", level=13, item_ids=["3075"], mode="SR",
            apply_item_resist_grants=True,
        )
        self.assertEqual(on.item_resist_armor, 0.0)
        self.assertEqual(on.item_resist_mr, 0.0)
        for field in ("physical_ehp", "magical_ehp", "true_ehp", "blended_ehp"):
            self.assertAlmostEqual(
                getattr(on, field), getattr(off, field), places=9, msg=field
            )


# ---------------- to_dict ----------------


class ItemResistToDictTests(unittest.TestCase):
    def test_to_dict_carries_both_fields(self) -> None:
        r = compute_ehp(
            _snap(), champion_id="Ornn", level=13, item_ids=["6665"], mode="SR",
            apply_item_resist_grants=True,
        )
        d = r.to_dict()
        self.assertIn("item_resist_armor", d)
        self.assertIn("item_resist_mr", d)
        self.assertTrue(math.isclose(d["item_resist_armor"], r.item_resist_armor))
        self.assertTrue(math.isclose(d["item_resist_mr"], r.item_resist_mr))


if __name__ == "__main__":
    unittest.main()
