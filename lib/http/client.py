"""Shared HTTP client for all Phase 3 outbound requests.

Responsibilities:
  - Polite User-Agent: ``RiotCommander/3.0 (+https://local)``
  - Per-hostname rate limit: <= 1 request/second (token bucket of 1).
  - Blocklist enforcement against ``lib/http/blocklist.json``.
  - Circuit breaker per hostname: opens after 5 consecutive failures,
    half-open after 60s; one probe call closes it on success.

Uses only the stdlib (``urllib.request``) — no third-party deps so the
client works in the embedded python-embed too.

Thread-safe. Intended use:

    from lib.http import get_client
    resp = get_client().get("https://ddragon.leagueoflegends.com/api/versions.json")
    data = resp.json()

For async code (the supervisor event loop), wrap ``get_client().get`` in
``asyncio.to_thread``.
"""
from __future__ import annotations

import json as _json
import logging
import ssl
import threading
import time
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import urlparse

USER_AGENT = "RiotCommander/3.0 (+https://local)"
DEFAULT_TIMEOUT = 15.0
MIN_INTERVAL_SEC = 1.0
BREAKER_THRESHOLD = 5
BREAKER_COOLDOWN_SEC = 60.0

# SSL context: prefer certifi's bundled Mozilla CA list when available —
# Python 3.14's embedded python-embed distribution ships without a CA
# store, which fails on some sites (aggregator B, cloudflare-fronted domains).
# Falls back to the default system store if certifi isn't installed.
try:
    import certifi as _certifi
    _SSL_CONTEXT: ssl.SSLContext | None = ssl.create_default_context(cafile=_certifi.where())
except ImportError:
    _SSL_CONTEXT = None

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_BLOCKLIST_PATH = _PROJECT_ROOT / "lib" / "http" / "blocklist.json"

logger = logging.getLogger("lib.http")


class HttpError(Exception):
    """Wrapper for network/HTTP failures."""


class Blocked(HttpError):
    """Target hostname is on the blocklist."""


class CircuitOpen(HttpError):
    """Breaker is open for this hostname; retry after cooldown."""


class Response:
    __slots__ = ("status", "headers", "body", "url")

    def __init__(self, status: int, headers: dict[str, str], body: bytes, url: str) -> None:
        self.status = status
        self.headers = headers
        self.body = body
        self.url = url

    def text(self, encoding: str = "utf-8") -> str:
        return self.body.decode(encoding, errors="replace")

    def json(self) -> Any:
        return _json.loads(self.text())


class _HostState:
    __slots__ = ("lock", "last_call", "failures", "opened_at")

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.last_call = 0.0
        self.failures = 0
        self.opened_at: float | None = None


class HttpClient:
    def __init__(self, blocklist_path: Path = _BLOCKLIST_PATH) -> None:
        self._blocklist_path = blocklist_path
        self._blocklist_hosts: set[str] = set()
        self._blocklist_suffixes: tuple[str, ...] = ()
        # AUDIT 2026-04-28 (P-audit4-l03): track mtime so is_blocked()
        # auto-reloads when Agent 6 edits the file mid-process. Removes
        # the manual `client.reload_blocklist()` step that used to be
        # required after every blocklist edit.
        self._blocklist_mtime: float = 0.0
        self._hosts: dict[str, _HostState] = {}
        self._hosts_lock = threading.Lock()
        self._reload_blocklist()

    # ----- blocklist -------------------------------------------------
    def _reload_blocklist(self) -> None:
        try:
            stat = self._blocklist_path.stat()
        except FileNotFoundError:
            logger.warning("blocklist missing at %s — allowing all", self._blocklist_path)
            self._blocklist_hosts = set()
            self._blocklist_suffixes = ()
            self._blocklist_mtime = 0.0
            return
        try:
            data = _json.loads(self._blocklist_path.read_text(encoding="utf-8"))
        except (OSError, _json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning("blocklist parse failed (%s): %s — allowing all",
                           self._blocklist_path, e)
            self._blocklist_hosts = set()
            self._blocklist_suffixes = ()
            self._blocklist_mtime = stat.st_mtime
            return
        hosts = data.get("hostnames") or []
        suffixes = data.get("suffixes") or []
        self._blocklist_hosts = {h.lower() for h in hosts}
        self._blocklist_suffixes = tuple(s.lower() for s in suffixes)
        self._blocklist_mtime = stat.st_mtime

    def _maybe_reload_blocklist(self) -> None:
        """Cheap mtime check on each is_blocked() call. One stat syscall;
        only re-parses when the file actually changed."""
        try:
            mtime = self._blocklist_path.stat().st_mtime
        except FileNotFoundError:
            if self._blocklist_mtime != 0.0:
                self._reload_blocklist()
            return
        if mtime != self._blocklist_mtime:
            self._reload_blocklist()

    def reload_blocklist(self) -> None:
        """Manual reload — kept for callers that want to force a refresh
        without waiting for the next is_blocked() to notice."""
        self._reload_blocklist()

    def is_blocked(self, url: str) -> bool:
        self._maybe_reload_blocklist()
        host = (urlparse(url).hostname or "").lower()
        if not host:
            return True
        if host in self._blocklist_hosts:
            return True
        for suf in self._blocklist_suffixes:
            if host.endswith(suf):
                return True
        return False

    # ----- per-host state -------------------------------------------
    def _host_state(self, host: str) -> _HostState:
        with self._hosts_lock:
            st = self._hosts.get(host)
            if st is None:
                st = _HostState()
                self._hosts[host] = st
            return st

    def _check_breaker(self, host: str, now: float) -> None:
        st = self._host_state(host)
        if st.opened_at is None:
            return
        if now - st.opened_at < BREAKER_COOLDOWN_SEC:
            raise CircuitOpen(
                f"breaker open for {host} — {BREAKER_COOLDOWN_SEC - (now - st.opened_at):.0f}s remaining"
            )
        # cooldown elapsed — allow one probe

    def _on_success(self, host: str) -> None:
        st = self._host_state(host)
        with st.lock:
            if st.failures > 0 or st.opened_at is not None:
                logger.info("breaker closed for %s after probe success", host)
            st.failures = 0
            st.opened_at = None

    def _on_failure(self, host: str, exc: Exception) -> None:
        st = self._host_state(host)
        with st.lock:
            st.failures += 1
            if st.failures >= BREAKER_THRESHOLD and st.opened_at is None:
                st.opened_at = time.monotonic()
                logger.warning("breaker OPENED for %s after %d failures: %s", host, st.failures, exc)

    # ----- rate limiter ---------------------------------------------
    def _rate_gate(self, host: str) -> None:
        st = self._host_state(host)
        with st.lock:
            now = time.monotonic()
            delta = now - st.last_call
            if delta < MIN_INTERVAL_SEC:
                sleep_for = MIN_INTERVAL_SEC - delta
                time.sleep(sleep_for)
                now = time.monotonic()
            st.last_call = now

    # ----- request core ---------------------------------------------
    def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        data: bytes | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> Response:
        if self.is_blocked(url):
            raise Blocked(f"hostname blocked by lib/http/blocklist.json: {url}")

        host = (urlparse(url).hostname or "").lower()
        now = time.monotonic()
        self._check_breaker(host, now)
        self._rate_gate(host)

        req_headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
        if headers:
            req_headers.update(headers)

        req = urllib_request.Request(url, data=data, headers=req_headers, method=method.upper())
        try:
            # Pass our certifi-backed SSL context for HTTPS — urllib only
            # uses it when explicitly supplied.
            open_kwargs: dict[str, Any] = {"timeout": timeout}
            if url.lower().startswith("https") and _SSL_CONTEXT is not None:
                open_kwargs["context"] = _SSL_CONTEXT
            with urllib_request.urlopen(req, **open_kwargs) as resp:
                body = resp.read()
                hdrs = {k: v for k, v in resp.getheaders()}
                r = Response(resp.status, hdrs, body, resp.url)
        except urllib_error.HTTPError as e:
            # 4xx/5xx — body available via e.read(); still a failure for breaker purposes.
            body = e.read() if hasattr(e, "read") else b""
            hdrs = {k: v for k, v in (e.headers.items() if e.headers else [])}
            r = Response(e.code, hdrs, body, url)
            if 500 <= e.code < 600:
                self._on_failure(host, e)
            else:
                # 4xx is a "working" remote, don't trip breaker
                self._on_success(host)
            return r
        except (urllib_error.URLError, TimeoutError, OSError) as e:
            self._on_failure(host, e)
            raise HttpError(f"network error for {url}: {e}") from e

        self._on_success(host)
        return r

    def get(self, url: str, **kw: Any) -> Response:
        return self.request("GET", url, **kw)

    def post(self, url: str, data: bytes | None = None, **kw: Any) -> Response:
        return self.request("POST", url, data=data, **kw)


_client_singleton: HttpClient | None = None
_singleton_lock = threading.Lock()


def get_client() -> HttpClient:
    global _client_singleton
    if _client_singleton is None:
        with _singleton_lock:
            if _client_singleton is None:
                _client_singleton = HttpClient()
    return _client_singleton
