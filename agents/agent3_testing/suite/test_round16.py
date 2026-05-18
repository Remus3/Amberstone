"""Round 16 - auto-analyze exposure + 30-day recency bucketing."""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest


# ── /api/env auto_analyze exposure ──────────────────────────────────

def test_auto_analyze_stats_idle_default() -> None:
    from agents.supervisor import Supervisor
    sup = Supervisor()
    stats = sup.auto_analyze_stats()
    assert stats["state"] == "idle"
    assert stats["fires_in_sec"] is None
    assert stats["running_sec"] is None
    assert stats["last_run_ago_sec"] is None
    assert stats["last_summary"] is None


def test_auto_analyze_stats_pending_shows_fires_in() -> None:
    from agents.supervisor import Supervisor
    sup = Supervisor()
    sup._auto_analyze_scheduled_at = time.monotonic() - 10    # 10s elapsed
    stats = sup.auto_analyze_stats()
    assert stats["state"] == "pending"
    assert stats["fires_in_sec"] is not None
    # Default IDLE is 120s - so ~110s remaining.
    assert 100 < stats["fires_in_sec"] < 120


def test_auto_analyze_stats_running_reports_running_sec() -> None:
    from agents.supervisor import Supervisor
    sup = Supervisor()
    sup._auto_analyze_running_since = time.monotonic() - 3.2
    stats = sup.auto_analyze_stats()
    assert stats["state"] == "running"
    assert stats["running_sec"] is not None
    assert 3.0 < stats["running_sec"] < 4.0


def test_auto_analyze_stats_idle_after_run_shows_last_ago() -> None:
    from agents.supervisor import Supervisor
    sup = Supervisor()
    sup._auto_analyze_last_done_at = time.monotonic() - 45.0
    sup._auto_analyze_last_summary = {"champion_buckets": 249, "top_items_total": 163}
    stats = sup.auto_analyze_stats()
    assert stats["state"] == "idle"
    assert stats["last_run_ago_sec"] is not None
    assert 44.0 < stats["last_run_ago_sec"] < 47.0
    assert stats["last_summary"]["champion_buckets"] == 249


# ── 30-day recency bucket ───────────────────────────────────────────

@pytest.fixture()
def seeded_recency(tmp_path: Path, monkeypatch):
    """Seed an aram.db with a mix of old matches + matches inside the
    30-day window so we can verify the recency bucket populates."""
    from agents.agent2_backend.db_schema import SCHEMA_STATEMENTS
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    import agents.agent4_coach_mentor.analyzer as analyzer_mod
    monkeypatch.setattr(analyzer_mod, "DB_DIR", db_dir)

    db_path = db_dir / "aram.db"
    conn = sqlite3.connect(db_path)
    try:
        for stmt in SCHEMA_STATEMENTS:
            conn.execute(stmt)
        now = datetime.now(timezone.utc)
        old_iso = (now - timedelta(days=180)).isoformat()
        recent_iso = (now - timedelta(days=5)).isoformat()

        # 10 old matches: 4 wins = 40% baseline
        for win in [1, 1, 1, 1, 0, 0, 0, 0, 0, 0]:
            conn.execute(
                """
                INSERT INTO matches
                  (started_at, ended_at, champion, ally_champions, enemy_champions,
                   duration_sec, win, final_rating_json, source)
                VALUES (?, ?, 'Ahri', '[]', '[]', 1200, ?, NULL, 'test')
                """,
                (old_iso, old_iso, win),
            )
        # 6 recent matches: 5 wins = 83% recent window
        for win in [1, 1, 1, 1, 1, 0]:
            conn.execute(
                """
                INSERT INTO matches
                  (started_at, ended_at, champion, ally_champions, enemy_champions,
                   duration_sec, win, final_rating_json, source)
                VALUES (?, ?, 'Ahri', '[]', '[]', 1200, ?, NULL, 'test')
                """,
                (recent_iso, recent_iso, win),
            )
        conn.commit()
    finally:
        conn.close()
    return db_dir


def test_recency_30d_populates_for_in_window_matches(seeded_recency: Path) -> None:
    from agents.agent4_coach_mentor import analyze_mode
    analyze_mode("aram")
    with sqlite3.connect(seeded_recency / "aram.db") as conn:
        row = conn.execute(
            "SELECT aggregates_json FROM adaptation_buckets WHERE champion='Ahri'"
        ).fetchone()
    aj = json.loads(row[0])
    # Overall: 9 wins / 16 games = 56.25%
    assert aj["win_rate"] == pytest.approx(0.5625, abs=0.01)
    r30 = aj.get("recency_30d")
    assert r30 is not None
    assert r30["games"] == 6
    assert r30["wins"] == 5
    assert r30["win_rate"] == pytest.approx(0.8333, abs=0.01)
    # delta should reflect the 83% - 56% uplift
    assert r30["delta_vs_alltime"] > 0.25


def test_recency_30d_absent_when_all_matches_old(tmp_path: Path, monkeypatch) -> None:
    from agents.agent2_backend.db_schema import SCHEMA_STATEMENTS
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    import agents.agent4_coach_mentor.analyzer as analyzer_mod
    monkeypatch.setattr(analyzer_mod, "DB_DIR", db_dir)
    conn = sqlite3.connect(db_dir / "aram.db")
    try:
        for stmt in SCHEMA_STATEMENTS:
            conn.execute(stmt)
        old = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
        for win in [1, 0]:
            conn.execute(
                """
                INSERT INTO matches
                  (started_at, ended_at, champion, ally_champions, enemy_champions,
                   duration_sec, win, final_rating_json, source)
                VALUES (?, ?, 'Lux', '[]', '[]', 1200, ?, NULL, 'test')
                """,
                (old, old, win),
            )
        conn.commit()
    finally:
        conn.close()

    from agents.agent4_coach_mentor import analyze_mode
    analyze_mode("aram")
    with sqlite3.connect(db_dir / "aram.db") as conn:
        row = conn.execute(
            "SELECT aggregates_json FROM adaptation_buckets WHERE champion='Lux'"
        ).fetchone()
    aj = json.loads(row[0])
    assert "recency_30d" not in aj     # no in-window matches → absent


def test_hint_line_mentions_30d_when_present(seeded_recency: Path, monkeypatch) -> None:
    from agents.agent4_coach_mentor import analyze_mode
    analyze_mode("aram")
    import coaches.adaptation_hint as ah
    monkeypatch.setattr(ah, "DB_DIR", seeded_recency)
    line = ah.format_hint_line("Ahri", "aram")
    assert "30d" in line
    # Directional arrow: 83% > 56% baseline → ↑
    assert "↑" in line
