"""Tests for the optional carry-efficiency grade axis in core/post_game_rubric.

BACKLOG.md residual 1 (aggregator B carry-efficiency grade axes). The fold is a
DEFAULT-OFF, additive bonus axis (gold_share + kill-participation). These tests
pin the two load-bearing contracts:

  * DEFAULT (carry_efficiency=False): the grade is byte-identical to the
    pre-fold calibration - same total_score, same percentile_grade, same
    components dict (no `carry_efficiency` key). Asserted as full-dict equality
    against the call WITHOUT the flag for representative per-role inputs.
  * Flag ON: a higher gold_share / KP yields a non-worse grade (monotonic).
    Proven by difference-of-differences (the ON-vs-OFF delta is >= 0 and grows
    with gold_share / KP), not a fragile absolute-value or cross-row compare.

The carry-efficiency axis reuses core.carry_share.gold_share_pct (item 505,
DISPLAY-only producer) + the existing kp_pct - this module does NOT re-derive
either; it consumes the 0-100 percents passed in `stats`.
"""
from __future__ import annotations

import pathlib
import unittest

from core import post_game_rubric as pgr


def _representative_stats(**overrides):
    """A solid-but-not-saturated ADC profile, plus carry-efficiency inputs.

    gold_share_pct / kp_pct are present so the ON path has real values to fold;
    the OFF path must ignore them entirely (byte-identical contract).
    """
    base = {
        "kills": 6,
        "deaths": 3,
        "assists": 8,
        "cs": 200,
        "game_time_s": 28 * 60,
        "vision_score": 18,
        "obj_participation_pct": 0.20,
        "damage_dealt_to_champions": 800 * 28,
        "gold_share_pct": 24.0,
        "kp_pct": 60.0,
    }
    base.update(overrides)
    return base


class DefaultOffByteIdenticalTests(unittest.TestCase):
    """carry_efficiency=False must be byte-identical to the pre-fold grade."""

    def test_default_kwarg_is_false(self):
        # carry_efficiency is a keyword flag defaulting False, so every existing
        # positional caller (routes + postmortem) is unbroken and lands on the
        # default-off path. ORUN5 later appended assume_carry_share_grade (its
        # canonical-named alias) AFTER it at the true END of the signature, so
        # this pins the default rather than a strict last-position index.
        import inspect

        sig = inspect.signature(pgr.compute_role_grade)
        params = list(sig.parameters)
        self.assertIn("carry_efficiency", params)
        self.assertEqual(params[-1], "assume_carry_share_grade")
        self.assertIs(sig.parameters["carry_efficiency"].default, False)

    def test_explicit_false_equals_omitted(self):
        # Passing the flag explicitly as False is identical to omitting it.
        for role in ("ADC", "SUP", "JG", "MID", "TOP"):
            stats = _representative_stats()
            omitted = pgr.compute_role_grade(stats, role=role)
            explicit = pgr.compute_role_grade(
                stats, role=role, carry_efficiency=False
            )
            self.assertEqual(omitted, explicit, role)

    def test_off_grade_independent_of_carry_inputs(self):
        # With the flag OFF, gold_share_pct / kp_pct must NOT move the grade.
        for role in ("ADC", "SUP", "JG", "MID", "TOP"):
            low = pgr.compute_role_grade(
                _representative_stats(gold_share_pct=10.0, kp_pct=20.0),
                role=role,
            )
            high = pgr.compute_role_grade(
                _representative_stats(gold_share_pct=45.0, kp_pct=95.0),
                role=role,
            )
            self.assertEqual(low, high, role)

    def test_off_components_has_no_carry_key(self):
        result = pgr.compute_role_grade(_representative_stats(), role="ADC")
        self.assertNotIn("carry_efficiency", result["components"])
        self.assertEqual(
            set(result["components"].keys()),
            {"kda", "cs_per_min", "obj_participation", "vision", "dpm"},
        )


class FlagOnMonotonicTests(unittest.TestCase):
    """carry_efficiency=True: higher gold_share / KP -> non-worse grade."""

    def test_on_adds_carry_component_key(self):
        result = pgr.compute_role_grade(
            _representative_stats(), role="ADC", carry_efficiency=True
        )
        self.assertIn("carry_efficiency", result["components"])

    def test_on_is_never_worse_than_off(self):
        # The axis is purely additive, so ON >= OFF for the same stats across
        # every role (a bonus axis can only raise the grade).
        for role in ("ADC", "SUP", "JG", "MID", "TOP"):
            stats = _representative_stats()
            off = pgr.compute_role_grade(stats, role=role)
            on = pgr.compute_role_grade(stats, role=role, carry_efficiency=True)
            self.assertGreaterEqual(on["total_score"], off["total_score"], role)

    def test_higher_gold_share_yields_non_worse_grade(self):
        # Monotonic in gold_share with the flag ON.
        low = pgr.compute_role_grade(
            _representative_stats(gold_share_pct=10.0),
            role="ADC",
            carry_efficiency=True,
        )
        high = pgr.compute_role_grade(
            _representative_stats(gold_share_pct=40.0),
            role="ADC",
            carry_efficiency=True,
        )
        self.assertGreaterEqual(high["total_score"], low["total_score"])
        self.assertGreater(high["total_score"], low["total_score"])

    def test_higher_kp_yields_non_worse_grade(self):
        # Monotonic in kp_pct with the flag ON.
        low = pgr.compute_role_grade(
            _representative_stats(kp_pct=20.0),
            role="ADC",
            carry_efficiency=True,
        )
        high = pgr.compute_role_grade(
            _representative_stats(kp_pct=90.0),
            role="ADC",
            carry_efficiency=True,
        )
        self.assertGreater(high["total_score"], low["total_score"])

    def test_difference_of_differences_monotonic(self):
        # Difference-of-differences: the ON-vs-OFF lift at high carry inputs
        # exceeds the lift at low carry inputs. This isolates the carry axis
        # from every other (unchanged) component without a fragile absolute.
        low_stats = _representative_stats(gold_share_pct=12.0, kp_pct=25.0)
        high_stats = _representative_stats(gold_share_pct=40.0, kp_pct=90.0)

        low_off = pgr.compute_role_grade(low_stats, role="ADC")["total_score"]
        low_on = pgr.compute_role_grade(
            low_stats, role="ADC", carry_efficiency=True
        )["total_score"]
        high_off = pgr.compute_role_grade(high_stats, role="ADC")["total_score"]
        high_on = pgr.compute_role_grade(
            high_stats, role="ADC", carry_efficiency=True
        )["total_score"]

        # OFF is identical regardless of carry inputs (byte-identical contract).
        self.assertEqual(low_off, high_off)
        # The carry lift is non-negative and strictly larger for the richer
        # carry profile.
        low_lift = low_on - low_off
        high_lift = high_on - high_off
        self.assertGreaterEqual(low_lift, 0.0)
        self.assertGreater(high_lift, low_lift)

    def test_zero_carry_inputs_add_nothing(self):
        # gold_share / KP absent (fail-soft 0.0) -> the carry component is 0.0,
        # so ON == OFF total even though the component key is present.
        stats = _representative_stats(gold_share_pct=0.0, kp_pct=0.0)
        off = pgr.compute_role_grade(stats, role="ADC")
        on = pgr.compute_role_grade(stats, role="ADC", carry_efficiency=True)
        self.assertEqual(on["total_score"], off["total_score"])
        self.assertEqual(on["components"]["carry_efficiency"], 0.0)

    def test_missing_carry_keys_fail_soft(self):
        # No gold_share_pct / kp_pct keys at all -> treated as 0.0, no raise.
        stats = {
            "kills": 5,
            "deaths": 2,
            "assists": 7,
            "cs": 180,
            "game_time_s": 25 * 60,
            "vision_score": 15,
            "obj_participation_pct": 0.15,
            "damage_dealt_to_champions": 700 * 25,
        }
        result = pgr.compute_role_grade(
            stats, role="ADC", carry_efficiency=True
        )
        self.assertEqual(result["components"]["carry_efficiency"], 0.0)


class AsciiHygieneTests(unittest.TestCase):
    """Both the module and this test file stay pure ASCII."""

    def test_module_and_test_have_no_unicode_punctuation(self):
        bad = {
            chr(0x2013),  # en-dash
            chr(0x2014),  # em-dash
            chr(0x2018),  # left single curly quote
            chr(0x2019),  # right single curly quote
            chr(0x201C),  # left double curly quote
            chr(0x201D),  # right double curly quote
        }
        for rel in (
            "core/post_game_rubric.py",
            "tests/test_post_game_rubric_carry_efficiency.py",
        ):
            text = pathlib.Path(rel).read_text(encoding="utf-8")
            offenders = sorted({c for c in text if c in bad})
            self.assertEqual(offenders, [], f"{rel} has unicode punctuation")


if __name__ == "__main__":
    unittest.main()
