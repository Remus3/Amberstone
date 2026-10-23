"""RM-811: the MCP / Mission Control siblings of RM-769..RM-771.

Four shapes, each measured before the fix:

1. ``tools/usage-mcp-server.js`` (stdio MCP) EXITED 1 on a JSON ``null``
   line: ``const { id, method, params } = msg`` threw inside the async line
   handler, an unhandled rejection that ends the process (measured: a ping
   on the next line answered, then the TypeError and exit 1). It also
   dropped a parse error and a non-object request with no reply, routed a
   non-string ``method`` like a string, and answered a non-object
   ``tools/call`` params with an ordinary result.
2. ``mc/handler.py`` answered a body that is not JSON with 400 and logged
   nothing, so a client hammering the control plane left no trace; its
   500 paths logged the client's request target (and the exception text)
   unscrubbed - the RM-321 log-injection class.
3. ``tools/ds_matchdb_mcp_server.py`` logged ``notification: %s`` and
   ``handler %s raised: %s: %s`` with the client's method and the exception
   text unscrubbed (RM-321 class).
4. The same server answered a non-object ``tools/call`` params with -32603
   (Internal error: ``"x".get`` raised AttributeError); JSON-RPC 2.0 says a
   params value that is not a structured value is -32602 Invalid params.

THE FIX: replies by the spec (-32700 parse error and -32600 invalid request
with id null; -32600 for a non-string method; -32602 for non-object params),
the stdio server survives every line, and every client-derived log value
goes through ``core.log_scrub`` (or an equivalent escape in the JS).
"""
from __future__ import annotations

import contextlib
import http.server
import json
import logging
import os
import shutil
import socket
import subprocess
import threading
from pathlib import Path
from typing import Iterator

import pytest

ROOT = Path(__file__).resolve().parent.parent
USAGE_JS = ROOT / "tools" / "usage-mcp-server.js"
NODE = shutil.which("node")
_HOST = "127.0.0.1"
_CTRL = {chr(c) for c in range(0x00, 0x20)} | {chr(c) for c in range(0x7F, 0xA0)}


def _ctrl_in(text: str) -> list[str]:
    return sorted({hex(ord(c)) for c in text if c in _CTRL})


class _Cap(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextlib.contextmanager
def _captured(name: str) -> Iterator[_Cap]:
    lg = logging.getLogger(name)
    cap, prior = _Cap(), lg.level
    lg.addHandler(cap)
    lg.setLevel(logging.DEBUG)
    try:
        yield cap
    finally:
        lg.removeHandler(cap)
        lg.setLevel(prior)


# -- 1. the stdio usage MCP server -------------------------------------------

needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")

_PING = '{"jsonrpc":"2.0","id":99,"method":"ping"}'


def _usage(*lines: str, timeout: float = 30.0) -> tuple[int, list[dict], str]:
    """Run the stdio server over ``lines`` (stdin then EOF); return the exit
    code, every stdout reply parsed, and stderr. No line ever names the one
    tool that reaches the network (``query_usage``)."""
    env = dict(os.environ)
    env.pop("ANTHROPIC_USAGE_KEY", None)      # no key: nothing could be sent
    proc = subprocess.run(
        [NODE, str(USAGE_JS)], input="".join(f"{ln}\n" for ln in lines),
        capture_output=True, text=True, encoding="utf-8", timeout=timeout,
        cwd=str(ROOT), env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    replies = [json.loads(ln) for ln in proc.stdout.splitlines() if ln.strip()]
    return proc.returncode, replies, proc.stderr


def _by_id(replies: list[dict], rid) -> list[dict]:
    return [r for r in replies if r.get("id") == rid]


@needs_node
@pytest.mark.parametrize("line", ["null", "5", '"x"', "true", "[]", "[1]"],
                         ids=["null", "number", "string", "bool",
                              "empty-array", "array"])
def test_a_non_object_line_is_invalid_request_and_the_server_lives(line):
    code, replies, stderr = _usage(line, _PING)
    assert code == 0, f"the server exited {code}: {stderr[-400:]}"
    bad = _by_id(replies, None)
    assert [r["error"]["code"] for r in bad] == [-32600], replies
    assert _by_id(replies, 99) == [{"jsonrpc": "2.0", "id": 99, "result": {}}]


@needs_node
@pytest.mark.parametrize("line", ["{", "not json", '{"a":'])
def test_a_parse_error_is_answered_32700(line):
    code, replies, stderr = _usage(line, _PING)
    assert code == 0, stderr[-400:]
    bad = _by_id(replies, None)
    assert [r["error"]["code"] for r in bad] == [-32700], replies
    assert bad[0]["error"]["message"] == "Parse error"
    assert _by_id(replies, 99), "the next request was not answered"


@needs_node
@pytest.mark.parametrize("method", ["[1]", '{"a":1}', "7", "null"])
def test_a_non_string_method_is_invalid_request(method):
    code, replies, stderr = _usage(
        '{"jsonrpc":"2.0","id":3,"method":' + method + "}", _PING)
    assert code == 0, stderr[-400:]
    got = _by_id(replies, 3)
    assert [r["error"]["code"] for r in got] == [-32600], replies
    assert _by_id(replies, 99)


@needs_node
@pytest.mark.parametrize("params", ['"x"', "[1]", "5", "true", "[]"])
def test_non_object_tools_call_params_are_invalid_params(params):
    code, replies, stderr = _usage(
        '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":'
        + params + "}", _PING)
    assert code == 0, stderr[-400:]
    got = _by_id(replies, 4)
    assert len(got) == 1, replies
    assert got[0].get("error", {}).get("code") == -32602, got
    assert "result" not in got[0]


@needs_node
def test_the_unknown_tool_and_known_methods_still_answer():
    """Negative control: the ordinary shapes are untouched."""
    code, replies, _ = _usage(
        '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}',
        '{"jsonrpc":"2.0","method":"notifications/initialized"}',
        '{"jsonrpc":"2.0","id":2,"method":"tools/list"}',
        '{"jsonrpc":"2.0","id":5,"method":"tools/call",'
        '"params":{"name":"no_such_tool","arguments":{}}}',
        '{"jsonrpc":"2.0","id":6,"method":"nope"}',
        _PING)
    assert code == 0
    assert _by_id(replies, 1)[0]["result"]["serverInfo"]["name"] == "anthropic-usage"
    assert _by_id(replies, 2)[0]["result"]["tools"][0]["name"] == "query_usage"
    assert "Unknown tool" in _by_id(replies, 5)[0]["result"]["content"][0]["text"]
    assert _by_id(replies, 6)[0]["error"]["code"] == -32601
    assert len(replies) == 5, replies        # the notification got no reply


# -- 2. Mission Control -------------------------------------------------------

_MC_TOKEN = "rm811-test-token"


@pytest.fixture
def mc(monkeypatch):
    """The real mc Handler over a plain loopback server (the production
    server is TLS; the handler is what is under test)."""
    from mc import handler as mc_handler
    from mc import routes

    monkeypatch.setenv("RC_MC_TOKEN", _MC_TOKEN)
    srv = http.server.ThreadingHTTPServer((_HOST, 0), mc_handler.Handler)
    srv.daemon_threads = True
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield srv.server_address[1], routes
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=5)


def _raw(port: int, payload: bytes) -> bytes:
    buf = b""
    with socket.create_connection((_HOST, port), timeout=8) as s:
        s.sendall(payload)
        while True:
            try:
                chunk = s.recv(65536)
            except (ConnectionResetError, ConnectionAbortedError):
                break
            if not chunk:
                break
            buf += chunk
    return buf


def _status(reply: bytes) -> int:
    return int(reply.split(b"\r\n", 1)[0].split(b" ")[1])


def _mc_post(port: int, path: bytes, body: bytes) -> bytes:
    return _raw(port, b"POST " + path + b" HTTP/1.0\r\nHost: 127.0.0.1\r\n"
                b"Authorization: Bearer " + _MC_TOKEN.encode() + b"\r\n"
                b"Content-Type: application/json\r\n"
                b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n"
                + body)


@pytest.mark.parametrize("body", [b"{x", b"[" * 100000, b"1" * 5000],
                         ids=["malformed", "deep", "5000-digits"])
def test_mc_logs_a_bad_json_body(mc, body):
    port, _routes = mc
    with _captured("rc.mc.handler") as cap:
        reply = _mc_post(port, b"/api/loop-control", body)
    assert _status(reply) == 400, reply[:200]
    warned = [r.getMessage() for r in cap.records if r.levelno >= logging.WARNING]
    assert any("invalid JSON" in m and "/api/loop-control" in m
               and _HOST in m for m in warned), warned


def test_mc_bad_json_log_is_scrubbed(mc):
    port, _routes = mc
    with _captured("rc.mc.handler") as cap:
        reply = _mc_post(port, b"/api/\x1b[31mFAKE\x7f", b"{x")
    assert _status(reply) == 400, reply[:200]
    msgs = [r.getMessage() for r in cap.records]
    warned = [r.getMessage() for r in cap.records if r.levelno >= logging.WARNING]
    assert any("FAKE" in m for m in warned), warned   # the bad-JSON line
    for m in msgs:
        assert _ctrl_in(m) == [], m


@pytest.mark.parametrize("verb", ["GET", "POST"])
def test_mc_500_log_scrubs_the_target_and_the_exception(mc, monkeypatch, verb):
    port, routes = mc

    def _boom(*_a):
        raise ValueError("route blew up \x1b[31mINJECTED\nFAKE-LINE")

    monkeypatch.setattr(routes, "GET_ROUTES", [(lambda p: True, _boom)])
    monkeypatch.setattr(routes, "POST_ROUTES", [(lambda p: True, _boom)])
    with _captured("rc.mc.handler") as cap:
        if verb == "GET":
            reply = _raw(port, b"GET /api/\x1b[31mX HTTP/1.0\r\n"
                         b"Host: 127.0.0.1\r\n\r\n")
        else:
            reply = _mc_post(port, b"/api/\x1b[31mX", b"{}")
    assert _status(reply) == 500, reply[:200]
    assert b"INJECTED" not in reply           # the reply stays fixed
    msgs = [r.getMessage() for r in cap.records if r.levelno >= logging.WARNING]
    assert any("INJECTED" in m for m in msgs), msgs
    for m in msgs:
        assert _ctrl_in(m) == [], m


# -- 3 + 4. the DS + match-DB MCP server -----------------------------------------

@pytest.fixture
def matchdb():
    import tools.ds_matchdb_mcp_server as mod
    srv = mod._MatchDBHTTPServer((_HOST, 0), mod._Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield srv.server_address[1], mod
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=5)


def _rpc(port: int, mod, req) -> tuple[int, dict | None]:
    body = (req if isinstance(req, bytes)
            else json.dumps(req).encode("utf-8"))
    reply = _raw(port, b"POST /mcp HTTP/1.0\r\nHost: 127.0.0.1\r\n"
                 b"Authorization: Bearer " + mod.AUTH_TOKEN.encode() + b"\r\n"
                 b"Content-Type: application/json\r\n"
                 b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n"
                 + body)
    head, _, payload = reply.partition(b"\r\n\r\n")
    status = _status(head)
    return status, (json.loads(payload) if payload else None)


def test_matchdb_notification_log_is_scrubbed(matchdb):
    port, mod = matchdb
    with _captured("ds-matchdb-mcp") as cap:
        status, _ = _rpc(port, mod, {
            "jsonrpc": "2.0",
            "method": "notifications/x\x1b[31mFAKE\nINJECTED-LINE\x7f"})
    assert status == 202
    msgs = [r.getMessage() for r in cap.records if "notification" in r.getMessage()]
    assert msgs and any("INJECTED-LINE" in m for m in msgs), msgs
    for m in msgs:
        assert _ctrl_in(m) == [], m


def test_matchdb_handler_raised_log_is_scrubbed(matchdb, monkeypatch):
    port, mod = matchdb

    def _boom(_params):
        raise ValueError("client said \x1b[31mINJECTED\nFAKE-LINE")

    monkeypatch.setitem(mod.METHOD_HANDLERS, "ping", _boom)
    with _captured("ds-matchdb-mcp") as cap:
        status, reply = _rpc(port, mod,
                             {"jsonrpc": "2.0", "id": 7, "method": "ping"})
    assert status == 200 and reply["error"]["code"] == -32603, reply
    assert "INJECTED" not in json.dumps(reply)
    msgs = [r.getMessage() for r in cap.records if "raised" in r.getMessage()]
    assert msgs and any("INJECTED" in m for m in msgs), msgs
    for m in msgs:
        assert _ctrl_in(m) == [], m


def test_matchdb_parse_error_log_is_scrubbed(matchdb):
    port, mod = matchdb
    with _captured("ds-matchdb-mcp") as cap:
        status, reply = _rpc(port, mod, b"\xff\x1b[31m{")
    assert status == 200 and reply["error"]["code"] == -32700, reply
    msgs = [r.getMessage() for r in cap.records if "parse error" in r.getMessage()]
    assert msgs, [r.getMessage() for r in cap.records]
    for m in msgs:
        assert _ctrl_in(m) == [], m


@pytest.mark.parametrize("params", ["x", [1], 5, True, [], 0, ""],
                         ids=["string", "array", "number", "bool",
                              "empty-array", "zero", "empty-string"])
@pytest.mark.parametrize("method", ["tools/call", "initialize", "tools/list",
                                    "ping"])
def test_matchdb_non_object_params_are_invalid_params(matchdb, method, params):
    port, mod = matchdb
    status, reply = _rpc(port, mod, {"jsonrpc": "2.0", "id": 8,
                                     "method": method, "params": params})
    assert status == 200
    assert reply.get("id") == 8, reply
    assert reply.get("error", {}).get("code") == -32602, reply
    assert "result" not in reply


@pytest.mark.parametrize("req", [
    {"jsonrpc": "2.0", "id": 9, "method": "ping"},
    {"jsonrpc": "2.0", "id": 9, "method": "ping", "params": None},
    {"jsonrpc": "2.0", "id": 9, "method": "ping", "params": {}},
], ids=["omitted", "null", "object"])
def test_matchdb_omitted_null_or_object_params_still_answer(matchdb, req):
    """Negative control: an omitted (or null) params is the empty object."""
    port, mod = matchdb
    status, reply = _rpc(port, mod, req)
    assert status == 200 and reply == {"jsonrpc": "2.0", "id": 9, "result": {}}


def test_matchdb_unknown_method_with_bad_params_is_still_method_not_found(
        matchdb):
    port, mod = matchdb
    status, reply = _rpc(port, mod, {"jsonrpc": "2.0", "id": 10,
                                     "method": "nope", "params": "x"})
    assert reply["error"]["code"] == -32601, reply
