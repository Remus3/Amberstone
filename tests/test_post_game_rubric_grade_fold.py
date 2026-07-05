"""ORUN5 tests for the assume_carry_share_grade grade-fold seam.

docs/ORCHESTRATION_PLAN.md ORUN5: fold gold_share + kill-participation into
core.post_game_rubric.compute_role_grade behind a DEFAULT-OFF
`assume_carry_share_grade` flag. The seam is the ORUN5 canonical-named alias of
the existing carry_efficiency fold - either flag arms the identical additive,
monotonic axis. These tests pin the four load-bearing ORUN5 contracts against
the assume_carry_share_grade parameter by name:

  1. OFF (default) is BYTE-IDENTICAL to a baseline compute_role_grade call -
     same total_score, same percentile_grade, same components dict (no
     `carry_efficiency` key) - across several role/stat fixtures. This is the
     critical ship invariant.
  2. ON with high gold_share / KP yields a >= grade and >= total_score
     (monotonic RAISE), never lower, proven by ON-vs-OFF difference-of-
     differences (delta >= 0 and grows with gold_share / KP) rather than a
     fragile absolute compare.
  3. Fail-soft: when gold_share_pct / kp_pct are absent the ON path does not
     crash and contributes a 0.0 bonus (grade unchanged from OFF).
  4. Bounded: the additive bonus cannot pathologically overflow the S+ bucket -
     total_score stays clamped to [0, 100] and a floor game does not vault to
     S+ on the fold alone.

Grounding (file:line verified before writing):
  * compute_role_grade signature + assume_carry_share_grade default False:
    core/post_game_rubric.py:405-412.
  * fold gate `if carry_efficiency or assume_carry_share_grade`:
    core/post_game_rubric.py:485.
  * _CARRY_EFFICIENCY_WEIGHT=0.5, _GOLD_SHARE_EVEN_BASELINE=20.0,
    _KP_NEUTRAL_BASELINE=50.0: core/post_game_rubric.py:335-337.
  * _grade_bucket S+ floor 85 / total_score clamp min(100, ...):
    core/post_game_rubric.py:390-402, 497.

Hermetic + offline: constructs stats dicts inline, no DB / network / file I/O.
"""
from __future__ import annotations

import inspect
import unittest

from core import post_game_rubric as pgr


def _solid_stats(**overrides):
    """A solid-but-not-saturated ADC profile with carry-share inputs present.

    gold_share_pct / kp_pct are present so the ON path folds real values; the
    OFF path must ignore them entirely (byte-identical contract).
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


# A spread of role/stat fixtures for the byte-identical sweep. Mixes roles,
# saturated / thin / empty stat lines, and present/absent carry-share inputs.
_BYTE_IDENTICAL_FIXTURES = (
    ("ADC", _solid_stats()),
    ("SUPPORT", _solid_stats(kills=1, assists=20, cs=30, vision_score=45)),
    ("JUNGLE", _solid_stats(gold_share_pct=30.0, kp_pct=80.0)),
    ("MIDDLE", _solid_stats(deaths=0, kills=12)),
    ("TOP", {"cs": 220, "game_time_s": 30 * 60}),  # no carry-share keys at all
    ("BOTTOM", {}),  # fully empty stats -> zero-ish grade
    ("ADC", _solid_stats(gold_share_pct=100.0, kp_pct=100.0)),  # saturated
)


class DefaultOffByteIdenticalTests(unittest.TestCase):
    """Contract 1: assume_carry_share_grade=False is byte-identical."""

    def test_param_exists_last_with_false_default(self):
        sig = inspect.signature(pgr.compute_role_grade)
        params = list(sig.parameters)
        self.assertIn("assume_carry_share_grade", params)
        # Appended at END (repo Python convention - no mid-signature insert).
        self.assertEqual(params[-1], "assume_carry_share_grade")
        self.assertIs(
            sig.parameters["assume_carry_share_grade"].default, False
        )

    def test_omitted_equals_explicit_false_across_fixtures(self):
        for role, stats in _BYTE_IDENTICAL_FIXTURES:
            omitted = pgr.compute_role_grade(stats, role=role)
            explicit = pgr.compute_role_grade(
                stats, role=role, assume_carry_share_grade=False
            )
            # Full-dict equality: total_score, percentile_grade, and the
            # components dict must all match exactly.
            self.assertEqual(
                omitted, explicit, f"OFF drifted for role={role}"
            )

    def test_off_never_adds_carry_component(self):
        for role, stats in _BYTE_IDENTICAL_FIXTURES:
            result = pgr.compute_role_grade(
                stats, role=role, assume_carry_share_grade=False
            )
            self.assertNotIn("carry_efficiency", result["components"])


class OnMonotonicRaiseTests(unittest.TestCase):
    """Contract 2: ON with high gold_share / KP is a non-worse grade."""

    def test_on_adds_carry_component(self):
        result = pgr.compute_role_grade(
            _solid_stats(), role="ADC", assume_carry_share_grade=True
        )
        self.assertIn("carry_efficiency", result["components"])
        self.assertGreater(result["components"]["carry_efficiency"], 0.0)

    def test_on_never_lowers_total_across_fixtures(self):
        for role, stats in _BYTE_IDENTICAL_FIXTURES:
            off = pgr.compute_role_grade(stats, role=role)
            on = pgr.compute_role_grade(
                stats, role=role, assume_carry_share_grade=True
            )
            self.assertGreaterEqual(
                on["total_score"],
                off["total_score"],
                f"ON lowered total for role={role}",
            )

    def test_higher_gold_share_raises_more(self):
        # Difference-of-differences: the ON-vs-OFF delta grows with gold_share.
        low = pgr.compute_role_grade(
            _solid_stats(gold_share_pct=10.0),
            role="ADC",
            assume_carry_share_grade=True,
        )
        high = pgr.compute_role_grade(
            _solid_stats(gold_share_pct=40.0),
            role="ADC",
            assume_carry_share_grade=True,
        )
        self.assertGreater(high["total_score"], low["total_score"])

    def test_higher_kp_raises_more(self):
        low = pgr.compute_role_grade(
            _solid_stats(kp_pct=20.0),
            role="ADC",
            assume_carry_share_grade=True,
        )
        high = pgr.compute_role_grade(
            _solid_stats(kp_pct=100.0),
            role="ADC",
            assume_carry_share_grade=True,
        )
        self.assertGreater(high["total_score"], low["total_score"])

    def test_grade_bucket_never_drops_on(self):
        # The bucket (letter grade) can only improve or hold, never regress.
        order = {"D": 0, "C": 1, "B": 2, "A": 3, "S": 4, "S+": 5}
        for role, stats in _BYTE_IDENTICAL_FIXTURES:
            off = pgr.compute_role_grade(stats, role=role)
            on = pgr.compute_role_grade(
                stats, role=role, assume_carry_share_grade=True
            )
            self.assertGreaterEqual(
                order[on["percentile_grade"]],
                order[off["percentile_grade"]],
                f"grade bucket regressed for role={role}",
            )

    def test_alias_matches_carry_efficiency(self):
        # assume_carry_share_grade is the ORUN5 alias of carry_efficiency -
        # both arm the identical fold, so results match exactly.
        stats = _solid_stats()
        via_alias = pgr.compute_role_grade(
            stats, role="ADC", assume_carry_share_grade=True
        )
        via_original = pgr.compute_role_grade(
            stats, role="ADC", carry_efficiency=True
        )
        self.assertEqual(via_alias, via_original)


class FailSoftTests(unittest.TestCase):
    """Contract 3: ON with absent carry-share stats is a 0.0 bonus, no crash."""

    def test_missing_both_keys_zero_bonus(self):
        stats = {
            "kills": 5,
            "deaths": 4,
            "assists": 7,
            "cs": 180,
            "game_time_s": 26 * 60,
            "vision_score": 16,
            "obj_participation_pct": 0.18,
            "damage_dealt_to_champions": 700 * 26,
        }
        off = pgr.compute_role_grade(stats, role="ADC")
        on = pgr.compute_role_grade(
            stats, role="ADC", assume_carry_share_grade=True
        )
        # Component present but 0.0; total_score unchanged from OFF.
        self.assertEqual(on["components"]["carry_efficiency"], 0.0)
        self.assertEqual(on["total_score"], off["total_score"])

    def test_none_values_fail_soft(self):
        stats = _solid_stats(gold_share_pct=None, kp_pct=None)
        result = pgr.compute_role_grade(
            stats, role="ADC", assume_carry_share_grade=True
        )
        self.assertEqual(result["components"]["carry_efficiency"], 0.0)

    def test_empty_stats_no_crash(self):
        result = pgr.compute_role_grade(
            {}, role="ADC", assume_carry_share_grade=True
        )
        self.assertEqual(result["components"]["carry_efficiency"], 0.0)
        self.assertGreaterEqual(result["total_score"], 0.0)


class BoundedBonusTests(unittest.TestCase):
    """Contract 4: the additive bonus is bounded (no S+ overflow pathology)."""

    def test_total_score_clamped_to_100(self):
        # Everything maxed (stats + carry-share saturated) still clamps to 100.
        stats = _solid_stats(
            kills=40,
            deaths=0,
            assists=40,
            cs=500,
            vision_score=200,
            obj_participation_pct=1.0,
            damage_dealt_to_champions=5000 * 28,
            gold_share_pct=100.0,
            kp_pct=100.0,
        )
        result = pgr.compute_role_grade(
            stats, role="ADC", assume_carry_share_grade=True
        )
        self.assertLessEqual(result["total_score"], 100.0)
        self.assertGreaterEqual(result["total_score"], 0.0)

    def test_carry_component_bounded(self):
        # Even at 100% gold_share + 100% KP the carry component is capped. Each
        # of the two sub-axes carries half the weight and clamps to 2x, so the
        # max carry contribution = 2 * (weight / 2) * 2 = 2 * weight = 1.0 ->
        # at most 10 points of total_score.
        stats = _solid_stats(gold_share_pct=100.0, kp_pct=100.0)
        result = pgr.compute_role_grade(
            stats, role="ADC", assume_carry_share_grade=True
        )
        self.assertLessEqual(
            result["components"]["carry_efficiency"],
            2.0 * pgr._CARRY_EFFICIENCY_WEIGHT,
        )

    def test_floor_game_does_not_vault_to_s_plus(self):
        # A weak stat line with maxed carry-share must NOT reach S+ on the fold
        # alone - the bonus is a nudge (at most +10 total_score), not a
        # re-baseline. A near-zero base cannot cross the 85 S+ floor.
        weak = {
            "kills": 0,
            "deaths": 10,
            "assists": 0,
            "cs": 10,
            "game_time_s": 30 * 60,
            "vision_score": 2,
            "obj_participation_pct": 0.0,
            "damage_dealt_to_champions": 100,
            "gold_share_pct": 100.0,
            "kp_pct": 100.0,
        }
        result = pgr.compute_role_grade(
            weak, role="ADC", assume_carry_share_grade=True
        )
        self.assertNotEqual(result["percentile_grade"], "S+")


if __name__ == "__main__":
    unittest.main()
