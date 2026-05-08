# arch: /metrics Prometheus endpoint | section=dashboard | frozen=no
"""Prometheus `/metrics` exposition route (T3 #12).

Counters and histograms are bumped at their source modules
(`core/cost_tracker.py`, `core/coach_trace.py`); this module owns the
gauges that need a refresh at scrape-time and serves the text-format
exposition body.

Gauges read from already-canonical sources:
- `ops/runtime/health.json` for RC liveness + worker ages.
- `dashboard._bridge_log` for cross-Claude bridge silence.
- `core.decision_detector.DecisionStore` for pending decision count.
- `core.cost_tracker.daily_spend()` for today's USD ledger.
"""
import logging
import time

from core.prom_metrics import Gauge, render_all
from dashboard._context import read_json
from dashboard._dispatch import equals

# Eager import so the histograms / counters declared at module scope in
# these instrumentation files appear in /metrics even before the first
# coach call. Without this, scrapers wouldn't see the metric exists
# until traffic flows.
import core.cost_tracker  # noqa: F401
import core.coach_trace   # noqa: F401

log = logging.getLogger("rc.web_dashboard")

_G_RC_ALIVE = Gauge(
    "rc_alive",
    "1 if RC main reports alive in health.json, 0 otherwise.",
)
_G_UI_PULSE_AGE = Gauge(
    "rc_dashboard_ui_pulse_age_seconds",
    "Seconds since the last ui_pulse heartbeat (health.json ui_pulse_age_s).",
)
_G_GAME_POLL_AGE = Gauge(
    "rc_game_poll_worker_age_seconds",
    "Seconds since the last game-poll worker tick (health.json game_poll_worker_age_s).",
)
_G_BRIDGE_AGE = Gauge(
    "rc_bridge_gamepc_result_age_seconds",
    "Seconds since the last cross-Claude bridge result from Game-PC.",
)
_G_DECISIONS_PENDING = Gauge(
    "rc_decisions_pending",
    "Pending coachable decisions (current count from DecisionStore).",
)
_G_DAILY_SPEND_USD = Gauge(
    "rc_daily_spend_usd",
    "USD spend so far today (resets at local midnight).",
)
_G_DAILY_CALLS = Gauge(
    "rc_daily_calls",
    "API calls so far today (resets at local midnight).",
)


def _refresh_gauges() -> None:
    h = read_json("ops/runtime/health.json") or {}
    _G_RC_ALIVE.set(1.0 if h.get("alive") else 0.0)
    if h.get("ui_pulse_age_s") is not None:
        _G_UI_PULSE_AGE.set(float(h.get("ui_pulse_age_s") or 0.0))
    if h.get("game_poll_worker_age_s") is not None:
        _G_GAME_POLL_AGE.set(float(h.get("game_poll_worker_age_s") or 0.0))

    try:
        from dashboard._bridge_log import gamepc_result_age_s
        age = gamepc_result_age_s()
        if age is not None:
            _G_BRIDGE_AGE.set(age)
    except Exception as exc:
        log.debug("metrics bridge_age refresh: %s", exc)

    try:
        from core.decision_detector import DecisionStore
        _G_DECISIONS_PENDING.set(len(DecisionStore().list_pending()))
    except Exception as exc:
        log.debug("metrics decisions_pending refresh: %s", exc)

    try:
        from core.cost_tracker import get_tracker
        spend = get_tracker().daily_spend()
        _G_DAILY_SPEND_USD.set(float(spend.get("total_usd") or 0.0))
        _G_DAILY_CALLS.set(float(spend.get("calls") or 0))
    except Exception as exc:
        log.debug("metrics daily_spend refresh: %s", exc)


def _serve_metrics(h) -> None:
    t0 = time.monotonic()
    try:
        _refresh_gauges()
        body = render_all().encode("utf-8")
        log.debug("metrics rendered in %.1f ms (%d bytes)",
                  (time.monotonic() - t0) * 1000, len(body))
        h._send(200, body, "text/plain; version=0.0.4; charset=utf-8")
    except Exception as exc:
        log.warning("metrics: %s", exc)
        h._send(500, b"metrics_render_failed", "text/plain")


GET_ROUTES = [
    (equals("/metrics"), _serve_metrics),
]
POST_ROUTES = []
