"""MAIN FIX 2026-10-21 1254 item #2: PostToolUse output reaches the model.

A PostToolUse hook that exits 0 with plain stdout (tools/pytest_guard.py) or
stderr (tools/edit_lint_check.py arms 1-2) is never shown to the model, so a
py_compile failure after an edit was invisible. The fleet UI/UX standard
section 5 (FLEET-COMMON item 15) sets the shape: silent by default; a finding
is ONE stdout line
    {"hookSpecificOutput": {"hookEventName": "PostToolUse",
                            "additionalContext": "..."}}
with exit 0 and no ANSI.

Every test here runs the REAL script as a child process and feeds it a recorded
payload on stdin, which is the only end-to-end proof of the channel.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_HOOKS = {
    "pytest_guard": REPO_ROOT / "tools" / "pytest_guard.py",
    "edit_lint_check": REPO_ROOT / "tools" / "edit_lint_check.py",
}
_EMDASH = chr(0x2014)


def _payload(tool: str, tool_input: dict, cwd: Path) -> str:
    return json.dumps({
        "session_id": "00000000-0000-0000-0000-000000000000",
        "transcript_path": "<transcript>",
        "cwd": str(cwd),
        "hook_event_name": "PostToolUse",
        "tool_name": tool,
        "tool_input": tool_input,
        "tool_response": {"success": True},
    })


def _hook(name: str, stdin: str, cwd: Path) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_FILE_PATHS", "RC_FULL_SUITE")}
    return subprocess.run(
        [sys.executable, str(_HOOKS[name])], input=stdin, capture_output=True,
        text=True, timeout=60, env=env, cwd=str(cwd),
    )


def _context(proc: subprocess.CompletedProcess) -> str:
    assert proc.returncode == 0, (proc.returncode, proc.stderr)
    assert "\x1b" not in proc.stdout + proc.stderr, "no ANSI in hook output"
    lines = proc.stdout.splitlines()
    assert len(lines) == 1, f"exactly ONE stdout line expected, got {proc.stdout!r}"
    assert lines[0].isascii()
    hso = json.loads(lines[0])["hookSpecificOutput"]
    assert hso["hookEventName"] == "PostToolUse"
    ctx = hso["additionalContext"]
    assert isinstance(ctx, str) and ctx.strip()
    assert "\n" not in ctx, "additionalContext must be one line"
    return ctx


def _silent(proc: subprocess.CompletedProcess) -> None:
    assert proc.returncode == 0, (proc.returncode, proc.stderr)
    assert proc.stdout == "", f"clean run must be silent, got {proc.stdout!r}"


# ---------- pytest_guard ---------------------------------------------------


def test_pytest_guard_compile_failure_is_one_context_line(tmp_path):
    bad = tmp_path / "broken.py"
    bad.write_bytes(b"x = 1\ndef f(:\n    pass\n")
    ctx = _context(_hook("pytest_guard", _payload("Write", {"file_path": str(bad)}, tmp_path),
                         tmp_path))
    assert "broken.py" in ctx
    assert ":2" in ctx, "the context names the failing line"
    assert "SyntaxError" in ctx or "syntax" in ctx.lower()


def test_pytest_guard_clean_compile_is_silent(tmp_path):
    ok = tmp_path / "fine.py"
    ok.write_text("x = 1\n", encoding="utf-8")
    _silent(_hook("pytest_guard", _payload("Edit", {"file_path": str(ok)}, tmp_path), tmp_path))


@pytest.mark.parametrize("tool_input", [
    {"file_path": "docs/notes.md"},
    {"file_path": "web/js/main.js"},
    {"command": "git status"},
])
def test_pytest_guard_nothing_to_report_is_silent(tool_input, tmp_path):
    _silent(_hook("pytest_guard", _payload("Edit", tool_input, tmp_path), tmp_path))


def test_pytest_guard_garbage_stdin_is_silent(tmp_path):
    _silent(_hook("pytest_guard", "not json {{{", tmp_path))


# ---------- edit_lint_check ------------------------------------------------


def test_edit_lint_check_glyph_finding_is_one_context_line(tmp_path):
    f = tmp_path / "g.txt"
    f.write_text("a " + _EMDASH + " b\n", encoding="utf-8")
    proc = _hook("edit_lint_check", _payload(
        "Write", {"file_path": str(f), "content": "a " + _EMDASH + " b\n"}, tmp_path), tmp_path)
    ctx = _context(proc)
    assert "g.txt" in ctx and "em-dash" in ctx
    assert proc.stderr == "", "stderr on exit 0 never reaches the model"


def test_edit_lint_check_credential_finding_is_one_context_line(tmp_path):
    f = tmp_path / "k.txt"
    body = "key " + "AKIA" + "A" * 16 + "\n"
    f.write_text(body, encoding="utf-8")
    proc = _hook("edit_lint_check", _payload(
        "Write", {"file_path": str(f), "content": body}, tmp_path), tmp_path)
    ctx = _context(proc)
    assert "CREDENTIAL" in ctx.upper() and "aws_access_key_id" in ctx
    assert "AKIA" not in proc.stdout + proc.stderr


def test_edit_lint_check_clean_edit_is_silent(tmp_path):
    f = tmp_path / "c.txt"
    f.write_text("plain\n", encoding="utf-8")
    proc = _hook("edit_lint_check", _payload(
        "Edit", {"file_path": str(f), "old_string": "p", "new_string": "plain"}, tmp_path),
        tmp_path)
    _silent(proc)
    assert proc.stderr == ""


@pytest.mark.parametrize("name", sorted(_HOOKS))
def test_hook_never_exits_non_zero_on_a_finding(name, tmp_path):
    bad = tmp_path / "both.py"
    bad.write_text("def f(:\n" + "# " + _EMDASH + "\n", encoding="utf-8")
    proc = _hook(name, _payload("Write", {"file_path": str(bad),
                                          "content": bad.read_text(encoding="utf-8")},
                                tmp_path), tmp_path)
    _context(proc)
