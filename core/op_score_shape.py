"""Deterministic arc-shape classifier for the op_score_curve per-minute series.

Pure, read-only, no I/O. Labels the SHAPE of a per-minute composite-score
series (one result bucket - wins or losses - from core.op_score_curve) with an
RC-native vocabulary so the OP-Score panel can caption "what your typical game
arc looks like" instead of leaving the reader to eyeball the polyline.

This is a DESCRIPTIVE re-expression of a curve the dashboard already plots: no
new data source, no Riot / Claude / ML model, no DB read, no schema lift. Given
a list of per-minute 0-100 values (with None gaps for thin minutes) it reports a
single label plus a one-line plain-language read derived purely from the curve's
start level, end level, net trend, and volatility.

Vocabulary (mutually exclusive, RC's OWN naming - not any third-party rating's
keyword set): Snowball, Ramping, Front-loaded, Commanding, Behind, Steady,
Volatile. Decision order (all thresholds on the 0-100 composite scale):
  1. swingy (mean minute-to-minute jump >= VOL_HIGH)            -> Volatile
  2. net rise (end - start >= TREND_FLAT):
       start already strong (>= LEVEL_HIGH)                     -> Snowball
       else                                                     -> Ramping
  3. net fall (end - start <= -TREND_FLAT)                       -> Front-loaded
  4. flat and high overall level (mean >= LEVEL_HIGH)            -> Commanding
  5. flat and low overall level  (mean <= LEVEL_LOW)            -> Behind
  6. flat and middling                                          -> Steady

The label is decided on the SAME 0.1-rounded start / trend / volatility the
result reports, so a reader never sees a reported trend of 6.0 under a
not-rising label (s144 true-audit cycle 131, RM-1622).

INPUT CONTRACT (s144 true-audit cycle 131, RM-1617..RM-1623). A point is
a composite score only if it is a real int or float (bool excluded), finite,
and on the 0-100 scale; anything else (None, NaN, +-inf, bool, text, bytes, an
off-scale number, an int too large for a float) is dropped as a gap, so every
number in the result is finite and the dict serializes as strict JSON. A
series that is not an iterable of points (a str, bytes, a mapping, a bare
number) is unreadable (None) rather than iterated character by character or
raising. summarize_curve reads only a dict payload whose "minutes" is a list
or tuple; a non-dict row is a gap. Nothing here raises on a malformed value
or container shape (an iterator that itself raises mid-iteration still
propagates its own error).
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Optional, Sequence

# All thresholds live on the same 0-100 scale as the composite OP-Score.
MIN_POINTS = 4        # fewer real (non-None) points than this -> shape unreadable
TREND_FLAT = 6.0      # |end - start| <= this reads as no net trend
VOL_HIGH = 11.0       # mean abs minute-to-minute delta >= this reads as swingy
LEVEL_HIGH = 60.0     # overall mean >= this is a strong level
LEVEL_LOW = 42.0      # overall mean <= this is a weak level
SCALE_MIN = 0.0       # a point below this is not a composite score
SCALE_MAX = 100.0     # a point above this is not a composite score

_READS = {
    "Snowball":     "Started ahead and pulled further in front.",
    "Ramping":      "Grew into the game; strongest in the later frames.",
    "Front-loaded": "Peaked early, then gave ground as the game went on.",
    "Commanding":   "Held a steady, strong pace from start to finish.",
    "Behind":       "Stayed on the back foot for most of the game.",
    "Steady":       "Even pace throughout, no big swings.",
    "Volatile":     "Up and down - momentum swung back and forth.",
}

# Exported so callers / tests can assert membership without re-listing the set.
KNOWN_LABELS = frozenset(_READS)


def _point(v) -> Optional[float]:
    """One composite score as a float, or None when ``v`` is not one.

    An int too large for a float is refused (OverflowError) instead of
    raising. The range check runs on the CONVERTED value, so an int / float
    subclass overriding __float__ cannot smuggle NaN or an off-scale number
    in, and the inclusive 0-100 check also refuses NaN (every comparison with
    NaN is False) and +-inf.
    """
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError, OverflowError):
        return None
    if not SCALE_MIN <= f <= SCALE_MAX:
        return None
    return f


def _clean(series) -> list:
    if series is None or isinstance(series, (str, bytes, bytearray, memoryview, Mapping)):
        return []
    try:
        items = iter(series)
    except TypeError:
        return []
    out = []
    for v in items:
        p = _point(v)
        if p is not None:
            out.append(p)
    return out


def _mean(vals: Sequence) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def classify_arc(series: Optional[Sequence]) -> Optional[dict]:
    """Classify ONE per-minute 0-100 series shape.

    ``series`` is a sequence of per-minute composite scores (None gaps allowed).
    Returns a dict {label, read, start, end, trend, volatility} or None when
    there are fewer than MIN_POINTS real (non-None) points to read. Pure - never
    raises, never does I/O. See the module docstring for the decision order.
    """
    vals = _clean(series)
    if len(vals) < MIN_POINTS:
        return None

    third = max(1, len(vals) // 3)
    # Every point is in [0, 100], so each mean, the trend and the volatility
    # are finite. Decide on the rounded numbers the result reports.
    start = round(_mean(vals[:third]), 1)
    end = round(_mean(vals[-third:]), 1)
    level = _mean(vals)
    trend = round(_mean(vals[-third:]) - _mean(vals[:third]), 1)
    deltas = [abs(vals[i] - vals[i - 1]) for i in range(1, len(vals))]
    volatility = round(_mean(deltas), 1)

    if volatility >= VOL_HIGH:
        label = "Volatile"
    elif trend >= TREND_FLAT:
        label = "Snowball" if start >= LEVEL_HIGH else "Ramping"
    elif trend <= -TREND_FLAT:
        label = "Front-loaded"
    elif level >= LEVEL_HIGH:
        label = "Commanding"
    elif level <= LEVEL_LOW:
        label = "Behind"
    else:
        label = "Steady"

    return {
        "label": label,
        "read": _READS[label],
        "start": start,
        "end": end,
        "trend": trend,
        "volatility": volatility,
    }


def summarize_curve(payload: Optional[dict]) -> dict:
    """Classify the win and loss arcs from a compute_op_score_curve payload.

    Returns {"win": <arc|None>, "loss": <arc|None>}. Safe on an empty, None or
    malformed payload (both None): a non-dict payload or a "minutes" that is
    not a list / tuple reads as no minutes, and a non-dict row is a gap. Pure -
    reads only payload["minutes"][*].win_avg / loss_avg, the already-computed
    per-minute composite series.
    """
    minutes = payload.get("minutes") if isinstance(payload, dict) else None
    if not isinstance(minutes, (list, tuple)):
        minutes = ()
    rows = [row for row in minutes if isinstance(row, dict)]
    win = [row.get("win_avg") for row in rows]
    loss = [row.get("loss_avg") for row in rows]
    return {"win": classify_arc(win), "loss": classify_arc(loss)}
