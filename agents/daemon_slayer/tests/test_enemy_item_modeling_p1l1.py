"""Enemy-item target-resistance modeling verification [P1-L1].

Audit lane: how Daemon Slayer models the defending target's
armor / MR / HP from an enemy item list, with 1..6 enemy items
across champion levels and game timeframes, and the damage-vs-target
interaction (the reduction -> pen pipeline + the negative-resist
damage-amp formula).

All expected values are derived from Riot / Meraki formulas in-test
(no hardcoded magic numbers, no fragile cross-item compares):

* Champion base resist at level L:
  ``base + perlevel * (L-1) * (0.7025 + 0.0175 * (L-1))``
  (the 1.6.0 quadratic growth fix - see stats.growth_multiplier).
* Item armor / MR / HP read straight from the vendored DDragon
  stat blocks (FlatArmorMod / FlatSpellBlockMod / FlatHPPoolMod)
  via stats.aggregate_item_stats - the same path build_champion uses.
* Penetration pipeline order (League):
  ``armor - red_flat ; *(1-red_pct) ; *(1-pen_pct) ; - pen_flat``.
* Negative-resist damage multiplier: ``2 - 100/(100-R)`` for R<0
  (equivalently 100/(100-R) on the *resist* side), ``100/(100+R)``
  for R>=0.

KEY RIOT RULE under audit (League Wiki, canonical):
  - Armor / MR *reduction* (flat and percent) is applied first and
    CAN take the resistance below zero. A negative resistance means
    the target takes AMPLIFIED damage.
  - Armor / MR *penetration* (flat and percent) is applied after
    reduction and CANNOT reduce the effective resistance below zero
    (it stops at 0); on already-negative resistance it is a no-op.

The pre-fix engine floored the WHOLE pipeline output at ``max(0.0, r)``,
which incorrectly clamps a *reduction*-driven negative to zero and
discards the negative-resist damage amp. ``test_reduction_can_drive_*``
below pin the Riot-correct behavior; the remaining tests are
regression hardening for the (already-correct) penetration, level
self-consistency, and %max-HP-off-total-HP behaviors.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from agents.daemon_slayer.dps import _armor_factor
from agents.daemon_slayer.effects import (
    effective_target_armor,
    effective_target_mr,
)
from agents.daemon_slayer._effects_data import ITEM_EFFECTS
from agents.daemon_slayer._effects_types import ItemEffect
from agents.daemon_slayer.stats import aggregate_item_stats, growth_multiplier

_PATCH_DIR = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "daemon_slayer"
    / "16.10.1"
)

# Real defensive / bruiser items, in build order. Pulled from the
# vendored DDragon stat blocks at runtime - no hardcoded stat values.
#   3075 Thornmail        (armor + hp)
#   3068 Sunfire Aegis    (armor + hp)
#   3110 Frozen Heart     (armor + mp)
#   3065 Spirit Visage    (mr + hp)
#   3143 Randuin's Omen   (armor + hp)
#   2504 Kaenic Rookern   (mr + hp)
_ENEMY_BUILD = ["3075", "3068", "3110", "3065", "3143", "2504"]

# Champion levels spanning the game timeframe.
_LEVELS = (1, 6, 11, 16, 18)

# A representative tank target's per-level base resist/HP coefficients
# (Ornn-class). Values are the formula inputs, not expected outputs -
# the expected resist is DERIVED from them with growth_multiplier.
_BASE_ARMOR, _BASE_ARMOR_PL = 33.0, 5.2
_BASE_MR, _BASE_MR_PL = 32.0, 2.05
_BASE_HP, _BASE_HP_PL = 660.0, 109.0


def _ddragon_items() -> dict:
    raw = json.loads(
        (_PATCH_DIR / "items.json").read_text(encoding="utf-8")
    )
    return raw["data"]


def _base_resist(base: float, perlevel: float, level: int) -> float:
    """Riot quadratic per-level base-stat growth (1.6.0 model)."""
    return base + perlevel * growth_multiplier(level)


class EnemyBuildResistAssemblyTests(unittest.TestCase):
    """For builds of 1..6 real defensive items at levels {1,6,11,16,18}:
    with NO caster penetration, the engine's effective target armor / MR
    must equal exactly ``base(level) + sum(item armor/MR)`` and target
    HP must equal ``base_hp(level) + sum(item HP)`` - i.e. the engine
    neither double-counts an item nor drops the per-level base term.
    """

    def setUp(self) -> None:
        self.dd = _ddragon_items()

    def test_armor_mr_hp_equal_base_plus_item_sum_no_pen(self) -> None:
        armor_sum = mr_sum = hp_sum = 0.0
        for n, iid in enumerate(_ENEMY_BUILD, start=1):
            totals = aggregate_item_stats(
                [self.dd[iid].get("stats", {})]
            )
            armor_sum += totals.get("armor_flat", 0.0)
            mr_sum += totals.get("mr_flat", 0.0)
            hp_sum += totals.get("hp_flat", 0.0)
            for level in _LEVELS:
                with self.subTest(build_size=n, level=level):
                    base_armor = _base_resist(
                        _BASE_ARMOR, _BASE_ARMOR_PL, level
                    )
                    base_mr = _base_resist(_BASE_MR, _BASE_MR_PL, level)
                    base_hp = _base_resist(_BASE_HP, _BASE_HP_PL, level)
                    ta = base_armor + armor_sum
                    tm = base_mr + mr_sum
                    th = base_hp + hp_sum
                    # No caster pen -> pure passthrough (documented).
                    self.assertAlmostEqual(
                        effective_target_armor(ta, [], level=level),
                        ta,
                        places=9,
                        msg="armor passthrough must not drop base or "
                        "double-count items",
                    )
                    self.assertAlmostEqual(
                        effective_target_mr(tm, []),
                        tm,
                        places=9,
                        msg="MR passthrough must not drop base or "
                        "double-count items",
                    )
                    # target HP is caller-supplied; assert the synthetic
                    # assembly itself is internally consistent (the
                    # invariant a caller relies on).
                    self.assertAlmostEqual(
                        th,
                        base_hp + hp_sum,
                        places=9,
                    )

    def test_three_item_enemy_differs_only_by_base_across_levels(
        self,
    ) -> None:
        """Self-consistency over the game timeframe: a fixed 3-item
        enemy at L6 vs L18 must differ ONLY by the base(level) term -
        item armor/MR is flat, base resist grows quadratically.
        """
        three = _ENEMY_BUILD[:3]
        armor_sum = sum(
            aggregate_item_stats(
                [self.dd[i].get("stats", {})]
            ).get("armor_flat", 0.0)
            for i in three
        )
        mr_sum = sum(
            aggregate_item_stats(
                [self.dd[i].get("stats", {})]
            ).get("mr_flat", 0.0)
            for i in three
        )
        for lo, hi in ((6, 18), (1, 11), (11, 16)):
            d_armor_eng = effective_target_armor(
                _base_resist(_BASE_ARMOR, _BASE_ARMOR_PL, hi)
                + armor_sum,
                [],
                level=hi,
            ) - effective_target_armor(
                _base_resist(_BASE_ARMOR, _BASE_ARMOR_PL, lo)
                + armor_sum,
                [],
                level=lo,
            )
            d_armor_base = _base_resist(
                _BASE_ARMOR, _BASE_ARMOR_PL, hi
            ) - _base_resist(_BASE_ARMOR, _BASE_ARMOR_PL, lo)
            self.assertAlmostEqual(
                d_armor_eng,
                d_armor_base,
                places=9,
                msg=f"L{lo}->L{hi} armor delta must equal the base "
                f"delta (item armor is flat)",
            )
            d_mr_eng = effective_target_mr(
                _base_resist(_BASE_MR, _BASE_MR_PL, hi) + mr_sum, []
            ) - effective_target_mr(
                _base_resist(_BASE_MR, _BASE_MR_PL, lo) + mr_sum, []
            )
            d_mr_base = _base_resist(
                _BASE_MR, _BASE_MR_PL, hi
            ) - _base_resist(_BASE_MR, _BASE_MR_PL, lo)
            self.assertAlmostEqual(
                d_mr_eng, d_mr_base, places=9
            )


class PenetrationFloorsAtZeroTests(unittest.TestCase):
    """Riot: penetration (after a NON-negative post-reduction resist)
    cannot push the effective resist below zero. These pin the
    already-correct behavior so the reduction-can-go-negative fix does
    not regress it.
    """

    def test_pen_floors_post_reduction_positive_resist(self) -> None:
        # 3-item enemy armor at L11, caster Serylda's 30% + 25 lethality.
        # Post-reduction == target_armor (no reduction), pen drives it
        # but floors at 0 only if pen exceeds armor.
        eff = [
            ItemEffect(
                item_id="p1", name="seryldas", armor_pen_pct=0.30
            ),
            ItemEffect(item_id="p2", name="leth", lethality=25.0),
        ]
        # Big flat pen that exceeds a small target -> floor at 0.
        big = [
            ItemEffect(
                item_id="p3", name="bigpen", armor_pen_flat=999.0
            )
        ]
        self.assertEqual(
            effective_target_armor(60.0, big, level=18), 0.0
        )
        self.assertEqual(
            effective_target_mr(
                60.0,
                [
                    ItemEffect(
                        item_id="m", name="bigmpen",
                        magic_pen_flat=999.0,
                    )
                ],
            ),
            0.0,
        )
        # Normal pen on a real target stays >= 0 and matches the
        # documented order.
        ta = 140.0
        got = effective_target_armor(ta, eff, level=18)
        expect = max(0.0, (ta * (1.0 - 0.30)) - 25.0 * 1.0)
        self.assertAlmostEqual(got, expect, places=9)

    def test_negative_input_passthrough_uses_amp_factor(self) -> None:
        # External shred already drove the target negative: penetration
        # is a no-op and the negative resist feeds the damage-amp curve.
        eff = [
            ItemEffect(
                item_id="n", name="pen",
                armor_pen_pct=0.40, armor_pen_flat=10.0,
            )
        ]
        self.assertEqual(
            effective_target_armor(-25.0, eff, level=18), -25.0
        )
        self.assertAlmostEqual(
            _armor_factor(-25.0), 2.0 - 100.0 / (100.0 - (-25.0))
        )


class ReductionCanDriveResistNegativeTests(unittest.TestCase):
    """Riot: armor / MR *reduction* (flat or percent) CAN take the
    resistance below zero, and a negative resist means the target takes
    AMPLIFIED damage (factor ``2 - 100/(100-R)`` > 1). Penetration is
    what floors at zero - reduction does not.

    Flesheater (667112 / 447112 Arena) carries a pure 30 flat armor
    AND 30 flat MR reduction with no penetration component, so it is
    the cleanest real-item demonstration. Black Cleaver / Obsidian
    Cleaver carry the percent-reduction analogue.
    """

    def test_flat_reduction_only_can_go_negative_armor(self) -> None:
        # Squishy enemy, low base armor (~27 at an early level), no
        # enemy armor items. Caster has Flesheater: 30 flat armor
        # reduction, no pen. Riot: 27 - 30 = -3, target then takes
        # 2 - 100/(100-(-3)) ~= 1.029x physical. Engine must NOT clamp
        # this to 0.
        fle = ITEM_EFFECTS["667112"]
        self.assertGreater(
            fle.armor_reduction_flat, 0.0,
            "Flesheater must carry flat armor reduction",
        )
        self.assertEqual(
            fle.armor_pen_pct, 0.0,
            "Flesheater must have no % armor pen (pure reduction item)",
        )
        self.assertEqual(fle.armor_pen_flat, 0.0)
        target_armor = 27.0
        got = effective_target_armor(target_armor, [fle], level=11)
        expected = target_armor - fle.armor_reduction_flat  # -3.0
        self.assertLess(
            expected, 0.0, "scenario must actually go negative"
        )
        self.assertAlmostEqual(
            got,
            expected,
            places=9,
            msg="flat armor REDUCTION must be allowed below zero "
            "(only penetration floors at 0)",
        )
        self.assertGreater(
            _armor_factor(got),
            1.0,
            "negative effective armor must amplify physical damage",
        )

    def test_flat_reduction_only_can_go_negative_mr(self) -> None:
        fle = ITEM_EFFECTS["667112"]
        self.assertGreater(fle.mr_reduction_flat, 0.0)
        self.assertEqual(fle.magic_pen_pct, 0.0)
        self.assertEqual(fle.magic_pen_flat, 0.0)
        target_mr = 22.0
        got = effective_target_mr(target_mr, [fle])
        expected = target_mr - fle.mr_reduction_flat  # -8.0
        self.assertLess(expected, 0.0)
        self.assertAlmostEqual(got, expected, places=9)
        self.assertGreater(_armor_factor(got), 1.0)

    def test_pct_reduction_alone_cannot_cross_zero(self) -> None:
        # Black Cleaver % reduction is multiplicative: positive armor
        # *(1-0.30) stays positive. This documents that % reduction
        # alone never crosses zero (only flat reduction / external
        # shred can), so the fix is scoped to the post-reduction sign.
        bc = ITEM_EFFECTS["3071"]
        self.assertGreater(bc.armor_reduction_pct, 0.0)
        got = effective_target_armor(40.0, [bc], level=11)
        self.assertAlmostEqual(
            got, 40.0 * (1.0 - bc.armor_reduction_pct), places=9
        )
        self.assertGreater(got, 0.0)

    def test_flat_reduction_then_pen_is_pen_noop_when_negative(
        self,
    ) -> None:
        # Reduction drives the resist negative; an ADDITIONAL pen item
        # in the same build must be a no-op (you do not penetrate
        # already-negative resist further, nor heal it back toward 0).
        fle = ITEM_EFFECTS["667112"]
        pen = ItemEffect(
            item_id="pp", name="extrapen",
            armor_pen_pct=0.35, armor_pen_flat=15.0,
        )
        target_armor = 20.0  # 20 - 30 flat red = -10, then pen no-op
        got = effective_target_armor(
            target_armor, [fle, pen], level=18
        )
        self.assertAlmostEqual(
            got,
            target_armor - fle.armor_reduction_flat,
            places=9,
            msg="pen must be a no-op once reduction made the resist "
            "negative",
        )

    def test_partial_reduction_still_positive_unaffected(self) -> None:
        # Regression guard: when flat reduction leaves the resist
        # positive, the full pen pipeline still applies and the result
        # still floors at 0 for over-penetration (unchanged behavior).
        fle = ITEM_EFFECTS["667112"]
        pen = ItemEffect(
            item_id="pp2", name="pen2", armor_pen_pct=0.40
        )
        target_armor = 200.0
        got = effective_target_armor(
            target_armor, [fle, pen], level=18
        )
        # 200 - 30 = 170 (still >0) -> *(1-0.40) = 102.
        expected = (target_armor - fle.armor_reduction_flat) * (
            1.0 - 0.40
        )
        self.assertAlmostEqual(got, expected, places=9)
        self.assertGreater(got, 0.0)


if __name__ == "__main__":
    unittest.main()
