"""Cross-dimension coaching-digest aggregator.

Payload-boundary slice of the former monolithic `coaches.adaptation_hint`
(AUTONOMOUS_AUDIT spec 4.C, 2026-05-18). `coaching_digest` composes the
KDA-streak + temporal insight surfaces into one ranked feed.
`coaches.adaptation_hint` re-exports it so existing call sites keep
working unchanged; behavior is pinned by the test_round* suite and
`tests/test_adaptation_hint_digest_true_audit_s144.py`.

Consumers: the supervisor's ``GET /api/digest`` (no try around the call,
body serialized with ``allow_nan=False``), the advisory scan in
``agents/agent4_coach_mentor/insight_detector.py`` and the ``--digest``
CLI. The feed is therefore hardened at this boundary (s144 true-audit
cycle 140, RM-1818..RM-1823):

* each producer call (``kda_trends`` per mode, and each temporal
  analysis) is isolated: a bad mode-DB row that raises one of the
  measured data-error classes skips that producer, logged at WARNING,
  and every other insight still reports. Any other exception class is a
  real bug and still raises;
* a KDA entry with a non-finite or non-numeric ratio / delta, or a
  champion that is not usable text, is dropped, and a champion label is
  one printable line of at most ``_MAX_LABEL_CHARS`` characters;
* a temporal bucket is used only with a finite win rate in [0, 1] and a
  well-formed axis value; a non-finite float in its ``data`` copy (for
  example a ``kda_ratio`` built from a REAL inf kills cell) becomes None;
* messages are 7-bit ASCII ("->", not U+2192);
* ``top_n`` must be an int (bool excluded), otherwise the default 5 is
  used; ``top_n <= 0`` lists no insight. ``count`` stays the total
  before the clip.
"""
from __future__ import annotations

import math
import sqlite3

from coaches._adaptation_common import SUPPORTED_MODES, logger
from coaches.adaptation_hint_aggregates import kda_trends
from coaches.adaptation_hint_temporal import (
    day_of_week_analysis,
    duration_analysis,
    time_of_day_analysis,
)

_DEFAULT_TOP_N = 5
_MAX_LABEL_CHARS = 64
# Exception classes a malformed mode-DB row is MEASURED to raise out of
# the producers (non-dict JSON -> AttributeError, junk numeric text ->
# ValueError, BLOB / TEXT cells -> TypeError, huge ints -> OverflowError).
# Narrow on purpose: anything else is a bug and must surface.
_DATA_ERRORS = (
    TypeError, ValueError, AttributeError, KeyError, OverflowError,
    sqlite3.Error,
)


def _bounded_int(v, default: int) -> int:
    if isinstance(v, bool) or not isinstance(v, int):
        return default
    return v


def _finite(v) -> float | None:
    """A finite float from a real (non-bool) int / float, else None."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    try:
        f = float(v)
    except OverflowError:
        return None
    return f if math.isfinite(f) else None


def _label(v) -> str | None:
    """One printable line of at most ``_MAX_LABEL_CHARS``, or None."""
    if not isinstance(v, str):
        return None
    text = "".join(ch if ch.isprintable() else " " for ch in v[:1024])
    text = " ".join(text.split())[:_MAX_LABEL_CHARS].strip()
    return text or None


def _scrubbed(d: dict) -> dict:
    """Shallow copy with every non-finite float replaced by None."""
    return {
        k: (None if isinstance(v, float) and not math.isfinite(v) else v)
        for k, v in d.items()
    }


def _call(name: str, scope: str, fn, *args, **kwargs):
    """Run one producer; a data error skips it (WARNING) instead of
    taking the whole digest down."""
    try:
        return fn(*args, **kwargs)
    except _DATA_ERRORS as e:
        logger.warning(
            "coaching_digest: %s(%s) skipped: %s: %s",
            name, scope, type(e).__name__, e,
        )
        return None


def _streak_entry(e) -> dict | None:
    """Validated copy of one ``kda_trends`` entry, or None."""
    if not isinstance(e, dict):
        return None
    champion = _label(e.get("champion"))
    baseline = _finite(e.get("baseline_ratio"))
    recent = _finite(e.get("recent_ratio"))
    delta = _finite(e.get("delta"))
    sample = e.get("sample")
    if (champion is None or baseline is None or recent is None
            or delta is None or isinstance(sample, bool)
            or not isinstance(sample, int) or sample < 0):
        return None
    return {
        "champion": champion,
        "baseline_ratio": baseline,
        "recent_ratio": recent,
        "delta": delta,
        "sample": sample,
    }


def _axis_ok(b: dict, axis: str) -> bool:
    v = b.get(axis)
    if axis == "hour":
        return (isinstance(v, int) and not isinstance(v, bool)
                and 0 <= v <= 23)
    return _label(v) == v and v is not None


def _bucket(b, axis: str) -> dict | None:
    """Scrubbed copy of a temporal bucket usable for an outlier, or None."""
    if not isinstance(b, dict):
        return None
    wr = _finite(b.get("win_rate"))
    games = b.get("games")
    if (wr is None or not 0.0 <= wr <= 1.0 or isinstance(games, bool)
            or not isinstance(games, int) or games < 0
            or not _axis_ok(b, axis)):
        return None
    out = _scrubbed(b)
    out["win_rate"] = wr
    return out


def _outlier_inputs(res, axis: str):
    """(insightful buckets, worst, best) from one temporal result."""
    if not isinstance(res, dict) or not isinstance(res.get("buckets"), list):
        return [], None, None
    insightful = []
    for raw in res["buckets"]:
        if isinstance(raw, dict) and raw.get("insight") is True:
            b = _bucket(raw, axis)
            if b is not None:
                insightful.append(b)
    return insightful, _bucket(res.get("worst"), axis), _bucket(
        res.get("best"), axis)


def _mean_rate(buckets: list[dict]) -> float:
    return sum(b["win_rate"] for b in buckets) / len(buckets)


def coaching_digest(
    mode: str | None = None,
    since_iso: str | None = None,
    top_n: int = _DEFAULT_TOP_N,
) -> dict:
    """Assemble a ranked list of actionable insights across all
    analysis dimensions - kda streaks, time-of-day, day-of-week,
    and game duration. Produces one-endpoint "what should I focus
    on?" output for dashboards, Discord pastes, and the CLI.

    Each insight: ``{type, severity (0-1), message, mode, champion?,
    data}``. Insights are sorted by severity desc and clipped to
    ``top_n``; ``count`` is the total before the clip.

    ``mode=None`` assembles from every supported mode (per-mode
    insights tagged with the originating mode).
    """
    insights: list[dict] = []
    modes = (mode,) if mode else SUPPORTED_MODES
    scope = mode or "all"

    # --- KDA streak insights (cold more severe than hot) --------
    for m in modes:
        t = _call("kda_trends", str(m), kda_trends, m, n=3, min_sample=5)
        if not isinstance(t, dict):
            continue
        cold = t.get("cold")
        for e in cold if isinstance(cold, list) else ():
            e = _streak_entry(e)
            if e is None or e["delta"] >= 0:
                continue
            severity = min(1.0, abs(e["delta"]) / 2.0)
            insights.append({
                "type": "cold_streak",
                "severity": round(severity, 3),
                "mode": m,
                "champion": e["champion"],
                "message": (
                    f"{e['champion']} ({m}) KDA {e['baseline_ratio']:.2f} "
                    f"-> {e['recent_ratio']:.2f} ({e['delta']:+.2f}) over "
                    f"last {e['sample']} games"
                ),
                "data": e,
            })
        hot = t.get("hot")
        for e in hot if isinstance(hot, list) else ():
            e = _streak_entry(e)
            if e is None or e["delta"] <= 0:
                continue
            severity = min(0.7, e["delta"] / 2.0)
            insights.append({
                "type": "hot_streak",
                "severity": round(severity, 3),
                "mode": m,
                "champion": e["champion"],
                "message": (
                    f"{e['champion']} ({m}) KDA {e['baseline_ratio']:.2f} "
                    f"-> {e['recent_ratio']:.2f} (+{e['delta']:.2f}) over "
                    f"last {e['sample']} games"
                ),
                "data": e,
            })

    # --- Time-of-day outliers -----------------------------------
    tod = _call("time_of_day_analysis", scope, time_of_day_analysis,
                mode=mode, since_iso=since_iso, min_games=5)
    insightful, worst, best = _outlier_inputs(tod, "hour")
    if insightful:
        avg_wr = _mean_rate(insightful)
        if worst and (avg_wr - worst["win_rate"]) >= 0.08:
            gap = avg_wr - worst["win_rate"]
            insights.append({
                "type": "worst_hour",
                "severity": round(min(0.8, gap * 4), 3),
                "mode": scope,
                "message": (
                    f"Slump at {worst['hour']:02d}h: "
                    f"{worst['win_rate']*100:.0f}% wr (n={worst['games']}, "
                    f"avg {avg_wr*100:.0f}%)"
                ),
                "data": worst,
            })
        if best and (best["win_rate"] - avg_wr) >= 0.08:
            gap = best["win_rate"] - avg_wr
            insights.append({
                "type": "best_hour",
                "severity": round(min(0.6, gap * 3), 3),
                "mode": scope,
                "message": (
                    f"Peak at {best['hour']:02d}h: "
                    f"{best['win_rate']*100:.0f}% wr (n={best['games']}, "
                    f"avg {avg_wr*100:.0f}%)"
                ),
                "data": best,
            })

    # --- Day-of-week outliers -----------------------------------
    dow = _call("day_of_week_analysis", scope, day_of_week_analysis,
                mode=mode, since_iso=since_iso, min_games=5)
    insightful, worst, best = _outlier_inputs(dow, "name")
    if insightful:
        avg_wr = _mean_rate(insightful)
        if worst and (avg_wr - worst["win_rate"]) >= 0.05:
            gap = avg_wr - worst["win_rate"]
            insights.append({
                "type": "worst_day",
                "severity": round(min(0.7, gap * 4), 3),
                "mode": scope,
                "message": (
                    f"Weak {worst['name']}: {worst['win_rate']*100:.0f}% wr "
                    f"(n={worst['games']}, avg {avg_wr*100:.0f}%)"
                ),
                "data": worst,
            })
        if best and (best["win_rate"] - avg_wr) >= 0.05:
            gap = best["win_rate"] - avg_wr
            insights.append({
                "type": "best_day",
                "severity": round(min(0.5, gap * 3), 3),
                "mode": scope,
                "message": (
                    f"Strong {best['name']}: {best['win_rate']*100:.0f}% wr "
                    f"(n={best['games']}, avg {avg_wr*100:.0f}%)"
                ),
                "data": best,
            })

    # --- Duration outliers --------------------------------------
    dur = _call("duration_analysis", scope, duration_analysis,
                mode=mode, since_iso=since_iso, min_games=5)
    insightful, worst, best = _outlier_inputs(dur, "tier")
    if len(insightful) >= 2:
        avg_wr = _mean_rate(insightful)
        if worst and (avg_wr - worst["win_rate"]) >= 0.08:
            gap = avg_wr - worst["win_rate"]
            insights.append({
                "type": "bad_duration",
                "severity": round(min(0.7, gap * 3), 3),
                "mode": scope,
                "message": (
                    f"Struggle in {worst['tier']} games: "
                    f"{worst['win_rate']*100:.0f}% wr (n={worst['games']})"
                ),
                "data": worst,
            })
        if best and (best["win_rate"] - avg_wr) >= 0.08:
            gap = best["win_rate"] - avg_wr
            insights.append({
                "type": "good_duration",
                "severity": round(min(0.5, gap * 2.5), 3),
                "mode": scope,
                "message": (
                    f"Strong in {best['tier']} games: "
                    f"{best['win_rate']*100:.0f}% wr (n={best['games']})"
                ),
                "data": best,
            })

    insights.sort(key=lambda x: -x["severity"])
    limit = _bounded_int(top_n, _DEFAULT_TOP_N)
    return {
        "mode": scope,
        "since": since_iso,
        "count": len(insights),
        "insights": insights[:limit] if limit > 0 else [],
    }
