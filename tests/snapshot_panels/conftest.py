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
        # HTTP/1.1 keep-alive is the core of the at-scale flake fix. The
        # default (HTTP/1.0) closes the TCP connection after EVERY request, so
        # each page boot - index.html + main.js + ~15 ES module / CSS / JSON
        # fetches - churns ~15 ephemeral ports into TIME_WAIT. Across ~274
        # pages that is several thousand sockets stuck in TIME_WAIT (~120 s on
        # Windows), which exhausts the ~16k dynamic-port pool partway through
        # the suite; new connections then stall and a fresh page's fetches
        # time out before its render lands (the tail files flaked for exactly
        # this reason while passing in isolation). With keep-alive every
        # context reuses ONE persistent connection for all its requests, so
        # the suite opens ~274 sockets total instead of thousands. Correct
        # Content-Length on every buffered response (below) keeps the
        # connection reusable; the streamed SSE response opts out via an
        # explicit Connection: close.
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

            Isolation (at-scale flake fix): the hold is a short bounded poll
            that releases the instant the store's generation advances. Each
            test bumps `store["gen"]` at start (see _reset_mock_store), so a
            lingering SSE thread from the PRIOR test terminates immediately at
            the next test boundary instead of sleeping a blind 15 s. That
            stops zombie 15 s-sleep threads from accumulating and starving the
            single ThreadingHTTPServer's request threads late in a full-suite
            run (the failure mode: a fresh page's static-asset GETs queue
            behind dozens of held connections and time out before boot).
            """
            import time as _time
            opened_gen = store.get("gen", 0)
            event_data = json.dumps(store["data"])
            body = f"data: {event_data}\n\n".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            # SSE streams until the server closes the socket (no
            # Content-Length), so it cannot be a reusable keep-alive
            # connection - tell the client this one closes. Every OTHER
            # response keeps the connection alive (HTTP/1.1 + Content-Length),
            # which is what collapses the suite's socket churn.
            self.send_header("Connection", "close")
            self.close_connection = True
            self.end_headers()
            try:
                self.wfile.write(body)
                self.wfile.flush()
                # Hold open so the browser's EventSource treats this as a live
                # stream (not a buffered one-shot), but release as soon as the
                # owning test ends (generation advanced) or a hard ceiling is
                # reached. Poll in small slices so the thread frees promptly.
                deadline = _time.monotonic() + 8.0
                while _time.monotonic() < deadline:
                    if store.get("gen", 0) != opened_gen:
                        break
                    _time.sleep(0.05)
            except (BrokenPipeError, ConnectionResetError):
                pass

    return _Handler


class _MockServer:
    def __init__(self) -> None:
        # `gen` is a monotonic generation counter. Bumping it signals every
        # in-flight SSE connection to release (see _Handler._send_sse), which
        # is how a prior test's held stream is torn down at the next test
        # boundary instead of lingering for a blind 15 s.
        self._store: dict = {"data": {}, "gen": 0}
        self._server: ThreadingHTTPServer | None = None
        self.url: str = ""

    def _bump_gen(self) -> None:
        self._store["gen"] = self._store.get("gen", 0) + 1

    def reset(self) -> None:
        """Per-test isolation hook: clear the fixture and advance the
        generation so any SSE stream still held open by the previous test
        stops serving stale data and its server thread exits promptly."""
        self._store["data"] = {}
        self._bump_gen()

    def set_fixture(self, name: str) -> None:
        path = FIXTURE_DIR / f"{name}.json"
        self._store["data"] = json.loads(path.read_text(encoding="utf-8"))
        self._bump_gen()

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


@pytest.fixture(autouse=True)
def _reset_mock_store(request):
    """Per-test isolation against the session-scoped mock server.

    The mock server holds ONE mutable fixture store shared across all ~274
    Playwright tests. Tests mutate it via set_fixture()/direct assignment and
    each opens an SSE stream the server holds open. Without a per-test reset a
    lingering SSE connection (or a slow HTTP /api/state fallback) from the
    prior test could read the store AFTER the next test mutated it, and the
    held streams piled up and starved the single server's request threads at
    full-suite scale - the source of the non-deterministic 5/10/27-failure
    flake. Resetting (clear + generation bump) at the START of every test that
    uses the server guarantees a clean store and forces the previous test's
    held SSE thread to release immediately. Only activates for tests that
    actually request the `mock_server` fixture; browser-free unit tests in
    this dir (node escaping checks, ASCII guards) are untouched.
    """
    if "mock_server" in request.fixturenames:
        request.getfixturevalue("mock_server").reset()
    yield


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
