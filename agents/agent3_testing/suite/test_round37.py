"""Round 37 - coaching_digest bundler."""
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


def _seed_bucket(db: Path, champ: str, aj: dict, wr: float = 0.5,
                 games: int = 20) -> None:
    with sqlite3.connect(db) as conn:
        wins = int(games * wr)
        conn.execute(
            """INSERT INTO adaptation_buckets
               (champion, games_played, wins, losses, avg_rating, last_updated, aggregates_json)
               VALUES (?, ?, ?, ?, ?, '2026-04-22T00:00:00Z', ?)""",
            (champ, games, wins, games - wins, wr, json.dumps(aj)),
        )
        conn.commit()


def _insert_match(db: Path, champ: str, win: int | None,
                  duration_sec: int, started_at: str,
                  k: int = 5, d: int = 5, a: int = 10) -> None:
    with sqlite3.connect(db) as conn:
        conn.execute(
            """INSERT INTO matches
               (started_at, champion, ally_champions, enemy_champions,
                duration_sec, win, source, kills, deaths, assists)
               VALUES (?, ?, '[]', '[]', ?, ?, 'live-phase3', ?, ?, ?)""",
            (started_at, champ, duration_sec, win, k, d, a),
        )
        conn.commit()


# ── digest assembly ─────────────────────────────────────────────────

def test_digest_picks_up_cold_streak(tmp_path: Path, monkeypatch) -> None:
    from coaches.adaptation_hint import coaching_digest
    _init(tmp_path, monkeypatch)
    _seed_bucket(tmp_path / "aram.db", "Jinx", {
        "win_rate": 0.55,
        "avg_kda": {"ratio": 4.0, "sample": 30},
        "recent_kda": {"ratio": 2.0, "sample": 10, "delta_ratio": -2.0},
    })
    d = coaching_digest(mode="aram", top_n=5)
    assert d["count"] >= 1
    ins = d["insights"][0]
    assert ins["type"] == "cold_streak"
    assert ins["champion"] == "Jinx"
    assert ins["severity"] == 1.0         # |delta|/2.0 clamped


def test_digest_hot_streak_capped_lower_than_cold(tmp_path: Path, monkeypatch) -> None:
    from coaches.adaptation_hint import coaching_digest
    _init(tmp_path, monkeypatch)
    _seed_bucket(tmp_path / "aram.db", "Heater", {
        "win_rate": 0.55,
        "avg_kda": {"ratio": 3.0, "sample": 30},
        "recent_kda": {"ratio": 6.0, "sample": 10, "delta_ratio": 3.0},
    })
    _seed_bucket(tmp_path / "aram.db", "Cooler", {
        "win_rate": 0.55,
        "avg_kda": {"ratio": 4.0, "sample": 30},
        "recent_kda": {"ratio": 2.0, "sample": 10, "delta_ratio": -2.0},
    })
    d = coaching_digest(mode="aram", top_n=10)
    cold = next(i for i in d["insights"] if i["champion"] == "Cooler")
    hot = next(i for i in d["insights"] if i["champion"] == "Heater")
    # Cold severity >= hot, by design (0.7 cap on hot).
    assert cold["severity"] >= hot["severity"]
    assert hot["severity"] <= 0.7


def test_digest_includes_worst_hour(tmp_path: Path, monkeypatch) -> None:
    from coaches.adaptation_hint import coaching_digest
    _init(tmp_path, monkeypatch)
    # 5 wins at 10am, 5 losses at 3am → 3am becomes the slump.
    now = datetime.now().astimezone()
    for _ in range(5):
        ts = now.replace(hour=10, minute=0, second=0, microsecond=0).isoformat()
        _insert_match(tmp_path / "aram.db", "Ahri", 1, 1200, ts)
    for _ in range(5):
        ts = now.replace(hour=3, minute=0, second=0, microsecond=0).isoformat()
        _insert_match(tmp_path / "aram.db", "Ahri", 0, 1200, ts)
    d = coaching_digest(mode="aram", top_n=10)
    types = {i["type"] for i in d["insights"]}
    assert "worst_hour" in types


def test_digest_sorted_by_severity(tmp_path: Path, monkeypatch) -> None:
    from coaches.adaptation_hint import coaching_digest
    _init(tmp_path, monkeypatch)
    # Big cold streak (sev 1.0)
    _seed_bucket(tmp_path / "aram.db", "Crash", {
        "win_rate": 0.5,
        "avg_kda": {"ratio": 5.0, "sample": 30},
        "recent_kda": {"ratio": 1.0, "sample": 10, "delta_ratio": -4.0},
    })
    # Small hot streak (sev ~0.2)
    _seed_bucket(tmp_path / "aram.db", "TinyHot", {
        "win_rate": 0.5,
        "avg_kda": {"ratio": 3.0, "sample": 30},
        "recent_kda": {"ratio": 3.4, "sample": 10, "delta_ratio": 0.4},
    })
    d = coaching_digest(mode="aram", top_n=5)
    sevs = [i["severity"] for i in d["insights"]]
    assert sevs == sorted(sevs, reverse=True)


def test_digest_respects_top_n(tmp_path: Path, monkeypatch) -> None:
    from coaches.adaptation_hint import coaching_digest
    _init(tmp_path, monkeypatch)
    for i in range(10):
        _seed_bucket(tmp_path / "aram.db", f"Cold{i}", {
            "win_rate": 0.5,
            "avg_kda": {"ratio": 4.0, "sample": 30},
            "recent_kda": {"ratio": 2.0, "sample": 10,
                           "delta_ratio": -1.0 - i * 0.1},
        })
    d = coaching_digest(mode="aram", top_n=3)
    assert len(d["insights"]) == 3


def test_digest_empty_when_no_data(tmp_path: Path, monkeypatch) -> None:
    from coaches.adaptation_hint import coaching_digest
    _init(tmp_path, monkeypatch)
    d = coaching_digest(mode="aram", top_n=5)
    assert d["insights"] == []
    assert d["count"] == 0


def test_digest_cross_mode_tags_insights(tmp_path: Path, monkeypatch) -> None:
    """When mode=None, per-mode insights are tagged with originating mode."""
    from coaches.adaptation_hint import coaching_digest
    _init(tmp_path, monkeypatch)
    _seed_bucket(tmp_path / "aram.db", "AramChamp", {
        "win_rate": 0.5,
        "avg_kda": {"ratio": 4.0, "sample": 30},
        "recent_kda": {"ratio": 2.0, "sample": 10, "delta_ratio": -2.0},
    })
    _seed_bucket(tmp_path / "sr_ranked.db", "SrChamp", {
        "win_rate": 0.5,
        "avg_kda": {"ratio": 4.0, "sample": 30},
        "recent_kda": {"ratio": 2.0, "sample": 10, "delta_ratio": -2.0},
    })
    d = coaching_digest(mode=None, top_n=10)
    modes_seen = {i["mode"] for i in d["insights"] if i["type"] == "cold_streak"}
    assert "aram" in modes_seen and "sr_ranked" in modes_seen


def test_digest_includes_duration_insight(tmp_path: Path, monkeypatch) -> None:
    from coaches.adaptation_hint import coaching_digest
    _init(tmp_path, monkeypatch)
    now = datetime.now().astimezone()
    # 6 long-game losses (bad at long games).
    for _ in range(6):
        ts = (now - timedelta(hours=1)).isoformat()
        _insert_match(tmp_path / "aram.db", "Ahri", 0, 3000, ts)
    # 6 quick-game wins (good at quick games).
    for _ in range(6):
        ts = (now - timedelta(hours=2)).isoformat()
        _insert_match(tmp_path / "aram.db", "Ahri", 1, 1200, ts)
    d = coaching_digest(mode="aram", top_n=15)
    types = {i["type"] for i in d["insights"]}
    assert "bad_duration" in types


# ── CLI ─────────────────────────────────────────────────────────────

def test_cli_digest_json(tmp_path: Path, monkeypatch, capsys) -> None:
    from coaches.adaptation_hint import main
    _init(tmp_path, monkeypatch)
    _seed_bucket(tmp_path / "aram.db", "Jinx", {
        "win_rate": 0.5,
        "avg_kda": {"ratio": 4.0, "sample": 30},
        "recent_kda": {"ratio": 2.0, "sample": 10, "delta_ratio": -2.0},
    })
    rc = main(["--digest", "-m", "aram", "-f", "json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["count"] >= 1


def test_cli_digest_text(tmp_path: Path, monkeypatch, capsys) -> None:
    from coaches.adaptation_hint import main
    _init(tmp_path, monkeypatch)
    _seed_bucket(tmp_path / "aram.db", "Jinx", {
        "win_rate": 0.5,
        "avg_kda": {"ratio": 4.0, "sample": 30},
        "recent_kda": {"ratio": 2.0, "sample": 10, "delta_ratio": -2.0},
    })
    rc = main(["--digest", "-m", "aram"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Coaching digest" in out
    assert "cold_streak" in out
    assert "Jinx" in out


def test_cli_digest_cross_mode_default(tmp_path: Path, monkeypatch, capsys) -> None:
    from coaches.adaptation_hint import main
    _init(tmp_path, monkeypatch)
    _seed_bucket(tmp_path / "aram.db", "X", {
        "win_rate": 0.5,
        "avg_kda": {"ratio": 4.0, "sample": 30},
        "recent_kda": {"ratio": 2.0, "sample": 10, "delta_ratio": -2.0},
    })
    rc = main(["--digest", "-f", "json"])
    data = json.loads(capsys.readouterr().out)
    assert data["mode"] == "all"


def test_cli_digest_empty_text(tmp_path: Path, monkeypatch, capsys) -> None:
    from coaches.adaptation_hint import main
    _init(tmp_path, monkeypatch)
    rc = main(["--digest", "-m", "aram"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "no actionable insights" in out


# ── supervisor route ────────────────────────────────────────────────

def test_supervisor_registers_digest_route() -> None:
    sup = Path("agents/supervisor.py").read_text(encoding="utf-8")
    assert "/api/digest" in sup
    assert "_handle_digest" in sup
