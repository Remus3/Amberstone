"""Item-side SPELL-SHIELD credit to the cc_blended discount (R104, ENGINE 1.197.0).

RED-first coverage for the NEW default-OFF ``apply_item_spell_shield`` seam on
``compute_ehp``. Today the item Annul spell shields earn ZERO CC-survival credit:
the ``_champion_spell_shield_overrides`` registry is champion-keyed (keyed by
``(champion_id, ability_key, form_index)``), so an ITEM can never match its
``champion_spell_shield_fraction`` - the exact structural gap the ``_item_revive``
/ ``_item_survival_window`` registries fill for the champion revive /
survival-window axes. Banshee's Veil (3102) / Edge of Night (3814) / Verdant
Barrier (4632) grant "Annul - a Spell Shield that blocks the next enemy Ability",
which - like the champion reactive spell shield (Sivir E / Nocturne W) - negates
ONE incoming CC instance and so lands on the cc_blended CC-pressure discount
(``cc_total *= (1 - frac)``), NOT the EHP numerator (that is the item-stasis lane).

This module is the item-side lane of that champion spell-shield axis: a NEW
``_item_spell_shield_overrides`` registry (item_id -> block_pct = 100.0, midpoint
= the reactive 0.2) plus a default-OFF ``apply_item_spell_shield`` seam that folds
the summed item block fraction into the same ``cc_total`` discount, combining
MULTIPLICATIVELY with the champion spell-shield fraction.

Contract:
  * OFF (default) -> item_spell_shield_frac == 0.0 -> cc_blended_ehp /
    enemy_cc_pressure_s BYTE-IDENTICAL to the pre-seam value (and to an explicit
    ``False`` run); blended_ehp never moves (the discount is a cc-only term).
  * ON + an enemy comp -> a spell-shield build negates one enemy CC instance ->
    a STRICTLY SMALLER enemy_cc_pressure_s and a LARGER (or equal, under the
    fraction clamp) cc_blended_ehp than the same build with the flag off.
  * The credit composes MULTIPLICATIVELY with the champion spell-shield fraction
    and applies AFTER the tenacity step (same seam as the champion block).
  * A non-spell-shield build with the flag ON does NOT leak credit.
"""
from __future__ import annotations

import math
import unittest

from agents.daemon_slayer._champion_spell_shield_overrides import (
    _SPELL_SHIELD_REACTIVE_PROB,
)
from agents.daemon_slayer._item_spell_shield_overrides import (
    _ITEM_SPELL_SHIELD,
    _ITEM_SPELL_SHIELD_PROB,
    item_spell_shield_fraction,
)
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import compute_ehp

_SNAP: DataSnapshot | None = None


def _snap() -> DataSnapshot:
    global _SNAP
    if _SNAP is None:
        _SNAP = DataSnapshot.load()
    return _SNAP


# ---------------- registry unit ----------------


class ItemSpellShieldRegistryTests(unittest.TestCase):
    def test_banshee_reactive_fraction(self) -> None:
        # A single Annul item blocks one effect (100%), amortized at the reactive
        # midpoint -> the fraction is exactly the midpoint.
        self.assertAlmostEqual(
            item_spell_shield_fraction(["3102"]),
            1.0 * _ITEM_SPELL_SHIELD_PROB,
            places=9,
        )

    def test_edge_of_night_same_nominal(self) -> None:
        self.assertAlmostEqual(
            item_spell_shield_fraction(["3814"]),
            1.0 * _ITEM_SPELL_SHIELD_PROB,
            places=9,
        )

    def test_verdant_barrier_same_nominal(self) -> None:
        self.assertAlmostEqual(
            item_spell_shield_fraction(["4632"]),
            1.0 * _ITEM_SPELL_SHIELD_PROB,
            places=9,
        )

    def test_arena_mirrors_same_nominal(self) -> None:
        for iid in ("223102", "223814"):
            self.assertAlmostEqual(
                item_spell_shield_fraction([iid]),
                1.0 * _ITEM_SPELL_SHIELD_PROB,
                places=9,
            )

    def test_midpoint_is_the_reactive_midpoint(self) -> None:
        # The item Annul reuses the champion reactive spell-shield midpoint (0.2).
        self.assertAlmostEqual(
            _ITEM_SPELL_SHIELD_PROB, _SPELL_SHIELD_REACTIVE_PROB, places=9
        )
        self.assertAlmostEqual(_ITEM_SPELL_SHIELD_PROB, 0.2, places=9)

    def test_two_shields_stack_multiplicatively(self) -> None:
        # 1 - (1 - p)^2 for two independent block-one shields (parity with the
        # champion product form; a real build caps at one via the Annul unique).
        p = _ITEM_SPELL_SHIELD_PROB
        self.assertAlmostEqual(
            item_spell_shield_fraction(["3102", "3814"]),
            1.0 - (1.0 - p) * (1.0 - p),
            places=9,
        )

    def test_unknown_item_id_yields_zero(self) -> None:
        self.assertEqual(item_spell_shield_fraction(["9999"]), 0.0)

    def test_empty_build_yields_zero(self) -> None:
        self.assertEqual(item_spell_shield_fraction([]), 0.0)

    def test_registered_ids_are_exactly_the_five(self) -> None:
        self.assertEqual(
            set(_ITEM_SPELL_SHIELD),
            {"3102", "223102", "3814", "223814", "4632"},
        )

    def test_all_block_pcts_are_100(self) -> None:
        for iid, pct in _ITEM_SPELL_SHIELD.items():
            self.assertAlmostEqual(pct, 100.0, places=9, msg=iid)

    def test_dropped_mirror_ids_not_registered(self) -> None:
        # ARAM 32xxxx mirrors + Verdant's Arena mirror are NOT in the DS item index
        # -> intentionally dropped.
        for iid in ("323102", "323814", "224632", "324632"):
            self.assertNotIn(iid, _ITEM_SPELL_SHIELD)

    def test_fraction_bounded_below_one(self) -> None:
        frac = item_spell_shield_fraction(["3102"])
        self.assertGreater(frac, 0.0)
        self.assertLess(frac, 1.0)


# ---------------- OFF byte-identical ----------------


class ItemSpellShieldOffByteIdenticalTests(unittest.TestCase):
    ENEMIES = ("Leona",)

    def _ehp(self, *, on, items=("3102",), enemies=ENEMIES):
        return compute_ehp(
            _snap(), champion_id="Lux", level=13, item_ids=list(items),
            mode="SR", enemy_champions=enemies, apply_item_spell_shield=on,
        )

    def test_flag_absent_equals_explicit_false(self) -> None:
        absent = compute_ehp(
            _snap(), champion_id="Lux", level=13, item_ids=["3102"], mode="SR",
            enemy_champions=self.ENEMIES,
        )
        explicit_off = self._ehp(on=False)
        self.assertAlmostEqual(
            absent.cc_blended_ehp, explicit_off.cc_blended_ehp, places=9
        )
        self.assertAlmostEqual(
            absent.enemy_cc_pressure_s, explicit_off.enemy_cc_pressure_s, places=9
        )

    def test_off_field_is_zero(self) -> None:
        off = self._ehp(on=False)
        self.assertEqual(off.item_spell_shield_frac, 0.0)

    def test_off_does_not_move_blended_ehp(self) -> None:
        off = self._ehp(on=False)
        on = self._ehp(on=True)
        # The cc discount never touches the pre-cc blended_ehp.
        self.assertAlmostEqual(on.blended_ehp, off.blended_ehp, places=9)


# ---------------- ON credit (cc_blended discount) ----------------


class ItemSpellShieldOnCreditTests(unittest.TestCase):
    ENEMIES = ("Leona",)
    HEAVY = ("Leona", "Morgana", "Annie")

    def _ehp(self, *, on, items=("3102",), enemies=ENEMIES):
        return compute_ehp(
            _snap(), champion_id="Lux", level=13, item_ids=list(items),
            mode="SR", enemy_champions=enemies, apply_item_spell_shield=on,
        )

    def test_on_populates_fraction_field(self) -> None:
        on = self._ehp(on=True)
        self.assertAlmostEqual(
            on.item_spell_shield_frac, _ITEM_SPELL_SHIELD_PROB, places=9
        )

    def test_on_raises_cc_blended_ehp(self) -> None:
        off = self._ehp(on=False)
        on = self._ehp(on=True)
        self.assertGreater(on.cc_blended_ehp, off.cc_blended_ehp)

    def test_on_lowers_enemy_cc_pressure_by_exactly_the_fraction(self) -> None:
        # Under a heavy comp the cc_pressure_fraction clamps at 1.0 so
        # cc_blended_ehp can be byte-identical, but the axis still fires: the block
        # discount strictly LOWERS enemy_cc_pressure_s by exactly (1 - frac).
        off = self._ehp(on=False, enemies=self.HEAVY)
        on = self._ehp(on=True, enemies=self.HEAVY)
        self.assertLess(on.enemy_cc_pressure_s, off.enemy_cc_pressure_s)
        self.assertAlmostEqual(
            on.enemy_cc_pressure_s,
            off.enemy_cc_pressure_s * (1.0 - _ITEM_SPELL_SHIELD_PROB),
            places=6,
        )

    def test_no_enemy_comp_field_still_populated(self) -> None:
        r = compute_ehp(
            _snap(), champion_id="Lux", level=13, item_ids=["3102"], mode="SR",
            enemy_champions=(), apply_item_spell_shield=True,
        )
        self.assertAlmostEqual(
            r.item_spell_shield_frac, _ITEM_SPELL_SHIELD_PROB, places=9
        )
        self.assertAlmostEqual(r.cc_blended_ehp, r.blended_ehp, places=6)


# ---------------- multiplicative compose with the champion axis ----------------


class ItemSpellShieldComposeTests(unittest.TestCase):
    ENEMIES = ("Leona",)

    def test_composes_multiplicatively_with_champion_spell_shield(self) -> None:
        # Sivir HAS a champion spell shield (E) and carries a Banshee's (3102).
        # With BOTH flags on, the two block-one negations combine multiplicatively:
        # enemy_cc_pressure_s scales by (1 - champ)(1 - item) below the tenacity
        # step. The item flag alone must erode strictly MORE than neither.
        heavy = ("Leona", "Morgana", "Annie")
        neither = compute_ehp(
            _snap(), champion_id="Sivir", level=18, item_ids=["3102"], mode="SR",
            enemy_champions=heavy,
        )
        both = compute_ehp(
            _snap(), champion_id="Sivir", level=18, item_ids=["3102"], mode="SR",
            enemy_champions=heavy, apply_spell_shield=True,
            apply_item_spell_shield=True,
        )
        champ_only = compute_ehp(
            _snap(), champion_id="Sivir", level=18, item_ids=["3102"], mode="SR",
            enemy_champions=heavy, apply_spell_shield=True,
        )
        # Both-on erodes more CC than champion-only, which erodes more than neither.
        self.assertLess(both.enemy_cc_pressure_s, champ_only.enemy_cc_pressure_s)
        self.assertLess(champ_only.enemy_cc_pressure_s, neither.enemy_cc_pressure_s)
        # Exact multiplicative product on the post-tenacity pressure.
        p_champ = _SPELL_SHIELD_REACTIVE_PROB
        p_item = _ITEM_SPELL_SHIELD_PROB
        self.assertAlmostEqual(
            both.enemy_cc_pressure_s,
            neither.enemy_cc_pressure_s * (1.0 - p_champ) * (1.0 - p_item),
            places=6,
        )

    def test_item_flag_independent_of_champion_field(self) -> None:
        # The item flag lights item_spell_shield_frac and does NOT touch the
        # champion spell_shield_frac (independent axes/fields).
        r = compute_ehp(
            _snap(), champion_id="Lux", level=13, item_ids=["3102"], mode="SR",
            enemy_champions=self.ENEMIES, apply_item_spell_shield=True,
        )
        self.assertGreater(r.item_spell_shield_frac, 0.0)
        self.assertEqual(r.spell_shield_frac, 0.0)


# ---------------- isolation (no leak) ----------------


class ItemSpellShieldIsolationTests(unittest.TestCase):
    ENEMIES = ("Leona",)

    def test_non_spell_shield_build_with_flag_on_is_byte_identical(self) -> None:
        # Bloodthirster (3072) is not in the spell-shield registry; arming the seam
        # must not leak any credit onto it.
        off = compute_ehp(
            _snap(), champion_id="Aatrox", level=13, item_ids=["3072"], mode="SR",
            enemy_champions=self.ENEMIES,
        )
        on = compute_ehp(
            _snap(), champion_id="Aatrox", level=13, item_ids=["3072"], mode="SR",
            enemy_champions=self.ENEMIES, apply_item_spell_shield=True,
        )
        self.assertAlmostEqual(on.cc_blended_ehp, off.cc_blended_ehp, places=9)
        self.assertAlmostEqual(
            on.enemy_cc_pressure_s, off.enemy_cc_pressure_s, places=9
        )
        self.assertEqual(on.item_spell_shield_frac, 0.0)


# ---------------- to_dict ----------------


class ItemSpellShieldToDictTests(unittest.TestCase):
    def test_to_dict_carries_field(self) -> None:
        r = compute_ehp(
            _snap(), champion_id="Lux", level=13, item_ids=["3102"], mode="SR",
            enemy_champions=("Leona",), apply_item_spell_shield=True,
        )
        d = r.to_dict()
        self.assertIn("item_spell_shield_frac", d)
        self.assertTrue(
            math.isclose(d["item_spell_shield_frac"], _ITEM_SPELL_SHIELD_PROB)
        )


if __name__ == "__main__":
    unittest.main()
