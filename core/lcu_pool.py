# arch: pooled loopback HTTPS reuse + min-interval guard (RC2 P6.4 port-safety) | section=core | frozen=no
"""core/lcu_pool.py - port-safety primitives for loopback LCU + Live Client reads.

RC2 Phase 6.4 (port-safety audit; docs/_archive/2026-07-28-research-consolidation/RC2_PORT_SAFETY_AUDIT.md).
Every LCU/:2999 reader today opens a NEW urllib connection per call with no
keep-alive (IO timing map Findings B), so tightening any poll cadence
multiplies ephemeral TCP+TLS handshakes and TIME_WAIT churn on loopback.
This module supplies two reusable, stdlib-only primitives:

  L6 - HttpsConnectionPool: one keep-alive http.client.HTTPSConnection per
       (host, port), reused under a per-key lock, with reconnect-on-drop
       (single retry, idempotent methods only - RM-345) so a peer-closed
       kept-alive socket self-heals without ever replaying a write. Eliminates
       the per-call handshake that otherwise caps how fast any LCU loop can run.
  L7 - MinIntervalGuard: a shared monotonic rate FLOOR keyed per endpoint so
       multiple stacked loops cannot independently push the effective read rate
       past a safe minimum. ready() is non-blocking (a loop skips its read when
       the floor has not elapsed).

pool_enabled() reads RC_LCU_POOL (default "1" since the E7 flip 2026-06-30 -
validated over a live game); explicit RC_LCU_POOL=0 restores the byte-identical
per-call path. MinIntervalGuard stays inert until a caller consults it.

s144 true-audit hardening (H1-H8, tests/test_lcu_pool_hardening_s144.py):
request() never raises - junk host / port / method / path / headers / body is
refused BEFORE a connection is built (so no exception can carry a header value
such as the Basic auth token), and an unexpected ValueError / TypeError /
OverflowError from the connection drops it and fails soft. A timeout is not a
dropped socket and is not retried. A write never rides a socket idle longer
than _WRITE_MAX_IDLE_S. At most _MAX_CONNS idle connections stay open (LRU),
so a rotated LCU port no longer leaves its socket open for the process
lifetime. close_all() waits for an in-flight request on each key.
"""
from __future__ import annotations

import http.client
import logging
import math
import numbers
import os
import ssl
import string
import threading
import time
from collections.abc import Mapping
from typing import Callable, Optional

_log = logging.getLogger("rc.lcu_pool")

_TRUTHY = ("1", "true", "yes", "on")

#: HTTP methods whose repetition is guaranteed side-effect-equivalent to a
#: single call (RFC 9110 s9.2.2). RM-345: the pool's reconnect-on-drop retry is
#: gated on this set. The fault it recovers from - HTTPException / OSError /
#: EOFError - is also raised by conn.getresponse(), i.e. AFTER the request bytes
#: are on the wire, so for anything NOT listed here the peer may already have
#: applied the write and a blind re-send would double-apply it. This is live,
#: not latent: pool_enabled() defaults ON and lcu/lcu_client.py routes every
#: method through the pool, including ready-check accept, rune-page create and
#: champ-select bench swap. POST and PATCH are deliberately absent.
#:
#: SCOPE - end to end since RM-366. RM-345 alone closed the double-apply inside
#: the pool only: on the give-up None, lcu/lcu_client.py fell through to its
#: urlopen path and re-sent the identical write (3 sends down to 2, not to 1).
#: RM-366 (frozen-file grant) makes the give-up distinguishable: the client
#: passes distinguish_sent=True and receives SENT_UNCONFIRMED when a
#: non-idempotent request's bytes were fully written before the fault, and
#: then returns None WITHOUT the urlopen re-send. A request that faulted while
#: being written (connect refused, send failed) still returns None and still
#: falls through, because it was never fully transmitted.
IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "PUT", "DELETE", "OPTIONS", "TRACE"})

#: Request-shape bounds (H1). Generous for every LCU endpoint and body RC sends
#: (the largest is a rune-page JSON well under 4 KiB); anything past them is junk.
_HOST_MAX = 253
_METHOD_MAX = 32
_PATH_MAX = 8192
_HEADERS_MAX = 64
_HEADER_VALUE_MAX = 8192
_BODY_MAX = 8 * 1024 * 1024
_PORT_MIN, _PORT_MAX = 1, 65535
#: RFC 9110 s5.6.2 tchar - the alphabet of a method and a header field name.
_TCHAR = frozenset(string.ascii_letters + string.digits + "!#$%&'*+-.^_`|~")

#: H5: a write rides a kept-alive socket only if that socket completed an
#: exchange within this many seconds. A write is never retried (RM-345), so on
#: a socket the peer closed while idle it would be lost outright; a fresh
#: connection costs one loopback handshake on a rare call. Reads keep reusing
#: any socket because a dropped one is retried.
_WRITE_MAX_IDLE_S = 2.0

#: H6: cap on cached connections. Each LCU restart rotates the port, i.e. a new
#: key; past the cap the least recently used IDLE connection is closed.
_MAX_CONNS = 8

#: H3: faults a connection raises on bad input or a broken peer that are not
#: transport errors. Caught so request() stays fail-soft; never retried.
_UNEXPECTED_FAULTS = (ValueError, TypeError, OverflowError)


class _SentUnconfirmed:
    """Sentinel type: a non-idempotent request was fully written, then the
    response failed. The peer may have applied it; never re-send (RM-366)."""

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return "SENT_UNCONFIRMED"

    def __bool__(self) -> bool:
        return False


SENT_UNCONFIRMED = _SentUnconfirmed()


def is_idempotent(method: object) -> bool:
    """True when re-sending `method` cannot double-apply a side effect (RM-345).

    Fail-closed by design: a non-string or unrecognised verb is treated as a
    write, so an unknown method is not replayed BY THE POOL. See the scope note
    on IDEMPOTENT_METHODS for how a caller suppresses its own fallback re-send
    via distinguish_sent / SENT_UNCONFIRMED (RM-366).
    """
    if not isinstance(method, str):
        return False
    return method.strip().upper() in IDEMPOTENT_METHODS


def pool_enabled() -> bool:
    """True when RC_LCU_POOL opts pooling in. Default ON since E7 (2026-06-30):
    the pool was validated over a live game (one persistent LCU socket held
    ~3 min, zero SSL EOF, reconnect self-heals, bounded socket count), so an
    unset env now pools; explicit RC_LCU_POOL=0 forces the legacy per-call path."""
    return os.environ.get("RC_LCU_POOL", "1").strip().lower() in _TRUTHY


def _default_ssl_context() -> ssl.SSLContext:
    """verify=off context matching every LCU/:2999 loopback reader (self-signed
    Riot localhost cert; hostname/CA checks are meaningless on loopback)."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _finite_real(value: object) -> Optional[float]:
    """float(value) for a finite real number that is not a bool, else None."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        return None
    try:
        out = float(value)
    except (OverflowError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _visible_ascii(text: str) -> bool:
    """Every character is printable ASCII with no space (0x21-0x7e)."""
    return all("!" <= c <= "~" for c in text)


def _coerce_port(port: object) -> Optional[int]:
    """An int, or a string of ASCII digits (the lockfile form), in 1..65535.

    A bool is refused (True used to become port 1) and so is a float (8.9 used
    to be truncated to 8, inf raised OverflowError)."""
    if isinstance(port, bool):
        return None
    if isinstance(port, int):
        value = port
    elif isinstance(port, str) and 0 < len(port) <= 5 and port.isascii() and port.isdigit():
        value = int(port)
    else:
        return None
    return value if _PORT_MIN <= value <= _PORT_MAX else None


def _valid_header_value(value: str) -> bool:
    return (len(value) <= _HEADER_VALUE_MAX
            and all(c == "\t" or " " <= c <= "~" for c in value))


def _invalid_field(host, port, method, path, headers, body) -> Optional[str]:
    """Name of the first request field with a junk shape, or None (H1).

    Only the field NAME is ever reported - never its value, which for the
    headers is the auth token."""
    if not (isinstance(host, str) and 0 < len(host) <= _HOST_MAX and _visible_ascii(host)):
        return "host"
    if _coerce_port(port) is None:
        return "port"
    if not (isinstance(method, str) and 0 < len(method) <= _METHOD_MAX
            and all(c in _TCHAR for c in method)):
        return "method"
    if not (isinstance(path, str) and path.startswith("/") and len(path) <= _PATH_MAX
            and _visible_ascii(path)):
        return "path"
    if headers is not None:
        if not isinstance(headers, Mapping) or len(headers) > _HEADERS_MAX:
            return "headers"
        for name, value in headers.items():
            if not (isinstance(name, str) and name and all(c in _TCHAR for c in name)):
                return "headers"
            if not (isinstance(value, str) and _valid_header_value(value)):
                return "headers"
    if body is not None and not (isinstance(body, (bytes, bytearray)) and len(body) <= _BODY_MAX):
        return "body"
    return None


class HttpsConnectionPool:
    """Thread-safe keep-alive HTTPS connection pool keyed by (host, port).

    request() returns (status, body_bytes) on success or None on a fail-soft
    error (matching the None-returning LCU readers). It never raises.

    A dropped kept-alive socket is transparently reconnected once before giving
    up, but ONLY for an idempotent method (IDEMPOTENT_METHODS, RM-345). The
    caught fault can be raised by getresponse() as well as by request(), so the
    request bytes may already have been applied by the peer; replaying a POST or
    PATCH on that fault would double-apply the write. A non-idempotent request
    is therefore sent exactly once - the poisoned socket is still dropped, and
    the call fails soft to None like any other give-up. A timeout is not a
    dropped socket, so it is not retried for any method (H4).
    """

    def __init__(
        self,
        *,
        ssl_context: Optional[ssl.SSLContext] = None,
        timeout: float = 3.0,
        connection_factory: Optional[Callable[[str, int], object]] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        secs = _finite_real(timeout)
        if secs is None or secs <= 0:
            raise ValueError("timeout must be a finite number of seconds > 0")
        self._timeout = secs
        self._ssl = ssl_context or _default_ssl_context()
        self._factory = connection_factory or self._default_factory
        self._clock = clock
        # Every structural change to these dicts happens under _registry_lock;
        # every change to one key's connection also holds that key's lock.
        self._conns: dict[tuple[str, int], object] = {}
        self._last_used: dict[tuple[str, int], float] = {}
        self._locks: dict[tuple[str, int], threading.Lock] = {}
        self._registry_lock = threading.Lock()

    def _default_factory(self, host: str, port: int):
        return http.client.HTTPSConnection(
            host, port, timeout=self._timeout, context=self._ssl
        )

    def _now(self) -> Optional[float]:
        """The clock reading, or None when it is not a finite number."""
        try:
            return _finite_real(self._clock())
        except (ArithmeticError, ValueError, TypeError):
            return None

    def _key_lock(self, key: tuple[str, int]) -> threading.Lock:
        with self._registry_lock:
            lk = self._locks.get(key)
            if lk is None:
                lk = threading.Lock()
                self._locks[key] = lk
            return lk

    def _get_conn(self, key: tuple[str, int], *, for_write: bool):
        """The cached connection for `key` (caller holds the key lock), or a
        new one. A write gets a fresh connection when the cached one has not
        completed an exchange within _WRITE_MAX_IDLE_S (H5)."""
        with self._registry_lock:
            conn = self._conns.get(key)
            last = self._last_used.get(key)
        if conn is not None and for_write:
            now = self._now()
            if last is None or now is None or not (0.0 <= now - last <= _WRITE_MAX_IDLE_S):
                self._drop(key)
                conn = None
        if conn is None:
            conn = self._factory(key[0], key[1])
            with self._registry_lock:
                self._conns[key] = conn
            self._evict_idle(keep=key)
        return conn

    def _evict_idle(self, *, keep: tuple[str, int]) -> None:
        """Close least-recently-used idle connections past _MAX_CONNS (H6).

        A key whose lock another thread holds is busy and is skipped; the lock
        is only TRIED, so this can never deadlock against a running request."""
        with self._registry_lock:
            excess = len(self._conns) - _MAX_CONNS
            if excess <= 0:
                return
            others = [k for k in self._conns if k != keep]
            others.sort(key=lambda k: self._last_used.get(k, -math.inf))
            candidates = [(k, self._locks.get(k)) for k in others]
        for k, lk in candidates:
            if excess <= 0:
                break
            if lk is None or not lk.acquire(blocking=False):
                continue
            try:
                if self._drop(k):
                    excess -= 1
            finally:
                lk.release()

    def _drop(self, key: tuple[str, int]) -> bool:
        with self._registry_lock:
            conn = self._conns.pop(key, None)
            self._last_used.pop(key, None)
        if conn is None:
            return False
        try:
            conn.close()
        except Exception:  # noqa: BLE001 - closing a dead socket is best-effort
            pass
        return True

    def request(
        self,
        host: str,
        port,
        method: str,
        path: str,
        *,
        headers: Optional[dict] = None,
        body: Optional[bytes] = None,
        distinguish_sent: bool = False,
    ):
        """See the class docstring. With ``distinguish_sent=True`` a
        non-idempotent request whose bytes were fully written before the
        fault returns the ``SENT_UNCONFIRMED`` sentinel instead of None, so
        a caller with its own fallback (lcu/lcu_client.py) can tell "may
        already be applied - do NOT re-send" from "never transmitted"
        (RM-366). The default keeps the plain None contract. A request with
        a junk field is never transmitted and returns None (H1)."""
        bad = _invalid_field(host, port, method, path, headers, body)
        if bad is not None:
            _log.debug("pool request refused: invalid %s", bad)
            return None
        key = (host, _coerce_port(port))
        hdrs = dict(headers) if headers else {}
        # RM-345: only an idempotent method may be replayed. The retry below
        # cannot tell a pre-write connect failure from a post-write response
        # failure, so a write gets a single attempt.
        retryable = is_idempotent(method)
        lock = self._key_lock(key)
        with lock:
            # Idempotent: two attempts - the first may hit a peer-closed
            # kept-alive socket, the second always runs on a fresh connection.
            # Non-idempotent: one attempt only.
            for attempt in (0, 1):
                sent = False
                try:
                    conn = self._get_conn(key, for_write=not retryable)
                    conn.request(method, path, body, hdrs)
                    # request() returned: every byte is on the wire, so from
                    # here on the peer may have applied the write (RM-366).
                    sent = True
                    resp = conn.getresponse()
                    data = resp.read()  # full read keeps the socket reusable
                    stamp = self._now()
                    if stamp is not None:
                        with self._registry_lock:
                            if key in self._conns:
                                self._last_used[key] = stamp
                    return (resp.status, data)
                except (http.client.HTTPException, OSError, EOFError) as e:
                    self._drop(key)
                    if not retryable:
                        _log.debug(
                            "pool request %s %s%s failed; not retried "
                            "(non-idempotent, RM-345, sent=%s): %s",
                            method, host, path, sent, type(e).__name__,
                        )
                        if sent and distinguish_sent:
                            return SENT_UNCONFIRMED
                        return None
                    if attempt == 1 or isinstance(e, TimeoutError):
                        _log.debug("pool request %s%s gave up (attempt %d): %s",
                                   host, path, attempt + 1, type(e).__name__)
                        return None
                except _UNEXPECTED_FAULTS as e:
                    # H3: never retried, and only the type name is logged - the
                    # message of a header ValueError carries the header value.
                    self._drop(key)
                    _log.debug("pool request %s%s faulted (sent=%s): %s",
                               host, path, sent, type(e).__name__)
                    if sent and distinguish_sent and not retryable:
                        return SENT_UNCONFIRMED
                    return None
        return None

    def close_all(self) -> None:
        """Close every cached connection, each under its key lock so a
        request in flight on another thread finishes first (H7)."""
        with self._registry_lock:
            keys = list(self._conns.keys())
        for key in keys:
            with self._key_lock(key):
                self._drop(key)


class MinIntervalGuard:
    """Shared monotonic rate floor. ready(key) returns True at most once per
    min_interval_s per key (non-blocking); a loop that gets False skips its
    read this tick. Lets several callers share ONE guard so none can push the
    effective rate past the floor (L7).

    The floor must be a finite number >= 0 (H8: NaN or a negative value used
    to disable it silently). A non-finite clock reading fails closed - the
    read is skipped and nothing is recorded, so one bad reading cannot turn
    the floor off for good."""

    def __init__(self, min_interval_s: float, *, clock: Callable[[], float] = time.monotonic) -> None:
        floor = _finite_real(min_interval_s)
        if floor is None or floor < 0:
            raise ValueError("min_interval_s must be a finite number of seconds >= 0")
        self._min = floor
        self._clock = clock
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def _now(self) -> Optional[float]:
        try:
            return _finite_real(self._clock())
        except (ArithmeticError, ValueError, TypeError):
            return None

    def ready(self, key: str = "") -> bool:
        now = self._now()
        if now is None:
            return False
        with self._lock:
            last = self._last.get(key)
            if last is not None and (now - last) < self._min:
                return False
            self._last[key] = now
            return True

    def time_until_ready(self, key: str = "") -> float:
        now = self._now()
        if now is None:
            return self._min
        with self._lock:
            last = self._last.get(key)
            if last is None:
                return 0.0
            remaining = self._min - (now - last)
            return max(0.0, remaining)


_shared_pool: Optional[HttpsConnectionPool] = None
_shared_lock = threading.Lock()


def get_shared_pool() -> HttpsConnectionPool:
    """Process-wide pool singleton (verify=off loopback context). Lazy so the
    pool is never built unless a caller actually opts in via RC_LCU_POOL."""
    global _shared_pool
    if _shared_pool is None:
        with _shared_lock:
            if _shared_pool is None:
                _shared_pool = HttpsConnectionPool()
    return _shared_pool
