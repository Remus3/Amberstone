# arch: pre-started worker-pool HTTP server for :8889 (RM-735) | section=vision | frozen=no
"""An HTTP server whose accept loop never starts a thread (RM-735).

``ThreadingHTTPServer`` (``socketserver.ThreadingMixIn``) starts one thread
per request FROM the ``serve_forever`` thread, and ``Thread.start()`` then
waits on ``self._started`` with no timeout. ``_started`` is set inside the
NEW thread (``threading.Thread._bootstrap_inner``, after ``_set_ident`` /
``_set_native_id``); a new thread that raises before that line - a
MemoryError under commit-charge exhaustion is the measured candidate - dies
without setting it, and the accept loop parks forever. The listen socket
stays bound, the backlog fills, and every client hangs in SYN_SENT: the
:8889 wedge seen twice in session 106 (py-spy: MainThread in
``process_request`` -> ``Thread.start`` -> ``_started.wait()``, one OS
thread). ``tests/test_vision_server_pool_rm735.py`` reproduces it exactly.

This server starts a fixed set of worker threads BEFORE it binds, so a
failure there leaves no half-alive listener behind. After that the accept
loop only hands each connection to a bounded queue with ``put_nowait``:
nothing on the accept path can block. A full queue closes the connection
(the client sees a reset or EOF, never a hang); a request that raises is
logged and its worker keeps serving; a connection silent for
``request_timeout_s`` is dropped so a stuck client cannot pin a worker for
good. ``dashboard/_vision_watchdog.py`` is the outer backstop for whatever
this cannot cover.

Hardened by the s144 true-audit (``tests/test_vision_server_pool_true_audit_s144.py``):

* Stopping never blocks and never strands a worker. One stop pill goes into
  the queue and every worker that takes it puts it back before it exits, so
  the pill outlives the pool: a worker still inside a request when
  ``server_close`` runs finds it as soon as that request ends. The old
  one-sentinel-per-worker scheme waited up to 1 s for a free slot, gave up,
  and left every other busy worker parked in ``queue.get()`` for good.
* Once closing, the accept path and the workers shut every connection
  instead of queueing or serving it - nothing is left waiting for a worker
  that no longer exists.
* A worker outlives ANY request: a ``BaseException`` that is not an
  ``Exception`` (``SystemExit`` from handler code) used to end the thread,
  and ``threading.excepthook`` ignores SystemExit, so the pool shrank in
  silence. It is logged like any other handler failure now.
* The pool sizes and the per-connection deadline are validated at
  construction, before a thread starts or the port is bound. A deadline of 0
  made every socket non-blocking, and a negative, NaN or overflowing one
  raised inside ``settimeout`` - on every request, a whole-server outage
  reported only as one warning per request.

The deadline is per socket OPERATION: a peer that trickles a byte inside
every window is not silent and can still hold a worker. The bind is loopback
only (RM-150), so only a local process can do that.
"""
from __future__ import annotations

import logging
import operator
import queue
import sys
import threading
from http.server import HTTPServer

_log = logging.getLogger("moon_vision")

# Concurrency the per-request threads gave in practice: a frame upload every
# 2 s, the 1 Hz relays, the LCU command queue and an occasional multi-second
# Sonnet / OCR call. 16 workers keep the S7 property (a slow handler never
# serializes the fast routes) with wide headroom.
DEFAULT_WORKERS = 16
DEFAULT_QUEUE_SIZE = 64
# Socket-operation deadline per connection. Loopback clients send their
# request at once; only a silent or stalled peer ever reaches it. Handler
# compute time (an inference call) is not a socket operation and is unaffected.
DEFAULT_REQUEST_TIMEOUT_S = 60.0
# Upper bound on that deadline. Past an hour it no longer stops a stuck
# client pinning a worker in any sense that matters, and far enough past it
# ``settimeout`` itself overflows (OverflowError on every request).
MAX_REQUEST_TIMEOUT_S = 3600.0


def _count(name: str, value: object) -> int:
    """A pool size: a real int >= 1. bool and float are refused, not coerced
    (``True`` used to mean one worker and ``2.5`` two)."""
    if not isinstance(value, bool):
        try:
            n = operator.index(value)
        except TypeError:
            n = 0
        if n >= 1:
            return n
    raise ValueError(f"PooledHTTPServer {name} must be an int >= 1, "
                     f"got {value!r}")


def _deadline(value: object) -> float | None:
    """The per-connection socket deadline: None (no deadline) or a finite
    number of seconds in (0, MAX_REQUEST_TIMEOUT_S]."""
    if value is None:
        return None
    if not isinstance(value, bool) and isinstance(value, (int, float)):
        seconds = float(value)
        # NaN fails both comparisons and inf the upper one, so the range
        # check alone refuses them.
        if 0.0 < seconds <= MAX_REQUEST_TIMEOUT_S:
            return seconds
    raise ValueError("PooledHTTPServer request_timeout_s must be None or "
                     f"seconds in (0, {MAX_REQUEST_TIMEOUT_S:g}], "
                     f"got {value!r}")


class PooledHTTPServer(HTTPServer):
    """``HTTPServer`` served by a fixed, pre-started pool of daemon workers."""

    def __init__(self, server_address, handler_class, *,
                 workers: int = DEFAULT_WORKERS,
                 queue_size: int = DEFAULT_QUEUE_SIZE,
                 request_timeout_s: float | None = DEFAULT_REQUEST_TIMEOUT_S,
                 bind_and_activate: bool = True) -> None:
        # Validated before any thread starts or the port is bound, so a bad
        # value leaves nothing half-built behind.
        workers = _count("workers", workers)
        queue_size = _count("queue_size", queue_size)
        self.request_timeout_s = _deadline(request_timeout_s)
        self.dropped = 0
        self._closing = False
        self._queue: queue.Queue = queue.Queue(maxsize=queue_size)
        self._workers: list[threading.Thread] = []
        try:
            for i in range(workers):
                t = threading.Thread(target=self._work, daemon=True,
                                     name=f"vision-worker-{i}")
                t.start()
                self._workers.append(t)
            super().__init__(server_address, handler_class, bind_and_activate)
        except BaseException:
            self._stop_workers()
            raise

    @property
    def workers_alive(self) -> int:
        return sum(1 for t in self._workers if t.is_alive())

    # -- accept path: never blocks -------------------------------------------
    def process_request(self, request, client_address) -> None:
        if self._closing:
            # No worker will take it any more; closing it now is the only
            # answer that does not leave the client hanging.
            self.shutdown_request(request)
            return
        try:
            self._queue.put_nowait((request, client_address))
        except queue.Full:
            self.dropped += 1
            if self.dropped == 1 or self.dropped % 100 == 0:
                _log.warning("worker pool saturated - dropped connection #%d "
                             "from %s", self.dropped, client_address)
            self.shutdown_request(request)

    # -- workers ---------------------------------------------------------------
    def _work(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                self._pass_on_stop()
                return
            request, client_address = item
            if self._closing:
                self.shutdown_request(request)
                continue
            try:
                if self.request_timeout_s is not None:
                    request.settimeout(self.request_timeout_s)
                self.finish_request(request, client_address)
            except BaseException:  # noqa: BLE001 - a worker must outlive any request
                # BaseException, not Exception: SystemExit from handler code
                # would otherwise end this thread with nothing logged.
                # KeyboardInterrupt is only ever raised in the main thread,
                # so nothing a worker should obey is swallowed here.
                self.handle_error(request, client_address)
            finally:
                self.shutdown_request(request)

    def handle_error(self, request, client_address) -> None:
        # The stdlib default prints to stderr, which is None under pythonw.
        # A peer that hung up or stalled is routine (a probe that timed out
        # client-side); anything else is a handler bug worth a traceback.
        try:
            exc = sys.exc_info()[1]
            if isinstance(exc, (ConnectionError, TimeoutError)):
                _log.debug("request from %s ended: %r", client_address, exc)
            else:
                _log.warning("request from %s failed", client_address,
                             exc_info=True)
        except Exception:  # noqa: BLE001
            pass

    def shutdown_request(self, request) -> None:
        try:
            super().shutdown_request(request)
        except Exception:  # noqa: BLE001
            pass

    # -- teardown --------------------------------------------------------------
    def server_close(self) -> None:
        super().server_close()
        self._stop_workers()

    def _stop_workers(self) -> None:
        """Stop the pool without blocking. Safe to call more than once."""
        self._closing = True
        # Whatever is still queued will never be served now.
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if item is not None:
                self.shutdown_request(item[0])
        if self._workers:
            self._pass_on_stop()

    def _pass_on_stop(self) -> None:
        """Leave one stop pill in the queue, never blocking.

        Called by ``_stop_workers`` and by every worker that takes the pill,
        so the pill is always there for the next worker that reaches
        ``get()`` - including one that was busy when the server closed. A
        connection that raced into the last free slot is shut (nobody will
        serve it) to make room, so a full queue can never swallow the pill.
        """
        while True:
            try:
                self._queue.put_nowait(None)
                return
            except queue.Full:
                pass
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                continue
            if item is not None:
                self.shutdown_request(item[0])
