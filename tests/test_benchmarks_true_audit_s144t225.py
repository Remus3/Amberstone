"""True-audit s144t225: core/benchmarks.py, the champion_benchmarks.json reader.

The reader feeds the LBAND1 live band (every SR /api/state tick), the
aftergame summary (``games_for(...) >= 5`` and the text_freq sort/sum, both
unguarded) and GET /api/champ-benchmarks (``rows_for_mode``). Each test below
was red against the pre-audit module:

- the cache reloaded only when the mtime INCREASED (a restore with an older
  mtime was never seen) although the docstring says "if the file mtime changes";
- a corrupt file was re-read and re-parsed on EVERY call (no failure memo);
- a stat error other than FileNotFoundError raised into every caller;
- a transient read error blanked good data until the next call;
- a non-dict document / champions / entry / metrics / text_freq raised
  AttributeError in the accessors;
- rank_value banded a NaN value "above-p75", raised TypeError on a str / None
  value or a str percentile, and banded against NaN or inverted percentiles;
- games_for returned the raw "games" value (str, None, bool, NaN, 3.7, -3);
- rows_for_mode lost the whole table to one str games value (sort TypeError),
  raised on a non-dict entry, and matched "X|" keys for an empty mode;
- get / text_freq / rows_for_mode returned the cache's own dicts, so a caller
  mutation poisoned every later read;
- text_freq passed non-count frequencies to callers that sort and sum them.

Hermetic: every test points BENCHMARKS_PATH at tmp_path (or a fake path) and
installs a fresh _Cache, so the gitignored live file is never read.
"""
from __future__ import annotations

import json
import math
import os

import pytest

from core import benchmarks


def _doc(champions):
    return {"generated_at": "x", "champions": champions}


def _entry(games=10, metrics=None, text_freq=None):
    out = {
        "games": games,
        "metrics": metrics if metrics is not None else {
            "cs_at_10": {"p25": 80.0, "p50": 90.0, "p75": 100.0, "avg": 90.0,
                         "n": 10, "weighted_n": 10.0},
        },
    }
    if text_freq is not None:
        out["text_freq"] = text_freq
    return out


@pytest.fixture
def bench_file(tmp_path, monkeypatch):
    path = tmp_path / "champion_benchmarks.json"
    monkeypatch.setattr(benchmarks, "BENCHMARKS_PATH", path)
    monkeypatch.setattr(benchmarks, "_cache", benchmarks._Cache())

    def write(obj, mtime=None, raw=None):
        data = raw if raw is not None else json.dumps(obj).encode("ascii")
        path.write_bytes(data)
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path

    return write


# --- cache: reload / failure memo / errors ---------------------------------

def test_reload_when_mtime_moves_backwards(bench_file):
    bench_file(_doc({"Vayne|sr": _entry(games=10)}), mtime=2_000_000_000)
    assert benchmarks.games_for("Vayne", "sr") == 10
    bench_file(_doc({"Vayne|sr": _entry(games=42)}), mtime=1_000_000_000)
    assert benchmarks.games_for("Vayne", "sr") == 42


def test_reload_when_size_changes_same_mtime(bench_file):
    bench_file(_doc({"Vayne|sr": _entry(games=10)}), mtime=1_500_000_000)
    assert benchmarks.games_for("Vayne", "sr") == 10
    bench_file(_doc({"Vayne|sr": _entry(games=1234)}), mtime=1_500_000_000)
    assert benchmarks.games_for("Vayne", "sr") == 1234


def test_corrupt_file_parsed_once_not_every_call(bench_file, monkeypatch):
    bench_file(None, raw=b"{not json")
    calls = {"n": 0}
    real = benchmarks.json.loads

    def counting(*a, **kw):
        calls["n"] += 1
        return real(*a, **kw)

    monkeypatch.setattr(benchmarks.json, "loads", counting)
    for _ in range(5):
        assert benchmarks.games_for("Vayne", "sr") == 0
    assert calls["n"] == 1


def test_corrupt_file_recovers_when_rewritten(bench_file):
    bench_file(None, raw=b"{not json")
    assert benchmarks.games_for("Vayne", "sr") == 0
    bench_file(_doc({"Vayne|sr": _entry(games=7)}))
    assert benchmarks.games_for("Vayne", "sr") == 7


@pytest.mark.parametrize("raw", [b"\xff\xfe\x00", b"[" * 100000, b"null",
                                 b'"text"', b"[1, 2]", b"7"])
def test_unparseable_or_non_object_document_is_empty(bench_file, raw):
    bench_file(None, raw=raw)
    assert benchmarks.get("Vayne", "sr", "cs_at_10") == {}
    assert benchmarks.rank_value("Vayne", "sr", "cs_at_10", 50) == "no-data"
    assert benchmarks.games_for("Vayne", "sr") == 0
    assert benchmarks.rows_for_mode("sr") == []
    assert benchmarks.text_freq("Vayne", "sr", "game_sense_early") == {}


class _FakePath:
    """A BENCHMARKS_PATH stand-in whose stat / read can be made to fail."""

    def __init__(self, real):
        self.real = real
        self.stat_exc = None
        self.read_exc = None

    def stat(self):
        if self.stat_exc is not None:
            raise self.stat_exc
        return self.real.stat()

    def read_bytes(self):
        if self.read_exc is not None:
            raise self.read_exc
        return self.real.read_bytes()

    def read_text(self, *a, **kw):
        if self.read_exc is not None:
            raise self.read_exc
        return self.real.read_text(*a, **kw)


def test_stat_permission_error_never_raises(bench_file, monkeypatch):
    real = bench_file(_doc({"Vayne|sr": _entry(games=10)}))
    fake = _FakePath(real)
    monkeypatch.setattr(benchmarks, "BENCHMARKS_PATH", fake)
    assert benchmarks.games_for("Vayne", "sr") == 10
    fake.stat_exc = PermissionError(13, "denied")
    # Last good data is kept through a transient stat failure.
    assert benchmarks.games_for("Vayne", "sr") == 10
    assert benchmarks.rank_value("Vayne", "sr", "cs_at_10", 95) == "p50-p75"


def test_stat_permission_error_cold_is_empty(bench_file, monkeypatch):
    real = bench_file(_doc({"Vayne|sr": _entry(games=10)}))
    fake = _FakePath(real)
    fake.stat_exc = PermissionError(13, "denied")
    monkeypatch.setattr(benchmarks, "BENCHMARKS_PATH", fake)
    assert benchmarks.games_for("Vayne", "sr") == 0
    fake.stat_exc = None
    assert benchmarks.games_for("Vayne", "sr") == 10


def test_transient_read_error_keeps_last_good_then_retries(bench_file, monkeypatch):
    real = bench_file(_doc({"Vayne|sr": _entry(games=10)}), mtime=1_000_000_000)
    fake = _FakePath(real)
    monkeypatch.setattr(benchmarks, "BENCHMARKS_PATH", fake)
    assert benchmarks.games_for("Vayne", "sr") == 10
    bench_file(_doc({"Vayne|sr": _entry(games=20)}), mtime=1_100_000_000)
    fake.read_exc = PermissionError(13, "sharing violation")
    assert benchmarks.games_for("Vayne", "sr") == 10
    fake.read_exc = None
    assert benchmarks.games_for("Vayne", "sr") == 20


def test_missing_file_is_empty(bench_file):
    assert benchmarks.games_for("Vayne", "sr") == 0
    assert benchmarks.rows_for_mode("sr") == []


# --- shape validation in the accessors -------------------------------------

@pytest.mark.parametrize("champions", [[["Vayne|sr", 1]], "x", 5, None])
def test_non_dict_champions_is_empty(bench_file, champions):
    bench_file({"champions": champions})
    assert benchmarks.get("Vayne", "sr", "cs_at_10") == {}
    assert benchmarks.games_for("Vayne", "sr") == 0
    assert benchmarks.rows_for_mode("sr") == []
    assert benchmarks.text_freq("Vayne", "sr", "k") == {}


@pytest.mark.parametrize("entry", [5, "x", [1], True])
def test_non_dict_entry_costs_only_itself(bench_file, entry):
    bench_file(_doc({"Vayne|sr": entry, "Ashe|sr": _entry(games=3)}))
    assert benchmarks.get("Vayne", "sr", "cs_at_10") == {}
    assert benchmarks.rank_value("Vayne", "sr", "cs_at_10", 1) == "no-data"
    assert benchmarks.games_for("Vayne", "sr") == 0
    assert benchmarks.text_freq("Vayne", "sr", "k") == {}
    rows = benchmarks.rows_for_mode("sr")
    assert [r["champion"] for r in rows] == ["Ashe"]


@pytest.mark.parametrize("metrics", [[1, 2], "x", 7])
def test_non_dict_metrics(bench_file, metrics):
    bench_file(_doc({"Vayne|sr": {"games": 4, "metrics": metrics}}))
    assert benchmarks.get("Vayne", "sr", "cs_at_10") == {}
    rows = benchmarks.rows_for_mode("sr")
    assert rows == [{"champion": "Vayne", "games": 4, "metrics": {}}]


@pytest.mark.parametrize("metric", [[80, 90, 100], "x", 3])
def test_non_dict_metric_entry(bench_file, metric):
    bench_file(_doc({"Vayne|sr": _entry(metrics={"cs_at_10": metric})}))
    assert benchmarks.get("Vayne", "sr", "cs_at_10") == {}
    assert benchmarks.rank_value("Vayne", "sr", "cs_at_10", 1) == "no-data"


# --- rank_value -------------------------------------------------------------

@pytest.mark.parametrize("value,band", [
    (79.9, "below-p25"), (80, "p25-p50"), (89, "p25-p50"), (90, "p50-p75"),
    (100, "above-p75"), (1e9, "above-p75"), (float("inf"), "above-p75"),
    (float("-inf"), "below-p25"),
])
def test_rank_value_bands(bench_file, value, band):
    bench_file(_doc({"Vayne|sr": _entry()}))
    assert benchmarks.rank_value("Vayne", "sr", "cs_at_10", value) == band


@pytest.mark.parametrize("value", [float("nan"), None, "95", True, False, [95],
                                   {"v": 95}])
def test_rank_value_junk_value_is_no_data(bench_file, value):
    bench_file(_doc({"Vayne|sr": _entry()}))
    assert benchmarks.rank_value("Vayne", "sr", "cs_at_10", value) == "no-data"


@pytest.mark.parametrize("pcts", [
    {"p25": "80", "p50": 90, "p75": 100},
    {"p25": 80, "p50": float("nan"), "p75": 100},
    {"p25": 80, "p50": 90, "p75": float("inf")},
    {"p25": True, "p50": 90, "p75": 100},
    {"p25": 100, "p50": 90, "p75": 80},
    {"p25": 80, "p50": 110, "p75": 100},
    {"p25": 80, "p50": 90},
])
def test_rank_value_junk_percentiles_is_no_data(bench_file, pcts):
    bench_file(_doc({"Vayne|sr": _entry(metrics={"cs_at_10": pcts})}))
    assert benchmarks.rank_value("Vayne", "sr", "cs_at_10", 95) == "no-data"


def test_rank_value_nan_written_as_json_nan(bench_file):
    raw = (b'{"champions": {"Vayne|sr": {"games": 9, "metrics": {"cs_at_10":'
           b' {"p25": NaN, "p50": NaN, "p75": NaN}}}}}')
    bench_file(None, raw=raw)
    assert benchmarks.rank_value("Vayne", "sr", "cs_at_10", 95) == "no-data"


# --- games_for --------------------------------------------------------------

@pytest.mark.parametrize("games,want", [
    (10, 10), (0, 0), (10.0, 10), ("9", 0), (None, 0), (True, 0), (False, 0),
    (float("nan"), 0), (float("inf"), 0), (3.7, 0), (-3, 0), (-2.0, 0),
    ([5], 0), ({"n": 5}, 0),
])
def test_games_for_returns_a_count(bench_file, games, want):
    bench_file(None, raw=json.dumps(
        _doc({"Vayne|sr": _entry(games=games)})).encode("ascii"))
    got = benchmarks.games_for("Vayne", "sr")
    assert got == want
    assert type(got) is int
    assert got >= 5 or got < 5  # the aftergame comparison never raises


def test_games_for_missing_key(bench_file):
    bench_file(_doc({"Vayne|sr": {"metrics": {}}}))
    assert benchmarks.games_for("Vayne", "sr") == 0


# --- rows_for_mode -----------------------------------------------------------

def test_rows_for_mode_one_junk_games_costs_only_itself(bench_file):
    bench_file(_doc({
        "Vayne|sr": _entry(games=161),
        "Ashe|sr": _entry(games="9"),
        "Jinx|sr": _entry(games=20),
        "Lux|aram": _entry(games=999),
    }))
    rows = benchmarks.rows_for_mode("sr")
    assert [r["champion"] for r in rows] == ["Vayne", "Jinx", "Ashe"]
    # The raw games value is passed through; the route is the validator.
    assert rows[2]["games"] == "9"


def test_rows_for_mode_nan_games_sorts_last(bench_file):
    raw = (b'{"champions": {"A|sr": {"games": 5}, "B|sr": {"games": NaN},'
           b' "C|sr": {"games": 50}, "D|sr": {"games": 7}}}')
    bench_file(None, raw=raw)
    names = [r["champion"] for r in benchmarks.rows_for_mode("sr")]
    assert names == ["C", "D", "A", "B"]


@pytest.mark.parametrize("mode", ["", None, 5, "a|sr", ["sr"]])
def test_rows_for_mode_bad_mode_is_empty(bench_file, mode):
    bench_file(_doc({"X|": _entry(), "Vayne|a|sr": _entry(), "Ashe|sr": _entry()}))
    assert benchmarks.rows_for_mode(mode) == []


def test_rows_for_mode_shape(bench_file):
    bench_file(_doc({"Vayne|sr": _entry(games=3), "Ashe|sr": _entry(games=8)}))
    rows = benchmarks.rows_for_mode("sr")
    assert [r["champion"] for r in rows] == ["Ashe", "Vayne"]
    assert set(rows[0]) == {"champion", "games", "metrics"}
    assert rows[0]["metrics"]["cs_at_10"]["p50"] == 90.0


# --- returned dicts never alias the cache -----------------------------------

def test_get_result_mutation_does_not_poison_cache(bench_file):
    bench_file(_doc({"Vayne|sr": _entry()}))
    b = benchmarks.get("Vayne", "sr", "cs_at_10")
    b["p25"] = 1e9
    b.clear()
    assert benchmarks.get("Vayne", "sr", "cs_at_10")["p25"] == 80.0
    assert benchmarks.rank_value("Vayne", "sr", "cs_at_10", 85) == "p25-p50"


def test_rows_for_mode_mutation_does_not_poison_cache(bench_file):
    bench_file(_doc({"Vayne|sr": _entry()}))
    row = benchmarks.rows_for_mode("sr")[0]
    row["metrics"]["cs_at_10"]["p25"] = -1
    row["metrics"].clear()
    assert benchmarks.get("Vayne", "sr", "cs_at_10")["p25"] == 80.0


def test_text_freq_mutation_does_not_poison_cache(bench_file):
    bench_file(_doc({"Vayne|sr": _entry(text_freq={"game_sense_early": {"Composed": 4}})}))
    f = benchmarks.text_freq("Vayne", "sr", "game_sense_early")
    f["Composed"] = 99
    assert benchmarks.text_freq("Vayne", "sr", "game_sense_early") == {"Composed": 4}


# --- text_freq ----------------------------------------------------------------

def test_text_freq_keeps_only_counts(bench_file):
    raw = json.dumps(_doc({"Vayne|sr": _entry(text_freq={"game_sense_early": {
        "Composed": 4, "Tilted": "3", "Calm": None, "Lost": True, "Bad": -1,
        "Half": 2.5, "Whole": 6.0,
    }})})).encode("ascii")
    bench_file(None, raw=raw)
    freq = benchmarks.text_freq("Vayne", "sr", "game_sense_early")
    assert freq == {"Composed": 4, "Whole": 6}
    # The aftergame consumer sorts and sums these; that must never raise.
    assert sum(freq.values()) == 10
    sorted(freq.items(), key=lambda kv: -kv[1])


@pytest.mark.parametrize("tf", [[1], "x", 3])
def test_text_freq_non_dict(bench_file, tf):
    bench_file(_doc({"Vayne|sr": _entry(text_freq=tf)}))
    assert benchmarks.text_freq("Vayne", "sr", "game_sense_early") == {}


def test_text_freq_non_dict_metric(bench_file):
    bench_file(_doc({"Vayne|sr": _entry(text_freq={"game_sense_early": [1, 2]})}))
    assert benchmarks.text_freq("Vayne", "sr", "game_sense_early") == {}


# --- key addressing -----------------------------------------------------------

@pytest.mark.parametrize("champ,mode", [("Vayne|sr", "x"), (None, "sr"),
                                        ("Vayne", None), ("", "sr"), ("Vayne", "")])
def test_bad_key_parts_are_no_data(bench_file, champ, mode):
    bench_file(_doc({"Vayne|sr|x": _entry(), "None|sr": _entry(),
                     "Vayne|None": _entry(), "|sr": _entry(), "Vayne|": _entry()}))
    assert benchmarks.get(champ, mode, "cs_at_10") == {}
    assert benchmarks.games_for(champ, mode) == 0


def test_real_shape_round_trip(bench_file):
    bench_file(_doc({"Tristana|sr_ranked": _entry(
        games=12, text_freq={"game_sense_early": {"Composed": 7, "Tilted": 2}})}))
    assert benchmarks.get("Tristana", "sr_ranked", "cs_at_10")["weighted_n"] == 10.0
    assert benchmarks.games_for("Tristana", "sr_ranked") == 12
    assert benchmarks.rank_value("Tristana", "sr_ranked", "cs_at_10", 101) == "above-p75"
    assert benchmarks.text_freq("Tristana", "sr_ranked", "game_sense_early") == {
        "Composed": 7, "Tilted": 2}
    assert math.isclose(
        benchmarks.get("Tristana", "sr_ranked", "cs_at_10")["avg"], 90.0)
