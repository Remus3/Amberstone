"""Staleness test for a wall-clock `ts` published across a process boundary.

RM-269. The vision relay stamps each snapshot with `time.time()` and every
consumer ages it against its OWN `time.time()`. After an NTP correction that
steps the clock backward, that age goes negative, no `age > max_age`
threshold trips, and arbitrarily old data reads as current until wall time
catches up - the `core/liveclient_cache.py` cycle-7 defect class one layer up.

A monotonic companion is no fix here: monotonic clocks are per-process and
`ts` is compared in another process. So a `ts` from the FUTURE (beyond a
small jitter tolerance) is treated as STALE. Every site that ages a relay
`ts` routes through `is_stale`; fixing one site only is what made this a
three-site problem.
"""
from __future__ import annotations

import math
import time
from typing import Any

# A same-host producer and consumer share one wall clock, so a genuine age
# is never negative; the tolerance only absorbs float / scheduling jitter.
FUTURE_TOLERANCE_S = 2.0


def is_stale(ts: Any, max_age_s: float, now: float | None = None) -> bool:
    """True when `ts` is older than `max_age_s`, from the future (backward
    clock step), or not a finite number."""
    try:
        stamp = float(ts)
    except (TypeError, ValueError):
        return True
    if not math.isfinite(stamp):
        return True
    age = (time.time() if now is None else now) - stamp
    if age < -FUTURE_TOLERANCE_S:
        return True
    return age > max_age_s
