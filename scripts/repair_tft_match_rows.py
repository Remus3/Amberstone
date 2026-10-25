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

Junk, duplicates and superseded rows are QUARANTINED, never deleted: moved, ids intact, into
the table matches_quarantine in the same file, with a reason. A QA game the
store never captured gets its EOG record from the QA recorder's own GET of
the same route (<qa dir>/eog_raw.json, parsed and scrubbed by
tft_placement.parse_eog; append-only persist). data/ratings/last_tft.json
ends on the newest game (performance_tracker.rate_tft_game's rule).

Input: the QA recorder's matches.jsonl (one JSON line per match with
game_id, dir, placement, start_iso, end_iso). Nothing identifying is read
into the store (parse_eog keeps no riot id / puuid).

Safety:
  * --dry-run is the default and opens the database READ-ONLY (no WAL
    checkpoint): not one byte of the root changes. It prints the full plan.
  * --apply refuses while a TFT game runs (TFTClient-Win64-Shipping.exe, or
    health.json has_game / tft_mode), unless --expect-quarantine equals the
    measured quarantine count, on unusable store inputs, and when a QA game
    would have no store record to rate from.
  * --apply takes a BACKUP before its first write:
    <root>/ops/runtime/backups/tft-n8-<stamp>/ (gitignored) holds a
    consistent copy of match_history.db (sqlite backup API, WAL content
    included), last_tft.json, placement_heatmap.json and a manifest of
    sha256s; the copy is re-read and row-counted before anything is written.
  * Idempotent: a repaired root plans nothing, and an --apply that plans
    nothing writes nothing (no backup either).

Usage:
    python scripts/repair_tft_match_rows.py --root <checkout> --qa-matches <matches.jsonl> --dry-run
    python scripts/repair_tft_match_rows.py --root <checkout> --qa-matches <matches.jsonl> \\
        --apply --expect-quarantine <n from the dry run>
"""
from __future__ import annotations

import argparse
import hashlib
import json
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
    try:
        h = json.loads((root / "ops" / "runtime" / "health.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        h = {}
    if isinstance(h, dict) and (h.get("has_game") or h.get("tft_mode")):
        return "health.json reports a game in progress"
    return ""


# -- digests and backup ------------------------------------------------------------

def _sha(path: Path) -> str:
    if not path.exists():
        return "-"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ro(db_path: Path) -> sqlite3.Connection:
    """A READ-ONLY connection: it never checkpoints the WAL or writes the
    database or its -wal (a path with spaces is fine: as_uri() quotes it).
    With no -wal on disk every row is in the main file and no connection is
    open in WAL mode, so `immutable` reads it without creating the empty
    -wal / -shm sidecars `mode=ro` would leave behind."""
    p = Path(db_path).resolve()
    if not p.exists():
        raise SystemExit(f"no database at {p}")
    query = "?mode=ro" if Path(str(p) + "-wal").exists() else "?immutable=1"
    c = sqlite3.connect(p.as_uri() + query, uri=True)
    c.row_factory = sqlite3.Row
    return c


def digest(db_path: Path) -> dict:
    """File digests (db, -wal) plus a logical digest of the rows, so a change
    can be attributed: per-mode counts and a hash over every TFT row."""
    out = {"files": {s or "db": _sha(Path(str(db_path) + s)) for s in ("", "-wal")}}
    c = _ro(db_path)
    try:
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
    finally:
        c.close()
    return out


def backup(root: Path, stamp: str) -> Path:
    """Copy everything --apply may change into a new gitignored directory and
    re-read the copy; raises SystemExit (before any write) when it does not
    match. Returns the directory."""
    data = root / "data"
    db_path = data / "match_history.db"
    dest = root / BACKUP_DIR / f"tft-n8-{stamp}"
    dest.mkdir(parents=True, exist_ok=False)
    src = _ro(db_path)
    dst = sqlite3.connect(str(dest / "match_history.db"))
    try:
        src.backup(dst)
        n_src = src.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
    finally:
        dst.close()
        src.close()
    chk = _ro(dest / "match_history.db")
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
            plan = pt.plan_tft_rating(root, gid, store_dir=tstore)
            plans[gid] = plan
            if plan is None:
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
                actions[gid] = "ok" if _row_matches(row, plan["row"]) else "update"
    last_gid = None
    newest = [m["game_id"] for m in qa if plans.get(m["game_id"])]
    if newest:
        p = plans[newest[-1]]
        if p["newest"]:
            try:
                cur = json.loads((root / "data" / "ratings" / "last_tft.json")
                                 .read_text(encoding="utf-8"))
            except (OSError, ValueError):
                cur = {}
            cur = cur if isinstance(cur, dict) else {}
            if any(cur.get(k) != p["data"].get(k) for k in _LAST_KEYS):
                last_gid = p["game_id"]
    return actions, last_gid, plans


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
    c = _ro(root / "data" / "match_history.db")
    try:
        games = {}
        for m in qa:
            games[m["game_id"]] = [
                {k: r[k] for k in ("id", "timestamp", "grade", "tft_placement", "tft_level",
                                   "tft_stage", "tft_comp", "game_id")}
                for r in c.execute("SELECT * FROM matches WHERE mode='TFT' AND game_id=?",
                                   (m["game_id"],))]
        tft_total = c.execute("SELECT COUNT(*) FROM matches WHERE mode='TFT'").fetchone()[0]
        zero = c.execute("SELECT COUNT(*) FROM matches WHERE mode='TFT' AND game_id=0").fetchone()[0]
    finally:
        c.close()
    try:
        last = json.loads((root / "data" / "ratings" / "last_tft.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        last = {}
    return {"games": games, "tft_rows": tft_total, "tft_rows_game_id_0": zero,
            "last_tft": {k: last.get(k) for k in _LAST_KEYS + ("timestamp",)}}


def plan(root: Path, qa: list[dict]) -> dict:
    """Everything --apply would do, read-only."""
    db_path = root / "data" / "match_history.db"
    store = root / "data" / "tft_matches"
    cutoff = min((m["start"] or m["end"]) for m in qa)
    acts = store_actions(qa, store)
    c = _ro(db_path)
    try:
        c.execute("PRAGMA busy_timeout = 5000")
        stamps, superseded = game_end_rows(c, qa)
        claimed = set(stamps) | set(superseded)
        junk = junk_rows(c, cutoff, claimed)
        junk_ids = {i for ids in junk.values() for i in ids}
        dups = duplicate_rows(c, cutoff, junk_ids | claimed)
        actions, last_gid, _plans = rating_plan(c, root, qa, store, acts, stamps)
        tft_rows = c.execute("SELECT COUNT(*) FROM matches WHERE mode='TFT'").fetchone()[0]
        unmatched = [dict(r) for r in c.execute(
            "SELECT id, timestamp, grade, tft_placement, tft_comp FROM matches "
            "WHERE mode = 'TFT' AND game_id = 0 AND timestamp >= ? ORDER BY id",
            (_ts(cutoff),)) if r["id"] not in claimed]
    finally:
        c.close()
    moves = {i: REASON_JUNK.format(cls=cls) for cls, ids in junk.items() for i in ids}
    moves.update({i: REASON_DUP.format(keep=k) for i, k in dups.items()})
    moves.update({i: REASON_SUPERSEDED.format(gid=g) for i, g in superseded.items()})
    n_q = len(moves)
    return {
        "cutoff": _ts(cutoff),
        "qa_games": [m["game_id"] for m in qa],
        "tft_rows": tft_rows,
        "junk_rows": len(junk_ids),
        "junk_by_class": {k: len(v) for k, v in junk.items()},
        "junk_id_range": [min(junk_ids), max(junk_ids)] if junk_ids else [],
        "dup_rows": len(dups),
        "dup_pairs": dups,
        "superseded_rows": superseded,
        "quarantine_rows": n_q,
        "stamp_rows": stamps,
        "unmatched_rows": unmatched,
        "kept_tft_rows": tft_rows - n_q - len(stamps),
        "store_add": [a["game_id"] for a in acts if "record" in a],
        "store_errors": [a for a in acts if "error" in a],
        "rating_plan": actions,
        "last_tft_plan": last_gid,
        "_moves": moves,
        "_acts": acts,
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


def run(root: Path, qa_path: Path, *, apply: bool = False, expect_quarantine=None,
        skip_live_check: bool = False, out=print) -> dict:
    root = Path(root)
    db_path = root / "data" / "match_history.db"
    store = root / "data" / "tft_matches"
    qa = load_qa_matches(qa_path)
    if not qa:
        raise SystemExit("no QA matches with a game id")
    report = {"before": digest(db_path)}
    p = plan(root, qa)
    moves, acts = p.pop("_moves"), p.pop("_acts")
    report.update(p)
    nothing = (not moves and not p["stamp_rows"] and not p["store_add"]
               and p["last_tft_plan"] is None
               and all(v == "ok" for v in p["rating_plan"].values()))
    report["nothing_to_do"] = nothing
    out(json.dumps({"summary": _summary(p)}, default=str))
    out(json.dumps({k: v for k, v in p.items() if k not in ("dup_pairs",)}, default=str))
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
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report["backup"] = str(backup(root, stamp))
    out(f"backup: {report['backup']}")
    for a in acts:
        if "record" in a and tp.persist(a["record"], store_dir=store):
            out(f"store: game {a['game_id']} eog record added")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c = sqlite3.connect(str(db_path))
    try:
        c.execute("PRAGMA busy_timeout = 5000")
        c.execute("BEGIN IMMEDIATE")
        moved = quarantine(c, moves, now)
        for rid, gid in p["stamp_rows"].items():
            c.execute("UPDATE matches SET game_id = ? WHERE id = ? AND game_id = 0", (gid, rid))
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()
    report["quarantined"] = moved
    import tft.placement_aggregator as pa
    real_update = pa.update_heatmap
    pa.update_heatmap = _heatmap_under(root)
    try:
        report["rated"] = {
            m["game_id"]: pt.rate_tft_game(root, m["game_id"], store_dir=store)[0]
            for m in qa
            if p["rating_plan"].get(m["game_id"]) != "ok" or m["game_id"] == p["last_tft_plan"]}
    finally:
        pa.update_heatmap = real_update
    report["after"] = digest(db_path)
    report["read_back"] = read_back(root, qa)
    out(json.dumps({k: report[k] for k in ("quarantined", "rated", "after", "read_back")},
                   default=str, indent=1))
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
    ap.add_argument("--skip-live-check", action="store_true",
                    help="tests / a copied root only")
    a = ap.parse_args(argv)
    rep = run(a.root, a.qa_matches, apply=a.apply, expect_quarantine=a.expect_quarantine,
              skip_live_check=a.skip_live_check)
    print(json.dumps({"before": rep["before"]}, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
