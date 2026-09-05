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
"""
from __future__ import annotations

import http.client
import logging
import os
import ssl
import threading
import time
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
#: SCOPE, measured - this gate closes the double-apply INSIDE THE POOL ONLY, and
#: the end-to-end hazard is NOT closed. On the give-up return of None,
#: lcu/lcu_client.py:191 falls through to its urlopen path at :200 and re-sends
#: the identical method and body, so a POST that faults in getresponse() is
#: still transmitted twice: this change takes the worst case from 3 sends to 2,
#: not to 1. Closing it needs an edit to lcu/lcu_client.py, which is a FROZEN
#: file requiring operator approval - filed as RM-366. Do not read the gate
#: below as an end-to-end exactly-once guarantee.
IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "PUT", "DELETE", "OPTIONS", "TRACE"})


def is_idempotent(method: object) -> bool:
    """True when re-sending `method` cannot double-apply a side effect (RM-345).

    Fail-closed by design: a non-string or unrecognised verb is treated as a
    write, so an unknown method is not replayed BY THE POOL. See the scope note
    on IDEMPOTENT_METHODS: the caller's urlopen fallthrough can still re-send it
    once, so this is not an end-to-end exactly-once guarantee (RM-366).
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


class HttpsConnectionPool:
    """Thread-safe keep-alive HTTPS connection pool keyed by (host, port).

    request() returns (status, body_bytes) on success or None on a fail-soft
    error (matching the None-returning LCU readers).

    A dropped kept-alive socket is transparently reconnected once before giving
    up, but ONLY for an idempotent method (IDEMPOTENT_METHODS, RM-345). The
    caught fault can be raised by getresponse() as well as by request(), so the
    request bytes may already have been applied by the peer; replaying a POST or
    PATCH on that fault would double-apply the write. A non-idempotent request
    is therefore sent exactly once - the poisoned socket is still dropped, and
    the call fails soft to None like any other give-up.
    """

    def __init__(
        self,
        *,
        ssl_context: Optional[ssl.SSLContext] = None,
        timeout: float = 3.0,
        connection_factory: Optional[Callable[[str, int], object]] = None,
    ) -> None:
        self._timeout = timeout
        self._ssl = ssl_context or _default_ssl_context()
        self._factory = connection_factory or self._default_factory
        self._conns: dict[tuple[str, int], object] = {}
        self._locks: dict[tuple[str, int], threading.Lock] = {}
        self._registry_lock = threading.Lock()

    def _default_factory(self, host: str, port: int):
        return http.client.HTTPSConnection(
            host, port, timeout=self._timeout, context=self._ssl
        )

    def _key_lock(self, key: tuple[str, int]) -> threading.Lock:
        with self._registry_lock:
            lk = self._locks.get(key)
            if lk is None:
                lk = threading.Lock()
                self._locks[key] = lk
            return lk

    def _get_conn(self, key: tuple[str, int]):
        conn = self._conns.get(key)
        if conn is None:
            conn = self._factory(key[0], key[1])
            self._conns[key] = conn
        return conn

    def _drop(self, key: tuple[str, int]) -> None:
        conn = self._conns.pop(key, None)
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001 - closing a dead socket is best-effort
                pass

    def request(
        self,
        host: str,
        port,
        method: str,
        path: str,
        *,
        headers: Optional[dict] = None,
        body: Optional[bytes] = None,
    ):
        try:
            key = (host, int(port))
        except (TypeError, ValueError):
            return None
        hdrs = headers or {}
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
                conn = self._get_conn(key)
                try:
                    conn.request(method, path, body, hdrs)
                    resp = conn.getresponse()
                    data = resp.read()  # full read keeps the socket reusable
                    return (resp.status, data)
                except (http.client.HTTPException, OSError, EOFError) as e:
                    self._drop(key)
                    if not retryable:
                        _log.debug(
                            "pool request %s %s%s failed; not retried "
                            "(non-idempotent, RM-345): %s",
                            method, host, path, e,
                        )
                        return None
                    if attempt == 1:
                        _log.debug("pool request %s%s failed twice: %s", host, path, e)
                        return None
        return None

    def close_all(self) -> None:
        with self._registry_lock:
            keys = list(self._conns.keys())
        for key in keys:
            self._drop(key)


class MinIntervalGuard:
    """Shared monotonic rate floor. ready(key) returns True at most once per
    min_interval_s per key (non-blocking); a loop that gets False skips its
    read this tick. Lets several callers share ONE guard so none can push the
    effective rate past the floor (L7)."""

    def __init__(self, min_interval_s: float, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._min = float(min_interval_s)
        self._clock = clock
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def ready(self, key: str = "") -> bool:
        now = self._clock()
        with self._lock:
            last = self._last.get(key)
            if last is not None and (now - last) < self._min:
                return False
            self._last[key] = now
            return True

    def time_until_ready(self, key: str = "") -> float:
        now = self._clock()
        with self._lock:
            last = self._last.get(key)
            if last is None:
                return 0.0
            remaining = self._min - (now - last)
            return remaining if remaining > 0.0 else 0.0


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
