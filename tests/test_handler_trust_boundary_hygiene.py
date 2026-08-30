"""Lane 8 cycle 13: request-log hygiene and body-framing at the :8888 boundary.

Four defects in ``dashboard/_handler.py``, each measured against the REAL
``Handler`` over a real socket before it was filed.

W1 LOG INJECTION. ``BaseHTTPRequestHandler.log_message`` translates C0 and
DEL-to-U+009F control characters to ``\\xHH`` before writing - that is a
deliberate stdlib hardening, and OVERRIDING the method silently opts out of
it. RC's override did, so an attacker-controlled request target carried raw
ESC into the log record. Three ``log.warning`` sites made it worse by
interpolating ``self.path`` with ``%s`` rather than ``%r``: those fire at
WARNING, so the injection did not even need debug logging enabled. The server
binds ``HOST = "::"`` on a ThreadingHTTPServer (``dashboard/server.py:35``),
so the reachable set is the whole LAN plus the tailnet, and the sink is
``logs/YYYY-MM-DD.log``, which the operator reads in a terminal.

W2 PEER ATTRIBUTION. The same override dropped ``address_string()``, which the
stdlib prefixes to every message, so no HTTP log line named who sent it - and
neither did the CSRF-reject or the control-endpoint auth-reject warning. A
rejected control request was unattributable on a LAN-reachable port.

W3 BODY FRAMING. Every body control keys off ``Content-Length``: the 1 MiB
cap, the read deadline, and the dict-or-400 guard. A ``Transfer-Encoding:
chunked`` POST has no ``Content-Length``, so ``n`` was 0, the declared body
was never read, and the route was dispatched with ``{}`` as though the client
had sent an empty object. Measured: ``POST /api/command`` chunked reached
``_dispatch._validate_request_body``. Nothing in RC sends chunked (checked),
so 411 is the correct answer.

W4 TOKEN COMPARISON. The control-endpoint gate compared with ``!=``. Graded
honestly: ``RC_DASH_TOKEN`` is set NOWHERE in this deployment, so the gate
does not run at all today and this change is inert defense-in-depth, not a
live defect. It is here because the correct idiom costs one line.
"""
from __future__ import annotations

import logging
import socket
import threading
from http.server import ThreadingHTTPServer

import pytest

from dashboard import _handler
from dashboard._handler import Handler

# C0 control characters, DEL, and the C1 range the stdlib table also covers.
_FORBIDDEN = (set(range(0x00, 0x20)) - {0x09, 0x0A, 0x0D}) | set(range(0x7F, 0xA0))


@pytest.fixture
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield srv.server_address[1]
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.fixture
def caplog_rc():
    """Capture every record on the handler's logger, at every level."""
    records: list[logging.LogRecord] = []

    class _Cap(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    lg = logging.getLogger("rc.web_dashboard")
    cap = _Cap()
    prior_level = lg.level
    lg.setLevel(logging.DEBUG)
    lg.addHandler(cap)
    try:
        yield records
    finally:
        lg.removeHandler(cap)
        lg.setLevel(prior_level)


def _raw(port: int, payload: bytes, timeout: float = 8.0) -> bytes:
    s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    try:
        s.sendall(payload)
        out = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                return out
            out += chunk
    finally:
        s.close()


def _messages(records) -> list[str]:
    return [r.getMessage() for r in records]


def _control_bytes_in(text: str) -> list[str]:
    return [hex(ord(ch)) for ch in text if ord(ch) in _FORBIDDEN]


# -- W1: control-character sanitization --------------------------------


def test_sanitizer_escapes_control_characters_and_keeps_text():
    out = _handler._scrub_log("/api/\x1b[31mred\x1b[0m\x08\x7f")
    assert _control_bytes_in(out) == []
    assert "\\x1b" in out
    assert "/api/" in out and "red" in out


def test_sanitizer_is_a_no_op_on_an_ordinary_path():
    """Negative control: the guard must not mangle normal traffic."""
    plain = "/api/state?mode=aram&n=5"
    assert _handler._scrub_log(plain) == plain


def test_sanitizer_fallback_branch_is_equivalent(monkeypatch):
    """The `_CONTROL_CHAR_TABLE is None` arm exists for a Python that drops
    the private stdlib attribute, so no ordinary run reaches it - which is
    exactly how a guard on a non-default call path ships untested
    (feedback_guard_on_nondefault_call_path_is_untested). Force the branch
    and require it to agree with the stdlib arm on every control character."""
    # The backslash is load-bearing in this sample. The stdlib table maps
    # it to `\\`; without it in the sample the two arms agreed trivially and
    # this test passed while the fallback was NOT equivalent
    # (feedback_acceptance_example_may_be_vacuous, caught by widening it).
    # Tab, LF and CR are deliberately OUTSIDE _FORBIDDEN (a log record may
    # legitimately contain them) but the stdlib table still escapes all
    # three, so a fallback that dropped them stayed green until the
    # cycle-13 adversarial pass measured it. Equivalence is asserted over
    # the FULL table domain, not just the bytes this file forbids.
    sample = "".join(chr(c) for c in sorted(_FORBIDDEN | {0x09, 0x0A, 0x0D})) + "\\/api/state"
    via_stdlib = _handler._scrub_log(sample)
    monkeypatch.setattr(_handler, "_CONTROL_CHAR_TABLE", None)
    via_fallback = _handler._scrub_log(sample)
    assert _control_bytes_in(via_fallback) == []
    assert via_fallback == via_stdlib, (
        "the fallback disagrees with the stdlib table")


def test_request_log_line_carries_no_raw_control_bytes(server, caplog_rc):
    evil = b"/api/\x1b[31mFAKE-ADMIN-OK\x1b[0m\x08\x08\x7f"
    _raw(server, b"GET " + evil + b" HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
    logged = _messages(caplog_rc)
    assert logged, "the request produced no log record at all"
    joined = "\n".join(logged)
    assert _control_bytes_in(joined) == [], (
        f"raw control bytes reached the log: {joined!r}")
    assert "\\x1b" in joined, "the escape was dropped rather than escaped"


def test_csrf_reject_warning_escapes_the_path(server, caplog_rc):
    """The WARNING sites matter most - they fire without debug logging."""
    _raw(server,
         b"POST /api/command\x1b[31mINJECT HTTP/1.0\r\nHost: 127.0.0.1\r\n"
         b"Origin: https://evil.example\r\nContent-Length: 2\r\n\r\n{}")
    warnings = [r.getMessage() for r in caplog_rc if r.levelno >= logging.WARNING]
    assert warnings, "a cross-origin POST logged no warning"
    joined = "\n".join(warnings)
    assert _control_bytes_in(joined) == [], (
        f"raw control bytes in a WARNING record: {joined!r}")


def test_proxy_failure_log_escapes_the_exception_text(server, caplog_rc,
                                                      monkeypatch):
    """Completeness check on W1: the request target is not the only channel.

    An exception raised while proxying is rendered with %s, so an exception
    whose str() carries a control byte would reach the log unescaped. No
    CURRENTLY reachable exception here does - int()'s ValueError repr-escapes
    its operand and urllib does not raise on an ESC in the path - so this
    drives a synthetic one to prove the guard exists rather than to prove a
    live bug. Without that distinction the test would look like evidence of
    a defect it is not claiming.
    """
    import urllib.request

    def boom(*_a, **_k):
        raise RuntimeError("upstream said \x1b[31mFAIL\x1b[0m")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    # /api/env is in SUPERVISOR_PROXY_PATHS, so this reaches the proxy.
    _raw(server, b"GET /api/env HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
    joined = "\n".join(_messages(caplog_rc))
    assert "FAIL" in joined, f"the proxy failure was not logged at all: {joined!r}"
    assert _control_bytes_in(joined) == [], (
        f"raw control bytes reached the log via exception text: {joined!r}")


# -- W2: peer attribution ----------------------------------------------


def test_request_log_line_names_the_peer(server, caplog_rc):
    _raw(server, b"GET /api/nothing-here HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
    joined = "\n".join(_messages(caplog_rc))
    assert "127.0.0.1" in joined, f"no peer address in {joined!r}"


def test_csrf_reject_warning_names_the_peer(server, caplog_rc):
    """NOTE, so this is not re-broken: the Host header must NOT be
    127.0.0.1 here. The CSRF warning already interpolates ``host=%r``, so
    with ``Host: 127.0.0.1`` this assertion passes on the pre-fix code for
    the wrong reason - it reads the echoed Host, not the peer. Sending a
    different Host makes the connection's own address the only source that
    can satisfy it (feedback_acceptance_example_may_be_vacuous)."""
    _raw(server,
         b"POST /api/command HTTP/1.0\r\nHost: legion-rc\r\n"
         b"Origin: https://evil.example\r\nContent-Length: 2\r\n\r\n{}")
    warnings = [r.getMessage() for r in caplog_rc if r.levelno >= logging.WARNING]
    assert warnings, "a cross-origin POST logged no warning"
    assert any("127.0.0.1" in m for m in warnings), f"no peer in {warnings!r}"


def test_control_endpoint_auth_reject_names_the_peer(server, caplog_rc,
                                                     monkeypatch):
    monkeypatch.setenv("RC_DASH_TOKEN", "s3cret")
    body = b'{"command":"noop"}'
    resp = _raw(server,
                b"POST /api/command HTTP/1.0\r\nHost: 127.0.0.1\r\n"
                b"X-RC-Token: wrong\r\nContent-Length: " +
                str(len(body)).encode() + b"\r\n\r\n" + body)
    assert b"401" in resp.split(b"\r\n")[0]
    warnings = [r.getMessage() for r in caplog_rc if r.levelno >= logging.WARNING]
    assert any("127.0.0.1" in m for m in warnings), f"no peer in {warnings!r}"


# -- W3: chunked body framing ------------------------------------------


def test_chunked_post_is_rejected_with_411(server):
    resp = _raw(server,
                b"POST /api/command HTTP/1.0\r\nHost: 127.0.0.1\r\n"
                b"Transfer-Encoding: chunked\r\nContent-Type: application/json"
                b"\r\n\r\n7\r\n{\"a\":1}\r\n0\r\n\r\n")
    status = resp.split(b"\r\n")[0]
    assert b"411" in status, f"chunked POST was not refused: {status!r}"


def test_chunked_post_never_reaches_the_dispatcher(server, monkeypatch):
    """The 411 must be returned BEFORE a route runs, not by the route."""
    seen: list[object] = []
    real = _handler._dispatch.dispatch_post

    def spy(handler, body):
        seen.append(body)
        return real(handler, body)

    monkeypatch.setattr(_handler._dispatch, "dispatch_post", spy)
    _raw(server,
         b"POST /api/command HTTP/1.0\r\nHost: 127.0.0.1\r\n"
         b"Transfer-Encoding: chunked\r\n\r\n0\r\n\r\n")
    assert seen == [], f"the discarded chunked body still reached a route: {seen!r}"


def test_duplicate_transfer_encoding_headers_cannot_smuggle_a_body(server,
                                                                    monkeypatch):
    """A repeated Transfer-Encoding must not walk past the 411.

    `email.message.Message.get` returns only the FIRST header of a repeated
    name, so `Transfer-Encoding: identity` followed by `Transfer-Encoding:
    chunked` read as "identity", walked past the guard, and the body was
    discarded and dispatched as `{}` - the exact defect the 411 exists to
    close, still firing after the fix. Found by the cycle-13 adversarial
    pass against the FIXED code, which is the argument for running one: the
    guard was real and its header accessor was not.
    """
    seen: list[object] = []
    real = _handler._dispatch.dispatch_post

    def spy(handler, body):
        seen.append(body)
        return real(handler, body)

    monkeypatch.setattr(_handler._dispatch, "dispatch_post", spy)
    resp = _raw(server,
                b"POST /api/command HTTP/1.0\r\nHost: 127.0.0.1\r\n"
                b"Transfer-Encoding: identity\r\nTransfer-Encoding: chunked"
                b"\r\n\r\n7\r\n{\"a\":1}\r\n0\r\n\r\n")
    status = resp.split(b"\r\n")[0]
    assert b"411" in status, (
        f"duplicate-header chunked POST was not refused: {status!r}")
    assert seen == [], f"the smuggled body still reached a route: {seen!r}"


def test_token_gate_survives_a_lone_surrogate_in_the_env(server, monkeypatch):
    """A surrogate in RC_DASH_TOKEN must 401, not raise.

    os.environ round-trips lone surrogates on Windows, so a plain
    `.encode("utf-8")` raises UnicodeEncodeError and turns the reject into a
    traceback - a crash where the old `!=` had merely returned False. The
    header side cannot carry one (headers are iso-8859-1-decoded), so this
    is entirely about the configured value.
    """
    monkeypatch.setenv("RC_DASH_TOKEN", "\ud800bad")
    body = b'{"command":"noop"}'
    resp = _raw(server,
                b"POST /api/command HTTP/1.0\r\nHost: 127.0.0.1\r\n"
                b"X-RC-Token: wrong\r\nContent-Length: " +
                str(len(body)).encode() + b"\r\n\r\n" + body)
    status = resp.split(b"\r\n")[0]
    assert b"401" in status, f"expected a clean 401, got: {status!r}"
    assert b"500" not in status


def test_ordinary_content_length_post_still_dispatches(server, monkeypatch):
    """Positive control: the 411 must not catch a normally framed body."""
    seen: list[object] = []
    real = _handler._dispatch.dispatch_post

    def spy(handler, body):
        seen.append(body)
        return real(handler, body)

    monkeypatch.setattr(_handler._dispatch, "dispatch_post", spy)
    body = b'{"command":"noop"}'
    _raw(server,
         b"POST /api/command HTTP/1.0\r\nHost: 127.0.0.1\r\n"
         b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
    assert seen == [{"command": "noop"}], (
        f"a normally framed POST stopped dispatching: {seen!r}")


# -- W4: token comparison ----------------------------------------------


def test_token_gate_still_accepts_the_right_token(server, monkeypatch):
    """Positive control around the compare_digest swap."""
    monkeypatch.setenv("RC_DASH_TOKEN", "s3cret")
    body = b'{"command":"noop"}'
    resp = _raw(server,
                b"POST /api/command HTTP/1.0\r\nHost: 127.0.0.1\r\n"
                b"X-RC-Token: s3cret\r\nContent-Length: " +
                str(len(body)).encode() + b"\r\n\r\n" + body)
    assert b"401" not in resp.split(b"\r\n")[0]


def test_token_comparison_is_constant_time():
    """Read the contract off disk - a timing property cannot be asserted
    behaviourally on this box, so pin the idiom instead."""
    from pathlib import Path
    src = Path(_handler.__file__).read_text(encoding="utf-8")
    assert "compare_digest" in src, (
        "the token gate does not use a constant-time compare")
    assert "req_token != dash_token" not in src, (
        "the naive compare is still present")
