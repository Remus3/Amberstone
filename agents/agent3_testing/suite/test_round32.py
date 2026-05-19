"""Round 32 - /api/advisories list + POST /api/task/<id>/dismiss."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


# A lightweight mock of the request-handler shape the handler methods need.
class _MockHandler:
    """Mimics just enough of BaseHTTPRequestHandler for the handler
    methods under test. We don't go through a real HTTP stack - the
    endpoints are pure logic over self.server.supervisor.scheduler."""

    def __init__(self, path: str, scheduler, command: str = "GET") -> None:
        self.path = path
        self.command = command
        self.server = type("S", (), {})()
        self.server.supervisor = type("Sup", (), {})()
        self.server.supervisor.scheduler = scheduler
        self.responses: list[tuple[int, dict]] = []

    def _send_json(self, status: int, body: dict) -> None:
        self.responses.append((status, body))

    def send_error(self, status: int, *_args) -> None:
        self.responses.append((status, {}))


@pytest.fixture()
def fresh_scheduler(tmp_path: Path):
    from agents.agent1_lead import Scheduler
    return Scheduler(queue_log=tmp_path / "q.jsonl")


def _make_handler(path: str, scheduler, command="GET"):
    """Return a _MockHandler bound to the real supervisor handler
    functions (pulled via method descriptors)."""
    from agents.supervisor import _QuietHandler
    h = _MockHandler(path, scheduler, command=command)
    # Bind the unbound handler methods to our mock.
    h._handle_advisories = _QuietHandler._handle_advisories.__get__(h)
    h._handle_task_dismiss = _QuietHandler._handle_task_dismiss.__get__(h)
    h.ADVISORY_OPS = _QuietHandler.ADVISORY_OPS
    return h


# ── /api/advisories ─────────────────────────────────────────────────

def test_advisories_empty_returns_empty_list(fresh_scheduler) -> None:
    h = _make_handler("/api/advisories", fresh_scheduler)
    h._handle_advisories()
    status, body = h.responses[0]
    assert status == 200
    assert body == {"advisories": []}


def test_advisories_list_includes_cold_streak(fresh_scheduler) -> None:
    fresh_scheduler.file_task(
        op="cold-streak-advisory",
        owner_agent="1", priority=70,
        payload={
            "mode": "aram", "champion": "Jinx", "delta": -1.5, "sample": 10,
            "baseline_kda_ratio": 3.94, "recent_kda_ratio": 2.44,
            "message": "Jinx (aram) KDA dropped 3.94 → 2.44",
            "detected_at": "2026-04-22T12:00:00Z",
        },
        user_override=True,
    )
    # A non-advisory task in the queue should NOT come back.
    fresh_scheduler.file_task(
        op="some-other-op", owner_agent="2", priority=50,
        payload={}, user_override=True,
    )

    h = _make_handler("/api/advisories", fresh_scheduler)
    h._handle_advisories()
    status, body = h.responses[0]
    assert status == 200
    advs = body["advisories"]
    assert len(advs) == 1
    a = advs[0]
    assert a["op"] == "cold-streak-advisory"
    assert a["champion"] == "Jinx"
    assert a["mode"] == "aram"
    assert a["delta"] == -1.5
    assert a["message"].startswith("Jinx")


def test_advisories_mode_filter(fresh_scheduler) -> None:
    for mode, champ in (("aram", "Jinx"), ("sr_ranked", "Nautilus")):
        fresh_scheduler.file_task(
            op="cold-streak-advisory", owner_agent="1", priority=70,
            payload={"mode": mode, "champion": champ, "delta": -1.5, "sample": 10},
            user_override=True,
        )

    h = _make_handler("/api/advisories?mode=aram", fresh_scheduler)
    h._handle_advisories()
    _, body = h.responses[0]
    assert len(body["advisories"]) == 1
    assert body["advisories"][0]["champion"] == "Jinx"


def test_advisories_respects_limit(fresh_scheduler) -> None:
    for i in range(12):
        fresh_scheduler.file_task(
            op="cold-streak-advisory", owner_agent="1", priority=70,
            payload={"mode": "aram", "champion": f"Ch{i}", "delta": -1.5, "sample": 10},
            user_override=True,
        )
    h = _make_handler("/api/advisories?limit=5", fresh_scheduler)
    h._handle_advisories()
    _, body = h.responses[0]
    assert len(body["advisories"]) == 5


def test_advisories_excludes_completed_by_default(fresh_scheduler) -> None:
    t = fresh_scheduler.file_task(
        op="cold-streak-advisory", owner_agent="1", priority=70,
        payload={"mode": "aram", "champion": "Jinx", "delta": -1.5, "sample": 10},
        user_override=True,
    )
    fresh_scheduler.complete(t.id, result={"dismissed_at": "now"})

    h = _make_handler("/api/advisories", fresh_scheduler)
    h._handle_advisories()
    _, body = h.responses[0]
    assert body["advisories"] == []


def test_advisories_include_completed_opt_in(fresh_scheduler) -> None:
    t = fresh_scheduler.file_task(
        op="cold-streak-advisory", owner_agent="1", priority=70,
        payload={"mode": "aram", "champion": "Jinx", "delta": -1.5, "sample": 10},
        user_override=True,
    )
    fresh_scheduler.complete(t.id, result={"dismissed_at": "now"})

    h = _make_handler("/api/advisories?include_completed=1", fresh_scheduler)
    h._handle_advisories()
    _, body = h.responses[0]
    assert len(body["advisories"]) == 1
    assert body["advisories"][0]["status"] == "completed"


# ── POST /api/task/<id>/dismiss ─────────────────────────────────────

def test_dismiss_completes_task(fresh_scheduler) -> None:
    t = fresh_scheduler.file_task(
        op="cold-streak-advisory", owner_agent="1", priority=70,
        payload={"mode": "aram", "champion": "Jinx"},
        user_override=True,
    )
    h = _make_handler(f"/api/task/{t.id}/dismiss", fresh_scheduler, command="POST")
    h._handle_task_dismiss()
    status, body = h.responses[0]
    assert status == 200
    assert body["status"] == "completed"
    # Scheduler side should agree.
    assert fresh_scheduler.get(t.id).status == "completed"
    # Result marker carries the dismissal metadata.
    result = fresh_scheduler.get(t.id).result or {}
    assert result.get("source") == "user"
    assert result.get("prior_status") in ("ready", "needs_approval")
    assert "dismissed_at" in result


def test_dismiss_idempotent(fresh_scheduler) -> None:
    t = fresh_scheduler.file_task(
        op="cold-streak-advisory", owner_agent="1", priority=70,
        payload={"mode": "aram", "champion": "Jinx"},
        user_override=True,
    )
    # First dismiss.
    h1 = _make_handler(f"/api/task/{t.id}/dismiss", fresh_scheduler, command="POST")
    h1._handle_task_dismiss()
    # Second dismiss: 200 no-op, no crash.
    h2 = _make_handler(f"/api/task/{t.id}/dismiss", fresh_scheduler, command="POST")
    h2._handle_task_dismiss()
    status, body = h2.responses[0]
    assert status == 200
    assert body.get("already_completed") is True


def test_dismiss_unknown_task_returns_404(fresh_scheduler) -> None:
    h = _make_handler("/api/task/nonexistent-id/dismiss", fresh_scheduler, command="POST")
    h._handle_task_dismiss()
    status, body = h.responses[0]
    assert status == 404


def test_dismiss_invalid_task_id_rejected(fresh_scheduler) -> None:
    h = _make_handler("/api/task/invalid$id/dismiss", fresh_scheduler, command="POST")
    h._handle_task_dismiss()
    status, body = h.responses[0]
    assert status == 400


def test_dismiss_malformed_url_rejected(fresh_scheduler) -> None:
    # Missing trailing /dismiss is handled by the dispatcher - we test
    # the handler with a malformed path it shouldn't have been routed to.
    h = _make_handler("/api/task//dismiss", fresh_scheduler, command="POST")
    h._handle_task_dismiss()
    status, _ = h.responses[0]
    assert status == 400


# ── supervisor route registration ───────────────────────────────────

def test_supervisor_registers_advisory_routes() -> None:
    # s243: the _QuietHandler web layer was split out of supervisor.py
    # (now a facade) into agents/_supervisor_http.py byte-verbatim. Route
    # registration is unchanged at runtime (the bound-method tests above
    # prove it); this structural pin follows the handler to its new home.
    sup = Path("agents/_supervisor_http.py").read_text(encoding="utf-8")
    assert "/api/advisories" in sup
    assert "_handle_advisories" in sup
    assert "_handle_task_dismiss" in sup
    assert '"/dismiss"' in sup
