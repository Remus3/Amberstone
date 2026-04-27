"""
tools/run_phase3_snapshot_regressions.py
Phase 3 Step 2 -- Deterministic snapshot regression harness.

Usage (from project root):
    python tools/run_phase3_snapshot_regressions.py

Or via wrapper:
    tools\\run_phase3_snapshot_regressions.cmd

No live Riot API, Anthropic API, Tk, or internet required.
No live project artifact mutation.

Exit code 0: all tests pass.
Exit code 1: one or more tests fail.
"""
import sys
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite  = loader.discover(
        start_dir = str(_PROJECT_ROOT / "tests" / "snapshot_regressions"),
        pattern   = "test_*.py",
        top_level_dir = str(_PROJECT_ROOT),
    )
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
