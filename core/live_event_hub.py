# arch: bounded live event ring + process hub fed by liveclient_cache | section=core | frozen=no
"""core/live_event_hub.py - RM-604 / X-04 (external reference F, clean-room).

Holds the last snapshot and a BOUNDED ring of derived events
(core/live_event_deriver.py) for the /api/events channel
(dashboard/routes_events.py).

  * Ids are monotonic integers. The counter is seeded from the wall clock in
    milliseconds when the hub is built, so ids keep increasing across a
    dashboard restart and a stale Last-Event-ID from the previous process
    never lands inside the new range (our choice; a restart therefore reads
    as a gap, which tells the client to re-read /api/state).
  * ``since(after)`` returns (gap, events): ``gap`` is
    ``{"kind": "gap", "from": a, "to": b}`` when ids a..b fell off the back
    of the ring (or the client claims an id ahead of head, i.e. from another
    process lifetime), else None.
  * Fed by a core.liveclient_cache listener (``ensure_installed``), the same
    tap core/live_session_recorder.py and core/ward_producer.py use. It is
    installed LAZILY by the first /api/events request, so the hub costs
    nothing until someone subscribes. A snapshot with ``data is None``
    (no game, relay error) is a None reading: the next real snapshot is a
    first snapshot again and emits nothing.
  * Fail-soft but never silent (s144 true-audit, RM-1037): a deriver,
    listener or install failure never reaches the poll loop, and the first
    failure of each streak is a WARNING (the rest are DEBUG until a success
    ends the streak). These used to be DEBUG-only, so a deriver regression
    turned the channel into heartbeats with nothing in the log.
  * ``since`` hands out copies, never the ring's own dicts, and refuses a
    non-integer cursor with TypeError (a NaN cursor used to answer "no gap,
    no events" forever).
"""
from __future__ import annotations

import collections
import logging
import threading
import time
from typing import Any, Callable, Iterable, List, Optional, Tuple

from core.live_event_deriver import derive_events

_log = logging.getLogger("rc.live_event_hub")

RING_MAX = 1024  # our choice; bounds memory for a whole game of events
_ERR_MAX = 200  # chars of an exception message kept in a log line


def _cursor(after: Any) -> int:
    """An event-id cursor must be a real int (bool and float refused)."""
    if isinstance(after, bool) or not isinstance(after, int):
        raise TypeError(f"event id cursor must be an int, not {type(after).__name__}")
    return after


class _FailStreak:
    """Warn on the first failure of a streak, DEBUG for the rest; a success
    ends the streak (logged at INFO with the streak length)."""

    def __init__(self, what: str) -> None:
        self._what = what
        self._streak = 0
        self._lock = threading.Lock()

    def fail(self, exc: BaseException) -> None:
        with self._lock:
            self._streak += 1
            n = self._streak
        msg = str(exc)[:_ERR_MAX]
        if n == 1:
            _log.warning("%s: %s: %s (further failures in this streak are logged "
                         "at debug)", self._what, type(exc).__name__, msg)
        else:
            _log.debug("%s (failure %d): %s: %s", self._what, n, type(exc).__name__, msg)

    def ok(self) -> None:
        if not self._streak:
            return
        with self._lock:
            n, self._streak = self._streak, 0
        if n:
            _log.info("%s: recovered after %d failure(s)", self._what, n)


class EventRing:
    """Thread-safe bounded ring with monotonic ids."""

    def __init__(self, maxlen: int = RING_MAX, id_seed: int = 0) -> None:
        self._buf: "collections.deque[dict]" = collections.deque(maxlen=max(1, int(maxlen)))
        self._head = int(id_seed)
        self._lock = threading.Lock()

    def __len__(self) -> int:
        """Return how many events the ring currently holds."""
        with self._lock:
            return len(self._buf)

    @property
    def head(self) -> int:
        with self._lock:
            return self._head

    def append(self, event: dict) -> int:
        with self._lock:
            self._head += 1
            self._buf.append(dict(event, id=self._head))
            return self._head

    def since(self, after: int) -> Tuple[Optional[dict], List[dict]]:
        after = _cursor(after)
        with self._lock:
            head = self._head
            if after > head:
                oldest = self._buf[0]["id"] if self._buf else head + 1
                return {"kind": "gap", "from": oldest, "to": head}, []
            # copies: a consumer mutating an event must not change what the
            # next reader (another subscriber) sees
            evs = [dict(e) for e in self._buf if e["id"] > after]
            oldest = self._buf[0]["id"] if self._buf else head + 1
            gap = None
            if after + 1 < oldest:
                gap = {"kind": "gap", "from": after + 1, "to": oldest - 1}
            return gap, evs


class LiveEventHub:
    """Last snapshot + ring. ``observe`` derives and stores; waiters wake."""

    def __init__(self, ring_max: int = RING_MAX, id_seed: Optional[int] = None,
                 completed_ids: Optional[Callable[[], Iterable[Any]]] = None) -> None:
        seed = int(time.time() * 1000) if id_seed is None else int(id_seed)
        self._ring = EventRing(ring_max, seed)
        self._prev: Any = None
        self._completed = completed_ids
        self._cond = threading.Condition()
        self._derive_fail = _FailStreak("live_event_hub derive_events")

    @property
    def head(self) -> int:
        return self._ring.head

    def since(self, after: int) -> Tuple[Optional[dict], List[dict]]:
        return self._ring.since(after)

    def observe(self, data: Any) -> List[dict]:
        cur = data if isinstance(data, dict) else None
        with self._cond:
            prev, self._prev = self._prev, cur
            if prev is None or cur is None:
                return []
            try:
                kw = {}
                if self._completed is not None:
                    kw["completed_ids"] = self._completed()
                events = derive_events(prev, cur, **kw)
                if not isinstance(events, list):
                    raise TypeError(f"derive_events returned {type(events).__name__}, not list")
            except Exception as exc:  # noqa: BLE001 - never stall the poll loop
                self._derive_fail.fail(exc)
                return []
            self._derive_fail.ok()
            out = []
            for ev in events:
                if isinstance(ev, dict):  # a junk item must not abort the batch
                    out.append(dict(ev, id=self._ring.append(ev)))
            if out:
                self._cond.notify_all()
            return out

    def wait(self, after: int, timeout: float) -> bool:
        """Block until head > after or timeout. True if new events exist."""
        with self._cond:
            if self._ring.head > after:
                return True
            self._cond.wait(timeout)
            return self._ring.head > after


_HUB: Optional[LiveEventHub] = None
_HUB_LOCK = threading.Lock()
_installed = False
_LISTENER_FAIL = _FailStreak("live_event_hub listener")
_INSTALL_FAIL = _FailStreak("live_event_hub install")


def get_hub() -> LiveEventHub:
    global _HUB
    with _HUB_LOCK:
        if _HUB is None:
            _HUB = LiveEventHub()
        return _HUB


def on_liveclient_snapshot(snap: Any) -> None:
    """liveclient_cache listener. Fail-soft; data None is a None reading."""
    try:
        hub = _HUB if _HUB is not None else get_hub()
        hub.observe(getattr(snap, "data", None))
    except Exception as exc:  # noqa: BLE001
        _LISTENER_FAIL.fail(exc)
        return
    _LISTENER_FAIL.ok()


def ensure_installed() -> bool:
    """Register the listener once (idempotent). False if the cache is absent."""
    global _installed
    if _installed:
        return True
    try:
        from core import liveclient_cache
        liveclient_cache.add_listener(on_liveclient_snapshot)
    except Exception as exc:  # noqa: BLE001
        # the route ignores False, so this line is the only trace of an
        # unfed hub; the next request retries
        _INSTALL_FAIL.fail(exc)
        return False
    _INSTALL_FAIL.ok()
    _installed = True
    return True


def _reset_for_tests() -> None:
    global _HUB, _installed, _LISTENER_FAIL, _INSTALL_FAIL
    with _HUB_LOCK:
        _HUB = None
    _installed = False
    _LISTENER_FAIL = _FailStreak("live_event_hub listener")
    _INSTALL_FAIL = _FailStreak("live_event_hub install")
