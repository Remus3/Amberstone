"""A total deadline for an HTTP request's HEAD - request line plus headers
(RM-744).

``BaseHTTPRequestHandler.handle_one_request`` reads the request line with
``rfile.readline`` and the headers with ``http.client.parse_headers`` on a
socket that, unless the handler sets ``timeout``, has no timeout at all. A
client that connects (or completes a TLS handshake) and then sends nothing
therefore holds its request thread and socket for as long as it likes.
Measured on the :8888 dashboard 2026-10-16: still open after 180 s, live and
in-process, its request thread alive throughout.

The stdlib answer, a class-level ``timeout``, is the wrong one here and was
MEASURED wrong (RM-152, 2026-08-04): socketserver arms it in ``setup()`` for
the life of the connection, PER RECEIVE. It aborts a client slow to speak or
one whose headers arrive in two packets with a gap, yet a trickler that sends
one byte inside every window is never cut.

``HeadDeadlineMixin`` instead gives the head ONE total budget
(``head_read_timeout_s``). The handler's ``rfile`` reads through
``_HeadDeadlineRaw``, which, while the deadline is armed, sets the socket
timeout to the time LEFT before every socket read and raises ``TimeoutError``
once none is left - so no trickle can re-arm it. The deadline is armed when
``handle_one_request`` starts and removed, with the socket's own timeout
restored, as soon as ``parse_request`` returns: the request body (RM-152 has
its own deadline for that), the route, long responses and SSE streams see
the socket exactly as before. A head that misses the deadline ends in the
stdlib's own ``TimeoutError`` path (logged "Request timed out", connection
closed, no reply).

List the mixin BEFORE the ``BaseHTTPRequestHandler`` base. It lives in
``core`` so the servers kept apart from ``dashboard/`` can adopt it.

The cap is read through ``effective_head_cap`` on every request (s144 lane 8
true-audit). ``None`` or infinity means no deadline; a finite cap past
``MAX_HEAD_READ_TIMEOUT_S`` is clamped to it; anything else that is not a
positive real number (NaN, zero, negative, a string, a bool) falls back to
``HEAD_READ_TIMEOUT_S`` with one warning per handler class and value. Before,
NaN / infinity / a cap past the platform's socket limit (measured on Windows:
about 2147482 s) raised ``ValueError`` / ``OverflowError`` out of the first
socket read - not ``TimeoutError``, so the stdlib did not catch it and every
request died with no reply - and a zero or negative cap timed out every
request before a byte was read. A handler with ``rbufsize = 0`` (whose
``rfile`` is the raw socket reader) is bounded too, and a buffered handler
keeps its own ``rbufsize``.
"""
from __future__ import annotations

import io
import logging
import math
import numbers
import threading
import time

log = logging.getLogger(__name__)

# A real request head lands in one packet. 30 s is generous for any slow
# link and well past a browser's unused-preconnect hold (Chrome drops an
# unused idle socket after 10 s), yet it bounds what used to be unbounded.
HEAD_READ_TIMEOUT_S = 30.0

# The largest cap honoured as given. One day is "effectively off" for a
# request head yet far inside every platform's socket timeout limit.
MAX_HEAD_READ_TIMEOUT_S = 86400.0

# (handler class name, repr of the bad value) already warned about.
_WARNED: set[tuple[str, str]] = set()
_WARNED_LOCK = threading.Lock()


def effective_head_cap(cap, owner: str = "") -> float | None:
    """The head budget in seconds a handler's ``head_read_timeout_s`` means.

    ``None`` or ``+inf`` -> ``None`` (no deadline). A positive finite real ->
    itself as a float, clamped to ``MAX_HEAD_READ_TIMEOUT_S``. Anything else
    -> ``HEAD_READ_TIMEOUT_S``: fail toward the bound, never unbounded and
    never a deadline that refuses every request. ``owner`` names the handler
    class in the one-time warning.
    """
    if cap is None:
        return None
    if isinstance(cap, numbers.Real) and not isinstance(cap, bool):
        try:
            value = float(cap)
        except OverflowError:  # an int past float range: huge, not "off"
            value = MAX_HEAD_READ_TIMEOUT_S if cap > 0 else -1.0
        if value == math.inf:
            return None
        if value > 0:  # False for NaN
            return min(value, MAX_HEAD_READ_TIMEOUT_S)
    fallback = HEAD_READ_TIMEOUT_S
    key = (owner, repr(cap)[:80])
    with _WARNED_LOCK:
        first = key not in _WARNED
        _WARNED.add(key)
    if first:
        log.warning("%s head_read_timeout_s=%s is not a positive number of "
                    "seconds; using %.1f s", owner or "handler", key[1],
                    fallback)
    return fallback


class _HeadDeadlineRaw(io.RawIOBase):
    """The raw stream under the handler's ``rfile``.

    With ``deadline`` (a ``time.monotonic`` value) set, every read first sets
    the socket timeout to the time left and fails once it is spent. With
    ``deadline`` None it is a plain pass-through to the socket's own reader.
    """

    def __init__(self, raw, sock) -> None:
        super().__init__()
        self._raw = raw
        self._sock = sock
        self.deadline: float | None = None

    def readable(self) -> bool:
        return True

    def readinto(self, b):
        deadline = self.deadline
        if deadline is not None:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError("request head not received within its "
                                   "deadline (RM-744)")
            self._sock.settimeout(left)
        return self._raw.readinto(b)

    def fileno(self) -> int:
        return self._raw.fileno()

    def close(self) -> None:
        if self.closed:
            return
        try:
            self._raw.close()
        finally:
            super().close()


class HeadDeadlineMixin:
    """One total deadline for the request line + headers (see module doc)."""

    head_read_timeout_s: float | None = HEAD_READ_TIMEOUT_S

    def setup(self) -> None:
        super().setup()
        self._head_raw = None
        self._head_prior_timeout = None
        sock = getattr(self, "connection", None)
        rfile = getattr(self, "rfile", None)
        if not callable(getattr(sock, "settimeout", None)):
            return  # not socket-backed: nothing to bound
        if isinstance(rfile, io.BufferedReader):
            # Nothing has been read yet, so detaching the stdlib's buffer
            # loses no bytes; the raw socket reader keeps the makefile
            # reference and is closed through the new buffer in finish().
            size = getattr(self, "rbufsize", -1)
            if not isinstance(size, int) or size <= 0:
                size = io.DEFAULT_BUFFER_SIZE
            self._head_raw = _HeadDeadlineRaw(rfile.detach(), sock)
            self.rfile = io.BufferedReader(self._head_raw, size)
        elif isinstance(rfile, io.RawIOBase):
            # rbufsize == 0: the stdlib hands over the raw socket reader.
            # Wrap it unbuffered, so the head stays bounded and nothing is
            # read ahead of the route.
            self._head_raw = _HeadDeadlineRaw(rfile, sock)
            self.rfile = self._head_raw

    def handle_one_request(self) -> None:
        self._arm_head_deadline()
        try:
            super().handle_one_request()
        finally:
            self._disarm_head_deadline()

    def parse_request(self) -> bool:
        try:
            return super().parse_request()
        finally:
            # The head is read (or refused): from here on the socket is the
            # route's, with its own timeout back.
            self._disarm_head_deadline()

    def _arm_head_deadline(self) -> None:
        raw = getattr(self, "_head_raw", None)
        if raw is None:
            return
        cap = effective_head_cap(self.head_read_timeout_s,
                                 type(self).__name__)
        if cap is None:
            return
        try:
            self._head_prior_timeout = self.connection.gettimeout()
        except OSError:
            self._head_prior_timeout = None
        raw.deadline = time.monotonic() + cap

    def _disarm_head_deadline(self) -> None:
        raw = getattr(self, "_head_raw", None)
        if raw is None or raw.deadline is None:
            return
        raw.deadline = None
        try:
            self.connection.settimeout(self._head_prior_timeout)
        except OSError:
            pass
