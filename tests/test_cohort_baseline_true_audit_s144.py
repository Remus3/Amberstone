"""S144-T-737 - true-audit hardening of core/cohort_baseline.py.

Every test here pins a junk-input contract the module did not keep before:
a non-finite, negative, boolean or overflowing value never reaches a rate or
a percentile, a non-dict row never raises, a malformed baseline table is "no
table" (None) rather than a KeyError / TypeError deep inside rank_of, and a
baseline FILE of the wrong shape raises ValueError (the one exception
tools/pgr_event_report.py catches) instead of AttributeError.
"""
from __future__ import annotations

import json
import math

import pytest

from core import cohort_baseline as cb

# ------------------------------------------------------------------ _num


@pytest.mark.parametrize("junk", [
    "nan", "NaN", "inf", "-inf", "1e999", float("nan"), float("inf"),
    10 ** 400, True, False, "-5", -5, -0.5, None, "", "abc", [1], {"a": 1},
])
def test_num_maps_every_unusable_value_to_zero(junk):
    out = cb._num(junk)
    assert out == 0.0
    assert math.isfinite(out)


@pytest.mark.parametrize("good, want", [
    ("12", 12.0), (" 7.5 ", 7.5), (3, 3.0), (0, 0.0), ("0", 0.0),
])
def test_num_still_parses_real_values(good, want):
    assert cb._num(good) == want


# ------------------------------------------------- row / participant metrics


def _sidecar(**over):
    base = {"TIME_PLAYED": "1200", "MINIONS_KILLED": "100",
            "NEUTRAL_MINIONS_KILLED": "20", "GOLD_EARNED": "10000",
            "CHAMPIONS_KILLED": "5", "NUM_DEATHS": "3", "ASSISTS": "7"}
    base.update(over)
    return base


def _mv5(**over):
    base = {"timePlayed": 1200, "totalMinionsKilled": 100,
            "neutralMinionsKilled": 20, "goldEarned": 10000,
            "kills": 5, "deaths": 3, "assists": 7}
    base.update(over)
    return base


@pytest.mark.parametrize("tp", ["nan", "inf", "1e999", True, 10 ** 400])
def test_a_junk_time_played_drops_the_row_not_a_nan_or_zero_rate(tp):
    assert cb.row_metrics(_sidecar(TIME_PLAYED=tp)) == {}
    assert cb.participant_metrics(_mv5(timePlayed=tp)) == {}


@pytest.mark.parametrize("bad", ["nan", "inf", "-300", True, 10 ** 400])
def test_a_junk_stat_field_is_zero_and_every_metric_stays_finite(bad):
    side = cb.row_metrics(_sidecar(GOLD_EARNED=bad))
    mv5 = cb.participant_metrics(_mv5(goldEarned=bad))
    for out in (side, mv5):
        assert out["gold_per_min"] == 0.0
        assert all(math.isfinite(v) and v >= 0 for v in out.values())


@pytest.mark.parametrize("junk", [None, [], "row", 5, ("TIME_PLAYED", "1200")])
def test_a_non_dict_row_is_unusable_not_a_crash(junk):
    assert cb.row_metrics(junk) == {}
    assert cb.participant_metrics(junk) == {}


# ------------------------------------------------------------------ build


def _metrics(v):
    return {"cs_per_min": v}


def test_build_drops_non_finite_and_non_numeric_values_before_percentiles():
    rows = [("MID", _metrics(float(i))) for i in range(25)]
    rows += [("MID", _metrics(float("nan"))), ("MID", _metrics(float("inf"))),
             ("MID", _metrics("7")), ("MID", _metrics(True)),
             ("MID", _metrics(None))]
    out = cb.build(rows)
    table = out["MID"]["cs_per_min"]
    assert table["n"] == 25
    assert all(math.isfinite(v) for v in table.values())
    # The clean build is unchanged by the junk.
    assert table == cb.build(rows[:25])["MID"]["cs_per_min"]
    json.dumps(out, allow_nan=False)


def test_build_skips_a_non_string_role_instead_of_failing_the_sort():
    rows = [("MID", _metrics(float(i))) for i in range(20)]
    rows += [(1, _metrics(1.0)), (["TOP"], _metrics(1.0)), (None, _metrics(1.0))]
    out = cb.build(rows)
    assert list(out) == ["MID"]


@pytest.mark.parametrize("junk", [None, "MID", ("MID",), ("MID", "x", "y"),
                                  ("MID", ["cs_per_min", 1.0]), 5])
def test_build_skips_a_malformed_row_instead_of_raising(junk):
    rows = [("MID", _metrics(float(i))) for i in range(20)] + [junk]
    assert cb.build(rows)["MID"]["cs_per_min"]["n"] == 20


# ---------------------------------------------------------------- rank_of


def _baselines():
    return {"MID": {"cs_per_min": {"n": 100, "mean": 7.0, "p10": 5.0,
                                   "p25": 6.0, "p50": 7.0, "p75": 8.0,
                                   "p90": 9.0}}}


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"),
                                   True, "7", None])
def test_rank_of_refuses_a_value_it_cannot_place(value):
    assert cb.rank_of(_baselines(), "MID", "cs_per_min", value) is None


def test_rank_of_still_places_an_int():
    band = cb.rank_of(_baselines(), "MID", "cs_per_min", 8)
    assert band["at_or_above_p"] == 75


@pytest.mark.parametrize("mutate", [
    lambda t: t.pop("p50"),
    lambda t: t.pop("n"),
    lambda t: t.update(p75="8"),
    lambda t: t.update(p90=float("nan")),
    lambda t: t.update(n=0),
    lambda t: t.update(n=True),
    lambda t: t.update(n="100"),
    lambda t: t.update(p10=None),
])
def test_a_malformed_table_is_no_table_not_a_crash(mutate):
    b = _baselines()
    mutate(b["MID"]["cs_per_min"])
    assert cb.rank_of(b, "MID", "cs_per_min", 7.5) is None


@pytest.mark.parametrize("baselines", [None, [], "x",
                                       {"MID": []}, {"MID": "x"},
                                       {"MID": {"cs_per_min": []}},
                                       {"MID": {"cs_per_min": "x"}}])
def test_a_junk_baselines_shape_is_no_table_not_a_crash(baselines):
    assert cb.rank_of(baselines, "MID", "cs_per_min", 7.5) is None


@pytest.mark.parametrize("role", [None, ["MID"], {"MID": 1}, 5])
def test_a_non_string_role_is_no_table_not_a_crash(role):
    assert cb.rank_of(_baselines(), role, "cs_per_min", 7.5) is None


# ------------------------------------------------------------------- load


def _write(tmp_path, payload, *, bom=False):
    p = tmp_path / "b.json"
    text = payload if isinstance(payload, str) else json.dumps(payload)
    p.write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))
    return p


@pytest.mark.parametrize("payload", [
    [], "[]", "5", '"roles"', "null",
    {"roles": []}, {"roles": "x"},
    {"tiers": ["GOLD"]}, {"tiers": "GOLD"},
    {"tiers": {"GOLD": "x"}}, {"tiers": {"GOLD": {"roles": []}}},
])
def test_load_raises_value_error_on_a_wrong_shape_file(tmp_path, payload):
    p = _write(tmp_path, payload)
    with pytest.raises(ValueError):
        cb.load(p, cohort="GOLD")


def test_load_reads_a_file_with_a_utf8_bom(tmp_path):
    p = _write(tmp_path, {"roles": _baselines()}, bom=True)
    assert cb.load(p) == _baselines()


def test_load_keeps_a_null_cohort_entry_as_an_empty_table(tmp_path):
    # Pre-existing contract (`tiers[cohort] or {}`): a cohort the builder
    # recorded with no data reads as "no tables", every band unavailable.
    p = _write(tmp_path, {"tiers": {"GOLD": None}})
    assert cb.load(p, cohort="GOLD") == {}


def test_load_a_single_cohort_file_with_no_roles_is_empty(tmp_path):
    p = _write(tmp_path, {"source": "x"})
    assert cb.load(p) == {}
