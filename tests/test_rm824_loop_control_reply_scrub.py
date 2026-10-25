# arch: RM-824 - Mission Control loop-control replies never carry exception text | section=tests | frozen=no
"""RM-824: an /api/loop-control reply never carries exception text.

Measured at main e9261314d, before the fix: six sites in
``dashboard/routes_loop_control.py`` (served only on Mission Control :8895)
put the bound exception's text into the JSON ``error`` field of the reply -
fire_lane's ValueError (400) and launch fault (503), steer's ValueError (400)
and OSError (503), interrupt_preview's probe fault (503) and interrupt's
kill-path fault (503). The ValueError ``ops/loop/lanes.py`` raises for the main
tree names REPO_ROOT, an OSError names its file, and a launch fault carries git
or spawn text. The log line beside four of them was already scrubbed (RM-811
residuals); the reply was not. That broke the RM-134 contract in
``dashboard/_errors.py`` (a reply never carries exception text) and the
CLAUDE.md error-handling rule (a friendly message out, the raw cause to logs).

Each case below drives the real HTTP entry point (``_serve_loop_control``,
arm-then-confirm included) into one site's exception path, with an exception
whose text carries a marker, a path and control characters, and asserts that
the status and envelope are the route's contract, that the reply carries none
of that text, that the message is FIXED (two different exception texts give
the same reply), and that the raw cause reached the log, scrubbed. A source
guard then sweeps the two MC-served loop modules and ``mc/`` for any reply that
names an except-bound exception.
"""
from __future__ import annotations

import ast
import json
import logging
import sys
import types
from pathlib import Path

import pytest

from dashboard import _arm_confirm as armgate
from dashboard import _idempotency as idem
from dashboard import routes_loop_control as mod
from tests._reply_leak_ast import (ASSIGNMENT_SHAPES, SAFE_ASSIGNMENTS,
                                   reply_leaks)

ROOT = Path(__file__).resolve().parent.parent

KEY = "5e1d7c2a-9b84-4f3e-a610-2c4d6e8f0a1b"
SECRET_PATH = r"C:\Example Repo\ops\loop\control\lanes\slot0.json"
_CONTROL_CHARS = ("\x1b", "\r", "\n", "\x85", "\x7f")


def _evil(marker: str) -> str:
    """Exception text with a marker, a filesystem path and control chars."""
    return f"{marker} at {SECRET_PATH} \x1b[31m\r\nFAKE-LINE\x85\x7f"


# --------------------------------------------------------------------------- harness
class _FakeH:
    def __init__(self) -> None:
        self.path = "/api/loop-control"
        self.sent: tuple | None = None

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.sent = (status, body, ctype)


class _Cap(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture(autouse=True)
def _clean_tables():
    idem.clear()
    armgate.clear()
    yield
    idem.clear()
    armgate.clear()


@pytest.fixture
def ctldir(tmp_path, monkeypatch):
    ctl = tmp_path / "control"
    ctl.mkdir()
    monkeypatch.setattr(mod, "CONTROL_DIR", ctl)
    return ctl


@pytest.fixture
def cap():
    lg = logging.getLogger("rc.web_dashboard")
    handler, prior = _Cap(), lg.level
    lg.addHandler(handler)
    lg.setLevel(logging.DEBUG)
    try:
        yield handler
    finally:
        lg.removeHandler(handler)
        lg.setLevel(prior)


def _raw_post(body: dict) -> tuple[int, bytes]:
    h = _FakeH()
    mod._serve_loop_control(h, body)
    assert h.sent is not None
    status, raw, ctype = h.sent
    assert ctype == "application/json"
    return status, raw


def _post(body: dict) -> tuple[int, bytes]:
    """Arm first when the action is gated - the way an operator drives it."""
    action = str(body.get("action") or "")
    if action in armgate.GATED_ACTIONS and "arm_token" not in body:
        st, armed = _raw_post({"action": "arm", "target_action": action,
                               "target": armgate.target_of(action, body)})
        assert st == 200, armed
        body = dict(body, arm_token=json.loads(armed)["arm_token"])
    return _raw_post(body)


class _Lanes:
    LANES = ("upgrade", "repo")

    def __init__(self, exc: Exception | None = None) -> None:
        self.exc = exc
        self.released: list = []

    def try_acquire_lane(self, lane, *, run_id, worktree, root=None):
        if self.exc is not None:
            raise self.exc
        return {"ok": True, "lane": lane, "run_id": run_id,
                "worktree": worktree, "token": "C:/tmp/lanes/slot0.json"}

    def release_lane(self, token, root=None):
        self.released.append(token)
        return True


def _raiser(exc: Exception):
    def _raise(*_a, **_k):
        raise exc
    return _raise


# --------------------------------------------------------------------------- the six sites
def _fire_lane_value_error(monkeypatch, text):
    monkeypatch.setattr(mod, "_lanes", lambda: _Lanes(ValueError(text)))
    return {"action": "fire_lane", "lane": "repo", "run_id": "cafe0001",
            "worktree": "C:/wt/repo", "idempotency_key": KEY}


def _fire_lane_launch_fault(monkeypatch, text):
    lanes = _Lanes()
    monkeypatch.setattr(mod, "_lanes", lambda: lanes)
    launcher = types.SimpleNamespace(launch_lane=_raiser(RuntimeError(text)))
    monkeypatch.setattr(mod, "_launcher", lambda: launcher)
    return {"action": "fire_lane", "lane": "upgrade", "run_id": "abc12345",
            "worktree": "C:/wt/upgrade", "idempotency_key": KEY}


def _steer_stub(monkeypatch, exc):
    stub = types.SimpleNamespace(TIERS=("note", "steer"), append=_raiser(exc))
    monkeypatch.setitem(sys.modules, mod._STEER_MODULE, stub)
    return {"action": "steer", "tier": "note", "text": "x",
            "idempotency_key": KEY}


def _steer_value_error(monkeypatch, text):
    return _steer_stub(monkeypatch, ValueError(text))


def _steer_os_error(monkeypatch, text):
    # errno + strerror + filename: str() renders "[Errno 5] <text>: '<path>'",
    # the shape a real share-locked or missing control file produces.
    return _steer_stub(monkeypatch, OSError(5, text, SECRET_PATH))


def _interrupt_stub(monkeypatch, text):
    stub = types.SimpleNamespace(preview=_raiser(RuntimeError(text)),
                                 execute=_raiser(RuntimeError(text)))
    monkeypatch.setattr(mod, "_interrupt", lambda: stub)


def _interrupt_preview_fault(monkeypatch, text):
    _interrupt_stub(monkeypatch, text)
    return {"action": "interrupt_preview"}


def _interrupt_fault(monkeypatch, text):
    _interrupt_stub(monkeypatch, text)
    return {"action": "interrupt", "fingerprint": "abc123",
            "idempotency_key": KEY}


# (setup, status, action, keyed) - status and envelope are the route's
# existing contract: a 400 for a rejected body, a 503 for a fault, never
# remembered by the idempotency table.
CASES = {
    "fire_lane-value-error": (_fire_lane_value_error, 400, "fire_lane", True),
    "fire_lane-launch-fault": (_fire_lane_launch_fault, 503, "fire_lane", True),
    "steer-value-error": (_steer_value_error, 400, "steer", True),
    "steer-os-error": (_steer_os_error, 503, "steer", True),
    "interrupt_preview-fault": (_interrupt_preview_fault, 503,
                                "interrupt_preview", False),
    "interrupt-fault": (_interrupt_fault, 503, "interrupt", True),
}


def _strings(node):
    """Every string in a parsed JSON document, keys included."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from _strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _strings(v)


def _drive(monkeypatch, case: str, marker: str) -> tuple[int, bytes, dict]:
    setup = CASES[case][0]
    status, raw = _post(setup(monkeypatch, _evil(marker)))
    return status, raw, json.loads(raw.decode("utf-8"))


@pytest.mark.parametrize("case", list(CASES))
def test_the_reply_carries_no_exception_text(case, ctldir, monkeypatch, cap):
    _setup, want_status, want_action, keyed = CASES[case]
    status, raw, payload = _drive(monkeypatch, case, "RM824MARKA")

    assert status == want_status, payload
    assert payload["ok"] is False
    assert payload["action"] == want_action
    assert isinstance(payload["error"], str) and payload["error"]
    assert "see logs" in payload["error"], payload["error"]

    text = raw.decode("utf-8")
    for leak in ("RM824MARKA", "Example Repo", "slot0.json", "FAKE-LINE",
                 "Errno", "\\u001b", "\\r", "\\n"):
        assert leak not in text, (leak, text)
    for s in _strings(payload):
        assert not any(c in s for c in _CONTROL_CHARS), repr(s)

    if keyed:
        assert idem.seen(KEY) is None, "a 400/503 must not be replayable"

    # The raw cause is logged, and scrubbed: a WARNING carries the marker and
    # no record carries a raw control character.
    msgs = [r.getMessage() for r in cap.records]
    assert any("RM824MARKA" in m for r, m in zip(cap.records, msgs)
               if r.levelno >= logging.WARNING), msgs
    for m in msgs:
        assert not any(c in m for c in _CONTROL_CHARS), repr(m)


@pytest.mark.parametrize("case", list(CASES))
def test_the_reply_message_is_fixed_per_site(case, ctldir, monkeypatch):
    """A FIXED client message: two different exception texts, one reply."""
    _s1, _r1, first = _drive(monkeypatch, case, "RM824MARKA")
    idem.clear()
    armgate.clear()
    _s2, _r2, second = _drive(monkeypatch, case, "RM824MARKB")
    assert first["error"] == second["error"]
    assert first == second


def test_a_launch_fault_still_reports_the_lane_released(ctldir, monkeypatch):
    status, _raw, payload = _drive(monkeypatch, "fire_lane-launch-fault",
                                   "RM824MARKA")
    assert status == 503
    assert payload["released"] is True
    assert "launch failed" in payload["error"]


# --------------------------------------------------------------------------- source guard
_LOG_LEVELS = {"debug", "info", "warning", "warn", "error", "exception",
               "critical", "log"}
# Calls an exception may flow into without reaching a reply: the scrubbers,
# the RM-134 envelope, this module's fixed-message helper, and type() (only
# the class NAME, server text, can come out of it).
_SAFE_CALLS = {"scrub_log", "scrub_controls", "send_error", "_fault", "type",
               "isinstance"}
_REPLY_CALLS = {"_send", "_send_json", "send_json"}


def _reply_leaks(src: str) -> list[int]:
    """Lines where an except-bound name, or a name assigned from it (RM-837),
    reaches a reply shape - a dict literal, a ``return`` value or a ``_send``
    call - before any safe call. A log call is not a reply (its scrubbing is
    RM-811's guard). The walk lives in ``tests/_reply_leak_ast.py``."""
    return reply_leaks(src, safe_calls=_SAFE_CALLS, log_levels=_LOG_LEVELS,
                       reply_calls=_REPLY_CALLS)


def _swept_files() -> list[Path]:
    from tests._repo_walk import repo_files
    mc_files = repo_files(ROOT / "mc", ("*.py",))
    assert len(mc_files) >= 4, mc_files       # an empty walk must not pass
    return [ROOT / "dashboard" / "routes_loop_control.py",
            ROOT / "dashboard" / "routes_loop_status.py", *mc_files]


@pytest.mark.parametrize("path", _swept_files(),
                         ids=lambda p: p.relative_to(ROOT).as_posix())
def test_no_mc_reply_names_a_bound_exception(path):
    assert _reply_leaks(path.read_text(encoding="utf-8")) == [], path


def test_the_sweep_sees_the_loop_control_handlers():
    """Floor: the guard has except handlers to look at in the module RM-824
    fixed, so a rename that empties the walk cannot read as clean."""
    tree = ast.parse((ROOT / "dashboard" / "routes_loop_control.py")
                     .read_text(encoding="utf-8"))
    bound = [h for h in ast.walk(tree)
             if isinstance(h, ast.ExceptHandler) and h.name]
    assert len(bound) >= 10, len(bound)


def test_the_reply_detector_is_not_vacuous():
    """The detector flags the measured pre-fix shapes and passes the safe
    ones, line for line."""
    src = (
        "def f(h):\n"
        "    try:\n"
        "        pass\n"
        "    except ValueError as exc:\n"
        "        return 400, {'error': str(exc)}\n"                    # 5
        "    except OSError as exc:\n"
        "        return 503, {'error': f'launch failed: {exc}'}\n"     # 7
        "    except KeyError as err:\n"
        "        h._send(500, json.dumps({'e': repr(err)}), 'x')\n"   # 9
        "    except TypeError as e:\n"
        "        return e.args[0]\n"                                   # 11
        "    except RuntimeError as exc:\n"
        "        log.warning('x: %s', scrub_log(str(exc)))\n"
        "        if type(exc).__name__ != 'MutexTimeout':\n"
        "            raise\n"
        "        send_error(h, exc)\n"
        "        return _fault(503, 'steer', exc, 'busy - see logs')\n"
        "    except Exception as exc:\n"
        "        raise RuntimeError('wrapped') from exc\n"
    )
    assert _reply_leaks(src) == [5, 7, 9, 11]


def test_the_reply_detector_follows_an_assignment():
    """RM-837: a name assigned from the bound exception - directly, by a
    subscript store, an ``update`` call or an augmented assignment, or one
    hop further - is followed to the reply it reaches."""
    assert _reply_leaks(ASSIGNMENT_SHAPES) == [6, 12, 18, 24, 31]
    assert _reply_leaks(SAFE_ASSIGNMENTS) == []
