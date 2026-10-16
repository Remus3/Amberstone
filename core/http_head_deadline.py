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
"""
from __future__ import annotations

import io
import time

# A real request head lands in one packet. 30 s is generous for any slow
# link and well past a browser's unused-preconnect hold (Chrome drops an
# unused idle socket after 10 s), yet it bounds what used to be unbounded.
HEAD_READ_TIMEOUT_S = 30.0


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
        if (not callable(getattr(sock, "settimeout", None))
                or not isinstance(rfile, io.BufferedReader)):
            return  # not a socket-backed buffered reader: nothing to bound
        # Nothing has been read yet, so detaching the stdlib's buffer loses
        # no bytes; the raw socket reader keeps the makefile reference and
        # is closed through the new buffer in finish().
        self._head_raw = _HeadDeadlineRaw(rfile.detach(), sock)
        self.rfile = io.BufferedReader(self._head_raw, io.DEFAULT_BUFFER_SIZE)

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
        cap = self.head_read_timeout_s
        if raw is None or cap is None:
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
