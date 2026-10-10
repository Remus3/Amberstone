"""S7 (2026-06-10) - :8889 must serve requests CONCURRENTLY.

Operator report: champ-select dashboard updates + build/rune pushes to the
League client were slow. Root cause class: vision_server bound a plain
``HTTPServer``, so one slow in-flight handler (in-process self-grab GDI
BitBlt + JPEG ~100-400ms, or a Sonnet/OCR inference call) serialized EVERY
other request behind it - /latest-lcu, /latest-liveclient and the LCU
command queue all stall for the slow handler's full duration.

Guards:
1. vision_server binds a concurrent server - ThreadingHTTPServer until
   RM-735, the pre-started worker pool since (drift guard on the source -
   ``main()`` blocks forever so the binding cannot be exercised directly).
2. Concurrency property: two overlapping requests against a
   ThreadingHTTPServer+Handler instance complete in ~one slow-handler
   duration, not two (the pre-S7 serial behavior).
"""
from __future__ import annotations

import re
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VS_INIT = REPO / "vision_server" / "__init__.py"


class VisionServerThreadingSourceGuard(unittest.TestCase):
    def test_binds_a_concurrent_server(self) -> None:
        src = VS_INIT.read_text(encoding="utf-8")
        # RM-735 (2026-10-10) replaced the thread-per-request
        # ThreadingHTTPServer with a pre-started worker pool
        # (vision_server/_pool.py) - still concurrent, but its accept loop
        # cannot park in Thread.start. main() binds through make_server;
        # RM-150 keeps the address as (host, PORT) from _bind_host(), pinned
        # by tests/test_vision_server_bind_rm150.py. What S7 guards is a
        # CONCURRENT server, so the pin follows the class.
        self.assertIn("from ._pool import PooledHTTPServer", src)
        self.assertRegex(src, re.compile(r"s = make_server\(host, PORT\)"))
        self.assertRegex(src, re.compile(
            r"PooledHTTPServer\(\(host, port\), handler or Handler\)"))
        self.assertNotRegex(
            src, re.compile(r"(?<![A-Za-z])HTTPServer\(\("),
            "plain HTTPServer binding reintroduced - serializes the relay "
            "+ LCU command queue behind slow vision handlers (S7)")

    def test_the_pool_is_concurrent(self) -> None:
        from vision_server import _pool
        self.assertGreaterEqual(_pool.DEFAULT_WORKERS, 4)


class _SlowThenFastHandler:
    """Factory for a BaseHTTPRequestHandler that sleeps on /slow only."""

    SLOW_S = 0.6

    @classmethod
    def build(cls):
        from http.server import BaseHTTPRequestHandler

        class H(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 (stdlib name)
                if self.path == "/slow":
                    time.sleep(cls.SLOW_S)
                body = b'{"ok": true}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a) -> None:
                pass

        return H


class VisionServerConcurrencyProperty(unittest.TestCase):
    def test_fast_request_not_blocked_by_slow(self) -> None:
        srv = ThreadingHTTPServer(("127.0.0.1", 0),
                                  _SlowThenFastHandler.build())
        srv.daemon_threads = True
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            slow_started = threading.Event()

            def hit_slow() -> None:
                slow_started.set()
                urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/slow", timeout=5).read()

            slow_thread = threading.Thread(target=hit_slow, daemon=True)
            slow_thread.start()
            slow_started.wait(timeout=2)
            time.sleep(0.05)  # let /slow enter its handler sleep

            t0 = time.monotonic()
            urllib.request.urlopen(
                f"http://127.0.0.1:{port}/fast", timeout=5).read()
            fast_elapsed = time.monotonic() - t0
            slow_thread.join(timeout=5)

            # Serial server: fast waits out the full slow sleep (>=0.5s).
            # Threaded server: fast returns in milliseconds.
            self.assertLess(
                fast_elapsed, _SlowThenFastHandler.SLOW_S * 0.5,
                f"fast request took {fast_elapsed:.3f}s behind /slow - "
                "server is serializing requests")
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()
