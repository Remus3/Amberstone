"""P2-W2 cycle 12 Phase-3 supervisor audit (slice H) - regression tests.

Covers the FIX-NOW hardening landed in this slice across the Phase 3
supervisor set (agents/_supervisor_http.py, _supervisor_ephemeral.py,
_supervisor_common.py, supervisor.py):

* HTTP handlers no longer leak a raw exception string (``str(exc)`` /
  ``f"...{exc}"``) into a wire-JSON ``error`` field. The dominant cycle
  5-11 class: an internal path, import detail, or secret-shaped traceback
  fragment reaching the dashboard. The new ``_QuietHandler._send_error``
  logs the raw cause and emits only a generic public message.
* ``_QuietHandler._send_json`` serializes with ``allow_nan=False`` so a
  non-finite float bubbling into a body becomes a generic 500 envelope
  instead of a bare ``NaN`` / ``Infinity`` token that breaks a strict
  dashboard ``JSON.parse`` (non-finite-token class).
* ``spawn_ephemeral_llm`` redacts the subprocess stderr it embeds in the
  ``EphemeralSpawnFailed`` message - that text becomes the task's
  ``last_error`` -> the /api/task/<id> wire body, so an ANTHROPIC_API_KEY
  echo in stderr must not leak there raw.
* ``refresh_lock`` / ``acquire_lock`` write the supervisor lockfile
  atomically (tmp + os.replace) so the frozen _Phase3Watcher never reads a
  torn JSON mid-write (non-atomic-write hard rule).
* ``Supervisor.stop`` toggles ``logging.raiseExceptions = False`` for the
  teardown drain (cycle-5 logging-after-close class) and restores it.

Symbols grep-confirmed against the live tree before use:
  _supervisor_http._QuietHandler                 (_supervisor_http.py:27)
  _QuietHandler._send_json                       (_supervisor_http.py:118)
  _QuietHandler._send_error                      (_supervisor_http.py:135)
  _QuietHandler._handle_input                    (_supervisor_http.py:152)
  _QuietHandler._handle_adaptation               (_supervisor_http.py:602)
  _supervisor_ephemeral.spawn_ephemeral_llm      (_supervisor_ephemeral.py:102)
  _supervisor_ephemeral.EphemeralSpawnFailed     (_supervisor_ephemeral.py:45)
  _supervisor_common.refresh_lock                (_supervisor_common.py:359)
  _supervisor_common._atomic_write_json          (_supervisor_common.py:226)
  _supervisor_common._STARTED_AT                 (_supervisor_common.py:170)
  agents.supervisor.Supervisor.stop              (supervisor.py:315)
  agent7_context.input_parser.InputParser        (input_parser.py:91)
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import threading
from pathlib import Path
from unittest import mock

import pytest

from agents import _supervisor_common as common
from agents import _supervisor_http as http_mod
from agents import _supervisor_ephemeral as eph
from agents.supervisor import Supervisor
from tests._asyncio_isolation import run_coro as _run_coro


# ---------------------------------------------------------------------------
# Test scaffolding: build a _QuietHandler without binding a socket.
# ---------------------------------------------------------------------------
class _FakeHandler(http_mod._QuietHandler):
    """A _QuietHandler with __init__ bypassed - no socket, no port bind.

    Captures the response status + body via the BaseHTTPRequestHandler
    surface the handler uses (send_response / send_header / end_headers /
    wfile.write). ``command`` defaults to GET so body writes happen.
    """

    def __init__(self, *, body: bytes = b"", headers: dict | None = None,
                 path: str = "/", server: object | None = None) -> None:
        # Intentionally do NOT call super().__init__ (it needs a live socket).
        self.command = "GET"
        self.path = path
        self.rfile = io.BytesIO(body)
        self.wfile = io.BytesIO()
        self.headers = headers or {"Content-Length": str(len(body))}
        self.server = server
        self._status: int | None = None
        self._sent_headers: dict[str, str] = {}

    # -- BaseHTTPRequestHandler surface used by _send_json / handlers ------
    def send_response(self, code: int, message: str | None = None) -> None:
        self._status = code

    def send_header(self, key: str, value: str) -> None:
        self._sent_headers[key] = value

    def end_headers(self) -> None:
        pass

    def address_string(self) -> str:
        return "test-client"

    # -- assertions helpers ----------------------------------------------
    def body_text(self) -> str:
        return self.wfile.getvalue().decode("utf-8")

    def body_json(self) -> dict:
        return json.loads(self.wfile.getvalue().decode("utf-8"))


class _StubSupervisor:
    """Minimal stand-in for the Supervisor the handler reads."""

    def __init__(self) -> None:
        self.warm_agent7 = None      # keeps spawn_fn == spawn_ephemeral_llm
        self.scheduler = object()    # only passed into the (patched) parser

    def record_input_latency(self, _ms: float) -> None:  # pragma: no cover
        pass


class _StubServer:
    def __init__(self, supervisor: object) -> None:
        self.supervisor = supervisor


# ---------------------------------------------------------------------------
# _send_error - never leaks the raw exception text to the wire body.
# ---------------------------------------------------------------------------
def test_send_error_returns_generic_message_only() -> None:
    h = _FakeHandler()
    secret = "sk-ant-SECRET_TRACEBACK_FRAGMENT_0123456789abcdef"
    exc = RuntimeError(f"boom at C:/private/path with {secret}")
    h._send_error(503, "coaching paused - retrying", exc)

    assert h._status == 503
    obj = h.body_json()
    # NEW behavior: only the generic public message is on the wire.
    assert obj == {"error": "coaching paused - retrying"}
    # OLD behavior (str(e) on the wire) would have leaked the raw text.
    assert secret not in h.body_text()
    assert "private/path" not in h.body_text()


def test_send_error_logs_raw_cause(caplog: pytest.LogCaptureFixture) -> None:
    h = _FakeHandler()
    with caplog.at_level(logging.WARNING, logger="supervisor"):
        h._send_error(500, "internal error - see supervisor log",
                      RuntimeError("raw-cause-xyz"))
    # The raw cause must be logged (so operators can still diagnose).
    assert any("raw-cause-xyz" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------
# _send_json - allow_nan=False guards against bare NaN/Infinity tokens.
# ---------------------------------------------------------------------------
def test_send_json_rejects_non_finite_float() -> None:
    h = _FakeHandler()
    # A handler that accidentally bubbles a non-finite float into the body.
    h._send_json(200, {"value": float("inf")})
    # NEW behavior: degrades to a 500 generic error envelope; the body is
    # strict-parseable JSON with no bare Infinity token.
    assert h._status == 500
    text = h.body_text()
    assert "Infinity" not in text
    assert "NaN" not in text
    # json.loads with default (strict) parser must succeed.
    assert json.loads(text) == {"error": "internal error - see supervisor log"}


def test_send_json_finite_payload_unchanged() -> None:
    h = _FakeHandler()
    h._send_json(200, {"ok": True, "n": 3, "f": 1.5})
    assert h._status == 200
    assert h.body_json() == {"ok": True, "n": 3, "f": 1.5}


# ---------------------------------------------------------------------------
# _handle_input - a parser raise yields a generic 500, not str(exc).
# ---------------------------------------------------------------------------
def test_handle_input_parser_raise_is_generic() -> None:
    secret_msg = "internal parser blew up: sk-ant-LEAKYKEY_0123456789abcdefXYZ"

    class _BoomParser:
        def __init__(self, *a, **kw) -> None:
            pass

        def parse(self, _text: str):
            raise RuntimeError(secret_msg)

    sup = _StubSupervisor()
    server = _StubServer(sup)
    body = json.dumps({"text": "why is my cs low"}).encode("utf-8")
    h = _FakeHandler(body=body, path="/api/input", server=server)
    h.command = "POST"

    # Patch the lazily-imported InputParser symbol the handler resolves.
    with mock.patch("agents.agent7_context.InputParser", _BoomParser):
        h._handle_input()

    assert h._status == 500
    obj = h.body_json()
    assert obj == {"error": "coaching paused - retrying"}
    # OLD behavior surfaced str(e) (the secret) directly to the wire.
    assert "sk-ant-" not in h.body_text()
    assert secret_msg not in h.body_text()


def test_handle_input_bad_json_is_generic() -> None:
    sup = _StubSupervisor()
    server = _StubServer(sup)
    body = b"{ this is not valid json"
    h = _FakeHandler(body=body, path="/api/input", server=server)
    h.command = "POST"
    h._handle_input()
    assert h._status == 400
    obj = h.body_json()
    assert obj == {"error": "malformed JSON body"}
    # The raw JSONDecodeError detail (line/col text) must not be echoed.
    assert "line" not in h.body_text().lower()


# ---------------------------------------------------------------------------
# _handle_adaptation - a helper-import failure yields a generic 500.
# ---------------------------------------------------------------------------
def test_handle_adaptation_import_failure_is_generic() -> None:
    sup = _StubSupervisor()
    server = _StubServer(sup)
    h = _FakeHandler(path="/api/adaptation?champion=Ahri&mode=aram",
                     server=server)

    leaky = ImportError("No module named 'coaches.secret_internal_path'")

    # Force the in-handler import to raise by removing the module and
    # making the import statement raise our crafted error.
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) \
        else __builtins__.__import__

    def _boom_import(name, *a, **kw):
        if name == "coaches.adaptation_hint":
            raise leaky
        return real_import(name, *a, **kw)

    with mock.patch("builtins.__import__", side_effect=_boom_import):
        h._handle_adaptation()

    assert h._status == 500
    obj = h.body_json()
    assert obj == {"error": "internal error - see supervisor log"}
    assert "secret_internal_path" not in h.body_text()


# ---------------------------------------------------------------------------
# spawn_ephemeral_llm - stderr embedded in EphemeralSpawnFailed is redacted.
# ---------------------------------------------------------------------------
def test_ephemeral_failure_message_redacts_stderr(tmp_path: Path) -> None:
    secret = "sk-ant-DEADBEEF_0123456789abcdefGHIJKL"

    class _FakeProc:
        returncode = 1
        stdout = ""
        stderr = f"Traceback ... ANTHROPIC_API_KEY={secret} ... boom"

    # Isolate every filesystem + subprocess boundary:
    #   * LOG_ROOT -> tmp_path so no real logs/ writes
    #   * shutil.which -> a fake path so the CLI-missing branch is skipped
    #   * AGENT_CHARTERS -> {} so no charter file is required
    #   * subprocess.run -> returns our non-zero fake proc (no real spawn)
    with mock.patch.object(eph, "LOG_ROOT", tmp_path), \
            mock.patch.object(eph.shutil, "which", return_value=str(tmp_path / "claude")), \
            mock.patch.object(eph, "AGENT_CHARTERS", {}), \
            mock.patch.object(eph.subprocess, "run", return_value=_FakeProc()):
        with pytest.raises(eph.EphemeralSpawnFailed) as ei:
            eph.spawn_ephemeral_llm("4", "task-redact-1", "test-op", {})

    msg = str(ei.value)
    # NEW behavior: the secret is scrubbed from the exception text (which
    # flows to Scheduler.fail(error=...) -> last_error -> the wire).
    assert secret not in msg
    assert "[REDACTED-SECRET]" in msg

    # And the per-task log mirror also has the secret redacted.
    task_log = tmp_path / "task-task-redact-1.log"
    assert task_log.exists()
    assert secret not in task_log.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# refresh_lock - atomic write (tmp + os.replace), no torn read.
# ---------------------------------------------------------------------------
def test_refresh_lock_is_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lock = tmp_path / "state" / "lockfile"
    monkeypatch.setattr(common, "LOCKFILE", lock)

    calls: list[tuple[str, str]] = []
    real_replace = common.os.replace

    def _spy_replace(src, dst):
        calls.append((str(src), str(dst)))
        return real_replace(src, dst)

    monkeypatch.setattr(common.os, "replace", _spy_replace)
    common.refresh_lock()

    # NEW behavior: the final move targets the lockfile via os.replace, and
    # the source is a distinct temp (never written directly to LOCKFILE).
    assert calls, "refresh_lock must finalize via os.replace (atomic write)"
    src, dst = calls[-1]
    assert dst == str(lock)
    assert src != str(lock)
    # The lockfile decodes as complete JSON with the heartbeat stamp.
    data = json.loads(lock.read_text(encoding="utf-8"))
    assert data["pid"] == common.os.getpid()
    assert "heartbeat_at" in data
    # No leftover temp file beside the lockfile.
    leftovers = [p.name for p in lock.parent.glob("*.tmp")]
    assert leftovers == []


def test_atomic_write_json_temp_is_pid_unique(tmp_path: Path) -> None:
    target = tmp_path / "lockfile"
    captured: list[str] = []
    real_replace = common.os.replace

    def _spy_replace(src, dst):
        captured.append(str(src))
        return real_replace(src, dst)

    with mock.patch.object(common.os, "replace", side_effect=_spy_replace):
        common._atomic_write_json(target, {"a": 1})

    # The temp name embeds the PID so two reclaiming starters never collide
    # on a shared .tmp (shared-.tmp-race class).
    assert captured
    assert str(common.os.getpid()) in captured[-1]
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}


# ---------------------------------------------------------------------------
# Supervisor.stop - toggles logging.raiseExceptions off then restores it.
# ---------------------------------------------------------------------------
def test_stop_restores_raise_exceptions() -> None:
    sup = Supervisor()
    # Nothing started: every optional handle is None, so stop() walks the
    # teardown path without touching real servers/threads.
    prev = logging.raiseExceptions
    try:
        logging.raiseExceptions = True
        _run_coro(sup.stop())
        # Restored to whatever it was on entry (True here).
        assert logging.raiseExceptions is True
    finally:
        logging.raiseExceptions = prev


def test_stop_suppresses_logging_during_drain() -> None:
    """During the drain, raiseExceptions must be False so a racing emit on
    a closing handler can't spray a traceback. We observe the value from
    inside a teardown hook (decision_loop.stop)."""
    sup = Supervisor()
    observed: dict[str, bool] = {}

    class _Loop:
        def stop(self_inner) -> None:
            observed["raise"] = logging.raiseExceptions

    sup._decision_loop = _Loop()
    prev = logging.raiseExceptions
    try:
        logging.raiseExceptions = True
        _run_coro(sup.stop())
    finally:
        logging.raiseExceptions = prev
    assert observed.get("raise") is False
