"""
tests/phase7_polish/test_wakeup_prune.py
Phase 7 — auto-prune helper for WAKEUP_NOTES.md.

Verifies the parse → render round-trip is byte-stable, and that pruning
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


# ── Synthetic fixtures ────────────────────────────────────────────────────────

HEADER = (
    "# WAKEUP_NOTES — RC hand-off ledger\n"
    "\n"
    "> Sessions s27–s137 archived to `docs/history_notes.md`. Only the last 3 sessions kept here.\n"
)


def _session(sid: str, body: str = "stuff happened") -> str:
    return f"# {sid} wrap — 2026-05-09\n\n## What shipped\n- {body}\n"


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


# ── Tests ─────────────────────────────────────────────────────────────────────

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
        s1 = "# s002 wrap — 2026-01-02\n\n## What's next\n4. last bullet\n"
        s2 = "# s001 wrap — 2026-01-01\n\n## What's next\n3. older bullet\n"
        rendered = WP.render(HEADER, [s1, s2])
        # Blank line BEFORE the separator that follows each session.
        self.assertIn("4. last bullet\n\n---\n\n# s001", rendered)

    def test_render_repairs_buggy_input(self):
        # If the on-disk file is ALREADY missing the blank line (e.g. legacy
        # bug), parse + re-render should restore the canonical shape.
        buggy = (
            HEADER
            + "\n---\n\n"
            + "# s002 wrap — 2026-01-02\n\n## last\n4. bullet\n"  # no extra \n
            + "---\n\n"  # missing leading \n — buggy
            + "# s001 wrap — 2026-01-01\n\n## last\n3. older\n"
        )
        header, sessions = WP.split_sessions(buggy)
        rendered = WP.render(header, sessions)
        self.assertIn("4. bullet\n\n---\n\n# s001", rendered)


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


if __name__ == "__main__":
    unittest.main()
