"""RM-753: the :8890 Phase 3 supervisor server's JSON body parse and its
state-changing POSTs - two siblings of the ws_server.py weaknesses fixed by
the lane 8 true-audit (LEDGER 1740).

(a) THE PARSE: ``_handle_input``, ``_handle_file_task`` and ``_handle_analyze``
caught ``json.JSONDecodeError`` only. A non-UTF-8 body (``UnicodeDecodeError``
- a ``ValueError``, not a ``JSONDecodeError``) and a deeply nested one
(``RecursionError``) escaped the handler, and a non-object body such as
``[]`` reached ``.get`` and raised ``AttributeError``: the connection was
dropped with no reply. Now each is a 400 with a generic message.

(b) THE ORIGIN: ``do_POST`` checked no ``Origin``, so a cross-site simple
POST (``text/plain``, no preflight) from any page open in a browser on this
machine reached the task dispatcher. Now a foreign ``Origin`` / ``Referer``
is a 403 before any route runs, by the same rule the :8888 dashboard applies
(``dashboard/_handler.py`` ``_csrf_ok``, shared as ``_same_origin_ok``):
no-Origin script callers and same-host / loopback origins pass.

Every case runs the production ``_WebServer`` + ``_QuietHandler`` on an
ephemeral loopback port with a recording stub supervisor, so a test can
tell "refused before dispatch" from "dispatched".
"""
from __future__ import annotations

import contextlib
import json
import socket
import threading
import types
from pathlib import Path

import pytest

from agents._supervisor_http import _QuietHandler, _WebServer

_HOST = "127.0.0.1"
_CLOSED = (ConnectionResetError, ConnectionAbortedError)
_PARSE_ROUTES = ("/api/input", "/api/file-task", "/api/analyze")
_STATE_ROUTES = ("/api/input", "/api/file-task", "/api/analyze",
                 "/api/task/t-1/dismiss")


class _Scheduler:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def file_task(self, **kw):
        self.calls.append(("file_task", kw))
        return types.SimpleNamespace(
            id="t-rm753", status="pending", priority=kw["priority"],
            owner_agent=kw["owner_agent"], op=kw["op"],
            categories=kw["categories"], payload={})

    def get(self, task_id):
        self.calls.append(("get", task_id))
        return None

    def __getattr__(self, name):            # anything else is a dispatch too
        def _rec(*a, **kw):
            self.calls.append((name, a, kw))
            raise RuntimeError(f"unexpected dispatch {name}")
        return _rec


class _Supervisor:
    def __init__(self) -> None:
        self.scheduler = _Scheduler()
        self.warm_agent7 = None


@pytest.fixture(autouse=True)
def no_real_work(monkeypatch):
    """Nothing here may start an analysis or an LLM spawn, even on a
    pre-fix tree where the guard is missing: both are replaced by stubs
    that fail loudly if reached."""
    import agents._supervisor_http as mod
    import agents.agent4_coach_mentor as mentor

    def _refuse(*_a, **_kw):
        raise AssertionError("real work dispatched (RM-753 test)")

    monkeypatch.setattr(mod, "spawn_ephemeral_llm", _refuse)
    monkeypatch.setattr(mentor, "analyze_all", _refuse)
    monkeypatch.setattr(mentor, "analyze_mode", _refuse)


@pytest.fixture
def served(tmp_path: Path):
    root = tmp_path / "webroot"
    root.mkdir()
    (root / "ok.txt").write_bytes(b"public\n")
    srv = _WebServer((_HOST, 0),
                     lambda *a, **kw: _QuietHandler(*a, directory=str(root), **kw))
    srv.supervisor = _Supervisor()
    serve = threading.Thread(target=srv.serve_forever, daemon=True,
                             name="rm753-serve")
    serve.start()
    try:
        yield srv
    finally:
        stopper = threading.Thread(target=srv.shutdown, daemon=True)
        stopper.start()
        stopper.join(timeout=2)
        srv.server_close()
        serve.join(timeout=2)


def _request(srv, method: str, path: str, body: bytes = b"",
             headers: dict | None = None) -> tuple[int | None, bytes]:
    """One raw HTTP/1.0 request. Returns (status, body); status None means
    the server dropped the connection without a reply."""
    port = srv.server_address[1]
    hdrs = {"Host": f"{_HOST}:{port}"}
    hdrs.update(headers or {})
    if method == "POST":
        hdrs.setdefault("Content-Type", "application/json")
        hdrs["Content-Length"] = str(len(body))
    head = f"{method} {path} HTTP/1.0\r\n" + "".join(
        f"{k}: {v}\r\n" for k, v in hdrs.items() if v is not None) + "\r\n"
    buf = b""
    with socket.create_connection((_HOST, port), timeout=10) as s:
        s.sendall(head.encode("latin-1") + body)
        while True:
            try:
                chunk = s.recv(65536)
            except _CLOSED:
                break
            if not chunk:
                break
            buf += chunk
    if not buf.startswith(b"HTTP/"):
        return None, buf
    status_line, _, rest = buf.partition(b"\r\n")
    return int(status_line.split(b" ")[1]), rest.partition(b"\r\n\r\n")[2]


def _still_serving(srv) -> None:
    status, payload = _request(srv, "GET", "/ok.txt")
    assert (status, payload) == (200, b"public\n"), (status, payload[:80])


# -- (a) the JSON body parse ----------------------------------------------------

_BAD_BODIES = {
    "invalid_utf8": b'{"text": "\xff\xfe", "op": "x", "owner_agent": "1"}',
    "deep_nesting": b"[" * 100_000 + b"]" * 100_000,
    "non_object_list": b"[]",
    "non_object_scalar": b"42",
    "non_object_string": b'"text"',
}


@pytest.mark.parametrize("route", _PARSE_ROUTES)
@pytest.mark.parametrize("kind", sorted(_BAD_BODIES))
def test_a_bad_json_body_is_a_400_and_the_handler_survives(served, route, kind):
    status, payload = _request(served, "POST", route, _BAD_BODIES[kind])
    assert status == 400, (
        f"{route} {kind}: expected 400, got {status} "
        f"({'connection dropped with no reply' if status is None else payload[:80]!r})")
    err = json.loads(payload)["error"]
    assert "JSON" in err, err
    # Generic message only: no exception text on the wire.
    assert "Error" not in err and "line" not in err, err
    assert served.supervisor.scheduler.calls == [], served.supervisor.scheduler.calls
    _still_serving(served)


@pytest.mark.parametrize("route,body,field", [
    ("/api/input", b'{"text": 5}', "text"),
    ("/api/input", b'{"text": ["a"]}', "text"),
    ("/api/input", b'{"text": "hi", "sim_fixture": {"a": 1}}', "sim_fixture"),
    ("/api/file-task", b'{"op": 7, "owner_agent": "6"}', "op"),
    ("/api/analyze", b'{"mode": 1}', "mode"),
])
def test_a_non_string_text_field_is_a_400_not_a_dropped_connection(
        served, route, body, field):
    """Sibling sweep, same root cause one level down: a truthy non-string
    reached ``.strip()`` and raised AttributeError (connection dropped)."""
    status, payload = _request(served, "POST", route, body)
    assert status == 400, (route, status, payload[:80])
    assert json.loads(payload) == {"error": f"'{field}' must be a string"}
    assert served.supervisor.scheduler.calls == []
    _still_serving(served)


def test_malformed_json_is_still_a_400_on_input_and_file_task(served):
    for route in ("/api/input", "/api/file-task"):
        status, payload = _request(served, "POST", route, b"{bad")
        assert (status, json.loads(payload)) == (400, {"error": "malformed JSON body"})


def test_malformed_json_on_analyze_is_a_400_not_an_all_mode_run(served):
    """Decision (RM-753): analyze used to read a JSONDecodeError as "no
    body" and run EVERY mode; a garbage body is now a 400 like the other
    two parse sites, so an undecodable request never starts work."""
    status, payload = _request(served, "POST", "/api/analyze", b"{bad")
    assert status == 400, (status, payload[:80])


def test_a_valid_object_body_still_reaches_the_route(served):
    body = json.dumps({"op": "rm753-op", "owner_agent": "6"}).encode()
    status, payload = _request(served, "POST", "/api/file-task", body)
    assert status == 200, payload[:120]
    assert json.loads(payload)["id"] == "t-rm753"
    assert [c[0] for c in served.supervisor.scheduler.calls] == ["file_task"]


# -- (b) the Origin guard on the state-changing POSTs ----------------------------

_FOREIGN = {
    "foreign_origin": {"Origin": "https://evil.example"},
    "null_origin": {"Origin": "null"},
    "foreign_referer": {"Referer": "https://evil.example/page.html"},
    "foreign_origin_loopback_referer": {
        "Origin": "https://evil.example",
        "Referer": "http://127.0.0.1:8890/index.html"},
}


# Bodies that are harmless if a pre-fix tree dispatches them (no LLM spawn,
# no analysis run): the guard must refuse them all the same.
_HARMLESS = {
    "/api/input": b"{}",
    "/api/file-task": b'{"op": "rm753-op", "owner_agent": "6"}',
    "/api/analyze": b"[]",
    "/api/task/t-1/dismiss": b"",
}


@pytest.mark.parametrize("route", _STATE_ROUTES)
@pytest.mark.parametrize("kind", sorted(_FOREIGN))
def test_a_cross_origin_post_is_refused_before_dispatch(served, route, kind):
    # The cross-site simple-request shape: text/plain needs no preflight.
    headers = dict(_FOREIGN[kind], **{"Content-Type": "text/plain"})
    status, payload = _request(served, "POST", route, _HARMLESS[route], headers)
    assert status == 403, (route, kind, status, payload[:80])
    assert json.loads(payload) == {"error": "cross_origin"}
    assert served.supervisor.scheduler.calls == [], served.supervisor.scheduler.calls


def _file_task_status(served, headers: dict) -> int | None:
    body = json.dumps({"op": "rm753-op", "owner_agent": "6"}).encode()
    status, _ = _request(served, "POST", "/api/file-task", body, headers)
    return status


def test_a_script_caller_with_no_origin_passes(served):
    assert _file_task_status(served, {}) == 200
    assert [c[0] for c in served.supervisor.scheduler.calls] == ["file_task"]


def test_a_same_host_page_passes(served):
    port = served.server_address[1]
    origin = f"http://{_HOST}:{port}"
    assert _file_task_status(served, {"Origin": origin,
                                      "Referer": origin + "/index.html"}) == 200


@pytest.mark.parametrize("origin", ["http://localhost:8888",
                                    "https://127.0.0.1:8888",
                                    "http://[::1]:8890"])
def test_a_loopback_origin_passes(served, origin):
    assert _file_task_status(served, {"Origin": origin}) == 200


def test_the_dismiss_route_passes_the_guard_for_a_script_caller(served):
    status, payload = _request(served, "POST", "/api/task/t-1/dismiss")
    assert (status, json.loads(payload)) == (404, {"error": "task not found"})
    assert served.supervisor.scheduler.calls == [("get", "t-1")]


def test_get_routes_are_not_origin_gated(served):
    """Reads stay open to a cross-origin page exactly as before: the guard
    is on state-changing POSTs only (a GET is not a CSRF write)."""
    status, payload = _request(served, "GET", "/ok.txt",
                               headers={"Origin": "https://evil.example"})
    assert (status, payload) == (200, b"public\n")
