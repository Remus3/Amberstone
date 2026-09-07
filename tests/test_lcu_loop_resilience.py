"""Layer-2 regression: the in-process spawn_task self-heal loops survive a
BaseException escaping their per-iteration guard, and still propagate an
external cancel.

Root cause (2026-07-04, pid 6440): after a mid-session League client restart,
RC's asyncio spawn_task auto-accept (lcu/lcu_client._auto_accept_loop_async)
and RuneWriter (lcu/lcu_rune_writer._run_async) coroutines silently stopped
ticking. See reference_runewriter_dies_after_game1. Layer-1 (commit 8d2b4e2b)
made RuneWriter._poll self-heal the shared LcuClient every poll, but carried a
caveat: "if the poll LOOP ITSELF died, _poll never runs and this is inert."

The one real per-loop death gap: both loops guarded the tick body with
`except Exception`, which does NOT catch a BaseException subclass. A stray
non-cancel BaseException escaping that guard terminates the coroutine, leaving
no logged trace - exactly the observed silent death. Layer-2 makes the tick-arm
uniform with the proven postgame-collector pattern
(lcu/lcu_postgame_collector.py:706-709): re-raise CancelledError so shutdown
still unwinds, but swallow everything else (fail-soft) so the next iteration
re-runs the self-heal.

Tests 2 + 4 are RED before the File-1 / File-2 fix (the _Boom BaseException
escapes `except Exception` and kills the coroutine), GREEN after. Fully
hermetic - no real LCU, no app._loop, no sockets. interval 0 so asyncio.sleep(0)
yields with NO wall-clock wait; each loop self-terminates by flipping its own
control flag from INSIDE the patched tick after N calls."""
from __future__ import annotations

import asyncio
import threading

from lcu.lcu_client import LcuClient
from lcu.lcu_rune_writer import RuneWriter
from tests._asyncio_isolation import run_coro as _run_coro


class _Boom(BaseException):
    """A NON-Exception BaseException subclass - escapes `except Exception`.

    Not asyncio.CancelledError, so it must NOT be treated as an external
    cancel; layer-2's `except BaseException` must catch it and keep looping.
    """


def _bare_auto_accept_client():
    """Construct an LcuClient with only the auto-accept loop's control flag,
    skipping the heavy __init__ (no lockfile, no session, no sockets)."""
    c = LcuClient.__new__(LcuClient)
    c._running = True
    return c


def _bare_rune_writer():
    """Construct a RuneWriter with only the poll loop's control flag +
    a zero poll interval, skipping __init__ (no champ-id map, no LCU)."""
    w = RuneWriter.__new__(RuneWriter)
    w._stop_event = asyncio.Event()
    w.POLL_INTERVAL = 0  # instance override: asyncio.sleep(0) never wall-waits
    return w


def test_async_auto_accept_survives_exception():
    """A normal Exception from the tick must NOT kill the 1 Hz loop (pins the
    already-present survival - PASSES today)."""
    c = _bare_auto_accept_client()
    calls = {"n": 0}

    def _tick():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient tick failure")
        if calls["n"] >= 3:
            c._running = False  # self-terminate from inside the tick

    c._auto_accept_tick = _tick
    _run_coro(c._auto_accept_loop_async(0))

    assert calls["n"] >= 3, (
        "auto-accept loop must survive a normal Exception and keep ticking; "
        f"only ticked {calls['n']} times"
    )


def test_async_auto_accept_survives_base_exception():
    """A non-Exception BaseException from the tick must NOT kill the loop.

    RED before the File-1 fix: `except Exception` does not catch _Boom, so the
    coroutine dies on call 1 and never reaches call 2. GREEN after the
    `except BaseException` tick-arm lands."""
    c = _bare_auto_accept_client()
    calls = {"n": 0}

    def _tick():
        calls["n"] += 1
        if calls["n"] == 1:
            raise _Boom("stray BaseException escapes except Exception")
        if calls["n"] >= 3:
            c._running = False  # self-terminate from inside the tick

    c._auto_accept_tick = _tick
    _run_coro(c._auto_accept_loop_async(0))

    assert calls["n"] >= 3, (
        "auto-accept loop must survive a BaseException subclass and keep "
        f"ticking; only ticked {calls['n']} times (loop died on the escape)"
    )


def test_async_auto_accept_cancel_stops_loop():
    """An external task.cancel() while the tick is in flight must STOP the loop
    - the `except asyncio.CancelledError: return` arm must win over the generic
    `except BaseException` arm (CancelledError IS a BaseException, so ordering
    is load-bearing: if the generic arm caught it first, shutdown would be
    swallowed and the loop would keep spinning forever).

    Guards shutdown semantics without wedging a real OS worker thread: we patch
    asyncio.to_thread so the "tick" is a cancellable coroutine that parks on a
    never-set Event. Cancelling the loop task injects CancelledError at that
    await; the loop must catch it and return, ticking exactly once."""
    c = _bare_auto_accept_client()
    ticks = {"n": 0}
    parked = asyncio.Event()  # set once the fake tick is awaiting (never proceeds)

    async def _fake_to_thread(fn, *args, **kwargs):
        # Stand in for asyncio.to_thread: run the tick counter, then park on a
        # cancellable await so an outer cancel lands HERE (at the tick-arm).
        ticks["n"] += 1
        parked.set()
        await asyncio.Event().wait()  # never set - only a cancel escapes

    async def _drive():
        real_to_thread = asyncio.to_thread
        asyncio.to_thread = _fake_to_thread
        try:
            task = asyncio.ensure_future(c._auto_accept_loop_async(0))
            await parked.wait()  # tick is now awaiting inside the loop
            task.cancel()
            # The loop catches the injected CancelledError and returns. Whether
            # `await task` re-surfaces CancelledError is Python-version
            # dependent (a suppressed cancel may still mark the task cancelled);
            # tolerate both - the tick-count assertion below is the real proof.
            try:
                await task
            except asyncio.CancelledError:
                pass
        finally:
            asyncio.to_thread = real_to_thread

    _run_coro(_drive())

    assert ticks["n"] == 1, (
        "cancel must stop the loop at the tick-arm after exactly one tick; "
        f"ticked {ticks['n']} times (CancelledError was not caught first)"
    )
    assert c._running is True, (
        "cancel path must NOT clear _running - it returns via the "
        "CancelledError arm, not by the loop condition going false"
    )


def test_async_runewriter_survives_exception():
    """RuneWriter poll loop survives a normal Exception (mirror of the
    auto-accept survival pin - PASSES today)."""
    w = _bare_rune_writer()
    calls = {"n": 0}

    def _poll():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient poll failure")
        if calls["n"] >= 3:
            w._stop_event.set()  # self-terminate from inside the poll

    w._poll = _poll
    _run_coro(w._run_async())

    assert calls["n"] >= 3, (
        "RuneWriter poll loop must survive a normal Exception and keep "
        f"polling; only polled {calls['n']} times"
    )


def test_async_runewriter_survives_base_exception():
    """RuneWriter poll loop must survive a non-Exception BaseException.

    RED before the File-2 fix: `except Exception` does not catch _Boom, so the
    coroutine dies on poll 1. GREEN after the `except BaseException` tick-arm."""
    w = _bare_rune_writer()
    calls = {"n": 0}

    def _poll():
        calls["n"] += 1
        if calls["n"] == 1:
            raise _Boom("stray BaseException escapes except Exception")
        if calls["n"] >= 3:
            w._stop_event.set()  # self-terminate from inside the poll

    w._poll = _poll
    _run_coro(w._run_async())

    assert calls["n"] >= 3, (
        "RuneWriter poll loop must survive a BaseException subclass and keep "
        f"polling; only polled {calls['n']} times (loop died on the escape)"
    )
