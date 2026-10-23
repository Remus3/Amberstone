"""MAIN FIX 2026-10-21 1254 items #1, #3, #11, #13, #14: the PostToolUse edit hook.

#1  Current Claude Code hands a PostToolUse hook its payload as JSON on stdin and
    does NOT set CLAUDE_FILE_PATHS. tools/edit_lint_check.py read only that env
    var, so its ruff, glyph and credential arms never ran on a live edit. The
    payloads below are recorded shapes of the four editing tools (Edit, Write,
    MultiEdit, NotebookEdit); the env var survives only as a fallback.
#3  `ruff check --fix` mid-edit deleted a just-added import before its first use
    was written. The arm is report-only.
#11 No `.ruff_cache/` is left in the cwd or beside the edited file.
#13 One ASCII rule shared with the commit gate (tools/ascii_rule.py): every
    codepoint > 127, the same exempt surfaces, the same population shape (the
    text the tool wrote, as the gate reads added lines).
#14 The fix hint names tools/strip_em_dashes.py / strip_smart_quotes.py as
    OPTIONAL helpers, never as hook dependencies.

Source stays ASCII: every non-ASCII probe is built with chr().
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tests._module_view import bind_subprocess  # noqa: E402
from tools import edit_lint_check  # noqa: E402

_EMDASH = chr(0x2014)
_TIMES = chr(0x00D7)
_BOX = chr(0x2500)
_RUFF_IMPORTABLE = importlib.util.find_spec("ruff") is not None
requires_ruff = pytest.mark.skipif(
    not _RUFF_IMPORTABLE, reason="ruff is not importable by this interpreter"
)


def _fake_aws() -> str:
    # Assembled at runtime from an inert prefix and a degenerate body, so no
    # credential-shaped literal is committed (same rule as the arm's own tests).
    return "AKIA" + "A" * 16


def _payload(tool: str, tool_input: dict, cwd: Path) -> dict:
    """A recorded PostToolUse payload shape (values are placeholders)."""
    return {
        "session_id": "00000000-0000-0000-0000-000000000000",
        "transcript_path": "<transcript>",
        "cwd": str(cwd),
        "permission_mode": "default",
        "hook_event_name": "PostToolUse",
        "tool_name": tool,
        "tool_input": tool_input,
        "tool_response": {"success": True},
        "tool_use_id": "toolu_placeholder",
    }


def _run(monkeypatch, capsys, payload, env_paths: str | None = None):
    """Run the hook in-process. Returns (rc, context or None, stdout, stderr)."""
    if env_paths is None:
        monkeypatch.delenv("CLAUDE_FILE_PATHS", raising=False)
    else:
        monkeypatch.setenv("CLAUDE_FILE_PATHS", env_paths)
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    monkeypatch.setattr("sys.stdin", io.StringIO(raw))
    rc = edit_lint_check.main()
    cap = capsys.readouterr()
    ctx = None
    if cap.out.strip():
        lines = cap.out.splitlines()
        assert len(lines) == 1, f"hook output must be ONE line, got {cap.out!r}"
        obj = json.loads(lines[0])
        hso = obj["hookSpecificOutput"]
        assert hso["hookEventName"] == "PostToolUse"
        ctx = hso["additionalContext"]
    return rc, ctx, cap.out, cap.err


# --------------------------------------------------------------------------
# #1 - the stdin payload is the input; the env var is only a fallback
# --------------------------------------------------------------------------


def test_edit_payload_on_stdin_runs_the_glyph_arm(tmp_path, monkeypatch, capsys):
    target = tmp_path / "note.txt"
    target.write_text("a " + _EMDASH + " b\n", encoding="utf-8")
    payload = _payload("Edit", {
        "file_path": str(target), "old_string": "a - b",
        "new_string": "a " + _EMDASH + " b", "replace_all": False,
    }, tmp_path)
    rc, ctx, _out, _err = _run(monkeypatch, capsys, payload)
    assert rc == 0
    assert ctx is not None, "an Edit payload on stdin must reach the glyph arm"
    assert "note.txt" in ctx and "em-dash" in ctx


def test_write_payload_on_stdin_runs_the_credential_arm(tmp_path, monkeypatch, capsys):
    target = tmp_path / "cfg.txt"
    body = "key " + _fake_aws() + "\n"
    target.write_text(body, encoding="utf-8")
    payload = _payload("Write", {"file_path": str(target), "content": body}, tmp_path)
    rc, ctx, out, err = _run(monkeypatch, capsys, payload)
    assert rc == 0
    assert ctx is not None and "aws_access_key_id" in ctx
    assert "cfg.txt:1" in ctx
    assert "AKIA" not in out + err, "a matched value must never be printed"


def test_multiedit_payload_reads_file_path_and_edits(tmp_path, monkeypatch, capsys):
    target = tmp_path / "multi.md"
    target.write_text("one\nx " + _TIMES + " y\n", encoding="utf-8")
    payload = _payload("MultiEdit", {
        "file_path": str(target),
        "edits": [
            {"old_string": "uno", "new_string": "one", "replace_all": False},
            {"old_string": "x by y", "new_string": "x " + _TIMES + " y"},
        ],
    }, tmp_path)
    rc, ctx, _out, _err = _run(monkeypatch, capsys, payload)
    assert rc == 0
    assert ctx is not None and "multi.md" in ctx and "U+00D7" in ctx


def test_notebook_edit_payload_reads_notebook_path(tmp_path, monkeypatch, capsys):
    nb = tmp_path / "probe.ipynb"
    src = "token = '" + _fake_aws() + "'"
    nb.write_text(json.dumps({"cells": [{"cell_type": "code", "source": [src]}]}),
                  encoding="utf-8")
    payload = _payload("NotebookEdit", {
        "notebook_path": str(nb), "cell_id": "c1", "new_source": src,
        "cell_type": "code", "edit_mode": "replace",
    }, tmp_path)
    rc, ctx, _out, _err = _run(monkeypatch, capsys, payload)
    assert rc == 0
    assert ctx is not None and "probe.ipynb" in ctx and "aws_access_key_id" in ctx


def test_relative_file_path_resolves_against_payload_cwd(tmp_path, monkeypatch, capsys):
    (tmp_path / "rel.txt").write_text("r " + _EMDASH + "\n", encoding="utf-8")
    monkeypatch.chdir(REPO_ROOT)
    payload = _payload("Write", {"file_path": "rel.txt",
                                 "content": "r " + _EMDASH + "\n"}, tmp_path)
    _rc, ctx, _out, _err = _run(monkeypatch, capsys, payload)
    assert ctx is not None and "rel.txt" in ctx


def test_stdin_payload_wins_over_the_env_var(tmp_path, monkeypatch, capsys):
    clean = tmp_path / "clean.txt"
    clean.write_text("fine\n", encoding="utf-8")
    dirty = tmp_path / "dirty.txt"
    dirty.write_text("d " + _EMDASH + "\n", encoding="utf-8")
    payload = _payload("Write", {"file_path": str(dirty),
                                 "content": "d " + _EMDASH + "\n"}, tmp_path)
    _rc, ctx, _out, _err = _run(monkeypatch, capsys, payload, env_paths=str(clean))
    assert ctx is not None and "dirty.txt" in ctx and "clean.txt" not in ctx


def test_env_var_is_still_a_fallback_when_stdin_has_no_path(tmp_path, monkeypatch, capsys):
    dirty = tmp_path / "legacy.txt"
    dirty.write_text("l " + _EMDASH + "\n", encoding="utf-8")
    _rc, ctx, _out, _err = _run(monkeypatch, capsys, "", env_paths=str(dirty))
    assert ctx is not None and "legacy.txt" in ctx and "em-dash" in ctx


def test_env_fallback_accepts_one_path_with_a_space(tmp_path, monkeypatch, capsys):
    spaced = tmp_path / "with space"
    spaced.mkdir()
    dirty = spaced / "s.txt"
    dirty.write_text("s " + _EMDASH + "\n", encoding="utf-8")
    _rc, ctx, _out, _err = _run(monkeypatch, capsys, "", env_paths=str(dirty))
    assert ctx is not None and "s.txt" in ctx


@pytest.mark.parametrize("raw", ["", "not json {{{", "[1, 2]", '"str"',
                                 '{"tool_input": "oops"}',
                                 '{"tool_input": {"command": "ls"}}'])
def test_unrecognised_stdin_is_a_silent_noop(raw, monkeypatch, capsys):
    rc, ctx, out, err = _run(monkeypatch, capsys, raw)
    assert rc == 0 and ctx is None and out == "" and err == ""


def test_bom_prefixed_payload_parses(tmp_path, monkeypatch, capsys):
    target = tmp_path / "bom.txt"
    target.write_text("b " + _EMDASH + "\n", encoding="utf-8")
    raw = chr(0xFEFF) + json.dumps(_payload("Write", {
        "file_path": str(target), "content": "b " + _EMDASH + "\n"}, tmp_path))
    _rc, ctx, _out, _err = _run(monkeypatch, capsys, raw)
    assert ctx is not None and "bom.txt" in ctx


# --------------------------------------------------------------------------
# #3 / #11 - ruff is report-only and leaves no cache
# --------------------------------------------------------------------------


class _Proc:
    def __init__(self, stdout="[]", stderr="", returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


def _capture_ruff(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((list(argv), kwargs))
        return _Proc()

    # edit_lint_check's own `subprocess` name only, never the shared module (RM-801).
    bind_subprocess(monkeypatch, edit_lint_check, run=fake_run)
    return calls


def test_ruff_argv_is_report_only_and_cacheless(tmp_path, monkeypatch, capsys):
    target = tmp_path / "m.py"
    target.write_text("import os\n", encoding="utf-8")
    calls = _capture_ruff(monkeypatch)
    _run(monkeypatch, capsys, _payload("Write", {"file_path": str(target),
                                                 "content": "import os\n"}, tmp_path))
    assert calls, "a .py edit must reach the ruff arm"
    argv, kwargs = calls[0]
    assert "check" in argv
    assert "--fix" not in argv, "#3: ruff must never rewrite a file mid-edit"
    assert "--no-cache" in argv, "#11: ruff must not leave .ruff_cache/ behind"
    assert "creationflags" in kwargs, "console children keep CREATE_NO_WINDOW"


@requires_ruff
@pytest.mark.parametrize("channel", ["stdin", "env"])
def test_ruff_reports_and_never_deletes_a_just_added_import(
        channel, tmp_path, monkeypatch, capsys):
    target = tmp_path / "fresh.py"
    target.write_text("import os\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    if channel == "stdin":
        _rc, ctx, _o, _e = _run(monkeypatch, capsys, _payload(
            "Write", {"file_path": str(target), "content": "import os\n"}, tmp_path))
    else:
        _rc, ctx, _o, _e = _run(monkeypatch, capsys, "", env_paths=str(target))
    assert target.read_text(encoding="utf-8") == "import os\n", (
        "ruff --fix deleted the import before its first use was written")
    assert ctx is not None and "F401" in ctx and "fresh.py" in ctx
    assert not (tmp_path / ".ruff_cache").exists(), "#11: .ruff_cache/ left behind"


# --------------------------------------------------------------------------
# #13 - one ASCII rule, shared with the commit gate
# --------------------------------------------------------------------------


def _rule():
    from tools import ascii_rule
    return ascii_rule


def test_ascii_arm_flags_any_codepoint_over_127(tmp_path, monkeypatch, capsys):
    target = tmp_path / "times.md"
    target.write_text("3 " + _TIMES + " 4\n", encoding="utf-8")
    _rc, ctx, _out, _err = _run(monkeypatch, capsys, _payload(
        "Write", {"file_path": str(target), "content": "3 " + _TIMES + " 4\n"},
        tmp_path))
    assert ctx is not None and "U+00D7" in ctx, (
        "the edit hook must apply the commit gate's codepoint > 127 rule")


def test_ascii_arm_reads_the_written_text_not_preexisting_lines(tmp_path, monkeypatch, capsys):
    """Population = what the tool wrote, as the commit gate reads added lines."""
    target = tmp_path / "old.js"
    target.write_text("// " + _BOX * 10 + "\nconst a = 1;\n", encoding="utf-8")
    _rc, ctx, _out, _err = _run(monkeypatch, capsys, _payload("Edit", {
        "file_path": str(target), "old_string": "const a = 0;",
        "new_string": "const a = 1;"}, tmp_path))
    assert ctx is None, f"pre-existing glyphs must not re-flag every edit: {ctx}"


def test_ascii_arm_honours_the_commit_gate_exemptions(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    mirror = repo / "data" / "items.json"
    mirror.parent.mkdir()
    text = '{"name": "Cho' + chr(0x2019) + 'Gath"}\n'
    mirror.write_text(text, encoding="utf-8")
    _rc, ctx, _out, _err = _run(monkeypatch, capsys, _payload(
        "Write", {"file_path": str(mirror), "content": text}, repo))
    assert ctx is None, "data/ is an upstream mirror, exempt in the commit gate too"
    assert _rule().is_exempt("data/items.json")


def test_hooks_share_one_rule_with_identical_readings():
    rule = _rule()
    gate_spec = importlib.util.spec_from_file_location(
        "precommit_gate_s4", REPO_ROOT / "tools" / "precommit_gate.py")
    gate = importlib.util.module_from_spec(gate_spec)
    gate_spec.loader.exec_module(gate)
    samples = [("a " + _EMDASH + " b", "x.py"), ("3 " + _TIMES + " 4", "docs/a.md"),
               ("plain - ascii", "x.py"), ("v " + _TIMES, "logs/a.log"),
               (chr(0x201C) + "q" + chr(0x201D), "web/js/main.js")]
    for text, path in samples:
        assert gate._glyph_hits(text, path) == rule.hits(text, path), (text, path)
    for rel in ("tools/edit_lint_check.py", "tools/precommit_gate.py"):
        src = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "ascii_rule" in src, f"{rel} must use tools/ascii_rule.py"
        assert "_BANNED = {" not in src, f"{rel} still carries its own glyph table"


def test_ascii_rule_is_ascii_and_names_the_codepoint():
    rule = _rule()
    src = (REPO_ROOT / "tools" / "ascii_rule.py").read_bytes()
    assert all(b < 128 for b in src)
    assert "em-dash" in rule.hits("x " + _EMDASH)
    assert any("2713" in h for h in rule.hits("ok " + chr(0x2713)))
    assert rule.hits("plain ascii - only") == []


# --------------------------------------------------------------------------
# #14 - the fix hint documents the strip tools as optional helpers
# --------------------------------------------------------------------------


def test_fix_hint_names_strip_tools_as_optional_helpers(tmp_path, monkeypatch, capsys):
    target = tmp_path / "hint.txt"
    target.write_text("h " + _EMDASH + "\n", encoding="utf-8")
    _rc, ctx, _out, _err = _run(monkeypatch, capsys, _payload(
        "Write", {"file_path": str(target), "content": "h " + _EMDASH + "\n"},
        tmp_path))
    assert ctx is not None
    assert "optional" in ctx.lower()
    assert "strip_em_dashes.py" in ctx and "strip_smart_quotes.py" in ctx


def test_fix_hint_omits_helpers_that_are_absent(monkeypatch, tmp_path):
    rule = _rule()
    monkeypatch.setattr(rule, "_HELPER_DIR", tmp_path)
    hint = rule.fix_hint()
    assert "strip_em_dashes.py" not in hint
    assert hint.isascii() and hint


# --------------------------------------------------------------------------
# end-to-end: the real script, a recorded payload on stdin
# --------------------------------------------------------------------------


def test_cli_reads_a_recorded_payload(tmp_path):
    target = tmp_path / "cli.txt"
    target.write_text("c " + _EMDASH + "\n", encoding="utf-8")
    payload = json.dumps(_payload("Write", {"file_path": str(target),
                                            "content": "c " + _EMDASH + "\n"}, tmp_path))
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_FILE_PATHS"}
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "edit_lint_check.py")],
        input=payload, capture_output=True, text=True, timeout=30, env=env,
        cwd=str(tmp_path),
    )
    assert proc.returncode == 0
    ctx = json.loads(proc.stdout.strip())["hookSpecificOutput"]["additionalContext"]
    assert "cli.txt" in ctx and "em-dash" in ctx
