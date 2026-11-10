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

  - MATCH: the row is correctly attributed. Stamp game_id if it is 0 and
    no other row already holds that gameId; a different non-zero game_id
    is a CONFLICT and is left as-is.
  - MISMATCH: the detail is misattributed. Find the target row whose
    db.champion == LCU's championName AND db.timestamp lands within
    +/- --window seconds of (gameCreation+gameDuration). A target must
    carry no detail, decode as a JSON object and hold game_id 0 or the
    detail's own gameId; a tie at the best delta is ambiguous and skipped.
    MOVE the detail there (and stamp its game_id); clear it on the source
    row, zeroing the source game_id only when it came from that detail.
  - UNRESOLVED / ORPHAN / CONFLICT: log + skip (operator decides).

Safe by default:
  - Backup: a SQLite online-backup snapshot (so committed rows still in
    the -wal sidecar are included) written to a temp name and then
    renamed, never over an existing backup.
  - --dry-run opens the DB read-only and prints the action plan.
  - The scan, plan and every UPDATE run inside ONE ``BEGIN IMMEDIATE``
    transaction, so a concurrent writer (RC's ingest route, the
    performance_tracker) cannot change a row between the read the plan
    is built from and the write that acts on it. Any failure rolls the
    whole batch back.
  - A junk row (non-object or non-UTF-8 raw_data, non-object detail,
    non-numeric or out-of-range ids, a timestamp the clock cannot convert,
    an empty or unreadable champion) is reported and skipped, never a
    crash that aborts the run.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# The backup's scratch -> final rename goes through the repo's one atomic
# rename (bounded WinError 5 retry), as core/rofl_archive.py does for a file
# another API wrote (RM-258 atomic-write guard).
from core.polled_json import _replace_with_retry  # noqa: E402

_DB = _ROOT / "data" / "match_history.db"

# Tolerance window for matching gameEnd-unix against db.timestamp.
WINDOW_S = 180

# Champion-name aliases: cases where DDragon's display name differs from
# the string performance_tracker writes to matches.champion. Add lazily.
_NAME_ALIASES: dict[str, str] = {
    # DDragon: "Kai'Sa" / performance_tracker: "Kai'Sa" - identical.
    # If a future drift surfaces, map DDragon-name -> perf-tracker-name here.
}

# A Riot id never needs more digits than this; a longer digit string is junk
# (and int() of a 4300+ digit string raises ValueError on 3.11+).
_MAX_ID_DIGITS = 19
# SQLite INTEGER is a signed 64-bit value; binding a larger Python int raises
# OverflowError, so anything outside it is junk too.
_INT64_MIN, _INT64_MAX = -(2 ** 63), 2 ** 63 - 1
_BACKUP_TAG = "bak-item211"


def _say(text: str) -> None:
    """print() that cannot raise on the text: a champion name from the DB or
    DDragon that the console / pipe encoding (cp1252 when stdout is
    redirected without UTF-8 mode) cannot represent is backslash-escaped
    instead of aborting the run."""
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        safe = text.encode(enc, "backslashreplace").decode(enc)
    except LookupError:
        safe = text.encode("ascii", "backslashreplace").decode("ascii")
    print(safe)


def _as_int(value: object) -> int | None:
    """Strict integer read: an int (never a bool), an integral finite float or
    a short ASCII digit string, inside SQLite's signed 64-bit range; anything
    else is None."""
    out = None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        out = value
    elif isinstance(value, float):
        out = int(value) if value.is_integer() else None
    elif isinstance(value, str):
        s = value.strip()
        if s.isascii() and s.isdigit() and len(s) <= _MAX_ID_DIGITS:
            out = int(s)
    if out is None or not _INT64_MIN <= out <= _INT64_MAX:
        return None
    return out


def _load_champion_map() -> dict[int, str]:
    """Return {championId(int) -> display name} from the most recent usable
    DDragon mirror under data/meta_build/ddragon/<version>/champion.json.
    A malformed entry is skipped; an unreadable newest file falls back to
    the next version."""
    base = _ROOT / "data" / "meta_build" / "ddragon"
    if not base.is_dir():
        sys.exit(f"ddragon mirror missing at {base}")
    versions = sorted(
        (p.name for p in base.iterdir() if p.is_dir()),
        key=lambda v: tuple(
            int(x) for x in v.split(".") if x.isascii() and x.isdigit()),
    )
    for v in reversed(versions):
        cj = base / v / "champion.json"
        if not cj.is_file():
            continue
        try:
            d = json.loads(cj.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            _say(f"[ddragon] {v}: unreadable champion.json "
                  f"({type(exc).__name__}); trying an older version")
            continue
        data = d.get("data") if isinstance(d, dict) else None
        if not isinstance(data, dict):
            _say(f"[ddragon] {v}: champion.json has no data object")
            continue
        out: dict[int, str] = {}
        skipped = 0
        for entry in data.values():
            cid = _as_int(entry.get("key")) if isinstance(entry, dict) else None
            name = entry.get("name") if isinstance(entry, dict) else None
            if cid is None or cid <= 0 or not isinstance(name, str) or not name.strip():
                skipped += 1
                continue
            out[cid] = _NAME_ALIASES.get(name, name)
        if out:
            note = f" ({skipped} malformed skipped)" if skipped else ""
            _say(f"[ddragon] {v}: {len(out)} champions{note}")
            return out
    sys.exit("no usable champion.json found under ddragon mirror")


def _row_lcu_owner(detail: object, tracked_puuid: object) -> int | None:
    """Resolve the operator's championId via a participantIdentities +
    participants walk. None if the puuid is empty, absent from the payload,
    matched more than once, or the payload is the wrong shape."""
    if not isinstance(detail, dict) or not isinstance(tracked_puuid, str):
        return None
    tracked = tracked_puuid.strip()
    if not tracked:
        # An empty puuid would "match" every participant whose puuid is
        # missing (bots, anonymised entries) - never resolve on it.
        return None
    idents = detail.get("participantIdentities")
    parts = detail.get("participants")
    if not isinstance(idents, list) or not isinstance(parts, list):
        return None
    pids = []
    for ident in idents:
        if not isinstance(ident, dict):
            continue
        player = ident.get("player")
        puuid = player.get("puuid") if isinstance(player, dict) else None
        if isinstance(puuid, str) and puuid.strip() == tracked:
            pids.append(_as_int(ident.get("participantId")))
    if len(pids) != 1 or pids[0] is None:
        return None
    for p in parts:
        if isinstance(p, dict) and _as_int(p.get("participantId")) == pids[0]:
            cid = _as_int(p.get("championId"))
            return cid if cid is not None and cid > 0 else None
    return None


def _ts_unix(ts: object) -> int | None:
    """db.timestamp is LOCAL wall-clock text (performance_tracker writes it),
    so it is read as local time. None for anything the clock cannot convert
    (Windows raises OSError for a pre-1970 local time)."""
    if not isinstance(ts, str):
        return None
    try:
        local = _dt.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").astimezone()
        return int(local.timestamp())
    except (ValueError, OverflowError, OSError):
        return None


class _BadText(bytes):
    """A TEXT cell that is not valid UTF-8, kept as raw bytes."""


def _text_factory(raw: bytes) -> str | bytes:
    """sqlite3's default text_factory raises OperationalError on the FIRST
    invalid-UTF-8 cell and aborts the whole fetch; this keeps such a cell as
    a _BadText so only its own row is skipped."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return _BadText(raw)


def _connect(target: str, **kwargs) -> sqlite3.Connection:
    conn = sqlite3.connect(target, **kwargs)
    conn.text_factory = _text_factory
    return conn


def _normalize_champ(name: object) -> str:
    return name.strip().lower() if isinstance(name, str) else ""


def _decode_raw(raw: object) -> dict | None:
    """raw_data as a dict; {} for an empty column; None when it is not a JSON
    object (such a row is never read from or written to)."""
    if raw is None or raw == "":
        return {}
    if not isinstance(raw, str):
        return None
    try:
        value = json.loads(raw)
    except (ValueError, RecursionError):  # RecursionError: absurdly deep nesting
        return None
    return value if isinstance(value, dict) else None


@dataclass
class Move:
    src: int
    dst: int
    gid: int
    champ: str
    clear_src_gid: bool


@dataclass
class Plan:
    matched: int = 0
    stamp: list[tuple[int, int]] = field(default_factory=list)
    move: list[Move] = field(default_factory=list)
    unresolved: list[tuple[int, str]] = field(default_factory=list)
    orphans: list[tuple[int, str]] = field(default_factory=list)
    conflicts: list[tuple[int, str]] = field(default_factory=list)


def build_plan(rows: list[tuple], champ_map: dict[int, str],
               window_s: int) -> tuple[Plan, dict[int, dict | None]]:
    """Pure planner. rows = (id, timestamp, mode, champion, game_id, raw_data).
    Returns the plan and each row's decoded raw_data (None = undecodable)."""
    plan = Plan()
    decoded = {r[0]: _decode_raw(r[5]) for r in rows}
    # game_id column: NULL reads as 0 (unknown). Anything that is not a
    # non-negative integer is junk: such a row is never stamped, never a move
    # target, and its column is never rewritten by a move.
    gid_of: dict[int, int] = {}
    junk_gid: set[int] = set()
    # SQLite hands back an INTEGER-affinity value as int; TEXT / REAL / BLOB
    # left in the column is junk however numeric it looks (the guarded stamp
    # UPDATE compares the stored value, not a parsed one).
    for r in rows:
        col = r[4]
        if col is None:
            gid = 0
        elif isinstance(col, int) and not isinstance(col, bool) and col >= 0:
            gid = col
        else:
            junk_gid.add(r[0])
            gid = 0
        gid_of[r[0]] = gid
    owners: dict[int, set[int]] = {}
    for rid, gid in gid_of.items():
        if gid:
            owners.setdefault(gid, set()).add(rid)

    # Move-target index: champion -> [rid, ts_unix, busy]. busy = carries a
    # detail, is undecodable, or has already been claimed by a move.
    idx_by_champ: dict[str, list[list]] = {}
    for r in rows:
        ts_unix = _ts_unix(r[1])
        if ts_unix is None:
            continue
        rd = decoded[r[0]]
        busy = rd is None or bool(rd.get("lcu_match_detail"))
        idx_by_champ.setdefault(_normalize_champ(r[3]), []).append(
            [r[0], ts_unix, busy])

    for r in rows:
        rid, db_champ = r[0], r[3]
        rd = decoded[rid]
        if rd is None:
            # Undecodable raw_data cannot be inspected; say so when it
            # visibly mentions a detail, otherwise there is nothing to do.
            if isinstance(r[5], _BadText):
                plan.unresolved.append((rid, "raw_data is not valid UTF-8"))
            elif isinstance(r[5], str) and "lcu_match_detail" in r[5]:
                plan.unresolved.append((rid, "raw_data is not a JSON object"))
            continue
        detail = rd.get("lcu_match_detail")
        if not detail:
            continue  # nothing to validate; left as-is
        if not isinstance(detail, dict):
            plan.unresolved.append((rid, "lcu_match_detail is not an object"))
            continue
        tracked = rd.get("tracked_puuid")
        if not isinstance(tracked, str) or not tracked.strip():
            plan.unresolved.append((rid, "tracked_puuid missing"))
            continue
        detail_gid = max(_as_int(detail.get("gameId")) or 0, 0)
        lcu_champ_id = _row_lcu_owner(detail, tracked)
        if not lcu_champ_id:
            plan.unresolved.append((rid, "lcu participant puuid not found"))
            continue
        lcu_name = champ_map.get(lcu_champ_id)
        if not lcu_name:
            plan.unresolved.append(
                (rid, f"championId {lcu_champ_id} not in ddragon map"))
            continue
        if not _normalize_champ(db_champ):
            # Without the row's own champion there is no evidence the
            # detail is misattributed; never move it on a guess.
            plan.unresolved.append((rid, "champion column empty or unreadable"))
            continue
        row_gid = gid_of[rid]

        if _normalize_champ(db_champ) == _normalize_champ(lcu_name):
            plan.matched += 1
            if not detail_gid or row_gid == detail_gid:
                continue
            if rid in junk_gid:
                plan.conflicts.append(
                    (rid, "game_id column is not a non-negative integer; "
                          "not stamped"))
                continue
            if row_gid:
                plan.conflicts.append(
                    (rid, f"game_id={row_gid} but detail gameId={detail_gid}; "
                          "left as-is"))
                continue
            others = owners.get(detail_gid, set()) - {rid}
            if others:
                plan.conflicts.append(
                    (rid, f"gameId={detail_gid} already on row(s) "
                          f"{sorted(others)}; not stamped"))
                continue
            plan.stamp.append((rid, detail_gid))
            owners.setdefault(detail_gid, set()).add(rid)
            gid_of[rid] = detail_gid
            continue

        # MISMATCH. Find the right home for this detail.
        creation_ms = _as_int(detail.get("gameCreation"))
        duration_s = _as_int(detail.get("gameDuration"))
        if not creation_ms or creation_ms <= 0 or duration_s is None or duration_s < 0:
            plan.orphans.append(
                (rid, f"db_champ={db_champ} lcu_champ={lcu_name} gid={detail_gid} "
                      "detail has no usable gameCreation/gameDuration"))
            continue
        game_end_unix = (creation_ms + duration_s * 1000) // 1000

        best: list[list] = []
        best_delta = None
        for cand in idx_by_champ.get(_normalize_champ(lcu_name), []):
            cand_id, cand_ts, busy = cand
            if cand_id == rid or busy or cand_id in junk_gid:
                continue  # never overwrite a populated / unreadable row
            cand_gid = gid_of[cand_id]
            if cand_gid and cand_gid != detail_gid:
                continue  # the row is provably a different game
            delta = abs(cand_ts - game_end_unix)
            if delta > window_s:
                continue
            if best_delta is None or delta < best_delta:
                best, best_delta = [cand], delta
            elif delta == best_delta:
                best.append(cand)
        if not best:
            plan.orphans.append(
                (rid, f"db_champ={db_champ} lcu_champ={lcu_name} "
                      f"gid={detail_gid} no within-{window_s}s target"))
            continue
        if len(best) > 1:
            plan.conflicts.append(
                (rid, f"gid={detail_gid} ambiguous target rows "
                      f"{sorted(c[0] for c in best)} at {best_delta}s"))
            continue
        target = best[0]
        dst = target[0]
        if detail_gid:
            others = owners.get(detail_gid, set()) - {rid, dst}
            if others:
                plan.conflicts.append(
                    (rid, f"gameId={detail_gid} already on row(s) "
                          f"{sorted(others)}; not moved"))
                continue
        clear_src = bool(detail_gid) and row_gid == detail_gid
        plan.move.append(Move(rid, dst, detail_gid, lcu_name, clear_src))
        # Claim the target so a later iteration cannot poach it too.
        target[2] = True
        if detail_gid:
            owners.setdefault(detail_gid, set()).add(dst)
            gid_of[dst] = detail_gid
            if clear_src:
                owners[detail_gid].discard(rid)
                gid_of[rid] = 0
    return plan, decoded


def _print_plan(plan: Plan) -> None:
    _say(f"[plan] correct={plan.matched} "
          f"stamp={len(plan.stamp)} "
          f"move={len(plan.move)} "
          f"unresolved={len(plan.unresolved)} "
          f"orphans={len(plan.orphans)} "
          f"conflicts={len(plan.conflicts)}")
    for m in plan.move:
        _say(f"  MOVE src={m.src} -> dst={m.dst}  gid={m.gid}  champ={m.champ}")
    for rid, why in plan.unresolved:
        _say(f"  SKIP id={rid}  why={why}")
    for rid, why in plan.orphans:
        _say(f"  ORPHAN id={rid}  {why}")
    for rid, why in plan.conflicts:
        _say(f"  CONFLICT id={rid}  {why}")


def _update_one(conn: sqlite3.Connection, sql: str, params: tuple) -> None:
    if conn.execute(sql, params).rowcount != 1:
        raise RuntimeError(f"expected one row updated: {sql} {params[-1]}")


def _apply(conn: sqlite3.Connection, plan: Plan,
           decoded: dict[int, dict | None]) -> None:
    """Apply MOVEs first (clear src + populate dst), then stamp game_ids on
    correctly attributed rows. Runs inside the caller's transaction.
    raw_data is re-encoded ASCII-escaped: a lone-surrogate ``\\ud800`` escape
    is valid JSON but cannot be bound to SQLite once decoded, so it must stay
    escaped (readers json.loads the column, so the escaping is invisible)."""
    now = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    for m in plan.move:
        src_rd = dict(decoded[m.src] or {})
        detail = src_rd.pop("lcu_match_detail", None)
        tracked = src_rd.pop("tracked_puuid", None)
        ingested_at = src_rd.pop("lcu_ingested_at", None)
        src_rd["item211_backfill_moved_to"] = int(m.dst)
        src_rd["item211_backfill_at"] = now
        src_json = json.dumps(src_rd, default=str)
        if m.clear_src_gid:
            _update_one(conn, "UPDATE matches SET raw_data = ?, game_id = 0 "
                              "WHERE id = ?", (src_json, m.src))
        else:
            _update_one(conn, "UPDATE matches SET raw_data = ? WHERE id = ?",
                        (src_json, m.src))

        dst_rd = dict(decoded[m.dst] or {})
        dst_rd["lcu_match_detail"] = detail
        if tracked:
            dst_rd["tracked_puuid"] = tracked
        if ingested_at:
            dst_rd["lcu_ingested_at"] = ingested_at
        dst_rd["item211_backfill_received_from"] = int(m.src)
        dst_rd["item211_backfill_at"] = now
        dst_json = json.dumps(dst_rd, default=str)
        if m.gid:
            _update_one(conn, "UPDATE matches SET raw_data = ?, game_id = ? "
                              "WHERE id = ?", (dst_json, int(m.gid), m.dst))
        else:
            _update_one(conn, "UPDATE matches SET raw_data = ? WHERE id = ?",
                        (dst_json, m.dst))
    for rid, gid in plan.stamp:
        _update_one(conn, "UPDATE matches SET game_id = ? WHERE id = ? "
                          "AND (game_id IS NULL OR game_id = 0)", (int(gid), rid))


def _ro_uri(db: Path) -> str:
    return db.resolve().as_uri() + "?mode=ro"


def _backup_db(db: Path, stamp: str) -> Path:
    """Online-backup snapshot of ``db`` beside it, named
    ``<name>.bak-item211-<stamp>[-n]``. Includes committed rows still in the
    -wal sidecar, is written under a temp name and renamed into place, and
    never replaces an existing backup."""
    final = db.with_name(f"{db.name}.{_BACKUP_TAG}-{stamp}")
    n = 0
    while final.exists():
        n += 1
        if n > 99:
            raise FileExistsError(f"no free backup name for {db.name} at {stamp}")
        final = db.with_name(f"{db.name}.{_BACKUP_TAG}-{stamp}-{n}")
    tmp = final.with_name(f"{final.name}.tmp-{os.getpid()}")
    try:
        src = sqlite3.connect(_ro_uri(db), uri=True)
        try:
            dst = sqlite3.connect(str(tmp))
            try:
                src.backup(dst)
                ok = dst.execute("PRAGMA quick_check").fetchone()
            finally:
                dst.close()
        finally:
            src.close()
        if not ok or ok[0] != "ok":
            raise RuntimeError(f"backup failed quick_check: {ok}")
        if final.exists():
            raise FileExistsError(f"backup name taken during the copy: {final}")
        _replace_with_retry(tmp, final)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return final


_SCAN_SQL = ("SELECT id, timestamp, mode, champion, game_id, raw_data "
             "FROM matches WHERE mode != 'TFT' ORDER BY timestamp DESC")


def _non_negative_int(text: str) -> int:
    value = _as_int(text)  # digits only, so a leading "-" is already None
    if value is None:
        raise argparse.ArgumentTypeError(f"expected a non-negative integer, got {text!r}")
    return value


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=_DB)
    ap.add_argument("--dry-run", action="store_true",
                    help="print plan without mutating the DB (opens it read-only)")
    ap.add_argument("--no-backup", action="store_true",
                    help="skip the online backup (dangerous)")
    ap.add_argument("--window", type=_non_negative_int, default=WINDOW_S,
                    help=f"max gameEnd-vs-db.timestamp delta in seconds "
                         f"(default {WINDOW_S})")
    args = ap.parse_args(argv)
    window_s = args.window

    if not args.db.is_file():
        sys.exit(f"db missing: {args.db}")

    champ_map = _load_champion_map()

    if args.dry_run:
        conn = _connect(_ro_uri(args.db), uri=True)
        try:
            rows = conn.execute(_SCAN_SQL).fetchall()
        finally:
            conn.close()
        _say(f"[scan] {len(rows)} non-TFT rows")
        plan, _decoded = build_plan(rows, champ_map, window_s)
        _print_plan(plan)
        _say("[dry-run] no mutations applied")
        return 0

    backup_path = None
    if not args.no_backup:
        stamp = _dt.datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
        backup_path = _backup_db(args.db, stamp)
        _say(f"[backup] {backup_path}")

    conn = _connect(str(args.db), timeout=10, isolation_level=None)
    try:
        # Hold the write lock from the scan to the last UPDATE: the plan is
        # built from rows no other writer can change before it is applied.
        conn.execute("BEGIN IMMEDIATE")
        try:
            rows = conn.execute(_SCAN_SQL).fetchall()
            _say(f"[scan] {len(rows)} non-TFT rows")
            plan, decoded = build_plan(rows, champ_map, window_s)
            _print_plan(plan)
            _apply(conn, plan, decoded)
        except BaseException:
            # SQLite may already have ended the transaction itself (I/O or
            # disk-full error); a bare ROLLBACK would then mask the cause.
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
    finally:
        conn.close()

    _say(f"[done] moved={len(plan.move)} stamped={len(plan.stamp)}")
    if backup_path:
        _say(f"[backup-kept] {backup_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
