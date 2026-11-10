"""Hardening tests for core.snowball_elasticity (s144 true-audit, S144-T-694).

The route that serves this module (dashboard/routes_snowball_elasticity.py)
turns any exception into a 500, and the module docstring promises it never
raises. These tests pin the defects found in the audit:

* an unknown result (tracked_win NULL, 2, text) was read as a LOSS
  (``int(win or 0)``) or raised ValueError (text) - now skipped (RM-610
  resolved-result rule, mirroring core.duration_winrate._as_result);
* a junk tracked_team_id (text, bytes) raised from ``int(team)``;
* a team whose total_gold is all NULL made ``None - int`` raise TypeError;
  an infinite REAL made ``int(inf)`` raise OverflowError; a text gold value
  was summed by SQLite as 0 and silently produced a wrong differential;
* an int64-overflowing SUM raised "integer overflow" and dropped EVERY match
  of that checkpoint, not just the junk one;
* the nearest frame was used even when one side's roster was incomplete or a
  participant row was duplicated (frames or participants), so the team sums
  compared 4 players against 5 or double-counted one player;
* the tracked-meta cache was stored on the connection: inert on a plain
  sqlite3.Connection (no __dict__, so the matches table was re-read per
  checkpoint) and STALE across calls on a connection subclass;
* the read-only URI was an f-string, so a '#' in the checkout path truncated
  it and the real db was never opened (core.duration_winrate fixed the same
  defect with Path.as_uri).

Every test injects an in-memory db (or a tmp_path db) - no real data.
"""
import math
import sqlite3

import pytest

from core import snowball_elasticity as se


def _conn(matches, participants, frames, factory=sqlite3.Connection,
          path=":memory:"):
    c = sqlite3.connect(path, factory=factory)
    c.execute("CREATE TABLE matches (match_id TEXT, map_id INTEGER, "
              "has_timeline INTEGER, tracked_team_id INTEGER, "
              "tracked_win INTEGER)")
    c.execute("CREATE TABLE participants (match_id TEXT, "
              "participant_id INTEGER, team_id INTEGER)")
    c.execute("CREATE TABLE timeline_frames (match_id TEXT, "
              "timestamp_ms INTEGER, participant_id INTEGER, "
              "total_gold INTEGER)")
    c.executemany("INSERT INTO matches VALUES (?,?,?,?,?)", matches)
    c.executemany("INSERT INTO participants VALUES (?,?,?)", participants)
    c.executemany("INSERT INTO timeline_frames VALUES (?,?,?,?)", frames)
    c.commit()
    return c


def _parts(mid):
    return ([(mid, pid, 100) for pid in range(1, 6)]
            + [(mid, pid, 200) for pid in range(6, 11)])


def _frames(mid, ts, tracked_each, enemy_each, tracked_team=100):
    out = []
    for pid in range(1, 11):
        team = 100 if pid <= 5 else 200
        out.append((mid, ts, pid,
                    tracked_each if team == tracked_team else enemy_each))
    return out


def _game(mid, win, diff=3000, ts=600_000, tracked_team=100):
    """One SR match whose tracked-team lead is ``diff`` at ``ts``."""
    m = [(mid, 11, 1, tracked_team, win)]
    return m, _parts(mid), _frames(mid, ts, 1000 + diff // 5, 1000,
                                   tracked_team)


def _build(games, factory=sqlite3.Connection, path=":memory:"):
    ms, ps, fs = [], [], []
    for m, p, f in games:
        ms += m
        ps += p
        fs += f
    return _conn(ms, ps, fs, factory=factory, path=path)


def _bucket(out, key, label):
    cp = next(c for c in out["checkpoints"] if c["key"] == key)
    return {b["label"]: b for b in cp["buckets"]}[label]


def _n(out, key="10min"):
    return next(c for c in out["checkpoints"] if c["key"] == key)["n"]


# -- unknown results -------------------------------------------------------

def test_null_and_out_of_range_result_is_skipped_not_a_loss():
    games = [_game(f"w{i}", 1) for i in range(5)]
    games += [_game("unk_null", None), _game("unk_two", 2)]
    out = se.compute_snowball_elasticity(conn=_build(games))
    b = _bucket(out, "10min", "ahead_big")
    assert b["games"] == 5
    assert b["wins"] == 5
    assert b["winrate"] == 100.0


def test_text_result_does_not_raise_and_is_skipped():
    games = [_game(f"w{i}", 1) for i in range(5)] + [_game("txt", "Win")]
    out = se.compute_snowball_elasticity(conn=_build(games))
    assert out["ok"] is True
    assert _bucket(out, "10min", "ahead_big")["games"] == 5


# -- junk tracked team -----------------------------------------------------

def test_junk_tracked_team_does_not_raise_and_is_skipped():
    games = [_game(f"w{i}", 1) for i in range(5)]
    games.append(([("tteam", 11, 1, "blue", 1)], _parts("tteam"),
                  _frames("tteam", 600_000, 1600, 1000)))
    games.append(([("bteam", 11, 1, b"\x01", 1)], _parts("bteam"),
                  _frames("bteam", 600_000, 1600, 1000)))
    out = se.compute_snowball_elasticity(conn=_build(games))
    assert out["ok"] is True
    assert _n(out) == 5


def test_bool_like_team_one_is_not_a_team():
    # Characterization pin (passes on the old code too): a tracked_team_id
    # of 1 (a bool stored as int) is neither side and never counts.
    games = [_game(f"w{i}", 1) for i in range(5)]
    games.append(([("one", 11, 1, 1, 1)], _parts("one"),
                  _frames("one", 600_000, 1600, 1000)))
    out = se.compute_snowball_elasticity(conn=_build(games))
    assert _n(out) == 5


# -- junk gold -------------------------------------------------------------

def test_all_null_team_gold_does_not_raise_and_drops_the_match():
    games = [_game(f"w{i}", 1) for i in range(5)]
    frames = [(mid, ts, pid, None if pid <= 5 else g)
              for (mid, ts, pid, g) in _frames("nul", 600_000, 1600, 1000)]
    games.append(([("nul", 11, 1, 100, 1)], _parts("nul"), frames))
    out = se.compute_snowball_elasticity(conn=_build(games))
    assert out["ok"] is True
    assert _n(out) == 5


def test_one_null_gold_drops_the_match_not_summed_as_zero():
    games = [_game(f"w{i}", 1) for i in range(5)]
    frames = _frames("onenul", 600_000, 1000, 1000)
    frames[0] = ("onenul", 600_000, 1, None)
    games.append(([("onenul", 11, 1, 100, 0)], _parts("onenul"), frames))
    out = se.compute_snowball_elasticity(conn=_build(games))
    # Old behaviour: SUM skips the NULL -> tracked team 1000 behind -> a
    # loss in "behind". It must not enter any bucket.
    assert _bucket(out, "10min", "behind")["games"] == 0
    assert _n(out) == 5


def test_infinite_gold_does_not_raise():
    games = [_game(f"w{i}", 1) for i in range(5)]
    frames = _frames("inf", 600_000, 1000, 1000)
    frames[0] = ("inf", 600_000, 1, float("inf"))
    games.append(([("inf", 11, 1, 100, 1)], _parts("inf"), frames))
    out = se.compute_snowball_elasticity(conn=_build(games))
    assert out["ok"] is True
    assert _n(out) == 5


def test_text_gold_is_not_summed_as_zero():
    games = [_game(f"w{i}", 1) for i in range(5)]
    frames = _frames("txtg", 600_000, 1000, 1000)
    frames[0] = ("txtg", 600_000, 1, "lots")
    games.append(([("txtg", 11, 1, 100, 0)], _parts("txtg"), frames))
    out = se.compute_snowball_elasticity(conn=_build(games))
    assert _bucket(out, "10min", "behind")["games"] == 0
    assert _n(out) == 5


def test_int64_overflow_in_one_match_keeps_the_other_matches():
    games = [_game(f"w{i}", 1) for i in range(5)]
    frames = _frames("big", 600_000, 1000, 1000)
    frames[0] = ("big", 600_000, 1, 2 ** 62)
    frames[1] = ("big", 600_000, 2, 2 ** 62)
    games.append(([("big", 11, 1, 100, 1)], _parts("big"), frames))
    out = se.compute_snowball_elasticity(conn=_build(games))
    # Old behaviour: SUM raised "integer overflow" and the checkpoint lost
    # all six matches. TOTAL sums as a float, so the five honest matches stay
    # (the junk one reads as a finite, very large lead - a plausibility bound
    # on gold is a separate filing, not invented here).
    assert _bucket(out, "10min", "ahead_big")["games"] == 6
    assert _n(out) == 6


# -- roster integrity ------------------------------------------------------

def test_incomplete_nearest_frame_falls_back_to_complete_frame():
    # At 600s the tracked team has only 4 frames (reads as 1000 behind);
    # at 660s - still inside the tolerance - both rosters are complete and
    # the tracked team leads by 3000.
    near = [f for f in _frames("part", 600_000, 1600, 1000) if f[2] != 1]
    far = _frames("part", 660_000, 1600, 1000)
    games = [([("part", 11, 1, 100, 1)], _parts("part"), near + far)]
    out = se.compute_snowball_elasticity(conn=_build(games))
    assert _bucket(out, "10min", "behind")["games"] == 0
    assert _bucket(out, "10min", "ahead_big")["games"] == 1


def test_incomplete_frame_with_no_fallback_drops_the_match():
    near = [f for f in _frames("part", 600_000, 1600, 1000) if f[2] != 1]
    games = [_game(f"w{i}", 1) for i in range(5)]
    games.append(([("part", 11, 1, 100, 1)], _parts("part"), near))
    out = se.compute_snowball_elasticity(conn=_build(games))
    assert _n(out) == 5


def test_duplicated_frame_row_is_not_double_counted():
    frames = _frames("dup", 600_000, 1000, 1000)
    frames.append(("dup", 600_000, 1, 1000))  # pid 1 twice -> +1000
    games = [_game(f"w{i}", 1) for i in range(5)]
    games.append(([("dup", 11, 1, 100, 1)], _parts("dup"), frames))
    out = se.compute_snowball_elasticity(conn=_build(games))
    assert _bucket(out, "10min", "ahead")["games"] == 0
    assert _n(out) == 5


def test_duplicate_masking_a_missing_player_is_not_counted():
    # pid 1 appears twice and pid 2 not at all: the tracked side still has
    # five rows (the same count as the enemy), so only the distinct-
    # participant check can see that it is really four players.
    frames = [f for f in _frames("mask", 600_000, 1600, 1000) if f[2] != 2]
    frames.append(("mask", 600_000, 1, 1600))
    games = [_game(f"e{i}", 1, diff=0) for i in range(5)]
    games.append(([("mask", 11, 1, 100, 1)], _parts("mask"), frames))
    out = se.compute_snowball_elasticity(conn=_build(games))
    assert _bucket(out, "10min", "ahead_big")["games"] == 0
    assert _n(out) == 5


def test_duplicated_participant_row_is_not_double_counted():
    parts = _parts("dpart") + [("dpart", 1, 100)]
    games = [_game(f"w{i}", 1) for i in range(5)]
    games.append(([("dpart", 11, 1, 100, 1)], parts,
                  _frames("dpart", 600_000, 1000, 1000)))
    out = se.compute_snowball_elasticity(conn=_build(games))
    assert _bucket(out, "10min", "ahead")["games"] == 0
    assert _n(out) == 5


# -- tracked meta read once, never cached on the connection ----------------

def test_tracked_meta_read_once_per_call():
    conn = _build([_game(f"w{i}", 1) for i in range(5)])
    stmts = []
    conn.set_trace_callback(stmts.append)
    se.compute_snowball_elasticity(conn=conn)
    meta_reads = [s for s in stmts if "tracked_team_id" in s
                  and "timeline_frames" not in s]
    assert len(meta_reads) == 1


class _AttrConn(sqlite3.Connection):
    """A Connection subclass HAS a __dict__, so an attribute cache sticks."""


def test_no_stale_tracked_meta_across_calls_on_one_connection():
    conn = _build([_game(f"w{i}", 1) for i in range(5)], factory=_AttrConn)
    first = se.compute_snowball_elasticity(conn=conn)
    assert _bucket(first, "10min", "ahead_big")["wins"] == 5
    conn.execute("UPDATE matches SET tracked_win = 0")
    conn.commit()
    second = se.compute_snowball_elasticity(conn=conn)
    assert _bucket(second, "10min", "ahead_big")["wins"] == 0
    assert not hasattr(conn, "_se_tracked_meta")


# -- read-only open --------------------------------------------------------

def test_ro_open_survives_hash_in_checkout_path(tmp_path, monkeypatch):
    root = tmp_path / "a#b"
    root.mkdir()
    db = root / "rewind_history.db"
    seed = _build([_game(f"w{i}", 1) for i in range(5)], path=str(db))
    seed.close()
    monkeypatch.setattr(se, "_REWIND_DB", db)
    out = se.compute_snowball_elasticity()
    assert _bucket(out, "10min", "ahead_big")["games"] == 5


def test_ro_open_is_read_only(tmp_path, monkeypatch):
    db = tmp_path / "rewind_history.db"
    _build([_game("w0", 1)], path=str(db)).close()
    monkeypatch.setattr(se, "_REWIND_DB", db)
    conn = se._open_ro()
    try:
        with pytest.raises(sqlite3.OperationalError) as caught:
            conn.execute("DELETE FROM matches")
    finally:
        conn.close()
    assert "readonly" in str(caught.value).replace(" ", "").lower()


def test_payload_is_strict_json_finite():
    games = [_game(f"w{i}", 1) for i in range(5)]
    out = se.compute_snowball_elasticity(conn=_build(games))
    for cp in out["checkpoints"]:
        for b in cp["buckets"]:
            for v in (b["winrate"], b["winrate_smoothed"]):
                assert v is None or math.isfinite(v)
