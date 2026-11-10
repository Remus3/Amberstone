"""RM-1723 - ruff SIM112 (an environment variable not spelled in capitals) held at zero in production code.

Not selected by ruff.toml. Measured 2026-11-06 with ``ruff check --isolated`` (target py39) over the tracked
production code: 3 findings, all ``os.environ.get("ProgramData")`` in the three boot-time fallback-log paths of
``tools/ds_keepalive.py``, ``tools/start_daemon_slayer.py`` and ``tools/start_ds_matchdb_mcp.py``. Windows folds
the case of an environment variable name (``os.environ`` upper-cases its keys there), so the mixed-case spelling
read the same value; on any other OS it silently read nothing and fell back to the literal ``C:\\ProgramData``.
They now say ``PROGRAMDATA``, the key ``os.environ`` actually stores, so the lookup no longer depends on that
folding.

Scope: tracked ``.py`` files. ``tests/``, any ``*/tests/`` directory, ``agents/daemon_slayer``, the vendored
``ops/fleet_kit`` and the ``agents/agent3_testing/suite`` suite are out of scope (nine ``SystemRoot`` reads in
test code are left). The run uses NO config (``--isolated``), so a per-file-ignore cannot hide a finding. The
baseline is empty and only shrinks.
"""
from __future__ import annotations

import collections
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("ruff") is None,
    reason="ruff is not importable by this interpreter",
)

_RULE = "SIM112"
_OUT_OF_SCOPE = (
    "tests/",
    "tools/tests/",
    "agents/daemon_slayer/",
    "agents/agent3_testing/suite/",
    "ops/fleet_kit/",
)
_BASELINE: dict[str, int] = {}
_FIXED = (
    "tools/ds_keepalive.py",
    "tools/start_daemon_slayer.py",
    "tools/start_ds_matchdb_mcp.py",
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", "--select", _RULE, *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, check=False, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def tree_counts() -> dict[str, int]:
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    counts: collections.Counter = collections.Counter()
    for d in _ruff(["."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and not rel.startswith(_OUT_OF_SCOPE) and "/tests/" not in rel:
            counts[rel] += 1
    return dict(counts)


def test_no_new_findings(tree_counts):
    extra = {f: n for f, n in tree_counts.items() if n > _BASELINE.get(f, 0)}
    assert not extra, f"ruff {_RULE} findings beyond the baseline, file: count: {extra}"


def test_baseline_is_exact(tree_counts):
    stale = {f: n for f, n in _BASELINE.items() if tree_counts.get(f, 0) != n}
    assert not stale, f"baseline rows to shrink or drop (file: recorded): {stale}"


def test_probe_is_live():
    """The isolated run reports a minimal offender, so an empty tree result is a real scan."""
    probe = "import os\nx = os.environ.get('ProgramData')\n"
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=probe)
    assert any(d["code"] == _RULE for d in found)


@pytest.mark.parametrize("rel", _FIXED)
def test_fallback_log_reads_the_stored_key(rel):
    """Each boot-time fallback-log path reads PROGRAMDATA, the key os.environ stores."""
    src = (REPO_ROOT / rel).read_text(encoding="utf-8")
    assert 'os.environ.get("PROGRAMDATA")' in src, rel
    assert 'os.environ.get("ProgramData")' not in src, rel
