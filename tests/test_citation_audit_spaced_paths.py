"""RM-435: `tools/citation_audit.py` must not truncate a spaced path to its tail.

`CITATION_RE` segments are `[\\w.-]+`, so a backticked `docs/my notes/x.md:12`
was extracted as `notes/x.md:12` and graded against the WRONG path
(FILE_MISSING, because `notes/x.md` is not a suffix of any tracked path).

Two fences, both load-bearing:

* BOUND (channel-pin precedent 1f42fd481 + 8e85ded6f): a spaced reading exists
  only when the citation is the WHOLE content of ONE paired backtick span.
* RESOLVE-FIRST: command-style spans such as `python tools/x.py:3` fit the same
  shape. The first cut (bb2686c8b) took the spaced reading unconditionally and
  turned three resolving cites into FILE_MISSING. Now the plain tail wins
  whenever it resolves; the spaced reading is taken only when the tail does
  not resolve AND the whole spaced path does. Extraction runs before the
  tracked-path index exists, so the choice lives at classification
  (`prefer_resolving_reading`), and `extract_citations` itself is unchanged.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools import citation_audit as ca  # noqa: E402


def _index_from(root: Path, rels: list[str]) -> ca._Index:
    """A tracked-path index over REAL files created under `root`."""
    for rel in rels:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("line\n" * 30, encoding="ascii")
    found = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
    assert found == sorted(rels)
    return ca._Index(found)


def _classify(text: str, index: ca._Index) -> list[tuple[str, int, int, bool]]:
    out = []
    for cite in ca.extract_citations(text, "d.md"):
        cands = ca.prefer_resolving_reading(cite, index)
        out.append((cite.path, cite.start, cite.end, bool(cands)))
    return out


def _cites(text: str) -> list[tuple[str, int, int]]:
    return [(c.path, c.start, c.end) for c in ca.extract_citations(text, "d.md")]


def _old_algorithm(text: str) -> list[tuple[str, int, int, str, int, int]]:
    """The pre-RM-435 extractor, in effect: CITATION_RE only."""
    out = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for m in ca.CITATION_RE.finditer(line):
            b = m.group(3)
            a = int(m.group(2))
            out.append(
                (m.group(1).replace("\\", "/"), a, int(b) if b else a, m.group(0), m.start(), lineno)
            )
    return out


# --- regressions the verifier found against bb2686c8b -----------------------


@pytest.fixture
def plain_tree(tmp_path: Path) -> ca._Index:
    return _index_from(tmp_path, ["docs/x.md", "tools/x.py", "tools/y.py"])


def test_command_style_see_span_keeps_the_resolving_plain_cite(plain_tree):
    assert _classify("`see docs/x.md:3`", plain_tree) == [("docs/x.md", 3, 3, True)]


def test_command_style_python_span_keeps_the_resolving_plain_cite(plain_tree):
    assert _classify("`python tools/x.py:3`", plain_tree) == [("tools/x.py", 3, 3, True)]


def test_two_command_style_spans_on_one_line_keep_both_plain_cites(plain_tree):
    got = _classify("`see docs/x.md:3` and `in tools/y.py:4-6`", plain_tree)
    assert got == [("docs/x.md", 3, 3, True), ("tools/y.py", 4, 6, True)]


# --- positive spaced cases, backed by real files ---------------------------


@pytest.fixture
def spaced_tree(tmp_path: Path) -> ca._Index:
    return _index_from(tmp_path, ["docs/my notes/x.md", "tools/my dir/x.py", "core/foo.py"])


def test_spaced_path_resolves_whole_when_its_tail_does_not(spaced_tree):
    assert _classify("see `docs/my notes/x.md:12` here", spaced_tree) == [
        ("docs/my notes/x.md", 12, 12, True)
    ]


def test_spaced_path_with_range_resolves_whole(spaced_tree):
    assert _classify("loop at `tools/my dir/x.py:9-11`", spaced_tree) == [
        ("tools/my dir/x.py", 9, 11, True)
    ]


def test_spaced_reading_moves_raw_and_col_to_the_whole_path(spaced_tree):
    line = "see `docs/my notes/x.md:12` for the rule"
    (cite,) = ca.extract_citations(line, "d.md")
    ca.prefer_resolving_reading(cite, spaced_tree)
    assert cite.raw == "docs/my notes/x.md:12"
    assert cite.col == line.index("docs/")


def test_spaced_and_plain_cites_on_one_line_keep_line_order(spaced_tree):
    got = _classify("`core/foo.py:3` then `docs/my notes/x.md:12`", spaced_tree)
    assert got == [("core/foo.py", 3, 3, True), ("docs/my notes/x.md", 12, 12, True)]


def test_both_readings_failing_keeps_the_old_plain_reading(tmp_path):
    index = _index_from(tmp_path, ["core/foo.py"])
    assert _classify("`docs/my notes/x.md:12`", index) == [("notes/x.md", 12, 12, False)]


def test_truncated_tail_alone_would_not_resolve(spaced_tree):
    # Before RM-435 the truncated tail made this FILE_MISSING.
    (cite,) = ca.extract_citations("`docs/my notes/x.md:12`", "d.md")
    assert spaced_tree.candidates(cite.path) == []
    assert ca.prefer_resolving_reading(cite, spaced_tree) == ["docs/my notes/x.md"]


# --- the bound: never searched loose ---------------------------------------


class ProseIsNotWidened(unittest.TestCase):
    """Negative controls. Each fails if the spaced shape is searched loose."""

    def _spaced(self, text: str) -> list:
        return [c.spaced_reading for c in ca.extract_citations(text, "d.md") if c.spaced_reading]

    def test_free_prose_carries_no_spaced_reading(self) -> None:
        self.assertEqual(_cites("see notes/and x.md:3 below"), [("x.md", 3, 3)])
        self.assertEqual(self._spaced("see notes/and x.md:3 below"), [])
        self.assertEqual(self._spaced("see docs/my notes/x.md:12"), [])

    def test_two_backtick_spans_on_one_line_are_not_paired_across(self) -> None:
        self.assertEqual(self._spaced("`docs/a b` and then `x.md:3`"), [])

    def test_closing_backtick_is_never_read_as_opening(self) -> None:
        self.assertEqual(self._spaced("`x`s notes/y z.md:3`z`"), [])

    def test_and_or_clock_time_yields_nothing(self) -> None:
        self.assertEqual(_cites("and/or 12:30"), [])

    def test_span_carrying_prose_after_the_cite_has_no_spaced_reading(self) -> None:
        self.assertEqual(self._spaced("`docs/my notes/x.md:3 is the rule`"), [])

    def test_segment_with_leading_or_trailing_space_has_no_spaced_reading(self) -> None:
        self.assertEqual(self._spaced("`docs/ my/x.md:3`"), [])
        self.assertEqual(self._spaced("`docs /x.md:3`"), [])

    def test_whole_span_spaced_cite_does_carry_a_reading(self) -> None:
        # Positive control for the helper above, so an always-empty
        # extractor cannot pass the negative arms.
        self.assertEqual(
            self._spaced("`docs/my notes/x.md:12`"),
            [(1, "docs/my notes/x.md", "docs/my notes/x.md:12")],
        )


class UnspacedBehaviourIsIdentical(unittest.TestCase):
    CORPUS = "\n".join(
        [
            "see `core/foo.py:12` and `a/b.js:5-9`",
            "https://127.0.0.1:8888/api  ENGINE 1.235.0  DS :8860  at 12:30",
            "`BACKLOG.md -> tools/rm_id_registry.py:58` and core\\x.py:4",
            "prose tools/citation_audit.py:176-180 and `x`s notes/y z.md:3`z`",
            "- `docs/a b` and then `x.md:3` | `.github/x.yml:2 - 4`",
            "`see docs/x.md:3` and `in tools/y.py:4-6` `docs/my notes/x.md:12`",
        ]
    )

    def test_extractor_output_equals_the_old_algorithm(self) -> None:
        got = [
            (c.path, c.start, c.end, c.raw, c.col, c.doc_line)
            for c in ca.extract_citations(self.CORPUS, "d.md")
        ]
        self.assertEqual(got, _old_algorithm(self.CORPUS))
        self.assertGreater(len(got), 5)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
