"""One-shot + reusable maintenance: purge U+2014 (em-dash) from the repo.

Hard rule (CLAUDE.md, 2026-05-18): no em-dashes in any authored text.
This replaces every em-dash with a plain ASCII hyphen-minus '-'. A flat
1:1 char swap (not context-aware) is deliberate: it keeps the functional
"-no-data-" sentinel consistent on BOTH sides automatically (the literal
producers like `grade or "X"` and the consumer `val == "X"` in
core/match_metrics.py get the identical substitution), and ' X ' (spaced
em-dash) naturally becomes ' - ' which reads fine in prose.

EXCLUSIONS (immutable history / non-text, per the standing
don't-rewrite-history rule + CLAUDE.md carve-out):
  - .git/ , __pycache__/ , any path component '_archive'
  - *.log (append-only operational history)
  - binary / generated: .pyc .pyd .db .db-shm .db-wal .png .jpg .jpeg
    .gif .ico .zip .exe .dll .lnk .woff .woff2 .ttf
  - this script itself (it documents the char in its own docstring)

Usage:
  py tools/strip_em_dashes.py            # dry-run (default): report only
  py tools/strip_em_dashes.py --apply    # rewrite in place (atomic)
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

EM = "—"
REPL = "-"
ROOT = Path(__file__).resolve().parent.parent

# git-tracked enumeration already excludes everything gitignored
# (.pyc, ops/runtime state, web/data/ddragon mirror, logs if ignored,
# .venv, ...). These are the additional tracked-but-immutable carve-outs
# per the standing don't-rewrite-history rule + CLAUDE.md.
_SKIP_DIR_PARTS = {"_archive"}
_SKIP_EXT = {
    ".pyc", ".pyd", ".db", ".png", ".jpg", ".jpeg", ".gif", ".ico",
    ".zip", ".exe", ".dll", ".lnk", ".woff", ".woff2", ".ttf", ".bin",
    ".so", ".o",
    # append-only operational ledgers (task_queue / bridge_log): logs
    # in JSON form, concurrently written by the running supervisor.
    ".jsonl",
}
# any *.log, *.log.1, *.log.3, supervisor.log.3, ...
_LOG_RE = re.compile(r"\.log(\.\d+)?$", re.IGNORECASE)
_SELF = Path(__file__).resolve()


def _skip(path: Path) -> bool:
    if path.resolve() == _SELF:
        return True
    if set(path.parts) & _SKIP_DIR_PARTS:
        return True
    name = path.name.lower()
    if _LOG_RE.search(name):
        return True
    if name.endswith((".db-shm", ".db-wal")):
        return True
    if path.suffix.lower() in _SKIP_EXT:
        return True
    return False


def _tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT,
        capture_output=True, check=True,
    ).stdout
    return [ROOT / p for p in out.decode("utf-8").split("\0") if p]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="rewrite files in place (default: dry-run)")
    ap.add_argument("--top", type=int, default=15,
                    help="show N highest-count files")
    args = ap.parse_args()

    by_ext: Counter[str] = Counter()
    per_file: list[tuple[int, str]] = []
    total_occ = 0
    files_changed = 0
    skipped_binary = 0

    import os
    for p in _tracked_files():
        if _skip(p):
            continue
        try:
            raw = p.read_bytes()
        except OSError:
            continue
        if b"\xe2\x80\x94" not in raw:  # UTF-8 bytes for U+2014
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            skipped_binary += 1
            continue
        n = text.count(EM)
        if not n:
            continue
        total_occ += n
        files_changed += 1
        by_ext[p.suffix.lower() or "<none>"] += n
        per_file.append((n, str(p.relative_to(ROOT))))
        if args.apply:
            new = text.replace(EM, REPL)
            tmp = p.with_suffix(p.suffix + ".emtmp")
            tmp.write_text(new, encoding="utf-8", newline="")
            os.replace(tmp, p)

    mode = "APPLIED" if args.apply else "DRY-RUN (no writes)"
    print(f"=== strip_em_dashes {mode} ===")
    print(f"files with em-dashes : {files_changed}")
    print(f"total occurrences    : {total_occ}")
    print(f"skipped (binary utf8): {skipped_binary}")
    print("by extension:")
    for ext, c in by_ext.most_common():
        print(f"  {ext:<8} {c}")
    print(f"top {args.top} files by count:")
    for n, rel in sorted(per_file, reverse=True)[:args.top]:
        print(f"  {n:>6}  {rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
