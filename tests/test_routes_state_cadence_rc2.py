"""RC2 P6.3 - UI responsiveness: render cadence + no-store idempotency.

The IO timing map (docs/_archive/2026-07-28-research-consolidation/RC2_RESEARCH_io_timing_map.md, lever L4)
found the dashboard update latency is governed by two cadences that MUST move
together: the SSE re-build tick (_SSE_TICK_S) and the shared /api/state TTL
cache (dashboard/routes_state.py). At 1.0s they doubled the operator's
worst-case "champ select updates slow" latency. RC2 6.3 halves both to 0.5s
(operator-approved E12/L4), makes them a SINGLE env-tunable constant so they
can never drift apart (the line-96 "must match" invariant becomes structural),
and clamps to a busy-loop floor. No new connections (SSE is push); the 2x
build/s is bounded by the _deterministic_coaching 3.0s DS-call TTL.

Also locks the no-store idempotency contract: every /api/state response carries
Cache-Control: no-store (memory feedback_dashboard_render_idempotency) so a
browser/proxy never serves a stale render.
"""
from __future__ import annotations

import importlib
import io
import time
from unittest import mock

import dashboard.routes_state as rs
from dashboard._handler import Handler


# -- render cadence (L4): single env-tunable, tick == ttl -----------------

def test_cadence_default_halved_responsiveness_floor():
    # Default cadence is the RC2 6.3 halved value; must not regress slower
    # than 1.0s (the pre-RC2 latency the timing map flagged).
    assert 0 < rs._STATE_CADENCE_S <= 1.0
    assert rs._STATE_CADENCE_S == 0.5


def test_sse_tick_equals_state_ttl_invariant():
    # The SSE tick and the TTL-cache window are the SAME constant so they
    # cannot drift (previously two hardcoded 1.0s literals).
    assert rs._SSE_TICK_S == rs._STATE_CADENCE_S


def test_cadence_env_override():
    with mock.patch.dict("os.environ", {"RC_STATE_CADENCE_SEC": "0.25"}):
        mod = importlib.reload(rs)
        try:
            assert mod._STATE_CADENCE_S == 0.25
            assert mod._SSE_TICK_S == 0.25
        finally:
            importlib.reload(importlib.import_module("dashboard.routes_state"))


def test_cadence_clamps_busy_loop_floor():
    # A zero / negative / sub-floor override must clamp up, not spin a
    # 0s-sleep SSE loop or a 0s TTL (every tick rebuilds).
    with mock.patch.dict("os.environ", {"RC_STATE_CADENCE_SEC": "0"}):
        mod = importlib.reload(rs)
        try:
            assert mod._STATE_CADENCE_S >= 0.1
        finally:
            importlib.reload(importlib.import_module("dashboard.routes_state"))


def test_cadence_garbage_falls_back_to_default():
    with mock.patch.dict("os.environ", {"RC_STATE_CADENCE_SEC": "not-a-number"}):
        mod = importlib.reload(rs)
        try:
            assert mod._STATE_CADENCE_S == 0.5
        finally:
            importlib.reload(importlib.import_module("dashboard.routes_state"))


# -- TTL compare is wired to the tunable (not an orphaned 1.0 literal) -----

def test_state_ttl_compare_honors_shrunk_cadence():
    rs._STATE_CACHE_PAYLOAD = None
    rs._STATE_CACHE_TS = 0.0
    orig = rs._STATE_CADENCE_S
    rs._STATE_CADENCE_S = 0.05
    try:
        with mock.patch.object(rs, "_timed_build_state",
                               side_effect=[{"n": 1}, {"n": 2}]) as bs:
            p1 = rs._state_payload_cached()      # builds n=1
            time.sleep(0.07)                     # past the 0.05 window
            p2 = rs._state_payload_cached()      # rebuilds n=2
            assert bs.call_count == 2
            assert p1 != p2
    finally:
        rs._STATE_CADENCE_S = orig
        rs._STATE_CACHE_PAYLOAD = None
        rs._STATE_CACHE_TS = 0.0


def test_state_ttl_dedupes_within_window():
    rs._STATE_CACHE_PAYLOAD = None
    rs._STATE_CACHE_TS = 0.0
    orig = rs._STATE_CADENCE_S
    rs._STATE_CADENCE_S = 5.0
    try:
        with mock.patch.object(rs, "_timed_build_state",
                               side_effect=[{"n": 1}, {"n": 2}]) as bs:
            p1 = rs._state_payload_cached()
            p2 = rs._state_payload_cached()
            assert bs.call_count == 1
            assert p1 == p2
    finally:
        rs._STATE_CADENCE_S = orig
        rs._STATE_CACHE_PAYLOAD = None
        rs._STATE_CACHE_TS = 0.0


# -- no-store idempotency: every /api/state response is uncacheable --------

def _capture_handler():
    h = Handler.__new__(Handler)
    h.headers = {}
    h.connection = object()  # no .cipher -> no TLS/HSTS branch
    sent = []
    h.send_response = lambda code: sent.append(("__status__", code))
    h.send_header = lambda k, v: sent.append((k, v))
    h.end_headers = lambda: sent.append(("__end__", None))
    h.wfile = io.BytesIO()
    h._sent = sent
    return h


def _header_map(h):
    return {k: v for k, v in h._sent if k not in ("__status__", "__end__")}


def test_serve_state_response_is_no_store():
    rs._STATE_CACHE_PAYLOAD = None
    rs._STATE_CACHE_TS = 0.0
    h = _capture_handler()
    with mock.patch.object(rs, "_timed_build_state", return_value={"ok": 1}):
        rs._serve_state(h)
    hdrs = _header_map(h)
    assert hdrs.get("Cache-Control") == "no-store"
    rs._STATE_CACHE_PAYLOAD = None
    rs._STATE_CACHE_TS = 0.0


def test_send_default_cache_control_is_no_store():
    # The handler-wide default _serve_state relies on (passes no override).
    h = _capture_handler()
    h._send(200, b"{}", "application/json")
    assert _header_map(h).get("Cache-Control") == "no-store"
