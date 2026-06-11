"""Item 211 recovery: re-attach a missing lcu_match_detail to a specific
match_history.db row by fetching the Match-V5 detail via Riot's web API.

Use when an orphan row exists (row written by performance_tracker; LCU
ingest never landed) AND the operator wants the items + post-game data
visible on Home Recent-5 / Post Game Review.

Per ADR-006 the Riot Web API is permitted for post-game enrichment.
Personal-tier key required at API-Key-Riot.txt.

Flow:
  1. Resolve current puuid via Account-V1 (DB rows may carry stale rotated
     PUUIDs - matches.tracked_puuid is NOT a reliable source).
  2. List matches by puuid within --window-min minutes of the row's
     db.timestamp (default +/- 30 min).
  3. Filter to the target champion (matches db.champion).
  4. Fetch full Match-V5 detail; synthesize an LCU-shaped blob with
     participantIdentities + participants[].stats.itemN.
  5. POST /api/last-match/ingest. The new gameId-keyed ingest logic
     attaches the blob to the right row via timestamp window fallback.

Synth blob is marked _source = "match_v5_recovery_item211" so downstream
consumers can distinguish recovered-from-API rows from LCU-live ingests.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sqlite3
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_DB = _ROOT / "data" / "match_history.db"
_DASH = "https://127.0.0.1:8888"


def _row_info(db: Path, row_id: int) -> tuple[str, str, str]:
    """Returns (timestamp, mode, champion) for row_id."""
    c = sqlite3.connect(str(db))
    try:
        r = c.execute(
            "SELECT timestamp, mode, champion FROM matches WHERE id = ?",
            (row_id,),
        ).fetchone()
    finally:
        c.close()
    if not r:
        sys.exit(f"row id {row_id} not in {db}")
    return r[0], r[1], r[2]


def _normalize_unit(n: int) -> int:
    """Riot's gameDuration is seconds when gameEndTimestamp is present,
    milliseconds in older payloads. > 100_000 implies milliseconds."""
    return n // 1000 if n > 100_000 else n


def _synth_lcu_detail(m5: dict, puuid: str) -> dict:
    info = m5.get("info") or {}
    identities = []
    participants_out = []
    for p in info.get("participants") or []:
        pid = p.get("participantId")
        identities.append(
            {"participantId": pid, "player": {"puuid": p.get("puuid")}}
        )
        stats = {f"item{i}": int(p.get(f"item{i}") or 0) for i in range(7)}
        for fld in (
            "championId", "teamId", "kills", "deaths", "assists",
            "win", "goldEarned", "totalDamageDealtToChampions",
            "totalMinionsKilled", "neutralMinionsKilled",
            "visionScore", "champLevel",
        ):
            stats[fld] = p.get(fld)
        participants_out.append({
            "participantId": pid,
            "championId": p.get("championId"),
            "stats": stats,
        })
    return {
        "gameId": info.get("gameId"),
        "gameCreation": int(info.get("gameCreation") or 0),
        "gameDuration": _normalize_unit(int(info.get("gameDuration") or 0)),
        "gameMode": info.get("gameMode"),
        "queueId": info.get("queueId"),
        "mapId": info.get("mapId"),
        "participantIdentities": identities,
        "participants": participants_out,
        "_source": "match_v5_recovery_item211",
        "_puuid_used": puuid,
    }


def _post_ingest(puuid: str, detail: dict, dashboard: str) -> tuple[int, str]:
    body = json.dumps({"tracked_puuid": puuid, "match_detail": detail}).encode()
    req = urllib.request.Request(
        f"{dashboard}/api/last-match/ingest",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    ctx = ssl._create_unverified_context()
    try:
        r = urllib.request.urlopen(req, context=ctx, timeout=15)
        return (r.status, r.read().decode())
    except urllib.error.HTTPError as exc:
        return (exc.code, exc.read().decode())


def find_by_champion(match_ids, puuid, champion, fetch):
    """First (match_id, detail) whose puuid-participant played `champion`
    (case-insensitive). `fetch` maps match_id -> detail dict or None."""
    want = (champion or "").strip().lower()
    for mid in match_ids:
        d = fetch(mid)
        if not d:
            continue
        info = d.get("info") or {}
        for p in info.get("participants") or []:
            if p.get("puuid") != puuid:
                continue
            cname = (p.get("championName") or "").strip()
            if cname.lower() == want:
                return (mid, d)
    return None


def verify_participant(detail, puuid):
    """championName the puuid played in `detail`, or None if absent."""
    info = (detail or {}).get("info") or {}
    for p in info.get("participants") or []:
        if p.get("puuid") == puuid:
            return (p.get("championName") or "").strip() or None
    return None


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    ap.add_argument("--row-id", type=int, required=True,
                    help="match_history.db row id whose ingest is missing")
    ap.add_argument("--riot-name", required=True,
                    help="operator's Riot ID game name (e.g. SamplePlayer)")
    ap.add_argument("--riot-tag", required=True,
                    help="operator's Riot ID tag (e.g. Trist)")
    ap.add_argument("--window-min", type=int, default=30,
                    help="search +/- N minutes of row's db.timestamp "
                         "(default 30)")
    ap.add_argument("--trust-lcu", default=None, metavar="CHAMP",
                    help="item-211 chain rows: db.champion is the WRONG "
                         "(previous game's) champ; match candidates against "
                         "this LCU-truth champion instead")
    ap.add_argument("--match-id", default=None, metavar="NA1_...",
                    help="skip the window search; fetch this Match-V5 id "
                         "directly (puuid participation still verified)")
    ap.add_argument("--db", type=Path, default=_DB)
    ap.add_argument("--dashboard", default=_DASH,
                    help=f"RC dashboard root (default {_DASH})")
    return ap


def main() -> int:
    args = build_parser().parse_args()

    ts_str, mode, champion = _row_info(args.db, args.row_id)
    print(f"[row {args.row_id}] ts={ts_str} mode={mode} champion={champion}")

    # Lazy import: Riot client lives in core/, requires API-Key-Riot.txt.
    from core.riot_api import (
        get_account_by_riot_id, get_recent_matches, get_match,
    )

    acct = get_account_by_riot_id(args.riot_name, args.riot_tag)
    if not acct or not acct.get("puuid"):
        sys.exit("account lookup failed - check Riot ID + API key")
    puuid = acct["puuid"]
    print(f"[account] puuid={puuid[:30]}...")

    if args.match_id:
        m5 = get_match(args.match_id)
        if not m5:
            sys.exit(f"Match-V5 fetch failed for {args.match_id}")
        played = verify_participant(m5, puuid)
        if not played:
            sys.exit(f"puuid not a participant in {args.match_id} - refusing")
        print(f"[match] explicit {args.match_id}: puuid played {played} "
              f"(row db.champion={champion}); posting ingest...")
        mid = args.match_id
    else:
        # Chain rows (item 211): the row's db.champion is the PREVIOUS
        # game's champ, so the strict filter refuses; --trust-lcu supplies
        # the LCU-truth champion to match instead.
        want = args.trust_lcu or champion
        row_unix = int(_dt.datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").timestamp())
        start = row_unix - args.window_min * 60
        end = row_unix + args.window_min * 60
        ids = get_recent_matches(puuid, count=20,
                                 start_time_unix_s=start, end_time_unix_s=end)
        if not ids:
            sys.exit(f"no Match-V5 ids in +/- {args.window_min}min of {ts_str}")
        print(f"[match-v5] {len(ids)} candidate(s): {ids}")

        chosen = find_by_champion(ids, puuid, want, get_match)
        if not chosen:
            sys.exit(f"no Match-V5 detail matched champion={want}"
                     + (" (--trust-lcu)" if args.trust_lcu else ""))
        mid, m5 = chosen
        print(f"[match] {mid} matches champion={want}; posting ingest...")

    detail = _synth_lcu_detail(m5, puuid)
    status, body = _post_ingest(puuid, detail, args.dashboard)
    print(f"[ingest] HTTP {status}  {body}")
    return 0 if status == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
