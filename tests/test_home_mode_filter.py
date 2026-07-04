"""Per-mode filtering for the HOME summary payload (BE half of the
home SR / ARAM / ARENA tabs - operator ruling, HOME QA round 1).

Covers:
  (a) _build_home_summary(mode_filter="ARAM") filters recent / today /
      this_week / trends / streaks to ARAM rows only;
  (b) the no-arg call keeps today's exact behavior (TFT excluded from
      recent/today/this_week, streaks still TFT-inclusive) plus the
      additive mode_filter="ALL" echo;
  (c) tonight_pick derives from the FILTERED this_week;
  (d) route-level whitelist parsing via routes_history._parse_home_mode
      ("aram" -> "ARAM"; "tft"/"garbage"/absent -> None, never a 4xx);
  (e) rank is an identity read - NEVER filtered;
  (f) last20 is MODE-AWARE by queue_id (operator scope extension):
      SR -> queues 400/420/430/440/480/490, ARENA -> 1700/1710,
      ALL -> unchanged; ARAM -> DATA-DRIVEN (second refinement): auto-
      enables on queues (450, 2400) only when rewind carries at least
      one Mayhem (2400) row; until then {} - ARAM Mayhem never lands in
      rewind_history.db today (Match-V5 403s event modes), so a classic-
      450-only L20 would misrepresent a Mayhem-main's form.

Fixture schema + monkeypatch pattern mirrored from
tests/test_home_weekly_digest.py:47-58 (_make_match_db CREATE TABLE) and
:82-93 (_APP_DIR patch + _get_lcu_for_rank(None) + DB_CONN_LOCAL evict).
The rewind fixture mirrors the fields dashboard/builders.py:50-55
_compute_last20 reads (tracked_win / game_creation_ts) plus queue_id.
ASCII-only authored content (CLAUDE.md hard rule).
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _make_match_db(path: Path, rows) -> None:
    # Canonical matches schema copied from tests/test_home_weekly_digest.py:47
    # (same shape as data/match_history.db - the columns _build_home_summary
    # reads: timestamp/mode/champion/grade/kda_str/game_time_s/kills/deaths/
    # assists/cs/cs_per_min/gold_per_min/label/raw_data).
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
    for ts, mode, champ, grade, k, d, a, cs, cspm, gpm, dur in rows:
        conn.execute(
            "INSERT INTO matches (timestamp, mode, champion, grade,"
            " game_time_s, kills, deaths, assists, cs, cs_per_min,"
            " gold_per_min, kda_str, label) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (ts, mode, champ, grade, dur, k, d, a, cs, cspm, gpm,
             f"{k}/{d}/{a}", ""),
        )
    conn.commit()
    conn.close()


def _make_rewind_db(path: Path, rows) -> None:
    # Minimal rewind_history.db shape: only the columns the last20 query
    # reads (dashboard/builders.py:50-55 - tracked_win ordered by
    # game_creation_ts) plus queue_id for the mode-aware extension.
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE matches ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  queue_id INTEGER, tracked_win INTEGER,"
        "  game_creation_ts INTEGER)"
    )
    for queue_id, tracked_win, ts in rows:
        conn.execute(
            "INSERT INTO matches (queue_id, tracked_win, game_creation_ts)"
            " VALUES (?,?,?)", (queue_id, tracked_win, ts))
    conn.commit()
    conn.close()


def _rewind_rows():
    """(queue_id, tracked_win, game_creation_ts) - newest first by ts.

    Full trail W,L,W,L,W,W (wins 4 / losses 2); SR queues give W,L;
    Arena queues give W,W; the NULL row is undecided and excluded.
    """
    return [
        (420,  1,    100),   # SR ranked        -> W
        (450,  0,     99),   # ARAM classic     -> L
        (1700, 1,     98),   # Arena            -> W
        (400,  0,     97),   # SR draft         -> L
        (1710, 1,     96),   # Arena            -> W
        (450,  1,     95),   # ARAM classic     -> W
        (420,  None,  94),   # undecided        -> excluded everywhere
    ]


def _seed_rows():
    """SR + ARAM + ARENA + TFT rows across today / yesterday / this-week /
    14d windows, with timestamps ordered so streak assertions are exact.

    Row tuple: (ts, mode, champion, grade, k, d, a, cs, cs_per_min,
                gold_per_min, game_time_s).
    """
    now = datetime.now()
    day = now.strftime("%Y-%m-%d")
    yday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    d3 = (now - timedelta(days=3)).strftime("%Y-%m-%d")
    d10 = (now - timedelta(days=10)).strftime("%Y-%m-%d")
    return [
        # today, newest first by clock time:
        # TFT S is the newest row overall (unfiltered good_grades = 1,
        # proving streaks stay TFT-inclusive when unfiltered).
        (f"{day} 21:00:00", "TFT",   "Dark Star Vertical", "S",
         0, 0, 0, 0, 0.0, 0.0, 1800),
        (f"{day} 20:00:00", "SR",    "Garen", "C",  3, 4, 5, 180, 8.0, 420.0, 1800),
        (f"{day} 19:00:00", "ARAM",  "Lux",   "S", 12, 2, 20,  60, 3.0, 700.0, 1200),
        (f"{day} 18:00:00", "ARAM",  "Sona",  "A",  4, 3, 30,  40, 5.0, 650.0, 1100),
        (f"{day} 17:00:00", "ARENA", "Jax",   "B",  6, 5, 4,    0, 0.0, 0.0,   900),
        # yesterday: SR only (no ARAM) - splits play_days between the
        # unfiltered (2) and ARAM-filtered (1) streaks.
        (f"{yday} 20:00:00", "SR",   "Darius", "S", 20, 1, 5, 200, 7.5, 500.0, 1900),
        # 3 days ago (this-week window): one row per mode; the ARAM B
        # breaks the ARAM good-grade run at exactly 2.
        (f"{d3} 20:00:00", "ARAM",  "Lux",    "B", 5, 6, 12, 50, 4.0, 600.0, 1150),
        (f"{d3} 19:00:00", "SR",    "Ahri",   "A", 7, 2,  8, 190, 7.0, 430.0, 1750),
        (f"{d3} 18:00:00", "ARENA", "Sett",   "A", 8, 4,  6,   0, 0.0, 0.0,   950),
        # 10 days ago (14d trends window, outside this-week): SR only -
        # under the ARAM filter this day must go blank in trends.
        (f"{d10} 20:00:00", "SR",   "Garen",  "B", 4, 3, 6, 170, 6.0, 410.0, 1700),
    ]


def _build(mode_filter=None, rewind_rows=None):
    import dashboard.builders_home as H
    with TemporaryDirectory() as td:
        app_dir = Path(td)
        (app_dir / "data").mkdir()
        _make_match_db(app_dir / "data" / "match_history.db", _seed_rows())
        if rewind_rows is not None:
            _make_rewind_db(app_dir / "data" / "rewind_history.db",
                            rewind_rows)
        try:
            with mock.patch.object(H, "_get_lcu_for_rank", return_value=None):
                with mock.patch.object(H, "_APP_DIR", app_dir):
                    if mode_filter is None:
                        return H._build_home_summary()
                    return H._build_home_summary(mode_filter)
        finally:
            # Evict the temp-dir conns so TemporaryDirectory can delete
            # the db file on Windows (test_home_weekly_digest.py:87-93).
            from dashboard import _context
            conns = getattr(_context.DB_CONN_LOCAL, "conns", {})
            for k in [k for k in list(conns.keys())
                      if k.startswith(str(app_dir))]:
                c = conns.pop(k, None)
                if c is not None:
                    c.close()


# -- (a) mode_filter="ARAM" filters every derived section -------------


def test_aram_filter_recent_rows_all_aram():
    out = _build("ARAM")
    assert out["mode_filter"] == "ARAM"
    assert len(out["recent"]) == 3
    assert all(r["mode"] == "ARAM" for r in out["recent"])
    assert [r["champion"] for r in out["recent"]] == ["Lux", "Sona", "Lux"]


def test_aram_filter_today_counts_only_aram():
    out = _build("ARAM")
    assert out["today"]["games"] == 2
    assert out["today"]["modes"] == {"ARAM": 2}
    assert out["today"]["grades"] == {"S": 1, "A": 1}
    assert out["today"]["total_kda"] == "16/5/50"


def test_aram_filter_this_week_only_aram_champs():
    out = _build("ARAM")
    champs = {r["champion"] for r in out["this_week"]}
    assert champs == {"Lux", "Sona"}
    lux = next(r for r in out["this_week"] if r["champion"] == "Lux")
    assert lux["games"] == 2
    assert lux["modes"] == ["ARAM"]


def test_aram_filter_trends_only_aram_points():
    out = _build("ARAM")
    now = datetime.now()
    day = now.strftime("%Y-%m-%d")
    d10 = (now - timedelta(days=10)).strftime("%Y-%m-%d")
    cs_by_date = {p["date"]: p["value"] for p in out["trends"]["cs_per_min"]}
    kda_by_date = {p["date"]: p["value"] for p in out["trends"]["kda"]}
    # today: ARAM-only average (3.0 + 5.0) / 2 - the SR 8.0 / TFT rows are out.
    assert cs_by_date[day] == 4.0
    # the SR-only day 10 days back must be a no-data gap under the filter.
    assert cs_by_date[d10] is None
    assert kda_by_date[d10] is None


def test_aram_filter_streaks_computed_over_aram_rows():
    out = _build("ARAM")
    # ARAM rows newest-first: today S, today A, then the 3-days-ago B breaks.
    assert out["streaks"]["good_grades"] == 2
    # yesterday had SR only - the ARAM play-day chain is today alone.
    assert out["streaks"]["play_days"] == 1


# -- (b) no-arg call keeps today's exact behavior ---------------------


def test_unfiltered_shape_and_tft_exclusions_unchanged():
    out = _build()
    assert out["mode_filter"] == "ALL"
    # recent-3 (round-2 ruling: 5 -> 3, all tabs): the newest 3 non-TFT
    # rows are today's Garen (SR), Lux + Sona (ARAM) - never TFT.
    assert len(out["recent"]) == 3
    assert all(r["mode"] != "TFT" for r in out["recent"])
    assert [r["champion"] for r in out["recent"]] == ["Garen", "Lux", "Sona"]
    assert {r["mode"] for r in out["recent"]} == {"SR", "ARAM"}
    # today: 4 non-TFT games (SR + 2 ARAM + ARENA) - unaffected by the
    # recent LIMIT.
    assert out["today"]["games"] == 4
    assert out["today"]["modes"] == {"SR": 1, "ARAM": 2, "ARENA": 1}
    # this_week: top-3 champs by games (round-2 ruling: 5 -> 3). Lux
    # leads with 2 games; the 1-game ties fill the remaining 2 slots.
    assert len(out["this_week"]) == 3
    assert out["this_week"][0]["champion"] == "Lux"
    assert out["this_week"][0]["games"] == 2
    champs = {r["champion"] for r in out["this_week"]}
    assert champs <= {"Lux", "Sona", "Garen", "Jax", "Darius", "Ahri", "Sett"}
    assert "Dark Star Vertical" not in champs


def test_unfiltered_streaks_still_tft_inclusive():
    out = _build()
    # Newest row overall is the TFT S; the next (SR C) breaks the run.
    # Pre-existing behavior: streaks INCLUDE TFT when unfiltered.
    assert out["streaks"]["good_grades"] == 1
    # today + yesterday both have games (any mode) -> 2-day chain.
    assert out["streaks"]["play_days"] == 2


def test_unfiltered_trends_include_all_modes():
    out = _build()
    d10 = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
    cs_by_date = {p["date"]: p["value"] for p in out["trends"]["cs_per_min"]}
    assert cs_by_date[d10] == 6.0


# -- (c) tonight_pick derives from the filtered this_week -------------


def test_tonight_pick_derives_from_filtered_week():
    out_all = _build()
    out_aram = _build("ARAM")
    # Unfiltered pick is the SR smurf game (Darius 25.0 avg KDA).
    assert out_all["tonight_pick"]["champion"] == "Darius"
    # Filtered pick must come from the ARAM pool only.
    assert out_aram["tonight_pick"]["champion"] in {"Lux", "Sona"}
    assert out_aram["tonight_pick"]["modes"] == ["ARAM"]


# -- (d) route-level whitelist parsing --------------------------------


def test_parse_home_mode_whitelist():
    from dashboard.routes_history import _parse_home_mode
    assert _parse_home_mode("/api/home/summary?mode=aram") == "ARAM"
    assert _parse_home_mode("/api/home/summary?mode=SR") == "SR"
    assert _parse_home_mode("/api/home/summary?mode=Arena") == "ARENA"
    # Out-of-whitelist values fall back to unfiltered - never a 4xx.
    assert _parse_home_mode("/api/home/summary?mode=tft") is None
    assert _parse_home_mode("/api/home/summary?mode=garbage") is None
    assert _parse_home_mode("/api/home/summary?mode=") is None
    assert _parse_home_mode("/api/home/summary") is None


def test_builder_ignores_out_of_whitelist_filter():
    # Defense in depth: even if a caller bypasses the route whitelist,
    # the builder treats an unknown mode as unfiltered ALL.
    out = _build("TFT")
    assert out["mode_filter"] == "ALL"
    assert out["today"]["games"] == 4


# -- (e) rank is an identity read - never filtered --------------------


def test_rank_unaffected_by_filter():
    out_all = _build()
    out_aram = _build("ARAM")
    assert "rank" in out_all and "rank" in out_aram
    assert out_all["rank"] == out_aram["rank"]


# -- (f) last20 mode-aware queue_id policy ----------------------------


def test_last20_all_unchanged_full_trail():
    out = _build(rewind_rows=_rewind_rows())
    assert out["last20"]["results"] == ["W", "L", "W", "L", "W", "W"]
    assert out["last20"]["wins"] == 4
    assert out["last20"]["losses"] == 2
    assert out["last20"]["win_rate"] == 66.7


def test_last20_sr_filter_only_sr_queues():
    out = _build("SR", rewind_rows=_rewind_rows())
    assert out["last20"]["results"] == ["W", "L"]
    assert out["last20"]["wins"] == 1
    assert out["last20"]["losses"] == 1
    assert out["last20"]["win_rate"] == 50.0


def test_last20_arena_filter_only_arena_queues():
    out = _build("ARENA", rewind_rows=_rewind_rows())
    assert out["last20"]["results"] == ["W", "W"]
    assert out["last20"]["wins"] == 2
    assert out["last20"]["losses"] == 0
    assert out["last20"]["win_rate"] == 100.0


def test_last20_aram_empty_without_mayhem_rows():
    # No 2400 rows in rewind -> capability probe says Mayhem data has
    # not landed; a classic-450-only L20 would lie, so the strip is {}.
    out = _build("ARAM", rewind_rows=_rewind_rows())
    assert out["last20"] == {}


def test_last20_aram_auto_enables_with_mayhem_rows():
    rows = [(2400, 1, 101)] + _rewind_rows()
    out = _build("ARAM", rewind_rows=rows)
    # (450, 2400) queues newest-first: 2400 W, 450 L, 450 W.
    assert out["last20"]["results"] == ["W", "L", "W"]
    assert out["last20"]["wins"] == 2
    assert out["last20"]["losses"] == 1
    assert out["last20"]["win_rate"] == 66.7


def test_last20_aram_no_rewind_db_fail_soft():
    # No rewind_history.db at all -> probe cannot run -> {} (fail-soft).
    out = _build("ARAM")
    assert out["last20"] == {}


def test_last20_queue_constants_single_truth():
    import dashboard.builders_home as H
    assert H._LAST20_QUEUES["SR"] == (400, 420, 430, 440, 480, 490)
    assert H._LAST20_QUEUES["ARAM"] == (450, 2400)
    assert H._LAST20_QUEUES["ARENA"] == (1700, 1710)


def test_compute_last20_no_arg_byte_identical():
    # builders.py contract: the no-arg / queue_ids=None call is byte-
    # identical to pre-change behavior (History call site untouched).
    from dashboard.builders import _compute_last20
    with TemporaryDirectory() as td:
        db = Path(td) / "rewind_history.db"
        _make_rewind_db(db, _rewind_rows())
        conn = sqlite3.connect(str(db))
        try:
            expected = {
                "results": ["W", "L", "W", "L", "W", "W"],
                "wins": 4, "losses": 2, "win_rate": 66.7,
            }
            assert _compute_last20(conn) == expected
            assert _compute_last20(conn, None) == expected
            # and the param actually filters when set:
            sr = _compute_last20(conn, (400, 420, 430, 440, 480, 490))
            assert sr["results"] == ["W", "L"]
        finally:
            conn.close()
