"""Item-side MANA -> MAX-HP "Awe" credit to the EHP numerator (R105, ENGINE 1.198.0).

RED-first coverage for the NEW default-OFF ``apply_item_mana_health`` seam on
``compute_ehp``. Today the item "Awe" mana -> HP grant earns ZERO EHP: the engine
folds mana -> bonus AD (Manamune) and bonus mana -> AP (Archangel's / Seraph's) in
``build_champion`` but has NO mana -> HP walk and no ``_effects_types`` field for it,
so Winter's Approach (3119) / Fimbulwinter (3121) contribute only their FLAT health
stat to the resolved block - the "bonus health equal to 15% bonus mana" is missing.

The champion stacking-HP passive registry (``_passive_health_overrides``,
``passive_health_stack_hp``) is champion-keyed (``(champion_id, ability_key,
form_index)``), so an ITEM can never match it - the same structural gap the
``_item_revive`` / ``_item_survival_window`` / ``_item_spell_shield_overrides``
registries fill for the champion revive / survival-window / spell-shield axes. This
module is the item-side lane of that stacking-HP axis: a NEW ``_item_mana_health``
registry (item_id -> 0.15 of BONUS mana) plus a default-OFF ``apply_item_mana_health``
seam that folds ``0.15 * bonus_mana`` into every per-type EHP numerator next to
``ext_flat_hp`` (a genuine flat max-HP pool add).

Contract:
  * OFF (default) -> item_mana_health_hp == 0.0 -> physical/magical/true/blended/
    cc_blended/sustain EHP BYTE-IDENTICAL to the pre-seam value (and to an explicit
    ``False`` run).
  * ON + a Fimbulwinter/Winter's Approach build -> item_mana_health_hp ==
    0.15 * bonus_mana (bonus_mana = item-contributed max mana, derived from the same
    engine build), and physical/magical/true/blended EHP all STRICTLY RISE (a real
    max-HP pool add).
  * The credit is EXACT (deterministic, no amortization midpoint).
  * A non-family build with the flag ON does NOT leak credit - not even one that
    carries bonus mana (Archangel's Staff: mana -> AP "Awe", no HP).
"""
from __future__ import annotations

import math
import unittest

from agents.daemon_slayer._item_mana_health import (
    _ITEM_MANA_HEALTH_PCT,
    item_mana_health_hp,
)
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.engine import build_champion
from agents.daemon_slayer.ehp import compute_ehp

_SNAP: DataSnapshot | None = None


def _snap() -> DataSnapshot:
    global _SNAP
    if _SNAP is None:
        _SNAP = DataSnapshot.load()
    return _SNAP


def _bonus_mana(champion_id: str, level: int, items) -> float:
    """Item-contributed (bonus) max mana via the SAME engine build compute_ehp uses."""
    resolved = build_champion(
        _snap(), champion_id, level, item_ids=list(items), mode="SR",
    )
    total = float(resolved.stats.get("mp", 0.0))
    base = float(resolved.base_stats.get("mp", 0.0))
    return max(0.0, total - base)


# ---------------- registry unit ----------------


class ItemManaHealthRegistryTests(unittest.TestCase):
    def test_single_item_is_pct_of_bonus_mana(self) -> None:
        self.assertAlmostEqual(item_mana_health_hp(["3121"], 1000.0), 150.0, places=9)

    def test_winters_approach_same_nominal(self) -> None:
        self.assertAlmostEqual(item_mana_health_hp(["3119"], 1000.0), 150.0, places=9)

    def test_arena_and_aram_mirrors_same_nominal(self) -> None:
        for iid in ("223119", "223121", "323119", "323121"):
            self.assertAlmostEqual(
                item_mana_health_hp([iid], 1000.0), 150.0, places=9, msg=iid
            )

    def test_two_family_items_take_the_max_not_the_sum(self) -> None:
        # "Awe" is a UNIQUE passive over a SHARED bonus mana pool -> the MAX percent
        # applies, never the sum (a synthetic double-equip cannot double-count).
        self.assertAlmostEqual(
            item_mana_health_hp(["3119", "3121"], 1000.0), 150.0, places=9
        )

    def test_unknown_item_id_yields_zero(self) -> None:
        self.assertEqual(item_mana_health_hp(["9999"], 1000.0), 0.0)

    def test_empty_build_yields_zero(self) -> None:
        self.assertEqual(item_mana_health_hp([], 1000.0), 0.0)

    def test_zero_bonus_mana_yields_zero(self) -> None:
        self.assertEqual(item_mana_health_hp(["3121"], 0.0), 0.0)

    def test_negative_bonus_mana_clamped_to_zero(self) -> None:
        self.assertEqual(item_mana_health_hp(["3121"], -500.0), 0.0)

    def test_registered_ids_are_exactly_the_six(self) -> None:
        self.assertEqual(
            set(_ITEM_MANA_HEALTH_PCT),
            {"3119", "3121", "223119", "223121", "323119", "323121"},
        )

    def test_all_pcts_are_15_percent(self) -> None:
        for iid, pct in _ITEM_MANA_HEALTH_PCT.items():
            self.assertAlmostEqual(pct, 0.15, places=9, msg=iid)


# ---------------- OFF byte-identical ----------------


class ItemManaHealthOffByteIdenticalTests(unittest.TestCase):
    def _ehp(self, *, on, items=("3121",), champ="Rell", level=13):
        return compute_ehp(
            _snap(), champion_id=champ, level=level, item_ids=list(items),
            mode="SR", apply_item_mana_health=on,
        )

    def test_flag_absent_equals_explicit_false(self) -> None:
        absent = compute_ehp(
            _snap(), champion_id="Rell", level=13, item_ids=["3121"], mode="SR",
        )
        off = self._ehp(on=False)
        for field in (
            "physical_ehp", "magical_ehp", "true_ehp", "blended_ehp",
            "cc_blended_ehp", "effective_ehp_with_sustain",
        ):
            self.assertAlmostEqual(
                getattr(absent, field), getattr(off, field), places=9, msg=field
            )

    def test_off_field_is_zero(self) -> None:
        self.assertEqual(self._ehp(on=False).item_mana_health_hp, 0.0)


# ---------------- ON credit (EHP numerator) ----------------


class ItemManaHealthOnCreditTests(unittest.TestCase):
    def _ehp(self, *, on, items=("3121",), champ="Rell", level=13):
        return compute_ehp(
            _snap(), champion_id=champ, level=level, item_ids=list(items),
            mode="SR", apply_item_mana_health=on,
        )

    def test_on_field_equals_15pct_of_bonus_mana(self) -> None:
        on = self._ehp(on=True)
        expected = 0.15 * _bonus_mana("Rell", 13, ["3121"])
        self.assertGreater(expected, 0.0)  # sanity: Fimbulwinter carries item mana
        self.assertAlmostEqual(on.item_mana_health_hp, expected, places=6)

    def test_on_raises_every_ehp_type(self) -> None:
        off = self._ehp(on=False)
        on = self._ehp(on=True)
        self.assertGreater(on.physical_ehp, off.physical_ehp)
        self.assertGreater(on.magical_ehp, off.magical_ehp)
        self.assertGreater(on.true_ehp, off.true_ehp)
        self.assertGreater(on.blended_ehp, off.blended_ehp)

    def test_winters_approach_also_credits(self) -> None:
        on = compute_ehp(
            _snap(), champion_id="Rell", level=13, item_ids=["3119"], mode="SR",
            apply_item_mana_health=True,
        )
        self.assertGreater(on.item_mana_health_hp, 0.0)


# ---------------- isolation (no leak) ----------------


class ItemManaHealthIsolationTests(unittest.TestCase):
    def test_non_family_mana_item_with_flag_on_is_byte_identical(self) -> None:
        # Archangel's Staff (3003) grants BONUS MANA and an "Awe" passive, but its
        # Awe converts mana -> AP, NOT HP. Arming the seam must not leak any HP.
        off = compute_ehp(
            _snap(), champion_id="Ryze", level=13, item_ids=["3003"], mode="SR",
        )
        on = compute_ehp(
            _snap(), champion_id="Ryze", level=13, item_ids=["3003"], mode="SR",
            apply_item_mana_health=True,
        )
        self.assertEqual(on.item_mana_health_hp, 0.0)
        for field in ("physical_ehp", "magical_ehp", "true_ehp", "blended_ehp"):
            self.assertAlmostEqual(
                getattr(on, field), getattr(off, field), places=9, msg=field
            )

    def test_manaless_style_non_family_build_no_credit(self) -> None:
        # A pure-resist item (Thornmail 3075) on a manaless champ: no family item,
        # no credit, byte-identical.
        off = compute_ehp(
            _snap(), champion_id="Garen", level=13, item_ids=["3075"], mode="SR",
        )
        on = compute_ehp(
            _snap(), champion_id="Garen", level=13, item_ids=["3075"], mode="SR",
            apply_item_mana_health=True,
        )
        self.assertEqual(on.item_mana_health_hp, 0.0)
        self.assertAlmostEqual(on.blended_ehp, off.blended_ehp, places=9)


# ---------------- to_dict ----------------


class ItemManaHealthToDictTests(unittest.TestCase):
    def test_to_dict_carries_field(self) -> None:
        r = compute_ehp(
            _snap(), champion_id="Rell", level=13, item_ids=["3121"], mode="SR",
            apply_item_mana_health=True,
        )
        d = r.to_dict()
        self.assertIn("item_mana_health_hp", d)
        self.assertGreater(d["item_mana_health_hp"], 0.0)
        self.assertTrue(math.isclose(d["item_mana_health_hp"], r.item_mana_health_hp))


if __name__ == "__main__":
    unittest.main()
