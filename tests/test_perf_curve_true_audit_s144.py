"""True-audit regression tests for core.perf_curve (s144 true-audit cycle 141).

Each test pins one weakness found in the audit (RM-1824..RM-1831). All of them
inject an in-memory sqlite via the conn= seam (or a tmp_path db file for the
open path), so they never touch the gitignored rewind_history.db.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from core import perf_curve
from dashboard import routes_perf_curve as rpc


def _db(path=":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE matches (
            match_id TEXT PRIMARY KEY,
            tracked_win INTEGER,
            tracked_champion_id INTEGER,
            tracked_team_id INTEGER,
            map_id INTEGER,
            has_stats INTEGER,
            game_duration_s INTEGER
        );
        CREATE TABLE participants (
            match_id TEXT,
            participant_id INTEGER,
            champion_id INTEGER,
            team_id INTEGER
        );
        CREATE TABLE timeline_frames (
            match_id TEXT,
            participant_id INTEGER,
            timestamp_ms INTEGER,
            total_gold INTEGER,
            minions_killed INTEGER,
            jungle_minions INTEGER
        );
        """
    )
    return conn


def _add_game(conn, mid, *, win, champ=64, frames=(), pid=3):
    """win is stored verbatim; frames = (timestamp_ms, gold, minions, jungle)."""
    conn.execute("INSERT INTO matches VALUES (?,?,?,?,?,?,?)",
                 (mid, win, champ, 100, 12, 1, 1200))
    conn.execute("INSERT INTO participants VALUES (?,?,?,?)",
                 (mid, pid, champ, 100))
    for ts, gold, minions, jungle in frames:
        conn.execute("INSERT INTO timeline_frames VALUES (?,?,?,?,?,?)",
                     (mid, pid, ts, gold, minions, jungle))


def _good(conn, n=5, *, win=1, gold=1000, prefix="G"):
    for i in range(n):
        _add_game(conn, f"{prefix}{i}", win=win,
                  frames=[(60000, gold, 30, 4)])


def _series(payload, minute, key):
    for row in payload["minutes"]:
        if row["minute"] == minute:
            return row[key]
    return "MISSING"


def _strict_json(payload) -> str:
    return json.dumps(payload, allow_nan=False)


# RM-1824: an unknown result (NULL, 2, text) was read as a LOSS.
@pytest.mark.parametrize("bad_win", [None, 2, "yes", -1])
def test_unknown_result_is_never_counted_as_a_loss(bad_win):
    conn = _db()
    _good(conn, win=1, gold=1000, prefix="W")
    _good(conn, win=0, gold=600, prefix="L")
    for i in range(5):
        _add_game(conn, f"U{i}", win=bad_win, frames=[(60000, 99999, 0, 0)])
    out = perf_curve.compute_perf_curve(mode="aram", metric="gold", conn=conn)
    assert _series(out, 1, "loss_n") == 5
    assert _series(out, 1, "loss_avg") == 600.0
    assert _series(out, 1, "win_n") == 5
    assert _series(out, 1, "win_avg") == 1000.0
    assert out["n_games"] == 10


# RM-1825: a champion id outside SQLite's 64-bit range raised
# OverflowError (not sqlite3.Error) out of a "never raises" function, and a
# junk champion raised ValueError / TypeError.
@pytest.mark.parametrize("bad_champ",
                         [2 ** 63, -(2 ** 63) - 1, "abc", True, 64.5,
                          float("nan"), float("inf"), [64], b"64"])
def test_unusable_champion_never_raises_and_matches_nothing(bad_champ):
    conn = _db()
    _good(conn)
    out = perf_curve.compute_perf_curve(mode="aram", champion=bad_champ,
                                        conn=conn)
    assert out["ok"] is True
    assert out["n_games"] == 0
    assert out["minutes"] == []
    assert out["champion"] is None
    _strict_json(out)


@pytest.mark.parametrize("champ", [64, 64.0, "64", " 64 "])
def test_integral_champion_forms_filter_and_echo_an_int(champ):
    conn = _db()
    _good(conn)
    _add_game(conn, "OTHER", win=1, champ=99, frames=[(60000, 1, 0, 0)])
    out = perf_curve.compute_perf_curve(mode="aram", champion=champ, conn=conn)
    assert out["n_games"] == 5
    assert out["champion"] == 64
    assert type(out["champion"]) is int


def test_route_huge_champion_is_not_a_500(monkeypatch, tmp_path):
    db = tmp_path / "rewind_history.db"
    conn = _db(str(db))
    _good(conn)
    conn.commit()
    conn.close()
    monkeypatch.setattr(perf_curve, "_REWIND_DB", db)
    rpc._reset_caches()

    class _H:
        path = "/api/perf-curve?champion=99999999999999999999"
        status = None
        body = None

        def _send(self, status, body, _ct):
            self.status, self.body = status, body

    h = _H()
    try:
        rpc._serve_perf_curve(h)
    finally:
        rpc._reset_caches()
    assert h.status == 200
    assert json.loads(h.body)["n_games"] == 0


# RM-1826: an unhashable mode / metric raised TypeError from the
# membership test instead of falling back to the default.
def test_unhashable_mode_and_metric_fall_back():
    conn = _db()
    _good(conn)
    out = perf_curve.compute_perf_curve(mode=[], metric={}, conn=conn)
    assert out["mode"] == perf_curve.DEFAULT_MODE
    assert out["metric"] == perf_curve.DEFAULT_METRIC
    assert _series(out, 1, "win_avg") == 1000.0


class _AlwaysEqual:
    """Compares equal to everything: tuple membership alone accepts it."""

    def __eq__(self, other):
        return True

    __hash__ = object.__hash__


def test_non_string_metric_never_echoes_into_the_payload():
    conn = _db()
    _good(conn)
    out = perf_curve.compute_perf_curve(mode="aram", metric=_AlwaysEqual(),
                                        conn=conn)
    assert out["metric"] == perf_curve.DEFAULT_METRIC
    assert type(out["metric"]) is str
    _strict_json(out)


# RM-1827: a non-numeric stored value raised ValueError out of float()
# and lost the whole curve; a junk cs operand silently read as 0.
@pytest.mark.parametrize("junk", ["abc", b"\x00\x01", "1e999x"])
def test_junk_gold_skips_the_frame_not_the_curve(junk):
    conn = _db()
    _good(conn)
    _add_game(conn, "JUNK", win=1, frames=[(60000, junk, 0, 0)])
    out = perf_curve.compute_perf_curve(mode="aram", metric="gold", conn=conn)
    assert _series(out, 1, "win_n") == 5
    assert _series(out, 1, "win_avg") == 1000.0


def test_junk_cs_operand_skips_the_frame_instead_of_reading_zero():
    conn = _db()
    _good(conn)  # 30 minions + 4 jungle at minute 1
    for i in range(5):
        _add_game(conn, f"J{i}", win=1, frames=[(60000, 0, "abc", 4)])
    out = perf_curve.compute_perf_curve(mode="aram", metric="cs", conn=conn)
    assert _series(out, 1, "win_n") == 5
    assert _series(out, 1, "win_avg") == 34.0


def test_null_cs_operand_still_reads_zero():
    conn = _db()
    for i in range(5):
        _add_game(conn, f"N{i}", win=1, frames=[(60000, 0, None, 4)])
    out = perf_curve.compute_perf_curve(mode="aram", metric="cs", conn=conn)
    assert _series(out, 1, "win_avg") == 4.0


# RM-1828: an infinite or overflowing stored value reached the payload as
# inf / nan, which json.dumps writes as a bare Infinity / NaN token that a
# browser JSON.parse rejects (the panel goes blank).
@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), 1e308, -1e308,
                                 1e13])
def test_non_finite_or_absurd_gold_never_reaches_the_payload(bad):
    conn = _db()
    _good(conn)
    for i in range(5):
        _add_game(conn, f"X{i}", win=1, frames=[(60000, bad, 0, 0)])
    out = perf_curve.compute_perf_curve(mode="aram", metric="gold", conn=conn)
    _strict_json(out)
    assert _series(out, 1, "win_avg") == 1000.0
    assert _series(out, 1, "win_n") == 5


def test_huge_cs_operands_never_reach_the_payload():
    conn = _db()
    _good(conn)
    for i in range(5):
        _add_game(conn, f"X{i}", win=1, frames=[(60000, 0, 1e308, 1e308)])
    out = perf_curve.compute_perf_curve(mode="aram", metric="cs", conn=conn)
    _strict_json(out)
    assert _series(out, 1, "win_avg") == 34.0


# RM-1829: a junk timestamp raised (ValueError on text, OverflowError on
# inf) and lost the whole curve.
@pytest.mark.parametrize("bad_ts", ["abc", float("inf"), float("-inf"),
                                    b"60000"])
def test_junk_timestamp_never_raises(bad_ts):
    conn = _db()
    _good(conn)
    _add_game(conn, "TS", win=1, frames=[(bad_ts, 5, 0, 0)])
    out = perf_curve.compute_perf_curve(mode="aram", metric="gold", conn=conn)
    assert _series(out, 1, "win_avg") == 1000.0
    _strict_json(out)


# RM-1830: a NULL timestamp was bucketed at minute 0 (int(None or 0)).
def test_null_timestamp_is_not_bucketed_at_minute_zero():
    conn = _db()
    for i in range(5):
        _add_game(conn, f"W{i}", win=1,
                  frames=[(None, 777, 0, 0), (60000, 1000, 0, 0)])
    out = perf_curve.compute_perf_curve(mode="aram", metric="gold", conn=conn)
    assert _series(out, 0, "win_avg") == "MISSING"
    assert _series(out, 1, "win_avg") == 1000.0


def test_fractional_timestamp_buckets_by_floor():
    conn = _db()
    for i in range(5):
        _add_game(conn, f"W{i}", win=1, frames=[(119999.5, 1000, 0, 0)])
    out = perf_curve.compute_perf_curve(mode="aram", metric="gold", conn=conn)
    assert _series(out, 1, "win_avg") == 1000.0


# RM-1831: the read-only URI was an f-string over the raw path, so a '#'
# (fragment) or '%' in the checkout path opened the wrong file and the curve
# went silently empty.
@pytest.mark.parametrize("dirname", ["a#b", "pct%41dir", "q?x"])
def test_db_path_with_uri_special_characters_still_opens(monkeypatch,
                                                         tmp_path, dirname):
    try:
        folder = tmp_path / dirname
        folder.mkdir()
    except OSError:
        pytest.skip("filesystem refuses this name")
    db = folder / "rewind_history.db"
    conn = _db(str(db))
    _good(conn)
    conn.commit()
    conn.close()
    monkeypatch.setattr(perf_curve, "_REWIND_DB", db)
    out = perf_curve.compute_perf_curve(mode="aram", metric="gold")
    assert out["n_games"] == 5
    assert _series(out, 1, "win_avg") == 1000.0


def test_owned_connection_is_read_only(monkeypatch, tmp_path):
    db = tmp_path / "rewind_history.db"
    conn = _db(str(db))
    conn.commit()
    conn.close()
    monkeypatch.setattr(perf_curve, "_REWIND_DB", db)
    ro = perf_curve._open_ro()
    try:
        with pytest.raises(sqlite3.OperationalError):
            ro.execute("CREATE TABLE t (x)")
    finally:
        ro.close()


def test_well_formed_payload_is_unchanged():
    conn = _db()
    for i in range(6):
        _add_game(conn, f"W{i}", win=1,
                  frames=[(0, 500, 0, 0), (60000, 1000 + i, 10, 2)])
    for i in range(5):
        _add_game(conn, f"L{i}", win=0,
                  frames=[(0, 500, 0, 0), (60000, 600, 6, 0)])
    out = perf_curve.compute_perf_curve(mode="aram", metric="gold", conn=conn)
    assert out == {
        "ok": True, "mode": "aram", "metric": "gold", "champion": None,
        "n_games": 11, "min_games_n": 5,
        "minutes": [
            {"minute": 0, "win_avg": 500.0, "win_n": 6,
             "loss_avg": 500.0, "loss_n": 5},
            {"minute": 1, "win_avg": 1002.5, "win_n": 6,
             "loss_avg": 600.0, "loss_n": 5},
        ],
    }
