"""tests/test_gated_live_probe_relay_auth.py

`tools/gated_live_probe.py` is the sanctioned pre-flight for live-gated rows.
It reported `vision frame_bytes=0 / frame_dead=True` unconditionally, and that
false negative was written into `docs/LIVE_GAME_GATED_SYNC.md` as a PRECONDITION
that blocked G3-13 (ARAM Mayhem augment OCR) from ever being attempted.

Two independent defects, both in the probe and neither in the vision server:

1. `_RELAY_BASE` used `https://`, but the vision server on :8889 is plain HTTP
   (`modes/shared_vision.py:25`). Every request failed at the TLS layer.
2. Even over HTTP the relay requires an `X-RC-Token` header
   (`modes/shared_vision.py:_capture_screen`), and the probe sent none, so it
   got 401.

Measured 2026-08-02 during a live ARAM Mayhem game: the probe's own method
returned 0 bytes while an authenticated HTTP request to the SAME endpoint at
the SAME moment returned a 243396-byte frame aged 0.9s. The relay was healthy
the whole time.

`_RELAY_BASE` feeds BOTH `/latest-frame` and `/latest-liveclient`, so
`relay_present` was wrong for the same reason.
"""
from __future__ import annotations

import http.server
import sys
import threading
from pathlib import Path

import pytest

from tools import gated_live_probe as glp

TOKEN_HEADER = "X-RC-Token"
BODY = b"x" * 512


class _TokenGatedHandler(http.server.BaseHTTPRequestHandler):
    """Mimics the relay: 401 without the token, payload with it."""

    def do_GET(self):  # noqa: N802 - stdlib naming
        if self.headers.get(TOKEN_HEADER) != self.server.expected_token:
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b"unauthorized")
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(BODY)))
        self.end_headers()
        self.wfile.write(BODY)

    def log_message(self, *_a):  # silence the test server
        return


@pytest.fixture
def relay():
    srv = http.server.HTTPServer(("127.0.0.1", 0), _TokenGatedHandler)
    srv.expected_token = glp._relay_token()
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def test_script_entrypoint_does_not_crash():
    """The regression my package-import tests could not see.

    Every other test here does `from tools import gated_live_probe`, which runs
    with the repo root already on sys.path. The REAL invocation is
    `python tools/gated_live_probe.py`, where it is NOT - and the first version
    of the `core.vision_token` import raised ModuleNotFoundError and killed the
    tool, violating its own documented "never an exception" contract. Exercise
    the actual entry point as a subprocess.
    """
    import subprocess

    root = Path(__file__).resolve().parent.parent
    r = subprocess.run(
        [sys.executable, str(root / "tools" / "gated_live_probe.py"), "--json"],
        capture_output=True, text=True, timeout=120, cwd=str(root),
    )

    assert "ModuleNotFoundError" not in r.stderr
    assert "Traceback" not in r.stderr, r.stderr[-800:]


def test_relay_token_is_fail_soft(monkeypatch):
    """A broken token source must degrade to "", never raise."""
    monkeypatch.setitem(__import__("sys").modules, "core.vision_token", None)

    assert isinstance(glp._relay_token(), str)


def test_relay_base_is_http_not_https():
    """The vision server is plain HTTP; https can never connect."""
    assert glp._RELAY_BASE.startswith("http://")


def test_relay_token_is_the_canonical_one():
    """Must reuse core.vision_token, not a second hardcoded copy."""
    from core.vision_token import get_vision_token

    assert glp._relay_token() == get_vision_token()


def test_authenticated_probe_reads_the_frame(relay):
    """The regression: an authenticated GET must report real bytes."""
    n, err = glp._get_nbytes(f"{relay}/latest-frame")

    assert err is None
    assert n == len(BODY)


def test_unauthenticated_probe_is_what_produced_the_false_negative(relay):
    """Pin the old behaviour so the cause stays legible.

    Without the token the same endpoint yields no payload - which the probe
    then reported as `frame_dead=True`.
    """
    n, err = glp._get_nbytes(f"{relay}/latest-frame", token=None)

    assert (n or 0) == 0 or err is not None


def test_frame_dead_is_not_reported_for_a_healthy_relay(relay, monkeypatch):
    """End to end: collect() must not call a healthy relay dead.

    Both bases point at the stub. The dashboard half is deliberately NOT the
    live :8888 - an earlier draft passed `glp._DASH_BASE` and tripped the RF5
    hermeticity guard, because reaching the live dashboard lets a running RC
    write `data/*.jsonl` inside the test window. A probe test must not touch
    production. `/api/state` returns non-JSON here, so `state` is None and
    `collect` short-circuits, which is fine: the vision block is populated
    before that branch.
    """
    monkeypatch.setattr(glp, "_RELAY_BASE", relay)
    out = glp.collect(relay, relay)

    assert out["vision"]["frame_bytes"] == len(BODY)
    assert out["vision"]["frame_dead"] is False
