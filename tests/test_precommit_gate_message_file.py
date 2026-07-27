"""RC port of LW's section-2 finding: pre-commit CANNOT see the commit message.

THE DEFECT THIS PINS
--------------------
`tools/precommit_gate.py` originally ran only as a Claude PreToolUse hook, where
it received the ENTIRE command string - including the `-m "..."` text - so its
commit-message glyph check worked for free.

When the gate was ported into `.githooks/pre-commit` (2026-07-26, to close the
`bypassPermissions` hole), the hook invoked it as `echo "git commit" | gate`.
The staged-content and ruff halves still fired, so it LOOKED correct. The
message half silently became a no-op, because there is no message in the string.

It cannot be fixed by passing the message at pre-commit time either: git's order
is pre-commit -> prepare the message -> commit-msg, so `.git/COMMIT_EDITMSG` does
not exist yet when pre-commit runs. The message check belongs in `commit-msg`,
which receives the message file as `$1`.

MEASURED before the fix: a commit whose subject contained a U+2014 em-dash
LANDED (`755e4ba7`, reset). Credit to the parallel Sibling-A session for
predicting this exact failure before RC probed it.

These tests pin BOTH halves, because a check that only ever passes is worse than
no check.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parent.parent
GATE = REPO / "tools" / "precommit_gate.py"

# U+2014 EM DASH / U+2013 EN DASH / U+201C LEFT DOUBLE QUOTE, built from
# codepoints so this test file itself stays 7-bit ASCII and does not trip the
# repo's own hygiene suite.
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
SMART_QUOTE = chr(0x201C)


def _run_message_file(text: str) -> subprocess.CompletedProcess:
    tmp = pathlib.Path(tempfile.mktemp(suffix=".msg"))
    tmp.write_text(text, encoding="utf-8")
    try:
        return subprocess.run(
            [sys.executable, str(GATE), "--message-file", str(tmp)],
            capture_output=True, text=True, cwd=str(REPO), timeout=120,
        )
    finally:
        tmp.unlink(missing_ok=True)


class MessageFileModeTests(unittest.TestCase):
    """--message-file is the commit-msg entry point."""

    def test_clean_message_passes(self) -> None:
        r = _run_message_file("fix(ops): a perfectly ordinary subject line\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_em_dash_in_the_subject_is_blocked(self) -> None:
        r = _run_message_file(f"fix(ops): a subject with an {EM_DASH} in it\n")
        self.assertNotEqual(r.returncode, 0, "an em-dash subject must be blocked")
        self.assertIn("commit message", (r.stdout + r.stderr).lower())

    def test_en_dash_in_the_body_is_blocked(self) -> None:
        r = _run_message_file(f"fix(ops): fine subject\n\nbody has an {EN_DASH} dash\n")
        self.assertNotEqual(r.returncode, 0, "the BODY must be scanned, not just the subject")

    def test_smart_quote_is_blocked(self) -> None:
        r = _run_message_file(f"fix(ops): a {SMART_QUOTE}smart quote subject\n")
        self.assertNotEqual(r.returncode, 0)

    def test_missing_file_does_not_crash_the_commit(self) -> None:
        """A hook that explodes on its own bug must not wedge every commit."""
        r = subprocess.run(
            [sys.executable, str(GATE), "--message-file", "does-not-exist.msg"],
            capture_output=True, text=True, cwd=str(REPO), timeout=60,
        )
        self.assertEqual(r.returncode, 0, "an unreadable message file must fail OPEN")

    def test_comment_lines_are_ignored(self) -> None:
        """git's own template comments are stripped before commit and must not block."""
        r = _run_message_file(
            f"fix(ops): clean subject\n\n# Please enter the commit message {EM_DASH} etc\n"
        )
        self.assertEqual(r.returncode, 0, "commented template lines must not block")


class HookWiringTests(unittest.TestCase):
    """The gate must actually be WIRED into commit-msg, not merely capable."""

    def test_commit_msg_hook_invokes_the_gate(self) -> None:
        hook = (REPO / ".githooks" / "commit-msg").read_text(encoding="utf-8")
        self.assertIn("precommit_gate.py", hook)
        self.assertIn("--message-file", hook)

    def test_pre_commit_hook_still_gates_staged_content(self) -> None:
        hook = (REPO / ".githooks" / "pre-commit").read_text(encoding="utf-8")
        self.assertIn("precommit_gate.py", hook)

    def test_this_file_is_ascii(self) -> None:
        raw = pathlib.Path(__file__).read_bytes()
        self.assertEqual([b for b in raw if b > 127], [])


if __name__ == "__main__":
    unittest.main()
