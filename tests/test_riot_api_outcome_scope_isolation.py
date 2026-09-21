"""Pin the thread-isolation and nesting contract of riot_api.track_outcomes().

The rewind 429 fix (scripts/rewind_catchup.py, lib/rewind_live_writer.py)
reads ``scope.rate_limited`` to tell a Riot 429 from a real 404. That is only
sound if a scope sees exactly the calls made on ITS thread:

  (a) an outcome recorded on another thread never lands in this scope - the
      live writer runs on a Timer thread while request handlers and the
      team-context fan-out make their own Riot calls concurrently;
  (b) an inner scope's outcomes ALSO land in every enclosing scope (current
      documented behaviour, pinned so a refactor cannot silently drop it);
  (c) recording with no open scope is a no-op and leaves no residue that a
      later scope could read.

Offline: outcomes are injected through ``_record_outcome``, the same seam
``_call_ex`` publishes through.
"""

from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import riot_api as RA  # noqa: E402


class ThreadIsolationTests(unittest.TestCase):
    def test_other_thread_outcomes_do_not_leak_into_this_scope(self):
        other_seen: list[list[str]] = []
        ready = threading.Event()
        release = threading.Event()

        def _other() -> None:
            with RA.track_outcomes() as other_scope:
                RA._record_outcome("429")
                ready.set()
                release.wait(5)
                other_seen.append(list(other_scope.outcomes))
            # And one more with no scope open on that thread.
            RA._record_outcome("429")

        with RA.track_outcomes() as scope:
            t = threading.Thread(target=_other)
            t.start()
            self.assertTrue(ready.wait(5))
            RA._record_outcome("ok")
            release.set()
            t.join(5)
            self.assertFalse(t.is_alive())

        self.assertEqual(scope.outcomes, ["ok"])
        self.assertFalse(scope.rate_limited)
        # Positive control: the other thread's own scope DID see its 429,
        # so the empty result above is isolation, not a dead recorder.
        self.assertEqual(other_seen, [["429"]])

    def test_scope_opened_on_another_thread_is_invisible_here(self):
        opened = threading.Event()
        done = threading.Event()

        def _holder() -> None:
            with RA.track_outcomes():
                opened.set()
                done.wait(5)

        t = threading.Thread(target=_holder)
        t.start()
        self.assertTrue(opened.wait(5))
        try:
            # No scope open on THIS thread: must be a clean no-op, and must
            # not reach the other thread's open scope either.
            RA._record_outcome("429")
            stack = getattr(RA._OUTCOME_TLS, "stack", None)
            self.assertFalse(stack)
        finally:
            done.set()
            t.join(5)


class NestingTests(unittest.TestCase):
    def test_inner_scope_outcomes_also_land_in_outer_scope(self):
        with RA.track_outcomes() as outer:
            RA._record_outcome("ok")
            with RA.track_outcomes() as inner:
                RA._record_outcome("429")
            RA._record_outcome("404")
        self.assertEqual(inner.outcomes, ["429"])
        self.assertEqual(outer.outcomes, ["ok", "429", "404"])
        self.assertTrue(outer.rate_limited)
        self.assertTrue(inner.rate_limited)
        self.assertEqual(outer.last, "404")

    def test_outer_outcomes_do_not_leak_into_a_later_inner_scope(self):
        with RA.track_outcomes() as outer:
            RA._record_outcome("429")
            with RA.track_outcomes() as inner:
                RA._record_outcome("ok")
        self.assertEqual(inner.outcomes, ["ok"])
        self.assertFalse(inner.rate_limited)
        self.assertEqual(outer.outcomes, ["429", "ok"])


class NoScopeTests(unittest.TestCase):
    def test_record_with_no_open_scope_is_a_noop(self):
        # Must not raise, and must leave nothing for a later scope to read.
        RA._record_outcome("429")
        RA._record_outcome("rate_limited")
        with RA.track_outcomes() as scope:
            pass
        self.assertEqual(scope.outcomes, [])
        self.assertFalse(scope.rate_limited)
        self.assertIsNone(scope.last)

    def test_stack_is_empty_after_scopes_close(self):
        with RA.track_outcomes():
            with RA.track_outcomes():
                RA._record_outcome("429")
        self.assertFalse(getattr(RA._OUTCOME_TLS, "stack", None))


if __name__ == "__main__":
    unittest.main()
