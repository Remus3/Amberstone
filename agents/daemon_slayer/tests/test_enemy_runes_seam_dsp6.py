"""DSP6 enemy-rune threat seam characterization tests.

Anchors ``agents/daemon_slayer/enemy_runes.py`` - the NEW default-OFF enemy-rune
threat substrate (Press the Attack / Conqueror / Grasp of the Undying / Second
Wind + the non-rune antiheal bucket). Every magnitude is pinned to the DDragon
``runesReforged.json`` 16.12.1 longDesc value cited in the module ``formula``
strings (DDragon is authoritative; never aggregator D / aggregator A). The seam is a PURE
substrate: no live scorer consumes it (``ENEMY_RUNE_SEAM_IDS`` is the marker), so
the live ``/rank`` output is byte-identical to the pre-DSP6 engine. The live
default-ON flip is operator-gated in ``docs/LIVE_GAME_GATED_SYNC.md``.
"""

import unittest

import agents.daemon_slayer as ds
from agents.daemon_slayer import enemy_runes as er


PTA, CONQ, GRASP, SECOND_WIND = 8005, 8010, 8437, 8444
ALL_IDS = (PTA, CONQ, GRASP, SECOND_WIND)


class TestRegistry(unittest.TestCase):
    def test_registry_has_exactly_the_four_modeled_runes(self):
        self.assertEqual(set(er.ENEMY_RUNE_THREATS), set(ALL_IDS))

    def test_seam_ids_cover_every_registered_rune(self):
        # Default-OFF marker: the seam ids ARE the modeled set (no live scorer
        # consumes them yet; the live flip wires an EHP/target-preset consumer).
        self.assertEqual(er.ENEMY_RUNE_SEAM_IDS, frozenset(er.ENEMY_RUNE_THREATS))

    def test_antiheal_is_not_a_rune_id(self):
        # Antiheal is the 4th DSP6 bucket but has no rune id - carried as a
        # constant + flag helper, never in the registry / seam-id set.
        self.assertEqual(er.GRIEVOUS_WOUNDS_PCT, 0.40)

    def test_every_rune_carries_a_provenance_formula(self):
        for threat in er.ENEMY_RUNE_THREATS.values():
            self.assertTrue(threat.formula.strip(), threat.name)
            self.assertTrue(threat.name)


class TestPressTheAttack(unittest.TestCase):
    def test_incoming_amp(self):
        # DDragon: amplifies damage dealt by 8% -> 8% incoming amp on the player.
        self.assertAlmostEqual(er.compute_enemy_rune_value(PTA), 0.08)
        self.assertAlmostEqual(er.enemy_incoming_amp_pct([PTA]), 0.08)

    def test_axis(self):
        self.assertEqual(er.ENEMY_RUNE_THREATS[PTA].axis, "incoming_amp")

    def test_only_pta_contributes_incoming_amp(self):
        self.assertEqual(er.enemy_incoming_amp_pct([CONQ, GRASP, SECOND_WIND]), 0.0)

    def test_amp_is_level_independent(self):
        self.assertAlmostEqual(er.compute_enemy_rune_value(PTA, level=1), 0.08)
        self.assertAlmostEqual(er.compute_enemy_rune_value(PTA, level=18), 0.08)


class TestConqueror(unittest.TestCase):
    def test_max_stack_adaptive_force_level_scaling(self):
        # 12 stacks * (1.8 - 4.0 by level) = 21.6 (L1) -> 48.0 (L18).
        self.assertAlmostEqual(er.compute_enemy_rune_value(CONQ, level=1), 21.6)
        self.assertAlmostEqual(er.compute_enemy_rune_value(CONQ, level=18), 48.0)

    def test_damage_ramp_helper(self):
        self.assertAlmostEqual(er.enemy_damage_ramp([CONQ], level=18), 48.0)
        # only damage_ramp-axis runes contribute
        self.assertEqual(er.enemy_damage_ramp([PTA, GRASP, SECOND_WIND]), 0.0)

    def test_lifesteal_carried_for_target_lens(self):
        threat = er.ENEMY_RUNE_THREATS[CONQ]
        self.assertAlmostEqual(threat.lifesteal_pct_melee, 0.08)
        self.assertAlmostEqual(threat.lifesteal_pct_ranged, 0.05)

    def test_axis(self):
        self.assertEqual(er.ENEMY_RUNE_THREATS[CONQ].axis, "damage_ramp")

    def test_conqueror_not_in_incoming_amp(self):
        # Conqueror is raw bonus damage, not a flat % amp.
        self.assertEqual(er.enemy_incoming_amp_pct([CONQ]), 0.0)


class TestPokeSustain(unittest.TestCase):
    def test_grasp_heal_fraction(self):
        self.assertAlmostEqual(er.compute_enemy_rune_value(GRASP), 0.013)

    def test_second_wind_heal_fraction(self):
        self.assertAlmostEqual(er.compute_enemy_rune_value(SECOND_WIND), 0.04)

    def test_poke_sustain_pct_sums_melee(self):
        # Grasp 0.013 (max HP) + Second Wind 0.04 (missing HP), melee.
        self.assertAlmostEqual(
            er.enemy_poke_sustain_pct([GRASP, SECOND_WIND]), 0.053
        )

    def test_poke_sustain_pct_ranged_grasp_scaled(self):
        # Grasp ranged 40% effective: 0.013 * 0.40 = 0.0052; Second Wind unscaled.
        self.assertAlmostEqual(
            er.enemy_poke_sustain_pct([GRASP, SECOND_WIND], ranged=True),
            0.0052 + 0.04,
        )

    def test_poke_sustain_hp_exact(self):
        # Grasp melee: 0.013 * 2000 + 5 = 31.0; Second Wind: 0.04 * 800 = 32.0.
        got = er.enemy_poke_sustain_hp(
            [GRASP, SECOND_WIND], enemy_max_hp=2000.0, enemy_missing_hp=800.0
        )
        self.assertAlmostEqual(got, 31.0 + 32.0)

    def test_poke_sustain_hp_ranged_grasp(self):
        # Grasp ranged: (0.013 * 2000 + 5) * 0.40 = 12.4; Second Wind unscaled.
        got = er.enemy_poke_sustain_hp(
            [GRASP, SECOND_WIND],
            enemy_max_hp=2000.0,
            enemy_missing_hp=800.0,
            ranged=True,
        )
        self.assertAlmostEqual(got, 12.4 + 32.0)

    def test_grasp_magic_proc(self):
        # 3.5% of 2000 max HP = 70.0 (melee).
        self.assertAlmostEqual(
            er.enemy_grasp_magic_proc([GRASP], enemy_max_hp=2000.0), 70.0
        )
        # ranged 40%: 28.0
        self.assertAlmostEqual(
            er.enemy_grasp_magic_proc([GRASP], enemy_max_hp=2000.0, ranged=True),
            28.0,
        )
        # no Grasp -> 0.0
        self.assertEqual(
            er.enemy_grasp_magic_proc([PTA, CONQ], enemy_max_hp=2000.0), 0.0
        )

    def test_axes(self):
        self.assertEqual(er.ENEMY_RUNE_THREATS[GRASP].axis, "poke_sustain")
        self.assertEqual(er.ENEMY_RUNE_THREATS[SECOND_WIND].axis, "poke_sustain")


class TestAntiheal(unittest.TestCase):
    def test_present_returns_grievous_wounds(self):
        self.assertAlmostEqual(er.enemy_antiheal_pct(True), 0.40)

    def test_absent_returns_zero(self):
        self.assertEqual(er.enemy_antiheal_pct(False), 0.0)


class TestFailSoftAndClamp(unittest.TestCase):
    def test_unknown_rune_id_is_zero_everywhere(self):
        self.assertEqual(er.compute_enemy_rune_value(99999), 0.0)
        self.assertEqual(er.enemy_incoming_amp_pct([99999]), 0.0)
        self.assertEqual(er.enemy_damage_ramp([99999]), 0.0)
        self.assertEqual(er.enemy_poke_sustain_pct([99999]), 0.0)
        self.assertEqual(er.enemy_poke_sustain_hp([99999], 2000.0, 800.0), 0.0)

    def test_empty_or_none_ids_are_zero(self):
        for empty in ([], (), None):
            self.assertEqual(er.enemy_incoming_amp_pct(empty), 0.0)
            self.assertEqual(er.enemy_damage_ramp(empty), 0.0)
            self.assertEqual(er.enemy_poke_sustain_pct(empty), 0.0)

    def test_bad_ids_fail_soft(self):
        self.assertEqual(er.enemy_incoming_amp_pct(["x", None]), 0.0)
        self.assertEqual(er.enemy_poke_sustain_hp([GRASP], "x", "y"), 0.0)

    def test_bad_level_fails_soft_to_level_one(self):
        self.assertAlmostEqual(er.compute_enemy_rune_value(CONQ, level=None), 21.6)
        self.assertAlmostEqual(er.compute_enemy_rune_value(CONQ, level="x"), 21.6)

    def test_level_clamped_to_one_eighteen(self):
        self.assertAlmostEqual(er.compute_enemy_rune_value(CONQ, level=0), 21.6)
        self.assertAlmostEqual(er.compute_enemy_rune_value(CONQ, level=99), 48.0)


class TestEngineVersionPin(unittest.TestCase):
    def test_engine_version_bumped(self):
        self.assertEqual(ds.ENGINE_VERSION, "1.266.0")


if __name__ == "__main__":
    unittest.main()
