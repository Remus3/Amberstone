"""RM-1271: the commit-msg hook refuses a lane commit that lacks its `Lane:` trailer.

MAIN ORDER 2026-10-31-2215 item 5 asked for a `Lane: <name>` trailer on every
lane and merger commit, and for a hook check once a week of lane commits showed
the trailer on 90 percent or more of them (BACKLOG RM-1271). Measured
2026-11-04..11-11: 1459 of 1462 lane commits carried `Lane: <lane>` as the
last non-blank line (the 3 misses are s158 main-session fixups on lane/repo),
so the check was adjudicated in s161.

The rule, as `.githooks/commit-msg` step 4 implements it:

* it applies ONLY when the current branch is `lane/<x>`; a detached HEAD
  (every rebase step) and every other branch, main included, are not checked;
* the message's last non-blank line - after `#` comment lines are dropped and
  anything below a scissors line is cut, as git's default cleanup would - must
  be exactly `Lane: <x>` for that branch's <x>;
* it runs AFTER both trailer strips (RC's Co-Authored-By strip and the kit's
  fleet_identity strip), so a stripped AI trailer below `Lane:` cannot make a
  correct commit look wrong.

The check is inline POSIX sh, never a new `$ROOT/...` script: a lane worktree
runs main's hook against its own older tree, where a script added later would
be missing and would refuse every lane commit.

Same fixture shape as tests/test_git_hook_gate_e2e.py: a throwaway `git init`
in a temp dir with the REAL hook body and the REAL scripts it invokes copied
in, never the live repo. Each refusal case is paired with a positive control
on the same fixture, so a hook that refuses everything (an uncopied script, a
syntax error) cannot pass as a working check.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parent.parent
HOOK = REPO / ".githooks" / "commit-msg"

_HAVE_GIT = shutil.which("git") is not None

# Scripts the commit-msg hook invokes via "$ROOT/...", copied to the same
# relative path so each script's own ROOT resolves to the fixture.
_SUPPORT_SCRIPTS = (
    "tools/precommit_gate.py",
    "tools/ascii_rule.py",
    "scripts/precommit_msg_check.py",
)

# Variables that point git at ANOTHER repository. A suite started from inside
# a git hook inherits them, and `git -C <fixture>` would then act on the live
# repo instead of the fixture.
_GIT_REDIRECTS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_NAMESPACE",
    "GIT_PREFIX",
)

_SCISSORS = "# ------------------------ >8 ------------------------"


class HookPlacementTests(unittest.TestCase):
    """Static half: the check sits after both strips and calls no new script."""

    def setUp(self) -> None:
        self.text = HOOK.read_text(encoding="utf-8")

    def test_lane_check_runs_after_both_trailer_strips(self) -> None:
        self.assertIn("symbolic-ref --short -q HEAD", self.text, "no RM-1271 lane check in the hook")
        check = self.text.index("symbolic-ref --short -q HEAD")
        rc_strip = self.text.index("'^Co-Authored-By: Claude'")
        kit_strip = self.text.index('"ops/fleet_kit/fleet_identity.py" commit-msg')
        self.assertLess(rc_strip, kit_strip, "the two strips changed order")
        self.assertLess(kit_strip, check, "the lane check must run after the kit strip")

    def test_lane_check_is_inline_not_a_new_script(self) -> None:
        block = self.text[self.text.index("RM-1271") :]
        self.assertNotIn("$ROOT/", block, "a lane worktree's older tree may lack a new script")
        self.assertNotIn("$PY", block, "the lane check must not depend on python")


@unittest.skipUnless(_HAVE_GIT, "git not on PATH")
class LaneTrailerHookEndToEndTests(unittest.TestCase):
    """A real commit into a throwaway repo wired with the real commit-msg hook."""

    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="rc_lane_trailer_"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self._seq = 0
        self._build_fixture()

    # ---- fixture -------------------------------------------------------

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        proc = subprocess.run(
            ["git", "-C", str(self.root), *args],
            capture_output=True,
            text=True,
            env=self._env,
            check=False,
        )
        if check and proc.returncode != 0:
            self.fail(f"git {' '.join(args)} failed:\n{proc.stdout}\n{proc.stderr}")
        return proc

    def _build_fixture(self) -> None:
        env = {k: v for k, v in os.environ.items() if k not in _GIT_REDIRECTS}
        # Isolate from the operator's global/system git config (an inherited
        # core.hooksPath, autocrlf or default branch would change the fixture).
        env["GIT_CONFIG_GLOBAL"] = str(self.root / "no-global-gitconfig")
        env["GIT_CONFIG_SYSTEM"] = str(self.root / "no-system-gitconfig")
        # The hook honours ${PYTHON:-py}; pin it to this interpreter.
        env["PYTHON"] = sys.executable.replace("\\", "/")
        self._env = env

        subprocess.run(["git", "init", "-q", str(self.root)], capture_output=True, env=env, check=False)
        self._git("symbolic-ref", "HEAD", "refs/heads/main")
        self._git("config", "user.name", "lane trailer test")
        self._git("config", "user.email", "lanetrailer@example.invalid")
        self._git("config", "commit.gpgsign", "false")

        hooks = self.root / ".githooks"
        hooks.mkdir()
        dst = hooks / "commit-msg"
        dst.write_text(HOOK.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
        dst.chmod(0o755)
        for rel in _SUPPORT_SCRIPTS:
            out = self.root / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO / rel, out)
        self._git("config", "core.hooksPath", ".githooks")
        self._git("add", "-A")
        self._git("commit", "--no-verify", "-q", "-m", "chore: fixture baseline")

    def _head(self) -> str:
        return self._git("rev-parse", "HEAD").stdout.strip()

    def _commit(self, message: str, *extra: str) -> subprocess.CompletedProcess:
        """Stage a fresh change, then commit via -F (git's own message path)."""
        self._seq += 1
        (self.root / "change.txt").write_text(f"change {self._seq}\n", encoding="utf-8", newline="\n")
        self._git("add", "change.txt")
        msg = self.root / ".git" / "rm1271-message"
        msg.write_text(message, encoding="utf-8", newline="\n")
        return self._git("commit", "-F", str(msg), *extra, check=False)

    def _assert_lands(self, message: str, *extra: str) -> None:
        before = self._head()
        proc = self._commit(message, *extra)
        self.assertEqual(proc.returncode, 0, f"commit was refused:\n{proc.stdout}\n{proc.stderr}")
        self.assertNotEqual(self._head(), before, "HEAD did not advance")

    def _assert_refused(self, message: str, lane: str) -> None:
        before = self._head()
        proc = self._commit(message)
        self.assertNotEqual(proc.returncode, 0, f"a lane commit without its trailer LANDED:\n{proc.stdout}")
        self.assertEqual(self._head(), before, "HEAD advanced on a refused commit")
        reason = [ln for ln in proc.stderr.splitlines() if "RM-1271" in ln]
        self.assertEqual(len(reason), 1, f"want one RM-1271 reason line:\n{proc.stderr}")
        self.assertTrue(reason[0].isascii(), reason[0])
        self.assertIn(f"Lane: {lane}", reason[0])

    def _on_lane(self, lane: str = "queue") -> None:
        self._git("checkout", "-q", "-b", f"lane/{lane}")

    # ---- lane branch ---------------------------------------------------

    def test_lane_commit_with_its_trailer_lands(self) -> None:
        self._on_lane()
        self._assert_lands("test: a lane change\n\nWhy it changed.\n\nLane: queue\n")
        body = self._git("log", "-1", "--format=%B").stdout.rstrip("\n")
        self.assertTrue(body.endswith("Lane: queue"), body)

    def test_lane_commit_without_a_trailer_is_refused(self) -> None:
        self._on_lane()
        self._assert_refused("test: a lane change\n\nWhy it changed.\n", "queue")
        # Positive control on the same fixture: the hook refuses on the
        # trailer, not on something the harness forgot to copy.
        self._assert_lands("test: a lane change\n\nWhy it changed.\n\nLane: queue\n")

    def test_lane_commit_with_another_lanes_trailer_is_refused(self) -> None:
        self._on_lane()
        self._assert_refused("test: a lane change\n\nLane: ds\n", "queue")

    def test_trailer_followed_by_another_line_is_refused(self) -> None:
        self._on_lane()
        self._assert_refused("test: a lane change\n\nLane: queue\nReviewed-by: someone\n", "queue")

    def test_blank_and_comment_lines_after_the_trailer_are_accepted(self) -> None:
        self._on_lane()
        message = "test: a lane change\n\nLane: queue\n\n# a comment git strips\n\n#another\n\n\n"
        self._assert_lands(message, "--cleanup=strip")
        body = self._git("log", "-1", "--format=%B").stdout.rstrip("\n")
        self.assertTrue(body.endswith("Lane: queue"), body)

    def test_lines_below_the_scissors_are_ignored(self) -> None:
        self._on_lane()
        message = f"test: a lane change\n\nLane: queue\n{_SCISSORS}\n# Do not modify.\ndiff --git a/x b/x\n+added\n"
        self._assert_lands(message, "--cleanup=scissors")

    def test_check_runs_after_the_co_author_strip(self) -> None:
        self._on_lane()
        self._assert_lands("test: a lane change\n\nLane: queue\nCo-Authored-By: Claude <noreply@example.invalid>\n")

    # ---- not a lane branch ---------------------------------------------

    def test_main_commit_without_a_trailer_lands(self) -> None:
        self._assert_lands("test: a main change\n\nNo lane trailer here.\n")

    def test_other_branch_commit_without_a_trailer_lands(self) -> None:
        self._git("checkout", "-q", "-b", "feature/lane")
        self._assert_lands("test: a feature change\n")

    def test_detached_head_commit_without_a_trailer_lands(self) -> None:
        self._on_lane()
        self._git("checkout", "-q", "--detach")
        self._assert_lands("test: a detached change\n")


if __name__ == "__main__":
    unittest.main()
