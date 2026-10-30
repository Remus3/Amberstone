# arch: /metrics Prometheus endpoint | section=dashboard | frozen=no
"""Prometheus `/metrics` exposition route (T3 #12).

Counters and histograms are bumped at their source modules
(`core/cost_tracker.py`, `core/coach_trace.py`); this module owns the
gauges that need a refresh at scrape-time and serves the text-format
exposition body.

Gauges read from already-canonical sources:
- `ops/runtime/health.json` for RC liveness + worker ages.
- `core.decision_detector.DecisionStore` for pending decision count.
- `core.cost_tracker.daily_spend()` for today's USD ledger.

Every source is read independently and every value is validated before it
reaches a gauge (lane 8 s144 cycle 67): a junk field degrades only its own
gauge instead of 500ing the whole body, a non-finite or bool value is
rejected, and a value that is UNKNOWN this scrape (key absent or None, store
unreadable) clears its gauge, so a stale number is never served as current.
"""
import logging
import math
import time
from typing import Optional

from core.prom_metrics import Gauge, render_all
from dashboard._context import read_json
from dashboard._dispatch import equals

# Eager import so the histograms / counters declared at module scope in
# these instrumentation files appear in /metrics even before the first
# coach call. Without this, scrapers wouldn't see the metric exists
# until traffic flows.
import core.cost_tracker  # noqa: F401
import core.coach_trace   # noqa: F401
from core import riot_api_cache

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

# -- Riot API cache size (RM-153) ----------------------------------------
#
# data/riot_api_cache.db reached 3.3 GB unnoticed because nothing reported
# its size - stats() had no production callers at all. These gauges are that
# missing consumer, so the NEXT 3 GB is visible while it accumulates.
_CACHE_CAP_BYTES = riot_api_cache.DEFAULT_MAX_IMMUTABLE_BYTES

_G_CACHE_DISK_BYTES = Gauge(
    "rc_riot_api_cache_disk_bytes",
    "Bytes on disk for data/riot_api_cache.db including its WAL sidecars.",
)
_G_CACHE_IMMUTABLE_ROWS = Gauge(
    "rc_riot_api_cache_immutable_rows",
    "Rows in cache_immutable (Match-V5 details/timelines, Account-V1). "
    "These never expire by design.",
)
_G_CACHE_TTL_ROWS = Gauge(
    "rc_riot_api_cache_ttl_live_rows",
    "Unexpired rows in cache_ttl (League-V4 ranks, Champion-Mastery-V4).",
)
_G_CACHE_OVER_CAP = Gauge(
    "rc_riot_api_cache_over_cap",
    "1 if riot_api_cache.db is past the RM-153 size cap, 0 otherwise. "
    "Measured against DISK bytes (file + WAL sidecars), which is a strictly "
    "larger quantity than the payload bytes the planner caps - so this alarm "
    "leads plan_eviction rather than trailing it. Alarm only - eviction is "
    "opt-in and nothing calls it.",
)


def _num(value) -> Optional[float]:
    """`value` as a finite float, or None when it is not a usable number.

    Accepts int, float and numeric strings (float() accepted those before).
    Rejects bool (True is not an age of 1 s), every other type, and
    non-finite results: json.loads turns 1e400 into inf and accepts NaN /
    Infinity literals, and a non-finite gauge is not a measurement.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        f = float(value)
    except (ValueError, OverflowError):
        return None
    return f if math.isfinite(f) else None


def _set_or_clear(gauge: Gauge, value: Optional[float]) -> None:
    """Set a validated value, or clear the gauge when it is unknown."""
    if value is None:
        gauge.clear()
    else:
        gauge.set(value)


def _refresh_cache_gauges() -> None:
    """Size gauges for the Riot API cache. Cheap and fail-soft.

    Uses `stats_fast()`, never `stats()`: the latter's
    SUM(LENGTH(response_json)) was measured at 4.36-4.59s on the live 3.3 GB
    DB (8.37s cold) and would be paid on every scrape. `stats_fast()` rides
    covering-index counts plus a bare stat() instead.

    ASYMMETRY, DELIBERATE AND KNOWN. `_CACHE_CAP_BYTES` is compared here
    against DISK bytes, while `riot_api_cache.plan_eviction` applies the same
    constant to summed payload bytes. Those are not the same quantity - disk
    also carries page overhead, freelist and the WAL sidecars, so it is always
    the larger. Reconciling them would mean paying the scan this function
    exists to avoid, so the asymmetry is kept: the alarm fires at or before
    the planner would act, never after. Both sites say so.

    Each field is validated on its own, so one junk field no longer aborts
    the rest; an unknown disk size clears the over-cap alarm rather than
    leaving the previous verdict standing.
    """
    st = None
    try:
        st = riot_api_cache.get_cache().stats_fast()
    except Exception as exc:  # noqa: BLE001 - a scrape never 500s on the cache
        log.debug("metrics riot_api_cache refresh: %s", exc)
    if not isinstance(st, dict):
        st = {}
    disk = _num(st.get("disk_bytes"))
    _set_or_clear(_G_CACHE_DISK_BYTES, disk)
    _set_or_clear(_G_CACHE_IMMUTABLE_ROWS, _num(st.get("immutable_rows")))
    _set_or_clear(_G_CACHE_TTL_ROWS, _num(st.get("ttl_live_rows")))
    _set_or_clear(_G_CACHE_OVER_CAP,
                  None if disk is None
                  else (1.0 if disk > _CACHE_CAP_BYTES else 0.0))


def _refresh_health_gauges() -> None:
    h = read_json("ops/runtime/health.json")
    if not isinstance(h, dict):
        h = {}
    # Strict: the writer stores a real bool, and "false" / "0" are truthy.
    _G_RC_ALIVE.set(1.0 if h.get("alive") is True else 0.0)
    # game_poll_worker_age_s is None while the worker has never pulsed
    # (app/_health_monitor.py); that clears the gauge, never keeps the old age.
    _set_or_clear(_G_UI_PULSE_AGE, _num(h.get("ui_pulse_age_s")))
    _set_or_clear(_G_GAME_POLL_AGE, _num(h.get("game_poll_worker_age_s")))


def _refresh_decision_gauges() -> None:
    pending = None
    try:
        from core.decision_detector import DecisionStore
        pending = len(DecisionStore().list_pending())
    except Exception as exc:  # noqa: BLE001 - a scrape never 500s on the store
        log.debug("metrics decisions_pending refresh: %s", exc)
    _set_or_clear(_G_DECISIONS_PENDING, pending)


def _refresh_spend_gauges() -> None:
    spend = None
    try:
        from core.cost_tracker import get_tracker
        spend = get_tracker().daily_spend()
    except Exception as exc:  # noqa: BLE001 - a scrape never 500s on the ledger
        log.debug("metrics daily_spend refresh: %s", exc)
    if not isinstance(spend, dict):
        spend = {}
    _set_or_clear(_G_DAILY_SPEND_USD, _num(spend.get("total_usd")))
    _set_or_clear(_G_DAILY_CALLS, _num(spend.get("calls")))


def _refresh_gauges() -> None:
    _refresh_health_gauges()
    _refresh_decision_gauges()
    _refresh_spend_gauges()
    _refresh_cache_gauges()


def _serve_metrics(h) -> None:
    t0 = time.monotonic()
    try:
        _refresh_gauges()
        body = render_all().encode("utf-8")
        log.debug("metrics rendered in %.1f ms (%d bytes)",
                  (time.monotonic() - t0) * 1000, len(body))
        h._send(200, body, "text/plain; version=0.0.4; charset=utf-8")
    except Exception as exc:  # noqa: BLE001
        log.warning("metrics: %s", exc)
        h._send(500, b"metrics_render_failed", "text/plain")


GET_ROUTES = [
    (equals("/metrics"), _serve_metrics),
]
POST_ROUTES = []
