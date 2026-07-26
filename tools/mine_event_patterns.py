"""Mine T2 event criteria across the corpus into win-side vs loss-side rates.

    python tools/mine_event_patterns.py --role JUNGLE
    python tools/mine_event_patterns.py --out data/event_pattern_rates.json

THE POINT IS THE PROMOTION GATE. A criterion is only a coaching rule if
winners and losers do it at MEASURABLY different rates. Winners make mistakes
they get away with, and a corpus mined without this gate will teach them
confidently. See docs/REPLAY_T2_PARSE_CRITERIA.md section 4.

So every row reports the win-side value, the loss-side value, the difference,
and the sample size behind each - and nothing is labelled a rule here. The
verdict column says whether the separation clears a threshold, and the
threshold is stated rather than hidden.

Reads `<corpus>/timelines/*.json` written by tools/timeline_ingest.py. No API
calls, no client - this runs entirely off disk and can be re-run freely.
"""
from __future__ import annotations

import argparse
import collections
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import event_patterns as ep                          # noqa: E402
from core import replay_roster as rr                           # noqa: E402

# Criteria whose Finding.value is a per-player ratio: mine the MEAN.
RATIO_CRITERIA = {"objective_participation", "kill_participation",
                  "plate_share", "gold_deficit_profile"}
# Criteria that emit one Finding per occurrence: mine the COUNT per player.
COUNT_CRITERIA = {"death_cost", "shutdowns_given", "early_deaths",
                  "solo_deaths"}


def corpus_files(root=None):
    d = (Path(root) if root else rr.default_corpus_root()) / "timelines"
    return sorted(d.glob("*.json")) if d.exists() else []


def player_rows(match, timeline):
    """One row per participant: role, win, and every criterion's value."""
    rows = []
    for p in (match.get("info") or {}).get("participants") or []:
        pid = p.get("participantId")
        role = ep.POSITION_TO_ROLE.get(p.get("teamPosition") or "", "")
        if not role:
            continue
        findings = ep.analyse(match, timeline, pid)
        by = collections.defaultdict(list)
        for f in findings:
            by[f.criterion].append(f)
        row = {"role": role, "win": bool(p.get("win")), "values": {}}
        for name in COUNT_CRITERIA:
            row["values"][name] = float(len(by.get(name, [])))
        for name in RATIO_CRITERIA:
            fs = by.get(name) or []
            if fs:
                row["values"][name] = float(fs[0].value)
        # Gold handed over is the headline magnitude, not a count.
        row["values"]["death_gold_given"] = float(
            sum(f.magnitude_gold for f in by.get("death_cost", [])))
        rows.append(row)
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Mine event criteria into rates.")
    ap.add_argument("--root", help="corpus root")
    ap.add_argument("--role", action="append", help="restrict to role(s)")
    ap.add_argument("--min-sample", type=int, default=30,
                    help="minimum rows per side before a row is reportable")
    ap.add_argument("--min-sep", type=float, default=0.10,
                    help="relative separation required to flag SEPARATES "
                         "(default 0.10 = 10 pct of the losing-side value)")
    ap.add_argument("--out", default="data/event_pattern_rates.json")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args(argv)

    files = corpus_files(args.root)
    if args.limit:
        files = files[:args.limit]
    if not files:
        print("no timelines on disk yet - run tools/timeline_ingest.py first")
        return 2
    print(f"reading {len(files)} matches")

    buckets = collections.defaultdict(lambda: {"win": [], "loss": []})
    bad = 0
    for fp in files:
        try:
            blob = json.loads(fp.read_text(encoding="utf-8"))
            match, timeline = blob.get("match"), blob.get("timeline")
            if not match or not timeline:
                bad += 1
                continue
            for row in player_rows(match, timeline):
                if args.role and row["role"] not in {r.upper() for r in args.role}:
                    continue
                side = "win" if row["win"] else "loss"
                for crit, val in row["values"].items():
                    buckets[(row["role"], crit)][side].append(val)
        except (OSError, json.JSONDecodeError):
            bad += 1
    if bad:
        print(f"skipped {bad} unreadable or partial files")

    out = {"matches": len(files), "min_sample": args.min_sample,
           "min_separation": args.min_sep, "rows": []}
    for (role, crit), sides in sorted(buckets.items()):
        w, l = sides["win"], sides["loss"]
        if len(w) < args.min_sample or len(l) < args.min_sample:
            verdict = "INSUFFICIENT"
            wm = statistics.mean(w) if w else 0.0
            lm = statistics.mean(l) if l else 0.0
        else:
            wm, lm = statistics.mean(w), statistics.mean(l)
            denom = abs(lm) if abs(lm) > 1e-9 else 1e-9
            verdict = ("SEPARATES" if abs(wm - lm) / denom >= args.min_sep
                       else "NO SEPARATION")
        out["rows"].append({
            "role": role, "criterion": crit, "verdict": verdict,
            "win_mean": round(wm, 4), "loss_mean": round(lm, 4),
            "delta": round(wm - lm, 4), "n_win": len(w), "n_loss": len(l)})

    dest = Path(args.out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, indent=2), encoding="utf-8")
    tmp.replace(dest)

    print(f"{'role':8} {'criterion':26} {'win':>10} {'loss':>10} "
          f"{'delta':>10}  n(w/l)   verdict")
    for r in sorted(out["rows"], key=lambda x: (x["role"], x["criterion"])):
        print(f"{r['role']:<8} {r['criterion']:<26} {r['win_mean']:>10.3f} "
              f"{r['loss_mean']:>10.3f} {r['delta']:>10.3f}  "
              f"{r['n_win']}/{r['n_loss']}  {r['verdict']}")
    print(f"\nwrote {dest}")
    print("NOTE: SEPARATES means the two sides differ, NOT that the behaviour "
          "is causal. It is a candidate for a rule, never a rule by itself.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
