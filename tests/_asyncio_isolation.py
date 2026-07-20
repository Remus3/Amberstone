"""Shared off-main-thread coroutine runners (RM-100 follow-up).

Why this module exists
----------------------
The Playwright sync fixtures in ``tests/snapshot_panels`` (the only Playwright
driver under ``tests/``) leave a greenlet-backed ProactorEventLoop marked
running on the MAIN thread for the whole session, so asyncio's per-thread
running-loop marker stays set. A bare ``asyncio.run()`` on the main thread then
raises "asyncio.run() cannot be called from a running event loop" for ANY test
that collects after a snapshot_panels test. The nightly job runs ``pytest
tests/ agents/daemon_slayer/tests/`` in ONE process; the push ``check`` job
never does, which is why this class of failure is invisible on push and red
nightly.

Mechanism (measured here: py3.14 + playwright 1.59.0)
----------------------------------------------------
``playwright/_impl/_sync_base.py:114`` (and the identical site at ``:56``) calls
``asyncio._set_running_loop(self._loop)`` after every sync call and never pairs
it with a ``_set_running_loop(None)``. It is therefore WRONG to say Playwright
"never clears" the marker, and wrong to read the leak as permanent:
``PlaywrightContextManager.__exit__``
(``playwright/sync_api/_context_manager.py:86-98``) calls ``stop_sync()`` ->
``_connection.py:319`` ``loop.run_until_complete(...)``, and
``run_until_complete``'s own ``finally`` restores the marker to ``None``. Exit
DOES clear it, as a side effect.

So the leak is BOUNDED BY THE CONTEXT MANAGER. It spans the whole session only
because the ``pw_browser`` fixture is ``scope="session"``
(``tests/snapshot_panels/conftest.py:246``).

Measured probe: marker before start = ``None``; inside the session after
``page.set_content()`` = ``<ProactorEventLoop running=True closed=False>``;
a bare run inside the session = RuntimeError "asyncio.run() cannot be called
from a running event loop"; marker after ``cm.__exit__()`` = ``None``; a bare
run after exit = ok.

Recorded as a TRADEOFF, not a recommendation: narrowing ``pw_browser`` off
session scope WOULD bound the leak, but it costs a browser launch across ~387
snapshot_panels tests. That is a real cost, not a free fix.

The marker is NOT stale while the session fixture is alive - clearing it from a
conftest teardown hangs Playwright's next call (measured, RM-100). So the
coroutine has to move off the main thread instead. A fresh thread has no
running loop, so it is immune.

Five near-identical local copies of this workaround had accreted
(test_lcu_loop_resilience, test_obs_frame_source, test_p2w1_core_f,
test_p2w2_ds_h, test_coach_poll_offload_hot03). ROADMAP RM-100 names
consolidating them as the open follow-up; this module is that consolidation.
``tests/test_asyncio_isolation_guard.py`` fails if a sixth copy appears.

Zero bare ``asyncio.run`` calls remain under ``tests/`` today, so the latent bug
has no live trigger; the guard test pins that. The bug is LATENT, not fixed.

Worker exceptions are re-raised on the caller thread so real regressions still
fail loudly - the isolation must not become a swallow.
"""
from __future__ import annotations

import asyncio
import threading
from typing import Any

__all__ = ["run_coro", "run_coro_capturing_thread"]

_DEFAULT_TIMEOUT = 10.0


def _drive(coro: Any, box: dict, on_start=None) -> threading.Thread:
    """Start a daemon thread that runs *coro* on its own fresh event loop.

    ``on_start`` runs on the worker thread before the loop does, so a caller
    can record the loop thread's ident from INSIDE the worker (comparing the
    tick thread against the main thread would pass even if a to_thread offload
    were deleted).
    """
    def _worker() -> None:
        if on_start is not None:
            on_start()
        loop = asyncio.new_event_loop()
        try:
            box["value"] = loop.run_until_complete(coro)
        except BaseException as exc:  # noqa: BLE001 - re-raised on caller thread
            box["error"] = exc
        finally:
            loop.close()

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return t


def _join(t: threading.Thread, box: dict, timeout: float) -> Any:
    t.join(timeout)
    if t.is_alive():
        raise TimeoutError(f"coroutine did not finish within {timeout}s")
    if "error" in box:
        raise box["error"]
    return box.get("value")


def run_coro(coro, timeout: float = _DEFAULT_TIMEOUT):
    """Run *coro* on a fresh event loop in a dedicated daemon thread.

    Returns the coroutine's result. Re-raises the worker's exception on the
    caller thread. Raises TimeoutError if the worker outlives *timeout*.
    """
    box: dict[str, Any] = {}
    return _join(_drive(coro, box), box, timeout)


def run_coro_capturing_thread(coro, box: dict, timeout: float = _DEFAULT_TIMEOUT):
    """Like :func:`run_coro`, but record the worker's ident in ``box``.

    Writes ``box["loop_thread"]`` from inside the worker before the loop
    starts, for tests asserting that work was offloaded off the loop thread.
    """
    def _stamp() -> None:
        box["loop_thread"] = threading.get_ident()

    return _join(_drive(coro, box, on_start=_stamp), box, timeout)
