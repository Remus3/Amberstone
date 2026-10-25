"""
scripts/repair_tft_match_rows.py - session 134 N8 backfill (finished s135).

The writer fix (performance_tracker.save_tft_rating / rate_tft_game, same
slice) stops NEW wrong TFT ratings. Per the CLAUDE.md "Data fixes" rule the
rows ALREADY written stay wrong until this runs. Measured on a scratch COPY
of the live data (session 135), every mode='TFT' row of data/match_history.db
had game_id 0, and they fall into SIGNATURE classes:

  * junk, stale-planner 8th: "Dark Star Vertical" / 8th / level 0 / stage 0 /
    0 s - the comp_state.json planner comp and the alive_others default of 7
    (performance_tracker._legacy_tft_placement / _planner_comp);
  * junk, test literal: "Test Comp" or no comp, B / 4th / level 8 / stage 4 /
    exactly 1800 s, no units - tests that wrote through the _get_db root
    cache (performance_tracker._get_db) into the live file;
  * duplicates: a real game written twice (same comp, grade, placement,
    level, stage and bit-identical float game length, seconds apart);
  * real games, KEPT: everything else written before the first recorded game.
    s134 counted "every game_id-0 row before the first QA game" as junk
    (8,209), which would have quarantined the real games too;
  * the game-end row of a QA-recorded game (inside that game's window): it
    is stamped with its game id and re-rated from the RM-616 store, so the
    row is corrected IN PLACE (same id, same timestamp). A second such row,
    or every one when the fixed collector already wrote the game's own row,
    is a superseded write of that game and is quarantined;
  * a later game-id-less row no QA game explains: KEPT and reported.

Junk, duplicates and superseded rows are QUARANTINED, never deleted: moved,
ids intact, into the table matches_quarantine in the same file, with a
reason. A QA game the store never captured gets its EOG record from the QA
recorder's own GET of the same route (<qa dir>/eog_raw.json, parsed and
scrubbed by tft_placement.parse_eog; append-only persist).
data/ratings/last_tft.json ends on the newest game (rate_tft_game's rule).

Input: the QA recorder's matches.jsonl (one JSON line per match with
game_id, dir, placement, start_iso, end_iso). Nothing identifying is read
into the store (parse_eog keeps no riot id / puuid).

Safety:
  * Every read of the database before the write (the dry run, the plan, the
    digests, the read-back) runs on a byte COPY of match_history.db and its
    -wal in a temporary directory, taken while their size and mtime hold
    still: the root is only ever READ (no open of the live file, so no -shm
    or -wal byte changes either). --dry-run is the default.
  * --apply refuses while a TFT game runs (TFTClient-Win64-Shipping.exe, or
    health.json has_game / tft_mode); while RC itself runs (health.json pid
    alive) unless --allow-rc-running - stop RC and pause the RC-Supervisor
    task first; unless --expect-quarantine equals the measured count; on
    unusable store inputs; and when a QA game has no store record.
  * --apply re-plans INSIDE its `BEGIN IMMEDIATE` write transaction on the
    live file and refuses (rollback, nothing written) when the plan changed
    since it was printed - a concurrent writer (the fixed collector rating a
    game) can never leave two rows for one game. The re-rates after the
    commit go through MatchDB.upsert_by_game_id, itself one BEGIN IMMEDIATE.
  * --apply takes its BACKUP inside that transaction, before its first
    write: <root>/ops/runtime/backups/tft-n8-<stamp>/ (gitignored) holds a
    consistent copy of match_history.db (sqlite backup API), last_tft.json,
    placement_heatmap.json and a manifest of sha256s; the copy is re-read
    and row-counted before anything is written.
  * --apply logs every step and error to <root>/logs/repair_tft_match_rows.log
    and ends with a READ-BACK: one row per QA game holding the planned grade
    and placement, nothing left to quarantine, last_tft.json on the planned
    game. A failed read-back exits non-zero.
  * Idempotent: a repaired root plans nothing, and an --apply that plans
    nothing writes nothing (no backup either).

Usage:
    python scripts/repair_tft_match_rows.py --root <checkout> --qa-matches <matches.jsonl> --dry-run
    python scripts/repair_tft_match_rows.py --root <checkout> --qa-matches <matches.jsonl> \\
        --apply --expect-quarantine <n from the dry run>
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import logging
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import performance_tracker as pt  # noqa: E402
from core.match_db import NUMERIC_COLS, coerce_numeric  # noqa: E402
from core.polled_json import atomic_write_json  # noqa: E402
from tft import tft_placement as tp  # noqa: E402

_log = logging.getLogger("rc.scripts.repair_tft_match_rows")

QUARANTINE_TABLE = "matches_quarantine"
CLASS_STALE_8TH = "stale_planner_8th"
CLASS_TEST_LITERAL = "test_literal_top4"
_CLASS_SQL = {
    CLASS_STALE_8TH: ("tft_comp = 'Dark Star Vertical' AND tft_placement = 8 "
                      "AND game_time_s = 0 AND tft_level = 0 AND tft_stage = 0"),
    CLASS_TEST_LITERAL: ("champion IN ('', 'Test Comp') AND tft_comp IN ('', 'Test Comp') "
                         "AND grade = 'B' AND tft_placement = 4 AND tft_level = 8 "
                         "AND tft_stage = 4 AND game_time_s = 1800 "
                         "AND COALESCE(tft_units, '') IN ('', '[]')"),
}
REASON_JUNK = "s134-N8 junk: {cls}, game_id 0, written before the first recorded game"
REASON_DUP = "s134-N8 duplicate: the same game written twice, kept id {keep}"
REASON_SUPERSEDED = "s134-N8 superseded: a second game-end row of game {gid}"
TFT_GAME_IMAGE = "tftclient-win64-shipping.exe"
BACKUP_DIR = Path("ops") / "runtime" / "backups"
LOG_NAME = "repair_tft_match_rows.log"
# A game-end row is written within seconds of the game's end; a QA match's
# recorder end can trail the client end by a few seconds either way.
_END_WINDOW = timedelta(minutes=15)
# Two writes of one game land within a second or two of each other.
_DUP_WINDOW_S = 5.0
_DUP_KEY = ("champion", "grade", "tft_placement", "tft_level", "tft_stage",
            "game_time_s", "tft_comp", "tft_units")
# Columns compared to decide a game's row already holds its rating.
_SKIP_COMPARE = frozenset({"mode", "timestamp", "game_id"})
_JSON_COLS = frozenset({"tft_traits", "tft_units", "tft_augments", "tft_items", "notes"})
_LAST_KEYS = ("tft_game_id", "rating", "label", "tft_placement", "tft_level", "tft_stage",
              "tft_comp", "tft_placement_source")
_SNAPSHOT_TRIES = 5
# Called (no arguments) right before --apply takes the write lock. Tests
# interleave a concurrent writer here; production leaves it None.
_BEFORE_WRITE_LOCK = None


# -- inputs ----------------------------------------------------------------------

def _iso_local(iso: str) -> datetime:
    """A recorder ISO stamp (UTC offset) as a naive LOCAL datetime - the
    match_history.db timestamp convention."""
    return datetime.fromisoformat(iso).astimezone().replace(tzinfo=None)


def load_qa_matches(path: Path) -> list[dict]:
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        m = json.loads(line)
        gid = m.get("game_id")
        if not isinstance(gid, int) or gid <= 0 or not m.get("end_iso"):
            continue
        out.append({"game_id": gid, "dir": Path(m["dir"]),
                    "placement": m.get("placement"),
                    "start": _iso_local(m["start_iso"]) if m.get("start_iso") else None,
                    "end": _iso_local(m["end_iso"]),
                    "end_unix": datetime.fromisoformat(m["end_iso"]).timestamp()})
    return sorted(out, key=lambda m: m["end_unix"])


def live_game_reason(root: Path) -> str:
    """Why a TFT game counts as running now, or "" when none does."""
    try:
        import psutil
        for p in psutil.process_iter(["name"]):
            if (p.info.get("name") or "").lower() == TFT_GAME_IMAGE:
                return f"{TFT_GAME_IMAGE} is running (pid {p.pid})"
    except Exception as exc:  # noqa: BLE001
        return f"process table unreadable: {exc}"
    h = _health(root)
    if h.get("has_game") or h.get("tft_mode"):
        return "health.json reports a game in progress"
    return ""


def _health(root: Path) -> dict:
    try:
        h = json.loads((root / "ops" / "runtime" / "health.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return h if isinstance(h, dict) else {}


def rc_running_reason(root: Path) -> str:
    """Why RC counts as running (health.json names a live python process),
    or "". A pid that no longer exists, or now belongs to another program,
    is not RC."""
    pid = _health(root).get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return ""
    try:
        import psutil
        if not psutil.pid_exists(pid):
            return ""
        name = psutil.Process(pid).name().lower()
    except Exception as exc:  # noqa: BLE001 - unknown is not "stopped"
        return f"RC pid {pid} from health.json could not be checked ({exc})"
    if "python" not in name:
        return ""
    return f"RC is running (pid {pid}, ops/runtime/health.json)"


# -- read-only snapshots, digests and backup -----------------------------------------

def _sha(path: Path) -> str:
    if not path.exists():
        return "-"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stat(p: Path):
    try:
        s = p.stat()
    except OSError:
        return None
    return (s.st_size, s.st_mtime_ns)


@contextlib.contextmanager
def snapshot(db_path: Path):
    """A connection on a byte copy of db_path and its -wal (no -shm: the copy
    rebuilds its WAL index from the -wal on open) in a temporary directory.
    The live files are only READ, and the copy is retaken while either one's
    size or mtime moved under it, so the pair is consistent."""
    db_path = Path(db_path)
    if not db_path.exists():
        raise SystemExit(f"no database at {db_path}")
    wal = Path(str(db_path) + "-wal")
    with tempfile.TemporaryDirectory(prefix="tft-n8-snap-") as td:
        copy = Path(td) / "match_history.db"
        for _ in range(_SNAPSHOT_TRIES):
            before = (_stat(db_path), _stat(wal))
            for p in (copy, Path(str(copy) + "-wal"), Path(str(copy) + "-shm")):
                p.unlink(missing_ok=True)
            shutil.copyfile(db_path, copy)
            if before[1] is not None:
                shutil.copyfile(wal, Path(str(copy) + "-wal"))
            if (_stat(db_path), _stat(wal)) == before:
                break
        else:
            raise SystemExit(f"{db_path.name} kept changing while it was copied; "
                             "stop the writer and re-run")
        c = sqlite3.connect(str(copy))
        c.row_factory = sqlite3.Row
        try:
            yield c
        finally:
            c.close()


def digest(db_path: Path) -> dict:
    """File digests (db, -wal) plus a logical digest of the rows, so a change
    can be attributed: per-mode counts and a hash over every TFT row. Reads a
    snapshot (never opens the live file)."""
    out = {"files": {s or "db": _sha(Path(str(db_path) + s)) for s in ("", "-wal")}}
    with snapshot(db_path) as c:
        out["by_mode"] = {r[0]: r[1] for r in c.execute(
            "SELECT mode, COUNT(*) FROM matches GROUP BY mode ORDER BY mode")}
        h = hashlib.sha256()
        n = 0
        for r in c.execute("SELECT * FROM matches WHERE mode = 'TFT' ORDER BY id"):
            h.update(json.dumps(dict(r), sort_keys=True, default=str).encode("utf-8"))
            n += 1
        out["tft_rows"] = n
        out["tft_rows_sha256"] = h.hexdigest()
        out["tables"] = [r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        if QUARANTINE_TABLE in out["tables"]:
            out["quarantined"] = c.execute(
                f"SELECT COUNT(*) FROM {QUARANTINE_TABLE}").fetchone()[0]
    return out


def backup(root: Path, stamp: str) -> Path:
    """Copy everything --apply may change into a new gitignored directory and
    re-read the copy; raises SystemExit (before any write) when it does not
    match. Called while the apply HOLDS the write lock with nothing written
    yet: this second connection only reads (a reader is never blocked by the
    lock, and the backup API cannot read through the lock-holding connection
    itself), and no other writer can commit until the apply does - so the
    copy is exactly the state the writes start from."""
    data = root / "data"
    dest = root / BACKUP_DIR / f"tft-n8-{stamp}"
    dest.mkdir(parents=True, exist_ok=False)
    src = sqlite3.connect(str(data / "match_history.db"))
    dst = sqlite3.connect(str(dest / "match_history.db"))
    try:
        src.execute("PRAGMA busy_timeout = 5000")
        src.backup(dst)
        n_src = src.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
    finally:
        dst.close()
        src.close()
    chk = sqlite3.connect(str(dest / "match_history.db"))
    try:
        n_bak = chk.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
    finally:
        chk.close()
    if n_bak != n_src:
        raise SystemExit(f"refused: backup holds {n_bak} rows, source {n_src}")
    files = {"match_history.db": _sha(dest / "match_history.db")}
    for rel in (Path("ratings") / "last_tft.json", Path("placement_heatmap.json")):
        p = data / rel
        if p.exists():
            shutil.copy2(p, dest / p.name)
            if _sha(dest / p.name) != _sha(p):
                raise SystemExit(f"refused: backup copy of {p.name} does not match")
            files[p.name] = _sha(p)
    manifest = {"created": datetime.now().isoformat(timespec="seconds"),
                "matches_rows": n_src, "files": files}
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    return dest


# -- plan -------------------------------------------------------------------------

def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def game_end_rows(conn, qa: list[dict]) -> tuple[dict[int, int], dict[int, int]]:
    """({row id: game id} to stamp, {row id: game id} superseded) for the
    game-id-less TFT rows written in a QA game's window - one TFT game runs at
    a time, so such a row is that game's game-end rating. The newest one is
    stamped and corrected in place; the rest are superseded writes of the same
    game, and so is every one of them when the game already has a row with its
    own id (the fixed collector rated it before this ran)."""
    stamps: dict[int, int] = {}
    superseded: dict[int, int] = {}
    for m in qa:
        lo = _ts(m["start"] or (m["end"] - timedelta(hours=2)))
        hi = _ts(m["end"] + _END_WINDOW)
        ids = [r[0] for r in conn.execute(
            "SELECT id FROM matches WHERE mode = 'TFT' AND game_id = 0 "
            "AND timestamp >= ? AND timestamp <= ? ORDER BY id", (lo, hi))
            if r[0] not in stamps and r[0] not in superseded]
        if not ids:
            continue
        has_own = conn.execute("SELECT 1 FROM matches WHERE mode = 'TFT' AND game_id = ?",
                               (m["game_id"],)).fetchone()
        if not has_own:
            stamps[ids.pop()] = m["game_id"]
        for i in ids:
            superseded[i] = m["game_id"]
    return stamps, superseded


def junk_rows(conn, cutoff: datetime, exclude) -> dict[str, list[int]]:
    """{class: [ids]} of the junk signatures, game-id-less TFT rows written
    before the first recorded game."""
    out = {}
    taken = set(exclude)
    for cls, where in _CLASS_SQL.items():
        ids = [r[0] for r in conn.execute(
            f"SELECT id FROM matches WHERE mode = 'TFT' AND game_id = 0 AND timestamp < ? "
            f"AND ({where}) ORDER BY id", (_ts(cutoff),)) if r[0] not in taken]
        taken.update(ids)
        out[cls] = ids
    return out


def _epoch(ts: str):
    try:
        return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").timestamp()
    except (TypeError, ValueError):
        return None


def duplicate_rows(conn, cutoff: datetime, exclude) -> dict[int, int]:
    """{duplicate id: kept id}: a game-id-less TFT row before the cutoff that
    repeats an earlier row's comp, grade, placement, level, stage, units and
    (non-zero, float) game length within _DUP_WINDOW_S seconds."""
    taken = set(exclude)
    groups: dict[tuple, list] = {}
    for r in conn.execute(
            "SELECT * FROM matches WHERE mode = 'TFT' AND game_id = 0 AND timestamp < ? "
            "AND game_time_s > 0 ORDER BY id", (_ts(cutoff),)):
        if r["id"] in taken:
            continue
        groups.setdefault(tuple(r[k] for k in _DUP_KEY), []).append(r)
    out = {}
    for rows in groups.values():
        keep = rows[0]
        for r in rows[1:]:
            a, b = _epoch(keep["timestamp"]), _epoch(r["timestamp"])
            if a is not None and b is not None and abs(b - a) <= _DUP_WINDOW_S:
                out[r["id"]] = keep["id"]
            else:
                keep = r
    return out


def db_plan(conn, qa: list[dict], cutoff: datetime) -> dict:
    """The row-level plan on one connection: stamps, superseded, junk,
    duplicates, and the moves {id: reason} they quarantine. Run on the
    snapshot for the printed plan, and again on the live file inside the
    apply's write transaction."""
    stamps, superseded = game_end_rows(conn, qa)
    claimed = set(stamps) | set(superseded)
    junk = junk_rows(conn, cutoff, claimed)
    junk_ids = {i for ids in junk.values() for i in ids}
    dups = duplicate_rows(conn, cutoff, junk_ids | claimed)
    moves = {i: REASON_JUNK.format(cls=cls) for cls, ids in junk.items() for i in ids}
    moves.update({i: REASON_DUP.format(keep=k) for i, k in dups.items()})
    moves.update({i: REASON_SUPERSEDED.format(gid=g) for i, g in superseded.items()})
    return {"stamps": stamps, "superseded": superseded, "junk": junk, "junk_ids": junk_ids,
            "dups": dups, "moves": moves, "claimed": claimed}


def store_actions(qa: list[dict], store: Path) -> list[dict]:
    """The EOG records to add for QA games the store does not hold."""
    acts = []
    for m in qa:
        if tp.has_record(m["game_id"], tp.SOURCE_EOG, store_dir=store):
            continue
        raw_path = m["dir"] / "eog_raw.json"
        try:
            doc = json.loads(raw_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            acts.append({"game_id": m["game_id"], "error": f"{raw_path.name}: {exc}"})
            continue
        rec = tp.parse_eog(doc, now=m["end_unix"])
        if rec is None or rec["game_id"] != m["game_id"]:
            acts.append({"game_id": m["game_id"], "error": "eog_raw.json is not this game"})
            continue
        if m.get("placement") and rec["local_placement"] != m["placement"]:
            acts.append({"game_id": m["game_id"],
                         "error": f"placement {rec['local_placement']} != QA {m['placement']}"})
            continue
        acts.append({"game_id": m["game_id"], "record": rec})
    return acts


def _norm(col, v):
    if col in _JSON_COLS and isinstance(v, (list, dict)):
        v = json.dumps(v)
    if col in NUMERIC_COLS:
        return coerce_numeric(col, v)
    return "" if v is None else v


def _row_matches(db_row, plan_row: dict) -> bool:
    keys = db_row.keys()
    for k, v in plan_row.items():
        if k in _SKIP_COMPARE or k not in keys:
            continue
        if _norm(k, v) != _norm(k, db_row[k]):
            return False
    return True


def rating_plan(conn, root: Path, qa: list[dict], store: Path, acts: list[dict],
                stamps: dict[int, int]) -> tuple[dict, object, dict]:
    """({game id: insert | update | ok | no_record}, last_tft game id or None,
    {game id: plan}) - computed on a TEMPORARY copy of the store with the
    planned EOG records added, so nothing under root is written."""
    stamped = {gid: rid for rid, gid in stamps.items()}
    actions, plans = {}, {}
    with tempfile.TemporaryDirectory(prefix="tft-n8-plan-") as td:
        tstore = Path(td) / "tft_matches"
        if store.is_dir():
            shutil.copytree(store, tstore)
        else:
            tstore.mkdir()
        for a in acts:
            if "record" in a:
                tp.persist(a["record"], store_dir=tstore)
        for m in qa:
            gid = m["game_id"]
            plan_ = pt.plan_tft_rating(root, gid, store_dir=tstore)
            plans[gid] = plan_
            if plan_ is None:
                actions[gid] = "no_record"
                continue
            if gid in stamped:
                actions[gid] = "update"
                continue
            row = conn.execute("SELECT * FROM matches WHERE mode = 'TFT' AND game_id = ? "
                               "ORDER BY id DESC LIMIT 1", (gid,)).fetchone()
            if row is None:
                actions[gid] = "insert"
            else:
                actions[gid] = "ok" if _row_matches(row, plan_["row"]) else "update"
    last_gid = None
    newest = [m["game_id"] for m in qa if plans.get(m["game_id"])]
    if newest:
        p = plans[newest[-1]]
        if p["newest"]:
            cur = _last_tft(root)
            if any(cur.get(k) != p["data"].get(k) for k in _LAST_KEYS):
                last_gid = p["game_id"]
    return actions, last_gid, plans


def _last_tft(root: Path) -> dict:
    try:
        cur = json.loads((root / "data" / "ratings" / "last_tft.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return cur if isinstance(cur, dict) else {}


def plan(root: Path, qa: list[dict]) -> dict:
    """Everything --apply would do, from a snapshot (read-only)."""
    store = root / "data" / "tft_matches"
    cutoff = min((m["start"] or m["end"]) for m in qa)
    acts = store_actions(qa, store)
    with snapshot(root / "data" / "match_history.db") as c:
        d = db_plan(c, qa, cutoff)
        actions, last_gid, plans = rating_plan(c, root, qa, store, acts, d["stamps"])
        tft_rows = c.execute("SELECT COUNT(*) FROM matches WHERE mode='TFT'").fetchone()[0]
        unmatched = [dict(r) for r in c.execute(
            "SELECT id, timestamp, grade, tft_placement, tft_comp FROM matches "
            "WHERE mode = 'TFT' AND game_id = 0 AND timestamp >= ? ORDER BY id",
            (_ts(cutoff),)) if r["id"] not in d["claimed"]]
    n_q = len(d["moves"])
    return {
        "cutoff": _ts(cutoff),
        "qa_games": [m["game_id"] for m in qa],
        "tft_rows": tft_rows,
        "junk_rows": len(d["junk_ids"]),
        "junk_by_class": {k: len(v) for k, v in d["junk"].items()},
        "junk_id_range": [min(d["junk_ids"]), max(d["junk_ids"])] if d["junk_ids"] else [],
        "dup_rows": len(d["dups"]),
        "dup_pairs": d["dups"],
        "superseded_rows": d["superseded"],
        "quarantine_rows": n_q,
        "stamp_rows": d["stamps"],
        "unmatched_rows": unmatched,
        "kept_tft_rows": tft_rows - n_q - len(d["stamps"]),
        "store_add": [a["game_id"] for a in acts if "record" in a],
        "store_errors": [a for a in acts if "error" in a],
        "rating_plan": actions,
        "last_tft_plan": last_gid,
        "_moves": d["moves"],
        "_acts": acts,
        "_plans": plans,
        "_cutoff": cutoff,
    }


def _summary(p: dict) -> dict:
    ra = p["rating_plan"]
    return {
        "tft_rows": p["tft_rows"],
        "fix_in_place": len(p["stamp_rows"]),
        "insert": sum(1 for v in ra.values() if v == "insert"),
        "rerate_existing": sum(1 for g, v in ra.items() if v == "update"
                               and g not in p["stamp_rows"].values()),
        "quarantine": {"junk": p["junk_by_class"], "duplicates": p["dup_rows"],
                       "superseded_game_end": len(p["superseded_rows"]),
                       "total": p["quarantine_rows"]},
        "keep": p["kept_tft_rows"],
        "unmatched_kept": len(p["unmatched_rows"]),
        "store_add": p["store_add"],
        "last_tft_rewrite_to": p["last_tft_plan"],
    }


# -- apply ------------------------------------------------------------------------

def quarantine(conn, moves: dict[int, str], now: str) -> int:
    """Move rows {id: reason} into QUARANTINE_TABLE (same columns + reason /
    time), in the caller's transaction. Returns rows moved."""
    if not moves:
        return 0
    cols = [r[1] for r in conn.execute("PRAGMA table_info(matches)")]
    have = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                        (QUARANTINE_TABLE,)).fetchone()
    if not have:
        conn.execute(f"CREATE TABLE {QUARANTINE_TABLE} AS SELECT * FROM matches WHERE 0")
        conn.execute(f"ALTER TABLE {QUARANTINE_TABLE} ADD COLUMN quarantine_reason TEXT")
        conn.execute(f"ALTER TABLE {QUARANTINE_TABLE} ADD COLUMN quarantined_at TEXT")
    col_sql = ", ".join(cols)
    conn.execute("CREATE TEMP TABLE _n8_moves (id INTEGER PRIMARY KEY, reason TEXT)")
    conn.executemany("INSERT INTO _n8_moves (id, reason) VALUES (?, ?)", list(moves.items()))
    moved = conn.execute(
        f"INSERT INTO {QUARANTINE_TABLE} ({col_sql}, quarantine_reason, quarantined_at) "
        f"SELECT {', '.join('m.' + c for c in cols)}, q.reason, ? "
        f"FROM matches m JOIN _n8_moves q ON q.id = m.id", (now,)).rowcount
    deleted = conn.execute(
        "DELETE FROM matches WHERE id IN (SELECT id FROM _n8_moves)").rowcount
    conn.execute("DROP TABLE _n8_moves")
    if moved != len(moves) or deleted != len(moves):
        raise RuntimeError(f"quarantine mismatch: ids {len(moves)} moved {moved} "
                           f"deleted {deleted}")
    return moved


def _heatmap_under(root: Path):
    """update_heatmap bound to THIS root (the module's defaults are its own
    checkout's data/, which is not the root being repaired)."""
    def _update():
        from tft import placement_aggregator as pa
        heat = pa.build_heatmap(root / "data" / "ratings")
        atomic_write_json(root / "data" / "placement_heatmap.json", heat)
        return heat.get("games_counted", 0)
    return _update


def read_back(root: Path, qa: list[dict]) -> dict:
    with snapshot(root / "data" / "match_history.db") as c:
        games = {}
        for m in qa:
            games[m["game_id"]] = [
                {k: r[k] for k in ("id", "timestamp", "grade", "tft_placement", "tft_level",
                                   "tft_stage", "tft_comp", "game_id")}
                for r in c.execute("SELECT * FROM matches WHERE mode='TFT' AND game_id=?",
                                   (m["game_id"],))]
        tft_total = c.execute("SELECT COUNT(*) FROM matches WHERE mode='TFT'").fetchone()[0]
        zero = c.execute("SELECT COUNT(*) FROM matches WHERE mode='TFT' AND game_id=0").fetchone()[0]
    last = _last_tft(root)
    return {"games": games, "tft_rows": tft_total, "tft_rows_game_id_0": zero,
            "last_tft": {k: last.get(k) for k in _LAST_KEYS + ("timestamp",)}}


def verify(root: Path, qa: list[dict], p: dict, plans: dict, rb: dict) -> list[str]:
    """What the read-back says is still wrong ([] = repaired)."""
    bad = []
    for m in qa:
        gid = m["game_id"]
        rows = rb["games"].get(gid) or []
        want = plans.get(gid)
        if len(rows) != 1:
            bad.append(f"game {gid}: {len(rows)} rows, want 1")
        elif want and (rows[0]["grade"], rows[0]["tft_placement"]) != (
                want["grade"], want["row"]["tft_placement"]):
            bad.append(f"game {gid}: row {rows[0]['grade']} / {rows[0]['tft_placement']}, "
                       f"want {want['grade']} / {want['row']['tft_placement']}")
    if p["last_tft_plan"] and rb["last_tft"].get("tft_game_id") != p["last_tft_plan"]:
        bad.append(f"last_tft.json names game {rb['last_tft'].get('tft_game_id')}, "
                   f"want {p['last_tft_plan']}")
    with snapshot(root / "data" / "match_history.db") as c:
        left = db_plan(c, qa, p["_cutoff"])
    if left["moves"] or left["stamps"]:
        bad.append(f"still to repair: {len(left['moves'])} to quarantine, "
                   f"{len(left['stamps'])} to stamp")
    return bad


@contextlib.contextmanager
def _logfile(root: Path):
    """Every log record of the apply (this script, performance_tracker,
    MatchDB) also goes to <root>/logs/repair_tft_match_rows.log."""
    (root / "logs").mkdir(parents=True, exist_ok=True)
    h = logging.FileHandler(root / "logs" / LOG_NAME, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    h.setLevel(logging.INFO)
    lg = logging.getLogger()
    old = lg.level
    lg.addHandler(h)
    if lg.level > logging.INFO or lg.level == logging.NOTSET:
        lg.setLevel(logging.INFO)
    try:
        yield
    finally:
        lg.removeHandler(h)
        lg.setLevel(old)
        h.close()


def _fail(msg: str):
    _log.error(msg)
    raise SystemExit(msg)


def _write(root: Path, qa: list[dict], p: dict, moves: dict, report: dict) -> None:
    """The write transaction: re-plan on the live file under the write lock,
    refuse on any change, back up, quarantine, stamp, commit."""
    db_path = root / "data" / "match_history.db"
    if _BEFORE_WRITE_LOCK is not None:
        _BEFORE_WRITE_LOCK()
    c = sqlite3.connect(str(db_path))
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA busy_timeout = 5000")
        c.execute("BEGIN IMMEDIATE")
        try:
            live = db_plan(c, qa, p["_cutoff"])
            if live["moves"] != moves or live["stamps"] != p["stamp_rows"]:
                c.rollback()
                _fail("refused: the database changed since the plan (now "
                      f"{len(live['moves'])} to quarantine, {len(live['stamps'])} to stamp; "
                      f"planned {len(moves)} / {len(p['stamp_rows'])}) - a writer is active; "
                      "nothing was written, re-run the dry run")
            report["backup"] = str(backup(root, datetime.now().strftime("%Y%m%d-%H%M%S")))
            _log.info("backup: %s", report["backup"])
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            report["quarantined"] = quarantine(c, moves, now)
            for rid, gid in p["stamp_rows"].items():
                n = c.execute("UPDATE matches SET game_id = ? WHERE id = ? AND game_id = 0",
                              (gid, rid)).rowcount
                if n != 1:
                    raise RuntimeError(f"stamp of row {rid} matched {n} rows")
            c.commit()
            _log.info("committed: %d quarantined, %d stamped", report["quarantined"],
                      len(p["stamp_rows"]))
        except BaseException:
            if c.in_transaction:
                c.rollback()
            raise
    finally:
        c.close()


def run(root: Path, qa_path: Path, *, apply: bool = False, expect_quarantine=None,
        skip_live_check: bool = False, allow_rc_running: bool = False, out=print) -> dict:
    root = Path(root)
    db_path = root / "data" / "match_history.db"
    store = root / "data" / "tft_matches"
    qa = load_qa_matches(qa_path)
    if not qa:
        raise SystemExit("no QA matches with a game id")
    report = {"before": digest(db_path)}
    p = plan(root, qa)
    moves, acts, plans = p.pop("_moves"), p.pop("_acts"), p.pop("_plans")
    report.update({k: v for k, v in p.items() if k != "_cutoff"})
    nothing = (not moves and not p["stamp_rows"] and not p["store_add"]
               and p["last_tft_plan"] is None
               and all(v == "ok" for v in p["rating_plan"].values()))
    report["nothing_to_do"] = nothing
    out(json.dumps({"summary": _summary(p)}, default=str))
    out(json.dumps({k: v for k, v in report.items()
                    if k not in ("dup_pairs", "before", "nothing_to_do")}, default=str))
    if not apply:
        out("DRY RUN - nothing written. Apply with: --apply --expect-quarantine "
            f"{p['quarantine_rows']}")
        return report
    if p["store_errors"]:
        raise SystemExit(f"refused: store inputs unusable: {p['store_errors']}")
    if any(v == "no_record" for v in p["rating_plan"].values()):
        raise SystemExit(f"refused: a QA game has no store record: {p['rating_plan']}")
    if expect_quarantine is None or int(expect_quarantine) != p["quarantine_rows"]:
        raise SystemExit(f"refused: measured {p['quarantine_rows']} rows to quarantine, "
                         f"--expect-quarantine {expect_quarantine}")
    if nothing:
        out("nothing to do - already repaired; nothing written")
        return report
    if not skip_live_check:
        why = live_game_reason(root)
        if why:
            raise SystemExit(f"refused: {why}")
        if not allow_rc_running:
            why = rc_running_reason(root)
            if why:
                raise SystemExit(
                    f"refused: {why} - stop RC and pause the RC-Supervisor scheduled task "
                    "first (the supervisor restarts RC within about 5 s), then re-run; or "
                    "pass --allow-rc-running to apply beside a running RC.")
    with _logfile(root):
        _log.info("apply: root %s, %d to quarantine, %d to stamp, games %s", root,
                  len(moves), len(p["stamp_rows"]), p["qa_games"])
        _write(root, qa, p, moves, report)
        out(f"backup: {report['backup']}")
        for a in acts:
            if "record" in a and tp.persist(a["record"], store_dir=store):
                _log.info("store: game %s eog record added", a["game_id"])
                out(f"store: game {a['game_id']} eog record added")
        import tft.placement_aggregator as pa
        real_update = pa.update_heatmap
        pa.update_heatmap = _heatmap_under(root)
        rated = {}
        try:
            for m in qa:
                gid = m["game_id"]
                if p["rating_plan"].get(gid) == "ok" and gid != p["last_tft_plan"]:
                    continue
                try:
                    rated[gid] = pt.rate_tft_game(root, gid, store_dir=store)[0]
                except Exception as exc:  # noqa: BLE001 - recorded, then the read-back fails
                    _log.error("rating of game %s failed: %s", gid, exc)
                    rated[gid] = ""
        finally:
            pa.update_heatmap = real_update
        report["rated"] = rated
        report["after"] = digest(db_path)
        report["read_back"] = read_back(root, qa)
        out(json.dumps({k: report[k] for k in ("quarantined", "rated", "after", "read_back")},
                       default=str, indent=1))
        bad = verify(root, qa, p, plans, report["read_back"])
        if bad:
            _fail(f"read-back FAILED after the apply (backup {report['backup']}): "
                  + "; ".join(bad))
        _log.info("read-back OK: %s", report["read_back"]["last_tft"])
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, required=True,
                    help="checkout whose data/ is repaired (explicit: never this file's tree)")
    ap.add_argument("--qa-matches", type=Path, required=True)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true",
                      help="plan only, read-only (the default)")
    mode.add_argument("--apply", action="store_true")
    ap.add_argument("--expect-quarantine", type=int, default=None,
                    help="the quarantine count the dry run printed")
    ap.add_argument("--allow-rc-running", action="store_true",
                    help="apply although health.json names a live RC process")
    ap.add_argument("--skip-live-check", action="store_true",
                    help="tests / a copied root only")
    a = ap.parse_args(argv)
    rep = run(a.root, a.qa_matches, apply=a.apply, expect_quarantine=a.expect_quarantine,
              skip_live_check=a.skip_live_check, allow_rc_running=a.allow_rc_running)
    print(json.dumps({"before": rep["before"]}, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
