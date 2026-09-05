# arch: Riot Web API client + rate limiter + endpoint wrappers | section=core | frozen=no
"""Riot Web API client for the FU02 champ-select team-context fan-out.

Single permitted module for Riot Web API access per ADR-006. Wraps:

  Account-V1                - get_account_by_riot_id
  Match-V5                  - get_recent_matches, get_match, get_match_timeline
  League-V4                 - get_summoner_rank
  Champion-Mastery-V4       - get_champion_mastery

Rate limiting is per-process: a dual token bucket sized to Personal-tier
headline limits (20/s + 100/2min). Method-level limits surfaced by Riot
in `X-Method-Rate-Limit-Count` are tracked best-effort - on a 429 the
endpoint is skipped (caller decides retry; the dashboard renders partial
data anyway). Live-coaching loop must NOT call this module per ADR-006;
the only consumers are champ-select team-context fan-out + post-game
timeline review.

Soft-fail invariants:
  - Missing API key file -> log WARNING once, every fn returns None.
  - Network/HTTP error -> log WARNING, return None.
  - Cache layer is the source of truth for repeat lookups; this module
    is a fetch-and-store wrapper.
  - A 404/403 from an IMMUTABLE-cached endpoint is CACHED AS A NEGATIVE, for
    a short per-outcome TTL and scoped to the active API key (RM-163). Riot
    serves no Match-V5 timeline for the event modes, and before this the
    absence was re-discovered on every single request - 289ms of a 291ms
    /api/last-match build. Transport failures, 429, 401 and 5xx are NOT
    cached; see `_call_ex` and `_NEGATIVE_TTL_S_BY_OUTCOME`.
  - The TTL-cached endpoints (League-V4, Champion-Mastery-V4) deliberately do
    NOT negative-cache; see the note on `get_summoner_rank`.
  - The rate limiter shares state across all endpoints (bucket exhaustion
    on Match-V5 still blocks League-V4). Method-specific tracking is
    informational, not enforced - Riot's response headers are the
    canonical signal.

Region routing: Account-V1 + Match-V5 use the regional cluster
(`americas`/`europe`/`asia`); League-V4 + Champion-Mastery-V4 use the
platform cluster (`na1`/`euw1`/etc.). Defaults: regional=`americas`,
platform=`na1`. Multi-region support is out of scope for v1.
"""
from __future__ import annotations

import collections
import contextlib
import hashlib
import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

from core.prom_metrics import Counter, Gauge
from core.riot_api_cache import get_cache

log = logging.getLogger("rc.riot_api")

# -- key resolver --------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_API_KEY_FILE = _PROJECT_ROOT / "API-Key-Riot.txt"
_KEY_PREFIX = "RGAPI-"

_KEY_LOCK = threading.Lock()
_KEY_CACHE: Optional[str] = None
_KEY_WARNED_MISSING = False


def _get_api_key() -> Optional[str]:
    """Read + cache the Riot API key.

    NOTE: this file must hold the **Amberstone product-app key**, not the
    personal/development key. Endpoint entitlements differ per app - notably
    `/lol/match/v5/matches/by-puuid/{puuid}/replays` is approved for the product
    app only and 400s with the dev key. See memory
    `reference_riot_app_entitlements`.

    Returns the key string or None when:
      - file doesn't exist (logged once at WARNING)
      - file exists but is empty / wrong format (logged + cache cleared)
    """
    global _KEY_CACHE, _KEY_WARNED_MISSING
    with _KEY_LOCK:
        if _KEY_CACHE is not None:
            return _KEY_CACHE
        if not _API_KEY_FILE.exists():
            if not _KEY_WARNED_MISSING:
                log.warning(
                    "riot_api: %s not found; API calls disabled. "
                    "See ADR-006 + RC_TICKET_FU04 for key provisioning.",
                    _API_KEY_FILE,
                )
                _KEY_WARNED_MISSING = True
            return None
        try:
            raw = _API_KEY_FILE.read_text(encoding="utf-8").strip()
        # RM-291A: UnicodeDecodeError is a ValueError, not an OSError.
        except (OSError, UnicodeDecodeError) as exc:
            log.warning("riot_api: read %s failed: %s", _API_KEY_FILE, exc)
            return None
        # Strip surrounding quotes operators sometimes paste in.
        if (raw.startswith('"') and raw.endswith('"')) or (
                raw.startswith("'") and raw.endswith("'")):
            raw = raw[1:-1].strip()
        if not raw or not raw.startswith(_KEY_PREFIX):
            log.warning(
                "riot_api: key file %s missing %s prefix; clearing cache.",
                _API_KEY_FILE, _KEY_PREFIX,
            )
            _KEY_CACHE = None
            return None
        _KEY_CACHE = raw
        _KEY_WARNED_MISSING = False
        return _KEY_CACHE


def _key_fingerprint() -> str:
    """Short, non-reversible tag for the ACTIVE key - a cache-key component.

    PUUIDs are a per-API-key encryption of the same account: the value changes
    when the KEY changes, not on any time schedule. Any cache key over a PUUID
    must therefore carry key identity, or one rotation poisons the row forever
    (the account row lands in the IMMUTABLE cache, which never expires).

    Truncated sha256, never the key itself - the cache DB is not a secret store.
    "nokey" when no key resolves, so the key-less path still has a stable key.
    """
    key = _get_api_key()
    if not key:
        return "nokey"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def reload_api_key() -> None:
    """Force re-read of the API key file. Call after operator rotates."""
    global _KEY_CACHE, _KEY_WARNED_MISSING
    with _KEY_LOCK:
        _KEY_CACHE = None
        _KEY_WARNED_MISSING = False


# -- dual-bucket rate limiter --------------------------------------------

# Ceiling on any 429-imposed cooldown, in seconds. Sits ABOVE every backoff
# Riot can legitimately mean - the long bucket is 100 requests per 120s, so a
# real application-rate backoff is well inside 600s - and far BELOW the point
# where a bad value becomes indistinguishable from a permanent outage. See
# `DualBucket.note_429` for the defect this bounds.
_MAX_COOLDOWN_S = 600.0


class DualBucket:
    """Token-bucket dual-window limiter.

    Personal/Dev tier headlines: 20 requests per 1s + 100 requests per
    120s. Both buckets must have headroom for a request to be admitted.
    `acquire(timeout_s)` blocks up to `timeout_s` waiting for either
    bucket to drain; on timeout, returns False and the caller skips
    the call.
    """

    def __init__(
        self,
        short_n: int = 20,
        short_window_s: float = 1.0,
        long_n: int = 100,
        long_window_s: float = 120.0,
        max_cooldown_s: float = _MAX_COOLDOWN_S,
    ) -> None:
        self._short: collections.deque = collections.deque()
        self._long: collections.deque = collections.deque()
        self._short_n = int(short_n)
        self._short_w = float(short_window_s)
        self._long_n = int(long_n)
        self._long_w = float(long_window_s)
        self._lock = threading.Lock()
        self._max_cooldown_s = float(max_cooldown_s)
        # Tracks a forced cool-down imposed by a 429 response. Until
        # `_cooldown_until` passes, acquire() returns False even if the
        # local deques would admit. Set by `note_429`, which CLAMPS it - see
        # the note there.
        self._cooldown_until: float = 0.0

    def acquire(self, timeout_s: float = 5.0) -> bool:
        deadline = time.monotonic() + max(0.0, float(timeout_s))
        while True:
            with self._lock:
                now = time.monotonic()
                if now < self._cooldown_until:
                    pass   # fall through to wait/retry below
                else:
                    self._trim(self._short, now - self._short_w)
                    self._trim(self._long, now - self._long_w)
                    if (len(self._short) < self._short_n
                            and len(self._long) < self._long_n):
                        self._short.append(now)
                        self._long.append(now)
                        return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)

    def note_429(self, retry_after_s: float) -> None:
        """Caller observed a 429 - pause acquires until retry_after passes.

        CLAMPED AT BOTH ENDS, and the top end is the load-bearing one. The
        value originates in an upstream `Retry-After` header, and the previous
        `max(0.0, ...)` bounded only the bottom. A value of 999999999 - a
        misbehaving intermediary, a Riot bug, a header in milliseconds -
        therefore set a cooldown of 31.7 YEARS, after which every `acquire()`
        refused for the life of the process. Nothing in this module could
        clear it: `reload_api_key` touches only the key cache, and
        `_reset_bucket_for_tests` is test-only, so recovery meant restarting
        RC. The supervisor runs for days at a time.

        `min` after `max` also disposes of NaN without a special case: every
        NaN comparison is False, so `max(0.0, nan)` keeps 0.0 and the cooldown
        lands at zero rather than at a value that can never elapse.
        """
        with self._lock:
            bounded = min(self._max_cooldown_s, max(0.0, float(retry_after_s)))
            self._cooldown_until = time.monotonic() + bounded

    def snapshot(self) -> dict:
        """Read-only view for /metrics + tests."""
        with self._lock:
            now = time.monotonic()
            self._trim(self._short, now - self._short_w)
            self._trim(self._long, now - self._long_w)
            return {
                "short_used": len(self._short),
                "short_cap":  self._short_n,
                "long_used":  len(self._long),
                "long_cap":   self._long_n,
                "cooldown_remaining_s": max(0.0, self._cooldown_until - now),
            }

    @staticmethod
    def _trim(dq: collections.deque, cutoff: float) -> None:
        while dq and dq[0] < cutoff:
            dq.popleft()


_BUCKET = DualBucket(short_n=20, short_window_s=1.0,
                     long_n=100, long_window_s=120.0)


def _reset_bucket_for_tests() -> None:
    """Test helper - clear the module bucket between cases."""
    global _BUCKET
    _BUCKET = DualBucket(short_n=20, short_window_s=1.0,
                         long_n=100, long_window_s=120.0)


# -- Prom metrics --------------------------------------------------------

_M_CALLS_TOTAL = Counter(
    "rc_riot_api_calls_total",
    "Riot Web API calls by endpoint and outcome (ok / cache / cache_negative "
    "/ error / rate_limited / no_key / 429).",
    labelnames=("endpoint", "outcome"),
)
_M_BUCKET_SHORT = Gauge(
    "rc_riot_api_bucket_short_used",
    "Tokens currently held in the 20/s short-term rate-limit bucket.",
)
_M_BUCKET_LONG = Gauge(
    "rc_riot_api_bucket_long_used",
    "Tokens currently held in the 100/120s long-term rate-limit bucket.",
)


def _bump_metric(endpoint: str, outcome: str) -> None:
    try:
        _M_CALLS_TOTAL.inc(endpoint=endpoint, outcome=outcome)
        snap = _BUCKET.snapshot()
        _M_BUCKET_SHORT.set(snap["short_used"])
        _M_BUCKET_LONG.set(snap["long_used"])
    except Exception:    # pragma: no cover - metrics must never fault callers  # noqa: BLE001
        pass


# -- HTTP transport ------------------------------------------------------

_HTTP_TIMEOUT_S = 4.0


class _HttpResp:
    __slots__ = ("status", "body", "headers")

    def __init__(self, status: int, body: bytes, headers: dict) -> None:
        self.status = status
        self.body = body
        self.headers = headers


def _http_get(url: str, api_key: str, timeout_s: float = _HTTP_TIMEOUT_S) -> _HttpResp:
    """One-shot HTTPS GET to a Riot endpoint.

    Encapsulated so tests can monkey-patch the function rather than
    intercepting urllib internals. Always returns an `_HttpResp` -
    network errors are caller's responsibility to catch.
    """
    req = urllib.request.Request(
        url,
        headers={
            "X-Riot-Token": api_key,
            "Accept":       "application/json",
            "User-Agent":   "rc-riot-api/1",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            body = r.read()
            return _HttpResp(r.status, body, dict(r.headers))
    except urllib.error.HTTPError as exc:
        # HTTPError is NOT a plain exception. Its MRO ends
        # `OSError -> addinfourl -> addbase -> _TemporaryFileWrapper`, so it
        # OWNS the file object wrapping the socket, and `read()` does not
        # release it - only `close()` does. Returning without closing leaves
        # the connection held until the garbage collector happens to run.
        # This is a hot path, not a corner: RM-163 records the timeline route
        # 404/403-ing on EVERY /api/last-match build before negative caching
        # landed, so the leak was continuous. The close is in a `finally` so
        # it also covers the `read()` failure above it, and it is suppressed
        # because a close on an already-broken socket can itself raise and
        # must not turn a handled 404 into an unhandled exception.
        try:
            try:
                body = exc.read(4096)
            except Exception:  # noqa: BLE001
                body = b""
            return _HttpResp(int(exc.code), body, dict(exc.headers or {}))
        finally:
            with contextlib.suppress(Exception):
                exc.close()


# -- shared call wrapper -------------------------------------------------

def _call_ex(
    endpoint_label: str,
    url: str,
    rate_limit_timeout_s: float = 5.0,
) -> tuple[Optional[dict], str]:
    """Rate-limited HTTPS GET returning `(parsed_json_or_None, outcome)`.

    `_call` below discards the outcome and is the right call for endpoints
    that do not cache. Anything that CACHES must use this one, because a bare
    None cannot distinguish "Riot has no such resource" - a permanent answer
    worth remembering - from "the network blinked", which must be retried.
    RM-163: collapsing the two is what made every /api/last-match build pay a
    fresh 289ms timeline round trip forever.

    Outcomes (also the `outcome` metric label, except that `not_found` /
    `forbidden` still report as `error` so the label set is unchanged):
      no_key       - API key file missing/invalid; nothing fired
      rate_limited - bucket full for `rate_limit_timeout_s`; nothing fired
      429          - Riot returned 429; caller should back off
      not_found    - 404; Riot has no such resource (CACHEABLE NEGATIVE)
      forbidden    - 403; not served to this key/route (CACHEABLE NEGATIVE)
      error        - network exception, 401, 5xx, or JSON parse failure
      ok           - 200 with parsed body
    """
    key = _get_api_key()
    if key is None:
        _bump_metric(endpoint_label, "no_key")
        return None, "no_key"
    if not _BUCKET.acquire(timeout_s=rate_limit_timeout_s):
        log.warning("riot_api: bucket exhausted on %s", endpoint_label)
        _bump_metric(endpoint_label, "rate_limited")
        return None, "rate_limited"
    try:
        resp = _http_get(url, key)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        log.warning("riot_api: %s network error: %s", endpoint_label, exc)
        _bump_metric(endpoint_label, "error")
        return None, "error"

    if resp.status == 200:
        try:
            data = json.loads(resp.body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            log.warning("riot_api: %s parse error: %s", endpoint_label, exc)
            _bump_metric(endpoint_label, "error")
            return None, "error"
        _bump_metric(endpoint_label, "ok")
        return data, "ok"
    if resp.status == 429:
        retry_after = 60
        try:
            retry_after = int(resp.headers.get("Retry-After", "60"))
        except (TypeError, ValueError):
            retry_after = 60
        log.warning("riot_api: 429 on %s, retry-after=%ds",
                    endpoint_label, retry_after)
        _BUCKET.note_429(retry_after)
        _bump_metric(endpoint_label, "429")
        return None, "429"
    if resp.status == 404:
        # Not an error condition - Riot is answering. Match-V5 404s a match
        # id it never had, Account-V1 404s a Riot ID nobody owns.
        log.debug("riot_api: %s returned 404", endpoint_label)
        _bump_metric(endpoint_label, "error")
        return None, "not_found"
    if resp.status == 403:
        # AMBIGUOUS BY DESIGN, and the ambiguity is why the negative TTL is
        # bounded. Riot 403s BOTH the event modes Match-V5 does not serve
        # (ARAM Mayhem KIWI / queue 2400 - expected and permanent) AND a
        # revoked key. Treating it as cacheable is what fixes the measured
        # case; capping the entry at _NEGATIVE_TTL_S is what keeps the other
        # reading from outliving a key rotation.
        log.warning(
            "riot_api: %s returned 403 - either an unserved route/mode or a "
            "revoked key. Check %s if this is unexpected.",
            endpoint_label, _API_KEY_FILE,
        )
        _bump_metric(endpoint_label, "error")
        return None, "forbidden"
    if resp.status == 401:
        log.warning(
            "riot_api: %s returned 401 - key may be invalid or revoked. "
            "Check %s and re-issue if needed.",
            endpoint_label, _API_KEY_FILE,
        )
        _bump_metric(endpoint_label, "error")
        return None, "error"
    log.warning("riot_api: %s returned %d", endpoint_label, resp.status)
    _bump_metric(endpoint_label, "error")
    return None, "error"


def _call(
    endpoint_label: str,
    url: str,
    rate_limit_timeout_s: float = 5.0,
) -> Optional[dict]:
    """Rate-limited HTTPS GET returning parsed JSON or None on any failure.

    Thin projection of `_call_ex`. Correct for endpoints that do not cache
    (match-id lists, replay URLs, the TTL-cached lookups); anything writing
    to the immutable cache needs the outcome and must call `_call_ex`.
    """
    return _call_ex(endpoint_label, url, rate_limit_timeout_s)[0]


# -- negative caching (RM-163) -------------------------------------------

# Outcomes that mean "Riot answered, and the answer is that this does not
# exist / is not served". Everything else - 429, 5xx, 401, transport
# failures, and the two cases where nothing was even sent (no_key,
# rate_limited) - is a statement about the connection or our credentials,
# never about the resource, and caching it would turn a blip into a
# self-inflicted outage.
_CACHEABLE_NEGATIVE_OUTCOMES = frozenset({"not_found", "forbidden"})

# TTL per outcome. Both are SHORT, and the split is by how likely Riot is to
# change its mind - which is the only thing a negative TTL is really about.
#
#   not_found (404) - 300s. Riot says it does not have this. For a timeline
#     that is very often TEMPORARY: a match that just ended has its detail
#     before its timeline, so a post-game review opened within seconds of the
#     game hits a 404 that resolves minutes later. A long TTL here would hide
#     a real SR timeline from post-game review long after Riot published it,
#     which is a NEW bug traded for an old one. 5 minutes caps that blindness
#     below the time it takes to finish a queue and load the next game, and
#     still removes ~90 pct of the re-fetches (one per 5 min against one per
#     30s, the response-cache cadence).
#
#   forbidden (403) - 900s. Riot says it will not serve this route/mode to
#     us. With the API-key fingerprint in the negative key (see
#     `_negative_key`), the "rotated key" reading of a 403 can no longer
#     outlive the rotation, so what is left is the entitlement reading -
#     event modes like ARAM Mayhem KIWI / queue 2400, which are PERMANENT and
#     never backfill. It gets the longer TTL for that reason. It is capped at
#     15 minutes rather than an hour because the value curve is flat above
#     ~900s (over a 3-hour session: 12 calls at 900s vs 3 at 3600s, against
#     360 pre-fix) while the cost of being wrong keeps rising with the clock.
#
# NOTE: this ordering is deliberately the REVERSE of the first review pass,
# which proposed not_found=3600 / forbidden=300 on the ground that 403 is the
# ambiguous one. That ambiguity was real but it was a KEY-ATTRIBUTION problem,
# and fingerprinting the key into the negative key removes it structurally.
# Once it is gone, the only axis left is backfill likelihood, and on that axis
# 404 is the volatile one. Flip these two numbers if that reasoning is wrong;
# both are pinned by test so a flip is a one-line, one-test change.
_NEGATIVE_TTL_S_BY_OUTCOME = {
    "not_found": 300,
    "forbidden": 900,
}

# Used only if a future outcome joins _CACHEABLE_NEGATIVE_OUTCOMES without
# getting an entry above. Deliberately the SHORTEST value, so forgetting the
# table costs a few extra calls rather than a stale answer.
_NEGATIVE_TTL_FALLBACK_S = 300


def _negative_ttl_for(outcome: str) -> int:
    return int(_NEGATIVE_TTL_S_BY_OUTCOME.get(outcome, _NEGATIVE_TTL_FALLBACK_S))


# Key namespace for negatives. Load-bearing: it keeps a negative from ever
# colliding with a POSITIVE key in the same TTL table. Nothing collides today
# (no production caller writes a positive under `cached_get(..., ttl_s=)`),
# but the prefix is what keeps that true when one does.
_NEGATIVE_PREFIX = "neg"

# Marker field inside the stored row. The row exists to be COUNTED as absent,
# never returned: `_negative_cached` reports a bool and the callers return
# None, so no consumer ever sees this dict.
_NEGATIVE_MARKER = "__rc_negative__"


def _negative_key(cache_key: str) -> str:
    """Namespace the negative, SCOPED TO THE ACTIVE API KEY.

    Deliberately a DIFFERENT key in a DIFFERENT table: the positive lives in
    `cache_immutable`, which never expires, and a negative must never be able
    to land there - one bad window would otherwise blacklist a match for the
    life of the DB with no way back short of manual SQL.

    THE FINGERPRINT IS THE LOAD-BEARING PART. A 403 does not distinguish "Riot
    does not serve this mode" from "your key expired", and the expired-key
    reading fans out: every match and timeline id touched by /api/last-match,
    dashboard/builders_lcu_enrich.py, lib/rewind_live_writer.py and
    dashboard/routes_scouting.py would take a negative. Without the
    fingerprint, installing a FRESH VALID KEY would not clear any of them and
    RC would stay blind until they aged out - a cache that ignores the
    operator having already fixed the problem. With it, a new key is a new
    namespace and every stale negative is unreachable immediately.

    `get_account_by_riot_id` already fingerprints its POSITIVE key for the
    same class of reason (PUUIDs are key-scoped); `match:v5:` keys do not need
    it on the positive side, because match data is key-independent. Negatives
    are the opposite: the ANSWER depends on the key even when the resource
    does not.
    """
    return f"{_NEGATIVE_PREFIX}:{_key_fingerprint()}:{cache_key}"


def _negative_cached(cache_key: str) -> bool:
    """True when a live negative entry shadows `cache_key`."""
    row = get_cache().get_ttl(_negative_key(cache_key))
    return isinstance(row, dict) and row.get(_NEGATIVE_MARKER) is True


def _note_negative(cache_key: str, outcome: str) -> None:
    """Record that Riot has nothing for `cache_key`, for this outcome's TTL."""
    get_cache().set_ttl(
        _negative_key(cache_key),
        {_NEGATIVE_MARKER: True, "outcome": outcome, "at": int(time.time())},
        _negative_ttl_for(outcome),
    )


def _cached_or_fetch(
    endpoint_label: str,
    cache_key: str,
    url_fn: Any,
) -> Optional[dict]:
    """Immutable-cache read-through with RM-163 negative caching.

    The three immutable-cached endpoints below shared one body verbatim, and
    fixing only the timeline would have left the same defect in the other two
    - so they share it here instead of each carrying a copy.

    `url_fn` is a zero-arg callable, not a string, so the URL is built only on
    a MISS. Taking a built string would put `urllib.parse.quote` and an
    f-string on the cache-hit path, which is the exact path this row exists
    to make cheap.
    """
    cached = get_cache().get_immutable(cache_key)
    if cached is not None:
        _bump_metric(endpoint_label, "cache")
        return cached
    if _negative_cached(cache_key):
        _bump_metric(endpoint_label, "cache_negative")
        return None
    data, outcome = _call_ex(endpoint_label, url_fn())
    if data is not None:
        get_cache().set_immutable(cache_key, data)
    elif outcome in _CACHEABLE_NEGATIVE_OUTCOMES:
        _note_negative(cache_key, outcome)
    return data


# -- endpoint wrappers ---------------------------------------------------

def get_account_by_riot_id(
    name: str,
    tag: str,
    region: str = "americas",
) -> Optional[dict]:
    """Account-V1: PUUID lookup by Riot ID (game-name + tag-line).

    Cached in the immutable cache, SCOPED TO THE ACTIVE API KEY. The Riot ID is
    the durable identity; the PUUID is a key-scoped handle - Riot encrypts it
    per API key, so rotating the key changes the value. Without the fingerprint
    in the cache key, one rotation permanently poisons this row and every
    caller gets a PUUID that 400s "Exception decrypting" - returned from cache
    below before any network call, so even a deliberate re-resolve cannot
    escape it.

    Sibling keys need no equivalent: `league:v4:{region}:{puuid}` and the
    mastery keys embed the PUUID itself, so a new key yields a new cache key
    for free.
    """
    cache_key = f"account:v1:{_key_fingerprint()}:{region}:{name}#{tag}".lower()

    def _url() -> str:
        name_e = urllib.parse.quote(name, safe="")
        tag_e = urllib.parse.quote(tag, safe="")
        return (
            f"https://{region}.api.riotgames.com"
            f"/riot/account/v1/accounts/by-riot-id/{name_e}/{tag_e}"
        )

    return _cached_or_fetch("account_v1", cache_key, _url)


def get_replay_urls(
    puuid: str,
    region: str = "americas",
) -> Optional[list]:
    """Match-V5: pre-signed download URLs for this account's retained replays.

    MEASURED 2026-07-19: 200 `{"total": 5, "matchFileURLs": [...]}`, each a
    pre-signed S3 link on `lol-prod-us-west-2-match-history-replay` with
    `response-content-disposition=attachment; filename="NA1_xxxx.rofl"`.

    Deliberately NOT cached: the URLs carry `X-Amz-Expires=3600`, so a cached
    list is a list of dead links inside the hour. Riot serves exactly FIVE per
    account - a rolling recency window, not an archive - which is why the
    caller archives what it pulls.

    ENTITLEMENT: `/replays` is approved for the PRODUCT app (834837) only; the
    personal/dev key 400s on this exact route. `API-Key-Riot.txt` must hold the
    product key. Rate limit is 20000/10s, so throughput never binds here.
    """
    if not puuid:
        return None
    url = (
        f"https://{region}.api.riotgames.com"
        f"/lol/match/v5/matches/by-puuid/{urllib.parse.quote(puuid, safe='')}"
        f"/replays"
    )
    data = _call("match_v5_replays", url)
    if data is None:
        return None
    urls = data.get("matchFileURLs") if isinstance(data, dict) else None
    if not isinstance(urls, list):
        log.warning("riot_api: match_v5_replays unexpected shape: %s",
                    type(data).__name__)
        return None
    return urls


def get_recent_matches(
    puuid: str,
    count: int = 20,
    region: str = "americas",
    start: int = 0,
    start_time_unix_s: Optional[int] = None,
    end_time_unix_s: Optional[int] = None,
    queue: Optional[int] = None,
    match_type: Optional[str] = None,
) -> Optional[list]:
    """Match-V5: list of recent match IDs for a PUUID.

    Not cached - the list mutates every game. Caller decides cadence.

    ``start`` (0-based) + ``count`` (1..100) drive Riot's pagination.
    ``start_time_unix_s`` / ``end_time_unix_s`` filter the window; both
    are epoch SECONDS, not milliseconds. ``queue`` filters by queue id
    (420 ranked solo, 440 flex, 900 URF, etc.). ``match_type`` filters
    by Riot's enum (``ranked``, ``normal``, ``tourney``, ``tutorial``).
    All optional params are appended only when set so the URL stays
    minimal in the common case.
    """
    if not puuid:
        return None
    count = max(1, min(100, int(count)))
    start = max(0, int(start))
    params: list[tuple[str, Any]] = [("start", start), ("count", count)]
    if start_time_unix_s is not None:
        params.append(("startTime", int(start_time_unix_s)))
    if end_time_unix_s is not None:
        params.append(("endTime", int(end_time_unix_s)))
    if queue is not None:
        params.append(("queue", int(queue)))
    if match_type:
        params.append(("type", str(match_type)))
    qs = "&".join(f"{k}={urllib.parse.quote(str(v), safe='')}" for k, v in params)
    url = (
        f"https://{region}.api.riotgames.com"
        f"/lol/match/v5/matches/by-puuid/{urllib.parse.quote(puuid, safe='')}"
        f"/ids?{qs}"
    )
    data = _call("match_v5_ids", url)
    if data is None:
        return None
    if not isinstance(data, list):
        log.warning("riot_api: match_v5_ids unexpected shape: %s",
                    type(data).__name__)
        return None
    return data


def get_match(
    match_id: str,
    region: str = "americas",
) -> Optional[dict]:
    """Match-V5: full match detail. Immutable cache - match data never changes."""
    if not match_id:
        return None
    cache_key = f"match:v5:{match_id}"
    return _cached_or_fetch("match_v5_detail", cache_key, lambda: (
        f"https://{region}.api.riotgames.com"
        f"/lol/match/v5/matches/{urllib.parse.quote(match_id, safe='')}"
    ))


def get_match_timeline(
    match_id: str,
    region: str = "americas",
) -> Optional[dict]:
    """Match-V5: per-event timeline. Immutable cache."""
    if not match_id:
        return None
    cache_key = f"match:v5:timeline:{match_id}"
    return _cached_or_fetch("match_v5_timeline", cache_key, lambda: (
        f"https://{region}.api.riotgames.com"
        f"/lol/match/v5/matches/{urllib.parse.quote(match_id, safe='')}/timeline"
    ))


_RANK_TTL_S = 300


def get_summoner_rank(
    puuid: str,
    region: str = "na1",
) -> Optional[list]:
    """League-V4: ranked entries for a PUUID. TTL-cached (5 min).

    Riot's league/v4/entries/by-puuid returns a list - one entry per
    queue (RANKED_SOLO_5x5 / RANKED_FLEX_SR / etc.). Empty list = unranked.

    NO NEGATIVE CACHING HERE, AND THIS IS NOT AN OVERSIGHT (RM-163). The
    defect shape is present: the `if data is None: return None` below writes
    nothing on a 404, exactly like the immutable endpoints did, so the
    re-fetch is just as unbounded - `_RANK_TTL_S` bounds the POSITIVE only.
    It is left that way on purpose, because rank and mastery are MUTABLE
    resources and a cached negative about them would be wrong by design: an
    unranked player placing, or a first game on a new champion, both turn a
    correct 404 into a stale "no data" the moment it is recorded. A negative
    is only safe over a resource whose absence is a fact about the past, which
    is true of a finished match and false of a live ladder standing. Same
    reasoning applies to `get_champion_mastery` and
    `get_top_champion_masteries`.
    """
    if not puuid:
        return None
    cache_key = f"league:v4:{region}:{puuid}"
    cached = get_cache().get_ttl(cache_key)
    if cached is not None:
        _bump_metric("league_v4", "cache")
        # Cache stores wrapped under a key for shape consistency.
        return cached.get("entries") if isinstance(cached, dict) else cached
    url = (
        f"https://{region}.api.riotgames.com"
        f"/lol/league/v4/entries/by-puuid/{urllib.parse.quote(puuid, safe='')}"
    )
    data = _call("league_v4", url)
    if data is None:
        return None
    if not isinstance(data, list):
        log.warning("riot_api: league_v4 unexpected shape: %s",
                    type(data).__name__)
        return None
    get_cache().set_ttl(cache_key, {"entries": data}, _RANK_TTL_S)
    return data


_MASTERY_TTL_S = 300

# Upper bound on `get_top_champion_masteries(count=)`. Mirrors the 100 that
# `get_recent_matches` already clamps to, and sits comfortably below the
# 173-champion roster, so no real caller can notice it.
_MAX_MASTERY_COUNT = 100


def get_champion_mastery(
    puuid: str,
    champion_id: int,
    region: str = "na1",
) -> Optional[dict]:
    """Champion-Mastery-V4: per-champion mastery for a PUUID. TTL-cached (5 min)."""
    if not puuid or not champion_id:
        return None
    champion_id = int(champion_id)
    cache_key = f"mastery:v4:{region}:{puuid}:{champion_id}"
    cached = get_cache().get_ttl(cache_key)
    if cached is not None:
        _bump_metric("mastery_v4", "cache")
        return cached
    url = (
        f"https://{region}.api.riotgames.com"
        f"/lol/champion-mastery/v4/champion-masteries/by-puuid/"
        f"{urllib.parse.quote(puuid, safe='')}/by-champion/{champion_id}"
    )
    data = _call("mastery_v4", url)
    # The shape check used to guard only the cache write, so an unexpected
    # body was refused entry to the cache and then returned to the caller
    # anyway - from a function annotated `-> Optional[dict]`. Both siblings
    # (`get_summoner_rank`, `get_top_champion_masteries`) return None on a
    # wrong shape; the asymmetry was the defect, not the check.
    if not isinstance(data, dict):
        if data is not None:
            log.warning("riot_api: mastery_v4 unexpected shape: %s",
                        type(data).__name__)
        return None
    get_cache().set_ttl(cache_key, data, _MASTERY_TTL_S)
    return data


def get_top_champion_masteries(
    puuid: str,
    count: int = 3,
    region: str = "na1",
) -> Optional[list]:
    """Champion-Mastery-V4: a PUUID's top-``count`` champions by mastery points,
    highest first. TTL-cached (5 min). Returns a list of mastery dicts
    (``championId`` / ``championLevel`` / ``championPoints`` ...) or None on any
    failure. Used to surface each party member's main in the pre-game lobby.
    """
    if not puuid:
        return None
    try:
        # Clamped at BOTH ends, matching `get_recent_matches`. `count` reaches
        # the Riot query string and the TTL cache key, so an unbounded value
        # is both a request Riot rejects and a cache row per distinct integer.
        count = max(1, min(_MAX_MASTERY_COUNT, int(count)))
    except (TypeError, ValueError):
        count = 3
    cache_key = f"mastery_top:v4:{region}:{puuid}:{count}"
    cached = get_cache().get_ttl(cache_key)
    if cached is not None:
        _bump_metric("mastery_v4_top", "cache")
        return cached
    url = (
        f"https://{region}.api.riotgames.com"
        f"/lol/champion-mastery/v4/champion-masteries/by-puuid/"
        f"{urllib.parse.quote(puuid, safe='')}/top?count={count}"
    )
    data = _call("mastery_v4_top", url)
    if isinstance(data, list):
        get_cache().set_ttl(cache_key, data, _MASTERY_TTL_S)
        return data
    return None


# -- high-level helpers used by the team-context fan-out -----------------

# Mapping from Riot tier name -> ordinal for sorting / formatting.
_TIER_ORDER = (
    "IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM", "EMERALD",
    "DIAMOND", "MASTER", "GRANDMASTER", "CHALLENGER",
)


def format_rank_entry(entry: dict) -> str:
    """Render a League-V4 entry into the dashboard string format.

    Example: {"tier":"PLATINUM","rank":"IV","leaguePoints":47,...}
             -> "PLATINUM IV 47 LP"
    """
    if not isinstance(entry, dict):
        return ""
    tier = str(entry.get("tier") or "").upper()
    division = str(entry.get("rank") or "").upper()
    lp = entry.get("leaguePoints")
    if not tier:
        return ""
    parts = [tier]
    if division:
        parts.append(division)
    if isinstance(lp, (int, float)):
        parts.append(f"{int(lp)} LP")
    return " ".join(parts)


def pick_solo_rank(entries: list) -> Optional[dict]:
    """Pick the RANKED_SOLO_5x5 entry from a League-V4 list, falling back
    to the highest-tier entry if solo isn't present (some accounts only
    have flex)."""
    if not entries:
        return None
    solo = next(
        (e for e in entries
         if isinstance(e, dict)
         and str(e.get("queueType") or "").upper() == "RANKED_SOLO_5X5"),
        None,
    )
    if solo is not None:
        return solo
    ranked = [e for e in entries if isinstance(e, dict)
              and str(e.get("tier") or "").upper() in _TIER_ORDER]
    if not ranked:
        return None
    ranked.sort(
        key=lambda e: _TIER_ORDER.index(str(e.get("tier") or "").upper()),
        reverse=True,
    )
    return ranked[0]


def summarize_recent(
    puuid: str,
    match_ids: list,
    region: str = "americas",
) -> dict:
    """Walk a list of match IDs and produce mains + winrate + W/L streak.

    Returns a dict with keys:
      mains:           list[str]   top-3 most-played champion names
      win_rate_recent: float       wins / total over the sample
      w_l_streak_7:    list[int]   [wins, losses] over the last 7 games

    Cache-leveraged: every match is fetched via get_match() which caches
    immutably. Re-running this for the same PUUID after the first
    cold-fill is O(N) cache reads with no API calls.

    Soft-fail: missing data -> counted as zero contribution; the result
    keys always exist with sensible defaults so the dashboard renderer
    can blindly splat them into the entry.
    """
    out: dict = {
        "mains":           [],
        "win_rate_recent": 0.0,
        "w_l_streak_7":    [0, 0],
    }
    if not puuid or not match_ids:
        return out
    champ_counts: dict = {}
    wins = 0
    losses = 0
    last7_w = 0
    last7_l = 0
    seen = 0
    # Match IDs are returned newest-first - first 7 are the streak window.
    for idx, mid in enumerate(match_ids):
        match = get_match(mid, region=region)
        if not isinstance(match, dict):
            continue
        info = match.get("info") or {}
        participants = info.get("participants") or []
        if not isinstance(participants, list):
            continue
        me = next(
            (p for p in participants
             if isinstance(p, dict) and p.get("puuid") == puuid),
            None,
        )
        if me is None:
            continue
        seen += 1
        champ = str(me.get("championName") or "").strip()
        if champ:
            champ_counts[champ] = champ_counts.get(champ, 0) + 1
        win = bool(me.get("win"))
        if win:
            wins += 1
            if idx < 7:
                last7_w += 1
        else:
            losses += 1
            if idx < 7:
                last7_l += 1
    if seen:
        out["win_rate_recent"] = round(wins / seen, 3)
    out["w_l_streak_7"] = [last7_w, last7_l]
    if champ_counts:
        ranked = sorted(
            champ_counts.items(),
            key=lambda kv: (-kv[1], kv[0]),
        )
        out["mains"] = [name for name, _ in ranked[:3]]
    return out


# -- public surface for tests / introspection ----------------------------

def bucket_snapshot() -> dict:
    """Read-only view of the rate-limit bucket (for /metrics + tests)."""
    return _BUCKET.snapshot()


def is_configured() -> bool:
    """True iff the API key file is present and well-formed."""
    return _get_api_key() is not None


__all__ = [
    "DualBucket",
    "bucket_snapshot",
    "format_rank_entry",
    "get_account_by_riot_id",
    "get_champion_mastery",
    "get_top_champion_masteries",
    "get_match",
    "get_match_timeline",
    "get_recent_matches",
    "get_summoner_rank",
    "is_configured",
    "pick_solo_rank",
    "reload_api_key",
    "summarize_recent",
]
