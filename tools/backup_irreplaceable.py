#!/usr/bin/env python
"""RM-135: versioned backup of RC's irreplaceable single-copy DATA, with a
restore path that is actually exercised.

RC's existing backup tooling (ops/rc_supervisor.py, ops/rc_transactional_deploy.py)
is CODE-deployment rollback; it deliberately excludes data. So RC could roll
back a bad deploy and could not recover a lost database. This tool closes that
gap for the data that cannot be re-derived.

CLASSIFICATION FIRST (the row's own ordering - never back up 10 GB of mirror):
  IRREPLACEABLE  every `data/*.db` that is NOT a cache. rewind_history.db is the
                 crown jewel: it accumulates match history, Match-V5 403s on
                 event modes by design, and a known gap is already unrecoverable.
  REGENERABLE    `*cache*.db` (riot_api_cache.db - an HTTP cache), the DDragon /
                 CDragon mirrors and every other mirror under data/.
  OUT OF SCOPE   API-Key-Claude.txt (re-issuable from the console; copying a
                 secret around multiplies its exposure) and ~/.perseus-vault
                 (a MIRROR of tracked docs by CLAUDE.md's own rule - re-sync
                 with tools/perseus_sync.py; also outside the tree).

TARGET: `ops/backups/data/<UTC stamp>/` - inside the repo (no out-of-tree
write), gitignored, and the one directory the deploy rollback already EXCLUDES
(rc_supervisor.py note [12]), so a rollback cannot eat its own backups. It is
the SAME DISK: this protects against a destructive mistake or corruption (the
threat the row names - unattended headless lanes with full authority), not
against disk loss. An off-box copy is an operator decision (bytes leaving the
tree cross RC's halt boundary).

CONSISTENCY: each DB is copied with SQLite's online backup API
(`Connection.backup`), so a live writer cannot tear the copy. A manifest records
size + SHA-256 + row counts per table.

RESTORE IS EXERCISED: `verify` restores every DB of a snapshot into a temp dir
and runs `PRAGMA integrity_check` plus a per-table row-count comparison against
the manifest. An untested backup is the same failure class as an unfired hook.

Usage:
  python tools/backup_irreplaceable.py classify
  python tools/backup_irreplaceable.py backup [--keep N]
  python tools/backup_irreplaceable.py verify [SNAPSHOT_DIR]
  python tools/backup_irreplaceable.py restore SNAPSHOT_DIR NAME DEST   # never over a live file
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
BACKUP_ROOT = ROOT / "ops" / "backups" / "data"
DEFAULT_KEEP = 7


def classify(data_dir: Path = DATA) -> dict[str, list[str]]:
    out = {"irreplaceable": [], "regenerable": []}
    for p in sorted(data_dir.glob("*.db")):
        key = "regenerable" if "cache" in p.name.lower() else "irreplaceable"
        out[key].append(p.name)
    return out


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _table_counts(db: Path) -> dict[str, int]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        names = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {n: int(conn.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0])
                for n in names}
    finally:
        conn.close()


def _online_copy(src: Path, dest: Path) -> None:
    s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    try:
        d = sqlite3.connect(dest)
        try:
            s.backup(d)
        finally:
            d.close()
    finally:
        s.close()


def _write_json_atomic(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes((json.dumps(obj, indent=1, sort_keys=True) + "\n").encode("ascii"))
    tmp.replace(path)


def backup(data_dir: Path = DATA, backup_root: Path = BACKUP_ROOT,
           keep: int = DEFAULT_KEEP, now: float | None = None) -> Path:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(now or time.time()))
    snap = backup_root / stamp
    partial = backup_root / (stamp + ".partial")
    partial.mkdir(parents=True, exist_ok=False)
    manifest = {"created_utc": stamp, "source": str(data_dir), "files": {}}
    for name in classify(data_dir)["irreplaceable"]:
        dest = partial / name
        _online_copy(data_dir / name, dest)
        manifest["files"][name] = {"size": dest.stat().st_size,
                                   "sha256": _sha256(dest),
                                   "tables": _table_counts(dest)}
    _write_json_atomic(partial / "manifest.json", manifest)
    partial.rename(snap)  # a snapshot exists only once it is complete
    prune(backup_root, keep)
    return snap


def snapshots(backup_root: Path = BACKUP_ROOT) -> list[Path]:
    if not backup_root.is_dir():
        return []
    return sorted(p for p in backup_root.iterdir()
                  if p.is_dir() and not p.name.endswith(".partial")
                  and (p / "manifest.json").is_file())


def prune(backup_root: Path, keep: int) -> list[str]:
    """Drop the oldest COMPLETE snapshots beyond `keep` (never below 1).
    These are this tool's own regenerable copies, so a direct remove is used;
    the live data is never touched."""
    snaps = snapshots(backup_root)
    doomed = snaps[:-max(keep, 1)] if len(snaps) > max(keep, 1) else []
    for p in doomed:
        shutil.rmtree(p)
    return [p.name for p in doomed]


def verify(snap: Path) -> list[str]:
    """Restore every DB into a temp dir and check it. Returns problems."""
    manifest = json.loads((snap / "manifest.json").read_text(encoding="utf-8"))
    problems: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        for name, meta in manifest["files"].items():
            src = snap / name
            if not src.is_file():
                problems.append(f"{name}: missing from snapshot")
                continue
            if _sha256(src) != meta["sha256"]:
                problems.append(f"{name}: sha256 mismatch")
                continue
            restored = Path(tmp) / name
            _online_copy(src, restored)
            conn = sqlite3.connect(restored)
            try:
                ok = conn.execute("PRAGMA integrity_check").fetchone()[0]
            finally:
                conn.close()
            if ok != "ok":
                problems.append(f"{name}: integrity_check {ok}")
                continue
            if _table_counts(restored) != meta["tables"]:
                problems.append(f"{name}: row counts differ after restore")
    return problems


def restore(snap: Path, name: str, dest: Path) -> Path:
    """Restore ONE db to `dest`. Refuses to overwrite an existing file - put
    the live file aside (Recycle Bin) first; this tool never deletes live data."""
    if dest.exists():
        raise FileExistsError(f"{dest} exists - move it aside first")
    _online_copy(snap / name, dest)
    return dest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("classify")
    b = sub.add_parser("backup")
    b.add_argument("--keep", type=int, default=DEFAULT_KEEP)
    v = sub.add_parser("verify")
    v.add_argument("snapshot", nargs="?", type=Path)
    r = sub.add_parser("restore")
    r.add_argument("snapshot", type=Path)
    r.add_argument("name")
    r.add_argument("dest", type=Path)
    args = ap.parse_args(argv)
    if args.cmd == "classify":
        print(json.dumps(classify(), indent=1))
        return 0
    if args.cmd == "backup":
        snap = backup(keep=args.keep)
        problems = verify(snap)
        print(f"snapshot {snap.name}: {'VERIFIED' if not problems else problems}")
        return 0 if not problems else 1
    if args.cmd == "verify":
        snap = args.snapshot or (snapshots() or [None])[-1]
        if snap is None:
            print("no snapshot to verify")
            return 1
        problems = verify(snap)
        print(f"{snap.name}: {'VERIFIED' if not problems else problems}")
        return 0 if not problems else 1
    restore(args.snapshot, args.name, args.dest)
    print(f"restored {args.name} -> {args.dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
