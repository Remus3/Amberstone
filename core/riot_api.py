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
    """Read + cache the Personal-tier Riot API key.

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
        except OSError as exc:
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


def reload_api_key() -> None:
    """Force re-read of the API key file. Call after operator rotates."""
    global _KEY_CACHE, _KEY_WARNED_MISSING
    with _KEY_LOCK:
        _KEY_CACHE = None
        _KEY_WARNED_MISSING = False


# -- dual-bucket rate limiter --------------------------------------------

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
    ) -> None:
        self._short: collections.deque = collections.deque()
        self._long: collections.deque = collections.deque()
        self._short_n = int(short_n)
        self._short_w = float(short_window_s)
        self._long_n = int(long_n)
        self._long_w = float(long_window_s)
        self._lock = threading.Lock()
        # Tracks a forced cool-down imposed by a 429 response. Until
        # `_cooldown_until` passes, acquire() returns False even if the
        # local deques would admit. Set by `note_429`.
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
        """Caller observed a 429 - pause acquires until retry_after passes."""
        with self._lock:
            self._cooldown_until = time.monotonic() + max(0.0, float(retry_after_s))

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
    "Riot Web API calls by endpoint and outcome (ok / cache / error / "
    "rate_limited / no_key / 429).",
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
        try:
            body = exc.read(4096)
        except Exception:  # noqa: BLE001
            body = b""
        return _HttpResp(int(exc.code), body, dict(exc.headers or {}))


# -- shared call wrapper -------------------------------------------------

def _call(
    endpoint_label: str,
    url: str,
    rate_limit_timeout_s: float = 5.0,
) -> Optional[dict]:
    """Rate-limited HTTPS GET returning parsed JSON or None on any failure.

    Outcome metrics (`outcome` label):
      no_key       - API key file missing/invalid; nothing fired
      rate_limited - bucket full for `rate_limit_timeout_s`
      429          - Riot returned 429; caller should back off
      error        - network exception, non-2xx, or JSON parse failure
      ok           - 200 with parsed body
    """
    key = _get_api_key()
    if key is None:
        _bump_metric(endpoint_label, "no_key")
        return None
    if not _BUCKET.acquire(timeout_s=rate_limit_timeout_s):
        log.warning("riot_api: bucket exhausted on %s", endpoint_label)
        _bump_metric(endpoint_label, "rate_limited")
        return None
    try:
        resp = _http_get(url, key)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        log.warning("riot_api: %s network error: %s", endpoint_label, exc)
        _bump_metric(endpoint_label, "error")
        return None

    if resp.status == 200:
        try:
            data = json.loads(resp.body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            log.warning("riot_api: %s parse error: %s", endpoint_label, exc)
            _bump_metric(endpoint_label, "error")
            return None
        _bump_metric(endpoint_label, "ok")
        return data
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
        return None
    if resp.status in (401, 403):
        log.warning(
            "riot_api: %s returned %d - key may be invalid or revoked. "
            "Check %s and re-issue if needed.",
            endpoint_label, resp.status, _API_KEY_FILE,
        )
        _bump_metric(endpoint_label, "error")
        return None
    log.warning("riot_api: %s returned %d", endpoint_label, resp.status)
    _bump_metric(endpoint_label, "error")
    return None


# -- endpoint wrappers ---------------------------------------------------

def get_account_by_riot_id(
    name: str,
    tag: str,
    region: str = "americas",
) -> Optional[dict]:
    """Account-V1: PUUID lookup by Riot ID (game-name + tag-line).

    Cached in the immutable cache - Riot IDs map stably to PUUIDs.
    """
    name_e = urllib.parse.quote(name, safe="")
    tag_e = urllib.parse.quote(tag, safe="")
    cache_key = f"account:v1:{region}:{name}#{tag}".lower()
    cached = get_cache().get_immutable(cache_key)
    if cached is not None:
        _bump_metric("account_v1", "cache")
        return cached
    url = (
        f"https://{region}.api.riotgames.com"
        f"/riot/account/v1/accounts/by-riot-id/{name_e}/{tag_e}"
    )
    data = _call("account_v1", url)
    if data is not None:
        get_cache().set_immutable(cache_key, data)
    return data


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
    cached = get_cache().get_immutable(cache_key)
    if cached is not None:
        _bump_metric("match_v5_detail", "cache")
        return cached
    url = (
        f"https://{region}.api.riotgames.com"
        f"/lol/match/v5/matches/{urllib.parse.quote(match_id, safe='')}"
    )
    data = _call("match_v5_detail", url)
    if data is not None:
        get_cache().set_immutable(cache_key, data)
    return data


def get_match_timeline(
    match_id: str,
    region: str = "americas",
) -> Optional[dict]:
    """Match-V5: per-event timeline. Immutable cache."""
    if not match_id:
        return None
    cache_key = f"match:v5:timeline:{match_id}"
    cached = get_cache().get_immutable(cache_key)
    if cached is not None:
        _bump_metric("match_v5_timeline", "cache")
        return cached
    url = (
        f"https://{region}.api.riotgames.com"
        f"/lol/match/v5/matches/{urllib.parse.quote(match_id, safe='')}/timeline"
    )
    data = _call("match_v5_timeline", url)
    if data is not None:
        get_cache().set_immutable(cache_key, data)
    return data


_RANK_TTL_S = 300


def get_summoner_rank(
    puuid: str,
    region: str = "na1",
) -> Optional[list]:
    """League-V4: ranked entries for a PUUID. TTL-cached (5 min).

    Riot's league/v4/entries/by-puuid returns a list - one entry per
    queue (RANKED_SOLO_5x5 / RANKED_FLEX_SR / etc.). Empty list = unranked.
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
    if data is not None and isinstance(data, dict):
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
        count = max(1, int(count))
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
