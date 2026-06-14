"""Round 34 - time-of-day performance analysis."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _init(tmp_path: Path, monkeypatch):
    import agents.agent2_backend.db_schema as dbs
    from coaches import adaptation_hint
    monkeypatch.setattr(dbs, "DB_DIR", tmp_path)
    monkeypatch.setattr(adaptation_hint, "DB_DIR", tmp_path)
    for mode in ("aram", "sr_ranked"):
        dbs.init_mode(mode)


def _insert(db: Path, champ: str, win: int | None,
            k: int | None, d: int | None, a: int | None,
            started_at: str) -> None:
    with sqlite3.connect(db) as conn:
        conn.execute(
            """INSERT INTO matches
               (started_at, champion, ally_champions, enemy_champions,
                duration_sec, win, source, kills, deaths, assists)
               VALUES (?, ?, '[]', '[]', 1200, ?, 'live-phase3', ?, ?, ?)""",
            (started_at, champ, win, k, d, a),
        )
        conn.commit()


def _at_local_hour(hour: int, days_ago: int = 0) -> str:
    """Build an ISO timestamp that lands at the given local hour."""
    now = datetime.now().astimezone()
    dt = now.replace(hour=hour, minute=0, second=0, microsecond=0) \
            - timedelta(days=days_ago)
    return dt.isoformat()


# -- bucketing -------------------------------------------------------

def test_time_of_day_bucketing_by_local_hour(tmp_path: Path, monkeypatch) -> None:
    from coaches.adaptation_hint import time_of_day_analysis
    _init(tmp_path, monkeypatch)
    # 3 morning games (09:xx local), 2 late-night (23:xx local).
    for _ in range(3):
        _insert(tmp_path / "aram.db", "Ahri", 1, 10, 3, 15, _at_local_hour(9))
    for _ in range(2):
        _insert(tmp_path / "aram.db", "Ahri", 0, 3, 10, 5, _at_local_hour(23))

    data = time_of_day_analysis(mode="aram")
    assert data["mode"] == "aram"
    assert data["total_games"] == 5
    hour9 = next(b for b in data["buckets"] if b["hour"] == 9)
    hour23 = next(b for b in data["buckets"] if b["hour"] == 23)
    assert hour9["games"] == 3
    assert hour9["wins"] == 3
    assert hour9["win_rate"] == 1.0
    assert hour23["games"] == 2
    assert hour23["losses"] == 2
    assert hour23["win_rate"] == 0.0


def test_returns_all_24_buckets_even_when_empty(tmp_path: Path, monkeypatch) -> None:
    from coaches.adaptation_hint import time_of_day_analysis
    _init(tmp_path, monkeypatch)
    data = time_of_day_analysis()
    assert len(data["buckets"]) == 24
    assert all(b["games"] == 0 for b in data["buckets"])
    assert data["best"] is None and data["worst"] is None


def test_best_and_worst_picked_from_insightful_buckets(tmp_path: Path, monkeypatch) -> None:
    from coaches.adaptation_hint import time_of_day_analysis
    _init(tmp_path, monkeypatch)
    # Hour 15: 5 wins, 0 losses - clearly best.
    for _ in range(5):
        _insert(tmp_path / "aram.db", "Ahri", 1, 10, 3, 15, _at_local_hour(15))
    # Hour 2: 1 win, 4 losses - worst.
    _insert(tmp_path / "aram.db", "Jinx", 1, 10, 3, 15, _at_local_hour(2))
    for _ in range(4):
        _insert(tmp_path / "aram.db", "Jinx", 0, 3, 10, 5, _at_local_hour(2))
    data = time_of_day_analysis(mode="aram", min_games=3)
    assert data["best"]["hour"] == 15
    assert data["worst"]["hour"] == 2


def test_min_games_filter_excludes_outliers(tmp_path: Path, monkeypatch) -> None:
    """A single-game bucket with 100% wr must NOT be picked as best."""
    from coaches.adaptation_hint import time_of_day_analysis
    _init(tmp_path, monkeypatch)
    # Hour 4: 1 lucky win.
    _insert(tmp_path / "aram.db", "Ahri", 1, 10, 0, 20, _at_local_hour(4))
    # Hour 15: 4 wins, 1 loss - our real best.
    for _ in range(4):
        _insert(tmp_path / "aram.db", "Ahri", 1, 10, 3, 15, _at_local_hour(15))
    _insert(tmp_path / "aram.db", "Ahri", 0, 3, 10, 5, _at_local_hour(15))
    data = time_of_day_analysis(mode="aram", min_games=3)
    assert data["best"]["hour"] == 15
    # Hour 4 should show up but flagged not-insight.
    hour4 = next(b for b in data["buckets"] if b["hour"] == 4)
    assert hour4["insight"] is False


def test_mode_filter_isolates_mode(tmp_path: Path, monkeypatch) -> None:
    from coaches.adaptation_hint import time_of_day_analysis
    _init(tmp_path, monkeypatch)
    _insert(tmp_path / "aram.db", "Ahri", 1, 10, 3, 15, _at_local_hour(9))
    _insert(tmp_path / "sr_ranked.db", "Vladimir", 0, 3, 10, 5, _at_local_hour(9))
    aram = time_of_day_analysis(mode="aram")
    sr = time_of_day_analysis(mode="sr_ranked")
    all_modes = time_of_day_analysis()
    assert aram["total_games"] == 1
    assert sr["total_games"] == 1
    assert all_modes["total_games"] == 2


def test_since_filter_clips_old_games(tmp_path: Path, monkeypatch) -> None:
    from coaches.adaptation_hint import time_of_day_analysis
    _init(tmp_path, monkeypatch)
    now = datetime.now().astimezone()
    _insert(tmp_path / "aram.db", "Ahri", 1, 10, 3, 15,
            (now - timedelta(days=100)).isoformat())
    _insert(tmp_path / "aram.db", "Ahri", 1, 10, 3, 15,
            (now - timedelta(hours=2)).isoformat())
    recent = time_of_day_analysis(
        mode="aram",
        since_iso=(now - timedelta(days=1)).isoformat(),
    )
    assert recent["total_games"] == 1


def test_kda_ratio_per_bucket(tmp_path: Path, monkeypatch) -> None:
    from coaches.adaptation_hint import time_of_day_analysis
    _init(tmp_path, monkeypatch)
    # All at hour 15, two games -> mean 10/4/15 -> (10+15)/4 = 6.25.
    _insert(tmp_path / "aram.db", "Ahri", 1, 10, 3, 15, _at_local_hour(15))
    _insert(tmp_path / "aram.db", "Ahri", 1, 10, 5, 15, _at_local_hour(15))
    data = time_of_day_analysis(mode="aram", min_games=1)
    hour15 = next(b for b in data["buckets"] if b["hour"] == 15)
    assert hour15["kda_sample"] == 2
    assert hour15["kda_ratio"] == 6.25


# -- CLI -------------------------------------------------------------

def test_cli_hourly_json(tmp_path: Path, monkeypatch, capsys) -> None:
    from coaches.adaptation_hint import main
    _init(tmp_path, monkeypatch)
    for _ in range(3):
        _insert(tmp_path / "aram.db", "Ahri", 1, 10, 3, 15, _at_local_hour(15))
    rc = main(["--hourly", "-m", "aram", "-f", "json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["total_games"] == 3
    assert any(b["hour"] == 15 and b["games"] == 3 for b in data["buckets"])


def test_cli_hourly_text(tmp_path: Path, monkeypatch, capsys) -> None:
    from coaches.adaptation_hint import main
    _init(tmp_path, monkeypatch)
    for _ in range(3):
        _insert(tmp_path / "aram.db", "Ahri", 1, 10, 3, 15, _at_local_hour(15))
    rc = main(["--hourly", "-m", "aram"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Time-of-day breakdown" in out
    assert "best: 15h" in out


def test_cli_hourly_cross_mode_default(tmp_path: Path, monkeypatch, capsys) -> None:
    """Without --mode, the CLI runs across all modes."""
    from coaches.adaptation_hint import main
    _init(tmp_path, monkeypatch)
    _insert(tmp_path / "aram.db", "Ahri", 1, 10, 3, 15, _at_local_hour(15))
    _insert(tmp_path / "sr_ranked.db", "Vladimir", 1, 10, 3, 15, _at_local_hour(15))
    rc = main(["--hourly", "-f", "json"])
    data = json.loads(capsys.readouterr().out)
    assert data["mode"] == "all"
    assert data["total_games"] == 2


# -- supervisor endpoint ---------------------------------------------

def test_supervisor_registers_time_of_day_route() -> None:
    # s243: handler split byte-verbatim into _supervisor_http.py
    # (supervisor.py is now a facade); runtime routing unchanged.
    sup = Path("agents/_supervisor_http.py").read_text(encoding="utf-8")
    assert "/api/time-of-day" in sup
    assert "_handle_time_of_day" in sup
