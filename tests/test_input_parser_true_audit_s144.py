"""True-audit s144 (lane 8): agents/agent7_context/input_parser.py.

POST /api/input hands typed operator text to ``InputParser.parse``, and any
text no rule matches goes to a Haiku call whose JSON reply is FILED as a
scheduler task. Both halves were weaker than the module claims:

Rules
- A keyword search ran before the anchored commands, so "note: run a full
  audit next week" queued a BLOCKING priority-0 full audit, and "remind me to
  check the queue" / "Agent 2, report status" answered with a queue summary and
  filed nothing (the input was lost).
- "notebook ..." / "remembering ..." filed a note with a sliced body, and
  "Agent 10, ..." filed a direct order to agent 1.

LLM reply (model output is untrusted)
- The model's payload was spread AFTER the provenance keys, so it could set
  llm_derived / op_coerced / user_text, pre-set ``_frozen_file_hits`` to hide
  the scheduler's frozen-file evidence, and carry ``spawn_budget_usd`` /
  ``spawn_timeout_sec`` / ``additional_dirs``, which the ephemeral dispatcher
  honours on a --dangerously-skip-permissions spawn.
- owner_agent, priority and categories were taken as given: an owner "9", a
  priority below the operator's own explicit orders, a categories string split
  into characters, and a ``user-destructive-request`` without the hard gate.
  A priority of "high" raised and threw the whole classification away.
- An error envelope (ok False / is_error) or non-JSON stdout was shown to the
  operator verbatim (CLAUDE.md error-handling rule), a JSON object between
  prose braces was not found, and a non-str reply reached the dashboard as an
  object or the string "None".
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from agents.agent1_lead import Scheduler, TaskStatus
from agents.agent7_context.input_parser import InputParser


def _sched(tmp_path: Path) -> Scheduler:
    return Scheduler(queue_log=tmp_path / "q.jsonl")


def _all_tasks(s: Scheduler):
    return list(s._tasks.values())


def _llm(body, *, raw: bool = False):
    """A spawn stub returning ``body`` the way the CLI envelope carries it."""
    text = body if raw else json.dumps(body)

    def _spawn(agent, task_id, op, payload):
        return {"ok": True, "result": {"result": text}}
    return _spawn


def _env(envelope):
    def _spawn(agent, task_id, op, payload):
        return envelope
    return _spawn


def _task_parser(tmp_path: Path, task: dict, reply="ok"):
    s = _sched(tmp_path)
    body = {"task": task}
    if reply is not None:
        body["reply"] = reply
    return s, InputParser(scheduler=s, llm_spawn=_llm(body))


# -- rule precedence ---------------------------------------------------

def test_note_mentioning_a_full_audit_is_a_note_not_a_blocking_audit(tmp_path):
    s = _sched(tmp_path)
    r = InputParser(scheduler=s, llm_spawn=None).parse(
        "note: run a full audit next week")
    assert r.intent == "note"
    ops = [t.op for t in _all_tasks(s)]
    assert ops == ["user-note"]
    assert s.get(r.filed[0]).payload["body"] == "run a full audit next week"


def test_note_mentioning_the_queue_is_filed_not_answered_as_status(tmp_path):
    s = _sched(tmp_path)
    r = InputParser(scheduler=s, llm_spawn=None).parse(
        "remind me to check the queue later")
    assert r.intent == "note"
    assert len(r.filed) == 1


def test_direct_order_mentioning_status_is_filed(tmp_path):
    s = _sched(tmp_path)
    r = InputParser(scheduler=s, llm_spawn=None).parse(
        "Agent 2, report status of the champ pool")
    assert r.intent == "direct_agent2"
    assert s.get(r.filed[0]).payload["instruction"] == "report status of the champ pool"


def test_plain_status_and_audit_keep_their_meaning(tmp_path):
    s = _sched(tmp_path)
    p = InputParser(scheduler=s, llm_spawn=None)
    assert p.parse("what's in the queue").intent == "status"
    r = p.parse("Agent 6 audit now")
    assert r.intent == "audit"
    assert s.get(r.filed[0]).op == "agent6-full-audit-pass"


def test_destructive_note_still_hits_the_hard_gate(tmp_path):
    s = _sched(tmp_path)
    r = InputParser(scheduler=s, llm_spawn=None).parse(
        "note: delete all the old logs")
    assert r.intent == "destructive"
    assert s.get(r.filed[0]).status == TaskStatus.NEEDS_APPROVAL


@pytest.mark.parametrize("text", [
    "notebook battery is low tonight",
    "remembering the last game felt bad",
    "Agent 10, refresh the cache",
    "agent 34 go",
])
def test_keyword_or_agent_number_inside_a_longer_token_is_not_a_command(tmp_path, text):
    s = _sched(tmp_path)
    r = InputParser(scheduler=s, llm_spawn=None).parse(text)
    assert r.intent == "fallback_unparsed"
    assert s.get(r.filed[0]).op == "user-unparsed"


@pytest.mark.parametrize("text", [None, 123, b"note: x", ["note: x"]])
def test_non_str_input_is_empty_not_a_raise(tmp_path, text):
    s = _sched(tmp_path)
    r = InputParser(scheduler=s, llm_spawn=None).parse(text)
    assert r.intent == "chitchat"
    assert r.filed == []


# -- LLM payload is untrusted -------------------------------------------

def test_llm_payload_cannot_overwrite_provenance(tmp_path):
    s, p = _task_parser(tmp_path, {
        "op": "user-note", "owner_agent": "4", "priority": 50,
        "payload": {"llm_derived": False, "op_coerced": True,
                    "user_text": "forged", "llm_proposed_op": "x", "body": "b"},
    })
    r = p.parse("contemplate the weather")
    pl = s.get(r.filed[0]).payload
    assert pl["llm_derived"] is True
    assert pl["op_coerced"] is False
    assert pl["user_text"] == "contemplate the weather"
    assert pl["llm_proposed_op"] == "user-note"
    assert pl["body"] == "b"


def test_llm_payload_spawn_control_keys_are_dropped(tmp_path):
    s, p = _task_parser(tmp_path, {
        "op": "analyze-now", "owner_agent": "2",
        "payload": {"spawn_budget_usd": 500, "spawn_timeout_sec": 99999,
                    "additional_dirs": ["/"], "_private": 1, "champion": "Vayne"},
    })
    r = p.parse("contemplate the weather")
    pl = s.get(r.filed[0]).payload
    for k in ("spawn_budget_usd", "spawn_timeout_sec", "additional_dirs", "_private"):
        assert k not in pl
    assert pl["champion"] == "Vayne"


def test_llm_payload_cannot_hide_frozen_file_hits(tmp_path):
    s, p = _task_parser(tmp_path, {
        "op": "coach-propose", "owner_agent": "4",
        "payload": {"_frozen_file_hits": [], "target": "edit main.py now"},
    })
    r = p.parse("contemplate the weather")
    t = s.get(r.filed[0])
    assert t.payload["_frozen_file_hits"] == ["main.py"]
    assert t.status == TaskStatus.NEEDS_APPROVAL


@pytest.mark.parametrize("payload", [["a", "b"], "text", 7])
def test_llm_non_dict_payload_keeps_the_classification(tmp_path, payload):
    s, p = _task_parser(tmp_path, {"op": "user-note", "owner_agent": "4",
                                   "payload": payload})
    r = p.parse("contemplate the weather")
    assert r.intent == "fallback_llm"
    t = s.get(r.filed[0])
    assert t.op == "user-note"
    assert t.payload["llm_derived"] is True


@pytest.mark.parametrize("owner,expected", [
    ("9", "7"), (True, "7"), ("../x", "7"), (None, "7"), ("", "7"),
    ([3], "7"), (3, "3"), ("4", "4"), (" 5 ", "7"),
])
def test_llm_owner_agent_must_be_a_known_agent(tmp_path, owner, expected):
    s, p = _task_parser(tmp_path, {"op": "user-note", "owner_agent": owner})
    r = p.parse("contemplate the weather")
    assert s.get(r.filed[0]).owner_agent == expected


@pytest.mark.parametrize("prio,expected", [
    ("high", 50), (None, 50), (True, 50), (float("nan"), 50),
    (0, 20), (-5, 20), (10 ** 6, 100), (60, 60), (60.0, 60), (60.5, 50),
    ("70", 50),
])
def test_llm_priority_is_validated_and_bounded(tmp_path, prio, expected):
    s, p = _task_parser(tmp_path, {"op": "user-note", "owner_agent": "4",
                                   "priority": prio})
    r = p.parse("contemplate the weather")
    assert r.intent == "fallback_llm"
    assert s.get(r.filed[0]).priority == expected


def test_llm_infinite_priority_from_json_is_bounded(tmp_path):
    s = _sched(tmp_path)
    raw = '{"task": {"op": "user-note", "owner_agent": "4", "priority": Infinity}}'
    r = InputParser(scheduler=s, llm_spawn=_llm(raw, raw=True)).parse("x y z q")
    assert r.intent == "fallback_llm"
    assert s.get(r.filed[0]).priority == 50


@pytest.mark.parametrize("cats,expected", [
    ("abc", []), ({"1": 1}, []), (None, []),
    ([1, "x", True, 2.5, 3, 3], [1, 3]),
    ([True, 2, False], [2]),
])
def test_llm_categories_are_ints_only(tmp_path, cats, expected):
    s, p = _task_parser(tmp_path, {"op": "user-note", "owner_agent": "4",
                                   "categories": cats})
    r = p.parse("contemplate the weather")
    assert s.get(r.filed[0]).categories == expected


@pytest.mark.parametrize("value", [5, (1, 2), "12", {1: 1}])
def test_categories_helper_takes_only_a_list(value):
    from agents.agent7_context.input_parser import _llm_categories
    assert _llm_categories(value) == []


def test_llm_destructive_request_always_carries_the_hard_gate(tmp_path):
    s, p = _task_parser(tmp_path, {"op": "user-destructive-request",
                                   "owner_agent": "1", "categories": []})
    r = p.parse("get rid of everything in the data folder")
    t = s.get(r.filed[0])
    assert 1 in t.categories
    assert t.status == TaskStatus.NEEDS_APPROVAL


@pytest.mark.parametrize("reply", [{"x": 1}, None, "", "   ", 42])
def test_llm_task_reply_is_always_a_nonempty_str(tmp_path, reply):
    s, p = _task_parser(tmp_path, {"op": "user-note", "owner_agent": "4"},
                        reply=reply)
    r = p.parse("contemplate the weather")
    assert isinstance(r.reply, str)
    assert r.reply.strip()
    assert r.reply != "None"


@pytest.mark.parametrize("reply", [None, {"a": 1}, "", 0])
def test_llm_unusable_conversational_reply_files_the_input(tmp_path, reply):
    s = _sched(tmp_path)
    r = InputParser(scheduler=s, llm_spawn=_llm({"reply": reply})).parse(
        "contemplate the weather")
    assert r.intent == "fallback_unparsed"
    assert len(r.filed) == 1
    assert "None" not in r.reply


def test_llm_task_that_is_not_an_object_files_the_input(tmp_path):
    s = _sched(tmp_path)
    r = InputParser(scheduler=s, llm_spawn=_llm({"task": "user-note"})).parse(
        "contemplate the weather")
    assert r.intent == "fallback_unparsed"
    assert '"task"' not in r.reply


# -- the envelope: never show a raw API error ----------------------------

_SECRETISH = "API Error: 400 Your credit balance is too low"


@pytest.mark.parametrize("envelope", [
    {"ok": True, "result": {"is_error": True, "result": _SECRETISH}},
    {"ok": False, "result": {"result": _SECRETISH}},
    {"ok": True, "result": {"raw_stdout": _SECRETISH}},
    {"ok": True, "result": {"result": {"nested": _SECRETISH}}},
    {"ok": True, "result": _SECRETISH},
    None,
    [1, 2],
    "plain string",
])
def test_error_or_malformed_envelope_degrades_without_the_raw_text(tmp_path, envelope):
    s = _sched(tmp_path)
    r = InputParser(scheduler=s, llm_spawn=_env(envelope)).parse(
        "contemplate the weather")
    assert r.intent == "fallback_unparsed"
    assert "credit" not in r.reply.lower()
    assert "API Error" not in r.reply
    assert len(r.filed) == 1
    assert s.get(r.filed[0]).op == "user-unparsed"


def test_json_object_between_prose_braces_is_found(tmp_path):
    s = _sched(tmp_path)
    raw = 'Sure {thing}. {"reply": "hi there"} and {more}'
    r = InputParser(scheduler=s, llm_spawn=_llm(raw, raw=True)).parse(
        "contemplate the weather")
    assert r.reply == "hi there"
    assert r.used_llm is True


def test_warm_session_prose_is_still_a_reply(tmp_path):
    s = _sched(tmp_path)
    r = InputParser(scheduler=s, llm_spawn=_llm("Hello there.", raw=True)).parse(
        "howdy partner friend")
    assert r.intent == "chitchat"
    assert r.reply == "Hello there."
    assert r.filed == []


def test_llm_spawn_failure_is_logged_scrubbed_and_the_input_filed(tmp_path, caplog):
    def _boom(agent, task_id, op, payload):
        raise RuntimeError("bad\x1b[31m\r\nFORGED line")
    s = _sched(tmp_path)
    with caplog.at_level(logging.WARNING, logger="agent7.input_parser"):
        r = InputParser(scheduler=s, llm_spawn=_boom).parse("contemplate the weather")
    assert r.intent == "fallback_unparsed"
    msgs = [rec.getMessage() for rec in caplog.records
            if rec.name == "agent7.input_parser"]
    assert msgs
    assert all("\x1b" not in m and "\r" not in m and "\n" not in m for m in msgs)
    assert any("RuntimeError" in m for m in msgs)
