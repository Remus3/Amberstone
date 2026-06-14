"""Round 35 - day-of-week analysis."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
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


def _on_weekday(target_wd: int, hour: int = 14) -> str:
    """Build an ISO timestamp landing on the requested local weekday."""
    now = datetime.now().astimezone().replace(
        hour=hour, minute=0, second=0, microsecond=0,
    )
    # Step back up to 6 days to land on the target weekday.
    days_back = (now.weekday() - target_wd) % 7
    return (now - timedelta(days=days_back)).isoformat()


# -- bucketing -------------------------------------------------------

def test_bucketing_by_local_weekday(tmp_path: Path, monkeypatch) -> None:
    from coaches.adaptation_hint import day_of_week_analysis
    _init(tmp_path, monkeypatch)
    # 3 Mon wins, 2 Fri losses.
    for _ in range(3):
        _insert(tmp_path / "aram.db", "Ahri", 1, 10, 3, 15, _on_weekday(0))
    for _ in range(2):
        _insert(tmp_path / "aram.db", "Ahri", 0, 3, 10, 5, _on_weekday(4))

    data = day_of_week_analysis(mode="aram")
    mon = next(b for b in data["buckets"] if b["weekday"] == 0)
    fri = next(b for b in data["buckets"] if b["weekday"] == 4)
    assert mon["name"] == "Mon"
    assert mon["games"] == 3 and mon["win_rate"] == 1.0
    assert fri["name"] == "Fri"
    assert fri["games"] == 2 and fri["win_rate"] == 0.0


def test_returns_all_7_buckets(tmp_path: Path, monkeypatch) -> None:
    from coaches.adaptation_hint import day_of_week_analysis
    _init(tmp_path, monkeypatch)
    data = day_of_week_analysis()
    assert len(data["buckets"]) == 7
    assert [b["name"] for b in data["buckets"]] == \
           ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    assert all(b["games"] == 0 for b in data["buckets"])


def test_best_worst_require_min_games(tmp_path: Path, monkeypatch) -> None:
    from coaches.adaptation_hint import day_of_week_analysis
    _init(tmp_path, monkeypatch)
    # Saturday: 1 lucky win.
    _insert(tmp_path / "aram.db", "Ahri", 1, 10, 0, 20, _on_weekday(5))
    # Wednesday: 4 wins + 1 loss (real best).
    for _ in range(4):
        _insert(tmp_path / "aram.db", "Ahri", 1, 10, 3, 15, _on_weekday(2))
    _insert(tmp_path / "aram.db", "Ahri", 0, 3, 10, 5, _on_weekday(2))
    data = day_of_week_analysis(mode="aram", min_games=3)
    assert data["best"]["name"] == "Wed"
    sat = next(b for b in data["buckets"] if b["name"] == "Sat")
    assert sat["insight"] is False


def test_mode_filter(tmp_path: Path, monkeypatch) -> None:
    from coaches.adaptation_hint import day_of_week_analysis
    _init(tmp_path, monkeypatch)
    _insert(tmp_path / "aram.db", "Ahri", 1, 10, 3, 15, _on_weekday(2))
    _insert(tmp_path / "sr_ranked.db", "Vlad", 0, 3, 10, 5, _on_weekday(2))
    assert day_of_week_analysis(mode="aram")["total_games"] == 1
    assert day_of_week_analysis()["total_games"] == 2


def test_since_filter(tmp_path: Path, monkeypatch) -> None:
    from coaches.adaptation_hint import day_of_week_analysis
    _init(tmp_path, monkeypatch)
    now = datetime.now().astimezone()
    _insert(tmp_path / "aram.db", "Ahri", 1, 10, 3, 15,
            (now - timedelta(days=60)).isoformat())
    _insert(tmp_path / "aram.db", "Ahri", 1, 10, 3, 15,
            (now - timedelta(days=2)).isoformat())
    data = day_of_week_analysis(
        mode="aram",
        since_iso=(now - timedelta(days=14)).isoformat(),
    )
    assert data["total_games"] == 1


def test_kda_ratio_per_weekday(tmp_path: Path, monkeypatch) -> None:
    from coaches.adaptation_hint import day_of_week_analysis
    _init(tmp_path, monkeypatch)
    _insert(tmp_path / "aram.db", "Ahri", 1, 10, 3, 15, _on_weekday(2))
    _insert(tmp_path / "aram.db", "Ahri", 1, 10, 5, 15, _on_weekday(2))
    data = day_of_week_analysis(mode="aram", min_games=1)
    wed = next(b for b in data["buckets"] if b["name"] == "Wed")
    # Mean 10/4/15 -> (10+15)/4 = 6.25.
    assert wed["kda_sample"] == 2
    assert wed["kda_ratio"] == 6.25


# -- CLI -------------------------------------------------------------

def test_cli_weekday_json(tmp_path: Path, monkeypatch, capsys) -> None:
    from coaches.adaptation_hint import main
    _init(tmp_path, monkeypatch)
    for _ in range(3):
        _insert(tmp_path / "aram.db", "Ahri", 1, 10, 3, 15, _on_weekday(2))
    rc = main(["--weekday", "-m", "aram", "-f", "json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["total_games"] == 3
    wed = next(b for b in data["buckets"] if b["name"] == "Wed")
    assert wed["games"] == 3


def test_cli_weekday_text(tmp_path: Path, monkeypatch, capsys) -> None:
    from coaches.adaptation_hint import main
    _init(tmp_path, monkeypatch)
    for _ in range(3):
        _insert(tmp_path / "aram.db", "Ahri", 1, 10, 3, 15, _on_weekday(2))
    rc = main(["--weekday", "-m", "aram"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Day-of-week breakdown" in out
    assert "Wed" in out
    assert "best: Wed" in out


def test_cli_weekday_cross_mode_default(tmp_path: Path, monkeypatch, capsys) -> None:
    from coaches.adaptation_hint import main
    _init(tmp_path, monkeypatch)
    _insert(tmp_path / "aram.db", "Ahri", 1, 10, 3, 15, _on_weekday(2))
    _insert(tmp_path / "sr_ranked.db", "Vlad", 1, 10, 3, 15, _on_weekday(2))
    rc = main(["--weekday", "-f", "json"])
    data = json.loads(capsys.readouterr().out)
    assert data["mode"] == "all"
    assert data["total_games"] == 2


# -- supervisor route ------------------------------------------------

def test_supervisor_registers_day_of_week_route() -> None:
    # s243: handler split byte-verbatim into _supervisor_http.py
    # (supervisor.py is now a facade); runtime routing unchanged.
    sup = Path("agents/_supervisor_http.py").read_text(encoding="utf-8")
    assert "/api/day-of-week" in sup
    assert "_handle_day_of_week" in sup
