"""RM-321: every remaining `log_message` override must escape control chars.

`BaseHTTPRequestHandler.log_message` escapes C0 / DEL / C1 inside the method,
so an override silently loses it. Each test drives the REAL handler class over
a socket with an ESC-bearing request target and asserts no raw control byte
reaches the log record, and that the record names the peer. One test per file
on purpose - a shared parametrized guard is how coverage quietly narrows.
"""
from __future__ import annotations

import logging
import socket
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_BAD = set(range(0x00, 0x20)) - {9, 10, 13} | set(range(0x7F, 0xA0))
_PROBE = b"GET /\x1b[31mFAKE-ADMIN-OK\x1b[0m\x08\x08\x7f HTTP/1.1\r\nHost: x\r\n\r\n"


class _Grab(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.msgs: list[str] = []

    def emit(self, record):
        self.msgs.append(record.getMessage())


def _drive(handler_cls, logger_name: str) -> list[str]:
    lg = logging.getLogger(logger_name)
    grab = _Grab()
    old_level = lg.level
    lg.addHandler(grab)
    lg.setLevel(logging.DEBUG)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        s = socket.create_connection(("127.0.0.1", srv.server_address[1]), timeout=5)
        try:
            s.sendall(_PROBE)
            try:
                s.recv(4096)
            except OSError:
                pass
        finally:
            s.close()
        deadline = time.time() + 3
        while time.time() < deadline and not any("FAKE-ADMIN-OK" in m for m in grab.msgs):
            time.sleep(0.05)
    finally:
        srv.shutdown()
        srv.server_close()
        lg.removeHandler(grab)
        lg.setLevel(old_level)
    hits = [m for m in grab.msgs if "FAKE-ADMIN-OK" in m]
    assert hits, f"request was not logged by {logger_name}: probe proves nothing"
    return hits


def _assert_clean(hits):
    for m in hits:
        bad = [hex(ord(c)) for c in m if ord(c) in _BAD]
        assert not bad, f"raw control bytes reached the record: {bad} in {m!r}"
        assert "127.0.0.1" in m, f"record does not name the peer: {m!r}"


def test_mc_handler_scrubs():
    from mc.handler import Handler
    _assert_clean(_drive(Handler, "rc.mc.handler"))


def test_daemon_slayer_server_scrubs():
    from agents.daemon_slayer.server import Handler
    _assert_clean(_drive(Handler, "daemon_slayer.server"))


def test_ds_matchdb_mcp_server_scrubs():
    sys.path.insert(0, str(ROOT / "tools"))
    import ds_matchdb_mcp_server as m
    _assert_clean(_drive(m._Handler, "ds-matchdb-mcp"))


def test_vision_server_http_scrubs():
    from vision_server._http import Handler
    _assert_clean(_drive(Handler, "moon_vision"))


def test_core_fallback_matches_stdlib_table():
    from core.log_scrub import CONTROL_CHAR_TABLE, scrub_log
    sample = "".join(chr(i) for i in range(0, 0xB0)) + "\\x1b"
    assert CONTROL_CHAR_TABLE is not None
    assert scrub_log(sample) == scrub_log(sample, None)
