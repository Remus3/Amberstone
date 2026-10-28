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


def _finite(value: Any, *, text_ok: bool) -> float | None:
    """`value` as a finite float, or None. A bool is never a time or a
    duration, and only the wire `ts` may be numeric text (`text_ok`); a
    caller's own duration or clock must be a number. ArithmeticError covers
    OverflowError (a JSON big-int such as 10**400) and a numeric type whose
    __float__ refuses."""
    if isinstance(value, bool):
        return None
    if not text_ok and isinstance(value, (str, bytes, bytearray)):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError, ArithmeticError):
        return None
    return out if math.isfinite(out) else None


def is_stale(ts: Any, max_age_s: float, now: float | None = None) -> bool:
    """True when `ts` is older than `max_age_s`, from the future (backward
    clock step), or not a finite number.

    Fails CLOSED: a `max_age_s` or `now` that is not a finite number (NaN
    made every comparison False, so an hour-old stamp read fresh) also
    reports stale, because the callers decide on this answer whether to serve
    a cached snapshot as live game state (s144 true-audit). Never raises for
    any JSON-decoded value or any number; only a foreign object whose
    __float__ raises outside TypeError / ValueError / ArithmeticError still
    propagates, so a real bug in such a type is not masked as "stale".
    """
    stamp = _finite(ts, text_ok=True)
    limit = _finite(max_age_s, text_ok=False)
    clock = _finite(time.time() if now is None else now, text_ok=False)
    if stamp is None or limit is None or clock is None:
        return True
    age = clock - stamp
    if age < -FUTURE_TOLERANCE_S:
        return True
    return age > limit
