"""Retry a None-returning Riot helper while - and only while - it is THROTTLED.

RM-484, the offline-tool siblings of e1a1d13f7. Every public `core.riot_api`
helper returns a bare None for BOTH "Riot has no such resource" and "Riot
rate-limited us". The bulk ingest tools (timeline_ingest, ladder_role_scout,
replay_roster_pull, build_rank_baselines) read that None as absence: a
throttled ids page ended an account's history, a throttled timeline was
written to disk as a permanent `partial`, a throttled /replays listing was
recorded as an EMPTY rotation window, a throttled ladder call wrote an empty
role file.

`fetch_unthrottled` opens a `riot_api.track_outcomes()` scope around one call,
so the caller learns WHY it got None. A throttled call is retried after a
cooldown; any other outcome (ok, not_found, error) returns at once, because
retrying a real absence only burns the rate budget the throttle is about.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Optional, Tuple

from core import riot_api

# Long enough for Riot's short (1 s) bucket to refill and for a 429 cooldown
# (`Retry-After`, usually single-digit seconds) to clear; short enough that a
# genuinely saturated long bucket (100 / 120 s) costs at most ~90 s per call.
DEFAULT_ATTEMPTS = 4
DEFAULT_WAIT_S = 30.0

# Module seam so offline tests can neutralise the cooldown without touching
# the global `time.sleep`.
_sleep = time.sleep


def fetch_unthrottled(
    fn: Callable[[], Any],
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    wait_s: float = DEFAULT_WAIT_S,
    sleep: Optional[Callable[[float], None]] = None,
) -> Tuple[Any, bool]:
    """Call *fn* until it is not rate limited. Returns `(result, throttled)`.

    `throttled` is True only when EVERY attempt was rate limited; the caller
    must then treat the None as "unknown - ask again later", never as absence.
    `throttled` False with a None result is the ordinary "no such data".
    """
    nap = _sleep if sleep is None else sleep
    result = None
    for attempt in range(max(1, attempts)):
        with riot_api.track_outcomes() as scope:
            result = fn()
        if not scope.rate_limited:
            return result, False
        if attempt < attempts - 1:
            nap(wait_s)
    return result, True


__all__ = ["DEFAULT_ATTEMPTS", "DEFAULT_WAIT_S", "fetch_unthrottled"]
