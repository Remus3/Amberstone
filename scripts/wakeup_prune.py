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
# Accepts single sessions (`# s171 wrap`), sub-sessions (`# s171.8 wrap`),
# and en-dash/hyphen ranges (`# s209–s213 wrap`, `# s209-s213 wrap`).
SESSION_RE = re.compile(
    r"^# s\d+(?:\.\d+)*(?:[–-]s\d+(?:\.\d+)*)? wrap\b", re.M,
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
    sessions: list[str] = []
    extras: list[str] = []
    for block in rest:
        if SESSION_RE.match(block.lstrip("\n")):
            sessions.append(block)
        else:
            # Unexpected non-session block (e.g. a stray separator). Preserve
            # it at the tail so we never silently drop content.
            extras.append(block)
    return header, sessions + extras


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
    moved_ids = [SESSION_RE.search(b).group(0) for b in move_sessions]
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
