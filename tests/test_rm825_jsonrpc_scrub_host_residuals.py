"""RM-825: JSON-RPC, scrub and Host-gate residuals of RM-811 / RM-819.

Five shapes, each measured red on the base before the fix:

(a) ``tools/usage-mcp-server.js`` answered a NOTIFICATION (a request object
    with no ``id`` member): ``initialize``, ``ping``, ``tools/list`` and
    ``tools/call`` each sent a reply with the id absent. JSON-RPC 2.0
    section 4.1: the server MUST NOT reply to a notification. Kept on
    purpose (decision, not a miss): a non-string ``method`` with no id is
    still answered -32600 with id null - that object is not a valid Request,
    so it is not a notification either, and the spec's own section 7 example
    (``{"jsonrpc": "2.0", "method": 1, "params": "bar"}``) is answered
    exactly so. ``tools/ds_matchdb_mcp_server.py`` already behaves this way
    (202 with no body for a notification, -32600 id null for a non-string
    method), so the two servers now agree.
(b) A numeric id beyond 2^53 lost precision in ``JSON.parse``: the reply
    echoed a DIFFERENT id (9007199254740993 came back as ...992). DECISION:
    an integer-valued id outside ``Number.isSafeInteger`` is refused
    -32600 with id null, before any work. 2^53 itself is refused too: it
    cannot be told apart from 2^53 + 1 once parsed. A fractional id is
    never above 2^53 (every double there is an integer) and is still
    echoed. ACCEPTED residue: a fraction with more digits than a double
    holds (0.30000000000000001) is still echoed rounded (0.3) - JSON-RPC
    says ids SHOULD NOT carry fractional parts and MCP clients send
    integers or strings. Reverses if: an MCP client is measured sending a
    fractional id.
(c) ``core/log_scrub.py`` escaped C0, DEL and C1 only, so U+2028 / U+2029
    (a line break to a log viewer and ``str.splitlines``) and the bidi
    controls U+202A..U+202E / U+2066..U+2069 (they reorder what a terminal
    shows) reached a log raw - and so did the bidi marks U+061C / U+200E /
    U+200F (added by the verifier's sweep, same root); ``dashboard/_handler.py`` kept its own range
    copy and passed the stdlib table straight through, bypassing any
    widening; the DS shell's ``log_message`` and the JS ``scrubLog`` carried
    their own C1-only copies (same-root siblings).
(d) ``scrub_traceback`` bounded an exception group's width and depth but not
    a rendered line: a 100k-character exception message was one 100k line.
(e) ``core/http_host_gate.py`` kept an IPv6 zone id (``[fe80::1%25x]``
    parsed to ``fe80::1%25x``) and ``is_allowed_host`` passed it as an IP
    literal. DECISION: refused (421). No browser sends a zone id in a Host
    (RFC 6874 zone ids were never implemented by browsers), so the refusal
    costs no real client, and the RM-819 (c) "any IP literal passes" rule
    is about a LAN viewer's plain address, which still passes.
"""
from __future__ import annotations

import builtins
import json
import logging
import os
import shutil
import socket
import subprocess
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from core import http_host_gate as _host_gate
from core import log_scrub

ROOT = Path(__file__).resolve().parent.parent
USAGE_JS = ROOT / "tools" / "usage-mcp-server.js"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")

_PING = '{"jsonrpc":"2.0","id":99,"method":"ping"}'

# The RM-825 (c) code points: the bidi marks, the line / paragraph
# separator, then the bidi embedding / override controls and the isolates.
_EXTRA = ([0x061C, 0x200E, 0x200F, 0x2028, 0x2029]
          + list(range(0x202A, 0x202F)) + list(range(0x2066, 0x206A)))


def _usage(*lines: str, timeout: float = 30.0) -> tuple[int, list[dict], str]:
    """Run the stdio server over ``lines`` (stdin then EOF): exit code, the
    parsed replies, stderr. No line names ``query_usage`` (the network
    tool), and no key is in the environment."""
    env = dict(os.environ)
    env.pop("ANTHROPIC_USAGE_KEY", None)
    proc = subprocess.run(
        [NODE, str(USAGE_JS)], input="".join(f"{ln}\n" for ln in lines),
        capture_output=True, text=True, encoding="utf-8", timeout=timeout,
        cwd=str(ROOT), env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    replies = [json.loads(ln) for ln in proc.stdout.splitlines() if ln.strip()]
    return proc.returncode, replies, proc.stderr


# -- (a) a notification gets no reply ----------------------------------------

@needs_node
@pytest.mark.parametrize("line", [
    '{"jsonrpc":"2.0","method":"initialize","params":{}}',
    '{"jsonrpc":"2.0","method":"ping"}',
    '{"jsonrpc":"2.0","method":"tools/list"}',
    '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"nope"}}',
    '{"jsonrpc":"2.0","method":"tools/call","params":5}',
    '{"jsonrpc":"2.0","method":"nope"}',
], ids=["initialize", "ping", "tools-list", "tools-call", "tools-call-bad",
        "unknown"])
def test_a_notification_gets_no_reply(line):
    code, replies, stderr = _usage(line, _PING)
    assert code == 0, stderr[-400:]
    assert replies == [{"jsonrpc": "2.0", "id": 99, "result": {}}], replies


@needs_node
def test_a_null_id_is_a_request_not_a_notification():
    """``"id": null`` is a present id (a request), so it is still answered."""
    code, replies, stderr = _usage('{"jsonrpc":"2.0","id":null,"method":"ping"}')
    assert code == 0, stderr[-400:]
    assert replies == [{"jsonrpc": "2.0", "id": None, "result": {}}]


@needs_node
def test_a_non_string_method_without_id_is_still_invalid_request():
    """Pinned decision (module docstring): the spec's section 7 example."""
    code, replies, stderr = _usage(
        '{"jsonrpc":"2.0","method":1,"params":"bar"}', _PING)
    assert code == 0, stderr[-400:]
    assert replies[0] == {"jsonrpc": "2.0", "id": None,
                          "error": {"code": -32600, "message": "Invalid Request"}}
    assert len(replies) == 2


# -- (b) an id JSON.parse cannot hold exactly is refused ----------------------

@needs_node
@pytest.mark.parametrize("raw_id", ["9007199254740993", "9007199254740992",
                                    "-9007199254740993", "1e20"])
def test_an_unsafe_integer_id_is_refused(raw_id):
    code, replies, stderr = _usage(
        '{"jsonrpc":"2.0","id":' + raw_id + ',"method":"ping"}', _PING)
    assert code == 0, stderr[-400:]
    assert replies[0] == {"jsonrpc": "2.0", "id": None,
                          "error": {"code": -32600, "message": "Invalid Request"}}
    assert [r.get("id") for r in replies] == [None, 99], replies


@needs_node
@pytest.mark.parametrize("raw_id, want", [
    ("9007199254740991", 9007199254740991),     # Number.MAX_SAFE_INTEGER
    ("-9007199254740991", -9007199254740991),
    ("1.5", 1.5),
    ("0", 0),
])
def test_a_safe_id_is_echoed_exactly(raw_id, want):
    code, replies, stderr = _usage(
        '{"jsonrpc":"2.0","id":' + raw_id + ',"method":"ping"}')
    assert code == 0, stderr[-400:]
    assert replies == [{"jsonrpc": "2.0", "id": want, "result": {}}]


# -- (c) the extra code points are escaped, through one table -----------------

@pytest.mark.parametrize("cp", _EXTRA, ids=[f"U+{c:04X}" for c in _EXTRA])
def test_scrub_log_and_scrub_controls_escape_the_extra_code_point(cp):
    text = f"a{chr(cp)}b"
    want = f"a\\u{cp:04x}b"
    assert log_scrub.scrub_log(text) == want
    assert log_scrub.scrub_log(text, None) == want      # the fallback arm
    assert log_scrub.scrub_controls(text) == want


def test_the_widened_scrub_stays_idempotent_and_injective():
    sample = ("".join(chr(c) for c in range(0, 0xB0)) + "\\u2028\\"
              + "".join(chr(c) for c in _EXTRA) + "C:\\path")
    once = log_scrub.scrub_controls(sample)
    assert log_scrub.scrub_controls(once) == once
    logged = log_scrub.scrub_log(sample)
    assert log_scrub.scrub_controls(logged) == logged
    # The literal text `\u2028` a client types is NOT the escape of a real
    # U+2028: scrub_log doubles its backslash.
    assert log_scrub.scrub_log("\\u2028") != log_scrub.scrub_log("\u2028")
    assert log_scrub.scrub_log(sample) == log_scrub.scrub_log(sample, None)
    assert not any(chr(c) in logged for c in _EXTRA)


def test_one_shared_range_table():
    from dashboard import _handler
    assert set(_EXTRA) <= set(log_scrub.SCRUB_RANGES)
    assert _handler._SCRUB_RANGES is log_scrub.SCRUB_RANGES
    assert _handler._CONTROL_CHAR_TABLE is log_scrub.CONTROL_CHAR_TABLE
    assert _handler._scrub_log("x\u2028y\u202ez") == "x\\u2028y\\u202ez"


def test_scrub_filter_escapes_the_extra_code_points():
    rec = logging.LogRecord("t", logging.INFO, __file__, 1,
                            "client said %s", ("a\u2029b\u2066c",), None)
    log_scrub.ScrubFilter().filter(rec)
    assert rec.getMessage() == "client said a\\u2029b\\u2066c"


def test_daemon_slayer_shell_log_message_escapes_the_extra_code_points():
    """Same-root sibling: the DS shell's ``log_message`` kept a C1-only
    copy of the table (and its "core-free" note was stale since RM-819)."""
    from agents.daemon_slayer.server import Handler
    got: list[str] = []

    class _Grab(logging.Handler):
        def emit(self, record):
            got.append(record.getMessage())

    lg = logging.getLogger("daemon_slayer.server")
    grab, prior = _Grab(level=logging.DEBUG), lg.level
    lg.addHandler(grab)
    lg.setLevel(logging.DEBUG)
    try:
        h = Handler.__new__(Handler)
        h.client_address = ("127.0.0.1", 1)
        h.log_message("%s", "GET /x\u2028FAKE\u202e\x1b HTTP/1.1")
    finally:
        lg.removeHandler(grab)
        lg.setLevel(prior)
    assert got, "the DS shell logged nothing"
    assert "\\u2028FAKE\\u202e\\x1b" in got[0], got
    assert not any(chr(c) in got[0] for c in _EXTRA)


def _js_scrub(text: str) -> str:
    probe = ("const m = require(process.argv[1]);"
             "let s = ''; process.stdin.on('data', c => s += c);"
             "process.stdin.on('end', () => process.stdout.write("
             "JSON.stringify(m.scrubLog(JSON.parse(s)))));")
    proc = subprocess.run(
        [NODE, "-e", probe, str(USAGE_JS)], input=json.dumps(text),
        capture_output=True, text=True, encoding="utf-8", timeout=30,
        cwd=str(ROOT),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert proc.returncode == 0, proc.stderr[-400:]
    return json.loads(proc.stdout)


@needs_node
def test_js_scrub_log_matches_the_python_table():
    """The JS copy must escape exactly what ``core.log_scrub.scrub_log``
    does, the extra code points included."""
    sample = ("".join(chr(c) for c in range(0, 0xB0)) + "\\"
              + "".join(chr(c) for c in _EXTRA) + "plain")
    assert _js_scrub(sample) == log_scrub.scrub_log(sample)


# -- (d) a rendered traceback line is capped ----------------------------------

def _boom(text: str) -> BaseException:
    try:
        raise ValueError(text)
    except ValueError as e:
        return e


def test_scrub_traceback_caps_a_long_line():
    cap = log_scrub.MAX_LINE_CHARS
    out = log_scrub.scrub_traceback(_boom("A" * (cap * 25)))
    lines = out.rstrip("\n").split("\n")
    longest = max(len(ln) for ln in lines)
    assert longest <= cap + 64, longest
    assert any("chars cut" in ln for ln in lines), lines[-1][-80:]
    assert out.endswith("\n")


def test_scrub_traceback_caps_a_group_member_line():
    group_type = builtins.ExceptionGroup
    group = group_type("g", [_boom("B" * (log_scrub.MAX_LINE_CHARS * 3))])
    lines = log_scrub.scrub_traceback(group).rstrip("\n").split("\n")
    assert max(len(ln) for ln in lines) <= log_scrub.MAX_LINE_CHARS + 64


def test_scrub_traceback_leaves_an_ordinary_traceback_alone():
    """Negative control: a normal traceback is not touched by the cap."""
    exc = _boom("short message")
    out = log_scrub.scrub_traceback(exc)
    assert "chars cut" not in out
    assert out.rstrip("\n").endswith("ValueError: short message")


def test_scrub_filter_exc_text_is_capped():
    exc = _boom("C" * (log_scrub.MAX_LINE_CHARS * 4))
    rec = logging.LogRecord("t", logging.ERROR, __file__, 1, "x", (),
                            (type(exc), exc, exc.__traceback__))
    log_scrub.ScrubFilter().filter(rec)
    assert max(len(ln) for ln in rec.exc_text.split("\n")) <= (
        log_scrub.MAX_LINE_CHARS + 64)


# -- (e) a zone-id Host is refused --------------------------------------------

@pytest.mark.parametrize("value", ["[fe80::1%25x]", "[fe80::1%25x]:8888",
                                   "[fe80::1%eth0]", "fe80::1%eth0",
                                   "[::1%251]:8888"])
def test_a_zone_id_host_is_not_allowed(value):
    hostname = _host_gate.host_header_hostname(value)
    assert not _host_gate.is_allowed_host(hostname), hostname


@pytest.mark.parametrize("raw", ["fe80::1%25x", "fe80::1%eth0", "::1%1"])
def test_is_allowed_host_refuses_a_scoped_literal_directly(raw):
    assert not _host_gate.is_allowed_host(raw)


@pytest.mark.parametrize("value, want", [("[fe80::1]:8888", "fe80::1"),
                                         ("[::1]", "::1"),
                                         ("fe80::1", "fe80::1")])
def test_an_unscoped_ipv6_literal_still_passes(value, want):
    """Negative control: the RM-819 (c) IP-literal rule is unchanged."""
    assert _host_gate.host_header_hostname(value) == want
    assert _host_gate.is_allowed_host(want)


@pytest.fixture
def dashboard(monkeypatch):
    from dashboard import _dispatch
    from dashboard._handler import Handler
    monkeypatch.setattr(_host_gate, "_allowed_names_cache",
                        frozenset({"127.0.0.1", "localhost", "::1"}))
    calls: list[str] = []

    def _get(h):
        calls.append(h.path)
        h._send(200, b"ok", "text/plain")
        return True

    monkeypatch.setattr(_dispatch, "dispatch_get", _get)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.daemon_threads = True
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield srv.server_address[1], calls
    finally:
        srv.shutdown()
        srv.server_close()


def _get_status(port: int, host: str) -> tuple[int | None, bytes]:
    buf = b""
    head = f"GET /api/state HTTP/1.0\r\nHost: {host}\r\n\r\n".encode("latin-1")
    with socket.create_connection(("127.0.0.1", port), timeout=8) as s:
        s.sendall(head)
        while True:
            try:
                chunk = s.recv(65536)
            except (ConnectionResetError, ConnectionAbortedError):
                break
            if not chunk:
                break
            buf += chunk
    if not buf.startswith(b"HTTP/"):
        return None, buf
    return int(buf.split(b"\r\n", 1)[0].split(b" ")[1]), buf


@pytest.mark.parametrize("host", ["[fe80::1%25x]:{p}", "[::1%251]:{p}"])
def test_dashboard_refuses_a_zone_id_host_421(dashboard, host):
    port, calls = dashboard
    status, reply = _get_status(port, host.format(p=port))
    assert status == 421, reply[:200]
    assert calls == [], "the route ran for a zone-id Host"


def test_dashboard_still_serves_a_plain_ipv6_literal(dashboard):
    port, calls = dashboard
    status, reply = _get_status(port, f"[::1]:{port}")
    assert status == 200, reply[:200]
    assert calls == ["/api/state"]
