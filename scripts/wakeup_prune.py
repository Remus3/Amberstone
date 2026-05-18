"""
scripts/wakeup_prune.py — auto-prune WAKEUP_NOTES.md per the /done ritual.

# arch: phase 7 (2026-05-09) — automate /done section 6c WAKEUP_NOTES archival

Keeps the most recent N session blocks (default 3) in WAKEUP_NOTES.md and
moves older blocks to docs/history_notes.md, preserving newest-first order.

Why this exists:
    Bridge spawn overhead grows linearly with WAKEUP_NOTES.md size — each
    `claude --print` cold-loads it. Per /done section 6c, the file must be
    pruned at every session wrap. Doing it manually drifts; this helper makes
    it mechanical.

Usage:
    py scripts/wakeup_prune.py            # prune to default keep=3
    py scripts/wakeup_prune.py --keep 2   # keep only the last 2 sessions
    py scripts/wakeup_prune.py --dry-run  # report what would move; no writes
    py scripts/wakeup_prune.py --check    # exit 1 if more than --keep sessions
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
#   legacy — `# s171 wrap`, `# s171.8 wrap`, `# s209–s213 wrap` (en-dash or
#            hyphen ranges); or
#   dated  — `# 2026-05-17 (late) — …`, `# 2026-05-17 wrap — …`,
#            `# 2026-05-17 OVERNIGHT RUN-1 — …` (any suffix after the date).
# A leading pinned block (`# ✅ RESOLVED 2026-05-17 — …`) matches NEITHER —
# the date is not at heading-start — so split_sessions folds it into the
# header rather than archiving it.
SESSION_RE = re.compile(
    r"^# (?:"
    r"s\d+(?:\.\d+)*(?:[–-]s\d+(?:\.\d+)*)? wrap\b"
    r"|\d{4}-\d{2}-\d{2}\b"
    r")",
    re.M,
)

ARCHIVE_HEADER = (
    "# RC session history archive\n"
    "\n"
    "Sessions older than the last 2–3 full sessions are progressively compacted here.\n"
    "Current WAKEUP_NOTES.md keeps only the most recent 2–3 sessions.\n"
    "Compaction rule: 3+ sessions old → 1-2 line summary entry below.\n"
)


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
            sessions.append(block)
        elif not seen_session:
            # Pinned non-session block(s) that precede the first session
            # (e.g. `# ✅ RESOLVED … `). These belong with the header so
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
    between sections — i.e. blank line BEFORE the rule and blank line AFTER.
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


def prune(*, keep: int, dry_run: bool) -> int:
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
        print("(dry-run — no files written)")
        return 0

    _atomic_write(WAKEUP, new_wakeup)
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(ARCHIVE, new_archive)
    print(f"wakeup_prune: WAKEUP_NOTES now has {len(keep_sessions)} session(s); "
          f"archive now has {len(move_sessions) + len(a_sessions)}")
    return 0


def check(keep: int) -> int:
    if not WAKEUP.exists():
        return 0
    text = WAKEUP.read_text(encoding="utf-8")
    _, sessions = split_sessions(text)
    if len(sessions) > keep:
        print(
            f"wakeup_prune --check: WAKEUP_NOTES has {len(sessions)} sessions "
            f"(> keep={keep}); run `py scripts/wakeup_prune.py`",
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
