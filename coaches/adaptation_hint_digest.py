"""Cross-dimension coaching-digest aggregator.

Payload-boundary slice of the former monolithic `coaches.adaptation_hint`
(AUTONOMOUS_AUDIT spec 4.C, 2026-05-18). `coaching_digest` composes the
KDA-streak + temporal insight surfaces into one ranked feed.
`coaches.adaptation_hint` re-exports it so existing call sites keep
working unchanged; body is byte-verbatim - behavior pinned by the
test_round* suite.
"""
from __future__ import annotations

from coaches._adaptation_common import SUPPORTED_MODES
from coaches.adaptation_hint_aggregates import kda_trends
from coaches.adaptation_hint_temporal import (
    day_of_week_analysis,
    duration_analysis,
    time_of_day_analysis,
)


def coaching_digest(
    mode: str | None = None,
    since_iso: str | None = None,
    top_n: int = 5,
) -> dict:
    """Assemble a ranked list of actionable insights across all
    analysis dimensions - kda streaks, time-of-day, day-of-week,
    and game duration. Produces one-endpoint "what should I focus
    on?" output for dashboards, Discord pastes, and the CLI.

    Each insight: ``{type, severity (0-1), message, mode, champion?,
    data}``. Insights are sorted by severity desc and clipped to
    ``top_n``.

    ``mode=None`` assembles from every supported mode (per-mode
    insights tagged with the originating mode).
    """
    insights: list[dict] = []
    modes = (mode,) if mode else SUPPORTED_MODES

    # --- KDA streak insights (cold more severe than hot) --------
    for m in modes:
        t = kda_trends(m, n=3, min_sample=5)
        for e in t.get("cold", []):
            severity = min(1.0, abs(e["delta"]) / 2.0)
            insights.append({
                "type": "cold_streak",
                "severity": round(severity, 3),
                "mode": m,
                "champion": e["champion"],
                "message": (
                    f"{e['champion']} ({m}) KDA {e['baseline_ratio']:.2f} "
                    f"→ {e['recent_ratio']:.2f} ({e['delta']:+.2f}) over "
                    f"last {e['sample']} games"
                ),
                "data": e,
            })
        for e in t.get("hot", []):
            severity = min(0.7, e["delta"] / 2.0)
            insights.append({
                "type": "hot_streak",
                "severity": round(severity, 3),
                "mode": m,
                "champion": e["champion"],
                "message": (
                    f"{e['champion']} ({m}) KDA {e['baseline_ratio']:.2f} "
                    f"→ {e['recent_ratio']:.2f} (+{e['delta']:.2f}) over "
                    f"last {e['sample']} games"
                ),
                "data": e,
            })

    # --- Time-of-day outliers -----------------------------------
    tod = time_of_day_analysis(mode=mode, since_iso=since_iso, min_games=5)
    insightful_buckets = [b for b in tod["buckets"]
                          if b["insight"] and b["win_rate"] is not None]
    if insightful_buckets:
        avg_wr = sum(b["win_rate"] for b in insightful_buckets) / len(insightful_buckets)
        worst = tod["worst"]
        best = tod["best"]
        if worst and worst["win_rate"] is not None and (avg_wr - worst["win_rate"]) >= 0.08:
            gap = avg_wr - worst["win_rate"]
            insights.append({
                "type": "worst_hour",
                "severity": round(min(0.8, gap * 4), 3),
                "mode": mode or "all",
                "message": (
                    f"Slump at {worst['hour']:02d}h: "
                    f"{worst['win_rate']*100:.0f}% wr (n={worst['games']}, "
                    f"avg {avg_wr*100:.0f}%)"
                ),
                "data": worst,
            })
        if best and best["win_rate"] is not None and (best["win_rate"] - avg_wr) >= 0.08:
            gap = best["win_rate"] - avg_wr
            insights.append({
                "type": "best_hour",
                "severity": round(min(0.6, gap * 3), 3),
                "mode": mode or "all",
                "message": (
                    f"Peak at {best['hour']:02d}h: "
                    f"{best['win_rate']*100:.0f}% wr (n={best['games']}, "
                    f"avg {avg_wr*100:.0f}%)"
                ),
                "data": best,
            })

    # --- Day-of-week outliers -----------------------------------
    dow = day_of_week_analysis(mode=mode, since_iso=since_iso, min_games=5)
    dow_insightful = [b for b in dow["buckets"]
                      if b["insight"] and b["win_rate"] is not None]
    if dow_insightful:
        avg_wr = sum(b["win_rate"] for b in dow_insightful) / len(dow_insightful)
        worst = dow["worst"]
        best = dow["best"]
        if worst and worst["win_rate"] is not None and (avg_wr - worst["win_rate"]) >= 0.05:
            gap = avg_wr - worst["win_rate"]
            insights.append({
                "type": "worst_day",
                "severity": round(min(0.7, gap * 4), 3),
                "mode": mode or "all",
                "message": (
                    f"Weak {worst['name']}: {worst['win_rate']*100:.0f}% wr "
                    f"(n={worst['games']}, avg {avg_wr*100:.0f}%)"
                ),
                "data": worst,
            })
        if best and best["win_rate"] is not None and (best["win_rate"] - avg_wr) >= 0.05:
            gap = best["win_rate"] - avg_wr
            insights.append({
                "type": "best_day",
                "severity": round(min(0.5, gap * 3), 3),
                "mode": mode or "all",
                "message": (
                    f"Strong {best['name']}: {best['win_rate']*100:.0f}% wr "
                    f"(n={best['games']}, avg {avg_wr*100:.0f}%)"
                ),
                "data": best,
            })

    # --- Duration outliers --------------------------------------
    dur = duration_analysis(mode=mode, since_iso=since_iso, min_games=5)
    dur_insightful = [b for b in dur["buckets"]
                      if b["insight"] and b["win_rate"] is not None]
    if len(dur_insightful) >= 2:
        avg_wr = sum(b["win_rate"] for b in dur_insightful) / len(dur_insightful)
        worst = dur["worst"]
        best = dur["best"]
        if worst and (avg_wr - worst["win_rate"]) >= 0.08:
            gap = avg_wr - worst["win_rate"]
            insights.append({
                "type": "bad_duration",
                "severity": round(min(0.7, gap * 3), 3),
                "mode": mode or "all",
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
                "mode": mode or "all",
                "message": (
                    f"Strong in {best['tier']} games: "
                    f"{best['win_rate']*100:.0f}% wr (n={best['games']})"
                ),
                "data": best,
            })

    insights.sort(key=lambda x: -x["severity"])
    return {
        "mode": mode or "all",
        "since": since_iso,
        "count": len(insights),
        "insights": insights[:top_n],
    }
