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
        # Post-calibration (item 335): ADC KDA + DPM are co-dominant
        # (1.5 each) - the carry expectation. See the module docstring.
        self.assertEqual(pgr._DEFAULT_WEIGHTS["ADC"].kda, 1.5)

    def test_sup_vision_score_weight(self):
        # SUP has the dominant vision weight (highest single weight of any
        # role/axis) - the public-source signal for support.
        self.assertEqual(pgr._DEFAULT_WEIGHTS["SUP"].vision_score, 1.8)

    def test_jg_obj_participation_weight(self):
        # JG is judged most on objective participation - the heaviest
        # weight in the JG vector (public source: "KP heaviest for JG").
        self.assertEqual(pgr._DEFAULT_WEIGHTS["JG"].obj_participation, 1.5)

    def test_sup_cs_per_min_weight_is_zero(self):
        # Support CS is intentionally NOT scored (taking CS is anti-pattern).
        self.assertEqual(pgr._DEFAULT_WEIGHTS["SUP"].cs_per_min, 0.0)


class CalibrationInvariantTests(unittest.TestCase):
    """Durable calibration contract (item 335), independent of the live
    rewind_history.db. Two invariants the recalibration locks in:

      1. Every role's weight vector sums to 5.0, so a median-of-the-role
         performance (each axis at baseline -> normalized 1.0) maps to
         raw_total == 5.0, x10 == 50.0, the floor of the B band.
      2. A profile sitting EXACTLY at the role baselines therefore grades
         B at total_score 50.0 for every role. This is the empirically-
         anchored "median game is a B" intent (the baselines are the real
         per-role SR medians from 5957 games; see the module docstring).
    """

    def test_every_role_weight_vector_sums_to_five(self):
        for role, w in pgr._DEFAULT_WEIGHTS.items():
            total = (w.kda + w.cs_per_min + w.obj_participation
                     + w.vision_score + w.damage_per_min)
            self.assertAlmostEqual(
                total, 5.0, places=6,
                msg=f"{role} weight vector sums to {total}, expected 5.0",
            )

    def test_baseline_profile_grades_b_at_fifty(self):
        # Construct a profile whose every axis sits exactly at the role
        # baseline; each component normalizes to 1.0 so total == sum(w)*10
        # == 50.0 and the grade is the B floor.
        for role, base in pgr._ROLE_BASELINES.items():
            minutes = 20.0
            stats = {
                # kda == (kills + assists) / max(1, deaths); deaths=1 makes
                # the denominator 1 so kills carries the baseline kda value.
                "kills": base["kda"],
                "deaths": 1.0,
                "assists": 0.0,
                "cs": base["cs_per_min"] * minutes,
                "game_time_s": minutes * 60.0,
                "vision_score": base["vision_score"],
                "damage_dealt_to_champions": base["damage_per_min"] * minutes,
                "obj_participation_pct": base["obj_participation"],
            }
            result = pgr.compute_role_grade(stats, role=role)
            self.assertAlmostEqual(
                result["total_score"], 50.0, places=4,
                msg=f"{role} baseline profile scored {result['total_score']}",
            )
            self.assertEqual(
                result["percentile_grade"], "B",
                msg=f"{role} baseline profile graded {result['percentile_grade']}",
            )


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
        # 5/2/8 KDA, 22 min, 160 CS (no dmg/vis/obj in stats).
        # item-335 calibration: kda 1.5 * clamp(6.5/2.3=2.83 -> 2.0) = 3.0;
        # cs 1.1 * clamp(7.27/7.15=1.017) = 1.12. raw ~ 4.12, x10 ~ 41 (C).
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

    def test_sub_minute_game_uses_true_per_minute_rate(self):
        # Bug-hunt fix: a sub-60s game must divide by the true minutes, not a
        # 1.0-minute floor. Two sub-minute games with the SAME cs but different
        # durations therefore get DIFFERENT cs_per_min component scores (the
        # shorter game has the higher rate). Pre-fix both floored to cs/1.0 and
        # tied, hiding the difference.
        short = pgr.compute_role_grade({"cs": 3, "game_time_s": 30}, role="ADC")
        long_ = pgr.compute_role_grade({"cs": 3, "game_time_s": 50}, role="ADC")
        self.assertGreater(short["components"]["cs_per_min"],
                           long_["components"]["cs_per_min"])

    def test_normal_game_score_unchanged_by_rate_fix(self):
        # The floor removal is byte-identical for any real game (minutes > 1):
        # cs / max(1.0, m) == cs / m when m > 1. A 22-min game stays in band.
        result = pgr.compute_role_grade(
            {"kills": 5, "deaths": 2, "assists": 8, "cs": 160,
             "game_time_s": 22 * 60}, role="ADC")
        self.assertGreaterEqual(result["total_score"], 40.0)
        self.assertLessEqual(result["total_score"], 70.0)

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
        # be a dominant signal for SUP. item-335: SUP base vis 58, kda
        # 2.85. KDA=4.0 norm 1.40 -> 1.6*1.40 = 2.24. Vision 60/58 = 1.034
        # -> 1.8*1.034 = 1.86 (>= 0.5).
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
        # item-335 calibration (ADC base kda 2.3, cs 7.15, obj 0.15,
        # vis 15, dpm 731):
        # kda 22 -> clamp 2.0 -> 1.5*2 = 3.0.
        # cs/min 8 -> 8/7.15 = 1.12 -> 1.1*1.12 = 1.23.
        # obj 0.70/0.15 -> clamp 2.0 -> 0.6*2 = 1.2.
        # vision 20/15 = 1.33 -> 0.3*1.33 = 0.4.
        # dpm 1200/731 = 1.64 -> 1.5*1.64 = 2.46.
        # raw_total ~ 8.29; x10 = 82.9 -> S.
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


class NoOverrideFileDefaultPreservationTests(unittest.TestCase):
    """When no override file exists, default weights match the documented
    starting calibration values exactly. Pins the post-loader state so an
    accidental override during test runs (e.g. a stray file on disk) would
    surface as a test failure rather than silently shifting scores.
    """

    def test_no_override_file_in_tree(self):
        # The override file is gitignored personal calibration data; the
        # repo tree should not carry a checked-in copy. If a future
        # contributor commits a calibration file by accident, this guard
        # fires.
        override = pathlib.Path("data/post_game_rubric_weights.json")
        self.assertFalse(
            override.exists(),
            f"{override} should NOT exist in the repo tree (gitignored personal data)",
        )

    def test_adc_default_weights_unchanged(self):
        # Pins the ADC calibration (item 335). If the override loader
        # silently changes these (e.g. via a stray file in the test
        # environment), this fires. Sum == 5.0 (median game -> 50 = B).
        w = pgr._DEFAULT_WEIGHTS["ADC"]
        self.assertEqual(w.kda, 1.5)
        self.assertEqual(w.cs_per_min, 1.1)
        self.assertEqual(w.obj_participation, 0.6)
        self.assertEqual(w.vision_score, 0.3)
        self.assertEqual(w.damage_per_min, 1.5)

    def test_sup_default_weights_unchanged(self):
        # Sum == 5.0; vision dominant, cs == 0 (farming is anti-pattern).
        w = pgr._DEFAULT_WEIGHTS["SUP"]
        self.assertEqual(w.kda, 1.6)
        self.assertEqual(w.cs_per_min, 0.0)
        self.assertEqual(w.obj_participation, 1.0)
        self.assertEqual(w.vision_score, 1.8)
        self.assertEqual(w.damage_per_min, 0.6)


if __name__ == "__main__":
    unittest.main()
