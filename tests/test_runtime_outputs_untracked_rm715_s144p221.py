"""RM-715 (RM-1727) - four runtime outputs stay out of the git index and out of the bundle.

MEASURED 2026-11-06: three runtime files sat in the index although a running RC rewrites or
regenerates them, so a normal run dirtied the tree (and the PKG-4 bundle builder shipped the
stale copies, because ``tools/build_portable.py`` ``exclusion_reason`` only drops the log suffixes):

- ``data/coaching_ts.json`` - superseded by ``ops/runtime/coaching_ts_<mode>.json``
  (the live writer is ``core/coaching_timestamps.py``); nothing tracked reads the old file.
- ``data/rewind_scraper.log`` and ``data/rewind_scraper_err.log`` - scraper stdout / stderr.
- ``data/coach_cache/sr_draft.json`` - one file of the per-mode coach cache that
  ``agents/agent2_backend/pipeline/orchestrator.py`` (``COACH_CACHE_DIR``) rewrites per run.

Out of scope on purpose: the three ``ops/audit/lolmath_ds_sweep/*.log`` files. ``NOTICE`` records
them as tracked scrape logs, so untracking them is a licence decision, not runtime hygiene.

The guard asks git, not the filesystem: the files stay on disk after ``git rm --cached``, so the
index and the ignore rules are the only honest evidence. It skips with a reason when git is
absent, so COULD-NOT-CHECK stays apart from CHECKED-AND-FOUND-NOTHING.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_GIT = shutil.which("git")

_FILES = (
    "data/coaching_ts.json",
    "data/rewind_scraper.log",
    "data/rewind_scraper_err.log",
    "data/coach_cache/sr_draft.json",
)
# Whole shapes, so a sibling written later (another mode's cache, a rotated log) is covered too.
_SHAPES = (
    "data/coach_cache/*",
    "data/rewind_scraper*.log",
)

pytestmark = pytest.mark.skipif(_GIT is None, reason="git not on PATH - cannot read the index")


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [_GIT, *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=120, check=False
    )


def test_none_of_the_runtime_outputs_is_tracked() -> None:
    proc = _git("ls-files", "--", *_FILES, *_SHAPES)
    assert proc.returncode == 0, proc.stderr[-300:]
    tracked = sorted(line for line in proc.stdout.splitlines() if line)
    assert not tracked, f"runtime outputs are tracked again: {tracked}"


@pytest.mark.parametrize("rel", _FILES)
def test_each_runtime_output_is_ignored(rel: str) -> None:
    # --no-index: answer from the .gitignore rules alone, so an index entry cannot mask a missing rule.
    proc = _git("check-ignore", "-q", "--no-index", "--", rel)
    assert proc.returncode in (0, 1), proc.stderr[-300:]
    assert proc.returncode == 0, f"{rel} is not matched by any .gitignore rule"


@pytest.mark.parametrize("rel", ["data/coach_cache/aram.json", "data/rewind_scraper_old.log"])
def test_a_sibling_of_each_shape_is_ignored_too(rel: str) -> None:
    proc = _git("check-ignore", "-q", "--no-index", "--", rel)
    assert proc.returncode in (0, 1), proc.stderr[-300:]
    assert proc.returncode == 0, f"{rel} is not matched by any .gitignore rule"


def test_the_lolmath_logs_stay_tracked() -> None:
    """The out-of-scope half: NOTICE names them, so this slice must not have swept them up."""
    proc = _git("ls-files", "--", "ops/audit/lolmath_ds_sweep/*.log")
    assert proc.returncode == 0, proc.stderr[-300:]
    assert len([line for line in proc.stdout.splitlines() if line]) == 3
