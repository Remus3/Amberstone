"""
core/liveclient_cache.py - process-wide shared cache for the Live Client snapshot.

Pre-2026-05-01 each consumer (4 mode coaches, vision_tracker, decision_detector)
hit http://127.0.0.1:8889/latest-liveclient on its own thread/cadence - ~6-8
HTTP polls per second, idle. This module collapses them into one background
poll at 0.5s; consumers call `get()` and read the cached Snapshot.

Design mirrors web_dashboard._STATE_CACHE_PAYLOAD: module-level reference
held by an immutable dataclass, atomic rebind under the GIL, no reader lock.

Thread safety: the poll thread is the sole writer. Readers grab the
`_snapshot` reference once and read fields off the local; even if the
writer rebinds mid-read, the reader's local still points at the prior
immutable instance.

Lazy auto-start: `get()` calls `start()` on first invocation so importers
don't need to worry about init order (main.py still calls `start()`
explicitly so the cache is warm before coaches launch).
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional
from urllib.error import HTTPError
from urllib.request import Request, urlopen

_log = logging.getLogger("rc.liveclient_cache")

_RELAY_URL = "http://127.0.0.1:8889/latest-liveclient"
_RELAY_TIMEOUT = 2.0
_DEFAULT_POLL_S = 0.5


@dataclass(frozen=True)
class Snapshot:
    """Immutable snapshot of the latest relay fetch.

    `data`     - parsed /allgamedata dict, or None if no game / fetch failed.
    `ts`       - unix time the relay claims its data was current (from wrap.ts).
    `fetched_at` - unix time the cache last attempted a fetch.
    `no_game`  - True iff the most recent fetch saw an authoritative 404 from
                 the relay (no game running on Game-PC). Distinct from a
                 transient network error so callers can skip wasteful
                 fallbacks (mirrors game_reader._relay_says_no_game).
    """
    data: Optional[dict] = None
    ts: float = 0.0
    fetched_at: float = 0.0
    no_game: bool = False

    @property
    def age_s(self) -> float:
        """Seconds since the relay's reported data timestamp."""
        return max(0.0, time.time() - self.ts) if self.ts else 0.0


_EMPTY = Snapshot()
_snapshot: Snapshot = _EMPTY
_thread: Optional[threading.Thread] = None
_task: Optional[Any] = None  # asyncio.Task or concurrent.futures.Future
_stop = threading.Event()
_start_lock = threading.Lock()


def _auth_headers() -> dict:
    try:
        from core.vision_token import get_vision_token
        return {"X-RC-Token": get_vision_token()}
    except Exception:
        return {"X-RC-Token": "8e8f131e212b329438218eca27372dde"}


def _fetch_once() -> Snapshot:
    """One relay round-trip. Returns a Snapshot reflecting whatever happened."""
    fetched_at = time.time()
    try:
        req = Request(_RELAY_URL, headers=_auth_headers())
        with urlopen(req, timeout=_RELAY_TIMEOUT) as r:
            wrap = json.loads(r.read())
    except HTTPError as e:
        if e.code == 404:
            return Snapshot(data=None, ts=0.0, fetched_at=fetched_at, no_game=True)
        return Snapshot(data=None, ts=0.0, fetched_at=fetched_at, no_game=False)
    except Exception:
        return Snapshot(data=None, ts=0.0, fetched_at=fetched_at, no_game=False)
    if not isinstance(wrap, dict) or "error" in wrap:
        return Snapshot(data=None, ts=0.0, fetched_at=fetched_at, no_game=False)
    data = wrap.get("data")
    ts = float(wrap.get("ts") or 0)
    if not isinstance(data, dict):
        return Snapshot(data=None, ts=ts, fetched_at=fetched_at, no_game=False)
    return Snapshot(data=data, ts=ts, fetched_at=fetched_at, no_game=False)


def _loop(poll_s: float) -> None:
    global _snapshot
    while not _stop.is_set():
        try:
            _snapshot = _fetch_once()
        except Exception as exc:
            _log.debug("liveclient_cache loop: %s", exc)
        _stop.wait(poll_s)


async def _loop_async(poll_s: float) -> None:
    """Async equivalent of _loop. Wraps blocking HTTP in asyncio.to_thread
    so a 2s urlopen timeout never stalls the event loop."""
    global _snapshot
    while not _stop.is_set():
        try:
            _snapshot = await asyncio.to_thread(_fetch_once)
        except Exception as exc:
            _log.debug("liveclient_cache loop: %s", exc)
        try:
            await asyncio.sleep(poll_s)
        except asyncio.CancelledError:
            return


def start(poll_s: float = _DEFAULT_POLL_S) -> None:
    """Launch the background fetcher (idempotent). Prefers spawning on the
    main AppLoop if one exists; falls back to a daemon thread otherwise."""
    global _thread, _task
    with _start_lock:
        if (_thread is not None and _thread.is_alive()) or _task is not None:
            return
        _stop.clear()
        try:
            from app._loop import get_loop as _get_loop
            _sched = _get_loop()
        except Exception:
            _sched = None
        if _sched is not None:
            _task = _sched.spawn_task(_loop_async(poll_s))
            _log.info("liveclient_cache started (poll=%.2fs, async)", poll_s)
        else:
            _thread = threading.Thread(
                target=_loop, args=(poll_s,),
                daemon=True, name="liveclient-cache",
            )
            _thread.start()
            _log.info("liveclient_cache started (poll=%.2fs, thread)", poll_s)


def stop() -> None:
    """Stop the background fetcher (mostly for tests)."""
    global _thread, _task
    _stop.set()
    if _thread is not None:
        _thread.join(timeout=3)
        _thread = None
    if _task is not None:
        try: _task.cancel()
        except Exception: pass
        _task = None


def get() -> Snapshot:
    """Return the latest Snapshot. Auto-starts the fetcher on first call."""
    if _task is None and (_thread is None or not _thread.is_alive()):
        start()
    return _snapshot
