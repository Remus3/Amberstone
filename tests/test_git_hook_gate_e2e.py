"""End-to-end proof that the tracked git hooks actually REFUSE a bad commit.

WHY THIS EXISTS
---------------
MEASURED 2026-07-26: all five tracked hooks in `.githooks/` were committed mode
100644. Git refuses to execute a non-executable hook and says nothing about it,
so on every Linux clone - CI included - the entire gate was absent while every
check reported green. The same day, a headless
`claude -p --permission-mode bypassPermissions` run committed a banned U+2014
em-dash straight through, because the Claude PreToolUse gate does not survive
that mode and the git-level gate that was supposed to back it up was inert.

CLAUDE.md draws the conclusion this file implements: "Never treat a hook's
PRESENCE as proof it fires; the only valid test is end-to-end (stage a banned
glyph, attempt a real commit, assert HEAD unchanged)." Every cheaper assertion
available - the hook file exists, core.hooksPath is set, the index mode is
100755 - was true at some point while the gate was still not firing.

THE POSITIVE CONTROL IS NOT OPTIONAL
------------------------------------
A refusal test alone is worthless here: a commit that fails because the harness
forgot to copy a script the hook invokes looks exactly like a commit that failed
because the gate worked. So the clean-ASCII case must be asserted to COMMIT, and
it additionally asserts the hook's own stdout marker so a silently-unwired
harness cannot pass by doing nothing.

WHY A TEMPORARY REPO
--------------------
The commit under test must be real, and this repo is not a place to make throwaway
commits. `git worktree` was also ruled out: a post-commit gist-mirror hook used to
corrupt a linked worktree's index here (memory
`reference_gist_hook_worktree_index_corruption`). That hook was deleted on
2026-09-07 with the external review package it mirrored, so the specific bug is
gone - but the first reason stands on its own, so the fixture stays a standalone
`git init` in a temp dir, with the REAL hook bodies and the REAL scripts they
invoke copied in.

WHY pre-commit IS REDUCED AND commit-msg IS NOT
-----------------------------------------------
`.githooks/commit-msg` only invokes repo-independent scripts, so it is copied
byte for byte. `.githooks/pre-commit` has four numbered steps, and steps 3-4
(gen_archmap --check, gen_state_schema --check) re-derive generated artifacts
from the whole RC tree and cannot run against a two-file temp repo. Steps 1 and
2 - the glyph/ruff gate and py_compile - are the gate itself and
are carried over verbatim, parsed out of the real file rather than retyped, with
assertions that the parse actually found them. If someone deletes the gate from
the real hook, the parse fails loudly instead of testing a hand-written copy.

The em-dash below is written as an escape on purpose: this file is scanned by
tests/test_smart_quote_hygiene.py, so a literal U+2014 in the source would fail
the repo's own ASCII hygiene guard.
"""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parent.parent
HOOKS = REPO / ".githooks"

# Written as an escape, never a literal: this file is itself scanned by the
# repo's ASCII hygiene guards.
EM_DASH = "\u2014"

_HAVE_GIT = shutil.which("git") is not None

# Steps of .githooks/pre-commit that run against the whole RC tree and so cannot
# be exercised in a two-file fixture. Everything else is carried over.
_WHOLE_TREE_STEPS = (3, 4)

# Hooks the fixture deliberately does NOT install: post-checkout hard-fails when
# git-lfs is absent, and pre-push is irrelevant to a commit-time gate.
_FIXTURE_HOOKS = ("pre-commit", "commit-msg")

# Scripts the two installed hooks invoke via "$ROOT/...". Copied to the same
# relative path so each script's own `parent.parent` ROOT resolves to the fixture.
_SUPPORT_SCRIPTS = (
    "tools/precommit_gate.py",
    "scripts/precommit_pycompile.py",
    "scripts/precommit_msg_check.py",
)

_STEP_MARKER = re.compile(r"^# (\d+)\. ", re.M)


def _reduce_pre_commit(text: str) -> str:
    """Carry over the repo-independent steps of the REAL pre-commit hook.

    Parses the numbered step markers rather than retyping the hook, so a gate
    that has been removed upstream cannot be silently reintroduced here.
    """
    marks = list(_STEP_MARKER.finditer(text))
    if len(marks) < 4:
        raise AssertionError(
            f"expected 4 numbered steps in {HOOKS / 'pre-commit'}, parsed {len(marks)} "
            "- the hook has been restructured and this fixture must be re-read"
        )
    out = [text[: marks[0].start()]]
    kept: dict[int, str] = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        num = int(m.group(1))
        block = text[m.start():end]
        if num in _WHOLE_TREE_STEPS:
            continue
        kept[num] = block
        out.append(block)
    if "precommit_gate.py" not in kept.get(1, ""):
        raise AssertionError("pre-commit step 1 no longer invokes precommit_gate.py")
    if "precommit_pycompile.py" not in kept.get(2, ""):
        raise AssertionError("pre-commit step 2 no longer invokes precommit_pycompile.py")
    return "".join(out)


class TrackedHookModeTests(unittest.TestCase):
    """The exact regression that made every hook inert on Linux.

    File modes ARE carried by a clone, unlike core.hooksPath, so this is a
    property of the repository and runs unconditionally. Asserted directly and
    by name: a 100644 hook produces no error message anywhere, so the only way
    it ever surfaces is an assertion that names the mode.
    """

    @unittest.skipUnless(_HAVE_GIT, "git not on PATH")
    def test_every_tracked_hook_is_executable_in_the_index(self) -> None:
        out = subprocess.run(
            ["git", "-C", str(REPO), "ls-files", "-s", ".githooks/"],
            capture_output=True, text=True,
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        rows = [ln for ln in out.stdout.splitlines() if ln.strip()]
        self.assertGreaterEqual(len(rows), 5, f"expected 5 tracked hooks, saw {rows}")
        bad = [ln for ln in rows if not ln.startswith("100755 ")]
        self.assertEqual(
            bad, [], "git silently refuses to run a non-executable hook: " + str(bad)
        )


@unittest.skipUnless(_HAVE_GIT, "git not on PATH")
class HookGateEndToEndTests(unittest.TestCase):
    """A real commit into a throwaway repo wired exactly like this one."""

    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="rc_hook_gate_"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self._build_fixture()

    # ---- fixture -------------------------------------------------------

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        proc = subprocess.run(
            ["git", "-C", str(self.root), *args],
            capture_output=True, text=True, env=self._env,
        )
        if check and proc.returncode != 0:
            self.fail(f"git {' '.join(args)} failed:\n{proc.stdout}\n{proc.stderr}")
        return proc

    def _build_fixture(self) -> None:
        import os

        # Isolate from the operator's global/system git config: an inherited
        # core.hooksPath, autocrlf or LFS filter would make this fixture measure
        # the wrong thing.
        self._env = dict(os.environ)
        self._env["GIT_CONFIG_GLOBAL"] = str(self.root / "no-global-gitconfig")
        self._env["GIT_CONFIG_SYSTEM"] = str(self.root / "no-system-gitconfig")
        # The hooks honour ${PYTHON:-py}; pin it to the interpreter running the
        # test so the fixture does not depend on `py` or on PATH resolution.
        self._env["PYTHON"] = sys.executable.replace("\\", "/")

        subprocess.run(
            ["git", "init", "-q", str(self.root)], capture_output=True, env=self._env,
        )
        self._git("config", "user.name", "hook gate test")
        self._git("config", "user.email", "hookgate@example.invalid")
        self._git("config", "commit.gpgsign", "false")

        hooks = self.root / ".githooks"
        hooks.mkdir()
        for name in _FIXTURE_HOOKS:
            body = (HOOKS / name).read_text(encoding="utf-8")
            if name == "pre-commit":
                body = _reduce_pre_commit(body)
            dst = hooks / name
            dst.write_text(body, encoding="utf-8", newline="\n")
            dst.chmod(0o755)

        for rel in _SUPPORT_SCRIPTS:
            dst = self.root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO / rel, dst)

        # Same wiring scripts/install_hooks.py performs: a RELATIVE core.hooksPath
        # so the pointer survives being cloned to another location.
        self._git("config", "core.hooksPath", ".githooks")

        # Track the hooks with the executable index mode, mirroring the live repo
        # so this fixture stays meaningful on the Linux runner that actually
        # matters - where 100644 is the difference between a gate and nothing.
        self._git("add", "-A")
        for name in _FIXTURE_HOOKS:
            self._git("update-index", "--chmod=+x", f".githooks/{name}")
        # Baseline commit only - --no-verify because the fixture's own scaffolding
        # is not what is under test.
        self._git("commit", "--no-verify", "-q", "-m", "chore: fixture baseline")

    def _head(self) -> str:
        return self._git("rev-parse", "HEAD").stdout.strip()

    def _commit(self, message: str) -> subprocess.CompletedProcess:
        """Commit via -F so a non-ASCII MESSAGE cannot be mangled by argv encoding."""
        msg = self.root / ".commit-message"
        msg.write_text(message + "\n", encoding="utf-8", newline="\n")
        return self._git("commit", "-F", str(msg), check=False)

    # ---- the three assertions -----------------------------------------

    def test_clean_ascii_change_commits(self) -> None:
        """POSITIVE CONTROL. Without this, a refusal proves nothing.

        A hook that dies because the harness forgot to copy a script it invokes
        refuses every commit and looks identical to a working gate. This also
        asserts the hook's own stdout marker, so an unwired fixture cannot pass
        by silently doing nothing at all.
        """
        (self.root / "sample_module.py").write_text(
            'print("all ascii here")\n', encoding="utf-8", newline="\n"
        )
        self._git("add", "sample_module.py")
        before = self._head()

        proc = self._commit("test: add an all-ascii fixture module")

        self.assertEqual(
            proc.returncode, 0,
            f"clean ASCII commit was refused:\n{proc.stdout}\n{proc.stderr}",
        )
        self.assertNotEqual(self._head(), before, "HEAD did not advance")
        self.assertIn(
            "py_compile", proc.stdout + proc.stderr,
            "the pre-commit hook produced no output - it did not run, so the "
            "refusal tests below would prove nothing",
        )

    def test_em_dash_in_staged_content_is_refused(self) -> None:
        """The banned glyph in FILE CONTENT half of the gate (pre-commit)."""
        (self.root / "notes.txt").write_text(
            f"a clause{EM_DASH}and its continuation\n", encoding="utf-8", newline="\n"
        )
        self._git("add", "notes.txt")
        before = self._head()

        proc = self._commit("test: stage a banned glyph")

        self.assertNotEqual(
            proc.returncode, 0,
            f"an em-dash in staged content COMMITTED:\n{proc.stdout}\n{proc.stderr}",
        )
        self.assertEqual(self._head(), before, "HEAD advanced on a refused commit")

    def test_em_dash_in_commit_message_is_refused(self) -> None:
        """The half that CANNOT live in pre-commit, and was a real measured miss.

        Git's order is pre-commit -> prepare the message -> commit-msg, so
        `.git/COMMIT_EDITMSG` does not exist yet when pre-commit runs. While the
        gate was invoked only from pre-commit the content and ruff halves still
        fired - so it LOOKED healthy - while a U+2014 in a commit SUBJECT landed
        clean (measured 2026-07-26).
        """
        (self.root / "clean.txt").write_text(
            "nothing wrong with this file\n", encoding="utf-8", newline="\n"
        )
        self._git("add", "clean.txt")
        before = self._head()

        proc = self._commit(f"test: subject with a banned{EM_DASH}glyph in it")

        self.assertNotEqual(
            proc.returncode, 0,
            f"an em-dash in the commit MESSAGE committed:\n{proc.stdout}\n{proc.stderr}",
        )
        self.assertEqual(self._head(), before, "HEAD advanced on a refused commit")


if __name__ == "__main__":
    unittest.main()
