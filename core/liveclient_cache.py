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
from typing import Any, Callable, Optional
from urllib.error import HTTPError
from urllib.request import Request, urlopen

_log = logging.getLogger("rc.liveclient_cache")

_RELAY_URL = "http://127.0.0.1:8889/latest-liveclient"
_RELAY_TIMEOUT = 2.0
_DEFAULT_POLL_S = 0.5

# Reported age for a snapshot carrying data whose timestamp could not be
# established (absent, null, non-numeric, or implausibly far in the future).
# FAIL-CLOSED: an unknown age reads as stale, never as fresh. A finite value
# rather than float("inf") because core/decision_detector.py:830 and
# core/vision_tracker.py:279 hand age_s back to callers and json.dumps emits a
# bare `Infinity`, which is not valid JSON. One day exceeds every consumer gate
# (the loosest is 12.0s at coaches/_base_coach.py:689).
_UNKNOWN_AGE_S = 86400.0

# Tolerance for ordinary clock jitter before a future timestamp is treated as
# unusable. The relay is same-host (1-PC, ADR-011), so real skew is sub-second.
_MAX_CLOCK_SKEW_S = 5.0


@dataclass(frozen=True)
class Snapshot:
    """Immutable snapshot of the latest relay fetch.

    `data`     - parsed /allgamedata dict, or None if no game / fetch failed.
    `ts`       - unix time the relay claims its data was current (from wrap.ts).
    `fetched_at` - unix time the cache last attempted a fetch.
    `no_game`  - True iff the most recent fetch saw an authoritative 404 from
                 the relay (no game running - the vision server's in-process
                 :2999 self-read also came up empty, ADR-011). Distinct from a
                 transient network error so callers can skip wasteful
                 fallbacks (mirrors game_reader._relay_says_no_game).
    """
    data: Optional[dict] = None
    ts: float = 0.0
    fetched_at: float = 0.0
    no_game: bool = False

    @property
    def age_s(self) -> float:
        """Seconds since the relay's reported data timestamp.

        FAIL-CLOSED. If `data` is present but `ts` could not be established
        (absent, null, non-numeric, or implausibly far in the future) this
        returns `_UNKNOWN_AGE_S`, not 0.0. Returning 0.0 for an unknown
        timestamp reported unusable data as PERFECTLY FRESH to all eight
        consumers that gate on this number, which is the opposite of what a
        freshness check is for.

        `data is None` still reports 0.0: every consumer tests `snap.data is
        None` first, and the empty snapshot has no age to report.
        """
        if self.data is None:
            return 0.0
        ts = _coerce_ts(self.ts)
        if ts is None:
            # Nothing enforces the `ts: float` annotation - a Snapshot built
            # directly (not via _fetch_once) can carry any object, and a bare
            # subtraction raised TypeError straight into the caller. age_s is
            # read on every consumer's hot path, so it must be TOTAL: an
            # untrustworthy timestamp reports stale, it does not raise.
            return _UNKNOWN_AGE_S
        age = time.time() - ts
        if age < -_MAX_CLOCK_SKEW_S:
            # Timestamp is from the future by more than clock jitter allows:
            # the envelope is not trustworthy, so do not report it as fresh.
            return _UNKNOWN_AGE_S
        return max(0.0, age)


_EMPTY = Snapshot()
_snapshot: Snapshot = _EMPTY
_thread: Optional[threading.Thread] = None
_task: Optional[Any] = None  # asyncio.Task or concurrent.futures.Future
_stop = threading.Event()
_start_lock = threading.Lock()

# Snapshot listeners (UX wave 1, ward-heat producer wire). Each listener
# is called after every successful fetch with the new Snapshot. Listeners
# must be cheap and fail-soft; any exception is logged at debug and
# swallowed so a noisy listener never stalls the poll loop.
_listeners: list = []
_listeners_lock = threading.Lock()


def add_listener(fn: Callable[..., object]) -> None:
    """Register a snapshot listener. Called after every fetch.

    The listener receives the new Snapshot. Idempotent: a listener
    already registered is not added again (compared by identity).
    """
    with _listeners_lock:
        for existing in _listeners:
            if existing is fn:
                return
        _listeners.append(fn)


def remove_listener(fn: Callable[..., object]) -> None:
    """Remove a listener if present. Idempotent."""
    with _listeners_lock:
        try:
            _listeners.remove(fn)
        except ValueError:
            pass


def clear_listeners() -> None:
    """Drop all listeners. Test helper."""
    with _listeners_lock:
        _listeners.clear()


def _fire_listeners(snap: Snapshot) -> None:
    with _listeners_lock:
        listeners = list(_listeners)
    for fn in listeners:
        try:
            fn(snap)
        except Exception as exc:  # noqa: BLE001
            _log.debug("liveclient_cache listener %r: %s", fn, exc)


def _auth_headers() -> dict:
    """Resolve the relay auth header via core.vision_token.

    AUDIT 2026-06-11 (deep-audit P2-W1-A): the previous fallback returned
    the retired hardcoded legacy token, silently un-retiring the constant
    that vision_token proposal 1.7 (2026-04-28) removed. A running relay
    server resolves its token through the same raising resolver
    (vision_server/_config.py), so the legacy constant could never
    authenticate against a live server anyway - it only masked a broken
    deploy. On resolver failure we now send an empty token: the request
    401s, the snapshot fails soft, and the 0.5s poll loop retries.
    """
    try:
        from core.vision_token import get_vision_token
        return {"X-RC-Token": get_vision_token()}
    except Exception as exc:  # noqa: BLE001
        _log.debug("liveclient_cache: vision token unresolved: %s", exc)
        return {"X-RC-Token": ""}


def _coerce_ts(raw: Any) -> Optional[float]:
    """Coerce a relay-supplied `ts` to a float, or None if it is unusable.

    Strict on purpose. `bool` is rejected explicitly because it is a subclass
    of `int`, so `float(True)` is 1.0 - a 1970 timestamp, which would read as
    an enormous but PLAUSIBLE age rather than as the malformed field it is.
    """
    if raw is None or isinstance(raw, bool):
        return None
    if not isinstance(raw, (int, float)):
        return None
    value = float(raw)
    if value != value or value in (float("inf"), float("-inf")):  # NaN / inf
        return None
    if value <= 0.0:
        return None
    return value


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
    except Exception:  # noqa: BLE001
        return Snapshot(data=None, ts=0.0, fetched_at=fetched_at, no_game=False)
    if not isinstance(wrap, dict) or "error" in wrap:
        return Snapshot(data=None, ts=0.0, fetched_at=fetched_at, no_game=False)
    data = wrap.get("data")
    ts = _coerce_ts(wrap.get("ts"))
    if ts is None:
        # The relay is a separate process on its own release cadence, so a
        # renamed or retyped `ts` is a contract change, not an impossibility.
        # Logged at WARNING (not debug) so it is visible in logs/ - the
        # previous code raised here, OUTSIDE the try above, and the poll loop
        # swallowed it at debug level while _snapshot silently froze.
        _log.warning(
            "liveclient_cache: relay envelope carried an unusable ts (%r); "
            "snapshot will be reported stale",
            wrap.get("ts"),
        )
        ts = 0.0
    if not isinstance(data, dict):
        return Snapshot(data=None, ts=ts, fetched_at=fetched_at, no_game=False)
    return Snapshot(data=data, ts=ts, fetched_at=fetched_at, no_game=False)


def _loop(poll_s: float) -> None:
    global _snapshot
    while not _stop.is_set():
        try:
            _snapshot = _fetch_once()
            _fire_listeners(_snapshot)
        except Exception as exc:  # noqa: BLE001
            _log.debug("liveclient_cache loop: %s", exc)
        _stop.wait(poll_s)


async def _loop_async(poll_s: float) -> None:
    """Async equivalent of _loop. Wraps blocking HTTP in asyncio.to_thread
    so a 2s urlopen timeout never stalls the event loop."""
    global _snapshot
    while not _stop.is_set():
        try:
            _snapshot = await asyncio.to_thread(_fetch_once)
            _fire_listeners(_snapshot)
        except Exception as exc:  # noqa: BLE001
            _log.debug("liveclient_cache loop: %s", exc)
        try:
            await asyncio.sleep(poll_s)
        except asyncio.CancelledError:
            return


def _task_alive() -> bool:
    """True iff the async poll task exists AND has not finished.

    A task that has ended (``done()`` -> True: cancelled during a mid-game RC
    restart transition, or an unexpected raise) is treated as DEAD so ``start()``
    / ``get()`` respawn it. Without this, a finished-but-non-None ``_task`` froze
    the idempotent guards forever: the cache stopped polling, ``Snapshot.age_s``
    grew past the 5s bound, ``liveclient_summary()`` collapsed to ``{}``, and the
    in-game overlay never left the dashboard (the recurring "overlay not showing"
    bug). An opaque handle without ``done()`` is assumed alive (prior behavior)."""
    t = _task
    if t is None:
        return False
    done = getattr(t, "done", None)
    if callable(done):
        try:
            return not done()
        except Exception:  # noqa: BLE001
            return True
    return True


def _on_task_done(fut: Any) -> None:
    """Clear ``_task`` when the async poll loop ends so ``get()`` / ``start()`` can
    respawn it. Runs on the loop thread when the task completes. Only nulls
    ``_task`` if ``fut`` is still the current task (a newer respawn must win). An
    unexpected exit (not a plain cancel) is logged so the crash-loop is visible."""
    global _task
    if _task is fut:
        _task = None
    try:
        cancelled_fn = getattr(fut, "cancelled", None)
        if callable(cancelled_fn) and cancelled_fn():
            return
        exc_fn = getattr(fut, "exception", None)
        exc = exc_fn() if callable(exc_fn) else None
    except Exception:  # noqa: BLE001
        return
    if exc is not None:
        _log.warning(
            "liveclient_cache poll task ended with %r; will respawn on next get()",
            exc,
        )


def start(poll_s: float = _DEFAULT_POLL_S) -> None:
    """Launch the background fetcher (idempotent). Prefers spawning on the
    main AppLoop if one exists; falls back to a daemon thread otherwise."""
    global _thread, _task
    with _start_lock:
        if (_thread is not None and _thread.is_alive()) or _task_alive():
            return
        _stop.clear()
        try:
            from app._loop import get_loop as _get_loop
            _sched = _get_loop()
        except Exception:  # noqa: BLE001
            _sched = None
        if _sched is not None:
            _task = _sched.spawn_task(_loop_async(poll_s))
            # Self-heal: clear _task when the loop ends so a cancelled/exited task
            # never wedges the idempotent guard (the overlay-freeze regression).
            _add_cb = getattr(_task, "add_done_callback", None)
            if callable(_add_cb):
                _add_cb(_on_task_done)
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
        except Exception: pass  # noqa: BLE001
        _task = None


def get() -> Snapshot:
    """Return the latest Snapshot. Auto-starts (or RE-starts) the fetcher.

    Respawns when the async task has finished (``not _task_alive()``), not just
    when it is None - so a cancelled/exited poll task self-heals on the next read
    instead of freezing the cache stale (the overlay-not-showing regression)."""
    if not _task_alive() and (_thread is None or not _thread.is_alive()):
        start()
    return _snapshot
