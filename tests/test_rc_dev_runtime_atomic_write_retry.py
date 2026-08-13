"""Guard: ``_atomic_write_json`` survives a TRANSIENT Windows rename failure.

Why this exists (measured, not theorised). ``ops/runtime/last_fatal.txt`` on
Legion carried, dated 2026-08-12 20:44:33::

    heartbeat_error: PermissionError: [WinError 5] Access is denied:
    'C:\\Riot Commander\\ops\\runtime\\health.json.tmp'
    -> 'C:\\Riot Commander\\ops\\runtime\\health.json'

Windows gives no POSIX rename-over-open-file guarantee. A reader, an antivirus
scan or the search indexer holding a handle for a few milliseconds makes
``os.replace`` raise ``PermissionError``/``OSError``. The write is genuinely
retryable: the payload is already on disk as ``.tmp`` and only the rename
failed.

The failure mode this prevents is deceptive. ``_heartbeat_loop`` catches the
exception and calls ``write_fatal``, which writes a marker file and RETURNS -
the loop keeps running and the process stays alive. So nothing crashes, no
supervisor restart fires, and ``health.json`` simply stops advancing while
every monitor still reads a well-formed payload with a live pid. RC looked up
and was not.

Scope note: ``_atomic_write_json`` is a SHARED helper with nine call sites
(boot marker, shutdown marker, heartbeat, command files, profile write, two
request writes, result writes), so the retry belongs in the helper rather than
around the heartbeat call.

``ops/rc_dev_runtime.py`` is a FROZEN file (CLAUDE.md). This change was
approved by the operator on 2026-08-12.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ops import rc_dev_runtime as rdr  # noqa: E402


class AtomicWriteRetryTests(unittest.TestCase):
    """The rename retries on a transient OSError and still lands the payload."""

    def test_retry_constants_are_declared_and_bounded_by_the_heartbeat(self) -> None:
        # The retry budget must fit inside one heartbeat interval, or a slow
        # failure turns into ticks piling up behind each other. Default
        # heartbeat_interval is 1.0s (rc_dev_runtime.py:97).
        self.assertGreaterEqual(rdr._ATOMIC_WRITE_RETRIES, 3)
        worst_case = sum(
            rdr._ATOMIC_WRITE_BACKOFF_S * (2 ** i)
            for i in range(rdr._ATOMIC_WRITE_RETRIES - 1)
        )
        self.assertLess(
            worst_case,
            1.0,
            f"total backoff {worst_case}s must stay under the 1.0s heartbeat interval",
        )

    def test_transient_permission_error_is_retried_and_the_write_succeeds(self) -> None:
        target = Path(self.enterContext(_tmpdir())) / "health.json"
        payload = {"pid": 1344, "alive": True}
        real_replace = rdr.os.replace
        calls = {"n": 0}

        def flaky(src, dst):
            calls["n"] += 1
            if calls["n"] < 3:
                raise PermissionError(5, "Access is denied")
            return real_replace(src, dst)

        with mock.patch.object(rdr.os, "replace", side_effect=flaky), \
                mock.patch.object(rdr.time, "sleep") as slept:
            rdr._atomic_write_json(target, payload)

        self.assertEqual(calls["n"], 3, "should have retried twice then succeeded")
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), payload)
        # Backoff must actually be applied between attempts, not busy-looped.
        self.assertEqual(slept.call_count, 2)
        self.assertTrue(
            all(c.args[0] > 0 for c in slept.call_args_list),
            "each backoff must be a positive delay",
        )

    def test_first_attempt_success_does_not_sleep(self) -> None:
        # The happy path is the overwhelmingly common one - it must not pay a
        # delay. A regression that sleeps before every replace would add a
        # per-tick stall to a 1 Hz loop.
        target = Path(self.enterContext(_tmpdir())) / "health.json"
        with mock.patch.object(rdr.time, "sleep") as slept:
            rdr._atomic_write_json(target, {"ok": True})
        slept.assert_not_called()
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"ok": True})

    def test_persistent_failure_still_raises_so_the_caller_can_report_it(self) -> None:
        # Retry must not SWALLOW a real, persistent fault - that would trade a
        # visible stale-health bug for a silent one. _heartbeat_loop's
        # write_fatal path stays reachable.
        target = Path(self.enterContext(_tmpdir())) / "health.json"
        with mock.patch.object(
            rdr.os, "replace", side_effect=PermissionError(5, "Access is denied")
        ), mock.patch.object(rdr.time, "sleep"):
            with self.assertRaises(PermissionError):
                rdr._atomic_write_json(target, {"ok": True})

    def test_persistent_failure_does_not_leave_an_orphan_tmp_behind(self) -> None:
        # An abandoned health.json.tmp is what made the live incident hard to
        # read: the payload existed on disk under the wrong name.
        tmpdir = Path(self.enterContext(_tmpdir()))
        target = tmpdir / "health.json"
        with mock.patch.object(
            rdr.os, "replace", side_effect=PermissionError(5, "Access is denied")
        ), mock.patch.object(rdr.time, "sleep"):
            with self.assertRaises(PermissionError):
                rdr._atomic_write_json(target, {"ok": True})
        self.assertEqual(
            sorted(p.name for p in tmpdir.iterdir()),
            [],
            "no orphan .tmp may survive an exhausted retry budget",
        )

    def test_a_non_oserror_is_not_retried(self) -> None:
        # Only rename-contention is retryable. A TypeError from a bad payload
        # is a bug and must surface on the first attempt.
        target = Path(self.enterContext(_tmpdir())) / "health.json"
        calls = {"n": 0}

        def boom(src, dst):
            calls["n"] += 1
            raise TypeError("not a rename problem")

        with mock.patch.object(rdr.os, "replace", side_effect=boom), \
                mock.patch.object(rdr.time, "sleep"):
            with self.assertRaises(TypeError):
                rdr._atomic_write_json(target, {"ok": True})
        self.assertEqual(calls["n"], 1, "a non-OSError must not be retried")


def _tmpdir():
    import tempfile

    return tempfile.TemporaryDirectory()


if __name__ == "__main__":
    unittest.main()
