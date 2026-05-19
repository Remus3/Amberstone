"""Round 29 - session_summary helper + /api/session endpoint + --session CLI."""
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
            a: int | None, started_at: str) -> None:
    with sqlite3.connect(db) as conn:
        conn.execute(
            """INSERT INTO matches
               (started_at, champion, ally_champions, enemy_champions,
                duration_sec, win, source, kills, deaths, assists)
               VALUES (?, ?, '[]', '[]', 1200, ?, 'live-phase3', ?, ?, ?)""",
            (started_at, champ, win, k, d, a),
        )
        conn.commit()


# ── session_summary semantics ───────────────────────────────────────

def test_session_summary_filters_by_since(tmp_path: Path, monkeypatch) -> None:
    from coaches.adaptation_hint import session_summary
    _init(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(hours=2)).isoformat()
    old = (now - timedelta(days=3)).isoformat()
    _insert(tmp_path / "aram.db", "Ahri", 1, 10, 3, 15, recent)
    _insert(tmp_path / "aram.db", "Jinx", 0, 5, 8, 10, recent)
    _insert(tmp_path / "aram.db", "OldChamp", 1, 1, 1, 1, old)
    since = (now - timedelta(hours=12)).isoformat()
    data = session_summary(since)
    assert data["games"] == 2
    assert data["wins"] == 1
    assert data["losses"] == 1
    assert data["win_rate"] == 0.5


def test_session_summary_per_mode_breakdown(tmp_path: Path, monkeypatch) -> None:
    from coaches.adaptation_hint import session_summary
    _init(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    ts = (now - timedelta(hours=1)).isoformat()
    _insert(tmp_path / "aram.db", "Ahri", 1, 10, 3, 15, ts)
    _insert(tmp_path / "aram.db", "Ahri", 1, 8, 5, 12, ts)
    _insert(tmp_path / "sr_ranked.db", "Vladimir", 0, 6, 10, 8, ts)
    data = session_summary((now - timedelta(hours=12)).isoformat())
    assert data["per_mode"]["aram"]["games"] == 2
    assert data["per_mode"]["aram"]["wins"] == 2
    # (10+8)/2=9 k, (3+5)/2=4 d, (15+12)/2=13.5 a → (9+13.5)/4 = 5.625
    assert data["per_mode"]["aram"]["kda_ratio"] == 5.62
    assert data["per_mode"]["sr_ranked"]["games"] == 1
    assert data["per_mode"]["sr_ranked"]["losses"] == 1


def test_session_summary_champion_rollup(tmp_path: Path, monkeypatch) -> None:
    from coaches.adaptation_hint import session_summary
    _init(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    ts = (now - timedelta(hours=1)).isoformat()
    # Same champ across two modes - should collapse.
    _insert(tmp_path / "aram.db", "Ahri", 1, 10, 3, 15, ts)
    _insert(tmp_path / "sr_ranked.db", "Ahri", 0, 5, 10, 8, ts)
    data = session_summary((now - timedelta(hours=12)).isoformat())
    ahri = next(c for c in data["champions"] if c["champion"] == "Ahri")
    assert ahri["games"] == 2
    assert ahri["wins"] == 1
    assert ahri["losses"] == 1
    assert sorted(ahri["modes"]) == ["aram", "sr_ranked"]
    assert ahri["kda_sample"] == 2


def test_session_summary_handles_null_win(tmp_path: Path, monkeypatch) -> None:
    """Live matches with win=NULL should still count towards games but
    not inflate W/L."""
    from coaches.adaptation_hint import session_summary
    _init(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    ts = (now - timedelta(hours=1)).isoformat()
    _insert(tmp_path / "aram.db", "Ahri", None, 10, 3, 15, ts)
    data = session_summary((now - timedelta(hours=12)).isoformat())
    assert data["games"] == 1
    assert data["wins"] == 0
    assert data["losses"] == 0
    assert data["win_rate"] is None     # no reported games
    # KDA still accrues.
    assert data["avg_kda"]["sample"] == 1


def test_session_summary_empty_when_nothing_recent(tmp_path: Path, monkeypatch) -> None:
    from coaches.adaptation_hint import session_summary
    _init(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    data = session_summary((now + timedelta(hours=1)).isoformat())
    assert data["games"] == 0
    assert data["wins"] == 0
    assert data["win_rate"] is None
    assert data["avg_kda"] is None
    assert data["champions"] == []


# ── _parse_since helpers ────────────────────────────────────────────

def test_parse_since_today() -> None:
    from coaches.adaptation_hint import _parse_since, _start_of_today_iso
    assert _parse_since("today") == _start_of_today_iso()
    assert _parse_since("") == _start_of_today_iso()


def test_parse_since_hours_and_days() -> None:
    from coaches.adaptation_hint import _parse_since
    import datetime as _dt
    now = _dt.datetime.now().astimezone()
    parsed = _dt.datetime.fromisoformat(_parse_since("24h"))
    delta = now - parsed
    assert 23 * 3600 < delta.total_seconds() < 25 * 3600
    parsed_d = _dt.datetime.fromisoformat(_parse_since("7d"))
    delta_d = now - parsed_d
    assert 6.5 * 86400 < delta_d.total_seconds() < 7.5 * 86400


def test_parse_since_passthrough_iso() -> None:
    from coaches.adaptation_hint import _parse_since
    raw = "2026-04-15T10:00:00+00:00"
    assert _parse_since(raw) == raw


# ── CLI --session ───────────────────────────────────────────────────

def test_cli_session_text(tmp_path: Path, monkeypatch, capsys) -> None:
    from coaches.adaptation_hint import main
    _init(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    ts = (now - timedelta(hours=1)).isoformat()
    _insert(tmp_path / "aram.db", "Ahri", 1, 10, 3, 15, ts)
    rc = main(["--session", "--since", "24h"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Session summary" in out
    assert "Ahri" in out
    assert "1 games" in out or "1 games · 1W-0L" in out


def test_cli_session_json(tmp_path: Path, monkeypatch, capsys) -> None:
    from coaches.adaptation_hint import main
    _init(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    ts = (now - timedelta(hours=1)).isoformat()
    _insert(tmp_path / "aram.db", "Ahri", 1, 10, 3, 15, ts)
    rc = main(["--session", "--since", "24h", "-f", "json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["games"] == 1
    assert data["avg_kda"]["ratio"] == 8.33


def test_supervisor_registers_session_route() -> None:
    # s243: handler split byte-verbatim into _supervisor_http.py
    # (supervisor.py is now a facade); runtime routing unchanged.
    sup = Path("agents/_supervisor_http.py").read_text(encoding="utf-8")
    assert "/api/session" in sup
    assert "_handle_session" in sup
