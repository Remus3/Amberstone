"""Tests for C1 staged-amp block-index routing (item 246, gap-plan Phase C1).

Sion Q + Hwei Q f2 each carry a "Maximum ..." damage block that already models
the charged / isolated ceiling. Rather than an amp (which would double-count the
same value the block holds), route the block-index under ``apply_ability_amps``:

- Hwei Q form 2 (Severing Bolt): default ``"first"`` selects damage-block 0
  ("Magic Damage"); under ``apply_ability_amps`` the route selects damage-block
  1 ("Maximum Damage" = isolated / immobilized + max-missing-HP ceiling, which
  Meraki pre-bakes as a flat value == block0 * the "Maximum Damage Increase" %,
  so NO separate missing-HP coefficient is needed - the route IS the ceiling).
- Sion Q (Decimating Smash): NO gated route - ``champion_block_index.json``
  ``{Q:2}`` already selects the "Maximum Physical Damage" block by default (the
  s191 routing predates this seam), so flag on/off is byte-identical.

Default path (``apply_ability_amps=False``) is byte-identical. Does NOT pin
ENGINE_VERSION (orchestrator owns the bump).
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer._ability_amp_overrides import (
    _STAGED_AMP_BLOCK_ROUTES,
    _staged_amp_block_route_for,
)
from agents.daemon_slayer.ability_dps import compute_ability_dps
from agents.daemon_slayer.data_loader import DataSnapshot

_SNAP = DataSnapshot.load()


def _q(result):
    for s in result.per_spell:
        if s.key == "Q":
            return s
    return None


class RouteRegistryShapeTests(unittest.TestCase):
    def test_hwei_q_f2_routes_to_damage_block_1(self):
        self.assertEqual(_staged_amp_block_route_for("Hwei", "Q", 2), 1)

    def test_sion_q_has_no_staged_route(self):
        # Sion Q is resolved by champion_block_index.json {Q:2}, not a gated route.
        self.assertIsNone(_staged_amp_block_route_for("Sion", "Q", 0))

    def test_unmapped_returns_none(self):
        self.assertIsNone(_staged_amp_block_route_for("Ahri", "Q", 0))

    def test_route_value_is_damage_block_index(self):
        self.assertEqual(_STAGED_AMP_BLOCK_ROUTES[("Hwei", "Q", 2)], 1)


class HweiQF2RouteEngineTests(unittest.TestCase):
    """Hwei Q form 2 routes to the "Maximum Damage" block under the flag."""

    def _q_raw(self, amps):
        r = compute_ability_dps(
            _SNAP, "Hwei", 9, item_ids=[], mode="SR",
            form_index_overrides={"Q": 2}, apply_ability_amps=amps,
        )
        return _q(r).raw_damage_per_cast

    def test_default_is_magic_damage_block0(self):
        # apply_ability_amps=False -> "first" -> damage-block 0 "Magic Damage".
        self.assertAlmostEqual(self._q_raw(False), 160.0)

    def test_flag_on_routes_to_maximum_damage_block1(self):
        # apply_ability_amps=True -> route -> damage-block 1 "Maximum Damage".
        self.assertAlmostEqual(self._q_raw(True), 560.0)


class SionQAlreadyMaxTests(unittest.TestCase):
    """Sion Q already selects the Maximum block by default; the flag is a no-op."""

    def _q_raw(self, amps):
        r = compute_ability_dps(
            _SNAP, "Sion", 9, item_ids=[], mode="SR", apply_ability_amps=amps,
        )
        return _q(r).raw_damage_per_cast

    def test_flag_on_off_byte_identical(self):
        off = self._q_raw(False)
        on = self._q_raw(True)
        self.assertEqual(off, on)
        # And it IS the Maximum block (577.904 itemless L9 rank4), not Minimum.
        self.assertGreater(off, 500.0)


class ByteIdenticalDefaultTests(unittest.TestCase):
    def test_hwei_default_form_unaffected_by_flag(self):
        # The default Hwei Q form is 1 (Devastating Fire); no staged route on it,
        # so flag on/off identical on the default form.
        off = compute_ability_dps(_SNAP, "Hwei", 9, item_ids=[], mode="SR",
                                  apply_ability_amps=False)
        on = compute_ability_dps(_SNAP, "Hwei", 9, item_ids=[], mode="SR",
                                 apply_ability_amps=True)
        self.assertEqual(_q(off).raw_damage_per_cast, _q(on).raw_damage_per_cast)

    def test_unmapped_champion_byte_identical(self):
        off = compute_ability_dps(_SNAP, "Ahri", 9, item_ids=[], mode="SR",
                                  apply_ability_amps=False)
        on = compute_ability_dps(_SNAP, "Ahri", 9, item_ids=[], mode="SR",
                                 apply_ability_amps=True)
        self.assertEqual(off.total_ability_dps, on.total_ability_dps)


class AsciiHygieneTests(unittest.TestCase):
    def test_module_and_test_are_ascii(self):
        import agents.daemon_slayer._ability_amp_overrides as mod
        for path in (mod.__file__, __file__):
            with open(path, "rb") as fh:
                raw = fh.read()
            raw.decode("ascii")


if __name__ == "__main__":
    unittest.main()
