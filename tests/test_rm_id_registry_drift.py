"""RM-360: the authoritative `RM-NN` id registry may not point at a taken id.

WHY
---
`ROADMAP.md`'s doc table declares `docs/DS_SWEEP_TRACKER.md` the authoritative
`RM-NN` id registry - "take ids from here, never from ROADMAP prose". That line
is prose, nothing reads it, and it has drifted twice:

* 2026-08-14 (LEDGER 1245) - "one 57-id registry collision corrected".
* 2026-09-05 (RM-360, this row) - the pin read `RM-337` while `RM-337` through
  `RM-342` were all live, so a lane obeying the documented rule would have
  minted a SIXTH duplicate.

A repeat is the argument for a guard rather than a third manual correction.
This module is that guard.

WHAT IS ASSERTED
----------------
The id named on the registry's live next-free line must not appear as an
ALLOCATED id anywhere in the scanned corpus. Allocation is the whole difficulty
and is defined in `tools/rm_id_registry.py`; read that module's docstring before
changing anything here.

WHY THIS IS NOT "the id must not appear at all"
------------------------------------------------
Written naively that way the guard is RED on the day it lands, and for a reason
that is not a defect: the next-free id legitimately appears as POINTER prose in
several places at once, because the documented rule is that the tracker line and
the `ROADMAP.md` pin move in the SAME commit. At the time this landed the pinned
id appeared three times - `docs/DS_SWEEP_TRACKER.md:72`, `docs/LEDGER.md:72` and
`ROADMAP.md:55` - and every one of them was a pointer saying "this id is free".
A guard that fires on its own subject being announced as free gets deleted.

The distinction is per-OCCURRENCE, never per-LINE, and `ROADMAP.md:55` is the
line that proves it: it carries `RM-378 OPEN` and a next-free pointer in the
same sentence. A line-scoped predicate calls the pinned id allocated there and
goes red over nothing.

WHY THE SCAN INCLUDES THE ARCHIVES AND THE REFILL DOCS
-------------------------------------------------------
The RM-360 acceptance names `ROADMAP.md`, `BACKLOG.md` and `docs/LEDGER.md`.
Those three are scanned, and four more are scanned TOO, which extends the
acceptance rather than substituting for it:

* `docs/_research_refill_*.md` - a filed row body most often lives here as a
  `### RM-NNN (Row N)` header and is invisible to the three named files. That
  is the miss that made the LANE 10 queue un-derivable (LEDGER 1338 (a)).
* `docs/ROADMAP_HISTORY.md`, `docs/history_notes.md`, and the registry itself -
  a CLOSED row's allocation record is relocated verbatim into an archive, so
  the three named files forget it ever existed. `RM-188` is the measured proof
  and has its own test below.

SYNTHETIC IDS USE THE RESERVED `RM-9xx` BAND
---------------------------------------------
Fixture strings below use `RM-9xx`, never a live-range id. A test file is
tracked `.py`, and the documented way a lane mints an id is a tree-wide grep
over `*.md` and `*.py`; fixtures written with real-range ids would show up in
that grep as phantom allocations. Ids that ARE real - `RM-359`, `RM-188` -
appear only where the assertion is deliberately about the live corpus.

ANTI-VACUITY
------------
`test_the_classifier_finds_real_allocations_in_the_live_corpus` exists because
every assertion above passes trivially if the classifier stops matching. A guard
that cannot fire is worse than no guard: it reports safety it is not checking.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from tools import rm_id_registry as reg

REPO_ROOT = Path(__file__).resolve().parent.parent


class PointerVersusAllocatedPredicate(unittest.TestCase):
    """The classifier, on synthetic text, one shape per test."""

    def test_next_free_pointer_prose_is_not_an_allocation(self) -> None:
        for text in (
            "Next free id = **RM-920** (2026-09-06).",
            "next free id RM-920.",
            "Live next-free id **RM-920**.",
            "**Next free id = RM-920.**",
            "Next free id after both land = RM-920. The",
            "Next free GAP spec = **RM-920**",
            "next free is RM-920, not the RM-919 that line carried",
        ):
            with self.subTest(text=text):
                self.assertEqual(["pointer"], _kinds(text, 920))

    def test_prose_ABOUT_a_pointer_is_not_itself_a_pointer(self) -> None:
        """The cue must be a pin, not a sentence discussing pins.

        Both shapes below are real and recurring. The first is the house mint
        idiom - `docs/LEDGER.md` reads "every RM-379 occurrence was next-free
        pointer prose. RM-379 carries ..." - where the SECOND id sits 25 chars
        behind a "next-free" that belongs to a discussion, not to a pin, and
        RM-379 is allocated by that very entry. The second is `ROADMAP.md`,
        where "Its next-free figure (RM-369) is RETIRED as stale" would
        otherwise clear an id the line above it calls OPEN. Both are cited by
        their TEXT rather than a line number, because both files are prepended
        to or relocated on most cycles and a line number here rots at once.

        The follower words are a measured blocklist, not a guess: a census of
        every `next[-space]free <word>` in tracked `.md` returned "pointer",
        "figure(s)" and "statements" as the only non-pin followers, against
        "id", "GAP spec", "is" and a bare id as the real ones.
        """
        for text in (
            "every RM-919 occurrence was next-free pointer prose. RM-920 carries",
            "Its next-free figure (RM-920) is RETIRED as stale.",
            "Next-free figures in those blocks are superseded; RM-920 OPEN",
            "next-free statements are stale; RM-920 was minted",
        ):
            with self.subTest(text=text):
                self.assertEqual(["allocated"], _kinds(text, 920))

    def test_a_status_marker_makes_it_an_allocation(self) -> None:
        for text in (
            "- **RM-920 OPEN (filed 2026-09-06)** - a thing.",
            "- **RM-920 SHIPPED 2026-09-06 (LEDGER 9999)**",
            "**RM-920 CLOSED** - struck.",
            "RM-920 REFUTED by reading.",
            "### RM-920 (Row 3) - LANE 7, Tier-0. A defect.",
        ):
            with self.subTest(text=text):
                self.assertEqual(["allocated"], _kinds(text, 920))

    def test_a_bare_mention_defaults_to_allocated(self) -> None:
        """Uncertain reads as taken, never as free.

        The guard's job is to stop a collision. A bare mention that turns out to
        be harmless costs one sentence in a failure message; a bare mention
        wrongly cleared costs a duplicate id and a manual correction.
        """
        self.assertEqual(["allocated"], _kinds("see RM-920 for context", 920))

    def test_the_pointer_cue_does_not_leak_to_a_later_id_on_the_same_line(self) -> None:
        """`ROADMAP.md:55` in miniature - one line, one pointer, one allocation."""
        text = "Next free id RM-920. **RM-921 OPEN** in `BACKLOG.md`."
        self.assertEqual(["pointer"], _kinds(text, 920))
        self.assertEqual(["allocated"], _kinds(text, 921))

    def test_an_intervening_id_breaks_the_pointer_cue(self) -> None:
        text = "next free id RM-920, and RM-921 is taken"
        self.assertEqual(["allocated"], _kinds(text, 921))

    def test_the_cue_does_not_reach_across_a_line_break(self) -> None:
        """Deliberate: a cue on the previous line excuses nothing on this one.

        The cost is a red if someone ever wraps a pin between the words and the
        id. That red is explicable in one line and the failure message says so;
        a cue leaking downward would be a silent PASS over a real collision,
        which is the direction that must not happen.
        """
        self.assertEqual(["allocated"], _kinds("Next free id =\nRM-920 OPEN", 920))

    def test_a_longer_id_is_not_matched_by_a_shorter_query(self) -> None:
        self.assertEqual([], _kinds("RM-9201 OPEN is a different id", 920))

    def test_ids_are_matched_by_value_not_by_substring(self) -> None:
        self.assertEqual([], _kinds("RM-92 and RM-9200", 920))


class LivePinParsing(unittest.TestCase):
    def test_pins_are_read_in_document_order(self) -> None:
        text = "Next free id = **RM-99**\nPrior pin: Next free id was **RM-88**\n"
        self.assertEqual([99, 88], reg.pin_ids(text))

    def test_the_live_pin_is_the_first_one_by_POSITION_not_the_highest(self) -> None:
        """Position, not value - and the case is built so the two disagree.

        With a well-formed tracker the first pin IS the highest, so a `max()`
        implementation would pass every realistic input and this assertion
        would prove nothing. The out-of-order text below is the only shape that
        separates them. `TrackerStructure` then asserts the real file is not in
        that shape, so the two tests together say: read by position, and check
        that position still means what it claims.
        """
        text = "Next free id = **RM-88**\nPrior pin: Next free id was **RM-99**\n"
        self.assertEqual(88, reg.live_pin(text))

    def test_a_document_with_no_pin_raises_rather_than_passing_silently(self) -> None:
        with self.assertRaises(reg.RegistryError):
            reg.live_pin("no pointer here")

    def test_the_pin_takes_the_nearest_id_not_a_later_one(self) -> None:
        text = "Next free id = **RM-920** (2026-09-06). RM-919 was minted by"
        self.assertEqual([920], reg.pin_ids(text))


class TrackerStructure(unittest.TestCase):
    """Structural preconditions for reading the live pin off the real file."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = reg.read(REPO_ROOT / reg.PIN_DOC)
        cls.pins = reg.pin_ids(cls.text)

    def test_the_registry_file_exists_and_carries_a_pin(self) -> None:
        self.assertTrue(self.pins, f"{reg.PIN_DOC} carries no 'Next free id' line")

    def test_the_first_pin_is_the_highest_pin_in_the_file(self) -> None:
        """The pin blocks are newest-first, and the live pin is read as the FIRST.

        If a new pin is ever appended BELOW an older one, `live_pin` silently
        returns a stale id and every assertion in this module then guards the
        wrong number. That failure is invisible without this assertion.
        """
        self.assertEqual(
            max(self.pins),
            self.pins[0],
            "the newest pin is not first in "
            f"{reg.PIN_DOC}; pins in document order are {self.pins}. "
            "Move the new pin above the older ones, or `live_pin` guards a "
            "stale id.",
        )


class NextFreeIdIsActuallyFree(unittest.TestCase):
    """The row's acceptance, against the live tree."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.result = reg.audit(REPO_ROOT)

    def test_the_scan_covers_the_three_files_the_row_names(self) -> None:
        scanned = {p.relative_to(REPO_ROOT).as_posix() for p in self.result.scanned}
        for required in ("ROADMAP.md", "BACKLOG.md", "docs/LEDGER.md"):
            self.assertIn(required, scanned)

    def test_the_scan_reaches_the_research_refill_docs(self) -> None:
        """Row bodies live here, so a census that skips them is blind."""
        scanned = {p.relative_to(REPO_ROOT).as_posix() for p in self.result.scanned}
        self.assertTrue(
            any(p.startswith("docs/_research_refill_") for p in scanned),
            f"no refill doc reached the scan; scanned {sorted(scanned)}",
        )

    def test_the_scan_reaches_the_relocated_history_docs(self) -> None:
        """A shipped row's allocation record often survives ONLY in an archive.

        `ROADMAP.md:28` relocates closed rows VERBATIM into
        `docs/ROADMAP_HISTORY.md`, which takes their `RM-NN` heading with them.
        Measured at the commit this landed in: `RM-188` carries a `REFUTED`
        marker in `docs/ROADMAP_HISTORY.md` (the row reading "DO NOT RE-FILE
        THIS") and appeared ZERO times in `ROADMAP.md`, `BACKLOG.md`,
        `docs/LEDGER.md` or the refill docs. A scan of the three acceptance
        files alone would have cleared RM-188 as free, which is the exact
        collision this guard exists to prevent - so the archives are scanned
        too.

        That zero is a SNAPSHOT and has already moved: the ledger entry for
        this row discusses RM-188 by name, so the acceptance docs now mention
        it. Which is precisely why the assertion below is "the archive still
        shows it", not "the acceptance docs do not" - the second form would
        have been a test that quietly stopped testing anything.
        """
        scanned = {p.relative_to(REPO_ROOT).as_posix() for p in self.result.scanned}
        for required in (
            "docs/ROADMAP_HISTORY.md",
            "docs/history_notes.md",
            reg.PIN_DOC,
        ):
            self.assertIn(required, scanned)

    def test_an_id_allocated_only_in_an_archive_is_still_seen_as_taken(self) -> None:
        """The RM-188 case itself, pinned so the scan cannot quietly shrink."""
        archive = reg.read(REPO_ROOT / "docs/ROADMAP_HISTORY.md")
        self.assertTrue(
            reg.allocated(archive, 188),
            "RM-188 is REFUTED in docs/ROADMAP_HISTORY.md but the "
            "classifier no longer sees it as allocated",
        )

    def test_the_pinned_next_free_id_is_not_allocated_anywhere(self) -> None:
        self.assertEqual(
            [],
            list(self.result.collisions),
            "\n"
            + reg.describe(self.result)
            + "\n\nThe registry pin names an id that is already taken. Re-derive "
            "the true next-free id and update BOTH `docs/DS_SWEEP_TRACKER.md` "
            "and the `ROADMAP.md` pin in the SAME commit.",
        )

    def test_the_classifier_finds_real_allocations_in_the_live_corpus(self) -> None:
        """Anti-vacuity: prove the guard can still fire.

        Every other assertion here passes trivially if the classifier stops
        matching anything. This pins that a known-taken id is still SEEN as
        taken, so a green above means "checked and clear", not "checked
        nothing". RM-359 is used because it shipped (LEDGER 1350) and is
        therefore permanently allocated.
        """
        found = 0
        for path in self.result.scanned:
            found += len(reg.allocated(reg.read(path), 359))
        self.assertGreater(
            found,
            0,
            "the classifier found no allocated occurrence of the shipped id "
            "RM-359 anywhere in the corpus, so this guard is not actually "
            "checking anything",
        )


def _kinds(text: str, rm_id: int) -> list[str]:
    return [occ.kind for occ in reg.occurrences(text, rm_id)]


if __name__ == "__main__":
    unittest.main()
