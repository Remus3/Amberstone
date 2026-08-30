# arch: contention + byte-fidelity tests for POST /api/loop-control | section=tests | frozen=no
"""Lane 8 cycle 21 regression tests for dashboard.routes_loop_control._awrite.

The module docstring of routes_loop_control states that loop_controller.py
"polls those files", and _awrite's own docstring says "loop_controller polls
mid-write". That is the exact condition under which Windows os.replace raises
PermissionError (WinError 5): a concurrent reader holding the destination open
takes a share lock for the duration of its read.

core/polled_json.py:39 _replace_with_retry already exists for this and its
comment calls the contention "routine". _awrite did not use it, so:

  1. The operator's emergency `stop` - the halt button on the phone over
     Tailscale - raised PermissionError out of apply_action, was swallowed by
     the catch-all in _serve_loop_control, and returned HTTP 500 "internal
     error - see logs". The loop kept running. Same for the halt_save intent,
     which raises STOP on the same path.
  2. The failed replace left a STOP.tmp behind. test_loop_control_route.py
     ::test_atomic_no_tmp_left pins the opposite, but passes because it never
     exercises contention - the guard was on a call path no test drove.

Separately, _awrite used Path.write_text, which translates LF to CRLF on
Windows. The route reports `len(text)` characters to the operator while writing
a different number of bytes, and MAX_DIRECTIVE is consequently not a byte cap.
"""
from __future__ import annotations

import contextlib
import json
import threading
import time

import pytest

from dashboard import routes_loop_control as mod


class FakeHandler:
    """Minimal handler stand-in capturing _send(status, body, ctype)."""

    def __init__(self, path: str = "/api/loop-control") -> None:
        self.path = path
        self.sent: tuple | None = None

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.sent = (status, body, ctype)


@pytest.fixture
def ctldir(tmp_path, monkeypatch):
    ctl = tmp_path / "control"
    ctl.mkdir()
    monkeypatch.setattr(mod, "CONTROL_DIR", ctl)
    return ctl


@contextlib.contextmanager
def _transient_reader(path, hold_s: float = 0.06):
    """Hold `path` open for read briefly, the way a poller actually does.

    loop_controller polls every 5 s and the AHK bridge every 1 s; each read
    holds the share lock for milliseconds, not for the whole write attempt.
    That is the window _replace_with_retry (~275 ms of backoff) is sized for,
    so the reader must RELEASE for the retry to be able to win - a reader held
    for the full attempt tests the exhaustion path, not the retry path.
    """
    started = threading.Event()

    def _hold():
        with open(path, encoding="utf-8"):
            started.set()
            time.sleep(hold_s)

    t = threading.Thread(target=_hold, daemon=True)
    t.start()
    started.wait(timeout=5)
    try:
        yield
    finally:
        t.join(timeout=5)


def _post(body):
    h = FakeHandler()
    mod._serve_loop_control(h, body)
    assert h.sent is not None
    status, raw, ctype = h.sent
    return status, json.loads(raw.decode("utf-8")), ctype


# ------------------------------------------------- contention on the halt path
def test_stop_succeeds_while_a_reader_holds_STOP_open(ctldir):
    """The halt must land even though the controller is mid-poll on STOP."""
    stop = ctldir / "STOP"
    stop.write_text("previous reason", encoding="utf-8")
    with _transient_reader(stop):
        status, payload, _ = _post({"action": "stop", "reason": "halt from phone"})
    assert status == 200, f"halt failed under a concurrent reader: {payload}"
    assert payload["ok"] is True
    assert stop.read_text(encoding="utf-8") == "halt from phone"


def test_stop_under_contention_leaves_no_tmp(ctldir):
    """A contended write must not strand STOP.tmp in the control dir."""
    stop = ctldir / "STOP"
    stop.write_text("previous reason", encoding="utf-8")
    with _transient_reader(stop):
        _post({"action": "stop", "reason": "halt from phone"})
    assert list(ctldir.glob("*.tmp")) == []


def test_halt_save_raises_STOP_while_a_reader_holds_it(ctldir):
    """queue_intent halt_save writes the intent AND raises STOP on the same path."""
    stop = ctldir / "STOP"
    stop.write_text("previous reason", encoding="utf-8")
    with _transient_reader(stop):
        status, payload, _ = _post({
            "action": "queue_intent", "intent": "halt_save",
            "idempotency_key": "a1b2c3d4-0000-4000-8000-000000000001",
        })
    assert status == 200, f"halt_save failed under a concurrent reader: {payload}"
    assert payload["ok"] is True
    assert stop.read_text(encoding="utf-8") == "halt_save queued from dashboard"
    assert json.loads((ctldir / "INTENT_HALT_SAVE.json").read_text(
        encoding="utf-8"))["intent"] == "halt_save"


def test_set_directive_survives_a_reader_on_the_override(ctldir):
    override = ctldir / "directive_override.md"
    override.write_text("old directive", encoding="utf-8")
    with _transient_reader(override):
        status, payload, _ = _post({"action": "set_directive", "text": "new directive"})
    assert status == 200, f"set_directive failed under a reader: {payload}"
    assert override.read_text(encoding="utf-8") == "new directive"


# ---------------------------------------------------------------- byte fidelity
def test_directive_bytes_on_disk_match_the_reported_char_count(ctldir):
    """Path.write_text turns LF into CRLF on Windows; the cap must be honest."""
    text = "line1\nline2\nline3"
    status, payload, _ = _post({"action": "set_directive", "text": text})
    assert status == 200
    raw = (ctldir / "directive_override.md").read_bytes()
    assert b"\r\n" not in raw, "LF was rewritten as CRLF"
    assert len(raw) == len(text.encode("utf-8")) == 17
    assert payload["detail"] == "17 chars queued"


def test_stop_reason_newlines_are_written_verbatim(ctldir):
    _post({"action": "stop", "reason": "halting\nmid-cycle"})
    assert (ctldir / "STOP").read_bytes() == b"halting\nmid-cycle"


def test_the_char_cap_also_bounds_bytes_for_ascii_text(ctldir):
    """MAX_DIRECTIVE chars, half of them newlines, must not become 2x bytes.

    SCOPE, stated so the name does not overclaim: `MAX_DIRECTIVE` is applied as
    `text[:MAX_DIRECTIVE]`, a CHARACTER cap, so this proves only that the LF ->
    CRLF rewrite no longer inflates it. A directive of multi-byte UTF-8 can
    still exceed MAX_DIRECTIVE bytes (up to 4x). That is bounded, not
    unbounded, so it is not the defect this cycle fixed - it is recorded here
    rather than silently implied away by a broader-sounding test name.

    A directive of PURE newlines is not the case to test: apply_action strips
    the text first, so it is an empty-text 400 by contract, not a write.
    """
    text = "a\n" * mod.MAX_DIRECTIVE  # 2x MAX chars, half of them newlines
    status, _, _ = _post({"action": "set_directive", "text": text})
    assert status == 200
    raw = (ctldir / "directive_override.md").read_bytes()
    assert len(raw) == mod.MAX_DIRECTIVE, "the char cap must also bound bytes"
    assert b"\r\n" not in raw


# ------------------------------------------------- read-only means read-only
def test_interrupt_preview_creates_nothing_on_disk(tmp_path, monkeypatch):
    """Its docstring says 'Kills nothing, writes nothing' - hold it to that."""
    ctl = tmp_path / "control"
    monkeypatch.setattr(mod, "CONTROL_DIR", ctl)

    class _Stub:
        @staticmethod
        def preview():
            return {"ok": True, "victims": [], "fingerprint": "deadbeef"}

    monkeypatch.setitem(mod.sys.modules, mod._INTERRUPT_MODULE, _Stub)
    status, payload, _ = _post({"action": "interrupt_preview"})
    assert status == 200 and payload["fingerprint"] == "deadbeef"
    assert not ctl.exists(), "a read-only preview created the control dir"


# ------------------------------------------- the exhaustion path, not the retry
def test_a_reader_held_past_the_retry_window_is_503_not_500(ctldir):
    """Retry exhausted is a KNOWN transient condition, not an internal error.

    The operator has to be able to tell "your halt did not land, press it
    again" from "the server is broken". CLAUDE.md Error Handling: friendly
    actionable message out, raw cause to the log.
    """
    stop = ctldir / "STOP"
    stop.write_text("previous reason", encoding="utf-8")
    with open(stop, encoding="utf-8"):  # held for the WHOLE attempt
        status, payload, _ = _post({"action": "stop", "reason": "halt"})
    assert status == 503, f"expected a retryable 503, got {status}: {payload}"
    assert payload["error"] == "control file busy - the loop is mid-poll, retry"
    assert "WinError" not in payload["error"] and "Temp" not in payload["error"]


def test_an_exhausted_retry_strands_no_tmp(ctldir):
    """A stranded STOP.tmp is the next writer's problem - clean it up."""
    stop = ctldir / "STOP"
    stop.write_text("previous reason", encoding="utf-8")
    with open(stop, encoding="utf-8"):
        _post({"action": "stop", "reason": "halt"})
    assert list(ctldir.glob("*.tmp")) == []


# --------------------------------------------------- steer under lock contention
def test_steer_lock_contention_is_503_not_500(ctldir, monkeypatch):
    """ops/loop/steer.py raises MutexTimeout, a RuntimeError - NOT an OSError.

    Only ValueError/OSError were caught, so losing the 5 s named-mutex race
    fell through to the top-level guard and became a 500 "internal error" for
    what is simply "busy, retry".
    """
    class MutexTimeout(RuntimeError):
        """Same NAME as ops/loop/winmutex.py:46, which is what the route matches."""

    class _Boom:
        TIERS = ("note", "steer")

        @staticmethod
        def append(text, *, tier, key):
            raise MutexTimeout("mutex RC-SteerLog not free within 5.0s")

    monkeypatch.setitem(mod.sys.modules, mod._STEER_MODULE, _Boom)
    status, payload, _ = _post({
        "action": "steer", "text": "focus the audit on the poller",
        "idempotency_key": "beef-0000-4000-8000-000000000002",
    })
    assert status == 503, f"expected 503, got {status}: {payload}"
    assert payload["error"] == "steer channel busy - retry"
    assert "mutex" not in payload["error"], "raw cause leaked to the client"


def test_a_non_mutex_runtimeerror_is_NOT_reported_as_busy(ctldir, monkeypatch):
    """A real bug in steer.append must not be dressed up as lock contention.

    "busy - retry" hides the fault AND suggests a remedy that cannot work, so
    the RuntimeError catch is narrowed to MutexTimeout by name; everything else
    falls through to the generic scrubbed guard.
    """
    class _Bug:
        TIERS = ("note", "steer")

        @staticmethod
        def append(text, *, tier, key):
            raise RuntimeError("dictionary changed size during iteration")

    monkeypatch.setitem(mod.sys.modules, mod._STEER_MODULE, _Bug)
    status, payload, _ = _post({
        "action": "steer", "text": "a steer",
        "idempotency_key": "beef-0000-4000-8000-000000000003",
    })
    assert status == 500, f"a genuine bug must not be a 503: {payload}"
    assert payload["error"] == "internal error - see logs"
    assert "dictionary" not in payload["error"], "raw cause leaked to the client"
