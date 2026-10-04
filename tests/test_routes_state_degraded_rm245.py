"""RM-245: four routes_state.py degraded-mode paths that reported SUCCESS.

(a) SSE sent `data: {}` on a failed build, which the client applies as
    authoritative EMPTY state; (b) /api/asset-stamp answered 200 mtime=0 on
    failure; (c) a slow build defeated the TTL cache herd (no in-flight
    dedupe); (d) cost_ok failed OPEN when the cost probe errored.
"""
from __future__ import annotations

import io
import json
import sys
import threading
import time
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import dashboard.routes_state as rs  # noqa: E402


class _H:
    def __init__(self):
        self.wfile = io.BytesIO()
        self.connection = None
        self.sent = None

    def send_response(self, code):
        self.code = code

    def send_header(self, *a):
        pass

    def end_headers(self):
        pass

    def _send(self, status, payload, ctype):
        self.sent = (status, payload, ctype)


def _reset_cache():
    rs._STATE_CACHE_PAYLOAD = None
    rs._STATE_CACHE_TS = 0.0


def test_a_sse_failed_build_sends_no_data_event():
    _reset_cache()
    h = _H()
    with mock.patch.object(rs, "_state_payload_cached",
                           side_effect=RuntimeError("boom")), \
            mock.patch.object(rs, "_SSE_MAX_DURATION_S", 0.2), \
            mock.patch.object(rs, "_SSE_TICK_S", 0.05):
        rs._serve_state_stream(h)
    out = h.wfile.getvalue()
    assert b"data:" not in out, out
    assert b": state-build-failed" in out  # keep-alive comment, ignored by EventSource


def test_a_sse_good_build_still_streams():
    _reset_cache()
    h = _H()
    with mock.patch.object(rs, "_state_payload_cached", return_value=b'{"x":1}'), \
            mock.patch.object(rs, "_SSE_MAX_DURATION_S", 0.15), \
            mock.patch.object(rs, "_SSE_TICK_S", 0.05):
        rs._serve_state_stream(h)
    assert b'data: {"x":1}' in h.wfile.getvalue()


def test_b_asset_stamp_failure_is_not_a_200():
    h = _H()
    with mock.patch.object(rs, "_asset_stamp_mtime", side_effect=OSError("x")):
        rs._serve_asset_stamp(h)
    assert h.sent[0] >= 500
    assert json.loads(h.sent[1])["ok"] is False


def test_c_concurrent_misses_build_once():
    _reset_cache()
    calls = [0]
    lock = threading.Lock()

    def slow_build():
        with lock:
            calls[0] += 1
        time.sleep(0.6)  # slower than the 0.5 s TTL, as measured live
        return {"n": calls[0]}

    results = []
    with mock.patch.object(rs, "_timed_build_state", slow_build):
        ts = [threading.Thread(target=lambda: results.append(rs._state_payload_cached()))
              for _ in range(8)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(10)
    assert len(results) == 8
    assert calls[0] == 1, f"{calls[0]} builds for 8 concurrent requests"
    assert len(set(results)) == 1


def test_d_cost_probe_failure_is_not_green():
    class _R:
        def __init__(self, body):
            self._b = body

        def read(self):
            return self._b

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(url, timeout=None):
        if "8889" in url:
            return _R(b'{"alive": true}')
        return _R(b'{"status": "ok"}')

    def broken_tracker():
        raise RuntimeError("cost db gone")

    h = _H()
    with mock.patch.object(rs, "read_json", return_value={"alive": True}), \
            mock.patch.object(rs.urllib.request, "urlopen", fake_urlopen), \
            mock.patch("core.cost_tracker.get_tracker", broken_tracker), \
            mock.patch.object(rs, "_agent6_audit_outcomes_ex", return_value=([], True)):
        rs._serve_health_all(h)
    body = json.loads(h.sent[1])
    assert "banner" not in body["cost"]
    assert body["status"] != "green", body["status"]
