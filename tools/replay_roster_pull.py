"""Pull RANKED replays for every tracked player into a role-partitioned corpus.

    python tools/replay_roster_pull.py --dry-run
    python tools/replay_roster_pull.py --role JUNGLE
    python tools/replay_roster_pull.py --account blaberfish2#NA1

Each account's 5-wide `/replays` window is listed, filtered to ranked queues via
Match-V5 `info.queueId`, then downloaded into
`<root>/players/<ROLE>/<Name-Tag>/` with a Layer-1 stats sidecar per file.

WHY THIS MUST RUN ON A CADENCE: the window holds only the 5 most recent
RETAINED files per account and rotates as that player keeps playing. Measured
2026-07-26 - of three requested `blaberfish2#NA1` matches, two were still in the
window and the third had already rotated out, permanently. There is no
fetch-by-match-id route, so a game not pulled during its residency is lost.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import riot_api                                        # noqa: E402
from core import replay_roster as rr                             # noqa: E402
from core.rofl_archive import (download_replays, extract_archive,  # noqa: E402
                               record_pull_observation)

log = logging.getLogger("replay_roster_pull")


def _now_stamp() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _queue_lookup(match_id):
    """Match-V5 queue id for one match, or None when it cannot be resolved.

    None is a REJECT, not a maybe - plan_pull fails closed rather than spend a
    10 MB download on a guess.
    """
    try:
        blob = riot_api.get_match(match_id)
    except Exception as exc:                       # noqa: BLE001 - report, never abort the roster
        log.warning("queue lookup failed for %s: %s", match_id, exc)
        return None
    if not isinstance(blob, dict):
        return None
    return (blob.get("info") or {}).get("queueId")


def _pull_one(entry, root, queues, dry_run, extract):
    pdir = rr.player_dir(root, entry.role, entry.name, entry.tag)
    acct = riot_api.get_account_by_riot_id(entry.name, entry.tag)
    if not acct or not acct.get("puuid"):
        print(f"{entry.role:7} {entry.riot_id:24} ACCOUNT LOOKUP FAILED")
        return 1

    urls = riot_api.get_replay_urls(acct["puuid"]) or []
    plan = rr.plan_pull(urls, _queue_lookup, queues=queues, archive_dir=pdir)

    head = (f"{entry.role:7} {entry.riot_id:24} listed={len(urls)} "
            f"ranked={len(plan.keep)} already={len(plan.already)} "
            f"rejected={len(plan.rejected)}")
    if plan.unparsed:
        head += f" unparsed={len(plan.unparsed)}"
    print(head)
    for match_id, queue in sorted(plan.rejected.items()):
        why = "queue unresolved" if queue is None else f"queue {queue}"
        print(f"          skip {match_id} ({why})")

    if dry_run:
        for url in plan.keep:
            print(f"          would pull {rr.match_id_of(url)} -> {pdir}")
        return 0

    pdir.mkdir(parents=True, exist_ok=True)
    # Record the whole listed window, not just what was kept: the rotation
    # verdict needs every observation, and a non-ranked game still proves the
    # window moved.
    record_pull_observation(pdir, entry.riot_id,
                           [rr.match_id_of(u) for u in urls if rr.match_id_of(u)])

    res = download_replays(plan.keep, pdir, index_path=pdir / "index.json")
    print(f"          downloaded={len(res.downloaded)} skipped={len(res.skipped)} "
          f"gone={len(res.gone)} expired={len(res.expired)} "
          f"failed={len(res.failed)}")
    for match_id in res.downloaded:
        print(f"          got  {match_id}")
    for match_id in res.gone:
        print(f"          gone {match_id} (listed, no longer retained)")

    if extract:
        ex = extract_archive(pdir, stats_dir=rr.stats_dir(pdir))
        print(f"          extract extracted={len(ex.extracted)} "
              f"skipped={len(ex.skipped)} failed={len(ex.failed)}")
    return 1 if res.failed else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Pull ranked replays for tracked players into the corpus.")
    ap.add_argument("--roster", help="roster json (default data/replay_roster.json)")
    ap.add_argument("--root", help="corpus root (default the RC_ROFL_Archive dir)")
    ap.add_argument("--role", action="append",
                    help="only this role; repeatable")
    ap.add_argument("--account", action="append", metavar="NAME#TAG",
                    help="only this Riot ID; repeatable")
    ap.add_argument("--queues", default=",".join(str(q) for q in rr.RANKED_QUEUES),
                    help="comma-separated queue ids to keep "
                         "(default 420,440 = ranked solo + flex)")
    ap.add_argument("--dry-run", action="store_true",
                    help="list and filter, download nothing")
    ap.add_argument("--no-extract", action="store_true",
                    help="skip the Layer-1 stats sidecar extraction")
    ap.add_argument("--log-file", metavar="PATH",
                    help="append stdout AND logging here. REQUIRED under the "
                         "scheduled task: it runs via pythonw.exe, which "
                         "discards stdout, so without this a failing run is "
                         "silent")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    level = logging.WARNING if args.quiet else logging.INFO
    if args.log_file:
        sink = Path(args.log_file)
        sink.parent.mkdir(parents=True, exist_ok=True)
        stream = sink.open("a", encoding="utf-8", buffering=1)
        sys.stdout = stream
        sys.stderr = stream
        logging.basicConfig(level=level, stream=stream,
                            format="%(asctime)s %(levelname)s %(message)s")
        print(f"--- roster pull {_now_stamp()} ---")
    else:
        logging.basicConfig(level=level, format="%(levelname)s %(message)s")

    entries = rr.load_roster(args.roster)
    if args.role:
        wanted = {r.upper() for r in args.role}
        entries = [e for e in entries if e.role in wanted]
    if args.account:
        wanted_ids = {a.lower() for a in args.account}
        entries = [e for e in entries if e.riot_id.lower() in wanted_ids]
    if not entries:
        print("no roster entries matched the filters")
        return 2

    queues = tuple(int(q) for q in args.queues.split(",") if q.strip())
    root = Path(args.root) if args.root else rr.default_corpus_root()
    print(f"corpus: {rr.players_root(root)}")
    print(f"queues: {queues}")

    rc = 0
    for entry in entries:
        rc |= _pull_one(entry, root, queues, args.dry_run, not args.no_extract)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
