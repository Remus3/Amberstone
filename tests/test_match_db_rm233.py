"""
tests/test_match_db_rm233.py - RM-233.

Three defects in core/match_db.py, each of which makes a failure SILENT.

(a) __init__ ran `PRAGMA journal_mode = WAL` and DISCARDED the returned row.
    That pragma is a query, not a command: SQLite answers with the journal
    mode it actually settled on, and it can legitimately answer `delete`
    (no shared-memory support on the filesystem, an already-open connection
    holding the old mode, a locked db). The module's own docstring then
    claims "WAL allows concurrent readers without blocking writes" and the
    open log line says "MatchDB opened (WAL)" - both false, with no signal
    anywhere that they are false.

(b) `save_match` was annotated `-> None` and the `except Exception` arm
    logged and fell off the end. Success and a LOST match both returned
    None, so no caller could tell them apart. Both production callers
    (performance_tracker.py:415 and :477) discard the value, so widening
    the return to bool is additive - nothing in the tree reads it.

(c) `get_recent(limit=...)` passes limit straight into `LIMIT ?`, and
    SQLite treats a NEGATIVE limit as UNLIMITED. The whole live table came
    back for `get_recent(mode, -1)`. The one production caller
    (tools/ds_matchdb_mcp_server.py:342) clamps with `max(1, min(int(limit),
    200))` so it cannot reach this, which is why the defect is graded LOW -
    but `get_recent` is a public method with a default argument, and "LIMIT
    n returns at most n rows" should hold at the method, not only at one
    caller.

The forced-fallback harness below is deliberately NOT a mock of the fix: it
subclasses sqlite3.Connection and rewrites the SET half of the pragma to
`delete`, so the database really ends up in delete journal mode and the
pragma really answers `delete`. The positive control in the same class
proves an unpatched MatchDB still reaches `wal`.
"""

import sqlite3
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.match_db import MatchDB  # noqa: E402


class _DeleteJournalConnection(sqlite3.Connection):
    """A real connection that refuses to leave `delete` journal mode."""

    def execute(self, sql, *args):
        lowered = sql.lower()
        if "journal_mode" in lowered and "=" in lowered:
            sql = "PRAGMA journal_mode = delete"
        return super().execute(sql, *args)


# Bound BEFORE any patch: `core.match_db` does `import sqlite3`, so patching
# "core.match_db.sqlite3.connect" rebinds the attribute on the shared sqlite3
# module itself. Calling sqlite3.connect from inside the replacement would
# re-enter the replacement (measured: RecursionError).
_REAL_CONNECT = sqlite3.connect


def _delete_journal_connect(*args, **kwargs):
    kwargs["factory"] = _DeleteJournalConnection
    return _REAL_CONNECT(*args, **kwargs)


class TestJournalModeFallbackIsVisible(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "match_history.db"

    def test_wal_is_reached_on_a_normal_open(self):
        """Positive control: nothing patched, so the pragma answers wal."""
        db = MatchDB(self.path)
        self.addCleanup(db.close)
        self.assertEqual(db.journal_mode, "wal")
        row = db._conn().execute("PRAGMA journal_mode").fetchone()
        self.assertEqual(str(row[0]).lower(), "wal")

    def test_silent_fallback_to_delete_is_recorded_and_warned(self):
        with mock.patch("core.match_db.sqlite3.connect", _delete_journal_connect):
            with self.assertLogs("rc.match_db", level="WARNING") as caught:
                db = MatchDB(self.path)
            self.addCleanup(db.close)
            # The database really is in delete mode - not a stubbed answer.
            row = db._conn().execute("PRAGMA journal_mode").fetchone()
            self.assertEqual(str(row[0]).lower(), "delete")
        self.assertEqual(db.journal_mode, "delete")
        blob = "\n".join(caught.output).lower()
        self.assertIn("journal", blob)
        self.assertIn("delete", blob)

    def test_open_log_line_does_not_claim_wal_when_it_is_delete(self):
        with mock.patch("core.match_db.sqlite3.connect", _delete_journal_connect):
            with self.assertLogs("rc.match_db", level="INFO") as caught:
                db = MatchDB(self.path)
            self.addCleanup(db.close)
        opened = [ln for ln in caught.output if "MatchDB opened" in ln]
        self.assertTrue(opened, caught.output)
        for line in opened:
            self.assertNotIn("(WAL)", line)


class TestSaveMatchReportsFailure(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = MatchDB(Path(self._tmp.name) / "match_history.db")
        self.addCleanup(self.db.close)

    def test_successful_save_returns_true(self):
        self.assertIs(self.db.save_match({"mode": "SR", "champion": "Vayne"}), True)
        self.assertEqual(len(self.db.get_recent("SR", 5)), 1)

    def test_insert_failure_returns_false(self):
        # Genuinely break the INSERT: the table the statement targets is gone.
        self.db._conn().execute("DROP TABLE matches")
        self.assertIs(self.db.save_match({"mode": "SR", "champion": "Vayne"}), False)

    def test_unbindable_value_returns_false(self):
        # A set cannot be bound as a parameter - sqlite3.InterfaceError.
        self.assertIs(self.db.save_match({"mode": "SR", "champion": {1, 2}}), False)

    def test_failure_and_success_are_distinguishable(self):
        good = self.db.save_match({"mode": "ARAM", "champion": "Ziggs"})
        self.db._conn().execute("DROP TABLE matches")
        bad = self.db.save_match({"mode": "ARAM", "champion": "Ziggs"})
        self.assertNotEqual(good, bad)


class TestGetRecentLimitIsBounded(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = MatchDB(Path(self._tmp.name) / "match_history.db")
        self.addCleanup(self.db.close)
        for i in range(5):
            self.db.save_match(
                {"mode": "SR", "champion": f"C{i}",
                 "timestamp": f"2026-09-0{i + 1} 00:00:00"})

    def test_negative_limit_is_not_unlimited_mode_filtered(self):
        self.assertEqual(self.db.get_recent("SR", -1), [])

    def test_negative_limit_is_not_unlimited_unfiltered(self):
        self.assertEqual(self.db.get_recent("", -1), [])

    def test_zero_limit_still_returns_nothing(self):
        self.assertEqual(self.db.get_recent("SR", 0), [])

    def test_positive_limit_is_unchanged(self):
        self.assertEqual(len(self.db.get_recent("SR", 2)), 2)
        self.assertEqual(len(self.db.get_recent("", 3)), 3)
        self.assertEqual(len(self.db.get_recent("SR", 99)), 5)

    def test_numeric_string_limit_is_honoured(self):
        self.assertEqual(len(self.db.get_recent("SR", "2")), 2)


if __name__ == "__main__":
    unittest.main()
