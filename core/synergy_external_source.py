"""Live duo-synergy fetch primitive - Tencent 101.qq hero-rank-double (item 277).

The LIVE half of the item-199 pick/ban duo-synergy lane. Item 199 shipped
the consumer (`core/smoothed_rates_101qq` + `/api/duo-synergy` + the
champ-select bot/sup grid) on a STATIC May-25 capture seed. This module is
the on-demand refresh: it fetches Tencent's CN-official duo-synergy table
for a lane pair so `smoothed_rates_101qq` can run on live data, falling
back to the committed static seed when the CN endpoint is unreachable.

Endpoint (verified live from Legion 2026-06-02, see
docs/_archive/CAPTURE_101QQ_INSTRUCTIONS.md):

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

import math
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
_TIMEOUT_S = 6.0             # PER-ATTEMPT socket timeout (not a deadline)
_DATE_LOOKBACK_DAYS = 3      # try yesterday, then back a couple days for data

# TOTAL wall-clock deadline for one fetch_rows call, across the whole date
# loop. _TIMEOUT_S is a per-socket-operation timeout, so without this the
# worst case is at least _DATE_LOOKBACK_DAYS * _TIMEOUT_S = 18s, and a
# slow-drip server (a byte every few seconds) resets the socket timer on
# every read and can stall the caller indefinitely. The deadline both stops
# new date attempts and shrinks the per-attempt timeout to what is left, so
# the LAST attempt cannot overrun the budget either.
_TOTAL_BUDGET_S = 10.0
# Do not start an attempt with less than this left - a sub-half-second
# connect+read has no realistic chance and only burns the tail of the budget.
_MIN_ATTEMPT_S = 0.5

# Negative-cache TTL. Only successes used to be cached, so while the CN
# endpoint was down EVERY call re-paid the whole timeout budget. A failure is
# remembered for 5 minutes - long enough that a down endpoint is cheap to ask
# about, far shorter than the 6h success TTL so a recovered endpoint is picked
# up quickly. force_refresh bypasses it; the entry is never served as data.
_NEG_TTL_S = 300.0

# Hard cap on the response body. This is untrusted third-party input (RC does
# not control the CN endpoint), and an uncapped read lets a hostile or
# malfunctioning server stream unbounded bytes into memory. A full 200-row
# getRankDouble page is well under 100 KB, so 4 MiB is generous.
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024

_LANES = frozenset({"top", "jungle", "mid", "bottom", "support"})

# Injectable clock + now so tests are deterministic.
_clock: Callable[[], float] = time.monotonic
_utcnow: Callable[[], datetime] = lambda: datetime.now(timezone.utc)


class SynergyError(RuntimeError):
    """Any fetch/parse failure - caught at the fetch_rows boundary."""


# in-memory cache keyed (lane1, lane2, tier, date0) -> (fetched_monotonic, rows)
_lock = threading.Lock()
_cache: dict[tuple, tuple[float, list]] = {}
# negative cache: same key shape -> monotonic timestamp of the FAILURE. Held
# separately from _cache so the success path and its len()/prune semantics are
# untouched, and so a negative entry can never be mistaken for row data.
_neg_cache: dict[tuple, float] = {}


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


def _reject_non_finite(token: str):
    """json.loads parse_constant hook - any NaN/Infinity/-Infinity in an
    untrusted CN payload fails the whole fetch (the date loop then tries the
    next date, and fetch_rows stays fail-soft)."""
    raise SynergyError(f"payload carries a non-finite JSON literal: {token}")


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
            # Read at most the cap plus one byte: that one extra byte is what
            # makes an overflow DETECTABLE without ever buffering the whole
            # stream. A Content-Length header is not trusted for this - it is
            # attacker-controlled and may be absent under chunked encoding.
            body = r.read(_MAX_RESPONSE_BYTES + 1)
        if len(body) > _MAX_RESPONSE_BYTES:
            raise SynergyError(
                f"{url} response too large (> {_MAX_RESPONSE_BYTES} bytes)")
    except SynergyError:
        raise
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise SynergyError(f"{url} fetch failed: {exc}") from exc
    try:
        # parse_constant fires on exactly the three NON-STANDARD literals
        # json.loads accepts by default - NaN, Infinity, -Infinity. They must
        # die at the door: isinstance(float("nan"), float) is True so a
        # non-finite survives every downstream type check, gets sorted on by
        # core.smoothed_rates_101qq, and json.dumps re-emits it as a bare NaN
        # token (allow_nan defaults True). That token is not valid JSON, so a
        # browser JSON.parse rejects the WHOLE /api/duo-synergy response over
        # one poisoned row.
        data = loads(body, parse_constant=_reject_non_finite)
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
        rate = r.get("doublewinrate")
        # bool is a subclass of int, so a literal `true` passed the plain
        # isinstance check as a win rate. Non-finite values can also arrive by
        # a route that skipped the parse boundary (a caller-supplied envelope),
        # and one of them poisons the whole serialized response.
        if isinstance(rate, bool) or not isinstance(rate, (int, float)):
            continue
        if not math.isfinite(rate):
            continue
        out.append(r)
    if not out:
        raise SynergyError("payload yielded zero usable pair rows")
    return out


def _prune_locked(now: float) -> None:
    """Drop expired entries from both caches. Caller holds _lock.

    The cache key embeds the lookup date, so yesterday's keys are never read
    again and would otherwise accumulate forever (one unreachable entry per
    day per lane pair) in a long-running process. Expired entries can never be
    served, so the prune is behavior-preserving.
    """
    stale = [k for k, (ts, _r) in _cache.items() if (now - ts) >= _TTL_S]
    for k in stale:
        _cache.pop(k, None)
    stale_neg = [k for k, ts in _neg_cache.items() if (now - ts) >= _NEG_TTL_S]
    for k in stale_neg:
        _neg_cache.pop(k, None)


def fetch_rows(
    lane1: str, lane2: str, *,
    tier: int = _TIER_DEFAULT,
    force_refresh: bool = False,
) -> Optional[list]:
    """Live raw duo-synergy rows for a lane pair (the `data` list), or None
    on any failure (fail-soft). In-memory TTL cached; tries recent dates
    until one has data, under a total wall-clock budget (_TOTAL_BUDGET_S).
    A failure is negative-cached for _NEG_TTL_S so a down endpoint stops
    costing the caller the whole budget on every call."""
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
            failed_at = _neg_cache.get(ckey)
            if failed_at is not None and (now - failed_at) < _NEG_TTL_S:
                # Remembered failure: still None (the negative entry is never
                # served as data), just None FAST.
                return None
    deadline = now + _TOTAL_BUDGET_S
    rows: Optional[list] = None
    for date in dates:
        remaining = deadline - _clock()
        if remaining < _MIN_ATTEMPT_S:
            break
        try:
            raw = _http_get_json(_build_url(lane1, lane2, tier, date),
                                 timeout_s=min(_TIMEOUT_S, remaining))
            rows = _validate_rows(raw)
        except SynergyError:
            continue
        if rows:
            break
    if not rows:
        with _lock:
            now = _clock()
            _prune_locked(now)
            _neg_cache[ckey] = now
        return None
    with _lock:
        now = _clock()
        _prune_locked(now)
        _cache[ckey] = (now, list(rows))
        _neg_cache.pop(ckey, None)
    return list(rows)


def _reset_cache_for_tests() -> None:
    with _lock:
        _cache.clear()
        _neg_cache.clear()
