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


class TestSplitterBlindnessRM276(unittest.TestCase):
    """RM-276. `split_sessions` had TWO blindnesses, not one, and a fix that
    closed only the first would have gone green with the second still live.

    (4a) FIRST-PART BLINDNESS. `split_sessions` does `text.split(SEP)` and
    takes `parts[0]` as the pinned header without ever scanning it, so a
    /done append that omits the `\\n---\\n\\n` separator lands its heading
    inside `parts[0]` and is returned INSIDE the header block - the one block
    prune never archives. `_split_on_interior_headings`, which exists exactly
    to recover glued blocks, was reached only for `parts[1:]`.

    (4b) INTERIOR-HEADING-IN-A-LATER-BLOCK BLINDNESS. The per-block gate was
    `SESSION_RE.match(block.lstrip("\\n"))`, so ONLY a block that STARTS with
    a heading was ever re-split. A block that does not start with a heading
    but CONTAINS one fell through to `leading_pins` (folded into the header,
    unarchivable) or to `trailing_extras` (appended whole, so several glued
    sessions counted as one). This fires with ZERO headings in `parts[0]`,
    which is why splitting `parts[0]` alone provably cannot reach it - hence
    one arm per route SHAPE below.

    DISARM RECORD (RM-276 acceptance clause 3, as tightened 2026-09-18 -
    numbers returned by `split_sessions`, not a verdict). Observed by driving
    the real module over these exact fixtures at HEAD `1c7726330`:

        CONTROL  (all SEP-separated)  3 of 3 before -> 3 of 3 after
        ARM-4a   (glued parts[0])     2 of 3 before -> 3 of 3 after
        ARM-4b-i (leading_pins)       2 of 3 before -> 3 of 3 after
        ARM-4b-ii(trailing_extras)    2 of 3 before -> 3 of 3 after
        BONUS    (no SEP anywhere)    0 of 3 before -> 3 of 3 after

    The CONTROL returns 3 of 3 both before and after on purpose: it is a
    control, NOT a guard arm. The row says so explicitly - a fixture in which
    every session is properly separated passes against the unfixed splitter
    and therefore proves nothing. It is kept only to show the fix did not
    break the well-formed shape.
    """

    HEADER = "# RC wakeup notes\n\nOperator hand-off file.\n"
    S1 = "# 2026-09-18 - session one\n\nbody one\n"
    S2 = "# 2026-09-17 - session two\n\nbody two\n"
    S3 = "# 2026-09-16 - session three\n\nbody three\n"
    STRAY = "leftover prose with no heading\n\n"

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="rc_wakeup_rm276_"))
        self._orig_wakeup = WP.WAKEUP
        self._orig_archive = WP.ARCHIVE
        WP.WAKEUP = self.tmp / "WAKEUP_NOTES.md"
        WP.ARCHIVE = self.tmp / "docs" / "history_notes.md"

    def tearDown(self):
        WP.WAKEUP = self._orig_wakeup
        WP.ARCHIVE = self._orig_archive
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- the five fixture shapes ------------------------------------------
    def _control(self) -> str:
        return (self.HEADER + WP.SEP + self.S1 + WP.SEP + self.S2
                + WP.SEP + self.S3)

    def _glued_parts0(self) -> str:
        """ARM-4a: the first session is glued into `parts[0]` behind a blank
        line instead of a separator. Its later sessions carry a REAL
        separator, which is what makes this a VALID synthetic per clause (2)
        rather than the worthless all-separated shape."""
        return (self.HEADER + "\n" + self.S1 + WP.SEP + self.S2
                + WP.SEP + self.S3)

    def _stray_ahead_of_first_block(self) -> str:
        """ARM-4b-i, the `leading_pins` route SHAPE: ZERO headings in
        `parts[0]`; the FIRST rest-block carries one stray non-heading line
        ahead of its heading, so the gate rejects it before any session has
        been seen and the block is folded into the header."""
        return (self.HEADER + WP.SEP + self.STRAY + self.S1 + WP.SEP
                + self.S2 + WP.SEP + self.S3)

    def _stray_ahead_of_later_block(self) -> str:
        """ARM-4b-ii, the `trailing_extras` route SHAPE: ZERO headings in
        `parts[0]`; a LATER block - reached after a session has already been
        seen - carries one stray non-heading line ahead of TWO headings, so
        two sessions are appended whole as a single unsplit tail block."""
        return (self.HEADER + WP.SEP + self.S1 + WP.SEP + self.STRAY
                + self.S2 + "\n" + self.S3)

    def _no_separator_anywhere(self) -> str:
        """BONUS arm, not required by clause (4): with no `SEP` in the file
        at all, the old separator-presence early return reported zero
        sessions at any file size. Scanning `parts[0]` "rather than by
        assuming a separator" closes this too."""
        return self.HEADER + "\n" + self.S1 + "\n" + self.S2 + "\n" + self.S3

    @staticmethod
    def _headings(text: str) -> int:
        return len(WP.SESSION_RE.findall(text))

    # -- CONTROL (not a guard arm) ----------------------------------------
    def test_control_every_session_separated_is_a_control_not_an_arm(self):
        header, sessions = WP.split_sessions(self._control())

        self.assertEqual(len(sessions), 3)
        self.assertEqual(self._headings(header), 0)

    # -- ARM 4a: first-part blindness --------------------------------------
    def test_arm_4a_session_glued_into_parts0_is_found(self):
        text = self._glued_parts0()
        self.assertEqual(self._headings(text.split(WP.SEP)[0]), 1,
                         "fixture must actually hide a heading in parts[0]")

        header, sessions = WP.split_sessions(text)

        self.assertEqual(len(sessions), 3)
        self.assertEqual(
            self._headings(header), 0,
            "a session left inside the header block can never be archived")
        self.assertIn("session one", sessions[0])
        self.assertIn("session two", sessions[1])
        self.assertIn("session three", sessions[2])

    # -- ARM 4b-i: interior heading, leading_pins SHAPE --------------------
    def test_arm_4b_i_stray_line_ahead_of_first_block_heading(self):
        text = self._stray_ahead_of_first_block()
        self.assertEqual(
            self._headings(text.split(WP.SEP)[0]), 0,
            "this arm must fire with ZERO headings in parts[0], or it is "
            "just arm 4a again and a parts[0]-only fix would pass it")

        header, sessions = WP.split_sessions(text)

        self.assertEqual(len(sessions), 3)
        self.assertEqual(self._headings(header), 0)
        self.assertIn("session one", sessions[0])
        self.assertIn("session two", sessions[1])
        self.assertIn("session three", sessions[2])
        self.assertIn("leftover prose", "".join(sessions) + header,
                      "content must never be silently dropped")

    # -- ARM 4b-ii: interior heading, trailing_extras SHAPE ----------------
    def test_arm_4b_ii_stray_line_ahead_of_two_later_headings(self):
        text = self._stray_ahead_of_later_block()
        self.assertEqual(
            self._headings(text.split(WP.SEP)[0]), 0,
            "this arm must fire with ZERO headings in parts[0]")

        header, sessions = WP.split_sessions(text)

        self.assertEqual(len(sessions), 3)
        self.assertEqual(self._headings(header), 0)
        # One heading per returned block: two sessions glued into one block
        # is exactly the under-count this arm exists to catch.
        self.assertEqual([self._headings(b) for b in sessions], [1, 1, 1])
        # Newest-first order must survive the re-split.
        self.assertIn("session one", sessions[0])
        self.assertIn("session two", sessions[1])
        self.assertIn("session three", sessions[2])
        # The stray preamble must SURVIVE, and survive IN POSITION. 4b-i
        # asserted this and 4b-ii did not, which is the gap wave 7 slice S4
        # was sent to close: the two arms take different routes through
        # `split_sessions`, so survival on one is not evidence for the other.
        # Order-sensitive on purpose - "the characters are all still there"
        # is exactly the order-blind claim that let a 5.7 MB reorder through.
        self.assertIn("leftover prose", sessions[1])
        self.assertLess(sessions[1].index("leftover prose"),
                        sessions[1].index("session two"),
                        "the stray preamble must stay AHEAD of the heading "
                        "it preceded on disk, not merely be present")

    # -- BONUS arm ---------------------------------------------------------
    def test_bonus_no_separator_anywhere_still_finds_every_session(self):
        _, sessions = WP.split_sessions(self._no_separator_anywhere())

        self.assertEqual(len(sessions), 3)

    # -- clause (4) first half: --keep 3 must RELOCATE the surplus ---------
    def test_keep_3_relocates_the_surplus_from_a_glued_parts0_file(self):
        WP.WAKEUP.write_text(
            self.HEADER + "\n" + self.S1 + WP.SEP + self.S2 + WP.SEP
            + self.S3 + WP.SEP + "# 2026-09-15 - session four\n\nbody four\n",
            encoding="utf-8",
        )

        self.assertEqual(WP.prune(keep=3, dry_run=False), 0)

        after = WP.WAKEUP.read_text(encoding="utf-8")
        self.assertEqual(len(WP.split_sessions(after)[1]), 3)
        self.assertIn("session one", after)
        self.assertNotIn("session four", after)
        self.assertIn("session four",
                      WP.ARCHIVE.read_text(encoding="utf-8"))

    def test_keep_3_relocates_the_surplus_from_a_stray_line_file(self):
        WP.WAKEUP.write_text(
            self.HEADER + WP.SEP + self.S1 + WP.SEP + self.STRAY + self.S2
            + "\n" + self.S3 + WP.SEP
            + "# 2026-09-15 - session four\n\nbody four\n",
            encoding="utf-8",
        )

        self.assertEqual(WP.prune(keep=3, dry_run=False), 0)

        after = WP.WAKEUP.read_text(encoding="utf-8")
        self.assertEqual(len(WP.split_sessions(after)[1]), 3)
        self.assertNotIn("session four", after)
        self.assertIn("session four",
                      WP.ARCHIVE.read_text(encoding="utf-8"))

    # -- clause (5): --check shares split_sessions, so it shares the fix ---
    def test_check_sees_the_glued_parts0_session(self):
        WP.WAKEUP.write_text(self._glued_parts0(), encoding="utf-8")

        self.assertEqual(WP.check(keep=3), 0)
        self.assertEqual(WP.check(keep=2), 1,
                         "--check must count the glued session too")

    def test_check_sees_the_stray_line_sessions(self):
        WP.WAKEUP.write_text(self._stray_ahead_of_later_block(),
                             encoding="utf-8")

        self.assertEqual(WP.check(keep=3), 0)
        self.assertEqual(WP.check(keep=2), 1)


class TestZeroHeadingBlockStaysInPosition(unittest.TestCase):
    """RM-276 (4c). The MECHANISM behind the reorder, and it PRE-DATES the
    (4a)/(4b) fixes: `split_sessions` used to file every zero-heading block
    seen after the first session into a `trailing_extras` bucket and return
    `sessions + trailing_extras`, hoisting it to the FILE TAIL.

    On this minimal fixture the old code returned `[S1, S2, ZERO]` on BOTH
    sides of the (4a)/(4b) fixes, so nothing in the RM-276 suite could see
    it. What the (4b) fix changed was the REAL archive: 63 of its 95
    non-matching blocks became in-place sessions, leaving 32 zero-heading
    blocks interleaved among them instead of sitting contiguously at the
    tail, so the hoist stopped being a byte-identical no-op and started
    reordering `docs/history_notes.md` - which `prune()` re-renders whole.

    Every assertion here is ORDER-SENSITIVE. "The character multiset is
    identical and no line is lost" is true of a reorder too, and order is
    precisely what the repo's no-history-rewrite rule protects.
    """

    HEADER = "# RC wakeup notes\n\nOperator hand-off file.\n"
    S1 = "# 2026-09-18 - session one\n\nbody one\n"
    ZERO = "an operator note with no heading at all\n"
    S2 = "# 2026-09-17 - session two\n\nbody two\n"

    def test_zero_heading_block_keeps_its_index(self):
        text = (self.HEADER + WP.SEP + self.S1 + WP.SEP + self.ZERO
                + WP.SEP + self.S2)
        self.assertEqual(
            len(WP.SESSION_RE.findall(self.ZERO)), 0,
            "fixture must actually carry a ZERO-heading block")

        _, sessions = WP.split_sessions(text)

        # Exact ordered equality, not `assertCountEqual` and not a substring
        # sweep. The old bucket returned [S1, S2, ZERO].
        self.assertEqual(sessions, [self.S1, self.ZERO, self.S2])

    def test_zero_heading_block_round_trips_byte_identically(self):
        text = (self.HEADER + WP.SEP + self.S1 + WP.SEP + self.ZERO
                + WP.SEP + self.S2)

        header, blocks = WP.split_blocks(text)

        self.assertEqual(WP.render_blocks(header, blocks), text)

    def test_zero_heading_block_between_glued_sessions_keeps_its_index(self):
        """The interesting shape is the one the (4b) fix created on the real
        archive: zero-heading blocks INTERLEAVED with glued ones, not parked
        contiguously at the tail."""
        glued = self.S1 + "\n" + "# 2026-09-16 - session three\n\nbody three\n"
        text = self.HEADER + WP.SEP + glued + WP.SEP + self.ZERO + WP.SEP + self.S2

        _, sessions = WP.split_sessions(text)

        self.assertEqual(len(sessions), 4)
        self.assertEqual([len(WP.SESSION_RE.findall(b)) for b in sessions],
                         [1, 1, 0, 1])
        self.assertIn("session one", sessions[0])
        self.assertIn("session three", sessions[1])
        self.assertEqual(sessions[2], self.ZERO)
        self.assertIn("session two", sessions[3])


class TestSplitRenderIsByteStable(unittest.TestCase):
    """THE MISSING INVARIANT. `prune()` re-renders the WHOLE archive via
    `render_blocks(*prepend_sessions(...))`, so ANY change to how blocks are
    split changes what gets written back over `docs/history_notes.md` - the
    protected append-only archive. Nothing in this suite asserted that the
    round trip was faithful, so a splitter change that reordered 5.7 MB of
    history went green.

    Measured before the wave 7 fix: `render(split_sessions(archive))` came
    back +304 bytes with real deletions in the difflib opcode stream (1477
    lines inserted, 1335 deleted - a reorder, not an append). Measured after:
    0 bytes delta, identical sha256, zero opcodes. Both tracked files are
    read READ-ONLY here and every assertion is anchored against a vacuous
    pass: an empty or missing file would satisfy `rendered == disk` trivially
    (`split_blocks("")` returns `("", [])`), so size, block count and heading
    count are asserted first.
    """

    TRACKED = ("docs/history_notes.md", "WAKEUP_NOTES.md")

    def _read(self, rel: str) -> str:
        path = _PROJECT_ROOT / rel
        self.assertTrue(path.is_file(), f"tracked file missing: {path}")
        text = path.read_text(encoding="utf-8")
        # -- anti-vacuity anchors -----------------------------------------
        self.assertGreater(len(text), 1000,
                           f"{rel} read back too small to be the real file; "
                           f"an empty read would pass every assertion below")
        self.assertGreater(len(WP.SESSION_RE.findall(text)), 0,
                           f"{rel} carries no session heading at all")
        return text

    def test_split_render_reproduces_both_tracked_files_byte_for_byte(self):
        import hashlib
        for rel in self.TRACKED:
            with self.subTest(rel):
                text = self._read(rel)

                header, blocks = WP.split_blocks(text)
                rendered = WP.render_blocks(header, blocks)

                self.assertGreater(len(blocks), 0,
                                   f"{rel} parsed to zero blocks")
                self.assertEqual(
                    len(rendered.encode("utf-8")), len(text.encode("utf-8")),
                    f"{rel}: re-render changed the byte count")
                self.assertEqual(
                    hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
                    hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    f"{rel}: re-render is not byte-identical, so a prune "
                    f"would rewrite it")
                self.assertEqual(rendered, text)

    def test_heading_sequence_survives_the_split_in_order(self):
        """Order-sensitive content preservation. A multiset check passes on a
        reorder; this does not."""
        for rel in self.TRACKED:
            with self.subTest(rel):
                text = self._read(rel)
                on_disk = WP.SESSION_RE.findall(text)

                header, blocks = WP.split_blocks(text)
                recovered = WP.SESSION_RE.findall(header) + [
                    m for b in blocks for m in WP.SESSION_RE.findall(b.body)
                ]

                self.assertEqual(recovered, on_disk)

    def test_a_prune_of_the_real_archive_is_a_pure_insertion(self):
        """The write path, not just the round trip: prepending to the real
        archive must not rewrite, move or re-space one pre-existing byte.

        Read-only - `prepend_sessions` / `render_blocks` are pure and nothing
        is written to disk.
        """
        text = self._read("docs/history_notes.md")
        header, blocks = WP.split_blocks(text)
        moved = ["# 2026-09-18 - probe session\n\nprobe body\n"]

        out_header, out_blocks = WP.prepend_sessions(header, blocks, moved)
        rebuilt = WP.render_blocks(out_header, out_blocks)

        self.assertIn("probe session", rebuilt)
        self.assertGreater(len(rebuilt), len(text))
        self.assertTrue(rebuilt.startswith(out_header))
        # Full positional reconstruction, which is strictly stronger than an
        # `endswith` check: deleting exactly the inserted span - the bytes
        # between the header and the pre-existing tail - must give the
        # archive back EXACTLY. `endswith` alone would accept extra bytes
        # smuggled in just ahead of the tail.
        kept_tail = len(text) - len(out_header)
        self.assertEqual(
            rebuilt[:len(out_header)] + rebuilt[len(rebuilt) - kept_tail:],
            text,
            "a prune did not merely insert - it rewrote pre-existing archive "
            "bytes, which is a history rewrite")

    def test_the_faithful_pair_is_not_a_no_op_renderer(self):
        """Anti-vacuity for the guard itself: `render_blocks` must actually
        reassemble from the parsed blocks, not echo an input it kept a
        reference to. Drop a block and the output must shrink accordingly."""
        text = self._read("docs/history_notes.md")
        header, blocks = WP.split_blocks(text)

        short = WP.render_blocks(header, blocks[:-1])

        self.assertLess(len(short), len(text))
        self.assertEqual(
            len(short) + len(blocks[-1].sep) + len(blocks[-1].body),
            len(text))


if __name__ == "__main__":
    unittest.main()
