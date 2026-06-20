# arch: pooled loopback HTTPS reuse + min-interval guard (RC2 P6.4 port-safety) | section=core | frozen=no
"""core/lcu_pool.py - port-safety primitives for loopback LCU + Live Client reads.

RC2 Phase 6.4 (port-safety audit; docs/research/RC2_PORT_SAFETY_AUDIT.md).
Every LCU/:2999 reader today opens a NEW urllib connection per call with no
keep-alive (IO timing map Findings B), so tightening any poll cadence
multiplies ephemeral TCP+TLS handshakes and TIME_WAIT churn on loopback.
This module supplies two reusable, stdlib-only primitives:

  L6 - HttpsConnectionPool: one keep-alive http.client.HTTPSConnection per
       (host, port), reused under a per-key lock, with reconnect-on-drop
       (single retry) so a peer-closed kept-alive socket self-heals. Eliminates
       the per-call handshake that otherwise caps how fast any LCU loop can run.
  L7 - MinIntervalGuard: a shared monotonic rate FLOOR keyed per endpoint so
       multiple stacked loops cannot independently push the effective read rate
       past a safe minimum. ready() is non-blocking (a loop skips its read when
       the floor has not elapsed).

Both ship DEFAULT-OFF: pool_enabled() reads RC_LCU_POOL (default "0"), so the
live path stays byte-identical until a caller opts in.
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


def pool_enabled() -> bool:
    """True when RC_LCU_POOL opts pooling in. Default OFF (byte-identical live
    path) so wiring a pilot reader cannot change runtime behavior unless set."""
    return os.environ.get("RC_LCU_POOL", "0").strip().lower() in _TRUTHY


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
    error (matching the None-returning LCU readers). A dropped kept-alive
    socket is transparently reconnected once before giving up.
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
        lock = self._key_lock(key)
        with lock:
            # Two attempts: the first may hit a peer-closed kept-alive socket;
            # the second always runs on a freshly built connection.
            for attempt in (0, 1):
                conn = self._get_conn(key)
                try:
                    conn.request(method, path, body, hdrs)
                    resp = conn.getresponse()
                    data = resp.read()  # full read keeps the socket reusable
                    return (resp.status, data)
                except (http.client.HTTPException, OSError, EOFError) as e:
                    self._drop(key)
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
