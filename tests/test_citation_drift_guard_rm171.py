"""RM-171: the broken-`file:line`-citation set may not silently GROW.

WHY
---
This repo's don't-redo discipline rests on a reader being able to follow a
`path.py:<N>` citation to the thing its prose claims lives there. Nothing in
the toolchain reads line numbers, so they rot in silence. RM-171 was filed on
a one-file measurement: of 8 places citing `core/build_order_precompute.py:<N>`
only 2 pointed at what their text claimed, and one reader citation moved
`:569` -> `:684` -> `:722` across two commits in a SINGLE session.

The measurement lives in `tools/citation_audit.py` (read its docstring for the
classes and, importantly, for the honest limits of the claim matcher). This
module is the BUDGET.

WHAT IS BUDGETED, AND WHY IT IS ONLY THE HARD FAILURES
------------------------------------------------------
Only ``FILE_MISSING`` and ``PAST_EOF`` are pinned. Those are pure filesystem
facts - the path is not tracked, or the file is shorter than the cited line.
They cannot be argued with.

The audit ALSO grades resolving citations as CONFIRMED / MOVED / ABSENT via a
prose heuristic, and that grading is where most real rot lives. It is
deliberately NOT pinned here. A guard whose red/green depends on a substring
heuristic over English prose goes red when someone rewords a sentence, and a
guard that cries wolf gets deleted. Pinning the hard half gives a guard that
is always right when it fires; the soft half is reported by the tool for a
human to read.

WHY A PINNED SET RATHER THAN A COUNT
-------------------------------------
A count-only budget lets a fix silently pay for a new break. This asserts SET
EQUALITY against `_KNOWN_BROKEN`, so the guard fails in BOTH directions:

* a citation breaks that was not already known    -> RED (the point)
* a known-broken citation gets fixed and the      -> RED (the baseline may not
  baseline is not shrunk                             rot into a blanket pass)

Set equality is also the only shape that actually breaks in this repo - a
subset/count assertion is how `reference_repo_root_guard_worktree_blind` went
green while blind.

EVERY BASELINE ENTRY CARRIES A REASON. An entry with no reason is a bug in
this file. Four reason families, none of which is "we could not be bothered":

  EXTERNAL   the cited file was never in this repo (a third-party package
             internal, an external repo under review, a memory file that
             lives outside the tree). Nothing here can ever resolve.
  DELETED    the file was deliberately removed and the prose is describing
             that removal. Re-pointing it would destroy the record.
  HISTORICAL the citation describes a state that has since changed, in a
             point-in-time spec / plan / QA doc. Re-pointing it would make
             the doc assert something it never asserted.
  ROT        genuine drift that could NOT be repaired mechanically because
             the named symbol is gone or the target is ambiguous. These are
             the ones a human should actually action.

Keying is (doc, raw-citation-text), not the line the citation sits ON, so a
doc reflow does not churn the baseline. Two identical citations in one file
collapse to one entry - accepted, because the guard's job is "is this citation
broken", not "how many times is it written".

SCOPE
-----
`tools.citation_audit.in_scope` fences the guarded surface. Append-only
records (`docs/LEDGER.md`, `docs/history_notes.md`, `docs/ROADMAP_HISTORY.md`,
the `_archive` tree, `WAKEUP_NOTES.md`, the dated QA/handoff dirs) are audited
in report-only mode and are NEVER budgeted: a stale citation in an append-only
record is CORRECT - it records what was true when it was written, and editing
one is a history rewrite (`feedback_no_history_rewrite`).

Not to be confused with COMMIT-HASH citations. The repo already accepts that
~34 percent of pre-2026-07 8-hex commit citations are unresolvable and that
this is EXPECTED, not rot (CLAUDE.md Settled). This guard never looks at them.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from tools import citation_audit as ca

REPO_ROOT = Path(__file__).resolve().parent.parent

# (doc, raw citation, reason family, why)
_KNOWN_BROKEN: tuple[tuple[str, str, str, str], ...] = (
    (
        "CLAUDE.md",
        "dashboard.js:5055",
        "DELETED",
        "The Settled fence records that web/js/dashboard.js was quarantined "
        "(dab3ca74 -> docs/_archive/2026-05-18-dead-dashboard-js/) and that the "
        "_replayQueueLabel 920 bug died with it. The whole point of the line is "
        "that the file no longer exists.",
    ),
    (
        "docs/CHERRY_AUGMENT_SCAFFOLD_NOTES.md",
        "tools/gamepc_lcu_agent.py:1179",
        "DELETED",
        "Game-PC was retired from the pipeline (ADR-011) and the agent removed. "
        "The notes describe a handler that lived on the retired box.",
    ),
    (
        "docs/COST_TRACE.md",
        "dashboard/_champ_select.py:92",
        "ROT",
        "The row is stale in CONTENT, not just in line number: that file is now "
        "a 26-line facade delegating to _champ_select_deterministic, and its "
        "docstring says ZERO Anthropic call - while this row still claims "
        "HAIKU / record_anthropic_response. Needs a human to re-state the row, "
        "not a re-pointed number.",
    ),
    (
        "docs/DS_COMPLETENESS_GAP.md",
        "docs/DAEMON_SLAYER.md:122",
        "HISTORICAL",
        "docs/DAEMON_SLAYER.md was compacted from ~190 lines to 110. This gap "
        "doc quotes the old layout.",
    ),
    (
        "docs/DS_COMPLETENESS_GAP.md",
        "docs/DAEMON_SLAYER.md:185-187",
        "HISTORICAL",
        "Same compaction of docs/DAEMON_SLAYER.md.",
    ),
    (
        "docs/DS_COMPLETENESS_GAP.md",
        "docs/DAEMON_SLAYER.md:191-193",
        "HISTORICAL",
        "Same compaction of docs/DAEMON_SLAYER.md.",
    ),
    (
        "docs/ELECTRON_OVERLAY.md",
        "web/js/ws_client.js:4",
        "ROT",
        "web/js/ws_client.js is not tracked. Whether the location.hostname "
        "derivation moved or the file was folded into another module needs a "
        "human who knows the overlay transport; guessing a new host file would "
        "be a fabricated citation.",
    ),
    (
        "docs/LIVE_GAME_GATED_SYNC.md",
        "docs/OVERLAY_BUILD_MASTER_PLAN.md:806-816",
        "HISTORICAL",
        "OVERLAY_BUILD_MASTER_PLAN.md was compacted to 351 lines and its tables "
        "relocated (the doc says so itself at :44).",
    ),
    (
        "docs/LIVE_GAME_GATED_SYNC.md",
        "tools/gamepc_lcu_agent.py:1179",
        "DELETED",
        "Same retired Game-PC agent. This row already flags itself PATH IS "
        "STALE in its own prose.",
    ),
    (
        "docs/LIVE_GAME_GATED_SYNC.md",
        "OVERLAY_BUILD_MASTER_PLAN.md:666",
        "HISTORICAL",
        "Same master-plan compaction. Cited as a PAIR with :828, so re-pointing "
        "only the flagged half would split a two-sided comparison.",
    ),
    (
        "docs/LIVE_GAME_GATED_SYNC.md",
        "docs/OVERLAY_BUILD_MASTER_PLAN.md:416",
        "HISTORICAL",
        "Same; F1-06 now sits at :90 but the row cites :416 vs :828 as a pair.",
    ),
    (
        "docs/LIVE_GAME_GATED_SYNC.md",
        "docs/OVERLAY_BUILD_MASTER_PLAN.md:817",
        "HISTORICAL",
        "Same; WP-E5 now sits at :64/:338 but the row cites :817 vs :823 as a "
        "pair.",
    ),
    (
        "docs/ORCHESTRATION_PLAN.md",
        "gemini_audit.ps1:32",
        "DELETED",
        "ops/gemini_audit.ps1 was removed by the Gemini decommission "
        "(aee3bb96). MERGER-OWNED FILE - reported, not edited, by RM-171.",
    ),
    (
        "docs/ORCHESTRATION_PLAN.md",
        "_sync_base.py:114",
        "EXTERNAL",
        "playwright package internal, never in this repo. MERGER-OWNED FILE.",
    ),
    (
        "docs/ORCHESTRATION_PLAN.md",
        "_connection.py:319",
        "EXTERNAL",
        "playwright package internal, never in this repo. MERGER-OWNED FILE.",
    ),
    (
        "docs/RC2_QA_CONSOLIDATED.md",
        "routes_pickban.py:1263",
        "ROT",
        "dashboard/routes_pickban.py is 1235 lines. The QA row's claim "
        "(counter-picks vs live enemy comp) names no symbol, so there is "
        "nothing to re-point against.",
    ),
    (
        "docs/research/RESEARCH_CONSOLIDATED_2026-07-28.md",
        "analysis.js:129-134",
        "EXTERNAL",
        "Third-party plugin under license review, not vendored (CLAUDE.md "
        "third-party lift gate). Never in this repo.",
    ),
    (
        "docs/research/RESEARCH_CONSOLIDATED_2026-07-28.md",
        "cache.js:64-65",
        "EXTERNAL",
        "Same external plugin under license review; never vendored here.",
    ),
    (
        "docs/research/RESEARCH_CONSOLIDATED_2026-07-28.md",
        "globalCache.js:77-78",
        "EXTERNAL",
        "Same external plugin under license review; never vendored here.",
    ),
    (
        "docs/research/RESEARCH_CONSOLIDATED_2026-07-28.md",
        "lcu.js:42",
        "EXTERNAL",
        "Same external plugin under license review; never vendored here.",
    ),
    (
        "docs/specs/FORWARD_LEAP_PLAN.md",
        "DS.md:15",
        "ROT",
        "No DS.md is tracked. Probably shorthand for docs/DAEMON_SLAYER.md, "
        "but that doc has since been compacted so the shorthand cannot be "
        "expanded AND re-pointed without asserting a line nobody wrote.",
    ),
    (
        "docs/specs/SPEC_data_provenance_guard_and_index.md",
        "ROADMAP.md:231",
        "HISTORICAL",
        "The sentence containing this citation exists to record that the cite "
        "went stale DURING the audit. Repairing it would delete the finding.",
    ),
    (
        "docs/specs/SPEC_rm98_cast_rate_time_base.md",
        "project_ds_rm98_cast_rate_time_base.md:46-49",
        "EXTERNAL",
        "Perseus/memory file under ~/.claude/projects/.../memory/, outside the "
        "repo tree by design.",
    ),
    (
        "docs/specs/SPEC_rm98_cast_rate_time_base.md",
        "project_ds_ability_haste_measured_inert.md:43-45",
        "EXTERNAL",
        "Same Perseus/memory store outside the repo tree by design.",
    ),
    (
        "docs/specs/WP_C2_SPEC.md",
        "OVERLAY_BUILD_MASTER_PLAN.md:645",
        "HISTORICAL",
        "Master-plan compaction. Also content-stale: the spec says B4 is OPEN "
        "and the plan now records B4 DONE 2026-06-29, so a re-point would "
        "carry a false claim to a real line.",
    ),
    (
        "docs/specs/WP_C2_SPEC.md",
        "OVERLAY_BUILD_MASTER_PLAN.md:808",
        "HISTORICAL",
        "Same master-plan compaction; B4 status is now DONE, not OPEN.",
    ),
    (
        "docs/specs/WP_C2_SPEC.md",
        "docs/OVERLAY_BUILD_MASTER_PLAN.md:645",
        "HISTORICAL",
        "Same citation written with the docs/ prefix.",
    ),
    (
        "docs/specs/leap/LEAP-02-ds-staged-passives-gwen-kaisa.md",
        "DS.md:71",
        "ROT",
        "Same untracked DS.md shorthand as FORWARD_LEAP_PLAN.md.",
    ),
    (
        "docs/specs/leap/LEAP-03-onhit-consumer-completion.md",
        "docs/DAEMON_SLAYER.md:169-172",
        "HISTORICAL",
        "The spec's premise is that DAEMON_SLAYER.md STILL says six archetypes. "
        "It now says seven (line 81) and the work shipped, so re-pointing the "
        "number would preserve a claim that is measurably false.",
    ),
    (
        "docs/specs/leap/LEAP-03-onhit-consumer-completion.md",
        "docs/DAEMON_SLAYER.md:169",
        "HISTORICAL",
        "Same - the six-archetype line was corrected to seven.",
    ),
    (
        "docs/specs/leap/LEAP-03-onhit-consumer-completion.md",
        "docs/DAEMON_SLAYER.md:172",
        "HISTORICAL",
        "The 6-button picker-grid text does still exist (now line 84), but it "
        "is cited as one half of a :169 + :172 edit plan whose other half is "
        "already done. Fixing one number alone makes the plan incoherent.",
    ),
    (
        "docs/specs/leap/LEAP-03-onhit-consumer-completion.md",
        "DAEMON_SLAYER.md:169",
        "HISTORICAL",
        "Same citation written without the docs/ prefix.",
    ),
    (
        "docs/superpowers/plans/2026-07-31-mission-control-s10-decouple.md",
        "dev.js:778",
        "ROT",
        "The plan is QUOTING a stale citation carried by a comment in "
        "tests/test_interrupt_panel.py. Repairing it here would hide the "
        "defect the plan is reporting; the comment is what needs fixing.",
    ),
)

_REASON_FAMILIES = frozenset({"EXTERNAL", "DELETED", "HISTORICAL", "ROT"})


class CitationBaselineIntegrity(unittest.TestCase):
    """The baseline itself must stay honest."""

    def test_every_entry_carries_a_real_reason(self) -> None:
        for doc, raw, family, why in _KNOWN_BROKEN:
            with self.subTest(entry=f"{doc} {raw}"):
                self.assertIn(family, _REASON_FAMILIES, "unknown reason family")
                self.assertGreaterEqual(
                    len(why), 40, "a one-word excuse is not a reason"
                )

    def test_no_duplicate_entries(self) -> None:
        keys = [(d, r) for d, r, _, _ in _KNOWN_BROKEN]
        self.assertEqual(len(keys), len(set(keys)), "duplicate baseline key")

    def test_baseline_is_confined_to_the_guarded_scope(self) -> None:
        # An entry outside `in_scope` could never be produced by the audit, so
        # it would sit here forever looking like coverage while guarding air.
        for doc, raw, _, _ in _KNOWN_BROKEN:
            with self.subTest(entry=f"{doc} {raw}"):
                self.assertTrue(ca.in_scope(doc), f"{doc} is not a guarded doc")


class CitationDriftGuard(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = ca.audit(REPO_ROOT)

    def test_the_audit_actually_found_citations(self) -> None:
        # Anti-vacuity floor. If the extractor regex or the scope fence ever
        # breaks, every assertion below passes trivially against an empty
        # census. The living docs carried 1918 citations when this was
        # written; 500 is a floor, not a target.
        self.assertGreater(
            len(self.rows), 500, "citation extraction collapsed - guard is blind"
        )

    def test_no_net_new_broken_citation(self) -> None:
        observed = {(r.doc, r.raw) for r in ca.broken(self.rows)}
        expected = {(d, r) for d, r, _, _ in _KNOWN_BROKEN}

        new = sorted(observed - expected)
        fixed = sorted(expected - observed)

        msg = []
        if new:
            msg.append(
                "NET-NEW broken citations (a doc now cites a file that is not "
                "tracked, or a line past the end of one). Fix the citation, or "
                "add it to _KNOWN_BROKEN WITH A REASON:\n"
                + "\n".join(f"    {d}  ->  {c}" for d, c in new)
            )
        if fixed:
            msg.append(
                "These baseline entries are NO LONGER broken. Delete them from "
                "_KNOWN_BROKEN so the budget shrinks with the debt:\n"
                + "\n".join(f"    {d}  ->  {c}" for d, c in fixed)
            )
        self.assertEqual(observed, expected, "\n\n".join(msg))


class CitationAuditMechanics(unittest.TestCase):
    """Pin the extractor's behaviour so the guard cannot go quietly blind."""

    def test_extracts_plain_and_range_citations(self) -> None:
        got = ca.extract_citations("see `core/foo.py:12` and `a/b.js:5-9`", "d.md")
        self.assertEqual(
            [(c.path, c.start, c.end) for c in got],
            [("core/foo.py", 12, 12), ("a/b.js", 5, 9)],
        )

    def test_ignores_host_port_and_version_shapes(self) -> None:
        # These are the shapes that made an open-ended suffix regex unusable.
        noise = "https://127.0.0.1:8888/api  ENGINE 1.235.0  DS :8860  at 12:30"
        self.assertEqual(ca.extract_citations(noise, "d.md"), [])

    def test_immutable_history_is_not_guarded(self) -> None:
        for doc in ("docs/LEDGER.md", "docs/history_notes.md", "WAKEUP_NOTES.md"):
            with self.subTest(doc=doc):
                self.assertFalse(ca.in_scope(doc))

    def test_living_docs_are_guarded(self) -> None:
        for doc in ("CLAUDE.md", "BACKLOG.md", "docs/ARCHITECTURE.md"):
            with self.subTest(doc=doc):
                self.assertTrue(ca.in_scope(doc))


if __name__ == "__main__":
    unittest.main()
