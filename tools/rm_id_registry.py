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


#: A marker on a `ROADMAP.md` id cancels "this row is a bare OPEN". `PARTIAL`
#: is in here and NOT in `BACKLOG_CLOSED_MARKERS` on purpose: a row reading
#: "RM-321 PARTIAL - 4 REMAIN OPEN" is honestly open-ish in ROADMAP and is not
#: a closed body in BACKLOG, so it must not be reported in either direction.
BARE_OPEN_CANCELLERS = frozenset({"SHIPPED", "CLOSED", "DONE", "REFUTED", "PARTIAL"})

#: A `BACKLOG.md` row-leading marker that says the body is finished.
BACKLOG_CLOSED_MARKERS = frozenset({"SHIPPED", "CLOSED", "DONE", "REFUTED"})

#: Delimiter text that may join two ids in a ROADMAP enumeration. Anything
#: else ends the run - see `roadmap_dispositions`.
_ENUM_SEP = re.compile(r"^[\s/,+&*_`\"'()\[\].:;|-]*$")

#: A `BACKLOG.md` row body opener - `- **RM-250 ...`, with the bold optional.
_ROW_HEAD = re.compile(r"^\s*[-*]\s+\*{0,2}RM-(\d{2,3})(?!\d)")

#: A lowercase letter means prose has started, so anything past it is no longer
#: the row-leading disposition. See `backlog_row_dispositions`.
_PROSE = re.compile(r"[a-z]")


@dataclass(frozen=True)
class Disposition:
    """One status marker, bound to one id, with a citable line."""

    rm_id: int
    marker: str
    line: int
    excerpt: str


@dataclass(frozen=True)
class DispositionDrift:
    """A ROADMAP row that still says OPEN over a finished BACKLOG body."""

    rm_id: int
    roadmap: Disposition
    backlog: Disposition


def roadmap_dispositions(text: str) -> dict[int, list[Disposition]]:
    """Bind every status marker in `ROADMAP.md` prose to the ids it governs.

    A marker binds to the maximal RUN of ids that ends immediately before it,
    where consecutive run members - and the last member and the marker - are
    joined by DELIMITER TEXT ONLY (`_ENUM_SEP`). Both halves are paid for by a
    real line in this repo:

    * `RM-250 / RM-251 OPEN` - the marker governs BOTH ids. Binding only to
      the nearest one silently clears `RM-250`, which is the drift this exists
      to catch.
    * `RM-281 HALF-CLOSED + RM-283 OPEN` - the run stops at `RM-283`, because
      the text back to `RM-281` carries the word `CLOSED` and is therefore not
      delimiter-only. Binding the `OPEN` to `RM-281` is a FALSE POSITIVE on a
      row that is correctly half-closed, and it is the single most important
      negative control on this function.

    The same rule defuses a ROADMAP "pointer cluster" - a line naming a dozen
    ids and then, after a sentence of prose, saying `Still OPEN: RM-358`. The
    prose is not delimiter text, so the run before that `OPEN` is EMPTY and the
    dozen ids inherit nothing. `ROADMAP.md`'s SHIPPED/CLOSED cluster line is
    exactly that shape.

    Scanning is per LINE. A ROADMAP row is one line, so a marker may never
    reach backwards into the row above it.
    """
    found: dict[int, list[Disposition]] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        ids = [(m.start(), m.end(), int(m.group(1))) for m in _ID.finditer(line)]
        for marker in _MARKER.finditer(line):
            cursor = marker.start(1)
            for id_start, id_end, rm_id in reversed(ids):
                if id_end > cursor:
                    continue
                if not _ENUM_SEP.match(line[id_end:cursor]):
                    break
                found.setdefault(rm_id, []).append(
                    Disposition(
                        rm_id=rm_id,
                        marker=marker.group(1),
                        line=number,
                        excerpt=_excerpt(line, id_start, id_end),
                    )
                )
                cursor = id_start
    return found


def backlog_row_dispositions(text: str) -> dict[int, Disposition]:
    """The ROW-LEADING disposition of each `BACKLOG.md` row body.

    A row body opens `- **RM-250 FIRST HALF SHIPPED ...`, so the disposition is
    the FIRST marker after the id - but only while nothing but SHOUTED
    QUALIFIER text separates them. Two rules, each measured on this tree:

    * no intervening `RM-NN`, so a row cannot claim its neighbour's verb;
    * no LOWERCASE letter in the gap, because lowercase means the row has
      started explaining itself and any marker beyond that point is prose, not
      a disposition. `BACKLOG.md`'s `RM-204` row is the control: it opens
      `- **RM-204 (OPERATOR-GATED) - the Arena augment play-line is ...` and
      its first vocabulary hit sits far downstream inside that sentence.
      Without the lowercase rule RM-204 is reported as a fifth drifted id, and
      the honest fix is this predicate, never an allowlist.

    The uppercase gap is allowed rather than banned because the two real
    closed rows need it: `RM-250 FIRST HALF SHIPPED` and `RM-291 FULLY CLOSED`.

    Note this is deliberately NOT the run rule used for ROADMAP. There a marker
    governs an ENUMERATION, so a non-delimiter joiner must end it; here it
    governs the single id its own row is about.
    """
    found: dict[int, Disposition] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        head = _ROW_HEAD.match(line)
        if head is None:
            continue
        rm_id = int(head.group(1))
        if rm_id in found:
            continue  # the first body wins; later ones are follow-up notes
        rest = line[head.end() :]
        marker = _MARKER.search(rest)
        if marker is None:
            continue
        gap = rest[: marker.start(1)]
        if _ID.search(gap) or _PROSE.search(gap):
            continue
        found[rm_id] = Disposition(
            rm_id=rm_id,
            marker=marker.group(1),
            line=number,
            excerpt=_excerpt(line, head.start(1), head.end(1)),
        )
    return found


def disposition_drift(
    roadmap_text: str, backlog_text: str
) -> tuple[DispositionDrift, ...]:
    """Every id ROADMAP still calls OPEN whose BACKLOG body is finished.

    "Bare OPEN" means the id carries an `OPEN` marker in ROADMAP and carries no
    `BARE_OPEN_CANCELLERS` marker there - a row already reading
    `RM-302 SHIPPED ...; RM-301 OPEN` has told the reader the truth about
    RM-302 and is not drift.
    """
    roadmap = roadmap_dispositions(roadmap_text)
    backlog = backlog_row_dispositions(backlog_text)
    drifted: list[DispositionDrift] = []
    for rm_id, marks in sorted(roadmap.items()):
        markers = {d.marker for d in marks}
        if "OPEN" not in markers or markers & BARE_OPEN_CANCELLERS:
            continue
        body = backlog.get(rm_id)
        if body is None or body.marker not in BACKLOG_CLOSED_MARKERS:
            continue
        opens = [d for d in marks if d.marker == "OPEN"]
        drifted.append(DispositionDrift(rm_id=rm_id, roadmap=opens[0], backlog=body))
    return tuple(drifted)


def describe_drift(drifted: tuple[DispositionDrift, ...]) -> str:
    """A failure message that names the two lines a reader has to reconcile."""
    if not drifted:
        return "No ROADMAP/BACKLOG disposition drift."
    lines = [f"{len(drifted)} RM row(s) say OPEN in ROADMAP over a finished body:"]
    for row in drifted:
        lines.append(
            f"  RM-{row.rm_id}: ROADMAP.md:{row.roadmap.line} says OPEN"
            f"  |  BACKLOG.md:{row.backlog.line} says {row.backlog.marker}"
        )
        lines.append(f"      ROADMAP.md:{row.roadmap.line}  {row.roadmap.excerpt}")
        lines.append(f"      BACKLOG.md:{row.backlog.line}  {row.backlog.excerpt}")
    lines.append(
        "Reconcile ROADMAP.md against the BACKLOG.md body: change the "
        "disposition word (and drop the `[!]` marker where it no longer "
        "applies), keeping the row's surviving content. If the BACKLOG body is "
        "the stale half, fix THAT instead - never silence this guard."
    )
    return "\n".join(lines)


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
