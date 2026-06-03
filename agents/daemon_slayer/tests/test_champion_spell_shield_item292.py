"""Item 292 (ENGINE 1.104.0) - champion spell-shield / block-one CC registry tests.

The EIGHTH survivability axis: a champion's SELF spell-shield / single-CC-instance
block ABILITY (Sivir E / Nocturne W / Fiora W / Morgana E self) feeds the
cc_blended discount (it negates one incoming CC instance the caster would eat ->
a larger cc_blended_ehp), the block-one sibling of the item-290 tenacity axis.
Proves (a) the default path is byte-identical, (b) the on path produces the
hand-verified block fraction at a pinned input, (c) the discount is a SEPARATE
seam that composes with tenacity, and (d) the documented exclusions.
"""
from __future__ import annotations

import math
import unittest

from agents.daemon_slayer._champion_spell_shield_overrides import (
    _CHAMPION_SPELL_SHIELD_OVERRIDES,
    _SPELL_SHIELD_DURATION_PROB,
    _SPELL_SHIELD_PARRY_PROB,
    _SPELL_SHIELD_REACTIVE_PROB,
    champion_spell_shield_fraction,
)
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import compute_ehp

_SNAP: DataSnapshot | None = None


def _snap() -> DataSnapshot:
    global _SNAP
    if _SNAP is None:
        _SNAP = DataSnapshot.load()
    return _SNAP


class RegistryFractionTests(unittest.TestCase):
    def test_flag_off_is_zero(self):
        # The default (flag False) returns 0.0 for every champion - byte-identical.
        for cid in ("Sivir", "Nocturne", "Fiora", "Morgana", "Ashe"):
            self.assertEqual(
                champion_spell_shield_fraction(cid, 18, False), 0.0
            )

    def test_unregistered_champion_is_zero_even_on(self):
        self.assertEqual(champion_spell_shield_fraction("Ashe", 18, True), 0.0)

    def test_sivir_reactive_value(self):
        # Sivir E: 100% block of the next effect, amortized at the reactive midpoint.
        frac = champion_spell_shield_fraction("Sivir", 18, True)
        self.assertAlmostEqual(frac, 1.0 * _SPELL_SHIELD_REACTIVE_PROB, places=9)

    def test_nocturne_reactive_value(self):
        frac = champion_spell_shield_fraction("Nocturne", 18, True)
        self.assertAlmostEqual(frac, 1.0 * _SPELL_SHIELD_REACTIVE_PROB, places=9)

    def test_fiora_parry_value(self):
        # Fiora W: a sub-second pre-timed parry, amortized at the lower parry midpoint.
        frac = champion_spell_shield_fraction("Fiora", 18, True)
        self.assertAlmostEqual(frac, 1.0 * _SPELL_SHIELD_PARRY_PROB, places=9)

    def test_morgana_self_sustained_value(self):
        # Morgana E (self cast): 5s CC-immunity shield, the higher sustained midpoint.
        frac = champion_spell_shield_fraction("Morgana", 18, True)
        self.assertAlmostEqual(frac, 1.0 * _SPELL_SHIELD_DURATION_PROB, places=9)

    def test_fraction_bounded_below_one(self):
        for cid in ("Sivir", "Nocturne", "Fiora", "Morgana"):
            frac = champion_spell_shield_fraction(cid, 18, True)
            self.assertGreater(frac, 0.0)
            self.assertLess(frac, 1.0)

    def test_registry_is_exactly_the_four_self_entries(self):
        keys = set(_CHAMPION_SPELL_SHIELD_OVERRIDES)
        self.assertEqual(
            keys,
            {
                ("Sivir", "E", 0),
                ("Nocturne", "W", 0),
                ("Fiora", "W", 0),
                ("Morgana", "E", 0),
            },
        )

    def test_excluded_champions_absent(self):
        # Champion-innate tenacity/immunity (item 290: Garen/Olaf/Malzahar),
        # cast-bound engage immunity (Galio R), area/projectile walls (Yasuo W /
        # Shen W), and untargetable/stasis windows (Vladimir/Fizz/Kayle) are NOT
        # seeded in the spell-shield block-one registry.
        for cid in (
            "Garen", "Olaf", "Malzahar", "Galio", "Yasuo", "Shen",
            "Vladimir", "Fizz", "Kayle",
        ):
            self.assertEqual(champion_spell_shield_fraction(cid, 18, True), 0.0)


class ComputeEhpSeamTests(unittest.TestCase):
    # A SINGLE-enemy comp: keeps cc_pressure_fraction UNCLAMPED (the 3-champ heavy
    # comp saturates min(pressure/_FIGHT_WINDOW_S=6.0, 1.0) at 1.0, hiding the
    # cc_blended_ehp delta even though enemy_cc_pressure_s still drops). The heavy
    # comp is exercised separately in test_heavy_comp_reduces_pressure_under_clamp.
    ENEMIES = ("Leona",)
    HEAVY = ("Leona", "Morgana", "Annie")

    def _ehp(self, champ, *, on, enemies=ENEMIES, items=None):
        return compute_ehp(
            _snap(), champion_id=champ, level=18,
            item_ids=items or (), mode="SR",
            enemy_champions=enemies,
            apply_spell_shield=on,
        )

    def test_default_off_field_zero(self):
        off = self._ehp("Sivir", on=False)
        self.assertEqual(off.spell_shield_frac, 0.0)

    def test_no_enemy_comp_field_still_populated(self):
        # With no enemy comp the cc discount is inert, but the block fraction field
        # is still surfaced for a future consumer.
        r = compute_ehp(
            _snap(), champion_id="Sivir", level=18, item_ids=(), mode="SR",
            enemy_champions=(), apply_spell_shield=True,
        )
        self.assertGreater(r.spell_shield_frac, 0.0)
        self.assertAlmostEqual(r.cc_blended_ehp, r.blended_ehp, places=6)

    def test_spell_shield_raises_cc_blended_ehp(self):
        # A spell-shield champion negates one enemy CC instance -> a LARGER
        # cc_blended_ehp than the same champion with the flag off.
        off = self._ehp("Sivir", on=False)
        on = self._ehp("Sivir", on=True)
        self.assertAlmostEqual(on.blended_ehp, off.blended_ehp, places=6)
        self.assertGreater(on.cc_blended_ehp, off.cc_blended_ehp)
        self.assertAlmostEqual(
            on.spell_shield_frac, _SPELL_SHIELD_REACTIVE_PROB, places=9
        )

    def test_heavy_comp_reduces_pressure_under_clamp(self):
        # Under a heavy 3-champ comp the cc_pressure_fraction clamps at 1.0 so
        # cc_blended_ehp can be byte-identical, but the axis still fires: the block
        # discount strictly LOWERS enemy_cc_pressure_s (the quantity it reduces).
        off = self._ehp("Sivir", on=False, enemies=self.HEAVY)
        on = self._ehp("Sivir", on=True, enemies=self.HEAVY)
        self.assertLess(on.enemy_cc_pressure_s, off.enemy_cc_pressure_s)
        self.assertAlmostEqual(
            on.enemy_cc_pressure_s,
            off.enemy_cc_pressure_s * (1.0 - _SPELL_SHIELD_REACTIVE_PROB),
            places=6,
        )

    def test_unregistered_champion_unchanged_by_flag(self):
        # Ashe has no spell-shield: flag on/off identical cc_blended_ehp.
        off = self._ehp("Ashe", on=False)
        on = self._ehp("Ashe", on=True)
        self.assertAlmostEqual(on.cc_blended_ehp, off.cc_blended_ehp, places=6)
        self.assertEqual(on.spell_shield_frac, 0.0)

    def test_separate_seam_from_champion_tenacity(self):
        # The spell-shield flag does NOT touch champion_tenacity_frac, and the
        # tenacity flag does NOT touch spell_shield_frac - independent axes. Use a
        # champ that has BOTH? None overlap, so assert each flag only lights its own
        # field for a spell-shield champ (Sivir has no innate tenacity).
        r = compute_ehp(
            _snap(), champion_id="Sivir", level=18, item_ids=(), mode="SR",
            enemy_champions=self.ENEMIES,
            apply_spell_shield=True, apply_champion_tenacity=True,
        )
        self.assertGreater(r.spell_shield_frac, 0.0)
        self.assertEqual(r.champion_tenacity_frac, 0.0)

    def test_composes_with_item_tenacity(self):
        # Spell-shield (Sivir) + item tenacity (Mercury's 3111): the block discount
        # applies AFTER the tenacity-scaled pressure, so both-on erodes strictly
        # more CC than either alone -> cc_blended(both) >= cc_blended(shield_only).
        both = compute_ehp(
            _snap(), champion_id="Sivir", level=18, item_ids=("3111",),
            mode="SR", enemy_champions=self.ENEMIES,
            apply_build_tenacity=True, apply_spell_shield=True,
        )
        shield_only = compute_ehp(
            _snap(), champion_id="Sivir", level=18, item_ids=("3111",),
            mode="SR", enemy_champions=self.ENEMIES,
            apply_build_tenacity=False, apply_spell_shield=True,
        )
        self.assertGreaterEqual(both.cc_blended_ehp, shield_only.cc_blended_ehp)

    def test_other_flag_paths_unaffected_by_new_flag(self):
        # Regression: with apply_spell_shield default-off, a spell-shield champ's
        # cc_blended_ehp is unchanged whether the new flag is omitted or explicit
        # False (proves the new flag gates the discount off cleanly).
        a = compute_ehp(
            _snap(), champion_id="Sivir", level=18, item_ids=(),
            mode="SR", enemy_champions=self.ENEMIES,
        )
        b = compute_ehp(
            _snap(), champion_id="Sivir", level=18, item_ids=(),
            mode="SR", enemy_champions=self.ENEMIES,
            apply_spell_shield=False,
        )
        self.assertAlmostEqual(a.cc_blended_ehp, b.cc_blended_ehp, places=9)


class ToDictTests(unittest.TestCase):
    def test_to_dict_carries_field(self):
        r = compute_ehp(
            _snap(), champion_id="Sivir", level=18, item_ids=(), mode="SR",
            enemy_champions=("Leona",), apply_spell_shield=True,
        )
        d = r.to_dict()
        self.assertIn("spell_shield_frac", d)
        self.assertTrue(math.isclose(
            d["spell_shield_frac"], _SPELL_SHIELD_REACTIVE_PROB
        ))


if __name__ == "__main__":
    unittest.main()
