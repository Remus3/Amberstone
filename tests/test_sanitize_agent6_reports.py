"""Guard: the agent6 report sanitizer actually clears the guard it exists for.

``tests/test_smart_quote_hygiene.py::test_agent6_reports_are_ascii`` has gone
red three times (2026-07-27, 2026-08-04, 2026-08-25) on reports committed by
cloud scheduled routines, which run in a fresh clone with no ``core.hooksPath``
and so never trip the local pre-commit gate.

The remediation the guard pointed at was ``tools/strip_smart_quotes.py
--apply``, and that tool does NOT map U+2713 - the dominant glyph the routines
emit. So the prescribed fix could not clear the guard, and every occurrence was
repaired by hand instead. ``test_the_old_tool_could_not_have_fixed_this`` pins
that gap so the two tools' division of labour cannot quietly rot back.

Everything here works on strings and tmp_path; nothing mutates the tracked
reports directory.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

from tools.sanitize_agent6_reports import GLYPH_MAP, sanitize_text

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TOOL = _REPO_ROOT / "tools" / "sanitize_agent6_reports.py"
_OLD_TOOL = _REPO_ROOT / "tools" / "strip_smart_quotes.py"

# The exact glyph mix of the 2026-08-25 incident: an em-dash in the H1 and
# eight check marks in a status table.
_INCIDENT_20260825 = (
    "# RC Weekly Health " + chr(0x2014) + " 2026-08-25\r\n"
    "\r\n"
    "| rewind_history.db | 0.00 B | " + chr(0x2713) + " |\r\n"
    "| match_history.db | 0.00 B | " + chr(0x2713) + " |\r\n"
)


class SanitizerBehaviourTests(unittest.TestCase):
    def test_check_mark_becomes_ok_not_dropped(self) -> None:
        # The charter's own prescription: "Write OK, not a tick."
        out, mapped, dropped = sanitize_text("status " + chr(0x2713))
        self.assertEqual(out, "status OK")
        self.assertEqual(mapped, {"U+2713": 1})
        self.assertEqual(dropped, {})

    def test_em_dash_becomes_spaced_hyphen(self) -> None:
        out, _, _ = sanitize_text("Health " + chr(0x2014) + " 2026-08-25")
        self.assertEqual(out, "Health  -  2026-08-25")
        self.assertTrue(out.isascii())

    def test_full_incident_text_becomes_ascii(self) -> None:
        out, mapped, dropped = sanitize_text(_INCIDENT_20260825)
        self.assertTrue(out.isascii(), "sanitizer left non-ASCII behind")
        self.assertEqual(mapped, {"U+2014": 1, "U+2713": 2})
        self.assertEqual(dropped, {})
        self.assertIn("| 0.00 B | OK |", out)

    def test_crlf_line_endings_survive(self) -> None:
        # Only non-ASCII codepoints are rewritten, so every CR and LF must
        # come through untouched and no bare LF may appear. Windows line
        # endings silently flipping is its own recurring defect class here.
        out, _, _ = sanitize_text(_INCIDENT_20260825)
        self.assertEqual(out.count("\r\n"), _INCIDENT_20260825.count("\r\n"))
        self.assertEqual(out.count("\n"), out.count("\r\n"),
                         "a bare LF appeared - CRLF was not preserved")

    def test_accented_letter_folds_rather_than_needing_a_map_entry(self) -> None:
        # Tier 2 (NFKD) exists so the map does not have to enumerate letters.
        out, mapped, dropped = sanitize_text(chr(0x00E9) + "clair")
        self.assertEqual(out, "eclair")
        self.assertEqual(dropped, {})
        self.assertEqual(mapped, {"U+00E9": 1})

    def test_unmappable_glyph_is_dropped_but_reported(self) -> None:
        # An emoji has no ASCII spelling. It must be removed, and the removal
        # must be visible - a silent drop is how a new glyph class hides.
        out, _, dropped = sanitize_text("build " + chr(0x1F680))
        self.assertTrue(out.isascii())
        self.assertEqual(dropped, {"U+1F680": 1})

    def test_ascii_input_is_returned_untouched(self) -> None:
        src = "# Report\r\n\r\n| db | 0.00 B | OK |\r\n"
        out, mapped, dropped = sanitize_text(src)
        self.assertEqual(out, src)
        self.assertEqual((mapped, dropped), ({}, {}))


class ToolContractTests(unittest.TestCase):
    def test_the_tool_source_is_itself_7bit_ascii(self) -> None:
        raw = _TOOL.read_bytes()
        self.assertEqual([b for b in raw if b > 127], [],
                         "the sanitizer must not need to be its own exclusion")

    def test_the_old_tool_could_not_have_fixed_this(self) -> None:
        """Pin the gap that made this module necessary.

        ``strip_smart_quotes.py`` handles dashes / quotes / ellipsis / NBSP
        and has NO notion of U+2713, so pointing the guard at it left the
        dominant glyph in place. If that tool ever learns check marks, this
        assertion fails and the two tools' split needs re-deciding on purpose
        rather than by drift.
        """
        old_src = _OLD_TOOL.read_text(encoding="utf-8")
        self.assertNotIn("2713", old_src)
        self.assertIn(chr(0x2713), GLYPH_MAP)

    def test_check_mode_exits_nonzero_on_a_dirty_file(self) -> None:
        # Drive the real CLI so the CI-facing exit code is covered, not just
        # the pure function underneath it.
        import tools.sanitize_agent6_reports as mod

        original = mod.REPORTS_DIR
        try:
            import tempfile

            with tempfile.TemporaryDirectory() as td:
                d = Path(td)
                (d / "dirty.md").write_bytes(
                    ("x " + chr(0x2713)).encode("utf-8")
                )
                mod.REPORTS_DIR = d
                self.assertEqual(mod.main(["--check"]), 1)
                self.assertEqual(mod.main(["--apply"]), 0)
                self.assertEqual((d / "dirty.md").read_bytes(), b"x OK")
                self.assertEqual(mod.main(["--check"]), 0)
        finally:
            mod.REPORTS_DIR = original

    def test_tracked_reports_dir_is_currently_clean(self) -> None:
        # The live assertion. Redundant with test_agent6_reports_are_ascii by
        # design: this one names the one-command fix in its own message.
        proc = subprocess.run(
            [sys.executable, str(_TOOL), "--check"],
            capture_output=True, text=True, cwd=str(_REPO_ROOT),
        )
        self.assertEqual(
            proc.returncode, 0,
            "agent6 reports carry non-ASCII. Fix with:\n"
            "  python tools/sanitize_agent6_reports.py --apply\n"
            + proc.stdout,
        )


if __name__ == "__main__":
    unittest.main()
