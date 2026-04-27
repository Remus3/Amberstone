"""Round 24 — recent-window KDA trend + dashboard surface."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path


def _seed_matches(db: Path, rows: list[tuple[int, int, int]], champ: str = "Ahri") -> None:
    """Each row is (k, d, a) with started_at stepped so order is stable."""
    with sqlite3.connect(db) as conn:
        for i, (k, d, a) in enumerate(rows):
            conn.execute(
                """INSERT INTO matches
                   (started_at, champion, ally_champions, enemy_champions,
                    duration_sec, win, source, kills, deaths, assists)
                   VALUES (?, ?, '[]', '[]', 1200, 1, 'live-phase3', ?, ?, ?)""",
                (f"2026-04-{(i % 28) + 1:02d}T00:00:00+00:00", champ, k, d, a),
            )
        conn.commit()


def test_recent_kda_surfaces_when_sample_sufficient(tmp_path: Path, monkeypatch) -> None:
    """A champion with ≥5 matches + KDA gets a recent_kda block."""
    from agents.agent4_coach_mentor.analyzer import analyze_mode
    import agents.agent4_coach_mentor.analyzer as analyzer_mod
    import agents.agent2_backend.db_schema as dbs

    monkeypatch.setattr(dbs, "DB_DIR", tmp_path)
    monkeypatch.setattr(analyzer_mod, "DB_DIR", tmp_path)
    dbs.init_mode("aram")

    db = tmp_path / "aram.db"
    # 15 rows — older games are strong (KDA ~4), recent 10 drop to ~2.
    older = [(10, 2, 8)] * 5      # ratio (10+8)/2 = 9.0
    recent = [(4, 8, 6)] * 10     # ratio (4+6)/8 = 1.25
    _seed_matches(db, older + recent)

    analyze_mode("aram")

    with sqlite3.connect(db) as conn:
        aj = json.loads(conn.execute(
            "SELECT aggregates_json FROM adaptation_buckets WHERE champion='Ahri'"
        ).fetchone()[0])
    assert "recent_kda" in aj
    rk = aj["recent_kda"]
    assert rk["sample"] == 10
    assert rk["k"] == 4.0
    assert rk["d"] == 8.0
    assert rk["a"] == 6.0
    assert rk["ratio"] == 1.25
    # Baseline across all 15 is mixed higher; delta should be negative.
    assert rk["delta_ratio"] < 0


def test_recent_kda_absent_under_five_samples(tmp_path: Path, monkeypatch) -> None:
    from agents.agent4_coach_mentor.analyzer import analyze_mode
    import agents.agent4_coach_mentor.analyzer as analyzer_mod
    import agents.agent2_backend.db_schema as dbs

    monkeypatch.setattr(dbs, "DB_DIR", tmp_path)
    monkeypatch.setattr(analyzer_mod, "DB_DIR", tmp_path)
    dbs.init_mode("aram")
    _seed_matches(tmp_path / "aram.db", [(1, 1, 1), (2, 2, 2), (3, 3, 3), (4, 4, 4)])
    analyze_mode("aram")
    with sqlite3.connect(tmp_path / "aram.db") as conn:
        aj = json.loads(conn.execute(
            "SELECT aggregates_json FROM adaptation_buckets WHERE champion='Ahri'"
        ).fetchone()[0])
    assert "avg_kda" in aj      # 4 samples still populates avg_kda
    assert "recent_kda" not in aj


def test_hint_line_shows_recent_delta(tmp_path: Path, monkeypatch) -> None:
    from coaches import adaptation_hint
    import agents.agent2_backend.db_schema as dbs

    monkeypatch.setattr(dbs, "DB_DIR", tmp_path)
    monkeypatch.setattr(adaptation_hint, "DB_DIR", tmp_path)
    dbs.init_mode("aram")

    aj = {
        "win_rate": 0.55, "recent_win_rate": None, "recent_sample_size": 0,
        "avg_kda": {"k": 8.0, "d": 5.0, "a": 13.0, "ratio": 4.20, "sample": 20},
        "recent_kda": {"k": 4.0, "d": 8.0, "a": 6.0, "ratio": 1.25,
                       "sample": 10, "delta_ratio": -2.95},
    }
    with sqlite3.connect(tmp_path / "aram.db") as conn:
        conn.execute(
            """INSERT INTO adaptation_buckets
               (champion, games_played, wins, losses, avg_rating, last_updated, aggregates_json)
               VALUES ('Ahri', 20, 11, 9, 0.55, '2026-04-22T00:00:00Z', ?)""",
            (json.dumps(aj),),
        )
        conn.commit()

    line = adaptation_hint.format_hint_line("Ahri", "aram")
    assert "typical KDA 4.2" in line
    assert "recent 1.25" in line
    assert "↓" in line           # -2.95 is below the -0.3 threshold
    assert "-2.95" in line


def test_for_champion_exposes_recent_kda(tmp_path: Path, monkeypatch) -> None:
    from coaches import adaptation_hint
    import agents.agent2_backend.db_schema as dbs

    monkeypatch.setattr(dbs, "DB_DIR", tmp_path)
    monkeypatch.setattr(adaptation_hint, "DB_DIR", tmp_path)
    dbs.init_mode("aram")

    aj = {
        "win_rate": 0.55, "recent_win_rate": None, "recent_sample_size": 0,
        "avg_kda": {"k": 8, "d": 5, "a": 13, "ratio": 4.2, "sample": 20},
        "recent_kda": {"k": 12, "d": 3, "a": 15, "ratio": 9.0,
                       "sample": 10, "delta_ratio": 4.8},
    }
    with sqlite3.connect(tmp_path / "aram.db") as conn:
        conn.execute(
            """INSERT INTO adaptation_buckets
               (champion, games_played, wins, losses, avg_rating, last_updated, aggregates_json)
               VALUES ('Ahri', 20, 11, 9, 0.55, '2026-04-22T00:00:00Z', ?)""",
            (json.dumps(aj),),
        )
        conn.commit()
    data = adaptation_hint.for_champion("Ahri", "aram")
    assert data["recent_kda"]["ratio"] == 9.0
    assert data["recent_kda"]["delta_ratio"] == 4.8


# ── dashboard surface ─────────────────────────────────────────────

def test_dashboard_has_kda_row() -> None:
    """HTML should expose adapt-kda element for the renderer to target."""
    html = Path("web/index.html").read_text(encoding="utf-8")
    assert 'id="adapt-kda"' in html
    assert "Typical KDA" in html


def test_dashboard_js_binds_kda_element() -> None:
    js = Path("web/js/dashboard.js").read_text(encoding="utf-8")
    assert 'kda: el("adapt-kda")' in js
    assert "data.avg_kda" in js
    # Must also consume recent_kda when serving the trend.
    assert "data.recent_kda" in js
