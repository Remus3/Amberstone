"""Thread-scoped ``time.sleep`` probe for retry/backoff tests.

**Why this exists.** A module that does ``import time`` holds a reference to the
ONE global ``time`` module object, so ``mod.time is time`` and
``patch("mod.time.sleep")`` replaces ``time.sleep`` process-wide - not just for
that module. Every thread alive during the patch then lands on the mock.

Measured 2026-08-01: `tests/test_supervisor_common_l02.py` asserted
``mock_sleep.call_count == 2`` against `_atomic_write_json`, which is hard-bounded
at 3 attempts / 2 sleeps and cannot exceed it. CI observed **21378**. The excess
was other threads in the same worker process. Worse, the mock returned instantly
for those threads, converting their sleeps into a busy-spin - which is why the
number was so large rather than merely wrong (a local repro reached 94273 in
0.35s with a single background poll thread).

There is no narrower seam to patch: the callee resolves ``time.sleep`` through
the shared module at call time. So ``record_sleeps`` keeps the process-wide
patch but makes it HONEST:

- calls from the thread that opened the context are recorded and return
  immediately (the test still runs fast)
- calls from any other thread pass through to the real ``time.sleep`` (their
  timing is undisturbed and they never enter the recorded list)

The recorded list therefore describes the code under test and nothing else.

Prefer asserting on the recorded VALUES (``sleeps == [0.06, 0.06]``) over a bare
count - it pins the backoff schedule as well as the retry count, at no cost.
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Iterator, List

__all__ = ["record_sleeps", "thread_scoped"]


@contextmanager
def record_sleeps() -> Iterator[List[float]]:
    """Record ``time.sleep`` calls made by the CALLING thread only.

    Yields the list of recorded durations; it fills as the code under test runs.
    """
    recorded: List[float] = []
    owner = threading.get_ident()
    real_sleep = time.sleep

    def probe(seconds: float = 0.0) -> None:
        if threading.get_ident() == owner:
            recorded.append(seconds)
            return
        real_sleep(seconds)

    saved = time.sleep
    time.sleep = probe  # type: ignore[assignment]
    try:
        yield recorded
    finally:
        time.sleep = saved  # type: ignore[assignment]


def thread_scoped(side_effect, passthrough):
    """Wrap a patch ``side_effect`` so only the calling thread sees it.

    Same hazard as ``record_sleeps``: ``patch("os.replace", ...)`` is global, so
    a concurrent thread doing a legitimate replace would hit the test's fault
    injector - corrupting the test's own call log, and in the raising case
    breaking unrelated code. Calls from other threads are routed to
    ``passthrough`` (normally the real function) instead.
    """
    owner = threading.get_ident()

    def wrapper(*args, **kwargs):
        if threading.get_ident() != owner:
            return passthrough(*args, **kwargs)
        return side_effect(*args, **kwargs)

    return wrapper
