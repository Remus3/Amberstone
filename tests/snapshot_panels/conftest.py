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
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

WEB_DIR = Path(__file__).parent.parent.parent / "web"
FIXTURE_DIR = Path(__file__).parent / "fixtures"

# Deterministic /api/personal-build response for the champ-select fixtures
# (my_champion = 222 / Jinx). The compute_personal_build dict shape (no `ok`
# field); positive + negative lifts exercise both bar/lift signs. Lets the
# champ-select view tests render the personal best-build card headlessly.
_PERSONAL_BUILD_FIXTURE = {
    "champion": "Jinx", "champion_id": 222, "mode": "aram",
    "games": 42, "win_rate": 0.52, "baseline_win_rate": 0.52,
    "confidence": "ok",
    "items": [
        {"item_id": 3031, "name": "Infinity Edge", "games": 30, "wins": 19,
         "win_rate": 0.633, "adj_win_rate": 0.60, "lift": 0.08,
         "is_boots": False},
        {"item_id": 6672, "name": "Kraken Slayer", "games": 24, "wins": 15,
         "win_rate": 0.625, "adj_win_rate": 0.585, "lift": 0.065,
         "is_boots": False},
        {"item_id": 3094, "name": "Rapid Firecannon", "games": 18, "wins": 10,
         "win_rate": 0.556, "adj_win_rate": 0.54, "lift": 0.02,
         "is_boots": False},
        {"item_id": 3006, "name": "Berserker's Greaves", "games": 35,
         "wins": 18, "win_rate": 0.514, "adj_win_rate": 0.515, "lift": -0.005,
         "is_boots": True},
        {"item_id": 3036, "name": "Lord Dominik's Regards", "games": 12,
         "wins": 5, "win_rate": 0.417, "adj_win_rate": 0.475, "lift": -0.045,
         "is_boots": False},
    ],
    "most_common_build": [3031, 6672, 3094, 3006],
    "source": "rewind_history.db",
}

# Deterministic /api/cs-archetype-pick response for the champ-select fixtures
# (my_champion = 222 / Jinx -> carry). Lets the read-only combat-style archetype
# chip (R89) render headlessly on the My Pick card. Shape mirrors
# dashboard.routes_archetype._serve_archetype_get: {ok, champion, pick{...},
# archetypes}; the chip reads pick.primary.
_ARCHETYPE_PICK_FIXTURE = {
    "ok": True,
    "champion": "Jinx",
    "pick": {"primary": "carry", "secondary": "", "source": "default"},
    "archetypes": ["carry", "bruiser", "tank", "mage", "assassin", "enchanter"],
}


# Deterministic /api/draft-elo response for the B-OVL-4 chip tests. Shape
# mirrors dashboard/routes_draft_elo.py's success payload (the `?breakdown=1`
# form the frontend always requests), trimmed to the keys draft_elo.js reads:
# ok / predicted_wr / team_score / sample{min_solo,min_pair} / top_contributions.
#
# Deliberately a BAD band with a LOW sample density (predicted_wr 0.38 < the
# 0.42 red threshold; min_solo 4 < 10) so one payload exercises BOTH colour
# lanes the overlay must re-map: `.de-wr.de-band-red` and `.de-sample-low`.
#
# OPT-IN, not a default: store["draft_elo"] starts as None and the route then
# answers {"ok": false}, which is exactly what an unstubbed /api/* returned
# before this existed. A test that wants a populated chip calls
# mock_server.set_draft_elo(DRAFT_ELO_BAD_BAND) and resets it afterwards, so
# every other snapshot page keeps rendering the empty chip it always did.
DRAFT_ELO_BAD_BAND = {
    "ok": True,
    "ally": {"champs": [24, 64, 103, 22, 412], "total": -21.0},
    "enemy": {"champs": [122, 121, 157, 51, 555], "total": 21.0},
    "team_score": -42.0,
    "predicted_wr": 0.38,
    "sample": {"min_solo": 4, "min_pair": 1, "min_matchup": 0},
    "queue_ids": [420],
    "top_contributions": [
        {"kind": "enemy-pair", "a": 122, "b": 121, "delta": -18.0, "n": 7},
        {"kind": "matchup", "a": 24, "b": 122, "delta": -13.0, "n": 5},
        {"kind": "ally-pair", "a": 22, "b": 412, "delta": 6.0, "n": 9},
    ],
}

# Same shape, a GOOD band with a HIGH sample density - the control case the
# bad-band assertions are read against (green must stay green in both shells).
DRAFT_ELO_GOOD_BAND = {
    "ok": True,
    "ally": {"champs": [24, 64, 103, 22, 412], "total": 33.0},
    "enemy": {"champs": [122, 121, 157, 51, 555], "total": -22.0},
    "team_score": 55.0,
    "predicted_wr": 0.63,
    "sample": {"min_solo": 44, "min_pair": 12, "min_matchup": 6},
    "queue_ids": [420],
    "top_contributions": [
        {"kind": "ally-pair", "a": 22, "b": 412, "delta": 21.0, "n": 31},
        {"kind": "matchup", "a": 24, "b": 122, "delta": 12.0, "n": 18},
        {"kind": "enemy-pair", "a": 121, "b": 157, "delta": -4.0, "n": 12},
    ],
}


def _make_handler(store: dict) -> type:
    """Return an HTTP handler class bound to the shared fixture store."""

    class _Handler(SimpleHTTPRequestHandler):
        # HTTP/1.1 keep-alive is the at-scale flake fix - but ONLY on Windows,
        # and this platform scoping is load-bearing (do not make it
        # unconditional). The default HTTP/1.0 closes the TCP connection after
        # EVERY request, so each page boot (index.html + main.js + ~15 ES module
        # / CSS / JSON fetches plus champion/item PNGs) churns dozens of ephemeral
        # ports into TIME_WAIT. Across ~274 pages that is thousands of sockets
        # stuck in TIME_WAIT (~120 s on Windows), exhausting the ~16k Windows
        # dynamic-port pool partway through the suite; a fresh page's fetches then
        # stall and time out before its render lands (the non-deterministic
        # 5/10/27-failure local flake). Keep-alive lets each context reuse one
        # persistent connection (~274 sockets total). Linux does NOT have this
        # flake (larger ephemeral range + TIME_WAIT recycling), so it stays on
        # HTTP/1.0: on the Linux CI runner keep-alive instead STALLS the render
        # tests - the gitignored ddragon image mirror is absent so champion/item
        # PNGs 404, and a 404 send_error on a persistent connection raises
        # BrokenPipe and wedges the small keep-alive connection pool, leaving
        # panels half-rendered (spike_markers / ds_relscore / overlay_combat /
        # header_single_row / player_gpi timed out, CI run 28159713805). The flake
        # is Windows-only, so the fix is too; CI keeps the proven HTTP/1.0 path.
        protocol_version = "HTTP/1.1" if sys.platform == "win32" else "HTTP/1.0"

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
            elif p == "/api/personal-build":
                self._send_json(_PERSONAL_BUILD_FIXTURE)
            elif p == "/api/cs-archetype-pick":
                self._send_json(_ARCHETYPE_PICK_FIXTURE)
            elif p == "/api/draft-elo":
                # Opt-in stub (see DRAFT_ELO_BAD_BAND). Unset -> the not-ok
                # answer the generic /api/ fallthrough used to give, so the
                # chip renders its empty state exactly as before.
                self._send_json(
                    store.get("draft_elo") or {"ok": False, "error": "no fixture"}
                )
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

            The hold is a plain bounded sleep (the long-proven behavior). Two
            earlier iterations tried to release the held thread promptly - a
            generation-gated close and a heartbeat-disconnect close - and BOTH
            raced the page render on the Linux CI runner (the stream closed or
            churned mid-render and 4-5 render tests timed out). The SSE thread is
            a daemon and the response is Connection: close, so a lingering sleep
            costs only a short-lived idle thread - not worth a render-timing risk.
            """
            import time as _time
            event_data = json.dumps(store["data"])
            body = f"data: {event_data}\n\n".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            # SSE is an unbounded stream (no Content-Length) so it cannot be a
            # reusable keep-alive connection - mark it close. This matters only on
            # the Windows HTTP/1.1 keep-alive path (it stops the server trying to
            # reuse a streaming socket); on the HTTP/1.0 default it is a harmless
            # no-op (HTTP/1.0 closes after every response anyway).
            self.send_header("Connection", "close")
            self.close_connection = True
            self.end_headers()
            try:
                self.wfile.write(body)
                self.wfile.flush()
                # Hold open so the browser's EventSource processes the event as a
                # stream rather than a buffered one-shot response.
                _time.sleep(15)
            except (BrokenPipeError, ConnectionResetError):
                pass

    return _Handler


class _MockServer:
    def __init__(self) -> None:
        self._store: dict = {"data": {}, "draft_elo": None}
        self._server: ThreadingHTTPServer | None = None
        self.url: str = ""

    def set_fixture(self, name: str) -> None:
        path = FIXTURE_DIR / f"{name}.json"
        self._store["data"] = json.loads(path.read_text(encoding="utf-8"))

    def set_draft_elo(self, payload: dict | None) -> None:
        """Arm (or clear) the /api/draft-elo stub. None restores the not-ok
        answer, which is what every page that does not opt in still sees."""
        self._store["draft_elo"] = payload

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
