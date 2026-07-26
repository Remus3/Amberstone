"""Find the top N players per role on the NA ladder who actually MAIN that role.

    python tools/ladder_role_scout.py --top 20

Ladder endpoints give LP but not role, so role has to be inferred from recent
ranked games. The cheap way is a global match dedup: challenger players share
games constantly, so one match fetch resolves the role of up to 10 tracked
accounts at once. Fetching per account instead would cost several times more
calls for the same answer.

RATE REALITY (measured from Riot's own headers 2026-07-26):
`X-App-Rate-Limit: 100:120,20:1` - the app cap is 100 calls per 120 s and it is
RIOT'S, not ours. `core/riot_api.py` mirrors it exactly. The 2000:10 method
limit never binds. So this job is inherently slow (~50 calls/min) and is meant
to run in the background; it is not tunable by editing our limiter.

Writes `data/ladder_role_mains.json`.
"""
from __future__ import annotations

import argparse
import collections
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import riot_api                                     # noqa: E402
from core.replay_roster import ROLES                           # noqa: E402

log = logging.getLogger("ladder_role_scout")

# Match-V5 teamPosition -> our role enum.
POSITION_TO_ROLE = {
    "TOP": "TOP", "JUNGLE": "JUNGLE", "MIDDLE": "MID",
    "BOTTOM": "BOT", "UTILITY": "SUPPORT",
}

PLATFORM = "na1"
REGION = "americas"


# SELF-PACING, and it is load-bearing rather than politeness.
#
# `riot_api._call` waits only `rate_limit_timeout_s` (default 5 s) for a bucket
# token and then returns None. Riot's app cap is 100 calls / 120 s, so an
# unpaced sweep burns its 100 tokens in ~30 s and EVERY later call returns None
# after a 5 s wait. The scout would then read None as "this account has no
# ranked games" and silently drop roughly two thirds of the ladder while
# exiting 0. Measured on the first run: 100 accounts in 27 s, then an unbroken
# wall of "bucket exhausted".
#
# So pace below the cap (100/120 s = one per 1.2 s) and treat a None as a
# COUNTED FAILURE, never as an empty result.
_MIN_INTERVAL_S = 1.35
_last_call_at = 0.0
_failures = collections.Counter()


def _paced(endpoint: str, url: str):
    global _last_call_at
    gap = time.monotonic() - _last_call_at
    if gap < _MIN_INTERVAL_S:
        time.sleep(_MIN_INTERVAL_S - gap)
    _last_call_at = time.monotonic()
    blob = riot_api._call(endpoint, url, rate_limit_timeout_s=30.0)
    if blob is None:
        _failures[endpoint] += 1
    return blob


def _ladder(tier: str) -> list:
    """Challenger / grandmaster entries, newest snapshot."""
    url = (f"https://{PLATFORM}.api.riotgames.com/lol/league/v4/"
           f"{tier}leagues/by-queue/RANKED_SOLO_5x5")
    blob = _paced("league_v4", url)
    return list((blob or {}).get("entries") or [])


def _recent_ranked_ids(puuid: str, count: int):
    """Match ids, or None on failure - callers MUST distinguish None from []."""
    url = (f"https://{REGION}.api.riotgames.com/lol/match/v5/matches/"
           f"by-puuid/{puuid}/ids?queue=420&start=0&count={count}")
    return _paced("match_v5_ids", url)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Top N per role among NA ladder players who main it.")
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--matches", type=int, default=8,
                    help="recent ranked games sampled per account")
    ap.add_argument("--tiers", default="challenger",
                    help="comma-separated: challenger,grandmaster")
    ap.add_argument("--min-share", type=float, default=0.6,
                    help="fraction of sampled games on a role to count as "
                         "MAINING it (default 0.6)")
    ap.add_argument("--out", default="data/ladder_role_mains.json")
    ap.add_argument("--log-file")
    args = ap.parse_args(argv)

    if args.log_file:
        sink = Path(args.log_file)
        sink.parent.mkdir(parents=True, exist_ok=True)
        stream = sink.open("a", encoding="utf-8", buffering=1)
        sys.stdout = stream
        sys.stderr = stream
        logging.basicConfig(level=logging.INFO, stream=stream,
                            format="%(asctime)s %(levelname)s %(message)s")
    else:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    t0 = time.time()
    entries = []
    for tier in args.tiers.split(","):
        rows = _ladder(tier.strip())
        print(f"{tier.strip()}: {len(rows)} entries", flush=True)
        entries.extend(rows)
    lp = {e["puuid"]: int(e.get("leaguePoints") or 0) for e in entries}
    print(f"accounts: {len(lp)}", flush=True)

    # Phase 1: collect match ids per account (1 call each).
    per_account = {}
    dropped = []
    for i, puuid in enumerate(lp, 1):
        ids = _recent_ranked_ids(puuid, args.matches)
        if ids is None:
            dropped.append(puuid)          # a FAILURE, not an empty history
        else:
            per_account[puuid] = ids
        if i % 25 == 0:
            print(f"  ids {i}/{len(lp)}  ok={len(per_account)} "
                  f"dropped={len(dropped)}  elapsed={time.time() - t0:.0f}s",
                  flush=True)
    if dropped:
        print(f"WARNING {len(dropped)} accounts failed the ids call and are "
              f"EXCLUDED, not counted as roleless", flush=True)

    # Phase 2: fetch each DISTINCT match once. This is the whole efficiency
    # argument - challenger players share games, so one fetch resolves many.
    wanted = {m for ids in per_account.values() for m in ids}
    print(f"distinct matches: {len(wanted)} "
          f"(vs {sum(len(v) for v in per_account.values())} account-slots)",
          flush=True)

    roles = collections.defaultdict(collections.Counter)
    names = {}
    match_failures = 0
    for i, mid in enumerate(sorted(wanted), 1):
        gap = time.monotonic() - _last_call_at
        if gap < _MIN_INTERVAL_S:
            time.sleep(_MIN_INTERVAL_S - gap)
        globals()["_last_call_at"] = time.monotonic()
        blob = riot_api.get_match(mid)
        if not blob:
            match_failures += 1
            continue
        for p in blob["info"]["participants"]:
            pu = p.get("puuid")
            if pu not in lp:
                continue
            role = POSITION_TO_ROLE.get(p.get("teamPosition") or "")
            if role:
                roles[pu][role] += 1
            if p.get("riotIdGameName"):
                names[pu] = f"{p['riotIdGameName']}#{p.get('riotIdTagline', '')}"
        if i % 50 == 0:
            print(f"  matches {i}/{len(wanted)}  elapsed={time.time() - t0:.0f}s",
                  flush=True)

    # Phase 3: main role = modal position at or above --min-share.
    by_role = collections.defaultdict(list)
    unresolved = 0
    for puuid, counter in roles.items():
        total = sum(counter.values())
        if not total:
            continue
        role, n = counter.most_common(1)[0]
        if n / total < args.min_share:
            unresolved += 1
            continue
        by_role[role].append({
            "riot_id": names.get(puuid, ""),
            "lp": lp.get(puuid, 0),
            "role_games": n,
            "sampled_games": total,
            "share": round(n / total, 3),
        })

    out = {"generated_at_unix": int(time.time()), "tiers": args.tiers,
           "min_share": args.min_share, "sampled_per_account": args.matches,
           "roles": {}}
    for role in ROLES:
        rows = sorted(by_role.get(role, []),
                      key=lambda r: (-r["lp"], -r["share"]))
        out["roles"][role] = rows[:args.top]
        print(f"{role:8} resolved={len(by_role.get(role, [])):4d} "
              f"-> top {len(out['roles'][role])}", flush=True)
    print(f"unresolved (no role at or above {args.min_share} share): {unresolved}",
          flush=True)
    print(f"call failures: ids={len(dropped)} matches={match_failures} "
          f"detail={dict(_failures)}", flush=True)
    out["accounts_dropped"] = len(dropped)
    out["match_failures"] = match_failures

    dest = Path(args.out)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_text(json.dumps(out, indent=2), encoding="utf-8")
    tmp.replace(dest)
    print(f"wrote {dest}  elapsed={time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
