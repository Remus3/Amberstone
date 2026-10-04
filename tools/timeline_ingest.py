"""Bulk-ingest Match-V5 match + timeline JSON for the analysis corpus.

    python tools/timeline_ingest.py --per-account 40
    python tools/timeline_ingest.py --source ladder --per-account 20

WHY THIS AND NOT MORE .rofl FILES. The 14 headless criteria in
`docs/REPLAY_T2_PARSE_CRITERIA.md` are computed from Match-V5 frames (T1) and
events (T2). A `.rofl` contributes only its end-of-game tail (T0) unless it is
replayed interactively (T3). So for inference data points per unit of cost the
timeline lane wins on every axis, measured 2026-07-26:

    .rofl        ~13 MB   5 per account, ROLLING, hard retention cutoff
    timeline    ~116 KB   paginated arbitrarily deep, NO retention cutoff
                          (a 2026-03-31 patch-16.6 match still returns 22 frames)

The `.rofl` corpus is still worth keeping - it is the permanent record and the
only T3 substrate - but it is not how the corpus grows.

RATE REALITY: Riot's app cap is 100 calls / 120 s (`X-App-Rate-Limit:
100:120,20:1`, read from a live response header). That is RIOT'S, not ours, and
cannot be tuned. Two calls per match means roughly 25 matches per minute at
best. This job is therefore long by construction and is meant to run detached.

DO NOT RUN CONCURRENTLY WITH tools/replay_roster_pull.py. Both pace themselves
independently, so together they would issue ~89 calls/min against a 50/min cap
and start collecting 429s. `--wait-for-idle` blocks until no other RC ingest
process is running.

Output: `<corpus>/timelines/<match_id>.json` = {"match": ..., "timeline": ...}.
Resumable: an existing file is skipped without a call.

EXIT CODES (RM-510; see `exit_code()`):
    0   clean - no row failed hard and nothing stayed rate limited. A
        'partial' (Riot has no timeline for that match) is a fact, not a gap.
    75  EX_TEMPFAIL (sysexits.h) - the run finished, but at least one match,
        account lookup or ids page stayed rate limited after every retry, and
        no row failed hard. Re-running later finishes the work (resumable).
    1   at least one match row ended 'fail', or an account lookup / ids page
        returned None WITHOUT a throttle (a failed call; an empty ids page
        is the end of the history, not a failure). Hard wins. Same contract
        as tools/ladder_role_scout.py.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import replay_roster as rr                            # noqa: E402
from core import riot_api                                       # noqa: E402
from core.riot_retry import fetch_unthrottled                   # noqa: E402

log = logging.getLogger("timeline_ingest")

REGION = "americas"

# Below Riot's 100/120 s app cap. See the module docstring - this is not
# politeness, an unpaced sweep silently degrades to None-returning calls.
_MIN_INTERVAL_S = 1.35
_last_call_at = 0.0

# RM-510: sysexits.h EX_TEMPFAIL - "temporary failure, retry later".
EX_TEMPFAIL = 75
# RM-510: ids pages that stayed rate limited (each truncates one account's
# history for this run). main() resets it; exit_code() reads it.
_ids_rate_limited = {"n": 0}
# RM-510 residual: ids pages that returned None WITHOUT a throttle (a failed
# call, not an end of history). main() resets it; counts as a hard failure.
_ids_failed = {"n": 0}


def exit_code(tally: dict, other_rate_limited: int = 0,
              other_hard: int = 0) -> int:
    """The RM-510 contract: 1 on any hard fail, else 75 on any throttle, else 0."""
    if tally.get("fail") or other_hard:
        return 1
    if tally.get("rate_limited") or other_rate_limited:
        return EX_TEMPFAIL
    return 0


def _pace() -> None:
    global _last_call_at
    gap = time.monotonic() - _last_call_at
    if gap < _MIN_INTERVAL_S:
        time.sleep(_MIN_INTERVAL_S - gap)
    _last_call_at = time.monotonic()


def timelines_dir(corpus_root=None) -> Path:
    root = Path(corpus_root) if corpus_root else rr.default_corpus_root()
    return root / "timelines"


def match_ids_for(puuid: str, want: int, queue: int = 420) -> list:
    """Up to *want* ranked match ids, paginating 100 at a time.

    Returns what it got; a short page means the account's history ended, which
    is a fact about the account and not a failure.
    """
    out = []
    start = 0
    while len(out) < want:
        count = min(100, want - len(out))
        url = (f"https://{REGION}.api.riotgames.com/lol/match/v5/matches/"
               f"by-puuid/{puuid}/ids?queue={queue}&start={start}&count={count}")
        _pace()
        # RM-484: a throttled page is NOT the end of the history - retry it.
        page, throttled = fetch_unthrottled(
            lambda u=url: riot_api._call("match_v5_ids", u,
                                         rate_limit_timeout_s=30.0))
        if throttled:
            _ids_rate_limited["n"] += 1
            log.warning("ids page rate limited for %s at start=%d - "
                        "history truncated for this run", puuid[:12], start)
        elif page is None:
            # RM-510 residual: None WITHOUT a throttle is a failed call, not
            # the end of the history ([] is the end). Hard failure.
            _ids_failed["n"] += 1
            log.warning("ids page FAILED (not a throttle) for %s at start=%d",
                        puuid[:12], start)
        if not page:
            break
        out.extend(page)
        if len(page) < count:
            break
        start += len(page)
    return out[:want]


def _stored_partial_match(dest: Path):
    """The match half of an on-disk file whose timeline is null, else None."""
    try:
        blob = json.loads(dest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(blob, dict) and blob.get("match") and not blob.get("timeline"):
        return blob["match"]
    return None


def ingest_match(match_id: str, dest_dir: Path, retry_partial: bool = False) -> str:
    """Fetch match + timeline into one file. Returns a status string.

    Statuses: 'have' (already on disk, no call), 'ok', 'partial' (match but no
    timeline), 'fail', 'rate_limited'. A partial is written so the match half
    is not lost, and is reported so it can be retried rather than silently
    counted as done.

    RM-484: a THROTTLED call is 'rate_limited' and writes nothing. The old code
    wrote a throttled timeline as a partial, and because an existing file is
    'have', that partial was never fetched again. `retry_partial` re-fetches
    the timeline for such files already on disk (the backfill), reusing their
    stored match half.
    """
    dest = dest_dir / f"{match_id}.json"
    match = None
    if dest.exists():
        if not retry_partial:
            return "have"
        match = _stored_partial_match(dest)
        if match is None:
            return "have"
    if match is None:
        _pace()
        match, throttled = fetch_unthrottled(lambda: riot_api.get_match(match_id))
        if throttled:
            return "rate_limited"
        if not match:
            return "fail"
    _pace()
    timeline, throttled = fetch_unthrottled(
        lambda: riot_api.get_match_timeline(match_id))
    if throttled:
        return "rate_limited"
    payload = {"match": match, "timeline": timeline}
    tmp = dest.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    tmp.replace(dest)
    return "ok" if timeline else "partial"


def _other_ingest_running() -> bool:
    """True when a sibling RC ingest process holds the rate budget."""
    try:
        import subprocess
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
             "Where-Object { $_.CommandLine -like '*replay_roster_pull*' -or "
             "$_.CommandLine -like '*ladder_role_scout*' } | "
             "Measure-Object).Count"],
            capture_output=True, text=True, timeout=30)
        return int((out.stdout or "0").strip() or 0) > 0
    except Exception:  # noqa: BLE001 - never block ingest on a probe failure
        return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Bulk Match-V5 timeline ingest.")
    ap.add_argument("--per-account", type=int, default=40,
                    help="ranked matches to request per account")
    ap.add_argument("--source", default="roster", choices=("roster", "ladder"),
                    help="roster = data/replay_roster.json; "
                         "ladder = data/ladder_role_mains.json")
    ap.add_argument("--queue", type=int, default=420)
    ap.add_argument("--root", help="corpus root")
    ap.add_argument("--limit", type=int, help="stop after N distinct matches")
    ap.add_argument("--wait-for-idle", action="store_true",
                    help="block until no sibling RC ingest is running")
    ap.add_argument("--retry-partial", action="store_true",
                    help="re-fetch the timeline of on-disk files whose "
                         "timeline is null (RM-484 backfill: older runs wrote "
                         "a rate-limited timeline as a permanent partial)")
    ap.add_argument("--log-file")
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
    else:
        logging.basicConfig(level=level, format="%(levelname)s %(message)s")

    while args.wait_for_idle and _other_ingest_running():
        print("waiting: another RC ingest holds the rate budget", flush=True)
        time.sleep(60)

    if args.source == "roster":
        ids = [(e.riot_id, e.name, e.tag) for e in rr.load_roster()]
    else:
        blob = json.loads(Path("data/ladder_role_mains.json").read_text(
            encoding="utf-8"))
        seen, ids = set(), []
        for rows in blob["roles"].values():
            for r in rows:
                rid = r.get("riot_id") or ""
                if "#" in rid and rid.lower() not in seen:
                    seen.add(rid.lower())
                    name, _, tag = rid.partition("#")
                    ids.append((rid, name, tag))

    dest = timelines_dir(args.root)
    dest.mkdir(parents=True, exist_ok=True)
    print(f"accounts={len(ids)} per_account={args.per_account} -> {dest}",
          flush=True)
    t0 = time.time()

    # Collect ids first, dedup globally. High-elo players share games heavily,
    # so the distinct count is far below accounts x per_account and every
    # duplicate saved is two calls not spent.
    wanted, resolved, failed_acct, acct_rate_limited = [], 0, 0, 0
    _ids_rate_limited["n"] = 0
    _ids_failed["n"] = 0
    seen_ids = set()
    for i, (riot_id, name, tag) in enumerate(ids, 1):
        _pace()
        acct, throttled = fetch_unthrottled(
            lambda n=name, t=tag: riot_api.get_account_by_riot_id(n, t))
        if not acct or not acct.get("puuid"):
            failed_acct += 1
            acct_rate_limited += 1 if throttled else 0
            why = " (rate limited)" if throttled else ""
            print(f"  ACCOUNT LOOKUP FAILED {riot_id}{why}", flush=True)
            continue
        resolved += 1
        got = match_ids_for(acct["puuid"], args.per_account, args.queue)
        fresh = [m for m in got if m not in seen_ids]
        seen_ids.update(fresh)
        wanted.extend(fresh)
        if i % 10 == 0:
            print(f"  ids {i}/{len(ids)} distinct={len(seen_ids)} "
                  f"elapsed={time.time() - t0:.0f}s", flush=True)
    print(f"accounts resolved={resolved} failed={failed_acct} "
          f"distinct matches={len(wanted)}", flush=True)

    if args.retry_partial:
        # The backfill covers every file on disk, not only this run's ids;
        # ingest_match leaves a complete file as 'have' without a call.
        on_disk = [p.stem for p in dest.glob("*.json") if p.stem not in seen_ids]
        seen_ids.update(on_disk)
        wanted.extend(on_disk)
        print(f"retry-partial: {len(on_disk)} more on-disk files considered",
              flush=True)

    if args.limit:
        wanted = wanted[:args.limit]
        print(f"limited to {len(wanted)}", flush=True)

    tally = {"ok": 0, "have": 0, "partial": 0, "fail": 0, "rate_limited": 0}
    for i, mid in enumerate(sorted(wanted), 1):
        tally[ingest_match(mid, dest, retry_partial=args.retry_partial)] += 1
        if i % 50 == 0:
            print(f"  matches {i}/{len(wanted)} {tally} "
                  f"elapsed={time.time() - t0:.0f}s", flush=True)
    print(f"DONE {tally} elapsed={time.time() - t0:.0f}s -> {dest}", flush=True)
    other = acct_rate_limited + _ids_rate_limited["n"]
    acct_hard = failed_acct - acct_rate_limited
    rc = exit_code(tally, other, acct_hard + _ids_failed["n"])
    if rc:
        print(f"EXIT {rc}: fail={tally['fail']} rate_limited={tally['rate_limited']} "
              f"account_lookups_failed={acct_hard} "
              f"account_lookups_rate_limited={acct_rate_limited} "
              f"ids_pages_failed={_ids_failed['n']} "
              f"ids_pages_rate_limited={_ids_rate_limited['n']} "
              "(75 = re-run later; resumable)", flush=True)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
