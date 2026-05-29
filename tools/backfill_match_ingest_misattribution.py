"""Item 211 backfill: remap lcu_match_detail blobs that landed on the
wrong match_history.db row pre-fix.

Pre-fix /api/last-match/ingest used "ORDER BY timestamp DESC LIMIT 1"
to find the row to stamp with the LCU match detail. That raced the local
performance_tracker writer, so the detail (and the operator's items)
attached to the PREVIOUS row.

This tool walks every non-TFT row that carries lcu_match_detail. It
extracts the LCU's tracked-participant championId, maps to the
DDragon display name, and compares against the row's stored champion
column.

  - MATCH: the row is correctly attributed. Stamp game_id if 0; done.
  - MISMATCH: the detail is misattributed. Find the target row whose
    db.champion == LCU's championName AND db.timestamp lands within
    +/- 180s of (gameCreation+gameDuration). If found + that target row
    has no detail, MOVE the detail there (and stamp its game_id);
    clear it on the source row.
  - UNRESOLVED: log + skip (operator decides).

Safe by default:
  - Atomic file-copy backup of data/match_history.db before any UPDATE.
  - --dry-run prints the action plan without mutating.
  - Single sqlite transaction wraps all UPDATEs.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import shutil
import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_DB = _ROOT / "data" / "match_history.db"

# Tolerance window for matching gameEnd-unix against db.timestamp.
WINDOW_S = 180

# Champion-name aliases: cases where DDragon's display name differs from
# the string performance_tracker writes to matches.champion. Add lazily.
_NAME_ALIASES: dict[str, str] = {
    # DDragon: "Kai'Sa" / performance_tracker: "Kai'Sa" - identical.
    # If a future drift surfaces, map DDragon-name -> perf-tracker-name here.
}


def _load_champion_map() -> dict[int, str]:
    """Return {championId(int) -> display name} from the most recent
    DDragon mirror under data/meta_build/ddragon/<version>/champion.json."""
    base = _ROOT / "data" / "meta_build" / "ddragon"
    if not base.exists():
        sys.exit(f"ddragon mirror missing at {base}")
    versions = sorted(
        [p.name for p in base.iterdir() if p.is_dir()],
        key=lambda v: tuple(int(x) for x in v.split(".") if x.isdigit()),
    )
    for v in reversed(versions):
        cj = base / v / "champion.json"
        if cj.exists():
            d = json.loads(cj.read_text(encoding="utf-8"))
            out: dict[int, str] = {}
            for v_ in d["data"].values():
                cid = int(v_["key"])
                name = _NAME_ALIASES.get(v_["name"], v_["name"])
                out[cid] = name
            print(f"[ddragon] {v}: {len(out)} champions")
            return out
    sys.exit("no usable champion.json found under ddragon mirror")


def _row_lcu_owner(detail: dict, tracked_puuid: str) -> int | None:
    """Resolve operator's championId via participantIdentities+participants
    walk. None if the puuid is not found in the payload."""
    me_pid = None
    for ident in (detail.get("participantIdentities") or []):
        player = ident.get("player") or {}
        if str(player.get("puuid") or "").strip() == tracked_puuid:
            me_pid = ident.get("participantId")
            break
    if me_pid is None:
        return None
    for p in (detail.get("participants") or []):
        if p.get("participantId") == me_pid:
            try:
                return int(p.get("championId") or 0) or None
            except (TypeError, ValueError):
                return None
    return None


def _ts_unix(ts: str) -> int | None:
    try:
        return int(_dt.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").timestamp())
    except (TypeError, ValueError):
        return None


def _normalize_champ(name: str) -> str:
    return (name or "").strip().lower()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=_DB)
    ap.add_argument("--dry-run", action="store_true",
                    help="print plan without mutating the DB")
    ap.add_argument("--no-backup", action="store_true",
                    help="skip the atomic backup (dangerous)")
    ap.add_argument("--window", type=int, default=WINDOW_S,
                    help=f"max gameEnd-vs-db.timestamp delta in seconds "
                         f"(default {WINDOW_S})")
    args = ap.parse_args()
    window_s = int(args.window)

    if not args.db.exists():
        sys.exit(f"db missing: {args.db}")

    champ_map = _load_champion_map()

    backup_path = None
    if not args.dry_run and not args.no_backup:
        ts = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = args.db.with_suffix(f".db.bak-item211-{ts}")
        shutil.copy2(args.db, backup_path)
        print(f"[backup] {backup_path}")

    conn = sqlite3.connect(str(args.db))
    try:
        cur = conn.execute(
            "SELECT id, timestamp, mode, champion, game_id, raw_data "
            "FROM matches WHERE mode != 'TFT' "
            "ORDER BY timestamp DESC"
        )
        rows = cur.fetchall()
        print(f"[scan] {len(rows)} non-TFT rows")

        # Index rows by normalized champion + timestamp for the move target
        # search. Refreshed in-memory after each move.
        by_id = {r[0]: list(r) for r in rows}
        # 0=id 1=timestamp 2=mode 3=champion 4=game_id 5=raw_data

        plan_correct = []      # (row_id, gid)
        plan_move = []         # (src_id, dst_id, gid, lcu_champ)
        plan_unresolved = []   # (row_id, reason)
        plan_orphans = []      # rows with detail but champ mismatch + no target

        # Index: db.champion (normalized) -> list of (id, ts_unix, has_detail).
        def _has_detail(rd: str) -> bool:
            try:
                return bool(json.loads(rd or "{}").get("lcu_match_detail"))
            except Exception:
                return False

        idx_by_champ: dict[str, list[tuple[int, int, bool]]] = {}
        for rid, row in by_id.items():
            ts_unix = _ts_unix(row[1])
            if ts_unix is None:
                continue
            key = _normalize_champ(row[3])
            idx_by_champ.setdefault(key, []).append(
                (rid, ts_unix, _has_detail(row[5]))
            )

        for rid, row in list(by_id.items()):
            ts, _mode, db_champ, gid, raw = row[1], row[2], row[3], row[4], row[5]
            try:
                rd = json.loads(raw or "{}")
            except Exception:
                rd = {}
            detail = rd.get("lcu_match_detail") or {}
            if not detail:
                continue  # nothing to validate; left as-is
            tracked = (rd.get("tracked_puuid") or "").strip()
            detail_gid = int(detail.get("gameId") or 0)
            lcu_champ_id = _row_lcu_owner(detail, tracked)
            if not lcu_champ_id:
                plan_unresolved.append((rid, "lcu participant puuid not found"))
                continue
            lcu_name = champ_map.get(lcu_champ_id)
            if not lcu_name:
                plan_unresolved.append(
                    (rid, f"championId {lcu_champ_id} not in ddragon map"))
                continue
            if _normalize_champ(db_champ) == _normalize_champ(lcu_name):
                plan_correct.append((rid, detail_gid))
                continue

            # MISMATCH. Find the right home for this detail.
            game_creation_ms = int(detail.get("gameCreation") or 0)
            game_duration_s = int(detail.get("gameDuration") or 0)
            game_end_unix = (game_creation_ms + game_duration_s * 1000) // 1000

            target_rid = None
            best_delta = None
            for cand_id, cand_ts_unix, cand_has_detail in idx_by_champ.get(
                _normalize_champ(lcu_name), []
            ):
                if cand_id == rid:
                    continue
                if cand_has_detail:
                    continue  # already populated; never overwrite
                delta = abs(cand_ts_unix - game_end_unix)
                if delta <= window_s and (best_delta is None or delta < best_delta):
                    target_rid = cand_id
                    best_delta = delta
            if target_rid is None:
                plan_orphans.append(
                    (rid, f"db_champ={db_champ} lcu_champ={lcu_name} "
                          f"gid={detail_gid} no within-{window_s}s target"))
                continue
            plan_move.append((rid, target_rid, detail_gid, lcu_name))
            # Mark the target row as detail-bearing so a later iteration
            # cannot poach it too.
            for i, (cid, c_ts, _) in enumerate(idx_by_champ[
                _normalize_champ(lcu_name)
            ]):
                if cid == target_rid:
                    idx_by_champ[_normalize_champ(lcu_name)][i] = (
                        cid, c_ts, True
                    )
                    break

        print(f"[plan] correct={len(plan_correct)} "
              f"move={len(plan_move)} "
              f"unresolved={len(plan_unresolved)} "
              f"orphans={len(plan_orphans)}")
        for src, dst, gid, name in plan_move:
            print(f"  MOVE src={src} -> dst={dst}  gid={gid}  champ={name}")
        for rid, why in plan_unresolved:
            print(f"  SKIP id={rid}  why={why}")
        for rid, why in plan_orphans:
            print(f"  ORPHAN id={rid}  {why}")

        if args.dry_run:
            print("[dry-run] no mutations applied")
            return 0

        # Apply MOVEs first (clear src + populate dst), then stamp game_ids
        # on correctly-attributed rows.
        with conn:
            for src, dst, gid, _name in plan_move:
                src_raw = by_id[src][5]
                src_rd = json.loads(src_raw or "{}")
                detail = src_rd.pop("lcu_match_detail", None)
                tracked = src_rd.pop("tracked_puuid", None)
                ingested_at = src_rd.pop("lcu_ingested_at", None)
                src_rd["item211_backfill_moved_to"] = int(dst)
                src_rd["item211_backfill_at"] = _dt.datetime.now().isoformat(
                    timespec="seconds")
                conn.execute(
                    "UPDATE matches SET raw_data = ?, game_id = 0 WHERE id = ?",
                    (json.dumps(src_rd, default=str, ensure_ascii=False), src),
                )

                dst_raw = by_id[dst][5]
                dst_rd = json.loads(dst_raw or "{}")
                dst_rd["lcu_match_detail"] = detail
                if tracked:
                    dst_rd["tracked_puuid"] = tracked
                if ingested_at:
                    dst_rd["lcu_ingested_at"] = ingested_at
                dst_rd["item211_backfill_received_from"] = int(src)
                dst_rd["item211_backfill_at"] = _dt.datetime.now().isoformat(
                    timespec="seconds")
                conn.execute(
                    "UPDATE matches SET raw_data = ?, game_id = ? WHERE id = ?",
                    (json.dumps(dst_rd, default=str, ensure_ascii=False),
                     int(gid or 0), dst),
                )
            for rid, gid in plan_correct:
                if not gid:
                    continue
                cur_gid = conn.execute(
                    "SELECT game_id FROM matches WHERE id = ?", (rid,),
                ).fetchone()[0]
                if cur_gid != gid:
                    conn.execute(
                        "UPDATE matches SET game_id = ? WHERE id = ?",
                        (int(gid), rid),
                    )

        print(f"[done] moved={len(plan_move)} stamped={len(plan_correct)}")
        if backup_path:
            print(f"[backup-kept] {backup_path}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
