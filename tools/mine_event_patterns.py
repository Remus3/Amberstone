"""Mine T2 event criteria across the corpus into win-side vs loss-side rates.

    python tools/mine_event_patterns.py --role JUNGLE
    python tools/mine_event_patterns.py --out data/event_pattern_rates.json

THE POINT IS THE PROMOTION GATE. A criterion is only a coaching rule if
winners and losers do it at MEASURABLY different rates. Winners make mistakes
they get away with, and a corpus mined without this gate will teach them
confidently. See docs/REPLAY_T2_PARSE_CRITERIA.md section 4.

NORMALISATION, decided after reading the first full run (1266 matches,
2026-07-26) and written up in that doc's section 4b. The loudest rows in that
table were artefacts of how the population was counted, so four corrections
are now built in rather than left to the reader:

  TEAM-LEVEL CRITERIA ARE MINED ONCE PER TEAM. `gold_deficit_profile` is
    computed from team gold totals, so all five players on a side carry the
    same number. Mined per player it counted one observation five times and
    read identically (0.240 vs 0.709) across all five roles, which is what
    gave it away. It now buckets under the role `TEAM`.

  COUNTS ARE ACCOMPANIED BY RATES. A raw death count confounds "died more"
    with "played longer", and losing games are not the same length as winning
    ones. Per-minute variants ride alongside the raw counts.

  SHUTDOWNS ARE NORMALISED BY THE DEATHS THAT COULD PAY ONE. Winners gave more
    shutdown gold in every role (1.42 vs 0.52). That is exposure, not
    behaviour: a shutdown is only payable if you were already ahead. Promoted
    unnormalised it would coach "give more shutdowns".

  THE GATE IS SPREAD-AWARE. A relative-difference threshold alone flags a
    0.008 gap on a 0.027 base. Every row now also carries a standardised
    effect size, and SEPARATES needs both.

WHAT NORMALISATION CANNOT FIX, stated because it bounds every row: the ten
rows from one match are NOT independent - they share a game, a duration and an
outcome - so n is an upper bound on information, not a sample size. No p-value
is reported here, deliberately, because computing one under that dependence
would be a fabricated precision.

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
                  "plate_share"}
# Criteria that emit one Finding per occurrence: mine the COUNT per player.
COUNT_CRITERIA = {"death_cost", "shutdowns_given", "early_deaths",
                  "solo_deaths"}
# Counts that also get a per-minute companion. `shutdowns_given` is absent on
# purpose: its confound is exposure, not time, so it gets a rate over deaths.
PER_MINUTE_OF = {"death_cost": "deaths_per_min",
                 "early_deaths": "early_deaths_per_min",
                 "solo_deaths": "solo_deaths_per_min",
                 "death_gold_given": "death_gold_given_per_min"}
# Computed from TEAM totals, so identical for all five players on a side.
TEAM_CRITERIA = {"gold_deficit_profile"}


def corpus_files(root=None):
    d = (Path(root) if root else rr.default_corpus_root()) / "timelines"
    return sorted(d.glob("*.json")) if d.exists() else []


def _minutes(match) -> float:
    """Game length in minutes, or 0.0 when the blob does not carry one.

    Match-V5 has shipped `gameDuration` in both seconds and milliseconds
    depending on era, so a value that would imply a multi-day game is read as
    milliseconds rather than trusted.
    """
    raw = float((match.get("info") or {}).get("gameDuration") or 0)
    if raw <= 0:
        return 0.0
    if raw > 60000:  # implausible as seconds; this blob is in milliseconds
        raw /= 1000.0
    return raw / 60.0


def player_rows(match, timeline):
    """One row per participant: role, win, criterion values, and absences.

    `absent` is load-bearing. A criterion that declines to emit (no elite
    monster taken, no death to divide by) drops that player from its own
    sample, and those players are not randomly distributed - teams that took
    zero objectives are disproportionately the losing ones. Recording the
    absence lets the report show the two sides' samples are different sizes
    instead of quietly averaging over the survivors.
    """
    rows = []
    minutes = _minutes(match)
    for p in (match.get("info") or {}).get("participants") or []:
        pid = p.get("participantId")
        role = ep.POSITION_TO_ROLE.get(p.get("teamPosition") or "", "")
        if not role:
            continue
        findings = ep.analyse(match, timeline, pid)
        by = collections.defaultdict(list)
        for f in findings:
            by[f.criterion].append(f)
        values, absent = {}, []
        for name in COUNT_CRITERIA:
            values[name] = float(len(by.get(name, [])))
        for name in sorted(RATIO_CRITERIA):
            fs = by.get(name) or []
            if fs:
                values[name] = float(fs[0].value)
            else:
                absent.append(name)
        # Gold handed over is the headline magnitude, not a count.
        values["death_gold_given"] = float(
            sum(f.magnitude_gold for f in by.get("death_cost", [])))
        # Exposure correction: of the deaths you had, how many paid a bounty
        # for being ahead. Undefined with no deaths, and 0.0 would be a lie -
        # a player who never died did not "give no shutdowns", they had no
        # opportunity to.
        if values["death_cost"] > 0:
            values["shutdown_rate"] = (values["shutdowns_given"]
                                       / values["death_cost"])
        else:
            absent.append("shutdown_rate")
        if minutes > 0:
            for src, dst in PER_MINUTE_OF.items():
                values[dst] = values[src] / minutes
        else:
            absent.extend(sorted(PER_MINUTE_OF.values()))
        rows.append({"role": role, "win": bool(p.get("win")),
                     "participant_id": pid, "values": values,
                     "absent": absent})
    return rows


def team_rows(match, timeline):
    """One row per TEAM for criteria computed from team totals.

    Read off seat 1 and seat 6 because the criterion is team-identical by
    construction; reading all ten and averaging would produce the same number
    while pretending to five times the evidence.
    """
    rows = []
    for pid in (1, 6):
        values = {}
        for name in sorted(TEAM_CRITERIA):
            fs = ep.CRITERIA[name](match, timeline, pid)
            if fs:
                values[name] = float(fs[0].value)
        if not values:
            continue
        rows.append({"role": "TEAM", "win": ep.won(match, pid),
                     "participant_id": pid, "values": values, "absent": []})
    return rows


def verdict(win_values, loss_values, min_sample, min_sep, min_effect) -> dict:
    """Gate one criterion's two populations.

    SEPARATES requires BOTH a relative gap and a standardised effect size.
    The relative gap alone flags any small-based metric; the effect size alone
    would flag a tiny but very tight difference. Both, or neither.
    """
    n_w, n_l = len(win_values), len(loss_values)
    wm = statistics.mean(win_values) if win_values else 0.0
    lm = statistics.mean(loss_values) if loss_values else 0.0
    sd_w = statistics.pstdev(win_values) if n_w > 1 else 0.0
    sd_l = statistics.pstdev(loss_values) if n_l > 1 else 0.0
    pooled = ((sd_w ** 2 + sd_l ** 2) / 2.0) ** 0.5
    effect = ((wm - lm) / pooled) if pooled > 1e-12 else 0.0
    if n_w < min_sample or n_l < min_sample:
        name = "INSUFFICIENT"
    else:
        denom = abs(lm) if abs(lm) > 1e-9 else 1e-9
        name = ("SEPARATES"
                if abs(wm - lm) / denom >= min_sep and abs(effect) >= min_effect
                else "NO SEPARATION")
    return {"verdict": name, "win_mean": wm, "loss_mean": lm,
            "delta": wm - lm, "effect": effect, "sd_win": sd_w,
            "sd_loss": sd_l, "n_win": n_w, "n_loss": n_l}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Mine event criteria into rates.")
    ap.add_argument("--root", help="corpus root")
    ap.add_argument("--role", action="append", help="restrict to role(s)")
    ap.add_argument("--min-sample", type=int, default=30,
                    help="minimum rows per side before a row is reportable")
    ap.add_argument("--min-sep", type=float, default=0.10,
                    help="relative separation required to flag SEPARATES "
                         "(default 0.10 = 10 pct of the losing-side value)")
    ap.add_argument("--min-effect", type=float, default=0.20,
                    help="standardised effect size also required (default "
                         "0.20, a conventionally SMALL effect)")
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
    absences = collections.defaultdict(lambda: {"win": 0, "loss": 0})
    bad = 0
    wanted = {r.upper() for r in args.role} if args.role else None
    for fp in files:
        try:
            blob = json.loads(fp.read_text(encoding="utf-8"))
            match, timeline = blob.get("match"), blob.get("timeline")
            if not match or not timeline:
                bad += 1
                continue
            rows = player_rows(match, timeline) + team_rows(match, timeline)
            for row in rows:
                if wanted and row["role"] not in wanted | {"TEAM"}:
                    continue
                side = "win" if row["win"] else "loss"
                for crit, val in row["values"].items():
                    buckets[(row["role"], crit)][side].append(val)
                for crit in row["absent"]:
                    absences[(row["role"], crit)][side] += 1
        except (OSError, json.JSONDecodeError):
            bad += 1
    if bad:
        print(f"skipped {bad} unreadable or partial files")

    out = {"matches": len(files), "min_sample": args.min_sample,
           "min_separation": args.min_sep, "min_effect": args.min_effect,
           "rows": []}
    for (role, crit), sides in sorted(buckets.items()):
        stats = verdict(sides["win"], sides["loss"], args.min_sample,
                        args.min_sep, args.min_effect)
        gap = absences.get((role, crit), {"win": 0, "loss": 0})
        out["rows"].append({
            "role": role, "criterion": crit, "verdict": stats["verdict"],
            "win_mean": round(stats["win_mean"], 4),
            "loss_mean": round(stats["loss_mean"], 4),
            "delta": round(stats["delta"], 4),
            "effect": round(stats["effect"], 3),
            "n_win": stats["n_win"], "n_loss": stats["n_loss"],
            "absent_win": gap["win"], "absent_loss": gap["loss"]})

    dest = Path(args.out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, indent=2), encoding="utf-8")
    tmp.replace(dest)

    print(f"{'role':8} {'criterion':26} {'win':>10} {'loss':>10} "
          f"{'delta':>10} {'effect':>7}  n(w/l)  absent(w/l)  verdict")
    for r in sorted(out["rows"], key=lambda x: (x["role"], x["criterion"])):
        print(f"{r['role']:<8} {r['criterion']:<26} {r['win_mean']:>10.3f} "
              f"{r['loss_mean']:>10.3f} {r['delta']:>10.3f} "
              f"{r['effect']:>7.2f}  {r['n_win']}/{r['n_loss']}  "
              f"{r['absent_win']}/{r['absent_loss']}  {r['verdict']}")
    print(f"\nwrote {dest}")
    print("NOTE: SEPARATES means the two sides differ, NOT that the behaviour "
          "is causal. It is a candidate for a rule, never a rule by itself.")
    print("NOTE: the ten rows from one match are not independent, so n is an "
          "upper bound on information, not a sample size.")
    print("NOTE: a non-zero absent count means the two sides were averaged "
          "over DIFFERENT populations - read that row with the bias in mind.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
