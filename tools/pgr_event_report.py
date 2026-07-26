"""Render one match's PGR from the local corpus. No API calls, no client.

    python tools/pgr_event_report.py --match NA1_5576603201 --pid 1
    python tools/pgr_event_report.py --latest --all-players
    python tools/pgr_event_report.py --match NA1_5576603201 --pid 1 --json

Reads `<corpus>/timelines/<matchId>.json` written by tools/timeline_ingest.py
and `data/rank_baselines.json` written by tools/build_rank_baselines.py. The
baselines are OPTIONAL: without them every cohort band is reported as
unavailable by name rather than defaulted to average.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import cohort_baseline as cb                          # noqa: E402
from core import pgr_event_report as pgr                        # noqa: E402
from core import replay_roster as rr                            # noqa: E402

DEFAULT_BASELINES = "data/rank_baselines.json"


def _timeline_dir(root=None) -> Path:
    return (Path(root) if root else rr.default_corpus_root()) / "timelines"


def _pick(directory: Path, match_id: str | None, latest: bool):
    if match_id:
        fp = directory / f"{match_id}.json"
        return fp if fp.exists() else None
    files = sorted(directory.glob("*.json"),
                   key=lambda p: p.stat().st_mtime)
    if not files:
        return None
    return files[-1] if latest else files[0]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Render one match's PGR.")
    ap.add_argument("--root", help="corpus root")
    ap.add_argument("--match", help="match id, e.g. NA1_5576603201")
    ap.add_argument("--latest", action="store_true",
                    help="use the most recently ingested match")
    ap.add_argument("--pid", type=int, default=1, help="participant 1-10")
    ap.add_argument("--all-players", action="store_true")
    ap.add_argument("--baselines", default=DEFAULT_BASELINES)
    ap.add_argument("--json", action="store_true", help="emit the raw dict")
    args = ap.parse_args(argv)

    directory = _timeline_dir(args.root)
    fp = _pick(directory, args.match, args.latest)
    if fp is None:
        print(f"no such match under {directory}")
        return 2

    blob = json.loads(fp.read_text(encoding="utf-8"))
    match, timeline = blob.get("match"), blob.get("timeline")
    if not match or not timeline:
        print(f"{fp.name} is partial - no match or no timeline")
        return 2

    baselines = {}
    bp = Path(args.baselines)
    if bp.exists():
        baselines = cb.load(bp)
    else:
        print(f"NOTE: {bp} absent - cohort bands will report as unavailable")

    pids = range(1, 11) if args.all_players else [args.pid]
    reports = [pgr.render(match, timeline, pid, baselines) for pid in pids]
    if args.json:
        print(json.dumps(reports if args.all_players else reports[0],
                         indent=2))
        return 0
    print(f"{fp.stem}\n")
    for report in reports:
        print(pgr.render_text(report))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
