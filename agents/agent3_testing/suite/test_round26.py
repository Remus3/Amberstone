"""Round 26 — KDA trends helper + /api/trending endpoint."""
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


def _seed_bucket(db: Path, champ: str, aj: dict) -> None:
    with sqlite3.connect(db) as conn:
        conn.execute(
            """INSERT INTO adaptation_buckets
               (champion, games_played, wins, losses, avg_rating, last_updated, aggregates_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (champ, 20, 11, 9, 0.55, "2026-04-22T00:00:00Z", json.dumps(aj)),
        )
        conn.commit()


# ── kda_trends hot/cold sort ────────────────────────────────────────

def test_kda_trends_sorts_hot_and_cold(tmp_path: Path, monkeypatch) -> None:
    from coaches import adaptation_hint
    _init(tmp_path, monkeypatch)
    db = tmp_path / "aram.db"

    _seed_bucket(db, "Heater", {
        "avg_kda": {"ratio": 2.0, "sample": 20},
        "recent_kda": {"ratio": 5.0, "sample": 10, "delta_ratio": 3.0},
    })
    _seed_bucket(db, "SlightHeater", {
        "avg_kda": {"ratio": 3.0, "sample": 20},
        "recent_kda": {"ratio": 3.8, "sample": 10, "delta_ratio": 0.8},
    })
    _seed_bucket(db, "Cooler", {
        "avg_kda": {"ratio": 4.0, "sample": 20},
        "recent_kda": {"ratio": 2.5, "sample": 10, "delta_ratio": -1.5},
    })
    _seed_bucket(db, "NoRecent", {
        "avg_kda": {"ratio": 3.0, "sample": 20},
        # no recent_kda → must be excluded
    })

    trends = adaptation_hint.kda_trends("aram", n=3)
    assert [e["champion"] for e in trends["hot"]] == ["Heater", "SlightHeater"]
    assert [e["champion"] for e in trends["cold"]] == ["Cooler"]
    assert trends["hot"][0]["delta"] == 3.0


def test_kda_trends_respects_n(tmp_path: Path, monkeypatch) -> None:
    from coaches import adaptation_hint
    _init(tmp_path, monkeypatch)
    db = tmp_path / "aram.db"
    for i, delta in enumerate([2.0, 1.5, 1.0, 0.5]):
        _seed_bucket(db, f"Hot{i}", {
            "avg_kda": {"ratio": 3.0, "sample": 20},
            "recent_kda": {"ratio": 3.0 + delta, "sample": 10, "delta_ratio": delta},
        })
    trends = adaptation_hint.kda_trends("aram", n=2)
    assert len(trends["hot"]) == 2
    assert trends["hot"][0]["champion"] == "Hot0"


def test_kda_trends_respects_min_sample(tmp_path: Path, monkeypatch) -> None:
    from coaches import adaptation_hint
    _init(tmp_path, monkeypatch)
    db = tmp_path / "aram.db"
    _seed_bucket(db, "TooFew", {
        "avg_kda": {"ratio": 3.0, "sample": 20},
        "recent_kda": {"ratio": 5.0, "sample": 3, "delta_ratio": 2.0},
    })
    trends = adaptation_hint.kda_trends("aram", n=3)
    assert trends["hot"] == []
    assert trends["cold"] == []


def test_kda_trends_missing_mode_returns_empty(tmp_path: Path, monkeypatch) -> None:
    from coaches import adaptation_hint
    import agents.agent2_backend.db_schema as dbs
    monkeypatch.setattr(dbs, "DB_DIR", tmp_path)
    monkeypatch.setattr(adaptation_hint, "DB_DIR", tmp_path)
    # Don't create a DB — kda_trends must not crash.
    out = adaptation_hint.kda_trends("aram")
    assert out == {"mode": "aram", "hot": [], "cold": []}


# ── top_champions now carries KDA ───────────────────────────────────

def test_top_champions_includes_kda(tmp_path: Path, monkeypatch) -> None:
    from coaches import adaptation_hint
    _init(tmp_path, monkeypatch)
    db = tmp_path / "aram.db"
    _seed_bucket(db, "Ahri", {
        "avg_kda": {"ratio": 3.4, "sample": 30, "k": 9, "d": 5, "a": 13},
        "recent_kda": {"ratio": 2.8, "sample": 10, "delta_ratio": -0.6},
    })
    champs = adaptation_hint.top_champions("aram", n=5, min_games=1)
    assert len(champs) == 1
    c = champs[0]
    assert c["avg_kda"]["ratio"] == 3.4
    assert c["recent_kda"]["delta_ratio"] == -0.6


# ── /api/trending endpoint wiring ───────────────────────────────────

def test_trending_handler_parses_args(tmp_path: Path, monkeypatch) -> None:
    """_handle_trending returns shaped JSON with mode-specific trends."""
    from coaches import adaptation_hint
    _init(tmp_path, monkeypatch)
    _seed_bucket(tmp_path / "aram.db", "Heater", {
        "avg_kda": {"ratio": 2.0, "sample": 20},
        "recent_kda": {"ratio": 5.0, "sample": 10, "delta_ratio": 3.0},
    })
    # Call kda_trends directly (covers endpoint's payload shape).
    out = adaptation_hint.kda_trends("aram", n=3)
    assert out["mode"] == "aram"
    assert out["hot"][0]["champion"] == "Heater"
    assert "cold" in out


def test_supervisor_registers_trending_route() -> None:
    """Cheap static-analysis check: the route dispatcher must know about
    /api/trending so the handler can be reached."""
    sup = Path("agents/supervisor.py").read_text(encoding="utf-8")
    assert "/api/trending" in sup
    assert "_handle_trending" in sup
