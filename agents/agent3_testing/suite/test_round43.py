"""Round 43 - strict deterministic op allowlist + Agent 7 LLM op vocabulary."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest


# ── supervisor _run_deterministic tightening ───────────────────────

def _make_supervisor(tmp_path: Path):
    """Build a Supervisor-like object that has just enough structure
    for _run_deterministic to execute without booting the whole
    scheduler / WS stack."""
    from agents import supervisor as sup_mod
    # We don't need a real Supervisor instance - _run_deterministic
    # only touches `task` attrs + LOG_ROOT. Pin LOG_ROOT to tmp_path.
    log_root = tmp_path / "logs"
    log_root.mkdir()
    monkey = SimpleNamespace(LOG_ROOT=log_root, orig=sup_mod.LOG_ROOT)
    sup_mod.LOG_ROOT = log_root
    handler = sup_mod.Supervisor.__dict__["_run_deterministic"]
    return handler, monkey


def _restore(monkey) -> None:
    from agents import supervisor as sup_mod
    sup_mod.LOG_ROOT = monkey.orig


def _fake_task(op: str, owner: str = "3", payload=None):
    return SimpleNamespace(
        id=f"t-fake-{op}",
        op=op,
        owner_agent=owner,
        payload=payload or {},
    )


def test_unknown_op_raises(tmp_path: Path) -> None:
    """The exact bug from 2026-04-23: op='update' used to silently
    complete - now it must raise."""
    handler, monkey = _make_supervisor(tmp_path)
    try:
        self = SimpleNamespace()  # _run_deterministic is a bound method -
        # but it only uses `task`, so self doesn't actually need to be a
        # real Supervisor. The method treats `self` opaquely.
        with pytest.raises(RuntimeError) as exc:
            handler(self, _fake_task("update", owner="3"))
        assert "no deterministic handler" in str(exc.value)
        assert "op='update'" in str(exc.value)
    finally:
        _restore(monkey)


def test_record_keeping_op_noops(tmp_path: Path) -> None:
    """Record-keeping ops (advisories, notes) still complete without
    a handler - filing IS the work."""
    handler, monkey = _make_supervisor(tmp_path)
    try:
        self = SimpleNamespace()
        result = handler(self, _fake_task("cold-streak-advisory", owner="1"))
        assert result["dispatched"] is True
        assert result.get("noop") is True
        result2 = handler(self, _fake_task("user-note", owner="4"))
        assert result2.get("noop") is True
    finally:
        _restore(monkey)


def test_test_prefixed_op_noops(tmp_path: Path) -> None:
    """pytest fakes use 'test-*' - permit so existing tests still pass."""
    handler, monkey = _make_supervisor(tmp_path)
    try:
        self = SimpleNamespace()
        result = handler(self, _fake_task("test-round22-detail", owner="6"))
        assert result["dispatched"] is True
        assert result.get("noop") is True
    finally:
        _restore(monkey)


def test_registered_handler_still_runs(tmp_path: Path, monkeypatch) -> None:
    """game-summary must still route to the real handler (not the noop
    path) - the allowlist can't break existing deterministic ops."""
    handler, monkey = _make_supervisor(tmp_path)
    try:
        # Stub ingest_game_summary so we don't need a real mode DB.
        import agents.agent2_backend.game_ingest as gi
        calls = {"n": 0}
        def _fake(payload):
            calls["n"] += 1
            return {"inserted": False, "stub": True}
        monkeypatch.setattr(gi, "ingest_game_summary", _fake)

        self = SimpleNamespace()
        result = handler(self, _fake_task("game-summary", owner="2",
                                          payload={"champion": "X"}))
        assert calls["n"] == 1
        assert result["handler"] == "game_ingest.ingest_game_summary"
    finally:
        _restore(monkey)


# ── Agent 7 LLM fallback op constraint ──────────────────────────────

def _fake_llm_returning(op: str, reply: str = "ok"):
    """Build a llm_spawn callable that mimics the Haiku CLI envelope."""
    def _spawn(agent, task_id, op_name, payload):
        body = {"task": {"op": op, "owner_agent": "3", "priority": 50,
                         "payload": {"target": "item_build_display"}},
                "reply": reply}
        return {"result": {"result": json.dumps(body)}}
    return _spawn


def test_llm_allowed_op_passes_through(tmp_path: Path) -> None:
    """An op already in the allowed vocabulary gets filed as-is."""
    from agents.agent1_lead import Scheduler
    from agents.agent7_context.input_parser import InputParser, LLM_ALLOWED_OPS
    assert "user-note" in LLM_ALLOWED_OPS   # sanity

    s = Scheduler(queue_log=tmp_path / "q.jsonl")
    p = InputParser(scheduler=s, llm_spawn=_fake_llm_returning("user-note"))
    # Phrase that misses every rule so we hit the LLM fallback.
    r = p.parse("contemplate the weather")
    assert r.used_llm is True
    assert r.intent == "fallback_llm"
    # Scheduler records the filed task with the allowed op.
    assert r.filed
    t = s.get(r.filed[0])
    assert t.op == "user-note"
    assert t.payload["op_coerced"] is False


def test_llm_fabricated_op_coerced_to_unparsed(tmp_path: Path) -> None:
    """The exact bug: LLM emits op='update', parser coerces to
    'user-unparsed' instead of letting it file to agent 3."""
    from agents.agent1_lead import Scheduler
    from agents.agent7_context.input_parser import InputParser

    s = Scheduler(queue_log=tmp_path / "q.jsonl")
    p = InputParser(scheduler=s, llm_spawn=_fake_llm_returning("update"))
    r = p.parse("please update the item build display for current context")
    assert r.used_llm is True
    assert r.intent == "fallback_llm_coerced"
    # The filed task lands as user-unparsed on agent 7.
    t = s.get(r.filed[0])
    assert t.op == "user-unparsed"
    assert t.owner_agent == "7"
    assert t.payload["llm_proposed_op"] == "update"
    assert t.payload["op_coerced"] is True
    # Reply surfaces the coercion so the user sees what happened.
    assert "update" in r.reply
    assert "user-unparsed" in r.reply


def test_llm_prompt_carries_allowed_ops(tmp_path: Path) -> None:
    """The instruction passed to the LLM must enumerate the allowed
    ops so the model can constrain itself."""
    from agents.agent1_lead import Scheduler
    from agents.agent7_context.input_parser import InputParser, LLM_ALLOWED_OPS

    captured = {}
    def _spawn(agent, task_id, op_name, payload):
        captured["payload"] = payload
        return {"result": {"result": '{"reply": "acknowledged"}'}}

    s = Scheduler(queue_log=tmp_path / "q.jsonl")
    p = InputParser(scheduler=s, llm_spawn=_spawn)
    p.parse("totally novel thing")
    assert "allowed_ops" in captured["payload"]
    # Confirm all expected ops flow through.
    for op in ("game-summary", "user-note", "user-unparsed"):
        assert op in captured["payload"]["allowed_ops"]
    # Instruction mentions the vocabulary.
    instr = captured["payload"]["instruction"]
    assert "Allowed op values" in instr
    assert "DO NOT invent op names" in instr


def test_llm_conversational_reply_unchanged(tmp_path: Path) -> None:
    """Pure-reply LLM responses still work (no task filed)."""
    from agents.agent1_lead import Scheduler
    from agents.agent7_context.input_parser import InputParser

    def _spawn(agent, task_id, op_name, payload):
        return {"result": {"result": '{"reply": "hi there"}'}}
    s = Scheduler(queue_log=tmp_path / "q.jsonl")
    p = InputParser(scheduler=s, llm_spawn=_spawn)
    r = p.parse("howdy")
    # A pure {"reply": ...} from LLM => no filed task, reply surfaces.
    assert r.reply == "hi there" or r.intent in ("fallback_llm", "chitchat")


# ── constant-integrity smoke tests ─────────────────────────────────

def test_supervisor_allowlist_constants_present() -> None:
    sup = Path("agents/supervisor.py").read_text(encoding="utf-8")
    assert "_DETERMINISTIC_HANDLED_OPS" in sup
    assert "_DETERMINISTIC_RECORDKEEPING_OPS" in sup
    assert "no deterministic handler for op=" in sup


def test_parser_allowlist_constants_present() -> None:
    parser = Path("agents/agent7_context/input_parser.py").read_text(encoding="utf-8")
    assert "LLM_ALLOWED_OPS" in parser
    assert "op_coerced" in parser
    assert "llm_proposed_op" in parser
