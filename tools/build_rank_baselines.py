"""Build per-RANK, per-role cohort baselines across every tier.

    python tools/build_rank_baselines.py --wait-for-idle

The challenger baseline in `data/cohort_baselines.json` answers "vs the best".
It cannot answer "vs my peers", and comparing a Platinum player against
challenger returns p0 on everything - true, and useless as coaching. This
builds a baseline per tier so a finding can be scored against the right cohort.

CHEAPER THAN THE T0 BUILD: every metric exists on the Match-V5 participant, so
this needs ONE call per match - no timeline, no .rofl. That is what makes an
all-tiers sweep affordable at Riot's 100/120 s app cap.

TIER SAMPLING. Non-apex tiers are paged from league-exp-v4 per division;
apex tiers (MASTER / GRANDMASTER / CHALLENGER) have their own league-v4
endpoints and no divisions. Divisions within a tier are MERGED into one
baseline: a per-division sweep costs four times as much for a distinction
finer than a coaching line needs. That merge is a stated tradeoff, not an
oversight - Platinum IV and Platinum I do differ.

DO NOT RUN CONCURRENTLY with another RC ingest; --wait-for-idle blocks until
the others are done.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import cohort_baseline as cb                        # noqa: E402
from core import corpus_hygiene as ch                         # noqa: E402
from core import event_patterns as ep                         # noqa: E402
from core import riot_api                                     # noqa: E402

PLATFORM = "na1"
REGION = "americas"
QUEUE = "RANKED_SOLO_5x5"

TIERS = ["IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM", "EMERALD",
         "DIAMOND", "MASTER", "GRANDMASTER", "CHALLENGER"]
DIVISIONS = ["I", "II", "III", "IV"]
APEX = {"MASTER": "masterleagues", "GRANDMASTER": "grandmasterleagues",
        "CHALLENGER": "challengerleagues"}

_MIN_INTERVAL_S = 1.35
_last = 0.0


def _pace():
    global _last
    gap = time.monotonic() - _last
    if gap < _MIN_INTERVAL_S:
        time.sleep(_MIN_INTERVAL_S - gap)
    _last = time.monotonic()


def _call(label, url, timeout=30.0):
    _pace()
    return riot_api._call(label, url, rate_limit_timeout_s=timeout)


def accounts_for_tier(tier: str, want: int) -> list:
    """PUUIDs sampled from a tier, spread across its divisions."""
    if tier in APEX:
        blob = _call("league_v4", f"https://{PLATFORM}.api.riotgames.com/lol/"
                                  f"league/v4/{APEX[tier]}/by-queue/{QUEUE}")
        entries = (blob or {}).get("entries") or []
        return [e["puuid"] for e in entries[:want] if e.get("puuid")]
    out, per_div = [], max(1, want // len(DIVISIONS))
    for div in DIVISIONS:
        page = _call("league_exp_v4",
                     f"https://{PLATFORM}.api.riotgames.com/lol/league-exp/v4/"
                     f"entries/{QUEUE}/{tier}/{div}?page=1")
        for e in (page or [])[:per_div]:
            if e.get("puuid"):
                out.append(e["puuid"])
    return out[:want]


def match_ids(puuid: str, count: int) -> list:
    return _call("match_v5_ids",
                 f"https://{REGION}.api.riotgames.com/lol/match/v5/matches/"
                 f"by-puuid/{puuid}/ids?queue=420&start=0&count={count}") or []


def _others_running() -> bool:
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
             "Where-Object { $_.CommandLine -like '*timeline_ingest*' -or "
             "$_.CommandLine -like '*replay_roster_pull*' -or "
             "$_.CommandLine -like '*ladder_role_scout*' } | "
             "Measure-Object).Count"],
            capture_output=True, text=True, timeout=30)
        return int((out.stdout or "0").strip() or 0) > 0
    except Exception:  # noqa: BLE001
        return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Per-rank cohort baselines.")
    ap.add_argument("--accounts-per-tier", type=int, default=16)
    ap.add_argument("--matches-per-account", type=int, default=8)
    ap.add_argument("--tiers", default=",".join(TIERS))
    ap.add_argument("--out", default="data/rank_baselines.json")
    ap.add_argument("--wait-for-idle", action="store_true")
    ap.add_argument("--log-file")
    args = ap.parse_args(argv)

    if args.log_file:
        sink = Path(args.log_file)
        sink.parent.mkdir(parents=True, exist_ok=True)
        stream = sink.open("a", encoding="utf-8", buffering=1)
        sys.stdout = stream
        sys.stderr = stream

    while args.wait_for_idle and _others_running():
        print("waiting: another RC ingest holds the rate budget", flush=True)
        time.sleep(60)

    tiers = [t.strip().upper() for t in args.tiers.split(",") if t.strip()]
    t0 = time.time()
    out = {"source": "match_v5", "tier": "T0", "queue": QUEUE,
           "accounts_per_tier": args.accounts_per_tier,
           "matches_per_account": args.matches_per_account,
           "divisions_merged": True,
           "undetectable_afk_rate": ch.UNDETECTABLE_AFK_RATE, "tiers": {}}

    for tier in tiers:
        puuids = accounts_for_tier(tier, args.accounts_per_tier)
        print(f"{tier}: {len(puuids)} accounts", flush=True)
        if not puuids:
            print(f"  {tier}: no accounts resolved - SKIPPED", flush=True)
            continue
        wanted, seen = [], set()
        for pu in puuids:
            for mid in match_ids(pu, args.matches_per_account):
                if mid not in seen:
                    seen.add(mid)
                    wanted.append(mid)
        rows, kept, dropped, failed = [], 0, 0, 0
        for mid in wanted:
            _pace()
            match = riot_api.get_match(mid)
            if not match:
                failed += 1
                continue
            if not ch.judge(match).include:
                dropped += 1
                continue
            kept += 1
            for p in match["info"]["participants"]:
                role = ep.POSITION_TO_ROLE.get(p.get("teamPosition") or "", "")
                metrics = cb.participant_metrics(p)
                if role and metrics:
                    rows.append((role, metrics))
        out["tiers"][tier] = {
            "matches": kept, "dropped": dropped, "failed": failed,
            "player_rows": len(rows), "roles": cb.build(rows)}
        print(f"  {tier}: matches={kept} dropped={dropped} failed={failed} "
              f"rows={len(rows)} elapsed={time.time() - t0:.0f}s", flush=True)

    dest = Path(args.out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, indent=2), encoding="utf-8")
    tmp.replace(dest)
    print(f"\nwrote {dest} elapsed={time.time() - t0:.0f}s", flush=True)

    print(f"\n{'tier':14} {'rows':>6} " + " ".join(
        f"{r:>9}" for r in ("TOP", "JUNGLE", "MID", "BOT", "SUPPORT")))
    for tier in tiers:
        t = out["tiers"].get(tier)
        if not t:
            continue
        med = []
        for role in ("TOP", "JUNGLE", "MID", "BOT", "SUPPORT"):
            tbl = (t["roles"].get(role) or {}).get("cs_per_min")
            med.append(f"{tbl['p50']:>9.2f}" if tbl else f"{'-':>9}")
        print(f"{tier:14} {t['player_rows']:>6} " + " ".join(med), flush=True)
    print("(median cs_per_min by role)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
