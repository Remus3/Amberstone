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
"""
from __future__ import annotations

import logging
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


class PooledHTTPServer(HTTPServer):
    """``HTTPServer`` served by a fixed, pre-started pool of daemon workers."""

    def __init__(self, server_address, handler_class, *,
                 workers: int = DEFAULT_WORKERS,
                 queue_size: int = DEFAULT_QUEUE_SIZE,
                 request_timeout_s: float | None = DEFAULT_REQUEST_TIMEOUT_S,
                 bind_and_activate: bool = True) -> None:
        workers = int(workers)
        if workers < 1:
            raise ValueError("PooledHTTPServer needs at least one worker")
        self.request_timeout_s = request_timeout_s
        self.dropped = 0
        self._closing = False
        self._queue: queue.Queue = queue.Queue(maxsize=max(1, int(queue_size)))
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
            if item is None or self._closing:
                if item is not None:
                    self.shutdown_request(item[0])
                return
            request, client_address = item
            try:
                if self.request_timeout_s is not None:
                    request.settimeout(self.request_timeout_s)
                self.finish_request(request, client_address)
            except Exception:  # noqa: BLE001 - a worker must outlive any request
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
        self._closing = True
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if item is not None:
                self.shutdown_request(item[0])
        # One sentinel per worker; each worker that takes one exits and frees
        # its slot, so a queue smaller than the pool still drains.
        for _ in self._workers:
            try:
                self._queue.put(None, timeout=1.0)
            except queue.Full:
                break
