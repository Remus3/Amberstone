"""Round 30 - win-signal inference in game_ingest."""
from __future__ import annotations

import sqlite3
from pathlib import Path


def _init(tmp_path: Path, monkeypatch):
    import agents.agent2_backend.game_ingest as gi
    import agents.agent2_backend.db_schema as dbs
    monkeypatch.setattr(dbs, "DB_DIR", tmp_path)
    monkeypatch.setattr(gi, "DB_DIR", tmp_path)
    dbs.init_mode("aram")


BASE_PAYLOAD = {
    "game_mode": "ARAM",
    "champion": "Ahri",
    "game_time_s": 1200,
    "finished_at": "2026-04-22T12:00:00+00:00",
    "kda": "10/3/15",
}


# ── _infer_win direct unit ──────────────────────────────────────────

def test_infer_win_explicit_passthrough() -> None:
    from agents.agent2_backend.game_ingest import _infer_win
    assert _infer_win({"win": 1}) == 1
    assert _infer_win({"win": 0}) == 0
    # Falsy-but-present 0 must NOT fall through to string parsing.
    assert _infer_win({"win": 0, "action": "Victory"}) == 0


def test_infer_win_from_action_string() -> None:
    from agents.agent2_backend.game_ingest import _infer_win
    assert _infer_win({"action": "Victory"}) == 1
    assert _infer_win({"action": "defeat"}) == 0
    assert _infer_win({"action": "LOST"}) == 0
    assert _infer_win({"action": "in-progress"}) is None


def test_infer_win_from_label_string() -> None:
    from agents.agent2_backend.game_ingest import _infer_win
    assert _infer_win({"label": "Victory"}) == 1
    # Rating grades are not win signals - leave NULL.
    assert _infer_win({"label": "S+"}) is None
    assert _infer_win({"label": "A"}) is None


def test_infer_win_from_nested_stats() -> None:
    from agents.agent2_backend.game_ingest import _infer_win
    assert _infer_win({"stats": {"outcome": "victory"}}) == 1
    assert _infer_win({"stats": {"outcome": "defeat"}}) == 0
    assert _infer_win({"notes": {"result": "lose"}}) == 0
    assert _infer_win({"stats": {"win": True}}) == 1
    assert _infer_win({"stats": {"win": False}}) == 0
    assert _infer_win({"stats": {"win": 1}}) == 1
    assert _infer_win({"stats": {"win": 42}}) is None  # non-boolean int → ignored


def test_infer_win_empty_returns_none() -> None:
    from agents.agent2_backend.game_ingest import _infer_win
    assert _infer_win({}) is None
    assert _infer_win({"action": ""}) is None
    assert _infer_win({"action": "Unknown"}) is None


# ── end-to-end ingest behaviour ─────────────────────────────────────

def test_ingest_stores_win_from_action(tmp_path: Path, monkeypatch) -> None:
    from agents.agent2_backend.game_ingest import ingest_game_summary
    _init(tmp_path, monkeypatch)
    payload = {**BASE_PAYLOAD, "action": "Victory"}
    result = ingest_game_summary(payload)
    assert result["has_win_signal"] is True
    assert result["win"] == 1
    with sqlite3.connect(tmp_path / "aram.db") as conn:
        row = conn.execute(
            "SELECT win FROM matches WHERE match_id = ?",
            (result["match_id"],),
        ).fetchone()
    assert row[0] == 1


def test_ingest_stores_win_from_label(tmp_path: Path, monkeypatch) -> None:
    from agents.agent2_backend.game_ingest import ingest_game_summary
    _init(tmp_path, monkeypatch)
    # Note: rating labels are often grades ("S", "A+"). Only explicit
    # win/loss words count. Use an unambiguous word here.
    payload = {**BASE_PAYLOAD, "champion": "Jinx", "label": "Defeat"}
    result = ingest_game_summary(payload)
    assert result["win"] == 0
    with sqlite3.connect(tmp_path / "aram.db") as conn:
        row = conn.execute(
            "SELECT win FROM matches WHERE champion = 'Jinx'"
        ).fetchone()
    assert row[0] == 0


def test_ingest_leaves_win_null_without_signal(tmp_path: Path, monkeypatch) -> None:
    from agents.agent2_backend.game_ingest import ingest_game_summary
    _init(tmp_path, monkeypatch)
    payload = {**BASE_PAYLOAD, "champion": "Vayne", "label": "B+"}
    result = ingest_game_summary(payload)
    assert result["has_win_signal"] is False
    assert result["win"] is None
    with sqlite3.connect(tmp_path / "aram.db") as conn:
        row = conn.execute(
            "SELECT win FROM matches WHERE champion = 'Vayne'"
        ).fetchone()
    assert row[0] is None


def test_ingest_explicit_win_takes_precedence(tmp_path: Path, monkeypatch) -> None:
    """If the caller already resolved win, the string parser must not
    second-guess it - otherwise an off-label wrong string could flip."""
    from agents.agent2_backend.game_ingest import ingest_game_summary
    _init(tmp_path, monkeypatch)
    payload = {**BASE_PAYLOAD, "champion": "Zed", "win": 0, "action": "Victory"}
    result = ingest_game_summary(payload)
    assert result["win"] == 0
