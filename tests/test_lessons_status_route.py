"""Tests for tools/lessons_status.py + dashboard/routes_lessons.

Covers: build_report shape, --plain text rendering, --no-refresh flag
honored, route registration, route fail-soft.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

import core.lessons_ack_watcher as aw
import core.lessons_confidence as conf
from tools import lessons_status


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    sent = tmp_path / "lessons_sent.jsonl"
    received = tmp_path / "lessons_received.jsonl"
    monkeypatch.setattr(aw, "LESSONS_SENT_LOG", sent)
    monkeypatch.setattr(conf, "LESSONS_SENT_LOG", sent)
    monkeypatch.setattr(conf, "LESSONS_RECEIVED_LOG", received)
    # build_report skips the HTTPS shuttle when the ledger is empty;
    # nothing else to patch in that path.
    return (sent, received)


# ---------------------------------------------------------------------------
# build_report
# ---------------------------------------------------------------------------

def test_build_report_empty(isolated_state):
    r = lessons_status.build_report(refresh=False)
    assert "summary" in r and "refresh" in r and "confidence" in r
    assert r["summary"]["total_sent"] == 0
    # refresh=False -> refresh payload is empty
    assert r["refresh"] == {}


def test_build_report_with_data(isolated_state):
    sent, received = isolated_state
    _write(sent, [
        {"lesson_id": "L1", "path": "memory/feedback_x.md",
         "ack_received": True,
         "ack": {"source": "peer", "decision": "applied", "took": True}},
    ])
    _write(received, [
        {"lesson_id": "L2", "from": "peer", "decision": "discarded"},
    ])
    r = lessons_status.build_report(refresh=False)
    assert r["summary"]["total_sent"] == 1
    assert r["summary"]["took"] == 1
    assert "peer:feedback" in r["confidence"]["buckets"]
    assert r["confidence"]["totals"]["received"] == 1


def test_build_report_refresh_calls_watcher(isolated_state, monkeypatch):
    sent, _ = isolated_state
    _write(sent, [{"lesson_id": "L1", "ack_received": False}])
    called = {"n": 0}

    def fake_update(*, since=None):
        called["n"] += 1
        return aw.WatcherReport(
            fetched_results=0, unacked_before=1, unacked_after=1,
            newly_acked=[], already_acked=0,
        )
    monkeypatch.setattr(aw, "update_sent_acks", fake_update)
    r = lessons_status.build_report(refresh=True)
    assert called["n"] == 1
    assert r["refresh"]["unacked_before"] == 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_json_default(isolated_state, capsys):
    rc = lessons_status.main(["--no-refresh"])
    assert rc == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert "summary" in parsed


def test_cli_plain_output(isolated_state, capsys, monkeypatch):
    sent, received = isolated_state
    _write(sent, [
        {"lesson_id": "L1", "path": "memory/feedback_x.md",
         "ack_received": True,
         "ack": {"source": "peer", "decision": "applied", "took": True}},
    ])
    rc = lessons_status.main(["--no-refresh", "--plain"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "sender ledger" in out
    assert "confidence" in out
    assert "peer:feedback" in out


def test_cli_no_refresh_skips_watcher(isolated_state, monkeypatch, capsys):
    called = {"n": 0}

    def fake_update(*, since=None):
        called["n"] += 1
        return aw.WatcherReport(0, 0, 0, [], 0)
    monkeypatch.setattr(aw, "update_sent_acks", fake_update)
    lessons_status.main(["--no-refresh"])
    assert called["n"] == 0


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

class _FakeHandler:
    def __init__(self, path: str):
        self.path = path
        self.responses: list[tuple] = []

    def _send(self, status: int, body: bytes, content_type: str):
        self.responses.append((status, body, content_type))


def test_route_registered():
    from dashboard import routes_lessons, _dispatch
    matchers = [m for m, _ in routes_lessons.GET_ROUTES]
    assert len(matchers) == 1
    assert matchers[0]("/api/lessons/status")
    assert not matchers[0]("/api/lessons/other")
    # _dispatch registers all known route modules - sanity-check the import
    assert hasattr(routes_lessons, "GET_ROUTES")
    assert routes_lessons.POST_ROUTES == []


def test_route_returns_json_default(isolated_state, monkeypatch):
    from dashboard import routes_lessons
    monkeypatch.setattr(aw, "update_sent_acks",
                        lambda **k: aw.WatcherReport(0, 0, 0, [], 0))
    h = _FakeHandler("/api/lessons/status")
    routes_lessons._serve_lessons_status(h)
    assert len(h.responses) == 1
    status, body, ctype = h.responses[0]
    assert status == 200
    payload = json.loads(body)
    assert "summary" in payload
    assert "confidence" in payload
    assert "now" in payload
    assert ctype == "application/json"


def test_route_refresh_query_param(isolated_state, monkeypatch):
    from dashboard import routes_lessons
    called = {"n": 0}

    def fake_update(**k):
        called["n"] += 1
        return aw.WatcherReport(0, 0, 0, [], 0)
    monkeypatch.setattr(aw, "update_sent_acks", fake_update)

    h = _FakeHandler("/api/lessons/status?refresh=0")
    routes_lessons._serve_lessons_status(h)
    assert called["n"] == 0  # refresh=0 skips watcher

    h2 = _FakeHandler("/api/lessons/status?refresh=1")
    routes_lessons._serve_lessons_status(h2)
    assert called["n"] == 1


def test_route_fail_soft_on_exception(isolated_state, monkeypatch):
    """A broken build_report should 500 with a short error string,
    not propagate."""
    from dashboard import routes_lessons
    import tools.lessons_status as ls_mod
    monkeypatch.setattr(ls_mod, "build_report",
                        lambda **k: (_ for _ in ()).throw(RuntimeError("boom")))
    h = _FakeHandler("/api/lessons/status")
    routes_lessons._serve_lessons_status(h)
    assert h.responses[0][0] == 500
    body = json.loads(h.responses[0][1])
    assert "boom" in body.get("error", "")
