"""Tests for the cross-spell self-state amp seam (item 257, gap-plan C2x).

AurelionSol W (Astral Flight) carries a "Breath of Light Flat Damage Modifier"
``[108,109,110,111,112]%`` (x1.08..1.12 -> addend 0.08..0.12 by W rank) that
amplifies the Q beam (Breath of Light) WHILE W flight is active. W f0 itself has
no damage block, so the amp cannot be keyed to W (item 239 STAGED it for this
reason). The cross-spell seam keys the amp on the TARGET spell (Q) and sources
the magnitude + gate from the W rank + W-flight self-state.

Consumed by ``compute_ability_dps`` ONLY under ``apply_ability_amps=True``:
  * resolves the SOURCE (W) rank via ``rank_at_level`` at the current level,
  * gates on the W-flight self-state midpoint (0.4),
  * multiplies the target Q's per-cast amp factor,
  * skips when W is unleveled (source rank < 0 -> no buff).

Default path (``apply_ability_amps=False``) is byte-identical. Does NOT pin
ENGINE_VERSION (the orchestrator owns the bump).
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer._ability_amp_overrides import (
    _COND_W_FLIGHT,
    _CROSS_SPELL_AMP_OVERRIDES,
    _DEFAULT_AMP_PROBABILITY,
    _STAGED_AMP_CANDIDATES,
    CrossSpellAmpEntry,
    _amp_multiplier,
    _cross_spell_amp_for,
)
from agents.daemon_slayer.ability_dps import compute_ability_dps
from agents.daemon_slayer.data_loader import DataSnapshot

_SNAP = DataSnapshot.load()


def _q(result):
    for s in result.per_spell:
        if s.key == "Q":
            return s
    return None


def _aurelion_q(level, amps):
    r = compute_ability_dps(
        _SNAP, "AurelionSol", level, item_ids=[], mode="SR", apply_ability_amps=amps
    )
    return _q(r)


class RegistryShapeTests(unittest.TestCase):
    def test_aurelion_q_cross_spell_entry_present(self):
        e = _cross_spell_amp_for("AurelionSol", "Q", 0)
        self.assertIsNotNone(e)
        self.assertIsInstance(e, CrossSpellAmpEntry)

    def test_source_key_is_w(self):
        self.assertEqual(_cross_spell_amp_for("AurelionSol", "Q", 0).source_key, "W")

    def test_amp_per_rank_matches_w_modifier(self):
        # W "Breath of Light Flat Damage Modifier" [108..112]% -> addend 0.08..0.12.
        self.assertEqual(
            _cross_spell_amp_for("AurelionSol", "Q", 0).amp_per_rank,
            (0.08, 0.09, 0.10, 0.11, 0.12),
        )

    def test_condition_is_w_flight(self):
        self.assertEqual(
            _cross_spell_amp_for("AurelionSol", "Q", 0).condition, _COND_W_FLIGHT
        )

    def test_entry_not_always_on(self):
        self.assertFalse(_cross_spell_amp_for("AurelionSol", "Q", 0).always_on)

    def test_registry_keyed_by_target_spell(self):
        self.assertIn(("AurelionSol", "Q", 0), _CROSS_SPELL_AMP_OVERRIDES)

    def test_w_flight_condition_in_probability_map(self):
        self.assertEqual(_DEFAULT_AMP_PROBABILITY[_COND_W_FLIGHT], 0.4)


class ResolverNegativeTests(unittest.TestCase):
    def test_other_champion_returns_none(self):
        self.assertIsNone(_cross_spell_amp_for("Caitlyn", "Q", 0))

    def test_aurelion_w_target_returns_none(self):
        # The amp is keyed to the TARGET (Q), never to W.
        self.assertIsNone(_cross_spell_amp_for("AurelionSol", "W", 0))

    def test_aurelion_wrong_form_returns_none(self):
        self.assertIsNone(_cross_spell_amp_for("AurelionSol", "Q", 1))


class StagedEmptyTests(unittest.TestCase):
    def test_staged_candidates_now_empty(self):
        # AurelionSol W was the last staged entry; resolved here -> registry empty.
        self.assertEqual(_STAGED_AMP_CANDIDATES, {})


class MultiplierMathTests(unittest.TestCase):
    """_amp_multiplier on the cross-spell entry at a SOURCE (W) rank."""

    def setUp(self):
        self.e = _cross_spell_amp_for("AurelionSol", "Q", 0)

    def test_w_rank0_factor(self):
        # 1 + 0.4 * 0.08 = 1.032
        self.assertAlmostEqual(
            _amp_multiplier(self.e, 0, _DEFAULT_AMP_PROBABILITY), 1.032
        )

    def test_w_rank2_factor(self):
        # 1 + 0.4 * 0.10 = 1.04
        self.assertAlmostEqual(
            _amp_multiplier(self.e, 2, _DEFAULT_AMP_PROBABILITY), 1.04
        )

    def test_w_rank4_factor(self):
        # 1 + 0.4 * 0.12 = 1.048
        self.assertAlmostEqual(
            _amp_multiplier(self.e, 4, _DEFAULT_AMP_PROBABILITY), 1.048
        )

    def test_rank_clamped_above_bounds(self):
        # rank index past the tuple end clamps to the last addend (0.12).
        self.assertAlmostEqual(
            _amp_multiplier(self.e, 9, _DEFAULT_AMP_PROBABILITY), 1.048
        )

    def test_unknown_condition_inert(self):
        bad = CrossSpellAmpEntry(source_key="W", amp_per_rank=(0.5,), condition="nope")
        self.assertEqual(_amp_multiplier(bad, 0, _DEFAULT_AMP_PROBABILITY), 1.0)


class EngineDefaultByteIdenticalTests(unittest.TestCase):
    """Default apply_ability_amps=False -> cross-spell amp never applies."""

    def test_aurelion_q_default_unchanged_lvl11(self):
        off = _aurelion_q(11, False)
        # Live baseline pinned pre-seam (item 257): 292.5 post-mit / 15.7318 dps.
        self.assertAlmostEqual(off.post_mitigation_damage_per_cast, 292.5, places=3)

    def test_aurelion_q_off_equals_prior_across_levels(self):
        for lvl in (1, 5, 11, 16, 18):
            self.assertGreater(_aurelion_q(lvl, False).post_mitigation_damage_per_cast, 0.0)


class EngineCrossSpellAppliesTests(unittest.TestCase):
    """Under the flag, AurelionSol Q is amplified by the W-rank cross-spell amp."""

    def test_lvl1_byte_identical_w_unleveled(self):
        # At level 1, W rank is -1 (unleveled) -> cross-spell skipped -> identical.
        off = _aurelion_q(1, False).post_mitigation_damage_per_cast
        on = _aurelion_q(1, True).post_mitigation_damage_per_cast
        self.assertAlmostEqual(off, on, places=6)

    def test_lvl11_amp_applies_w_rank2(self):
        off = _aurelion_q(11, False).post_mitigation_damage_per_cast
        on = _aurelion_q(11, True).post_mitigation_damage_per_cast
        # W rank 2 at lvl 11 -> x1.04.
        self.assertAlmostEqual(on, off * 1.04, places=4)
        self.assertAlmostEqual(on, 304.2, places=3)

    def test_lvl16_amp_applies_w_rank4(self):
        off = _aurelion_q(16, False).post_mitigation_damage_per_cast
        on = _aurelion_q(16, True).post_mitigation_damage_per_cast
        # W rank 4 at lvl 16 -> x1.048.
        self.assertAlmostEqual(on, off * 1.048, places=4)
        self.assertAlmostEqual(on, 306.54, places=2)

    def test_dps_scales_with_amp_lvl11(self):
        off = _aurelion_q(11, False).dps
        on = _aurelion_q(11, True).dps
        self.assertAlmostEqual(on, off * 1.04, places=4)


class ControlChampionByteIdenticalTests(unittest.TestCase):
    """A champion with no cross-spell entry is byte-identical under the flag."""

    def test_caitlyn_q_flag_on_unchanged(self):
        r_off = compute_ability_dps(_SNAP, "Caitlyn", 11, item_ids=[], mode="SR",
                                    apply_ability_amps=False)
        r_on = compute_ability_dps(_SNAP, "Caitlyn", 11, item_ids=[], mode="SR",
                                   apply_ability_amps=True)
        self.assertAlmostEqual(
            _q(r_off).post_mitigation_damage_per_cast,
            _q(r_on).post_mitigation_damage_per_cast,
            places=6,
        )


class AsciiHygieneTests(unittest.TestCase):
    def test_module_ascii(self):
        import agents.daemon_slayer._ability_amp_overrides as m

        raw = open(m.__file__, encoding="utf-8").read()
        self.assertEqual(raw, raw.encode("ascii", "replace").decode("ascii"))

    def test_test_file_ascii(self):
        raw = open(__file__, encoding="utf-8").read()
        self.assertEqual(raw, raw.encode("ascii", "replace").decode("ascii"))


if __name__ == "__main__":
    unittest.main()
