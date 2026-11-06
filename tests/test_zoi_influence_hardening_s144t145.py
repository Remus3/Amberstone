"""s144 true-audit cycle 145 - core/zoi_influence.py hardening (RM-1847..RM-1853).

compute_zoi is documented "fail-soft, NEVER raises" and feeds /api/state.zoi,
which the dashboard serves as strict JSON. Each test below was RED against the
pre-hardening module:

- RM-1847 a truthy non-iterable `dots` (an int, a float, True, an object)
  raised TypeError from the `for d in dots` loop.
- RM-1848 an over-64-bit int in px / x_frac / y_frac / confidence /
  my_level / game_time_s raised OverflowError out of `_num` (float(10**400)).
- RM-1849 a finite px * confidence that overflows to inf (or a weight sum
  that does) turned the weighted centroid into NaN and raised ValueError from
  int(round(nan)) on the ally control percentage.
- RM-1850 a negative px times a negative confidence read as POSITIVE
  presence (-50 * -0.9 = 45) and inflated the bubble; a confidence above the
  documented [0,1] range inflated weight and radius past the producer's domain.
- RM-1851 a malformed `base_fallback` (None, non-numeric, wrong length)
  raised TypeError on unpack or on the quadrant comparison.
- RM-1852 a capability helper returning a non-number raised TypeError on
  `r_frac * cap`; a NaN / inf / negative one put a non-finite or negative
  radius into the payload.
- RM-1853 zoi_callout passed a None / non-str / blank / multi-line `line`
  straight into the callout row.

Well-formed input stays byte-identical (golden pins at the bottom).
Synthetic fixtures only.
"""
from __future__ import annotations

import json
import math

import pytest

import core.zoi_capability as zcap
from core.zoi_influence import _R_MIN_FRAC, compute_zoi, zoi_callout


def _dot(team, x, y, px=40, conf=0.8, **extra):
    d = {"team": team, "x_frac": x, "y_frac": y, "px": px, "confidence": conf}
    d.update(extra)
    return d


def _strict(z):
    """The payload must survive strict JSON (no NaN / Infinity tokens)."""
    return json.loads(json.dumps(z, allow_nan=False))


def _assert_sane(z):
    assert z is not None
    _strict(z)
    pct = z["map_control"]["ally_control_pct"]
    assert isinstance(pct, int) and 0 <= pct <= 100
    for b in z["bubbles"]:
        assert math.isfinite(b["r_frac"]) and b["r_frac"] >= 0.0
        assert math.isfinite(b["weight"]) and b["weight"] >= 0.0
        assert 0.0 <= b["cx"] <= 1.0 and 0.0 <= b["cy"] <= 1.0


# --- RM-1847: non-iterable dots ----------------------------------------

@pytest.mark.parametrize("dots", [5, 3.5, True, object()])
def test_non_iterable_dots_returns_none(dots):
    assert compute_zoi(dots, my_level=6, game_time_s=600) is None


def test_dict_and_str_dots_still_none():
    # characterization: iterating a dict / str yields no valid dot -> None
    assert compute_zoi({"team": "blue"}, my_level=6, game_time_s=600) is None
    assert compute_zoi("blue", my_level=6, game_time_s=600) is None


# --- RM-1848: over-64-bit ints -----------------------------------------

@pytest.mark.parametrize("field", ["px", "x_frac", "y_frac", "confidence"])
def test_huge_int_dot_field_drops_that_dot(field):
    bad = _dot("blue", 0.2, 0.8)
    bad[field] = 10 ** 400
    good = _dot("red", 0.8, 0.2)
    z = compute_zoi([bad, good], my_level=6, game_time_s=600)
    _assert_sane(z)
    assert [b["team"] for b in z["bubbles"]] == ["red"]
    assert z["map_control"]["ally_control_pct"] == 0


def test_huge_int_level_reads_as_unknown_level():
    z = compute_zoi([_dot("blue", 0.2, 0.8)], my_level=10 ** 400,
                    game_time_s=600)
    _assert_sane(z)
    assert z["map_control"]["line"].endswith("play to your wave")


def test_huge_int_game_time_reads_as_unknown_time():
    z = compute_zoi([_dot("blue", 0.2, 0.8), _dot("red", 0.8, 0.2)],
                    my_level=6, game_time_s=10 ** 400)
    ref = compute_zoi([_dot("blue", 0.2, 0.8), _dot("red", 0.8, 0.2)],
                      my_level=6, game_time_s=None)
    _assert_sane(z)
    assert z == ref


# --- RM-1849: weight overflow ------------------------------------------

def test_product_overflow_never_raises():
    dots = [_dot("blue", 0.2, 0.8, px=1e200, conf=1e200),
            _dot("red", 0.8, 0.2, px=30, conf=0.5)]
    _assert_sane(compute_zoi(dots, my_level=6, game_time_s=600))


def test_weight_sum_overflow_never_raises():
    dots = [_dot("blue", 0.2, 0.8, px=1e308, conf=1.0),
            _dot("blue", 0.3, 0.7, px=1e308, conf=1.0),
            _dot("red", 0.8, 0.2, px=30, conf=0.5)]
    z = compute_zoi(dots, my_level=6, game_time_s=600)
    _assert_sane(z)
    # the enormous blue blobs still dominate the control split
    assert z["map_control"]["ally_control_pct"] == 100


# --- RM-1850: sign + range of px / confidence --------------------------

def test_negative_px_and_negative_confidence_is_no_presence():
    dots = [_dot("blue", 0.2, 0.8, px=-50, conf=-0.9),
            _dot("red", 0.8, 0.2, px=30, conf=0.5)]
    z = compute_zoi(dots, my_level=6, game_time_s=600)
    _assert_sane(z)
    blue = [b for b in z["bubbles"] if b["team"] == "blue"][0]
    assert blue["weight"] == 0.0
    assert blue["r_frac"] == round(_R_MIN_FRAC, 5)
    assert z["map_control"]["ally_control_pct"] == 0


def test_confidence_above_one_is_clamped_to_one():
    over = compute_zoi([_dot("blue", 0.2, 0.8, conf=50.0),
                        _dot("red", 0.8, 0.2)], my_level=6, game_time_s=600)
    at_one = compute_zoi([_dot("blue", 0.2, 0.8, conf=1.0),
                          _dot("red", 0.8, 0.2)], my_level=6, game_time_s=600)
    assert over == at_one


# --- RM-1851: base_fallback --------------------------------------------

@pytest.mark.parametrize("fb", [None, 5, ("a", "b"), (0.1, 0.2, 0.3),
                                (float("nan"), 0.5), (10 ** 400, 0.5), "ab"])
def test_malformed_base_fallback_uses_center(fb):
    # one zero-weight dot forces both the team and the global fallback path
    dots = [_dot("blue", 0.2, 0.8, px=0, conf=0.5)]
    z = compute_zoi(dots, my_level=6, game_time_s=600, base_fallback=fb)
    ref = compute_zoi(dots, my_level=6, game_time_s=600)
    _assert_sane(z)
    assert z == ref


def test_valid_base_fallback_still_honored():
    dots = [_dot("blue", 0.5, 0.5, px=0, conf=0.5)]
    z = compute_zoi(dots, my_level=6, game_time_s=600,
                    base_fallback=(0.1, 0.9))
    assert z["map_control"]["action_quadrant"] == "ally_base"
    z = compute_zoi(dots, my_level=6, game_time_s=600,
                    base_fallback=[5.0, -5.0])
    assert z["map_control"]["action_quadrant"] == "enemy_base"


# --- RM-1852: capability helper returns ---------------------------------

@pytest.mark.parametrize("ret", [None, "x", float("nan"), float("inf"),
                                 -3.0, 0.0, 10 ** 400])
def test_garbage_dot_capability_is_neutral(monkeypatch, ret):
    monkeypatch.setattr(zcap, "capability_weight", lambda *a, **k: ret)
    dots = [_dot("blue", 0.2, 0.8, champion="Ahri"),
            _dot("red", 0.8, 0.2, champion="Zed")]
    z = compute_zoi(dots, my_level=6, game_time_s=600, ally_roster=["Ahri"],
                    enemy_roster=["Zed"], dot_champions=True)
    monkeypatch.setattr(zcap, "capability_weight", lambda *a, **k: 1.0)
    ref = compute_zoi(dots, my_level=6, game_time_s=600, ally_roster=["Ahri"],
                      enemy_roster=["Zed"], dot_champions=True)
    _assert_sane(z)
    assert z["bubbles"] == ref["bubbles"]


@pytest.mark.parametrize("ret", [None, float("nan"), -1.0, 99.0])
def test_garbage_team_capability_is_bounded(monkeypatch, ret):
    monkeypatch.setattr(zcap, "team_mean_weight", lambda *a, **k: ret)
    dots = [_dot("blue", 0.2, 0.8), _dot("red", 0.8, 0.2)]
    z = compute_zoi(dots, my_level=6, game_time_s=600, ally_roster=["Ahri"],
                    enemy_roster=["Zed"])
    _assert_sane(z)
    base = compute_zoi(dots, my_level=6, game_time_s=600)
    for b, b0 in zip(z["bubbles"], base["bubbles"]):
        assert b0["r_frac"] * zcap.CAP_MIN - 1e-5 <= b["r_frac"]
        assert b["r_frac"] <= b0["r_frac"] * zcap.CAP_MAX + 1e-5


# --- RM-1853: zoi_callout line -----------------------------------------

@pytest.mark.parametrize("line", [None, 5, "", "   ", b"bytes", ["x"]])
def test_callout_unusable_line_is_none(line):
    assert zoi_callout({"map_control": {"line": line}}) is None


def test_callout_multiline_line_is_one_line():
    co = zoi_callout({"map_control": {"line": "Map control 40%.\nAction\tmid"}})
    assert co["line"] == "Map control 40%. Action mid"


def test_callout_well_formed_unchanged():
    z = compute_zoi([_dot("blue", 0.2, 0.8), _dot("red", 0.8, 0.2)],
                    my_level=6, game_time_s=600)
    co = zoi_callout(z)
    assert co == {"tag": "map_control", "line": z["map_control"]["line"],
                  "eta_s": None, "kind": "map_control"}


# --- byte-identity on well-formed input (captured pre-hardening) ----------

_GOLD_DOTS = [_dot("blue", .21, .77, 42, .81), _dot("blue", .35, .62, 18, .4),
              _dot("red", .71, .3, 55, .93), _dot("red", .9, .12, 7, .2)]

_GOLD_DEFAULT = (
    '{"bubbles": [{"cx": 0.21, "cy": 0.77, "r_frac": 0.07223, "team": "blue", '
    '"weight": 34.02}, {"cx": 0.35, "cy": 0.62, "r_frac": 0.05319, "team": '
    '"blue", "weight": 7.2}, {"cx": 0.71, "cy": 0.3, "r_frac": 0.07995, '
    '"team": "red", "weight": 51.15}, {"cx": 0.9, "cy": 0.12, "r_frac": '
    '0.04895, "team": "red", "weight": 1.4}], "demarcation": {"ally_side": '
    '"left", "x1": 0.0, "x2": 0.8689, "y1": 0.0691, "y2": 1.0}, '
    '"map_control": {"action_quadrant": "top_river", "ally_control_pct": 44, '
    '"line": "Map control 44%. Action top river. ult rank 2 - force a fight"}}'
)

_GOLD_ROSTER_BUBBLES = [
    {"cx": 0.21, "cy": 0.77, "r_frac": 0.08107, "team": "blue", "weight": 34.02},
    {"cx": 0.35, "cy": 0.62, "r_frac": 0.05916, "team": "blue", "weight": 7.2},
    {"cx": 0.71, "cy": 0.3, "r_frac": 0.10223, "team": "red", "weight": 51.15},
    {"cx": 0.9, "cy": 0.12, "r_frac": 0.05748, "team": "red", "weight": 1.4},
]


def test_well_formed_default_output_byte_identical():
    z = compute_zoi(_GOLD_DOTS, my_level=11, game_time_s=845)
    assert json.dumps(z, sort_keys=True) == _GOLD_DEFAULT


def test_well_formed_roster_output_unchanged():
    z = compute_zoi(_GOLD_DOTS, my_level=7, game_time_s=1500,
                    ally_roster=["Ahri"], enemy_roster=["Zed"])
    assert z["bubbles"] == _GOLD_ROSTER_BUBBLES
    assert z["map_control"]["ally_control_pct"] == 44
    assert "dmz" in z
