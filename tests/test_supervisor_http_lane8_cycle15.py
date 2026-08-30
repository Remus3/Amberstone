# arch: lane 8 cycle 15 - agents/_supervisor_http.py deep audit | section=tests | frozen=no
"""Lane 8 Headless-True-Audit cycle 15 - `agents/_supervisor_http.py`.

Target picked on section-3 criterion 1 (externally reachable input) and
criterion 3 (threaded server), and because my own RM-228 named this file the
worst of five `log_message` overrides. The bind was re-measured LIVE this run
rather than inherited: `Get-NetTCPConnection -LocalPort 8890,8891 -State Listen`
reports both on `0.0.0.0` (pid 25908), and the source hardcodes
`("0.0.0.0", port)`.

Two defect families are pinned here. Both were reproduced against the REAL
handler over a REAL socket before a line of production code was touched.

1. THE L4 DENYLIST IS INERT AGAINST PERCENT-ENCODING. `_is_forbidden` reads
   `self.path`, which is the RAW request target, but
   `SimpleHTTPRequestHandler.translate_path` calls `urllib.parse.unquote` on
   that same target before opening the file. So the gate and the file-opener
   disagree about what the path IS. Measured: `/.env` -> 403, `/%2Eenv` -> 200
   with the file body; `/api-key-claude.txt` -> 403, `/api-key-claude%2Etxt`
   and `/%61pi-key-claude.txt` -> 200 with the body.

   SEVERITY, graded down by measurement and stated here so nobody re-inflates
   it. This is a BROKEN SAFETY NET, not a live secret leak and not an
   arbitrary file read:
     - It is CONFINED TO THE WEB ROOT. Five escape vectors (`/../x`,
       `/%2E%2E/x`, `/..%2Fx`, `/%2e%2e%2fx`, `/....//x`) were all measured
       404/403 - the stdlib `translate_path` collapses traversal correctly, so
       nothing outside `web/` is reachable and this is NOT the item-1177 class.
     - The real `web/` root contains NO dotfile and no secret-shaped file
       today, so nothing is leaking right now.
   What IS broken is precisely the control's stated purpose. The class
   docstring says the denylist exists so "a misplaced `.env` in `web/` never
   reaches the wire, even inside the LAN" - the misplaced-file case is the
   operator error it was built to catch, and it does not catch it.

2. RM-228 FOR THIS FILE: the `log_message` override drops the stdlib's
   control-character escaping. `BaseHTTPRequestHandler.log_message` ends with
   `message.translate(self._control_char_table)`; the override does not.
   Measured against the real handler: a request target carrying ESC, BS and
   DEL put raw `0x1b`, `0x08` and `0x7f` into the log record, at INFO, on a
   0.0.0.0-bound port. The peer half of RM-228's census was correct and is NOT
   a defect here - this override already calls `address_string()`, unlike some
   of its siblings, and that is asserted below so a future edit cannot drop it.
"""
from __future__ import annotations

import http.client
import io
import logging
import socket
import socketserver
import threading
import time
from pathlib import Path

import pytest

from agents._supervisor_http import _QuietHandler


# ---------------------------------------------------------------------------
# Harness - a real server on an ephemeral loopback port, real sockets.
# ---------------------------------------------------------------------------

class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


@pytest.fixture
def webroot(tmp_path: Path) -> Path:
    root = tmp_path / "webroot"
    root.mkdir()
    (root / ".env").write_text("SECRET_KEY=cycle15-canary\n", encoding="utf-8")
    (root / "api-key-claude.txt").write_text(
        "sk-ant-cycle15-canary\n", encoding="utf-8"
    )
    (root / "ok.txt").write_text("public\n", encoding="utf-8")
    return root


@pytest.fixture
def server(webroot: Path):
    srv = _Server(
        ("127.0.0.1", 0),
        lambda *a, **kw: _QuietHandler(*a, directory=str(webroot), **kw),
    )
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def _get(srv, target: str) -> tuple[int, bytes]:
    """GET a RAW request target - `putrequest` must not re-encode it."""
    conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=5)
    try:
        conn.putrequest("GET", target, skip_accept_encoding=True)
        conn.putheader("Host", "127.0.0.1")
        conn.endheaders()
        resp = conn.getresponse()
        return resp.status, resp.read()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 1. Characterization - what the denylist already does right.
# ---------------------------------------------------------------------------

def test_char_public_file_is_served(server):
    """Pin the happy path before changing the gate."""
    status, body = _get(server, "/ok.txt")
    assert status == 200
    assert b"public" in body


def test_char_literal_dotfile_is_blocked(server):
    """The plain, unencoded form was already blocked - keep it that way."""
    status, body = _get(server, "/.env")
    assert status == 403
    assert b"cycle15-canary" not in body


def test_char_literal_denylisted_name_is_blocked(server):
    status, body = _get(server, "/api-key-claude.txt")
    assert status == 403
    assert b"cycle15-canary" not in body


# ---------------------------------------------------------------------------
# 2. Regression - the percent-encoded bypass.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("target", [
    "/%2Eenv",                # uppercase hex
    "/%2eenv",                # lowercase hex - the table is case-insensitive
    "/api-key-claude%2Etxt",  # encode a char in the MIDDLE of a denylisted name
    "/%61pi-key-claude.txt",  # encode a plain letter: nothing special about "."
])
def test_encoded_basename_cannot_bypass_the_denylist(server, target):
    """`_is_forbidden` reads the raw target; `translate_path` unquotes it.

    Any character of the basename can be percent-encoded to make the two
    disagree, so the gate must decode exactly as `translate_path` does.
    """
    status, body = _get(server, target)
    assert b"cycle15-canary" not in body, (
        f"{target} served a denylisted file body - the L4 gate was bypassed"
    )
    assert status == 403, f"{target} should be forbidden, got {status}"


def test_double_encoding_is_not_over_decoded(server):
    """Decode ONCE, exactly as `translate_path` does - no more.

    `%252E` unquotes once to the literal text `%2E`, which is NOT a dot, so
    the file `.env` is not what is being requested and the honest answer is
    404 (no such file), not 403. A gate that unquotes in a loop would answer
    403 here and would be describing a request nobody made.
    """
    status, _ = _get(server, "/%252Eenv")
    assert status == 404


def _gate(target: str) -> bool:
    class _Stub:
        _DENYLIST_NAMES = _QuietHandler._DENYLIST_NAMES
    return _QuietHandler._is_forbidden(_Stub(), target)


def test_gate_treats_an_encoded_backslash_as_a_separator():
    """Pin the gate's reading of `%5C`, at the unit level.

    HONEST SCOPE, because a mutation run showed this guard was otherwise
    untested and a leak-shaped assertion here would be VACUOUS: the stdlib
    already refuses to serve these. `translate_path` drops any segment whose
    `os.path.dirname` is non-empty, and on Windows `os.path.dirname("x\\.env")`
    is `"x"` - measured - so `/x%5C.env` serves nothing either way. What the
    guard changes is the GATE's answer. This test asserts that contract
    directly rather than pretending to prevent a leak the stdlib prevents.
    """
    for target in ("/%5C.env", "/x%5C.env", "/sub%5Capi-key-claude.txt"):
        assert _gate(target) is True, f"gate let {target} through"


def test_gate_is_never_looser_than_before_for_backslash_targets():
    """Regression for a defect the cycle-15 VERIFIER found in the fix itself.

    The first revision normalised `\\` to `/` and tested only that reading, so
    `/..\\OUTSIDE.txt` - previously 403, because the slash-only basename
    `..\\OUTSIDE.txt` starts with a dot - became a 301 to the directory
    listing, since the normalised basename is the innocent `OUTSIDE.txt`.
    Normalising picks ONE reading and that reading is sometimes the more
    permissive one. The gate now takes the UNION of both readings.

    No secret was ever exposed by that regression (the listing shows the
    `.env` NAME, and its body stayed 403 in both versions), which is exactly
    why only a targeted assertion catches it - the leak-shaped tests all
    stayed green.
    """
    for target in ("/..\\OUTSIDE.txt", "/..%5COUTSIDE.txt", "/..\\.env"):
        assert _gate(target) is True, (
            f"gate got LOOSER for {target} - the union reading regressed"
        )


def test_encoded_traversal_still_cannot_escape_the_web_root(server, tmp_path):
    """Guard the property that keeps this finding a safety-net bug.

    If this ever regresses to 200 the severity changes category entirely, from
    "denylist bypass inside web/" to "arbitrary file read".
    """
    outside = tmp_path / "OUTSIDE.txt"
    outside.write_text("ARBITRARY-READ-CANARY\n", encoding="utf-8")
    for target in ("/../OUTSIDE.txt", "/%2E%2E/OUTSIDE.txt",
                   "/..%2FOUTSIDE.txt", "/%2e%2e%2fOUTSIDE.txt"):
        status, body = _get(server, target)
        assert b"ARBITRARY-READ-CANARY" not in body, f"{target} escaped web root"
        assert status in (403, 404), f"{target} returned {status}"


# ---------------------------------------------------------------------------
# 2b. Regression - a chunked body must be REJECTED, not silently discarded.
# ---------------------------------------------------------------------------

def _fake_handler(header_block: str, body: bytes):
    """A handler with real HTTPMessage headers - a dict cannot hold a
    repeated header, which is exactly the input the duplicate-header case
    lives in, so the double must not under-specify that."""
    import email.parser
    from http.client import HTTPMessage
    h = _QuietHandler.__new__(_QuietHandler)
    h.headers = email.parser.Parser(_class=HTTPMessage).parsestr(header_block)
    h.rfile = io.BytesIO(body)
    return h


def test_content_length_body_is_still_read():
    """Characterization: the supported path must keep working."""
    body = b'{"text":"real payload"}'
    h = _fake_handler(f"Content-Length: {len(body)}\n", body)
    assert h._read_body() == body


def test_chunked_body_is_detected_as_unreadable():
    """Measured: `_read_body` returns b"" for a well-formed chunked request."""
    body = b'{"text":"real payload"}'
    raw = b"%x\r\n" % len(body) + body + b"\r\n0\r\n\r\n"
    h = _fake_handler("Transfer-Encoding: chunked\n", raw)
    assert h._read_body() == b"", "precondition changed - re-derive this finding"
    assert h._rejects_chunked() is True


def test_duplicate_transfer_encoding_header_cannot_bypass_the_guard():
    """`Message.get` returns only the FIRST of a repeated header.

    `Transfer-Encoding: identity` followed by `Transfer-Encoding: chunked`
    walks past a `get`-based guard; the joined `get_all` view cannot be split
    that way. This is the exact bypass cycle 13 found in its own first fix.
    """
    h = _fake_handler(
        "Transfer-Encoding: identity\nTransfer-Encoding: chunked\n", b"")
    assert h.headers.get("Transfer-Encoding") == "identity"  # the trap
    assert h._rejects_chunked() is True


def test_plain_post_is_not_rejected_as_chunked():
    """Negative control - the guard must not reject ordinary bodies."""
    h = _fake_handler("Content-Length: 2\n", b"{}")
    assert h._rejects_chunked() is False


def test_do_post_actually_invokes_the_chunked_guard(server):
    """WIRING, over a real socket - the unit tests above cannot see this.

    A mutation run proved the point: deleting the call from `do_POST` left
    every `_rejects_chunked` unit test green, which is
    `feedback_guard_on_nondefault_call_path_is_untested` exactly. An unrouted
    path is used deliberately so the guard's 411 is distinguishable from the
    404 that routing would otherwise give, and so no handler (and no LLM
    spawn) runs.
    """
    sock = socket.create_connection(("127.0.0.1", server.server_address[1]),
                                    timeout=6)
    try:
        sock.sendall(
            b"POST /api/no-such-route HTTP/1.1\r\nHost: x\r\n"
            b"Transfer-Encoding: chunked\r\n\r\n2\r\n{}\r\n0\r\n\r\n"
        )
        status_line = sock.recv(200).split(b"\r\n")[0]
    finally:
        sock.close()
    assert b"411" in status_line, (
        f"do_POST did not reject the chunked body: {status_line!r}"
    )


# ---------------------------------------------------------------------------
# 3. Regression - RM-228 log-injection scrub for this file.
# ---------------------------------------------------------------------------

_CONTROL = set(range(0x00, 0x20)) | {0x7F} | set(range(0x80, 0xA0))
_ALLOWED = {0x09, 0x0A, 0x0D}


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record):
        self.messages.append(record.getMessage())


@pytest.fixture
def caplog_supervisor():
    from agents._supervisor_common import log as sup_log
    cap = _Capture()
    prev = sup_log.level
    sup_log.addHandler(cap)
    sup_log.setLevel(logging.INFO)
    yield cap
    sup_log.removeHandler(cap)
    sup_log.setLevel(prev)


def _raw_request(srv, raw: bytes) -> None:
    """Send bytes `http.client` would refuse to put on the wire."""
    sock = socket.create_connection(("127.0.0.1", srv.server_address[1]), timeout=5)
    try:
        sock.sendall(raw)
        try:
            sock.recv(256)
        except OSError:
            pass
    finally:
        sock.close()
    time.sleep(0.3)


def test_log_message_escapes_control_characters(server, caplog_supervisor):
    """A request target must not inject raw escapes into logs/YYYY-MM-DD.log.

    The stdlib does this inside `log_message` via `_control_char_table`, so an
    override silently opts out. The operator reads that file with cat/tail.
    """
    _raw_request(
        server,
        b"GET /\x1b[31mFAKE-ADMIN-OK\x1b[0m\x08\x08\x7f HTTP/1.1\r\nHost: x\r\n\r\n",
    )
    hits = [m for m in caplog_supervisor.messages if "FAKE-ADMIN-OK" in m]
    assert hits, "the request was not logged at all - the probe proves nothing"
    for msg in hits:
        offenders = [hex(ord(c)) for c in msg
                     if ord(c) in _CONTROL and ord(c) not in _ALLOWED]
        assert not offenders, (
            f"raw control bytes reached the log record: {offenders}"
        )


def test_log_message_still_names_the_peer(server, caplog_supervisor):
    """The peer half of RM-228 was already correct here - pin it.

    This override calls `address_string()` where some siblings do not. It is
    asserted so a future edit to add scrubbing cannot quietly drop attribution
    on a 0.0.0.0-bound port.
    """
    _get(server, "/ok.txt")
    hits = [m for m in caplog_supervisor.messages if "ok.txt" in m]
    assert hits, "request not logged"
    assert any("127.0.0.1" in m for m in hits), (
        "log line does not name the peer: " + repr(hits)
    )
