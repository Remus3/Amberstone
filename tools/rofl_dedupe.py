"""Deduplicate identical .rofl containers with hardlinks.

    python tools/rofl_dedupe.py                # report only
    python tools/rofl_dedupe.py --apply

The roster pull downloads a replay once per TRACKED PLAYER who was in it, so a
challenger game with four tracked participants lands on disk four times.
Measured 2026-07-26: 424 files covering 341 matches - 83 redundant copies,
1.07 GB, 20 percent of the archive. The tracked accounts queue into each other
constantly, so the share grows rather than plateaus.

Hardlinks keep every per-player path exactly where it is - nothing that walks
`players/<ROLE>/<player>/` sees any change - while the bytes exist once.

TWO SAFETY RULES, both enforced rather than assumed:

  CONTENT IS VERIFIED, NOT INFERRED. Files are linked only when their SHA-256
  matches. Two replays of the same match id downloaded from different accounts
  SHOULD be byte-identical, but "should" is not a reason to delete one of them.
  A size or name match alone is never sufficient.

  ALREADY-LINKED FILES ARE SKIPPED. Same inode means the work is done, so a
  re-run is a no-op and this is safe on a schedule.

Naming note: replays arrive as both `NA1_<id>.rofl` (RC's pull) and
`NA1-<id>.rofl` (the game client). Both spellings are one match.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

DEFAULT_ROOT = Path.home() / "Documents" / "RC_ROFL_Archive"
_CHUNK = 1 << 20


def match_key(path: Path) -> str:
    """Filename -> match id, collapsing the two naming conventions."""
    return path.stem.replace("NA1-", "NA1_")


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(_CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def groups(root: Path) -> dict:
    """match id -> [paths], only for ids with more than one file."""
    by = collections.defaultdict(list)
    for p in root.rglob("*.rofl"):
        if "_quarantine" in p.parts:
            continue
        by[match_key(p)].append(p)
    return {k: sorted(v) for k, v in by.items() if len(v) > 1}


def plan(root: Path):
    """(links_to_make, skipped_mismatches, already_linked_bytes)."""
    links, mismatched, already = [], [], 0
    for _mid, paths in sorted(groups(root).items()):
        keeper = paths[0]
        keeper_stat = keeper.stat()
        keeper_hash = None
        for other in paths[1:]:
            st = other.stat()
            if st.st_ino and st.st_ino == keeper_stat.st_ino:
                already += st.st_size
                continue
            if st.st_size != keeper_stat.st_size:
                mismatched.append((keeper, other, "size"))
                continue
            if keeper_hash is None:
                keeper_hash = digest(keeper)
            if digest(other) != keeper_hash:
                mismatched.append((keeper, other, "content"))
                continue
            links.append((keeper, other, st.st_size))
    return links, mismatched, already


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Hardlink duplicate .rofl files.")
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    ap.add_argument("--apply", action="store_true",
                    help="actually relink (default is report only)")
    args = ap.parse_args(argv)

    root = Path(args.root)
    if not root.exists():
        print(f"no such archive: {root}")
        return 2

    links, mismatched, already = plan(root)
    reclaim = sum(sz for _, _, sz in links)
    print(f"archive        {root}")
    print(f"duplicate sets {len(groups(root))}")
    print(f"relinkable     {len(links)} files, {reclaim / 2**30:.2f} GB")
    if already:
        print(f"already linked {already / 2**30:.2f} GB (previous run)")
    for keeper, other, why in mismatched:
        print(f"  SKIP {other.name} in {other.parent.name}: {why} differs "
              f"from {keeper.parent.name}")

    if not args.apply:
        print("\nreport only - pass --apply to relink")
        return 0

    done = failed = 0
    for keeper, other, _sz in links:
        tmp = other.with_suffix(".rofl.relink")
        try:
            # Link beside the target first, then swap. A crash mid-operation
            # leaves either the original or the link, never a missing replay.
            if tmp.exists():
                tmp.unlink()
            os.link(keeper, tmp)
            os.replace(tmp, other)
            done += 1
        except OSError as exc:
            failed += 1
            print(f"  FAILED {other}: {exc}")
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
    print(f"\nrelinked {done}, failed {failed}, "
          f"reclaimed about {reclaim / 2**30:.2f} GB")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
