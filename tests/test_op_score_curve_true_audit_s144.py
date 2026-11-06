"""True-audit regression tests for core.op_score_curve (s144 true-audit cycle 142).

Each test pins one weakness found in the audit (RM-1832..RM-1838). All of them
inject an in-memory sqlite via the conn= seam (or a tmp_path db file for the
open path), so they never touch the gitignored rewind_history.db.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from core import op_score_curve
from dashboard import routes_op_score as ros


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
            xp INTEGER,
            minions_killed INTEGER,
            jungle_minions INTEGER,
            total_dmg_done INTEGER
        );
        """
    )
    return conn


def _add_game(conn, mid, *, win, champ=64, frames=(), pid=3):
    """win is stored verbatim; frames = (ts_ms, gold, xp, minions, jungle, dmg)."""
    conn.execute("INSERT INTO matches VALUES (?,?,?,?,?,?,?)",
                 (mid, win, champ, 100, 12, 1, 1200))
    conn.execute("INSERT INTO participants VALUES (?,?,?,?)",
                 (mid, pid, champ, 100))
    for frame in frames:
        conn.execute("INSERT INTO timeline_frames VALUES (?,?,?,?,?,?,?,?)",
                     (mid, pid) + tuple(frame))


_FULL = (60000, 1000, 1000, 30, 4, 1000)


def _good(conn, n=5, *, win=1, frame=_FULL, prefix="G"):
    for i in range(n):
        _add_game(conn, f"{prefix}{i}", win=win, frames=[frame])


def _series(payload, minute, key):
    for row in payload["minutes"]:
        if row["minute"] == minute:
            return row[key]
    return "MISSING"


def _strict_json(payload) -> str:
    return json.dumps(payload, allow_nan=False)


def _run(conn, **kw):
    return op_score_curve.compute_op_score_curve(mode="aram", conn=conn, **kw)


# RM-1832: an unknown result (NULL, 2, text) was read as a LOSS via
# bool(), and its frames also set the per-minute normalization baseline.
@pytest.mark.parametrize("bad_win", [None, 2, "yes", -1])
def test_unknown_result_is_never_counted_as_a_loss(bad_win):
    conn = _db()
    _good(conn, win=1, prefix="W")
    _good(conn, win=0, frame=(60000, 500, 1000, 30, 4, 1000), prefix="L")
    for i in range(5):
        _add_game(conn, f"U{i}", win=bad_win,
                  frames=[(60000, 99999, 99999, 999, 99, 99999)])
    out = _run(conn)
    assert out["n_games"] == 10
    assert _series(out, 1, "win_n") == 5
    assert _series(out, 1, "loss_n") == 5
    # The unknown games do not define the baseline: the won games still max
    # every stat (100) and the lost games are at half gold only.
    assert _series(out, 1, "win_avg") == 100.0
    assert _series(out, 1, "loss_avg") == round(
        100.0 - 50.0 * op_score_curve.W_GOLD, 1)


# RM-1833: a champion id outside SQLite's 64-bit range raised
# OverflowError (not sqlite3.Error) out of a "never raises" function, a junk
# champion raised ValueError / TypeError, and the raw value was echoed (bytes
# then broke json.dumps in the route).
@pytest.mark.parametrize("bad_champ",
                         [2 ** 63, -(2 ** 63) - 1, "abc", True, 64.5,
                          float("nan"), float("inf"), [64], b"64",
                          "9" * 5000])
def test_unusable_champion_never_raises_and_matches_nothing(bad_champ):
    conn = _db()
    _good(conn)
    out = _run(conn, champion=bad_champ)
    assert out["ok"] is True
    assert out["n_games"] == 0
    assert out["minutes"] == []
    assert out["champion"] is None
    _strict_json(out)


@pytest.mark.parametrize("champ", [64, 64.0, "64", " 64 "])
def test_integral_champion_forms_filter_and_echo_an_int(champ):
    conn = _db()
    _good(conn)
    _add_game(conn, "OTHER", win=1, champ=99, frames=[_FULL])
    out = _run(conn, champion=champ)
    assert out["n_games"] == 5
    assert out["champion"] == 64
    assert type(out["champion"]) is int


def test_route_huge_champion_is_not_a_500(monkeypatch, tmp_path):
    db = tmp_path / "rewind_history.db"
    conn = _db(str(db))
    _good(conn)
    conn.commit()
    conn.close()
    monkeypatch.setattr(op_score_curve, "_REWIND_DB", db)
    ros._reset_caches()

    class _H:
        path = "/api/op-score-curve?champion=99999999999999999999"
        status = None
        body = None

        def _send(self, status, body, _ct):
            self.status, self.body = status, body

    h = _H()
    try:
        ros._serve_op_score(h)
    finally:
        ros._reset_caches()
    assert h.status == 200
    assert json.loads(h.body)["n_games"] == 0


# RM-1834: an unhashable mode raised TypeError from the membership test
# instead of falling back to the default.
@pytest.mark.parametrize("bad_mode", [[], {}, None, 12])
def test_unusable_mode_falls_back(bad_mode):
    conn = _db()
    _good(conn)
    out = op_score_curve.compute_op_score_curve(mode=bad_mode, conn=conn)
    assert out["mode"] == op_score_curve.DEFAULT_MODE
    assert _series(out, 1, "win_avg") == 100.0


# RM-1835: a non-numeric stored stat raised ValueError out of float() and
# lost the whole curve (the route answered 500); a junk cs operand silently
# read as 0 in the SQL arithmetic.
@pytest.mark.parametrize("col", [1, 2, 5])
@pytest.mark.parametrize("junk", ["abc", b"\x00\x01", "1e999x"])
def test_junk_stat_skips_the_frame_not_the_curve(junk, col):
    conn = _db()
    _good(conn)
    frame = list(_FULL)
    frame[col] = junk
    _add_game(conn, "JUNK", win=1, frames=[tuple(frame)])
    out = _run(conn)
    assert out["n_games"] == 6
    assert _series(out, 1, "win_n") == 5
    assert _series(out, 1, "win_avg") == 100.0


@pytest.mark.parametrize("col", [3, 4])
def test_junk_cs_operand_skips_the_frame_instead_of_reading_zero(col):
    conn = _db()
    _good(conn, prefix="W")
    frame = list(_FULL)
    frame[col] = "abc"
    for i in range(5):
        _add_game(conn, f"J{i}", win=0, frames=[tuple(frame)])
    out = _run(conn)
    assert _series(out, 1, "loss_avg") is None
    assert _series(out, 1, "loss_n") == 0


def test_null_stats_still_read_zero():
    # Historical contract kept: a NULL stat reads 0 (a NULL cs operand is the
    # documented COALESCE). Only the gold term is NULL here, so the composite
    # loses exactly the gold weight.
    conn = _db()
    _good(conn, prefix="W")
    for i in range(5):
        _add_game(conn, f"N{i}", win=0,
                  frames=[(60000, None, 1000, None, 34, 1000)])
    out = _run(conn)
    assert _series(out, 1, "loss_avg") == round(
        100.0 - 100.0 * op_score_curve.W_GOLD, 1)


# RM-1836: an infinite or absurd stored stat became the per-minute
# normalization max, so every real game's stat at that minute read as 0 and
# the whole minute's score collapsed.
@pytest.mark.parametrize("col", [1, 2, 3, 5])
@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), 1e308, 1e13])
def test_non_finite_or_absurd_stat_never_sets_the_baseline(bad, col):
    conn = _db()
    _good(conn)
    frame = list(_FULL)
    frame[col] = bad
    for i in range(5):
        _add_game(conn, f"X{i}", win=0, frames=[tuple(frame)])
    out = _run(conn)
    _strict_json(out)
    assert _series(out, 1, "win_avg") == 100.0
    assert _series(out, 1, "win_n") == 5
    assert _series(out, 1, "loss_n") == 0


# RM-1837: a junk timestamp raised (ValueError on text, OverflowError on
# inf) and lost the whole curve; a NULL timestamp was bucketed at minute 0.
# (A text "60000" is not listed: INTEGER affinity stores it as the int 60000,
# a well-formed row. A BLOB keeps its bytes, and int(b"60000") used to accept
# it.)
@pytest.mark.parametrize("bad_ts", ["abc", float("inf"), float("-inf"),
                                    b"60000"])
def test_junk_timestamp_never_raises(bad_ts):
    conn = _db()
    _good(conn)
    _add_game(conn, "TS", win=1, frames=[(bad_ts, 5, 5, 0, 0, 5)])
    out = _run(conn)
    assert _series(out, 1, "win_avg") == 100.0
    _strict_json(out)


def test_null_timestamp_is_not_bucketed_at_minute_zero():
    conn = _db()
    for i in range(5):
        _add_game(conn, f"W{i}", win=1,
                  frames=[(None, 777, 777, 7, 0, 777), _FULL])
    out = _run(conn)
    assert _series(out, 0, "win_avg") == "MISSING"
    assert _series(out, 1, "win_avg") == 100.0


def test_fractional_timestamp_buckets_by_floor():
    conn = _db()
    _good(conn, frame=(119999.5, 1000, 1000, 30, 4, 1000))
    out = _run(conn)
    assert _series(out, 1, "win_avg") == 100.0


# RM-1838: the read-only URI was an f-string over the raw path, so a '#'
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
    monkeypatch.setattr(op_score_curve, "_REWIND_DB", db)
    out = op_score_curve.compute_op_score_curve(mode="aram")
    assert out["n_games"] == 5
    assert _series(out, 1, "win_avg") == 100.0


def test_owned_connection_is_read_only(monkeypatch, tmp_path):
    db = tmp_path / "rewind_history.db"
    conn = _db(str(db))
    conn.commit()
    conn.close()
    monkeypatch.setattr(op_score_curve, "_REWIND_DB", db)
    ro = op_score_curve._open_ro()
    try:
        with pytest.raises(sqlite3.OperationalError):
            ro.execute("CREATE TABLE t (x)")
    finally:
        ro.close()


def test_well_formed_payload_is_unchanged():
    # Literal captured from the PRE-audit module on this fixture: well-formed
    # rows (NULL stats included) must give a byte-identical payload.
    conn = _db()
    for i in range(6):
        _add_game(conn, f"W{i}", win=1,
                  frames=[(0, 500, 300, 0, 0, 100),
                          (60000, 1000 + i, 900, 10 + i, 2, 2000 - i * 7),
                          (120000, 1800, 1500, 20, None, 4000)])
    for i in range(5):
        _add_game(conn, f"L{i}", win=0,
                  frames=[(0, 500, 300, 0, 0, 100),
                          (60000, 600 + i * 3, 700, 6, 0, 900),
                          (120000, None, 1400, 15, 1, 3100 + i)])
    out = _run(conn)
    assert _strict_json(out) == _WELL_FORMED_JSON


_WELL_FORMED_JSON = (
    '{"ok": true, "mode": "aram", "metric": "opscore", "champion": null, '
    '"n_games": 11, "min_games_n": 5, "weights": {"gold": 0.35, "xp": 0.2, '
    '"cs": 0.2, "combat": 0.25}, "minutes": [{"minute": 0, "win_avg": 80.0, '
    '"win_n": 6, "loss_avg": 80.0, "loss_n": 5}, {"minute": 1, '
    '"win_avg": 96.8, "win_n": 6, "loss_avg": 55.0, "loss_n": 5}, '
    '{"minute": 2, "win_avg": 100.0, "win_n": 6, "loss_avg": 54.1, '
    '"loss_n": 5}], "arc": {"win": null, "loss": null}}'
)
