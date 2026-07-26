"""Build per-role cohort baselines from the archived .rofl stats sidecars.

    python tools/build_cohort_baseline.py

Reads `<corpus>/players/<ROLE>/<player>/stats/*.json` plus the cached Match-V5
match blob for each (role and duration are not in the sidecar), applies
`core.corpus_hygiene`, and writes `data/cohort_baselines.json`.

Entirely off disk - no API calls, no client - so it is safe to run alongside an
ingest that owns the rate budget.

JOIN NOTE: sidecar players join to Match-V5 on participant ORDER, index+1 ==
participantId. NOT on puuid: the sidecar PUUID is the raw game uuid while the
Match-V5 one is API-key-encrypted, and joining on it matches zero rows.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import cohort_baseline as cb                        # noqa: E402
from core import corpus_hygiene as ch                         # noqa: E402
from core import event_patterns as ep                         # noqa: E402
from core import replay_roster as rr                          # noqa: E402
from core import riot_api                                     # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build per-role cohort baselines.")
    ap.add_argument("--root", help="corpus root")
    ap.add_argument("--out", default="data/cohort_baselines.json")
    ap.add_argument("--no-hygiene", action="store_true",
                    help="skip the AFK/remake filter (for comparison only)")
    args = ap.parse_args(argv)

    root = Path(args.root) if args.root else None
    sidecars = sorted(rr.players_root(root).rglob("stats/*.json"))
    print(f"sidecars: {len(sidecars)}")

    rows = []
    kept = dropped = no_match = short = 0
    for sc in sidecars:
        match = riot_api.get_cache().get_immutable(f"match:v5:{sc.stem}")
        if not match:
            no_match += 1
            continue
        if not args.no_hygiene and not ch.judge(match, sc).include:
            dropped += 1
            continue
        kept += 1
        try:
            blob = json.loads(sc.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        # Participant ORDER is the join key - index+1 == participantId.
        for idx, player in enumerate(blob.get("players") or [], 1):
            role = ep.role_of(match, idx)
            if not role:
                continue
            metrics = cb.row_metrics(player)
            if not metrics:
                short += 1
                continue
            rows.append((role, metrics))

    print(f"matches kept={kept} dropped={dropped} not_in_cache={no_match}")
    print(f"player-rows usable={len(rows)} skipped_short={short}")

    baselines = cb.build(rows)
    payload = {"source": "rofl_stats_sidecar", "tier": "T0",
               "matches": kept, "player_rows": len(rows),
               "min_time_played_s": cb.MIN_TIME_PLAYED_S,
               "undetectable_afk_rate": ch.UNDETECTABLE_AFK_RATE,
               "roles": baselines}
    dest = Path(args.out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(dest)

    for role in sorted(baselines):
        print(f"\n== {role} ==")
        print(f"  {'metric':28} {'n':>5} {'p10':>9} {'p25':>9} {'p50':>9} "
              f"{'p75':>9} {'p90':>9}")
        for name, t in sorted(baselines[role].items()):
            print(f"  {name:28} {t['n']:>5} {t['p10']:>9.2f} {t['p25']:>9.2f} "
                  f"{t['p50']:>9.2f} {t['p75']:>9.2f} {t['p90']:>9.2f}")
    print(f"\nwrote {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
