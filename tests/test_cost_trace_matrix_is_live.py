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
That was estimated on 2026-08-06 before this file was written: roughly 114
candidate doc lines yielding about 62 that name a `.py` with no
`messages.create`. **Treat those as an ESTIMATE, not a datum.** An independent
re-implementation of the same stated rule got 773/708 over all tracked `.md`
and 234/184 excluding archive and history - neither near 114/62. The rule as
prose is too under-specified to reproduce, and the answer swings about 3x on
corpus choice alone. The 114/62 corpus was: tracked `.md`, excluding
`docs/_archive/**`, the five append-only history files, the generated
review-mirror tree that existed at the time, any path containing CHANGELOG,
and any cited path under `tests/`.

What DOES reproduce, and is the actual reason for the refusal, is the
qualitative result: every sampled hit was CORRECT prose - a shadow-report tool,
a deterministic substrate, a precompute module, or a sentence whose whole point
is that the file does NOT call Anthropic (`docs/COST_TRACE.md:11` on
`core/moon_proxy.py`, `BACKLOG.md:30` on `dashboard/_champ_select.py`). One
independent sample of 12 was 12 for 12 correct prose, including a line that
matched only because it mentions "Claude PreToolUse hooks". Precision is
somewhere between terrible and very terrible regardless of corpus, and a guard
at that precision is one people baseline into silence. Deliberately NOT built.

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
# RM-435: `_SITE` admits no space, so `tools/my dir/x.py:9` read as
# `dir/x.py:9` and a real row went red on a phantom path. A spaced site counts
# only when it is the WHOLE of one bounded unit, never searched loose:
#   * one paired backtick span (the channel-pin bound, 1f42fd481 + 8e85ded6f);
#   * or the whole site cell once `~` / `*` / whitespace decoration is
#     stripped. The matrix cells are NOT backticked today, so the markdown
#     code-span bound alone would never fire on a real row; the cell is the
#     table's own bound, since a site cell's entire content is the claim.
# Deliberate limits: a spaced site needs a `/`, and no segment may start or
# end with a space. Everything else falls back to the unspaced `_SITE`.
_SPACED_SEGMENT = r"[A-Za-z0-9_.-](?:[A-Za-z0-9_. -]*[A-Za-z0-9_.-])?"
_SPACED_SITE = re.compile(
    rf"((?:{_SPACED_SEGMENT}/)+{_SPACED_SEGMENT}\.py):(\d+)"
)
_CODE_SPAN = re.compile(r"`[^`\n]*`")


def _site_path(cell: str) -> str | None:
    """The site path one matrix cell names, or None."""
    units = [s.group(0)[1:-1] for s in _CODE_SPAN.finditer(cell)]
    units.append(cell.strip("~* \t"))
    for unit in units:
        spaced = _SPACED_SITE.fullmatch(unit)
        if spaced is not None and " " in spaced.group(1):
            return spaced.group(1)
    site = _SITE.search(cell)
    return None if site is None else site.group(1)

_LIVE_TIERS = {"HAIKU", "SONNET", "OPUS"}

# The call-site matrix is exactly this many rows. Pinned, not floored.
#
# WHY EXACT AND NOT ">= SOME FLOOR". The first version of this guard used
# `assertGreaterEqual(len(rows), 15)` against 21 real rows, which left six rows
# of slack: a row identified only by its `path.py:N` shape drops out of the
# parse entirely when the line number is stripped, so deleting the numbers from
# six rows would have taken them out of the guard's view while it reported
# green. Worse, the doc's own correction paragraph advised readers not to trust
# those line numbers, which reads as an invitation to remove them. Doc and
# guard were giving opposite instructions.
#
# So: the count is exact, and separately EVERY table row in the matrix section
# must yield a parseable site. There is now no way to shrink the checked set
# without failing. The doc carries a matching DO-NOT-STRIP note.
_EXPECTED_ROWS = 21

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


def _matrix_body() -> list[str]:
    """Return every DATA row of the call-site matrix, parseable or not.

    The section runs from the ``| Site | Tier | ...`` header to the first blank
    line. The ``|---|`` separator is dropped; everything else is a data row and
    is expected to name a call site. Returning unparseable rows too is the
    point: it is what lets the guard notice a row that stopped being visible.
    """
    lines = _DOC.read_text(encoding="utf-8").splitlines()
    body: list[str] = []
    inside = False
    for raw in lines:
        stripped = raw.strip()
        if not inside:
            if stripped.startswith("| Site ") and "Tier" in stripped:
                inside = True
            continue
        if not stripped:
            break
        if not stripped.startswith("|"):
            break
        if set(stripped) <= set("|- "):
            continue
        body.append(raw)
    return body


def _parse_row(raw: str) -> tuple[str, str] | None:
    """Return (site_path, tier) for one matrix row, or None if it does not."""
    m = _ROW.match(raw.strip())
    if not m:
        return None
    cells = [c.strip() for c in m.group("cells").split("|")]
    if len(cells) < 2:
        return None
    site = _site_path(cells[0])
    if site is None:
        return None
    return site, cells[1].strip("`~* ").upper()


def _matrix_rows() -> list[tuple[str, str, str]]:
    """Return (raw_line, site_path, tier) for every parseable matrix row."""
    out: list[tuple[str, str, str]] = []
    for raw in _matrix_body():
        parsed = _parse_row(raw)
        if parsed is not None:
            out.append((raw, parsed[0], parsed[1]))
    return out


class CostTraceMatrixTests(unittest.TestCase):
    """Every file the matrix calls a live call site must still be one."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.body = _matrix_body()
        cls.rows = _matrix_rows()

    def test_every_matrix_row_is_visible_to_this_guard(self) -> None:
        """No row may drop out of the parse. This is the anti-slack check.

        A row is identified by its ``path.py:N`` shape. Strip the line number
        and the row vanishes from every assertion below without any of them
        failing. Checking the parsed set against the FULL set of table rows is
        what makes that impossible.
        """
        invisible = [r for r in self.body if _parse_row(r) is None]
        self.assertEqual(
            invisible, [],
            "these docs/COST_TRACE.md matrix rows no longer name a "
            "`path.py:N` call site, so this guard cannot see them. Restore the "
            "site reference - the line number may be re-pointed but not "
            "removed:\n  " + "\n  ".join(r.strip() for r in invisible),
        )

    def test_the_matrix_row_count_is_pinned(self) -> None:
        """Fail loudly on a reformat instead of passing vacuously.

        Without this, renaming a column or switching the table to a list turns
        every assertion below into a no-op over an empty list, and the guard
        reports green while checking nothing. Exact, not a floor - see the
        comment on _EXPECTED_ROWS.
        """
        self.assertEqual(
            len(self.body), _EXPECTED_ROWS,
            f"the call-site matrix is {len(self.body)} rows, pinned at "
            f"{_EXPECTED_ROWS}. Adding or retiring a call site is a real "
            "change: update _EXPECTED_ROWS in the same commit that edits the "
            "table, and say why in the message. A count that drifts silently "
            "is how the row this guard exists for went stale for two months.",
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


class SiteParserSpacedPathTests(unittest.TestCase):
    """RM-435: `_SITE` must not truncate a spaced site path to its tail.

    The old parser read `tools/my dir/x.py:9` as `dir/x.py:9`, so a real row
    would go red against a phantom path. A space is admitted only when the
    site is the WHOLE of one bounded unit - one backtick span, or the whole
    (de-decorated) site cell - never searched loose across cell prose.
    """

    def _site(self, cell: str) -> str | None:
        parsed = _parse_row(f"| {cell} | HAIKU | YES | POLLING | p |")
        return None if parsed is None else parsed[0]

    def test_bare_spaced_site_cell_is_not_truncated(self) -> None:
        self.assertEqual(self._site("tools/my dir/x.py:9"), "tools/my dir/x.py")

    def test_backticked_spaced_site_is_not_truncated(self) -> None:
        self.assertEqual(self._site("`tools/my dir/x.py:9`"), "tools/my dir/x.py")

    def test_struck_spaced_site_is_not_truncated(self) -> None:
        self.assertEqual(self._site("~~tools/my dir/x.py:9~~"), "tools/my dir/x.py")
        self.assertEqual(self._site("~~`tools/my dir/x.py:9`~~"), "tools/my dir/x.py")

    def test_prose_cell_is_not_joined_into_a_path(self) -> None:
        self.assertEqual(self._site("see notes and x.py:3"), "x.py")
        self.assertEqual(self._site("see notes/and x.py:3 later"), "x.py")

    def test_two_backtick_spans_are_not_paired_across(self) -> None:
        self.assertEqual(self._site("`tools/a b` and `c/y.py:3`"), "c/y.py")

    def test_and_or_clock_time_is_not_a_site(self) -> None:
        self.assertIsNone(self._site("and/or 12:30"))

    def test_leading_space_segment_is_not_a_path(self) -> None:
        self.assertEqual(self._site("tools/ my/x.py:9 x"), "my/x.py")

    def test_real_matrix_rows_parse_exactly_as_the_unspaced_regex(self) -> None:
        body = _matrix_body()
        self.assertEqual(len(body), _EXPECTED_ROWS)
        for raw in body:
            cells = [c.strip() for c in _ROW.match(raw.strip()).group("cells").split("|")]
            old = _SITE.search(cells[0])
            with self.subTest(row=raw.strip()[:60]):
                self.assertIsNotNone(old)
                self.assertEqual(_parse_row(raw)[0], old.group(1))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
