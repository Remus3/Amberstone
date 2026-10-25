# arch: RM-853 - the /api/task/<id> reply's last_error never carries exception text | section=tests | frozen=no
"""RM-853: a supervisor task's raw exception text never reaches the
``/api/task/<id>`` reply as ``last_error``.

Measured at main 17ae75595, before the fix: ``agents/supervisor.py``
``_dispatch_loop`` called ``self._scheduler.fail(task.id, error=str(e))`` for
any dispatch exception (and ``_run_deterministic`` inlines the cause into the
message it re-raises for ``game-summary`` and ``ui-proposal``);
``agents/agent1_lead/scheduler.py`` ``fail`` stores it as ``last_error`` and
persists it to ``task_queue.jsonl``; ``agents/_supervisor_http.py``
``_handle_task_detail`` served it verbatim, and the :8888 dashboard proxies
``/api/task`` (a 2xx passthrough). The dispatcher also logged the cause
through ``log.exception``, raw (the supervisor logger has no scrub filter).

Decision (recorded in the commit and the LEDGER entry): BOTH halves. The
dispatcher stores a fixed line and logs the cause once, scrubbed, with its
type name and traceback; the reply maps ``last_error`` through
``_supervisor_http.public_last_error`` - a server-authored reason passes, an
agent0 rejection becomes its stable ``agent0:<code>:<label>`` code, anything
else becomes the fixed line. Why both: the writer fix alone leaves the rows a
pre-fix supervisor already persisted (replayed into the store on every
restart) and the agent0 rejection text (which embeds the filer's
``remote_path``) on the wire; the reply mapping alone leaves raw, unscrubbed
exception text in the persisted store. Backfilling the live store was the
rejected alternative: it is a live-state write, and the reply mapping covers
the old rows without one.

Each dispatch case drives the real ``_dispatch_loop`` with an exception whose
text carries a marker, a filesystem path and control characters, then serves
the stored task through the real ``_handle_task_detail``.
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import json
import logging
from pathlib import Path

import pytest

from tests._asyncio_isolation import run_coro

ROOT = Path(__file__).resolve().parents[1]
SECRET_PATH = r"C:\Example Repo\data\secret_rm853.db"
_CONTROL_CHARS = ("\x1b", "\r", "\x85", "\x7f")
_LEAKS = ("Example Repo", "secret_rm853", "FAKE-LINE", "Errno",
          "\\u001b", "\\r", "\\n", "\\u0085", "\\u007f")


def _evil(marker: str) -> str:
    """Text with a marker, a filesystem path and control characters."""
    return f"{marker} at {SECRET_PATH} \x1b[31m\r\nFAKE-LINE\x85\x7f"


def _assert_clean(raw: str, *markers: str) -> None:
    for needle in (*_LEAKS, *markers):
        assert needle not in raw, f"reply leaks {needle!r}: {raw!r}"
    for ch in _CONTROL_CHARS:
        assert ch not in raw, f"reply carries control char {ch!r}"


class _Cap(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def capture():
    """Attach a capturing handler to a named logger, isolated from its real
    handlers (the supervisor logger writes files) and from its filters, so a
    filter can never mask a call site that stopped scrubbing."""
    attached: list[tuple[logging.Logger, list, list, bool, int]] = []

    def _attach(name: str) -> _Cap:
        lg = logging.getLogger(name)
        attached.append((lg, list(lg.handlers), list(lg.filters),
                         lg.propagate, lg.level))
        cap = _Cap()
        lg.handlers = [cap]
        lg.filters = []
        lg.propagate = False
        lg.setLevel(logging.DEBUG)
        return cap

    try:
        yield _attach
    finally:
        for lg, handlers, filters, propagate, level in attached:
            lg.handlers = handlers
            lg.filters = filters
            lg.propagate = propagate
            lg.setLevel(level)


class _MockHandler:
    """Just enough of the request handler for ``_handle_task_detail``."""

    def __init__(self, path: str, scheduler) -> None:
        self.path = path
        self.command = "GET"
        self.server = type("S", (), {})()
        self.server.supervisor = type("Sup", (), {})()
        self.server.supervisor.scheduler = scheduler
        self.responses: list[tuple[int, dict]] = []

    def _send_json(self, status: int, body: dict) -> None:
        self.responses.append((status, body))


def _reply(scheduler, task_id: str) -> dict:
    from agents._supervisor_http import _QuietHandler
    h = _MockHandler(f"/api/task/{task_id}", scheduler)
    _QuietHandler._handle_task_detail.__get__(h)()
    assert len(h.responses) == 1
    status, body = h.responses[0]
    assert status == 200
    # The wire form: what the :8888 proxy forwards as a 2xx body.
    json.dumps(body)
    return body


def _scheduler(tmp_path: Path, **kw):
    from agents.agent1_lead.scheduler import Scheduler
    return Scheduler(queue_log=tmp_path / "task_queue.jsonl", **kw)


def _dispatch_once(sup_mod, sched) -> None:
    """Run the real ``_dispatch_loop`` until the one ready task reaches a
    terminal event (or the queue is empty), then stop it."""
    sup = sup_mod.Supervisor.__new__(sup_mod.Supervisor)
    sup._stop = asyncio.Event()
    sup._scheduler = sched
    sup.cross_machine_enabled = True
    sup._warm_agent7 = None
    sup._warm_agent7_alive = False
    real_next, real_fail, real_complete = (sched.next_ready, sched.fail,
                                           sched.complete)

    def _next():
        t = real_next()
        if t is None:
            sup._stop.set()
        return t

    def _fail(task_id, error):
        try:
            return real_fail(task_id, error=error)
        finally:
            sup._stop.set()

    def _complete(task_id, result=None):
        try:
            return real_complete(task_id, result=result)
        finally:
            sup._stop.set()

    sched.next_ready, sched.fail, sched.complete = _next, _fail, _complete
    run_coro(sup._dispatch_loop(), timeout=30)


# --------------------------------------------- the three dispatch raise sites
def _spawn_raiser(monkeypatch, sup_mod, exc):
    def _raise(*_a, **_k):
        raise exc
    monkeypatch.setattr(sup_mod, "spawn_ephemeral_llm", _raise)
    return "4", "audit-pass"


def _ingest_raiser(monkeypatch, sup_mod, exc):
    import agents.agent2_backend.game_ingest as gi

    def _raise(_payload):
        raise gi.IngestError(str(exc))
    monkeypatch.setattr(gi, "ingest_game_summary", _raise)
    return "1", "game-summary"


def _ui_raiser(monkeypatch, sup_mod, exc):
    import agents.agent4_coach_mentor.ui_applier as ua

    def _raise(_payload):
        raise ua.UIApplyError(str(exc))
    monkeypatch.setattr(ua, "apply_ui_proposal", _raise)
    return "1", "ui-proposal"


_SITES = {
    "dispatch-raise": _spawn_raiser,       # supervisor.py _dispatch_loop
    "game-summary": _ingest_raiser,        # the re-raise with the cause inlined
    "ui-proposal": _ui_raiser,             # the re-raise with the cause inlined
}


def _fail_through_dispatch(monkeypatch, tmp_path, site, exc):
    import agents.supervisor as sup_mod
    monkeypatch.setattr(sup_mod, "LOG_ROOT", tmp_path)
    owner, op = _SITES[site](monkeypatch, sup_mod, exc)
    sched = _scheduler(tmp_path)
    task = sched.file_task(op=op, owner_agent=owner, payload={"k": "v"})
    _dispatch_once(sup_mod, sched)
    assert sched.get(task.id).status == "failed", "the task must fail"
    return sched, task.id


@pytest.mark.parametrize("site", sorted(_SITES))
def test_a_dispatch_failure_reply_never_carries_the_exception_text(
        site, monkeypatch, tmp_path):
    from agents._supervisor_http import TASK_FAILED_ERROR
    marker = f"MARKER-{site.upper()}"
    sched, tid = _fail_through_dispatch(monkeypatch, tmp_path, site,
                                        RuntimeError(_evil(marker)))
    body = _reply(sched, tid)
    assert body["last_error"] == TASK_FAILED_ERROR
    _assert_clean(json.dumps(body), marker)


@pytest.mark.parametrize("site", sorted(_SITES))
def test_a_dispatch_failure_never_persists_the_exception_text(
        site, monkeypatch, tmp_path):
    """The writer half: the task store (and its jsonl, replayed on every
    supervisor restart) holds the fixed line, not the cause."""
    from agents._supervisor_http import TASK_FAILED_ERROR
    marker = f"STORED-{site.upper()}"
    sched, tid = _fail_through_dispatch(monkeypatch, tmp_path, site,
                                        RuntimeError(_evil(marker)))
    assert sched.get(tid).last_error == TASK_FAILED_ERROR
    stored = (tmp_path / "task_queue.jsonl").read_text(encoding="utf-8")
    _assert_clean(stored, marker)


def test_two_different_exceptions_yield_identical_replies(monkeypatch,
                                                         tmp_path):
    volatile = {"id", "created_at", "updated_at", "events"}
    bodies = []
    for i, exc in enumerate((OSError(5, _evil("FIRST-TEXT"), SECRET_PATH),
                             ValueError(_evil("SECOND-TEXT")))):
        sub = tmp_path / f"run{i}"
        sub.mkdir()
        sched, tid = _fail_through_dispatch(monkeypatch, sub,
                                            "dispatch-raise", exc)
        body = _reply(sched, tid)
        bodies.append({k: v for k, v in body.items() if k not in volatile})
    assert bodies[0] == bodies[1], "the reply must not depend on the cause"


def test_the_cause_is_logged_once_scrubbed_with_its_type(monkeypatch,
                                                        tmp_path, capture):
    import agents.supervisor as sup_mod
    cap = capture(sup_mod.log.name)
    marker = "LOGGED-CAUSE"
    # Not KeyError: its str() is the repr of the key, which escapes the
    # control characters by itself and would hide an unscrubbed call site.
    _sched, tid = _fail_through_dispatch(monkeypatch, tmp_path,
                                         "dispatch-raise",
                                         LookupError(_evil(marker)))
    hits = [r for r in cap.records if marker in r.getMessage()]
    assert len(hits) == 1, "the cause is logged exactly once"
    rec = hits[0]
    text = rec.getMessage()
    assert tid in text and "LookupError" in text
    assert "Traceback" in text, "the traceback rides on the one line"
    for ch in _CONTROL_CHARS + ("\n",):
        assert ch not in text, f"the logged cause carries {ch!r}"
    # A raw exc_info would be rendered unscrubbed by the file handlers.
    assert rec.exc_info is None
    assert rec.levelno >= logging.ERROR


# ------------------------------------------------------- the reply boundary
def test_a_row_persisted_before_the_fix_is_served_fixed(tmp_path):
    """A pre-fix supervisor stored ``str(e)``; that row is replayed from
    ``task_queue.jsonl`` into a fresh store and must still serve fixed."""
    from agents._supervisor_http import TASK_FAILED_ERROR
    old = _scheduler(tmp_path)
    t = old.file_task(op="audit-pass", owner_agent="4")
    old.fail(t.id, error=_evil("PRE-FIX-ROW"))
    replayed = _scheduler(tmp_path)
    assert "PRE-FIX-ROW" in (replayed.get(t.id).last_error or "")
    body = _reply(replayed, t.id)
    assert body["last_error"] == TASK_FAILED_ERROR
    _assert_clean(json.dumps(body), "PRE-FIX-ROW")


def test_an_agent0_rejection_serves_its_stable_code_only(tmp_path):
    """``scheduler.py`` stores ``agent0:<code>:<label>:<message>`` and the
    message embeds the filer's ``remote_path``; the reply keeps the code."""
    from agents.agent0_gatekeeper.evaluator import Decision, Rejection
    evil_path = _evil("AGENT0-PATH")

    def _evaluate(a0_task):
        return Decision(accepted=False, task=a0_task, rejection=Rejection(
            reason_code=3, reason_label="destination_traversal",
            message=f"path contains traversal segment: {a0_task.remote_path}",
            disposition="dead_letter"))

    sched = _scheduler(tmp_path, agent0_evaluate=_evaluate)
    # Category 5 routes the task through agent0 review at filing time, so
    # the real writer (scheduler.py _agent0_review) stores the rejection.
    t = sched.file_task(op="push-file", owner_agent="2", categories=[5],
                        payload={"remote_path": evil_path})
    assert "AGENT0-PATH" in sched.get(t.id).last_error
    body = _reply(sched, t.id)
    assert body["last_error"] == "agent0:3:destination_traversal"
    _assert_clean(json.dumps(body["last_error"]), "AGENT0-PATH")


def _server_reasons() -> list[str]:
    from agents.agent1_lead import scheduler as sch
    reasons = [sch._RECONCILE_TIMEOUT_REASON, sch._GATE_LIMBO_REASON,
               inspect.signature(sch.Scheduler.deny)
               .parameters["reason"].default]
    # Every reason= string literal the supervisor passes to the scheduler.
    tree = ast.parse((ROOT / "agents" / "supervisor.py")
                     .read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if (kw.arg == "reason" and isinstance(kw.value, ast.Constant)
                        and isinstance(kw.value.value, str)):
                    reasons.append(kw.value.value)
    return reasons


def test_the_server_reason_census_is_not_vacuous():
    reasons = _server_reasons()
    assert "supervisor-restart" in reasons
    assert "supervisor-restart-gate-limbo" in reasons
    assert len(set(reasons)) >= 5


@pytest.mark.parametrize("reason", sorted(set(_server_reasons())))
def test_a_server_authored_reason_still_reaches_the_reply(reason, tmp_path):
    sched = _scheduler(tmp_path)
    t = sched.file_task(op="audit-pass", owner_agent="4")
    sched.fail(t.id, error=reason)
    assert _reply(sched, t.id)["last_error"] == reason


@pytest.mark.parametrize("stored", [
    {"error": "DICT-ROW"}, ["LIST-ROW"], 7,
    "agent0:3:Destination_Traversal:mixed-case label",
    "agent0:x:label:no numeric code",
    "boom",
])
def test_anything_else_is_served_as_the_fixed_line(stored, tmp_path):
    from agents._supervisor_http import TASK_FAILED_ERROR
    sched = _scheduler(tmp_path)
    t = sched.file_task(op="audit-pass", owner_agent="4")
    sched.get(t.id).last_error = stored
    assert _reply(sched, t.id)["last_error"] == TASK_FAILED_ERROR


def test_a_task_without_an_error_still_serves_null(tmp_path):
    sched = _scheduler(tmp_path)
    t = sched.file_task(op="audit-pass", owner_agent="4")
    assert _reply(sched, t.id)["last_error"] is None


# ---------------------------------------------------- RM-863 (d) exact match
def _public_reasons() -> list[str]:
    from agents._supervisor_http import _PUBLIC_TASK_ERRORS
    return sorted(_PUBLIC_TASK_ERRORS)


def _near_misses(reason: str) -> list[str]:
    """A server reason with other text around it - none of these may pass."""
    return [reason + " " + _evil("SUFFIXED"), reason + "x",
            _evil("PREFIXED") + " " + reason, " " + reason, reason + "\n",
            reason.upper()]


@pytest.mark.parametrize("reason", _public_reasons())
def test_a_server_reason_passes_only_on_an_exact_match(reason, tmp_path):
    """RM-863 (d): ``public_last_error`` passes a stored reason only when it
    EQUALS a server-authored one. A prefix-match mutant (``startswith``
    instead of the set lookup) survived every RM-853 test above: a row
    stored as ``<reason>: <exception text>`` would have reached the wire."""
    from agents._supervisor_http import TASK_FAILED_ERROR, public_last_error
    assert public_last_error(reason) == reason
    for stored in _near_misses(reason):
        assert public_last_error(stored) == TASK_FAILED_ERROR, stored
    # And through the real reply, from the store.
    sched = _scheduler(tmp_path)
    t = sched.file_task(op="audit-pass", owner_agent="4")
    sched.fail(t.id, error=reason + ": " + _evil("THROUGH-REPLY"))
    body = _reply(sched, t.id)
    assert body["last_error"] == TASK_FAILED_ERROR
    _assert_clean(json.dumps(body), "THROUGH-REPLY")


def test_the_exact_match_census_is_not_vacuous():
    from agents._supervisor_http import TASK_FAILED_ERROR
    reasons = _public_reasons()
    assert len(reasons) >= 6, reasons
    assert TASK_FAILED_ERROR in reasons
