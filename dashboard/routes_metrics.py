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
    """
    try:
        st = riot_api_cache.get_cache().stats_fast()
        disk = float(st.get("disk_bytes") or 0)
        _G_CACHE_DISK_BYTES.set(disk)
        _G_CACHE_IMMUTABLE_ROWS.set(float(st.get("immutable_rows") or 0))
        _G_CACHE_TTL_ROWS.set(float(st.get("ttl_live_rows") or 0))
        _G_CACHE_OVER_CAP.set(1.0 if disk > _CACHE_CAP_BYTES else 0.0)
    except Exception as exc:  # noqa: BLE001
        log.debug("metrics riot_api_cache refresh: %s", exc)


def _refresh_gauges() -> None:
    h = read_json("ops/runtime/health.json") or {}
    _G_RC_ALIVE.set(1.0 if h.get("alive") else 0.0)
    if h.get("ui_pulse_age_s") is not None:
        _G_UI_PULSE_AGE.set(float(h.get("ui_pulse_age_s") or 0.0))
    if h.get("game_poll_worker_age_s") is not None:
        _G_GAME_POLL_AGE.set(float(h.get("game_poll_worker_age_s") or 0.0))

    try:
        from core.decision_detector import DecisionStore
        _G_DECISIONS_PENDING.set(len(DecisionStore().list_pending()))
    except Exception as exc:  # noqa: BLE001
        log.debug("metrics decisions_pending refresh: %s", exc)

    try:
        from core.cost_tracker import get_tracker
        spend = get_tracker().daily_spend()
        _G_DAILY_SPEND_USD.set(float(spend.get("total_usd") or 0.0))
        _G_DAILY_CALLS.set(float(spend.get("calls") or 0))
    except Exception as exc:  # noqa: BLE001
        log.debug("metrics daily_spend refresh: %s", exc)

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
