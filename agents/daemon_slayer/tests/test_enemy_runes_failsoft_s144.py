"""Fail-soft contract of the DSP6 enemy-rune seam (S144-T-571).

``agents/daemon_slayer/enemy_runes.py`` promises "fail-soft (never raises;
unknown rune -> 0.0)" and "bad numbers -> 0.0". Measured at the lane base:

* one junk id (``"x"``, ``None``, an object) zeroed the WHOLE id set, so
  ``enemy_incoming_amp_pct(["x", 8005])`` was 0.0, not 0.08;
* a non-finite id raised ``OverflowError`` out of every helper;
* a fractional id (``8005.5``) was truncated onto Press the Attack;
* a bare scalar id (``8005``) read as an empty set and a bare string
  (``"8437"``) was iterated character by character;
* an unhashable rune id raised ``TypeError`` out of
  ``compute_enemy_rune_value``, and a digit-string id read as unknown;
* an infinite level zeroed Conqueror instead of reading as level 1;
* a NaN / infinite / negative / bool HP came back as a NaN, infinite or
  negative HP total;
* ``antiheal_present="false"`` and ``ranged="false"`` were truthy.

Well-formed input keeps its output byte-for-byte (``TestWellFormedGolden``).
The ``dsp_live_consumers`` wrapper already pre-sanitizes, so the DS routes were
not affected; direct callers of this module were.
"""

import math
import unittest
from decimal import Decimal
from fractions import Fraction

from agents.daemon_slayer import enemy_runes as er

PTA, CONQ, GRASP, SECOND_WIND = 8005, 8010, 8437, 8444
NAN = float("nan")
INF = float("inf")


class TestJunkIdDropsAlone(unittest.TestCase):
    def test_junk_id_does_not_zero_incoming_amp(self):
        self.assertEqual(er.enemy_incoming_amp_pct(["x", PTA]), 0.08)
        self.assertEqual(er.enemy_incoming_amp_pct([None, PTA, object()]), 0.08)

    def test_junk_id_does_not_zero_damage_ramp(self):
        self.assertAlmostEqual(er.enemy_damage_ramp([None, CONQ], 18), 48.0)

    def test_junk_id_does_not_zero_poke_sustain(self):
        self.assertEqual(er.enemy_poke_sustain_pct([object(), SECOND_WIND]), 0.04)
        self.assertAlmostEqual(
            er.enemy_poke_sustain_hp(["x", SECOND_WIND], 2000.0, 500.0), 20.0
        )

    def test_junk_id_does_not_zero_grasp_proc(self):
        self.assertAlmostEqual(er.enemy_grasp_magic_proc(["x", GRASP], 1000.0), 35.0)


class TestNonFiniteAndLookalikeIds(unittest.TestCase):
    def test_infinite_id_never_raises_and_drops_alone(self):
        for bad in (INF, -INF, NAN):
            self.assertEqual(er.enemy_incoming_amp_pct([bad, PTA]), 0.08)
            self.assertEqual(er.enemy_damage_ramp([bad]), 0.0)
            self.assertEqual(er.enemy_poke_sustain_pct([bad]), 0.0)
            self.assertEqual(er.enemy_poke_sustain_hp([bad], 2000.0, 0.0), 0.0)
            self.assertEqual(er.enemy_grasp_magic_proc([bad], 2000.0), 0.0)

    def test_fractional_id_is_not_a_lookalike(self):
        self.assertEqual(er.enemy_incoming_amp_pct([8005.5]), 0.0)
        self.assertEqual(er.enemy_grasp_magic_proc([8437.9], 1000.0), 0.0)

    def test_bool_id_is_not_an_id(self):
        self.assertEqual(er._iter_ids([True, False]), ())

    def test_integral_float_and_digit_string_are_ids(self):
        self.assertEqual(er.enemy_incoming_amp_pct([8005.0]), 0.08)
        self.assertEqual(er.enemy_incoming_amp_pct([" 8005 "]), 0.08)


class TestBareScalarIsOneId(unittest.TestCase):
    def test_bare_int(self):
        self.assertEqual(er.enemy_incoming_amp_pct(PTA), 0.08)
        self.assertAlmostEqual(er.enemy_grasp_magic_proc(GRASP, 1000.0), 35.0)

    def test_bare_string_is_not_split_into_characters(self):
        self.assertEqual(er.enemy_poke_sustain_pct("8444"), 0.04)
        self.assertEqual(er._iter_ids("8437"), (8437,))

    def test_non_iterable_is_empty(self):
        self.assertEqual(er.enemy_incoming_amp_pct(object()), 0.0)
        self.assertEqual(er._iter_ids(None), ())

    def test_only_plain_ascii_digit_strings_are_ids(self):
        self.assertEqual(er.enemy_incoming_amp_pct(["8_005"]), 0.0)
        self.assertEqual(er.enemy_incoming_amp_pct(["\u0668\u0660\u0660\u0665"]), 0.0)
        self.assertEqual(er.compute_enemy_rune_value("+8010", 18), 0.0)

    def test_iterable_raising_value_error_is_empty(self):
        def gen():
            yield PTA
            raise ValueError("torn feed")

        self.assertEqual(er.enemy_incoming_amp_pct(gen()), 0.0)

    def test_index_raising_value_error_drops_alone(self):
        class BadIndex:
            def __index__(self):
                raise ValueError("no")

        self.assertEqual(er.enemy_incoming_amp_pct([BadIndex(), PTA]), 0.08)

    def test_huge_int_id_is_unknown_not_an_error(self):
        self.assertEqual(er.enemy_incoming_amp_pct([10**400, PTA]), 0.08)


class TestComputeEnemyRuneValueId(unittest.TestCase):
    def test_unhashable_id_never_raises(self):
        self.assertEqual(er.compute_enemy_rune_value([CONQ]), 0.0)
        self.assertEqual(er.compute_enemy_rune_value({"id": CONQ}), 0.0)

    def test_digit_string_and_integral_float_resolve(self):
        self.assertAlmostEqual(er.compute_enemy_rune_value("8010", 18), 48.0)
        self.assertAlmostEqual(er.compute_enemy_rune_value(8010.0, 18), 48.0)

    def test_bool_and_fractional_ids_are_unknown(self):
        self.assertEqual(er.compute_enemy_rune_value(True), 0.0)
        self.assertEqual(er.compute_enemy_rune_value(8010.5, 18), 0.0)


class TestBadLevelReadsAsOne(unittest.TestCase):
    def test_non_finite_level_reads_as_level_one(self):
        for bad in (INF, -INF, NAN, True, object(), "nan", Fraction(10**400)):
            self.assertAlmostEqual(er.compute_enemy_rune_value(CONQ, level=bad), 21.6)
            self.assertAlmostEqual(er.enemy_damage_ramp([CONQ], bad), 21.6)

    def test_int_past_float_range_clamps(self):
        self.assertAlmostEqual(er.compute_enemy_rune_value(CONQ, level=10**400), 48.0)
        self.assertAlmostEqual(er.compute_enemy_rune_value(CONQ, level=-10**400), 21.6)

    def test_numeric_string_level_is_read(self):
        self.assertAlmostEqual(er.compute_enemy_rune_value(CONQ, level="18"), 48.0)
        self.assertAlmostEqual(er.compute_enemy_rune_value(CONQ, level="18.5"), 48.0)

    def test_private_clamp_never_raises(self):
        self.assertEqual(er._clamp_level(INF), 1)
        self.assertEqual(er._clamp_level(-INF), 1)


class TestBadHpIsZero(unittest.TestCase):
    BAD = (NAN, INF, -INF, -1000.0, True, None, "x", 10**400, "inf")

    def test_poke_sustain_hp_bad_max_hp(self):
        for bad in self.BAD:
            got = er.enemy_poke_sustain_hp([GRASP, SECOND_WIND], bad, 500.0)
            self.assertEqual(got, 0.0, bad)

    def test_poke_sustain_hp_bad_missing_hp(self):
        for bad in self.BAD:
            got = er.enemy_poke_sustain_hp([GRASP, SECOND_WIND], 2000.0, bad)
            self.assertEqual(got, 0.0, bad)

    def test_grasp_proc_bad_max_hp(self):
        for bad in self.BAD:
            self.assertEqual(er.enemy_grasp_magic_proc([GRASP], bad), 0.0, bad)

    def test_numeric_string_hp_is_still_read(self):
        self.assertAlmostEqual(er.enemy_grasp_magic_proc([GRASP], "1000"), 35.0)


class TestStrictFlags(unittest.TestCase):
    def test_antiheal_word_false_is_off(self):
        for off in ("false", "0", "", "no", None, NAN, 0, 0.0, object()):
            self.assertEqual(er.enemy_antiheal_pct(off), 0.0, off)

    def test_antiheal_true_forms_are_on(self):
        for on in (True, 1, "true", " Yes ", "on", "1", 2.5):
            self.assertEqual(er.enemy_antiheal_pct(on), 0.40, on)

    def test_other_numeric_flags(self):
        self.assertEqual(er.enemy_antiheal_pct(Decimal(1)), 0.40)
        self.assertEqual(er.enemy_antiheal_pct(Fraction(1, 2)), 0.40)
        self.assertEqual(er.enemy_antiheal_pct(Decimal("sNaN")), 0.0)
        self.assertEqual(er.enemy_antiheal_pct(Decimal(0)), 0.0)

    def test_int_past_float_range_never_raises(self):
        self.assertEqual(er.enemy_antiheal_pct(10**400), 0.40)
        self.assertEqual(er.enemy_poke_sustain_pct([GRASP], ranged=10**400), 0.0052)

    def test_ranged_word_false_is_melee(self):
        self.assertEqual(er.enemy_poke_sustain_pct([GRASP], ranged="false"), 0.013)
        self.assertAlmostEqual(
            er.enemy_poke_sustain_hp([GRASP], 1000.0, 0.0, ranged="false"), 18.0
        )
        self.assertAlmostEqual(
            er.enemy_grasp_magic_proc([GRASP], 1000.0, ranged="false"), 35.0
        )


class TestWellFormedGolden(unittest.TestCase):
    """Literal values from the pre-hardening module on well-formed input."""

    def test_amp_and_duplicates_sum(self):
        self.assertEqual(er.enemy_incoming_amp_pct([PTA, CONQ]), 0.08)
        self.assertEqual(er.enemy_incoming_amp_pct([PTA, PTA]), 0.16)

    def test_ramp_by_level(self):
        self.assertAlmostEqual(er.enemy_damage_ramp([CONQ], 1), 21.6)
        self.assertAlmostEqual(er.enemy_damage_ramp([CONQ], 9.9), 12.0 * (1.8 + 2.2 * 8 / 17))
        self.assertAlmostEqual(er.enemy_damage_ramp([CONQ], 18), 48.0)

    def test_poke_ranged_and_hp(self):
        self.assertAlmostEqual(er.enemy_poke_sustain_pct([GRASP, SECOND_WIND], True), 0.0452)
        self.assertAlmostEqual(
            er.enemy_poke_sustain_hp([GRASP, SECOND_WIND], 2000.0, 500.0, True),
            (0.013 * 2000.0 + 5.0) * 0.4 + 20.0,
        )
        self.assertAlmostEqual(er.enemy_poke_sustain_hp([GRASP], 0.0), 5.0)
        self.assertAlmostEqual(er.enemy_grasp_magic_proc([GRASP], 2000, True), 28.0)

    def test_every_output_finite(self):
        for v in (
            er.enemy_poke_sustain_hp([GRASP, SECOND_WIND], NAN, NAN),
            er.enemy_grasp_magic_proc([GRASP], INF),
        ):
            self.assertTrue(math.isfinite(v))


if __name__ == "__main__":
    unittest.main()
