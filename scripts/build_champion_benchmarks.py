"""
Build champion_benchmarks.json from match_metrics.db.

Aggregates the retro-filled metrics by (champion, mode) and emits per-metric
percentile distributions (p25/p50/p75) so the coach can compare live values
against the user's own historical performance on that champion.

Output: data/coach_reference/champion_benchmarks.json

Format:
{
  "generated_at": "2026-04-24T03:00:00Z",
  "source_rows": 94598,
  "champions": {
    "Tristana|sr_ranked": {
      "games": 47,
      "metrics": {
        "kill_participation_pct": {"p25": 58, "p50": 64, "p75": 71, "avg": 64.3, "n": 47},
        "cs_at_10":               {"p25": 70, "p50": 78, "p75": 85, "avg": 77.8, "n": 45},
        ...
      }
    },
    ...
  }
}

Only numeric-parseable metrics contribute to percentiles. Text metrics
(like "Composed", "L6 hit · L11 pending") are counted for frequency but
not averaged. We keep text-metric frequency maps so the coach can say
"your most common Game Sense early rating is Composed (58% of games)".
"""
from __future__ import annotations
import sqlite3
import json
import re
from pathlib import Path
from datetime import datetime, timezone
from statistics import mean

# Per-row weighting by provenance tier. Coach-confidence scaling — see
# memory feedback_metric_provenance_tagging. source_truth = 1.0 baseline,
# inferred rows contribute less to the aggregate.
PROVENANCE_WEIGHTS = {
    "source_truth":    1.00,
    "inferred_tight":  0.75,
    "inferred_wide":   0.40,
}

ROOT = Path(__file__).resolve().parent.parent
METRICS_DB = ROOT / "data" / "match_metrics.db"
OUT = ROOT / "data" / "coach_reference" / "champion_benchmarks.json"

# Metrics whose first integer token is the numeric signal (e.g.
# "68% · 20/33 team" → 68; "82 CS · +10 vs Ezreal" → 82). For these we
# compute percentile distributions across matches.
NUMERIC_METRICS = {
    "kill_participation_pct",
    "time_alive_pct",
    "damage_share",
    "cs_at_10", "cs_at_15",
    "vision_score",
    "longest_alive_s",
    "cs_at_10_str", "csd_at_15_str",
    "cs_current", "gold_current", "level_current",
    "level_at_10",
    "gold_at_10", "gold_at_15",
    "xp_at_10",
    "first_blood_time_s", "first_tower_time_s",
}

# Text metrics where frequency distribution is more useful than average.
TEXT_FREQ_METRICS = {
    "game_sense_early", "game_sense_mid", "game_sense_late",
    "digest_state", "tilt_meter",
    "build_deviation",
}


def _first_int(s: str) -> int | None:
    m = re.search(r"-?\d+", s or "")
    return int(m.group(0)) if m else None


def _percentiles(values: list[tuple[float, float]]) -> dict:
    """Percentile + weighted mean from (value, weight) tuples. Percentiles
    are computed on raw values (unweighted — so p50 still reflects the
    true sample midpoint); avg is provenance-weighted."""
    if not values:
        return {}
    vs = sorted(v for v, _ in values)
    def _pct(p):
        if not vs: return None
        k = (len(vs) - 1) * p
        lo = int(k)
        hi = min(lo + 1, len(vs) - 1)
        frac = k - lo
        return round(vs[lo] * (1 - frac) + vs[hi] * frac, 2)
    total_w = sum(w for _, w in values)
    weighted_avg = round(
        sum(v * w for v, w in values) / total_w, 2
    ) if total_w > 0 else None
    return {
        "p25": _pct(0.25),
        "p50": _pct(0.50),
        "p75": _pct(0.75),
        "avg": weighted_avg,
        "n":   len(values),
        "weighted_n": round(total_w, 2),
    }


def main() -> int:
    if not METRICS_DB.exists():
        print(f"ERROR: {METRICS_DB} doesn't exist — run retrofill_match_metrics.py first")
        return 2

    conn = sqlite3.connect(f"file:{METRICS_DB}?mode=ro", uri=True)
    cur = conn.cursor()

    # Total rows for sanity
    (total_rows,) = cur.execute("SELECT COUNT(*) FROM match_metrics").fetchone()
    print(f"match_metrics total rows: {total_rows}")

    # Group numeric metrics by (champion, mode, metric_key). Values are
    # stored as (value, weight) tuples where weight comes from provenance.
    champ_buckets: dict[tuple[str, str], dict[str, list[tuple[float, float]]]] = {}
    text_buckets: dict[tuple[str, str], dict[str, dict[str, int]]] = {}
    game_counts: dict[tuple[str, str], set] = {}
    prov_counts: dict[str, int] = {}

    for champ, mode, metric_key, metric_value, match_id, provenance in cur.execute("""
        SELECT champion, mode, metric_key, metric_value, match_id, provenance
        FROM match_metrics
        WHERE champion IS NOT NULL AND mode IS NOT NULL
    """):
        if not champ or not mode:
            continue
        key = (champ, mode)
        game_counts.setdefault(key, set()).add(match_id)
        prov_counts[provenance] = prov_counts.get(provenance, 0) + 1
        weight = PROVENANCE_WEIGHTS.get(provenance, 0.4)

        if metric_key in NUMERIC_METRICS:
            v = _first_int(metric_value)
            if v is not None:
                champ_buckets.setdefault(key, {}).setdefault(metric_key, []).append((float(v), weight))
        elif metric_key in TEXT_FREQ_METRICS:
            tv = (metric_value or "").strip()
            if tv and tv != "—":
                text_buckets.setdefault(key, {}).setdefault(metric_key, {})
                text_buckets[key][metric_key][tv] = text_buckets[key][metric_key].get(tv, 0) + 1

    conn.close()

    # Build output
    out: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_rows": total_rows,
        "provenance_breakdown": prov_counts,
        "provenance_weights": PROVENANCE_WEIGHTS,
        "champions": {},
    }
    for (champ, mode), metrics in sorted(champ_buckets.items()):
        key = f"{champ}|{mode}"
        entry = {
            "games": len(game_counts.get((champ, mode), set())),
            "metrics": {k: _percentiles(v) for k, v in metrics.items()},
        }
        txt = text_buckets.get((champ, mode), {})
        if txt:
            entry["text_freq"] = txt
        out["champions"][key] = entry

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")

    print(f"champions with data: {len(out['champions'])}")
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")

    # Spot-check — print Tristana sr_ranked summary
    t = out["champions"].get("Tristana|sr_ranked")
    if t:
        print()
        print("Tristana sr_ranked sample:")
        print(f"  games: {t['games']}")
        for k in ("cs_at_10", "kill_participation_pct", "damage_share", "longest_alive_s"):
            m = t["metrics"].get(k)
            if m:
                print(f"  {k:28s} p25={m['p25']}  p50={m['p50']}  p75={m['p75']}  avg={m['avg']}  n={m['n']}")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
