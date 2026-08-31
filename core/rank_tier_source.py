"""Live rank-tier aggregate fetch primitive (overlay item 8, Phase 1).

The LIVE half of the in-game rank-tier stats panel. The consumer
(`core.rank_tier_bench`) runs on a committed STATIC estimate seed
(`data/rank_tiers/rank_tier_averages.seed.json`, lifted from the
last_match.js `_RANK_TIER_AVERAGES` reference table). This module is the
optional on-demand refresh: given a tier + mode it fetches a per-tier
metric-average payload from an operator-configured aggregate endpoint so
the bench can serve measured numbers instead of the estimate.

There is NO real endpoint wired in this phase. The module is import-safe
and returns None cleanly whenever it is unconfigured (no
`config/rank_tier_source.json`, `enabled` false, or an empty endpoint) -
so `rank_tier_bench` falls back to the static seed. The endpoint + keys
live in gitignored `config/rank_tier_source.json` (template committed as
`config/rank_tier_source.example.json`).

Mirrors `core.synergy_external_source`: an in-memory TTL cache, a
monkeypatchable `_http_get_json` seam, and fail-soft semantics (any
failure returns None, never raises out of `fetch_rows`).

Hardening (the endpoint is operator-configured third-party input, and the
consumer sweeps 20 (tier, mode) cells per refresh):
  - NEGATIVE CACHING. A failed fetch is remembered for `_NEG_TTL_S`, so a
    down endpoint costs one timeout per minute instead of one per call
    (20 per bench refresh). `force_refresh=True` bypasses it.
  - BOUNDED RESPONSE READ. The body is read in chunks up to
    `_MAX_BODY_BYTES`; anything larger is rejected without being
    materialised, so a hostile or wedged endpoint cannot exhaust memory.
  - ENDPOINT-AWARE CACHE KEY. The endpoint lives in config and is re-read
    on every call, so the cache key carries a short digest of the resolved
    config identity. Changing the endpoint invalidates cached rows instead
    of serving the old endpoint's data for up to the 6h TTL. It is a
    DIGEST, never the raw endpoint, because the endpoint may embed an API
    key and cache keys surface in reprs, debuggers and crash dumps.
  - NO RAW URL IN A MESSAGE. `_build_url` composes the fetch URL verbatim from
    that same endpoint, so the URL carries the credential too. Every exception
    message names the endpoint through `_safe_url` (scheme + host + port +
    path; query, fragment and userinfo dropped) and every wrapped third-party
    message goes through `_redact` first, because urllib quotes the URL it was
    handed straight back at us. Machine-guarded by an AST taint scan over
    every raise + logging site in tests/test_rank_tier_live_budget.py.
  - NO NON-FINITE NUMBERS. `json.loads` accepts the non-standard literals
    NaN / Infinity / -Infinity by default; such a value passes an
    `isinstance(x, float)` check, survives `float()`, reaches the grid, and
    `json.dumps` then re-emits a bare `NaN` token that a browser
    `JSON.parse` rejects - poisoning the WHOLE dashboard response, not one
    row. `parse_constant` kills the class at the parse boundary.

Row contract (the `data` list the endpoint returns / the bench folds):
each row is a metric-average record
    {"role": "all", "bracket": "early"|"mid", "metric": "cs"|"kda"|"kp",
     "avg": <number>}
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from json import JSONDecodeError, loads
from pathlib import Path
from typing import Callable, Optional

_ROOT = Path(__file__).resolve().parent.parent
# Real config is gitignored; the committed template is the *.example.json.
_CONFIG_PATH = _ROOT / "config" / "rank_tier_source.json"

_USER_AGENT = "Mozilla/5.0 (RC rank-tier fetch)"
_TTL_S = 6 * 3600.0          # in-memory cache lifetime (matches synergy source)
_TIMEOUT_S = 6.0
# How long a FAILED (tier, mode, endpoint) is remembered. Short on purpose: it
# exists to stop the bench's 20-cell sweep re-paying a full timeout per cell,
# not to keep a recovered endpoint dark.
_NEG_TTL_S = 60.0
# Hard ceiling on an untrusted response body. A rank-tier aggregate is a few
# hundred rows of small numbers; 2 MiB is orders of magnitude of headroom.
_MAX_BODY_BYTES = 2 * 1024 * 1024
_READ_CHUNK_BYTES = 65536

_VALID_TIERS = frozenset({
    "iron", "bronze", "silver", "gold", "platinum",
    "emerald", "diamond", "master", "grandmaster", "challenger",
})
_VALID_MODES = frozenset({"SR", "ARAM"})

# Injectable clock so tests are deterministic.
_clock: Callable[[], float] = time.monotonic

# Distinct-from-None sentinel: `null` is a legal JSON document that parses to
# None, so None cannot double as "nothing was parsed".
_UNSET = object()


class RankTierSourceError(RuntimeError):
    """Any fetch/parse failure - caught at the fetch_rows boundary."""


# in-memory caches keyed (tier, mode, config_identity):
#   _cache      -> (fetched_monotonic, rows)      successes, _TTL_S
#   _neg_cache  -> failed_monotonic               failures,  _NEG_TTL_S
_lock = threading.Lock()
_cache: dict[tuple, tuple[float, list]] = {}
_neg_cache: dict[tuple, float] = {}


def _read_config() -> Optional[dict]:
    """Load config/rank_tier_source.json, or None when absent/unparseable.

    Fail-soft: a missing file (the default in this phase) is the normal
    unconfigured state, not an error."""
    try:
        raw = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, JSONDecodeError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def _config_enabled(cfg: Optional[dict]) -> bool:
    """True only when a config is present, explicitly enabled, and carries a
    non-empty endpoint. Anything else keeps the source dark (bench -> seed)."""
    if not isinstance(cfg, dict):
        return False
    endpoint = cfg.get("endpoint")
    return bool(cfg.get("enabled")) and isinstance(endpoint, str) and bool(endpoint.strip())


def _config_identity(cfg: Optional[dict]) -> str:
    """Short stable digest of the RESOLVED endpoint identity.

    Bound into the cache key so an operator endpoint edit invalidates cached
    rows rather than serving the previous endpoint's data for up to the 6h TTL.

    It is a DIGEST and never the endpoint itself: the endpoint may carry an API
    key in its query string, and cache keys leak into reprs, debuggers and
    crash dumps. Nothing in this module may log it or put it in an exception
    message - nor the endpoint, nor a URL built from it. Guarded by
    tests/test_rank_tier_live_budget.py
    ::test_defect_f_no_message_site_in_the_module_carries_the_raw_endpoint, an
    AST taint scan over every raise + logging site. That guard USED to filter
    candidate lines on "ident"/"digest", which made it structurally blind to
    the four `{url}` interpolations that were live in _http_get_json while
    this sentence claimed otherwise - a written invariant the code violates is
    worse than none, because the next reader trusts it."""
    if not isinstance(cfg, dict):
        return "-"
    raw = "\x00".join((
        str(cfg.get("endpoint", "")),
        str(cfg.get("tier_param", "")),
    ))
    return hashlib.blake2s(raw.encode("utf-8", "replace"), digest_size=8).hexdigest()


def _reject_non_finite(constant: str) -> float:
    """json.loads `parse_constant` hook - fires only on NaN / Infinity /
    -Infinity, the non-standard literals Python accepts by default. Raising
    here kills the whole non-finite class at the parse boundary, before any
    isinstance/float check can wave it through and before json.dumps can
    re-emit a bare NaN token that a browser JSON.parse rejects."""
    raise RankTierSourceError(f"non-finite JSON constant in payload: {constant}")


def _build_url(endpoint: str, tier_param: str, tier: str, mode: str) -> str:
    """Compose the aggregate query URL. `tier_param` is the query-string key
    for the tier (defaults to 'tier'); mode rides along as 'mode'.

    The result carries the operator-configured endpoint VERBATIM, credential
    included. It is fine to fetch and never fine to log: put `_safe_url(url)`
    in a message, never `url`."""
    sep = "&" if "?" in endpoint else "?"
    tp = (tier_param or "tier").strip() or "tier"
    return f"{endpoint}{sep}{tp}={tier}&mode={mode}"


def _safe_url(url: str) -> str:
    """The display form of a fetch URL - the only form safe to put in a message.

    Keeps scheme + host + port + path, so an operator reading a log can still
    tell WHICH endpoint failed, and drops the three parts that can carry a
    credential: the query string (where this module's own config note says an
    API key lives), the fragment, and any userinfo in the netloc. A dropped
    query is MARKED, so "no parameters" and "parameters withheld" stay
    distinguishable. A credential in the PATH would still show - out of scope
    by the same config contract that puts it in the query string."""
    raw = str(url)
    try:
        parts = urllib.parse.urlsplit(raw)
        host = parts.hostname or ""
        port = parts.port
    except ValueError:
        # An unparseable netloc/port. No safe subset can be extracted, so name
        # nothing rather than guess at what is credential-bearing.
        return "<endpoint>"
    netloc = f"{host}:{port}" if (host and port is not None) else host
    shown = urllib.parse.urlunsplit((parts.scheme, netloc, parts.path, "", ""))
    if parts.query or parts.fragment:
        shown = f"{shown}?<redacted>"
    return shown or "<endpoint>"


def _redaction_needles(url: str) -> list:
    """Every substring of `url` that must not survive into a message."""
    raw = str(url)
    out = {raw}
    try:
        parts = urllib.parse.urlsplit(raw)
    except ValueError:
        return [n for n in out if n]
    if parts.query:
        out.add(parts.query)
        for pair in parts.query.split("&"):
            out.add(pair)
            _k, sep, value = pair.partition("=")
            # Long values only: a credential is long, and blanking a short one
            # ("SR", "iron") would mangle unrelated text in the message.
            if sep and len(value) >= 8:
                out.add(value)
    if parts.fragment:
        out.add(parts.fragment)
    userinfo = parts.netloc.rpartition("@")[0]
    if userinfo:
        out.add(parts.netloc)
        out.add(userinfo)
    return [n for n in out if n]


def _redact(text, url: str) -> str:
    """A third-party message with every credential-bearing piece of `url` cut
    out. urllib quotes the URL it was handed straight back at us
    (`urllib.request.Request` does exactly that for a schemeless endpoint), so
    a wrapped message is untrusted text, not a safe diagnostic. Longest needle
    first, so the full URL is replaced as one unit rather than in pieces."""
    out = str(text)
    for needle in sorted(_redaction_needles(url), key=len, reverse=True):
        out = out.replace(needle, "<redacted>")
    return out


def _http_get_json(url: str, timeout_s: float = _TIMEOUT_S) -> dict:
    """One-shot GET -> JSON object. Monkey-patchable seam for tests (mirrors
    synergy_external_source). Raises RankTierSourceError on any failure.

    NO MESSAGE RAISED HERE CARRIES THE RAW URL. `url` is composed by
    `_build_url` from the operator-configured endpoint, which may embed an API
    key in its query string, so every message names the endpoint through
    `_safe_url` and every wrapped third-party message goes through `_redact`.

    The underlying exception is also NOT chained (`raise ... from exc`), and
    each wrapping raise is deliberately issued AFTER its except block so
    __context__ is empty too: traceback prints a cause and a context in full,
    which would put a credential in a log by the back door on any Python
    release where urllib decides to quote the URL back at us. The failure's
    TYPE and its redacted message are carried in our own message instead, so
    nothing diagnosable is lost."""
    req = None
    detail = ""
    try:
        req = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "User-Agent": _USER_AGENT},
            method="GET",
        )
    except ValueError as exc:
        # Request() raises ValueError("unknown url type: %r" % url) for a
        # schemeless or otherwise malformed endpoint - and that message quotes
        # the RAW url, credential included. It fires while BUILDING the
        # request, so the fetch try/except below never saw it.
        detail = _redact(f"{type(exc).__name__}: {exc}", url)
    if req is None:
        raise RankTierSourceError(f"{_safe_url(url)} unusable endpoint: {detail}")

    body = None
    detail = ""
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            if r.status != 200:
                raise RankTierSourceError(f"{_safe_url(url)} -> HTTP {r.status}")
            # Bounded read: this is untrusted third-party input from an
            # operator-configured endpoint, so it never gets to decide how much
            # memory we allocate. Chunked (a single sized read may return short)
            # and deliberately allowed to reach _MAX_BODY_BYTES + 1 so an
            # oversize body is DETECTABLE without being materialised.
            chunks = []
            total = 0
            while total <= _MAX_BODY_BYTES:
                want = min(_READ_CHUNK_BYTES, _MAX_BODY_BYTES + 1 - total)
                chunk = r.read(want)
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
            body = b"".join(chunks)
    except RankTierSourceError:
        raise
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        detail = _redact(f"{type(exc).__name__}: {exc}", url)
    if body is None:                    # not `not body`: b"" is a valid read
        raise RankTierSourceError(f"{_safe_url(url)} fetch failed: {detail}")

    if len(body) > _MAX_BODY_BYTES:
        raise RankTierSourceError(
            f"{_safe_url(url)} response exceeds the {_MAX_BODY_BYTES} byte cap")
    data = _UNSET
    detail = ""
    try:
        data = loads(body, parse_constant=_reject_non_finite)
    except RankTierSourceError:
        raise
    except (JSONDecodeError, ValueError) as exc:
        detail = _redact(f"{type(exc).__name__}: {exc}", url)
    if data is _UNSET:                  # not `data is None`: null is valid JSON
        raise RankTierSourceError(f"{_safe_url(url)} bad JSON: {detail}")
    if not isinstance(data, dict):
        raise RankTierSourceError(
            f"{_safe_url(url)} top-level is {type(data).__name__}, want dict")
    return data


def _validate_rows(raw: dict) -> list:
    """Envelope -> the raw `data` metric-row list, keeping only dict rows.
    Raises RankTierSourceError on a bad/empty envelope so the caller fails
    soft (returns None)."""
    rows = raw.get("data") if isinstance(raw, dict) else None
    if not isinstance(rows, list) or not rows:
        raise RankTierSourceError("payload.data empty or not a list")
    out = [r for r in rows if isinstance(r, dict)]
    if not out:
        raise RankTierSourceError("payload yielded zero usable metric rows")
    return out


def _prune_locked(now: float) -> None:
    """Drop expired positive + negative entries so a long-running process does
    not accumulate dead keys. Behaviour-preserving: an expired entry can never
    be served. Caller holds `_lock`. Mirrors synergy_external_source."""
    for k in [k for k, (ts, _r) in _cache.items() if (now - ts) >= _TTL_S]:
        _cache.pop(k, None)
    for k in [k for k, ts in _neg_cache.items() if (now - ts) >= _NEG_TTL_S]:
        _neg_cache.pop(k, None)


def fetch_rows(
    tier: str, mode: str, *,
    force_refresh: bool = False,
) -> Optional[list]:
    """Live per-tier metric-average rows for a (tier, mode), or None on any
    failure (fail-soft). In-memory TTL cached, positively AND negatively, and
    keyed by the resolved endpoint identity so a config change is not served
    stale. Returns None immediately when unconfigured, so the bench
    transparently falls back to the static seed. Never raises."""
    t = str(tier or "").strip().lower()
    m = str(mode or "").strip().upper()
    if t not in _VALID_TIERS or m not in _VALID_MODES:
        return None
    cfg = _read_config()
    if not _config_enabled(cfg):
        return None
    # The endpoint is config, re-read every call - bind its identity into the
    # key (as a digest, never the raw string) so an endpoint edit invalidates.
    ckey = (t, m, _config_identity(cfg))
    now = _clock()
    if not force_refresh:
        with _lock:
            cached = _cache.get(ckey)
            if cached is not None and (now - cached[0]) < _TTL_S:
                return list(cached[1])
            failed_at = _neg_cache.get(ckey)
            if failed_at is not None and (now - failed_at) < _NEG_TTL_S:
                # Negative cache: the bench sweeps 20 cells per refresh, so a
                # down endpoint would otherwise cost 20 full timeouts each time.
                return None
    try:
        url = _build_url(
            str(cfg.get("endpoint", "")),
            str(cfg.get("tier_param", "")),
            t, m,
        )
        raw = _http_get_json(url)
        rows = _validate_rows(raw)
    except (RankTierSourceError, OSError, ValueError):
        rows = None
    if not rows:
        with _lock:
            now = _clock()
            _prune_locked(now)
            _neg_cache[ckey] = now
        return None
    with _lock:
        now = _clock()
        _prune_locked(now)
        _neg_cache.pop(ckey, None)      # a success clears the failure memory
        _cache[ckey] = (now, list(rows))
    return list(rows)


def _reset_cache_for_tests() -> None:
    with _lock:
        _cache.clear()
        _neg_cache.clear()
