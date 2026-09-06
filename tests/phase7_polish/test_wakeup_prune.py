"""
tests/phase7_polish/test_wakeup_prune.py
Phase 7 - auto-prune helper for WAKEUP_NOTES.md.

Verifies the parse -> render round-trip is byte-stable, and that pruning
moves the correct session blocks newest-first into the archive.
"""
import importlib.util
import sys
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))


def _load_module():
    """Load scripts/wakeup_prune.py without going through scripts.* import path
    (the scripts dir has no __init__.py)."""
    spec = importlib.util.spec_from_file_location(
        "wakeup_prune",
        _PROJECT_ROOT / "scripts" / "wakeup_prune.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


WP = _load_module()


# -- Synthetic fixtures --------------------------------------------------------

HEADER = (
    "# WAKEUP_NOTES - RC hand-off ledger\n"
    "\n"
    "> Sessions s27-s137 archived to `docs/history_notes.md`. Only the last 3 sessions kept here.\n"
)


def _session(sid: str, body: str = "stuff happened") -> str:
    return f"# {sid} wrap - 2026-05-09\n\n## What shipped\n- {body}\n"


def _doc(sessions: list[str]) -> str:
    """Build a synthetic WAKEUP_NOTES.md mirroring the real-file shape.

    Real shape (verified against the live file): each section ends with `\\n`,
    followed by `\\n---\\n\\n` (blank line BEFORE rule, blank line AFTER) before
    the next section.
    """
    if not sessions:
        return HEADER + "\n"
    body_parts = [s.rstrip("\n") + "\n" for s in sessions]
    return HEADER + "\n---\n\n" + "\n---\n\n".join(body_parts)


# -- Tests ---------------------------------------------------------------------

class TestSplit(unittest.TestCase):
    def test_three_sessions_split_cleanly(self):
        text = _doc([_session("s141"), _session("s140"), _session("s139")])
        header, sessions = WP.split_sessions(text)
        self.assertEqual(len(sessions), 3)
        self.assertIn("s141", sessions[0])
        self.assertIn("s140", sessions[1])
        self.assertIn("s139", sessions[2])
        self.assertIn("hand-off ledger", header)

    def test_no_sessions_returns_header_only(self):
        text = HEADER + "\n"
        header, sessions = WP.split_sessions(text)
        self.assertEqual(sessions, [])
        self.assertEqual(header.strip(), HEADER.strip())

    def test_single_session(self):
        text = _doc([_session("s141")])
        _, sessions = WP.split_sessions(text)
        self.assertEqual(len(sessions), 1)
        self.assertIn("s141", sessions[0])


class TestRender(unittest.TestCase):
    def test_round_trip_three_sessions(self):
        original = _doc([_session("s141"), _session("s140"), _session("s139")])
        header, sessions = WP.split_sessions(original)
        rendered = WP.render(header, sessions)
        # Round-trip should produce same content (modulo trailing newlines).
        self.assertEqual(rendered.strip(), original.strip())

    def test_render_no_sessions(self):
        rendered = WP.render(HEADER, [])
        self.assertEqual(rendered, HEADER.rstrip("\n") + "\n")

    def test_render_preserves_blank_line_before_separator(self):
        # Regression for s142 dogfood bug: render() was stripping the natural
        # trailing \n on each block, collapsing `4. bullet\n\n---\n\n# next`
        # to `4. bullet\n---\n\n# next` (missing blank line before ---).
        s1 = "# s002 wrap - 2026-01-02\n\n## What's next\n4. last bullet\n"
        s2 = "# s001 wrap - 2026-01-01\n\n## What's next\n3. older bullet\n"
        rendered = WP.render(HEADER, [s1, s2])
        # Blank line BEFORE the separator that follows each session.
        self.assertIn("4. last bullet\n\n---\n\n# s001", rendered)

    def test_render_repairs_buggy_input(self):
        # If the on-disk file is ALREADY missing the blank line (e.g. legacy
        # bug), parse + re-render should restore the canonical shape.
        buggy = (
            HEADER
            + "\n---\n\n"
            + "# s002 wrap - 2026-01-02\n\n## last\n4. bullet\n"  # no extra \n
            + "---\n\n"  # missing leading \n - buggy
            + "# s001 wrap - 2026-01-01\n\n## last\n3. older\n"
        )
        header, sessions = WP.split_sessions(buggy)
        rendered = WP.render(header, sessions)
        self.assertIn("4. bullet\n\n---\n\n# s001", rendered)


class TestDatedAndPinnedFormat(unittest.TestCase):
    """Real-file shape regression (s235): recent sessions use a dated heading
    (`# 2026-05-17 (late) - ...`) not the legacy `# sNNN wrap`, and the file
    opens with a pinned non-session block (`# \u2705 RESOLVED ... `) right after the
    top header. Pre-fix, SESSION_RE matched neither, so split_sessions
    tail-dumped them all into `extras` (inverting newest/oldest) and prune()
    crashed at the moved_ids line - a lucky guard against mis-archiving the
    newest sessions + un-pinning the RESOLVED block.
    """

    PIN = (
        "# \u2705 RESOLVED 2026-05-17 - champ-select wrong for ARAM\n"
        "\nResolved-block body that must never be archived.\n"
    )

    @staticmethod
    def _dated(date: str, label: str, body: str = "stuff") -> str:
        return f"# {date} {label}\n\n## What shipped\n- {body}\n"

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="rc_wakeup_dated_"))
        self._orig_wakeup = WP.WAKEUP
        self._orig_archive = WP.ARCHIVE
        WP.WAKEUP = self.tmp / "WAKEUP_NOTES.md"
        WP.ARCHIVE = self.tmp / "docs" / "history_notes.md"

    def tearDown(self):
        WP.WAKEUP = self._orig_wakeup
        WP.ARCHIVE = self._orig_archive
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- regex ------------------------------------------------------------
    def test_session_re_matches_dated_headings(self):
        for h in (
            "# 2026-05-17 (late) - KEYSTONE champ-select",
            "# 2026-05-17 (eve) - build-order UI",
            "# 2026-05-17 wrap - Vanguard crash",
            "# 2026-05-17 OVERNIGHT RUN-1 - contextual DS",
        ):
            self.assertIsNotNone(WP.SESSION_RE.match(h), h)

    def test_session_re_still_matches_legacy(self):
        self.assertIsNotNone(WP.SESSION_RE.match("# s234 wrap - 2026-05-17"))
        self.assertIsNotNone(
            WP.SESSION_RE.match("# s209-s213 wrap - 2026-05-16"))

    def test_session_re_does_not_match_pin(self):
        self.assertIsNone(
            WP.SESSION_RE.match(
                "# \u2705 RESOLVED 2026-05-17 - champ-select wrong"))

    # -- split ------------------------------------------------------------
    def test_leading_pin_folds_into_header_not_sessions(self):
        text = _doc([
            self.PIN,
            self._dated("2026-05-17", "(late) - keystone"),
            self._dated("2026-05-16", "(eve) - build order"),
        ])
        header, sessions = WP.split_sessions(text)
        self.assertEqual(len(sessions), 2)
        self.assertIn("RESOLVED", header)
        self.assertTrue(all("RESOLVED" not in s for s in sessions))
        self.assertIn("(late)", sessions[0])
        self.assertIn("(eve)", sessions[1])

    def test_pinned_dated_round_trip_is_stable(self):
        original = _doc([
            self.PIN,
            self._dated("2026-05-17", "(late) - a"),
            self._dated("2026-05-16", "(eve) - b"),
        ])
        header, sessions = WP.split_sessions(original)
        self.assertEqual(WP.render(header, sessions).strip(), original.strip())

    # -- prune ------------------------------------------------------------
    def test_prune_keeps_newest_dated_archives_oldest_pin_retained(self):
        WP.WAKEUP.write_text(_doc([
            self.PIN,
            self._dated("2026-05-17", "(late) - newest"),
            self._dated("2026-05-16", "(eve) - mid"),
            self._dated("2026-05-15", "wrap - old1"),
            self._dated("2026-05-14", "wrap - old2"),
            self._dated("2026-05-13", "wrap - old3"),
        ]), encoding="utf-8")
        rc = WP.prune(keep=3, dry_run=False)
        self.assertEqual(rc, 0)

        wakeup_after = WP.WAKEUP.read_text(encoding="utf-8")
        self.assertIn("RESOLVED", wakeup_after)            # pin retained
        self.assertIn("newest", wakeup_after)
        self.assertIn("mid", wakeup_after)
        self.assertIn("old1", wakeup_after)
        self.assertNotIn("old2", wakeup_after)
        self.assertNotIn("old3", wakeup_after)

        archive_after = WP.ARCHIVE.read_text(encoding="utf-8")
        self.assertNotIn("RESOLVED", archive_after)        # pin never archived
        self.assertIn("old2", archive_after)
        self.assertIn("old3", archive_after)
        # Newest-first inside the archive (old2 before old3).
        self.assertLess(
            archive_after.index("old2"), archive_after.index("old3"))

    def test_prune_does_not_crash_on_pin_in_move_slice(self):
        # The original crash: a non-session block in the move slice hitting
        # SESSION_RE.search(b).group(0) -> AttributeError.
        WP.WAKEUP.write_text(_doc([
            self.PIN,
            self._dated("2026-05-17", "(late) - a"),
            self._dated("2026-05-16", "(eve) - b"),
            self._dated("2026-05-15", "wrap - c"),
            self._dated("2026-05-14", "wrap - d"),
        ]), encoding="utf-8")
        self.assertEqual(WP.prune(keep=2, dry_run=True), 0)


class TestSessionReSuffixedDate(unittest.TestCase):
    """Regression: the dated alternative of SESSION_RE ended in `\\b`, so a
    heading whose date is followed directly by a word char - the letter-suffixed
    `# 2026-07-19a` form used when two sessions wrap on one calendar day - never
    matched. split_sessions then found ZERO sessions, so prune() and --check
    both reported "nothing to do" at ANY file size and WAKEUP_NOTES.md grew
    unbounded. The comment block above SESSION_RE documents the intent as "any
    suffix after the date", so the regex contradicted its own contract.

    The pinned-block exclusion documented alongside it must survive the fix: a
    leading `# <checkmark> RESOLVED <date> - ...` block matches NEITHER
    alternative, because its date is not at heading-start.
    """

    # Written as a \\u escape so this source file stays 7-bit ASCII (repo rule)
    # while the runtime string still carries the real U+2705 the live file uses.
    PIN_CHECKMARK = "# \u2705 RESOLVED 2026-05-17 - champ-select wrong for ARAM"
    PIN_ASCII = "# RESOLVED 2026-05-17 - champ-select wrong for ARAM"

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="rc_wakeup_suffix_"))
        self._orig_wakeup = WP.WAKEUP
        self._orig_archive = WP.ARCHIVE
        WP.WAKEUP = self.tmp / "WAKEUP_NOTES.md"
        WP.ARCHIVE = self.tmp / "docs" / "history_notes.md"

    def tearDown(self):
        WP.WAKEUP = self._orig_wakeup
        WP.ARCHIVE = self._orig_archive
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def _block(heading: str, body: str) -> str:
        return f"{heading}\n\n## What shipped\n- {body}\n"

    # -- regex contract ---------------------------------------------------
    def test_plain_dated_heading_matches(self):
        for h in (
            "# 2026-07-19",
            "# 2026-07-19 wrap - phase 2 tails",
            "# 2026-07-19 (late) - paren suffix",
        ):
            self.assertIsNotNone(WP.SESSION_RE.match(h), h)

    def test_letter_suffixed_dated_heading_matches(self):
        # THE BUG: there is no word boundary between "9" and "a", so the old
        # `\\b`-terminated pattern rejected every letter-suffixed heading.
        for h in (
            "# 2026-07-19a",
            "# 2026-07-19a - second wrap of the day",
            "# 2026-07-19b (eve) - third wrap of the day",
            "# 2026-05-17c wrap - trailing label",
        ):
            self.assertIsNotNone(WP.SESSION_RE.match(h), h)

    def test_legacy_snn_wrap_heading_still_matches(self):
        for h in (
            "# s234 wrap",
            "# s234 wrap - 2026-05-17",
            "# s171.8 wrap - dotted",
            "# s209-s213 wrap - range",
        ):
            self.assertIsNotNone(WP.SESSION_RE.match(h), h)

    def test_pinned_block_still_matches_neither_alternative(self):
        # Must hold for the live checkmark form AND a hypothetical ASCII-swept
        # form: the exclusion rests on the date not being at heading-start.
        for h in (self.PIN_CHECKMARK, self.PIN_ASCII):
            self.assertIsNone(WP.SESSION_RE.match(h), h)

    def test_non_heading_lines_still_match_neither(self):
        for h in (
            "## 2026-07-19a - h2 is not a session heading",
            "#2026-07-19a - no space after the hash",
            "text 2026-07-19a - not a heading at all",
        ):
            self.assertIsNone(WP.SESSION_RE.match(h), h)

    # -- end-to-end -------------------------------------------------------
    def test_suffixed_sessions_split_instead_of_vanishing(self):
        text = _doc([
            self.PIN_CHECKMARK + "\n\nPinned body.\n",
            self._block("# 2026-07-19b (eve)", "NEWEST"),
            self._block("# 2026-07-19a", "MIDDLE"),
            self._block("# 2026-07-19", "OLDEST"),
        ])
        header, sessions = WP.split_sessions(text)
        self.assertEqual(len(sessions), 3)
        self.assertIn("RESOLVED", header)
        self.assertIn("NEWEST", sessions[0])
        self.assertIn("MIDDLE", sessions[1])
        self.assertIn("OLDEST", sessions[2])

    def test_check_reports_overflow_for_suffixed_headings(self):
        # Pre-fix this returned 0 ("nothing to do") at any file size, because
        # split_sessions found zero matching headings.
        WP.WAKEUP.write_text(_doc([
            self._block("# 2026-07-19d", "S4"),
            self._block("# 2026-07-19c", "S3"),
            self._block("# 2026-07-19b", "S2"),
            self._block("# 2026-07-19a", "S1"),
        ]), encoding="utf-8")
        self.assertEqual(WP.check(keep=3), 1)

    def test_prune_archives_oldest_suffixed_session(self):
        WP.WAKEUP.write_text(_doc([
            self.PIN_CHECKMARK + "\n\nPinned body.\n",
            self._block("# 2026-07-19d", "KEEP3"),
            self._block("# 2026-07-19c", "KEEP2"),
            self._block("# 2026-07-19b", "KEEP1"),
            self._block("# 2026-07-19a", "MOVED"),
        ]), encoding="utf-8")
        self.assertEqual(WP.prune(keep=3, dry_run=False), 0)

        wakeup_after = WP.WAKEUP.read_text(encoding="utf-8")
        self.assertIn("RESOLVED", wakeup_after)        # pin retained
        self.assertIn("KEEP1", wakeup_after)
        self.assertNotIn("MOVED", wakeup_after)

        archive_after = WP.ARCHIVE.read_text(encoding="utf-8")
        self.assertIn("MOVED", archive_after)
        self.assertNotIn("RESOLVED", archive_after)    # pin never archived


class TestPrune(unittest.TestCase):
    def setUp(self):
        # Redirect WAKEUP/ARCHIVE constants to a tmp dir for the test.
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="rc_wakeup_test_"))
        self._orig_wakeup = WP.WAKEUP
        self._orig_archive = WP.ARCHIVE
        WP.WAKEUP = self.tmp / "WAKEUP_NOTES.md"
        WP.ARCHIVE = self.tmp / "docs" / "history_notes.md"

    def tearDown(self):
        WP.WAKEUP = self._orig_wakeup
        WP.ARCHIVE = self._orig_archive
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_keep_3_with_5_sessions_moves_oldest_2(self):
        WP.WAKEUP.write_text(_doc([
            _session("s145"), _session("s144"), _session("s143"),
            _session("s142"), _session("s141"),
        ]), encoding="utf-8")
        rc = WP.prune(keep=3, dry_run=False)
        self.assertEqual(rc, 0)

        wakeup_after = WP.WAKEUP.read_text(encoding="utf-8")
        self.assertIn("s145", wakeup_after)
        self.assertIn("s144", wakeup_after)
        self.assertIn("s143", wakeup_after)
        self.assertNotIn("s142", wakeup_after)
        self.assertNotIn("s141", wakeup_after)

        archive_after = WP.ARCHIVE.read_text(encoding="utf-8")
        self.assertIn("s142", archive_after)
        self.assertIn("s141", archive_after)
        # Newer-first inside the archive (s142 before s141).
        self.assertLess(archive_after.index("s142"), archive_after.index("s141"))

    def test_no_prune_when_at_or_under_keep(self):
        WP.WAKEUP.write_text(
            _doc([_session("s141"), _session("s140")]), encoding="utf-8")
        rc = WP.prune(keep=3, dry_run=False)
        self.assertEqual(rc, 0)
        self.assertFalse(WP.ARCHIVE.exists())

    def test_dry_run_writes_nothing(self):
        text = _doc([
            _session("s145"), _session("s144"), _session("s143"),
            _session("s142"), _session("s141"),
        ])
        WP.WAKEUP.write_text(text, encoding="utf-8")
        rc = WP.prune(keep=3, dry_run=True)
        self.assertEqual(rc, 0)
        # File unchanged + archive not created.
        self.assertEqual(WP.WAKEUP.read_text(encoding="utf-8"), text)
        self.assertFalse(WP.ARCHIVE.exists())

    def test_appends_to_existing_archive(self):
        WP.WAKEUP.write_text(_doc([
            _session("s145"), _session("s144"), _session("s143"),
            _session("s142"),
        ]), encoding="utf-8")
        WP.ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
        # Pre-seed archive with an older session.
        WP.ARCHIVE.write_text(
            WP.ARCHIVE_HEADER + "\n---\n\n" + _session("s140").strip("\n") + "\n",
            encoding="utf-8",
        )
        rc = WP.prune(keep=3, dry_run=False)
        self.assertEqual(rc, 0)
        archive_after = WP.ARCHIVE.read_text(encoding="utf-8")
        self.assertIn("s142", archive_after)
        self.assertIn("s140", archive_after)
        # Newly archived (s142) appears above the pre-existing s140.
        self.assertLess(archive_after.index("s142"), archive_after.index("s140"))

    def test_check_passes_when_within_limit(self):
        WP.WAKEUP.write_text(
            _doc([_session("s141"), _session("s140")]), encoding="utf-8")
        self.assertEqual(WP.check(keep=3), 0)

    def test_check_fails_when_over_limit(self):
        WP.WAKEUP.write_text(_doc([
            _session("s145"), _session("s144"), _session("s143"),
            _session("s142"), _session("s141"),
        ]), encoding="utf-8")
        self.assertEqual(WP.check(keep=3), 1)


class TestKeepCountIsBounded(unittest.TestCase):
    """RM-363 sibling sweep. The third instance of the same root cause.

    `--keep` is `type=int` with no range, and the only test on it is the
    early-out `if len(sessions) <= keep`, which any non-positive value sails
    straight through. At `keep=0` the split is `sessions[:0]` / `sessions[0:]`,
    so EVERY session including the current one is relocated and
    `WAKEUP_NOTES.md` is rewritten down to its header. At `keep=-1` the knob
    inverts: it keeps all but the oldest and archives that one instead.

    Lower severity than the two rmtree siblings - the displaced blocks are
    written to `docs/history_notes.md`, so nothing is unlinked and the
    content survives - but it still empties the live hand-off ledger, which
    `CLAUDE.md` makes the session-to-session continuity record.
    """

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="rc_wakeup_keep_"))
        self._orig_wakeup = WP.WAKEUP
        self._orig_archive = WP.ARCHIVE
        WP.WAKEUP = self.tmp / "WAKEUP_NOTES.md"
        WP.ARCHIVE = self.tmp / "docs" / "history_notes.md"
        WP.WAKEUP.write_text(
            _doc([_session("s150"), _session("s149"), _session("s148"),
                  _session("s147")]),
            encoding="utf-8",
        )

    def tearDown(self):
        WP.WAKEUP = self._orig_wakeup
        WP.ARCHIVE = self._orig_archive
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _sessions_left(self) -> int:
        _, sessions = WP.split_sessions(
            WP.WAKEUP.read_text(encoding="utf-8"))
        return len(sessions)

    def test_keep_zero_is_refused_and_the_ledger_is_untouched(self):
        before = WP.WAKEUP.read_text(encoding="utf-8")

        rc = WP.prune(keep=0, dry_run=False)

        self.assertEqual(rc, 2)
        self.assertEqual(WP.WAKEUP.read_text(encoding="utf-8"), before,
                         "a keep-zero prune rewrote WAKEUP_NOTES")
        self.assertEqual(self._sessions_left(), 4)

    def test_negative_keep_is_refused(self):
        rc = WP.prune(keep=-1, dry_run=False)

        self.assertEqual(rc, 2)
        self.assertEqual(self._sessions_left(), 4)

    def test_check_mode_refuses_the_same_value(self):
        """`--check` takes the same knob down a second path and writes
        nothing, but it must not report a bad policy as a clean tree."""
        self.assertEqual(WP.check(keep=0), 2)

    def test_keep_one_still_prunes(self):
        """Anti-vacuity: the smallest legal value must still do its job."""
        rc = WP.prune(keep=1, dry_run=False)

        self.assertEqual(rc, 0)
        self.assertEqual(self._sessions_left(), 1)

    def test_the_shipped_default_still_prunes(self):
        rc = WP.prune(keep=3, dry_run=False)

        self.assertEqual(rc, 0)
        self.assertEqual(self._sessions_left(), 3)


if __name__ == "__main__":
    unittest.main()
