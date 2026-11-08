"""
Thin reader for data/coach_reference/champion_benchmarks.json.

Loaded lazily on first access, cached in-memory, reloaded whenever the
underlying file's mtime or size changes (in either direction). Gives the coach
a simple API for:

  - `get(champion, mode, metric_key)` -> benchmark dict with p25/p50/p75/avg
  - `rank_value(champion, mode, metric_key, value)` -> label for where
    `value` sits in the distribution: "below-p25" / "p25-p50" / "p50-p75"
    / "above-p75" / "no-data"
  - `games_for(champion, mode)` -> how many games back the row (an int >= 0)
  - `rows_for_mode(mode)` -> every champion row for one stored mode suffix
  - `text_freq(champion, mode, metric_key)` -> {text value: count}

Intended use by coach output code:

    from core.benchmarks import rank_value
    tag = rank_value("Tristana", "sr_ranked", "cs_at_10", cs_this_game)
    # e.g. "above-p75" -> coach line: "CS lead at 10 is your top quartile"

Benchmarks are weighted by provenance when built (see
scripts/build_champion_benchmarks.py) - source_truth rows count full,
inferred rows count less. The weighted_n field in each metric shows the
effective sample size.

Fail-soft contract (true-audit s144t225): no accessor raises on a missing,
unreadable, corrupt or wrongly shaped file. A missing file or an unparseable /
non-object document reads as empty; one wrongly shaped champion row, metric or
frequency costs only itself; a transient stat / read error keeps the last good
data and is retried on the next call; a corrupt file is parsed once per
(mtime, size), not on every call. Every returned dict is a copy, so a caller
mutating it can never poison a later read.

Regenerate the JSON by running:
    $env:LOCALAPPDATA/Programs/Python/Python314/python.exe scripts/build_champion_benchmarks.py
"""
from __future__ import annotations

import json
import logging
import math
import numbers
import threading
from pathlib import Path

_log = logging.getLogger("rc.benchmarks")

ROOT = Path(__file__).resolve().parent.parent
BENCHMARKS_PATH = ROOT / "data" / "coach_reference" / "champion_benchmarks.json"

_PERCENTILE_KEYS = ("p25", "p50", "p75")


def _empty() -> dict:
    return {"champions": {}}


class _Cache:
    """(mtime_ns, size)-keyed, lock-guarded cache of the parsed document.

    ``all()`` always answers a dict whose "champions" value is a dict (the
    per-entry shape is validated by the accessors, not here). The cached dict
    is never handed to a caller unwrapped by the public accessors - they copy.
    """

    def __init__(self) -> None:
        self._data: dict | None = None
        # Signature of the file the cached data (or the cached parse failure)
        # came from; None until the first successful stat + read.
        self._sig: tuple | None = None
        self._lock = threading.Lock()

    def _load_if_stale(self) -> dict:
        path = BENCHMARKS_PATH
        with self._lock:
            try:
                st = path.stat()
            except FileNotFoundError:
                # The file is gone: empty, and forget the old signature so a
                # re-created file with the same mtime and size still reloads.
                self._data = None
                self._sig = None
                return _empty()
            except OSError as exc:
                # A transient stat failure (sharing violation, AV scanner)
                # keeps the last good data; retried on the next call.
                _log.debug("benchmarks stat failed: %s", type(exc).__name__)
                return self._data if self._data is not None else _empty()
            sig = (getattr(st, "st_mtime_ns", None), getattr(st, "st_size", None))
            if self._data is not None and sig == self._sig:
                return self._data
            try:
                raw = path.read_bytes()
            except OSError as exc:
                # Not memoised: a read that failed mid-replace is retried, and
                # the last good data is served meanwhile.
                _log.debug("benchmarks read failed: %s", type(exc).__name__)
                return self._data if self._data is not None else _empty()
            self._data = _parse(raw)
            self._sig = sig
            return self._data

    def all(self) -> dict:
        return self._load_if_stale()


def _parse(raw: bytes) -> dict:
    """Parsed document with a dict "champions", or the empty document."""
    try:
        doc = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, RecursionError) as exc:
        # ValueError covers JSONDecodeError and UnicodeDecodeError.
        _log.warning("benchmarks file unreadable (%s); serving no data",
                     type(exc).__name__)
        return _empty()
    if not isinstance(doc, dict) or not isinstance(doc.get("champions"), dict):
        _log.warning("benchmarks file has no champions object; serving no data")
        return _empty()
    return doc


_cache = _Cache()


def _champions() -> dict:
    """The champions mapping from the cache, or {} when it is not a dict."""
    data = _cache.all()
    if not isinstance(data, dict):
        return {}
    champs = data.get("champions")
    return champs if isinstance(champs, dict) else {}


def _key_part_ok(part) -> bool:
    return isinstance(part, str) and part != "" and "|" not in part


def _entry(champion, mode) -> dict:
    """The "<champion>|<mode>" row as a dict, or {} (never the raw junk)."""
    if not (_key_part_ok(champion) and _key_part_ok(mode)):
        return {}
    entry = _champions().get(f"{champion}|{mode}")
    return entry if isinstance(entry, dict) else {}


def _finite_number(val) -> float | int | None:
    """``val`` when it is an int / float (not a bool) and finite, else None."""
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        return None
    if isinstance(val, float) and not math.isfinite(val):
        return None
    return val


def _count(val) -> int | None:
    """A non-negative integral count as an int, else None. 10.0 reads as 10;
    a bool, str, NaN, inf, 3.7 or a negative is not a count."""
    num = _finite_number(val)
    if num is None or num < 0:
        return None
    if isinstance(num, float):
        if not num.is_integer():
            return None
        return int(num)
    return num


def _copy_metrics(metrics) -> dict:
    """Two-level copy of a metrics mapping (metric -> stat dict); a non-dict
    metrics value reads as {}, a non-dict stat entry is passed through only as
    a copy-safe scalar or a shallow copy."""
    if not isinstance(metrics, dict):
        return {}
    out = {}
    for name, stats in metrics.items():
        if isinstance(stats, dict):
            out[name] = dict(stats)
        elif isinstance(stats, list):
            out[name] = list(stats)
        else:
            out[name] = stats
    return out


def get(champion: str, mode: str, metric_key: str) -> dict:
    """Return the benchmark entry for (champion, mode, metric_key), or an
    empty dict if none. The entry has keys p25, p50, p75, avg, n, weighted_n.
    The result is a copy; a non-dict entry reads as {}."""
    metrics = _entry(champion, mode).get("metrics")
    if not isinstance(metrics, dict):
        return {}
    stats = metrics.get(metric_key)
    return dict(stats) if isinstance(stats, dict) else {}


def rank_value(champion: str, mode: str, metric_key: str, value: float) -> str:
    """Bucket `value` into the benchmark distribution.

    Returns one of:
      - "no-data"     : no benchmark for this champion+mode+metric, a value
                        that is not a number (bool, str, None, NaN), or a
                        distribution whose p25 / p50 / p75 are not finite
                        numbers in order (p25 <= p50 <= p75)
      - "below-p25"   : value < p25
      - "p25-p50"     : p25 <= value < p50
      - "p50-p75"     : p50 <= value < p75
      - "above-p75"   : value >= p75
    """
    # numbers.Real, not (int, float): a numpy scalar from a caller is a number.
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        return "no-data"
    if math.isnan(value):
        return "no-data"
    b = get(champion, mode, metric_key)
    if not b:
        return "no-data"
    pcts = [_finite_number(b.get(k)) for k in _PERCENTILE_KEYS]
    if any(p is None for p in pcts):
        return "no-data"
    p25, p50, p75 = pcts
    if not p25 <= p50 <= p75:
        return "no-data"
    if value < p25:
        return "below-p25"
    if value < p50:
        return "p25-p50"
    if value < p75:
        return "p50-p75"
    return "above-p75"


def games_for(champion: str, mode: str) -> int:
    """How many matches back the benchmark for this champion+mode: an int >= 0.
    A missing row or a "games" value that is not a non-negative integral
    number (str, None, bool, NaN, 3.7, -3) reads as 0."""
    games = _count(_entry(champion, mode).get("games"))
    return 0 if games is None else games


def rows_for_mode(mode: str) -> list[dict]:
    """Return every champion's benchmark row for a stored mode suffix.

    Surface read for the dashboard Benchmarks tab (descriptive personal-corpus
    per-champion stat breakdown). Keys are "<Champ>|<mode>"; this filters to the
    given suffix and returns one entry per champion:

        [{"champion": "Vayne", "games": 161, "metrics": {...}}, ...]

    Sorted by games desc (the trust ordering - Aggregator-B-style, the most-played
    champion's distribution is the most reliable); a row whose games value is
    not a count sorts last, its raw value passed through for the route to judge.
    An unknown / empty / non-str / "|"-bearing mode returns []. A non-dict row is
    skipped; a non-dict metrics value reads as {}. Rows are copies.
    """
    if not _key_part_ok(mode):
        return []
    suffix = f"|{mode}"
    rows: list[dict] = []
    for key, entry in _champions().items():
        if not isinstance(key, str) or not key.endswith(suffix):
            continue
        # WHY rsplit on the LAST "|": champ ids are "|"-free DDragon ids and the
        # mode suffix is the only "|" in the key, so the head is the champion.
        champ = key.rsplit("|", 1)[0]
        if not _key_part_ok(champ) or not isinstance(entry, dict):
            continue
        rows.append({
            "champion": champ,
            "games": entry.get("games", 0),
            "metrics": _copy_metrics(entry.get("metrics")),
        })

    def _order(row: dict) -> int:
        games = _count(row["games"])
        return -1 if games is None else games

    rows.sort(key=_order, reverse=True)
    return rows


def text_freq(champion: str, mode: str, metric_key: str) -> dict:
    """Frequency distribution of a text-valued metric (e.g. game_sense_early).
    Returns {value: count} with only non-negative integral counts kept (as
    ints), so a caller can sort and sum it. Used for aggregate statements like
    "your most common Game Sense early rating is Composed (N of M games)"."""
    freqs = _entry(champion, mode).get("text_freq")
    if not isinstance(freqs, dict):
        return {}
    dist = freqs.get(metric_key)
    if not isinstance(dist, dict):
        return {}
    out = {}
    for label, n in dist.items():
        count = _count(n)
        if count is not None:
            out[label] = count
    return out
