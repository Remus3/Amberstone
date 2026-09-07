"""Repo-root pytest hooks - apply to BOTH suites (`tests/` and the DS suite).

`tests/conftest.py` only covers `tests/`, but the `subTest` channel defect
this installs a gate for has instances in `agents/daemon_slayer/tests/` too
(`462f1255` fixed one there). A rootdir conftest is the only place a single
installation reaches both.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from tests._subtest_channel_guard import install as _install_subtest_guard

_install_subtest_guard()
