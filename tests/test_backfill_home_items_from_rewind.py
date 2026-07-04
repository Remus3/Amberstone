"""A7 data-completeness: one-shot backfill of Home Recent build items into
pre-ingest match_history rows from rewind_history.db.

Operator ruling (HOME_QA 2026-07-04, item A7): rows that predate the LCU
ingest pipeline carry ``items == []`` and render hatched empty slots. This
backfills the operator's 6 build-slot items from rewind_history.db.

SAFETY (the reason this is a STRICT join): match_history gap rows have no
match_id and (mostly) game_id=0, so the only rewind join key is fuzzy -
(champion, timestamp-window). Join-quality probe (2026-07-04): a 10-min
window yields 22 unambiguous vs 1 ambiguous; widening to 30 min makes it
WORSE (9 ambiguous). So the tool backfills ONLY when EXACTLY ONE rewind
match falls in the tight window - ambiguous (>1) and no-match rows keep the
honest empty placeholder (a wrong-item backfill would be fabricated data,
worse than empty). Idempotent (only rows lacking lcu_match_detail are
touched) + precise (stamps the known row id, not the ingest endpoint's
timestamp-window resolution). ASCII-only.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_PUUID = "REWIND-PUUID-9"


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _make_match_db(path: Path, rows) -> None:
    # rows: (timestamp, mode, champion, raw_data)
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
    for ts, mode, champ, raw in rows:
        conn.execute(
            "INSERT INTO matches (timestamp, mode, champion, raw_data)"
            " VALUES (?,?,?,?)", (ts, mode, champ, raw))
    conn.commit()
    conn.close()


def _make_rewind_db(path: Path, matches, participants) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE matches ("
        "  match_id TEXT PRIMARY KEY, queue_id INTEGER,"
        "  game_creation_ts INTEGER, game_end_ts INTEGER,"
        "  game_duration_s INTEGER,"
        "  tracked_champion_id INTEGER, tracked_champion_name TEXT)"
    )
    conn.execute(
        "CREATE TABLE participants ("
        "  match_id TEXT, puuid TEXT, champion_id INTEGER,"
        "  champion_name TEXT, win INTEGER,"
        "  item0 INTEGER, item1 INTEGER, item2 INTEGER,"
        "  item3 INTEGER, item4 INTEGER, item5 INTEGER, item6 INTEGER)"
    )
    conn.executemany(
        "INSERT INTO matches VALUES (?,?,?,?,?,?,?)", matches)
    conn.executemany(
        "INSERT INTO participants VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        participants)
    conn.commit()
    conn.close()


def _fixture(td: Path):
    now = datetime(2026, 6, 1, 20, 0, 0)
    # Gap row that HAS a rewind twin (Ziggs, ends ~ same time)
    # Gap row with NO rewind twin (Zed)
    _make_match_db(td / "match_history.db", [
        (_ts(now), "ARAM", "Ziggs", ""),                 # will backfill
        (_ts(now - timedelta(days=3)), "SR", "Zed", ""),  # no twin -> stays empty
    ])
    end_ms = int(now.timestamp() * 1000)
    _make_rewind_db(
        td / "rewind_history.db",
        matches=[
            ("NA1_5592802194", 2400, end_ms - 1_200_000, end_ms,
             1200, 115, "Ziggs"),
        ],
        participants=[
            ("NA1_5592802194", _PUUID, 115, "Ziggs", 1,
             1001, 3006, 6655, 3089, 3135, 3157, 3363),
        ],
    )


def _items(raw_data: str):
    import dashboard.builders_home as H
    return H._lcu_build_items(raw_data)


def _subtype(raw_data: str):
    import dashboard.builders_home as H
    return H._lcu_queue_subtype(raw_data)


def _row_raw(db_path: Path, champ: str) -> str:
    conn = sqlite3.connect(str(db_path))
    try:
        r = conn.execute(
            "SELECT raw_data FROM matches WHERE champion=?", (champ,)
        ).fetchone()
        return r[0] if r else ""
    finally:
        conn.close()


def test_backfill_stamps_matching_row():
    from tools.backfill_home_items_from_rewind import backfill
    with TemporaryDirectory() as td:
        tdp = Path(td)
        _fixture(tdp)
        report = backfill(tdp / "match_history.db", tdp / "rewind_history.db",
                          window_s=600, dry_run=False)
        assert report["stamped"] == 1, report
        raw = _row_raw(tdp / "match_history.db", "Ziggs")
        assert _items(raw) == [1001, 3006, 6655, 3089, 3135, 3157]
        # mode_subtype now derives too (queueId 2400 -> Mayhem)
        assert _subtype(raw) == "Mayhem"


def test_backfill_skips_unmatched_row():
    from tools.backfill_home_items_from_rewind import backfill
    with TemporaryDirectory() as td:
        tdp = Path(td)
        _fixture(tdp)
        backfill(tdp / "match_history.db", tdp / "rewind_history.db",
                 window_s=600, dry_run=False)
        # Zed had no rewind twin -> still empty (honest placeholder)
        assert _items(_row_raw(tdp / "match_history.db", "Zed")) == []


def test_backfill_is_idempotent():
    from tools.backfill_home_items_from_rewind import backfill
    with TemporaryDirectory() as td:
        tdp = Path(td)
        _fixture(tdp)
        first = backfill(tdp / "match_history.db", tdp / "rewind_history.db",
                         window_s=600, dry_run=False)
        second = backfill(tdp / "match_history.db", tdp / "rewind_history.db",
                          window_s=600, dry_run=False)
        assert first["stamped"] == 1
        assert second["stamped"] == 0, "re-run must not re-stamp"


def test_dry_run_writes_nothing():
    from tools.backfill_home_items_from_rewind import backfill
    with TemporaryDirectory() as td:
        tdp = Path(td)
        _fixture(tdp)
        report = backfill(tdp / "match_history.db", tdp / "rewind_history.db",
                          window_s=600, dry_run=True)
        assert report["stamped"] == 1  # would-stamp count
        assert _items(_row_raw(tdp / "match_history.db", "Ziggs")) == []


def test_ambiguous_window_skips():
    # Two rewind twins for the same champion inside the window -> skip.
    from tools.backfill_home_items_from_rewind import backfill
    with TemporaryDirectory() as td:
        tdp = Path(td)
        now = datetime(2026, 6, 1, 20, 0, 0)
        _make_match_db(tdp / "match_history.db", [
            (_ts(now), "ARAM", "Lux", ""),
        ])
        end_ms = int(now.timestamp() * 1000)
        _make_rewind_db(
            tdp / "rewind_history.db",
            matches=[
                ("NA1_1", 450, end_ms - 1_200_000, end_ms, 1200, 99, "Lux"),
                ("NA1_2", 2400, end_ms - 1_000_000, end_ms - 200_000,
                 800, 99, "Lux"),
            ],
            participants=[
                ("NA1_1", _PUUID, 99, "Lux", 1, 1, 2, 3, 4, 5, 6, 7),
                ("NA1_2", _PUUID, 99, "Lux", 0, 8, 9, 10, 11, 12, 13, 14),
            ],
        )
        report = backfill(tdp / "match_history.db",
                          tdp / "rewind_history.db",
                          window_s=600, dry_run=False)
        assert report["stamped"] == 0
        assert report["ambiguous"] == 1
        assert _items(_row_raw(tdp / "match_history.db", "Lux")) == []


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
