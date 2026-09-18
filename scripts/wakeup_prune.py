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
    $env:LOCALAPPDATA/Programs/Python/Python314/python.exe scripts/wakeup_prune.py            # prune to default keep=3
    $env:LOCALAPPDATA/Programs/Python/Python314/python.exe scripts/wakeup_prune.py --keep 2   # keep only the last 2 sessions
    $env:LOCALAPPDATA/Programs/Python/Python314/python.exe scripts/wakeup_prune.py --dry-run  # report what would move; no writes
    $env:LOCALAPPDATA/Programs/Python/Python314/python.exe scripts/wakeup_prune.py --check    # exit 1 if more than --keep sessions
                                          # remain in WAKEUP_NOTES.md
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import NamedTuple

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


class Block(NamedTuple):
    """One parsed block plus the EXACT bytes that preceded it on disk.

    RM-276 (4d) SEPARATOR-INVENTION. `render` joins every block with `SEP`,
    so the moment `_split_on_interior_headings` cuts a glued block into two
    entries, re-rendering INSERTS a `\\n---\\n\\n` rule that was never in the
    file. On `docs/history_notes.md` that is 54 cut points and 142 inserted
    lines, and `prune()` writes the whole re-render back over the protected
    append-only archive. Splitting glued sessions is CORRECT - counting them
    separately is the entire point of RM-276 - so the fix is not to stop
    splitting but to stop inventing: each block remembers its own `sep`
    (`SEP` for a genuinely separated block, `""` for a piece that was glued
    to the one before it), and `render_blocks` replays exactly that.
    """

    sep: str
    body: str


def split_blocks(text: str) -> tuple[str, list[Block]]:
    """Return (header_text, [Block,...]) such that

        header_text + "".join(b.sep + b.body for b in blocks) == text

    byte for byte. That identity is what `render_blocks` relies on, and it is
    asserted against both tracked files by
    `tests/phase7_polish/test_wakeup_prune.py` TestSplitRenderIsByteStable -
    on the real files, not by construction, so a parsing regression is caught.
    """
    header, *rest = text.split(SEP)
    # RM-276 (4a) FIRST-PART BLINDNESS. `parts[0]` used to be taken as the
    # pinned header unconditionally, without ever being scanned. A /done
    # append that omits the separator before its heading therefore landed
    # that session INSIDE the header block - the one block prune never
    # archives - so the newest sessions became structurally unprunable while
    # the tool reported success. Cut the header at its FIRST heading and hand
    # the remainder to the same per-block path as everything else. This is
    # done BEFORE any separator-presence test on purpose: the header must be
    # split at a heading "rather than by assuming a separator", which also
    # means a file carrying no separator at all is no longer reported empty.
    raw: list[Block] = []
    first = SESSION_RE.search(header)
    if first is not None:
        # Glued into the header, so NOTHING separated it on disk: sep = "".
        raw.append(Block("", header[first.start():]))
        header = header[: first.start()]
    raw.extend(Block(SEP, part) for part in rest)
    if not raw:
        return text, []
    leading_pins: list[Block] = []
    # RM-276 (4c) OUT-OF-POSITION HOIST. There used to be a third bucket,
    # `trailing_extras`, holding every zero-heading block seen AFTER the first
    # session, and `return sessions + trailing_extras` appended it at the FILE
    # TAIL. That is a reorder, and `prune()` re-renders the WHOLE archive via
    # `render(a_header, move_sessions + a_sessions)`, so the reorder is written
    # back to `docs/history_notes.md` - the protected append-only archive the
    # repo's no-history-rewrite rule exists to defend. The hoist PRE-DATES the
    # (4a)/(4b) fixes above: a fixture `H, S1, ZERO-note, S2` returned
    # `[S1, S2, ZERO-note]` on both sides of them. It was merely INVISIBLE on
    # the real archive, because every non-matching block happened to sit
    # contiguously at the tail already, which made the hoist a byte-identical
    # no-op. Closing (4b) turned 63 of those blocks into in-place sessions and
    # left 32 zero-heading blocks interleaved among them, which ACTIVATED the
    # hoist and moved 5.7 MB of history out of order.
    #
    # The cause is the separate bucket, not the archive, so the bucket is
    # GONE: a zero-heading block after the first session is appended to
    # `sessions` AT ITS OWN INDEX. Nothing is dropped (same blocks, same
    # count) and nothing moves. Do NOT reintroduce a tail bucket, and do NOT
    # "fix" a future reorder by skipping the re-render - order preservation is
    # the invariant, and `tests/phase7_polish/test_wakeup_prune.py`
    # TestSplitRenderIsByteStable asserts it against both tracked files.
    blocks: list[Block] = []
    seen_session = False
    for block in raw:
        # RM-276 (4b) INTERIOR-HEADING-IN-A-LATER-BLOCK BLINDNESS. This gate
        # was `SESSION_RE.match(block.lstrip("\n"))`, which admitted only a
        # block that STARTS with a heading. A block that does not start with
        # one but CONTAINS one fell straight through to the two branches
        # below and was appended WHOLE: into `leading_pins` (folded into the
        # header, hence unarchivable) or into `trailing_extras` (so several
        # glued sessions counted as one). That fires with ZERO headings in
        # `parts[0]`, so the (4a) fix above provably cannot reach it - the
        # gate itself was the defect. `search` subsumes the old
        # `match(lstrip)` form because SESSION_RE is `re.M`-anchored.
        if SESSION_RE.search(block.body):
            seen_session = True
            # A missing separator can glue several sessions into one block;
            # re-split so each is counted independently. Any non-heading
            # preamble ahead of the first heading rides with the first
            # sub-block, so nothing is dropped and nothing is reordered. The
            # pieces are CONTIGUOUS slices of `block.body`, so every piece
            # after the first was glued: sep = "".
            pieces = _split_on_interior_headings(block.body)
            blocks.append(Block(block.sep, pieces[0]))
            blocks.extend(Block("", piece) for piece in pieces[1:])
        elif not seen_session:
            # Pinned non-session block(s) that precede the first session
            # (e.g. `# <U+2705> RESOLVED ... `). These belong with the header so
            # they are never archived and stay at the top of WAKEUP_NOTES.
            leading_pins.append(block)
        else:
            # Unexpected non-session block AFTER sessions began (e.g. a
            # stray separator / malformed block). Preserve it IN POSITION -
            # see the (4c) note above. Appending here, rather than into a
            # tail bucket, is what makes split -> render byte-stable.
            blocks.append(block)
    # Fold the pins into the header with their OWN separators, not with a
    # canonical `render` pass - the same (4d) no-invention rule.
    for pin in leading_pins:
        header = header + pin.sep + pin.body
    return header, blocks


def split_sessions(text: str) -> tuple[str, list[str]]:
    """Return (header_block, [session_blocks_newest_first]).

    A "session block" is the body of a session entry (without the leading
    `\\n---\\n\\n` separator). Order is preserved as it appears in the file
    (newest first by RC convention).

    Thin projection of `split_blocks`, kept because it is the historical
    public surface. It DROPS each block's separator, so a caller that
    re-renders from this view cannot be byte-faithful - use `split_blocks` +
    `render_blocks` when the target is `docs/history_notes.md`.
    """
    header, blocks = split_blocks(text)
    return header, [b.body for b in blocks]


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


def render_blocks(header: str, blocks: list[Block]) -> str:
    """Faithful inverse of `split_blocks`: replay each block's own separator.

    Unlike `render`, this invents nothing and normalises nothing, so it
    reproduces the parsed file byte for byte. Use it for
    `docs/history_notes.md`, which the no-history-rewrite rule protects.
    """
    return header + "".join(b.sep + b.body for b in blocks)


def prepend_sessions(
    header: str, blocks: list[Block], new_bodies: list[str]
) -> tuple[str, list[Block]]:
    """Insert `new_bodies` newest-first ahead of `blocks`, as a PURE INSERTION.

    The result satisfies

        render_blocks(out_header, out_blocks).endswith(
            render_blocks(header, blocks)[len(out_header):])

    i.e. not one pre-existing byte after the insertion point is rewritten,
    moved or re-spaced. The awkward case is a first block whose `sep` is `""`
    because it was glued into the header: the visual break between header and
    that block lived in the HEADER's trailing newline run, so that run is
    moved intact to sit ahead of the block again rather than being replaced
    by a `---` rule the archive never had.
    """
    if not new_bodies:
        return header, list(blocks)
    fresh = [Block(SEP, b.rstrip("\n") + "\n") for b in new_bodies]
    out = list(blocks)
    if out and out[0].sep == "":
        stem = header.rstrip("\n")
        glue = header[len(stem):] or "\n\n"
        fresh[-1] = Block(fresh[-1].sep, fresh[-1].body.rstrip("\n") + glue)
        header = stem
    return header, fresh + out


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

    # The archive is the protected append-only history, so it is parsed and
    # re-rendered through the FAITHFUL pair - `split_blocks` / `render_blocks`
    # via `prepend_sessions` - not through `render`, which would normalise
    # every glued boundary in 5.7 MB of history into a `---` rule it never
    # had. WAKEUP_NOTES above deliberately keeps the canonical `render`: it is
    # the live working file, and repairing a malformed separator there is the
    # documented behaviour (TestRender.test_render_repairs_buggy_input).
    if ARCHIVE.exists():
        a_header, a_blocks = split_blocks(ARCHIVE.read_text(encoding="utf-8"))
    else:
        a_header = ARCHIVE_HEADER
        a_blocks = []
    new_archive = render_blocks(*prepend_sessions(a_header, a_blocks, move_sessions))

    if dry_run:
        print("(dry-run - no files written)")
        return 0

    _atomic_write(WAKEUP, new_wakeup)
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(ARCHIVE, new_archive)
    print(f"wakeup_prune: WAKEUP_NOTES now has {len(keep_sessions)} session(s); "
          f"archive now has {len(move_sessions) + len(a_blocks)}")
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
            f"(> keep={keep}); run `$env:LOCALAPPDATA/Programs/Python/Python314/python.exe scripts/wakeup_prune.py`",
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
