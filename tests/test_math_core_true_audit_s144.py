"""s144 true-audit (cycle 125) of core/math_core.py.

Each test is named for the weakness it pins (RM-1597..242). The golden
parity file (tests/test_math_core_golden.py) proves the formulas against
external sources; this file proves the helpers are TOTAL and fail CLOSED on
input the goldens never feed them, and that the JavaScript ports agree with
node itself (the external oracle) well beyond the golden rows.
"""
from __future__ import annotations

import decimal
import json
import math
import random
import shutil
import subprocess
import sys

import pytest

from core import math_core as m

NAN = float("nan")
INF = float("inf")


# --------------------------------------------------------------------------
# Freshness (live path: core/liveclient_cache.Snapshot.age_s / is_fresh)


@pytest.mark.parametrize("bad_now", [NAN, INF, -INF, True, False, None, "100", [100.0]])
def test_s144_t234_freshness_unusable_now_fails_closed(bad_now):
    # A NaN clock read as age 0.0 and FRESH (max(0.0, nan) is 0.0).
    f = m.freshness(100.0, 8.0, now=bad_now)
    assert f.fresh is False
    assert f.age_s is None
    assert f.reason == "unknown"
    assert m.observation_age(100.0, now=bad_now) is None


@pytest.mark.parametrize("bad_skew", [NAN, INF, -1.0, True, "5", None])
def test_s144_t235_unusable_skew_is_refused_not_a_disabled_future_check(bad_skew):
    # A NaN skew made `age < -skew` always False: a timestamp 900 s in the
    # future read as FRESH with age 0.
    with pytest.raises(ValueError):
        m.freshness(1000.0, 8.0, now=100.0, max_skew_s=bad_skew)
    with pytest.raises(ValueError):
        m.observation_age(1000.0, now=100.0, max_skew_s=bad_skew)


def test_s144_t235_zero_skew_is_a_valid_strict_setting():
    assert m.observation_age(100.5, now=100.0, max_skew_s=0) is None
    assert m.observation_age(100.0, now=100.0, max_skew_s=0) == 0.0
    assert m.freshness(101.0, 8.0, now=100.0, max_skew_s=0.0).reason == "future"


@pytest.mark.parametrize("huge", [10**400, -(10**400)], ids=["huge-pos", "huge-neg"])
def test_s144_t236_out_of_range_int_timestamp_is_unknown_not_a_raise(huge):
    # float(10**400) raised OverflowError out of a helper documented as total.
    assert m.observation_age(huge, now=100.0) is None
    f = m.freshness(huge, 8.0, now=100.0)
    assert (f.fresh, f.age_s, f.reason) == (False, None, "unknown")


@pytest.mark.parametrize("bad_window", ["8", True, False, None, NAN, INF, -INF, 0, -1.0, [8.0]])
def test_s144_t237_freshness_window_must_be_a_positive_finite_number(bad_window):
    # "8" raised TypeError, True was a 1 s window, inf was a window that never
    # expires (always fresh, the opposite of a freshness check).
    with pytest.raises(ValueError):
        m.freshness(100.0, bad_window, now=100.0)


def test_s144_t237_int_window_is_still_accepted():
    assert m.freshness(100.0, 8, now=104.0).fresh is True


def test_freshness_characterization_unchanged():
    assert m.freshness(100.0, 8.0, now=105.0) == m.Freshness(True, 5.0, "fresh")
    assert m.freshness(100.0, 8.0, now=108.5) == m.Freshness(False, 8.5, "stale")
    assert m.freshness(120.0, 8.0, now=100.0) == m.Freshness(False, None, "future")
    assert m.freshness(102.0, 8.0, now=100.0) == m.Freshness(True, 0.0, "fresh")
    assert m.observation_age(100, now=103) == 3.0


# --------------------------------------------------------------------------
# to_fixed (JavaScript Number.prototype.toFixed port)


@pytest.mark.parametrize(
    "value,digits,expected",
    [
        (1e20, 10, "100000000000000000000.0000000000"),
        (123456789.123, 25, "123456789.1229999959468841552734375"),
        (5e-324, 100, "0." + "0" * 100),
    ],
)
def test_s144_t238_to_fixed_works_across_its_documented_domain(value, digits, expected):
    # Decimal.quantize ran under the ambient 28-digit context and raised
    # InvalidOperation for any result longer than 28 digits.
    assert m.to_fixed(value, digits) == expected


@pytest.mark.parametrize(
    "value,digits,expected",
    [(-0.001, 2, "-0.00"), (-0.4, 0, "-0"), (-1e-300, 5, "-0.00000"), (-0.0, 2, "0.00"), (0.0, 0, "0")],
)
def test_s144_t239_negative_that_rounds_to_zero_keeps_its_sign(value, digits, expected):
    # ECMA-262 toFixed takes the sign off FIRST; only -0 itself prints "0".
    assert m.to_fixed(value, digits) == expected


@pytest.mark.parametrize(
    "value,expected",
    [(INF, "Infinity"), (-INF, "-Infinity"), (NAN, "NaN"), (1e21, "1e+21"), (-1.5e25, "-1.5e+25")],
)
def test_s144_t240_non_finite_and_huge_follow_the_spec(value, expected):
    # inf raised InvalidOperation; 1e21 printed 22 fixed digits.
    assert m.to_fixed(value, 2) == expected


@pytest.mark.parametrize("bad_digits", [True, False, 2.5, "2", None, -1, 101])
def test_s144_t242_to_fixed_digits_must_be_an_int_in_range(bad_digits):
    with pytest.raises(ValueError):
        m.to_fixed(1.25, bad_digits)


# --------------------------------------------------------------------------
# The ambient decimal context must not reach a pure function


def test_s144_t241_rounding_ignores_a_lowered_ambient_precision():
    with decimal.localcontext() as ctx:
        ctx.prec = 3
        assert m.js_math_round(12345.4) == 12345.0
        assert m.to_fixed(12345.4, 1) == "12345.4"
        assert m.hud_health(12345.4) == 12346


def test_s144_t241_rounding_ignores_ambient_traps():
    with decimal.localcontext() as ctx:
        for sig in (decimal.Inexact, decimal.Rounded, decimal.FloatOperation):
            ctx.traps[sig] = True
        assert m.js_math_round(0.49999999999999994) == 0.0
        assert m.to_fixed(2.55, 1) == "2.5"
        assert m.hud_health(771.4) == 772


@pytest.mark.parametrize("bad", [NAN, INF, -INF])
def test_s144_t242_hud_health_non_finite_is_a_value_error(bad):
    # NaN raised ValueError but inf raised OverflowError.
    with pytest.raises(ValueError):
        m.hud_health(bad)


def test_js_math_round_characterization():
    assert m.js_math_round(2.5) == 3.0
    assert m.js_math_round(-2.5) == -2.0
    assert m.js_math_round(-20.5) == -20.0
    r = m.js_math_round(-0.5)
    assert r == 0 and math.copysign(1.0, r) < 0
    r = m.js_math_round(-0.0)
    assert r == 0 and math.copysign(1.0, r) < 0
    assert m.js_math_round(1e300) == 1e300
    assert math.isnan(m.js_math_round(NAN))
    assert m.js_math_round(-INF) == -INF
    assert m.hud_health(771.4) == 772 and m.hud_health(-0.5) == 0 and m.hud_health(5) == 5


# --------------------------------------------------------------------------
# node as the external oracle, far beyond the golden rows


def _oracle_values() -> list[float]:
    rng = random.Random(125)
    vals = [0.5, -0.5, 1.5, -1.5, 0.49999999999999994, -0.49999999999999994, 2**52 + 0.5,
            -(2**52) - 0.5, 2**53, 1e-7, -1e-7, 4503599627370495.5, -4503599627370495.5]
    for _ in range(300):
        exp = rng.randint(-12, 22)
        vals.append(rng.uniform(-1, 1) * 10**exp)
    for _ in range(100):
        vals.append(rng.randint(-10**6, 10**6) / 8.0)
    return vals


def _node(script: str):
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    out = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, timeout=60, creationflags=flags, check=True
    ).stdout
    return json.loads(out)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH")
def test_js_ports_agree_with_node_on_a_wide_sample():
    vals = _oracle_values()
    rng = random.Random(7)
    digits = [rng.randint(0, 100) for _ in vals]
    payload = json.dumps([[repr(v), d] for v, d in zip(vals, digits)])
    script = (
        "const rows=" + payload + ";"
        "process.stdout.write(JSON.stringify(rows.map(([s,d])=>{const x=Number(s);"
        "const r=Math.round(x);return [r,Object.is(r,-0),x.toFixed(d)];})));"
    )
    got = _node(script)
    assert len(got) == len(vals)
    for v, d, (r, neg0, fixed) in zip(vals, digits, got):
        mine = m.js_math_round(v)
        # JSON prints a large double as an integer literal; compare as doubles.
        assert mine == float(r), (v, mine, r)
        assert (mine == 0 and math.copysign(1.0, mine) < 0) == neg0, v
        assert m.to_fixed(v, d) == fixed, (v, d)
