"""The precommit gate must block ANY non-ASCII on an added line, not 6 chars.

MEASURED 2026-07-28, a same-day incident that motivated this. ``_BANNED`` held
exactly six characters - em-dash, en-dash and four smart quotes - so every
other non-ASCII codepoint passed the gate unremarked. ``scripts/db_size_monitor.py``
used U+00D7 as a missing-file marker, that output is captured verbatim into the
weekly agent6 health report, the report is COMMITTED, and
``tests/test_smart_quote_hygiene.py`` asserts it is byte-ASCII. So a scheduled
task turned the suite red through a gate that was working exactly as written.

**The repo-wide ASCII assertion is stricter than the commit gate was.** That is
the defect: two rules that are supposed to enforce the same CLAUDE.md hard rule
("7-bit ASCII authored content") disagreed about what it means, and the looser
one ran first.

Scope is deliberately narrower than "every staged file". CLAUDE.md's retroactive
purge explicitly did NOT sweep logs, ``docs/_archive/**``, ``.jsonl`` ledgers,
binaries or ``.pyc`` - and upstream DATA (DDragon, Meraki mirrors) legitimately
carries non-ASCII champion and item names that RC does not author. Gating those
would block correct commits, and a gate that blocks correct work is one people
learn to bypass.
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_GATE = Path(__file__).resolve().parent.parent / "tools" / "precommit_gate.py"


def _gate():
    spec = importlib.util.spec_from_file_location("precommit_gate_uut", _GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class GlyphHitsTests(unittest.TestCase):

    def setUp(self) -> None:
        self.g = _gate()

    def test_the_six_named_glyphs_still_report_by_name(self) -> None:
        """Regression: widening must not lose the specific diagnostics."""
        for ch, name in (
            ("\u2014", "em-dash"), ("\u2013", "en-dash"),
            ("\u201c", "smart-dquote-open"), ("\u201d", "smart-dquote-close"),
            ("\u2018", "smart-quote-open"), ("\u2019", "smart-quote-close"),
        ):
            with self.subTest(ch=repr(ch)):
                hits = self.g._glyph_hits("prefix " + ch + " suffix", "a.py")
                self.assertIn(name, hits)

    def test_the_multiplication_sign_that_shipped_is_caught(self) -> None:
        """U+00D7 - the exact character that reached the repo on 2026-07-28."""
        hits = self.g._glyph_hits('mark = "  " if ok else "\u00d7 "', "scripts/db_size_monitor.py")
        self.assertTrue(hits, "U+00D7 must be blocked; it was not in the old 6-char set")

    def test_arbitrary_non_ascii_is_caught_and_names_its_codepoint(self) -> None:
        """A catch-all is only useful if the operator can see WHAT it caught."""
        hits = self.g._glyph_hits("x = '\u2713 done'", "tools/thing.py")
        self.assertTrue(hits)
        self.assertTrue(
            any("2713" in h.lower() for h in hits),
            f"the report must name the codepoint so it can be fixed; got {hits}",
        )

    def test_plain_ascii_is_never_flagged(self) -> None:
        """The false-positive side - measure it, do not assume it."""
        for line in (
            "def f(x): return x + 1",
            "# a comment - with a spaced hyphen",
            "assert d['Kai\\'Sa'] == 1  # apostrophe is ASCII",
            'print(f"{a}/{b} -> {c}")',
        ):
            with self.subTest(line=line):
                self.assertEqual([], self.g._glyph_hits(line, "a.py"))

    def test_unswept_surfaces_are_exempt(self) -> None:
        """CLAUDE.md's purge deliberately skipped these; the gate must too."""
        glyph = "value \u00d7 2"
        for path in (
            "logs/2026-07-28.log",
            "docs/_archive/old-note.md",
            "data/event_pattern_rates.jsonl",
            "agents/daemon_slayer/tests/fixtures/x.jsonl",
        ):
            with self.subTest(path=path):
                self.assertEqual(
                    [], self.g._glyph_hits(glyph, path),
                    f"{path} is an unswept surface and must not block a commit",
                )

    def test_upstream_data_mirrors_are_exempt(self) -> None:
        """RC does not author DDragon/Meraki names and cannot fix them."""
        for path in (
            "data/daemon_slayer/16.14.1/items.json",
            "data/daemon_slayer/16.14.1/champions.json",
        ):
            with self.subTest(path=path):
                self.assertEqual([], self.g._glyph_hits('"name": "Cho\u2019Gath"', path))

    def test_authored_markdown_and_powershell_are_in_scope(self) -> None:
        """The 2026-05-18 boot-script incident was a .ps1 - keep it gated."""
        for path in ("docs/NOTE.md", "tools/regen_rc_cert.ps1", "web/js/main.js"):
            with self.subTest(path=path):
                self.assertTrue(self.g._glyph_hits("a \u2014 b", path))


if __name__ == "__main__":
    unittest.main()
