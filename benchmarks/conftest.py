"""Make the repository root importable for the benchmark modules.

pytest inserts the directory containing the test file (``benchmarks/``) onto
``sys.path`` rather than the repository root, so the engine modules that live
at the top level (``item_advisor``, ``composition_advisor``, ...) would not be
importable. Prepending the repo root fixes that without touching the main
test suite's conftest.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# RM-170 (2026-08-06): these benchmarks are CI-only by design. The `benchmark`
# fixture is supplied by pytest-codspeed, which .github/workflows/codspeed.yml
# pip-installs on the runner and which is deliberately NOT in requirements.txt
# or requirements.lock (nothing local needs it). Without this shim a plain
# `pytest .` from the repo root reported 7 red "ERROR at setup of ..." lines
# reading `fixture 'benchmark' not found` - an environment gap wearing the
# costume of a broken module. Note the module itself imports fine and all 7
# tests COLLECT fine; they were never collection errors.
#
# Define the fallback ONLY when no benchmark plugin is present. conftest
# fixtures take precedence over plugin fixtures, so an unconditional
# definition here would SHADOW pytest-codspeed on the CI runner and silently
# stop the benchmarks from ever measuring anything.
def _no_benchmark_plugin() -> bool:
    """True when neither benchmark plugin is importable.

    Spelled as two LITERAL find_spec calls rather than a loop so
    tests/test_skip_condition_hygiene.py can resolve the target names and see
    that the skip below gates on an absent THIRD-PARTY capability. A loop
    variable is opaque to that guard and resolves to UNRESOLVED, which it
    treats as a defect.
    """
    return (
        importlib.util.find_spec("pytest_codspeed") is None
        and importlib.util.find_spec("pytest_benchmark") is None
    )


if _no_benchmark_plugin():

    @pytest.fixture
    def benchmark():
        if _no_benchmark_plugin():
            pytest.skip(
                "pytest-codspeed is not installed - benchmarks run in CI via "
                ".github/workflows/codspeed.yml (`pytest benchmarks/ "
                "--codspeed`). Install it to run them: pip install pytest-codspeed"
            )
        # Only reachable if a plugin appeared between import and call time, in
        # which case ITS fixture should have won and this shim should not exist.
        raise RuntimeError(
            "a benchmark plugin is importable but the conftest fallback fixture "
            "was still used - restart pytest so the plugin registers"
        )
