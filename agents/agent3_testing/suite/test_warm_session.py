"""Unit tests for Agent 7 warm session — mocked Anthropic client.

No real network calls. Verify:
  * Lazy client instantiation on first send.
  * Idle reset after timeout.
  * Token counters accumulate.
  * Failure during send rolls back the trailing user message so a
    retry doesn't duplicate.
  * Close clears state.
  * warm_spawn_factory produces an InputParser-compatible spawn callable.
"""
from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agents.agent7_context.warm_session import (
    WarmAgent7Session,
    WarmSessionError,
    warm_spawn_factory,
)


def _fake_response(text: str = "hi", inp: int = 10, out: int = 5):
    return SimpleNamespace(
        content=[SimpleNamespace(text=text)],
        usage=SimpleNamespace(input_tokens=inp, output_tokens=out),
    )


def _patched_session(api_key: str = "sk-ant-test") -> WarmAgent7Session:
    return WarmAgent7Session(api_key=api_key, charter="TEST CHARTER")


def test_send_happy_path() -> None:
    s = _patched_session()
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response("hello world", 42, 11)
    with patch("anthropic.Anthropic", return_value=fake_client):
        out = s.send("ping")
    assert out["text"] == "hello world"
    assert out["input_tokens"] == 42
    assert out["output_tokens"] == 11
    assert out["turns"] == 1
    stats = s.stats()
    assert stats["warm"] is True
    assert stats["history_len"] == 2    # user + assistant
    assert stats["total_input_tokens"] == 42


def test_send_raises_on_empty_text() -> None:
    s = _patched_session()
    with pytest.raises(WarmSessionError):
        s.send("")
    with pytest.raises(WarmSessionError):
        s.send("   ")


def test_missing_api_key_raises() -> None:
    s = WarmAgent7Session(api_key="")
    with pytest.raises(WarmSessionError) as ei:
        s.send("anything")
    assert "no ANTHROPIC_API_KEY" in str(ei.value)


def test_idle_reset_clears_history() -> None:
    s = _patched_session()
    s._idle_timeout = 0.05       # tighten for the test
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response()
    with patch("anthropic.Anthropic", return_value=fake_client):
        s.send("first")
        assert len(s._messages) == 2
        # Advance past the idle timeout.
        time.sleep(0.1)
        s.send("after-idle")
    # History was cleared between turns, so only 2 messages present
    # (the post-reset user + assistant). The first turn is gone.
    assert len(s._messages) == 2
    assert s._messages[0]["content"] == "after-idle"


def test_failure_rolls_back_user_message() -> None:
    s = _patched_session()
    fake_client = MagicMock()
    fake_client.messages.create.side_effect = RuntimeError("boom")
    with patch("anthropic.Anthropic", return_value=fake_client):
        with pytest.raises(WarmSessionError):
            s.send("ping")
    assert s._messages == []     # no stale trailing user


def test_close_clears_state() -> None:
    s = _patched_session()
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response()
    with patch("anthropic.Anthropic", return_value=fake_client):
        s.send("ping")
    s.close()
    st = s.stats()
    assert st["warm"] is False
    assert st["history_len"] == 0


def test_history_trimmed_to_cap() -> None:
    s = _patched_session()
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response()
    with patch("anthropic.Anthropic", return_value=fake_client):
        for i in range(30):      # more than MAX_HISTORY_TURNS * 2
            s.send(f"turn-{i}")
    from agents.agent7_context.warm_session import MAX_HISTORY_TURNS
    assert len(s._messages) <= MAX_HISTORY_TURNS * 2


def test_warm_spawn_factory_matches_cli_envelope() -> None:
    s = _patched_session()
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response(
        text='{"reply":"from warm","filed":[]}', inp=12, out=8
    )
    with patch("anthropic.Anthropic", return_value=fake_client):
        spawn = warm_spawn_factory(s)
        env = spawn("7", "t-x", "demo", {"message": "hello"})
    assert env["ok"] is True
    assert env["substrate"] == "warm_agent7_session"
    assert env["exit_code"] == 0
    # Same shape as spawn_ephemeral_llm — .result.result carries the text
    assert env["result"]["type"] == "result"
    assert env["result"]["result"] == '{"reply":"from warm","filed":[]}'
    assert env["result"]["usage"]["input_tokens"] == 12
