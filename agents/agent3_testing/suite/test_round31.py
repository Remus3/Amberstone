"""Round 31 - cold-streak detector."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


def _init(tmp_path: Path, monkeypatch) -> Path:
    """Seed an aram DB + monkeypatch the cooldown file into tmp_path."""
    import agents.agent2_backend.db_schema as dbs
    from coaches import adaptation_hint
    import agents.agent4_coach_mentor.cold_streak_detector as det
    monkeypatch.setattr(dbs, "DB_DIR", tmp_path)
    monkeypatch.setattr(adaptation_hint, "DB_DIR", tmp_path)
    monkeypatch.setattr(det, "COOLDOWN_FILE", tmp_path / "cold_advisories.json")
    dbs.init_mode("aram")
    return tmp_path


def _seed_cold(db: Path, champ: str, delta: float, sample: int = 10) -> None:
    aj = {
        "win_rate": 0.5,
        "avg_kda": {"ratio": 4.0, "sample": 30},
        "recent_kda": {
            "ratio": 4.0 + delta, "sample": sample, "delta_ratio": delta,
        },
    }
    with sqlite3.connect(db) as conn:
        conn.execute(
            """INSERT INTO adaptation_buckets
               (champion, games_played, wins, losses, avg_rating, last_updated, aggregates_json)
               VALUES (?, 30, 15, 15, 0.5, '2026-04-22T00:00:00Z', ?)""",
            (champ, json.dumps(aj)),
        )
        conn.commit()


class FakeScheduler:
    def __init__(self):
        self.filed: list = []
    def file_task(self, *, op, owner_agent, priority, categories, payload, user_override):
        t = type("T", (), {})()
        t.id = f"fake-{len(self.filed) + 1}"
        self.filed.append({
            "op": op, "owner_agent": owner_agent, "priority": priority,
            "categories": categories, "payload": payload,
            "user_override": user_override, "id": t.id,
        })
        return t


# -- threshold filtering ---------------------------------------------

def test_fires_on_significant_cold_streak(tmp_path: Path, monkeypatch) -> None:
    from agents.agent4_coach_mentor.cold_streak_detector import detect_and_file
    _init(tmp_path, monkeypatch)
    _seed_cold(tmp_path / "aram.db", "Jinx", delta=-1.5)

    sched = FakeScheduler()
    summary = detect_and_file(sched, modes=("aram",))
    assert len(summary["filed"]) == 1
    assert sched.filed[0]["op"] == "cold-streak-advisory"
    assert sched.filed[0]["owner_agent"] == "1"   # deterministic - no LLM spawn
    assert sched.filed[0]["payload"]["champion"] == "Jinx"
    assert sched.filed[0]["payload"]["delta"] == -1.5


def test_ignores_below_delta_floor(tmp_path: Path, monkeypatch) -> None:
    from agents.agent4_coach_mentor.cold_streak_detector import detect_and_file
    _init(tmp_path, monkeypatch)
    _seed_cold(tmp_path / "aram.db", "Jinx", delta=-0.5)   # |delta| < 1.0
    sched = FakeScheduler()
    summary = detect_and_file(sched, modes=("aram",))
    assert summary["filed"] == []
    assert summary["below_threshold"] >= 1


def test_ignores_below_sample_floor(tmp_path: Path, monkeypatch) -> None:
    """delta passes threshold but sample is below the last-10 floor."""
    from agents.agent4_coach_mentor.cold_streak_detector import detect_and_file
    _init(tmp_path, monkeypatch)
    _seed_cold(tmp_path / "aram.db", "Jinx", delta=-2.0, sample=5)
    sched = FakeScheduler()
    summary = detect_and_file(sched, modes=("aram",))
    assert summary["filed"] == []


def test_ignores_hot_streaks(tmp_path: Path, monkeypatch) -> None:
    """Positive delta is not a cold streak."""
    from agents.agent4_coach_mentor.cold_streak_detector import detect_and_file
    _init(tmp_path, monkeypatch)
    _seed_cold(tmp_path / "aram.db", "Jinx", delta=+2.0)
    sched = FakeScheduler()
    summary = detect_and_file(sched, modes=("aram",))
    assert summary["filed"] == []


# -- cooldown --------------------------------------------------------

def test_cooldown_prevents_duplicate_file(tmp_path: Path, monkeypatch) -> None:
    from agents.agent4_coach_mentor.cold_streak_detector import detect_and_file
    _init(tmp_path, monkeypatch)
    _seed_cold(tmp_path / "aram.db", "Jinx", delta=-1.5)
    sched = FakeScheduler()
    detect_and_file(sched, modes=("aram",))
    assert len(sched.filed) == 1
    # Second pass within cooldown window must be a no-op.
    detect_and_file(sched, modes=("aram",))
    assert len(sched.filed) == 1


def test_cooldown_expires_after_window(tmp_path: Path, monkeypatch) -> None:
    from agents.agent4_coach_mentor.cold_streak_detector import detect_and_file
    _init(tmp_path, monkeypatch)
    import agents.agent4_coach_mentor.cold_streak_detector as det
    _seed_cold(tmp_path / "aram.db", "Jinx", delta=-1.5)

    # Pre-seed cooldown with a stale timestamp (25 h ago).
    stale = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    (tmp_path / "cold_advisories.json").write_text(
        json.dumps({"aram:Jinx": stale}), encoding="utf-8"
    )

    sched = FakeScheduler()
    summary = detect_and_file(sched, modes=("aram",))
    assert len(summary["filed"]) == 1


def test_custom_cooldown_hours_respected(tmp_path: Path, monkeypatch) -> None:
    from agents.agent4_coach_mentor.cold_streak_detector import detect_and_file
    _init(tmp_path, monkeypatch)
    _seed_cold(tmp_path / "aram.db", "Jinx", delta=-1.5)

    # Fresh filing - no prior cooldown.
    sched = FakeScheduler()
    detect_and_file(sched, modes=("aram",))
    assert len(sched.filed) == 1
    # With cooldown_hours=0, the next call should file again immediately.
    detect_and_file(sched, modes=("aram",), cooldown_hours=0)
    assert len(sched.filed) == 2


def test_cooldown_survives_corrupt_file(tmp_path: Path, monkeypatch) -> None:
    """A corrupt cooldown file mustn't block detection - treat as empty."""
    from agents.agent4_coach_mentor.cold_streak_detector import detect_and_file
    _init(tmp_path, monkeypatch)
    (tmp_path / "cold_advisories.json").write_text(
        "{not-valid-json", encoding="utf-8"
    )
    _seed_cold(tmp_path / "aram.db", "Jinx", delta=-1.5)
    sched = FakeScheduler()
    summary = detect_and_file(sched, modes=("aram",))
    assert len(summary["filed"]) == 1


# -- persistence -----------------------------------------------------

def test_cooldown_file_written_atomically(tmp_path: Path, monkeypatch) -> None:
    from agents.agent4_coach_mentor.cold_streak_detector import detect_and_file
    _init(tmp_path, monkeypatch)
    _seed_cold(tmp_path / "aram.db", "Jinx", delta=-1.5)
    sched = FakeScheduler()
    detect_and_file(sched, modes=("aram",))
    cooldowns = json.loads((tmp_path / "cold_advisories.json").read_text(encoding="utf-8"))
    assert "aram:Jinx" in cooldowns
    # No lingering tmp file.
    assert not (tmp_path / "cold_advisories.json.tmp").exists()


def test_scheduler_failure_doesnt_crash(tmp_path: Path, monkeypatch) -> None:
    """If file_task raises, the detector logs and keeps iterating so
    one bad champion doesn't block the rest."""
    from agents.agent4_coach_mentor.cold_streak_detector import detect_and_file
    _init(tmp_path, monkeypatch)
    _seed_cold(tmp_path / "aram.db", "Jinx", delta=-1.5)
    _seed_cold(tmp_path / "aram.db", "Thresh", delta=-1.2)

    class HalfBrokenSched:
        def __init__(self):
            self.calls = 0
            self.filed = []
        def file_task(self, **kw):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("boom")
            t = type("T", (), {})()
            t.id = "ok"
            self.filed.append(kw)
            return t

    sched = HalfBrokenSched()
    summary = detect_and_file(sched, modes=("aram",))
    # The second champion still gets through.
    assert len(summary["filed"]) == 1
    assert len(sched.filed) == 1


# -- payload shape ---------------------------------------------------

def test_payload_carries_context(tmp_path: Path, monkeypatch) -> None:
    from agents.agent4_coach_mentor.cold_streak_detector import detect_and_file
    _init(tmp_path, monkeypatch)
    _seed_cold(tmp_path / "aram.db", "Jinx", delta=-1.5)
    sched = FakeScheduler()
    detect_and_file(sched, modes=("aram",))
    p = sched.filed[0]["payload"]
    assert p["mode"] == "aram"
    assert p["champion"] == "Jinx"
    assert p["delta"] == -1.5
    assert p["sample"] == 10
    assert "detected_at" in p
    assert "baseline_kda_ratio" in p and "recent_kda_ratio" in p
    assert "KDA dropped" in p["message"]
