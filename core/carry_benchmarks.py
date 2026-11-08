"""
Thin reader for data/coach_reference/carry_benchmarks.json (OQ12 slice A).

Mirrors core/benchmarks.py: lazy first load, in-memory cache, reload when
the file's (mtime_ns, size) changes in either direction. API for the Post
Game Review payload builder (dashboard/builders_last_match._carry_normalized):

  - bucket_for(duration_s)       -> "short" / "mid" / "long", or None when
       the duration is not a finite, non-negative real number (bool, str,
       None, NaN, inf, -1 have no bucket)
  - resolve(role, mode, dur_s)   -> (bench_key | None, metrics dict)
       fallback chain: role|bucket -> role|all -> mode|bucket -> mode|all
       -> (None, {}). The "|<bucket>" keys are skipped when the duration has
       no bucket, and a role / mode that is not a non-empty str free of "|"
       is skipped. A key only qualifies when its kp_pct sample count is a
       whole number >= max(min_n, 1) (thin cells give noisy percentiles);
       min_n comes from the JSON and falls back to DEFAULT_MIN_N when it is
       not a non-negative whole number. The metrics dict is a private copy
       holding only dict-valued metrics, with every non-finite float
       statistic served as None (strict-JSON safe).
  - band(value, bench)           -> "low" / "avg" / "high" / None
       low iff value < p25; high iff value > p75; else avg. None when the
       value is not a finite real number (None, bool, str, NaN, inf), or
       when the bench is not a dict carrying finite p25 <= p75.

Fail-soft contract (true-audit s144t229): no accessor raises on a missing,
unreadable, corrupt or wrongly shaped file, and one wrongly shaped group or
metric costs only itself. A transient stat / read error keeps the last good
document and is retried on the next call; a corrupt file is parsed once per
(mtime_ns, size), not on every call.

Regenerate the JSON by running:
    $env:LOCALAPPDATA/Programs/Python/Python314/python.exe scripts/build_carry_benchmarks.py
"""
from __future__ import annotations

import json
import logging
import math
import numbers
import threading
from pathlib import Path

_log = logging.getLogger("rc.carry_benchmarks")

ROOT = Path(__file__).resolve().parent.parent
CARRY_BENCHMARKS_PATH = ROOT / "data" / "coach_reference" / "carry_benchmarks.json"

DEFAULT_MIN_N = 50

# Duration buckets in seconds: [lo, hi] inclusive; None = unbounded.
# Kept in lockstep with scripts/build_carry_benchmarks.BUCKETS (and pinned
# by the emitted JSON's own "buckets" key).
BUCKETS = {
    "short": [0, 1199],
    "mid":   [1200, 1799],
    "long":  [1800, None],
}


def _empty() -> dict:
    return {"groups": {}}


def _finite_real(val) -> float | int | None:
    """``val`` when it is a real number (not a bool) and finite, else None.
    numbers.Real, not (int, float): a numpy scalar from a caller counts."""
    if isinstance(val, bool) or not isinstance(val, numbers.Real):
        return None
    try:
        if not math.isfinite(val):
            return None
    except (TypeError, ValueError, OverflowError):
        return None
    return val


def _count(val) -> int | None:
    """A non-negative whole number as an int, else None. 300.0 reads as 300;
    a bool, str, None, NaN, inf, 120.5 or a negative is not a count."""
    num = _finite_real(val)
    if num is None or num < 0:
        return None
    if isinstance(num, numbers.Integral):
        return int(num)
    num = float(num)
    if not num.is_integer():
        return None
    return int(num)


def bucket_for(duration_s) -> str | None:
    """Map a game duration in seconds onto its benchmark bucket, or None when
    the duration is not a finite, non-negative real number."""
    d = _finite_real(duration_s)
    if d is None or d < 0:
        return None
    if d >= 1800:
        return "long"
    if d >= 1200:
        return "mid"
    return "short"


class _Cache:
    """(path, mtime_ns, size)-keyed, lock-guarded cache of the parsed
    document. The path is part of the key so tests that repoint
    CARRY_BENCHMARKS_PATH reload. ``all()`` always answers a dict whose
    "groups" value is a dict; resolve() copies before handing anything out."""

    def __init__(self) -> None:
        self._data: dict | None = None
        # Signature of the file the cached data (or the cached parse
        # failure) came from; None until the first successful stat + read.
        self._sig: tuple | None = None
        self._lock = threading.Lock()

    def all(self) -> dict:
        path = Path(CARRY_BENCHMARKS_PATH)
        with self._lock:
            try:
                st = path.stat()
            except FileNotFoundError:
                # Gone: empty, and forget the signature so a re-created file
                # with the same mtime and size still reloads.
                self._data = None
                self._sig = None
                return _empty()
            except (OSError, ValueError) as exc:
                # A transient stat failure (sharing violation, AV scanner)
                # keeps the last good data of THIS path; retried on the next
                # call. ValueError: a path with an embedded NUL.
                _log.debug("carry benchmarks stat failed: %s",
                           type(exc).__name__)
                return self._last_good(path)
            sig = (str(path), getattr(st, "st_mtime_ns", None),
                   getattr(st, "st_size", None))
            if self._data is not None and sig == self._sig:
                return self._data
            try:
                raw = path.read_bytes()
            except OSError as exc:
                # Not memoised: a read that failed mid-replace is retried,
                # and the last good data is served meanwhile.
                _log.debug("carry benchmarks read failed: %s",
                           type(exc).__name__)
                return self._last_good(path)
            self._data = _parse(raw)
            self._sig = sig
            return self._data

    def _last_good(self, path: Path) -> dict:
        """The cached document when it came from ``path``, else empty: a
        repointed path never serves the previous file's data."""
        if self._data is not None and self._sig is not None \
                and self._sig[0] == str(path):
            return self._data
        return _empty()


def _parse(raw: bytes) -> dict:
    """Parsed document with a dict "groups", or the empty document."""
    try:
        doc = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, RecursionError) as exc:
        # ValueError covers JSONDecodeError and UnicodeDecodeError.
        _log.warning("carry benchmarks file unreadable (%s); serving no data",
                     type(exc).__name__)
        return _empty()
    if not isinstance(doc, dict) or not isinstance(doc.get("groups"), dict):
        _log.warning("carry benchmarks file has no groups object; "
                     "serving no data")
        return _empty()
    return doc


_cache = _Cache()


def _key_part_ok(part) -> bool:
    return isinstance(part, str) and part != "" and "|" not in part


def _group_metrics(group) -> dict | None:
    """The group's metrics mapping when it is a dict, else None."""
    if not isinstance(group, dict):
        return None
    metrics = group.get("metrics")
    return metrics if isinstance(metrics, dict) else None


def _kp_count(metrics: dict) -> int | None:
    kp = metrics.get("kp_pct")
    if not isinstance(kp, dict):
        return None
    return _count(kp.get("n"))


def _safe_stat(val):
    """A statistic value for the payload, copied: a non-finite float becomes
    None at any depth (json.dumps would write a bare NaN / Infinity token),
    and every dict / list is a fresh one, so the caller never holds the
    cache's own objects. JSON leaves (str, int, bool, None) are immutable."""
    if isinstance(val, float):
        return val if math.isfinite(val) else None
    if isinstance(val, dict):
        return {k: _safe_stat(v) for k, v in val.items()}
    if isinstance(val, (list, tuple)):
        return [_safe_stat(v) for v in val]
    return val


def _copy_metrics(metrics: dict) -> dict:
    """Private copy of a metrics mapping: dict-valued metrics only, each
    statistic passed through _safe_stat."""
    out: dict = {}
    for name, stats in metrics.items():
        if isinstance(stats, dict):
            try:
                out[name] = {k: _safe_stat(v) for k, v in stats.items()}
            except RecursionError:
                # A pathologically deep stat costs only its own metric.
                continue
    return out


def resolve(role: str | None, mode: str | None, duration_s):
    """Best qualifying benchmark for (role, mode, duration).

    Returns (bench_key, metrics_dict) or (None, {}). role is the SR
    team_position (TOP/JUNGLE/MIDDLE/BOTTOM/UTILITY) or None for
    non-CLASSIC modes; mode is the Match-V5 game_mode string (CLASSIC /
    ARAM / CHERRY / ...). Never raises; see the module docstring."""
    data = _cache.all()
    groups = data["groups"]  # _parse guarantees a dict
    min_n = _count(data.get("min_n"))
    if min_n is None:
        min_n = DEFAULT_MIN_N
    floor = max(min_n, 1)
    bucket = bucket_for(duration_s)

    candidates: list[str] = []
    for part in (role, mode):
        if not _key_part_ok(part):
            continue
        if bucket is not None:
            candidates.append(f"{part}|{bucket}")
        candidates.append(f"{part}|all")
    for key in candidates:
        metrics = _group_metrics(groups.get(key))
        if metrics is None:
            continue
        kp_n = _kp_count(metrics)
        if kp_n is not None and kp_n >= floor:
            return key, _copy_metrics(metrics)
    return None, {}


def band(value, bench: dict | None) -> str | None:
    """Bucket `value` against a single metric's percentile bench.

    "low" iff value < p25, "high" iff value > p75, else "avg". None when the
    value is not a finite real number (None, bool, str, NaN, inf), or when
    the bench is not a dict carrying finite p25 <= p75 (the frontend
    renders the no-band state)."""
    v = _finite_real(value)
    if v is None or not isinstance(bench, dict):
        return None
    p25 = _finite_real(bench.get("p25"))
    p75 = _finite_real(bench.get("p75"))
    if p25 is None or p75 is None or p25 > p75:
        return None
    if v < p25:
        return "low"
    if v > p75:
        return "high"
    return "avg"
