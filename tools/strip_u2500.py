"""One-shot + reusable maintenance: replace U+2500 BOX DRAWINGS LIGHT
HORIZONTAL with ASCII hyphen-minus in operator-granted target files.

Background (item 176, 2026-05-24): two FROZEN files contain bulk U+2500
chars used in intentional docstring tree-drawing:
    ops/rc_supervisor.py     58 U+2500 chars
    ops/rc_self_monitor.py   484 U+2500 chars

The operator authorized "Grant + sweep" of these two files via the
--allow-frozen flag this run, normalizing the box-drawing horizontal rule
to plain ASCII '-' (the visual rule still reads as a separator).

WHY THIS TOOL IS NARROW-SCOPE (explicit file list, not repo-wide walk):
U+2500 appears intentionally in many non-frozen authored files across the
repo (test fixtures, docstrings, ASCII-art separators in 207+ tracked
files totalling ~54,000 occurrences as of 2026-05-24). Unlike smart quotes
or em-dashes (which are banned globally by the CLAUDE.md hard rule),
U+2500 is NOT a banned codepoint. Sweeping it repo-wide would corrupt
intentional ASCII-art across the codebase. Therefore this tool takes an
EXPLICIT comma-separated path list via --allow-frozen (which doubles as
"explicit allowlist"), and refuses to walk the repo blindly.

REPLACEMENT:
    U+2500 BOX DRAWINGS LIGHT HORIZONTAL  -> 0x2D '-' (ASCII hyphen-minus)
    UTF-8 bytes:  e2 94 80  -> 2d   (3 bytes -> 1 byte)

The visual width changes (the box-drawing glyph is roughly the width of
an em-dash; ASCII '-' is narrower), but the SEMANTIC intent of a
horizontal separator rule is preserved. Tree-drawing patterns like
'+------+' become '+------+' (unchanged) since they used ASCII to begin
with; ASCII-art like '----' (built from U+2500) becomes '----' which still
reads as a rule.

ATOMIC WRITE: tmp.write_bytes() + os.replace() (Windows-safe).

EXCLUSIONS: the tool refuses to operate on any file NOT listed in
--allow-frozen. There is no implicit walk. _HARD_SKIP_FROZEN is the
defense-in-depth set: any path in that frozenset is NEVER rewritten
regardless of the flag. Currently empty so all listed files are
operator-grantable; bump ONLY with explicit operator authorization for
a specific path that must never be touched even by accidental grant.

Usage:
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/strip_u2500.py --allow-frozen ops/rc_supervisor.py,ops/rc_self_monitor.py
                          # rewrite the named files in place (atomic),
                          # report per-file pre/post counts
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/strip_u2500.py --allow-frozen ops/rc_supervisor.py --dry-run
                          # dry-run: report counts, no writes

Exit codes:
    0  if any file was rewritten (or, in --dry-run, any file would have been)
    1  if --allow-frozen was empty OR no listed file contained U+2500

This script keeps itself 7-bit ASCII (codepoints constructed via \\xNN
byte literals; no literal U+2500 glyph in the source) so it does not
self-trip the drift guard.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# UTF-8 byte sequence for U+2500 BOX DRAWINGS LIGHT HORIZONTAL.
# Constructed via \xNN byte escapes so this source file stays 7-bit ASCII.
U2500_BYTES = b"\xe2\x94\x80"
ASCII_HYPHEN = b"\x2d"  # ASCII '-'

ROOT = Path(__file__).resolve().parent.parent
_SELF = Path(__file__).resolve()

# HARD SKIP: paths in this set are NEVER rewritten, even when listed in
# --allow-frozen. Defense-in-depth defaulted to empty so any frozen file
# is operator-grantable via the flag. Bump ONLY with explicit operator
# authorization for a specific path that must never be touched even by
# accidental grant (mirrors strip_smart_quotes.py + repair_mojibake.py
# precedent).
_HARD_SKIP_FROZEN: frozenset[str] = frozenset()


def _count_u2500(raw: bytes) -> int:
    return raw.count(U2500_BYTES)


def _process_file(rel_posix: str, dry_run: bool) -> tuple[int, int, str]:
    """Return (pre_count, post_count, status_msg) for one path.

    status_msg is one of: "rewritten", "dry-run", "no-hits", "missing",
    "decode-fail", "read-fail", "hard-skip", "ascii-mismatch".
    """
    if rel_posix in _HARD_SKIP_FROZEN:
        return (0, 0, "hard-skip")
    abs_path = ROOT / rel_posix
    if not abs_path.is_file():
        return (0, 0, "missing")
    try:
        raw = abs_path.read_bytes()
    except OSError:
        return (0, 0, "read-fail")
    pre = _count_u2500(raw)
    if pre == 0:
        return (0, 0, "no-hits")
    new = raw.replace(U2500_BYTES, ASCII_HYPHEN)
    post = _count_u2500(new)
    if post != 0:
        # Should never happen given the replace() call, but defense-in-depth.
        return (pre, post, "ascii-mismatch")
    # Sanity: result must still be valid UTF-8.
    try:
        new.decode("utf-8")
    except UnicodeDecodeError:
        return (pre, post, "decode-fail")
    if dry_run:
        return (pre, post, "dry-run")
    tmp = abs_path.with_suffix(abs_path.suffix + ".u2500tmp")
    tmp.write_bytes(new)
    os.replace(tmp, abs_path)
    return (pre, post, "rewritten")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Replace U+2500 box-drawing horizontal with ASCII '-' in "
            "operator-granted target files. Refuses to walk the repo "
            "blindly; --allow-frozen is REQUIRED."
        )
    )
    ap.add_argument(
        "--allow-frozen",
        type=str,
        default="",
        help=(
            "comma-separated repo-relative POSIX paths to sweep "
            "(REQUIRED - this tool does NOT walk the repo). "
            "Paths in _HARD_SKIP_FROZEN are still NEVER rewritten "
            "regardless of this flag."
        ),
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="report counts only; do not rewrite",
    )
    args = ap.parse_args()

    raw_list = [s.strip() for s in args.allow_frozen.split(",") if s.strip()]
    if not raw_list:
        print(
            "ERROR: --allow-frozen is REQUIRED. This tool does not walk "
            "the repo blindly because U+2500 is intentional ASCII-art in "
            "many non-frozen files. Pass an explicit comma-separated "
            "path list.",
            file=sys.stderr,
        )
        return 1

    allow_frozen = []
    hard_skipped = []
    for p in raw_list:
        if p in _HARD_SKIP_FROZEN:
            hard_skipped.append(p)
        else:
            allow_frozen.append(p)

    mode = "DRY-RUN (no writes)" if args.dry_run else "APPLIED"
    print(f"=== strip_u2500 {mode} ===")
    print("signature (hex)     : e2 94 80  (U+2500 BOX DRAWINGS LIGHT HORIZONTAL)")
    print("replacement (hex)   : 2d        (ASCII hyphen-minus '-')")
    print(f"target files        : {len(allow_frozen)}")
    if hard_skipped:
        print(
            f"HARD-SKIP from --allow-frozen (override IGNORED): {sorted(hard_skipped)}"
        )

    total_pre = 0
    total_post = 0
    rewritten = 0
    skipped = 0
    print("per-file results:")
    for rel in allow_frozen:
        pre, post, status = _process_file(rel, args.dry_run)
        total_pre += pre
        total_post += post
        marker = ""
        if status in ("rewritten", "dry-run"):
            rewritten += 1
        else:
            skipped += 1
            marker = f"  [{status}]"
        print(f"  pre={pre:>6}  post={post:>6}  {rel}{marker}")

    print(f"total pre-count     : {total_pre}")
    print(f"total post-count    : {total_post}")
    print(f"files rewritten     : {rewritten}")
    print(f"files skipped       : {skipped}")
    if total_pre == 0:
        print(
            "WARNING: no listed file contained U+2500. Nothing to sweep.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
