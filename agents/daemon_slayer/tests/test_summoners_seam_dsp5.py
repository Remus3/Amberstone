"""DSP5 summoner-spell seam characterization tests.

Anchors ``agents/daemon_slayer/summoners.py`` - the NEW default-OFF
summoner-spell substrate (Ignite / Exhaust / Heal / Barrier / Cleanse / Ghost).
Every magnitude is pinned to the LoL wiki value cited in the module ``formula``
strings (DDragon/CDragon zero summoner magnitudes; the wiki is the sanctioned
fallback per ``reference_lol_wiki_access``). The seam is a PURE substrate: no
live scorer consumes it (``SUMMONER_SEAM_IDS`` is the marker), so the live
``/rank`` output is byte-identical to the pre-DSP5 engine. The live default-ON
flip is operator-gated in ``docs/LIVE_GAME_GATED_SYNC.md``.
"""

import unittest

import agents.daemon_slayer as ds
from agents.daemon_slayer import summoners as sm


IGNITE, EXHAUST, HEAL, BARRIER, CLEANSE, GHOST = 14, 3, 7, 21, 1, 6
ALL_IDS = (IGNITE, EXHAUST, HEAL, BARRIER, CLEANSE, GHOST)


class TestSummonerRegistry(unittest.TestCase):
    def test_registry_has_exactly_the_six_modeled_spells(self):
        self.assertEqual(set(sm.SUMMONER_SPELLS), set(ALL_IDS))

    def test_seam_ids_cover_every_registered_spell(self):
        # Default-OFF marker: the seam ids ARE the modeled set (no live scorer
        # consumes them yet; the live flip wires fight_report/matchup/coach).
        self.assertEqual(sm.SUMMONER_SEAM_IDS, frozenset(sm.SUMMONER_SPELLS))

    def test_every_spell_carries_a_provenance_formula(self):
        for spell in sm.SUMMONER_SPELLS.values():
            self.assertTrue(spell.formula.strip(), spell.name)
            self.assertTrue(spell.name)
            self.assertGreater(spell.cooldown_s, 0.0)


class TestIgnite(unittest.TestCase):
    def test_true_damage_level_scaling(self):
        # Wiki: 70 - 525 true damage over 5s (by level).
        self.assertAlmostEqual(sm.compute_summoner_value(IGNITE, level=1), 70.0)
        self.assertAlmostEqual(sm.compute_summoner_value(IGNITE, level=18), 525.0)

    def test_antiheal_grievous_wounds(self):
        self.assertAlmostEqual(sm.summoner_antiheal_pct(IGNITE), 0.40)

    def test_axis(self):
        self.assertEqual(sm.SUMMONER_SPELLS[IGNITE].axis, "antiheal_true")

    def test_only_ignite_applies_antiheal(self):
        for sid in (EXHAUST, HEAL, BARRIER, CLEANSE, GHOST):
            self.assertEqual(sm.summoner_antiheal_pct(sid), 0.0)


class TestExhaust(unittest.TestCase):
    def test_incoming_damage_reduction(self):
        # Wiki: target's damage dealt reduced by 35% (3s).
        self.assertAlmostEqual(sm.summoner_incoming_dr_pct(EXHAUST), 0.35)
        self.assertAlmostEqual(sm.compute_summoner_value(EXHAUST), 0.35)

    def test_axis(self):
        self.assertEqual(sm.SUMMONER_SPELLS[EXHAUST].axis, "incoming_dr")

    def test_only_exhaust_grants_incoming_dr(self):
        for sid in (IGNITE, HEAL, BARRIER, CLEANSE, GHOST):
            self.assertEqual(sm.summoner_incoming_dr_pct(sid), 0.0)


class TestHealBarrierEhp(unittest.TestCase):
    def test_heal_level_scaling(self):
        # Wiki: restores 80 - 346 health (by level).
        self.assertAlmostEqual(sm.compute_summoner_value(HEAL, level=1), 80.0)
        self.assertAlmostEqual(sm.compute_summoner_value(HEAL, level=18), 346.0)

    def test_heal_grants_move_speed(self):
        self.assertAlmostEqual(sm.compute_summoner_ms_pct(HEAL), 0.30)

    def test_barrier_level_scaling(self):
        # Wiki: shields 100 - 502.35 (by level) for 2.5s.
        self.assertAlmostEqual(sm.compute_summoner_value(BARRIER, level=1), 100.0)
        self.assertAlmostEqual(sm.compute_summoner_value(BARRIER, level=18), 502.35)

    def test_ehp_bonus_dispatch(self):
        self.assertAlmostEqual(sm.compute_summoner_ehp_bonus(HEAL, level=18), 346.0)
        self.assertAlmostEqual(sm.compute_summoner_ehp_bonus(BARRIER, level=1), 100.0)
        # damage / cc / pure-ms spells contribute no flat EHP
        self.assertEqual(sm.compute_summoner_ehp_bonus(IGNITE, level=18), 0.0)
        self.assertEqual(sm.compute_summoner_ehp_bonus(GHOST, level=18), 0.0)

    def test_axes(self):
        self.assertEqual(sm.SUMMONER_SPELLS[HEAL].axis, "ehp_heal")
        self.assertEqual(sm.SUMMONER_SPELLS[BARRIER].axis, "ehp_shield")


class TestCleanse(unittest.TestCase):
    def test_cc_duration_discount(self):
        # Wiki: 75% tenacity for 3s (reduces incoming immobilize duration).
        self.assertAlmostEqual(sm.summoner_cc_discount_pct(CLEANSE), 0.75)
        self.assertAlmostEqual(sm.compute_summoner_value(CLEANSE), 0.75)

    def test_axis(self):
        self.assertEqual(sm.SUMMONER_SPELLS[CLEANSE].axis, "cc_discount")

    def test_only_cleanse_discounts_cc(self):
        for sid in (IGNITE, EXHAUST, HEAL, BARRIER, GHOST):
            self.assertEqual(sm.summoner_cc_discount_pct(sid), 0.0)


class TestGhost(unittest.TestCase):
    def test_move_speed_level_scaling(self):
        # Wiki: 24% - 50.82% bonus move speed (by level) for 10s.
        self.assertAlmostEqual(sm.compute_summoner_ms_pct(GHOST, level=1), 0.24)
        self.assertAlmostEqual(sm.compute_summoner_ms_pct(GHOST, level=18), 0.5082)

    def test_axis(self):
        self.assertEqual(sm.SUMMONER_SPELLS[GHOST].axis, "move_speed")


class TestFailSoftAndClamp(unittest.TestCase):
    def test_unknown_spell_id_is_zero_everywhere(self):
        self.assertEqual(sm.compute_summoner_value(99999), 0.0)
        self.assertEqual(sm.summoner_antiheal_pct(99999), 0.0)
        self.assertEqual(sm.summoner_incoming_dr_pct(99999), 0.0)
        self.assertEqual(sm.summoner_cc_discount_pct(99999), 0.0)
        self.assertEqual(sm.compute_summoner_ms_pct(99999), 0.0)
        self.assertEqual(sm.compute_summoner_ehp_bonus(99999), 0.0)

    def test_bad_level_fails_soft_to_level_one(self):
        self.assertAlmostEqual(sm.compute_summoner_value(IGNITE, level=None), 70.0)
        self.assertAlmostEqual(sm.compute_summoner_value(IGNITE, level="x"), 70.0)

    def test_level_clamped_to_one_eighteen(self):
        self.assertAlmostEqual(sm.compute_summoner_value(IGNITE, level=0), 70.0)
        self.assertAlmostEqual(sm.compute_summoner_value(IGNITE, level=99), 525.0)


class TestEngineVersionPin(unittest.TestCase):
    def test_engine_version_bumped(self):
        self.assertEqual(ds.ENGINE_VERSION, "1.267.0")


if __name__ == "__main__":
    unittest.main()
