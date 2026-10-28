"""Characterization + contract tests for ``core.aram_action_rule.decide_action``.

Stage 1 of the deterministic ARAM coach (Tier-1, no live wiring). The
function encodes the ARAM HP-band / wave-position decision tree that is
ALREADY documented in the coach user prompt, the ``=== ARAM DECISION
TREE ===`` block of ``coaches/aram_coach.py``. This is a correct-by-construction
surface that will later replace the ARAM per-tick Haiku action verdict
(the laning-VERDICT precompute measured 23% agreement vs Haiku and is a
settled dead-end; this tree is not a predictor, it is the operator's
own documented rule).

The cases below DEFINE the contract - they are the source of truth for
the ladder, the exact non-overlapping HP bands, the wave index shift,
and the [0,4] clamp. Do not relax an assertion to make an
implementation pass; fix the implementation.

Ladder (most -> least aggressive), index 0..4:
    0 ALL-IN | 1 POKE | 2 HOLD | 3 DISENGAGE | 4 FALL BACK
"""
from __future__ import annotations

import unittest


def _label(value):
    """Serialization-safe subTest label for an arbitrary hostile value.

    MEASURED 2026-07-26 under ``pytest -n 8``: pytest 9's
    ``_pytest/unittest.py:436`` addSubTest stuffs the RAW ``subTest``
    kwargs into ``SubtestContext(msg=..., kwargs=dict(test.params))``
    and emits a report for EVERY subtest, passing ones included. Under
    xdist that report crosses the execnet channel, and execnet's
    serializer only handles builtin primitives - a bare ``object()``
    raises ``execnet.gateway_base.DumpError: can't serialize <class
    'object'>`` from inside ``subTest.__exit__``, failing the parent
    test. Serially there is no channel, so the same matrix passes.
    Labelling by repr keeps the hostile inputs below byte-identical -
    only the reported label changes.

    CORRECTED 2026-07-28: this note used to name ``set()`` alongside
    ``object()``. Measured - execnet serializes a ``set`` fine, and
    ``object()`` is the only unserializable value in the matrix below.
    The grammar is now PINNED by ``tests/test_subtest_channel_guard.py``
    instead of restated from memory here, and the repo-root
    ``conftest.py`` gate fails any future instance serially too.
    """
    return repr(value)


class DecideActionContractTests(unittest.TestCase):
    """The exact (hp_pct, wave_pct, low_enemy_count) -> label contract."""

    CASES = [
        # (hp_pct, wave_pct, low_enemy_count, expected_label)
        # -- base HP bands at neutral wave (35..65), no shift --
        (90, 50, 2, "ALL-IN"),       # >80 + >=2 low -> top tier
        (90, 50, 0, "POKE"),         # >80 but <2 low -> demote to POKE
        (70, 50, 0, "POKE"),         # 60..80 -> POKE
        (50, 50, 0, "HOLD"),         # 40..<60 -> HOLD
        (35, 50, 0, "DISENGAGE"),    # 30..<40 -> DISENGAGE
        (20, 50, 0, "FALL BACK"),    # <30 -> FALL BACK
        # -- wave > 65 shifts one tier MORE aggressive (index - 1) --
        (70, 70, 0, "ALL-IN"),       # POKE(1) -> ALL-IN(0)
        (50, 20, 0, "DISENGAGE"),    # HOLD(2) -> DISENGAGE(3) (wave<35)
        # -- wave < 35 shifts one tier LESS aggressive (index + 1) --
        (70, 20, 0, "HOLD"),         # POKE(1) -> HOLD(2)
        # -- clamp at the ends --
        (90, 70, 2, "ALL-IN"),       # ALL-IN(0) - 1 clamps at 0
        (20, 20, 0, "FALL BACK"),    # FALL BACK(4) + 1 clamps at 4
        # -- None wave = neutral, no shift --
        (70, None, 0, "POKE"),
        # -- exact band boundaries (non-overlapping) --
        (80, 50, 2, "POKE"),         # 80 is in 60..80 band, NOT >80
        (81, 50, 2, "ALL-IN"),       # 81 is >80, with 2 low -> ALL-IN
        (81, 50, 1, "POKE"),         # 81 is >80 but <2 low -> POKE
        (60, 50, 0, "POKE"),         # 60 is bottom of 60..80
        (59, 50, 0, "HOLD"),         # 59 is top of 40..<60
        (40, 50, 0, "HOLD"),         # 40 is bottom of 40..<60
        (39, 50, 0, "DISENGAGE"),    # 39 is top of 30..<40
        (30, 50, 0, "DISENGAGE"),    # 30 is bottom of 30..<40
        (29, 50, 0, "FALL BACK"),    # 29 is <30
        # -- None hp = neutral guard -> HOLD --
        (None, 50, 0, "HOLD"),
    ]

    def test_contract_table(self) -> None:
        from core.aram_action_rule import decide_action

        for hp, wave, low, expected in self.CASES:
            with self.subTest(hp=hp, wave=wave, low=low):
                self.assertEqual(decide_action(hp, wave, low), expected)


class FailSoftTests(unittest.TestCase):
    """The rule never raises and always returns a canonical label."""

    LABELS = {"ALL-IN", "POKE", "HOLD", "DISENGAGE", "FALL BACK"}

    def test_none_hp_returns_hold(self) -> None:
        from core.aram_action_rule import decide_action

        self.assertEqual(decide_action(None, 50, 0), "HOLD")

    def test_non_numeric_hp_treated_as_neutral_hold(self) -> None:
        from core.aram_action_rule import decide_action

        self.assertEqual(decide_action("not-a-number", 50, 0), "HOLD")

    def test_non_numeric_wave_is_no_shift(self) -> None:
        from core.aram_action_rule import decide_action

        # Garbage wave coerces to the no-shift (neutral) case, so a
        # 70% HP base stays POKE rather than shifting.
        self.assertEqual(decide_action(70, "junk", 0), "POKE")

    def test_string_inputs_are_no_reading(self) -> None:
        from core.aram_action_rule import decide_action

        # A str is not a reading (s144 true-audit; it used to be float()-
        # parsed, so " 6e1 " read 60% and "1_000" read 1000%). A str hp is
        # the neutral HOLD, a str wave the no-shift case, a str low count 0.
        self.assertEqual(decide_action("90", 50, 2), "HOLD")
        self.assertEqual(decide_action(" 6e1 ", 50, 0), "HOLD")
        self.assertEqual(decide_action(70, "80", 0), "POKE")
        self.assertEqual(decide_action(90, 50, "2"), "POKE")

    def test_always_returns_canonical_label(self) -> None:
        from core.aram_action_rule import decide_action

        for hp in (None, -5, 0, 29, 30, 39, 40, 59, 60, 80, 81, 100, 150):
            for wave in (None, 0, 34, 35, 50, 65, 66, 100):
                for low in (0, 1, 2, 5):
                    out = decide_action(hp, wave, low)
                    self.assertIn(out, self.LABELS)

    def test_never_raises_on_garbage(self) -> None:
        from core.aram_action_rule import decide_action

        for args in [
            (object(), object(), object()),
            ([], {}, set()),
            (float("nan"), 50, 0),
            (90, float("nan"), 2),
        ]:
            with self.subTest(args=_label(args)):
                out = decide_action(*args)
                self.assertIn(out, self.LABELS)


class _RaisingFloat(float):
    """A float subclass whose __float__ raises (a hostile number)."""

    def __float__(self):
        raise RuntimeError("hostile __float__")


class _RaisingInt(int):
    """An int subclass whose __float__ / __int__ / __index__ raise."""

    def __float__(self):
        raise RuntimeError("hostile __float__")

    def __int__(self):
        raise RuntimeError("hostile __int__")

    def __index__(self):
        raise RuntimeError("hostile __index__")


class JunkInputHardeningTests(unittest.TestCase):
    """s144 true-audit: a junk input is no reading and never raises.

    Each case was measured against the pre-fix module; the comment names
    what it did then.
    """

    def test_inf_low_count_does_not_raise(self) -> None:
        from core.aram_action_rule import decide_action

        # int(inf) raised OverflowError out of a "never raises" function.
        self.assertEqual(decide_action(50, None, float("inf")), "HOLD")
        self.assertEqual(decide_action(90, None, float("inf")), "POKE")
        self.assertEqual(decide_action(90, None, float("-inf")), "POKE")
        self.assertEqual(decide_action(90, None, float("nan")), "POKE")

    def test_huge_int_hp_or_wave_does_not_raise(self) -> None:
        from core.aram_action_rule import decide_action

        # float(10**400) raised OverflowError (only TypeError / ValueError
        # were caught).
        self.assertEqual(decide_action(10**400, None, 0), "HOLD")
        self.assertEqual(decide_action(70, 10**400, 0), "POKE")
        self.assertEqual(decide_action(70, -(10**400), 0), "POKE")

    def test_raising_number_subclass_does_not_raise(self) -> None:
        from core.aram_action_rule import decide_action

        # A __float__ / __int__ raising RuntimeError propagated.
        self.assertEqual(decide_action(_RaisingFloat(70), 50, 0), "HOLD")
        self.assertEqual(decide_action(_RaisingInt(70), 50, 0), "HOLD")
        self.assertEqual(decide_action(70, _RaisingFloat(80), 0), "POKE")
        self.assertEqual(decide_action(90, 50, _RaisingInt(2)), "POKE")

    def test_raising_class_object_does_not_raise(self) -> None:
        from core.aram_action_rule import decide_action

        class _RaisingClass:
            @property
            def __class__(self):
                raise RuntimeError("hostile __class__")

        # An isinstance-first gate raises on it (the pre-fix float() path
        # did not; this pins the new gate, which checks the type first).
        self.assertEqual(decide_action(_RaisingClass(), 50, 0), "HOLD")
        self.assertEqual(decide_action(70, _RaisingClass(), 0), "POKE")
        self.assertEqual(decide_action(90, 50, _RaisingClass()), "POKE")

    def test_bool_is_never_a_reading(self) -> None:
        from core.aram_action_rule import decide_action

        # True hp read 1% -> FALL BACK; False wave read 0 -> one tier less
        # aggressive; a bool low count is a flag, not a count.
        self.assertEqual(decide_action(True, 50, 0), "HOLD")
        self.assertEqual(decide_action(False, 50, 0), "HOLD")
        self.assertEqual(decide_action(70, False, 0), "POKE")
        self.assertEqual(decide_action(70, True, 0), "POKE")
        self.assertEqual(decide_action(90, 50, True), "POKE")

    def test_hp_outside_its_band_is_neutral(self) -> None:
        from core.aram_action_rule import decide_action

        # -50 read FALL BACK and 1e300 read the top tier. 0..150 is the
        # band the caller admits (the producer allows up to 1.5x max HP).
        self.assertEqual(decide_action(-50, 50, 0), "HOLD")
        self.assertEqual(decide_action(-0.001, 50, 0), "HOLD")
        self.assertEqual(decide_action(1e300, 50, 2), "HOLD")
        self.assertEqual(decide_action(150.001, 50, 2), "HOLD")
        # The band edges are readings.
        self.assertEqual(decide_action(0, 50, 0), "FALL BACK")
        self.assertEqual(decide_action(150, 50, 2), "ALL-IN")

    def test_wave_outside_its_band_is_no_shift(self) -> None:
        from core.aram_action_rule import decide_action

        # -500 shifted one tier less aggressive, 1e9 one tier more.
        self.assertEqual(decide_action(70, -500, 0), "POKE")
        self.assertEqual(decide_action(70, 1e9, 0), "POKE")
        self.assertEqual(decide_action(70, 100.5, 0), "POKE")
        self.assertEqual(decide_action(70, -0.5, 0), "POKE")
        # The band edges are readings.
        self.assertEqual(decide_action(70, 0, 0), "HOLD")
        self.assertEqual(decide_action(70, 100, 0), "ALL-IN")

    def test_low_count_is_a_whole_number_in_band(self) -> None:
        from core.aram_action_rule import decide_action

        # 2.9 truncated to 2 and promoted ALL-IN; 10**9 promoted too. ARAM
        # fields five enemies, so a count is a whole 0..5.
        self.assertEqual(decide_action(90, 50, 2.9), "POKE")
        self.assertEqual(decide_action(90, 50, 10**9), "POKE")
        self.assertEqual(decide_action(90, 50, 6), "POKE")
        self.assertEqual(decide_action(90, 50, -2), "POKE")
        # An integral float and the band edge are counts.
        self.assertEqual(decide_action(90, 50, 2.0), "ALL-IN")
        self.assertEqual(decide_action(90, 50, 5), "ALL-IN")

    def test_int_and_float_subclasses_still_read(self) -> None:
        from core.aram_action_rule import decide_action

        class MyFloat(float):
            pass

        class MyInt(int):
            pass

        self.assertEqual(decide_action(MyFloat(90), MyInt(50), MyInt(2)), "ALL-IN")


if __name__ == "__main__":
    unittest.main()
