"""Round 25 — matchup-level KDA deltas + insight card KDA."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path


def _init(tmp_path: Path, monkeypatch):
    import agents.agent4_coach_mentor.analyzer as analyzer_mod
    import agents.agent2_backend.db_schema as dbs
    from coaches import adaptation_hint
    monkeypatch.setattr(dbs, "DB_DIR", tmp_path)
    monkeypatch.setattr(analyzer_mod, "DB_DIR", tmp_path)
    monkeypatch.setattr(adaptation_hint, "DB_DIR", tmp_path)
    dbs.init_mode("aram")


def _insert_match(
    conn: sqlite3.Connection, champ: str, enemies: list[str],
    win: int, k: int | None, d: int | None, a: int | None,
    i: int,
) -> None:
    conn.execute(
        """INSERT INTO matches
           (started_at, champion, ally_champions, enemy_champions,
            duration_sec, win, source, kills, deaths, assists)
           VALUES (?, ?, '[]', ?, 1200, ?, 'live-phase3', ?, ?, ?)""",
        (
            f"2026-04-{(i % 28) + 1:02d}T00:00:00+00:00",
            champ, json.dumps(enemies), win, k, d, a,
        ),
    )


# ── matchup KDA aggregation ─────────────────────────────────────────

def test_matchup_kda_ratio_and_delta(tmp_path: Path, monkeypatch) -> None:
    """A champion with a clear baseline KDA + a specific enemy she
    underperforms against should get a negative kda_delta in the
    matchup modifier."""
    from agents.agent4_coach_mentor.analyzer import analyze_mode
    _init(tmp_path, monkeypatch)

    db = tmp_path / "aram.db"
    with sqlite3.connect(db) as conn:
        # 10 games not vs Zed — strong KDA (10/3/15 → ratio (10+15)/3 = 8.33)
        for i in range(10):
            _insert_match(conn, "Ahri", ["Garen"], 1, 10, 3, 15, i)
        # 5 games vs Zed — bad KDA (2/10/3 → ratio (2+3)/10 = 0.5)
        for i in range(5):
            _insert_match(conn, "Ahri", ["Zed"], 0, 2, 10, 3, 100 + i)
        conn.commit()

    analyze_mode("aram")

    with sqlite3.connect(db) as conn:
        row = conn.execute(
            """SELECT modifier_json FROM matchup_modifiers
               WHERE champion = 'Ahri' AND opponent_signature = 'Zed'"""
        ).fetchone()
    mj = json.loads(row[0])
    assert mj["kda_sample"] == 5
    assert mj["kda_ratio"] == 0.5
    # Baseline: overall Ahri KDA across all 15 rows.
    # (10*10 + 5*2)/15 = 7.33 k, (10*3 + 5*10)/15 = 5.33 d,
    # (10*15 + 5*3)/15 = 11.0 a → ratio (7.33+11.0)/5.33 ≈ 3.44
    # Delta should be very negative.
    assert mj["kda_delta"] < -2.0


def test_matchup_kda_omitted_when_no_kda_rows(tmp_path: Path, monkeypatch) -> None:
    """Activated matchups without any KDA rows shouldn't get kda_ratio."""
    from agents.agent4_coach_mentor.analyzer import analyze_mode
    _init(tmp_path, monkeypatch)

    db = tmp_path / "aram.db"
    with sqlite3.connect(db) as conn:
        # 6 games vs Ezreal with no KDA data.
        for i in range(6):
            _insert_match(conn, "Ahri", ["Ezreal"], 1, None, None, None, i)
        conn.commit()

    analyze_mode("aram")

    with sqlite3.connect(db) as conn:
        row = conn.execute(
            """SELECT modifier_json FROM matchup_modifiers
               WHERE champion='Ahri' AND opponent_signature='Ezreal'"""
        ).fetchone()
    mj = json.loads(row[0])
    assert "kda_ratio" not in mj
    assert "kda_delta" not in mj
    # Base win/loss modifier is still there.
    assert mj["sample"] == 6


def test_for_champion_exposes_matchup_kda(tmp_path: Path, monkeypatch) -> None:
    """counters[i]['kda_ratio'] + ['kda_delta'] surface to consumers."""
    from coaches import adaptation_hint
    _init(tmp_path, monkeypatch)

    db = tmp_path / "aram.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            """INSERT INTO adaptation_buckets
               (champion, games_played, wins, losses, avg_rating, last_updated, aggregates_json)
               VALUES ('Ahri', 20, 12, 8, 0.60, '2026-04-22T00:00:00Z', ?)""",
            (json.dumps({"win_rate": 0.60}),),
        )
        mj = {
            "sample": 5, "observed_wr": 0.20, "baseline_wr": 0.60, "delta": -0.40,
            "kda_sample": 5, "kda_ratio": 1.1, "kda_delta": -2.3,
        }
        conn.execute(
            """INSERT INTO matchup_modifiers
               (champion, opponent_signature, sample_count, activated, modifier_json, last_updated)
               VALUES ('Ahri', 'Zed', 5, 1, ?, '2026-04-22T00:00:00Z')""",
            (json.dumps(mj),),
        )
        conn.commit()

    data = adaptation_hint.for_champion("Ahri", "aram")
    assert len(data["counters"]) == 1
    c = data["counters"][0]
    assert c["opponent"] == "Zed"
    assert c["kda_ratio"] == 1.1
    assert c["kda_delta"] == -2.3
    assert c["kda_sample"] == 5


def test_hint_line_annotates_matchup_kda(tmp_path: Path, monkeypatch) -> None:
    from coaches import adaptation_hint
    _init(tmp_path, monkeypatch)

    db = tmp_path / "aram.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            """INSERT INTO adaptation_buckets
               (champion, games_played, wins, losses, avg_rating, last_updated, aggregates_json)
               VALUES ('Ahri', 20, 12, 8, 0.60, '2026-04-22T00:00:00Z', ?)""",
            (json.dumps({"win_rate": 0.60}),),
        )
        mj = {
            "sample": 5, "observed_wr": 0.20, "baseline_wr": 0.60, "delta": -0.40,
            "kda_sample": 5, "kda_ratio": 1.1, "kda_delta": -2.3,
        }
        conn.execute(
            """INSERT INTO matchup_modifiers
               (champion, opponent_signature, sample_count, activated, modifier_json, last_updated)
               VALUES ('Ahri', 'Zed', 5, 1, ?, '2026-04-22T00:00:00Z')""",
            (json.dumps(mj),),
        )
        conn.commit()

    line = adaptation_hint.format_hint_line("Ahri", "aram", enemies=["Zed"])
    assert "vs Zed -40%" in line
    assert "KDA 1.1" in line
    assert "-2.3" in line


def test_hint_line_skips_tiny_kda_delta(tmp_path: Path, monkeypatch) -> None:
    """|kda_delta| < 0.3 is below the noise floor — don't clutter the line."""
    from coaches import adaptation_hint
    _init(tmp_path, monkeypatch)

    db = tmp_path / "aram.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            """INSERT INTO adaptation_buckets
               (champion, games_played, wins, losses, avg_rating, last_updated, aggregates_json)
               VALUES ('Ahri', 20, 12, 8, 0.60, '2026-04-22T00:00:00Z', ?)""",
            (json.dumps({"win_rate": 0.60}),),
        )
        mj = {
            "sample": 5, "observed_wr": 0.20, "baseline_wr": 0.60, "delta": -0.40,
            "kda_sample": 5, "kda_ratio": 3.4, "kda_delta": 0.1,
        }
        conn.execute(
            """INSERT INTO matchup_modifiers
               (champion, opponent_signature, sample_count, activated, modifier_json, last_updated)
               VALUES ('Ahri', 'Zed', 5, 1, ?, '2026-04-22T00:00:00Z')""",
            (json.dumps(mj),),
        )
        conn.commit()
    line = adaptation_hint.format_hint_line("Ahri", "aram", enemies=["Zed"])
    # Win% segment present, KDA segment absent.
    assert "vs Zed -40%" in line
    assert "KDA" not in line


# ── insight_card KDA ────────────────────────────────────────────────

def test_insight_card_includes_kda(tmp_path: Path, monkeypatch) -> None:
    from coaches import adaptation_hint
    _init(tmp_path, monkeypatch)

    with sqlite3.connect(tmp_path / "aram.db") as conn:
        aj = {
            "win_rate": 0.72, "recent_win_rate": None, "recent_sample_size": 0,
            "avg_kda": {"k": 15, "d": 11, "a": 22, "ratio": 3.36, "sample": 30},
        }
        conn.execute(
            """INSERT INTO adaptation_buckets
               (champion, games_played, wins, losses, avg_rating, last_updated, aggregates_json)
               VALUES ('Tristana', 30, 22, 8, 0.72, '2026-04-22T00:00:00Z', ?)""",
            (json.dumps(aj),),
        )
        conn.commit()
    card = adaptation_hint.insight_card("Tristana", "aram")
    assert "KDA 3.36" in card


def test_insight_card_shows_recent_arrow(tmp_path: Path, monkeypatch) -> None:
    from coaches import adaptation_hint
    _init(tmp_path, monkeypatch)

    with sqlite3.connect(tmp_path / "aram.db") as conn:
        aj = {
            "win_rate": 0.55, "recent_win_rate": None, "recent_sample_size": 0,
            "avg_kda": {"k": 15, "d": 5, "a": 22, "ratio": 7.4, "sample": 30},
            "recent_kda": {"k": 6, "d": 10, "a": 8, "ratio": 1.4,
                           "sample": 10, "delta_ratio": -6.0},
        }
        conn.execute(
            """INSERT INTO adaptation_buckets
               (champion, games_played, wins, losses, avg_rating, last_updated, aggregates_json)
               VALUES ('Kaisa', 30, 16, 14, 0.55, '2026-04-22T00:00:00Z', ?)""",
            (json.dumps(aj),),
        )
        conn.commit()
    card = adaptation_hint.insight_card("Kaisa", "aram")
    assert "KDA 7.4" in card
    assert "↓1.4" in card


def test_insight_card_suppresses_small_kda_drift(tmp_path: Path, monkeypatch) -> None:
    from coaches import adaptation_hint
    _init(tmp_path, monkeypatch)

    with sqlite3.connect(tmp_path / "aram.db") as conn:
        aj = {
            "win_rate": 0.60,
            "avg_kda": {"k": 10, "d": 5, "a": 15, "ratio": 5.0, "sample": 20},
            "recent_kda": {"k": 10, "d": 5, "a": 15, "ratio": 5.1,
                           "sample": 10, "delta_ratio": 0.1},
        }
        conn.execute(
            """INSERT INTO adaptation_buckets
               (champion, games_played, wins, losses, avg_rating, last_updated, aggregates_json)
               VALUES ('Ahri', 20, 12, 8, 0.6, '2026-04-22T00:00:00Z', ?)""",
            (json.dumps(aj),),
        )
        conn.commit()
    card = adaptation_hint.insight_card("Ahri", "aram")
    assert "KDA 5.0" in card
    # No recent-arrow annotation, since |delta| < 0.3
    assert "↑" not in card and "↓" not in card


# ── dashboard JS surfaces kda_delta ─────────────────────────────────

def test_dashboard_counter_line_uses_matchup_kda() -> None:
    js = Path("web/js/dashboard.js").read_text(encoding="utf-8")
    assert "c.kda_ratio" in js
    assert "c.kda_delta" in js
