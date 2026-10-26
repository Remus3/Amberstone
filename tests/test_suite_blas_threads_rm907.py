"""RM-907 (MAIN ORDER 2026-10-25 2045 item 2): the suite runs one BLAS thread
per process.

`import numpy` committed ~496 MB of private memory per process on this
16-thread box (OpenBLAS per-thread buffers) against 14 MB with
OPENBLAS_NUM_THREADS=1; eight xdist workers plus every python child a test
spawns paid it, toward a 24.5 GB suite peak commit. The rootdir conftest sets
the variables before any test imports numpy, and children inherit them.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

VARS = ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")


@pytest.mark.parametrize("var", VARS)
def test_blas_thread_vars_are_set_in_the_test_process(var):
    assert os.environ.get(var), var


def test_a_spawned_child_inherits_the_cap():
    code = "import os; print(os.environ.get('OPENBLAS_NUM_THREADS', ''))"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, timeout=60, check=True).stdout.strip()
    assert out == "1", out


@pytest.mark.skipif(sys.platform != "win32", reason="private commit is a Windows counter")
def test_a_spawned_child_imports_numpy_lean():
    code = (
        "import psutil; p = psutil.Process(); a = p.memory_info().private;"
        "import numpy; print(round((p.memory_info().private - a) / 2**20))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, timeout=120, check=True).stdout.strip()
    # 496 MB unthrottled on a 16-thread box; one thread commits ~14 MB.
    assert int(out) < 200, out
