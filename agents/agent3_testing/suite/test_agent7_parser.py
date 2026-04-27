"""Unit tests for Agent 7 input parser (rule-based path only)."""
from __future__ import annotations

from pathlib import Path

import pytest

from agents.agent1_lead import Scheduler, TaskStatus
from agents.agent7_context import InputParser


@pytest.fixture()
def parser(tmp_path: Path) -> InputParser:
    s = Scheduler(queue_log=tmp_path / "q.jsonl")
    # No LLM spawn — force rule-based path for these tests.
    return InputParser(scheduler=s, llm_spawn=None)


def test_empty_input(parser: InputParser) -> None:
    r = parser.parse("")
    assert r.intent == "chitchat"
    assert r.filed == []


def test_audit_now_files_priority_zero(parser: InputParser) -> None:
    r = parser.parse("Audit now")
    assert r.intent == "audit"
    assert len(r.filed) == 1
    t = parser._scheduler.get(r.filed[0])
    assert t.op == "agent6-full-audit-pass"
    assert t.owner_agent == "6"
    assert t.priority == 0
    assert t.user_override is True


def test_status_is_readonly(parser: InputParser) -> None:
    r = parser.parse("what's in the queue")
    assert r.intent == "status"
    assert r.filed == []
    assert "Queue:" in r.reply


def test_direct_agent_command(parser: InputParser) -> None:
    r = parser.parse("Agent 2, refresh DDragon")
    assert r.intent == "direct_agent2"
    assert len(r.filed) == 1
    t = parser._scheduler.get(r.filed[0])
    assert t.owner_agent == "2"
    assert t.payload["instruction"] == "refresh DDragon"
    assert t.user_override is True


def test_destructive_goes_to_hard_gate(parser: InputParser) -> None:
    r = parser.parse("rm -rf data/db/")
    assert r.intent == "destructive"
    t = parser._scheduler.get(r.filed[0])
    assert t.status == TaskStatus.NEEDS_APPROVAL
    assert 1 in t.categories


def test_note_goes_to_agent4(parser: InputParser) -> None:
    r = parser.parse("note: try Taliyah in next ARAM")
    assert r.intent == "note"
    t = parser._scheduler.get(r.filed[0])
    assert t.owner_agent == "4"
    assert t.payload["body"] == "try Taliyah in next ARAM"


def test_unparsed_input_still_files_task(parser: InputParser) -> None:
    # Nonsense input that matches no rule — rules-only mode, no LLM.
    r = parser.parse("quergglebranch flibbertigibbet")
    assert r.intent == "fallback_unparsed"
    assert len(r.filed) == 1
    t = parser._scheduler.get(r.filed[0])
    assert t.op == "user-unparsed"
    assert t.owner_agent == "7"


def test_restart_rc_writes_trigger(tmp_path: Path, monkeypatch) -> None:
    # Redirect project root so we don't touch the real restart_trigger.txt.
    trigger_dir = tmp_path / "fake-root"
    trigger_dir.mkdir()
    import agents.agent7_context.input_parser as ip
    monkeypatch.setattr(ip, "_PROJECT_ROOT", trigger_dir)
    s = Scheduler(queue_log=tmp_path / "q.jsonl")
    p = InputParser(scheduler=s)
    r = p.parse("restart RC")
    assert r.intent == "restart_rc"
    assert (trigger_dir / "restart_trigger.txt").exists()
