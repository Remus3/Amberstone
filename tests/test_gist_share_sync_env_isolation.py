"""Regression: gist_share_sync._git must operate on the gist CLONE_DIR even when
a hook has exported GIT_DIR into the environment.

MEASURED 2026-09-01. The post-commit hook runs tools/gist_share_sync.py, and git
exports GIT_DIR / GIT_WORK_TREE / GIT_INDEX_FILE pointing at the committing
worktree while a hook runs. Those OVERRIDE `git -C CLONE_DIR` (git resolves the
repo from GIT_DIR, not the -C cwd), so `_git` left them inherited and every call
hit the committing worktree instead of the gist clone: it staged that worktree,
committed "sync Share -> gist" onto its branch, `reset --hard` moved its HEAD to a
rootless commit, `gc --prune=now --expire=now` orphaned in-flight DS commits, and
`push --force origin main` fired at the RC remote. It corrupted lane/ds across
repeated recovery attempts and was only saved from clobbering origin/main by local
main == origin main making the force-push a no-op.

The fix is env scrubbing in `_clean_git_env`; this pins it in both directions -
the scrub removes the leak vars, and (where the gist clone exists) git actually
resolves the clone under a polluting GIT_DIR.
"""
import os
import unittest
from pathlib import Path
from unittest import mock

from tools import gist_share_sync as G

_LEAK = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
         "GIT_COMMON_DIR", "GIT_NAMESPACE")


class GitEnvIsolation(unittest.TestCase):
    def test_clean_git_env_strips_every_hook_leak_var(self):
        polluted = dict(os.environ)
        polluted.update({v: "/decoy" for v in _LEAK})
        with mock.patch.dict(os.environ, polluted, clear=True):
            env = G._clean_git_env()
        for var in _LEAK:
            self.assertNotIn(var, env, f"{var} leaked into the git env")
        # a non-git var is preserved (the scrub is targeted, not a wipe)
        self.assertEqual(env.get("PATH"), os.environ.get("PATH"))

    def test_clean_git_env_is_what_git_actually_runs_with(self):
        # _git must pass env=_clean_git_env(); pin the wiring so a refactor that
        # drops the env= kwarg re-opens the hole.
        with mock.patch.object(G.subprocess, "run") as run:
            run.return_value = mock.Mock()
            with mock.patch.dict(os.environ, {"GIT_DIR": "/decoy/.git"}, clear=False):
                G._git("status")
        passed = run.call_args.kwargs.get("env")
        self.assertIsNotNone(passed, "_git did not pass env= (GIT_DIR would leak)")
        self.assertNotIn("GIT_DIR", passed)

    def test_git_resolves_the_clone_not_a_polluting_GIT_DIR(self):
        # End-to-end, only where the gist clone is present (skips cleanly on CI
        # and any box without it, so the suite stays green there).
        if not (Path(G.CLONE_DIR) / ".git").is_dir():
            self.skipTest("gist clone not present")
        decoy = str(Path(G.REPO_ROOT) / ".git")
        with mock.patch.dict(os.environ, {"GIT_DIR": decoy}, clear=False):
            out = G._git("rev-parse", "--absolute-git-dir").stdout.strip()
        self.assertEqual(Path(out).resolve(), (Path(G.CLONE_DIR) / ".git").resolve())


if __name__ == "__main__":
    unittest.main()
