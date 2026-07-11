"""Item-side LOW-HP MAGIC/TRUE amp ("Cinderbloom", Shadowflame) credit to the
burst scorer (R110, ENGINE 1.203.0).

RED-first coverage for the NEW default-OFF ``assume_item_lowhp_magic_crit`` seam
on ``compute_burst_damage``. Today Shadowflame's Cinderbloom passive - "Magic and
true damage Critically Strikes enemies below 40% Health, dealing 20% increased
damage" (DDragon 16.13.1, id 4645; the Arena mirror 224645 deals +15%) - earns
ZERO burst credit: the engine models Shadowflame's 15 flat magic pen but no
magic-crit / low-HP gate exists anywhere in the scorer (self-documented omission
in ``_effects_data.py``). A live delta==0 probe (Xerath L11 + [4645], SR) confirmed
``total_burst_damage`` is byte-identical at target hp_pct 0.41 vs 0.39 today.

A genuinely NEW damage-layer axis: it is GATED on the TARGET's current HP (< 40%,
a NEW gate no item-effects amp uses) and it amplifies TRUE damage as well as MAGIC
(``total_magic_amp_multiplier`` is MAGIC-only and always-on; the existing burst
target-HP gates are the INVERSE high-HP anti-tank direction). Physical damage and
the auto-attack path are NEVER amplified.

Contract:
  * OFF (default) -> item_lowhp_magic_crit_mult == 1.0 -> total_burst_damage
    BYTE-IDENTICAL to the pre-seam value (and an explicit ``False`` run).
  * Target AT OR ABOVE 40% HP, even armed -> identity 1.0 (strict-below gate).
  * ON + a carrier + target < 40% -> item_lowhp_magic_crit_mult == 1 + amp
    (4645 -> 1.20, Arena 224645 -> 1.15) and the burst delta equals EXACTLY
    ``amp * (magic + true portion)`` - proving physical is excluded.
  * A non-carrier build with the flag ON does NOT leak credit (mult 1.0,
    byte-identical).
"""
from __future__ import annotations

import math
import unittest

from agents.daemon_slayer._item_lowhp_magic_crit import (
    _ITEM_LOWHP_MAGIC_CRIT,
    _LOWHP_THRESHOLD,
    item_lowhp_magic_crit_amp,
)
from agents.daemon_slayer.ability_dps import compute_ability_dps
from agents.daemon_slayer.burst import compute_burst_damage
from agents.daemon_slayer.data_loader import DataSnapshot

_SNAP: DataSnapshot | None = None


def _snap() -> DataSnapshot:
    global _SNAP
    if _SNAP is None:
        _SNAP = DataSnapshot.load()
    return _SNAP


def _burst(*, champ="Xerath", items=("4645",), hp_pct, on, level=11):
    return compute_burst_damage(
        _snap(), champ, level, item_ids=list(items), mode="SR",
        target_armor=60.0, target_mr=40.0, target_max_hp=2000.0,
        target_current_hp_pct=hp_pct, assume_item_lowhp_magic_crit=on,
    )


def _magic_true_ability_portion(result) -> float:
    """Sum the MAGIC + TRUE ability final damage of an OFF run (the amp base).

    Mirrors the engine site-#1 gate: ``dt = (form.damage_type or "MAGIC")`` so a
    null-typed cast counts as MAGIC exactly where the fold amplifies it. Auto
    attacks (physical) are excluded - they are never amplified.
    """
    return sum(
        c.final_damage
        for c in result.per_cast
        if c.is_ability and (c.damage_type or "MAGIC").upper() in ("MAGIC", "TRUE")
    )


# ---------------- registry unit ----------------


class LowHpMagicCritRegistryTests(unittest.TestCase):
    def test_off_is_identity(self) -> None:
        self.assertEqual(
            item_lowhp_magic_crit_amp(["4645"], 0.39, assume_item_lowhp_magic_crit=False),
            1.0,
        )

    def test_sr_shadowflame_is_1_20_below_threshold(self) -> None:
        self.assertEqual(
            item_lowhp_magic_crit_amp(["4645"], 0.39, assume_item_lowhp_magic_crit=True),
            1.20,
        )

    def test_arena_mirror_is_1_15_below_threshold(self) -> None:
        self.assertEqual(
            item_lowhp_magic_crit_amp(["224645"], 0.39, assume_item_lowhp_magic_crit=True),
            1.15,
        )

    def test_gate_is_strictly_below_forty(self) -> None:
        # exactly at 0.40 -> identity (below-only); above -> identity.
        self.assertEqual(
            item_lowhp_magic_crit_amp(["4645"], _LOWHP_THRESHOLD, assume_item_lowhp_magic_crit=True),
            1.0,
        )
        self.assertEqual(
            item_lowhp_magic_crit_amp(["4645"], 0.41, assume_item_lowhp_magic_crit=True),
            1.0,
        )

    def test_two_carriers_take_max_not_product(self) -> None:
        # UNIQUE Cinderbloom over a shared pool -> MAX, never product (two 4645
        # cannot double to 1.44; SR + Arena picks the stronger 0.20).
        self.assertEqual(
            item_lowhp_magic_crit_amp(["4645", "4645"], 0.39, assume_item_lowhp_magic_crit=True),
            1.20,
        )
        self.assertEqual(
            item_lowhp_magic_crit_amp(["224645", "4645"], 0.39, assume_item_lowhp_magic_crit=True),
            1.20,
        )

    def test_unknown_item_is_identity(self) -> None:
        self.assertEqual(
            item_lowhp_magic_crit_amp(["3020"], 0.39, assume_item_lowhp_magic_crit=True), 1.0
        )

    def test_empty_build_is_identity(self) -> None:
        self.assertEqual(
            item_lowhp_magic_crit_amp([], 0.39, assume_item_lowhp_magic_crit=True), 1.0
        )

    def test_registered_ids_are_exactly_the_two(self) -> None:
        self.assertEqual(set(_ITEM_LOWHP_MAGIC_CRIT), {"4645", "224645"})
        self.assertEqual(_ITEM_LOWHP_MAGIC_CRIT["4645"], 0.20)
        self.assertEqual(_ITEM_LOWHP_MAGIC_CRIT["224645"], 0.15)


# ---------------- OFF byte-identical ----------------


class LowHpMagicCritOffByteIdenticalTests(unittest.TestCase):
    def test_flag_absent_equals_explicit_false(self) -> None:
        absent = compute_burst_damage(
            _snap(), "Xerath", 11, item_ids=["4645"], mode="SR",
            target_armor=60.0, target_mr=40.0, target_max_hp=2000.0,
            target_current_hp_pct=0.39,
        )
        off = _burst(hp_pct=0.39, on=False)
        self.assertAlmostEqual(
            absent.total_burst_damage, off.total_burst_damage, places=9
        )

    def test_off_mult_is_identity(self) -> None:
        self.assertEqual(_burst(hp_pct=0.39, on=False).item_lowhp_magic_crit_mult, 1.0)


# ---------------- gate (target HP threshold) ----------------


class LowHpMagicCritGateTests(unittest.TestCase):
    def test_armed_above_threshold_is_byte_identical(self) -> None:
        # target NOT below 40% -> the amp never fires even armed.
        off = _burst(hp_pct=0.41, on=False)
        on = _burst(hp_pct=0.41, on=True)
        self.assertEqual(on.item_lowhp_magic_crit_mult, 1.0)
        self.assertAlmostEqual(on.total_burst_damage, off.total_burst_damage, places=9)

    def test_armed_at_exactly_threshold_is_identity(self) -> None:
        on = _burst(hp_pct=_LOWHP_THRESHOLD, on=True)
        self.assertEqual(on.item_lowhp_magic_crit_mult, 1.0)

    def test_amp_fires_below_threshold(self) -> None:
        off = _burst(hp_pct=0.39, on=False)
        on = _burst(hp_pct=0.39, on=True)
        self.assertEqual(on.item_lowhp_magic_crit_mult, 1.20)
        self.assertGreater(on.total_burst_damage, off.total_burst_damage)


# ---------------- ON credit magnitude (magic + TRUE only) ----------------


class LowHpMagicCritMagnitudeTests(unittest.TestCase):
    def test_delta_equals_amp_times_magic_true_portion(self) -> None:
        # THE correctness assertion: the burst rises by EXACTLY amp * (magic+true
        # portion). If physical were amplified the delta would exceed this, so the
        # equality proves physical / AA exclusion precisely.
        off = _burst(hp_pct=0.39, on=False)
        on = _burst(hp_pct=0.39, on=True)
        magic_true = _magic_true_ability_portion(off)
        self.assertGreater(magic_true, 0.0)  # Xerath is a pure-magic caster
        self.assertAlmostEqual(
            on.total_burst_damage,
            off.total_burst_damage + 0.20 * magic_true,
            places=6,
        )

    def test_auto_attack_portion_is_never_amplified(self) -> None:
        off = _burst(hp_pct=0.39, on=False)
        on = _burst(hp_pct=0.39, on=True)
        self.assertAlmostEqual(
            on.auto_attack_damage, off.auto_attack_damage, places=9
        )

    def test_arena_mirror_mult_is_1_15(self) -> None:
        on = _burst(items=("224645",), hp_pct=0.39, on=True)
        self.assertEqual(on.item_lowhp_magic_crit_mult, 1.15)


# ---------------- isolation (no leak) ----------------


class LowHpMagicCritIsolationTests(unittest.TestCase):
    def test_non_carrier_build_flag_on_is_byte_identical(self) -> None:
        # Sorcerer's Shoes (3020) carries no Cinderbloom; arming the seam must not
        # leak any amp even against a sub-40% target.
        off = _burst(items=("3020",), hp_pct=0.39, on=False)
        on = _burst(items=("3020",), hp_pct=0.39, on=True)
        self.assertEqual(on.item_lowhp_magic_crit_mult, 1.0)
        self.assertAlmostEqual(
            on.total_burst_damage, off.total_burst_damage, places=9
        )


# ---------------- to_dict ----------------


class LowHpMagicCritToDictTests(unittest.TestCase):
    def test_to_dict_carries_field(self) -> None:
        r = _burst(hp_pct=0.39, on=True)
        d = r.to_dict()
        self.assertIn("item_lowhp_magic_crit_mult", d)
        self.assertTrue(
            math.isclose(d["item_lowhp_magic_crit_mult"], r.item_lowhp_magic_crit_mult)
        )
        self.assertEqual(d["item_lowhp_magic_crit_mult"], 1.20)


# ---------------- API symmetry (inert on compute_ability_dps) ----------------


class LowHpMagicCritInertOnDpsTests(unittest.TestCase):
    def test_dps_accepts_kwarg_and_is_inert(self) -> None:
        # compute_ability_dps accepts assume_item_lowhp_magic_crit for caller API
        # symmetry with compute_burst_damage but is DELIBERATELY INERT here
        # (mirrors assume_physical_burst / assume_shielded_target). The amp is a
        # burst-only valuation; sustained DPS is unchanged ON or OFF.
        off = compute_ability_dps(
            _snap(), "Xerath", 11, item_ids=["4645"], mode="SR",
            target_armor=60.0, target_max_hp=2000.0,
            assume_item_lowhp_magic_crit=False,
        )
        on = compute_ability_dps(
            _snap(), "Xerath", 11, item_ids=["4645"], mode="SR",
            target_armor=60.0, target_max_hp=2000.0,
            assume_item_lowhp_magic_crit=True,
        )
        self.assertEqual(on.total_ability_dps, off.total_ability_dps)


if __name__ == "__main__":
    unittest.main()
