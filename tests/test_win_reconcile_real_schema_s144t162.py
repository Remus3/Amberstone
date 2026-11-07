"""win_reconcile against the REAL postgame collector schema (RM-1946).

``agents/agent2_backend/win_reconcile.py`` copies the authoritative WIN /
LOSS from ``data/postgame_stats.db`` into the live-phase3 mode-DB rows. Its
query read ``captured_at`` off ``<mode>_player_stats``, but the collector
(``lcu/lcu_postgame_collector.py`` ``_MODES_SQL``) puts ``captured_at`` on
``<mode>_matches`` only. Every real query therefore raised "no such column",
the error was counted as an ordinary "no match", and the reconciler never
patched one row (measured read-only 2026-11-06: 103 of 103 live-phase3 rows
across aram / arena / sr_ranked still win IS NULL). The old suite never saw it
because its fixture invented a ``captured_at`` column on ``player_stats``.

Every test here builds the postgame DB from the collector's own DDL, so a
future schema drift on either side turns this file red instead of green.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import agents.agent2_backend.win_reconcile as wr
from agents.agent2_backend.db_schema import SCHEMA_STATEMENTS
from lcu.lcu_postgame_collector import _MODES_SQL

_ENDED = datetime(2026, 4, 22, 16, 0, tzinfo=timezone.utc)


def _collector_ts(dt: datetime) -> str:
    """The collector's captured_at format (lcu_postgame_collector.py)."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_postgame_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        for sql in _MODES_SQL.values():
            conn.executescript(sql)
        conn.commit()
    finally:
        conn.close()


def _make_mode_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        for stmt in SCHEMA_STATEMENTS:
            conn.execute(stmt)
        conn.commit()
    finally:
        conn.close()


_SEQ = {"n": 0}


def _add_postgame(
    pg: Path, champion: str, captured: datetime, result: str,
    *, mode: str = "ARAM", is_local: int = 1,
) -> None:
    _SEQ["n"] += 1
    mid = f"SYN-{_SEQ['n']}"
    tbl = mode.lower()
    conn = sqlite3.connect(pg)
    try:
        conn.execute(
            f"INSERT INTO {tbl}_matches (match_id, game_mode, captured_at)"
            " VALUES (?, ?, ?)",
            (mid, mode, _collector_ts(captured)),
        )
        conn.execute(
            f"INSERT INTO {tbl}_player_stats (match_id, game_mode,"
            " champion_name, team_result, is_local_player)"
            " VALUES (?, ?, ?, ?, ?)",
            (mid, mode, champion, result, is_local),
        )
        conn.commit()
    finally:
        conn.close()


def _add_live(db: Path, champion: str, ended_at: str | None) -> int:
    conn = sqlite3.connect(db)
    try:
        cur = conn.execute(
            "INSERT INTO matches (started_at, ended_at, champion,"
            " ally_champions, enemy_champions, duration_sec, win, source)"
            " VALUES ('2026-04-22T15:40:00+00:00', ?, ?, '[]', '[]', 1200,"
            " NULL, 'live-phase3')",
            (ended_at, champion),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def _win(db: Path, mid: int):
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            "SELECT win FROM matches WHERE match_id = ?", (mid,)
        ).fetchone()[0]
    finally:
        conn.close()


@pytest.fixture
def dbs(tmp_path: Path, monkeypatch) -> dict:
    mode_dir = tmp_path / "db"
    mode_dir.mkdir()
    aram = mode_dir / "aram.db"
    _make_mode_db(aram)
    pg = tmp_path / "postgame_stats.db"
    _make_postgame_db(pg)
    monkeypatch.setattr(wr, "MODE_DB_DIR", mode_dir)
    monkeypatch.setattr(wr, "POSTGAME_DB", pg)
    return {"aram": aram, "pg": pg, "dir": mode_dir}


def test_collector_schema_keeps_captured_at_on_matches_only() -> None:
    """Pins the premise: a collector change that moves the column re-opens
    the join in win_reconcile."""
    ddl = _MODES_SQL["ARAM"]
    ps = ddl.split("CREATE TABLE IF NOT EXISTS aram_player_stats", 1)[1]
    ps = ps.split(");", 1)[0]
    assert "captured_at" not in ps
    m = ddl.split("CREATE TABLE IF NOT EXISTS aram_matches", 1)[1]
    assert "captured_at" in m.split(");", 1)[0]


def test_patches_win_against_real_collector_schema(dbs: dict) -> None:
    mid = _add_live(dbs["aram"], "Ahri", _ENDED.isoformat())
    _add_postgame(dbs["pg"], "Ahri", _ENDED + timedelta(seconds=30), "WIN")
    out = wr.reconcile_mode("aram")
    assert out["patched"] == 1, out
    assert _win(dbs["aram"], mid) == 1


def test_loss_against_real_collector_schema(dbs: dict) -> None:
    mid = _add_live(dbs["aram"], "Ahri", _ENDED.isoformat())
    _add_postgame(dbs["pg"], "Ahri", _ENDED + timedelta(seconds=30), "LOSS")
    wr.reconcile_mode("aram")
    assert _win(dbs["aram"], mid) == 0


def test_query_error_is_counted_and_logged_not_read_as_no_match(
    dbs: dict, caplog,
) -> None:
    conn = sqlite3.connect(dbs["pg"])
    try:
        conn.execute("DROP TABLE aram_player_stats")
        conn.commit()
    finally:
        conn.close()
    _add_live(dbs["aram"], "Ahri", _ENDED.isoformat())
    with caplog.at_level(logging.WARNING, logger="agent2.win_reconcile"):
        out = wr.reconcile_mode("aram")
    assert out["skipped_error"] == 1, out
    assert out["skipped_no_match"] == 0, out
    assert any("postgame query error" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("ended", [None, "", "not-a-date"])
def test_unparseable_ended_at_never_matches_a_game_played_now(
    dbs: dict, ended,
) -> None:
    """The old fallback used datetime.now(), so an old row with a bad
    ended_at took the result of whatever game was being played NOW."""
    mid = _add_live(dbs["aram"], "Ahri", ended)
    now = datetime.now(timezone.utc)
    _add_postgame(dbs["pg"], "Ahri", now, "WIN")
    out = wr.reconcile_mode("aram")
    assert out["patched"] == 0, out
    assert out["skipped_bad_ended_at"] == 1, out
    assert _win(dbs["aram"], mid) is None


def test_non_utc_offset_ended_at_is_windowed_in_utc(dbs: dict) -> None:
    """The SQL prefilter compared strings, so a -08:00 ended_at put the
    window eight hours away from the collector's UTC captured_at."""
    local = _ENDED.astimezone(timezone(timedelta(hours=-8)))
    mid = _add_live(dbs["aram"], "Ahri", local.isoformat())
    _add_postgame(dbs["pg"], "Ahri", _ENDED + timedelta(seconds=30), "WIN")
    out = wr.reconcile_mode("aram")
    assert out["patched"] == 1, out
    assert _win(dbs["aram"], mid) == 1


def test_outside_window_is_not_matched(dbs: dict) -> None:
    mid = _add_live(dbs["aram"], "Ahri", _ENDED.isoformat())
    _add_postgame(dbs["pg"], "Ahri", _ENDED + timedelta(seconds=601), "WIN")
    out = wr.reconcile_mode("aram")
    assert out["patched"] == 0
    assert _win(dbs["aram"], mid) is None


def test_non_local_player_row_is_not_matched(dbs: dict) -> None:
    mid = _add_live(dbs["aram"], "Ahri", _ENDED.isoformat())
    _add_postgame(
        dbs["pg"], "Ahri", _ENDED + timedelta(seconds=30), "WIN", is_local=0,
    )
    out = wr.reconcile_mode("aram")
    assert out["patched"] == 0
    assert _win(dbs["aram"], mid) is None


def test_connections_are_closed(dbs: dict, monkeypatch) -> None:
    """sqlite3's own context manager commits but never closes, so every
    idle cycle of the supervisor left two handles open."""
    opened: list[sqlite3.Connection] = []
    real = sqlite3.connect

    def _track(*a, **k):
        c = real(*a, **k)
        opened.append(c)
        return c

    _add_live(dbs["aram"], "Ahri", _ENDED.isoformat())
    _add_postgame(dbs["pg"], "Ahri", _ENDED + timedelta(seconds=30), "WIN")
    monkeypatch.setattr(wr.sqlite3, "connect", _track)
    out = wr.reconcile_mode("aram")
    monkeypatch.undo()
    assert out["patched"] == 1, out
    assert len(opened) == 2
    for c in opened:
        with pytest.raises(sqlite3.ProgrammingError):
            c.execute("SELECT 1")


def test_postgame_path_with_uri_metacharacter(
    tmp_path: Path, monkeypatch,
) -> None:
    """``f"file:{path}?mode=ro"`` cut the path at a '#'."""
    mode_dir = tmp_path / "db"
    mode_dir.mkdir()
    aram = mode_dir / "aram.db"
    _make_mode_db(aram)
    pg_dir = tmp_path / "pg#dir"
    pg_dir.mkdir()
    pg = pg_dir / "postgame_stats.db"
    _make_postgame_db(pg)
    monkeypatch.setattr(wr, "MODE_DB_DIR", mode_dir)
    monkeypatch.setattr(wr, "POSTGAME_DB", pg)
    mid = _add_live(aram, "Ahri", _ENDED.isoformat())
    _add_postgame(pg, "Ahri", _ENDED + timedelta(seconds=30), "WIN")
    out = wr.reconcile_mode("aram")
    assert out.get("patched") == 1, out
    assert _win(aram, mid) == 1


def test_error_mid_batch_reports_the_rollback_not_phantom_patches(
    dbs: dict,
) -> None:
    """An sqlite error after one UPDATE rolls the batch back; the summary
    used to claim the rolled-back rows as patched."""
    first = _add_live(dbs["aram"], "Ahri", _ENDED.isoformat())
    second = _add_live(dbs["aram"], "Lux", _ENDED.isoformat())
    _add_postgame(dbs["pg"], "Ahri", _ENDED + timedelta(seconds=30), "WIN")
    _add_postgame(dbs["pg"], "Lux", _ENDED + timedelta(seconds=40), "LOSS")
    conn = sqlite3.connect(dbs["aram"])
    try:
        conn.execute(
            "CREATE TRIGGER boom BEFORE UPDATE OF win ON matches"
            " WHEN NEW.champion = 'Lux' BEGIN"
            " SELECT RAISE(ABORT, 'synthetic failure'); END"
        )
        conn.commit()
    finally:
        conn.close()
    out = wr.reconcile_mode("aram")
    assert "error" in out, out
    assert out["patched"] == 0, out
    assert out["rolled_back"] is True, out
    assert _win(dbs["aram"], first) is None
    assert _win(dbs["aram"], second) is None


@pytest.mark.parametrize("bad", [None, 7, ["aram"], {"m": 1}])
def test_junk_mode_is_skipped_not_raised(bad) -> None:
    out = wr.reconcile_mode(bad)
    assert out["skipped"] is True
    assert out["reason"] == "no postgame mapping"
