"""Repo-root pytest hooks - apply to BOTH suites (`tests/` and the DS suite).

`tests/conftest.py` only covers `tests/`, but the `subTest` channel defect
this installs a gate for has instances in `agents/daemon_slayer/tests/` too
(`462f1255` fixed one there). A rootdir conftest is the only place a single
installation reaches both.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# MAIN ORDER 2026-10-25 2045 item 2 (RM-907): one BLAS thread per test
# process. Measured on this 16-thread box: `import numpy` (OpenBLAS) commits
# ~496 MB of private memory per process for per-thread buffers, 14 MB with
# OPENBLAS_NUM_THREADS=1. Every xdist worker and every python child a test
# spawns inherits os.environ, so set it before any numpy import. setdefault:
# an explicit caller value still wins. Pinned by
# tests/test_suite_blas_threads_rm907.py.
for _blas_var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_blas_var, "1")

sys.path.insert(0, str(Path(__file__).parent))

from tests._subtest_channel_guard import install as _install_subtest_guard
# MAIN FIX TEMP-1: refuse an ad-hoc --basetemp inside a session scratchpad.
# RM-878: claim a per-run temp root (configure) and release it (unconfigure),
# so a concurrent run's sweep of the shared pytest-of-<user> root cannot reach it.
from tests._basetemp_guard import pytest_configure, pytest_unconfigure  # noqa: F401
# ENV-APIKEY: the shared Anthropic key lookup must never reach the real
# <repo>/API-Key-Claude.txt, including at COLLECTION (vision_server resolves
# the key at import). Installed here, before either suite is collected.
from tests._anthropic_key_guard import install as _install_anthropic_key_guard

_install_subtest_guard()
_install_anthropic_key_guard()
