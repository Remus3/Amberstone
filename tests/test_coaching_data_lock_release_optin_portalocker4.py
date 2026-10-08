"""portalocker 4.x: coaching_data_lock must opt in to release errors.

portalocker 4.0 changed `Lock.release()` to SWALLOW unlock / close failures
(it logs a warning and closes the handle itself) unless the Lock was built
with the keyword-only `raise_on_release_error=True`. coaching_data_lock
counts release failures in `file_lock_release_failures`, which is polled on
`/api/health/all` (RM-282), so on 4.x that counter would silently stop
moving. The module therefore opts in whenever the installed `Lock`
declares the keyword.

It must NOT pass the keyword to a 3.x Lock: 3.x has no such parameter and
forwards unknown keywords (`**file_open_kwargs`) to `open()`, so every
acquire would fail as a lock infrastructure failure. The operator box runs
whatever was last installed from requirements.txt, so both shapes are live.
"""
from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import portalocker

from core import coaching_data_lock as cdl


class _FakeHandle:
    def close(self) -> None:
        pass


def _lock_4x(record: list, release_error: Exception | None = None):
    """Stand-in with the 4.x signature and the 4.x release contract."""

    class _Lock4:
        def __init__(self, filename, mode="a", timeout=None, check_interval=0.25,
                     fail_when_locked=False, flags=None, *,
                     raise_on_release_error=False, **file_open_kwargs):
            record.append({"raise_on_release_error": raise_on_release_error,
                           "file_open_kwargs": dict(file_open_kwargs)})
            self._raise = raise_on_release_error
            self.fh = None

        def acquire(self):
            self.fh = _FakeHandle()
            return self.fh

        def release(self):
            # 4.x claims and closes the handle first, then raises the
            # unlock failure ONLY when the caller opted in.
            self.fh = None
            if release_error is not None and self._raise:
                raise release_error

    return _Lock4


def _lock_3x(record: list):
    """Stand-in with the 3.x signature: unknown keywords reach open()."""

    class _Lock3:
        def __init__(self, filename, mode="a", timeout=None, check_interval=0.25,
                     fail_when_locked=False, flags=None, **file_open_kwargs):
            record.append({"file_open_kwargs": dict(file_open_kwargs)})
            self._file_open_kwargs = file_open_kwargs
            self.fh = None

        def acquire(self):
            if self._file_open_kwargs:
                raise TypeError(
                    "open() got an unexpected keyword argument "
                    f"{sorted(self._file_open_kwargs)[0]!r}")
            self.fh = _FakeHandle()
            return self.fh

        def release(self):
            self.fh = None

    return _Lock3


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        cdl._reset_state_for_tests()
        self.addCleanup(cdl._reset_state_for_tests)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        # Never touch the live ops/runtime/coaching_data.lock.
        self._patch(cdl, "_LOCK_FILE", Path(tmp.name) / "runtime" / "coaching_data.lock")
        self.record: list = []

    def _patch(self, target, attr, value) -> None:
        p = mock.patch.object(target, attr, value)
        p.start()
        self.addCleanup(p.stop)

    def _use(self, lock_cls) -> None:
        self._patch(cdl.portalocker, "Lock", lock_cls)

    def _run_once(self) -> dict:
        with cdl.coaching_data_lock():
            pass
        return cdl.coaching_data_lock_stats()


class TestOptInFollowsTheInstalledSignature(_Base):
    def test_a_4x_lock_is_built_with_raise_on_release_error(self) -> None:
        self._use(_lock_4x(self.record))
        stats = self._run_once()
        self.assertEqual(len(self.record), 1)
        self.assertIs(self.record[0]["raise_on_release_error"], True)
        self.assertEqual(self.record[0]["file_open_kwargs"], {})
        self.assertEqual(stats["file_lock_failures"], 0)

    def test_a_3x_lock_is_not_handed_the_keyword(self) -> None:
        self._use(_lock_3x(self.record))
        stats = self._run_once()
        self.assertEqual(self.record, [{"file_open_kwargs": {}}])
        self.assertEqual(stats["file_lock_failures"], 0,
                         "the 4.x keyword leaked into a 3.x open()")

    def test_a_4x_release_failure_still_moves_the_rm282_counter(self) -> None:
        self._use(_lock_4x(self.record, release_error=portalocker.LockException("unlock failed")))
        with self.assertLogs(cdl._log, level="WARNING"):
            stats = self._run_once()
        self.assertEqual(stats["file_lock_release_failures"], 1)
        self.assertEqual(stats["file_lock_failures"], 0)


class TestRealInstalledPortalocker(_Base):
    """No stub: the installed portalocker (3.x on an un-upgraded box, 4.x in
    CI once requirements are bumped) must take and release the lock cleanly
    through the module's real call shape."""

    def test_round_trip_through_the_real_library(self) -> None:
        declares = "raise_on_release_error" in inspect.signature(portalocker.Lock).parameters
        stats = self._run_once()
        self.assertEqual(stats["file_lock_failures"], 0, f"declares={declares}")
        self.assertEqual(stats["file_lock_release_failures"], 0, f"declares={declares}")


if __name__ == "__main__":
    unittest.main()
