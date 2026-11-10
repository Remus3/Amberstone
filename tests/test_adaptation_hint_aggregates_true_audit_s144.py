"""True-audit (s144 lane 8, cycle 150) of ``coaches/adaptation_hint_aggregates.py``.

``top_champions`` backs the supervisor's ``GET /api/adaptation`` (no
champion) and ``kda_trends`` backs ``GET /api/trending``, the coaching
digest, the cold-streak advisory pass and the ``--trends`` CLI. Both
read rows of a mode DB that RC did not validate on the way in, and the
supervisor serializes with ``allow_nan=False``.

Findings pinned here (RM-1876..RM-1885), each measured before the fix:

* RM-1876 ``with sqlite3.connect()`` commits but never closes, so each
  call leaked one connection until GC.
* RM-1877 ``top_champions`` raised on one bad row and lost the whole
  list: a NULL ``avg_rating`` / ``wins`` / ``losses`` (TypeError), a junk
  TEXT ``games_played`` or ``recent_sample_size`` (ValueError), a
  non-object ``aggregates_json`` (AttributeError).
* RM-1878 ``top_champions`` passed non-finite numbers through (a TEXT
  ``inf`` rating, ``NaN`` / ``Infinity`` literals in the aggregates), so
  the strict-JSON body failed and ``/api/adaptation`` answered 500.
* RM-1879 ``kda_trends`` raised on one bad row and lost every streak in
  the mode: a non-dict ``recent_kda`` / ``avg_kda`` (AttributeError), a
  junk ``delta_ratio`` / ``sample`` / ``ratio`` (ValueError), a list
  ``aggregates_json`` (AttributeError).
* RM-1880 a non-finite or absurd ``delta_ratio`` took a hot / cold
  slot ahead of every real streak and broke the strict-JSON body.
* RM-1881 ``n`` was a raw LIMIT / slice bound: a negative ``n`` listed
  EVERY row in ``top_champions`` (LIMIT -1) and all but the last streak in
  ``kda_trends``; a str raised TypeError; a huge int raised OverflowError.
* RM-1882 a dropped junk row still consumed a ``top_champions`` LIMIT
  slot, so it crowded a valid champion out of the top-N.
* RM-1883 the champion name was passed raw: a BLOB reached the payload
  as bytes, a newline split the CLI line, a blank name was listed.
* RM-1884 a deeply nested ``aggregates_json`` raised RecursionError and
  undecodable BLOB bytes raised UnicodeDecodeError out of both functions.
* RM-1885 a TEXT cell holding invalid UTF-8 raised OperationalError
  mid-fetch, so one such row emptied the whole mode (found by the cycle
  verifier). It now comes back as bytes, which every validator rejects.

Well-formed rows give byte-identical output.
"""
from __future__ import annotations

import json
import math
import sqlite3
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

GOOD_AJ = {
    "win_rate": 0.55,
    "recent_win_rate": 0.6,
    "recent_sample_size": 10,
    "avg_duration_sec": 1100.5,
    "avg_kda": {"k": 9.0, "d": 5.0, "a": 13.0, "ratio": 4.4, "sample": 30},
    "recent_kda": {"k": 6.0, "d": 6.0, "a": 9.0, "ratio": 2.5,
                   "sample": 10, "delta_ratio": -1.9},
}
HOT_AJ = {
    "avg_kda": {"ratio": 2.0, "sample": 20},
    "recent_kda": {"ratio": 5.0, "sample": 10, "delta_ratio": 3.0},
}


@pytest.fixture
def db(tmp_path: Path, monkeypatch) -> Path:
    import agents.agent2_backend.db_schema as dbs
    from coaches import adaptation_hint
    monkeypatch.setattr(dbs, "DB_DIR", tmp_path)
    monkeypatch.setattr(adaptation_hint, "DB_DIR", tmp_path)
    dbs.init_mode("aram")
    return tmp_path / "aram.db"


def _row(db: Path, champ, aj, games=20, wins=11, losses=9, rating=0.55):
    raw = aj if not isinstance(aj, (dict, list)) else json.dumps(aj)
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "INSERT INTO adaptation_buckets (champion, games_played, wins,"
            " losses, avg_rating, last_updated, aggregates_json)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (champ, games, wins, losses, rating, "2026-04-22T00:00:00Z", raw),
        )
        conn.commit()
    finally:
        conn.close()


def _strict(obj) -> None:
    json.dumps(obj, default=str, allow_nan=False)


def _top(**kw):
    from coaches.adaptation_hint_aggregates import top_champions
    kw.setdefault("n", 10)
    kw.setdefault("min_games", 1)
    return top_champions("aram", **kw)


def _trends(**kw):
    from coaches.adaptation_hint_aggregates import kda_trends
    return kda_trends("aram", **kw)


# -- characterization: well-formed rows are byte-identical ---------------

def test_top_champions_well_formed_row_is_unchanged(db: Path) -> None:
    _row(db, "Ahri", GOOD_AJ)
    assert _top() == [{
        "champion": "Ahri",
        "games_played": 20,
        "wins": 11,
        "losses": 9,
        "win_rate": 0.55,
        "recent_win_rate": 0.6,
        "recent_sample_size": 10,
        "avg_duration_sec": 1100.5,
        "avg_kda": GOOD_AJ["avg_kda"],
        "recent_kda": GOOD_AJ["recent_kda"],
    }]


def test_top_champions_orders_and_limits_by_games(db: Path) -> None:
    for i, g in enumerate((5, 50, 20)):
        _row(db, f"C{i}", GOOD_AJ, games=g)
    assert [c["champion"] for c in _top(n=2)] == ["C1", "C2"]
    assert [c["champion"] for c in _top(min_games=21)] == ["C1"]


def test_top_champions_missing_optional_fields_keep_old_defaults(db: Path) -> None:
    _row(db, "Bare", None)
    (c,) = _top()
    assert c["recent_win_rate"] is None
    assert c["recent_sample_size"] == 0
    assert c["avg_duration_sec"] is None
    assert c["avg_kda"] is None and c["recent_kda"] is None


def test_kda_trends_well_formed_is_unchanged(db: Path) -> None:
    _row(db, "Heater", HOT_AJ)
    _row(db, "Cooler", GOOD_AJ)
    assert _trends(n=3) == {
        "mode": "aram",
        "hot": [{"champion": "Heater", "baseline_ratio": 2.0,
                 "recent_ratio": 5.0, "delta": 3.0, "sample": 10}],
        "cold": [{"champion": "Cooler", "baseline_ratio": 4.4,
                  "recent_ratio": 2.5, "delta": -1.9, "sample": 10}],
    }


def test_kda_trends_missing_ratio_keeps_zero_default(db: Path) -> None:
    _row(db, "NoRatio", {"avg_kda": {"sample": 20},
                         "recent_kda": {"sample": 10, "delta_ratio": 1.0}})
    (e,) = _trends()["hot"]
    assert e["baseline_ratio"] == 0.0 and e["recent_ratio"] == 0.0


def test_unknown_mode_is_empty() -> None:
    from coaches.adaptation_hint_aggregates import kda_trends, top_champions
    assert top_champions("nope") == []
    assert kda_trends("nope") == {"mode": "nope", "hot": [], "cold": []}
    assert top_champions(["aram"]) == []


# -- RM-1876 connection lifetime -------------------------------------

def test_every_connection_is_closed(db: Path, monkeypatch) -> None:
    _row(db, "Ahri", GOOD_AJ)
    real = sqlite3.connect
    opened: list[sqlite3.Connection] = []

    def spy(*a, **kw):
        c = real(*a, **kw)
        opened.append(c)
        return c

    monkeypatch.setattr(sqlite3, "connect", spy)
    _top()
    _trends()
    assert len(opened) == 2
    for c in opened:
        with pytest.raises(sqlite3.ProgrammingError):
            c.execute("SELECT 1")


# -- RM-1877 / 410 top_champions bad rows ----------------------------

@pytest.mark.parametrize("bad", [
    {"rating": None},
    {"wins": None},
    {"losses": None},
    {"games": "lots"},
    {"aj": {"recent_sample_size": "ten"}},
    {"aj": None, "raw": "null"},
    {"aj": None, "raw": "[1, 2]"},
    {"aj": None, "raw": "7"},
    {"aj": {"avg_kda": [1, 2], "recent_kda": "x"}},
])
def test_top_champions_one_bad_row_never_loses_the_list(db: Path, bad) -> None:
    _row(db, "Good", GOOD_AJ, games=10)
    aj = bad.get("raw", bad.get("aj", GOOD_AJ))
    _row(db, "Bad", aj, games=bad.get("games", 30),
         wins=bad.get("wins", 11), losses=bad.get("losses", 9),
         rating=bad.get("rating", 0.55))
    out = _top()
    _strict(out)
    assert "Good" in [c["champion"] for c in out]
    good = next(c for c in out if c["champion"] == "Good")
    assert good["avg_kda"] == GOOD_AJ["avg_kda"]


def test_top_champions_null_counts_are_clamped_and_rating_none(db: Path) -> None:
    _row(db, "Nulls", GOOD_AJ, wins=None, losses=-4, rating=None)
    (c,) = _top()
    assert c["wins"] == 0 and c["losses"] == 0
    assert c["win_rate"] is None


def test_top_champions_numeric_text_count_still_parses(db: Path) -> None:
    _row(db, "TextCount", {"recent_sample_size": "7"})
    (c,) = _top()
    assert c["recent_sample_size"] == 7


@pytest.mark.parametrize("raw", [
    '{"recent_win_rate": NaN}',
    '{"avg_duration_sec": Infinity}',
    '{"avg_kda": {"ratio": -Infinity, "sample": 3}}',
    '{"recent_kda": {"ratio": 1e400, "delta_ratio": NaN}}',
    '{"recent_win_rate": 1e300}',
    '{"recent_win_rate": true}',
])
def test_top_champions_never_breaks_strict_json(db: Path, raw) -> None:
    _row(db, "Ahri", raw)
    out = _top()
    _strict(out)
    assert out[0]["champion"] == "Ahri"


def test_top_champions_absurd_finite_value_is_none(db: Path) -> None:
    _row(db, "Ahri", '{"recent_win_rate": 1e300, "avg_duration_sec": -1e13}')
    (c,) = _top()
    assert c["recent_win_rate"] is None and c["avg_duration_sec"] is None


def test_top_champions_text_inf_rating_is_none(db: Path) -> None:
    _row(db, "Ahri", GOOD_AJ, rating="inf")
    (c,) = _top()
    assert c["win_rate"] is None
    _strict(c)


def test_top_champions_nested_kda_values_are_scrubbed(db: Path) -> None:
    _row(db, "Ahri", '{"avg_kda": {"ratio": NaN, "sample": 3, "x": [1]}}')
    (c,) = _top()
    assert c["avg_kda"] == {"ratio": None, "sample": 3, "x": None}


# -- RM-1879 / 412 kda_trends bad rows -------------------------------

@pytest.mark.parametrize("aj", [
    {"avg_kda": {"ratio": 3.0}, "recent_kda": [1, 2]},
    {"avg_kda": [1, 2], "recent_kda": {"sample": 10, "delta_ratio": -1.0}},
    {"avg_kda": {"ratio": 3.0},
     "recent_kda": {"sample": 10, "delta_ratio": "steep"}},
    {"avg_kda": {"ratio": 3.0},
     "recent_kda": {"sample": "many", "delta_ratio": -1.0}},
    {"avg_kda": {"ratio": "high"},
     "recent_kda": {"sample": 10, "delta_ratio": -1.0}},
    {"avg_kda": {"ratio": 3.0},
     "recent_kda": {"sample": True, "delta_ratio": -1.0}},
    {"avg_kda": {"ratio": 3.0},
     "recent_kda": {"sample": 10, "delta_ratio": True}},
    [1, 2, 3],
])
def test_kda_trends_one_bad_row_never_loses_the_mode(db: Path, aj) -> None:
    _row(db, "Cooler", GOOD_AJ)
    _row(db, "Bad", aj)
    out = _trends(n=3)
    _strict(out)
    assert [e["champion"] for e in out["cold"]] == ["Cooler"]
    assert out["hot"] == []


@pytest.mark.parametrize("delta", ["-Infinity", "Infinity", "NaN", "-1e13",
                                   "1e400"])
def test_kda_trends_absurd_delta_never_takes_a_slot(db: Path, delta) -> None:
    _row(db, "Cooler", GOOD_AJ)
    _row(db, "Heater", HOT_AJ)
    for i in range(3):
        raw = ('{"avg_kda": {"ratio": 3.0}, "recent_kda":'
               ' {"ratio": 1.0, "sample": 10, "delta_ratio": DELTA}}')
        _row(db, f"Junk{i}", raw.replace("DELTA", delta))
    out = _trends(n=1)
    _strict(out)
    assert [e["champion"] for e in out["cold"]] == ["Cooler"]
    assert [e["champion"] for e in out["hot"]] == ["Heater"]


def test_kda_trends_non_finite_ratio_is_dropped(db: Path) -> None:
    _row(db, "Cooler", GOOD_AJ)
    _row(db, "Junk", '{"avg_kda": {"ratio": NaN}, "recent_kda":'
         ' {"ratio": 1.0, "sample": 10, "delta_ratio": -5.0}}')
    out = _trends()
    _strict(out)
    assert [e["champion"] for e in out["cold"]] == ["Cooler"]


def test_kda_trends_negative_sample_never_passes_a_zero_floor(db: Path) -> None:
    _row(db, "Neg", {"avg_kda": {"ratio": 3.0},
                     "recent_kda": {"sample": -3, "delta_ratio": -1.0}})
    assert _trends(min_sample=0)["cold"] == []


def test_kda_trends_float_sample_truncates_like_before(db: Path) -> None:
    _row(db, "Flt", {"avg_kda": {"ratio": 3.0},
                     "recent_kda": {"sample": 7.9, "delta_ratio": -1.0}})
    (e,) = _trends()["cold"]
    assert e["sample"] == 7 and isinstance(e["sample"], int)


# -- RM-1881 n / floor bounds ----------------------------------------

def test_top_champions_negative_n_lists_nothing(db: Path) -> None:
    for i in range(4):
        _row(db, f"C{i}", GOOD_AJ, games=10 + i)
    assert _top(n=-1) == []
    assert _top(n=0) == []


def test_kda_trends_negative_n_lists_nothing(db: Path) -> None:
    for i, d in enumerate((1.0, 2.0, -1.0, -2.0)):
        _row(db, f"C{i}", {"avg_kda": {"ratio": 3.0},
                           "recent_kda": {"sample": 10, "delta_ratio": d}})
    assert _trends(n=-1) == {"mode": "aram", "hot": [], "cold": []}
    assert _trends(n=0) == {"mode": "aram", "hot": [], "cold": []}


@pytest.mark.parametrize("n", ["3", None, 2.5, True, 10 ** 30])
def test_junk_or_huge_n_never_raises(db: Path, n) -> None:
    _row(db, "Ahri", GOOD_AJ)
    assert [c["champion"] for c in _top(n=n)] == ["Ahri"]
    assert [e["champion"] for e in _trends(n=n)["cold"]] == ["Ahri"]


@pytest.mark.parametrize("floor", ["5", None, True, 10 ** 30, -(10 ** 30)])
def test_junk_or_huge_floor_never_raises(db: Path, floor) -> None:
    _row(db, "Ahri", GOOD_AJ)
    assert isinstance(_top(min_games=floor), list)
    assert isinstance(_trends(min_sample=floor)["cold"], list)


# -- RM-1882 junk rows never crowd the LIMIT -------------------------

def test_dropped_rows_never_consume_a_limit_slot(db: Path) -> None:
    _row(db, "Junk1", GOOD_AJ, games="lots")
    _row(db, "Junk2", GOOD_AJ, games=99, rating=0.5, wins="x")
    _row(db, b"Blob", GOOD_AJ, games=98)
    _row(db, "Good", GOOD_AJ, games=10)
    assert "Good" in [c["champion"] for c in _top(n=2)]


# -- RM-1883 champion label ------------------------------------------

def test_champion_label_is_one_printable_line(db: Path) -> None:
    _row(db, "Ja\nx", GOOD_AJ, games=30)
    _row(db, "   ", GOOD_AJ, games=29)
    _row(db, b"Jinx", GOOD_AJ, games=28)
    _row(db, "Z" * 200, GOOD_AJ, games=27)
    names = [c["champion"] for c in _top()]
    assert names == ["Ja x", "Z" * 64]
    cold = [e["champion"] for e in _trends(n=10)["cold"]]
    assert cold == ["Ja x", "Z" * 64]


# -- RM-1884 decode failures -----------------------------------------

@pytest.mark.parametrize("raw", ["[" * 100000, b"\xff\xfe\x00junk",
                                 '{"a": 1', ""])
def test_undecodable_aggregates_never_raise(db: Path, raw) -> None:
    _row(db, "Good", GOOD_AJ, games=10)
    _row(db, "Bad", raw, games=30)
    top = _top()
    assert [c["champion"] for c in top] == ["Bad", "Good"]
    assert top[0]["avg_kda"] is None
    assert [e["champion"] for e in _trends()["cold"]] == ["Good"]


def _raw_sql_row(db: Path, champ_sql: str, aj_sql: str, games: int) -> None:
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "INSERT INTO adaptation_buckets (champion, games_played, wins,"
            " losses, avg_rating, last_updated, aggregates_json)"
            f" VALUES ({champ_sql}, ?, 1, 1, 0.5, 'x', {aj_sql})", (games,))
        conn.commit()
    finally:
        conn.close()


# -- RM-1885 invalid UTF-8 TEXT cells (verifier note, cycle 150) -------

@pytest.mark.parametrize("champ_sql,aj_sql", [
    ("CAST(x'ff41' AS TEXT)", "'{}'"),
    ("'Bad'", "CAST(x'ff7b7d' AS TEXT)"),
])
def test_invalid_utf8_cell_skips_only_its_row(db: Path, champ_sql,
                                              aj_sql) -> None:
    _row(db, "Good", GOOD_AJ, games=10)
    _raw_sql_row(db, champ_sql, aj_sql, games=30)
    assert "Good" in [c["champion"] for c in _top()]
    assert [e["champion"] for e in _trends()["cold"]] == ["Good"]


def test_float_floor_is_still_honoured(db: Path) -> None:
    _row(db, "Ahri", GOOD_AJ, games=20)
    assert _top(min_games=20.5) == []
    assert [c["champion"] for c in _top(min_games=19.5)] == ["Ahri"]
    assert _trends(min_sample=10.5)["cold"] == []


def test_outputs_are_finite_everywhere(db: Path) -> None:
    _row(db, "A", '{"recent_win_rate": NaN, "avg_kda": {"ratio": NaN}}')
    for c in _top():
        for v in c.values():
            if isinstance(v, float):
                assert math.isfinite(v)
