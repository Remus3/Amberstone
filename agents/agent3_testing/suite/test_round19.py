"""Round 19 - /api/activity + post-game summary filing."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from agents.agent1_lead import Scheduler


# -- Scheduler.recent_events -----------------------------------------

def test_recent_events_empty_when_log_missing(tmp_path: Path) -> None:
    s = Scheduler(queue_log=tmp_path / "never-exists.jsonl")
    assert s.recent_events() == []


def test_recent_events_newest_first(tmp_path: Path) -> None:
    s = Scheduler(queue_log=tmp_path / "q.jsonl")
    t1 = s.file_task("first", owner_agent="6", priority=10)
    time.sleep(0.005)
    t2 = s.file_task("second", owner_agent="6", priority=20)
    evts = s.recent_events(limit=5)
    assert len(evts) >= 2
    # Newest event should be the 'second' filing, not the 'first'.
    assert evts[0]["task_id"] == t2.id
    assert evts[0]["op"] == "second"
    assert evts[1]["task_id"] == t1.id


def test_recent_events_respects_limit(tmp_path: Path) -> None:
    s = Scheduler(queue_log=tmp_path / "q.jsonl")
    for i in range(12):
        s.file_task(f"op-{i}", owner_agent="6", priority=50)
    evts = s.recent_events(limit=5)
    assert len(evts) == 5


def test_recent_events_skips_corrupt_lines(tmp_path: Path) -> None:
    log = tmp_path / "q.jsonl"
    log.write_text(
        '{"event":"filed","ts":"2026-04-22T00:00:00Z","task":{"id":"t1","op":"good","owner_agent":"6","status":"ready","priority":50}}\n'
        'this-line-is-corrupt\n'
        '{"event":"filed","ts":"2026-04-22T00:00:01Z","task":{"id":"t2","op":"also-good","owner_agent":"6","status":"ready","priority":50}}\n',
        encoding="utf-8",
    )
    s = Scheduler(queue_log=log)
    evts = s.recent_events(limit=10)
    assert len(evts) == 2
    assert {e["task_id"] for e in evts} == {"t1", "t2"}


def test_recent_events_trimmed_fields(tmp_path: Path) -> None:
    """The returned shape is whitelisted - no full payload dump."""
    s = Scheduler(queue_log=tmp_path / "q.jsonl")
    s.file_task(
        "big-payload", owner_agent="2", priority=50,
        payload={"blob": "x" * 2000, "secret": "never-show-this"},
    )
    evts = s.recent_events(limit=1)
    assert evts
    keys = set(evts[0].keys())
    assert keys == {"ts", "event", "task_id", "op", "owner_agent", "status", "priority"}
    # Ensure nothing leaked the payload blob.
    assert not any(
        "never-show-this" in json.dumps(e) for e in evts
    )


# -- Post-game summary filing ----------------------------------------

def test_post_game_summary_files_task(tmp_path: Path, monkeypatch) -> None:
    """Supervisor._file_post_game_summary reads the newest coaching JSON
    and files a game-summary task with the relevant fields."""
    from agents.supervisor import Supervisor
    import agents.supervisor as sup_mod

    # Redirect the module's _PROJECT_ROOT to our tmp dir so we control the
    # coaching-JSON source without touching real files.
    monkeypatch.setattr(sup_mod, "_PROJECT_ROOT", tmp_path)

    # Seed a recent ARAM coaching JSON.
    aram = tmp_path / "data"
    aram.mkdir()
    (aram / "aram_coaching_data.json").write_text(
        json.dumps({
            "mode": "game",
            "game_mode": "ARAM",
            "champion": "Ahri",
            "game_time": "24:00",
            "kda": "10/3/15",
            "items_display": "Ludens, Sorc Boots",
            "item_build": "Ludens → Shadowflame",
            "action": "Victory",
        }),
        encoding="utf-8",
    )

    sup = Supervisor()
    sup._scheduler = Scheduler(queue_log=tmp_path / "q.jsonl")

    sup._file_post_game_summary("game", "client")

    # Confirm the task landed.
    ready_and_done = (
        sup._scheduler.list_by_status("ready")
        + sup._scheduler.list_by_status("completed")
    )
    matches = [t for t in ready_and_done if t.op == "game-summary"]
    assert len(matches) == 1
    t = matches[0]
    # Round 20: owner 4->2 so supervisor runs the deterministic consumer
    # instead of spawning an LLM.
    assert t.owner_agent == "2"
    assert t.user_override is True
    assert t.payload["prev_mode"] == "game"
    assert t.payload["new_mode"] == "client"
    assert t.payload["champion"] == "Ahri"
    assert t.payload["source"] == "aram_coaching_data.json"
    assert "Ludens" in t.payload["item_build"]


def test_post_game_summary_survives_missing_json(tmp_path: Path, monkeypatch) -> None:
    """If no coaching JSON exists (edge case), the handler must not crash.

    Behaviour CHANGED 2026-07-28 (M-02): it used to file a minimal
    champion-less payload, which the ingester refuses outright at
    ``game_ingest.py:203-216``. 170 of the 583 game-summary rows in
    ``agents/state/task_queue.jsonl`` were exactly that no-op. The
    emit-side guard now suppresses it, so the assertion here inverts:
    no crash, and no task.
    """
    from agents.supervisor import Supervisor
    import agents.supervisor as sup_mod
    monkeypatch.setattr(sup_mod, "_PROJECT_ROOT", tmp_path)

    sup = Supervisor()
    sup._scheduler = Scheduler(queue_log=tmp_path / "q.jsonl")
    sup._file_post_game_summary("game", "client")

    tasks = sup._scheduler.list_by_status("ready") + sup._scheduler.list_by_status("completed")
    matches = [t for t in tasks if t.op == "game-summary"]
    assert matches == [], (
        "a champion-less, mode-less summary is a guaranteed ingest refusal "
        "and must not be enqueued"
    )
