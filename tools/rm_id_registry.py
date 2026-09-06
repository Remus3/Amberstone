"""RM-360: read the authoritative `RM-NN` id registry, and tell allocated ids
from pointer prose.

`ROADMAP.md`'s doc table declares `docs/DS_SWEEP_TRACKER.md` the authoritative
`RM-NN` id registry - "take ids from here, never from ROADMAP prose". Nothing
read that line, so it drifted twice: a 57-id collision corrected 2026-08-14
(LEDGER 1245), then a six-id staleness filed as RM-360 itself.

Two users:

* `tests/test_rm_id_registry_drift.py` - the guard, so the NEXT drift fails CI
  instead of producing a duplicate id.
* a lane about to mint an id - `python tools/rm_id_registry.py` prints the pin,
  the verdict, and every occurrence that made it, which is the check a lane
  currently performs by hand and sometimes skips.

THE HARD PART IS "ALLOCATED", NOT THE PARSING
----------------------------------------------
An id occurrence means one of three things, and only the first two matter:

* ALLOCATED - it heads a filed row body (`### RM-360 (Row 17) - ...`,
  `- **RM-291 OPEN ...`) or carries a status marker (`OPEN`, `FILED`,
  `SHIPPED`, `CLOSED`, `DONE`, `REFUTED`, `PARTIAL`). The id is taken.
* POINTER - it is the subject of next-free prose (`Next free id = **RM-380**`).
  The id is being announced as FREE, which is the opposite of taken.
* a bare mention - graded ALLOCATED, see below.

THREE RULES, EACH PAID FOR BY A REAL LINE IN THIS REPO
-------------------------------------------------------
1. **Per-occurrence, never per-line.** `ROADMAP.md:55` carries `RM-378 OPEN`
   and `Next free id RM-380` in one sentence. A line-scoped predicate grades
   `RM-380` allocated there and the guard is red on arrival over nothing.

2. **A pointer cue is cancelled by an intervening id.** `Next free id RM-380.
   RM-379 was minted by` - the cue belongs to `RM-380` only. Without this rule
   the cue leaks rightward and clears ids that are genuinely taken.

3. **Bare mentions default to ALLOCATED.** Uncertain reads as taken. A false
   positive costs one sentence in a failure message; a false negative costs a
   duplicate id and a manual correction, which is the defect this exists to
   stop. Same reason the cue does not cross a newline: a wrapped pin gives an
   explicable red, a downward-leaking cue gives a silent pass.

Ids are compared BY VALUE. `RM-380` must not match inside `RM-3801`, and
`RM-38` must not match a query for `RM-380`.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The authoritative registry. `ROADMAP.md` prose points every lane here.
PIN_DOC = "docs/DS_SWEEP_TRACKER.md"

#: Named by the RM-360 acceptance.
ACCEPTANCE_DOCS = ("ROADMAP.md", "BACKLOG.md", "docs/LEDGER.md")

#: Where an allocation record goes when a row CLOSES. `ROADMAP.md:28` relocates
#: shipped rows VERBATIM into `docs/ROADMAP_HISTORY.md`, heading and all, and
#: `docs/history_notes.md` is the deeper archive of the same. Measured AT THE
#: COMMIT THIS LANDED IN: `RM-188` is `REFUTED` in `docs/ROADMAP_HISTORY.md`
#: (the row reading "DO NOT RE-FILE THIS") with 8 allocated occurrences across
#: the two archives, and appeared ZERO times in the three acceptance docs, so a
#: scan of those alone would have cleared a taken id. That count is a snapshot,
#: not an invariant - the ledger entry for this very row then mentioned RM-188
#: and raised the total, which is why the test asserts the ARCHIVE still shows
#: it rather than asserting the acceptance docs do not. The
#: registry is scanned too - it records its own allocations ("RM-130..RM-134
#: allocated") in the file otherwise opened only for the pin.
ARCHIVE_DOCS = ("docs/ROADMAP_HISTORY.md", "docs/history_notes.md", PIN_DOC)

#: Row bodies live here as `### RM-NNN (Row N)` headers and are invisible to the
#: three files above. Scanning them EXTENDS the acceptance; it does not replace
#: it. Skipping them is the miss that made the LANE 10 queue un-derivable
#: (LEDGER 1338 finding (a)).
REFILL_GLOB = "docs/_research_refill_*.md"

_ID = re.compile(r"RM-(\d{2,3})(?!\d)")
_PIN = re.compile(r"next[-\s]free\s+id\b.{0,60}?RM-(\d{2,3})(?!\d)", re.IGNORECASE)
#: A pin, not a sentence ABOUT pins. The negative lookahead is a measured
#: blocklist: a census of every `next[-space]free <word>` in tracked `.md`
#: returned "pointer", "figure(s)" and "statements" as the only followers that
#: DISCUSS a pointer, against "id", "GAP spec", "is" and a bare id as the ones
#: that ARE one. Without it the house mint idiom in `docs/LEDGER.md` - the
#: sentence "every RM-379 occurrence was next-free pointer prose. RM-379
#: carries ..." - clears an id the same entry allocates. (Cited by its text,
#: not its line: an entry is prepended to that file every cycle, so a line
#: number here rots within a day. Same reason the archive is cited by its row
#: text above.)
_CUE = re.compile(
    r"next[-\s]free(?!\s+(?:pointer|figure|figures|statement|statements)\b)",
    re.IGNORECASE,
)
_MARKER = re.compile(
    r"[\s*_`\"'.,;:()\[\]-]{0,6}(OPEN|FILED|SHIPPED|CLOSED|DONE|REFUTED|PARTIAL)\b"
)

#: How far back a pointer cue may sit. The longest real one is
#: "Next free id after both land = **RM-205**" at 24 chars; 80 leaves room
#: without letting the cue wander to an unrelated sentence.
_LOOKBACK = 80


class RegistryError(RuntimeError):
    """The registry could not be read the way this module requires."""


@dataclass(frozen=True)
class Occurrence:
    """One `RM-NN` token, graded."""

    rm_id: int
    kind: str  # "allocated" | "pointer"
    line: int
    excerpt: str


@dataclass(frozen=True)
class AuditResult:
    pin: int
    scanned: tuple[Path, ...]
    collisions: tuple[tuple[str, Occurrence], ...]


def read(path: Path) -> str:
    """Read a doc as text without letting an encoding surprise pass silently."""
    return path.read_text(encoding="utf-8", errors="strict")


def pin_ids(text: str) -> list[int]:
    """Every next-free pin in the document, in document order."""
    return [int(m.group(1)) for m in _PIN.finditer(text)]


def live_pin(text: str) -> int:
    """The current pin.

    The pin blocks are newest-first, so the live one is the FIRST. The guard
    asserts separately that the first pin is also the highest, because a pin
    appended below an older one would otherwise be read silently and wrongly.
    """
    pins = pin_ids(text)
    if not pins:
        raise RegistryError("no 'Next free id' line found")
    return pins[0]


def classify(text: str, start: int) -> str:
    """Grade the id occurrence beginning at `start`. See the module docstring."""
    window_start = max(0, start - _LOOKBACK)
    window = text[window_start:start]
    # Rule 3: a cue on a previous line excuses nothing on this one.
    newline = window.rfind("\n")
    if newline != -1:
        window = window[newline + 1 :]
    cues = list(_CUE.finditer(window))
    if cues:
        between = window[cues[-1].end() :]
        # Rule 2: the cue belongs to the FIRST id after it, and no other.
        if not _ID.search(between):
            return "pointer"
    return "allocated"


def occurrences(text: str, rm_id: int) -> list[Occurrence]:
    """Every occurrence of one id, graded, with a line number and an excerpt."""
    found: list[Occurrence] = []
    for match in _ID.finditer(text):
        if int(match.group(1)) != rm_id:
            continue
        start = match.start()
        found.append(
            Occurrence(
                rm_id=rm_id,
                kind=classify(text, start),
                line=text.count("\n", 0, start) + 1,
                excerpt=_excerpt(text, start, match.end()),
            )
        )
    return found


def allocated(text: str, rm_id: int) -> list[Occurrence]:
    return [occ for occ in occurrences(text, rm_id) if occ.kind == "allocated"]


def scan_paths(root: Path) -> tuple[Path, ...]:
    """Every doc the collision check reads."""
    paths = [root / name for name in ACCEPTANCE_DOCS + ARCHIVE_DOCS]
    missing = [p for p in paths if not p.is_file()]
    if missing:
        raise RegistryError(
            "the acceptance docs are not all present: "
            + ", ".join(p.name for p in missing)
        )
    paths.extend(sorted(root.glob(REFILL_GLOB)))
    return tuple(paths)


def audit(root: Path = REPO_ROOT) -> AuditResult:
    """Is the pinned next-free id actually free?"""
    pin = live_pin(read(root / PIN_DOC))
    scanned = scan_paths(root)
    collisions: list[tuple[str, Occurrence]] = []
    for path in scanned:
        rel = path.relative_to(root).as_posix()
        for occ in allocated(read(path), pin):
            collisions.append((rel, occ))
    return AuditResult(pin=pin, scanned=scanned, collisions=tuple(collisions))


def describe(result: AuditResult) -> str:
    lines = [
        f"{PIN_DOC} pins next-free id RM-{result.pin}.",
        f"Scanned {len(result.scanned)} docs.",
    ]
    if not result.collisions:
        lines.append("No allocated occurrence found - the id is free.")
        return "\n".join(lines)
    lines.append(f"ALLOCATED in {len(result.collisions)} place(s):")
    for rel, occ in result.collisions:
        lines.append(f"  {rel}:{occ.line}  {occ.excerpt}")
    return "\n".join(lines)


def _excerpt(text: str, start: int, end: int, span: int = 55) -> str:
    left = text.rfind("\n", 0, start) + 1
    right = text.find("\n", end)
    if right == -1:
        right = len(text)
    line = text[left:right]
    at = start - left
    lo = max(0, at - span)
    hi = min(len(line), at + span)
    return ("..." if lo else "") + line[lo:hi].strip() + ("..." if hi < len(line) else "")


def main() -> int:
    result = audit()
    print(describe(result))
    return 1 if result.collisions else 0


if __name__ == "__main__":
    sys.exit(main())
