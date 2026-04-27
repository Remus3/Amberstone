"""Round 28 — adaptation_hint CLI."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path


def _init(tmp_path: Path, monkeypatch):
    import agents.agent2_backend.db_schema as dbs
    from coaches import adaptation_hint
    monkeypatch.setattr(dbs, "DB_DIR", tmp_path)
    monkeypatch.setattr(adaptation_hint, "DB_DIR", tmp_path)
    dbs.init_mode("aram")


def _seed(db: Path, champ: str, aj: dict, games: int = 20, wr: float = 0.55) -> None:
    with sqlite3.connect(db) as conn:
        conn.execute(
            """INSERT INTO adaptation_buckets
               (champion, games_played, wins, losses, avg_rating, last_updated, aggregates_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (champ, games, int(games * wr), games - int(games * wr), wr,
             "2026-04-22T00:00:00Z", json.dumps(aj)),
        )
        conn.commit()


def test_cli_hint_format(tmp_path: Path, monkeypatch, capsys) -> None:
    from coaches.adaptation_hint import main
    _init(tmp_path, monkeypatch)
    _seed(tmp_path / "aram.db", "Ahri", {
        "win_rate": 0.55,
        "avg_kda": {"k": 9, "d": 5, "a": 15, "ratio": 4.8, "sample": 20},
    })
    rc = main(["--champion", "Ahri", "--mode", "aram", "--format", "hint"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Ahri" in out
    assert "ARAM baseline" in out
    assert "typical KDA 4.8" in out


def test_cli_card_format(tmp_path: Path, monkeypatch, capsys) -> None:
    from coaches.adaptation_hint import main
    _init(tmp_path, monkeypatch)
    _seed(tmp_path / "aram.db", "Ahri", {
        "win_rate": 0.55,
        "avg_kda": {"k": 9, "d": 5, "a": 15, "ratio": 4.8, "sample": 20},
    })
    rc = main(["-c", "Ahri", "-m", "aram", "-f", "card"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "KDA 4.8" in out
    # Compact card uses ' · ' separators.
    assert " · " in out


def test_cli_json_format(tmp_path: Path, monkeypatch, capsys) -> None:
    from coaches.adaptation_hint import main
    _init(tmp_path, monkeypatch)
    _seed(tmp_path / "aram.db", "Ahri", {
        "win_rate": 0.55,
        "avg_kda": {"k": 9, "d": 5, "a": 15, "ratio": 4.8, "sample": 20},
    })
    rc = main(["-c", "Ahri", "-m", "aram", "-f", "json"])
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["champion"] == "Ahri"
    assert data["avg_kda"]["ratio"] == 4.8
    # json output also carries a precomputed hint string.
    assert "hint" in data


def test_cli_no_data_fallback(tmp_path: Path, monkeypatch, capsys) -> None:
    from coaches.adaptation_hint import main
    _init(tmp_path, monkeypatch)
    rc = main(["-c", "Unknown", "-m", "aram"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "no data" in out.lower()


def test_cli_trends_text(tmp_path: Path, monkeypatch, capsys) -> None:
    from coaches.adaptation_hint import main
    _init(tmp_path, monkeypatch)
    _seed(tmp_path / "aram.db", "Heater", {
        "avg_kda": {"ratio": 2.0, "sample": 20},
        "recent_kda": {"ratio": 5.0, "sample": 10, "delta_ratio": 3.0},
    })
    _seed(tmp_path / "aram.db", "Cooler", {
        "avg_kda": {"ratio": 4.0, "sample": 20},
        "recent_kda": {"ratio": 2.5, "sample": 10, "delta_ratio": -1.5},
    })
    rc = main(["--trends", "--mode", "aram"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "ARAM KDA streaks" in out
    assert "Heater" in out
    assert "+3.00" in out
    assert "Cooler" in out
    assert "-1.50" in out


def test_cli_trends_json(tmp_path: Path, monkeypatch, capsys) -> None:
    from coaches.adaptation_hint import main
    _init(tmp_path, monkeypatch)
    _seed(tmp_path / "aram.db", "Heater", {
        "avg_kda": {"ratio": 2.0, "sample": 20},
        "recent_kda": {"ratio": 5.0, "sample": 10, "delta_ratio": 3.0},
    })
    rc = main(["--trends", "-m", "aram", "-f", "json"])
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["mode"] == "aram"
    assert data["hot"][0]["champion"] == "Heater"


def test_cli_trends_empty(tmp_path: Path, monkeypatch, capsys) -> None:
    from coaches.adaptation_hint import main
    _init(tmp_path, monkeypatch)
    rc = main(["--trends", "-m", "aram"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "no recent-window sample" in out


def test_cli_enemies_surface_in_hint(tmp_path: Path, monkeypatch, capsys) -> None:
    from coaches.adaptation_hint import main
    _init(tmp_path, monkeypatch)
    _seed(tmp_path / "aram.db", "Ahri", {"win_rate": 0.60})
    with sqlite3.connect(tmp_path / "aram.db") as conn:
        mj = {"sample": 5, "observed_wr": 0.20, "baseline_wr": 0.60, "delta": -0.40}
        conn.execute(
            """INSERT INTO matchup_modifiers
               (champion, opponent_signature, sample_count, activated, modifier_json, last_updated)
               VALUES ('Ahri', 'Zed', 5, 1, ?, '2026-04-22T00:00:00Z')""",
            (json.dumps(mj),),
        )
        conn.commit()
    rc = main(["-c", "Ahri", "-m", "aram", "-e", "Zed,Jinx"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "vs Zed" in out


def test_cli_requires_champion_when_not_trends(tmp_path: Path, monkeypatch) -> None:
    """argparse should error when --champion missing & --trends absent."""
    import pytest
    from coaches.adaptation_hint import main
    _init(tmp_path, monkeypatch)
    with pytest.raises(SystemExit):
        main(["--mode", "aram"])
