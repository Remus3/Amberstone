"""Shared HTTP client for all Phase 3 outbound requests.

Responsibilities:
  - Polite User-Agent: ``Amberstone/3.0 (+https://local)``
  - Per-hostname rate limit: <= 1 request/second (token bucket of 1).
  - Blocklist enforcement against ``lib/http/blocklist.json``.
  - Circuit breaker per hostname: opens after 5 consecutive failures,
    half-open after 60s; exactly one probe call is admitted, and its
    success closes the breaker while its failure restarts the cooldown.
  - Response size ceiling: ``max_bytes``, defaulting to
    ``DEFAULT_MAX_RESPONSE_BYTES``. ``timeout`` bounds time, not bytes.

Uses only the stdlib (``urllib.request``) - no third-party deps so the
client works in the embedded python-embed too.

Thread-safe. Intended use:

    from lib.http import get_client
    resp = get_client().get("https://ddragon.leagueoflegends.com/api/versions.json")
    data = resp.json()

For async code (the supervisor event loop), wrap ``get_client().get`` in
``asyncio.to_thread``.

SECURITY POSTURE (lane 8 cycle 27, RM-255)
------------------------------------------
This module is the single chokepoint for every outbound third-party fetch
in the tree, so the blocklist is the whole control. Three rules hold it up:

1. It FAILS CLOSED. If the blocklist cannot be loaded at construction, every
   url is blocked until the file is repaired. The previous behaviour was to
   log a warning and empty the set, which silently allowed everything - a
   control that disappears without anyone noticing is not a control.
2. It is NEVER SILENTLY WIDENED. If a good list was loaded and the file later
   goes missing or corrupt, the last known good list is RETAINED rather than
   emptied. That covers the realistic case - a reader stat-ing the file mid
   write - without converting a transient into a total outage of all fetching.
3. Hostnames are NORMALIZED before matching. A trailing dot is a legal fully
   qualified DNS name that resolves identically, so ``reddit.com.`` must not
   walk past an entry for ``reddit.com``.

Two further boundaries, same reasoning: only http and https are permitted
(the default opener also carries FileHandler and FTPHandler, so a
``file://localhost/...`` url was a local file read through the HTTP client),
and every redirect TARGET is re-checked, because the blocklist used to be
consulted only on the initial url and an allowed host could redirect to a
blocked one.
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

USER_AGENT = "Amberstone/3.0 (+https://local)"
DEFAULT_TIMEOUT = 15.0
MIN_INTERVAL_SEC = 1.0
BREAKER_THRESHOLD = 5
BREAKER_COOLDOWN_SEC = 60.0

# RM-351. `timeout` bounds TIME, not BYTES: a remote that keeps drip-feeding
# data inside the inactivity timeout streams for as long as it likes, and a
# bare `resp.read()` buffers all of it. Every caller therefore inherits a
# ceiling. 16 MiB is far above the largest artefact anything in this tree
# actually pulls through here (a DDragon bundle is single-digit MB, an icon is
# KBs, a scraped page smaller still) and still bounds the amplification.
# Pass `max_bytes=None` to opt a specific call out.
DEFAULT_MAX_RESPONSE_BYTES = 16 * 1024 * 1024
READ_CHUNK_BYTES = 64 * 1024

# Only these schemes may be fetched. The default opener also installs
# FileHandler, FTPHandler and DataHandler, so without this allowlist a url
# like file://localhost/C:/Windows/win.ini reads a LOCAL FILE through what
# every caller believes is an HTTP client.
ALLOWED_SCHEMES = ("http", "https")

# SSL context: prefer certifi's bundled Mozilla CA list when available -
# Python 3.14's embedded python-embed distribution ships without a CA
# store, which fails on some sites (aggregator B, cloudflare-fronted domains).
# Falls back to the default system store if certifi isn't installed.
#
# certifi is declared in requirements.txt as of lane 8 cycle 27. Before that
# it was present on Legion only as a TRANSITIVE dependency of httpx/requests
# and absent from requirements.txt entirely, so CI - which installs
# requirements.txt - had no certifi and this context was None there. The
# hardening worked on one box by accident.
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
    """Target hostname is on the blocklist, uses a forbidden scheme, or the
    blocklist itself could not be loaded (in which case everything is
    blocked - see the module docstring, rule 1)."""


class CircuitOpen(HttpError):
    """Breaker is open for this hostname; retry after cooldown."""


class ResponseTooLarge(HttpError):
    """A 2xx/3xx response body ran past ``max_bytes`` (RM-351).

    Raised rather than truncated, because a short body is a LIE to the caller:
    ``resp.json()`` over half a document fails somewhere far away from the
    real cause. The 4xx/5xx path is deliberately asymmetric and truncates
    instead - see the comment on that branch in ``request``.
    """


class _BlocklistInvalid(Exception):
    """Blocklist file parsed as JSON but is not the shape we require.

    Internal - callers see the effect (fail closed, or last known good),
    never this exception.
    """


def _normalize_host(host: str) -> str:
    """Lowercase and strip trailing dots from a hostname.

    ``reddit.com.`` is a legal fully qualified domain name that resolves
    identically to ``reddit.com``, so without this a single extra character
    defeated both halves of the blocklist - the exact-host set AND the
    suffix list (``site.ru.`` does not end with ``.ru``).
    """
    return host.strip().lower().rstrip(".")


def _require_str_list(value: Any, field: str) -> list[str]:
    """Validate that a blocklist field is absent or a list of strings.

    Without this a ``"hostnames": "reddit.com"`` typo was iterated
    CHARACTER BY CHARACTER into a set of single letters, which blocks
    nothing and reports no error, and a non-string element raised
    AttributeError straight out of the constructor.
    """
    if value is None:
        return []
    if not isinstance(value, list):
        raise _BlocklistInvalid(f"{field} must be a list, got {type(value).__name__}")
    for i, item in enumerate(value):
        if not isinstance(item, str):
            raise _BlocklistInvalid(
                f"{field}[{i}] must be a string, got {type(item).__name__}"
            )
    return value


def _parse_blocklist(raw: str) -> tuple[set[str], tuple[str, ...]]:
    """Parse and validate blocklist text. Raises on anything unexpected."""
    data = _json.loads(raw)
    if not isinstance(data, dict):
        raise _BlocklistInvalid(
            f"top level must be a JSON object, got {type(data).__name__}"
        )
    hosts = _require_str_list(data.get("hostnames"), "hostnames")
    suffixes = _require_str_list(data.get("suffixes"), "suffixes")
    norm_hosts = {h for h in (_normalize_host(x) for x in hosts) if h}
    norm_suffixes = tuple(s for s in (x.strip().lower() for x in suffixes) if s)
    return norm_hosts, norm_suffixes


def _read_bounded(reader: Any, max_bytes: int | None) -> tuple[bytes, bool]:
    """Read a body without trusting the remote to ever stop (RM-351).

    Returns ``(body, over_cap)``. The body is at most ``max_bytes`` + 1 bytes -
    the one extra byte is how we learn the stream still had more to give,
    since a read that returns exactly the cap is indistinguishable from a
    body that happened to end there. ``max_bytes=None`` restores the
    unbounded read for a caller that has explicitly opted out.

    ``len(chunk)`` is subtracted rather than the amount requested, so a reader
    that hands back more than it was asked for still terminates the loop.
    """
    if max_bytes is None:
        return reader.read(), False
    chunks: list[bytes] = []
    remaining = max_bytes + 1
    while remaining > 0:
        chunk = reader.read(min(READ_CHUNK_BYTES, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    body = b"".join(chunks)
    return body, len(body) > max_bytes


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
    # `lock` guards the breaker fields. `rate_lock` is SEPARATE and guards
    # only the rate limiter, which sleeps while holding it - sharing one lock
    # meant a thread sleeping up to a second in the rate gate also blocked
    # another thread's breaker bookkeeping for that host.
    __slots__ = ("lock", "rate_lock", "last_call", "failures", "opened_at", "probe_in_flight")

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.rate_lock = threading.Lock()
        self.last_call = 0.0
        self.failures = 0
        self.opened_at: float | None = None
        self.probe_in_flight = False


class _BlocklistRedirectHandler(urllib_request.HTTPRedirectHandler):
    """Re-checks the blocklist on every redirect hop.

    The blocklist used to be consulted only on the url the caller passed.
    The default opener follows redirects, so an allowed host could 302
    straight to a blocked one and the fetch went through.
    """

    def __init__(self, client: HttpClient) -> None:
        self._client = client

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if self._client.is_blocked(newurl):
            raise Blocked(f"redirect target blocked by lib/http/blocklist.json: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class HttpClient:
    def __init__(self, blocklist_path: Path = _BLOCKLIST_PATH) -> None:
        self._blocklist_path = blocklist_path
        # Both halves live in ONE tuple so a reader can never observe the
        # hostname set already swapped while the suffix tuple is still the
        # old one. Assigning a single attribute is atomic; assigning two
        # is a torn read waiting to happen, and the docstring above claims
        # this class is thread-safe.
        self._rules: tuple[set[str], tuple[str, ...]] = (set(), ())
        # AUDIT 2026-04-28 (P-audit4-l03): track mtime so is_blocked()
        # auto-reloads when Agent 6 edits the file mid-process. Removes
        # the manual `client.reload_blocklist()` step that used to be
        # required after every blocklist edit.
        self._blocklist_mtime: float = 0.0
        self._blocklist_ok = False
        self._have_known_good = False
        self._fail_closed = True
        self._degraded_logged = False
        self._blocklist_lock = threading.RLock()
        self._hosts: dict[str, _HostState] = {}
        self._hosts_lock = threading.Lock()
        # Build the opener once. The SSL context is attached to the HTTPS
        # handler here rather than passed per call, so it applies to every
        # hop including redirects.
        handlers: list[Any] = [_BlocklistRedirectHandler(self)]
        if _SSL_CONTEXT is not None:
            handlers.append(urllib_request.HTTPSHandler(context=_SSL_CONTEXT))
        self._opener = urllib_request.build_opener(*handlers)
        self._reload_blocklist()

    # ----- blocklist -------------------------------------------------
    def _reload_blocklist(self) -> None:
        with self._blocklist_lock:
            try:
                stat = self._blocklist_path.stat()
            except OSError as e:
                # File is gone or unreadable. mtime 0.0 so a re-created file
                # is noticed on the next check.
                self._blocklist_mtime = 0.0
                self._handle_blocklist_failure(e)
                return
            try:
                raw = self._blocklist_path.read_text(encoding="utf-8")
                hosts, suffixes = _parse_blocklist(raw)
            except (OSError, _json.JSONDecodeError, UnicodeDecodeError, _BlocklistInvalid) as e:
                # Record the bad file's mtime so we do not re-parse (and
                # re-log) on every single is_blocked() call. A repair changes
                # the mtime and triggers a fresh load.
                self._blocklist_mtime = stat.st_mtime
                self._handle_blocklist_failure(e)
                return
            self._rules = (hosts, suffixes)
            self._blocklist_mtime = stat.st_mtime
            self._blocklist_ok = True
            self._have_known_good = True
            self._fail_closed = False
            self._degraded_logged = False

    # The two halves are exposed separately for readability at the call
    # sites; both read the single atomic tuple.
    @property
    def _blocklist_hosts(self) -> set[str]:
        return self._rules[0]

    @property
    def _blocklist_suffixes(self) -> tuple[str, ...]:
        return self._rules[1]

    def _handle_blocklist_failure(self, exc: Exception) -> None:
        """Apply rule 1 (fail closed) or rule 2 (last known good).

        Caller must hold ``self._blocklist_lock``.
        """
        self._blocklist_ok = False
        # While degraded we re-read on every check (see _maybe_reload_blocklist),
        # so log only on entry to the degraded state - otherwise a broken file
        # writes one line per outbound request forever.
        first = not self._degraded_logged
        self._degraded_logged = True
        if self._have_known_good:
            if first:
                logger.warning(
                    "blocklist reload failed (%s): %s - RETAINING last known good "
                    "(%d hostnames, %d suffixes); the blocklist is never silently widened",
                    self._blocklist_path, exc,
                    len(self._blocklist_hosts), len(self._blocklist_suffixes),
                )
            return
        if first:
            logger.error(
                "blocklist unusable at %s (%s) - FAILING CLOSED, every outbound request "
                "is blocked until the file is repaired",
                self._blocklist_path, exc,
            )
        self._rules = (set(), ())
        self._fail_closed = True

    def _maybe_reload_blocklist(self) -> None:
        """Cheap mtime check on each is_blocked() call. One stat syscall;
        only re-parses when the file actually changed. A missing file reads
        as mtime 0.0, which differs from any real mtime and so triggers the
        reload that applies the fail-closed / last-known-good rules.

        WHILE DEGRADED THE MTIME IS NOT TRUSTED and every call re-parses.
        A writer that truncates the file, and finishes writing it inside the
        SAME filesystem timestamp tick, leaves a perfectly good file whose
        mtime equals the one we cached from the truncated read. Trusting the
        cache there would make a transient mid-write permanent - a permanent
        fail-closed outage, which is strictly worse than the fail-open bug
        this module was hardened to remove. The extra read costs one syscall
        per request and only while something is actually broken.
        """
        try:
            mtime = self._blocklist_path.stat().st_mtime
        except OSError:
            mtime = 0.0
        if mtime != self._blocklist_mtime or not self._blocklist_ok:
            self._reload_blocklist()

    def reload_blocklist(self) -> None:
        """Manual reload - kept for callers that want to force a refresh
        without waiting for the next is_blocked() to notice."""
        self._reload_blocklist()

    @property
    def blocklist_ok(self) -> bool:
        """True when the last load attempt succeeded.

        False means either fail-closed (nothing was ever loaded) or that the
        client is serving a retained last-known-good list. Re-checks the file
        first so the answer reflects the state on disk, not a stale flag.
        """
        self._maybe_reload_blocklist()
        return self._blocklist_ok

    @property
    def blocklist_state(self) -> str:
        """One of "ok", "stale", "failed_closed".

        ``blocklist_ok`` alone cannot distinguish an OUTAGE (failed_closed -
        nothing was ever loaded, so every request is refused) from a WARNING
        (stale - the file went bad but the last known good list is still
        being enforced). A health probe needs to tell those apart.
        """
        self._maybe_reload_blocklist()
        if self._blocklist_ok:
            return "ok"
        return "failed_closed" if self._fail_closed else "stale"

    def is_blocked(self, url: str) -> bool:
        self._maybe_reload_blocklist()
        if self._fail_closed:
            return True
        try:
            parsed = urlparse(url)
            scheme = (parsed.scheme or "").lower()
            raw_host = parsed.hostname or ""
        except ValueError:
            # Malformed url (bad IPv6 bracket, non-integer port). Refuse it.
            return True
        if scheme not in ALLOWED_SCHEMES:
            return True
        host = _normalize_host(raw_host)
        if not host:
            return True
        # Local refs: _reload_blocklist can swap these between the two reads.
        hosts = self._blocklist_hosts
        suffixes = self._blocklist_suffixes
        if host in hosts:
            return True
        return any(host.endswith(suf) for suf in suffixes)

    # ----- per-host state -------------------------------------------
    def _host_state(self, host: str) -> _HostState:
        with self._hosts_lock:
            st = self._hosts.get(host)
            if st is None:
                st = _HostState()
                self._hosts[host] = st
            return st

    def _check_breaker(self, host: str, now: float) -> None:
        """Raise CircuitOpen unless this caller may proceed.

        Implements the half-open contract the module docstring promises:
        once the cooldown elapses exactly ONE caller is admitted as the
        probe, and everyone else keeps getting CircuitOpen until that probe
        resolves. All reads happen under the lock that the mutators use.
        """
        st = self._host_state(host)
        with st.lock:
            if st.opened_at is None:
                return
            elapsed = now - st.opened_at
            if elapsed < BREAKER_COOLDOWN_SEC:
                raise CircuitOpen(
                    f"breaker open for {host} - {BREAKER_COOLDOWN_SEC - elapsed:.0f}s remaining"
                )
            if st.probe_in_flight:
                raise CircuitOpen(f"breaker open for {host} - probe already in flight")
            st.probe_in_flight = True

    def _on_success(self, host: str) -> None:
        st = self._host_state(host)
        with st.lock:
            if st.failures > 0 or st.opened_at is not None:
                logger.info("breaker closed for %s after probe success", host)
            st.failures = 0
            st.opened_at = None
            st.probe_in_flight = False

    def _on_failure(self, host: str, exc: Exception) -> None:
        st = self._host_state(host)
        with st.lock:
            st.failures += 1
            was_probe = st.probe_in_flight
            st.probe_in_flight = False
            if st.failures >= BREAKER_THRESHOLD and st.opened_at is None:
                st.opened_at = time.monotonic()
                logger.warning("breaker OPENED for %s after %d failures: %s", host, st.failures, exc)
            elif was_probe and st.opened_at is not None:
                # Half-open probe failed - restart the cooldown rather than
                # letting the next caller straight through.
                st.opened_at = time.monotonic()
                logger.warning("breaker re-opened for %s after probe failure: %s", host, exc)

    def _clear_probe(self, host: str) -> None:
        """Release a half-open probe slot without scoring success or failure."""
        st = self._host_state(host)
        with st.lock:
            st.probe_in_flight = False

    # ----- rate limiter ---------------------------------------------
    def _rate_gate(self, host: str) -> None:
        st = self._host_state(host)
        with st.rate_lock:
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
        max_bytes: int | None = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> Response:
        if max_bytes is not None and max_bytes < 0:
            raise ValueError(
                f"max_bytes must be non-negative or None (to disable), got {max_bytes!r}"
            )
        scheme = (urlparse(url).scheme or "").lower()
        if scheme not in ALLOWED_SCHEMES:
            raise Blocked(
                f"scheme {scheme!r} is not permitted (allowed: {', '.join(ALLOWED_SCHEMES)}): {url}"
            )
        if self.is_blocked(url):
            raise Blocked(f"hostname blocked by lib/http/blocklist.json: {url}")

        host = _normalize_host(urlparse(url).hostname or "")
        now = time.monotonic()
        self._check_breaker(host, now)
        # From here on this call may be holding the half-open probe slot, and
        # EVERY exit has to settle it - including an exception none of the
        # handlers below anticipate. http.client.IncompleteRead is not an
        # OSError, so it escapes the network handler entirely; without this
        # finally it would leave probe_in_flight True and wedge that hostname
        # for the life of the process. `settled` is checked rather than
        # clearing unconditionally so we never release a probe slot that a
        # different thread has since been admitted into.
        settled = False
        try:
            self._rate_gate(host)

            req_headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
            if headers:
                req_headers.update(headers)

            req = urllib_request.Request(
                url, data=data, headers=req_headers, method=method.upper()
            )
            try:
                # self._opener carries the certifi-backed SSL context and the
                # redirect handler that re-checks the blocklist on every hop.
                with self._opener.open(req, timeout=timeout) as resp:
                    body, over_cap = _read_bounded(resp, max_bytes)
                    if over_cap:
                        # Not caught by any handler below and `settled` is
                        # still False, so the `finally` releases the probe
                        # slot WITHOUT counting this against the breaker.
                        # An over-cap body is a client-side policy rejection
                        # like Blocked, not evidence the remote is unhealthy.
                        raise ResponseTooLarge(
                            f"response body exceeded max_bytes={max_bytes} for {url}"
                        )
                    hdrs = {k: v for k, v in resp.getheaders()}
                    r = Response(resp.status, hdrs, body, resp.url)
            except Blocked:
                # Raised by the redirect handler. Not a network failure, so it
                # must not count against the breaker.
                self._clear_probe(host)
                settled = True
                raise
            except urllib_error.HTTPError as e:
                # 4xx/5xx - body available via e.read(); still a failure for breaker purposes.
                # The error body is DIAGNOSTIC only - the caller reads
                # `resp.status` - so an over-cap one is truncated rather than
                # raised (RM-351). Raising here would turn a well-formed 404
                # into a network-class exception and would skip the
                # `_on_success` bookkeeping a working-but-refusing remote is
                # owed, wrongly walking the breaker toward open.
                if hasattr(e, "read"):
                    body, over_cap = _read_bounded(e, max_bytes)
                    if over_cap:
                        body = body[:max_bytes]
                        logger.warning(
                            "error body for %s truncated at max_bytes=%d", url, max_bytes
                        )
                else:
                    body = b""
                hdrs = {k: v for k, v in (e.headers.items() if e.headers else [])}
                r = Response(e.code, hdrs, body, url)
                if 500 <= e.code < 600:
                    self._on_failure(host, e)
                else:
                    # 4xx is a "working" remote, don't trip breaker
                    self._on_success(host)
                settled = True
                return r
            except (urllib_error.URLError, TimeoutError, OSError) as e:
                self._on_failure(host, e)
                settled = True
                raise HttpError(f"network error for {url}: {e}") from e

            self._on_success(host)
            settled = True
            return r
        finally:
            if not settled:
                self._clear_probe(host)

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
