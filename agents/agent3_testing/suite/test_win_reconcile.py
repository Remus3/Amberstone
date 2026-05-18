"""Round 21 - win-signal reconciler (postgame_stats.db → mode DB)."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agents.agent2_backend.db_schema import SCHEMA_STATEMENTS


def _make_postgame_db(path: Path) -> None:
    """Stand up just the minimum columns the reconciler queries on."""
    with sqlite3.connect(path) as conn:
        conn.execute("""
            CREATE TABLE aram_player_stats (
                id INTEGER PRIMARY KEY,
                match_id TEXT, game_mode TEXT,
                champion_name TEXT, team_id INTEGER,
                team_result TEXT, is_local_player INTEGER,
                captured_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE sr_player_stats (
                id INTEGER PRIMARY KEY,
                match_id TEXT, game_mode TEXT,
                champion_name TEXT, team_id INTEGER,
                team_result TEXT, is_local_player INTEGER,
                captured_at TEXT
            )
        """)
        conn.commit()


def _make_mode_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        for stmt in SCHEMA_STATEMENTS:
            conn.execute(stmt)
        conn.commit()


@pytest.fixture()
def wired(tmp_path: Path, monkeypatch) -> Path:
    """Redirect the reconciler's DB paths to tmp_path and seed both DBs."""
    mode_dir = tmp_path / "db"
    mode_dir.mkdir()
    _make_mode_db(mode_dir / "aram.db")
    _make_mode_db(mode_dir / "sr_ranked.db")

    pg_db = tmp_path / "postgame_stats.db"
    _make_postgame_db(pg_db)

    import agents.agent2_backend.win_reconcile as wr_mod
    monkeypatch.setattr(wr_mod, "MODE_DB_DIR", mode_dir)
    monkeypatch.setattr(wr_mod, "POSTGAME_DB", pg_db)
    return tmp_path


def _insert_live_match(
    db_path: Path, champion: str, ended_at: datetime,
    duration_sec: int = 1200,
) -> int:
    started = (ended_at - timedelta(seconds=duration_sec)).isoformat()
    ended_iso = ended_at.isoformat()
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO matches
              (started_at, ended_at, champion, ally_champions, enemy_champions,
               duration_sec, win, final_rating_json, source)
            VALUES (?, ?, ?, '[]', '[]', ?, NULL, NULL, 'live-phase3')
            """,
            (started, ended_iso, champion, duration_sec),
        )
        conn.commit()
        return int(cur.lastrowid)


def _insert_postgame_stats(
    pg_path: Path, table: str, champion: str,
    captured_at: datetime, team_result: str, is_local: int = 1,
) -> None:
    with sqlite3.connect(pg_path) as conn:
        conn.execute(
            f"""
            INSERT INTO {table}
              (match_id, game_mode, champion_name, team_id,
               team_result, is_local_player, captured_at)
            VALUES ('mid-?', 'ARAM', ?, 100, ?, ?, ?)
            """,
            (champion, team_result, is_local, captured_at.isoformat()),
        )
        conn.commit()


def test_reconcile_populates_win(wired: Path) -> None:
    from agents.agent2_backend.win_reconcile import reconcile_mode
    ended = datetime(2026, 4, 22, 16, 0, tzinfo=timezone.utc)
    mid = _insert_live_match(wired / "db" / "aram.db", "Ahri", ended)
    _insert_postgame_stats(
        wired / "postgame_stats.db", "aram_player_stats",
        "Ahri", ended + timedelta(seconds=10), "WIN",
    )

    result = reconcile_mode("aram")
    assert result["scanned"] == 1
    assert result["patched"] == 1
    with sqlite3.connect(wired / "db" / "aram.db") as conn:
        win = conn.execute(
            "SELECT win FROM matches WHERE match_id = ?", (mid,)
        ).fetchone()[0]
    assert win == 1


def test_reconcile_handles_loss(wired: Path) -> None:
    from agents.agent2_backend.win_reconcile import reconcile_mode
    ended = datetime(2026, 4, 22, 16, 0, tzinfo=timezone.utc)
    _insert_live_match(wired / "db" / "aram.db", "Ahri", ended)
    _insert_postgame_stats(
        wired / "postgame_stats.db", "aram_player_stats",
        "Ahri", ended + timedelta(seconds=20), "LOSS",
    )
    reconcile_mode("aram")
    with sqlite3.connect(wired / "db" / "aram.db") as conn:
        win = conn.execute(
            "SELECT win FROM matches WHERE source='live-phase3'"
        ).fetchone()[0]
    assert win == 0


def test_reconcile_skips_no_candidate(wired: Path) -> None:
    from agents.agent2_backend.win_reconcile import reconcile_mode
    _insert_live_match(
        wired / "db" / "aram.db", "Ahri",
        datetime(2026, 4, 22, 16, 0, tzinfo=timezone.utc),
    )
    # postgame_stats is empty for this champion - no match.
    result = reconcile_mode("aram")
    assert result["scanned"] == 1
    assert result["patched"] == 0
    assert result["skipped_no_match"] == 1


def test_reconcile_champion_mismatch_not_matched(wired: Path) -> None:
    from agents.agent2_backend.win_reconcile import reconcile_mode
    ended = datetime(2026, 4, 22, 16, 0, tzinfo=timezone.utc)
    _insert_live_match(wired / "db" / "aram.db", "Ahri", ended)
    _insert_postgame_stats(
        wired / "postgame_stats.db", "aram_player_stats",
        "Lux", ended + timedelta(seconds=10), "WIN",
    )
    result = reconcile_mode("aram")
    assert result["skipped_no_match"] == 1
    with sqlite3.connect(wired / "db" / "aram.db") as conn:
        win = conn.execute(
            "SELECT win FROM matches WHERE source='live-phase3'"
        ).fetchone()[0]
    assert win is None


def test_reconcile_skips_non_local_player(wired: Path) -> None:
    from agents.agent2_backend.win_reconcile import reconcile_mode
    ended = datetime(2026, 4, 22, 16, 0, tzinfo=timezone.utc)
    _insert_live_match(wired / "db" / "aram.db", "Ahri", ended)
    # Another Ahri match but from a teammate, not local player.
    _insert_postgame_stats(
        wired / "postgame_stats.db", "aram_player_stats",
        "Ahri", ended + timedelta(seconds=15), "WIN", is_local=0,
    )
    result = reconcile_mode("aram")
    assert result["skipped_no_match"] == 1


def test_reconcile_idempotent_does_not_overwrite_existing(wired: Path) -> None:
    """If win is already set, reconciler leaves it alone."""
    from agents.agent2_backend.win_reconcile import reconcile_mode
    ended = datetime(2026, 4, 22, 16, 0, tzinfo=timezone.utc)
    # Insert with win already set to 1.
    with sqlite3.connect(wired / "db" / "aram.db") as conn:
        conn.execute(
            """
            INSERT INTO matches
              (started_at, ended_at, champion, ally_champions, enemy_champions,
               duration_sec, win, final_rating_json, source)
            VALUES (?, ?, 'Ahri', '[]', '[]', 1200, 1, NULL, 'live-phase3')
            """,
            ((ended - timedelta(seconds=1200)).isoformat(), ended.isoformat()),
        )
        conn.commit()
    # Postgame says LOSS - but we should NOT overwrite the existing 1.
    _insert_postgame_stats(
        wired / "postgame_stats.db", "aram_player_stats",
        "Ahri", ended, "LOSS",
    )
    result = reconcile_mode("aram")
    assert result["scanned"] == 0   # only NULL-win rows are scanned
    with sqlite3.connect(wired / "db" / "aram.db") as conn:
        win = conn.execute(
            "SELECT win FROM matches WHERE source='live-phase3'"
        ).fetchone()[0]
    assert win == 1


def test_reconcile_outside_window_no_match(wired: Path) -> None:
    from agents.agent2_backend.win_reconcile import reconcile_mode
    ended = datetime(2026, 4, 22, 16, 0, tzinfo=timezone.utc)
    _insert_live_match(wired / "db" / "aram.db", "Ahri", ended)
    # Postgame row is an hour later - well outside the 10-min window.
    _insert_postgame_stats(
        wired / "postgame_stats.db", "aram_player_stats",
        "Ahri", ended + timedelta(hours=1), "WIN",
    )
    result = reconcile_mode("aram")
    assert result["skipped_no_match"] == 1


def test_reconcile_ambiguous_two_close_diff_results(wired: Path) -> None:
    from agents.agent2_backend.win_reconcile import reconcile_mode
    ended = datetime(2026, 4, 22, 16, 0, tzinfo=timezone.utc)
    _insert_live_match(wired / "db" / "aram.db", "Ahri", ended)
    # Two postgame rows 2s apart with conflicting team_result - bail out.
    _insert_postgame_stats(
        wired / "postgame_stats.db", "aram_player_stats",
        "Ahri", ended + timedelta(seconds=10), "WIN",
    )
    _insert_postgame_stats(
        wired / "postgame_stats.db", "aram_player_stats",
        "Ahri", ended + timedelta(seconds=12), "LOSS",
    )
    result = reconcile_mode("aram")
    assert result["skipped_ambig"] == 1
    assert result["patched"] == 0


def test_reconcile_all_returns_dict_of_modes(wired: Path) -> None:
    from agents.agent2_backend.win_reconcile import reconcile_all
    out = reconcile_all()
    # Every mapped mode shows up.
    assert "aram" in out
    assert "sr_ranked" in out
    assert "arena" in out
    assert "brawl" in out


def test_reconcile_mode_with_missing_db_returns_skip(wired: Path, monkeypatch) -> None:
    import agents.agent2_backend.win_reconcile as wr_mod
    # Point at a non-existent directory.
    monkeypatch.setattr(wr_mod, "MODE_DB_DIR", wired / "does-not-exist")
    out = wr_mod.reconcile_mode("aram")
    assert out["skipped"] is True
    assert "mode DB missing" in out["reason"]
