"""
Build carry_benchmarks.json from rewind_history.db (OQ12 slice A).

Aggregates per-participant kill participation + gold share + damage share
across the operator's local Match-V5 corpus (~2950 matches, all 10
participants per match) and emits p25/p50/p75 percentile bands so the Post
Game Review can tell the operator where a value sits relative to the
corpus - "your 62% KP is avg for BOTTOM in a mid-length game".

Grouping: each participant row lands under "<group>|<bucket>" keys where
group is BOTH the participant's team_position (when non-empty - SR only;
ARAM/Arena rows have "") AND always the match game_mode, and bucket is a
game-duration band (short/mid/long) PLUS an always-emitted "all". So one
SR bot-laner in a 25-minute game feeds BOTTOM|mid, BOTTOM|all, CLASSIC|mid
and CLASSIC|all.

Per-participant metrics:
  kp_pct         = 100 * (kills + assists) / teams.champion_kills
                   (row skipped for kp ONLY when champion_kills <= 0)
  gold_share_pct = 100 * gold_earned / SUM(team gold_earned)
  dmg_share_pct  = 100 * total_damage_dealt_to_champs / SUM(team same)

Filters: matches shorter than MIN_DURATION_S (remakes) and game_mode in
SKIP_MODES ("" / PRACTICETOOL) are excluded entirely.

Output: data/coach_reference/carry_benchmarks.json (atomic write - the
reader `core.carry_benchmarks` polls it at runtime). The JSON is COMMITTED
(CI has no DB). Percentiles use plain linear interpolation - no provenance
weighting; every row here is Match-V5 source truth.

Regenerate:
    $env:LOCALAPPDATA/Programs/Python/Python314/python.exe scripts/build_carry_benchmarks.py
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "rewind_history.db"
OUT = ROOT / "data" / "coach_reference" / "carry_benchmarks.json"

MIN_DURATION_S = 300           # skip remakes / instant-ff rows
MIN_N = 50                     # reader-side qualification floor (recorded)
SKIP_MODES = ("", "PRACTICETOOL")

# Duration buckets in seconds: [lo, hi] inclusive; None = unbounded.
BUCKETS = {
    "short": [0, 1199],
    "mid":   [1200, 1799],
    "long":  [1800, None],
}


def bucket_for(duration_s: int) -> str:
    if duration_s >= 1800:
        return "long"
    if duration_s >= 1200:
        return "mid"
    return "short"


def _percentiles(values: list[float]) -> dict:
    """p25/p50/p75 with linear interpolation (mirrors
    scripts/build_champion_benchmarks._percentiles, unweighted), rounded
    to 1 decimal, plus the per-metric sample count."""
    if not values:
        return {}
    vs = sorted(values)

    def _pct(p: float) -> float:
        k = (len(vs) - 1) * p
        lo = int(k)
        hi = min(lo + 1, len(vs) - 1)
        frac = k - lo
        return round(vs[lo] * (1 - frac) + vs[hi] * frac, 1)

    return {"p25": _pct(0.25), "p50": _pct(0.50), "p75": _pct(0.75),
            "n": len(vs)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build carry_benchmarks.json from rewind_history.db")
    parser.add_argument("--db", default=None,
                        help="path to rewind_history.db (default: repo data/)")
    parser.add_argument("--out", default=None,
                        help="output JSON path (default: data/coach_reference/)")
    args = parser.parse_args(argv)
    db_path = Path(args.db) if args.db else DB
    out_path = Path(args.out) if args.out else OUT

    if not db_path.exists():
        print(f"ERROR: {db_path} doesn't exist")
        return 2

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    cur = conn.cursor()

    # Match filter map: match_id -> (game_mode, bucket).
    match_info: dict = {}
    for match_id, game_mode, dur in cur.execute(
            "SELECT match_id, game_mode, game_duration_s FROM matches"):
        mode = (game_mode or "").strip()
        dur = int(dur or 0)
        if dur < MIN_DURATION_S or mode in SKIP_MODES:
            continue
        match_info[match_id] = (mode, bucket_for(dur))

    # Team champion_kills for kp; per-team gold/dmg sums for the shares.
    team_kills: dict = {}
    for match_id, team_id, ck in cur.execute(
            "SELECT match_id, team_id, champion_kills FROM teams"):
        team_kills[(match_id, team_id)] = int(ck or 0)

    team_sums: dict = {}
    for match_id, team_id, gold_sum, dmg_sum in cur.execute(
            "SELECT match_id, team_id, SUM(gold_earned),"
            " SUM(total_damage_dealt_to_champs)"
            " FROM participants GROUP BY match_id, team_id"):
        team_sums[(match_id, team_id)] = (int(gold_sum or 0),
                                          int(dmg_sum or 0))

    # Accumulate per-group metric value lists + per-group row counts.
    values: dict = {}     # group_key -> {metric: [floats]}
    counts: dict = {}     # group_key -> participant-row count
    n_participants = 0
    seen_matches: set = set()

    for match_id, team_id, pos, kills, assists, dmg, gold in cur.execute(
            "SELECT match_id, team_id, team_position, kills, assists,"
            " total_damage_dealt_to_champs, gold_earned FROM participants"):
        info = match_info.get(match_id)
        if info is None:
            continue
        mode, bucket = info
        n_participants += 1
        seen_matches.add(match_id)

        row_metrics: dict = {}
        ck = team_kills.get((match_id, team_id), 0)
        if ck > 0:
            row_metrics["kp_pct"] = (
                100.0 * (int(kills or 0) + int(assists or 0)) / ck)
        gold_total, dmg_total = team_sums.get((match_id, team_id), (0, 0))
        if gold_total > 0:
            row_metrics["gold_share_pct"] = 100.0 * int(gold or 0) / gold_total
        if dmg_total > 0:
            row_metrics["dmg_share_pct"] = 100.0 * int(dmg or 0) / dmg_total

        groups = [mode]
        pos = (pos or "").strip()
        if pos:
            groups.append(pos)
        for group in groups:
            for b in (bucket, "all"):
                key = f"{group}|{b}"
                counts[key] = counts.get(key, 0) + 1
                for metric, v in row_metrics.items():
                    values.setdefault(key, {}).setdefault(metric, []).append(v)

    conn.close()

    groups_out: dict = {}
    for key in sorted(counts):
        metrics = {m: _percentiles(vs)
                   for m, vs in sorted(values.get(key, {}).items())}
        groups_out[key] = {"n": counts[key], "metrics": metrics}

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_db": db_path.name,
        "source_matches": len(seen_matches),
        "source_participants": n_participants,
        "min_n": MIN_N,
        "buckets": BUCKETS,
        "groups": groups_out,
    }

    # Atomic write - the reader polls this file at runtime.
    sys.path.insert(0, str(ROOT))
    from core.polled_json import atomic_write_json
    atomic_write_json(out_path, out)

    print(f"matches used: {len(seen_matches)}   participants: {n_participants}")
    print(f"groups: {len(groups_out)}")
    print(f"wrote {out_path} ({out_path.stat().st_size // 1024} KB)")
    for k in ("CLASSIC|all", "ARAM|all", "BOTTOM|all"):
        g = groups_out.get(k)
        if g:
            kp = g["metrics"].get("kp_pct", {})
            print(f"  {k:14s} n={g['n']:6d} kp p50={kp.get('p50')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
