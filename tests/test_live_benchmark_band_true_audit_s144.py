"""s144 true-audit (lane 8) regression tests for core.live_benchmark_band.

band_metrics / band_from_state promise "pure + fail-soft ... Never raises" and
band only a plausible live value against a trustworthy distribution. Measured
at HEAD before this slice:

  F1  a >1e308 int game time / cs / level raised OverflowError (float() of a
      long int), a non-str mode raised AttributeError, an unhashable champion
      raised TypeError and a str tolerance raised TypeError.
  F2  a NaN cs banded "top quartile" (every NaN comparison is False, so it fell
      through to above-p75) and carried a bare NaN into the band dict the shadow
      writer json.dumps; inf banded top quartile, -5 cs bottom quartile, level 0
      and level 99 banded.
  F3  a str game time was float()-parsed ("600", " 6e2 ", "6_00" banded) while
      band_from_state and the cs / level fields refuse strings.
  F4  an infinite / huge tolerance opened BOTH checkpoints at any clock (cs at
      33:20 banded as cs_at_10 and cs_at_15), and min_games <= 0 resolved to a
      mode with ZERO games, hiding the real distribution.
  F5  a padded champion (" Tristana ") missed the benchmark lookup; a long
      name was looked up.
  F6  a distribution with a NaN / non-number / out-of-order percentile was
      banded (NaN p25..p75 -> every value "top quartile") and a junk p50 was
      passed through.
  F7  band_from_state took a NaN game_time_s instead of the game_seconds alias.

The real core.benchmarks banding runs against an in-memory stub cache (the same
seam tests/test_live_benchmark_band.py uses), so no gitignored data is read.
"""
from __future__ import annotations

import json
import math

import pytest

from core import benchmarks
from core import live_benchmark_band as lbb

_NAN = float("nan")
_INF = float("inf")


class _StubCache:
    def __init__(self, data):
        self._d = data

    def all(self):
        return self._d


def _metrics(cs10=(60.0, 75.0, 90.0), cs15=(100.0, 120.0, 140.0),
             lvl10=(6.0, 7.0, 8.0)):
    out = {}
    for key, tup in (("cs_at_10", cs10), ("cs_at_15", cs15),
                     ("level_at_10", lvl10)):
        if tup is not None:
            out[key] = {"p25": tup[0], "p50": tup[1], "p75": tup[2]}
    return out


def _install(monkeypatch, champions=None, **metric_kw):
    if champions is None:
        champions = {"Tristana|sr": {"games": 20, "metrics": _metrics(**metric_kw)}}
    monkeypatch.setattr(benchmarks, "_cache", _StubCache({"champions": champions}))


def _metric_set(bands):
    return {b["metric"] for b in bands}


# ---------------------------------------------------------------------------
# Baseline: valid input still bands (guards against an over-tight fix).
# ---------------------------------------------------------------------------
def test_valid_input_still_bands(monkeypatch):
    _install(monkeypatch)
    out = lbb.band_metrics("Tristana", 600, cs=80, level=7)
    assert [(b["metric"], b["band"], b["value"], b["p50"]) for b in out] == [
        ("cs_at_10", "p50-p75", 80.0, 75.0),
        ("level_at_10", "p50-p75", 7.0, 7.0),
    ]
    assert out[0]["line"] == "CS at 10: above your Tristana median."
    out15 = lbb.band_metrics("Tristana", 900.0, cs=150.0)
    assert [(b["metric"], b["band"]) for b in out15] == [("cs_at_15", "above-p75")]


def test_valid_band_from_state_still_bands(monkeypatch):
    _install(monkeypatch)
    out = lbb.band_from_state({"champion": "Tristana", "game_time_s": 610.0,
                               "cs": 50, "level": 6})
    assert [(b["metric"], b["band"]) for b in out] == [
        ("cs_at_10", "below-p25"), ("level_at_10", "p25-p50")]


# ---------------------------------------------------------------------------
# F1: never raises.
# ---------------------------------------------------------------------------
_BIG = 10 ** 400


@pytest.mark.parametrize("kwargs", [
    {"game_time_s": _BIG, "cs": 80},
    {"game_time_s": -_BIG, "cs": 80},
    {"game_time_s": 600, "cs": _BIG},
    {"game_time_s": 600, "level": _BIG},
    {"game_time_s": 600, "cs": -_BIG, "level": -_BIG},
    {"game_time_s": 600, "cs": 80, "mode": 5},
    {"game_time_s": 600, "cs": 80, "mode": ["SR"]},
    {"game_time_s": 600, "cs": 80, "mode": b"SR"},
    {"game_time_s": 600, "cs": 80, "tolerance_s": "45"},
    {"game_time_s": 600, "cs": 80, "tolerance_s": [45]},
    {"game_time_s": 600, "cs": 80, "tolerance_s": _BIG},
    {"game_time_s": 600, "cs": 80, "min_games": _BIG},
    {"game_time_s": 600, "cs": 80, "min_games": [5]},
])
def test_f1_band_metrics_never_raises(monkeypatch, kwargs):
    _install(monkeypatch)
    gt = kwargs.pop("game_time_s")
    out = lbb.band_metrics("Tristana", gt, **kwargs)
    assert isinstance(out, list)


@pytest.mark.parametrize("champ", [["Tristana"], {"a": 1}, {"Tristana"},
                                   bytearray(b"Tristana")])
def test_f1_unhashable_champion_never_raises(monkeypatch, champ):
    _install(monkeypatch)
    assert lbb.band_metrics(champ, 600, cs=80) == []


@pytest.mark.parametrize("state", [
    {"champion": "Tristana", "game_time_s": _BIG, "cs": 80},
    {"champion": "Tristana", "game_time_s": 600, "cs": _BIG},
    {"champion": "Tristana", "game_time_s": 600, "level": -_BIG},
    {"champion": "Tristana", "game_seconds": _BIG, "cs": 80},
])
def test_f1_band_from_state_never_raises(monkeypatch, state):
    _install(monkeypatch)
    out = lbb.band_from_state(state)
    assert isinstance(out, list)


def test_f1_band_from_state_non_str_mode_never_raises(monkeypatch):
    _install(monkeypatch)
    assert lbb.band_from_state({"champion": "Tristana", "game_time_s": 600,
                                "cs": 80}, mode=1) == []


# ---------------------------------------------------------------------------
# F2: a junk live value is no reading, never a quartile.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("cs", [_NAN, _INF, -_INF, -5, -0.5, 10 ** 5 + 1, 1e9,
                                _BIG])
def test_f2_junk_cs_is_not_banded(monkeypatch, cs):
    _install(monkeypatch)
    assert "cs_at_10" not in _metric_set(lbb.band_metrics("Tristana", 600, cs=cs))
    assert "cs_at_15" not in _metric_set(lbb.band_metrics("Tristana", 900, cs=cs))


@pytest.mark.parametrize("level", [_NAN, _INF, -_INF, 0, 0.5, -3, 31, 99, _BIG])
def test_f2_junk_level_is_not_banded(monkeypatch, level):
    _install(monkeypatch)
    assert lbb.band_metrics("Tristana", 600, level=level) == []


def test_f2_junk_value_does_not_cost_the_other_metric(monkeypatch):
    _install(monkeypatch)
    out = lbb.band_metrics("Tristana", 600, cs=_NAN, level=7)
    assert _metric_set(out) == {"level_at_10"}
    out = lbb.band_metrics("Tristana", 600, cs=80, level=99)
    assert _metric_set(out) == {"cs_at_10"}


@pytest.mark.parametrize("cs,level", [(0, 1), (10 ** 5, 30), (0.0, 30.0)])
def test_f2_range_edges_are_banded(monkeypatch, cs, level):
    _install(monkeypatch)
    assert _metric_set(lbb.band_metrics("Tristana", 600, cs=cs, level=level)) == {
        "cs_at_10", "level_at_10"}


def test_f2_band_dicts_are_strict_json(monkeypatch):
    _install(monkeypatch)
    for cs in (_NAN, _INF, -_INF, 80):
        out = lbb.band_metrics("Tristana", 600, cs=cs, level=7)
        json.dumps(out, allow_nan=False)  # raises ValueError on NaN / inf
        for b in out:
            assert math.isfinite(b["value"])


# ---------------------------------------------------------------------------
# F3: game time is a finite number in 0..10**6, never a parsed string.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("gt", ["600", " 6e2 ", "6_00", "600.0", b"600",
                                True, _INF, -_INF, 10 ** 6 + 600, -600])
def test_f3_junk_game_time_is_no_reading(monkeypatch, gt):
    _install(monkeypatch)
    assert lbb.band_metrics("Tristana", gt, cs=80, level=7) == []


def test_f3_float_and_int_game_time_band(monkeypatch):
    _install(monkeypatch)
    assert lbb.band_metrics("Tristana", 600, cs=80)
    assert lbb.band_metrics("Tristana", 600.0, cs=80)
    assert lbb.band_metrics("Tristana", 555, cs=80)  # lower window edge


# ---------------------------------------------------------------------------
# F4: junk knobs keep their defaults.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("tol", [_INF, _NAN, 10 ** 9, 150.0, 1e6, -1, True,
                                 "45"])
def test_f4_junk_tolerance_uses_default(monkeypatch, tol):
    _install(monkeypatch)
    # 2000 s is far from both checkpoints: the default window bands nothing.
    assert lbb.band_metrics("Tristana", 2000, cs=80, tolerance_s=tol) == []
    # 600 s is inside the default window: a junk knob must not close it.
    assert lbb.band_metrics("Tristana", 600, cs=80, tolerance_s=tol)
    # A clock between the checkpoints never bands both at once.
    out = lbb.band_metrics("Tristana", 750, cs=80, tolerance_s=tol)
    assert not ({"cs_at_10", "cs_at_15"} <= _metric_set(out))


def test_f4_valid_tolerance_is_honoured(monkeypatch):
    _install(monkeypatch)
    assert lbb.band_metrics("Tristana", 700, cs=80, tolerance_s=100) != []
    assert lbb.band_metrics("Tristana", 610, cs=80, tolerance_s=0) == []
    assert lbb.band_metrics("Tristana", 600, cs=80, tolerance_s=0) != []
    assert lbb.band_metrics("Tristana", 749, cs=80, tolerance_s=149.9) != []


def test_f4_zero_min_games_does_not_hide_the_distribution(monkeypatch):
    # sr_ranked has no row (0 games); the real distribution is under "sr".
    _install(monkeypatch)
    for mg in (0, -1, True, False, 5.0, _NAN, "5", None):
        out = lbb.band_metrics("Tristana", 600, cs=80, min_games=mg)
        assert _metric_set(out) == {"cs_at_10"}, mg


def test_f4_bool_min_games_is_not_a_floor_of_one(monkeypatch):
    # 3 games: thin under the default floor of 5, enough under a floor of 1.
    _install(monkeypatch, {"Tristana|sr": {"games": 3, "metrics": _metrics()}})
    assert lbb.band_metrics("Tristana", 600, cs=80, min_games=1) != []
    assert lbb.band_metrics("Tristana", 600, cs=80, min_games=True) == []
    assert lbb.band_metrics("Tristana", 600, cs=80, min_games=False) == []


def test_f4_valid_min_games_is_honoured(monkeypatch):
    _install(monkeypatch)
    assert lbb.band_metrics("Tristana", 600, cs=80, min_games=21) == []
    assert lbb.band_metrics("Tristana", 600, cs=80, min_games=20) != []
    assert lbb.band_metrics("Tristana", 600, cs=80, min_games=1) != []


@pytest.mark.parametrize("games", [True, "20", _NAN, _INF, None, [20]])
def test_f4_junk_games_count_is_not_trusted(monkeypatch, games):
    _install(monkeypatch, {"Tristana|sr": {"games": games,
                                           "metrics": _metrics()}})
    assert lbb.band_metrics("Tristana", 600, cs=80, min_games=1) == []


# ---------------------------------------------------------------------------
# F5: the champion is a short stripped str.
# ---------------------------------------------------------------------------
def test_f5_padded_champion_is_looked_up_and_printed_stripped(monkeypatch):
    _install(monkeypatch)
    out = lbb.band_metrics(" Tristana\t", 600, cs=80)
    assert _metric_set(out) == {"cs_at_10"}
    assert out[0]["line"] == "CS at 10: above your Tristana median."


@pytest.mark.parametrize("champ", [5, 5.0, True, None, b"Tristana", "",
                                   "   ", "T" * 65])
def test_f5_junk_champion_is_no_band(monkeypatch, champ):
    long_name = "T" * 65
    champs = {"Tristana|sr": {"games": 20, "metrics": _metrics()},
              f"{long_name}|sr": {"games": 20, "metrics": _metrics()}}
    _install(monkeypatch, champs)
    assert lbb.band_metrics(champ, 600, cs=80) == []


# ---------------------------------------------------------------------------
# F6: a degenerate distribution is no band; p50 is a finite number or None.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("tup", [(_NAN, _NAN, _NAN), (60.0, _NAN, 90.0),
                                 (60.0, 75.0, _INF), (90.0, 75.0, 60.0),
                                 (60.0, "75", 90.0), (True, 75.0, 90.0)])
def test_f6_degenerate_distribution_is_no_band(monkeypatch, tup):
    _install(monkeypatch, cs10=tup)
    out = lbb.band_metrics("Tristana", 600, cs=80, level=7)
    assert _metric_set(out) == {"level_at_10"}


def test_f6_equal_percentiles_still_band(monkeypatch):
    _install(monkeypatch, cs10=(75.0, 75.0, 75.0))
    out = lbb.band_metrics("Tristana", 600, cs=80)
    assert [(b["band"], b["p50"]) for b in out] == [("above-p75", 75.0)]


# ---------------------------------------------------------------------------
# F7: band_from_state reads a junk number as no reading and falls through.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("junk", [_NAN, _INF, _BIG, -600, 10 ** 6 + 600,
                                  2e6, True])
def test_f7_junk_game_time_falls_through_to_game_seconds(monkeypatch, junk):
    _install(monkeypatch)
    out = lbb.band_from_state({"champion": "Tristana", "game_time_s": junk,
                               "game_seconds": 600, "cs": 80})
    assert _metric_set(out) == {"cs_at_10"}


def test_f7_junk_cs_in_state_is_not_banded(monkeypatch):
    _install(monkeypatch)
    out = lbb.band_from_state({"champion": "Tristana", "game_time_s": 600,
                               "cs": _NAN, "level": 7})
    assert _metric_set(out) == {"level_at_10"}
