"""RM-611 (X-11, external reference E): retain the raw League documents the
post-game collector already fetches, gzipped, in a ``raw_documents`` table.

Probe (2026-10-04, before a line was written):
  * ``git grep raw_documents`` / ``DERIVE_VERSION`` was empty outside BACKLOG.
  * ``lcu/lcu_postgame_collector.py`` fetched the EOG stats block
    (``_fetch_eog_stats_block``), the match-history game entry
    (``_capture_via_history``) and the LCU timeline (``_try_fetch_timeline``)
    and threw every document away after parsing; only per-player
    ``raw_stats_json`` survived. The timeline in particular was discarded
    whole whenever it held zero ITEM_* events, which RM-106a measured is the
    permanent case.
  * The table lives in ``data/postgame_stats.db`` (``_DB_PATH``, gitignored by
    ``**/*.db``) because raw documents name nine other players.

Contract pinned here: additive table, gzip body, one row per (match, kind),
first capture wins, NO new network calls, and a raw-store failure never costs
the capture it rides on.
"""
from __future__ import annotations

import gzip
import json
import sqlite3

import pytest

from core import raw_documents as rd


def _conn(path):
    return sqlite3.connect(str(path))


# ------------------------------------------------------------ the store

def test_round_trip_is_lossless_and_body_is_gzip(tmp_path):
    doc = {"gameId": 9001, "teams": [{"teamId": 100, "players": []}]}
    conn = _conn(tmp_path / "x.db")
    try:
        rd.ensure_schema(conn)
        assert rd.store(conn, "9001", "eog", doc) is True
        body = conn.execute(
            "SELECT body FROM raw_documents WHERE match_id='9001'").fetchone()[0]
        assert bytes(body[:2]) == b"\x1f\x8b", "body must be gzip"
        assert json.loads(gzip.decompress(body)) == doc
        assert rd.load(conn, "9001", "eog") == doc
        assert rd.load(conn, "9001", "timeline") is None
    finally:
        conn.close()


def test_schema_columns_are_exactly_the_specified_four(tmp_path):
    conn = _conn(tmp_path / "x.db")
    try:
        rd.ensure_schema(conn)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(raw_documents)")]
        assert cols == ["match_id", "kind", "fetched_at", "body"]
    finally:
        conn.close()


def test_first_capture_wins_and_a_repeat_is_a_noop(tmp_path):
    conn = _conn(tmp_path / "x.db")
    try:
        rd.ensure_schema(conn)
        assert rd.store(conn, "M1", "timeline", {"v": 1}) is True
        assert rd.store(conn, "M1", "timeline", {"v": 2}) is False
        assert rd.load(conn, "M1", "timeline") == {"v": 1}
        n = conn.execute("SELECT COUNT(*) FROM raw_documents").fetchone()[0]
        assert n == 1
    finally:
        conn.close()


def test_unknown_kind_and_empty_match_id_are_refused(tmp_path):
    conn = _conn(tmp_path / "x.db")
    try:
        rd.ensure_schema(conn)
        with pytest.raises(ValueError):
            rd.store(conn, "M1", "replay", {})
        with pytest.raises(ValueError):
            rd.store(conn, "", "eog", {})
    finally:
        conn.close()


def test_kinds_for_lists_what_is_held(tmp_path):
    conn = _conn(tmp_path / "x.db")
    try:
        rd.ensure_schema(conn)
        rd.store(conn, "M1", "timeline", {})
        rd.store(conn, "M1", "eog", {})
        rd.store(conn, "M2", "match", {})
        assert rd.kinds_for(conn, "M1") == ["eog", "timeline"]
    finally:
        conn.close()


# ------------------------------------------------- the collector writes it

@pytest.fixture()
def pgc(tmp_path, monkeypatch):
    import lcu.lcu_postgame_collector as mod
    monkeypatch.setattr(mod, "_DB_PATH", tmp_path / "pg.db")
    mod._ensure_schema()
    return mod


def _bare_collector(mod):
    c = mod.PostgameCollector.__new__(mod.PostgameCollector)
    c._trigger_at = None
    c.calls = []
    return c


_EOG = {"gameId": 4242, "gameMode": "CLASSIC", "gameLength": 1500,
        "teams": [{"teamId": 100, "win": "Win", "players": [
            {"championName": "Ashe", "stats": {}}]}]}
_TIMELINE = {"frames": [{"timestamp": 0, "events": [
    {"type": "CHAMPION_KILL", "timestamp": 61000, "killerId": 1,
     "victimId": 6}]}]}


def test_schema_is_created_by_the_collector(pgc, tmp_path):
    conn = _conn(tmp_path / "pg.db")
    try:
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "raw_documents" in names
    finally:
        conn.close()


def test_eog_capture_retains_eog_and_timeline_with_no_new_fetch(pgc, tmp_path):
    c = _bare_collector(pgc)
    c._fetch_eog_stats_block = lambda: dict(_EOG)
    c._publish_game_end_pin = lambda *a, **k: None

    def _status(path):
        c.calls.append(path)
        return (200, _TIMELINE)
    c._lcu_get_status = _status
    c._lcu_get = lambda path: c.calls.append(path)

    assert c._capture("CLASSIC") is True
    # The ONLY fetch is the one the collector already made (RM-107 route).
    assert c.calls == [pgc._TIMELINE_PATH.format(game_id="4242")]
    conn = _conn(tmp_path / "pg.db")
    try:
        assert rd.kinds_for(conn, "4242") == ["eog", "timeline"]
        assert rd.load(conn, "4242", "eog") == _EOG
        assert rd.load(conn, "4242", "timeline") == _TIMELINE
    finally:
        conn.close()


def test_timeline_non_200_retains_no_timeline_row(pgc, tmp_path):
    c = _bare_collector(pgc)
    c._fetch_eog_stats_block = lambda: dict(_EOG)
    c._publish_game_end_pin = lambda *a, **k: None
    c._lcu_get_status = lambda path: (404, None)
    c._capture("CLASSIC")
    conn = _conn(tmp_path / "pg.db")
    try:
        assert rd.kinds_for(conn, "4242") == ["eog"]
    finally:
        conn.close()


def test_history_fallback_retains_the_match_document(pgc, tmp_path):
    game = {"gameId": 5151, "gameMode": "ARAM", "gameDuration": 1100,
            "gameCreation": 1, "participants": [], "participantIdentities": [],
            "teams": []}
    c = _bare_collector(pgc)
    c._publish_game_end_pin = lambda *a, **k: None

    def _get(path):
        c.calls.append(path)
        if path.startswith("/lol-summoner/"):
            return {"puuid": "p-synthetic"}
        return {"games": {"games": [game]}}
    c._lcu_get = _get
    assert c._capture_via_history("ARAM") is True
    assert len(c.calls) == 2, "no new network call may be added"
    conn = _conn(tmp_path / "pg.db")
    try:
        assert rd.kinds_for(conn, "5151") == ["match"]
        assert rd.load(conn, "5151", "match") == game
    finally:
        conn.close()


def test_a_raw_store_failure_never_costs_the_capture(pgc, tmp_path, monkeypatch):
    def _boom(*a, **k):
        raise sqlite3.OperationalError("disk I/O error")
    monkeypatch.setattr(rd, "store", _boom)
    c = _bare_collector(pgc)
    c._fetch_eog_stats_block = lambda: dict(_EOG)
    c._publish_game_end_pin = lambda *a, **k: None
    c._lcu_get_status = lambda path: (200, _TIMELINE)
    assert c._capture("CLASSIC") is True
    conn = _conn(tmp_path / "pg.db")
    try:
        rows = conn.execute("SELECT match_id FROM sr_matches").fetchall()
        assert rows == [("4242",)], "the parsed capture must still land"
    finally:
        conn.close()
