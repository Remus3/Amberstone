"""S144-D-164..166 - ``compute_ehp``'s float knobs never crash, go NaN or invert.

Measured at HEAD (lane/ds, 2026-11-08), Malphite L11 with Thornmail 3075 +
Spirit Visage 3065, mode SR (blended_ehp 4834.17 at the defaults):

- S144-D-164: ``external_resist_armor`` / ``external_resist_mr`` = +inf raised
  ZeroDivisionError (``max(0.0, inf)`` kept the inf, the resist curve divided by
  it). NaN already read as 0.0, only because ``max(0.0, nan)`` returns its first
  argument.
- S144-D-165: ``external_revive_multiplier`` = +inf and ``external_flat_hp`` =
  +inf returned a NaN blended_ehp.
- S144-D-166: ``_clamp_pct`` let NaN through (both of its comparisons are False
  for NaN), so a NaN ``enemy_shred_pct`` / ``enemy_armor_pen_pct`` /
  ``enemy_magic_pen_pct`` read as MORE than the 0.99 cap: blended 3148.73 for
  either armor knob, below the 3165.58 a 2.0 (capped 0.99) pen gives, and
  3813.04 for magic pen, below its own 3823.26 cap; the note printed "nan%".

Contract after the fix: a non-finite external knob reads as its default
(0.0 / 0.0 / 1.0 / 0.0), the same thing NaN already did, and a NaN percent pen
term reads as 0.0 (no pen). The HTTP routes reject non-finite numbers before
the engine (``server._opt_float``), so only Python callers could reach these.
Every finite value is unchanged; +inf pen still reads as the 0.99 cap.
"""
from __future__ import annotations

import math

import pytest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import _clamp_pct, compute_ehp

_NAN = float("nan")
_INF = float("inf")
_ITEMS = ["3075", "3065"]


@pytest.fixture(scope="module")
def snap():
    return DataSnapshot.load()


def _ehp(snap, **kw):
    return compute_ehp(snap, "Malphite", 11, item_ids=_ITEMS, mode="SR", **kw)


def _finite_fields(r):
    for name in ("physical_ehp", "magical_ehp", "true_ehp", "blended_ehp"):
        assert math.isfinite(getattr(r, name)), name


# ---- S144-D-164: external resist ------------------------------------------


@pytest.mark.parametrize("key", ("external_resist_armor", "external_resist_mr"))
def test_external_resist_really_moves_ehp(snap, key):
    # Anchor: the knob is live, so the default-equality asserts are not vacuous.
    assert _ehp(snap, **{key: 50.0}).blended_ehp > _ehp(snap).blended_ehp


@pytest.mark.parametrize("key", ("external_resist_armor", "external_resist_mr"))
@pytest.mark.parametrize("bad", (_INF, -_INF, _NAN))
def test_non_finite_external_resist_reads_as_zero(snap, key, bad):
    got = _ehp(snap, **{key: bad})
    _finite_fields(got)
    assert got.blended_ehp == _ehp(snap).blended_ehp


# ---- S144-D-165: external revive and flat HP -------------------------------


def test_external_revive_and_flat_hp_really_move_ehp(snap):
    base = _ehp(snap).blended_ehp
    assert _ehp(snap, external_revive_multiplier=1.5).blended_ehp > base
    assert _ehp(snap, external_flat_hp=300.0).blended_ehp > base


@pytest.mark.parametrize("key", ("external_revive_multiplier", "external_flat_hp"))
@pytest.mark.parametrize("bad", (_INF, -_INF, _NAN))
def test_non_finite_revive_or_flat_hp_reads_as_default(snap, key, bad):
    got = _ehp(snap, **{key: bad})
    _finite_fields(got)
    assert got.blended_ehp == _ehp(snap).blended_ehp
    assert not any("nan" in n or "inf" in n for n in got.notes)


@pytest.mark.parametrize(
    "key,value", (("external_revive_multiplier", 0.5), ("external_flat_hp", -500.0))
)
def test_finite_floors_unchanged(snap, key, value):
    assert _ehp(snap, **{key: value}).blended_ehp == _ehp(snap).blended_ehp


# ---- S144-D-166: NaN percent pen -------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    ((_NAN, 0.0), (-_INF, 0.0), (_INF, 0.99), (-0.5, 0.0), (0.0, 0.0),
     (0.4, 0.4), (0.99, 0.99), (2.0, 0.99)),
)
def test_clamp_pct(value, expected):
    assert _clamp_pct(value) == expected


@pytest.mark.parametrize(
    "key", ("enemy_shred_pct", "enemy_armor_pen_pct", "enemy_magic_pen_pct")
)
def test_nan_pen_pct_reads_as_no_pen(snap, key):
    base = _ehp(snap)
    capped = _ehp(snap, **{key: 2.0})
    assert capped.blended_ehp < base.blended_ehp  # anchor: the knob bites
    got = _ehp(snap, **{key: _NAN})
    _finite_fields(got)
    assert got.blended_ehp == base.blended_ehp
    assert got.blended_ehp >= capped.blended_ehp
    assert not any("nan" in n for n in got.notes)


@pytest.mark.parametrize(
    "key", ("enemy_shred_pct", "enemy_armor_pen_pct", "enemy_magic_pen_pct")
)
def test_inf_pen_pct_still_reads_as_the_cap(snap, key):
    assert _ehp(snap, **{key: _INF}).blended_ehp == _ehp(snap, **{key: 0.99}).blended_ehp
