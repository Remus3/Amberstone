"""RM-435: `tools/citation_audit.py` must not truncate a spaced path to its tail.

`CITATION_RE` segments are `[\\w.-]+`, so a backticked `docs/my notes/x.md:12`
used to be extracted as `notes/x.md:12` - the audit then graded the WRONG path
(FILE_MISSING, because `notes/x.md` is not a suffix of any tracked path).

The fix follows the channel-pin precedent (1f42fd481 + 8e85ded6f): a space is
admitted ONLY when the whole citation is the entire content of ONE paired
backtick span. Free prose is never widened, because a loose spaced search joins
words across prose into a phantom path - exactly what a verifier refuted in
the first channel-pin widening. The negative-control arms below pin that.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools import citation_audit as ca  # noqa: E402


def _cites(text: str) -> list[tuple[str, int, int]]:
    return [(c.path, c.start, c.end) for c in ca.extract_citations(text, "d.md")]


def _old_algorithm(text: str) -> list[tuple[str, int, int, str, int, int]]:
    """The pre-RM-435 extractor, verbatim in effect: CITATION_RE only."""
    out = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for m in ca.CITATION_RE.finditer(line):
            b = m.group(3)
            a = int(m.group(2))
            out.append(
                (m.group(1).replace("\\", "/"), a, int(b) if b else a, m.group(0), m.start(), lineno)
            )
    return out


class SpacedPathCapturedWhole(unittest.TestCase):
    def test_backticked_spaced_path_is_not_truncated(self) -> None:
        self.assertEqual(
            _cites("see `docs/my notes/x.md:12` for the rule"),
            [("docs/my notes/x.md", 12, 12)],
        )

    def test_backticked_spaced_path_with_range(self) -> None:
        self.assertEqual(
            _cites("the loop at `tools/my dir/x.py:9-11` retries"),
            [("tools/my dir/x.py", 9, 11)],
        )

    def test_raw_and_col_point_at_the_whole_path(self) -> None:
        line = "see `docs/my notes/x.md:12` for the rule"
        (cite,) = ca.extract_citations(line, "d.md")
        self.assertEqual(cite.raw, "docs/my notes/x.md:12")
        self.assertEqual(cite.col, line.index("docs/"))

    def test_spaced_cite_resolves_against_the_real_tracked_path(self) -> None:
        # The truncated tail `notes/x.md` is NOT a suffix key of this index
        # (the segment is `my notes`), which is why the old extractor graded
        # a real file FILE_MISSING.
        index = ca._Index(["docs/my notes/x.md", "docs/other.md"])
        (cite,) = ca.extract_citations("`docs/my notes/x.md:12`", "d.md")
        self.assertEqual(index.candidates(cite.path), ["docs/my notes/x.md"])

    def test_spaced_and_plain_cites_on_one_line_keep_line_order(self) -> None:
        self.assertEqual(
            _cites("`core/foo.py:3` then `docs/my notes/x.md:12` then `a/b.js:5`"),
            [("core/foo.py", 3, 3), ("docs/my notes/x.md", 12, 12), ("a/b.js", 5, 5)],
        )


class ProseIsNotWidened(unittest.TestCase):
    """Negative controls. Each fails if the spaced shape is searched loose."""

    def test_free_prose_is_not_joined_into_a_path(self) -> None:
        self.assertEqual(_cites("see notes and x.md:3 below"), [("x.md", 3, 3)])
        self.assertEqual(_cites("see notes/and x.md:3 below"), [("x.md", 3, 3)])

    def test_unbackticked_spaced_path_keeps_pre_rm435_tail(self) -> None:
        # Deliberate limit: outside a code span a space is prose, not a path.
        self.assertEqual(_cites("see docs/my notes/x.md:12"), [("notes/x.md", 12, 12)])

    def test_two_backtick_spans_on_one_line_are_not_paired_across(self) -> None:
        self.assertEqual(_cites("`docs/a b` and then `x.md:3`"), [("x.md", 3, 3)])

    def test_closing_backtick_is_never_read_as_opening(self) -> None:
        self.assertEqual(_cites("`x`s notes/y z.md:3`z`"), [("z.md", 3, 3)])

    def test_and_or_clock_time_yields_nothing(self) -> None:
        self.assertEqual(_cites("and/or 12:30"), [])

    def test_prose_arrow_span_from_the_real_tree_is_unchanged(self) -> None:
        # Shape measured in docs/LEDGER.md: a span holding prose plus a cite.
        self.assertEqual(
            _cites("`BACKLOG.md -> tools/rm_id_registry.py:58`"),
            [("tools/rm_id_registry.py", 58, 58)],
        )

    def test_segment_with_leading_or_trailing_space_is_not_a_path(self) -> None:
        self.assertEqual(_cites("`docs/ my/x.md:3`"), [("my/x.md", 3, 3)])
        # Pre-RM-435 result, kept: the left fence refuses a match after `/`.
        self.assertEqual(_cites("`docs /x.md:3`"), [])

    def test_span_carrying_prose_around_a_spaced_path_is_not_captured(self) -> None:
        # The bound is the WHOLE span. Prose inside it keeps the old reading.
        self.assertEqual(
            _cites("`docs/my notes/x.md:3 is the rule`"), [("notes/x.md", 3, 3)]
        )

    def test_single_segment_spaced_span_is_not_a_path(self) -> None:
        self.assertEqual(_cites("`see x.md:3`"), [("x.md", 3, 3)])


class UnspacedBehaviourIsIdentical(unittest.TestCase):
    CORPUS = "\n".join(
        [
            "see `core/foo.py:12` and `a/b.js:5-9`",
            "https://127.0.0.1:8888/api  ENGINE 1.235.0  DS :8860  at 12:30",
            "`BACKLOG.md -> tools/rm_id_registry.py:58` and core\\x.py:4",
            "prose tools/citation_audit.py:176-180 and `x`s notes/y z.md:3`z`",
            "- `docs/a b` and then `x.md:3` | `.github/x.yml:2 - 4`",
            "unpaired ` stray `core/foo.py:1` and `docs/my notes`",
        ]
    )

    def test_extractor_matches_the_old_algorithm_when_no_spaced_span(self) -> None:
        got = [
            (c.path, c.start, c.end, c.raw, c.col, c.doc_line)
            for c in ca.extract_citations(self.CORPUS, "d.md")
        ]
        self.assertEqual(got, _old_algorithm(self.CORPUS))
        self.assertGreater(len(got), 5)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
