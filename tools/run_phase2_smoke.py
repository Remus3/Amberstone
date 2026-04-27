"""
tools/run_phase2_smoke.py
One-command entry point for the Phase 2 deterministic smoke harness.

Usage (from project root):
    python tools/run_phase2_smoke.py

Or via the wrapper:
    tools\\run_phase2_smoke.cmd

Returns 0 on all tests passing, nonzero on any failure.

No live external dependencies required:
  - No Riot client / localhost:2999
  - No Anthropic API calls
  - No Tk window / mainloop
  - No internet access
  - Standard library only (unittest)
"""
import sys
import unittest
from pathlib import Path

# Ensure project root is on sys.path so all modules resolve correctly
_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

def main():
    import io
    stream = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    loader  = unittest.TestLoader()
    suite   = loader.discover(
        start_dir=str(_PROJECT_ROOT / "tests" / "phase2_smoke"),
        pattern="test_*.py",
        top_level_dir=str(_PROJECT_ROOT),
    )
    runner  = unittest.TextTestRunner(verbosity=2, stream=stream)
    result  = runner.run(suite)
    stream.flush()
    return 0 if result.wasSuccessful() else 1

if __name__ == "__main__":
    sys.exit(main())
