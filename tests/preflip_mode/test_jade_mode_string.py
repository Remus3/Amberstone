"""RM-141 S2: JADE is a first-class mode string, KIWI_JADE routes to ARAM.

Riot ships JADE and KIWI_JADE as two SEPARATE gameMode tokens (measured in
data/meta_build/ddragon/16.15.1/summoner.json: 16 rows carry JADE, 8 carry
KIWI_JADE). KIWI_JADE is the ARAM-Mayhem-Jade crossover played on the
Howling Abyss, so it belongs to the ARAM coach surface, not the JADE one.
A substring test (`"JADE" in gm`) would swallow KIWI_JADE into JADE, which
is why the exact-equality branch must sit AFTER the ARAM branch. Both
halves are pinned here so neither can regress.
"""
from __future__ import annotations

import unittest

import core.game_snapshot as gs
from core.game_snapshot import (
    ALL_MODES,
    MODE_ARAM,
    MODE_SR,
    GameEnvelope,
    mode_from_game_mode_string,
)
from core.mode_capabilities import (
    MODE_CAPABILITIES,
    _RAW_SR_STRINGS,
    district_config,
    has_capability,
)


class TestJadeModeString(unittest.TestCase):
    def test_jade_maps_to_its_own_mode(self):
        self.assertEqual(mode_from_game_mode_string("JADE"), "JADE")

    def test_kiwi_jade_maps_to_aram_not_jade(self):
        # The single most important assertion in RM-141: the crossover is
        # played on the Howling Abyss, so the ARAM coach surface owns it.
        self.assertEqual(mode_from_game_mode_string("KIWI_JADE"), MODE_ARAM)

    def test_jade_is_case_insensitive(self):
        self.assertEqual(mode_from_game_mode_string("jade"), "JADE")
        self.assertEqual(mode_from_game_mode_string("kiwi_jade"), MODE_ARAM)

    def test_mode_jade_constant_exists_and_is_in_all_modes(self):
        self.assertEqual(getattr(gs, "MODE_JADE", None), "JADE")
        self.assertIn("JADE", ALL_MODES)

    def test_game_envelope_accepts_jade(self):
        env = GameEnvelope(mode="JADE")
        self.assertEqual(env.mode, "JADE")

    def test_classic_still_maps_to_sr(self):
        self.assertEqual(mode_from_game_mode_string("CLASSIC"), MODE_SR)

    def test_kiwi_still_maps_to_aram(self):
        self.assertEqual(mode_from_game_mode_string("KIWI"), MODE_ARAM)

    def test_arena_and_tft_unaffected_by_the_new_branch(self):
        # The JADE branch sits between ARAM and ARENA, so pin the neighbour.
        self.assertEqual(mode_from_game_mode_string("CHERRY"), "ARENA")
        self.assertEqual(mode_from_game_mode_string("TFT"), "TFT")


class TestJadeCapabilities(unittest.TestCase):
    def test_jade_row_exists_and_is_fail_closed(self):
        # Asserting the ROW (not just the accessor) keeps this test from
        # passing vacuously off the fail-closed default for an absent key.
        self.assertIn("JADE", MODE_CAPABILITIES)
        self.assertIs(MODE_CAPABILITIES["JADE"]["has_wards"], False)
        self.assertIsNone(MODE_CAPABILITIES["JADE"]["district_config"])

    def test_jade_has_no_wards(self):
        self.assertIs(has_capability("JADE", "has_wards"), False)
        self.assertIs(has_capability("jade", "has_wards"), False)

    def test_jade_has_no_district_config(self):
        self.assertIsNone(district_config("JADE"))

    def test_kiwi_jade_capabilities_resolve_through_aram(self):
        self.assertIs(has_capability("KIWI_JADE", "has_wards"), False)
        self.assertEqual(district_config("KIWI_JADE"), "aram")

    def test_jade_is_not_smuggled_into_the_raw_sr_allowlist(self):
        # _RAW_SR_STRINGS exists to stop the catch-all SR default leaking SR
        # capabilities; JADE has its own key so it must never appear there.
        self.assertNotIn("JADE", _RAW_SR_STRINGS)
        self.assertNotIn("KIWI_JADE", _RAW_SR_STRINGS)


if __name__ == "__main__":
    unittest.main()
