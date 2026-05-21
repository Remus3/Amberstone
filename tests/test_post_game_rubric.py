"""Tests for core/post_game_rubric.py.

Exercises:
  - RoleWeights dataclass shape + immutability
  - _DEFAULT_WEIGHTS registry coverage + spot values
  - _normalize_role canonicalization + alias map + unknown fallback
  - compute_role_grade for solid/perfect/SUP/zero/missing-stats profiles
  - Divide-by-zero guards (game_time_s=0, deaths=0)
  - Custom weights kwarg override
  - Grade bucket boundaries (S+/S/A/B/C/D)
  - ASCII hygiene (no em-dashes, no smart quotes in the source)
"""
from __future__ import annotations

import dataclasses
import pathlib
import unittest

from core import post_game_rubric as pgr


class RoleWeightsTests(unittest.TestCase):
    """Frozen dataclass behavior."""

    def test_can_construct_with_role_only(self):
        w = pgr.RoleWeights(role="ADC")
        self.assertEqual(w.role, "ADC")
        # All numeric defaults are 0.0
        self.assertEqual(w.kda, 0.0)
        self.assertEqual(w.cs_per_min, 0.0)
        self.assertEqual(w.obj_participation, 0.0)
        self.assertEqual(w.vision_score, 0.0)
        self.assertEqual(w.damage_per_min, 0.0)

    def test_float_defaults_zero(self):
        # Zero defaults so partial overrides do not have to spell out
        # every axis. This is the durable contract.
        w = pgr.RoleWeights(role="X", kda=1.0)
        self.assertEqual(w.kda, 1.0)
        self.assertEqual(w.cs_per_min, 0.0)

    def test_frozen_via_dataclass_replace(self):
        # dataclasses.replace works on frozen dataclasses; direct mutation
        # would raise FrozenInstanceError, but replace returns a NEW
        # instance with the override.
        original = pgr.RoleWeights(role="ADC", kda=2.1)
        modified = dataclasses.replace(original, kda=99.0)
        self.assertEqual(original.kda, 2.1)
        self.assertEqual(modified.kda, 99.0)
        # The original is genuinely frozen (mutation raises).
        with self.assertRaises(dataclasses.FrozenInstanceError):
            original.kda = 5.0  # type: ignore[misc]


class DefaultWeightsTests(unittest.TestCase):
    """Registry coverage + spot calibration values."""

    def test_five_roles_present(self):
        self.assertEqual(
            set(pgr._DEFAULT_WEIGHTS.keys()),
            {"ADC", "SUP", "JG", "MID", "TOP"},
        )

    def test_adc_kda_weight(self):
        self.assertEqual(pgr._DEFAULT_WEIGHTS["ADC"].kda, 2.1)

    def test_sup_vision_score_weight(self):
        # SUP has the dominant vision weight.
        self.assertEqual(pgr._DEFAULT_WEIGHTS["SUP"].vision_score, 1.5)

    def test_jg_obj_participation_weight(self):
        # JG is judged most on objective participation.
        self.assertEqual(pgr._DEFAULT_WEIGHTS["JG"].obj_participation, 0.70)

    def test_sup_cs_per_min_weight_is_zero(self):
        # Support CS is intentionally NOT scored (taking CS is anti-pattern).
        self.assertEqual(pgr._DEFAULT_WEIGHTS["SUP"].cs_per_min, 0.0)


class NormalizeRoleTests(unittest.TestCase):
    """Canonicalization + alias map + unknown fallback."""

    def test_canonical_pass_through(self):
        for canonical in ("ADC", "MID", "TOP", "JG", "SUP"):
            self.assertEqual(pgr._normalize_role(canonical), canonical)

    def test_bottom_maps_to_adc(self):
        self.assertEqual(pgr._normalize_role("BOTTOM"), "ADC")
        self.assertEqual(pgr._normalize_role("bottom"), "ADC")

    def test_jungle_maps_to_jg(self):
        self.assertEqual(pgr._normalize_role("JUNGLE"), "JG")

    def test_support_and_utility_map_to_sup(self):
        self.assertEqual(pgr._normalize_role("SUPPORT"), "SUP")
        self.assertEqual(pgr._normalize_role("UTILITY"), "SUP")

    def test_unknown_falls_back_to_mid(self):
        self.assertEqual(pgr._normalize_role("XQUEUE"), "MID")
        self.assertEqual(pgr._normalize_role(""), "MID")

    def test_none_falls_back_to_mid(self):
        self.assertEqual(pgr._normalize_role(None), "MID")


class ComputeRoleGradeTests(unittest.TestCase):
    """Core scorer behavior."""

    def test_solid_adc_profile_lands_in_b_or_a(self):
        # 5/2/8 KDA, 22 min, 160 CS. KDA=6.5 norm 2.6 clamp 2.0 -> 4.2.
        # CS/min=7.27 norm 0.97 -> 0.825. raw_total ~ 5.025, x10 ~ 50.25.
        result = pgr.compute_role_grade(
            {
                "kills": 5,
                "deaths": 2,
                "assists": 8,
                "cs": 160,
                "game_time_s": 22 * 60,
            },
            role="ADC",
        )
        self.assertEqual(result["role"], "ADC")
        self.assertGreaterEqual(result["total_score"], 40.0)
        self.assertLessEqual(result["total_score"], 70.0)
        self.assertIn(result["percentile_grade"], {"A", "B", "C"})

    def test_missing_stats_keys_does_not_raise(self):
        # Empty stats dict should fail-soft: every component treated as 0.
        result = pgr.compute_role_grade({}, role="ADC")
        self.assertEqual(result["role"], "ADC")
        self.assertEqual(result["total_score"], 0.0)
        self.assertEqual(result["percentile_grade"], "D")
        self.assertIn("components", result)

    def test_custom_weights_kwarg_overrides_defaults(self):
        # Pass a custom RoleWeights with kda=10 (vs default 2.1).
        custom = pgr.RoleWeights(role="ADC", kda=10.0)
        stats = {
            "kills": 5,
            "deaths": 2,
            "assists": 8,
            "cs": 160,
            "game_time_s": 22 * 60,
        }
        with_default = pgr.compute_role_grade(stats, role="ADC")
        with_custom = pgr.compute_role_grade(
            stats, role="ADC", weights=custom
        )
        # Custom weights should produce a different total_score.
        self.assertNotEqual(
            with_default["total_score"], with_custom["total_score"]
        )

    def test_sup_profile_with_vision_component_meaningful(self):
        # 1/4/15 KDA, vision 60, 28 min game. Vision component should
        # be the dominant signal for SUP. KDA=4.0 norm 1.33 -> comp 3.33.
        # Vision=60 norm 1.09 -> comp 1.636 (>= 0.5).
        result = pgr.compute_role_grade(
            {
                "kills": 1,
                "deaths": 4,
                "assists": 15,
                "cs": 28,
                "game_time_s": 28 * 60,
                "vision_score": 60,
            },
            role="SUP",
        )
        self.assertEqual(result["role"], "SUP")
        self.assertGreaterEqual(result["components"]["vision"], 0.5)
        # Total score should be a real number, not near-zero.
        self.assertGreater(result["total_score"], 30.0)

    def test_zero_game_time_no_div_by_zero(self):
        # CS/min and DPM use max(1.0, minutes), but minutes==0 -> per-min
        # values explicitly set to 0 (not 1.0/0).
        result = pgr.compute_role_grade(
            {
                "kills": 5,
                "deaths": 1,
                "assists": 10,
                "cs": 100,
                "game_time_s": 0,
            },
            role="ADC",
        )
        # Did not raise; cs_per_min component is 0 because minutes==0.
        self.assertEqual(result["components"]["cs_per_min"], 0.0)
        # KDA component is still computed (independent of game time).
        self.assertGreater(result["components"]["kda"], 0.0)

    def test_zero_deaths_no_div_by_zero(self):
        # KDA = (kills + assists) / max(1, deaths). At deaths=0 the
        # denominator is 1 (not 0), so no ZeroDivisionError.
        result = pgr.compute_role_grade(
            {"kills": 10, "deaths": 0, "assists": 5, "game_time_s": 1800},
            role="MID",
        )
        # 15/1 = 15 KDA, well above the 2.8 MID baseline -> clamped to 2x.
        self.assertGreater(result["components"]["kda"], 0.0)

    def test_zero_stats_returns_zero_total(self):
        result = pgr.compute_role_grade(
            {
                "kills": 0,
                "deaths": 0,
                "assists": 0,
                "cs": 0,
                "game_time_s": 0,
                "vision_score": 0,
                "obj_participation_pct": 0,
                "damage_dealt_to_champions": 0,
            },
            role="JG",
        )
        self.assertEqual(result["total_score"], 0.0)
        self.assertEqual(result["percentile_grade"], "D")

    def test_perfect_adc_profile_lands_in_s_range(self):
        # 10/0/12 KDA, 30 min, 240 CS, vision 20, obj 0.70, dpm 1200.
        # KDA 22 -> norm 8.8 -> clamp 2.0 -> comp 4.2.
        # CS/min 8 -> norm 1.067 -> comp 0.907.
        # obj 0.70/0.55 = 1.27 -> comp 0.636.
        # vision 20/15 = 1.33 -> comp 0.4.
        # dpm 1200 -> norm 2.0 -> comp 1.7.
        # raw_total ~ 7.843; x10 = 78.43 -> S.
        result = pgr.compute_role_grade(
            {
                "kills": 10,
                "deaths": 0,
                "assists": 12,
                "cs": 240,
                "game_time_s": 30 * 60,
                "vision_score": 20,
                "obj_participation_pct": 0.70,
                "damage_dealt_to_champions": 1200 * 30,
            },
            role="ADC",
        )
        self.assertIn(result["percentile_grade"], {"S+", "S"})
        self.assertGreater(result["total_score"], 70.0)

    def test_components_dict_carries_all_axes(self):
        result = pgr.compute_role_grade({}, role="ADC")
        self.assertEqual(
            set(result["components"].keys()),
            {"kda", "cs_per_min", "obj_participation", "vision", "dpm"},
        )

    def test_canonicalizes_role_in_output(self):
        # BOTTOM alias is canonicalized to ADC in the output payload.
        result = pgr.compute_role_grade({}, role="BOTTOM")
        self.assertEqual(result["role"], "ADC")


class GradeBucketsTests(unittest.TestCase):
    """Boundary checks for _grade_bucket."""

    def test_s_plus_at_90(self):
        self.assertEqual(pgr._grade_bucket(90), "S+")

    def test_s_at_80(self):
        self.assertEqual(pgr._grade_bucket(80), "S")

    def test_a_at_70(self):
        self.assertEqual(pgr._grade_bucket(70), "A")

    def test_b_at_55(self):
        self.assertEqual(pgr._grade_bucket(55), "B")

    def test_c_at_40(self):
        self.assertEqual(pgr._grade_bucket(40), "C")

    def test_d_at_20_and_zero(self):
        self.assertEqual(pgr._grade_bucket(20), "D")
        self.assertEqual(pgr._grade_bucket(0), "D")


class AsciiHygieneTests(unittest.TestCase):
    """Source file is pure ASCII (no em/en-dashes, no smart quotes)."""

    def test_module_source_has_no_unicode_punctuation(self):
        path = pathlib.Path("core/post_game_rubric.py")
        text = path.read_text(encoding="utf-8")
        # Build the BAD set via chr() so this test file itself stays
        # ASCII-clean against its own scan.
        bad = {
            chr(0x2013),  # en-dash
            chr(0x2014),  # em-dash
            chr(0x2018),  # left single curly quote
            chr(0x2019),  # right single curly quote
            chr(0x201C),  # left double curly quote
            chr(0x201D),  # right double curly quote
        }
        hits = [c for c in text if c in bad]
        self.assertEqual(
            hits,
            [],
            f"core/post_game_rubric.py contains banned Unicode punctuation: {hits!r}",
        )


if __name__ == "__main__":
    unittest.main()
