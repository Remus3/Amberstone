"""No test may start the live TFT OCR capture thread.

MEASURED 2026-07-28. A full-dual-suite run under ``-n 8 --dist loadfile``
HUNG for 2h29m instead of the noted 145s. It did not fail - it wedged, and
had to be killed by hand. The sequence:

  1. worker ``gw6`` went down ("node down: Not properly terminated");
  2. the controller then hung in ``pytest_sessionfinish`` with
     ``OSError: cannot send (already closed?)``;
  3. ``pytest-timeout`` was INSTALLED and ``--timeout=600`` was passed, and it
     never fired - because the hang is outside any test, in xdist session
     teardown. **A dead worker under -n 8 becomes an unbounded hang, not a
     failure.** No summary was printed, so the run measured nothing.

The pollution this pins: ``tft/tft_state_reader.py:60-68``.
``TftStateReader.__init__`` unconditionally starts a daemon thread running
``_ocr_loop``, which does REAL screen capture and REAL HTTP to ``:8889``
every 2 seconds, forever, whenever ``TftOcrReader().available`` is true. It
is true on any host with pytesseract installed, i.e. Legion. Three tests in
``tests/phase2_smoke/test_snapshot_translation.py`` (lines 62, 67, 73)
construct it directly and never stop it, so the thread outlives the test and
keeps capturing for the rest of the session.

That the thread killed gw6 is SUSPECTED, not proven - the crash left no
traceback. What IS proven is that the suite spawns unbounded real-capture
threads it never joins, which is a hermeticity defect on its own terms and a
plausible cause of a worker that cannot terminate cleanly.

The guard is the autouse ``_no_live_tft_ocr`` fixture in ``tests/conftest.py``,
which forces ``TftOcrReader.available`` False for the whole suite. A test that
genuinely needs the real reader must opt in explicitly and stop what it starts.
"""
from __future__ import annotations

import threading
import unittest


def _ocr_threads() -> list[threading.Thread]:
    """Every live thread the TFT reader could have started.

    Named rather than counted: ``tft_state_reader`` names its thread
    ``TftOcr`` at ``:66``, so an exact-name match cannot collide with an
    unrelated worker thread and cannot silently pass if the name changes -
    a rename breaks the assertion loudly instead of weakening it.
    """
    return [t for t in threading.enumerate() if t.name == "TftOcr" and t.is_alive()]


class NoLiveOcrThreadTests(unittest.TestCase):

    def test_constructing_the_reader_starts_no_capture_thread(self) -> None:
        """RED without the conftest guard on any host with pytesseract."""
        from tft.tft_state_reader import TftStateReader

        before = _ocr_threads()
        reader = TftStateReader()
        self.addCleanup(lambda: setattr(reader, "_ocr_running", False))

        after = _ocr_threads()
        self.assertEqual(
            [t.name for t in after], [t.name for t in before],
            "TftStateReader started a live OCR capture thread inside the test "
            "suite - it does real screen capture and real HTTP to :8889 every "
            "2s and is never joined. See this module's docstring for the "
            "2h29m xdist hang it is implicated in.",
        )

    def test_the_guard_is_actually_in_force(self) -> None:
        """Prove the fixture is doing the work, not a coincidence.

        Without this, the test above passes vacuously on any host where
        pytesseract happens to be absent - which is exactly the CI runner,
        i.e. the one place the defect could never be caught.
        """
        from tft.tft_ocr_reader import TftOcrReader

        self.assertFalse(
            TftOcrReader().available,
            "the _no_live_tft_ocr autouse guard is not in force; this suite's "
            "no-capture-thread assertion would pass vacuously",
        )

    def test_no_ocr_thread_leaked_from_any_earlier_test(self) -> None:
        """Catches a leak from a sibling module, not just from this one."""
        leaked = _ocr_threads()
        self.assertEqual(
            [], leaked,
            "a live TftOcr capture thread leaked out of an earlier test: "
            + ", ".join(t.name for t in leaked),
        )


if __name__ == "__main__":
    unittest.main()
