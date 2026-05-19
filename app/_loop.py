# arch: async scheduler (post-tkinter-removal) | section=orchestration | frozen=yes
"""
app/_loop.py - asyncio scheduler replacing the Tk mainloop / root.after
pattern for game polling (T2 #8 C1, 2026-05-01).

Drop-in replacement: `app.scheduler.schedule(ms, fn)` is the asyncio
equivalent of `root.after(ms, fn)` - one-shot, no args, no return,
thread-safe. Re-arming a poll loop works the same way: the scheduled
callable can call `schedule()` again to re-fire.

`run_forever()` blocks the caller (mirrors `mainloop()`). `stop()` is
thread-safe + idempotent.

Callback exceptions are caught + logged, mirroring the behavior of
`tk.Tk().report_callback_exception` so a single bad callback never
takes down the loop.
"""
import asyncio
import logging
import threading
import traceback
from typing import Any, Callable, Coroutine, Optional

_log = logging.getLogger("rc.app.loop")

_INSTANCE: "Optional[AppLoop]" = None


def get_loop() -> "Optional[AppLoop]":
    """Return the process-wide AppLoop, or None if no AppLoop has been
    constructed yet. Used by subsystems (coaches, module pollers) that
    need to spawn tasks on the main loop without taking a constructor-
    time reference. Subsystems that fall back to threads when the loop
    isn't ready use the None branch."""
    return _INSTANCE


def ensure_loop() -> "AppLoop":
    """Idempotently create + return the process-wide AppLoop. Call this
    before launching subsystems whose loops should ride the main event
    loop, even if `OverlayApp` hasn't been constructed yet (T2 #8 C4 -
    main.py creates the singleton early so liveclient_cache/etc. can
    spawn_task on it during boot)."""
    global _INSTANCE
    if _INSTANCE is None:
        AppLoop()  # constructor sets _INSTANCE
    return _INSTANCE  # type: ignore[return-value]


class AppLoop:
    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._loop.set_exception_handler(self._on_exception)
        self._loop_thread_id: Optional[int] = None
        global _INSTANCE
        _INSTANCE = self

    # ── Public API ───────────────────────────────────────────────────────────

    def schedule(self, ms: int, fn: Callable[[], Any]) -> None:
        """
        Run `fn()` after `ms` milliseconds. Thread-safe.
        Drop-in for `tk.Tk().after(ms, fn)`.
        """
        if self._loop.is_closed():
            return
        delay = max(0, ms) / 1000.0
        if threading.get_ident() == self._loop_thread_id:
            self._loop.call_later(delay, self._safe_call, fn)
        else:
            self._loop.call_soon_threadsafe(
                self._loop.call_later, delay, self._safe_call, fn
            )

    def spawn_task(self, coro: Coroutine[Any, Any, Any]) -> Any:
        """Schedule a coroutine on the loop. Thread-safe."""
        if threading.get_ident() == self._loop_thread_id:
            return self._loop.create_task(coro)
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def run_forever(self) -> None:
        """Block on the event loop. Mirrors `tk.Tk().mainloop()` semantics."""
        self._loop_thread_id = threading.get_ident()
        try:
            self._loop.run_forever()
        finally:
            try:
                self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            except Exception:
                _log.exception("AppLoop shutdown_asyncgens raised")
            self._loop.close()

    def stop(self) -> None:
        """Stop the loop. Thread-safe + idempotent."""
        try:
            self._loop.call_soon_threadsafe(self._loop.stop)
        except RuntimeError:
            pass

    # ── Internals ────────────────────────────────────────────────────────────

    @staticmethod
    def _safe_call(fn: Callable[[], Any]) -> None:
        try:
            fn()
        except Exception:
            _log.error("scheduler callback raised:\n%s", traceback.format_exc())

    @staticmethod
    def _on_exception(loop, context) -> None:
        msg = context.get("message", "")
        exc = context.get("exception")
        if exc is not None:
            _log.error(
                "AppLoop unhandled exception: %s\n%s",
                msg,
                "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
            )
        else:
            _log.error("AppLoop unhandled: %s", msg)
