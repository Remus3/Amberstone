"""Lane 8 (true-audit) s144 cycle 228: core/role_bracket_bench.py hardening.

The reader feeds GET /api/role-bracket-bench from the gitignored rewind corpus
(data/rewind_history.db, SQLite, WAL). Every test builds a synthetic corpus in
tmp_path with the columns the reader's query names (scripts/rewind_scraper.py
SCHEMA subset) and points REWIND_DB_PATH at it. Match ids are synthetic.
"""
from __future__ import annotations

import math
import os
import sqlite3
import unittest
from pathlib import Path
from unittest import mock

import pytest

from core import role_bracket_bench as bench

_SCHEMA = """
CREATE TABLE matches (
    match_id TEXT PRIMARY KEY,
    game_mode TEXT,
    game_duration_s INTEGER,
    tracked_champion_id INTEGER,
    tracked_team_id INTEGER,
    tracked_kp INTEGER
);
CREATE TABLE participants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id TEXT NOT NULL,
    team_id INTEGER,
    champion_id INTEGER,
    champ_level INTEGER,
    total_minions_killed INTEGER,
    neutral_minions_killed INTEGER,
    team_position TEXT,
    kills INTEGER,
    deaths INTEGER,
    assists INTEGER
);
"""

_INF = float("inf")


def _row(mid, *, dur=1200, pos="MIDDLE", lvl=14, tmk=150, nmk=10,
         k=4, d=2, a=6, kp=50, mode="CLASSIC"):
    return {"mid": mid, "dur": dur, "pos": pos, "lvl": lvl, "tmk": tmk,
            "nmk": nmk, "k": k, "d": d, "a": a, "kp": kp, "mode": mode}


def _insert(conn, r, *, participant_copies=1):
    conn.execute(
        "INSERT INTO matches VALUES (?, ?, ?, ?, ?, ?)",
        (r["mid"], r["mode"], r["dur"], 1, 100, r["kp"]))
    for _ in range(participant_copies):
        conn.execute(
            "INSERT INTO participants (match_id, team_id, champion_id,"
            " champ_level, total_minions_killed, neutral_minions_killed,"
            " team_position, kills, deaths, assists)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (r["mid"], 100, 1, r["lvl"], r["tmk"], r["nmk"], r["pos"],
             r["k"], r["d"], r["a"]))


def _make_db(path: Path, rows, *, copies=None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(_SCHEMA)
        for r in rows:
            _insert(conn, r, participant_copies=(copies or {}).get(r["mid"], 1))
        conn.commit()
    finally:
        conn.close()
    return path


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    """Factory: build a corpus at tmp_path/<name> and point the reader at it."""
    bench._reset_cache()

    def _build(rows, *, name="rewind_history.db", copies=None):
        path = _make_db(tmp_path / name, rows, copies=copies)
        monkeypatch.setattr(bench, "REWIND_DB_PATH", path)
        return path

    yield _build
    bench._reset_cache()


def _all_numbers(grid):
    for by_bracket in grid.values():
        for cell in by_bracket.values():
            yield cell["n"]
            for key in ("lvl", "cs", "tf", "kda"):
                for field in ("avg", "p50", "n"):
                    v = cell[key][field]
                    if v is not None:
                        yield v


# --- characterization (green on the old module and the new one) -------------

def test_clean_corpus_grid_shape_and_values(corpus):
    corpus([
        _row("T_1", dur=600, lvl=10, tmk=80, nmk=0, k=2, d=0, a=3, kp=40),
        _row("T_2", dur=1200, lvl=14, tmk=150, nmk=10, k=4, d=2, a=6, kp=50),
        _row("T_3", dur=1800, lvl=16, tmk=200, nmk=20, k=6, d=4, a=2, kp=60),
        _row("T_4", dur=1300, pos="UTILITY", lvl=12, tmk=20, nmk=0, kp=70),
        _row("T_5", dur=1300, pos="", lvl=12),            # unknown role
        _row("T_6", dur=1300, mode="ARAM", lvl=18),        # not SR
        _row("T_7", dur=0, lvl=18),                        # unfinished
    ])
    grid = bench.role_bracket_grid()
    assert set(grid) == {"mid", "support"}
    early = grid["mid"]["early"]
    assert early["n"] == 1
    assert early["lvl"] == {"avg": 10.0, "p50": 10.0, "n": 1}
    assert early["kda"]["avg"] == 5.0          # (2 + 3) / max(0 -> 1)
    mid = grid["mid"]["mid"]
    assert mid["n"] == 2
    assert mid["lvl"] == {"avg": 15.0, "p50": 15.0, "n": 2}
    assert mid["cs"] == {"avg": 190.0, "p50": 190.0, "n": 2}
    assert mid["tf"] == {"avg": 55.0, "p50": 55.0, "n": 2}
    assert mid["kda"] == {"avg": 3.5, "p50": 3.5, "n": 2}   # 5.0 and 2.0
    assert grid["support"]["mid"]["n"] == 1


def test_bracket_boundary_is_14_minutes():
    assert bench._bracket_for_duration(839) == "early"
    assert bench._bracket_for_duration(840) == "mid"
    assert bench._bracket_for_duration(5000) == "mid"
    assert bench._bracket_for_duration(0) is None
    assert bench._bracket_for_duration(-5) is None
    assert bench._bracket_for_duration(None) is None
    assert bench._bracket_for_duration("junk") is None


def test_null_kda_components_read_as_zero(corpus):
    corpus([_row("T_1", k=None, d=None, a=None, lvl=None, kp=None)])
    cell = bench.role_bracket_grid()["mid"]["mid"]
    assert cell["n"] == 1
    assert cell["kda"] == {"avg": 0.0, "p50": 0.0, "n": 1}
    assert cell["lvl"] == {"avg": None, "p50": None, "n": 0}
    assert cell["tf"]["n"] == 0


def test_corpus_absent_is_empty_grid(tmp_path, monkeypatch):
    bench._reset_cache()
    monkeypatch.setattr(bench, "REWIND_DB_PATH", tmp_path / "missing.db")
    assert bench.corpus_present() is False
    assert bench.role_bracket_grid() == {}


def test_normalize_role_aliases():
    assert bench.normalize_role("Mid") == "mid"
    assert bench.normalize_role(" adc\t") == "bot"
    assert bench.normalize_role("UTILITY") == "support"
    assert bench.normalize_role("") is None
    assert bench.normalize_role("feeder") is None


# --- F1: junk TEXT / BLOB value in a numeric column ---------------------------

def test_text_value_in_numeric_column_costs_only_itself(corpus):
    corpus([_row("T_1", lvl="x"), _row("T_2", lvl=16)])
    grid = bench.role_bracket_grid()          # old: ValueError from float()
    cell = grid["mid"]["mid"]
    assert cell["n"] == 2
    assert cell["lvl"] == {"avg": 16.0, "p50": 16.0, "n": 1}
    assert cell["cs"]["n"] == 2


def test_blob_value_in_numeric_column_costs_only_itself(corpus):
    corpus([_row("T_1", lvl=b"\x01\x02"), _row("T_2", lvl=12)])
    cell = bench.role_bracket_grid()["mid"]["mid"]
    assert cell["lvl"] == {"avg": 12.0, "p50": 12.0, "n": 1}
    assert cell["n"] == 2


def test_invalid_utf8_text_costs_only_its_row(corpus):
    path = corpus([_row("T_1", lvl=10), _row("T_2", lvl=16)])
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("UPDATE participants SET team_position ="
                     " CAST(x'ff4d4944' AS TEXT) WHERE match_id = 'T_1'")
        conn.execute("UPDATE participants SET champ_level ="
                     " CAST(x'c3' AS TEXT) WHERE match_id = 'T_2'")
        conn.commit()
    finally:
        conn.close()
    grid = bench.role_bracket_grid()          # old: OperationalError -> {}
    cell = grid["mid"]["mid"]
    assert cell["n"] == 1
    assert cell["lvl"] == {"avg": None, "p50": None, "n": 0}
    assert cell["cs"]["n"] == 1


def test_match_with_every_stat_junk_still_counts_in_n(corpus):
    corpus([_row("T_1", lvl="x", tmk="x", kp="x", d="x"), _row("T_2", lvl=9)])
    cell = bench.role_bracket_grid()["mid"]["mid"]
    assert cell["n"] == 2                     # matches in the cell
    assert cell["lvl"]["n"] == 1
    assert cell["kda"]["n"] == 1


def test_junk_kda_component_drops_only_the_kda_value(corpus):
    corpus([_row("T_1", d="x"), _row("T_2", k=3, d=1, a=1)])
    cell = bench.role_bracket_grid()["mid"]["mid"]
    assert cell["kda"] == {"avg": 4.0, "p50": 4.0, "n": 1}
    assert cell["lvl"]["n"] == 2


def test_blob_position_is_skipped_not_raised(corpus):
    # A BLOB team_position (an int would be stored as TEXT by the column
    # affinity) is skipped, never .strip()ped with a str argument.
    corpus([_row("T_1", pos=b"\xffMIDDLE"), _row("T_2", pos="MIDDLE", lvl=9)])
    grid = bench.role_bracket_grid()
    assert set(grid) == {"mid"}
    assert grid["mid"]["mid"]["n"] == 1


# --- F2: non-finite / negative stat values ------------------------------------

def test_infinite_stat_value_is_skipped(corpus):
    corpus([_row("T_1", lvl=_INF, kp=-_INF), _row("T_2", lvl=10, kp=40)])
    grid = bench.role_bracket_grid()
    assert all(math.isfinite(v) for v in _all_numbers(grid))
    cell = grid["mid"]["mid"]
    assert cell["lvl"] == {"avg": 10.0, "p50": 10.0, "n": 1}
    assert cell["tf"] == {"avg": 40.0, "p50": 40.0, "n": 1}


def test_huge_finite_values_cannot_overflow_the_grid(corpus):
    # Each value is finite, but two of them sum past the float max.
    big = 1.5e308
    corpus([_row("T_1", lvl=big, kp=big, k=big, tmk=big, dur=big),
            _row("T_2", lvl=big, kp=big, k=big, tmk=big),
            _row("T_3", lvl=10, kp=40, k=1, d=1, a=1, tmk=100, nmk=0)])
    grid = bench.role_bracket_grid()
    assert all(math.isfinite(v) for v in _all_numbers(grid))
    cell = grid["mid"]["mid"]
    assert cell["n"] == 2                     # the huge-duration row is skipped
    assert cell["lvl"] == {"avg": 10.0, "p50": 10.0, "n": 1}
    assert cell["kda"] == {"avg": 2.0, "p50": 2.0, "n": 1}
    assert cell["cs"] == {"avg": 100.0, "p50": 100.0, "n": 1}


def test_infinite_kda_component_is_skipped(corpus):
    corpus([_row("T_1", k=_INF), _row("T_2", k=1, d=1, a=1)])
    grid = bench.role_bracket_grid()
    assert all(math.isfinite(v) for v in _all_numbers(grid))
    assert grid["mid"]["mid"]["kda"] == {"avg": 2.0, "p50": 2.0, "n": 1}


def test_negative_stat_value_is_skipped(corpus):
    corpus([_row("T_1", tmk=-500, nmk=0, d=-3), _row("T_2", tmk=100, nmk=0)])
    cell = bench.role_bracket_grid()["mid"]["mid"]
    assert cell["cs"] == {"avg": 100.0, "p50": 100.0, "n": 1}
    assert cell["kda"]["n"] == 1


# --- F3: non-finite duration ----------------------------------------------------

def test_non_finite_duration_has_no_bracket():
    assert bench._bracket_for_duration(_INF) is None
    assert bench._bracket_for_duration(float("nan")) is None
    assert bench._bracket_for_duration(True) is None
    assert bench._bracket_for_duration(b"900") is None


def test_infinite_duration_row_is_skipped(corpus):
    corpus([_row("T_1", dur=_INF, lvl=18), _row("T_2", dur=1000, lvl=10)])
    cell = bench.role_bracket_grid()["mid"]["mid"]
    assert cell["n"] == 1
    assert cell["lvl"]["avg"] == 10.0


# --- F4: duplicate participant rows -----------------------------------------------

def test_duplicate_participant_rows_count_the_match_once(corpus):
    corpus([_row("T_1", lvl=10), _row("T_2", lvl=16)], copies={"T_1": 3})
    cell = bench.role_bracket_grid()["mid"]["mid"]
    assert cell["n"] == 2
    assert cell["lvl"] == {"avg": 13.0, "p50": 13.0, "n": 2}


# --- F5: read-only URI built from a path with '#' / '%' ---------------------------

def test_path_with_hash_and_percent_opens_the_right_file(corpus):
    corpus([_row("T_1", lvl=11)], name="c%41t#x/rewind_history.db")
    grid = bench.role_bracket_grid()          # old: f"file:{posix}?mode=ro"
    assert grid["mid"]["mid"]["lvl"]["avg"] == 11.0


# --- F6: cache staleness (WAL writes, older-mtime restore) ------------------------

def test_wal_commit_without_checkpoint_refreshes_the_grid(corpus):
    path = corpus([_row("T_1", lvl=10)])
    writer = sqlite3.connect(str(path))
    try:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        writer.execute("PRAGMA wal_autocheckpoint=0")
        assert bench.role_bracket_grid()["mid"]["mid"]["n"] == 1
        before = path.stat().st_mtime_ns
        _insert(writer, _row("T_2", lvl=16))
        writer.commit()
        os.utime(path, ns=(before, before))   # main file untouched by a WAL commit
        cell = bench.role_bracket_grid()["mid"]["mid"]
        assert cell["n"] == 2
    finally:
        writer.close()


def test_restored_db_with_older_mtime_is_reread(corpus, tmp_path):
    path = corpus([_row("T_1", lvl=10)])
    assert bench.role_bracket_grid()["mid"]["mid"]["n"] == 1
    st = path.stat()
    other = _make_db(tmp_path / "restore" / "r.db",
                     [_row("T_1", lvl=10), _row("T_2", lvl=16)])
    other.replace(path)
    older = st.st_mtime_ns - 3_600_000_000_000
    os.utime(path, ns=(older, older))
    assert bench.role_bracket_grid()["mid"]["mid"]["n"] == 2


# --- F7: a failed rebuild keeps the last good grid, retried on a backoff ----------

def _bump(path: Path) -> None:
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))


def test_failed_rebuild_keeps_last_good_grid(corpus):
    path = corpus([_row("T_1", lvl=10)])
    good = bench.role_bracket_grid()
    _bump(path)
    with mock.patch.object(bench.sqlite3, "connect",
                           side_effect=sqlite3.OperationalError("locked")):
        assert bench.role_bracket_grid() == good   # old: {} (and cached)


def test_failed_build_is_not_rescanned_on_every_call(corpus):
    corpus([_row("T_1", lvl=10)])
    with mock.patch.object(bench.sqlite3, "connect",
                           side_effect=sqlite3.OperationalError("locked")) as c:
        for _ in range(4):
            assert bench.role_bracket_grid() == {}
    assert c.call_count == 1


def test_failed_build_is_retried_after_the_backoff(corpus):
    corpus([_row("T_1", lvl=10)])
    clock = [1000.0]
    with mock.patch.object(bench.time, "monotonic", lambda: clock[0], create=True):
        with mock.patch.object(bench.sqlite3, "connect",
                               side_effect=sqlite3.OperationalError("locked")):
            assert bench.role_bracket_grid() == {}
        clock[0] += 5.0
        assert bench.role_bracket_grid() == {}        # still backing off
        clock[0] += 120.0
        assert bench.role_bracket_grid()["mid"]["mid"]["n"] == 1


# --- F8: a stat error other than FileNotFoundError --------------------------------

class _DeniedPath:
    def stat(self):
        raise PermissionError("denied")

    def is_file(self):
        return True

    def __fspath__(self):
        return "denied.db"

    def __str__(self):
        return "denied.db"


def test_stat_permission_error_is_an_empty_grid(monkeypatch):
    bench._reset_cache()
    monkeypatch.setattr(bench, "REWIND_DB_PATH", _DeniedPath())
    try:
        assert bench.role_bracket_grid() == {}     # old: PermissionError
    finally:
        bench._reset_cache()


# --- F9: the cache never hands out its own dicts ---------------------------------

def test_returned_grid_is_a_private_copy(corpus):
    corpus([_row("T_1", lvl=10)])
    bench.role_bracket_grid()                 # miss: builds the cache
    first = bench.role_bracket_grid()         # hit: must still be a copy
    first["mid"]["mid"]["lvl"]["avg"] = 99.0
    first["mid"].pop("mid")
    first["junk"] = {}
    again = bench.role_bracket_grid()
    assert again["mid"]["mid"]["lvl"]["avg"] == 10.0
    assert "junk" not in again


# --- F10: normalize_role takes ASCII spellings only -------------------------------

@pytest.mark.parametrize("raw", [
    "mar\u212asman",        # KELVIN SIGN lower()s to "k"
    "\u3000mid",            # ideographic space strip()ped by str.strip
    "mid\u00a0",            # NBSP
    "\u0085top",            # NEL
    "mid\x1c",              # ASCII file separator (str.strip eats it)
    5, None, ["mid"], b"mid",
])
def test_normalize_role_refuses_non_ascii_and_non_str(raw):
    assert bench.normalize_role(raw) is None


class _Unittest(unittest.TestCase):
    """Keeps the module importable under plain unittest discovery."""

    def test_module_constants(self):
        self.assertEqual(bench.VALID_BRACKETS, ("early", "mid"))
