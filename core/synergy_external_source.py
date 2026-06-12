"""Live duo-synergy fetch primitive - Tencent 101.qq hero-rank-double (item 277).

The LIVE half of the item-199 pick/ban duo-synergy lane. Item 199 shipped
the consumer (`core/smoothed_rates_101qq` + `/api/duo-synergy` + the
champ-select bot/sup grid) on a STATIC May-25 capture seed. This module is
the on-demand refresh: it fetches Tencent's CN-official duo-synergy table
for a lane pair so `smoothed_rates_101qq` can run on live data, falling
back to the committed static seed when the CN endpoint is unreachable.

Endpoint (verified live from Legion 2026-06-02, see
docs/CAPTURE_101QQ_INSTRUCTIONS.md):

    https://faas-6831.native.qq.com/faas/6831/1371/getRankDouble
      ?championid=&date=<YYYYMMDD>&tier=200&lane1=<lane>&lane2=<lane>
      &pagesize=200&pageindex=0

Returns the raw `data` rows (schema-identical to the static seed:
championid1/2 DDragon numeric keys, doublewinrate, iwinrate1/2, itemp1,
irank, lane1/2). In-memory TTL cache (the data is daily-refreshed); never
written to disk (third-party redistributable - the consumer's static seed
is the only on-disk copy). Fail-soft: any failure returns None.
"""
from __future__ import annotations

import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from json import JSONDecodeError, loads
from typing import Callable, Optional

_ENDPOINT = "https://faas-6831.native.qq.com/faas/6831/1371/getRankDouble"
_REFERER = "https://101.qq.com/"
_USER_AGENT = "Mozilla/5.0 (RC duo-synergy fetch)"
_TIER_DEFAULT = 200
_PAGESIZE = 200
_TTL_S = 6 * 3600.0          # daily-refreshed data; 6h in-memory cache
_TIMEOUT_S = 6.0
_DATE_LOOKBACK_DAYS = 3      # try yesterday, then back a couple days for data

_LANES = frozenset({"top", "jungle", "mid", "bottom", "support"})

# Injectable clock + now so tests are deterministic.
_clock: Callable[[], float] = time.monotonic
_utcnow: Callable[[], datetime] = lambda: datetime.now(timezone.utc)


class SynergyError(RuntimeError):
    """Any fetch/parse failure - caught at the fetch_rows boundary."""


# in-memory cache keyed (lane1, lane2, tier, date0) -> (fetched_monotonic, rows)
_lock = threading.Lock()
_cache: dict[tuple, tuple[float, list]] = {}


def _candidate_dates() -> list[str]:
    """Tencent stats lag ~1 day; try yesterday then a couple days back."""
    base = _utcnow().date()
    return [(base - timedelta(days=d)).strftime("%Y%m%d")
            for d in range(1, 1 + _DATE_LOOKBACK_DAYS)]


def _build_url(lane1: str, lane2: str, tier: int, date: str) -> str:
    return (
        f"{_ENDPOINT}?championid=&date={date}&tier={tier}"
        f"&lane1={lane1}&lane2={lane2}&pagesize={_PAGESIZE}&pageindex=0"
    )


def _http_get_json(url: str, timeout_s: float = _TIMEOUT_S) -> dict:
    """One-shot GET -> JSON object. Monkey-patchable seam for tests
    (augment_external_source pattern). Raises SynergyError on any failure."""
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": _USER_AGENT,
            "Referer": _REFERER,
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            if r.status != 200:
                raise SynergyError(f"{url} -> HTTP {r.status}")
            body = r.read()
    except SynergyError:
        raise
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise SynergyError(f"{url} fetch failed: {exc}") from exc
    try:
        data = loads(body)
    except (JSONDecodeError, ValueError) as exc:
        raise SynergyError(f"{url} bad JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise SynergyError(f"{url} top-level is {type(data).__name__}, want dict")
    return data


def _validate_rows(raw: dict) -> list:
    """Tencent envelope -> the raw `data` row list, validated for the keys
    the consumer's indexer needs. Raises SynergyError on a bad/empty envelope
    so the date-loop tries the next date."""
    if raw.get("code") not in (0, "0"):
        raise SynergyError(f"payload code={raw.get('code')} msg={raw.get('message')!r}")
    rows = raw.get("data")
    if not isinstance(rows, list) or not rows:
        raise SynergyError("payload.data empty or not a list")
    out: list = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        if r.get("championid1") is None or r.get("championid2") is None:
            continue
        if not isinstance(r.get("doublewinrate"), (int, float)):
            continue
        out.append(r)
    if not out:
        raise SynergyError("payload yielded zero usable pair rows")
    return out


def fetch_rows(
    lane1: str, lane2: str, *,
    tier: int = _TIER_DEFAULT,
    force_refresh: bool = False,
) -> Optional[list]:
    """Live raw duo-synergy rows for a lane pair (the `data` list), or None
    on any failure (fail-soft). In-memory TTL cached; tries recent dates
    until one has data."""
    if lane1 not in _LANES or lane2 not in _LANES:
        return None
    dates = _candidate_dates()
    ckey = (lane1, lane2, tier, dates[0])
    now = _clock()
    if not force_refresh:
        with _lock:
            cached = _cache.get(ckey)
            if cached is not None and (now - cached[0]) < _TTL_S:
                return list(cached[1])
    rows: Optional[list] = None
    for date in dates:
        try:
            raw = _http_get_json(_build_url(lane1, lane2, tier, date))
            rows = _validate_rows(raw)
        except SynergyError:
            continue
        if rows:
            break
    if not rows:
        return None
    with _lock:
        now = _clock()
        # Prune expired entries on insert: the cache key embeds the lookup
        # date, so yesterday's keys are never read again and would otherwise
        # accumulate forever (one unreachable entry per day per lane pair) in
        # a long-running process. Expired entries can never be served, so the
        # prune is behavior-preserving.
        stale = [k for k, (ts, _r) in _cache.items() if (now - ts) >= _TTL_S]
        for k in stale:
            _cache.pop(k, None)
        _cache[ckey] = (now, list(rows))
    return list(rows)


def _reset_cache_for_tests() -> None:
    with _lock:
        _cache.clear()
