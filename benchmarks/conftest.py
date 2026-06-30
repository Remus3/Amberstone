"""Make the repository root importable for the benchmark modules.

pytest inserts the directory containing the test file (``benchmarks/``) onto
``sys.path`` rather than the repository root, so the engine modules that live
at the top level (``item_advisor``, ``composition_advisor``, ...) would not be
importable. Prepending the repo root fixes that without touching the main
test suite's conftest.
"""
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
