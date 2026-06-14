"""Unit tests for Agent 4 analyzer - per-champion aggregates + matchup
activation against a tmp SQLite DB with known inputs."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agents.agent2_backend.db_schema import SCHEMA_STATEMENTS
from agents.agent4_coach_mentor.analyzer import (
    MATCHUP_ACTIVATE_THRESHOLD,
    Analyzer,
)


@pytest.fixture()
def seeded_db(tmp_path: Path, monkeypatch) -> Path:
    """Build a temp mode DB with synthetic matches, then point the
    analyzer at it by monkeypatching DB_DIR."""
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    import agents.agent4_coach_mentor.analyzer as analyzer_mod
    monkeypatch.setattr(analyzer_mod, "DB_DIR", db_dir)

    db_path = db_dir / "aram.db"
    conn = sqlite3.connect(db_path)
    try:
        for stmt in SCHEMA_STATEMENTS:
            conn.execute(stmt)

        now = datetime.now(timezone.utc).isoformat()
        # Ahri: 6 games, 4 wins (67% wr).
        # 5 of those games have "Darius" in the enemy comp -> activates matchup.
        for i, win in enumerate([1, 1, 1, 1, 0, 0]):
            enemies = ["Darius", "Jinx", "Garen", "Rakan", "Lux"] if i < 5 else \
                      ["Jinx", "Garen", "Rakan", "Lux", "Fizz"]
            conn.execute(
                """
                INSERT INTO matches
                  (started_at, ended_at, champion, ally_champions, enemy_champions,
                   duration_sec, win, final_rating_json, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'test')
                """,
                (now, now, "Ahri",
                 json.dumps(["Ahri", "Vi", "Thresh", "Caitlyn", "Orianna"]),
                 json.dumps(enemies),
                 1200 + i * 60, win),
            )
        # Lux: 2 games, 1 win - not enough for matchup activation.
        for win in [1, 0]:
            conn.execute(
                """
                INSERT INTO matches
                  (started_at, ended_at, champion, ally_champions, enemy_champions,
                   duration_sec, win, final_rating_json, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'test')
                """,
                (now, now, "Lux",
                 json.dumps(["Lux", "Vi", "Thresh", "Caitlyn", "Orianna"]),
                 json.dumps(["Darius", "Jinx", "Garen", "Rakan", "Ahri"]),
                 1000, win),
            )
        conn.commit()
    finally:
        conn.close()
    return db_path


def test_analyze_populates_adaptation_buckets(seeded_db: Path) -> None:
    summary = Analyzer("aram").analyze()
    assert summary["matches_scanned"] == 8
    assert summary["champion_buckets"] == 2       # Ahri + Lux

    with sqlite3.connect(seeded_db) as conn:
        conn.row_factory = sqlite3.Row
        rows = {r["champion"]: dict(r) for r in
                conn.execute("SELECT * FROM adaptation_buckets ORDER BY champion")}
    ahri = rows["Ahri"]
    lux = rows["Lux"]

    assert ahri["games_played"] == 6
    assert ahri["wins"] == 4
    assert ahri["losses"] == 2
    assert abs(ahri["avg_rating"] - 0.6667) < 0.001

    assert lux["games_played"] == 2
    assert lux["wins"] == 1
    assert lux["losses"] == 1
    assert abs(lux["avg_rating"] - 0.5) < 0.001

    # aggregates_json carries the rolling stats.
    aj = json.loads(ahri["aggregates_json"])
    assert aj["win_rate"] == pytest.approx(0.6667, abs=0.001)
    assert aj["recent_sample_size"] == 6
    assert aj["avg_duration_sec"] is not None


def test_matchup_activates_at_threshold(seeded_db: Path) -> None:
    Analyzer("aram").analyze()

    with sqlite3.connect(seeded_db) as conn:
        conn.row_factory = sqlite3.Row
        rows = list(conn.execute(
            "SELECT * FROM matchup_modifiers WHERE champion='Ahri' ORDER BY opponent_signature"
        ))

    by_opp = {r["opponent_signature"]: dict(r) for r in rows}

    # Ahri vs Darius - 5 samples -> activated.
    ahri_darius = by_opp["Darius"]
    assert ahri_darius["sample_count"] == 5
    assert ahri_darius["activated"] == 1
    assert ahri_darius["sample_count"] >= MATCHUP_ACTIVATE_THRESHOLD
    mj = json.loads(ahri_darius["modifier_json"])
    # Ahri won 4/5 games when Darius was enemy - higher than baseline.
    assert mj["observed_wr"] == 0.8
    assert mj["sample"] == 5
    assert mj["delta"] > 0

    # Ahri vs Fizz - only 1 sample -> not activated.
    ahri_fizz = by_opp["Fizz"]
    assert ahri_fizz["sample_count"] == 1
    assert ahri_fizz["activated"] == 0


def test_analyze_is_idempotent(seeded_db: Path) -> None:
    Analyzer("aram").analyze()
    Analyzer("aram").analyze()     # re-run
    with sqlite3.connect(seeded_db) as conn:
        n = conn.execute("SELECT COUNT(*) FROM adaptation_buckets").fetchone()[0]
    assert n == 2     # no duplicate rows - UPSERT is correct


def test_unknown_mode_rejected() -> None:
    with pytest.raises(ValueError):
        Analyzer("urf")


def test_skips_matches_with_null_win(seeded_db: Path) -> None:
    # Insert a row without win/loss signal (mimics pre-Phase-3 rewind data).
    with sqlite3.connect(seeded_db) as conn:
        conn.execute(
            """
            INSERT INTO matches
              (started_at, ended_at, champion, ally_champions, enemy_champions,
               duration_sec, win, final_rating_json, source)
            VALUES (?, ?, 'Yasuo', '[]', '[]', 1500, NULL, NULL, 'test')
            """,
            (datetime.now(timezone.utc).isoformat(),
             datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()

    Analyzer("aram").analyze()

    with sqlite3.connect(seeded_db) as conn:
        conn.row_factory = sqlite3.Row
        yasuo = conn.execute(
            "SELECT * FROM adaptation_buckets WHERE champion='Yasuo'"
        ).fetchone()
    # Yasuo has 0 observable games (win=NULL) so no bucket row.
    assert yasuo is None
