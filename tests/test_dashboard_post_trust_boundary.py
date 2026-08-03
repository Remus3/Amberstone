"""Lane 8 deep audit of ``dashboard/api_schema.py`` - the declared validation
boundary for every dashboard POST body - and the ``dashboard/_handler.py``
body reader that actually stands in front of it.

Selected by risk criterion 1 (it is the trust boundary for request bodies RC
does not author) and criterion 4 (load-bearing, zero LEDGER mentions, no
dedicated test module). Recorded expectation before reading: ``_AllowExtra``
on request models where ``_ForbidExtra`` belongs, and missing range/length
bounds. Measured 2026-08-03:

**REFUTED, and recorded so it is not re-investigated.** The `= {}` / `= []`
field defaults are NOT shared-mutable-default bugs. Pydantic v2 deep-copies
defaults per instance; two instances were constructed and mutated
independently to confirm it. This is the dataclass intuition being wrong here.

**REAL FINDING 1 - the module docstring is false in two independent ways.**
``api_schema.py:5`` states "POST body models use extra=forbid (strict input
gates)". Measured against ``_dispatch._REQUEST_MODELS``: 4 of the 6 wired POST
paths use ``extra="allow"``. And none of the six is a *gate* at all -
``_dispatch._validate_request_body`` logs a WARNING per field error and
**never raises**, then ``dispatch_post`` calls the route with the unchanged
body regardless. The models are a logging decoration, not an input gate.

An earlier draft of this note claimed "the routes defend themselves, so
nothing is currently exploitable". **The verifier gate REFUTED that**, and
the counterexample was the very route cited as the defence:
``_serve_command_post`` whitelists the command STRING but never checks the
body is a dict, so ``[1,2,3]`` raised an uncaught ``AttributeError`` at
``routes_state.py:516`` and the client got NO HTTP response at all. Same for
``/api/input``; ds-preview, build-order and speak degraded to 500. Only
``/api/team-context/refresh`` checked. See ``TestNonDictBody`` below - the
claim was wrong, the hole was real, and it is now closed at the boundary.

**REAL FINDING 3 - a non-dict body reached every route.** Fixed in
``do_POST``: dict-or-400, once, at the trust boundary rather than in ~40
handlers. Verified first that zero POST routes consume a positional body.

**REAL FINDING 2 - a negative Content-Length wedges a handler thread.**
``_handler.do_POST`` caps the body at 1 MiB with ``if n > _MAX_POST_BYTES``,
but ``int("-1")`` is -1, which passes that check; ``self.rfile.read(n) if n
else b""`` then treats -1 as truthy and reads to EOF. Measured against the
real ``Handler`` on an ephemeral port: the request HUNG with no response, and
completed in 0.00s the instant the client shut down its write side - the
read-to-EOF signature. ``dashboard/server.py:54`` serves on
``ThreadingHTTPServer`` (one thread per connection) and ``:35`` binds
``HOST = "::"``, so the cost is one pinned thread per request from anywhere on
the LAN or tailnet, and ``RC_DASH_TOKEN`` is unset in this deployment so the
control-endpoint auth does not gate it either.

This is the SAME defect closed in ``vision_server/_http.py`` on 2026-08-03
(LEDGER 1177). The sweep that fixed it did not look across files, so the
dashboard - the wider surface of the two - kept it.

**SCOPE LIMIT, stated because the verifier measured it and an unqualified
claim here would be false.** This fix removes one TRIGGER, not the class. A
perfectly legal ``Content-Length: 1048575`` (under the cap) with zero body
sent pins a handler thread exactly the same way, released only when the
client goes away - measured against the FIXED handler at 4.01s no-response,
0.18s after SHUT_WR. The real fix is a read timeout on the connection, which
is a behaviour change for every dashboard client including the 500 ms poll
and the supervisor proxy stream, so it is filed as RM-152 rather than bolted
on here. Do NOT read this module as proof the dashboard is slowloris-safe.
"""
from __future__ import annotations

import socket
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from dashboard._handler import Handler


class _Server:
    """The real dashboard Handler on a real socket - no mocks in the path."""

    def __enter__(self) -> "_Server":
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.srv.daemon_threads = True
        self.port = self.srv.server_address[1]
        self.thread = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.srv.shutdown()
        self.srv.server_close()
        self.thread.join(timeout=5)

    def post(self, content_length, body: bytes, timeout: float = 4.0):
        """Send a hand-built POST so a malformed header survives the client.

        Returns (status_line, seconds) or (None, seconds) on no response.
        """
        s = socket.create_connection(("127.0.0.1", self.port), timeout=10)
        try:
            hdr = ("POST /api/command HTTP/1.1\r\nHost: x\r\n"
                   "Content-Type: application/json\r\n"
                   f"Content-Length: {content_length}\r\n\r\n").encode()
            s.sendall(hdr + body)
            t0 = time.time()
            s.settimeout(timeout)
            try:
                return s.recv(200).splitlines()[0], time.time() - t0
            except socket.timeout:
                return None, time.time() - t0
        finally:
            s.close()


class TestNegativeContentLength:
    """A malformed Content-Length must be refused, not read to EOF."""

    def test_negative_content_length_does_not_hang(self):
        with _Server() as srv:
            status, elapsed = srv.post(-1, b'{"command":"refresh"}')
        assert status is not None, (
            f"no response in {elapsed:.1f}s - the handler thread is pinned "
            "reading to EOF and only the client can release it")
        assert b"400" in status, f"expected a 400 refusal, got {status!r}"

    def test_a_normal_body_is_unaffected(self):
        """Positive control - the guard must not break the working path."""
        body = b'{"command":"bogus"}'
        with _Server() as srv:
            status, _ = srv.post(len(body), body)
        assert status is not None and b"400" in status, \
            "an unknown command should still reach the route and 400"

    def test_oversize_is_still_capped(self):
        """Positive control - the pre-existing 1 MiB cap must survive."""
        with _Server() as srv:
            status, _ = srv.post(99_999_999, b"")
        assert status is not None and b"413" in status, \
            f"the oversize cap regressed: {status!r}"

    def test_non_numeric_content_length_is_refused(self):
        with _Server() as srv:
            status, _ = srv.post("abc", b"")
        assert status is not None and b"400" in status, \
            f"a non-numeric Content-Length must 400, got {status!r}"


class TestNonDictBody:
    """A valid-JSON but non-dict body must 400, not raise out of the route.

    Found by the verifier gate REFUTING this audit's own claim that "the
    routes defend themselves". They defend against an unknown command
    STRING; none of them checked the body was a dict at all. Measured
    pre-fix: POST /api/command with `[1,2,3]` raised an uncaught
    AttributeError and the client got NO response whatsoever.
    """

    @pytest.mark.parametrize("raw", [b"[1,2,3]", b'"hello"', b"7", b"null"])
    def test_non_dict_body_is_refused_cleanly(self, raw):
        with _Server() as srv:
            status, _ = srv.post(len(raw), raw)
        assert status is not None, (
            "no response at all - the route raised out of the handler")
        assert b"400" in status, f"expected 400 for {raw!r}, got {status!r}"

    def test_empty_body_still_reaches_the_route(self):
        """Positive control - an empty body becomes {} and must still route."""
        with _Server() as srv:
            status, _ = srv.post(0, b"")
        assert status is not None and b"400" in status, \
            "empty body should reach _serve_command_post and 400 on no command"


class TestSchemaContractIsHonest:
    """Pin what the validation layer ACTUALLY does, not what it claims."""

    def test_docstring_does_not_claim_a_gate_it_does_not_provide(self):
        """The contract is read off disk, per the standing rule that a
        contract test must read the contract rather than restate it."""
        import dashboard.api_schema as _mod
        # Anchor on the module's real location - a relative path here
        # silently depends on CWD being the repo root (verifier note).
        src = Path(_mod.__file__).read_text(encoding="utf-8")
        head = src.split('"""')[1]
        assert "strict input gates" not in head, (
            "api_schema.py still advertises 'strict input gates'. "
            "_dispatch._validate_request_body never raises, so no model here "
            "gates anything - the word invites a route author to skip their "
            "own validation.")
        assert "soft" in head.lower(), (
            "the docstring must say the validation is soft-warn, so a reader "
            "learns the truth from the module they are editing")

    def test_extra_policy_per_wired_post_path_is_pinned(self):
        """4 of 6 allow extra. That may be the right call for forward-compat,
        but it must be a DELIBERATE one - this test makes a change visible."""
        from dashboard._dispatch import _REQUEST_MODELS
        actual = {p: m.model_config.get("extra")
                  for p, m in _REQUEST_MODELS.items()}
        assert actual == {
            "/api/input": "forbid",
            "/api/command": "forbid",
            "/api/ds-preview": "allow",
            "/api/build-order": "allow",
            "/api/speak": "allow",
            "/api/team-context/refresh": "allow",
        }, f"the extra-policy census changed: {actual}"

    def test_validation_is_soft_and_that_is_pinned(self):
        """An invalid body must NOT raise out of the validator - callers
        depend on the soft contract. If this ever becomes strict, it is a
        breaking change that must be made deliberately."""
        from dashboard._dispatch import _validate_request_body
        _validate_request_body("/api/command", {"command": 123, "bogus": True})
        _validate_request_body("/api/input", {})
        _validate_request_body("/api/command", "not-a-dict")


class TestMatchDbMcpSibling:
    """Third instance of the same defect, found by the cross-file sweep.

    Lower severity than the dashboard - ``tools/ds_matchdb_mcp_server.py``
    binds loopback :8861 and ``_check_auth`` runs before the body read - but
    the identical read-to-EOF, on the same ThreadingHTTPServer shape.
    """

    def test_negative_content_length_does_not_hang(self):
        from tools import ds_matchdb_mcp_server as mcp

        srv = ThreadingHTTPServer(("127.0.0.1", 0), mcp._Handler)
        srv.daemon_threads = True
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=10)
            try:
                hdr = ("POST /mcp HTTP/1.1\r\nHost: x\r\n"
                       f"Authorization: Bearer {mcp.AUTH_TOKEN}\r\n"
                       "Content-Type: application/json\r\n"
                       "Content-Length: -1\r\n\r\n").encode()
                s.sendall(hdr + b'{"method":"tools/list","id":1}')
                s.settimeout(4)
                try:
                    status = s.recv(200).splitlines()[0]
                except socket.timeout:
                    pytest.fail("no response in 4s - worker thread pinned "
                                "reading to EOF on a negative Content-Length")
                assert b"200" in status or b"400" in status, \
                    f"unexpected status {status!r}"
            finally:
                s.close()
        finally:
            srv.shutdown()
            srv.server_close()
            t.join(timeout=5)


@pytest.mark.parametrize("field_defaults_are_isolated", [True])
def test_pydantic_v2_deep_copies_mutable_defaults(field_defaults_are_isolated):
    """REFUTED hypothesis, pinned so it is not re-investigated.

    `items: list[str] = []` looks like the classic shared-mutable-default
    bug. It is not one in pydantic v2 - defaults are deep-copied per
    instance. Recorded as a negative result with a live proof.
    """
    from dashboard.api_schema import BuildOrderRequest, StateResponse
    a = BuildOrderRequest(champion="Jinx")
    b = BuildOrderRequest(champion="Ashe")
    a.items.append("3031")
    assert b.items == [], "pydantic v2 no longer isolates defaults"
    s1, s2 = StateResponse(), StateResponse()
    s1.coach["k"] = 1
    assert s2.coach == {}
