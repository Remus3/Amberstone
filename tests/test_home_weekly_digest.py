"""OQ13 slice A: mode-factored weekly Good/Bad/Ugly digest.

`_home_weekly_digest` aggregates the home 7-day window per GAME MODE and
judges each mode against its own benchmark row (`_MODE_BENCH`) - the
existing `_home_pick_tips` lines are mode-blind, which mis-grades ARAM
(live 7d: ARAM averages 11.7 deaths/game + 2.0 CS/min while SR sits at
8.8 + 6.6; neither is a flag IN ITS OWN MODE). Pure-function tests hit
`_home_weekly_digest` directly; one payload-boundary test pins
``out["weekly_digest"]`` off a throwaway temp match_history.db (no
gitignored data read - passes on a clean checkout / CI).

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

from dashboard.builders_home import _home_weekly_digest  # noqa: E402


def _rows(mode, n, k, d, a, cs, dur, grade="B"):
    """n identical (mode, grade, kills, deaths, assists, cs, game_time_s)
    tuples - the exact row shape `_build_home_summary`'s week cursor yields."""
    return [(mode, grade, k, d, a, cs, dur)] * n


def _mode(digest, name):
    for m in digest["modes"]:
        if m["mode"] == name:
            return m
    raise AssertionError(f"mode {name} missing from digest: {digest}")


# -- MODE-FACTORING CORE ------------------------------------------------------

def test_identical_stats_aram_lenient_sr_strict():
    """The keystone: the SAME raw stats (4 games, 10.0 deaths/game,
    2.0 CS/min, 2.0 avg KDA) are fine in ARAM but flagged in SR."""
    aram = _mode(_home_weekly_digest(_rows("ARAM", 4, 10, 10, 10, 40, 1200)),
                 "ARAM")
    sr = _mode(_home_weekly_digest(_rows("SR", 4, 10, 10, 10, 40, 1200)),
               "SR")
    # Identical arithmetic ...
    assert aram["deaths_pg"] == sr["deaths_pg"] == 10.0
    assert aram["cs_per_min"] == sr["cs_per_min"] == 2.0
    assert aram["avg_kda"] == sr["avg_kda"] == 2.0
    # ... mode-factored verdicts.
    assert aram["bad"] == ""
    assert sr["bad"] == "10.0 deaths per game (bench 6 for SR)"


def test_aram_never_flags_cs():
    # 1.0 CS/min in ARAM (cspm_lo is None) with deaths under the 12 bench.
    m = _mode(_home_weekly_digest(_rows("ARAM", 4, 8, 5, 12, 20, 1200)),
              "ARAM")
    assert m["cs_per_min"] == 1.0
    assert m["bad"] == ""


def test_sr_flags_low_cs():
    # SR deaths_pg 3.0 (under the 6 bench) but 3.0 CS/min under the 6.0 bar.
    m = _mode(_home_weekly_digest(_rows("SR", 3, 2, 3, 2, 60, 1200)), "SR")
    assert m["deaths_pg"] == 3.0
    assert m["bad"] == "3.0 CS/min under the 6 bar"


def test_unknown_mode_uses_default_bench():
    # deaths_pg 9.0 > default 8.0 -> flagged with the default bench value.
    m = _mode(_home_weekly_digest(_rows("URF", 3, 5, 9, 5, 30, 1200)), "URF")
    assert m["bad"] == "9.0 deaths per game (bench 8 for URF)"


# -- small-sample suppression -------------------------------------------------

def test_small_sample_suppresses_good_and_bad():
    m = _mode(_home_weekly_digest(_rows("ARAM", 2, 10, 2, 10, 50, 900,
                                        grade="S")), "ARAM")
    assert m["good"] == ""
    assert m["bad"] == ""
    assert m["ugly"] == "Small sample - 2 games in ARAM"


def test_small_sample_singular_game_word():
    m = _mode(_home_weekly_digest(_rows("SR", 1, 1, 10, 1, 10, 900)), "SR")
    assert m["ugly"] == "Small sample - 1 game in SR"


# -- sort order + totals ------------------------------------------------------

def test_sort_games_desc_then_mode_asc_and_total_games():
    rows = (_rows("SR", 3, 5, 3, 5, 150, 1500)
            + _rows("ARAM", 3, 5, 3, 5, 150, 1500)
            + _rows("ARENA", 4, 5, 3, 5, 0, 900))
    d = _home_weekly_digest(rows)
    assert [m["mode"] for m in d["modes"]] == ["ARENA", "ARAM", "SR"]
    assert d["total_games"] == 10
    assert d["window_days"] == 7


def test_empty_rows_empty_digest():
    assert _home_weekly_digest([]) == {
        "window_days": 7, "total_games": 0, "modes": []}


# -- arithmetic ---------------------------------------------------------------

def test_arithmetic_hand_computed():
    rows = [
        ("SR", "A", 5, 4, 7, 200, 1800),
        ("SR", "B", 3, 2, 5, 180, 1500),
        ("SR", "C", 2, 2, 2, 100, 1200),
    ]
    m = _mode(_home_weekly_digest(rows), "SR")
    assert m["games"] == 3
    assert m["avg_kda"] == 3.0     # (10 + 14) / 8
    assert m["deaths_pg"] == 2.7   # 8 / 3
    assert m["cs_per_min"] == 6.4  # 480 cs / 75 min
    assert m["best_grade"] == "A"
    assert m["worst_grade"] == "C"
    # avg_kda 3.0 meets the SR kda_good bench -> KDA headline.
    assert m["good"] == "3.0 KDA over 3 games"
    assert m["bad"] == ""   # 2.7 deaths under 6; 6.4 CS/min over the bar
    assert m["ugly"] == ""  # no D/F, KDA over 1.0


def test_zero_time_cs_per_min_is_zero():
    m = _mode(_home_weekly_digest(_rows("ARENA", 3, 5, 3, 5, 0, 0)), "ARENA")
    assert m["cs_per_min"] == 0.0


# -- grade lines --------------------------------------------------------------

def test_good_falls_back_to_best_grade_count():
    # avg KDA 1.53 below the ARAM 2.5 bench, but two S games headline.
    rows = [
        ("ARAM", "S", 4, 5, 6, 30, 1200),
        ("ARAM", "S", 3, 5, 5, 30, 1200),
        ("ARAM", "B", 2, 5, 3, 30, 1200),
    ]
    m = _mode(_home_weekly_digest(rows), "ARAM")
    assert m["good"] == "2x S-grade games"


def test_good_best_grade_count_singular():
    rows = [
        ("ARAM", "A", 4, 5, 6, 30, 1200),
        ("ARAM", "B", 3, 5, 5, 30, 1200),
        ("ARAM", "B", 2, 5, 3, 30, 1200),
    ]
    m = _mode(_home_weekly_digest(rows), "ARAM")
    assert m["good"] == "1x A-grade game"


def test_good_plain_best_grade_fallback():
    # KDA 0.8 under the bench and best grade B (not S/A) -> plain fallback.
    m = _mode(_home_weekly_digest(_rows("ARAM", 3, 2, 5, 2, 30, 1200)),
              "ARAM")
    assert m["good"] == "Best grade B"


def test_ugly_counts_worst_grade_games():
    rows = [
        ("SR", "F", 1, 8, 1, 100, 1500),
        ("SR", "F", 2, 7, 2, 100, 1500),
        ("SR", "D", 1, 6, 3, 100, 1500),
        ("SR", "A", 9, 2, 9, 200, 1500),
    ]
    m = _mode(_home_weekly_digest(rows), "SR")
    assert m["worst_grade"] == "F"
    assert m["ugly"] == "2 games graded F"
    # KDA under bench, one A game -> the S/A-count good fallback fires too.
    assert m["good"] == "1x A-grade game"


def test_ugly_singular_grade_and_kda_floor():
    rows = [
        ("ARAM", "B", 1, 9, 2, 30, 1200),
        ("ARAM", "D", 1, 9, 2, 30, 1200),
        ("ARAM", "B", 1, 9, 2, 30, 1200),
    ]
    m = _mode(_home_weekly_digest(rows), "ARAM")
    assert m["ugly"] == "1 game graded D"
    # No D/F at all -> falls to the KDA-under-1.0 line.
    m2 = _mode(_home_weekly_digest(_rows("ARAM", 3, 1, 9, 2, 30, 1200)),
               "ARAM")
    assert m2["avg_kda"] < 1.0
    assert m2["ugly"] == "KDA under 1.0 - rough week"


def test_no_grades_renders_dash():
    rows = [
        ("ARAM", "", 5, 5, 5, 30, 1200),
        ("ARAM", None, 5, 5, 5, 30, 1200),
        ("ARAM", "", 5, 5, 5, 30, 1200),
    ]
    m = _mode(_home_weekly_digest(rows), "ARAM")
    assert m["best_grade"] == "-"
    assert m["worst_grade"] == "-"


def test_lines_are_ascii():
    rows = (_rows("ARAM", 4, 10, 10, 10, 40, 1200)
            + _rows("SR", 4, 10, 10, 10, 40, 1200, grade="F")
            + _rows("BRAWL", 1, 1, 1, 1, 1, 100))
    for m in _home_weekly_digest(rows)["modes"]:
        for key in ("good", "bad", "ugly"):
            assert all(ord(c) < 128 for c in m[key]), repr(m[key])


# -- payload boundary ---------------------------------------------------------

def _make_match_db(path: Path, rows) -> None:
    """Throwaway match_history.db mirroring the live matches schema (same
    columns the test_home_last20 boundary fixture creates). ``rows`` is a
    list of (ts, mode, champion, grade, kills, deaths, assists, cs, dur)."""
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


def test_payload_boundary_weekly_digest_shape_and_tft_excluded():
    import dashboard.builders_home as H
    from tests.test_home_last20 import _evict_under
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with TemporaryDirectory() as td:
        app_dir = Path(td)
        (app_dir / "data").mkdir()
        _make_match_db(app_dir / "data" / "match_history.db", [
            (now, "ARAM", "Lux", "A", 10, 8, 12, 40, 1200),
            (now, "ARAM", "Jinx", "B", 6, 9, 10, 30, 1100),
            (now, "ARAM", "Sona", "S", 4, 7, 20, 25, 1000),
            (now, "SR", "Garen", "C", 3, 4, 5, 180, 1800),
            (now, "TFT", "Dark Star Vertical", "A", 0, 0, 0, 0, 1500),
        ])
        try:
            # Pin rank to Unranked so the builder never touches a live LCU.
            with mock.patch.object(H, "_get_lcu_for_rank",
                                   return_value=None):
                with mock.patch.object(H, "_APP_DIR", app_dir):
                    out = H._build_home_summary()
        finally:
            _evict_under(app_dir)
    wd = out.get("weekly_digest")
    assert isinstance(wd, dict)
    assert wd["window_days"] == 7
    assert wd["total_games"] == 4  # the TFT row is excluded
    by_mode = {m["mode"]: m for m in wd["modes"]}
    assert set(by_mode) == {"ARAM", "SR"}  # no TFT entry
    assert wd["modes"][0]["mode"] == "ARAM"  # 3 games sorts first
    assert by_mode["ARAM"]["games"] == 3
    assert by_mode["SR"]["games"] == 1
    assert by_mode["SR"]["ugly"] == "Small sample - 1 game in SR"
    for m in wd["modes"]:
        assert {"mode", "games", "avg_kda", "deaths_pg", "cs_per_min",
                "best_grade", "worst_grade", "good", "bad", "ugly"} <= set(m)
