"""Round 38 — insight_detector: digest-driven advisory filer."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _init(tmp_path: Path, monkeypatch):
    import agents.agent2_backend.db_schema as dbs
    from coaches import adaptation_hint
    import agents.agent4_coach_mentor.insight_detector as det
    monkeypatch.setattr(dbs, "DB_DIR", tmp_path)
    monkeypatch.setattr(adaptation_hint, "DB_DIR", tmp_path)
    monkeypatch.setattr(det, "COOLDOWN_FILE", tmp_path / "insight_cooldowns.json")
    for mode in ("aram", "sr_ranked"):
        dbs.init_mode(mode)


def _seed_bucket(db: Path, champ: str, aj: dict, games: int = 20,
                 wr: float = 0.55) -> None:
    with sqlite3.connect(db) as conn:
        wins = int(games * wr)
        conn.execute(
            """INSERT INTO adaptation_buckets
               (champion, games_played, wins, losses, avg_rating, last_updated, aggregates_json)
               VALUES (?, ?, ?, ?, ?, '2026-04-22T00:00:00Z', ?)""",
            (champ, games, wins, games - wins, wr, json.dumps(aj)),
        )
        conn.commit()


def _insert_match(db: Path, champ: str, win: int | None,
                  duration_sec: int, started_at: str,
                  k: int = 5, d: int = 5, a: int = 10) -> None:
    with sqlite3.connect(db) as conn:
        conn.execute(
            """INSERT INTO matches
               (started_at, champion, ally_champions, enemy_champions,
                duration_sec, win, source, kills, deaths, assists)
               VALUES (?, ?, '[]', '[]', ?, ?, 'live-phase3', ?, ?, ?)""",
            (started_at, champ, duration_sec, win, k, d, a),
        )
        conn.commit()


class FakeScheduler:
    def __init__(self):
        self.filed: list = []
    def file_task(self, **kw):
        t = type("T", (), {})()
        t.id = f"fake-{len(self.filed) + 1}"
        self.filed.append({**kw, "id": t.id})
        return t


# ── severity filter ─────────────────────────────────────────────────

def test_files_only_above_severity_floor(tmp_path: Path, monkeypatch) -> None:
    from agents.agent4_coach_mentor.insight_detector import detect_insights_and_file
    _init(tmp_path, monkeypatch)

    # Build a scenario that generates a worst_hour with severity >= 0.7:
    # 5 wins at 10am, 6 losses at 3am. With avg_wr ~= 0.45 and
    # worst = 0.0, gap is 0.45, severity = min(0.8, 0.45 * 4) = 0.8.
    now = datetime.now().astimezone()
    for _ in range(5):
        ts = now.replace(hour=10, minute=0, second=0, microsecond=0).isoformat()
        _insert_match(tmp_path / "aram.db", "Ahri", 1, 1200, ts)
    for _ in range(6):
        ts = now.replace(hour=3, minute=0, second=0, microsecond=0).isoformat()
        _insert_match(tmp_path / "aram.db", "Ahri", 0, 1200, ts)

    sched = FakeScheduler()
    out = detect_insights_and_file(sched, modes=("aram",), severity_floor=0.7)
    # At least one worst_hour insight should fire; cold/hot streaks
    # aren't seeded here.
    assert len(out["filed"]) >= 1
    op = sched.filed[0]["op"]
    assert op == "coaching-insight-advisory"


def test_skips_below_floor(tmp_path: Path, monkeypatch) -> None:
    from agents.agent4_coach_mentor.insight_detector import detect_insights_and_file
    _init(tmp_path, monkeypatch)
    # Mild-only signal, nothing should clear severity 0.7.
    _seed_bucket(tmp_path / "aram.db", "Mild", {
        "win_rate": 0.5,
        "avg_kda": {"ratio": 3.0, "sample": 30},
        "recent_kda": {"ratio": 3.2, "sample": 10, "delta_ratio": 0.2},
    })
    sched = FakeScheduler()
    out = detect_insights_and_file(sched, modes=("aram",), severity_floor=0.7)
    assert out["filed"] == []
    assert out["skipped_severity"] >= 0


def test_skips_cold_streak_type(tmp_path: Path, monkeypatch) -> None:
    """Cold-streak advisories are owned by cold_streak_detector —
    insight_detector must not duplicate them."""
    from agents.agent4_coach_mentor.insight_detector import detect_insights_and_file
    _init(tmp_path, monkeypatch)
    _seed_bucket(tmp_path / "aram.db", "Crash", {
        "win_rate": 0.5,
        "avg_kda": {"ratio": 5.0, "sample": 30},
        "recent_kda": {"ratio": 1.0, "sample": 10, "delta_ratio": -4.0},
    })
    sched = FakeScheduler()
    out = detect_insights_and_file(sched, modes=("aram",), severity_floor=0.5)
    assert all(f["type"] != "cold_streak" for f in out["filed"])
    assert out["skipped_type"] >= 1


# ── cooldown ────────────────────────────────────────────────────────

def test_cooldown_prevents_duplicate(tmp_path: Path, monkeypatch) -> None:
    from agents.agent4_coach_mentor.insight_detector import detect_insights_and_file
    _init(tmp_path, monkeypatch)
    # Build a worst_hour scenario severity >= 0.7.
    now = datetime.now().astimezone()
    for _ in range(5):
        ts = now.replace(hour=10, minute=0, second=0, microsecond=0).isoformat()
        _insert_match(tmp_path / "aram.db", "Ahri", 1, 1200, ts)
    for _ in range(6):
        ts = now.replace(hour=3, minute=0, second=0, microsecond=0).isoformat()
        _insert_match(tmp_path / "aram.db", "Ahri", 0, 1200, ts)

    sched = FakeScheduler()
    first = detect_insights_and_file(sched, modes=("aram",), severity_floor=0.7)
    initial = len(sched.filed)
    assert initial >= 1
    second = detect_insights_and_file(sched, modes=("aram",), severity_floor=0.7)
    assert len(sched.filed) == initial
    assert len(second["skipped_cooldown"]) >= 1


def test_cooldown_expires(tmp_path: Path, monkeypatch) -> None:
    from agents.agent4_coach_mentor.insight_detector import detect_insights_and_file
    _init(tmp_path, monkeypatch)
    now_local = datetime.now().astimezone()
    for _ in range(5):
        ts = now_local.replace(hour=10).isoformat()
        _insert_match(tmp_path / "aram.db", "Ahri", 1, 1200, ts)
    for _ in range(6):
        ts = now_local.replace(hour=3).isoformat()
        _insert_match(tmp_path / "aram.db", "Ahri", 0, 1200, ts)

    sched = FakeScheduler()
    detect_insights_and_file(sched, modes=("aram",), severity_floor=0.7)
    initial = len(sched.filed)
    # Zero cooldown → next pass re-fires.
    detect_insights_and_file(sched, modes=("aram",), severity_floor=0.7,
                             cooldown_hours=0)
    assert len(sched.filed) > initial


def test_cooldown_keys_include_scope(tmp_path: Path, monkeypatch) -> None:
    """Two different insight scopes (e.g. different hours) must each
    get their own cooldown — one shouldn't block the other."""
    from agents.agent4_coach_mentor.insight_detector import _cooldown_key
    key_a = _cooldown_key({
        "type": "worst_hour", "mode": "aram",
        "data": {"hour": 3},
    })
    key_b = _cooldown_key({
        "type": "worst_hour", "mode": "aram",
        "data": {"hour": 8},
    })
    assert key_a != key_b


def test_cooldown_keys_include_champion(tmp_path: Path, monkeypatch) -> None:
    from agents.agent4_coach_mentor.insight_detector import _cooldown_key
    key_jinx = _cooldown_key({
        "type": "hot_streak", "mode": "aram",
        "champion": "Jinx", "data": {},
    })
    key_ahri = _cooldown_key({
        "type": "hot_streak", "mode": "aram",
        "champion": "Ahri", "data": {},
    })
    assert key_jinx != key_ahri


# ── payload shape ───────────────────────────────────────────────────

def test_filed_payload_has_insight_fields(tmp_path: Path, monkeypatch) -> None:
    from agents.agent4_coach_mentor.insight_detector import detect_insights_and_file
    _init(tmp_path, monkeypatch)
    now = datetime.now().astimezone()
    for _ in range(5):
        ts = now.replace(hour=10).isoformat()
        _insert_match(tmp_path / "aram.db", "Ahri", 1, 1200, ts)
    for _ in range(6):
        ts = now.replace(hour=3).isoformat()
        _insert_match(tmp_path / "aram.db", "Ahri", 0, 1200, ts)

    sched = FakeScheduler()
    detect_insights_and_file(sched, modes=("aram",), severity_floor=0.7)
    assert sched.filed, "expected at least one filed advisory"
    payload = sched.filed[0]["payload"]
    assert "insight_type" in payload
    assert "severity" in payload
    assert payload["severity"] >= 0.7
    assert "message" in payload
    assert "detected_at" in payload
    # Scheduler op args match our convention.
    assert sched.filed[0]["owner_agent"] == "1"
    assert sched.filed[0]["op"] == "coaching-insight-advisory"


# ── supervisor /api/advisories surface ──────────────────────────────

def test_api_advisories_whitelists_new_op() -> None:
    sup = Path("agents/supervisor.py").read_text(encoding="utf-8")
    assert '"coaching-insight-advisory"' in sup
    # Shape-differentiation branch must exist for the new op.
    assert 'op == "coaching-insight-advisory"' in sup


# ── auto-analyze wires the new detector ─────────────────────────────

def test_supervisor_wires_insight_detector() -> None:
    sup = Path("agents/supervisor.py").read_text(encoding="utf-8")
    assert "from agents.agent4_coach_mentor.insight_detector import" in sup
    assert "detect_insights_and_file" in sup
