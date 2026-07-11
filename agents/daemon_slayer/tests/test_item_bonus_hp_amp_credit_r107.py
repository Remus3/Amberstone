"""Item-side BONUS-HP-AMP ("Warmog's Vitality") credit to the EHP numerator
(R107, ENGINE 1.200.0).

RED-first coverage for the NEW default-OFF ``apply_item_bonus_hp_amp`` seam on
``compute_ehp``. Today Warmog's Armor's "Warmog's Vitality" passive earns ZERO
EHP: it grants "bonus health equal to 12% bonus health from items" (verbatim
``data/daemon_slayer/16.13.1/items_meraki.json`` for 3083), but the engine folds
only the item's FLAT health stat into the resolved block - no self-HP amplifier
walk exists in ``build_champion`` and no ``_effects_types`` field carries it. A
live probe (Sion L13 + Warmog/Heartsteel/Sunfire) confirmed ``hp - base_hp``
equals the raw item flat HP EXACTLY, so the +12% (270 HP on a 2250 item-HP build)
is absent from every EHP numerator.

This is a genuinely NEW axis - an HP -> HP self-amplifier - distinct from the
seven saturated item-side survivability families (omnivamp / item-shield /
item-revive / item-stasis / item-spell-shield / item mana->HP R105 / item
resist-grant R106). It is the item twin of the champion stacking-HP passive
(``passive_health_stack_hp``, champion-keyed so an item can never match it), the
same structural gap the sibling ``_item_*`` registries fill. A NEW
``_item_bonus_hp_amp`` registry (item_id -> 0.12 of bonus-health-from-items) plus
a default-OFF ``apply_item_bonus_hp_amp`` seam folds ``0.12 * bonus_hp_from_items``
into every per-type EHP numerator next to ``ext_flat_hp`` / ``item_mana_health_hp``
(a genuine flat max-HP pool add).

Contract:
  * OFF (default) -> item_bonus_hp_amp_hp == 0.0 -> physical/magical/true/blended/
    cc_blended/sustain EHP BYTE-IDENTICAL to the pre-seam value (and to an explicit
    ``False`` run).
  * ON + a Warmog's build -> item_bonus_hp_amp_hp == 0.12 * bonus_hp_from_items
    (bonus_hp_from_items = total max HP - base max HP, derived from the same engine
    build), and physical/magical/true/blended EHP all STRICTLY RISE (a real max-HP
    pool add).
  * The credit is EXACT (deterministic, no amortization midpoint) - like R105's
    mana->HP, unlike R106's ramping resist grant.
  * A non-family build with the flag ON does NOT leak credit - not even one that
    carries large item bonus HP from OTHER items (Heartsteel + Sunfire, no Warmog's).
"""
from __future__ import annotations

import math
import unittest

from agents.daemon_slayer._item_bonus_hp_amp import (
    _ITEM_BONUS_HP_AMP_PCT,
    item_bonus_hp_amp_hp,
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


def _bonus_hp_from_items(champion_id: str, level: int, items) -> float:
    """Item-contributed (bonus) max HP via the SAME engine build compute_ehp uses."""
    resolved = build_champion(
        _snap(), champion_id, level, item_ids=list(items), mode="SR",
    )
    total = float(resolved.stats.get("hp", 0.0))
    base = float(resolved.base_stats.get("hp", 0.0))
    return max(0.0, total - base)


# ---------------- registry unit ----------------


class ItemBonusHpAmpRegistryTests(unittest.TestCase):
    def test_single_item_is_12pct_of_bonus_hp(self) -> None:
        self.assertAlmostEqual(item_bonus_hp_amp_hp(["3083"], 1000.0), 120.0, places=9)

    def test_arena_mirror_same_nominal(self) -> None:
        self.assertAlmostEqual(
            item_bonus_hp_amp_hp(["443083"], 1000.0), 120.0, places=9
        )

    def test_two_family_items_take_the_max_not_the_sum(self) -> None:
        # "Warmog's Vitality" is a UNIQUE passive over a SHARED bonus-HP pool -> the
        # MAX percent applies, never the sum (a synthetic base + Arena-mirror
        # double-equip cannot double-count).
        self.assertAlmostEqual(
            item_bonus_hp_amp_hp(["3083", "443083"], 1000.0), 120.0, places=9
        )

    def test_unknown_item_id_yields_zero(self) -> None:
        self.assertEqual(item_bonus_hp_amp_hp(["9999"], 1000.0), 0.0)

    def test_empty_build_yields_zero(self) -> None:
        self.assertEqual(item_bonus_hp_amp_hp([], 1000.0), 0.0)

    def test_zero_bonus_hp_yields_zero(self) -> None:
        self.assertEqual(item_bonus_hp_amp_hp(["3083"], 0.0), 0.0)

    def test_negative_bonus_hp_clamped_to_zero(self) -> None:
        self.assertEqual(item_bonus_hp_amp_hp(["3083"], -500.0), 0.0)

    def test_registered_ids_are_exactly_the_two(self) -> None:
        self.assertEqual(set(_ITEM_BONUS_HP_AMP_PCT), {"3083", "443083"})

    def test_all_pcts_are_12_percent(self) -> None:
        for iid, pct in _ITEM_BONUS_HP_AMP_PCT.items():
            self.assertAlmostEqual(pct, 0.12, places=9, msg=iid)


# ---------------- OFF byte-identical ----------------


class ItemBonusHpAmpOffByteIdenticalTests(unittest.TestCase):
    def _ehp(self, *, on, items=("3083", "3084", "3068"), champ="Sion", level=13):
        return compute_ehp(
            _snap(), champion_id=champ, level=level, item_ids=list(items),
            mode="SR", apply_item_bonus_hp_amp=on,
        )

    def test_flag_absent_equals_explicit_false(self) -> None:
        absent = compute_ehp(
            _snap(), champion_id="Sion", level=13,
            item_ids=["3083", "3084", "3068"], mode="SR",
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
        self.assertEqual(self._ehp(on=False).item_bonus_hp_amp_hp, 0.0)


# ---------------- ON credit (EHP numerator) ----------------


class ItemBonusHpAmpOnCreditTests(unittest.TestCase):
    def _ehp(self, *, on, items=("3083", "3084", "3068"), champ="Sion", level=13):
        return compute_ehp(
            _snap(), champion_id=champ, level=level, item_ids=list(items),
            mode="SR", apply_item_bonus_hp_amp=on,
        )

    def test_on_field_equals_12pct_of_bonus_hp_from_items(self) -> None:
        on = self._ehp(on=True)
        expected = 0.12 * _bonus_hp_from_items("Sion", 13, ["3083", "3084", "3068"])
        self.assertGreater(expected, 0.0)  # sanity: build carries item bonus HP
        self.assertAlmostEqual(on.item_bonus_hp_amp_hp, expected, places=6)

    def test_on_raises_every_ehp_type(self) -> None:
        off = self._ehp(on=False)
        on = self._ehp(on=True)
        self.assertGreater(on.physical_ehp, off.physical_ehp)
        self.assertGreater(on.magical_ehp, off.magical_ehp)
        self.assertGreater(on.true_ehp, off.true_ehp)
        self.assertGreater(on.blended_ehp, off.blended_ehp)

    def test_arena_mirror_also_credits(self) -> None:
        on = compute_ehp(
            _snap(), champion_id="Sion", level=13, item_ids=["443083"], mode="SR",
            apply_item_bonus_hp_amp=True,
        )
        self.assertGreater(on.item_bonus_hp_amp_hp, 0.0)


# ---------------- isolation (no leak) ----------------


class ItemBonusHpAmpIsolationTests(unittest.TestCase):
    def test_other_hp_items_with_flag_on_are_byte_identical(self) -> None:
        # Heartsteel (3084) + Sunfire Aegis (3068) grant large item bonus HP but
        # NEITHER carries "Warmog's Vitality". Arming the seam must not leak any HP:
        # the +12% amp fires ONLY when Warmog's (3083 / 443083) is equipped.
        off = compute_ehp(
            _snap(), champion_id="Sion", level=13, item_ids=["3084", "3068"],
            mode="SR",
        )
        on = compute_ehp(
            _snap(), champion_id="Sion", level=13, item_ids=["3084", "3068"],
            mode="SR", apply_item_bonus_hp_amp=True,
        )
        self.assertEqual(on.item_bonus_hp_amp_hp, 0.0)
        for field in ("physical_ehp", "magical_ehp", "true_ehp", "blended_ehp"):
            self.assertAlmostEqual(
                getattr(on, field), getattr(off, field), places=9, msg=field
            )

    def test_non_hp_build_no_credit(self) -> None:
        # A pure-resist item (Thornmail 3075) build: no Warmog's, no credit,
        # byte-identical even with the flag armed.
        off = compute_ehp(
            _snap(), champion_id="Garen", level=13, item_ids=["3075"], mode="SR",
        )
        on = compute_ehp(
            _snap(), champion_id="Garen", level=13, item_ids=["3075"], mode="SR",
            apply_item_bonus_hp_amp=True,
        )
        self.assertEqual(on.item_bonus_hp_amp_hp, 0.0)
        self.assertAlmostEqual(on.blended_ehp, off.blended_ehp, places=9)


# ---------------- to_dict ----------------


class ItemBonusHpAmpToDictTests(unittest.TestCase):
    def test_to_dict_carries_field(self) -> None:
        r = compute_ehp(
            _snap(), champion_id="Sion", level=13,
            item_ids=["3083", "3084", "3068"], mode="SR",
            apply_item_bonus_hp_amp=True,
        )
        d = r.to_dict()
        self.assertIn("item_bonus_hp_amp_hp", d)
        self.assertGreater(d["item_bonus_hp_amp_hp"], 0.0)
        self.assertTrue(math.isclose(d["item_bonus_hp_amp_hp"], r.item_bonus_hp_amp_hp))


if __name__ == "__main__":
    unittest.main()
