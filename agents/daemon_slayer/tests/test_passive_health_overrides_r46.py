"""R46 - effects-text-only STACKING permanent max-HP passive registry tests.

A NEW survivability axis: champion passives that grant PERMANENT bonus maximum
health PER STACK and stack (effectively) without bound over a game - Sion W Soul
Furnace (+4 health per kill, +15 large/champ), Cho'Gath R Feast (+80/120/160 per
Feast stack by rank), Swain P Ravenous Flock (+15 per Soul Fragment). This is NOT
in the resolved stat block (not base-per-level, not an item), so the EHP scorer
never saw it. A permanent bonus max-HP sits at the TOP of the damage stack exactly
like ``ext_flat_hp`` / ``flat_mit_*`` - it adds RAW to every per-type numerator and
rides the SAME armor/MR curve.

``assume_passive_health_stacks`` defaults False -> ``passive_health_stack_hp``
returns 0.0 -> every EHP numerator is byte-identical to ENGINE 1.160.0.

The hp-per-stack value is EXACT from the verbatim 16.13.1 Meraki truth
(``data/daemon_slayer/16.13.1/champion_abilities.json`` effects_descriptions +
the parsed Feast 'Bonus Health Per Stack' damage_block [80,120,160]); only the
assumed STACK COUNT by level is an operator-tunable conservative midpoint (the
live stack feed we lack), the analog of ``_REVIVE_PROB`` /
``_ASSUMED_FLAT_DR_INSTANCES``.
"""
from __future__ import annotations

import dataclasses
import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import compute_ehp
from agents.daemon_slayer._passive_health_overrides import (
    PassiveHealthEntry,
    _PASSIVE_HEALTH_OVERRIDES,
    _hp_per_stack_at_level,
    _stacks_at_level,
    passive_health_stack_hp,
)

_SNAP = DataSnapshot.load()

# An unregistered champion (no stacking-HP entry) for the no-spurious-effect +
# byte-identical-OFF-and-ON checks.
_UNREG = "Garen"


def _ehp(cid, lvl=11, items=(), **kw):
    return compute_ehp(_SNAP, champion_id=cid, level=lvl, item_ids=items, mode="SR", **kw)


class RegistryShapeTests(unittest.TestCase):
    def test_exactly_three_seeds(self):
        self.assertEqual(len(_PASSIVE_HEALTH_OVERRIDES), 3)

    def test_keys_are_the_seeded_set(self):
        self.assertEqual(
            set(_PASSIVE_HEALTH_OVERRIDES),
            {
                ("Sion", "W", 0),
                ("Chogath", "R", 0),
                ("Swain", "P", 0),
            },
        )

    def test_assumed_stacks_is_eighteen_levels_monotonic_nonneg(self):
        for entry in _PASSIVE_HEALTH_OVERRIDES.values():
            self.assertEqual(len(entry.assumed_stacks_by_level), 18)
            prev = -1.0
            for s in entry.assumed_stacks_by_level:
                self.assertGreaterEqual(s, 0.0)
                self.assertGreaterEqual(s, prev)  # non-decreasing by level
                prev = s

    def test_every_entry_has_a_nonempty_note(self):
        for entry in _PASSIVE_HEALTH_OVERRIDES.values():
            self.assertTrue(entry.note.strip())

    def test_entry_is_frozen(self):
        entry = _PASSIVE_HEALTH_OVERRIDES[("Sion", "W", 0)]
        with self.assertRaises(dataclasses.FrozenInstanceError):
            entry.hp_per_stack = 99.0  # type: ignore[misc]


class CharacterizationTests(unittest.TestCase):
    """Each seed's hp-per-stack matches the verbatim cited 16.13.1 Meraki truth."""

    def test_sion_w_flat_four_per_stack(self):
        # "Sion gains 4 bonus health whenever he kills an enemy" (the conservative
        # bulk-farm value; the +15 large/champ case is the rarer omitted upside).
        entry = _PASSIVE_HEALTH_OVERRIDES[("Sion", "W", 0)]
        self.assertEqual(entry.hp_per_stack, 4.0)
        self.assertFalse(entry.level_scaled_hp)

    def test_swain_p_flat_fifteen_per_fragment(self):
        # "For each stack, Swain gains 15 bonus health permanently."
        entry = _PASSIVE_HEALTH_OVERRIDES[("Swain", "P", 0)]
        self.assertEqual(entry.hp_per_stack, 15.0)
        self.assertFalse(entry.level_scaled_hp)

    def test_chogath_r_feast_rank_block_80_120_160(self):
        # Feast 'Bonus Health Per Stack' damage_block [80,120,160] by R rank,
        # resolved per champion level (no ult below 6 -> 0; R1 6-10, R2 11-15,
        # R3 16-18).
        entry = _PASSIVE_HEALTH_OVERRIDES[("Chogath", "R", 0)]
        self.assertTrue(entry.level_scaled_hp)
        hp = entry.hp_per_stack
        self.assertEqual(len(hp), 18)
        self.assertEqual(hp[4], 0.0)   # level 5: no ult yet
        self.assertEqual(hp[5], 80.0)  # level 6: R1
        self.assertEqual(hp[10], 120.0)  # level 11: R2
        self.assertEqual(hp[15], 160.0)  # level 16: R3
        # the three rank values are exactly the Meraki block.
        self.assertEqual(set(v for v in hp if v > 0), {80.0, 120.0, 160.0})


class PassiveHealthStackHpTests(unittest.TestCase):
    def test_off_returns_zero(self):
        self.assertEqual(passive_health_stack_hp("Sion", 11, False), 0.0)
        self.assertEqual(passive_health_stack_hp("Chogath", 16, False), 0.0)
        self.assertEqual(passive_health_stack_hp("Swain", 11, False), 0.0)

    def test_unregistered_champ_zero_even_on(self):
        self.assertEqual(passive_health_stack_hp(_UNREG, 11, True), 0.0)

    def test_sion_equals_hp_per_stack_times_stacks(self):
        entry = _PASSIVE_HEALTH_OVERRIDES[("Sion", "W", 0)]
        for lvl in (1, 6, 11, 18):
            expected = _hp_per_stack_at_level(
                entry.hp_per_stack, lvl, entry.level_scaled_hp
            ) * _stacks_at_level(entry.assumed_stacks_by_level, lvl)
            self.assertAlmostEqual(passive_health_stack_hp("Sion", lvl, True), expected)
            self.assertGreater(expected, 0.0)

    def test_swain_equals_hp_per_stack_times_stacks(self):
        entry = _PASSIVE_HEALTH_OVERRIDES[("Swain", "P", 0)]
        for lvl in (6, 11, 18):
            expected = 15.0 * _stacks_at_level(entry.assumed_stacks_by_level, lvl)
            self.assertAlmostEqual(passive_health_stack_hp("Swain", lvl, True), expected)

    def test_chogath_zero_below_ult_then_rank_scaled(self):
        # No ult below level 6 -> no Feast HP.
        self.assertEqual(passive_health_stack_hp("Chogath", 5, True), 0.0)
        entry = _PASSIVE_HEALTH_OVERRIDES[("Chogath", "R", 0)]
        for lvl in (6, 11, 16, 18):
            expected = _hp_per_stack_at_level(
                entry.hp_per_stack, lvl, entry.level_scaled_hp
            ) * _stacks_at_level(entry.assumed_stacks_by_level, lvl)
            self.assertAlmostEqual(passive_health_stack_hp("Chogath", lvl, True), expected)
        self.assertGreater(passive_health_stack_hp("Chogath", 18, True), 0.0)

    def test_monotonic_nondecreasing_in_level(self):
        for cid in ("Sion", "Swain", "Chogath"):
            prev = -1.0
            for lvl in range(1, 19):
                cur = passive_health_stack_hp(cid, lvl, True)
                self.assertGreaterEqual(cur, prev)
                prev = cur


class EhpByteIdenticalTests(unittest.TestCase):
    def test_default_equals_explicit_false_registered_champ(self):
        a = _ehp("Sion")
        b = _ehp("Sion", assume_passive_health_stacks=False)
        self.assertEqual(a.physical_ehp, b.physical_ehp)
        self.assertEqual(a.magical_ehp, b.magical_ehp)
        self.assertEqual(a.true_ehp, b.true_ehp)
        self.assertEqual(a.blended_ehp, b.blended_ehp)

    def test_unregistered_champ_identical_on_vs_off(self):
        off = _ehp(_UNREG)
        on = _ehp(_UNREG, assume_passive_health_stacks=True)
        self.assertEqual(off.physical_ehp, on.physical_ehp)
        self.assertEqual(off.magical_ehp, on.magical_ehp)
        self.assertEqual(off.true_ehp, on.true_ehp)
        self.assertEqual(off.blended_ehp, on.blended_ehp)

    def test_registered_champ_raises_all_three_axes_on(self):
        # A max-HP grant raises EVERY damage-type EHP (incl. true, which ignores
        # resists) - it is a pure numerator add.
        off = _ehp("Sion")
        on = _ehp("Sion", assume_passive_health_stacks=True)
        self.assertGreater(on.physical_ehp, off.physical_ehp)
        self.assertGreater(on.magical_ehp, off.magical_ehp)
        self.assertGreater(on.true_ehp, off.true_ehp)
        self.assertGreater(on.blended_ehp, off.blended_ehp)


class EnginePinTests(unittest.TestCase):
    def test_engine_version(self):
        self.assertEqual(ENGINE_VERSION, "1.190.0")


if __name__ == "__main__":
    unittest.main()
