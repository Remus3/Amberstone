"""Reap orphaned :8889 vision-server instances before a fresh bind.

Regression (project_liveclient_loopback_regression, 2026-07-05): dashboard/
server.py self-heals the vision server by spawning moon_vision_server.py
whenever :8889 does not answer a connect() probe, and vision_server.main binds
a ThreadingHTTPServer with allow_reuse_address=True (SO_REUSEADDR). A fresh
instance therefore CO-BINDS :8889 alongside any still-running predecessor
instead of failing; across RC restarts the old child is never killed (parent
exits, child keeps running + keeps the bind), so orphaned instances accumulate.
With several sockets co-bound to 0.0.0.0:8889 the OS refuses every connect()
(~2s), which blanks /api/state.lcu, the overlay roster + vision frames.

Contract:
  - find_stale_vision_pids matches OTHER moon_vision_server.py / -m vision_server
    processes and excludes the current pid + unrelated processes.
  - reap_stale_vision_instances kills exactly those and returns their pids.
  - a killer that raises for one pid does not abort the sweep (best-effort).
  - an empty / unavailable process list reaps nothing and never raises.
"""
from __future__ import annotations

import pathlib
import unittest

from vision_server import _reap


class FindStaleVisionPidsTests(unittest.TestCase):
    def _procs(self):
        return [
            (100, r"C:\...\pythonw.exe C:\Riot Commander\moon_vision_server.py"),
            (200, r"C:\...\pythonw.exe C:\Riot Commander\moon_vision_server.py"),
            (300, r"C:\...\pythonw.exe main.py"),            # dashboard - keep
            (400, r"C:\...\python.exe -m vision_server"),    # alt launch - stale
            (500, r"C:\...\python.exe -m pytest tests"),     # unrelated - keep
        ]

    def test_excludes_self_and_unrelated(self):
        stale = _reap.find_stale_vision_pids(100, procs=self._procs())
        self.assertEqual(sorted(stale), [200, 400])

    def test_no_other_instances_returns_empty(self):
        stale = _reap.find_stale_vision_pids(
            100, procs=[(100, "moon_vision_server.py"), (300, "main.py")]
        )
        self.assertEqual(stale, [])


class ReapStaleVisionInstancesTests(unittest.TestCase):
    def _procs(self):
        return [
            (100, "moon_vision_server.py"),    # self (excluded)
            (200, "moon_vision_server.py"),    # orphan
            (400, "python -m vision_server"),  # orphan
            (300, "pythonw main.py"),          # keep
        ]

    def test_reaps_only_stale(self):
        killed = []
        reaped = _reap.reap_stale_vision_instances(
            exclude_pid=100, procs=self._procs(), killer=killed.append
        )
        self.assertEqual(sorted(reaped), [200, 400])
        self.assertEqual(sorted(killed), [200, 400])

    def test_kill_failure_does_not_abort_sweep(self):
        killed = []

        def flaky(pid):
            if pid == 200:
                raise PermissionError("access denied")
            killed.append(pid)

        reaped = _reap.reap_stale_vision_instances(
            exclude_pid=100, procs=self._procs(), killer=flaky
        )
        self.assertEqual(reaped, [400])   # 200 raised -> not counted as reaped
        self.assertEqual(killed, [400])   # sweep continued past the failure

    def test_empty_proc_list_is_noop(self):
        self.assertEqual(
            _reap.reap_stale_vision_instances(exclude_pid=1, procs=[]), []
        )


class NoBannedCodepointsTests(unittest.TestCase):
    def test_no_banned_codepoints(self):
        text = pathlib.Path(_reap.__file__).read_text(encoding="utf-8")
        banned = {
            0x2014: "em-dash", 0x2013: "en-dash",
            0x2018: "lsquo", 0x2019: "rsquo",
            0x201C: "ldquo", 0x201D: "rdquo",
        }
        hits = [name for cp, name in banned.items() if chr(cp) in text]
        self.assertFalse(hits, f"_reap.py has banned codepoints: {hits}")


if __name__ == "__main__":
    unittest.main()
