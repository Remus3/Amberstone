"""
Thin reader for data/coach_reference/champion_benchmarks.json.

Loaded lazily on first access, cached in-memory, reloaded if the underlying
file mtime changes. Gives the coach a simple API for:

  - `get(champion, mode, metric_key)` -> benchmark dict with p25/p50/p75/avg
  - `rank_value(champion, mode, metric_key, value)` -> label for where
    `value` sits in the distribution: "below-p25" / "p25-p50" / "p50-p75"
    / "above-p75" / "no-data"

Intended use by coach output code:

    from core.benchmarks import rank_value
    tag = rank_value("Tristana", "sr_ranked", "cs_at_10", cs_this_game)
    # e.g. "above-p75" -> coach line: "CS lead at 10 is your top quartile"

Benchmarks are weighted by provenance when built (see
scripts/build_champion_benchmarks.py) - source_truth rows count full,
inferred rows count less. The weighted_n field in each metric shows the
effective sample size.

Regenerate the JSON by running:
    $env:LOCALAPPDATA/Programs/Python/Python314/python.exe scripts/build_champion_benchmarks.py
"""
from __future__ import annotations
import json
import threading
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
BENCHMARKS_PATH = ROOT / "data" / "coach_reference" / "champion_benchmarks.json"


class _Cache:
    def __init__(self) -> None:
        self._data: dict | None = None
        self._mtime: float = 0.0
        self._lock = threading.Lock()

    def _load_if_stale(self) -> dict:
        try:
            mtime = BENCHMARKS_PATH.stat().st_mtime
        except FileNotFoundError:
            return {"champions": {}}
        with self._lock:
            if self._data is None or mtime > self._mtime:
                try:
                    self._data = json.loads(BENCHMARKS_PATH.read_text(encoding="utf-8"))
                    self._mtime = mtime
                except Exception:  # noqa: BLE001
                    self._data = {"champions": {}}
            return self._data or {"champions": {}}

    def all(self) -> dict:
        return self._load_if_stale()


_cache = _Cache()


def get(champion: str, mode: str, metric_key: str) -> dict:
    """Return the benchmark entry for (champion, mode, metric_key), or an
    empty dict if none. The entry has keys p25, p50, p75, avg, n, weighted_n."""
    data = _cache.all()
    key = f"{champion}|{mode}"
    champ_entry = (data.get("champions", {}) or {}).get(key, {})
    return champ_entry.get("metrics", {}).get(metric_key, {}) or {}


def rank_value(champion: str, mode: str, metric_key: str, value: float) -> str:
    """Bucket `value` into the benchmark distribution.

    Returns one of:
      - "no-data"     : no benchmark for this champion+mode+metric
      - "below-p25"   : value < p25
      - "p25-p50"     : p25 <= value < p50
      - "p50-p75"     : p50 <= value < p75
      - "above-p75"   : value >= p75
    """
    b = get(champion, mode, metric_key)
    if not b:
        return "no-data"
    p25, p50, p75 = b.get("p25"), b.get("p50"), b.get("p75")
    if p25 is None or p50 is None or p75 is None:
        return "no-data"
    if value < p25:  return "below-p25"
    if value < p50:  return "p25-p50"
    if value < p75:  return "p50-p75"
    return "above-p75"


def games_for(champion: str, mode: str) -> int:
    """How many matches back the benchmark for this champion+mode."""
    data = _cache.all()
    key = f"{champion}|{mode}"
    return ((data.get("champions", {}) or {}).get(key, {}) or {}).get("games", 0)


def rows_for_mode(mode: str) -> list[dict]:
    """Return every champion's benchmark row for a stored mode suffix.

    Surface read for the dashboard Benchmarks tab (descriptive personal-corpus
    per-champion stat breakdown). Keys are "<Champ>|<mode>"; this filters to the
    given suffix and returns one entry per champion:

        [{"champion": "Vayne", "games": 161, "metrics": {...}}, ...]

    Sorted by games desc (the trust ordering - Aggregator-B-style, the most-played
    champion's distribution is the most reliable). An unknown / empty mode
    returns []. Additive over the existing _cache - no schema change.
    """
    data = _cache.all()
    suffix = f"|{mode}"
    rows: list[dict] = []
    for key, entry in (data.get("champions", {}) or {}).items():
        if not key.endswith(suffix):
            continue
        # WHY rsplit on the LAST "|": champ ids are "|"-free DDragon ids and the
        # mode suffix is the only "|" in the key, so the head is the champion.
        champ = key.rsplit("|", 1)[0]
        rows.append({
            "champion": champ,
            "games": (entry or {}).get("games", 0),
            "metrics": (entry or {}).get("metrics", {}) or {},
        })
    rows.sort(key=lambda r: r.get("games", 0), reverse=True)
    return rows


def text_freq(champion: str, mode: str, metric_key: str) -> dict:
    """Frequency distribution of a text-valued metric (e.g. game_sense_early).
    Returns {value: count}. Used for aggregate statements like "your most
    common Game Sense early rating is Composed (N of M games)"."""
    data = _cache.all()
    key = f"{champion}|{mode}"
    champ_entry = (data.get("champions", {}) or {}).get(key, {})
    return (champ_entry.get("text_freq", {}) or {}).get(metric_key, {}) or {}
