"""Round 22 - POST /api/file-task + ops._scheduler_client fallback + task detail."""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest


def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    import socket
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# -- /api/file-task (via spawned supervisor) -------------------------

@pytest.fixture(scope="module")
def live_supervisor():
    if not _port_open("127.0.0.1", 8890):
        pytest.skip("supervisor not running on :8890")


@pytest.mark.timeout(10)
def test_file_task_endpoint_happy_path(live_supervisor) -> None:
    body = {
        "op": "test-round22-file-task-happy",
        "owner_agent": "6",
        "priority": 75,
        "payload": {"note": "ping from test"},
        "user_override": True,
    }
    req = urllib.request.Request(
        "http://127.0.0.1:8890/api/file-task",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=3) as r:
        data = json.loads(r.read().decode())
    assert data["id"].startswith("t-")
    assert data["op"] == body["op"]
    assert data["owner_agent"] == "6"
    assert data["priority"] == 75
    assert data["status"] in ("ready", "in_progress", "completed")


@pytest.mark.timeout(10)
def test_file_task_endpoint_missing_fields_400(live_supervisor) -> None:
    body = {"priority": 50}      # no op, no owner_agent
    req = urllib.request.Request(
        "http://127.0.0.1:8890/api/file-task",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=3)
        pytest.fail("expected 400")
    except urllib.error.HTTPError as e:
        assert e.code == 400
        err = json.loads(e.read().decode())
        assert "required" in err["error"]


@pytest.mark.timeout(10)
def test_file_task_endpoint_frozen_file_gates(live_supervisor) -> None:
    """Payload mentioning a frozen file should land in NEEDS_APPROVAL
    when user_override is false - guardrail is re-used from round 18."""
    body = {
        "op": "test-round22-frozen",
        "owner_agent": "2",
        "priority": 55,
        "payload": {"target": "main.py", "diff": "fake"},
    }
    req = urllib.request.Request(
        "http://127.0.0.1:8890/api/file-task",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=3) as r:
        data = json.loads(r.read().decode())
    assert data["status"] == "needs_explicit_approval"
    assert "main.py" in (data.get("frozen_file_hits") or [])

    # Hermeticity (WP-F5-H02): a frozen-gate task lands in NEEDS_APPROVAL
    # which has no automatic terminal transition - left filed it leaks
    # into the live queue forever (1567 such orphans accumulated before
    # this cleanup landed). Dismiss it so the test leaves no residue.
    tid = data.get("id")
    if tid:
        dismiss = urllib.request.Request(
            f"http://127.0.0.1:8890/api/task/{tid}/dismiss",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(dismiss, timeout=3).close()
        except urllib.error.HTTPError:
            pass  # best-effort cleanup; the gate-limbo reaper is the backstop


# -- ops/_scheduler_client.py fallback path -------------------------

def test_client_fallback_when_supervisor_unreachable(tmp_path: Path, monkeypatch) -> None:
    """Point the client at a dead port so HTTP fails, confirm it falls
    back to a direct Scheduler.file_task that writes to jsonl."""
    monkeypatch.setenv("RC_SUPERVISOR_URL", "http://127.0.0.1:1")   # TCP 1 - guaranteed closed

    # Isolate the scheduler fallback by redirecting QUEUE_LOG.
    import agents.agent1_lead.scheduler as sched_mod
    monkeypatch.setattr(sched_mod, "QUEUE_LOG", tmp_path / "q.jsonl")

    # Reload client so DEFAULT_BASE_URL picks up the env change.
    import importlib
    import ops._scheduler_client as client_mod
    importlib.reload(client_mod)

    result = client_mod.file_task(
        op="fallback-test-op",
        owner_agent="6",
        priority=42,
        payload={"source": "fallback-path"},
    )
    assert result["used_http"] is False
    assert result["op"] == "fallback-test-op"
    assert result["owner_agent"] == "6"
    assert result["priority"] == 42
    # jsonl file exists and contains the task.
    jsonl = tmp_path / "q.jsonl"
    assert jsonl.exists()
    text = jsonl.read_text(encoding="utf-8")
    assert "fallback-test-op" in text


# -- /api/task/<id> detail endpoint ---------------------------------

@pytest.mark.timeout(10)
def test_task_detail_endpoint(live_supervisor) -> None:
    """File a task via /api/file-task, then fetch /api/task/<id>."""
    body = {
        "op": "test-round22-detail",
        "owner_agent": "6",
        "priority": 85,
        "payload": {"note": "detail probe"},
        "user_override": True,
    }
    req = urllib.request.Request(
        "http://127.0.0.1:8890/api/file-task",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=3) as r:
        filed = json.loads(r.read().decode())

    tid = filed["id"]
    # Give the scheduler a moment to flush its event log.
    time.sleep(0.2)
    with urllib.request.urlopen(f"http://127.0.0.1:8890/api/task/{tid}", timeout=3) as r:
        d = json.loads(r.read().decode())
    assert d["id"] == tid
    assert d["op"] == body["op"]
    assert d["priority"] == 85
    assert isinstance(d["events"], list)
    assert d["events"], "expected at least one event (filed)"
    assert d["events"][0]["event"] in ("filed", "dispatched", "completed")


@pytest.mark.timeout(10)
def test_task_detail_404_for_unknown(live_supervisor) -> None:
    try:
        urllib.request.urlopen(
            "http://127.0.0.1:8890/api/task/t-does-not-exist", timeout=3,
        )
        pytest.fail("expected 404")
    except urllib.error.HTTPError as e:
        assert e.code == 404


@pytest.mark.timeout(10)
def test_task_detail_rejects_bad_id(live_supervisor) -> None:
    try:
        urllib.request.urlopen(
            "http://127.0.0.1:8890/api/task/../../etc/passwd", timeout=3,
        )
        pytest.fail("expected 400")
    except urllib.error.HTTPError as e:
        assert e.code in (400, 404)     # traversal rejected either by handler
                                        # or by earlier path normalization
