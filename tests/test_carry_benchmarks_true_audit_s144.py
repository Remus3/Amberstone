"""True-audit s144 cycle 229: core/carry_benchmarks.py hardening.

The reader behind the Post Game Review carry_normalized block
(dashboard/builders_last_match._carry_normalized -> resolve / band). Each
test below pins one measured weakness of the pre-audit module:

  F1  bucket_for raised on NaN / inf / junk durations (ValueError /
      OverflowError out of resolve) and bucketed bool / negative values;
      an unusable duration now has no bucket and resolve falls to "|all".
  F2  the cache reloaded only when the mtime INCREASED, so an older-mtime
      restore or a same-mtime rewrite of a different size was never read.
  F3  a corrupt file was re-parsed on every call; it is now parsed once
      per (mtime_ns, size) and reads as no data (core/benchmarks precedent:
      a corrupt file is a real state, not a transient one).
  F4  a transient stat / read OSError served empty instead of last good.
  F5  a wrongly shaped document / group / metric raised AttributeError /
      TypeError out of resolve; one junk group now costs only itself.
  F6  a junk min_n (str, None, bool, negative) raised or let a 0-sample
      cell qualify; it now falls back to DEFAULT_MIN_N.
  F7  band() called NaN "avg", bool a number, inverted / NaN percentiles
      "avg", and raised on a str value or a non-dict bench.
  F8  resolve handed out the cache's own dicts (a caller mutation poisoned
      every later read) and passed non-finite percentiles through, which
      json.dumps writes as a bare NaN token.
  F9  a UTF-8 BOM made the file read as corrupt.

ASCII-only authored content (CLAUDE.md hard rule).
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
from unittest import mock

import pytest

import core.carry_benchmarks as cb


def _grp(kp_n=200, p25=40.0, p75=60.0) -> dict:
    return {
        "n": kp_n,
        "metrics": {
            "kp_pct": {"p25": p25, "p50": 50.0, "p75": p75, "n": kp_n},
            "gold_share_pct": {"p25": 18.0, "p50": 20.0, "p75": 24.0,
                               "n": kp_n},
            "dmg_share_pct": {"p25": 20.0, "p50": 26.0, "p75": 32.0,
                              "n": kp_n},
        },
    }


def _doc(groups: dict, min_n=50) -> dict:
    return {"min_n": min_n, "groups": groups}


@pytest.fixture
def bench_file(tmp_path, monkeypatch):
    path = tmp_path / "carry_benchmarks.json"
    monkeypatch.setattr(cb, "CARRY_BENCHMARKS_PATH", path)
    monkeypatch.setattr(cb, "_cache", cb._Cache())
    return path


def _write(path: Path, doc, mtime_ns: int | None = None) -> None:
    raw = doc if isinstance(doc, bytes) else json.dumps(doc).encode("utf-8")
    path.write_bytes(raw)
    if mtime_ns is not None:
        os.utime(path, ns=(mtime_ns, mtime_ns))


# ---------------------------------------------------------------- F1


@pytest.mark.parametrize("dur", [float("nan"), float("inf"), float("-inf"),
                                 "abc", "1500", True, False, -1, -5000,
                                 None, [1500], b"1500"])
def test_f1_unusable_duration_has_no_bucket(dur):
    assert cb.bucket_for(dur) is None


@pytest.mark.parametrize("dur,want", [(0, "short"), (1199, "short"),
                                      (1199.9, "short"), (1200, "mid"),
                                      (1200.0, "mid"), (1799, "mid"),
                                      (1800, "long"), (10 ** 7, "long")])
def test_f1_valid_duration_buckets_unchanged(dur, want):
    assert cb.bucket_for(dur) == want


@pytest.mark.parametrize("dur", [float("nan"), float("inf"), "abc", -1])
def test_f1_resolve_with_unusable_duration_falls_to_all(bench_file, dur):
    _write(bench_file, _doc({"BOTTOM|short": _grp(), "BOTTOM|all": _grp(300)}))
    key, metrics = cb.resolve("BOTTOM", "CLASSIC", dur)
    assert key == "BOTTOM|all"
    assert metrics["kp_pct"]["n"] == 300


def test_f1_no_bucket_never_builds_a_none_key(bench_file):
    _write(bench_file, _doc({"BOTTOM|None": _grp(900),
                             "BOTTOM|all": _grp(300)}))
    assert cb.resolve("BOTTOM", None, float("nan"))[0] == "BOTTOM|all"


# ---------------------------------------------------------------- F2


def test_f2_older_mtime_restore_is_reloaded(bench_file):
    _write(bench_file, _doc({"BOTTOM|all": _grp(300)}), mtime_ns=2_000_000_000_000_000_000)
    assert cb.resolve("BOTTOM", None, 1500)[1]["kp_pct"]["n"] == 300
    _write(bench_file, _doc({"BOTTOM|all": _grp(400)}), mtime_ns=1_000_000_000_000_000_000)
    assert cb.resolve("BOTTOM", None, 1500)[1]["kp_pct"]["n"] == 400


def test_f2_same_mtime_different_size_is_reloaded(bench_file):
    t = 1_500_000_000_000_000_000
    _write(bench_file, _doc({"BOTTOM|all": _grp(300)}), mtime_ns=t)
    assert cb.resolve("BOTTOM", None, 1500)[0] == "BOTTOM|all"
    _write(bench_file, _doc({"BOTTOM|all": _grp(300),
                             "BOTTOM|mid": _grp(9000)}), mtime_ns=t)
    key, metrics = cb.resolve("BOTTOM", None, 1500)
    assert key == "BOTTOM|mid"
    assert metrics["kp_pct"]["n"] == 9000


def test_f2_unchanged_file_is_not_reread(bench_file):
    _write(bench_file, _doc({"BOTTOM|all": _grp(300)}))
    cb.resolve("BOTTOM", None, 1500)
    with mock.patch.object(Path, "read_bytes",
                           side_effect=AssertionError("re-read")), \
            mock.patch.object(Path, "read_text",
                              side_effect=AssertionError("re-read")):
        assert cb.resolve("BOTTOM", None, 1500)[0] == "BOTTOM|all"


# ---------------------------------------------------------------- F3


def test_f3_corrupt_file_is_parsed_once(bench_file):
    _write(bench_file, b"{not json")
    calls = {"n": 0}
    real = json.loads

    def counting(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    with mock.patch.object(cb.json, "loads", side_effect=counting):
        for _ in range(5):
            assert cb.resolve("BOTTOM", "CLASSIC", 1500) == (None, {})
    assert calls["n"] == 1


def test_f3_good_file_after_corrupt_is_read(bench_file):
    _write(bench_file, b"{not json", mtime_ns=1_000_000_000_000_000_000)
    assert cb.resolve("BOTTOM", None, 1500) == (None, {})
    _write(bench_file, _doc({"BOTTOM|all": _grp(300)}),
           mtime_ns=1_000_000_000_000_000_000)
    assert cb.resolve("BOTTOM", None, 1500)[0] == "BOTTOM|all"


# ---------------------------------------------------------------- F4


def test_f4_transient_stat_error_keeps_last_good(bench_file):
    _write(bench_file, _doc({"BOTTOM|all": _grp(300)}))
    assert cb.resolve("BOTTOM", None, 1500)[0] == "BOTTOM|all"
    with mock.patch.object(Path, "stat", side_effect=PermissionError(13, "x")):
        assert cb.resolve("BOTTOM", None, 1500)[0] == "BOTTOM|all"


def test_f4_transient_read_error_keeps_last_good_and_retries(bench_file):
    _write(bench_file, _doc({"BOTTOM|all": _grp(300)}),
           mtime_ns=1_000_000_000_000_000_000)
    assert cb.resolve("BOTTOM", None, 1500)[0] == "BOTTOM|all"
    _write(bench_file, _doc({"BOTTOM|mid": _grp(500)}),
           mtime_ns=1_100_000_000_000_000_000)
    with mock.patch.object(Path, "read_bytes",
                           side_effect=PermissionError(13, "x")), \
            mock.patch.object(Path, "read_text",
                              side_effect=PermissionError(13, "x")):
        assert cb.resolve("BOTTOM", None, 1500)[0] == "BOTTOM|all"
    # The failed read was not memoised: the next call reads the new file.
    assert cb.resolve("BOTTOM", None, 1500)[0] == "BOTTOM|mid"


def test_f4_repointed_path_never_serves_the_previous_file(bench_file,
                                                         tmp_path,
                                                         monkeypatch):
    # Verifier round 1 find: a stat / read error on a NEW path served the
    # OLD path's cached document.
    _write(bench_file, _doc({"BOTTOM|all": _grp(300)}))
    assert cb.resolve("BOTTOM", None, 1500)[0] == "BOTTOM|all"
    other = tmp_path / "other.json"
    monkeypatch.setattr(cb, "CARRY_BENCHMARKS_PATH", other)
    with mock.patch.object(Path, "stat", side_effect=PermissionError(13, "x")):
        assert cb.resolve("BOTTOM", None, 1500) == (None, {})
    _write(other, _doc({"BOTTOM|all": _grp(300)}))
    with mock.patch.object(Path, "read_bytes",
                           side_effect=PermissionError(13, "x")):
        assert cb.resolve("BOTTOM", None, 1500) == (None, {})


def test_f4_nul_in_path_reads_empty(bench_file, tmp_path, monkeypatch):
    monkeypatch.setattr(cb, "CARRY_BENCHMARKS_PATH",
                        Path(str(tmp_path / "bad") + "\x00.json"))
    assert cb.resolve("BOTTOM", "CLASSIC", 1500) == (None, {})


def test_f4_missing_file_reads_empty(bench_file):
    assert cb.resolve("BOTTOM", "CLASSIC", 1500) == (None, {})


# ---------------------------------------------------------------- F5


@pytest.mark.parametrize("doc", [[1, 2], "str", 5, None,
                                 {"groups": [1]}, {"groups": "x"},
                                 {"min_n": 50}])
def test_f5_wrongly_shaped_document_reads_empty(bench_file, doc):
    _write(bench_file, doc)
    assert cb.resolve("BOTTOM", "CLASSIC", 1500) == (None, {})


@pytest.mark.parametrize("junk", [
    [1, 2],                                   # group not a dict
    "x",
    {"metrics": [1]},                         # metrics not a dict
    {"metrics": {"kp_pct": [1]}},             # kp_pct not a dict
    {"metrics": {"kp_pct": {"n": "999"}}},    # n a str
    {"metrics": {"kp_pct": {"n": None}}},
    {"metrics": {"kp_pct": {"n": True}}},     # bool is not a count
    {"metrics": {"kp_pct": {"n": float("nan")}}},
    {"metrics": {"kp_pct": {"n": 120.5}}},    # not integral
    {"metrics": {"kp_pct": {"n": -400}}},
])
def test_f5_one_junk_group_costs_only_itself(bench_file, junk):
    _write(bench_file, _doc({"BOTTOM|mid": junk, "BOTTOM|all": _grp(300)},
                            min_n=1))
    key, metrics = cb.resolve("BOTTOM", "CLASSIC", 1500)
    assert key == "BOTTOM|all"
    assert metrics["kp_pct"]["n"] == 300


def test_f5_integral_float_count_qualifies(bench_file):
    g = _grp(300)
    g["metrics"]["kp_pct"]["n"] = 300.0
    _write(bench_file, _doc({"BOTTOM|mid": g}))
    assert cb.resolve("BOTTOM", None, 1500)[0] == "BOTTOM|mid"


@pytest.mark.parametrize("role", [5, ["BOTTOM"], "", "BOTTOM|mid"])
def test_f5_unusable_role_is_skipped(bench_file, role):
    _write(bench_file, _doc({"BOTTOM|mid": _grp(), "CLASSIC|all": _grp(900),
                             "BOTTOM|mid|mid": _grp()}))
    key, _ = cb.resolve(role, "CLASSIC", 1500)
    assert key == "CLASSIC|all"


# ---------------------------------------------------------------- F6


@pytest.mark.parametrize("min_n", ["50", None, True, -3, float("nan"),
                                   float("inf"), 2.5, [50]])
def test_f6_junk_min_n_uses_default(bench_file, min_n):
    _write(bench_file, _doc({"BOTTOM|mid": _grp(10), "BOTTOM|all": _grp(60)},
                            min_n=min_n))
    key, _ = cb.resolve("BOTTOM", None, 1500)
    assert key == "BOTTOM|all"  # 10 < DEFAULT_MIN_N (50) <= 60


def test_f6_zero_sample_cell_never_qualifies(bench_file):
    _write(bench_file, _doc({"BOTTOM|mid": _grp(0), "BOTTOM|all": _grp(1)},
                            min_n=0))
    assert cb.resolve("BOTTOM", None, 1500)[0] == "BOTTOM|all"


def test_f6_missing_kp_n_never_qualifies_at_min_n_zero(bench_file):
    g = _grp(5)
    del g["metrics"]["kp_pct"]["n"]
    _write(bench_file, _doc({"BOTTOM|mid": g, "BOTTOM|all": _grp(1)},
                            min_n=0))
    assert cb.resolve("BOTTOM", None, 1500)[0] == "BOTTOM|all"


# ---------------------------------------------------------------- F7

BENCH = {"p25": 40.0, "p50": 50.0, "p75": 60.0, "n": 100}


@pytest.mark.parametrize("value", [float("nan"), float("inf"),
                                   float("-inf"), True, False, "55",
                                   [55], {"v": 55}])
def test_f7_band_unusable_value_is_none(value):
    assert cb.band(value, BENCH) is None


@pytest.mark.parametrize("bench", [
    [1, 2], "x", 5,
    {"p25": float("nan"), "p75": 60.0},
    {"p25": 40.0, "p75": float("inf")},
    {"p25": "40", "p75": 60.0},
    {"p25": True, "p75": 60.0},
    {"p25": 60.0, "p75": 40.0},             # inverted
])
def test_f7_band_unusable_bench_is_none(bench):
    assert cb.band(50.0, bench) is None


@pytest.mark.parametrize("value,want", [(39.9, "low"), (40, "avg"),
                                        (50, "avg"), (60.0, "avg"),
                                        (60.1, "high"), (-5, "low")])
def test_f7_band_valid_values_unchanged(value, want):
    assert cb.band(value, BENCH) == want


def test_f7_band_degenerate_equal_percentiles_is_avg():
    assert cb.band(50.0, {"p25": 50.0, "p75": 50.0}) == "avg"


# ---------------------------------------------------------------- F8


def test_f8_caller_mutation_cannot_poison_cache(bench_file):
    _write(bench_file, _doc({"BOTTOM|all": _grp(300)}))
    _, metrics = cb.resolve("BOTTOM", None, 1500)
    metrics["kp_pct"]["p25"] = -999
    metrics.clear()
    _, again = cb.resolve("BOTTOM", None, 1500)
    assert again["kp_pct"]["p25"] == 40.0


def test_f8_non_finite_stats_are_served_as_none(bench_file):
    g = _grp(300)
    g["metrics"]["kp_pct"]["p25"] = float("nan")
    g["metrics"]["gold_share_pct"]["p75"] = float("inf")
    _write(bench_file, _doc({"BOTTOM|all": g}))
    _, metrics = cb.resolve("BOTTOM", None, 1500)
    assert metrics["kp_pct"]["p25"] is None
    assert metrics["gold_share_pct"]["p75"] is None
    assert metrics["kp_pct"]["p50"] == 50.0
    # Strict JSON: no bare NaN / Infinity token can reach a payload.
    json.dumps(metrics, allow_nan=False)


def test_f8_nested_non_finite_stats_are_served_as_none(bench_file):
    # Verifier round 1 find: a NaN inside a list / dict stat passed through.
    g = _grp(300)
    g["metrics"]["kp_pct"]["p25"] = [float("nan"), 1.5]
    g["metrics"]["kp_pct"]["extra"] = {"a": float("inf"), "b": [float("-inf")]}
    _write(bench_file, _doc({"BOTTOM|all": g}))
    _, metrics = cb.resolve("BOTTOM", None, 1500)
    assert metrics["kp_pct"]["p25"] == [None, 1.5]
    assert metrics["kp_pct"]["extra"] == {"a": None, "b": [None]}
    json.dumps(metrics, allow_nan=False)
    # And the nested copies are private too.
    metrics["kp_pct"]["extra"]["b"].append(7)
    metrics["kp_pct"]["p25"].append(7)
    _, again = cb.resolve("BOTTOM", None, 1500)
    assert again["kp_pct"]["extra"] == {"a": None, "b": [None]}
    assert again["kp_pct"]["p25"] == [None, 1.5]


def test_f8_pathologically_deep_stat_costs_only_its_metric(bench_file):
    deep = "[" * 3000 + "]" * 3000
    raw = ('{"min_n": 1, "groups": {"BOTTOM|all": {"metrics": {'
           '"kp_pct": {"p25": 40.0, "p75": 60.0, "n": 300}, '
           '"gold_share_pct": {"p25": ' + deep + '}}}}}').encode()
    _write(bench_file, raw)
    key, metrics = cb.resolve("BOTTOM", None, 1500)
    assert key == "BOTTOM|all"
    assert metrics["kp_pct"]["n"] == 300


def test_f8_non_dict_metric_entry_is_dropped(bench_file):
    g = _grp(300)
    g["metrics"]["gold_share_pct"] = [1, 2]
    _write(bench_file, _doc({"BOTTOM|all": g}))
    _, metrics = cb.resolve("BOTTOM", None, 1500)
    assert "gold_share_pct" not in metrics
    assert metrics["kp_pct"]["n"] == 300


def test_f8_missing_file_result_is_private(bench_file):
    key, metrics = cb.resolve("BOTTOM", "CLASSIC", 1500)
    metrics["poison"] = 1
    assert cb.resolve("BOTTOM", "CLASSIC", 1500) == (None, {})


# ---------------------------------------------------------------- F9


def test_f9_utf8_bom_file_is_read(bench_file):
    raw = b"\xef\xbb\xbf" + json.dumps(_doc({"BOTTOM|all": _grp(300)})).encode()
    _write(bench_file, raw)
    assert cb.resolve("BOTTOM", None, 1500)[0] == "BOTTOM|all"


@pytest.mark.parametrize("raw", [b"\xff\xfe\x00", b"[" * 100000])
def test_f9_undecodable_or_deep_file_reads_empty(bench_file, raw):
    _write(bench_file, raw)
    assert cb.resolve("BOTTOM", None, 1500) == (None, {})


# ------------------------------------------------- characterization


def test_real_committed_json_resolves_finite_strict_json():
    real = Path(cb.__file__).resolve().parent.parent / "data" / \
        "coach_reference" / "carry_benchmarks.json"
    if not real.exists():
        pytest.skip("committed carry_benchmarks.json absent")
    with mock.patch.object(cb, "CARRY_BENCHMARKS_PATH", real), \
            mock.patch.object(cb, "_cache", cb._Cache()):
        for role in ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY", None):
            for mode in ("CLASSIC", "ARAM"):
                for dur in (600, 1500, 2400):
                    key, metrics = cb.resolve(role, mode, dur)
                    assert key is not None
                    json.dumps(metrics, allow_nan=False)
                    for stats in metrics.values():
                        for v in stats.values():
                            assert v is None or math.isfinite(v)
