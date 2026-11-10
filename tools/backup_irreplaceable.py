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


def _ro_uri(path: Path, *, immutable: bool = False) -> str:
    """A read-only SQLite URI for `path`, percent-encoded by pathlib.

    S144-T-723: the URI used to be `f"file:{path}?mode=ro"`, so a '#' in the
    path cut it (the fragment) and a '%41' decoded to 'A' - SQLite opened a
    DIFFERENT file and the tool backed up or counted an empty database with no
    error. `immutable=1` is for this tool's own snapshot files only (never a
    live database): it reads the main file without creating `-wal` / `-shm`
    sidecars next to it, which a plain read-only open of a WAL-mode file does.
    """
    uri = path.resolve().as_uri() + "?mode=ro"
    return uri + "&immutable=1" if immutable else uri


def _bare_name(name: object) -> str:
    """`name` when it is a plain file name inside a snapshot, else ValueError.
    A manifest key or a restore argument must never walk out of the snapshot."""
    if (not isinstance(name, str) or not name or name in (".", "..")
            or Path(name).name != name or any(c in name for c in "/\\:")):
        raise ValueError(f"{name!r} is not a bare file name")
    return name


def _table_counts(db: Path, *, immutable: bool = False) -> dict[str, int]:
    conn = sqlite3.connect(_ro_uri(db, immutable=immutable), uri=True)
    try:
        names = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        # S144-T-723: a name holding '"' is doubled, not left to break the SQL.
        return {n: int(conn.execute(
                    'SELECT COUNT(*) FROM "{}"'.format(n.replace('"', '""'))).fetchone()[0])
                for n in names}
    finally:
        conn.close()


def _online_copy(src: Path, dest: Path, *, immutable: bool = False) -> None:
    """SQLite online backup of `src` into `dest`. Closing the destination
    checkpoints it, so a WAL-mode copy is one self-contained file (its header
    keeps WAL, so a restore comes back in the source's journal mode)."""
    s = sqlite3.connect(_ro_uri(src, immutable=immutable), uri=True)
    try:
        d = sqlite3.connect(dest)
        try:
            s.backup(d)
        finally:
            d.close()
    finally:
        s.close()


def _write_json_atomic(path: Path, obj) -> None:
    """RM-258: through core.polled_json (per-writer scratch, fsync, bounded
    WinError 5 retry); the bytes stay sorted, indent-1, ASCII and LF."""
    root = str(ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    from core.polled_json import atomic_write_bytes

    atomic_write_bytes(path, (json.dumps(obj, indent=1, sort_keys=True) + "\n").encode("ascii"))


def _no_sidecar(db: Path) -> None:
    """A copy is one self-contained file only when SQLite left no `-wal` next
    to it (closing the last connection checkpoints and removes it)."""
    for suffix in ("-wal", "-shm"):
        side = db.with_name(db.name + suffix)
        if side.exists():
            raise RuntimeError(f"{db.name}: {side.name} left behind - copy not self-contained")


def backup(data_dir: Path = DATA, backup_root: Path = BACKUP_ROOT,
           keep: int = DEFAULT_KEEP, now: float | None = None) -> Path:
    """Copy every irreplaceable DB into `<backup_root>/<UTC stamp>/`.

    S144-T-723: a data dir holding no irreplaceable database is REFUSED. It
    used to yield an empty snapshot that verify() called VERIFIED, and its
    prune() then rotated out a real snapshot - seven such runs (a moved or
    mistyped data dir) would have left no backup at all.
    The snapshot is built in a scratch dir under `backup_root` and renamed into
    place only when complete; a failure removes the scratch dir with it."""
    names = classify(data_dir)["irreplaceable"]
    if not names:
        raise RuntimeError(f"no irreplaceable database under {data_dir} - nothing to back up")
    stamp = time.strftime("%Y%m%dT%H%M%SZ",
                          time.gmtime(time.time() if now is None else now))
    snap = backup_root / stamp
    if snap.exists():
        raise FileExistsError(f"snapshot {stamp} already exists")
    backup_root.mkdir(parents=True, exist_ok=True)
    manifest = {"created_utc": stamp, "source": str(data_dir), "files": {}}
    with tempfile.TemporaryDirectory(dir=backup_root, prefix=stamp + ".partial-") as tmp:
        stage = Path(tmp) / (stamp + ".partial")
        stage.mkdir()
        for name in names:
            dest = stage / name
            _online_copy(data_dir / name, dest)
            _no_sidecar(dest)
            manifest["files"][name] = {"size": dest.stat().st_size,
                                       "sha256": _sha256(dest),
                                       "tables": _table_counts(dest, immutable=True)}
        _write_json_atomic(stage / "manifest.json", manifest)
        stage.rename(snap)  # a snapshot exists only once it is complete
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


def _manifest_files(snap: Path) -> dict:
    """The manifest's `files` map, or ValueError naming why it is unusable."""
    try:
        manifest = json.loads((snap / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"manifest unreadable ({type(exc).__name__})") from exc
    files = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(files, dict):
        raise ValueError("manifest has no files map")
    return files


def _check_one(snap: Path, name: object, meta: object, tmp: Path) -> str | None:
    """One manifest entry restored into `tmp` and checked; a problem or None."""
    try:
        name = _bare_name(name)
    except ValueError as exc:
        return f"{name!r}: {exc}"
    if not isinstance(meta, dict):
        return f"{name}: manifest entry is not an object"
    src = snap / name
    if not src.is_file():
        return f"{name}: missing from snapshot"
    if _sha256(src) != meta.get("sha256"):
        return f"{name}: sha256 mismatch"
    restored = tmp / name
    try:
        _online_copy(src, restored, immutable=True)
        conn = sqlite3.connect(restored)
        try:
            ok = conn.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            conn.close()
        if ok != "ok":
            return f"{name}: integrity_check {ok}"
        if _table_counts(restored, immutable=True) != meta.get("tables"):
            return f"{name}: row counts differ after restore"
    except sqlite3.Error as exc:
        return f"{name}: unreadable by SQLite ({type(exc).__name__}: {exc})"
    return None


def verify(snap: Path) -> list[str]:
    """Restore every DB into a temp dir and check it. Returns problems.

    S144-T-723: a missing or junk manifest, a manifest listing no database, a
    name that walks out of the snapshot and a file SQLite cannot read are each
    REPORTED as a problem (they used to raise, or to pass as VERIFIED)."""
    try:
        files = _manifest_files(snap)
    except ValueError as exc:
        return [str(exc)]
    if not files:
        return ["manifest lists no database"]
    problems: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        for name, meta in files.items():
            problem = _check_one(snap, name, meta, Path(tmp))
            if problem:
                problems.append(problem)
    return problems


def restore(snap: Path, name: str, dest: Path) -> Path:
    """Restore ONE db to `dest`. Refuses to overwrite an existing file - put
    the live file aside (Recycle Bin) first; this tool never deletes live data.

    S144-T-723: `name` must be a bare file name the manifest lists, and the
    snapshot file must match its recorded SHA-256 (a corrupted or unlisted file
    used to be restored silently). The copy is made in a scratch dir beside
    `dest` and renamed into place whole, so a failed copy leaves no
    half-written `dest` to block the retry."""
    name = _bare_name(name)
    if dest.exists():
        raise FileExistsError(f"{dest} exists - move it aside first")
    meta = _manifest_files(snap).get(name)
    if not isinstance(meta, dict):
        raise ValueError(f"{name}: not listed in the snapshot manifest")
    src = snap / name
    if not src.is_file() or _sha256(src) != meta.get("sha256"):
        raise ValueError(f"{name}: missing or sha256 mismatch - refusing to restore")
    with tempfile.TemporaryDirectory(dir=dest.parent, prefix=".restore-") as tmp:
        staged = Path(tmp) / name
        _online_copy(src, staged, immutable=True)
        _no_sidecar(staged)
        if dest.exists():
            raise FileExistsError(f"{dest} exists - move it aside first")
        staged.rename(dest)  # Windows refuses to replace an existing file
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
    try:
        return _run(args)
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        # S144-T-723: an expected failure is one line and exit 2, not a traceback.
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _run(args: argparse.Namespace) -> int:
    if args.cmd == "classify":
        print(json.dumps(classify(), indent=1))
        return 0
    if args.cmd == "backup":
        snap = backup(keep=args.keep)
        problems = verify(snap)
        print(f"snapshot {snap.name}: {problems or 'VERIFIED'}")
        return 0 if not problems else 1
    if args.cmd == "verify":
        snap = args.snapshot or (snapshots() or [None])[-1]
        if snap is None:
            print("no snapshot to verify")
            return 1
        problems = verify(snap)
        print(f"{snap.name}: {problems or 'VERIFIED'}")
        return 0 if not problems else 1
    restore(args.snapshot, args.name, args.dest)
    print(f"restored {args.name} -> {args.dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
