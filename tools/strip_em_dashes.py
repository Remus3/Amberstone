"""One-shot + reusable maintenance: purge Unicode dashes from the repo.

Hard rule (CLAUDE.md, 2026-05-18): no em-dashes OR en-dashes in any
authored text - keep authored content 7-bit ASCII. This replaces every
em-dash (U+2014) and en-dash (U+2013) with a plain ASCII hyphen-minus
'-'. A flat 1:1 char swap (not context-aware) is deliberate: it keeps
the functional "-no-data-" sentinel consistent on BOTH sides
automatically (the literal producers like `grade or "X"` and the
consumer `val == "X"` in core/match_metrics.py get the identical
substitution), and ' X ' (spaced dash) naturally becomes ' - ' which
reads fine in prose. Smart quotes / arrows / math symbols are NOT in
scope (the hard rule names dashes + smart-quotes; smart-quote sweep is
a separate operator-gated decision; arrows/x/~= are out of scope).

MOJIBAKE (added 2026-07-30): a dash can already be CORRUPTED on disk -
its UTF-8 bytes re-decoded as latin-1 and re-saved, one or more times.
An em-dash mangled once is 3 chars (U+00E2 U+0080 U+0094), mangled twice
is 6 chars (U+00C3 U+00A2 U+00C2 U+0080 U+00C2 U+0094). Neither contains
the raw E2 80 94 byte run, so the naive scan walked straight past them:
MEASURED on data/meta/tft_set17_meta.json, which carried 17 twice-mangled
and 4 once-mangled em-dashes while this tool reported the file clean.
The ladder is now generated programmatically (see _mojibake_ladder) to
_MOJIBAKE_DEPTH levels and each rung is stripped like a real dash.

This script keeps itself 7-bit ASCII (codepoints via chr(), not the
literal glyphs) so it does not need to be its own exclusion for that
reason - it is still skipped to avoid self-mutation mid-walk.

EXCLUSIONS (immutable history / non-text, per the standing
don't-rewrite-history rule + CLAUDE.md carve-out):
  - .git/ , __pycache__/ , any path component '_archive'
  - *.log (append-only operational history)
  - binary / generated: .pyc .pyd .db .db-shm .db-wal .png .jpg .jpeg
    .gif .ico .zip .exe .dll .lnk .woff .woff2 .ttf
  - this script itself (it documents the char in its own docstring)

Usage:
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/strip_em_dashes.py            # dry-run (default): report only
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/strip_em_dashes.py --apply    # rewrite in place (atomic)
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

EM = chr(0x2014)   # em-dash
EN = chr(0x2013)   # en-dash
REPL = "-"

# How many rounds of latin-1 re-decoding to unwind. Two is what has
# actually been observed on disk; three is cheap insurance.
_MOJIBAKE_DEPTH = 3


def _mojibake_ladder(ch: str, depth: int = _MOJIBAKE_DEPTH) -> list[str]:
    """Successive latin-1 mis-decodings of ch's UTF-8 bytes.

    Level 1 is the classic "encoded UTF-8, read as latin-1, saved again"
    corruption; level 2 is that same accident applied twice; and so on.
    Stops early if a rung is not latin-1 decodable.
    """
    out: list[str] = []
    cur = ch
    for _ in range(depth):
        try:
            cur = cur.encode("utf-8").decode("latin-1")
        except (UnicodeDecodeError, UnicodeEncodeError):
            break
        out.append(cur)
    return out


# Longest first so a deeper rung is consumed before a shallower one that
# might share a prefix; real dashes are last and are single chars anyway.
DASHES: tuple[str, ...] = tuple(sorted(
    {EM, EN, *_mojibake_ladder(EM), *_mojibake_ladder(EN)},
    key=len, reverse=True,
))
# Cheap byte prefilter: every form's UTF-8 encoding.
_DASH_BYTES = tuple(d.encode("utf-8") for d in DASHES)
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


def strip_dashes(text: str) -> tuple[str, int]:
    """Replace every dash form (real + mojibake) with REPL.

    Returns (new_text, occurrences_replaced). Forms are applied
    longest-first so a deeply mangled rung is not shredded by a shallower
    partial match.
    """
    n = 0
    for d in DASHES:
        c = text.count(d)
        if c:
            n += c
            text = text.replace(d, REPL)
    return text, n


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
        if not any(b in raw for b in _DASH_BYTES):  # U+2014 / U+2013
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            skipped_binary += 1
            continue
        new, n = strip_dashes(text)
        if not n:
            continue
        total_occ += n
        files_changed += 1
        by_ext[p.suffix.lower() or "<none>"] += n
        per_file.append((n, str(p.relative_to(ROOT))))
        if args.apply:
            tmp = p.with_suffix(p.suffix + ".emtmp")
            tmp.write_text(new, encoding="utf-8", newline="")
            os.replace(tmp, p)

    mode = "APPLIED" if args.apply else "DRY-RUN (no writes)"
    print(f"=== strip_em_dashes (em+en) {mode} ===")
    print(f"files with dashes    : {files_changed}")
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
