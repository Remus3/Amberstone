"""Round 33 - session_games timeline + /api/session-games + --games CLI."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _init(tmp_path: Path, monkeypatch):
    import agents.agent2_backend.db_schema as dbs
    from coaches import adaptation_hint
    monkeypatch.setattr(dbs, "DB_DIR", tmp_path)
    monkeypatch.setattr(adaptation_hint, "DB_DIR", tmp_path)
    for mode in ("aram", "sr_ranked"):
        dbs.init_mode(mode)


def _insert(db: Path, champ: str, win: int | None, k: int | None, d: int | None,
            a: int | None, started_at: str, duration: int = 1200) -> None:
    with sqlite3.connect(db) as conn:
        conn.execute(
            """INSERT INTO matches
               (started_at, champion, ally_champions, enemy_champions,
                duration_sec, win, source, kills, deaths, assists)
               VALUES (?, ?, '[]', '[]', ?, ?, 'live-phase3', ?, ?, ?)""",
            (started_at, champ, duration, win, k, d, a),
        )
        conn.commit()


# ── session_games ordering + shape ──────────────────────────────────

def test_session_games_returns_chronological_order(tmp_path: Path, monkeypatch) -> None:
    from coaches.adaptation_hint import session_games
    _init(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    _insert(tmp_path / "aram.db", "Ahri", 1, 10, 3, 15,
            (now - timedelta(hours=2)).isoformat())
    _insert(tmp_path / "aram.db", "Jinx", 0, 5, 8, 10,
            (now - timedelta(hours=5)).isoformat())
    _insert(tmp_path / "sr_ranked.db", "Vladimir", 1, 8, 4, 12,
            (now - timedelta(hours=3)).isoformat())
    rows = session_games((now - timedelta(hours=24)).isoformat())
    assert len(rows) == 3
    # Oldest-first: Jinx 5h ago → Vladimir 3h ago → Ahri 2h ago.
    assert [r["champion"] for r in rows] == ["Jinx", "Vladimir", "Ahri"]


def test_session_games_includes_kda_and_ratio(tmp_path: Path, monkeypatch) -> None:
    from coaches.adaptation_hint import session_games
    _init(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    _insert(tmp_path / "aram.db", "Ahri", 1, 10, 3, 15,
            (now - timedelta(hours=1)).isoformat())
    rows = session_games((now - timedelta(hours=2)).isoformat())
    row = rows[0]
    assert row["champion"] == "Ahri"
    assert row["win"] == 1
    assert row["kda"] == {"k": 10, "d": 3, "a": 15}
    assert row["kda_ratio"] == 8.33
    assert row["mode"] == "aram"
    assert row["duration_sec"] == 1200


def test_session_games_null_kda_yields_none_ratio(tmp_path: Path, monkeypatch) -> None:
    from coaches.adaptation_hint import session_games
    _init(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    _insert(tmp_path / "aram.db", "Ahri", 1, None, None, None,
            (now - timedelta(hours=1)).isoformat())
    rows = session_games((now - timedelta(hours=2)).isoformat())
    row = rows[0]
    assert row["kda"] is None
    assert row["kda_ratio"] is None


def test_session_games_limit_takes_tail(tmp_path: Path, monkeypatch) -> None:
    """With a limit, we want the most-recent games - the tail."""
    from coaches.adaptation_hint import session_games
    _init(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    for i in range(10):
        ts = (now - timedelta(hours=10 - i)).isoformat()
        _insert(tmp_path / "aram.db", f"Ch{i}", 1, 1, 1, 1, ts)
    rows = session_games((now - timedelta(hours=24)).isoformat(), limit=3)
    assert len(rows) == 3
    # The 3 most recent are Ch7, Ch8, Ch9.
    assert [r["champion"] for r in rows] == ["Ch7", "Ch8", "Ch9"]


def test_session_games_empty_when_since_in_future(tmp_path: Path, monkeypatch) -> None:
    from coaches.adaptation_hint import session_games
    _init(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    _insert(tmp_path / "aram.db", "Ahri", 1, 5, 5, 5, (now - timedelta(hours=1)).isoformat())
    rows = session_games((now + timedelta(hours=1)).isoformat())
    assert rows == []


def test_session_games_survives_missing_db(tmp_path: Path, monkeypatch) -> None:
    """If a mode DB doesn't exist, we skip it without raising."""
    from coaches.adaptation_hint import session_games
    import agents.agent2_backend.db_schema as dbs
    from coaches import adaptation_hint
    monkeypatch.setattr(dbs, "DB_DIR", tmp_path)
    monkeypatch.setattr(adaptation_hint, "DB_DIR", tmp_path)
    # Only init one mode; the others are absent.
    dbs.init_mode("aram")
    now = datetime.now(timezone.utc)
    _insert(tmp_path / "aram.db", "Ahri", 1, 5, 3, 10,
            (now - timedelta(hours=1)).isoformat())
    rows = session_games((now - timedelta(hours=2)).isoformat())
    assert len(rows) == 1


# ── CLI --games ─────────────────────────────────────────────────────

def test_cli_games_text(tmp_path: Path, monkeypatch, capsys) -> None:
    from coaches.adaptation_hint import main
    _init(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    _insert(tmp_path / "aram.db", "Ahri", 1, 10, 3, 15,
            (now - timedelta(hours=1)).isoformat())
    _insert(tmp_path / "aram.db", "Jinx", 0, 5, 8, 10,
            (now - timedelta(hours=2)).isoformat())
    rc = main(["--games", "--since", "24h"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Games since 24h" in out
    assert "Ahri" in out
    assert "Jinx" in out
    assert "W" in out and "L" in out
    # Order is chronological → Jinx appears before Ahri.
    assert out.index("Jinx") < out.index("Ahri")


def test_cli_games_json(tmp_path: Path, monkeypatch, capsys) -> None:
    from coaches.adaptation_hint import main
    _init(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    _insert(tmp_path / "aram.db", "Ahri", 1, 10, 3, 15,
            (now - timedelta(hours=1)).isoformat())
    rc = main(["--games", "--since", "24h", "-f", "json"])
    assert rc == 0
    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == 1
    assert rows[0]["kda_ratio"] == 8.33


def test_cli_games_limit(tmp_path: Path, monkeypatch, capsys) -> None:
    from coaches.adaptation_hint import main
    _init(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    for i in range(8):
        ts = (now - timedelta(hours=8 - i)).isoformat()
        _insert(tmp_path / "aram.db", f"Ch{i}", 1, 1, 1, 1, ts)
    rc = main(["--games", "--since", "24h", "--limit", "3", "-f", "json"])
    rows = json.loads(capsys.readouterr().out)
    assert rc == 0 and len(rows) == 3


def test_cli_text_empty_games(tmp_path: Path, monkeypatch, capsys) -> None:
    from coaches.adaptation_hint import main
    _init(tmp_path, monkeypatch)
    rc = main(["--games", "--since", "24h"])
    assert rc == 0
    assert "(no games)" in capsys.readouterr().out


# ── supervisor endpoint registration ────────────────────────────────

def test_supervisor_registers_session_games_route() -> None:
    # s243: handler split byte-verbatim into _supervisor_http.py
    # (supervisor.py is now a facade); runtime routing unchanged.
    sup = Path("agents/_supervisor_http.py").read_text(encoding="utf-8")
    assert "/api/session-games" in sup
    assert "_handle_session_games" in sup
