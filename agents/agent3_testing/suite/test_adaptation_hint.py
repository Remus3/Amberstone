"""Unit tests for coaches/adaptation_hint.py against a seeded tmp DB."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agents.agent2_backend.db_schema import SCHEMA_STATEMENTS


@pytest.fixture()
def seeded(tmp_path: Path, monkeypatch):
    """Build an aram.db in a tmp dir, point both analyzer and
    adaptation_hint at it via monkeypatched DB_DIR."""
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    import agents.agent4_coach_mentor.analyzer as analyzer_mod
    import coaches.adaptation_hint as hint_mod
    monkeypatch.setattr(analyzer_mod, "DB_DIR", db_dir)
    monkeypatch.setattr(hint_mod, "DB_DIR", db_dir)

    conn = sqlite3.connect(db_dir / "aram.db")
    try:
        for stmt in SCHEMA_STATEMENTS:
            conn.execute(stmt)
        now = datetime.now(timezone.utc).isoformat()
        # Ahri synthetic data — engineered for delta > 0.15:
        #   5 games vs Xerath, all wins  (100% vs Xerath, n=5)
        #   3 games vs other comps, all losses
        #   1 game with Fizz as enemy (alone, below sample threshold)
        # Baseline = 5/9 = 55.6%. Xerath delta = +44.4%.
        matches = [
            (1, ["Xerath", "Jinx", "Garen", "Rakan", "Lux"]),
            (1, ["Xerath", "Jinx", "Garen", "Rakan", "Lux"]),
            (1, ["Xerath", "Jinx", "Garen", "Rakan", "Lux"]),
            (1, ["Xerath", "Jinx", "Garen", "Rakan", "Lux"]),
            (1, ["Xerath", "Jinx", "Garen", "Rakan", "Lux"]),
            (0, ["Jinx", "Garen", "Rakan", "Lux", "Morgana"]),
            (0, ["Jinx", "Garen", "Rakan", "Lux", "Morgana"]),
            (0, ["Jinx", "Garen", "Rakan", "Lux", "Morgana"]),
            (0, ["Jinx", "Garen", "Rakan", "Lux", "Fizz"]),
        ]
        for win, enemies in matches:
            conn.execute(
                """
                INSERT INTO matches
                  (started_at, ended_at, champion, ally_champions, enemy_champions,
                   duration_sec, win, final_rating_json, source)
                VALUES (?, ?, 'Ahri', ?, ?, ?, ?, NULL, 'test')
                """,
                (now, now,
                 json.dumps(["Ahri", "Vi", "Thresh", "Caitlyn", "Orianna"]),
                 json.dumps(enemies),
                 1200, win),
            )
        conn.commit()
    finally:
        conn.close()
    # Run analyzer once to populate adaptation_buckets + matchup_modifiers.
    from agents.agent4_coach_mentor import analyze_mode
    analyze_mode("aram")
    return db_dir


def test_for_champion_returns_bucket(seeded: Path) -> None:
    from coaches.adaptation_hint import for_champion
    d = for_champion("Ahri", "aram")
    assert d["present"] is True
    assert d["games_played"] == 9
    assert d["wins"] == 5
    assert abs(d["win_rate"] - 0.5556) < 0.01


def test_for_champion_surfaces_strong_counter(seeded: Path) -> None:
    from coaches.adaptation_hint import for_champion
    d = for_champion("Ahri", "aram")
    counters = {c["opponent"] for c in d["counters"]}
    assert "Xerath" in counters
    xerath = next(c for c in d["counters"] if c["opponent"] == "Xerath")
    assert xerath["sample"] == 5
    assert xerath["delta"] > 0        # Ahri beats Xerath above baseline


def test_matchup_delta_below_sample_returns_none(seeded: Path) -> None:
    from coaches.adaptation_hint import matchup_delta
    # Ahri vs Fizz only has 1 sample — below _MIN_SAMPLE.
    assert matchup_delta("Ahri", "aram", "Fizz") is None


def test_matchup_delta_activated_returns_signed_float(seeded: Path) -> None:
    from coaches.adaptation_hint import matchup_delta
    d = matchup_delta("Ahri", "aram", "Xerath")
    assert d is not None
    assert isinstance(d, float)
    assert d > 0


def test_format_hint_line_respects_enemy_filter(seeded: Path) -> None:
    from coaches.adaptation_hint import format_hint_line
    # With matching enemy — line flags Xerath.
    hit = format_hint_line("Ahri", "aram", enemies=["Xerath", "Sivir"])
    assert "Ahri" in hit
    assert "Xerath" in hit
    # Without Xerath — no flagged matchups.
    miss = format_hint_line("Ahri", "aram", enemies=["Sivir", "Lulu"])
    assert "Ahri" in miss
    assert "Xerath" not in miss
    assert "active matchups" not in miss


def test_format_hint_line_empty_when_no_data(seeded: Path) -> None:
    from coaches.adaptation_hint import format_hint_line
    assert format_hint_line("Yasuo", "aram") == ""
    assert format_hint_line("Ahri", "brawl") == ""   # brawl.db missing
    assert format_hint_line("Ahri", "does_not_exist") == ""


def test_top_champions_ordered_by_games(seeded: Path) -> None:
    from coaches.adaptation_hint import top_champions
    top = top_champions("aram", n=5, min_games=1)
    assert top, "expected at least one champion"
    assert top[0]["champion"] == "Ahri"
    assert top[0]["games_played"] == 9
