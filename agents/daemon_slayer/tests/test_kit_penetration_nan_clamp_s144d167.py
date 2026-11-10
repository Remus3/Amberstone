"""S144-D-167 - ``_kit_penetration._clamp01`` never lets NaN through.

Measured at HEAD (lane/ds, 2026-11-08): ``_clamp01(nan)`` returned NaN (both of
its comparisons are False for NaN). So ``resolve_kit_penetration("Nilah",
crit_chance=nan)`` returned ``pct=nan``, and ``apply_kit_penetration(100.0, [],
11, champion="Nilah", enabled=True, crit_chance=nan)`` returned 0.0 effective
armor: full penetration, past Nilah's 33 percent endpoint (83.5 at crit 0.5,
67.0 at crit 1.0). An ``extra_pct`` NaN made any champion's ``pct`` NaN
(Darius 0.4 -> nan).

Contract after the fix: a NaN fraction reads as 0.0, the same as junk input
already did; +inf still reads as 1.0 and -inf as 0.0. Finite values are
unchanged.
"""
from __future__ import annotations

import math

import pytest

from agents.daemon_slayer import _kit_penetration as kp

_NAN = float("nan")
_INF = float("inf")


@pytest.mark.parametrize(
    "value,expected",
    [(_NAN, 0.0), (-_INF, 0.0), (_INF, 1.0), (-0.2, 0.0), (0.0, 0.0),
     (0.25, 0.25), (1.0, 1.0), (3.0, 1.0), ("junk", 0.0), (None, 0.0)],
)
def test_clamp01(value, expected):
    assert kp._clamp01(value) == expected


def test_nan_crit_reads_as_zero_crit():
    # Anchor: Nilah's crit-scaled row really pays at a real crit chance.
    assert kp.resolve_kit_penetration("Nilah", crit_chance=0.5).pct > 0.0
    got = kp.resolve_kit_penetration("Nilah", crit_chance=_NAN)
    assert got == kp.resolve_kit_penetration("Nilah", crit_chance=0.0)
    assert got.pct == 0.0


def test_nan_crit_never_zeroes_the_target_armor():
    half = kp.apply_kit_penetration(100.0, [], 11, champion="Nilah", enabled=True,
                                    crit_chance=0.5)
    assert half < 100.0  # anchor: the seam bites
    got = kp.apply_kit_penetration(100.0, [], 11, champion="Nilah", enabled=True,
                                   crit_chance=_NAN)
    assert got == 100.0


@pytest.mark.parametrize("champion", ["Darius", "Jhin"])
def test_nan_extra_pct_adds_nothing(champion):
    base = kp.resolve_kit_penetration(champion)
    got = kp.resolve_kit_penetration(champion, extra_pct=[_NAN])
    assert math.isfinite(got.pct)
    assert got.pct == base.pct
    assert got.flat == base.flat
    assert kp.resolve_kit_penetration(champion, extra_pct=[0.5]).pct > base.pct
