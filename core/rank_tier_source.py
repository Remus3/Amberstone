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

Row contract (the `data` list the endpoint returns / the bench folds):
each row is a metric-average record
    {"role": "all", "bracket": "early"|"mid", "metric": "cs"|"kda"|"kp",
     "avg": <number>}
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
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

_VALID_TIERS = frozenset({
    "iron", "bronze", "silver", "gold", "platinum",
    "emerald", "diamond", "master", "grandmaster", "challenger",
})
_VALID_MODES = frozenset({"SR", "ARAM"})

# Injectable clock so tests are deterministic.
_clock: Callable[[], float] = time.monotonic


class RankTierSourceError(RuntimeError):
    """Any fetch/parse failure - caught at the fetch_rows boundary."""


# in-memory cache keyed (tier, mode) -> (fetched_monotonic, rows)
_lock = threading.Lock()
_cache: dict[tuple, tuple[float, list]] = {}


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


def _build_url(endpoint: str, tier_param: str, tier: str, mode: str) -> str:
    """Compose the aggregate query URL. `tier_param` is the query-string key
    for the tier (defaults to 'tier'); mode rides along as 'mode'."""
    sep = "&" if "?" in endpoint else "?"
    tp = (tier_param or "tier").strip() or "tier"
    return f"{endpoint}{sep}{tp}={tier}&mode={mode}"


def _http_get_json(url: str, timeout_s: float = _TIMEOUT_S) -> dict:
    """One-shot GET -> JSON object. Monkey-patchable seam for tests (mirrors
    synergy_external_source). Raises RankTierSourceError on any failure."""
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": _USER_AGENT},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            if r.status != 200:
                raise RankTierSourceError(f"{url} -> HTTP {r.status}")
            body = r.read()
    except RankTierSourceError:
        raise
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise RankTierSourceError(f"{url} fetch failed: {exc}") from exc
    try:
        data = loads(body)
    except (JSONDecodeError, ValueError) as exc:
        raise RankTierSourceError(f"{url} bad JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise RankTierSourceError(f"{url} top-level is {type(data).__name__}, want dict")
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


def fetch_rows(
    tier: str, mode: str, *,
    force_refresh: bool = False,
) -> Optional[list]:
    """Live per-tier metric-average rows for a (tier, mode), or None on any
    failure (fail-soft). In-memory TTL cached. Returns None immediately when
    unconfigured, so the bench transparently falls back to the static seed."""
    t = str(tier or "").strip().lower()
    m = str(mode or "").strip().upper()
    if t not in _VALID_TIERS or m not in _VALID_MODES:
        return None
    cfg = _read_config()
    if not _config_enabled(cfg):
        return None
    ckey = (t, m)
    now = _clock()
    if not force_refresh:
        with _lock:
            cached = _cache.get(ckey)
            if cached is not None and (now - cached[0]) < _TTL_S:
                return list(cached[1])
    try:
        url = _build_url(
            str(cfg.get("endpoint", "")),
            str(cfg.get("tier_param", "")),
            t, m,
        )
        raw = _http_get_json(url)
        rows = _validate_rows(raw)
    except (RankTierSourceError, OSError, ValueError):
        return None
    if not rows:
        return None
    with _lock:
        now = _clock()
        # Prune expired entries on insert so a long-running process does not
        # accumulate dead keys (behavior-preserving: expired entries can never
        # be served). Mirrors synergy_external_source.
        stale = [k for k, (ts, _r) in _cache.items() if (now - ts) >= _TTL_S]
        for k in stale:
            _cache.pop(k, None)
        _cache[ckey] = (now, list(rows))
    return list(rows)


def _reset_cache_for_tests() -> None:
    with _lock:
        _cache.clear()
