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


class EventRing:
    """Thread-safe bounded ring with monotonic ids."""

    def __init__(self, maxlen: int = RING_MAX, id_seed: int = 0) -> None:
        self._buf: "collections.deque[dict]" = collections.deque(maxlen=max(1, int(maxlen)))
        self._head = int(id_seed)
        self._lock = threading.Lock()

    def __len__(self) -> int:
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
        with self._lock:
            head = self._head
            if after > head:
                oldest = self._buf[0]["id"] if self._buf else head + 1
                return {"kind": "gap", "from": oldest, "to": head}, []
            evs = [e for e in self._buf if e["id"] > after]
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
            kw = {}
            if self._completed is not None:
                kw["completed_ids"] = self._completed()
            try:
                events = derive_events(prev, cur, **kw)
            except Exception as exc:  # noqa: BLE001 - never stall the poll loop
                _log.debug("derive_events: %s", exc)
                return []
            out = []
            for ev in events:
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
        _log.debug("live_event_hub listener: %s", exc)


def ensure_installed() -> bool:
    """Register the listener once (idempotent). False if the cache is absent."""
    global _installed
    if _installed:
        return True
    try:
        from core import liveclient_cache
        liveclient_cache.add_listener(on_liveclient_snapshot)
    except Exception as exc:  # noqa: BLE001
        _log.debug("live_event_hub install: %s", exc)
        return False
    _installed = True
    return True


def _reset_for_tests() -> None:
    global _HUB, _installed
    with _HUB_LOCK:
        _HUB = None
    _installed = False
