"""
scripts/wakeup_prune.py - auto-prune WAKEUP_NOTES.md per the /done ritual.

# arch: phase 7 (2026-05-09) - automate /done section 6c WAKEUP_NOTES archival

Keeps the most recent N session blocks (default 3) in WAKEUP_NOTES.md and
moves older blocks to docs/history_notes.md, preserving newest-first order.

Why this exists:
    Bridge spawn overhead grows linearly with WAKEUP_NOTES.md size - each
    `claude --print` cold-loads it. Per /done section 6c, the file must be
    pruned at every session wrap. Doing it manually drifts; this helper makes
    it mechanical.

Usage:
    C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe scripts/wakeup_prune.py            # prune to default keep=3
    C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe scripts/wakeup_prune.py --keep 2   # keep only the last 2 sessions
    C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe scripts/wakeup_prune.py --dry-run  # report what would move; no writes
    C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe scripts/wakeup_prune.py --check    # exit 1 if more than --keep sessions
                                          # remain in WAKEUP_NOTES.md
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAKEUP = ROOT / "WAKEUP_NOTES.md"
ARCHIVE = ROOT / "docs" / "history_notes.md"

SEP = "\n---\n\n"
# A session heading is either:
#   legacy - `# s171 wrap`, `# s171.8 wrap`, `# s209-s213 wrap` (hyphen ranges;
#            the range separator was an en-dash/hyphen char class until the
#            2026-05-18 ASCII purge left it a degenerate `[--]`, now a plain
#            `-` - en-dash ranges have not matched since and none exist); or
#   dated  - `# 2026-05-17 (late) - ...`, `# 2026-05-17 wrap - ...`,
#            `# 2026-05-17 OVERNIGHT RUN-1 - ...`, `# 2026-07-19a - ...`
#            (any suffix after the date, including a bare letter suffix).
# A leading pinned block (`# <U+2705> RESOLVED 2026-05-17 - ...`) matches NEITHER -
# the date is not at heading-start - so split_sessions folds it into the
# header rather than archiving it.
#
# The dated alternative deliberately has NO trailing `\b`. A `\b` there rejects
# every heading whose date is followed directly by a word char - notably the
# letter-suffixed `# 2026-07-19a` form used when two sessions wrap on the same
# calendar day, since "9" and "a" are both word chars so no boundary exists.
# That made split_sessions find ZERO sessions and prune/--check silently report
# "nothing to do" at any file size. Do not re-add it; `^# ` + a full ISO date is
# already specific enough. Regression: tests/phase7_polish/test_wakeup_prune.py
# TestSessionReSuffixedDate.
SESSION_RE = re.compile(
    r"^# (?:"
    r"s\d+(?:\.\d+)*(?:-s\d+(?:\.\d+)*)? wrap\b"
    r"|\d{4}-\d{2}-\d{2}"
    r")",
    re.M,
)

ARCHIVE_HEADER = (
    "# RC session history archive\n"
    "\n"
    "Sessions older than the last 2-3 full sessions are progressively compacted here.\n"
    "Current WAKEUP_NOTES.md keeps only the most recent 2-3 sessions.\n"
    "Compaction rule: 3+ sessions old -> 1-2 line summary entry below.\n"
)


def _split_on_interior_headings(block: str) -> list[str]:
    """Split a single SEP-delimited block into one sub-block per session
    heading it contains.

    A /done append that OMITS the `\\n---\\n\\n` separator before its heading
    leaves two (or more) sessions glued into one block. Without this re-split
    split_sessions would count them as one - the documented separator gotcha
    (memory reference_wakeup_prune_separator_gotcha) that makes --check
    under-report and lets WAKEUP_NOTES.md grow unbounded. We cut the block at
    every interior heading-start so each session is counted (and archived)
    independently. Leading whitespace before the first heading rides with the
    first sub-block; a block with <= 1 heading is returned unchanged.
    """
    # Offsets of each session heading at line-start within the block. The regex
    # is multiline-anchored, so a heading mid-block matches at its own line.
    starts = [m.start() for m in SESSION_RE.finditer(block)]
    if len(starts) <= 1:
        return [block]
    # Keep any pre-heading preamble attached to the first sub-block.
    cut_points = [0] + starts[1:]
    out: list[str] = []
    for i, start in enumerate(cut_points):
        end = cut_points[i + 1] if i + 1 < len(cut_points) else len(block)
        piece = block[start:end]
        if piece:
            out.append(piece)
    return out


def split_sessions(text: str) -> tuple[str, list[str]]:
    """Return (header_block, [session_blocks_newest_first]).

    A "session block" is the body of a session entry (without the leading
    `\\n---\\n\\n` separator). Order is preserved as it appears in the file
    (newest first by RC convention).
    """
    parts = text.split(SEP)
    if len(parts) <= 1:
        return text, []
    header, *rest = parts
    leading_pins: list[str] = []
    sessions: list[str] = []
    trailing_extras: list[str] = []
    seen_session = False
    for block in rest:
        if SESSION_RE.match(block.lstrip("\n")):
            seen_session = True
            # A missing separator can glue several sessions into one block;
            # re-split so each is counted independently.
            sessions.extend(_split_on_interior_headings(block))
        elif not seen_session:
            # Pinned non-session block(s) that precede the first session
            # (e.g. `# <U+2705> RESOLVED ... `). These belong with the header so
            # they are never archived and stay at the top of WAKEUP_NOTES.
            leading_pins.append(block)
        else:
            # Unexpected non-session block AFTER sessions began (e.g. a
            # stray separator / malformed block). Preserve it at the tail
            # so we never silently drop content.
            trailing_extras.append(block)
    if leading_pins:
        header = render(header, leading_pins)
    return header, sessions + trailing_extras


def render(header: str, sessions: list[str]) -> str:
    """Reassemble file text from a header + ordered list of session blocks.

    Each block is normalised to end with exactly one `\\n`, then joined with
    `\\n---\\n\\n`. That produces the file shape: `<content>\\n\\n---\\n\\n`
    between sections - i.e. blank line BEFORE the rule and blank line AFTER.
    """
    header = header.rstrip("\n") + "\n"
    if not sessions:
        return header
    body_parts = [b.rstrip("\n") + "\n" for b in sessions]
    body = SEP.join(body_parts)
    return header + SEP + body


def _atomic_write(target: Path, content: str) -> None:
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8", newline="\n")
    tmp.replace(target)


def _reject_bad_keep(keep: int) -> bool:
    """RM-363: a keep count below 1 empties the ledger it exists to bound.

    The only test on `keep` used to be `len(sessions) <= keep`, which any
    non-positive value passes straight through. At 0 the split relocates
    EVERY session and WAKEUP_NOTES is rewritten down to its header; at -1
    the knob inverts and archives the oldest instead of keeping the newest.
    Checked before the file is read, so a bad policy cannot be masked by a
    missing-file early return.
    """
    if keep < 1:
        print(
            f"wakeup_prune: --keep must be >= 1, got {keep}; a keep of 0 "
            f"would archive every session and leave WAKEUP_NOTES empty",
            file=sys.stderr,
        )
        return True
    return False


def prune(*, keep: int, dry_run: bool) -> int:
    if _reject_bad_keep(keep):
        return 2
    if not WAKEUP.exists():
        print(f"wakeup_prune: WAKEUP_NOTES not found: {WAKEUP}", file=sys.stderr)
        return 1
    text = WAKEUP.read_text(encoding="utf-8")
    header, sessions = split_sessions(text)
    if len(sessions) <= keep:
        print(f"wakeup_prune: {len(sessions)} session(s) <= keep={keep}; nothing to do")
        return 0

    keep_sessions = sessions[:keep]
    move_sessions = sessions[keep:]
    moved_ids = [
        next((ln for ln in b.lstrip("\n").splitlines() if ln.strip()),
             "(non-session block)")
        for b in move_sessions
    ]
    print(f"wakeup_prune: moving {len(move_sessions)} session(s): {moved_ids}")

    new_wakeup = render(header, keep_sessions)

    if ARCHIVE.exists():
        a_header, a_sessions = split_sessions(ARCHIVE.read_text(encoding="utf-8"))
    else:
        a_header = ARCHIVE_HEADER
        a_sessions = []
    new_archive = render(a_header, move_sessions + a_sessions)

    if dry_run:
        print("(dry-run - no files written)")
        return 0

    _atomic_write(WAKEUP, new_wakeup)
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(ARCHIVE, new_archive)
    print(f"wakeup_prune: WAKEUP_NOTES now has {len(keep_sessions)} session(s); "
          f"archive now has {len(move_sessions) + len(a_sessions)}")
    return 0


def check(keep: int) -> int:
    if _reject_bad_keep(keep):
        return 2
    if not WAKEUP.exists():
        return 0
    text = WAKEUP.read_text(encoding="utf-8")
    _, sessions = split_sessions(text)
    if len(sessions) > keep:
        print(
            f"wakeup_prune --check: WAKEUP_NOTES has {len(sessions)} sessions "
            f"(> keep={keep}); run `C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe scripts/wakeup_prune.py`",
            file=sys.stderr,
        )
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--keep", type=int, default=3,
                    help="number of recent sessions to keep in WAKEUP_NOTES (default: 3)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would move without writing files")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if more than --keep sessions remain (no writes)")
    args = ap.parse_args()
    if args.check:
        return check(args.keep)
    return prune(keep=args.keep, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
