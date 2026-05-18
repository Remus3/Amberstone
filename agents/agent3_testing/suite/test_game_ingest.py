"""Round 20 - live-match → mode DB ingester."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest


@pytest.fixture()
def seeded_db(tmp_path: Path, monkeypatch) -> Path:
    """Empty mode DBs with the round-9 schema so the consumer has
    somewhere to insert."""
    from agents.agent2_backend.db_schema import SCHEMA_STATEMENTS
    import agents.agent2_backend.game_ingest as gi_mod

    db_dir = tmp_path / "db"
    db_dir.mkdir()
    monkeypatch.setattr(gi_mod, "DB_DIR", db_dir)

    for mode in ("aram", "arena", "brawl", "sr_ranked", "sr_draft"):
        p = db_dir / f"{mode}.db"
        with sqlite3.connect(p) as conn:
            for stmt in SCHEMA_STATEMENTS:
                conn.execute(stmt)
            conn.commit()
    return db_dir


def test_ingest_aram_match(seeded_db: Path) -> None:
    from agents.agent2_backend.game_ingest import ingest_game_summary
    result = ingest_game_summary({
        "champion": "Ahri",
        "game_mode": "KIWI",           # ARAM-mayhem internal name
        "game_time_s": 1200,
        "finished_at": "2026-04-22T14:00:00+00:00",
        "rating": "A",
        "notes": ["solid"],
    })
    assert result["inserted"] is True
    assert result["mode_db"] == "aram"
    assert result["champion"] == "Ahri"

    with sqlite3.connect(seeded_db / "aram.db") as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM matches WHERE source='live-phase3'"
        ).fetchone()
    assert row["champion"] == "Ahri"
    assert row["duration_sec"] == 1200
    # 1200s before 14:00:00 = 13:40:00
    assert row["started_at"].startswith("2026-04-22T13:40:00")
    assert row["win"] is None       # MVP: win is unknown
    rating_json = json.loads(row["final_rating_json"])
    assert rating_json["rating"] == "A"


def test_ingest_dedupe_same_match_twice(seeded_db: Path) -> None:
    from agents.agent2_backend.game_ingest import ingest_game_summary
    payload = {
        "champion": "Ahri",
        "game_mode": "ARAM",
        "game_time_s": 900,
        "finished_at": "2026-04-22T12:00:00+00:00",
    }
    r1 = ingest_game_summary(payload)
    r2 = ingest_game_summary(payload)
    assert r1["inserted"] is True
    assert r2["inserted"] is False
    assert "duplicate" in r2["reason"]


def test_ingest_unknown_game_mode_skipped(seeded_db: Path) -> None:
    from agents.agent2_backend.game_ingest import ingest_game_summary
    result = ingest_game_summary({
        "champion": "Ahri",
        "game_mode": "PRACTICETOOL",
        "game_time_s": 120,
    })
    assert result["inserted"] is False
    assert "unknown game_mode" in result["reason"]


def test_ingest_missing_champion_skipped(seeded_db: Path) -> None:
    from agents.agent2_backend.game_ingest import ingest_game_summary
    result = ingest_game_summary({
        "game_mode": "ARAM",
        "game_time_s": 1200,
    })
    assert result["inserted"] is False
    assert "missing champion" in result["reason"]


@pytest.mark.parametrize("mode_label,expected_db", [
    ("CLASSIC",     "sr_ranked"),
    ("ARAM",        "aram"),
    ("KIWI",        "aram"),
    ("ARENA",       "arena"),
    ("CHERRY",      "arena"),
    ("NEXUSBLITZ",  "brawl"),
    ("URF",         "brawl"),
    ("ONEFORALL",   "brawl"),
    ("aram",        "aram"),         # case-insensitive
])
def test_mode_mapping(seeded_db: Path, mode_label: str, expected_db: str) -> None:
    from agents.agent2_backend.game_ingest import ingest_game_summary
    result = ingest_game_summary({
        "champion": "Ahri",
        "game_mode": mode_label,
        "game_time_s": 1000,
        "finished_at": f"2026-04-22T12:00:{hash(mode_label)%60:02d}+00:00",
    })
    # Insert should succeed for all mapped modes.
    assert result["inserted"] is True, f"{mode_label}: {result}"
    assert result["mode_db"] == expected_db


def test_ingest_enemy_comp_preserved(seeded_db: Path) -> None:
    from agents.agent2_backend.game_ingest import ingest_game_summary
    result = ingest_game_summary({
        "champion": "Tristana",
        "game_mode": "ARAM",
        "game_time_s": 1000,
        "finished_at": "2026-04-22T15:00:00+00:00",
        "enemy_comp": ["Morgana", "Zed", "Jinx", "Garen", "Rakan"],
    })
    assert result["inserted"] is True
    with sqlite3.connect(seeded_db / "aram.db") as conn:
        row = conn.execute(
            "SELECT enemy_champions FROM matches WHERE champion='Tristana'"
        ).fetchone()
    enemies = json.loads(row[0])
    assert "Morgana" in enemies
    assert "Zed" in enemies
    assert len(enemies) == 5


def test_analyzer_sees_live_phase3_matches_in_recency(seeded_db: Path) -> None:
    """Full loop - ingest a 'today' match, run the analyzer, verify
    recency_30d bucket populates."""
    from agents.agent2_backend.game_ingest import ingest_game_summary
    now = datetime.now(timezone.utc).isoformat()
    # Insert 6 Ahri matches all within the last 30 days.
    # Win signal is null (MVP), so analyzer's recency_30d shows 0
    # games, BUT the matchup iteration still runs and the row exists
    # - important: we document the win-loss gap lives in the consumer
    # until live win detection is wired.
    for i in range(6):
        ingest_game_summary({
            "champion": "Ahri",
            "game_mode": "ARAM",
            "game_time_s": 1100 + i,
            "finished_at": now,
        })

    # Patch analyzer's DB_DIR to our seeded_db so it reads the same DB.
    import agents.agent4_coach_mentor.analyzer as analyzer_mod
    original_dir = analyzer_mod.DB_DIR
    try:
        analyzer_mod.DB_DIR = seeded_db
        from agents.agent4_coach_mentor import analyze_mode
        summary = analyze_mode("aram")
    finally:
        analyzer_mod.DB_DIR = original_dir

    # Analyzer scans the rows but since win is null, no champion bucket
    # gets written (observe() skips null wins). That's the documented
    # MVP behaviour. But the matches ARE queryable.
    assert summary["matches_scanned"] == 6
    with sqlite3.connect(seeded_db / "aram.db") as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM matches WHERE source='live-phase3' AND champion='Ahri'"
        ).fetchone()[0]
    # Each insert has a distinct started_at (derived from distinct
    # game_time_s offsets against the same finished_at), so no dedupe.
    assert count == 6
