"""S7 (2026-06-10) - :8889 must serve requests CONCURRENTLY.

Operator report: champ-select dashboard updates + build/rune pushes to the
League client were slow. Root cause class: vision_server bound a plain
``HTTPServer``, so one slow in-flight handler (in-process self-grab GDI
BitBlt + JPEG ~100-400ms, or a Sonnet/OCR inference call) serialized EVERY
other request behind it - /latest-lcu, /latest-liveclient and the LCU
command queue all stall for the slow handler's full duration.

Guards:
1. vision_server binds ThreadingHTTPServer (drift guard on the source -
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
    def test_binds_threading_http_server(self) -> None:
        src = VS_INIT.read_text(encoding="utf-8")
        self.assertIn("from http.server import ThreadingHTTPServer", src)
        self.assertRegex(src, re.compile(
            r"ThreadingHTTPServer\(\(\"0\.0\.0\.0\", PORT\), Handler\)"))
        self.assertIn("daemon_threads = True", src)
        self.assertNotRegex(
            src, re.compile(r"(?<!Threading)HTTPServer\(\("),
            "plain HTTPServer binding reintroduced - serializes the relay "
            "+ LCU command queue behind slow vision handlers (S7)")


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
