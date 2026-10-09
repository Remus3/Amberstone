"""Refuse a pytest ``--basetemp`` inside a Claude session scratchpad (MAIN FIX TEMP-1).

Why: MAIN measured 2026-10-09 that long-lived sessions passed ``--basetemp``
INSIDE the session scratchpad, one per run, so a scratchpad reached 8.5k
entries. pytest's retention (``pytest.ini``: ``tmp_path_retention_policy =
failed``, ``tmp_path_retention_count = 1``) does not reap an explicit basetemp
that changes per run, and MAIN's cleaner skips live sessions, so the copies
never went away. Temp file count is boot time on this box.

Rule: use the default tmp_path. If a run truly needs an explicit basetemp, use
the ONE fixed path ``<scratchpad>/pytest-basetemp`` - pytest clears it at the
start of each run, so a scratchpad holds at most one basetemp. Any other
basetemp inside a scratchpad is a usage error raised from
``pytest_configure`` (before any basetemp directory is created).

A scratchpad is the harness layout ``<..>/claude/<project>/<session>/scratchpad``
(names compared case-insensitively). The rootdir ``conftest.py`` re-exports
``pytest_configure`` so the guard reaches BOTH suites; an xdist worker is
skipped because its basetemp is the controller's plus ``popen-gwN``.
Pinned by ``tests/test_pytest_basetemp_scratchpad_temp1.py``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

FIXED_NAME = "pytest-basetemp"


def _scratchpad_root(path: Path):
    """Return the scratchpad ancestor (inclusive) of ``path``, or None."""
    chain = [path, *path.parents]
    for node in chain:
        if node.name.lower() != "scratchpad":
            continue
        ups = list(node.parents)
        if len(ups) >= 3 and ups[2].name.lower() == "claude":
            return node
    return None


def basetemp_problem(value):
    """Return a refusal message for ``value`` (a basetemp), or None if it is fine."""
    if not value:
        return None
    path = Path(os.path.abspath(os.path.expanduser(str(value))))
    root = _scratchpad_root(path)
    if root is None:
        return None
    rel = path.parts[len(root.parts):]
    if rel and rel[0].lower() == FIXED_NAME:
        return None
    return (
        "--basetemp inside a session scratchpad is refused (MAIN FIX TEMP-1): "
        "each run left a full tmp tree that is never reaped. Drop --basetemp "
        "(default tmp_path, retention failed/1), or use the ONE fixed path "
        f"<scratchpad>/{FIXED_NAME}, which pytest clears at the start of each run."
    )


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    if hasattr(config, "workerinput"):
        return
    problem = basetemp_problem(getattr(config.option, "basetemp", None))
    if problem:
        raise pytest.UsageError(problem)
