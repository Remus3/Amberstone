"""True-audit (s144 lane 8, cycle 139) of ``coaches/adaptation_hint_session.py``.

The module backs the supervisor's ``GET /api/session`` and
``GET /api/session-games`` (``agents/_supervisor_http.py``
``_handle_session`` / ``_handle_session_games``) and the ``--session`` /
``--games`` CLI. Both HTTP handlers call it with no try around the call
and send the result through ``_send_json(..., allow_nan=False)``, so one
bad mode-DB row either raised out of the handler or turned the whole
response into a generic 500.

Findings pinned here (RM-1809..RM-1817), each measured before the fix:

* RM-1809 a non-numeric TEXT kills / deaths / assists cell (SQLite
  INTEGER affinity keeps ``'abc'`` as TEXT) raised TypeError out of both
  functions - not a sqlite3.Error, so nothing caught it.
* RM-1810 a REAL inf in a KDA or duration cell reached the payload as
  ``inf``; ``allow_nan=False`` then replaced the whole response with a 500.
* RM-1811 one TEXT cell holding invalid UTF-8 raised
  ``sqlite3.OperationalError`` while the rows were read, so
  ``session_summary`` silently dropped the WHOLE mode, and
  ``session_games`` kept the rows read before it (a partial mode).
* RM-1812 ``session_games`` appended rows while iterating the cursor,
  so a mid-scan sqlite3.Error left a partial mode in the timeline.
* RM-1813 ``with sqlite3.connect()`` commits but never closes, so
  every call leaked one connection per mode DB until GC.
* RM-1814 negative or absurd (> 1e6) K/D/A counts were averaged into
  the KDA ratio; a non-text started_at (a BLOB sorts above every TEXT in
  SQLite) passed the ``started_at >= ?`` filter and then raised TypeError
  in the str sort.
* RM-1815 champion / source labels were passed raw: bytes reached the
  JSON as ``"b'...'"`` and a newline split the CLI text line.
* RM-1816 a non-int ``limit`` (str, float) raised TypeError; ``True``
  clamped the timeline to one row.
* RM-1817 a truthy non-str ``since_iso`` was bound as-is: a float is
  a number, which SQLite orders below every TEXT, so ``since=12.5``
  returned every game ever recorded; bytes / a list echoed back as the
  ``since`` field. (``since=0`` was already safe: it is falsy, so it fell
  back to today; it stays as a characterization case.)

The ``--games`` CLI (``coaches/adaptation_hint_cli.py``
``_format_games_text``) formats the champion with a str spec, so a
non-text or blank champion is "Unknown" in ``session_games`` too.

Well-formed rows give byte-identical output (characterization tests).
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

MODES = ("aram", "sr_ranked")


@pytest.fixture
def env(tmp_path: Path, monkeypatch):
    import agents.agent2_backend.db_schema as dbs
    from coaches import adaptation_hint
    monkeypatch.setattr(dbs, "DB_DIR", tmp_path)
    monkeypatch.setattr(adaptation_hint, "DB_DIR", tmp_path)
    for mode in MODES:
        dbs.init_mode(mode)
    return tmp_path


def _ts(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def _since() -> str:
    return _ts(12)


def _insert(db: Path, champ, win, k, d, a, started_at, duration=1200,
            source="live-phase3", champ_sql: str | None = None) -> None:
    champ_expr = champ_sql if champ_sql is not None else "?"
    params = ([] if champ_sql is not None else [champ])
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            f"""INSERT INTO matches
               (started_at, champion, ally_champions, enemy_champions,
                duration_sec, win, source, kills, deaths, assists)
               VALUES (?, {champ_expr}, '[]', '[]', ?, ?, ?, ?, ?, ?)""",
            [started_at, *params, duration, win, source, k, d, a],
        )
        conn.commit()
    finally:
        conn.close()


def _summary(since=None):
    from coaches.adaptation_hint import session_summary
    return session_summary(_since() if since is None else since)


def _games(since=None, limit=None):
    from coaches.adaptation_hint import session_games
    return session_games(_since() if since is None else since, limit=limit)


def _strict_json(obj) -> str:
    return json.dumps(obj, default=str, allow_nan=False)


# -- characterization: well-formed rows are byte-identical -----------------

def test_summary_well_formed_characterization(env):
    t = _ts(2)
    _insert(env / "aram.db", "Ahri", 1, 10, 3, 15, t)
    _insert(env / "aram.db", "Ahri", 0, 4, 6, 8, t)
    _insert(env / "sr_ranked.db", "Jinx", None, 7, 0, 5, t)
    _insert(env / "aram.db", "Old", 1, 1, 1, 1, _ts(48))
    data = _summary()
    assert data["games"] == 3 and data["wins"] == 1 and data["losses"] == 1
    assert data["win_rate"] == 0.5
    assert data["avg_kda"] == {"k": 7.0, "d": 3.0, "a": 9.33,
                               "ratio": 5.44, "sample": 3}
    assert data["per_mode"]["aram"] == {"games": 2, "wins": 1, "losses": 1,
                                        "kda_sample": 2, "kda_ratio": 4.11}
    assert data["per_mode"]["sr_ranked"]["kda_ratio"] == 12.0
    champs = {c["champion"]: c for c in data["champions"]}
    assert champs["Ahri"] == {"champion": "Ahri", "games": 2, "wins": 1,
                              "losses": 1, "win_rate": 0.5, "kda_ratio": 4.11,
                              "kda_sample": 2, "modes": ["aram"]}
    assert champs["Jinx"]["win_rate"] is None
    assert [c["champion"] for c in data["champions"]] == ["Ahri", "Jinx"]


def test_games_well_formed_characterization(env):
    _insert(env / "aram.db", "Ahri", 1, 10, 3, 15, _ts(3), duration=1500)
    _insert(env / "sr_ranked.db", "Jinx", 0, 2, 0, 4, _ts(2))
    _insert(env / "aram.db", "Lux", None, None, None, None, _ts(1))
    rows = _games()
    assert [r["champion"] for r in rows] == ["Ahri", "Jinx", "Lux"]
    assert rows[0]["kda"] == {"k": 10, "d": 3, "a": 15}
    assert rows[0]["kda_ratio"] == 8.33
    assert rows[0]["duration_sec"] == 1500
    assert isinstance(rows[0]["duration_sec"], int)
    assert rows[0]["win"] == 1 and rows[1]["win"] == 0 and rows[2]["win"] is None
    assert rows[1]["kda_ratio"] == 6.0
    assert rows[2]["kda"] is None and rows[2]["kda_ratio"] is None
    assert rows[0]["source"] == "live-phase3" and rows[0]["ended_at"] is None
    assert set(rows[0]) == {"started_at", "ended_at", "mode", "champion", "win",
                            "duration_sec", "kda", "kda_ratio", "source"}
    assert [r["champion"] for r in _games(limit=2)] == ["Jinx", "Lux"]


# -- RM-1809 non-numeric KDA cell ---------------------------------------

def test_t318_text_kda_cell_does_not_raise(env):
    t = _ts(2)
    _insert(env / "aram.db", "Ahri", 1, 10, 3, 15, t)
    _insert(env / "aram.db", "Jinx", 0, "abc", 2, 3, t)
    data = _summary()
    assert data["games"] == 2 and data["wins"] == 1 and data["losses"] == 1
    # The unusable triple is excluded from the KDA sample, not averaged.
    assert data["avg_kda"]["sample"] == 1
    assert data["avg_kda"]["ratio"] == 8.33
    rows = _games()
    assert len(rows) == 2
    jinx = next(r for r in rows if r["champion"] == "Jinx")
    assert jinx["kda"] is None and jinx["kda_ratio"] is None


# -- RM-1810 non-finite cells -------------------------------------------

@pytest.mark.parametrize("col", ["k", "d", "a"])
def test_t319_inf_kda_keeps_payload_strict_json(env, col):
    vals = {"k": 5, "d": 2, "a": 4}
    vals[col] = float("inf")
    _insert(env / "aram.db", "Ahri", 1, vals["k"], vals["d"], vals["a"], _ts(2))
    _insert(env / "aram.db", "Lux", 1, 1, 1, 1, _ts(2))
    data = _summary()
    _strict_json(data)
    assert data["avg_kda"]["sample"] == 1
    rows = _games()
    _strict_json(rows)
    assert [r["kda"] for r in rows if r["champion"] == "Ahri"] == [None]


def test_t319_inf_duration_and_win_are_dropped(env):
    _insert(env / "aram.db", "Ahri", float("inf"), 1, 1, 1, _ts(2),
            duration=float("-inf"))
    rows = _games()
    _strict_json(rows)
    assert rows[0]["duration_sec"] is None
    assert rows[0]["win"] is None
    data = _summary()
    _strict_json(data)
    assert data["games"] == 1 and data["wins"] == 0 and data["losses"] == 0


def test_t319_number_helper_rejects_nan():
    # SQLite stores NaN as NULL, so NaN never comes out of a mode DB; the
    # helper still refuses it (NaN fails every range comparison, so the
    # [0, cap] check alone would let it through).
    from coaches.adaptation_hint_session import _number
    assert _number(float("nan"), 10) is None
    assert _number(3, 10) == 3 and isinstance(_number(3, 10), int)
    assert _number(2.5, 10) == 2.5


# -- RM-1811 invalid UTF-8 text cell ------------------------------------

def test_t320_invalid_utf8_cell_keeps_the_mode(env):
    t = _ts(2)
    _insert(env / "aram.db", "Ahri", 1, 2, 2, 2, t)
    _insert(env / "aram.db", None, 0, 2, 2, 2, t,
            champ_sql="CAST(x'ff41' AS TEXT)")
    data = _summary()
    assert data["games"] == 2 and data["per_mode"]["aram"]["games"] == 2
    rows = _games()
    assert len(rows) == 2
    bad = next(r for r in rows if r["champion"] != "Ahri")
    assert isinstance(bad["champion"], str) and bad["champion"].endswith("A")
    _strict_json(rows)


# -- RM-1812 mid-scan sqlite3.Error -> no partial mode -------------------

class _BreakingCursor:
    def __init__(self, cur):
        self._rows = cur.fetchall()

    def _boom(self):
        raise sqlite3.DatabaseError("database disk image is malformed")

    def __iter__(self):
        yield self._rows[0]
        self._boom()

    def fetchall(self):
        self._boom()

    def fetchone(self):
        self._boom()


class _BreakingConn(sqlite3.Connection):
    def execute(self, sql, *args):
        cur = super().execute(sql, *args)
        if "FROM matches" in sql and "aram.db" in getattr(self, "_rc_path", ""):
            return _BreakingCursor(cur)
        return cur


def test_t321_mid_scan_error_drops_the_mode_whole(env, monkeypatch, caplog):
    t = _ts(2)
    _insert(env / "aram.db", "Ahri", 1, 1, 1, 1, t)
    _insert(env / "aram.db", "Lux", 1, 1, 1, 1, _ts(1))
    _insert(env / "sr_ranked.db", "Jinx", 0, 1, 1, 1, t)
    real_connect = sqlite3.connect

    def connect(path, *a, **kw):
        kw["factory"] = _BreakingConn
        conn = real_connect(path, *a, **kw)
        conn._rc_path = str(path)
        return conn

    monkeypatch.setattr(sqlite3, "connect", connect)
    with caplog.at_level(logging.WARNING, logger="coaches.adaptation_hint"):
        rows = _games()
    assert [r["champion"] for r in rows] == ["Jinx"]
    assert any("aram" in rec.getMessage() for rec in caplog.records)


# -- RM-1813 connections are closed -------------------------------------

@pytest.mark.parametrize("fn", ["summary", "games"])
def test_t322_every_connection_is_closed(env, monkeypatch, fn):
    _insert(env / "aram.db", "Ahri", 1, 1, 1, 1, _ts(2))
    opened: list[sqlite3.Connection] = []
    real_connect = sqlite3.connect

    def connect(*a, **kw):
        conn = real_connect(*a, **kw)
        opened.append(conn)
        return conn

    monkeypatch.setattr(sqlite3, "connect", connect)
    (_summary if fn == "summary" else _games)()
    assert len(opened) == len(MODES)
    for conn in opened:
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")


# -- RM-1814 out-of-range counts and non-text started_at ------------------

@pytest.mark.parametrize("triple", [(-5, 1, 1), (1, -1, 1), (1, 1, 10 ** 7)])
def test_t323_out_of_range_counts_leave_the_sample(env, triple):
    _insert(env / "aram.db", "Ahri", 1, *triple, _ts(2))
    _insert(env / "aram.db", "Lux", 1, 3, 1, 3, _ts(2))
    data = _summary()
    assert data["avg_kda"]["sample"] == 1 and data["avg_kda"]["ratio"] == 6.0
    ahri = next(r for r in _games() if r["champion"] == "Ahri")
    assert ahri["kda"] is None and ahri["kda_ratio"] is None


def test_t323_blob_started_at_is_not_a_session_row(env):
    _insert(env / "aram.db", "Ahri", 1, 1, 1, 1, _ts(2))
    _insert(env / "aram.db", "Blob", 1, 1, 1, 1, b"\x00\x01")
    rows = _games()
    assert [r["champion"] for r in rows] == ["Ahri"]
    assert _summary()["games"] == 1


# -- RM-1815 labels -----------------------------------------------------

def test_t324_labels_are_one_printable_line(env):
    _insert(env / "aram.db", "Ah\nri\x00", 1, 1, 1, 1, _ts(2),
            source="live\r\nphase3")
    _insert(env / "aram.db", None, 1, 1, 1, 1, _ts(2),
            champ_sql="CAST(x'4c7578' AS BLOB)", source=b"raw")
    _insert(env / "aram.db", "Z" * 500, 1, 1, 1, 1, _ts(2))
    rows = _games()
    names = sorted(str(r["champion"]) for r in rows)
    for r in rows:
        for key in ("champion", "source"):
            v = r[key]
            assert v is None or (isinstance(v, str) and v.isprintable()
                                 and len(v) <= 64)
    assert "Ah ri" in names
    assert any(r["source"] == "live phase3" for r in rows)
    assert "Unknown" in names  # the BLOB champion
    assert [r["source"] for r in rows if r["champion"] == "Unknown"] == [None]
    champs = [c["champion"] for c in _summary()["champions"]]
    assert all(isinstance(c, str) and c.isprintable() and len(c) <= 64
               for c in champs)
    assert "Unknown" in champs  # the BLOB champion


# -- RM-1816 limit ------------------------------------------------------

@pytest.mark.parametrize("limit", ["2", 2.5, True, -1, 0])
def test_t325_non_int_limit_does_not_clamp_or_raise(env, limit):
    for i in range(3):
        _insert(env / "aram.db", f"C{i}", 1, 1, 1, 1, _ts(3 - i))
    assert len(_games(limit=limit)) == 3


# -- RM-1817 since ------------------------------------------------------

@pytest.mark.parametrize("since", [0, 12.5, b"2000", ["x"]])
def test_t326_non_str_since_falls_back_to_today(env, since):
    _insert(env / "aram.db", "Old", 1, 1, 1, 1, "2000-01-01T00:00:00+00:00")
    data = _summary(since)
    assert data["games"] == 0
    assert isinstance(data["since"], str)
    assert _games(since) == []


def test_t326_datetime_since_is_used_as_iso(env):
    _insert(env / "aram.db", "Old", 1, 1, 1, 1, "2000-01-01T00:00:00+00:00")
    _insert(env / "aram.db", "New", 1, 1, 1, 1, _ts(2))
    cutoff = datetime(2000, 6, 1, tzinfo=timezone.utc)
    data = _summary(cutoff)
    assert data["since"] == cutoff.isoformat()
    assert data["games"] == 1
    assert [r["champion"] for r in _games(cutoff)] == ["New"]


def test_games_cli_text_survives_blank_and_non_text_champion(env):
    from coaches.adaptation_hint_cli import _format_games_text
    _insert(env / "aram.db", "   ", 1, 1, 1, 1, _ts(2))
    _insert(env / "aram.db", None, 1, 1, 1, 1, _ts(1), champ_sql="x'2a'")
    rows = _games()
    assert [r["champion"] for r in rows] == ["Unknown", "Unknown"]
    text = _format_games_text(rows)
    assert text.count("Unknown") == 2
