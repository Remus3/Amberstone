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
            """
            import time as _time
            event_data = json.dumps(store["data"])
            body = f"data: {event_data}\n\n".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            try:
                self.wfile.write(body)
                self.wfile.flush()
                # Hold open so the browser's EventSource processes the event
                # as a stream rather than a buffered one-shot response.
                _time.sleep(15)
            except (BrokenPipeError, ConnectionResetError):
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
