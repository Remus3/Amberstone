# arch: RM-439 failed-load gate (not-cached retry backoff + warn-once-per-streak) | section=core | frozen=no
"""RM-439 - failure state for fail-soft cached loaders: retry backoff + warn once.

The shape this replaces, repeated across ``core/``::

    if _CACHE is not None:
        return _CACHE
    try:
        out = <read + parse>
    except Exception:
        log.warning(...)          # or nothing at all
    _CACHE = out                  # a FAILURE cached as success, forever

A failed load must instead return the empty value WITHOUT caching it (the
reference fix is ``coaches/_arena_item_advisor.py``, ``1371e7b5e``). Two costs
follow from not caching, and this gate bounds both:

  * **Disk cost.** Several of these loaders sit on per-champion / per-item hot
    paths (``archetype_picks.canonical_champion_id``, ``kit_synergy._load_items``
    under ``canonical_item_id``). MEASURED 2026-09-16 on Legion: a parse of the
    16.15.1 ``items.json`` (845 KB) is ~3.5 ms, ``champions.json`` ~1.6 ms,
    ``ddragon_champions.json`` ~1.2 ms. Re-parsing a persistently broken file on
    every call of a 173-champion sweep is a real stall, so after a failure the
    loader does not touch the disk again for ``retry_after_s`` seconds.
  * **Log cost.** The failure warns once per failure STREAK; a success ends the
    streak, so a later, separate failure warns again.

Usage (always under the loader's own lock, when it has one)::

    if not _GATE.should_attempt():
        return {}
    try:
        out = ...
    except Exception as exc:
        if _GATE.record_failure():
            log.warning("... %s", exc)
        return {}
    _GATE.record_success()
    _CACHE = out

Any existing ``_invalidate_*`` helper must call ``reset()`` as well, or an
invalidate issued inside a backoff window is served the empty value.
"""
from __future__ import annotations

import threading
import time
from typing import Optional

# Seconds a failed loader waits before touching the disk again. Short enough
# that a transient Windows sharing violation or a patch refresh landing its
# files late heals within one coach poll or two; long enough that a broken file
# costs at most one parse per window instead of one per call.
DEFAULT_RETRY_AFTER_S = 5.0


class FailedLoadGate:
    """Per-loader failure streak: backoff window + first-failure flag."""

    __slots__ = ("retry_after_s", "_lock", "_failed_at", "_in_streak")

    def __init__(self, retry_after_s: float = DEFAULT_RETRY_AFTER_S) -> None:
        self.retry_after_s = float(retry_after_s)
        self._lock = threading.Lock()
        self._failed_at: Optional[float] = None
        self._in_streak = False

    def should_attempt(self) -> bool:
        """False while inside the backoff window that follows a failure."""
        with self._lock:
            if self._failed_at is None:
                return True
            # time.monotonic is looked up per call so tests can patch it.
            return (time.monotonic() - self._failed_at) >= self.retry_after_s

    def record_failure(self) -> bool:
        """Start (or extend) a failure streak. True only for the FIRST failure
        of the streak - the caller logs exactly then."""
        with self._lock:
            self._failed_at = time.monotonic()
            first = not self._in_streak
            self._in_streak = True
            return first

    def record_success(self) -> None:
        """End the streak; the next failure warns again."""
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self._failed_at = None
            self._in_streak = False
