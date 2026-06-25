"""
tests/snapshot_panels/conftest.py
Mock HTTP server + Playwright browser fixtures for panel snapshot tests.

Architecture:
  _MockServer: ThreadingHTTPServer that serves web/ static files and intercepts
  /api/* with fixture-driven responses. /api/state-stream sends an SSE envelope
  (health + state) so panels render immediately without waiting for the HTTP
  fallback (which kicks in only after 4 s).
"""
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

WEB_DIR = Path(__file__).parent.parent.parent / "web"
FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _make_handler(store: dict) -> type:
    """Return an HTTP handler class bound to the shared fixture store."""

    class _Handler(SimpleHTTPRequestHandler):
        # HTTP/1.1 keep-alive is the core of the at-scale flake fix. The default
        # (HTTP/1.0) closes the TCP connection after EVERY request, so each page
        # boot (index.html + main.js + ~15 ES module / CSS / JSON fetches) churns
        # ~15 ephemeral ports into TIME_WAIT. Across ~274 pages that is several
        # thousand sockets stuck in TIME_WAIT (~120 s on Windows), which exhausts
        # the ~16k dynamic-port pool partway through the suite; new connections
        # then stall and a fresh page's fetches time out before its render lands
        # (the tail files flaked for exactly this reason while passing isolated).
        # With keep-alive every context reuses ONE persistent connection, so the
        # suite opens ~274 sockets total instead of thousands. Every buffered
        # response sends a correct Content-Length (keeps the connection reusable);
        # the streamed SSE response opts out via an explicit Connection: close.
        protocol_version = "HTTP/1.1"

        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(WEB_DIR), **kwargs)

        def log_message(self, *_):  # silence access log during tests
            pass

        def do_POST(self):  # noqa: N802
            # Consume body to keep connection clean, return empty JSON.
            length = int(self.headers.get("Content-Length", 0))
            if length:
                self.rfile.read(length)
            self._send_json({})

        def do_GET(self):  # noqa: N802
            p = self.path.split("?")[0]
            if p == "/api/state-stream":
                self._send_sse()
            elif p == "/api/state":
                self._send_json(store["data"])
            elif p in ("/api/health", "/api/health/all"):
                mode = store["data"].get("mode_key", "client")
                self._send_json({
                    "alive": True, "pid": 9999, "mode": mode,
                    "has_game": mode != "client",
                    "aram_mode": mode == "aram",
                    "arena_mode": mode == "arena",
                    "brawl_mode": mode == "brawl",
                    "tft_mode": mode == "tft",
                    "last_reload_ok": True,
                })
            elif p.startswith("/api/"):
                self._send_json({})
            else:
                super().do_GET()

        def _send_json(self, obj: object) -> None:
            body = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _send_sse(self) -> None:
            """Stream a StateResponse SSE event so panels render immediately.

            main.js setupStateStream() expects raw StateResponse JSON
            (mode_key + coach), NOT the WS envelope format (type/mode/payload).
            Send one event with the full fixture dict, then hold the connection
            open so EventSource treats it as a live stream rather than a
            buffered one-shot response.

            HOLD MECHANISM (at-scale flake fix, CI/Linux-safe): the connection
            is held by a heartbeat loop that writes an SSE comment (":\\n\\n",
            which EventSource silently ignores) every poll slice and EXITS the
            instant that write raises - i.e. the moment the owning test's browser
            context closes and disconnects the socket. That releases the server
            thread promptly (no zombie 15 s-sleep threads piling up and starving
            the single ThreadingHTTPServer's request pool late in a full-suite
            run) WITHOUT ever closing the stream proactively. An earlier attempt
            closed the stream when a shared generation counter advanced; that
            raced the page's own store mutations and closed the stream mid-render
            on the Linux CI runner (spike_markers / ds_relscore / overlay_combat /
            header_single_row flaked), so the close here is driven ONLY by the
            client disconnect, never by server-side state. A hard ceiling bounds a
            truly-abandoned connection.
            """
            import time as _time
            event_data = json.dumps(store["data"])
            body = f"data: {event_data}\n\n".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            # SSE is an unbounded stream (no Content-Length) so it cannot be a
            # reusable keep-alive connection - mark it close. Every OTHER response
            # stays keep-alive (HTTP/1.1 + Content-Length), which is what
            # collapses the suite's socket churn (the TIME_WAIT flake above).
            self.send_header("Connection", "close")
            self.close_connection = True
            self.end_headers()
            try:
                self.wfile.write(body)
                self.wfile.flush()
                # Hold open until the client disconnects (the test's context
                # closes at test end -> the next heartbeat write raises) or the
                # ceiling hits. The ceiling is generous so it never fires during
                # a normal test; disconnect is the real release trigger.
                deadline = _time.monotonic() + 30.0
                while _time.monotonic() < deadline:
                    _time.sleep(0.25)
                    self.wfile.write(b":\n\n")  # SSE keep-alive comment (ignored)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    return _Handler


class _MockServer:
    def __init__(self) -> None:
        self._store: dict = {"data": {}}
        self._server: ThreadingHTTPServer | None = None
        self.url: str = ""

    def set_fixture(self, name: str) -> None:
        path = FIXTURE_DIR / f"{name}.json"
        self._store["data"] = json.loads(path.read_text(encoding="utf-8"))

    def start(self) -> None:
        handler_cls = _make_handler(self._store)
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
        port = self._server.server_address[1]
        self.url = f"http://127.0.0.1:{port}"
        t = threading.Thread(target=self._server.serve_forever, daemon=True)
        t.start()

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()


@pytest.fixture(scope="session")
def mock_server():
    srv = _MockServer()
    srv.start()
    yield srv
    srv.stop()


_WS_STUB = """
// Prevent the dashboard's WebSocket from connecting to the real supervisor
// (:8891) during snapshot tests.  The WS would deliver live game state from
// the host machine and override the fixture, causing non-deterministic
// body[data-mode] and flaky is_visible() failures.
// Stub fires onclose immediately so the reconnect loop backs off without
// ever sending a message.
(function () {
    const _Orig = window.WebSocket;
    window.WebSocket = function FakeWS(url) {
        this.readyState = 0; // CONNECTING
        this.onopen    = null;
        this.onclose   = null;
        this.onerror   = null;
        this.onmessage = null;
        const self = this;
        setTimeout(function () {
            self.readyState = 3; // CLOSED
            if (self.onclose) self.onclose({ code: 1006, reason: "stubbed" });
        }, 20);
    };
    window.WebSocket.prototype.send  = function () {};
    window.WebSocket.prototype.close = function () {};
    // Expose CLOSING/CLOSED constants so main.js guard checks work.
    window.WebSocket.CONNECTING = 0;
    window.WebSocket.OPEN       = 1;
    window.WebSocket.CLOSING    = 2;
    window.WebSocket.CLOSED     = 3;
})();
"""


@pytest.fixture(scope="session")
def pw_browser():
    with sync_playwright() as pw:
        b = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        yield b
        b.close()
