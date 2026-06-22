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
"""
from __future__ import annotations

from typing import Optional, Sequence

# All thresholds live on the same 0-100 scale as the composite OP-Score.
MIN_POINTS = 4        # fewer real (non-None) points than this -> shape unreadable
TREND_FLAT = 6.0      # |end - start| <= this reads as no net trend
VOL_HIGH = 11.0       # mean abs minute-to-minute delta >= this reads as swingy
LEVEL_HIGH = 60.0     # overall mean >= this is a strong level
LEVEL_LOW = 42.0      # overall mean <= this is a weak level

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


def _clean(series: Optional[Sequence]) -> list:
    out = []
    for v in series or []:
        if v is None:
            continue
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            continue
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
    start = _mean(vals[:third])
    end = _mean(vals[-third:])
    level = _mean(vals)
    trend = end - start
    deltas = [abs(vals[i] - vals[i - 1]) for i in range(1, len(vals))]
    volatility = _mean(deltas)

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
        "start": round(start, 1),
        "end": round(end, 1),
        "trend": round(trend, 1),
        "volatility": round(volatility, 1),
    }


def summarize_curve(payload: Optional[dict]) -> dict:
    """Classify the win and loss arcs from a compute_op_score_curve payload.

    Returns {"win": <arc|None>, "loss": <arc|None>}. Safe on an empty or None
    payload (both None). Pure - reads only payload["minutes"][*].win_avg /
    loss_avg, the already-computed per-minute composite series.
    """
    minutes = (payload or {}).get("minutes") or []
    win = [row.get("win_avg") for row in minutes]
    loss = [row.get("loss_avg") for row in minutes]
    return {"win": classify_arc(win), "loss": classify_arc(loss)}
