"""RM-403: `ROADMAP.md` may not call a row OPEN over a finished `BACKLOG.md` body.

WHY
---
RC tracks work as `RM-NN` rows in two places. `ROADMAP.md` carries the active
lanes; `BACKLOG.md` carries the bodies. The two are updated by different
sessions, and a row that ships gets its BACKLOG body rewritten while the
ROADMAP pointer is left alone. Nothing reads the pair, so the ROADMAP keeps
advertising work that is done.

Measured on this tree before the guard landed, each confirmed shipped by BOTH a
`docs/LEDGER.md` entry and a code probe:

* `RM-250` - ROADMAP said OPEN, BACKLOG said FIRST HALF SHIPPED (LEDGER 1333).
  Only the RM-250 half was stale; `RM-251` on the same ROADMAP line is
  genuinely open, which is why the binding rule below has to split them.
* `RM-291` - ROADMAP said OPEN, BACKLOG said FULLY CLOSED (LEDGER 1331/1332).
* `RM-387` - ROADMAP said OPEN, BACKLOG said SHIPPED (LEDGER 1368).
* `RM-388` - ROADMAP said OPEN, BACKLOG said SHIPPED (LEDGER 1369).

The cost is not cosmetic. A lane picking its next item off the ROADMAP picks a
row that is already shipped, and rediscovery is the standing failure mode this
repo spends the most on.

WHAT IS ASSERTED
----------------
No `RM-NN` carries a bare `OPEN` disposition in `ROADMAP.md` while its
row-leading disposition in `BACKLOG.md` is SHIPPED / CLOSED / REFUTED / DONE.

"Bare" matters: a ROADMAP row reading `RM-302 SHIPPED ...; RM-301 OPEN` has
already told the reader the truth about RM-302, so RM-302 is not drift.

THE BINDING RULE IS THE WHOLE DIFFICULTY
-----------------------------------------
A disposition word binds to the NEAREST PRECEDING id, and a naive per-line
regex gets this wrong in both directions. Both parsers live in
`tools/rm_id_registry.py` and both are exercised here on synthetic text before
they are trusted against the live docs:

* `ROADMAP.md` - a marker governs the maximal DELIMITER-JOINED run of ids that
  ends at it. `RM-250 / RM-251 OPEN` gives BOTH ids the OPEN;
  `RM-281 HALF-CLOSED + RM-283 OPEN` gives it to RM-283 ONLY, because the text
  back to RM-281 is not delimiter-only. That second line is real, RM-281 is
  correctly half-closed, and binding its OPEN wrongly is the most important
  false positive this guard can produce.
* a ROADMAP "pointer cluster" line names a dozen ids and then, a sentence
  later, says `Still OPEN: RM-358`. Prose is not delimiter text, so the run
  before that OPEN is empty and the dozen ids inherit nothing.
* `BACKLOG.md` - the row-leading marker is the first one after the row's own
  id, reachable across SHOUTED QUALIFIERS only (`RM-250 FIRST HALF SHIPPED`,
  `RM-291 FULLY CLOSED`). A lowercase letter in the gap means prose has begun
  and the row carries no disposition. Without that rule `RM-204` - whose row
  opens `(OPERATOR-GATED) - the Arena augment play-line is ...` - is reported
  as a fifth drifted id off a vocabulary word buried in its sentence.

Ids are compared BY VALUE through the existing `_ID` pattern, so `RM-250` never
matches inside `RM-2501` and is never confused with `RM-350`.

NO EXTERNAL BINARY
------------------
`tools/rm_id_registry.py` is pure text - no subprocess, no `git`, no network.
That is why it is reused here rather than shelling out to `git grep`: a guard
that ERRORS when a binary is absent is a guard that gets skipped (RM-392 /
RM-393).

ANTI-VACUITY
------------
Every assertion of the form "the drift set is empty" passes trivially if the
parser stops matching. `ParserFindsRealContent` therefore pins that both live
docs yield a non-trivial number of ids AND a non-trivial number of real
disposition markers, and `SyntheticPositiveControl` pins that a constructed
drifted pair is still DETECTED after the live docs are clean - so a green above
means "checked and clear", never "checked nothing".

SYNTHETIC IDS USE THE RESERVED `RM-9xx` BAND
---------------------------------------------
Fixture strings use `RM-9xx`, never a live-range id, for the reason
`tests/test_rm_id_registry_drift.py` gives: a lane mints an id with a tree-wide
grep over `*.md` and `*.py`, and real-range fixtures would show up in it as
phantom allocations. Real ids appear only where the assertion is deliberately
about the live corpus.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from tools import rm_id_registry as reg

REPO_ROOT = Path(__file__).resolve().parent.parent

ROADMAP = "ROADMAP.md"
BACKLOG = "BACKLOG.md"
LEDGER = "docs/LEDGER.md"

#: Live-doc floors for the anti-vacuity arms. Deliberately far below the real
#: figures (measured in the low hundreds on both docs when this landed) so an
#: ordinary relocation pass never reds them, while a parser that quietly stops
#: matching does.
_MIN_IDS = 40
_MIN_MARKERS = 20

#: Live floor for the LEDGER anti-vacuity arm. 88 ids carried a bound
#: disposition and 86 parsed as closed when this landed (2026-10-02); 30 leaves
#: a wide margin for an archive relocation while still reddening on a parser
#: that quietly stops matching. The ledger is append-only, so this floor can
#: only ever get easier to clear.
_MIN_LEDGER_CLOSURES = 30


class RoadmapMarkerBinding(unittest.TestCase):
    """The ROADMAP run rule, on synthetic text, one shape per test."""

    def test_a_marker_binds_to_every_id_in_the_enumeration_before_it(self) -> None:
        """`RM-250 / RM-251 OPEN` in miniature - the shape that hid the defect."""
        text = "- **RM-920 / RM-921 OPEN (filed 2026-09-10)** - a thing."
        self.assertEqual({"OPEN"}, _markers(text, 920))
        self.assertEqual({"OPEN"}, _markers(text, 921))

    def test_an_intervening_marker_ends_the_run(self) -> None:
        """THE negative control: `RM-281 HALF-CLOSED + RM-283 OPEN`.

        The OPEN belongs to RM-283, which is genuinely open. Binding it to
        RM-281 reports a row that is correctly half-closed as drifted, and that
        false positive is the failure mode most likely to get this guard
        deleted.

        The first id ends up carrying NO marker at all, not `CLOSED`: the gap
        `HALF-` is not delimiter text either, so the run rule refuses in both
        directions. That is deliberate and harmless - the guard only ever acts
        on an id it can see an `OPEN` on, so an unbound compound verb costs
        nothing, while an over-bound `OPEN` costs a false MUST-FIX. Asserting
        `CLOSED` here instead would be asserting a guarantee the rule does not
        make.
        """
        text = "- **RM-920 HALF-CLOSED + RM-921 OPEN; RM-922 CLOSED 2026-09-02**"
        self.assertNotIn("OPEN", _markers(text, 920))
        self.assertEqual({"OPEN"}, _markers(text, 921))
        self.assertEqual({"CLOSED"}, _markers(text, 922))

    def test_the_half_closed_shape_never_reaches_the_drift_report(self) -> None:
        """The same negative control, end to end through the real predicate."""
        self.assertEqual(
            (),
            reg.disposition_drift(
                "- **RM-920 HALF-CLOSED + RM-921 OPEN**",
                "- **RM-920 CLOSED 2026-09-02** - done.\n"
                "- **RM-921 OPEN (filed)** - live.",
            ),
        )

    def test_prose_between_the_ids_and_the_marker_ends_the_run(self) -> None:
        """The pointer-cluster shape: a dozen ids may not inherit a later verb."""
        text = (
            "- **SHIPPED / CLOSED pointer cluster covering RM-920 / RM-921 / "
            "RM-922.** READ that block before re-filing. **Still OPEN: RM-923**"
        )
        for rm_id in (920, 921, 922):
            with self.subTest(rm_id=rm_id):
                self.assertEqual(set(), _markers(text, rm_id))

    def test_a_marker_does_not_reach_backwards_into_the_previous_line(self) -> None:
        self.assertEqual(set(), _markers("- **RM-920**\n- SHIPPED tail", 920))

    def test_a_marker_before_any_id_binds_to_nothing(self) -> None:
        self.assertEqual(set(), _markers("Still-OPEN tails: RM-920 below.", 920))

    def test_ids_are_bound_by_value_not_by_substring(self) -> None:
        text = "- **RM-9201 OPEN** and **RM-92 OPEN**"
        self.assertEqual(set(), _markers(text, 920))

    def test_a_confusable_neighbour_id_is_not_credited(self) -> None:
        """`RM-250` vs `RM-350`, `RM-291` vs `RM-391` - all four are live."""
        text = "- **RM-921 OPEN**"
        self.assertEqual(set(), _markers(text, 911))
        self.assertEqual({"OPEN"}, _markers(text, 921))


class BacklogRowDisposition(unittest.TestCase):
    """The BACKLOG row-leading rule, on synthetic text."""

    def test_a_plain_row_leading_marker_is_read(self) -> None:
        rows = reg.backlog_row_dispositions("- **RM-920 SHIPPED 2026-09-08** - x.")
        self.assertEqual("SHIPPED", rows[920].marker)

    def test_a_shouted_qualifier_does_not_hide_the_disposition(self) -> None:
        """`RM-250 FIRST HALF SHIPPED` and `RM-291 FULLY CLOSED` are both real."""
        for text, expected in (
            ("- **RM-920 FIRST HALF SHIPPED 2026-09-05; SECOND HALF REFUTED**", "SHIPPED"),
            ("- **RM-920 FULLY CLOSED 2026-09-04 (Sweep A LEDGER 1331)**", "CLOSED"),
        ):
            with self.subTest(text=text):
                self.assertEqual(expected, reg.backlog_row_dispositions(text)[920].marker)

    def test_a_marker_buried_in_the_rows_prose_is_not_a_disposition(self) -> None:
        """The `RM-204` control - the fifth id a looser rule invents.

        That row opens `- **RM-204 (OPERATOR-GATED) - the Arena augment
        play-line is BUILT, TESTED ...` and its first vocabulary hit sits deep
        inside the sentence. The lowercase text before it is the signal that
        the row has stopped declaring a disposition and started explaining
        itself. The fix for a spurious hit is this predicate, never an
        allowlist.
        """
        text = "- **RM-920 (OPERATOR-GATED) - the lane is inert and CLOSED to us**"
        self.assertNotIn(920, reg.backlog_row_dispositions(text))

    def test_a_row_may_not_claim_a_neighbour_ids_verb(self) -> None:
        self.assertNotIn(920, reg.backlog_row_dispositions("- **RM-920 RM-921 OPEN**"))

    def test_only_a_row_OPENER_is_read_not_a_mid_paragraph_mention(self) -> None:
        self.assertEqual({}, reg.backlog_row_dispositions("see RM-920 SHIPPED above"))

    def test_the_first_body_wins_over_a_later_follow_up_note(self) -> None:
        text = "- **RM-920 SHIPPED 2026-09-08**\n- **RM-920 OPEN follow-up**"
        self.assertEqual("SHIPPED", reg.backlog_row_dispositions(text)[920].marker)


class SyntheticPositiveControl(unittest.TestCase):
    """A constructed drifted pair IS detected - so the guard can still fire."""

    def test_an_open_roadmap_row_over_a_shipped_body_is_reported(self) -> None:
        drifted = reg.disposition_drift(
            "- [!] **RM-920 OPEN (filed 2026-09-08, Tier-1)** - a tail.",
            "- **RM-920 SHIPPED 2026-09-08 (LEDGER 9999, Tier-1)** - done.",
        )
        self.assertEqual([920], [row.rm_id for row in drifted])
        self.assertEqual("SHIPPED", drifted[0].backlog.marker)

    def test_the_failure_message_cites_both_files_and_both_lines(self) -> None:
        message = reg.describe_drift(
            reg.disposition_drift(
                "intro\n- **RM-920 OPEN** - a tail.",
                "- **RM-920 CLOSED 2026-09-04** - done.",
            )
        )
        for needle in ("RM-920", f"{ROADMAP}:2", f"{BACKLOG}:1", "Reconcile"):
            with self.subTest(needle=needle):
                self.assertIn(needle, message)

    def test_a_roadmap_row_that_already_names_the_closure_is_not_drift(self) -> None:
        """`RM-302 SHIPPED ...; RM-301 OPEN` - RM-302 is honest, not stale."""
        drifted = reg.disposition_drift(
            "- **RM-920 SHIPPED 2026-09-04 (LEDGER 9999)**",
            "- **RM-920 SHIPPED 2026-09-04 (LEDGER 9999)**",
        )
        self.assertEqual((), drifted)

    def test_an_open_body_under_an_open_roadmap_row_is_not_drift(self) -> None:
        drifted = reg.disposition_drift(
            "- **RM-920 / RM-921 OPEN**",
            "- **RM-920 SHIPPED 2026-09-05**\n- **RM-921 OPEN (filed)** - live.",
        )
        self.assertEqual([920], [row.rm_id for row in drifted])

    def test_a_body_that_is_merely_PARTIAL_is_not_a_finished_body(self) -> None:
        self.assertEqual(
            (),
            reg.disposition_drift(
                "- **RM-920 OPEN**", "- **RM-920 PARTIAL - 1 of 5 closed**"
            ),
        )


class ParserFindsRealContent(unittest.TestCase):
    """ANTI-VACUITY against the live docs. See the module docstring."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.roadmap_text = reg.read(REPO_ROOT / ROADMAP)
        cls.backlog_text = reg.read(REPO_ROOT / BACKLOG)
        cls.roadmap = reg.roadmap_dispositions(cls.roadmap_text)
        cls.backlog = reg.backlog_row_dispositions(cls.backlog_text)

    def test_the_parser_finds_many_bound_ids_in_both_live_docs(self) -> None:
        for label, found in ((ROADMAP, self.roadmap), (BACKLOG, self.backlog)):
            with self.subTest(doc=label):
                self.assertGreaterEqual(
                    len(found),
                    _MIN_IDS,
                    f"only {len(found)} RM ids carried a disposition in {label}. "
                    "Either the parser stopped matching - in which case the "
                    "drift assertion below is vacuous and proves nothing - or "
                    "the doc was gutted. Check the parser first.",
                )

    def test_the_parser_finds_real_disposition_markers_in_both_live_docs(self) -> None:
        roadmap_marks = [d.marker for marks in self.roadmap.values() for d in marks]
        backlog_marks = [d.marker for d in self.backlog.values()]
        for label, marks in ((ROADMAP, roadmap_marks), (BACKLOG, backlog_marks)):
            with self.subTest(doc=label):
                self.assertGreaterEqual(
                    len(marks),
                    _MIN_MARKERS,
                    f"only {len(marks)} disposition markers parsed out of "
                    f"{label}; the status vocabulary regex is no longer "
                    "matching real prose, so this guard cannot fire.",
                )
                self.assertTrue(
                    set(marks) & reg.BACKLOG_CLOSED_MARKERS,
                    f"{label} parsed no SHIPPED/CLOSED/DONE/REFUTED marker at "
                    "all, which cannot be true of a live RC doc",
                )

    def test_both_live_docs_still_carry_open_rows(self) -> None:
        """If nothing is OPEN anywhere, the drift assertion cannot fire either."""
        open_ids = [
            rm_id
            for rm_id, marks in self.roadmap.items()
            if any(d.marker == "OPEN" for d in marks)
        ]
        self.assertTrue(open_ids, f"{ROADMAP} parsed as having no OPEN row at all")


class LiveDocsAgreeOnDisposition(unittest.TestCase):
    """The invariant itself, against the live tree."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.drifted = reg.disposition_drift(
            reg.read(REPO_ROOT / ROADMAP), reg.read(REPO_ROOT / BACKLOG)
        )

    def test_no_roadmap_row_says_open_over_a_finished_backlog_body(self) -> None:
        self.assertEqual(
            (),
            self.drifted,
            "\n" + reg.describe_drift(self.drifted),
        )

    def test_a_genuinely_open_row_is_not_swept_up_with_its_line_mate(self) -> None:
        """`RM-251` shares `ROADMAP.md`'s RM-250 line and IS open.

        Pinned against the live docs rather than a fixture, because the whole
        risk of the enumeration rule is that it over-binds on exactly this
        line. If RM-251 ever closes, its BACKLOG body changes and this
        assertion is the one that says so out loud instead of the guard
        quietly starting to report it.
        """
        body = reg.backlog_row_dispositions(reg.read(REPO_ROOT / BACKLOG)).get(251)
        self.assertIsNotNone(body, f"RM-251 no longer opens a row body in {BACKLOG}")
        self.assertEqual(
            "OPEN",
            body.marker,
            f"{BACKLOG}:{body.line} now says RM-251 is {body.marker}. If that is "
            f"correct, reconcile the RM-251 pointer in {ROADMAP} in the same "
            "commit - do not leave it reading OPEN.",
        )


class LedgerClosureReading(unittest.TestCase):
    """How a LEDGER closure record is told from a LEDGER mention.

    Synthetic text only - the live arms are below. Every shape here was taken
    off the real file during the 2026-10-02 measurement, then re-expressed in
    the reserved `RM-9xx` band.
    """

    def test_a_closure_marker_makes_an_id_closed(self) -> None:
        text = "1426. DONE **2026-09-18** - **RM-920 - CLOSED BY REFUSAL.** Done."
        self.assertEqual("CLOSED", reg.ledger_closed_ids(text)[920].marker)

    def test_a_bare_mention_is_not_a_closure(self) -> None:
        """PRESENCE IS NOT A DISPOSITION - the dominant over-read.

        Measured live: 49 of the 52 ids carrying a bare OPEN in ROADMAP.md
        appear somewhere in LEDGER, and essentially none are drift. A
        presence-means-done rule reports all 49.
        """
        text = "1426. DONE **2026-09-18** - the hand-off named RM-920 as fallback."
        self.assertNotIn(920, reg.ledger_closed_ids(text))

    def test_an_entry_quoting_a_rows_filed_OPEN_state_does_not_read_as_closed(
        self,
    ) -> None:
        """The `RM-217` shape: the entry that REFUTES a row quotes it first.

        `RM-217 OPEN** (filed 2026-08-15) whose ACCEPTANCE prescribed ...` sits
        in the very entry that closed it. The `OPEN` is a quotation of history,
        not a live disposition, and nothing in the text distinguishes the two -
        which is exactly why it disqualifies instead of being out-voted.
        """
        text = (
            "1427. DONE **2026-09-12** - **RM-920 OPEN** (filed 2026-08-15) whose "
            "ACCEPTANCE prescribed a marker. REFUTED. Also **RM-921 CLOSED**."
        )
        self.assertNotIn(920, reg.ledger_closed_ids(text))
        self.assertEqual("CLOSED", reg.ledger_closed_ids(text)[921].marker)

    def test_a_closure_marker_elsewhere_does_not_out_vote_the_quoted_open(
        self,
    ) -> None:
        """The disqualifier is file-wide, not per-entry. Uncertain reads as open."""
        text = "1. DONE - **RM-920 CLOSED**\n2. DONE - RM-920 OPEN** when filed"
        self.assertNotIn(920, reg.ledger_closed_ids(text))

    def test_a_PARTIAL_record_is_not_a_finished_record(self) -> None:
        text = "1426. DONE - **RM-920 PARTIAL - 1 of 5 closed; RM-921 SHIPPED**"
        self.assertNotIn(920, reg.ledger_closed_ids(text))
        self.assertIn(921, reg.ledger_closed_ids(text))

    def test_ledger_carries_no_row_bodies_so_the_row_rule_is_the_wrong_one(
        self,
    ) -> None:
        """Measured 2026-10-02: zero `- **RM-NN` openers in the live file.

        This pins WHY `ledger_closed_ids` uses the run rule. If LEDGER ever
        grows declarative row bodies, this fails and the choice gets re-made
        deliberately instead of silently staying wrong.
        """
        self.assertEqual(
            {},
            reg.backlog_row_dispositions(reg.read(REPO_ROOT / LEDGER)),
            f"{LEDGER} now carries `- **RM-NN` row openers. Re-decide which "
            "parser ledger_closed_ids should use.",
        )


class LedgerDriftSyntheticControl(unittest.TestCase):
    """Constructed drifted pairs ARE detected - so the live arms can fire."""

    def test_a_backlog_row_still_open_over_a_ledger_closure_is_reported(self) -> None:
        drifted = reg.backlog_ledger_drift(
            "- **RM-920 OPEN (filed 2026-09-17, LANE 7, Tier-1)** - a tail.",
            "1426. DONE - **RM-920 - CLOSED BY REFUSAL (`a6af3a3e5`).** Done.",
        )
        self.assertEqual([920], [row.rm_id for row in drifted])
        self.assertEqual("BACKLOG.md", drifted[0].doc)

    def test_a_roadmap_bare_open_over_a_ledger_closure_is_reported(self) -> None:
        drifted = reg.roadmap_ledger_drift(
            "- [!] **RM-920 OPEN** - a tail.",
            "1426. DONE - **RM-920 SHIPPED 2026-09-08.**",
        )
        self.assertEqual([920], [row.rm_id for row in drifted])

    def test_a_roadmap_row_that_already_names_the_closure_is_not_drift(self) -> None:
        self.assertEqual(
            (),
            reg.roadmap_ledger_drift(
                "- **RM-920 SHIPPED; RM-921 OPEN**",
                "1426. DONE - **RM-920 SHIPPED 2026-09-08.**",
            ),
        )

    def test_the_half_closed_control_survives_the_ledger_arm_too(self) -> None:
        """`RM-281 HALF-CLOSED + RM-283 OPEN` - the RM-403 control, re-run here.

        RM-283 is the id whose quoted OPEN produced one of the two measured
        reverse-direction false positives, so this shape has to stay clean in
        the new arm as well as the old one.
        """
        self.assertEqual(
            (),
            reg.roadmap_ledger_drift(
                "- **RM-920 HALF-CLOSED + RM-921 OPEN**",
                "1426. DONE - **RM-921 CLOSED** ... quoting `RM-921 OPEN`, where "
                "the OPEN belongs to RM-921.",
            ),
        )

    def test_the_failure_message_cites_both_files_and_both_lines(self) -> None:
        message = reg.describe_ledger_drift(
            reg.backlog_ledger_drift(
                "- **RM-920 OPEN** - a tail.",
                "head\n1426. DONE - **RM-920 CLOSED.**",
            )
        )
        for needle in ("RM-920", f"{BACKLOG}:1", f"{LEDGER}:2", "append-only"):
            with self.subTest(needle=needle):
                self.assertIn(needle, message)


class LedgerParserFindsRealContent(unittest.TestCase):
    """ANTI-VACUITY for the live LEDGER arms. See the module docstring."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.closed = reg.ledger_closed_ids(reg.read(REPO_ROOT / LEDGER))

    def test_the_parser_finds_many_closure_records_in_the_live_ledger(self) -> None:
        self.assertGreaterEqual(
            len(self.closed),
            _MIN_LEDGER_CLOSURES,
            f"only {len(self.closed)} ids parsed as closed out of {LEDGER}. "
            "Either the parser stopped matching - in which case both live "
            "arms below are vacuous - or the ledger was gutted.",
        )

    def test_the_live_ledger_closures_are_not_all_one_marker(self) -> None:
        markers = {d.marker for d in self.closed.values()}
        self.assertTrue(
            markers <= reg.BACKLOG_CLOSED_MARKERS and len(markers) >= 2,
            f"{LEDGER} parsed closure markers {sorted(markers)}; a live RC "
            "ledger carries more than one closure verb, so a single-verb read "
            "means the vocabulary regex is half broken.",
        )


class LiveDocsAgreeWithTheLedger(unittest.TestCase):
    """The invariants themselves, against the live tree.

    MEASURED 2026-10-02 before these landed, each corroborated TWICE because a
    doc agreeing with a doc is not evidence:

    * `RM-472` - `BACKLOG.md` said OPEN; LEDGER 1426 says CLOSED BY REFUSAL,
      and the refusal is in the source it names
      (`tests/test_skip_condition_hygiene.py` carries `_UNANALYSABLE_SHAPES`
      and `test_rm472_comprehension_and_lambda_laundered_reads_earn_no_
      capability`), with both cited commits resolving.
    * `RM-210` - `BACKLOG.md` said OPEN; LEDGER 1270 AND
      `docs/ROADMAP_HISTORY.md` both say CLOSED. The source probe split the
      row: acceptance (b) is MET (`docs/DAEMON_SLAYER.md` deleted the test-count
      recital and names RM-210 as the reason), acceptance (a) was NOT
      (`docs/ARCHITECTURE.md` still called the banner "drift-guarded" for
      counts no guard pins, unchanged since 2026-07-17 - before the row was
      even filed). The closure records over-claimed; the row's OPEN was the
      honest half. Acceptance (a) was then performed, which is why the row is
      closed today rather than silenced.

    The ROADMAP arm measured ZERO drift at the same moment and is kept because
    it is the same predicate on a different disposition map - no speculative
    code, and `LedgerDriftSyntheticControl` proves it can still fire.

    THE REVERSE DIRECTION IS DELIBERATELY NOT BUILT. A check for "LEDGER says
    OPEN while the doc says closed" returns exactly two candidates on this
    tree, `RM-217` and `RM-283`, and BOTH are LEDGER quoting history inside the
    entry that closed the row. There is no live instance, only false ones.
    """

    @classmethod
    def setUpClass(cls) -> None:
        ledger_text = reg.read(REPO_ROOT / LEDGER)
        cls.roadmap_drift = reg.roadmap_ledger_drift(
            reg.read(REPO_ROOT / ROADMAP), ledger_text
        )
        cls.backlog_drift = reg.backlog_ledger_drift(
            reg.read(REPO_ROOT / BACKLOG), ledger_text
        )

    def test_no_roadmap_row_says_open_over_a_ledger_closure_record(self) -> None:
        self.assertEqual(
            (),
            self.roadmap_drift,
            "\n" + reg.describe_ledger_drift(self.roadmap_drift),
        )

    def test_no_backlog_row_body_says_open_over_a_ledger_closure_record(self) -> None:
        self.assertEqual(
            (),
            self.backlog_drift,
            "\n" + reg.describe_ledger_drift(self.backlog_drift),
        )


def _markers(text: str, rm_id: int) -> set[str]:
    return {d.marker for d in reg.roadmap_dispositions(text).get(rm_id, [])}


if __name__ == "__main__":
    unittest.main()
