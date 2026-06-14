"""Round 23 - KDA schema migration + backfill + analyzer aggregation."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest


# -- schema migration ------------------------------------------------

def _make_old_mode_db(path: Path) -> None:
    """Build a matches table *without* kills/deaths/assists columns,
    mimicking a DB created before round 23."""
    with sqlite3.connect(path) as conn:
        conn.execute("""
            CREATE TABLE matches (
              match_id INTEGER PRIMARY KEY AUTOINCREMENT,
              started_at TEXT NOT NULL,
              ended_at TEXT,
              champion TEXT NOT NULL,
              ally_champions TEXT NOT NULL,
              enemy_champions TEXT NOT NULL,
              duration_sec INTEGER,
              win INTEGER,
              final_rating_json TEXT,
              source TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE _migration_state (
              source TEXT NOT NULL,
              source_ref TEXT NOT NULL,
              local_match_id INTEGER NOT NULL,
              migrated_at TEXT NOT NULL,
              PRIMARY KEY (source, source_ref)
            )
        """)
        conn.commit()


def test_migrate_adds_missing_columns(tmp_path: Path) -> None:
    from agents.agent2_backend.db_migrate_kda import ensure_kda_columns, KDA_COLUMNS

    db = tmp_path / "aram.db"
    _make_old_mode_db(db)

    result = ensure_kda_columns(db)
    assert result == {c: True for c in KDA_COLUMNS}

    with sqlite3.connect(db) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(matches)")}
    assert {"kills", "deaths", "assists"} <= cols


def test_migrate_is_idempotent(tmp_path: Path) -> None:
    from agents.agent2_backend.db_migrate_kda import ensure_kda_columns

    db = tmp_path / "aram.db"
    _make_old_mode_db(db)
    ensure_kda_columns(db)
    # Second run: all already present.
    result = ensure_kda_columns(db)
    assert result == {"kills": False, "deaths": False, "assists": False}


def test_migrate_missing_db_is_safe(tmp_path: Path) -> None:
    from agents.agent2_backend.db_migrate_kda import ensure_kda_columns
    out = ensure_kda_columns(tmp_path / "does-not-exist.db")
    assert out == {"kills": False, "deaths": False, "assists": False}


def test_init_all_includes_kda_natively(tmp_path: Path, monkeypatch) -> None:
    """Fresh mode DBs built by db_schema.init_all should have the KDA
    columns already - no migration step required on clean install."""
    import agents.agent2_backend.db_schema as dbs
    monkeypatch.setattr(dbs, "DB_DIR", tmp_path)
    dbs.init_mode("aram")
    with sqlite3.connect(tmp_path / "aram.db") as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(matches)")}
    assert {"kills", "deaths", "assists"} <= cols


# -- game_ingest parses live-coach kda string ------------------------

def test_parse_kda_string() -> None:
    from agents.agent2_backend.game_ingest import _parse_kda
    assert _parse_kda("10/3/15") == (10, 3, 15)
    assert _parse_kda("0/0/0") == (0, 0, 0)
    assert _parse_kda("not-kda") == (None, None, None)
    assert _parse_kda("10/3") == (None, None, None)
    assert _parse_kda(None) == (None, None, None)
    assert _parse_kda({"k": 5, "d": 2, "a": 8}) == (5, 2, 8)
    assert _parse_kda({"kills": 5, "deaths": 2, "assists": 8}) == (5, 2, 8)


def test_game_ingest_stores_kda(tmp_path: Path, monkeypatch) -> None:
    import agents.agent2_backend.game_ingest as gi
    import agents.agent2_backend.db_schema as dbs

    monkeypatch.setattr(dbs, "DB_DIR", tmp_path)
    monkeypatch.setattr(gi, "DB_DIR", tmp_path)
    dbs.init_mode("aram")

    result = gi.ingest_game_summary({
        "game_mode": "ARAM",
        "champion": "Ahri",
        "game_time_s": 1200,
        "finished_at": "2026-04-22T12:00:00+00:00",
        "kda": "12/4/18",
    })
    assert result["inserted"] is True
    assert result["kda"] == {"k": 12, "d": 4, "a": 18}

    with sqlite3.connect(tmp_path / "aram.db") as conn:
        row = conn.execute(
            "SELECT kills, deaths, assists FROM matches WHERE match_id = ?",
            (result["match_id"],),
        ).fetchone()
    assert row == (12, 4, 18)


def test_game_ingest_without_kda_leaves_nulls(tmp_path: Path, monkeypatch) -> None:
    import agents.agent2_backend.game_ingest as gi
    import agents.agent2_backend.db_schema as dbs

    monkeypatch.setattr(dbs, "DB_DIR", tmp_path)
    monkeypatch.setattr(gi, "DB_DIR", tmp_path)
    dbs.init_mode("aram")

    result = gi.ingest_game_summary({
        "game_mode": "ARAM",
        "champion": "Ahri",
        "game_time_s": 1200,
        "finished_at": "2026-04-22T12:00:00+00:00",
        # no kda
    })
    assert result["inserted"] is True
    assert result["kda"] is None

    with sqlite3.connect(tmp_path / "aram.db") as conn:
        row = conn.execute(
            "SELECT kills, deaths, assists FROM matches WHERE match_id = ?",
            (result["match_id"],),
        ).fetchone()
    assert row == (None, None, None)


# -- backfill from rewind --------------------------------------------

def _build_fake_rewind(path: Path, entries: list[tuple[str, int, int, int]]) -> None:
    """Minimal rewind schema - just what backfill reads."""
    with sqlite3.connect(path) as conn:
        conn.execute("""
            CREATE TABLE matches (
              match_id TEXT PRIMARY KEY,
              tracked_kills INTEGER,
              tracked_deaths INTEGER,
              tracked_assists INTEGER
            )
        """)
        conn.executemany(
            "INSERT INTO matches VALUES (?, ?, ?, ?)",
            entries,
        )
        conn.commit()


def test_backfill_updates_null_rows(tmp_path: Path, monkeypatch) -> None:
    import agents.agent2_backend.backfill_kda as bk
    import agents.agent2_backend.db_schema as dbs

    # Point at a temp project root + isolate DB_DIR.
    monkeypatch.setattr(dbs, "DB_DIR", tmp_path / "mdb")
    monkeypatch.setattr(bk, "REWIND_DB", tmp_path / "rewind.db")
    (tmp_path / "mdb").mkdir()

    # Fresh aram DB - has KDA columns natively (init_all path).
    dbs.init_mode("aram")

    mode_path = tmp_path / "mdb" / "aram.db"
    with sqlite3.connect(mode_path) as conn:
        cur = conn.execute(
            """INSERT INTO matches
               (started_at, champion, ally_champions, enemy_champions, source)
               VALUES ('2026-01-01T00:00:00+00:00', 'Ahri', '[]', '[]', 'rewind_migration')
            """
        )
        local_id = cur.lastrowid
        conn.execute(
            """INSERT INTO _migration_state
               (source, source_ref, local_match_id, migrated_at)
               VALUES ('rewind_migration', 'NA1_123', ?, '2026-01-01T00:00:00Z')""",
            (local_id,),
        )
        conn.commit()

    _build_fake_rewind(tmp_path / "rewind.db", [("NA1_123", 7, 2, 11)])

    summary = bk.backfill_all()
    assert summary["per_mode"]["aram"]["updated"] == 1
    assert summary["total_updated"] == 1

    with sqlite3.connect(mode_path) as conn:
        row = conn.execute(
            "SELECT kills, deaths, assists FROM matches WHERE match_id = ?",
            (local_id,),
        ).fetchone()
    assert row == (7, 2, 11)

    # Re-running should be a no-op (no candidates -> 0 updates).
    again = bk.backfill_all()
    assert again["per_mode"]["aram"]["updated"] == 0
    assert again["per_mode"]["aram"]["candidates"] == 0


def test_backfill_dry_run_does_not_write(tmp_path: Path, monkeypatch) -> None:
    import agents.agent2_backend.backfill_kda as bk
    import agents.agent2_backend.db_schema as dbs

    monkeypatch.setattr(dbs, "DB_DIR", tmp_path / "mdb")
    monkeypatch.setattr(bk, "REWIND_DB", tmp_path / "rewind.db")
    (tmp_path / "mdb").mkdir()

    dbs.init_mode("aram")
    mode_path = tmp_path / "mdb" / "aram.db"
    with sqlite3.connect(mode_path) as conn:
        cur = conn.execute(
            """INSERT INTO matches
               (started_at, champion, ally_champions, enemy_champions, source)
               VALUES ('2026-01-01T00:00:00+00:00', 'Ahri', '[]', '[]', 'rewind_migration')
            """
        )
        local_id = cur.lastrowid
        conn.execute(
            """INSERT INTO _migration_state
               (source, source_ref, local_match_id, migrated_at)
               VALUES ('rewind_migration', 'NA1_999', ?, '2026-01-01T00:00:00Z')""",
            (local_id,),
        )
        conn.commit()
    _build_fake_rewind(tmp_path / "rewind.db", [("NA1_999", 1, 2, 3)])

    summary = bk.backfill_all(dry_run=True)
    assert summary["per_mode"]["aram"]["would_update"] == 1

    with sqlite3.connect(mode_path) as conn:
        row = conn.execute(
            "SELECT kills, deaths, assists FROM matches WHERE match_id = ?",
            (local_id,),
        ).fetchone()
    # Still null - dry-run shouldn't write.
    assert row == (None, None, None)


def test_backfill_skips_already_populated(tmp_path: Path, monkeypatch) -> None:
    import agents.agent2_backend.backfill_kda as bk
    import agents.agent2_backend.db_schema as dbs

    monkeypatch.setattr(dbs, "DB_DIR", tmp_path / "mdb")
    monkeypatch.setattr(bk, "REWIND_DB", tmp_path / "rewind.db")
    (tmp_path / "mdb").mkdir()
    dbs.init_mode("aram")

    mode_path = tmp_path / "mdb" / "aram.db"
    with sqlite3.connect(mode_path) as conn:
        cur = conn.execute(
            """INSERT INTO matches
               (started_at, champion, ally_champions, enemy_champions, source,
                kills, deaths, assists)
               VALUES ('2026-01-01T00:00:00+00:00', 'Ahri', '[]', '[]',
                       'rewind_migration', 99, 99, 99)
            """
        )
        local_id = cur.lastrowid
        conn.execute(
            """INSERT INTO _migration_state
               (source, source_ref, local_match_id, migrated_at)
               VALUES ('rewind_migration', 'NA1_777', ?, '2026-01-01T00:00:00Z')""",
            (local_id,),
        )
        conn.commit()
    _build_fake_rewind(tmp_path / "rewind.db", [("NA1_777", 1, 2, 3)])

    summary = bk.backfill_all()
    assert summary["per_mode"]["aram"]["candidates"] == 0
    # Row is unchanged - the 99s are sacred once set.
    with sqlite3.connect(mode_path) as conn:
        row = conn.execute(
            "SELECT kills, deaths, assists FROM matches WHERE match_id = ?",
            (local_id,),
        ).fetchone()
    assert row == (99, 99, 99)


# -- analyzer avg_kda ------------------------------------------------

def test_analyzer_computes_avg_kda(tmp_path: Path, monkeypatch) -> None:
    from agents.agent4_coach_mentor.analyzer import analyze_mode
    import agents.agent4_coach_mentor.analyzer as analyzer_mod
    import agents.agent2_backend.db_schema as dbs

    monkeypatch.setattr(dbs, "DB_DIR", tmp_path)
    monkeypatch.setattr(analyzer_mod, "DB_DIR", tmp_path)
    dbs.init_mode("aram")

    db = tmp_path / "aram.db"
    rows = [
        (1, "Ahri", 10, 3, 15),
        (1, "Ahri", 8, 5, 12),
        (0, "Ahri", 4, 9, 10),
        (1, "Ahri", 12, 2, 18),
        (0, "Ahri", 6, 7, 11),
    ]
    with sqlite3.connect(db) as conn:
        for win, champ, k, d, a in rows:
            conn.execute(
                """INSERT INTO matches
                   (started_at, champion, ally_champions, enemy_champions,
                    duration_sec, win, source, kills, deaths, assists)
                   VALUES ('2026-04-20T00:00:00+00:00', ?, '[]', '[]',
                           1200, ?, 'live-phase3', ?, ?, ?)""",
                (champ, win, k, d, a),
            )
        conn.commit()

    summary = analyze_mode("aram")
    assert summary["champions_with_kda"] == 1

    with sqlite3.connect(db) as conn:
        aj_raw = conn.execute(
            "SELECT aggregates_json FROM adaptation_buckets WHERE champion = 'Ahri'"
        ).fetchone()[0]
    aj = json.loads(aj_raw)
    kda = aj["avg_kda"]
    assert kda["sample"] == 5
    assert kda["k"] == 8.0  # (10+8+4+12+6)/5
    assert kda["d"] == 5.2  # (3+5+9+2+7)/5
    assert kda["a"] == 13.2 # (15+12+10+18+11)/5
    # ratio = (8+13.2) / 5.2 = 4.08
    assert abs(kda["ratio"] - 4.08) < 0.01


def test_analyzer_ignores_null_kda_rows(tmp_path: Path, monkeypatch) -> None:
    """Rows with NULL k/d/a should not contribute to the kda sample."""
    from agents.agent4_coach_mentor.analyzer import analyze_mode
    import agents.agent4_coach_mentor.analyzer as analyzer_mod
    import agents.agent2_backend.db_schema as dbs

    monkeypatch.setattr(dbs, "DB_DIR", tmp_path)
    monkeypatch.setattr(analyzer_mod, "DB_DIR", tmp_path)
    dbs.init_mode("aram")

    db = tmp_path / "aram.db"
    with sqlite3.connect(db) as conn:
        # Two rows: one with full KDA, one without.
        conn.execute(
            """INSERT INTO matches
               (started_at, champion, ally_champions, enemy_champions,
                win, source, kills, deaths, assists)
               VALUES ('2026-04-20T00:00:00+00:00', 'Ahri', '[]', '[]',
                       1, 'live-phase3', 10, 5, 15)"""
        )
        conn.execute(
            """INSERT INTO matches
               (started_at, champion, ally_champions, enemy_champions,
                win, source)
               VALUES ('2026-04-20T00:00:00+00:00', 'Ahri', '[]', '[]',
                       1, 'live-phase3')"""
        )
        conn.commit()

    analyze_mode("aram")
    with sqlite3.connect(db) as conn:
        aj = json.loads(conn.execute(
            "SELECT aggregates_json FROM adaptation_buckets WHERE champion='Ahri'"
        ).fetchone()[0])
    assert aj["avg_kda"]["sample"] == 1
    assert aj["avg_kda"]["k"] == 10.0


# -- adaptation_hint surfaces KDA ------------------------------------

def test_hint_line_includes_kda(tmp_path: Path, monkeypatch) -> None:
    from coaches import adaptation_hint
    import agents.agent2_backend.db_schema as dbs

    monkeypatch.setattr(dbs, "DB_DIR", tmp_path)
    monkeypatch.setattr(adaptation_hint, "DB_DIR", tmp_path)
    dbs.init_mode("aram")

    db = tmp_path / "aram.db"
    aj = {
        "win_rate": 0.55, "recent_win_rate": None, "recent_sample_size": 0,
        "avg_duration_sec": 1200.0,
        "avg_kda": {"k": 8.0, "d": 5.2, "a": 13.2, "ratio": 4.08, "sample": 12},
    }
    with sqlite3.connect(db) as conn:
        conn.execute(
            """INSERT INTO adaptation_buckets
               (champion, games_played, wins, losses, avg_rating, last_updated, aggregates_json)
               VALUES ('Ahri', 20, 11, 9, 0.55, '2026-04-22T00:00:00Z', ?)""",
            (json.dumps(aj),),
        )
        conn.commit()

    line = adaptation_hint.format_hint_line("Ahri", "aram")
    assert "typical KDA" in line
    assert "4.08" in line
    assert "8.0/5.2/13.2" in line
    assert "n=12" in line


def test_hint_line_omits_kda_below_sample(tmp_path: Path, monkeypatch) -> None:
    """Below the 5-game floor the KDA segment shouldn't appear."""
    from coaches import adaptation_hint
    import agents.agent2_backend.db_schema as dbs

    monkeypatch.setattr(dbs, "DB_DIR", tmp_path)
    monkeypatch.setattr(adaptation_hint, "DB_DIR", tmp_path)
    dbs.init_mode("aram")

    db = tmp_path / "aram.db"
    aj = {
        "win_rate": 0.55, "recent_win_rate": None, "recent_sample_size": 0,
        "avg_kda": {"k": 1, "d": 1, "a": 1, "ratio": 2.0, "sample": 3},
    }
    with sqlite3.connect(db) as conn:
        conn.execute(
            """INSERT INTO adaptation_buckets
               (champion, games_played, wins, losses, avg_rating, last_updated, aggregates_json)
               VALUES ('Ahri', 20, 11, 9, 0.55, '2026-04-22T00:00:00Z', ?)""",
            (json.dumps(aj),),
        )
        conn.commit()

    line = adaptation_hint.format_hint_line("Ahri", "aram")
    assert "typical KDA" not in line


def test_for_champion_exposes_avg_kda(tmp_path: Path, monkeypatch) -> None:
    from coaches import adaptation_hint
    import agents.agent2_backend.db_schema as dbs

    monkeypatch.setattr(dbs, "DB_DIR", tmp_path)
    monkeypatch.setattr(adaptation_hint, "DB_DIR", tmp_path)
    dbs.init_mode("aram")

    db = tmp_path / "aram.db"
    aj = {
        "win_rate": 0.55, "recent_win_rate": None, "recent_sample_size": 0,
        "avg_kda": {"k": 9, "d": 4, "a": 14, "ratio": 5.75, "sample": 40},
    }
    with sqlite3.connect(db) as conn:
        conn.execute(
            """INSERT INTO adaptation_buckets
               (champion, games_played, wins, losses, avg_rating, last_updated, aggregates_json)
               VALUES ('Ahri', 40, 22, 18, 0.55, '2026-04-22T00:00:00Z', ?)""",
            (json.dumps(aj),),
        )
        conn.commit()

    data = adaptation_hint.for_champion("Ahri", "aram")
    assert data["avg_kda"] == {"k": 9, "d": 4, "a": 14, "ratio": 5.75, "sample": 40}
