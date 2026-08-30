"""RM-152: a request-body read deadline for the dashboard and the DS engine.

LEDGER 1181 closed one TRIGGER of the slowloris class - a NEGATIVE
Content-Length that read to EOF. It explicitly did not close the class, and
said so: a perfectly legal ``Content-Length: 1048575`` with zero body bytes
sent pins a ``ThreadingHTTPServer`` handler thread just the same, released
only when the client goes away. Measured against the FIXED handler on
2026-08-03: no response after 4.01s, released 0.18s after the client's
SHUT_WR. ``dashboard/server.py:35`` binds ``HOST = "::"``, so the reach is
anywhere on the LAN or the tailnet, and the body read runs BEFORE the
``RC_DASH_TOKEN`` check at ``_handler.py:342`` so a token would not gate it.

WHY THE DEADLINE IS SCOPED TO THE BODY READ AND NOT TO THE CONNECTION.
A ``socket.settimeout`` held for the life of the connection is the obvious
fix and it is the wrong one - but NOT for the reason this row was filed on,
and the difference is recorded here so the next reader does not inherit the
wrong model.

The filed expectation was truncation: ``/api/state-stream``
(``routes_state.py:288``) is a 600-second SSE response writing on
``h.connection`` with idle gaps up to 15s, and ``_proxy_to_supervisor``
(``_handler.py:152``) writes an upstream payload back down the same socket.
Both were expected to be cut mid-write by a lifetime deadline. MEASURED
2026-08-04 with ``Handler.timeout = 0.75`` armed: neither breaks. An 8 MiB
proxy payload arrived byte-complete even at a reader that stalled 3s
mid-stream, and the SSE stream still delivered 6 frames. The send buffer
absorbs the write, so SO_SNDTIMEO never trips.

The real breakage is on the READ side. socketserver arms ``Handler.timeout``
on the connection in ``setup()``, which deadlines the request line and
headers as well: a client slow to speak, or one whose headers arrive in two
packets with a gap, is aborted outright (ConnectionAbortedError at the
client, versus ``200 OK`` under the body-scoped deadline). The 2 Hz pollers
open a fresh connection per request - the handler answers HTTP/1.0, so there
is no keep-alive - and every one of them would be exposed to that.

So the deadline is armed immediately before ``rfile.read`` of the request
body and restored immediately after, in a ``finally``. Nothing outside that
window sees a timeout.
``test_a_client_slow_to_send_its_request_line_is_not_dropped`` is the test
that fails under the alternative; the proxy and SSE tests are end-to-end
regression pins and are labelled as such rather than oversold.
"""
from __future__ import annotations

import hashlib
import http.client
import http.server
import io
import socket
import threading
import time
from http.server import ThreadingHTTPServer

import pytest

import dashboard._handler as dash_handler
from dashboard._handler import Handler

# Small enough that the refusal tests finish fast, large enough that a real
# body written by a real client always lands inside it. The SHIPPED default
# is pinned separately by test_default_timeout_is_bounded_and_sane.
_TEST_DEADLINE_S = 0.75


class _RawClient:
    """Hand-built HTTP over a raw socket - the only way to declare a body and
    then decline to send it."""

    def __init__(self, port: int) -> None:
        self.port = port

    def post_and_stall(self, path: str, content_length: int, sent: bytes,
                       wait: float) -> tuple[bytes | None, float]:
        """Declare `content_length`, send only `sent`, then go quiet.

        Returns (first response line or None, seconds until it arrived).
        The socket is held open for the whole wait so a fix that merely
        depends on the client hanging up cannot pass this.
        """
        s = socket.create_connection(("127.0.0.1", self.port), timeout=10)
        try:
            hdr = (f"POST {path} HTTP/1.1\r\nHost: x\r\n"
                   "Content-Type: application/json\r\n"
                   f"Content-Length: {content_length}\r\n\r\n").encode()
            s.sendall(hdr + sent)
            t0 = time.time()
            s.settimeout(wait)
            try:
                return s.recv(400).splitlines()[0], time.time() - t0
            except socket.timeout:
                return None, time.time() - t0
        finally:
            s.close()

    def post(self, path: str, body: bytes,
             wait: float = 10.0) -> tuple[bytes | None, float]:
        return self.post_and_stall(path, len(body), body, wait)

    def get_full(self, path: str, wait: float = 15.0) -> tuple[bytes, bytes]:
        """Return (status line, body) reading until the server closes."""
        s = socket.create_connection(("127.0.0.1", self.port), timeout=10)
        try:
            s.sendall(f"GET {path} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
            s.settimeout(wait)
            buf = b""
            try:
                while True:
                    chunk = s.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
            except socket.timeout:
                pass
            if not buf:
                return b"", b""
            head, _, body = buf.partition(b"\r\n\r\n")
            return head.splitlines()[0], body
        finally:
            s.close()


class _Live:
    """A real handler class on a real ephemeral socket - no mocks in the path,
    and never a port RC actually uses."""

    def __init__(self, handler_cls) -> None:
        self.handler_cls = handler_cls

    def __enter__(self) -> _RawClient:
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), self.handler_cls)
        self.srv.daemon_threads = True
        self.thread = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.thread.start()
        return _RawClient(self.srv.server_address[1])

    def __exit__(self, *exc: object) -> None:
        self.srv.shutdown()
        self.srv.server_close()
        self.thread.join(timeout=5)


@pytest.fixture
def short_dash_deadline(monkeypatch: pytest.MonkeyPatch) -> float:
    monkeypatch.setattr(dash_handler, "_BODY_READ_TIMEOUT_S", _TEST_DEADLINE_S)
    return _TEST_DEADLINE_S


# --------------------------------------------------------------- refusal


class TestDashboardSlowBodyIsRefused:
    """Acceptance 3: a legal Content-Length with no body must be refused
    WITHIN the deadline, on wall time, with the client still connected."""

    def test_zero_body_with_large_legal_length_is_refused_in_time(
            self, short_dash_deadline: float) -> None:
        with _Live(Handler) as c:
            status, elapsed = c.post_and_stall(
                "/api/command", 1_048_575, b"", wait=8.0)
        assert status is not None, (
            f"no response in {elapsed:.2f}s - the handler thread is still "
            "pinned on a body that will never arrive (RM-152)")
        assert elapsed < short_dash_deadline + 4.0, (
            f"refused, but only after {elapsed:.2f}s - the deadline is not "
            "bounding the read")
        assert b"408" in status, f"expected a 408 refusal, got {status!r}"

    def test_partial_body_then_stall_is_refused_in_time(
            self, short_dash_deadline: float) -> None:
        """The trickle case - bytes arrive, then stop. A per-read timeout
        that is re-armed on every chunk would never fire here."""
        with _Live(Handler) as c:
            status, elapsed = c.post_and_stall(
                "/api/command", 65_536, b'{"command":"re', wait=8.0)
        assert status is not None, (
            f"no response in {elapsed:.2f}s on a stalled partial body")
        assert elapsed < short_dash_deadline + 4.0, \
            f"refused only after {elapsed:.2f}s"
        assert b"408" in status, f"expected 408, got {status!r}"

    def test_default_timeout_is_bounded_and_sane(self) -> None:
        """The shipped value, not the patched one. A LAN/loopback 1 MiB body
        lands in milliseconds, so anything past ~30s is not a bound."""
        default = dash_handler._BODY_READ_TIMEOUT_S
        assert 1.0 <= default <= 30.0, \
            f"the shipped body-read deadline is {default!r}"


# --------------------------------------------------- legitimate clients


class TestLegitimateDashboardClientsSurvive:
    """Acceptance 2. A test that only proves the refusal is half the job -
    the deadline is a behaviour change for EVERY client, so the clients that
    must not notice it are pinned here."""

    def test_a_normal_post_is_unaffected(
            self, short_dash_deadline: float) -> None:
        body = b'{"command":"bogus"}'
        with _Live(Handler) as c:
            status, elapsed = c.post("/api/command", body)
        assert status is not None and b"400" in status, \
            f"a normal POST must still reach the route: {status!r}"
        assert elapsed < 5.0, f"a 19-byte body took {elapsed:.2f}s"

    def test_500ms_poll_survives_across_gaps_longer_than_the_deadline(
            self, short_dash_deadline: float) -> None:
        """The dashboard polls at 2 Hz on fresh connections (the handler
        answers HTTP/1.0, so there is no keep-alive to preserve). Every gap
        below is longer than the patched deadline; a connection-lifetime
        timeout would start dropping these."""
        with _Live(Handler) as c:
            statuses = []
            for _ in range(6):
                head, _body = c.get_full("/api/ui-version", wait=8.0)
                statuses.append(head)
                time.sleep(0.5)
            heavy, _ = c.get_full("/api/state", wait=20.0)
        assert all(s and b"200" in s for s in statuses), \
            f"a 2 Hz poll started failing under the deadline: {statuses}"
        assert heavy and b"200" in heavy, \
            f"/api/state - the real 500 ms poll - failed: {heavy!r}"

    def test_a_client_slow_to_send_its_request_line_is_not_dropped(
            self, short_dash_deadline: float) -> None:
        """THE discriminating test - the one that fails under the alternative
        design, and the reason the other two in this class are not enough.

        MEASURED, and it corrects the premise this row was filed on. The
        expected failure mode of a connection-lifetime timeout was a
        TRUNCATED proxy or SSE response. That did not reproduce: with
        ``Handler.timeout = 0.75`` armed, an 8 MiB proxy payload came back
        byte-complete even to a reader that stalled 3s mid-stream, and the
        SSE stream still delivered 6 frames. Windows buffers the send, so
        the write never blocked long enough to trip SO_SNDTIMEO.

        What DOES break is the read side, and it breaks hard: socketserver
        arms ``Handler.timeout`` on the connection in ``setup()``, so it also
        deadlines the REQUEST LINE and header read. A client that connects
        and then takes longer than the deadline to send - or splits its
        headers across two packets with a gap, which any real network can do
        - was aborted outright: ConnectionAbortedError at the client, versus
        ``200 OK`` under the body-scoped deadline. Both cases measured on
        this handler on 2026-08-04.
        """
        with _Live(Handler) as c:
            s = socket.create_connection(("127.0.0.1", c.port), timeout=10)
            try:
                # Connect, then stall well past the deadline before speaking.
                # The abort can surface on either side of the exchange, so
                # the whole thing is guarded rather than just the recv.
                time.sleep(short_dash_deadline * 2)
                s.sendall(b"GET /api/ui-version HTTP/1.1\r\n")
                time.sleep(short_dash_deadline * 2)  # headers split by a gap
                s.sendall(b"Host: x\r\n\r\n")
                s.settimeout(10.0)
                got = s.recv(400)
            except (socket.timeout, ConnectionResetError,
                    ConnectionAbortedError) as exc:
                pytest.fail(
                    f"a slow-to-speak client was dropped ({type(exc).__name__}) "
                    "- the deadline is armed for the life of the connection, "
                    "not for the body read")
            finally:
                s.close()
        assert got, "the connection was closed without a response"
        assert b"200" in got.splitlines()[0], \
            f"slow-to-speak client got {got.splitlines()[0]!r}"

    def test_supervisor_proxy_response_is_not_truncated(
            self, short_dash_deadline: float, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The case that made RM-152 non-trivial: the proxy waits on an
        upstream and then writes the whole payload back down the client
        socket. Here the upstream takes 3x the body deadline and the payload
        is 256 KiB.

        Honest scope: this is an end-to-end regression pin, NOT a
        discriminator. The mutation probe above showed the naive design
        delivers this intact too. Kept because it is the client the row
        named, and because it does catch a deadline that fires on the
        response path. Bound to a fake upstream on an ephemeral port so it
        never touches the live supervisor at :8890.
        """
        payload = bytes(range(256)) * 1024  # 256 KiB, not compressible to noise
        digest = hashlib.sha256(payload).hexdigest()
        upstream_delay = short_dash_deadline * 3.0

        class _Upstream(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a: object) -> None:
                pass

            def do_GET(self) -> None:
                time.sleep(upstream_delay)
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        with _Live(_Upstream) as up:
            monkeypatch.setattr(
                dash_handler, "SUPERVISOR_ORIGIN",
                f"http://127.0.0.1:{up.port}")
            with _Live(Handler) as c:
                status, body = c.get_full("/api/trending", wait=20.0)
        assert status and b"200" in status, \
            f"the supervisor proxy failed under the deadline: {status!r}"
        assert len(body) == len(payload), (
            f"proxy body truncated: {len(body)} of {len(payload)} bytes - the "
            "deadline leaked outside the request-body read")
        assert hashlib.sha256(body).hexdigest() == digest, \
            "proxy body corrupted"

    def test_sse_stream_outlives_the_deadline(
            self, short_dash_deadline: float) -> None:
        """/api/state-stream holds a connection for up to 600s and idles up
        to 15s between frames. It must still be open well past the body
        deadline. Also a regression pin rather than a discriminator - see
        the measurement note on the slow-request-line test.
        """
        with _Live(Handler) as c:
            s = socket.create_connection(("127.0.0.1", c.port), timeout=10)
            try:
                s.sendall(b"GET /api/state-stream HTTP/1.1\r\nHost: x\r\n\r\n")
                s.settimeout(3.0)
                buf = b""
                start = time.time()
                # Stay past several deadline windows, then stop as soon as
                # the stream has proven itself. The hard cap keeps a loaded
                # box from turning a slow state build into a failure.
                min_span = short_dash_deadline * 3
                while time.time() - start < 15.0:
                    try:
                        chunk = s.recv(65536)
                    except socket.timeout:
                        if time.time() - start >= min_span:
                            break
                        continue
                    if not chunk:
                        break
                    buf += chunk
                    if b"data: " in buf and time.time() - start >= min_span:
                        break
            finally:
                s.close()
        assert b"200" in buf.split(b"\r\n", 1)[0], \
            f"SSE never opened: {buf[:120]!r}"
        assert b"text/event-stream" in buf, "SSE content type missing"
        assert b"retry: 2000" in buf, \
            "the SSE preamble never arrived - the stream was cut short"
        assert b"data: " in buf, (
            "no SSE frame arrived while the body deadline was armed - the "
            "deadline is killing long-lived responses")


# ------------------------------------------------------- daemon slayer


class TestDaemonSlayerBodyRead:
    """agents/daemon_slayer/server.py:2836 _read_json_body had NO upper cap
    at all and no deadline - a strictly worse version of the same hole."""

    @staticmethod
    def _handler():
        """Every DS route reads the shared snapshot cache, so it has to be
        populated before the Handler will answer anything but a 500
        ("snapshot not loaded yet", server.py:185). start_server does this
        via _CACHE.set; we do the same without binding its socket."""
        from agents.daemon_slayer import server as ds

        if not getattr(TestDaemonSlayerBodyRead, "_snapshot_loaded", False):
            ds._CACHE.set(ds._load_default_snapshot())
            TestDaemonSlayerBodyRead._snapshot_loaded = True
        return ds.Handler

    def test_zero_body_with_large_legal_length_is_refused_in_time(
            self, monkeypatch: pytest.MonkeyPatch) -> None:
        from agents.daemon_slayer import server as ds

        monkeypatch.setattr(ds, "_BODY_READ_TIMEOUT_S", _TEST_DEADLINE_S)
        with _Live(self._handler()) as c:
            status, elapsed = c.post_and_stall("/stats", 1_000_000, b"", wait=8.0)
        assert status is not None, \
            f"no response in {elapsed:.2f}s - DS worker thread pinned"
        assert elapsed < _TEST_DEADLINE_S + 4.0, \
            f"refused only after {elapsed:.2f}s"
        assert b"408" in status, f"expected 408, got {status!r}"

    def test_oversize_content_length_is_capped(self) -> None:
        """The cap the dashboard has had since 2026-04-27 and DS never did.
        Must be refused on the HEADER, before a single body byte is read."""
        with _Live(self._handler()) as c:
            status, elapsed = c.post_and_stall("/stats", 99_999_999, b"", wait=8.0)
        assert status is not None, f"no response in {elapsed:.2f}s"
        assert b"413" in status, \
            f"an unbounded Content-Length was accepted: {status!r}"
        assert elapsed < 2.0, \
            "413 arrived only after waiting on the body - reject on the header"

    def test_a_normal_post_still_works(self) -> None:
        with _Live(self._handler()) as c:
            status, elapsed = c.post("/stats", b'{"champion":"Jinx"}', wait=20.0)
        assert status is not None and b"200" in status, \
            f"a legitimate DS POST regressed: {status!r}"
        assert elapsed < 15.0, f"DS /stats took {elapsed:.2f}s"

    def test_a_bad_body_still_produces_its_own_error(self) -> None:
        with _Live(self._handler()) as c:
            status, _ = c.post("/stats", b"{not json", wait=20.0)
        assert status is not None and b"400" in status, \
            f"malformed JSON must still 400, got {status!r}"


# --------------------------------------------------- no socket to arm


_NO_CONNECTION = object()


class TestBodyReadWithoutASocket:
    """The deadline must not become a NEW way for a request to fail.

    ``_read_body_deadlined`` runs AHEAD of the RC_DASH_TOKEN gate in
    ``do_POST``, and ``do_POST`` answers 400 bad_body to anything raised out
    of it. The first cut of this fix reached for ``self.connection``
    unconditionally, so every caller holding an in-memory rfile raised
    ``AttributeError`` there and was answered 400 - pre-empting the 401 that
    an unauthenticated control POST had earned, and taking all 7 tests in
    tests/test_control_endpoint_auth.py with it.

    The rule these pin: the deadline exists to stop a peer holding a socket
    open, so where there is no socket to arm there is nothing to defend and
    the read is simply performed. Restoring ``sock = self.connection`` fails
    every test below.
    """

    @staticmethod
    def _post_handler(path, body=b"{}", token_header=None,
                      connection=_NO_CONNECTION):
        """A Handler wired for do_POST with a staged body and, by default,
        no ``connection`` attribute at all - the shape
        tests/test_control_endpoint_auth.py builds."""
        h = Handler.__new__(Handler)
        headers = {"Content-Length": str(len(body))}
        if token_header is not None:
            headers["X-RC-Token"] = token_header
        # Real container, not a dict - see the note on _headers in
        # tests/test_control_endpoint_auth.py. A dict has no get_all().
        _hm = http.client.HTTPMessage()
        for _k, _v in headers.items():
            _hm[_k] = _v
        h.headers = _hm
        h.path = path
        h.rfile = io.BytesIO(body)
        if connection is not _NO_CONNECTION:
            h.connection = connection
        h._csrf_ok = lambda: True
        sent: list[tuple] = []
        h._send = lambda code, payload, ctype=None: sent.append((code, payload))
        return h, sent

    def test_body_read_failure_does_not_pre_empt_the_auth_reply(
            self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The acceptance case. An unauthenticated control POST is owed 401,
        and must still get it when the body read has no socket to arm."""
        monkeypatch.setenv("RC_DASH_TOKEN", "s3cret")
        h, sent = self._post_handler("/api/command")
        h.do_POST()
        assert sent, "do_POST answered nothing at all"
        assert sent[-1][0] == 401, (
            f"the body read pre-empted the auth gate: got {sent[-1]!r}, "
            "expected 401 unauthorized")

    def test_socketless_read_returns_the_staged_body(self) -> None:
        h, _ = self._post_handler("/api/command", body=b'{"a":1}')
        assert h._read_body_deadlined(7) == b'{"a":1}'

    def test_a_connection_that_is_not_a_socket_is_tolerated(self) -> None:
        """Present but unarmable is the same case as absent: a stand-in with
        no ``settimeout`` must not be dereferenced as if it were a socket."""
        h, _ = self._post_handler("/api/command", body=b'{"a":1}',
                                  connection=object())
        assert h._read_body_deadlined(7) == b'{"a":1}'

    def test_daemon_slayer_twin_has_the_same_tolerance(self) -> None:
        """Sibling sweep. The DS handler carries a byte-for-byte copy of this
        read, so it carries the defect unless it is fixed in the same pass."""
        from agents.daemon_slayer import server as ds

        h = ds.Handler.__new__(ds.Handler)
        h.headers = {"Content-Length": "10"}
        h.rfile = io.BytesIO(b'{"a":1234}trailing')
        assert h._read_json_body() == {"a": 1234}

    def test_daemon_slayer_drain_without_a_socket_is_a_no_op(self) -> None:
        from agents.daemon_slayer import server as ds

        h = ds.Handler.__new__(ds.Handler)
        h.headers = {"Content-Length": "4"}
        h.rfile = io.BytesIO(b"junk")
        h._drain_request_body()  # must not raise
        assert h.rfile.read() == b""


# The spec-doc half of RM-152 lives in tests/test_mc_s10_spec_doc_rm152.py.
# It must not live here: naming a tracked .md selects a module into
# .github/workflows/docs-guards.yml, whose install is deliberately minimal,
# and every test above needs the full route registry to answer a POST.
