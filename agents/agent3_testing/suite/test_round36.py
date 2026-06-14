"""Round 36 - game-duration analysis."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path


def _init(tmp_path: Path, monkeypatch):
    import agents.agent2_backend.db_schema as dbs
    from coaches import adaptation_hint
    monkeypatch.setattr(dbs, "DB_DIR", tmp_path)
    monkeypatch.setattr(adaptation_hint, "DB_DIR", tmp_path)
    for mode in ("aram", "sr_ranked"):
        dbs.init_mode(mode)


def _insert(db: Path, champ: str, win: int | None, duration_sec: int,
            k: int | None = 0, d: int | None = 0, a: int | None = 0) -> None:
    with sqlite3.connect(db) as conn:
        conn.execute(
            """INSERT INTO matches
               (started_at, champion, ally_champions, enemy_champions,
                duration_sec, win, source, kills, deaths, assists)
               VALUES ('2026-04-22T00:00:00+00:00', ?, '[]', '[]',
                       ?, ?, 'live-phase3', ?, ?, ?)""",
            (champ, duration_sec, win, k, d, a),
        )
        conn.commit()


# -- tier bucketing --------------------------------------------------

def test_tier_boundaries(tmp_path: Path, monkeypatch) -> None:
    """14:59 → stomp, 15:00 → quick, 24:59 → quick, 25:00 → standard,
    34:59 → standard, 35:00 → long."""
    from coaches.adaptation_hint import duration_analysis
    _init(tmp_path, monkeypatch)
    for dur in (14 * 60 + 59, 15 * 60, 24 * 60 + 59,
                25 * 60, 34 * 60 + 59, 35 * 60):
        _insert(tmp_path / "aram.db", "Ahri", 1, dur, 5, 2, 7)
    data = duration_analysis(mode="aram", min_games=1)
    by_tier = {b["tier"]: b for b in data["buckets"]}
    assert by_tier["stomp"]["games"] == 1
    assert by_tier["quick"]["games"] == 2
    assert by_tier["standard"]["games"] == 2
    assert by_tier["long"]["games"] == 1


def test_four_tiers_always_returned(tmp_path: Path, monkeypatch) -> None:
    from coaches.adaptation_hint import duration_analysis
    _init(tmp_path, monkeypatch)
    data = duration_analysis()
    assert [b["tier"] for b in data["buckets"]] == \
           ["stomp", "quick", "standard", "long"]
    assert all(b["games"] == 0 for b in data["buckets"])


def test_null_and_zero_durations_skipped(tmp_path: Path, monkeypatch) -> None:
    """duration_sec IS NULL or 0 shouldn't count - they're incomplete rows."""
    from coaches.adaptation_hint import duration_analysis
    _init(tmp_path, monkeypatch)
    # 2 valid rows.
    _insert(tmp_path / "aram.db", "Ahri", 1, 1200, 5, 2, 7)
    _insert(tmp_path / "aram.db", "Ahri", 0, 1800, 3, 8, 2)
    # Invalid rows.
    with sqlite3.connect(tmp_path / "aram.db") as conn:
        conn.execute(
            """INSERT INTO matches
               (started_at, champion, ally_champions, enemy_champions,
                duration_sec, win, source, kills, deaths, assists)
               VALUES ('2026-04-22T00:00:00+00:00', 'Ahri', '[]', '[]',
                       NULL, 1, 'live-phase3', 5, 2, 7)"""
        )
        conn.execute(
            """INSERT INTO matches
               (started_at, champion, ally_champions, enemy_champions,
                duration_sec, win, source)
               VALUES ('2026-04-22T00:00:00+00:00', 'Ahri', '[]', '[]',
                       0, 1, 'live-phase3')"""
        )
        conn.commit()
    data = duration_analysis(mode="aram", min_games=1)
    assert data["total_games"] == 2


def test_best_worst_by_wr(tmp_path: Path, monkeypatch) -> None:
    from coaches.adaptation_hint import duration_analysis
    _init(tmp_path, monkeypatch)
    # Stomp tier: 1 win / 4 losses = 20% wr.
    _insert(tmp_path / "aram.db", "Ahri", 1, 600, 10, 5, 3)
    for _ in range(4):
        _insert(tmp_path / "aram.db", "Ahri", 0, 600, 3, 10, 5)
    # Long tier: 4 wins / 1 loss = 80% wr.
    for _ in range(4):
        _insert(tmp_path / "aram.db", "Ahri", 1, 3000, 10, 3, 15)
    _insert(tmp_path / "aram.db", "Ahri", 0, 3000, 3, 10, 5)
    data = duration_analysis(mode="aram", min_games=3)
    assert data["best"]["tier"] == "long"
    assert data["worst"]["tier"] == "stomp"


def test_champion_filter(tmp_path: Path, monkeypatch) -> None:
    from coaches.adaptation_hint import duration_analysis
    _init(tmp_path, monkeypatch)
    _insert(tmp_path / "aram.db", "Ahri", 1, 1200, 5, 2, 7)
    _insert(tmp_path / "aram.db", "Jinx", 0, 1200, 3, 8, 2)
    ahri = duration_analysis(mode="aram", champion="Ahri", min_games=1)
    assert ahri["total_games"] == 1
    assert ahri["champion"] == "Ahri"


def test_mode_filter(tmp_path: Path, monkeypatch) -> None:
    from coaches.adaptation_hint import duration_analysis
    _init(tmp_path, monkeypatch)
    _insert(tmp_path / "aram.db", "Ahri", 1, 1200, 5, 2, 7)
    _insert(tmp_path / "sr_ranked.db", "Vlad", 1, 2000, 5, 2, 7)
    assert duration_analysis(mode="aram")["total_games"] == 1
    assert duration_analysis()["total_games"] == 2


def test_kda_ratio_per_tier(tmp_path: Path, monkeypatch) -> None:
    from coaches.adaptation_hint import duration_analysis
    _init(tmp_path, monkeypatch)
    # Two long games: mean 10/4/15 -> (10+15)/4 = 6.25.
    _insert(tmp_path / "aram.db", "Ahri", 1, 3000, 10, 3, 15)
    _insert(tmp_path / "aram.db", "Ahri", 1, 3000, 10, 5, 15)
    data = duration_analysis(mode="aram", min_games=1)
    long_t = next(b for b in data["buckets"] if b["tier"] == "long")
    assert long_t["kda_ratio"] == 6.25


def test_min_games_flag(tmp_path: Path, monkeypatch) -> None:
    """Low-sample tier gets insight=False."""
    from coaches.adaptation_hint import duration_analysis
    _init(tmp_path, monkeypatch)
    _insert(tmp_path / "aram.db", "Ahri", 1, 600, 10, 3, 15)   # 1 stomp
    for _ in range(5):
        _insert(tmp_path / "aram.db", "Ahri", 1, 1800, 10, 3, 15)   # 5 standard
    data = duration_analysis(mode="aram", min_games=3)
    stomp = next(b for b in data["buckets"] if b["tier"] == "stomp")
    standard = next(b for b in data["buckets"] if b["tier"] == "standard")
    assert stomp["insight"] is False
    assert standard["insight"] is True
    # Best must be standard, not stomp.
    assert data["best"]["tier"] == "standard"


# -- CLI -------------------------------------------------------------

def test_cli_duration_json(tmp_path: Path, monkeypatch, capsys) -> None:
    from coaches.adaptation_hint import main
    _init(tmp_path, monkeypatch)
    for _ in range(3):
        _insert(tmp_path / "aram.db", "Ahri", 1, 3000, 10, 3, 15)
    rc = main(["--duration", "-m", "aram", "-f", "json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["total_games"] == 3
    long_t = next(b for b in data["buckets"] if b["tier"] == "long")
    assert long_t["games"] == 3


def test_cli_duration_text(tmp_path: Path, monkeypatch, capsys) -> None:
    from coaches.adaptation_hint import main
    _init(tmp_path, monkeypatch)
    for _ in range(3):
        _insert(tmp_path / "aram.db", "Ahri", 1, 3000, 10, 3, 15)
    rc = main(["--duration", "-m", "aram"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Duration breakdown" in out
    assert "long" in out
    assert "best: long" in out


def test_cli_duration_champion_filter(tmp_path: Path, monkeypatch, capsys) -> None:
    from coaches.adaptation_hint import main
    _init(tmp_path, monkeypatch)
    for _ in range(3):
        _insert(tmp_path / "aram.db", "Ahri", 1, 1200, 10, 3, 15)
    _insert(tmp_path / "aram.db", "Jinx", 1, 1200, 10, 3, 15)
    rc = main(["--duration", "-m", "aram", "-c", "Ahri", "-f", "json"])
    data = json.loads(capsys.readouterr().out)
    assert data["total_games"] == 3
    assert data["champion"] == "Ahri"


def test_cli_duration_cross_mode_default(tmp_path: Path, monkeypatch, capsys) -> None:
    from coaches.adaptation_hint import main
    _init(tmp_path, monkeypatch)
    _insert(tmp_path / "aram.db", "Ahri", 1, 1200, 5, 2, 7)
    _insert(tmp_path / "sr_ranked.db", "Vlad", 1, 2000, 5, 2, 7)
    rc = main(["--duration", "-f", "json"])
    data = json.loads(capsys.readouterr().out)
    assert data["mode"] == "all"
    assert data["total_games"] == 2


# -- supervisor route ------------------------------------------------

def test_supervisor_registers_duration_route() -> None:
    # s243: handler split byte-verbatim into _supervisor_http.py
    # (supervisor.py is now a facade); runtime routing unchanged.
    sup = Path("agents/_supervisor_http.py").read_text(encoding="utf-8")
    assert "/api/duration" in sup
    assert "_handle_duration" in sup
