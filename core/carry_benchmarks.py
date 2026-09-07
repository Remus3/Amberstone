"""
Thin reader for data/coach_reference/carry_benchmarks.json (OQ12 slice A).

Mirrors core/benchmarks.py: lazy first load, in-memory cache, reload when
the file mtime changes. API for the Post Game Review payload builder:

  - bucket_for(duration_s)       -> "short" / "mid" / "long"
  - resolve(role, mode, dur_s)   -> (bench_key | None, metrics dict)
       fallback chain: role|bucket -> role|all -> mode|bucket -> mode|all
       -> (None, {}). A key only qualifies when its kp_pct sample count
       meets the JSON's min_n floor (thin cells give noisy percentiles).
  - band(value, bench)           -> "low" / "avg" / "high" / None
       low iff value < p25; high iff value > p75; else avg; None value
       (or an unusable bench) -> None.

Regenerate the JSON by running:
    $env:LOCALAPPDATA/Programs/Python/Python314/python.exe scripts/build_carry_benchmarks.py
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

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

_EMPTY = {"groups": {}}


def bucket_for(duration_s: int) -> str:
    """Map a game duration in seconds onto its benchmark bucket."""
    d = int(duration_s or 0)
    if d >= 1800:
        return "long"
    if d >= 1200:
        return "mid"
    return "short"


class _Cache:
    """mtime-cached JSON load (mirrors core.benchmarks._Cache). Also keyed
    on the path so tests that repoint CARRY_BENCHMARKS_PATH get a reload
    even when the new file's mtime is older than the cached one."""

    def __init__(self) -> None:
        self._data: dict | None = None
        self._mtime: float = 0.0
        self._path: Path | None = None
        self._lock = threading.Lock()

    def all(self) -> dict:
        path = Path(CARRY_BENCHMARKS_PATH)
        try:
            mtime = path.stat().st_mtime
        except (FileNotFoundError, OSError):
            return dict(_EMPTY)
        with self._lock:
            if self._data is None or mtime > self._mtime or self._path != path:
                try:
                    self._data = json.loads(path.read_text(encoding="utf-8"))
                    self._mtime = mtime
                    self._path = path
                except Exception:  # noqa: BLE001 - corrupt file = no data
                    self._data = dict(_EMPTY)
            return self._data or dict(_EMPTY)


_cache = _Cache()


def resolve(role: str | None, mode: str | None, duration_s: int):
    """Best qualifying benchmark for (role, mode, duration).

    Returns (bench_key, metrics_dict) or (None, {}). role is the SR
    team_position (TOP/JUNGLE/MIDDLE/BOTTOM/UTILITY) or None for
    non-CLASSIC modes; mode is the Match-V5 game_mode string (CLASSIC /
    ARAM / CHERRY / ...)."""
    data = _cache.all()
    groups = data.get("groups", {}) or {}
    min_n = data.get("min_n", DEFAULT_MIN_N)
    bucket = bucket_for(duration_s)

    candidates: list = []
    if role:
        candidates += [f"{role}|{bucket}", f"{role}|all"]
    if mode:
        candidates += [f"{mode}|{bucket}", f"{mode}|all"]
    for key in candidates:
        metrics = ((groups.get(key) or {}).get("metrics")) or {}
        kp_n = ((metrics.get("kp_pct") or {}).get("n")) or 0
        if kp_n >= min_n:
            return key, metrics
    return None, {}


def band(value, bench: dict | None) -> str | None:
    """Bucket `value` against a single metric's percentile bench.

    "low" iff value < p25, "high" iff value > p75, else "avg". A None
    value, or a bench missing p25/p75, yields None (the frontend renders
    the no-band state)."""
    if value is None:
        return None
    b = bench or {}
    p25, p75 = b.get("p25"), b.get("p75")
    if p25 is None or p75 is None:
        return None
    if value < p25:
        return "low"
    if value > p75:
        return "high"
    return "avg"
