"""RM-103: Unending Despair Anguish self-heal registry (_item_proc_heal).

Guards the uncredited SELF-heal half of Unending Despair (SR 2502 / Arena
222502). The damage half has shipped since Phase 4 batch 33 as a
``PeriodicProc``; the "heal yourself equal to 250% of the post-mitigation
damage dealt" half had no carrier anywhere in the package.

Ground truth for every magnitude asserted below:
  * ``data/daemon_slayer/16.14.1/items_meraki.json`` item 2502 passive
    "Anguish": "Every 4 seconds after entering combat with champions, sap all
    enemy champions around you within 650 units to deal magic damage equal to
    3% of your bonus health to them and heal yourself equal to 250% of the
    post-mitigation damage dealt."
  * ``data/daemon_slayer/16.14.1/items.json`` - exactly TWO ids carry the name
    "Unending Despair": 2502 (maps 11/12/21/35) and 222502 (map 30). There is
    NO 322502 ARAM mirror; 2502 itself is the ARAM (map 12) item.

The whole lane is DEFAULT-OFF: with ``assume_item_proc_heal`` absent or False
every entry point returns exactly 0.0.
"""

from __future__ import annotations

import json
import pathlib
import re
import unittest

from agents.daemon_slayer._item_proc_heal import (
    _ASSUMED_TARGET_MR_FOR_PROC_HEAL,
    _ITEM_PROC_HEAL_BONUS_HP_SCALING,
    _PROC_HEAL_CHAMPIONS_IN_RANGE,
    _PROC_HEAL_TRIGGERS_PER_FIGHT,
    item_proc_heal_hp,
)

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_PATCH_DIR = _REPO_ROOT / "data" / "daemon_slayer" / "16.14.1"


class DefaultOffInertnessTests(unittest.TestCase):
    """The flag is the ONLY thing standing between 0.0 and a contribution."""

    def test_flag_absent_is_zero(self) -> None:
        self.assertEqual(item_proc_heal_hp(["2502"], bonus_hp=1200.0), 0.0)

    def test_flag_false_is_zero(self) -> None:
        self.assertEqual(
            item_proc_heal_hp(
                ["2502"], bonus_hp=1200.0, assume_item_proc_heal=False
            ),
            0.0,
        )

    def test_flag_off_is_zero_for_every_registered_id(self) -> None:
        for iid in _ITEM_PROC_HEAL_BONUS_HP_SCALING:
            with self.subTest(item_id=iid):
                self.assertEqual(
                    item_proc_heal_hp([iid], bonus_hp=3000.0), 0.0
                )

    def test_flag_on_but_unregistered_item_is_zero(self) -> None:
        self.assertEqual(
            item_proc_heal_hp(
                ["3026", "6653", "3143"],
                bonus_hp=1200.0,
                assume_item_proc_heal=True,
            ),
            0.0,
        )

    def test_flag_on_empty_build_is_zero(self) -> None:
        self.assertEqual(
            item_proc_heal_hp([], bonus_hp=1200.0, assume_item_proc_heal=True),
            0.0,
        )


class CoefficientTests(unittest.TestCase):
    """2.5 * 0.03 = 0.075 PRE-mitigation, per proc, per champion hit."""

    def test_pre_mitigation_coefficient_is_0075(self) -> None:
        for iid in ("2502", "222502"):
            with self.subTest(item_id=iid):
                self.assertAlmostEqual(
                    _ITEM_PROC_HEAL_BONUS_HP_SCALING[iid], 0.075, places=9
                )

    def test_registry_holds_exactly_the_two_real_ids(self) -> None:
        self.assertEqual(
            set(_ITEM_PROC_HEAL_BONUS_HP_SCALING), {"2502", "222502"}
        )

    def test_no_aram_mirror_322502_registered(self) -> None:
        self.assertNotIn("322502", _ITEM_PROC_HEAL_BONUS_HP_SCALING)

    def test_arena_mirror_shares_the_sr_coefficient(self) -> None:
        self.assertEqual(
            _ITEM_PROC_HEAL_BONUS_HP_SCALING["2502"],
            _ITEM_PROC_HEAL_BONUS_HP_SCALING["222502"],
        )


class AssumedTargetMrPinTests(unittest.TestCase):
    """Pin the ONE assumption so a later pass cannot move it silently."""

    def test_assumed_target_mr_is_sweep_standard_60(self) -> None:
        self.assertAlmostEqual(_ASSUMED_TARGET_MR_FOR_PROC_HEAL, 60.0, places=9)

    def test_trigger_and_range_seeds_are_conservative_unity(self) -> None:
        self.assertAlmostEqual(_PROC_HEAL_TRIGGERS_PER_FIGHT, 1.0, places=9)
        self.assertAlmostEqual(_PROC_HEAL_CHAMPIONS_IN_RANGE, 1.0, places=9)

    def test_post_mitigation_effective_coefficient_is_0046875(self) -> None:
        # 0.075 * 100/(100+60) = 0.075 * 0.625 = 0.046875
        got = item_proc_heal_hp(
            ["2502"], bonus_hp=1000.0, assume_item_proc_heal=True
        )
        self.assertAlmostEqual(got, 46.875, places=6)

    def test_default_credit_is_strictly_below_pre_mitigation(self) -> None:
        """The whole point of RM-103's MR step - it must NOT over-credit."""
        got = item_proc_heal_hp(
            ["2502"], bonus_hp=1200.0, assume_item_proc_heal=True
        )
        pre_mitigation = 0.075 * 1200.0
        self.assertLess(got, pre_mitigation)
        self.assertAlmostEqual(got, 56.25, places=6)


class TargetMrOverrideTests(unittest.TestCase):
    """No caller silently inherits the module seed."""

    def test_zero_mr_yields_full_pre_mitigation_value(self) -> None:
        got = item_proc_heal_hp(
            ["2502"],
            bonus_hp=1000.0,
            assume_item_proc_heal=True,
            target_mr=0.0,
        )
        self.assertAlmostEqual(got, 75.0, places=6)

    def test_higher_mr_reduces_credit_monotonically(self) -> None:
        low = item_proc_heal_hp(
            ["2502"], bonus_hp=1000.0, assume_item_proc_heal=True, target_mr=30.0
        )
        high = item_proc_heal_hp(
            ["2502"],
            bonus_hp=1000.0,
            assume_item_proc_heal=True,
            target_mr=200.0,
        )
        self.assertGreater(low, high)

    def test_negative_mr_shred_amplifies_above_pre_mitigation(self) -> None:
        """Mirrors ehp._armor_factor: 2 - 100/(100 - resist) for resist < 0."""
        got = item_proc_heal_hp(
            ["2502"],
            bonus_hp=1000.0,
            assume_item_proc_heal=True,
            target_mr=-25.0,
        )
        # 2 - 100/125 = 1.2 -> 75.0 * 1.2 = 90.0
        self.assertAlmostEqual(got, 90.0, places=6)


class TriggerAndRangeOverrideTests(unittest.TestCase):
    def test_two_triggers_doubles(self) -> None:
        one = item_proc_heal_hp(
            ["2502"], bonus_hp=1000.0, assume_item_proc_heal=True
        )
        two = item_proc_heal_hp(
            ["2502"],
            bonus_hp=1000.0,
            assume_item_proc_heal=True,
            triggers_per_fight=2.0,
        )
        self.assertAlmostEqual(two, 2.0 * one, places=6)

    def test_three_champions_in_range_triples(self) -> None:
        one = item_proc_heal_hp(
            ["2502"], bonus_hp=1000.0, assume_item_proc_heal=True
        )
        three = item_proc_heal_hp(
            ["2502"],
            bonus_hp=1000.0,
            assume_item_proc_heal=True,
            champions_in_range=3.0,
        )
        self.assertAlmostEqual(three, 3.0 * one, places=6)

    def test_zero_triggers_is_zero(self) -> None:
        self.assertEqual(
            item_proc_heal_hp(
                ["2502"],
                bonus_hp=1000.0,
                assume_item_proc_heal=True,
                triggers_per_fight=0.0,
            ),
            0.0,
        )


class DegenerateInputTests(unittest.TestCase):
    def test_zero_bonus_hp_is_zero(self) -> None:
        self.assertEqual(
            item_proc_heal_hp(
                ["2502"], bonus_hp=0.0, assume_item_proc_heal=True
            ),
            0.0,
        )

    def test_negative_bonus_hp_floors_at_zero(self) -> None:
        self.assertEqual(
            item_proc_heal_hp(
                ["2502"], bonus_hp=-500.0, assume_item_proc_heal=True
            ),
            0.0,
        )

    def test_negative_seeds_floor_at_zero(self) -> None:
        for kwargs in (
            {"triggers_per_fight": -1.0},
            {"champions_in_range": -2.0},
        ):
            with self.subTest(**kwargs):
                self.assertEqual(
                    item_proc_heal_hp(
                        ["2502"],
                        bonus_hp=1000.0,
                        assume_item_proc_heal=True,
                        **kwargs,
                    ),
                    0.0,
                )

    def test_int_item_ids_resolve(self) -> None:
        got = item_proc_heal_hp(
            [2502], bonus_hp=1000.0, assume_item_proc_heal=True
        )
        self.assertAlmostEqual(got, 46.875, places=6)

    def test_duplicate_ids_are_deduped_no_unique_stacking(self) -> None:
        """Anguish is a UNIQUE passive - two copies do not double the heal."""
        once = item_proc_heal_hp(
            ["2502"], bonus_hp=1000.0, assume_item_proc_heal=True
        )
        twice = item_proc_heal_hp(
            ["2502", "2502"], bonus_hp=1000.0, assume_item_proc_heal=True
        )
        self.assertAlmostEqual(twice, once, places=9)

    def test_sr_and_arena_copies_do_not_double(self) -> None:
        both = item_proc_heal_hp(
            ["2502", "222502"], bonus_hp=1000.0, assume_item_proc_heal=True
        )
        self.assertAlmostEqual(both, 46.875, places=6)


class FeedProvenanceTests(unittest.TestCase):
    """The coefficient is DERIVED from the vendored feed, not asserted at it."""

    @classmethod
    def setUpClass(cls) -> None:
        with open(_PATCH_DIR / "items_meraki.json", encoding="utf-8") as fh:
            cls.meraki = json.load(fh)["items"]
        with open(_PATCH_DIR / "items.json", encoding="utf-8") as fh:
            raw = json.load(fh)
        cls.ddragon = raw.get("data", raw)

    def test_meraki_states_3pct_bonus_health_and_250pct_heal(self) -> None:
        passives = self.meraki["2502"]["passives"]
        anguish = [p for p in passives if p.get("name") == "Anguish"]
        self.assertEqual(len(anguish), 1, "Meraki passive name is 'Anguish'")
        text = anguish[0]["effects"]
        self.assertIn("3% of your '''bonus''' health", text)
        self.assertIn("250% of the", text)
        self.assertIn("post-mitigation", text)

    def test_derived_coefficient_matches_registry(self) -> None:
        derived = 2.50 * 0.03
        self.assertAlmostEqual(
            _ITEM_PROC_HEAL_BONUS_HP_SCALING["2502"], derived, places=9
        )

    def test_exactly_two_unending_despair_ids_in_ddragon(self) -> None:
        ids = {
            k
            for k, v in self.ddragon.items()
            if (v.get("name") or "") == "Unending Despair"
        }
        self.assertEqual(ids, {"2502", "222502"})

    def test_both_ids_advertise_the_250pct_heal(self) -> None:
        # DDragon descriptions carry inline markup tags
        # ("<healing>heal for 250%</healing> of the damage dealt"), so strip
        # them before matching rather than asserting at the raw string.
        for iid in ("2502", "222502"):
            with self.subTest(item_id=iid):
                plain = " ".join(
                    re.sub(r"<[^>]+>", " ", self.ddragon[iid]["description"])
                    .split()
                )
                self.assertIn("Anguish", plain)
                self.assertIn("heal for 250% of the damage dealt", plain)

    def test_registered_ids_all_exist_in_the_item_index(self) -> None:
        for iid in _ITEM_PROC_HEAL_BONUS_HP_SCALING:
            with self.subTest(item_id=iid):
                self.assertIn(iid, self.ddragon)


if __name__ == "__main__":
    unittest.main()
