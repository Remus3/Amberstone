"""S144-P-346 - the three temporal analyses close the mode database they open.

``with sqlite3.connect(p) as conn:`` only COMMITS on exit; it never closes (measured on Python 3.14 / SQLite 3.50:
ResourceWarning "unclosed database", and on Windows the file stays locked until the connection object is collected, so
a mode DB cannot be replaced or removed while the traceback of a raise from inside the loop is alive). The three
analyses back ``GET /api/digest`` and the coach hint, which run on a timer, so each call left one open handle per mode.
They now hold the connection under ``contextlib.closing``.
"""
from __future__ import annotations

import sqlite3
import types

import pytest

from coaches import adaptation_hint
from coaches import adaptation_hint_temporal as tmod

_CALLS = (
    ("time_of_day_analysis", {}),
    ("duration_analysis", {}),
    ("day_of_week_analysis", {}),
)


def _make_db(path):
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE matches (match_id INTEGER PRIMARY KEY, started_at TEXT, win INTEGER, "
            "duration_sec INTEGER, champion TEXT, kills INTEGER, deaths INTEGER, assists INTEGER)"
        )
        for i in range(4):
            conn.execute(
                "INSERT INTO matches VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (i, f"2026-10-0{i + 1}T12:00:00Z", i % 2, 1500 + i * 400, "Jinx", 5, 2, 7),
            )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def tracked(tmp_path, monkeypatch):
    _make_db(tmp_path / "aram.db")
    monkeypatch.setattr(adaptation_hint, "DB_DIR", tmp_path)
    opened: list[sqlite3.Connection] = []
    closed: list[sqlite3.Connection] = []

    class Rec(sqlite3.Connection):
        def close(self):
            closed.append(self)
            super().close()

    def connect(*args, **kwargs):
        conn = sqlite3.connect(*args, factory=Rec, **kwargs)
        opened.append(conn)
        return conn

    shim = types.SimpleNamespace(connect=connect, Row=sqlite3.Row, Error=sqlite3.Error)
    monkeypatch.setattr(tmod, "sqlite3", shim)
    return opened, closed


@pytest.mark.parametrize(("name", "kwargs"), _CALLS)
def test_each_analysis_closes_the_connection_it_opens(tracked, name, kwargs):
    opened, closed = tracked
    out = getattr(tmod, name)(mode="aram", **kwargs)
    assert len(opened) == 1, "the analysis never opened the fixture DB, so a close assertion would prove nothing"
    assert closed == opened
    assert out["total_games"] == 4


@pytest.mark.parametrize(("name", "kwargs"), _CALLS)
def test_a_raise_from_inside_the_read_still_closes_the_connection(tracked, monkeypatch, name, kwargs):
    opened, closed = tracked
    # A matches table that vanished makes the SELECT raise sqlite3.Error inside the with block; the handle must still close.
    conn = sqlite3.connect(tmod._db("aram"))
    try:
        conn.execute("DROP TABLE matches")
        conn.commit()
    finally:
        conn.close()
    out = getattr(tmod, name)(mode="aram", **kwargs)
    assert out["total_games"] == 0
    assert len(opened) == 1 and closed == opened


def test_the_database_file_can_be_replaced_right_after_a_call(tracked, tmp_path):
    """On Windows an open handle makes the replace fail; elsewhere it is a plain regression check."""
    tmod.time_of_day_analysis(mode="aram")
    target = tmp_path / "aram.db"
    spare = tmp_path / "spare.db"
    _make_db(spare)
    spare.replace(target)
    assert target.exists()
