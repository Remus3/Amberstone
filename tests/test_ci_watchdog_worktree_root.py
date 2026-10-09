"""The CI watchdog's dedicated worktree is resolved, never a machine literal.

MAIN 2246 ORDER section 3 (leaks by class, worktree paths): tools/ci_watchdog.py
carried a drive-rooted literal for its throwaway worktree. The location is now
derived: env RC_CI_WATCHDOG_WORKTREE (non-blank) wins, else the folder
`RC-CIWatchdog` beside the checkout - the same sibling-of-the-checkout shape the
literal had before the checkout changed drives.
"""
from __future__ import annotations

from pathlib import Path

from tools import ci_watchdog as cw

REPO = Path(__file__).resolve().parents[1]


def test_default_is_the_checkout_sibling(tmp_path):
    repo = tmp_path / "Example Repo"
    got = cw.resolve_worktree(env={}, repo_root=repo)
    assert got == tmp_path / "RC-CIWatchdog"


def test_env_override_wins(tmp_path):
    got = cw.resolve_worktree(
        env={"RC_CI_WATCHDOG_WORKTREE": str(tmp_path / "wd")}, repo_root=tmp_path / "r")
    assert got == tmp_path / "wd"


def test_blank_env_is_ignored(tmp_path):
    repo = tmp_path / "r"
    got = cw.resolve_worktree(env={"RC_CI_WATCHDOG_WORKTREE": "   "}, repo_root=repo)
    assert got == tmp_path / "RC-CIWatchdog"


def test_module_default_matches_the_resolver():
    assert cw.WORKTREE == cw.resolve_worktree()


def test_no_drive_rooted_worktree_literal_in_the_module():
    text = (REPO / "tools" / "ci_watchdog.py").read_text(encoding="utf-8")
    for spelling in ("C:\\RC-CIWatchdog", "C:/RC-CIWatchdog"):
        assert spelling not in text, spelling
