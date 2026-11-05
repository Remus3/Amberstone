"""s144 true-audit (RM-1044): core.relay_age.is_stale must never raise and
must fail CLOSED (report stale) on every argument it cannot age.

Measured against the RM-269 module before this pass:
- a JSON big-int `ts` (`10**400`) raised OverflowError out of `float(ts)`,
  although the docstring promises "not a finite number" reads stale;
- a non-number `max_age_s` or `now` raised TypeError at the comparison;
- a NaN `max_age_s` or `now` made every comparison False, so ANY stamp -
  even one an hour old - read FRESH (fail-open), and an infinite
  `max_age_s` did the same.
The relay's consumers gate whether a cached snapshot is served on this
answer, so a fail-open here serves arbitrarily old game state as current.
"""
from __future__ import annotations

import decimal
import fractions
import time

import pytest

from core import relay_age

NAN = float("nan")
INF = float("inf")


class _Big(int):
    """10**400 with a short repr, so the parametrize id stays readable."""

    def __repr__(self):
        return "Big(10**400)"


BIG = _Big(10**400)


class _FloatRaises:
    """A ts whose __float__ raises something other than TypeError/ValueError."""

    def __init__(self, exc):
        self._exc = exc

    def __float__(self):
        raise self._exc


class TestNeverRaisesOnTs:
    @pytest.mark.parametrize("ts", [10**400, -(10**400), 10**309],
                             ids=["1e400", "-1e400", "1e309"])
    def test_big_int_ts_is_stale_not_overflow(self, ts):
        assert relay_age.is_stale(ts, 12.0, now=100.0) is True

    @pytest.mark.parametrize("exc", [OverflowError("x"), ZeroDivisionError("x"),
                                     ArithmeticError("x")])
    def test_float_raising_arithmetic_error_is_stale(self, exc):
        assert relay_age.is_stale(_FloatRaises(exc), 12.0, now=100.0) is True

    def test_foreign_float_error_still_propagates(self):
        # Documented scope: only the conversion failures a JSON value or a
        # number can produce read stale; a bug in a foreign type surfaces.
        with pytest.raises(RuntimeError):
            relay_age.is_stale(_FloatRaises(RuntimeError("x")), 12.0, now=100.0)

    def test_signalling_nan_decimal_is_stale(self):
        assert relay_age.is_stale(decimal.Decimal("sNaN"), 12.0, now=100.0) is True

    @pytest.mark.parametrize("ts", [None, "", "x", b"", [], {}, object(), "nan",
                                    "-inf", NAN, INF, -INF])
    def test_junk_ts_is_stale(self, ts):
        assert relay_age.is_stale(ts, 12.0, now=100.0) is True

    def test_huge_finite_ts_whose_age_overflows_is_stale(self):
        # now - ts == -inf: neither raises nor reads fresh.
        assert relay_age.is_stale(1.7e308, 12.0, now=-1.7e308) is True


class TestMaxAgeFailsClosed:
    @pytest.mark.parametrize("max_age", [NAN, INF, -INF])
    def test_non_finite_max_age_reads_stale(self, max_age):
        # Before: NaN / +inf read an hour-old stamp as FRESH.
        assert relay_age.is_stale(100.0, max_age, now=100.0 + 3600.0) is True

    @pytest.mark.parametrize("max_age", [NAN, INF])
    def test_non_finite_max_age_stale_even_for_a_fresh_stamp(self, max_age):
        assert relay_age.is_stale(100.0, max_age, now=100.0) is True

    @pytest.mark.parametrize("max_age", [None, "12", b"12", [], object(), True,
                                         False, BIG])
    def test_non_number_max_age_reads_stale_not_raise(self, max_age):
        assert relay_age.is_stale(100.0, max_age, now=105.0) is True

    def test_bool_max_age_is_refused_not_read_as_one_second(self):
        # True would read as 1.0 s and pass a half-second-old stamp as fresh.
        assert relay_age.is_stale(100.0, True, now=100.5) is True

    def test_negative_max_age_is_always_stale(self):
        assert relay_age.is_stale(100.0, -1.0, now=100.0) is True

    def test_int_and_numeric_max_age_types_are_accepted(self):
        assert relay_age.is_stale(100.0, 12, now=105.0) is False
        assert relay_age.is_stale(100.0, decimal.Decimal(12), now=105.0) is False
        assert relay_age.is_stale(100.0, fractions.Fraction(12), now=105.0) is False


class TestNowFailsClosed:
    @pytest.mark.parametrize("now", [NAN, INF, -INF])
    def test_non_finite_now_reads_stale(self, now):
        assert relay_age.is_stale(100.0, 12.0, now=now) is True

    @pytest.mark.parametrize("now", ["x", "105", b"1", [], object(), True,
                                     BIG])
    def test_non_number_now_reads_stale_not_raise(self, now):
        assert relay_age.is_stale(100.0, 12.0, now=now) is True

    def test_bool_now_is_refused_not_read_as_epoch_one(self):
        # True would read as now=1.0 and age a ts of 1.0 as exactly fresh.
        assert relay_age.is_stale(1.0, 12.0, now=True) is True

    def test_int_now_is_accepted(self):
        assert relay_age.is_stale(100, 12, now=105) is False

    def test_default_now_is_wall_clock(self):
        assert relay_age.is_stale(time.time(), 12.0) is False
        assert relay_age.is_stale(time.time() - 60.0, 12.0) is True

    def test_non_finite_wall_clock_reads_stale(self, monkeypatch):
        monkeypatch.setattr(relay_age.time, "time", lambda: NAN)
        assert relay_age.is_stale(100.0, 12.0) is True


class TestCharacterization:
    """The RM-269 behaviour the hardening must keep."""

    def test_boundary_age_equal_to_max_is_fresh(self):
        assert relay_age.is_stale(100.0, 12.0, now=112.0) is False

    def test_just_over_max_is_stale(self):
        assert relay_age.is_stale(100.0, 12.0, now=112.001) is True

    def test_future_within_tolerance_is_fresh(self):
        tol = relay_age.FUTURE_TOLERANCE_S
        assert relay_age.is_stale(100.0 + tol, 12.0, now=100.0) is False

    def test_future_past_tolerance_is_stale(self):
        tol = relay_age.FUTURE_TOLERANCE_S
        assert relay_age.is_stale(100.0 + tol + 0.001, 12.0, now=100.0) is True

    def test_numeric_string_ts_still_ages(self):
        # Lenient on purpose: float() accepts it; garbage strings read stale.
        assert relay_age.is_stale("100.0", 12.0, now=105.0) is False

    def test_bool_ts_reads_stale(self):
        assert relay_age.is_stale(True, 12.0, now=100.0) is True
        assert relay_age.is_stale(False, 12.0, now=100.0) is True

    def test_return_is_a_real_bool(self):
        for args in [(100.0, 12.0, 105.0), (100.0, 12.0, 200.0),
                     (None, 12.0, 100.0), (100.0, NAN, 105.0)]:
            assert type(relay_age.is_stale(*args)) is bool


class TestRelaySelfHealSiteNeverRaises:
    """vision_server._relay.get_latest_liveclient calls is_stale OUTSIDE any
    try; a stored ts it cannot age must self-heal, not escape as a 500."""

    @pytest.mark.parametrize("bad_ts", [BIG, NAN, "junk"], ids=["big", "nan", "junk"])
    def test_unageable_ts_self_heals(self, monkeypatch, bad_ts):
        from vision_server import _relay
        calls = []

        def spy():
            calls.append(1)
            return {"data": {"fresh": True}, "ts": time.time()}

        monkeypatch.setattr(_relay, "GAME_HOST", "127.0.0.1")
        monkeypatch.setattr(_relay, "_maybe_self_read", spy)
        with _relay._liveclient_lock:
            saved = dict(_relay._liveclient)
            _relay._liveclient.update({"data": {"old": 1}, "ts": bad_ts})
        try:
            snap = _relay.get_latest_liveclient()
        finally:
            with _relay._liveclient_lock:
                _relay._liveclient.clear()
                _relay._liveclient.update(saved)
        assert calls == [1]
        assert snap["data"] == {"fresh": True}
