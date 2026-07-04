"""DELETION GUARD for the OQ13 mode-factored weekly digest (HOME_QA C2).

The QA ruling removed the "THIS WEEK by mode" weekly Good/Bad/Ugly digest:
the `_home_weekly_digest` builder, the `_MODE_BENCH` benchmark consts, the
`out["weekly_digest"]` payload key, and the frontend card are all gone -
the THIS WEEK champ-pool panel already carries the week story. This file
was the pure-function + payload-boundary test for that digest; per the
LEDGER 766 precedent it is converted to a deletion guard that FAILS if the
builder or payload key reappears.

ASCII-only authored content (CLAUDE.md hard rule).
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def test_home_weekly_digest_builder_removed():
    import dashboard.builders_home as H
    assert not hasattr(H, "_home_weekly_digest"), (
        "dashboard.builders_home still defines _home_weekly_digest")


def test_mode_bench_consts_removed():
    import dashboard.builders_home as H
    assert not hasattr(H, "_MODE_BENCH"), (
        "the _MODE_BENCH const outlived the weekly digest that used it")
    assert not hasattr(H, "_MODE_BENCH_DEFAULT"), (
        "the _MODE_BENCH_DEFAULT const outlived the weekly digest")


def test_weekly_digest_not_reexported_from_builders():
    import dashboard.builders as B
    assert not hasattr(B, "_home_weekly_digest"), (
        "dashboard.builders still re-exports _home_weekly_digest")


def _make_match_db(path: Path, rows) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE matches ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  timestamp TEXT, mode TEXT, champion TEXT, grade TEXT,"
        "  game_time_s INTEGER, kills INTEGER, deaths INTEGER,"
        "  assists INTEGER, cs INTEGER, cs_per_min REAL,"
        "  gold INTEGER, gold_per_min REAL, kda_str TEXT,"
        "  kp_pct REAL, label TEXT, raw_data TEXT,"
        "  game_id INTEGER DEFAULT 0)"
    )
    for ts, mode, champ, grade, k, d, a, cs, dur in rows:
        conn.execute(
            "INSERT INTO matches (timestamp, mode, champion, grade,"
            " game_time_s, kills, deaths, assists, cs, cs_per_min,"
            " kda_str, label) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (ts, mode, champ, grade, dur, k, d, a, cs, 0.0,
             f"{k}/{d}/{a}", ""),
        )
    conn.commit()
    conn.close()


def test_weekly_digest_absent_from_payload():
    import dashboard.builders_home as H
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with TemporaryDirectory() as td:
        app_dir = Path(td)
        (app_dir / "data").mkdir()
        _make_match_db(app_dir / "data" / "match_history.db", [
            (now, "ARAM", "Lux", "A", 10, 8, 12, 40, 1200),
            (now, "SR", "Garen", "C", 3, 4, 5, 180, 1800),
        ])
        try:
            with mock.patch.object(H, "_get_lcu_for_rank",
                                   return_value=None):
                with mock.patch.object(H, "_APP_DIR", app_dir):
                    out = H._build_home_summary()
        finally:
            from dashboard import _context
            conns = getattr(_context.DB_CONN_LOCAL, "conns", {})
            for k in [k for k in list(conns.keys())
                      if k.startswith(str(app_dir))]:
                c = conns.pop(k, None)
                if c is not None:
                    c.close()
    assert "weekly_digest" not in out, (
        "home payload still carries weekly_digest")


def test_home_json_mock_has_no_weekly_digest():
    import json
    mock_path = _PROJECT_ROOT / "web" / "data" / "ui_mock" / "home.json"
    data = json.loads(mock_path.read_text(encoding="utf-8"))
    assert "weekly_digest" not in data, (
        "home.json mock still carries weekly_digest")
