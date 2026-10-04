"""RM-422: keep the longest tracked path short enough to clone on Windows.

`core.longpaths` is unset by default, and Windows MAX_PATH is 260 for a
non-longpath-aware API, so the clone ROOT budget is 260 - longest - 1. At a
154-char longest path a 114-char root (this machine's session scratchpad)
aborted checkout PARTWAY, leaving a half-populated tree every enumeration
reported as clean. The archive directories that held the longest paths were
renamed (2026-10-04) so the longest is now 129 and the root budget is 130.

This guard reads the GIT INDEX, not the disk, so it measures what a fresh
clone must write - a disk walk on the machine that already works is green by
construction. `core.longpaths` itself is documented in docs/OPERATIONS.md
(`git clone -c core.longpaths=true`); this test covers the consumers that a
git setting cannot reach.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

MAX_PATH = 260
# Longest tracked path allowed. Root budget = MAX_PATH - this - 1 = 130 chars,
# which covers user-profile, temp and CI-workspace roots seen on this machine.
MAX_TRACKED_PATH_CHARS = 129


def _tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO,
                         capture_output=True, check=True).stdout
    return [p.decode("utf-8") for p in out.split(b"\0") if p]


def test_longest_tracked_path_fits_the_clone_root_budget():
    paths = _tracked()
    assert len(paths) > 1000, "git index enumeration came back near-empty"
    too_long = sorted((len(p), p) for p in paths
                      if len(p) > MAX_TRACKED_PATH_CHARS)
    assert too_long == [], (
        f"tracked paths over {MAX_TRACKED_PATH_CHARS} chars shrink the clone "
        f"root budget below {MAX_PATH - MAX_TRACKED_PATH_CHARS - 1}: "
        f"{too_long[-5:]}"
    )


def test_budget_covers_the_root_that_failed():
    # The measured failing root (session scratchpad) was 114 chars.
    assert MAX_PATH - MAX_TRACKED_PATH_CHARS - 1 >= 114


def test_operations_doc_names_the_clone_flag():
    ops = (REPO / "docs" / "OPERATIONS.md").read_text(encoding="utf-8")
    assert "core.longpaths=true" in ops
