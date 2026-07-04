"""One-shot backfill: fill Home Recent build items into pre-ingest
match_history rows from rewind_history.db (A7, HOME_QA 2026-07-04).

Pre-LCU-ingest rows carry ``items == []`` and render hatched empty slots.
This stamps the operator's 6 build-slot items (+ queueId, so mode_subtype
also lights up) from rewind_history.db, which holds full per-participant
Match-V5 data for ~2954 tracked matches.

STRICT JOIN (safety). match_history gap rows have no match_id and mostly
game_id=0, so the only rewind key is fuzzy: (champion, timestamp-window).
The join-quality probe (2026-07-04) found a 10-min window gives 22
unambiguous vs 1 ambiguous; a 30-min window is WORSE (9 ambiguous). So this
tool stamps ONLY when EXACTLY ONE rewind match falls in the tight window;
ambiguous (>1) and no-match rows keep the honest empty placeholder. A
wrong-item backfill would be fabricated data - worse than an empty slot.

- Precise: stamps the KNOWN gap-row id (reuses the vetted
  dashboard.routes_last_match._stamp_row), not the ingest endpoint's
  timestamp-window row resolution.
- Idempotent: only rows lacking ``lcu_match_detail`` are discovered, so a
  re-run stamps nothing already done.
- WAL-safe: single UPDATE per row with busy_timeout=5000; SQLite serializes
  the commit against the running app's writer.

CLI is DRY-RUN by default; pass --apply to write.

Usage:
    python tools/backfill_home_items_from_rewind.py            # dry run
    python tools/backfill_home_items_from_rewind.py --apply    # write
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _parse_ts(ts: str) -> float | None:
    try:
        return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").timestamp()
    except (TypeError, ValueError):
        return None


def _game_id_from_match_id(match_id: str) -> int:
    # rewind match_id shape "NA1_5592802194"
    try:
        return int(str(match_id).split("_")[-1])
    except (TypeError, ValueError):
        return 0


def _load_rewind_by_champ(rconn: sqlite3.Connection) -> dict:
    """champion(lower) -> list of (match_id, queue_id, end_ts_s,
    tracked_champion_id)."""
    out: dict[str, list] = {}
    cur = rconn.execute(
        "SELECT match_id, queue_id, game_creation_ts, game_end_ts, "
        "       tracked_champion_id, tracked_champion_name FROM matches"
    )
    for mid, qid, gc, ge, tcid, tcname in cur:
        end_s = (ge or gc or 0) / 1000.0
        out.setdefault((tcname or "").lower(), []).append(
            (mid, qid, end_s, tcid))
    return out


def _rewind_items(rconn: sqlite3.Connection, match_id: str,
                  champion_id) -> dict | None:
    """The operator's participant row (by tracked champion_id) -> item ids
    + puuid + win. None if not uniquely resolvable."""
    rows = rconn.execute(
        "SELECT puuid, champion_id, win, item0, item1, item2, item3, "
        "       item4, item5, item6 FROM participants "
        "WHERE match_id=? AND champion_id=?",
        (match_id, champion_id),
    ).fetchall()
    if len(rows) != 1:
        return None  # 0 or a mirror -> cannot disambiguate, skip
    puuid, cid, win, *items = rows[0]
    return {
        "puuid": puuid,
        "champion_id": cid,
        "win": bool(win),
        "items": [int(x or 0) for x in items],  # item0..item6 (7)
    }


def _synth_detail(match_id: str, queue_id, rec: dict) -> dict:
    items = rec["items"]
    stats = {f"item{i}": items[i] for i in range(min(len(items), 7))}
    stats["win"] = rec["win"]
    return {
        "gameId": _game_id_from_match_id(match_id),
        "queueId": int(queue_id or 0),
        "participantIdentities": [
            {"participantId": 1, "player": {"puuid": rec["puuid"]}},
        ],
        "participants": [
            {"participantId": 1, "championId": rec["champion_id"],
             "stats": stats},
        ],
        "_source": "rewind_backfill",
    }


def backfill(match_db_path, rewind_db_path, window_s: int = 600,
             dry_run: bool = False) -> dict:
    """Stamp rewind build items into unambiguous pre-ingest gap rows.

    Returns a report: stamped / ambiguous / no_match counts + a per-row
    ``details`` list (champion, timestamp, verdict, match_id)."""
    from dashboard.routes_last_match import _stamp_row

    match_db_path = Path(match_db_path)
    rewind_db_path = Path(rewind_db_path)
    report = {"stamped": 0, "ambiguous": 0, "no_match": 0,
              "unparseable_ts": 0, "details": []}
    if not match_db_path.exists() or not rewind_db_path.exists():
        report["error"] = "missing db"
        return report

    rconn = sqlite3.connect(f"file:{rewind_db_path}?mode=ro", uri=True)
    mconn = sqlite3.connect(str(match_db_path))
    mconn.execute("PRAGMA busy_timeout = 5000")
    try:
        by_champ = _load_rewind_by_champ(rconn)
        gap = mconn.execute(
            "SELECT id, timestamp, mode, champion, raw_data FROM matches "
            "WHERE mode != 'TFT' AND (raw_data IS NULL OR "
            "raw_data NOT LIKE '%lcu_match_detail%')"
        ).fetchall()
        for rid, ts, _mode, champ, raw in gap:
            t = _parse_ts(ts)
            if t is None:
                report["unparseable_ts"] += 1
                continue
            cands = [c for c in by_champ.get((champ or "").lower(), [])
                     if abs(c[2] - t) <= window_s]
            if len(cands) != 1:
                key = "ambiguous" if len(cands) > 1 else "no_match"
                report[key] += 1
                report["details"].append(
                    {"id": rid, "champion": champ, "timestamp": ts,
                     "verdict": key, "candidates": len(cands)})
                continue
            match_id, queue_id, _end_s, tcid = cands[0]
            rec = _rewind_items(rconn, match_id, tcid)
            if rec is None or not any(rec["items"][:6]):
                report["no_match"] += 1
                report["details"].append(
                    {"id": rid, "champion": champ, "timestamp": ts,
                     "verdict": "no_items", "match_id": match_id})
                continue
            report["stamped"] += 1
            report["details"].append(
                {"id": rid, "champion": champ, "timestamp": ts,
                 "verdict": "stamp", "match_id": match_id,
                 "items": rec["items"][:6]})
            if not dry_run:
                detail = _synth_detail(match_id, queue_id, rec)
                _stamp_row(mconn, rid, raw or "", detail, rec["puuid"])
        if not dry_run:
            mconn.commit()
    finally:
        rconn.close()
        mconn.close()
    return report


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--match-db", default=str(_ROOT / "data" / "match_history.db"))
    ap.add_argument("--rewind-db", default=str(_ROOT / "data" / "rewind_history.db"))
    ap.add_argument("--window", type=int, default=600,
                    help="timestamp match window in seconds (default 600)")
    ap.add_argument("--apply", action="store_true",
                    help="write the backfill (default is a dry run)")
    args = ap.parse_args(argv)
    report = backfill(args.match_db, args.rewind_db, window_s=args.window,
                      dry_run=not args.apply)
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] window={args.window}s  stamped={report['stamped']}  "
          f"ambiguous={report['ambiguous']}  no_match={report['no_match']}  "
          f"unparseable_ts={report['unparseable_ts']}")
    for d in report["details"]:
        if d["verdict"] == "stamp":
            print(f"  STAMP id={d['id']:>5} {d['champion']:<14} {d['timestamp']}"
                  f"  <- {d.get('match_id')}  items={d.get('items')}")
    if report.get("error"):
        print(f"  ERROR: {report['error']}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
