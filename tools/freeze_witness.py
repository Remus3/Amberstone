#!/usr/bin/env python
"""RM-493: a freeze witness that is NOT purely a git witness.

RC states its freeze discipline in git terms ("`git status --porcelain` is
empty"), and git cannot see a `.pyc`: `.gitignore` ignores `__pycache__/`, so a
run that imports from a directory it is also measuring writes into that
directory invisibly to git. This witness hashes the FILESYSTEM, ignored files
included, so a bytecode write (or any other ignored-file change) moves it.

Usage:
  python tools/freeze_witness.py snapshot DIR [--out FILE]   # print/write digest
  python tools/freeze_witness.py verify DIR FILE             # exit 1 on drift
  python tools/freeze_witness.py price DIR                   # time vs git witness

The digest covers relative path, size and SHA-256 of every regular file under
DIR (symlinks/junctions are not followed). `.git` directories are skipped - the
object store is git's own witness, not the checkout's.

PRICE: `price` times this witness against `git status --porcelain -- DIR` on
the same directory, so the cost of the stronger witness is measured, not
assumed (the acceptance asks for it "priced against the git one").
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

SKIP_DIRS = frozenset({".git"})


def _walk(root: Path):
    """Pruned walk (never rglob - it cannot prune). Yields sorted rel paths."""
    out = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS
                             and not os.path.islink(os.path.join(dirpath, d)))
        for name in filenames:
            full = os.path.join(dirpath, name)
            if os.path.isfile(full) and not os.path.islink(full):
                out.append(os.path.relpath(full, root).replace("\\", "/"))
    return sorted(out)


def snapshot(root: Path) -> dict:
    root = Path(root)
    files = {}
    for rel in _walk(root):
        data = (root / rel).read_bytes()
        files[rel] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    blob = json.dumps(files, sort_keys=True).encode("ascii")
    return {"root": str(root), "files": len(files),
            "digest": hashlib.sha256(blob).hexdigest(), "entries": files}


def diff(before: dict, after: dict) -> dict:
    a, b = before["entries"], after["entries"]
    return {
        "added": sorted(set(b) - set(a)),
        "removed": sorted(set(a) - set(b)),
        "changed": sorted(k for k in set(a) & set(b) if a[k] != b[k]),
    }


def git_witness(root: Path) -> str:
    proc = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--", "."],
                          capture_output=True, text=True, check=False)
    return proc.stdout


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(text.encode("ascii"))
    tmp.replace(path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot")
    s.add_argument("dir", type=Path)
    s.add_argument("--out", type=Path)
    v = sub.add_parser("verify")
    v.add_argument("dir", type=Path)
    v.add_argument("file", type=Path)
    p = sub.add_parser("price")
    p.add_argument("dir", type=Path)
    args = ap.parse_args(argv)

    if args.cmd == "snapshot":
        snap = snapshot(args.dir)
        text = json.dumps(snap, indent=1, sort_keys=True) + "\n"
        if args.out:
            _write_atomic(args.out, text)
        print(f"{snap['digest']} {snap['files']} file(s)")
        return 0
    if args.cmd == "verify":
        before = json.loads(args.file.read_text(encoding="utf-8"))
        after = snapshot(args.dir)
        if after["digest"] == before["digest"]:
            print(f"FROZEN {after['digest']} {after['files']} file(s)")
            return 0
        d = diff(before, after)
        print(f"DRIFT added={len(d['added'])} removed={len(d['removed'])} "
              f"changed={len(d['changed'])}")
        for key in ("added", "removed", "changed"):
            for rel in d[key][:20]:
                print(f"  {key}: {rel}")
        return 1
    t0 = time.perf_counter()
    snap = snapshot(args.dir)
    t1 = time.perf_counter()
    git_witness(args.dir)
    t2 = time.perf_counter()
    print(f"filesystem witness: {t1 - t0:.3f}s over {snap['files']} file(s); "
          f"git witness: {t2 - t1:.3f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
