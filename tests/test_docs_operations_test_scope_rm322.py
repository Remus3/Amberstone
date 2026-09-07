# arch: the OPERATIONS test-scope table names the same trees as _TEST_TREES | section=tests | frozen=no
"""Guard: the AUTHORITATIVE test-scope table in ``docs/OPERATIONS.md`` must name
the same five test trees as the producing side, and its cite must still point at
it.

RM-322 (2026-09-04). That section drifted for a month: three of six counts, the
derived percentages, and the ``file:line`` cite of the enumerating side were all
stale, and it conflated "not in the local suites" with "unrun in CI".

**THIS GUARD DELIBERATELY DOES NOT PIN THE COUNTS.** Absolute test counts move on
almost every commit, so a count guard would go red on any commit that adds a
test and would be deleted within a week - the same reasoning that makes
``tests/test_docs_daemon_slayer_drift.py`` refuse to pin ``def test_`` counts,
and the same reason CLAUDE.md says a doc is not a source of truth. The counts in
that section are a dated MEASUREMENT and the section says so.

What IS stable, and what this pins:

1. The set of tree NAMES. If someone adds a sixth tree to ``_TEST_TREES`` and
   forgets the doc, that is a real contract break and the doc becomes wrong in a
   way no re-measure would fix.
2. The ``file:line`` cite pointing at the producing side. It read ``:59-60`` in
   the doc while ``_TEST_TREES`` had moved to ``:72`` - a cite that resolves to
   the wrong line is worse than no cite, because it reads as verified.

Both sides are read OFF DISK. Neither list is retyped here; restating either one
would make this test agree with itself instead of with the repo.
"""
from __future__ import annotations

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "OPERATIONS.md"
PRODUCER = ROOT / "tests" / "test_skip_condition_hygiene.py"

_SECTION_START = '## What "the suite is green" means (test scope)'
# Table rows look like:  | `tests` | 20561 | yes | yes | yes |
_TREE_ROW = re.compile(r"^\|\s*`([a-z0-9_/]+)`\s*\|\s*\d+\s*\|", re.M)
# The doc cites the producing side as `tests/test_skip_condition_hygiene.py:NN`.
_CITE = re.compile(r"`tests/test_skip_condition_hygiene\.py:(\d+)`")


def _section() -> str:
    text = DOC.read_text(encoding="utf-8")
    if _SECTION_START not in text:
        raise AssertionError(
            f"docs/OPERATIONS.md no longer contains the test-scope section "
            f"(looked for {_SECTION_START!r}). If it was renamed, update this "
            f"guard; if it was deleted, that is a decision that needs "
            f"recording, not a silent pass."
        )
    start = text.index(_SECTION_START)
    rest = text[start + len(_SECTION_START):]
    end = rest.find("\n### ")
    return rest[:end if end != -1 else len(rest)]


def _doc_trees() -> list[str]:
    return _TREE_ROW.findall(_section())


def _producer_trees() -> list[str]:
    text = PRODUCER.read_text(encoding="utf-8")
    m = re.search(r"_TEST_TREES\s*=\s*\((.*?)\)", text, re.S)
    if not m:
        raise AssertionError(
            f"could not find _TEST_TREES in {PRODUCER.name} - if it was renamed "
            f"or moved to another module, this guard and the OPERATIONS cite "
            f"both need updating"
        )
    return re.findall(r'"([^"]+)"', m.group(1))


class OperationsTestScopeTable(unittest.TestCase):
    def test_extractors_are_not_vacuous(self):
        """A parser that silently finds nothing would make every test below pass."""
        doc, producer = _doc_trees(), _producer_trees()
        # 4, not 5: `benchmarks` was deleted with .github/workflows/codspeed.yml
        # on 2026-09-06 (docs/OPERATIONS.md "Why CodSpeed was dropped"). This
        # floor is a vacuity check, not a census - it exists so a parser that
        # silently matches nothing cannot make every assertion below pass. Lower
        # it only alongside a real tree removal, and never to whatever the
        # parser happens to return.
        self.assertGreaterEqual(
            len(doc), 4,
            f"parsed {len(doc)} tree rows out of the OPERATIONS table; the "
            f"table format changed and this guard is reading nothing",
        )
        # 4, for the same reason as the doc floor above - `benchmarks` was
        # deleted 2026-09-06. The two floors must move together: they are the
        # vacuity check on OPPOSITE sides of the same comparison, so lowering
        # only one leaves the other able to read nothing and still pass.
        self.assertGreaterEqual(
            len(producer), 4,
            f"parsed {len(producer)} entries out of _TEST_TREES; the tuple "
            f"format changed and this guard is reading nothing",
        )

    def test_doc_names_the_same_trees_as_the_producer(self):
        doc, producer = set(_doc_trees()), set(_producer_trees())
        missing = sorted(producer - doc)
        extra = sorted(doc - producer)
        self.assertEqual(
            (missing, extra), ([], []),
            f"docs/OPERATIONS.md test-scope table is out of sync with "
            f"_TEST_TREES in tests/test_skip_condition_hygiene.py. "
            f"In _TEST_TREES but not in the doc table: {missing}. "
            f"In the doc table but not in _TEST_TREES: {extra}. "
            f"Add the tree to BOTH, or remove it from both. The doc calls "
            f"itself AUTHORITATIVE, so a tree missing there is a real contract "
            f"break - note this guard says nothing about the COUNTS, which are "
            f"a dated measurement and drift on every commit.",
        )

    def test_the_cite_still_points_at_the_producing_side(self):
        cites = _CITE.findall(_section())
        self.assertTrue(
            cites,
            "the test-scope section no longer cites "
            "tests/test_skip_condition_hygiene.py at all; it is the producing "
            "side and the section should name it",
        )
        lines = PRODUCER.read_text(encoding="utf-8").splitlines()
        for raw in cites:
            n = int(raw)
            self.assertLessEqual(
                n, len(lines),
                f"OPERATIONS.md cites test_skip_condition_hygiene.py:{n} but "
                f"that file has only {len(lines)} lines",
            )
            window = "\n".join(lines[max(0, n - 2):n + 2])
            self.assertIn(
                "_TEST_TREES", window,
                f"OPERATIONS.md cites test_skip_condition_hygiene.py:{n} as the "
                f"place that enumerates the test trees, but _TEST_TREES is not "
                f"within a line of there. The cite has rotted - find the real "
                f"line and update the doc. A cite that resolves to the wrong "
                f"line is worse than none, it reads as verified.",
            )


if __name__ == "__main__":
    unittest.main()
