"""No thread that can reach a live LcuClient may outlive its test module
(RM-909).

Why: the `rc.lcu` lockfile-notice dedupe (`lcu/lockfile_notice.py`) is ONE
filter for the whole process, so every LcuClient in a pytest-xdist worker
shares its state. A client left ticking by an earlier test module keeps
calling `connect()` on the REAL monotonic clock and logs its not-found repeat
(`lcu/lcu_client.py:136`) every 60 s for the rest of the worker's life. One
such record landing inside a later test's fake-clock window is the kit v24
gated-suite red (LEDGER 1919; `tests/_lcu_notice_isolation.py` shields the
two notice tests from it). RM-909 measured the source: 6 `TftWorker` poll
threads started by `tests/snapshot_regressions/test_app_authority.py`,
each holding `core.tft_worker.make_lcu_request()` and so a real LcuClient,
still calling `connect()` four test files later.

What counts as "can reach a live LcuClient" - a bounded walk from the
thread's target (its bound owner's attributes, closure cells, dict values):
  * an `lcu.lcu_client.LcuClient` instance (the frozen client's own
    auto-accept thread, or any owner that holds one);
  * one of the two LAZY readers that build an LcuClient on their first call
    and keep it: `core.tft_worker.make_lcu_request()` and
    `tft.tft_scouting.default_lcu_get()`. They are matched by qualname
    because the client does not exist until the first request.
Anything else - a server thread, an executor worker, a fake reader - is not
this guard's business.

`check_module(before)` runs at module teardown (wired from tests/conftest.py):
it stops what it finds, so one leak cannot cascade into later modules, and
returns a description of each for the failure message.
"""
from __future__ import annotations

import sys
import threading
import types

# Qualnames of the lazy readers that construct and keep an LcuClient.
LAZY_LCU_READERS = frozenset({
    "make_lcu_request.<locals>._request",   # core/tft_worker.py
    "default_lcu_get.<locals>.get",         # tft/tft_scouting.py
})

# How deep the walk goes from the thread target. Depth 3 reaches a TFT coach
# thread's closure -> the coach -> its worker -> the worker's reader.
MAX_DEPTH = 3

# How long a found thread gets to exit after it has been told to stop.
STOP_JOIN_S = 2.0

_SKIP_TYPES = (type, types.ModuleType, str, bytes, int, float, bool,
               type(None))


def _lcu_client_class():
    mod = sys.modules.get("lcu.lcu_client")
    return getattr(mod, "LcuClient", None) if mod is not None else None


def reaches_lcu_client(obj, depth: int = MAX_DEPTH, _seen=None) -> bool:
    """True when `obj` is, holds, or lazily builds an LcuClient within
    `depth` hops (instance attributes, closure cells, dict values)."""
    cls = _lcu_client_class()
    seen = set() if _seen is None else _seen
    return _reaches(obj, cls, depth, seen)


def _reaches(obj, cls, depth, seen) -> bool:
    if isinstance(obj, _SKIP_TYPES) or id(obj) in seen:
        return False
    seen.add(id(obj))
    if cls is not None and isinstance(obj, cls):
        return True
    if isinstance(obj, (types.FunctionType, types.MethodType)) \
            and obj.__qualname__ in LAZY_LCU_READERS:
        return True
    if depth <= 0:
        return False
    children = []
    if isinstance(obj, types.MethodType):
        children.append(obj.__self__)
        obj = obj.__func__
    if isinstance(obj, types.FunctionType):
        for cell in obj.__closure__ or ():
            try:
                children.append(cell.cell_contents)
            except ValueError:      # an empty cell
                continue
    elif isinstance(obj, dict):
        children.extend(obj.values())
    else:
        try:
            children.extend(vars(obj).values())
        except TypeError:           # no __dict__
            pass
    return any(_reaches(c, cls, depth - 1, seen) for c in children)


def thread_reaches_lcu_client(thread: threading.Thread) -> bool:
    """True when `thread`'s target (or, for a Thread subclass with no
    target, the thread object itself) can reach a live LcuClient. A walk
    that raises counts as not reaching: the guard must never fail a module
    on its own error."""
    target = getattr(thread, "_target", None)
    try:
        return reaches_lcu_client(target if target is not None else thread)
    except Exception:  # noqa: BLE001
        return False


def _owner(thread: threading.Thread):
    target = getattr(thread, "_target", None)
    return getattr(target, "__self__", None)


def stop(thread: threading.Thread) -> None:
    """Best-effort stop through the owner's own API, then a bounded join.
    Order: TftWorker.shutdown, LcuClient.stop_auto_accept, then a generic
    stop(). Never raises."""
    owner = _owner(thread)
    for name in ("shutdown", "stop_auto_accept", "stop"):
        fn = getattr(owner, name, None)
        if callable(fn):
            try:
                fn()
            except Exception:  # noqa: BLE001 - containment is best effort
                pass
            break
    if hasattr(owner, "_running"):
        try:
            owner._running = False
        except Exception:  # noqa: BLE001
            pass
    thread.join(timeout=STOP_JOIN_S)


def describe(thread: threading.Thread) -> str:
    target = getattr(thread, "_target", None)
    what = getattr(target, "__qualname__", None) or type(thread).__name__ + ".run"
    return f"{thread.name!r} (target {what})"


def check_module(before) -> list:
    """Every thread alive now, absent from `before`, that can reach a live
    LcuClient: each is stopped, then described. Returns the descriptions
    (empty = clean)."""
    found = [t for t in threading.enumerate()
             if t not in before and t.is_alive()
             and t is not threading.current_thread()
             and thread_reaches_lcu_client(t)]
    out = []
    for t in found:
        out.append(describe(t))
        stop(t)
    return out
