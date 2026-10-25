"""tft/rounds/ground_truth.py - post-match ground truth for the per-round store
(docs/TFT_PROGRAM.md section 3.4 oracle B, slice TFT-08).

SOURCE. The RM-616 placement store (`tft/tft_placement.py`, gitignored
`data/tft_matches/`) already holds what the LCU says about every finished TFT
game: one append-only file per (game, source), `<gameId>.eog.json` (the
post-game `tft-eog-stats` / game-client EOG block: final boards of all 8,
placement, local HP) and `<gameId>.history.json` (LCU TFT match history:
level, gold left, last round, elimination time, trait tiers). Both are
identity-free by construction. TFT-08 adds NO second LCU collector: this module
reads those files (read API + the documented file layout only) and BRIDGES
them into the section 1.5 tables of the per-round store.

BRIDGE (`sync` / `ingest_game`), idempotent by game id:
  * match row - looked up by `game_id`. A match the live capture already
    opened keeps its own meta, keys and reads; only absent values are filled
    (placement, ended_at) and gt_status is set. A match first seen here gets
    the deterministic match_id "gt-" + 16 hex of HMAC(salt, game id), so a
    re-run (or a concurrent second run) upserts the same row.
  * player rows - one per placement. Ground truth carries no identity, so a
    player the store does not know yet is keyed by
    player_key("tft-gt:<game id>:<placement>", salt): stable per game, joins
    the two sources of one game by placement (the RM-616 merge rule), and a
    later identity-keyed row joins by final_standing. slot 1 = local.
  * gt_board / gt_player - one attach per source: eog -> `lcu_eog`, history
    -> `lcu_mh` (schema.GT_SOURCES). gt_player merges with COALESCE, so the
    history fields land beside the EOG placement.
  * gt_status = 'full' once the history record (level / gold / last round
    for every player) is in, 'partial' with the EOG record only.
  A unit or player value outside the store's bounds is dropped from that ONE
  row before it is written (a bad star never drops a whole board), and a
  record that is not an RM-616 schema-1 record is skipped and counted.
  * accuracy - every match the run added or updated is graded at once
    (tft/rounds/accuracy.py write_final_accuracy, oracle B): a bridge-only
    match has no vision rows, so its fields land with coverage 0.

READS. `final_boards(store, set_id)` is the TFT-08 hand-off to the engine's
comp catalogue (tft/engine/milestones.records_from_store final_boards=): per match,
the local player's final board from the most trusted source present
(GT_SOURCE_ORDER).

BACKFILL (`backfill`, the CLI). `--eog-raw` takes recorder raw tft-eog-stats
documents (ops/runtime/tft_qa/<stamp>/eog_raw.json; a directory means every
eog_raw.json in it and one level below) and fills a MISSING RM-616 EOG record
through RM-616's own parse_eog + append-only persist (captured_at = the raw
file's mtime, the post-game instant the recorder wrote it); an existing
record is never touched. `--dry-run` runs the identical code path against
throwaway copies of both stores (RM-616 files; a byte copy of the db and its
-wal, never opened by SQLite in place) in a temp dir and reports what the
real run would write: the live files are only read, the db's folder stays
byte-identical, and no db, salt or directory is created. Both are idempotent:
a second run reports unchanged / present and writes nothing.

CLI (local backfill; reads the gitignored stores, prints counts, no network):
  python -m tft.rounds.ground_truth [--store-dir DIR] [--db PATH] [--salt PATH]
      [--eog-raw PATH ...] [--dry-run] [--json]

ASCII-only, LLM-free, stdlib only (CLAUDE.md hard rules).
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import logging
import re
import secrets
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable, Optional

import tft.tft_placement as tp
import tft.tft_set as tft_set
from tft.rounds.store import (
    Env,
    RoundStore,
    default_db_path,
    default_salt_path,
    identity_violations,
    load_salt,
    player_key,
)

_log = logging.getLogger(__name__)

# RM-616 source -> gt_board.source (schema.GT_SOURCES): both routes are LCU.
GT_SOURCE_BY_RM616 = {tp.SOURCE_EOG: "lcu_eog", tp.SOURCE_HISTORY: "lcu_mh"}
# Most trusted first, for final boards: EOG display data, then history.
GT_SOURCE_ORDER = ("lcu_eog", "lcu_mh", "match_v1", "eog_file_final")
PLACEMENT_SRC = "lcu"
PLACEMENT_CONF = 1.0
MATCH_ID_PREFIX = "gt-"
STATS_DROPPED = ("invalid", "queue_full", "write_errors", "closed", "unavailable")
RESULTS = ("added", "updated", "unchanged", "skipped")
EOG_RAW_NAME = "eog_raw.json"          # the recorder's raw tft-eog-stats copy
IMPORT_RESULTS = ("imported", "present", "unusable")

# The RM-616 store layout, as documented in the tft/tft_placement.py docstring.
_FILE_RE = re.compile(r"^([1-9][0-9]{0,18})\.(eog|history)\.json$")
_TEXT_MAX = 64
_UNSET = object()


# ---------------------------------------------------------------- RM-616 reads

def _rm616_dir(store_dir) -> Path:
    # RM-616's own default, read at CALL time so the tests/conftest.py redirect
    # of tft_placement._STORE_DIR (RM-406 _PROD_PATH_GLOBALS) applies here too.
    return Path(store_dir) if store_dir is not None else Path(tp._STORE_DIR)


def _int(v) -> Optional[int]:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def game_ids(store_dir=None) -> list:
    """Every game id with at least one RM-616 file, ascending."""
    try:
        names = [e.name for e in _rm616_dir(store_dir).iterdir() if e.is_file()]
    except OSError:
        return []
    return sorted({int(m.group(1)) for m in map(_FILE_RE.match, names) if m})


def source_records(game_id, store_dir=None) -> dict:
    """{RM-616 source: record} for one game: each per-source file that parses
    as an RM-616 schema-1 record of THIS game; anything else is left out."""
    gid = _int(game_id)
    if not gid or gid <= 0:
        return {}
    out = {}
    for src in (tp.SOURCE_EOG, tp.SOURCE_HISTORY):
        path = _rm616_dir(store_dir) / f"{gid}.{src}.json"
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            continue
        except (OSError, ValueError) as exc:
            _log.warning("tft ground truth: unreadable RM-616 %s record (%s)", src, type(exc).__name__)
            continue
        if (isinstance(doc, dict) and doc.get("schema") == tp.SCHEMA_VERSION
                and doc.get("source") == src and _int(doc.get("game_id")) == gid
                and isinstance(doc.get("players"), list) and doc["players"]):
            out[src] = doc
    return out


# ---------------------------------------------------------------- row shaping

def _text(v) -> Optional[str]:
    """A game-data string the store will take (1-64 chars, no identity shape)."""
    if not isinstance(v, str) or not 0 < len(v) <= _TEXT_MAX:
        return None
    return v if not identity_violations(v) else None


def _bounded(v, lo, hi=None) -> Optional[int]:
    v = _int(v)
    if v is None or v < lo or (hi is not None and v > hi):
        return None
    return v


def _num(v) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def _board_rows(key: str, board) -> list:
    rows = []
    for u in board if isinstance(board, list) else []:
        if not isinstance(u, dict):
            continue
        api = _text(u.get("character_id"))
        if api is None:
            continue
        items = [i for i in (_text(it.get("name_id")) for it in (u.get("items") or [])
                             if isinstance(it, dict)) if i]
        rows.append({"player_key": key, "champion_api": api, "star": _bounded(u.get("star"), 1, 4),
                     "items": items, "cost": _bounded(u.get("cost"), 0, 10)})
    return rows


def _player_row(key: str, p: dict) -> dict:
    return {"player_key": key, "placement": _bounded(p.get("placement"), 1, 8),
            "level": _bounded(p.get("level"), 1, 10), "last_round": _bounded(p.get("last_round"), 0),
            "gold_left": _bounded(p.get("gold_left"), 0), "eliminated_at": _num(p.get("time_eliminated_s"))}


def _placements(players) -> dict:
    """{placement: player} for players with a valid placement held by exactly one player."""
    seen: dict = {}
    for p in players:
        place = _bounded(p.get("placement"), 1, 8) if isinstance(p, dict) else None
        if place is not None:
            seen.setdefault(place, []).append(p)
    return {k: v[0] for k, v in sorted(seen.items()) if len(v) == 1}


def match_id_for(game_id: int, salt: bytes) -> str:
    """The deterministic, non-reversible match_id of a match first seen here."""
    digest = hmac.new(bytes(salt), f"tft-match:{int(game_id)}".encode("ascii"), hashlib.sha256)
    return MATCH_ID_PREFIX + digest.hexdigest()[:16]


def _gt_key(game_id: int, placement: int, salt: bytes) -> str:
    return player_key(f"tft-gt:{int(game_id)}:{int(placement)}", salt)


def _find_match(store: RoundStore, game_id: int) -> Optional[dict]:
    return next((m for m in store.list_matches() if m.get("game_id") == game_id), None)


# ---------------------------------------------------------------- the bridge

def ingest_game(store: RoundStore, game_id, *, store_dir=None, salt: bytes,
                existing: Any = _UNSET) -> str:
    """Bridge one RM-616 game into the store; returns one of RESULTS. Writes
    are enqueued (call store.flush() to wait for them); never raises on bad
    data. `existing` = the store's match row for this game id (sync passes
    it; by default it is looked up)."""
    return _ingest(store, game_id, store_dir=store_dir, salt=salt, existing=existing)[0]


def _ingest(store: RoundStore, game_id, *, store_dir, salt: bytes, existing: Any) -> tuple:
    """ingest_game's body: (result, match_id written or None)."""
    gid = _int(game_id)
    recs = source_records(gid, store_dir) if gid else {}
    merged = tp.merge(recs.get(tp.SOURCE_EOG), recs.get(tp.SOURCE_HISTORY)) if recs else None
    if not merged:
        return "skipped", None
    by_place = _placements(merged.get("players") or [])
    if not by_place:
        return "skipped", None
    if existing is _UNSET:
        existing = _find_match(store, gid)
    wanted = sorted(GT_SOURCE_BY_RM616[s] for s in recs)
    full = tp.SOURCE_HISTORY in recs and len(by_place) == len(merged["players"])
    status = "full" if full else "partial"
    if existing and set(existing.get("gt_sources") or []) >= set(wanted) \
            and existing.get("gt_status") == status:
        return "unchanged", None

    owned_mid = match_id_for(gid, salt)
    mid = existing["match_id"] if existing else owned_mid
    owned = mid == owned_mid
    ended = _num(merged.get("ended_at_effective_unix"))
    length = _int(merged.get("game_length_s"))
    local = next((p for p in by_place.values() if p.get("is_local") is True), None)
    local_place = _bounded(local.get("placement"), 1, 8) if local else None

    if owned:
        set_core = _text(merged.get("set_core_name"))
        set_id = _int(merged.get("set_number")) or tft_set.parse_set_id(set_core)
        store.begin_match({
            "match_id": mid, "game_id": gid, "set_id": set_id, "set_core_name": set_core,
            "queue_id": _bounded(merged.get("queue_id"), 0),
            "started_at": ended - length if ended is not None and length else ended})

    # player keys: the store's own keys first (local flag, then final standing)
    known = []
    if existing:
        doc = store.get_match(mid, rounds=False) or {}
        known = [p for p in doc.get("players") or [] if isinstance(p, dict)]
    known_local = next((p["player_key"] for p in known if p.get("is_local")), None)
    by_standing = {p["final_standing"]: p for p in known if _int(p.get("final_standing"))}
    keys: dict = {}
    used: set = set()
    for place, p in by_place.items():
        key = None
        if p.get("is_local") is True and known_local:
            key = known_local
        elif place in by_standing and by_standing[place]["player_key"] != known_local:
            key = by_standing[place]["player_key"]
        if key is None or key in used:
            key = _gt_key(gid, place, salt)
        keys[place] = key
        used.add(key)

    known_rows = {p["player_key"]: p for p in known}
    order = sorted(by_place, key=lambda pl: (by_place[pl] is not local, pl))
    for slot, place in enumerate(order, start=1):
        key, p = keys[place], by_place[place]
        standing = Env(place, PLACEMENT_CONF, PLACEMENT_SRC)
        row = known_rows.get(key)
        if row is None:
            fields = {"is_local": p.get("is_local") is True, "final_standing": standing}
            if owned:
                fields["slot"] = slot
            store.upsert_player(mid, key, **fields)
        elif row.get("final_standing") is None:
            store.upsert_player(mid, key, final_standing=standing)

    for src in sorted(recs):
        rec_places = _placements(recs[src].get("players") or [])
        boards, players = [], []
        for place, p in rec_places.items():
            key = keys.get(place)
            if key is None:
                continue
            boards.extend(_board_rows(key, p.get("board")))
            players.append(_player_row(key, p))
        store.attach_ground_truth(mid, GT_SOURCE_BY_RM616[src], boards, players)

    placement = Env(local_place, PLACEMENT_CONF, PLACEMENT_SRC) if local_place else None
    if owned:
        store.end_match(mid, placement, ended_at=ended, gt_status=status)
    else:
        keep_placement = existing.get("placement_src") not in (None, "absent")
        store.end_match(mid, None if keep_placement else placement,
                        ended_at=existing.get("ended_at") if existing.get("ended_at") is not None else ended,
                        gt_status=status)
    return ("updated" if existing else "added"), mid


def sync(store: RoundStore, *, store_dir=None, salt: Optional[bytes] = None) -> dict:
    """Bridge every RM-616 game into the store, grade every match it added
    or updated (oracle B accuracy rows), and wait for the writes. Returns
    {"games", "added", "updated", "unchanged", "skipped", "accuracy_rows",
    "dropped"} (+ "error" when the store is not available); never raises."""
    from tft.rounds import accuracy as gacc     # accuracy imports this module

    counts = dict.fromkeys(("games", *RESULTS, "accuracy_rows", "dropped"), 0)
    if not store.ok:
        counts["error"] = store.error or "store not available"
        return counts
    salt = load_salt() if salt is None else salt
    before = store.stats()
    ids = game_ids(store_dir)
    counts["games"] = len(ids)
    by_gid: dict = {}
    for m in store.list_matches():
        if _int(m.get("game_id")):
            by_gid.setdefault(m["game_id"], m)
    touched = []
    for gid in ids:
        try:
            result, mid = _ingest(store, gid, store_dir=store_dir, salt=salt,
                                  existing=by_gid.get(gid))
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            _log.warning("tft ground truth: game skipped (%s)", type(exc).__name__)
            result, mid = "skipped", None
        counts[result] += 1
        if mid is not None:
            touched.append(mid)
    store.flush()
    if touched:
        versions = {m["match_id"]: m.get("extractor_version") or "" for m in store.list_matches()}
        for mid in touched:
            try:
                rows = gacc.write_final_accuracy(store, mid, extractor_version=versions.get(mid, ""))
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                _log.warning("tft ground truth: accuracy skipped (%s)", type(exc).__name__)
                rows = []
            counts["accuracy_rows"] += len(rows)
        store.flush()
    after = store.stats()
    counts["dropped"] = sum(after[k] - before[k] for k in STATS_DROPPED)
    return counts


# ---------------------------------------------------------------- backfill

def _eog_raw_files(paths: Iterable) -> list:
    """The raw EoG files named by `paths` (a file, or a directory: its own
    eog_raw.json and every one a level below), de-duplicated, in order."""
    out, seen = [], set()
    for p in paths or ():
        p = Path(p)
        found = ([p] if p.is_file() else
                 [*sorted(p.glob(EOG_RAW_NAME)), *sorted(p.glob(f"*/{EOG_RAW_NAME}"))] if p.is_dir() else [])
        for f in found:
            key = str(f.resolve())
            if key not in seen:
                seen.add(key)
                out.append(f)
    return out


def import_eog_raw(paths: Iterable, *, store_dir=None) -> dict:
    """Fill MISSING RM-616 EOG records from recorder raw tft-eog-stats
    documents: RM-616's own parse_eog (identity-free by construction) and
    append-only persist, captured_at = the raw file's mtime. Returns
    {"files", "imported", "present", "unusable"}; never raises."""
    counts = dict.fromkeys(("files", *IMPORT_RESULTS), 0)
    for f in _eog_raw_files(paths):
        counts["files"] += 1
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
            rec = tp.parse_eog(doc, now=f.stat().st_mtime) if tp.is_tft_doc(doc) else None
        except (OSError, ValueError) as exc:
            _log.warning("tft ground truth: unreadable raw EoG (%s)", type(exc).__name__)
            rec = None
        if not rec:
            counts["unusable"] += 1
        elif tp.has_record(rec["game_id"], tp.SOURCE_EOG, store_dir=_rm616_dir(store_dir)):
            counts["present"] += 1
        else:
            try:
                ok = tp.persist(rec, store_dir=_rm616_dir(store_dir))
            except OSError as exc:
                _log.warning("tft ground truth: RM-616 EOG record not written (%s)", type(exc).__name__)
                ok = False
            counts["imported" if ok else "unusable"] += 1
    return counts


def _read_salt(path: Path) -> Optional[bytes]:
    """The install salt when it already exists (load_salt's rule), else None;
    never creates it."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    return data if len(data) >= 16 else None


def _copy_db(src: Path, dst: Path) -> None:
    """Byte copy of a store (the db file, then its -wal when present) for a
    dry run. The source is never OPENED by SQLite: even a mode=ro open of a
    WAL db creates -shm / -wal files beside it and leaves them. The -shm
    wal-index is not copied - SQLite rebuilds it from the copied -wal, so
    uncheckpointed rows reach the copy. A writer mid-transaction can make the
    snapshot (the prediction) stale; it can never change the source."""
    shutil.copyfile(src, dst)
    wal = src.with_name(src.name + "-wal")
    if wal.is_file():
        shutil.copyfile(wal, dst.with_name(dst.name + "-wal"))


def _run(db_path: Path, store_dir, eog_raw, salt: bytes) -> dict:
    imports = import_eog_raw(eog_raw, store_dir=store_dir)
    store = RoundStore.open(db_path)
    try:
        counts = sync(store, store_dir=store_dir, salt=salt)
        totals = store_counts(store) if store.ok else {}
    finally:
        store.close()
    return {"eog_raw": imports, "sync": counts, "store": totals}


def backfill(*, db_path=None, store_dir=None, eog_raw: Iterable = (), salt_path=None,
             dry_run: bool = False) -> dict:
    """Import missing RM-616 EOG records (eog_raw), bridge every RM-616 game
    into the round store and grade it. dry_run: the same run on throwaway
    copies of both stores - the live files are only read. Returns
    {"dry_run", "eog_raw", "sync", "store"}."""
    db = Path(db_path) if db_path is not None else default_db_path()
    salt_file = Path(salt_path) if salt_path is not None else default_salt_path()
    eog_raw = list(eog_raw or ())
    if not dry_run:
        out = _run(db, store_dir, eog_raw, load_salt(salt_file))
        return {"dry_run": False, **out}
    with tempfile.TemporaryDirectory(prefix="tft_gt_dry_", ignore_cleanup_errors=True) as tmp:
        tmp_store = Path(tmp) / "tft_matches"
        tmp_store.mkdir()
        src_dir = _rm616_dir(store_dir)
        try:
            entries = [e for e in src_dir.iterdir() if e.is_file() and _FILE_RE.match(e.name)]
        except OSError:
            entries = []
        for e in entries:
            shutil.copyfile(e, tmp_store / e.name)
        tmp_db = Path(tmp) / "tft_rounds.db"
        if db.is_file():
            _copy_db(db, tmp_db)
        salt = _read_salt(salt_file) or secrets.token_bytes(32)
        out = _run(tmp_db, tmp_store, eog_raw, salt)
    return {"dry_run": True, **out}


# ---------------------------------------------------------------- reads

def final_boards(store: RoundStore, set_id=None) -> dict:
    """{match_id: [unit rows]} - each match's LOCAL final board, from the most
    trusted ground-truth source present (GT_SOURCE_ORDER). Unit rows carry
    champion_api, star, items (api names), cost and source."""
    out = {}
    for m in store.list_matches(set_id=set_id):
        doc = store.get_match(m["match_id"], rounds=False)
        if not doc:
            continue
        local = next((p["player_key"] for p in doc["players"] if p.get("is_local")), None)
        if local is None:
            continue
        rows = [r for r in doc["gt_board"] if r.get("player_key") == local]
        for src in GT_SOURCE_ORDER:
            picked = [r for r in rows if r.get("source") == src]
            if picked:
                out[m["match_id"]] = [{k: r.get(k) for k in ("champion_api", "star", "items", "cost", "source")}
                                      for r in picked]
                break
    return out


def store_counts(store: RoundStore) -> dict:
    """Read-back totals: matches, matches with ground truth, gt_board / gt_player rows."""
    totals = {"matches": 0, "with_gt": 0, "full": 0, "gt_board": 0, "gt_player": 0, "players": 0}
    for m in store.list_matches():
        totals["matches"] += 1
        if m.get("gt_sources"):
            totals["with_gt"] += 1
        if m.get("gt_status") == "full":
            totals["full"] += 1
        doc = store.get_match(m["match_id"], rounds=False) or {}
        totals["gt_board"] += len(doc.get("gt_board") or [])
        totals["gt_player"] += len(doc.get("gt_player") or [])
        totals["players"] += len(doc.get("players") or [])
    return totals


# ---------------------------------------------------------------- CLI

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Bridge the RM-616 TFT post-game store into the "
                                             "per-round store (TFT-08 ground truth).")
    ap.add_argument("--store-dir", help="RM-616 store (default data/tft_matches)")
    ap.add_argument("--db", help="per-round store (default data/tft/tft_rounds.db)")
    ap.add_argument("--salt", help="install salt file (default data/tft/.salt)")
    ap.add_argument("--eog-raw", action="append", default=[], metavar="PATH",
                    help="recorder raw tft-eog-stats file, or a dir of <stamp>/eog_raw.json "
                         "(fills a missing RM-616 EOG record; repeatable)")
    ap.add_argument("--dry-run", action="store_true",
                    help="run on throwaway copies of both stores; write nothing")
    ap.add_argument("--json", action="store_true", help="print the counts as one JSON line")
    args = ap.parse_args(argv)
    out = backfill(db_path=args.db, store_dir=args.store_dir, eog_raw=args.eog_raw,
                   salt_path=args.salt, dry_run=args.dry_run)
    counts = out["sync"]
    if args.json:
        print(json.dumps(out, sort_keys=True))
    else:
        tag = " (dry run: nothing written)" if out["dry_run"] else ""
        print("rm616 eog import" + tag + ": " + " ".join(f"{k} {v}" for k, v in out["eog_raw"].items()))
        print("tft ground truth" + tag + ": " + " ".join(f"{k} {v}" for k, v in counts.items()))
        print("store read-back" + tag + ": " + " ".join(f"{k} {v}" for k, v in out["store"].items()))
    return 1 if counts.get("error") or counts["dropped"] or out["eog_raw"]["unusable"] else 0


if __name__ == "__main__":
    sys.exit(main())
