"""`docs/COST_TRACE.md` call-site matrix vs the live call sites (S19).

WHY THIS EXISTS, AND WHY IT IS THIS NARROW
------------------------------------------
RM-171 shipped `tools/citation_audit.py` for citations that do not RESOLVE.
This guard covers the harder neighbour: a citation that resolves cleanly and
still tells the reader something untrue.

The instance that motivated it: `docs/COST_TRACE.md` tabulated
`dashboard/_champ_select.py:92` as a live HAIKU call site with a
`record_anthropic_response` wire. That row was accurate when the matrix was
audited (2026-05-19). The Haiku-elimination program flipped the surface on
2026-06-06, leaving a 26-line facade with zero Anthropic call - and the doc
kept asserting a cost that no longer exists for two months. Nothing in the
toolchain reads a prose table, so nothing noticed.

WHY NOT A REPO-WIDE VERSION OF THIS CHECK
-----------------------------------------
The obvious generalisation is "any doc line that names a `.py` file and says
HAIKU / SONNET / Anthropic must name a file containing `messages.create`".
That was MEASURED on 2026-08-06 before this file was written: 114 candidate
doc lines across the tracked non-history Markdown, of which 62 name a `.py`
with no `messages.create`. Sampling those 62 shows essentially all are CORRECT
prose - a shadow-report tool, a deterministic substrate, a precompute module,
or a sentence whose whole point is that the file does NOT call Anthropic
(`docs/COST_TRACE.md:11` on `core/moon_proxy.py`, `BACKLOG.md:30` on
`dashboard/_champ_select.py`). Precision would be about 1 in 62. A guard at
that precision is a guard people baseline into silence, so it is deliberately
NOT built.

What makes THIS table checkable is that it is not prose. Every row of the
call-site matrix is, by the table's own header, an assertion that the named
file issues a call at the named tier. So the "does this file call Anthropic"
question is exactly the row's claim, and precision is 1.0 by construction.

SCOPE, STATED HONESTLY
----------------------
This checks WHICH FILE, not which line. The line numbers in that matrix are
from the 2026-05-19 audit and most have drifted; the doc now says so in its
own body. Re-pointing 19 line numbers that will rot again is not worth a
guard - asserting that every named file is still a call site is, because that
is the fact a reader actually acts on.
"""
from __future__ import annotations

import pathlib
import re
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_DOC = _ROOT / "docs" / "COST_TRACE.md"

# A matrix row: | <site> | <tier> | <tracked> | <cadence> | <purpose> |
_ROW = re.compile(r"^\|(?P<cells>.+)\|\s*$")
# `path/to/file.py:123`, tolerating backticks and ~~strikethrough~~.
_SITE = re.compile(r"([A-Za-z0-9_][A-Za-z0-9_./-]*\.py):(\d+)")

_LIVE_TIERS = {"HAIKU", "SONNET", "OPUS"}

# Rows deliberately kept in the table after the call site was retired, so the
# matching `by_purpose` key in old `data/spend/*.json` ledgers stays
# explainable. Each MUST be struck through in the doc and MUST carry a reason.
_RETIRED: dict[str, str] = {
    "dashboard/_champ_select.py": (
        "champ_select_brief was flipped off Haiku 2026-06-06 (items "
        "273/276/280/283). brief_via_coach is now a pure delegation to "
        "_champ_select_deterministic.brief_deterministic with zero Anthropic "
        "call. Row struck, not deleted, so the champ_select_brief purpose key "
        "in historical spend ledgers stays explainable."
    ),
}


def _matrix_rows() -> list[tuple[str, str, str]]:
    """Return (raw_line, site_path, tier) for every call-site matrix row."""
    out: list[tuple[str, str, str]] = []
    for raw in _DOC.read_text(encoding="utf-8").splitlines():
        m = _ROW.match(raw.strip())
        if not m:
            continue
        cells = [c.strip() for c in m.group("cells").split("|")]
        if len(cells) < 2:
            continue
        site = _SITE.search(cells[0])
        if not site:
            continue
        tier = cells[1].strip("`~* ").upper()
        out.append((raw, site.group(1), tier))
    return out


class CostTraceMatrixTests(unittest.TestCase):
    """Every file the matrix calls a live call site must still be one."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = _matrix_rows()

    def test_the_matrix_was_actually_parsed(self) -> None:
        """Fail loudly on a reformat instead of passing vacuously.

        Without this, renaming a column or switching the table to a list
        turns every assertion below into a no-op over an empty list, and the
        guard reports green while checking nothing.
        """
        self.assertGreaterEqual(
            len(self.rows), 15,
            f"parsed only {len(self.rows)} call-site rows out of "
            "docs/COST_TRACE.md - the table shape changed and this guard is no "
            "longer reading it. Fix the parser, do not lower this floor.",
        )
        tiers = {t for _, _, t in self.rows}
        self.assertTrue(
            _LIVE_TIERS & tiers,
            "no HAIKU/SONNET/OPUS row parsed at all - tier column moved?",
        )

    def test_every_live_row_names_a_real_call_site(self) -> None:
        for raw, path, tier in self.rows:
            if tier not in _LIVE_TIERS:
                continue
            with self.subTest(site=path, tier=tier):
                target = _ROOT / path
                self.assertTrue(
                    target.is_file(),
                    f"docs/COST_TRACE.md claims {path} is a {tier} call site, but the "
                    f"file does not exist:\n  {raw.strip()}",
                )
                src = target.read_text(encoding="utf-8", errors="replace")
                self.assertIn(
                    "messages.create", src,
                    f"docs/COST_TRACE.md claims {path} is a live {tier} call site, but "
                    "the file contains no `messages.create`. If the surface "
                    "was flipped off Anthropic, STRIKE the row through and add "
                    "it to _RETIRED with a reason - do not just delete it, the "
                    "purpose key survives in old data/spend/*.json ledgers.\n"
                    f"  {raw.strip()}",
                )

    def test_retired_rows_are_struck_through_and_not_live(self) -> None:
        """A retired row must read as retired, in the doc and in the tier."""
        seen = set()
        for raw, path, tier in self.rows:
            if path not in _RETIRED:
                continue
            seen.add(path)
            with self.subTest(site=path):
                self.assertNotIn(
                    tier, _LIVE_TIERS,
                    f"{path} is recorded as a RETIRED call site here but its row "
                    f"still carries a live tier ({tier}).",
                )
                self.assertIn(
                    "~~", raw,
                    f"{path} is recorded as RETIRED but its row is not struck "
                    "through, so a reader scanning the table cannot tell:\n"
                    f"  {raw.strip()}",
                )
        self.assertEqual(
            seen, set(_RETIRED),
            f"_RETIRED names a site that is no longer in the matrix at all: {sorted(set(_RETIRED) - seen)}. "
            "Drop the entry, or restore the struck row.",
        )

    def test_every_retired_entry_carries_a_reason(self) -> None:
        for path, why in _RETIRED.items():
            with self.subTest(site=path):
                self.assertGreater(
                    len(why.strip()), 40,
                    f"_RETIRED[{path!r}] has no usable reason. An entry without one "
                    "is indistinguishable from a silenced failure.",
                )

    def test_a_removed_call_would_be_caught(self) -> None:
        """Prove the assertion is load-bearing, not incidentally true.

        A guard that only ever sees passing input has never demonstrated it
        can fail. This exercises the same predicate against a file that is
        definitely not a call site.
        """
        not_a_call_site = _ROOT / "dashboard" / "_champ_select.py"
        self.assertTrue(not_a_call_site.is_file())
        self.assertNotIn(
            "messages.create",
            not_a_call_site.read_text(encoding="utf-8", errors="replace"),
            "dashboard/_champ_select.py grew a messages.create call. That is a "
            "real change to the Haiku-to-ZERO position, not a test problem - "
            "un-retire its COST_TRACE row and update the ledger.",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
