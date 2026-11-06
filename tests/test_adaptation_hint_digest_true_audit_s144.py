"""True-audit (s144 lane 8, cycle 140) of ``coaches/adaptation_hint_digest.py``.

``coaching_digest`` backs the supervisor's ``GET /api/digest``
(``agents/_supervisor_http.py`` ``_handle_digest``, no try around the
call, body serialized with ``allow_nan=False``), the advisory scan in
``agents/agent4_coach_mentor/insight_detector.py`` and the ``--digest``
CLI. It composes four producers (``kda_trends`` and the three temporal
analyses), so one bad mode-DB row anywhere decided the whole feed.

Findings pinned here (RM-1818..RM-1823), each measured before the fix:

* RM-1818 a non-finite KDA value in ``aggregates_json`` (the JSON
  literals ``-Infinity`` / ``NaN``, or ``1e400``) reached the insight:
  the message read "(-inf)" / "KDA nan" and the strict-JSON dump of the
  digest raised ValueError, so ``/api/digest`` answered a generic 500.
* RM-1819 one bad row in ANY producer raised out of ``coaching_digest``:
  a non-dict ``recent_kda`` (AttributeError) or a junk ``delta_ratio``
  (ValueError) in ``kda_trends``, a BLOB ``started_at`` or a TEXT kills
  cell (TypeError) in the temporal analyses. Every other insight was lost
  with it. Each producer call is now isolated and logged at WARNING.
* RM-1820 the champion label was passed raw: a BLOB printed
  "b'Jinx' (aram)", a newline split the CLI line, a blank name printed
  " (aram) KDA ...".
* RM-1821 ``top_n`` was used as a raw slice bound: a negative value
  silently dropped the LAST insights instead of listing none, a str
  raised TypeError and ``True`` clamped the feed to one insight.
* RM-1822 the KDA messages emitted U+2192. The source spells it as an
  escape, so the item-426 source-ASCII guard never saw it; the CLI text
  redirected to a cp1252 stream raises UnicodeEncodeError on it.
* RM-1823 a temporal bucket's ``data`` carried a non-finite
  ``kda_ratio`` (a REAL inf kills cell) into the insight, which also broke
  the strict-JSON dump.

The upstream raises themselves live in ``adaptation_hint_aggregates.py``
and ``adaptation_hint_temporal.py`` (out of this one-file cycle; filed).
Well-formed rows give the same insights; only the arrow changed to "->".
"""
from __future__ import annotations

import io
import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

MODES = ("aram", "sr_ranked")
COLD = {
    "win_rate": 0.55,
    "avg_kda": {"ratio": 4.0, "sample": 30},
    "recent_kda": {"ratio": 2.0, "sample": 10, "delta_ratio": -2.0},
}
HOT = {
    "win_rate": 0.55,
    "avg_kda": {"ratio": 3.0, "sample": 30},
    "recent_kda": {"ratio": 3.8, "sample": 8, "delta_ratio": 0.8},
}


@pytest.fixture
def env(tmp_path: Path, monkeypatch):
    import agents.agent2_backend.db_schema as dbs
    from coaches import adaptation_hint
    monkeypatch.setattr(dbs, "DB_DIR", tmp_path)
    monkeypatch.setattr(adaptation_hint, "DB_DIR", tmp_path)
    for mode in MODES:
        dbs.init_mode(mode)
    return tmp_path


def _bucket(db: Path, champ, aj, champ_sql: str | None = None) -> None:
    text = aj if isinstance(aj, str) else json.dumps(aj)
    champ_expr = champ_sql if champ_sql is not None else "?"
    args = (() if champ_sql is not None else (champ,)) + (text,)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO adaptation_buckets (champion, games_played, wins,"
            " losses, avg_rating, last_updated, aggregates_json) VALUES ("
            + champ_expr + ", 20, 10, 10, 0.5, '2026-04-22T00:00:00Z', ?)",
            args,
        )
    conn.close()


def _match(db: Path, win, started_at, duration=1200, kills="5",
           started_sql: str | None = None) -> None:
    start_expr = started_sql if started_sql is not None else "?"
    args = (() if started_sql is not None else (started_at,)) + (
        duration, win)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO matches (started_at, champion, ally_champions,"
            " enemy_champions, duration_sec, win, source, kills, deaths,"
            " assists) VALUES (" + start_expr + ", 'Ahri', '[]', '[]', ?, ?,"
            " 'live-phase3', " + kills + ", 5, 10)",
            args,
        )
    conn.close()


def _at_hour(hour: int) -> str:
    now = datetime.now().astimezone() - timedelta(days=1)
    return now.replace(hour=hour, minute=0, second=0, microsecond=0).isoformat()


def _hour_split(db: Path, win_kills: str = "5") -> None:
    """5 wins at 10h, 5 losses at 03h, same day and duration tier."""
    for _ in range(5):
        _match(db, 1, _at_hour(10), kills=win_kills)
    for _ in range(5):
        _match(db, 0, _at_hour(3))


def _digest(**kw):
    from coaches.adaptation_hint import coaching_digest
    return coaching_digest(**kw)


def _strict(d) -> str:
    return json.dumps(d, allow_nan=False)


# -- characterization: well-formed rows -------------------------------

def test_cold_and_hot_messages_exact(env):
    _bucket(env / "aram.db", "Jinx", COLD)
    _bucket(env / "aram.db", "Ezreal", HOT)
    d = _digest(mode="aram", top_n=5)
    assert d["mode"] == "aram" and d["since"] is None and d["count"] == 2
    cold, hot = d["insights"]
    assert cold["type"] == "cold_streak" and cold["severity"] == 1.0
    assert cold["champion"] == "Jinx" and cold["mode"] == "aram"
    assert cold["message"] == (
        "Jinx (aram) KDA 4.00 -> 2.00 (-2.00) over last 10 games")
    assert hot["type"] == "hot_streak" and hot["severity"] == 0.4
    assert hot["message"] == (
        "Ezreal (aram) KDA 3.00 -> 3.80 (+0.80) over last 8 games")
    assert cold["data"] == {"champion": "Jinx", "baseline_ratio": 4.0,
                            "recent_ratio": 2.0, "delta": -2.0, "sample": 10}
    _strict(d)


def test_hour_outliers_exact(env):
    _hour_split(env / "aram.db")
    d = _digest(mode="aram", top_n=10)
    by_type = {i["type"]: i for i in d["insights"]}
    assert set(by_type) == {"worst_hour", "best_hour"}
    assert by_type["worst_hour"]["message"] == (
        "Slump at 03h: 0% wr (n=5, avg 50%)")
    assert by_type["worst_hour"]["severity"] == 0.8
    assert by_type["best_hour"]["message"] == (
        "Peak at 10h: 100% wr (n=5, avg 50%)")
    assert by_type["best_hour"]["severity"] == 0.6
    assert by_type["worst_hour"]["mode"] == "aram"
    assert by_type["worst_hour"]["data"]["hour"] == 3
    _strict(d)


def test_count_is_total_before_top_n_clip(env):
    for i in range(4):
        _bucket(env / "aram.db", f"Cold{i}", COLD)
    d = _digest(mode="aram", top_n=2)
    # kda_trends keeps the 3 coldest; count is pre-clip.
    assert d["count"] == 3 and len(d["insights"]) == 2


def test_empty_digest_shape(env):
    assert _digest(mode="aram") == {
        "mode": "aram", "since": None, "count": 0, "insights": []}
    assert _digest()["mode"] == "all"


# -- RM-1818 non-finite KDA values ---------------------------------

@pytest.mark.parametrize("aj", [
    '{"avg_kda": {"ratio": 4.0}, "recent_kda": {"ratio": 2.0,'
    ' "sample": 10, "delta_ratio": -Infinity}}',
    '{"avg_kda": {"ratio": NaN}, "recent_kda": {"ratio": 2.0,'
    ' "sample": 10, "delta_ratio": -2.0}}',
    '{"avg_kda": {"ratio": 4.0}, "recent_kda": {"ratio": Infinity,'
    ' "sample": 10, "delta_ratio": 1.0}}',
    '{"avg_kda": {"ratio": 4.0}, "recent_kda": {"ratio": 2.0,'
    ' "sample": 10, "delta_ratio": 1e400}}',
])
def test_non_finite_kda_entry_is_skipped(env, aj):
    _bucket(env / "aram.db", "Broken", aj)
    _bucket(env / "aram.db", "Jinx", COLD)
    d = _digest(mode="aram", top_n=10)
    champs = [i.get("champion") for i in d["insights"]]
    assert champs == ["Jinx"]
    text = _strict(d)
    assert "inf" not in text.lower() and "nan" not in text.lower()


# -- RM-1819 one producer raising must not kill the digest ---------

@pytest.mark.parametrize("aj", [
    '{"avg_kda": {"ratio": 4.0}, "recent_kda": [1, 2]}',
    '{"avg_kda": {"ratio": 4.0}, "recent_kda": {"ratio": 2.0,'
    ' "sample": 10, "delta_ratio": "abc"}}',
])
def test_bad_bucket_in_one_mode_keeps_other_modes_and_dimensions(
        env, aj, caplog):
    _bucket(env / "aram.db", "Broken", aj)
    _bucket(env / "sr_ranked.db", "Jinx", COLD)
    _hour_split(env / "aram.db")
    with caplog.at_level(logging.WARNING, logger="coaches.adaptation_hint"):
        d = _digest(top_n=10)
    types = {i["type"] for i in d["insights"]}
    assert {"cold_streak", "worst_hour", "best_hour"} <= types
    assert [i["mode"] for i in d["insights"]
            if i["type"] == "cold_streak"] == ["sr_ranked"]
    # Since true-audit cycle 150 (RM-1879) kda_trends skips the bad
    # row itself, so the digest has nothing to isolate and logs no
    # kda_trends warning; the isolation is pinned by the test below.
    assert not any("kda_trends" in r.getMessage()
                   for r in caplog.records if r.levelno == logging.WARNING)


def test_kda_trends_data_error_in_one_mode_is_isolated(env, monkeypatch,
                                                       caplog):
    import coaches.adaptation_hint_digest as dg
    real = dg.kda_trends

    def flaky(mode, **kw):
        if mode == "aram":
            raise AttributeError("bad aram row")
        return real(mode, **kw)

    _bucket(env / "sr_ranked.db", "Jinx", COLD)
    monkeypatch.setattr(dg, "kda_trends", flaky)
    with caplog.at_level(logging.WARNING, logger="coaches.adaptation_hint"):
        d = dg.coaching_digest(top_n=10)
    assert [i["mode"] for i in d["insights"]
            if i["type"] == "cold_streak"] == ["sr_ranked"]
    assert any("kda_trends" in r.getMessage() and "aram" in r.getMessage()
               for r in caplog.records if r.levelno == logging.WARNING)


@pytest.mark.parametrize("kind", ["blob_started_at", "text_kills"])
def test_bad_match_row_keeps_kda_insights(env, kind, caplog):
    _bucket(env / "aram.db", "Jinx", COLD)
    if kind == "blob_started_at":
        _match(env / "aram.db", 1, None, started_sql="X'41'")
    else:
        _match(env / "aram.db", 1, _at_hour(10), kills="'abc'")
    with caplog.at_level(logging.WARNING, logger="coaches.adaptation_hint"):
        d = _digest(mode="aram", top_n=10)
    assert [i["champion"] for i in d["insights"]] == ["Jinx"]
    warned = [r.getMessage() for r in caplog.records
              if r.levelno == logging.WARNING]
    assert any("time_of_day_analysis" in m for m in warned)
    _strict(d)


def test_unexpected_exception_class_still_surfaces(env, monkeypatch):
    """Isolation is narrow: a non-data error is a real bug and raises."""
    import coaches.adaptation_hint_digest as dg

    def boom(*a, **k):
        raise RuntimeError("not a bad-row error")

    monkeypatch.setattr(dg, "time_of_day_analysis", boom)
    with pytest.raises(RuntimeError):
        dg.coaching_digest(mode="aram")


# -- RM-1820 champion label -----------------------------------------

def test_blob_champion_is_skipped(env):
    _bucket(env / "aram.db", None, COLD, champ_sql="X'4A696E78'")
    _bucket(env / "aram.db", "Ahri", COLD)
    d = _digest(mode="aram", top_n=10)
    assert [i["champion"] for i in d["insights"]] == ["Ahri"]
    assert all(isinstance(i["data"]["champion"], str) for i in d["insights"])


def test_blank_champion_is_skipped(env):
    _bucket(env / "aram.db", "  ", COLD)
    _bucket(env / "aram.db", "Ahri", COLD)
    d = _digest(mode="aram", top_n=10)
    assert [i["champion"] for i in d["insights"]] == ["Ahri"]


def test_control_chars_in_champion_become_one_line(env):
    _bucket(env / "aram.db", "Ji\nnx\x1b[31m" + "x" * 200, COLD)
    d = _digest(mode="aram", top_n=10)
    (ins,) = d["insights"]
    assert "\n" not in ins["message"] and "\x1b" not in ins["message"]
    assert ins["champion"].startswith("Ji nx")
    assert len(ins["champion"]) <= 64
    assert ins["data"]["champion"] == ins["champion"]
    assert ins["message"].startswith(ins["champion"] + " (aram) KDA")


# -- RM-1821 top_n --------------------------------------------------

@pytest.mark.parametrize("top_n,expected", [
    (-1, 0), (0, 0), (2, 2), (6, 6),
    # Non-int / bool fall back to the default 5 (6 are available, so the
    # default is told apart from "no limit"; None used to mean no limit).
    (True, 5), ("3", 5), (2.5, 5), (None, 5),
])
def test_top_n_bounds(env, top_n, expected):
    for i in range(3):
        _bucket(env / "aram.db", f"Cold{i}", COLD)
        _bucket(env / "aram.db", f"Hot{i}", HOT)
    d = _digest(mode="aram", top_n=top_n)
    assert len(d["insights"]) == expected
    assert d["count"] == 6


# -- RM-1822 ASCII output -------------------------------------------

def test_messages_are_ascii_and_cli_text_survives_cp1252(env, monkeypatch):
    from coaches.adaptation_hint import main
    _bucket(env / "aram.db", "Jinx", COLD)
    _bucket(env / "aram.db", "Ezreal", HOT)
    _hour_split(env / "aram.db")
    d = _digest(mode="aram", top_n=10)
    assert d["insights"]
    assert all(i["message"].isascii() for i in d["insights"])
    buf = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    monkeypatch.setattr("sys.stdout", buf)
    assert main(["--digest", "-m", "aram"]) == 0
    buf.flush()


def test_digest_source_is_ascii_without_arrow_escape():
    src = (Path(__file__).resolve().parent.parent / "coaches"
           / "adaptation_hint_digest.py").read_bytes()
    assert src.isascii()
    assert b"\\u2192" not in src


# -- RM-1823 non-finite bucket data -----------------------------------

def test_non_finite_kda_ratio_in_bucket_data_is_scrubbed(env):
    _hour_split(env / "aram.db", win_kills="9e999")
    d = _digest(mode="aram", top_n=10)
    by_type = {i["type"]: i for i in d["insights"]}
    assert "best_hour" in by_type
    assert by_type["best_hour"]["data"]["kda_ratio"] is None
    assert by_type["worst_hour"]["data"]["kda_ratio"] is not None
    _strict(d)
